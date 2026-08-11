"""Layer 6 -- root-cause regression pins (WP-7).

One named, self-contained check per systemic root cause the ecosystem audit
found (`HARNESS-DESIGN.md` §4 "Layer 6", `TEST-MATRIX.md` §6, IDs used
verbatim). Each check MUST fail today against the real machine and pass only
when the underlying cause is actually fixed -- not when a single repo is
patched around it. Scope is deliberately limited to the five root causes the
task specifies (RC-1..RC-5); RC-6/RC-7 and the `inv.*` invariants named
elsewhere in the design are out of this package's file ownership.

Five architectural choices this module makes, each traced against the real
running code/state on this machine (`EXISTING-VERIFICATION.md`,
`TEST-MATRIX.md` §6) rather than assumed from the docs:

1. **Wrap, never re-implement** (ADR-002). Manifest parsing goes through
   `cc.core.ecosystem.manifest.{load_layers,validate_layers}`; project
   discovery goes through `cc.core.ecosystem.projects.discover_projects`;
   lock reads go through `cc.core.ecosystem.projects.read_project_lock`; the
   required-hook-path constant is IMPORTED from
   `cc.core.ecosystem.project_integration` (the exact `project_integration.py
   :57` source the task cites) rather than re-literaled, so this pin can
   never silently drift from the contract it is pinning against.

2. **`Path.home()`, never `resolve_key()`/`cc.core.config_paths`, for the
   real-machine entry points.** Every test in this suite (this whole `cc`
   test tree, via `tests/conftest.py::_isolate_machine_config`, autouse) has
   already redirected `CC_MACHINE_ROOT` to an empty `tmp_path` by the time a
   `@pytest.mark.machine` test in this file runs. A check that resolved the
   manifest or the fleet root through `resolve_key()` would therefore see an
   EMPTY machine under pytest and silently report "0 subjects checked"
   instead of the real broken state -- precisely the "fabricated healthy"
   failure mode this harness exists to prevent. `fsguard.py`'s own
   `_home()` makes the identical choice for the identical reason; this
   module mirrors it. Real-machine defaults read `~/.claude/cc/config.json`
   directly with a plain `json.loads`, bypassing the env-var seam entirely.

3. **Every check is a pure function of (inputs) -> CheckResult(s)**
   (`HARNESS-DESIGN.md` §3.2 rule 2). `check_rc1`..`check_rc5` take already-
   resolved paths/layers and touch nothing but read the filesystem and run
   read-only git plumbing via `fsguard.run_git_readonly`. The `run_rc1`..
   `run_rc5` wrappers are the only functions that know about the real
   machine's default locations; tests exercise `check_rc*` directly against
   a synthetic `FleetFactory` fleet (World A) and `run_rc*` directly against
   the real machine (World B, `@pytest.mark.machine`).

4. **Network-gated, never a silent local-only fallback** (the task's own
   instruction for RC-3). This harness never runs `git fetch` -- `fsguard`'s
   read-only allowlist forbids it, and fetching would mutate a real
   repository's `.git/` (a tripwire violation). RC-3's PRIMARY assertion
   (`git rev-list --count <ref>`) is deliberately network-INDEPENDENT: an
   orphan commit's parentlessness is a local, structural git fact no amount
   of staleness can change, and it alone is sufficient FAIL evidence. The
   secondary ancestry check against a cached default-branch ref is used only
   to corroborate a NON-orphan tag, and is explicitly `COULD_NOT_RUN` (never
   silently coerced to PASS) when no local ref is cached at all.

5. **One check id per root cause, potentially several `CheckResult`s per
   id** (mirrors `test_group_by_root_cause_groups_multiple_repos_under_one_
   cause` in WP-1's own test suite: the SAME `id` may be used for several
   subjects). Where the task asks for two independent assertions under one
   root cause ("Assert both the installer-source contract ... and the fleet
   state"), each becomes its own `CheckResult` with its own subject and
   verdict, sharing one check `id` and one `root_cause=` tag -- so
   `report.group_by_root_cause` groups them together while each remains
   independently inspectable and independently gate-able.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from cc.core.conformance.fsguard import run_git_readonly
from cc.core.conformance.registry import register_check
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
    Verdict,
)
from cc.core.ecosystem.dimensions import DIMENSION_SEMANTICS
from cc.core.ecosystem.manifest import load_layers, validate_layers
from cc.core.ecosystem.project_integration import (
    _CLAUDE_REQUIRED_LOCK_PATHS as _CLAUDE_REQUIRED_LOCK_PATHS_SOURCE,
)
from cc.core.ecosystem.projects import (
    PROJECT_LOCK_FILENAME,
    discover_projects,
    read_project_lock,
)

# ---------------------------------------------------------------------------
# Shared constants and small, dependency-free helpers
# ---------------------------------------------------------------------------

# The ONE authoritative source for this path (project_integration.py:53-58,
# cited directly by the task). Imported, never re-literaled, so RC-1 can
# never silently drift from the contract it pins.
HOOK_RELATIVE_PATH: str = next(
    path
    for path in _CLAUDE_REQUIRED_LOCK_PATHS_SOURCE
    if path.endswith("copilot-hook.sh")
)

# The canonical dimension names (cc.core.ecosystem.dimensions.DIMENSION_
# SEMANTICS) are also the top-level directory names `discovery.py` scans a
# tier's source.path for (`root / dimension`) -- RC-5 uses the same
# convention to tell "declares nothing" apart from "declares nothing THAT
# EXISTS ON DISK", never inventing a directory convention of its own.
_DIMENSION_NAMES: tuple[str, ...] = tuple(DIMENSION_SEMANTICS)


def _default_home() -> Path:
    # See module docstring point 2 -- deliberately Path.home(), never the
    # CC_MACHINE_ROOT-honoring config seam.
    return Path.home()


def _real_machine_config(home: Path) -> Mapping[str, Any]:
    config_path = home / ".claude" / "cc" / "config.json"
    try:
        data: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _real_manifest_path(home: Path) -> Path:
    config = _real_machine_config(home)
    manifest = (config.get("layers") or {}).get("manifest")
    if manifest:
        return Path(manifest).expanduser()
    return home / ".config" / "copilot" / "copilot.layers.yml"


def _real_projects_roots(home: Path) -> tuple[Path, ...]:
    config = _real_machine_config(home)
    roots = (config.get("projects") or {}).get("roots") or []
    if not isinstance(roots, list):
        return ()
    return tuple(Path(r).expanduser() for r in roots if isinstance(r, str) and r)


def _discover_fleet(home: Path) -> tuple[Path, ...]:
    """The real fleet, discovered without ever calling `resolve_key()` (see
    module docstring point 2) -- `discover_projects` is only ever given
    EXPLICIT `roots=`, and `_registry=None` disables ITS OWN internal
    `resolve_key("projects.registry")` fallback too."""

    roots = _real_projects_roots(home)
    if not roots:
        return ()
    return tuple(discover_projects(roots=roots, _registry=None))


def _load_validated_layers(manifest_path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(validate_layers(load_layers(manifest_path)))


def foundation_layers(manifest_path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        layer
        for layer in _load_validated_layers(manifest_path)
        if layer.get("role") == "foundation"
    )


def tier_variant_layers(manifest_path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        layer
        for layer in _load_validated_layers(manifest_path)
        if layer.get("role") != "foundation"
    )


def _layer_source_path(layer: Mapping[str, Any]) -> Path:
    source = layer.get("source") or {}
    path = source.get("path")
    if not path:
        raise LookupError(f"layer {layer.get('id')!r} has no source.path")
    return Path(path).expanduser()


def _foundation_source_path(
    layers: Sequence[Mapping[str, Any]], product: str
) -> Path | None:
    for layer in layers:
        if layer.get("product") == product:
            return _layer_source_path(layer)
    return None


# ---------------------------------------------------------------------------
# RC-1 -- the enforcement hook is required by project_integration.py:57 but
# installed by nothing, and locked by no fleet repo.
# ---------------------------------------------------------------------------

RC1_ID = "rc.rc1.enforcement_hook_is_installed_by_something"

_RC1 = register_check(
    id=RC1_ID,
    layer=Layer.REGRESSION,
    severity=Severity.S0,
    scope=Scope.GLOBAL,
    summary=(
        "the framework enforcement hook (.claude/hooks/copilot-hook.sh) is "
        "referenced by a sanctioned installer command, and is already "
        "present, executable, and locked across the real fleet"
    ),
    remediation=(
        "wire .claude/hooks/copilot-hook.sh into setup-project.md's and "
        "update-project.md's copy/lock steps, then re-run /update-project "
        "fleet-wide so every repo's lock records it with a matching checksum"
    ),
    mode=Mode.FAST,
    expected_today=ExpectedToday.FAIL,
)

_HOOK_REFERENCE_PATTERN = re.compile(r"copilot-hook|\.claude/hooks/")


def _hook_state(repo: Path) -> tuple[bool, bool, bool]:
    """(present, executable, locked-with-matching-checksum) for one repo's
    copy of the enforcement hook."""

    hook = repo / HOOK_RELATIVE_PATH
    if not hook.is_file():
        return (False, False, False)
    try:
        mode_bits = hook.stat().st_mode
        content = hook.read_bytes()
    except OSError:
        return (True, False, False)
    executable = bool(mode_bits & 0o111)
    checksum_actual = f"sha256:{hashlib.sha256(content).hexdigest()}"
    lock = read_project_lock(repo / PROJECT_LOCK_FILENAME)
    locked = any(
        file_entry.get("path") == HOOK_RELATIVE_PATH
        and file_entry.get("checksum") == checksum_actual
        for component in (lock.get("components") or [])
        if isinstance(component, dict) and component.get("product") == "claude"
        for file_entry in (component.get("files") or [])
        if isinstance(file_entry, dict)
    )
    return (True, executable, locked)


def check_rc1(
    *, claude_foundation_path: Path, fleet_repos: Sequence[Path]
) -> tuple[CheckResult, ...]:
    """RC-1: two independent, self-contained assertions.

    1. installer-source contract -- does `setup-project.md` or
       `update-project.md` reference the hook at all?
    2. fleet state -- of the repos this machine can discover, how many have
       the hook PRESENT, EXECUTABLE, and LOCKED with a matching checksum
       (the compound definition `project_integration.py` itself uses, not
       mere file existence)?
    """

    setup_md = claude_foundation_path / ".claude" / "commands" / "setup-project.md"
    update_md = claude_foundation_path / ".claude" / "commands" / "update-project.md"

    hits: dict[str, int] = {}
    for md in (setup_md, update_md):
        text = md.read_text(encoding="utf-8") if md.is_file() else ""
        hits[md.name] = len(_HOOK_REFERENCE_PATTERN.findall(text))
    installer_ok = sum(hits.values()) > 0

    installer_evidence: tuple[Evidence, ...] = ()
    if not installer_ok:
        installer_evidence = (
            Evidence(
                kind="installer-source",
                path=str(setup_md),
                expected=f"a reference to {HOOK_RELATIVE_PATH} in a sanctioned installer",
                actual="0 references",
                detail=(
                    f"{setup_md.name}: {hits.get(setup_md.name, 0)} reference(s); "
                    f"{update_md.name}: {hits.get(update_md.name, 0)} reference(s)"
                ),
                command=f"grep -n copilot-hook {setup_md} {update_md}",
            ),
        )
    installer_result = _RC1.result(
        subject=str(setup_md),
        verdict=Verdict.PASS if installer_ok else Verdict.FAIL,
        evidence=installer_evidence,
        detail="whether any sanctioned command installs the enforcement hook",
        # Re-verified live 2026-08-10: setup-project.md now references
        # .claude/hooks/copilot-hook.sh (cp + chmod +x + `cc settings-hook
        # add`) -- the installer-source half of RC-1 is genuinely fixed.
        # The fleet half below is NOT -- see its own expected_today.
        expected_today=ExpectedToday.PASS,
        root_cause="RC-1",
    )

    total = len(fleet_repos)
    present_and_locked = 0
    broken_examples: list[str] = []
    for repo in fleet_repos:
        present, executable, locked = _hook_state(repo)
        if present and executable and locked:
            present_and_locked += 1
        elif len(broken_examples) < 8:
            if not present:
                state = "absent"
            elif not executable:
                state = "present but not executable"
            else:
                state = "present but not locked (or checksum mismatch)"
            broken_examples.append(f"{repo} [{state}]")

    fleet_ok = total > 0 and present_and_locked == total
    fleet_evidence: tuple[Evidence, ...] = ()
    if not fleet_ok:
        fleet_evidence = (
            Evidence(
                kind="fleet-lock-state",
                path=str(fleet_repos[0].parent) if fleet_repos else str(claude_foundation_path),
                expected=f"{HOOK_RELATIVE_PATH} present, executable, and locked in {total} of {total} discovered repos",
                actual=f"{present_and_locked} of {total} present-and-locked",
                detail="; ".join(broken_examples) if broken_examples else "no repos discovered",
            ),
        )
    fleet_result = _RC1.result(
        subject=f"fleet: {total} discovered repos",
        verdict=Verdict.PASS if fleet_ok else Verdict.FAIL,
        evidence=fleet_evidence,
        detail="how much of the real fleet already reflects the fix",
        # Re-verified live 2026-08-10: 0 of 59 discovered repos are
        # present-AND-executable-AND-locked (this repo's own hook is
        # present but not yet locked). The installer fix has not been
        # fanned out to the fleet via /update-project yet -- still
        # genuinely broken, not a check regression.
        expected_today=ExpectedToday.FAIL,
        root_cause="RC-1",
    )

    return (installer_result, fleet_result)


def run_rc1(*, home: Path | None = None) -> tuple[CheckResult, ...]:
    home = home or _default_home()
    layers = foundation_layers(_real_manifest_path(home))
    claude_path = _foundation_source_path(layers, "claude")
    if claude_path is None:
        raise LookupError("no claude foundation layer found in the real manifest")
    return check_rc1(claude_foundation_path=claude_path, fleet_repos=_discover_fleet(home))


# ---------------------------------------------------------------------------
# RC-2 -- codex has no in-place updater, and the installer hard-refuses a
# second run over an already-provisioned repo.
# ---------------------------------------------------------------------------

RC2_ID = "rc.rc2.codex_has_an_updater"

_RC2 = register_check(
    id=RC2_ID,
    layer=Layer.REGRESSION,
    severity=Severity.S0,
    scope=Scope.GLOBAL,
    summary="codex has a real in-place update path, not only a first-install script that refuses to re-run",
    remediation=(
        "add codex-copilot/scripts/update-project.sh that updates an "
        "installed plugin in place, and remove setup-project.sh's hard "
        "refusal on pre-existing artifacts so a second run repairs instead "
        "of exiting non-zero"
    ),
    mode=Mode.FAST,
    expected_today=ExpectedToday.FAIL,
)

_REFUSAL_PATTERN = re.compile(r"Refusing to replace")


def check_rc2(*, codex_foundation_path: Path) -> tuple[CheckResult, ...]:
    """RC-2: two independent, self-contained, purely static assertions
    (never executes the installer -- that dynamic proof is Layer 5's RT-5,
    owned by a different package)."""

    scripts_dir = codex_foundation_path / "scripts"
    updater = scripts_dir / "update-project.sh"
    setup = scripts_dir / "setup-project.sh"

    updater_exists = updater.is_file()
    updater_evidence: tuple[Evidence, ...] = ()
    if not updater_exists:
        listing = (
            sorted(p.name for p in scripts_dir.iterdir())
            if scripts_dir.is_dir()
            else []
        )
        updater_evidence = (
            Evidence(
                kind="missing-file",
                path=str(updater),
                expected="scripts/update-project.sh",
                actual="does not exist",
                detail=f"scripts/ contains: {', '.join(listing) if listing else '(directory missing)'}",
            ),
        )
    updater_result = _RC2.result(
        subject=str(updater),
        verdict=Verdict.PASS if updater_exists else Verdict.FAIL,
        evidence=updater_evidence,
        detail="whether an in-place codex updater exists at all",
        # Re-verified live 2026-08-10: codex-copilot/scripts/update-project.sh
        # now exists and performs a real in-place, content-hashed refresh.
        expected_today=ExpectedToday.PASS,
        root_cause="RC-2",
    )

    setup_text = setup.read_text(encoding="utf-8") if setup.is_file() else ""
    refusal_hits = _REFUSAL_PATTERN.findall(setup_text)
    refuses = bool(refusal_hits)
    setup_evidence: tuple[Evidence, ...] = ()
    if refuses:
        setup_evidence = (
            Evidence(
                kind="installer-source",
                path=str(setup),
                expected="no hard refusal on a pre-existing plugin/skill/gate link",
                actual=f"{len(refusal_hits)} 'Refusing to replace' guard(s)",
                detail="a second run over an already-provisioned repo exits non-zero instead of updating in place",
                command=f"grep -n 'Refusing to replace' {setup}",
            ),
        )
    setup_result = _RC2.result(
        subject=str(setup),
        verdict=Verdict.FAIL if refuses else Verdict.PASS,
        evidence=setup_evidence,
        detail="whether the first-install script still hard-refuses a second run",
        # Re-verified live 2026-08-10: setup-project.sh no longer contains
        # a "Refusing to replace" hard refusal.
        expected_today=ExpectedToday.PASS,
        root_cause="RC-2",
    )

    return (updater_result, setup_result)


def run_rc2(*, home: Path | None = None) -> tuple[CheckResult, ...]:
    home = home or _default_home()
    layers = foundation_layers(_real_manifest_path(home))
    codex_path = _foundation_source_path(layers, "codex")
    if codex_path is None:
        raise LookupError("no codex foundation layer found in the real manifest")
    return check_rc2(codex_foundation_path=codex_path)


# ---------------------------------------------------------------------------
# RC-3 -- orphan release tags: the release-cut step, not a branch artifact.
# ---------------------------------------------------------------------------

RC3_ID = "rc.rc3.orphan_release_tags"

_RC3 = register_check(
    id=RC3_ID,
    layer=Layer.REGRESSION,
    severity=Severity.S0,
    scope=Scope.PER_CELL,
    summary=(
        "every foundation's manifest-pinned tag is a real ancestor of its "
        "default branch, not a parentless release-cut snapshot"
    ),
    remediation=(
        "re-cut the release from a connected branch tip (an ordinary `git "
        "tag` on a real commit) instead of an orphan `git commit-tree` "
        "snapshot -- the cause is the release-cut step, not which branch "
        "happens to be checked out locally"
    ),
    mode=Mode.FAST,
    expected_today=ExpectedToday.FAIL,
)

# Per the task's own framing, these were the originally-measured,
# known-broken foundations. `cli` was ADDED after re-verification found its
# own foundation pin (`cli-copilot`'s `v0.3.5`, `rev-list --count` = 1) is
# the identical parentless-snapshot defect -- an earlier pass had wrongly
# assumed cli-copilot was a clean control case; it was never actually
# checked. Do not treat any foundation as known-good without checking it
# live. Any OTHER foundation layer found in the real manifest is still
# checked (arity-independent -- this must never hardcode "N products"), but
# is editorially expected to still pass today; a live mismatch against that
# expectation is itself a legitimate, worth-surfacing signal (see
# `ExpectedToday`'s docstring), not a harness bug.
_RC3_KNOWN_BROKEN_PRODUCTS = frozenset({"claude", "codex", "cli"})


def _rc3_expected_today(product: str) -> ExpectedToday:
    return (
        ExpectedToday.FAIL
        if product in _RC3_KNOWN_BROKEN_PRODUCTS
        else ExpectedToday.PASS
    )


def _git_rev_list_count(repo: Path, ref: str) -> int | None:
    result = run_git_readonly(("rev-list", "--count", ref), cwd=repo)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return int(text) if text.isdigit() else None


def _git_ref_resolves(repo: Path, ref: str) -> bool:
    result = run_git_readonly(("rev-parse", "--verify", f"{ref}^{{commit}}"), cwd=repo)
    return result.returncode == 0


def _cached_default_branch(repo: Path) -> str | None:
    """The best LOCAL (never-fetched) default-branch ref available. Tries
    the real remote-tracking ref first, then a bare local branch -- covers
    both a real clone (has `origin/main`) and a synthetic fixture repo (only
    a local `main`, no remote at all). Never fetches (module docstring
    point 4): a missing ref here means "explicit COULD_NOT_RUN", never a
    silent fallback to something less trustworthy."""

    for candidate in ("origin/main", "main", "origin/master", "master"):
        if _git_ref_resolves(repo, candidate):
            return candidate
    return None


def check_rc3(*, layers: Sequence[Mapping[str, Any]]) -> tuple[CheckResult, ...]:
    """RC-3, per foundation layer in `layers`. See module docstring point 4
    for the network-gating rationale."""

    results: list[CheckResult] = []
    for layer in layers:
        product = str(layer.get("product", "?"))
        try:
            repo = _layer_source_path(layer)
        except LookupError:
            continue
        ref = (layer.get("source") or {}).get("ref")
        subject = f"{product}-foundation ({repo})"
        expected_today = _rc3_expected_today(product)

        if not ref:
            continue  # tracks a branch directly, not a tag -- not this RC's concern

        if not repo.is_dir():
            results.append(
                _RC3.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    evidence=(
                        Evidence(
                            kind="repo",
                            path=str(repo),
                            expected="the foundation's source.path to exist",
                            actual="missing",
                        ),
                    ),
                    detail="cannot verify tag ancestry -- the source repository is not present",
                    expected_today=expected_today,
                    root_cause="RC-3",
                )
            )
            continue

        count = _git_rev_list_count(repo, ref)
        if count is None:
            results.append(
                _RC3.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    evidence=(
                        Evidence(
                            kind="git-ref",
                            path=str(repo),
                            command=f"git -C {repo} rev-list --count {ref}",
                            expected="a resolvable ref",
                            actual="did not resolve",
                        ),
                    ),
                    detail=f"the pinned ref {ref!r} does not resolve to a commit",
                    expected_today=expected_today,
                    root_cause="RC-3",
                )
            )
            continue

        if count == 1:
            results.append(
                _RC3.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=(
                        Evidence(
                            kind="git-rev-list",
                            path=str(repo),
                            command=f"git -C {repo} rev-list --count {ref}",
                            output="1",
                            expected="> 1 (a real ancestor chain reachable from a release commit)",
                            actual="1 (a parentless commit -- a release-cut snapshot, not a merge)",
                            detail="network-independent: an orphan commit stays orphan regardless of fetch freshness",
                        ),
                    ),
                    detail=f"{product} foundation's pinned tag {ref!r} is an orphan single-commit snapshot",
                    expected_today=expected_today,
                    root_cause="RC-3",
                )
            )
            continue

        branch = _cached_default_branch(repo)
        if branch is None:
            results.append(
                _RC3.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    evidence=(
                        Evidence(
                            kind="git-ref",
                            path=str(repo),
                            expected="a cached origin/main or main ref",
                            actual="neither resolves locally",
                        ),
                    ),
                    detail=(
                        "no cached default-branch ref to compare ancestry against, and this "
                        "harness never runs `git fetch` (read-only) -- explicit SKIP rather "
                        "than a silent local-only fallback"
                    ),
                    expected_today=expected_today,
                    root_cause="RC-3",
                )
            )
            continue

        ancestry = run_git_readonly(("merge-base", "--is-ancestor", ref, branch), cwd=repo)
        freshness_note = (
            f"compared against the last locally-cached {branch}; this harness never "
            "fetches (read-only), so a stale cache could mask a since-fixed upstream -- "
            "a PASS here is provisional until corroborated by a fresh clone"
        )
        if ancestry.returncode == 0:
            results.append(
                _RC3.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    detail=f"{ref} is an ancestor of {branch} ({freshness_note})",
                    expected_today=expected_today,
                    root_cause="RC-3",
                )
            )
        else:
            results.append(
                _RC3.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=(
                        Evidence(
                            kind="git-merge-base",
                            path=str(repo),
                            command=f"git -C {repo} merge-base --is-ancestor {ref} {branch}",
                            expected=f"exit 0 ({ref} an ancestor of {branch})",
                            actual=f"exit {ancestry.returncode}",
                            detail=freshness_note,
                        ),
                    ),
                    detail=f"{product} foundation's pinned tag {ref!r} has no merge-base with {branch}",
                    expected_today=expected_today,
                    root_cause="RC-3",
                )
            )
    return tuple(results)


def run_rc3(*, home: Path | None = None) -> tuple[CheckResult, ...]:
    home = home or _default_home()
    return check_rc3(layers=foundation_layers(_real_manifest_path(home)))


# ---------------------------------------------------------------------------
# RC-4 -- copilot.lock.json is a copied template, not a generated record.
# ---------------------------------------------------------------------------

RC4_ID = "rc.rc4.lock_is_generated_not_templated"

_RC4 = register_check(
    id=RC4_ID,
    layer=Layer.REGRESSION,
    severity=Severity.S0,
    scope=Scope.GLOBAL,
    summary="copilot.lock.json is written by the real per-project generator, not shipped as a pasted template",
    remediation=(
        "call cc.core.ecosystem.projects.write_project_lock (the PER-"
        "PROJECT writer -- not core/ecosystem/lockfile.py, which is the "
        "machine-level ecosystem lock, a different schema) from setup-"
        "project.md, update-project.md, and codex-copilot/scripts/setup-"
        "project.sh, so every project's lock is generated from what is "
        "actually installed"
    ),
    mode=Mode.FAST,
    expected_today=ExpectedToday.FAIL,
)

_LOCK_GENERATOR_PATTERN = re.compile(
    r"copilot\.lock\.json|write_project_lock|serialize_project_lock"
)


def check_rc4(
    *, installer_files: Sequence[Path], fleet_repos: Sequence[Path]
) -> tuple[CheckResult, ...]:
    """RC-4: two independent, self-contained assertions -- derivation (does
    any installer call the real generator?) and uniqueness (do independently
    -installed repos' locks actually differ, as a generated record must?)."""

    hits: dict[str, int] = {}
    for path in installer_files:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        hits[str(path)] = len(_LOCK_GENERATOR_PATTERN.findall(text))
    generator_ok = sum(hits.values()) > 0

    generator_evidence: tuple[Evidence, ...] = ()
    if not generator_ok:
        generator_evidence = (
            Evidence(
                kind="installer-source",
                path=str(installer_files[0]) if installer_files else "",
                expected="a reference to the real per-project lock generator",
                actual="0 references across every installer path checked",
                detail=", ".join(f"{Path(p).name}: {n}" for p, n in hits.items()) or "no installer files found",
            ),
        )
    generator_result = _RC4.result(
        subject="installer generator reference",
        verdict=Verdict.PASS if generator_ok else Verdict.FAIL,
        evidence=generator_evidence,
        detail="whether any sanctioned installer calls the real per-project lock writer",
        # Re-verified live 2026-08-10: codex-copilot/scripts/update-project.sh
        # (RC-2's new in-place updater) now computes real per-file sha256
        # checksums and writes a genuinely generated copilot.lock.json
        # component -- not a copied template. Claude's setup-project.md/
        # update-project.md TEXT still never literally mentions a lock
        # generator (this check is a text grep, so it can't see it), but
        # `cc settings-hook add` -- a step setup-project.md already runs --
        # independently writes a real, per-project mutation-ledger lock via
        # core/ecosystem/mutations.py (see roundtrip.setup.produces_
        # reference_install's own "lock" facet, re-verified live and now
        # PASS). This grep-based result is a real, if narrow, "does ANY
        # sanctioned installer TEXT reference a generator" answer.
        expected_today=ExpectedToday.PASS,
        root_cause="RC-4",
    )

    by_hash: dict[str, list[str]] = {}
    for repo in fleet_repos:
        lock_path = repo / PROJECT_LOCK_FILENAME
        if not lock_path.is_file():
            continue
        try:
            digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        except OSError:
            continue
        by_hash.setdefault(digest, []).append(str(repo))

    duplicate_clusters = {h: paths for h, paths in by_hash.items() if len(paths) > 1}
    uniqueness_evidence: tuple[Evidence, ...] = ()
    if duplicate_clusters:
        sample_digest, sample_paths = max(
            duplicate_clusters.items(), key=lambda item: len(item[1])
        )
        uniqueness_evidence = (
            Evidence(
                kind="lock-hash-collision",
                path=str(fleet_repos[0].parent) if fleet_repos else "",
                expected="every copilot.lock.json has a unique sha256 (a generated-per-project record cannot collide)",
                actual=(
                    f"{len(duplicate_clusters)} duplicate cluster(s) across "
                    f"{sum(len(v) for v in duplicate_clusters.values())} of {len(by_hash) and sum(len(v) for v in by_hash.values())} locks"
                ),
                detail=f"largest cluster {sample_digest[:16]}... shared by {len(sample_paths)} repos: {', '.join(sample_paths[:8])}",
            ),
        )
    uniqueness_result = _RC4.result(
        subject=f"fleet lock uniqueness ({sum(len(v) for v in by_hash.values())} locks found)",
        verdict=Verdict.FAIL if duplicate_clusters else Verdict.PASS,
        evidence=uniqueness_evidence,
        detail="whether any two independently-installed repos share a byte-identical lock",
        # Re-verified live 2026-08-10: 6 duplicate clusters across 42 of 59
        # real locks -- the generator fix above has not propagated across
        # the fleet (most repos have not had the new codex updater run
        # against them yet, and claude's own installer never regenerates a
        # lock at all). Still genuinely broken -- partial, not fixed.
        expected_today=ExpectedToday.FAIL,
        root_cause="RC-4",
    )

    return (generator_result, uniqueness_result)


def run_rc4(*, home: Path | None = None) -> tuple[CheckResult, ...]:
    home = home or _default_home()
    layers = foundation_layers(_real_manifest_path(home))
    claude_path = _foundation_source_path(layers, "claude")
    codex_path = _foundation_source_path(layers, "codex")

    installer_files: list[Path] = []
    if claude_path is not None:
        installer_files.append(claude_path / ".claude" / "commands" / "setup-project.md")
        installer_files.append(claude_path / ".claude" / "commands" / "update-project.md")
    if codex_path is not None:
        scripts_dir = codex_path / "scripts"
        if scripts_dir.is_dir():
            installer_files.extend(sorted(scripts_dir.glob("*.sh")))

    return check_rc4(
        installer_files=tuple(installer_files), fleet_repos=_discover_fleet(home)
    )


# ---------------------------------------------------------------------------
# RC-5 -- every tier-variant copilot.layer.yml ends dimensions: [], and the
# one variant with real content (knowledge-copilot-internal) has no file.
# ---------------------------------------------------------------------------

RC5_ID = "rc.rc5.tier_variants_declare_dimensions"

_RC5 = register_check(
    id=RC5_ID,
    layer=Layer.REGRESSION,
    severity=Severity.S0,
    scope=Scope.PER_CELL,
    summary="every tier-variant layer has a copilot.layer.yml whose dimensions: list names what it actually carries",
    remediation=(
        "author a copilot.layer.yml for every tier-variant layer and list "
        "every dimension directory (agents, skills, commands, protocol, "
        "knowledge, memory, tasks, cli-integrations, plugins) that actually "
        "holds committed content"
    ),
    mode=Mode.FAST,
    expected_today=ExpectedToday.FAIL,
)


def _dimensions_with_real_content(repo: Path) -> tuple[str, ...]:
    found: list[str] = []
    for dimension in _DIMENSION_NAMES:
        candidate = repo / dimension
        if candidate.is_dir() and any(p.is_file() for p in candidate.rglob("*")):
            found.append(dimension)
    return tuple(found)


def check_rc5(*, layers: Sequence[Mapping[str, Any]]) -> tuple[CheckResult, ...]:
    """RC-5, per tier-variant layer in `layers`. A declared `dimensions:`
    list is only accepted as PASS when it also covers every directory this
    machine can independently observe holding real content -- a non-empty
    but bogus list must not be able to game this check green (`HARNESS-
    DESIGN.md` §3.2 rule 3: evidence must be specific, not merely present)."""

    results: list[CheckResult] = []
    for layer in layers:
        product = str(layer.get("product", "?"))
        role = str(layer.get("role", "?"))
        try:
            repo = _layer_source_path(layer)
        except LookupError:
            continue
        subject = f"{product}-{role} ({repo})"

        if not repo.is_dir():
            results.append(
                _RC5.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    evidence=(
                        Evidence(
                            kind="repo",
                            path=str(repo),
                            expected="the tier's source.path to exist",
                            actual="missing",
                        ),
                    ),
                    detail="cannot verify -- the source repository is not present",
                    root_cause="RC-5",
                )
            )
            continue

        real_dims = _dimensions_with_real_content(repo)
        layer_yml = repo / "copilot.layer.yml"

        if not layer_yml.is_file():
            results.append(
                _RC5.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=(
                        Evidence(
                            kind="layer-manifest",
                            path=str(layer_yml),
                            expected="a copilot.layer.yml declaring this tier's dimensions",
                            actual="file does not exist",
                            detail=(
                                f"real content on disk under: {', '.join(real_dims)}"
                                if real_dims
                                else "no dimension content on disk yet"
                            ),
                        ),
                    ),
                    detail=f"{product} {role} has no copilot.layer.yml at all",
                    root_cause="RC-5",
                )
            )
            continue

        try:
            declared = yaml.safe_load(layer_yml.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            results.append(
                _RC5.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    evidence=(
                        Evidence(
                            kind="layer-manifest",
                            path=str(layer_yml),
                            expected="parseable YAML",
                            actual=f"YAML error: {exc}",
                        ),
                    ),
                    detail="copilot.layer.yml does not parse",
                    root_cause="RC-5",
                )
            )
            continue

        raw_dimensions = declared.get("dimensions") if isinstance(declared, dict) else None
        dimensions: tuple[str, ...] = (
            tuple(raw_dimensions) if isinstance(raw_dimensions, list) else ()
        )
        undeclared_real = tuple(d for d in real_dims if d not in dimensions)

        if not dimensions:
            results.append(
                _RC5.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=(
                        Evidence(
                            kind="layer-manifest",
                            path=str(layer_yml),
                            expected="a non-empty dimensions: list naming real content",
                            actual="dimensions: []",
                            detail=(
                                f"real content on disk under: {', '.join(real_dims)}"
                                if real_dims
                                else "no dimension content on disk yet (an empty list is at least honest here)"
                            ),
                        ),
                    ),
                    detail=f"{product} {role}'s copilot.layer.yml declares no dimensions",
                    root_cause="RC-5",
                )
            )
        elif undeclared_real:
            results.append(
                _RC5.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=(
                        Evidence(
                            kind="layer-manifest",
                            path=str(layer_yml),
                            expected=f"dimensions including {', '.join(undeclared_real)}",
                            actual=f"dimensions: {list(dimensions)}",
                            detail="the declared list omits a directory that holds real, on-disk content",
                        ),
                    ),
                    detail=f"{product} {role} under-declares its own content",
                    root_cause="RC-5",
                )
            )
        else:
            results.append(
                _RC5.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    detail=f"{product} {role} declares {list(dimensions)}",
                    root_cause="RC-5",
                )
            )
    return tuple(results)


def run_rc5(*, home: Path | None = None) -> tuple[CheckResult, ...]:
    home = home or _default_home()
    return check_rc5(layers=tier_variant_layers(_real_manifest_path(home)))


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

ALL_ROOT_CAUSE_CHECK_IDS: tuple[str, ...] = (RC1_ID, RC2_ID, RC3_ID, RC4_ID, RC5_ID)


def run_all_root_cause_checks(*, home: Path | None = None) -> tuple[CheckResult, ...]:
    """Every RC-1..RC-5 result against the real machine, in one call --
    the convenience seam `cc conformance check --layer regression` (WP-8,
    not owned here) and any future `pytest.mark.machine` smoke test both
    want."""

    home = home or _default_home()
    return (
        *run_rc1(home=home),
        *run_rc2(home=home),
        *run_rc3(home=home),
        *run_rc4(home=home),
        *run_rc5(home=home),
    )


__all__ = [
    "ALL_ROOT_CAUSE_CHECK_IDS",
    "HOOK_RELATIVE_PATH",
    "RC1_ID",
    "RC2_ID",
    "RC3_ID",
    "RC4_ID",
    "RC5_ID",
    "check_rc1",
    "check_rc2",
    "check_rc3",
    "check_rc4",
    "check_rc5",
    "foundation_layers",
    "run_all_root_cause_checks",
    "run_rc1",
    "run_rc2",
    "run_rc3",
    "run_rc4",
    "run_rc5",
    "tier_variant_layers",
]
