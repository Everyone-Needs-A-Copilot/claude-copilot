"""Layer 4 -- lock integrity (WP-5).

`HARNESS-DESIGN.md` section 4 "Layer 4 -- Lock integrity": proves
`copilot.lock.json` reflects the actual install, `ownership: framework` vs
`project` is accurate, and a fully-installed classification cannot be
obtained by waiver over missing required paths. `TEST-MATRIX.md` section 4
defines the five test IDs this module implements, `LI-1` through `LI-5`.

Wraps (never re-implements) `cc.core.ecosystem.projects.read_project_lock`
and `cc.core.ecosystem.project_integration`'s own lock verification --
`_verify_lock_entry` for checksum truth, `inspect_project_integration` for
the classification a waiver-detection check must not itself recompute, and
the module's own `_CLAUDE_REQUIRED_LOCK_PATHS` / `_CODEX_REQUIRED_LOCK_PATHS`
constants so the required-path list can never drift from the contract that
actually enforces it (`HARNESS-DESIGN.md` section 1.3: "A vendored copy
drifts, and a conformance harness that has drifted from the contract is
worse than none" -- the reason this harness imports the real constants
directly rather than copying their values).

Five checks, one function each, registered once at import time:

    lock.template.uniqueness                    LI-1 / RC-4   S0
    lock.records_match_disk                      LI-2          S1
    lock.ownership.frontmatter_agrees             LI-3          S1
    lock.waiver.ready_requires_required_paths     LI-4          S0
    lock.required_paths.full_mode_complete        LI-5          S0

`EXISTING-VERIFICATION.md` section 2 is the ground truth for LI-4:
`project_integration.py:539` sets `absent_required = []` whenever
`ownership_mode == "customized-preserve"`, so the lock is simultaneously
the claim and the yardstick a naive reader would use to verify that claim.
This module never treats a fully-installed classification as a pass oracle
on its own -- `check_lock_waiver_ready_requires_required_paths` independently
recomputes whether the required-path condition would have held without the
waiver, using the same required-path constants `_verify_lock_entry` itself
consults.

Every check is a pure function of `(repo_roots, ...)` -> `tuple[CheckResult,
...]`. None of them mutate anything -- they only ever call
`Path.read_bytes`/`read_text` and the read-only functions listed above.
Callers (a real machine sweep, or this package's own test suite) are
responsible for any read-only tripwire around the paths they pass in; this
module has no filesystem-write code path at all.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from cc.core.conformance.registry import register_check
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Verdict,
)
from cc.core.ecosystem.project_integration import (
    _CLAUDE_REQUIRED_LOCK_PATHS,
    _CODEX_REQUIRED_LOCK_PATHS,
    SUPPORTED_COMPONENTS,
    _verify_lock_entry,
    inspect_project_integration,
)
from cc.core.ecosystem.projects import PROJECT_LOCK_FILENAME, read_project_lock
from cc.core.entry_format import EntryValidationError, parse_frontmatter

# The same required-path lists `project_integration._verify_lock_entry`
# itself enforces -- imported, never copied, so LI-4/LI-5 can never silently
# drift from the contract they are grading (module docstring, and
# `HARNESS-DESIGN.md` section 1.3).
_REQUIRED_PATHS_BY_COMPONENT: Mapping[str, tuple[str, ...]] = {
    "claude": _CLAUDE_REQUIRED_LOCK_PATHS,
    "codex": _CODEX_REQUIRED_LOCK_PATHS,
}

# `_verify_lock_entry`'s own `missing[].id` vocabulary (verified against
# `project_integration.py` directly), split into the two buckets LI-2 needs
# to tell apart: a STRUCTURAL problem means the entry could not even be
# read far enough to compare a checksum (an honest COULD_NOT_RUN, never a
# fabricated PASS -- `inv.no_fabricated_healthy`); everything else that
# survives structurally is either a checksum match or a genuine mismatch,
# which the returned `evidence[]` already carries by `kind`.
#
# `valid-managed-output` is deliberately NOT in this set. Unlike the other
# three ids (which mean the LOCK ITSELF is too malformed to compare
# anything against disk at all -- no version string, no files list, an
# unsafe/duplicate path), a malformed `managed_outputs[]` record (wrong key
# set, unknown path/kind pairing, or a `fingerprint` that is missing or not
# a well-formed `sha256:<64 hex>` -- `project_integration._verify_lock_
# entry`'s own schema, mirrored by `project_reconciliation.py`) is a
# genuinely bad RECORD the installer wrote, not a schema this harness fails
# to understand. `codex-copilot/scripts/update-project.sh` writes exactly
# this shape today (`{"path", "kind"}`, no `fingerprint`) -- real, writer-
# side data this check must FAIL on, never downgrade to COULD_NOT_RUN
# (`inv.no_fabricated_healthy` cuts both ways: a real defect silently
# filed as "could not verify" is as dishonest as a fabricated PASS).
_STRUCTURAL_MISSING_IDS = frozenset(
    {
        "valid-lock-entry",
        "valid-framework-record",
        "safe-recorded-path",
    }
)
_INVALID_MANAGED_OUTPUT_ID = "valid-managed-output"
_CHECKSUM_EVIDENCE_KINDS = frozenset({"framework-file", "managed-output"})


def _component_entries(root: Path) -> dict[str, dict[str, Any]]:
    """The repo's `copilot.lock.json`, parsed down to `{component: entry}`
    for whichever of `SUPPORTED_COMPONENTS` it actually declares. Any
    unreadable, malformed, or wrong-schema lock degrades to `{}` -- the
    same fail-open posture `read_project_lock` itself documents -- so every
    check function below can treat "no lock, or no usable entry" as one
    uniform SKIP branch rather than a special case five times over."""

    raw = read_project_lock(root / PROJECT_LOCK_FILENAME)
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        return {}
    components = raw.get("components")
    if not isinstance(components, list):
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for entry in components:
        if not isinstance(entry, dict):
            continue
        component = entry.get("component")
        if component in SUPPORTED_COMPONENTS and component not in entries:
            entries[component] = entry
    return entries


def _recorded_paths(entry: Mapping[str, Any]) -> set[str]:
    files = entry.get("files")
    if not isinstance(files, list):
        return set()
    return {
        f["path"]
        for f in files
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    }


def _ownership_mode(entry: Mapping[str, Any]) -> str:
    mode = entry.get("ownership_mode", "full")
    return mode if isinstance(mode, str) else "full"


def _frontmatter_owner(path: Path) -> str | None:
    """The file's own declared `owner:` frontmatter value, or `None` if the
    file is unreadable, has no frontmatter block at all, or the frontmatter
    has no `owner` key. Never raises -- a file with no ownership opinion of
    its own is not a contradiction (`TEST-MATRIX.md` LI-3's own pass
    criterion: "or file has no owner: key at all -- silent, but not a
    direct contradiction")."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        frontmatter, _body = parse_frontmatter(text)
    except EntryValidationError:
        return None
    owner = frontmatter.get("owner")
    return owner if isinstance(owner, str) else None


def _resolve_expected(
    subject: str, verdict: Verdict, overrides: Mapping[str, ExpectedToday]
) -> ExpectedToday:
    """`expected_today` for one result: an explicit caller-supplied
    ground-truth override (what a World-B test, which knows the specific
    subject's documented `TEST-MATRIX.md` state, supplies) wins; absent
    that, a FAIL defaults to "this is the known-bad state" and every other
    verdict defaults to "this is not a documented problem". Keeps every
    check function here a pure, fleet-agnostic reader -- it never hardcodes
    which named repo is expected to fail; only the caller (a test, or a
    future baseline loader) carries that domain knowledge."""

    if subject in overrides:
        return overrides[subject]
    return ExpectedToday.FAIL if verdict is Verdict.FAIL else ExpectedToday.PASS


# ---------------------------------------------------------------------------
# LI-1 -- lock.template.uniqueness (RC-4)
# ---------------------------------------------------------------------------

_UNIQUENESS = register_check(
    id="lock.template.uniqueness",
    layer=Layer.LOCK,
    severity="S0",
    scope=Scope.PER_REPO,
    mode=Mode.FAST,
    summary=(
        "copilot.lock.json is generated per project, not copied from a "
        "template -- no two independently-installed repos may share a "
        "byte-identical lock file."
    ),
    remediation=(
        "Wire cc.core.ecosystem.projects.write_project_lock into "
        "setup-project.md / update-project.md / "
        "codex-copilot/scripts/setup-project.sh so every install generates "
        "its own lock instead of one being copied onto another (RC-4)."
    ),
    expected_today=ExpectedToday.FAIL,
)


def check_lock_template_uniqueness(
    repo_roots: Iterable[Path | str],
    *,
    expected_today: Mapping[str, ExpectedToday] | None = None,
) -> tuple[CheckResult, ...]:
    """LI-1 / RC-4. Groups every repo's `copilot.lock.json` by raw-byte
    sha256. A repo sharing its hash with one or more siblings is proof the
    lock was copied rather than generated -- a per-project generator cannot
    produce two byte-identical outputs for two different repos. Repos with
    no lock file at all are outside this check's scope (`TEST-MATRIX.md`
    section 4 scopes LI-1..LI-5 to "every repo with a copilot.lock.json")
    and are reported SKIP rather than silently omitted."""

    overrides = expected_today or {}
    roots = [Path(root) for root in repo_roots]
    digests: dict[Path, str] = {}
    by_digest: dict[str, list[Path]] = {}
    results: list[CheckResult] = []

    for root in roots:
        lock_path = root / PROJECT_LOCK_FILENAME
        if not lock_path.is_file():
            subject = str(root)
            results.append(
                _UNIQUENESS.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    detail=f"no {PROJECT_LOCK_FILENAME} present -- outside this check's scope",
                    expected_today=_resolve_expected(subject, Verdict.SKIP, overrides),
                )
            )
            continue
        try:
            digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        except OSError as exc:
            subject = str(root)
            results.append(
                _UNIQUENESS.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail=f"could not read {lock_path}: {exc}",
                    expected_today=_resolve_expected(
                        subject, Verdict.COULD_NOT_RUN, overrides
                    ),
                )
            )
            continue
        digests[root] = digest
        by_digest.setdefault(digest, []).append(root)

    for root, digest in digests.items():
        subject = str(root)
        siblings = sorted(str(p) for p in by_digest[digest] if p != root)
        if siblings:
            results.append(
                _UNIQUENESS.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=(
                        Evidence(
                            kind="lock-hash-collision",
                            path=str(root / PROJECT_LOCK_FILENAME),
                            expected="a lock hash unique to this repo (per-project generated)",
                            actual=f"sha256:{digest} shared by {len(by_digest[digest])} repos",
                            detail="byte-identical to: " + ", ".join(siblings),
                        ),
                    ),
                    expected_today=_resolve_expected(subject, Verdict.FAIL, overrides),
                    root_cause="rc.rc4",
                )
            )
        else:
            results.append(
                _UNIQUENESS.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=_resolve_expected(subject, Verdict.PASS, overrides),
                )
            )
    return tuple(results)


# ---------------------------------------------------------------------------
# LI-2 -- lock.records_match_disk (checksum truth)
# ---------------------------------------------------------------------------

_CHECKSUM_TRUTH = register_check(
    id="lock.records_match_disk",
    layer=Layer.LOCK,
    severity="S1",
    scope=Scope.PER_REPO,
    mode=Mode.FAST,
    summary=(
        "every path copilot.lock.json records for a component -- framework "
        "files and managed outputs alike -- must checksum-match the file "
        "currently on disk."
    ),
    remediation=(
        "Re-run the installer/updater for the drifted component so the "
        "lock is regenerated from the actual install, or restore the "
        "recorded file if it was deleted or hand-edited."
    ),
    expected_today=ExpectedToday.PASS,
)


def check_lock_records_match_disk(
    repo_roots: Iterable[Path | str],
    *,
    expected_today: Mapping[str, ExpectedToday] | None = None,
) -> tuple[CheckResult, ...]:
    """LI-2. Wraps `project_integration._verify_lock_entry`'s own checksum
    verification -- it is never re-implemented here -- and reports on only
    the checksum-truth slice of that function's combined verdict.
    Required-path completeness is a distinct concern
    (`check_lock_full_mode_records_required_paths`, LI-5) kept in a
    separate check on purpose: a future fix could satisfy one without the
    other (`TEST-MATRIX.md` LI-5's own note)."""

    overrides = expected_today or {}
    results: list[CheckResult] = []

    for raw_root in repo_roots:
        root = Path(raw_root)
        subject = str(root)
        entries = _component_entries(root)
        if not entries:
            results.append(
                _CHECKSUM_TRUTH.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    detail="no readable schema-1.0 copilot.lock.json component entry",
                    expected_today=_resolve_expected(subject, Verdict.SKIP, overrides),
                )
            )
            continue

        evidence: list[Evidence] = []
        unverifiable: list[str] = []
        for component, entry in sorted(entries.items()):
            _ok, verify_evidence, missing, _fingerprint = _verify_lock_entry(
                root, component, entry
            )
            missing_ids = {item.get("id") for item in missing}
            if missing_ids & _STRUCTURAL_MISSING_IDS:
                structural_details = [
                    item["detail"]
                    for item in missing
                    if item.get("id") in _STRUCTURAL_MISSING_IDS
                ]
                unverifiable.append(f"{component}: " + "; ".join(structural_details))
                continue
            for item in verify_evidence:
                if item.get("kind") not in _CHECKSUM_EVIDENCE_KINDS:
                    continue
                evidence.append(
                    Evidence(
                        kind=item["kind"],
                        path=item["path"],
                        expected="checksum recorded in copilot.lock.json matches disk",
                        actual=item.get("state", "mismatch"),
                        detail=f"{component}: {item.get('detail', '')}",
                    )
                )
            if _INVALID_MANAGED_OUTPUT_ID in missing_ids:
                invalid_details = [
                    item["detail"]
                    for item in missing
                    if item.get("id") == _INVALID_MANAGED_OUTPUT_ID
                ]
                evidence.append(
                    Evidence(
                        kind="invalid-managed-output",
                        path=str(root / PROJECT_LOCK_FILENAME),
                        expected=(
                            "every managed_outputs[] record has exactly "
                            "path/kind/fingerprint, kind matching the "
                            "component's allowed managed-output kinds, and "
                            "fingerprint a well-formed sha256:<64 hex> hash"
                        ),
                        actual="malformed managed-output record",
                        detail=f"{component}: " + "; ".join(invalid_details),
                    )
                )

        if evidence:
            results.append(
                _CHECKSUM_TRUTH.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=tuple(evidence),
                    detail="; ".join(unverifiable),
                    expected_today=_resolve_expected(subject, Verdict.FAIL, overrides),
                )
            )
        elif unverifiable:
            results.append(
                _CHECKSUM_TRUTH.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="; ".join(unverifiable),
                    expected_today=_resolve_expected(
                        subject, Verdict.COULD_NOT_RUN, overrides
                    ),
                )
            )
        else:
            results.append(
                _CHECKSUM_TRUTH.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=_resolve_expected(subject, Verdict.PASS, overrides),
                )
            )
    return tuple(results)


# ---------------------------------------------------------------------------
# LI-3 -- lock.ownership.frontmatter_agrees
# ---------------------------------------------------------------------------

_OWNERSHIP_AGREES = register_check(
    id="lock.ownership.frontmatter_agrees",
    layer=Layer.LOCK,
    severity="S1",
    scope=Scope.PER_REPO,
    mode=Mode.FAST,
    summary=(
        "a file the lock records with ownership: framework must not "
        "declare owner: project in its own frontmatter -- the lock's claim "
        "and the file's claim about itself must agree."
    ),
    remediation=(
        "Re-record the file's lock entry to match its own frontmatter "
        "(owner: project files are never framework-owned); never overwrite "
        "the file to match the lock (Q21 answer A: preserve the project's "
        "customization and correct the lock)."
    ),
    expected_today=ExpectedToday.PASS,
)


def check_lock_ownership_frontmatter_agrees(
    repo_roots: Iterable[Path | str],
    *,
    expected_today: Mapping[str, ExpectedToday] | None = None,
) -> tuple[CheckResult, ...]:
    """LI-3. Every `files[]` entry the lock schema accepts is already
    constrained to `ownership: "framework"` by
    `project_integration._verify_lock_entry` itself (any other value makes
    the whole entry invalid) -- so the only question this check answers is
    whether the file's OWN frontmatter contradicts that claim by declaring
    `owner: project`. `sproutworks` is the confirmed live case: 5 agents
    (`elec`, `emb`, `fmea`, `hyd`, `src`) declare `owner: project` in their
    own frontmatter while the lock still records all five as `ownership:
    "framework"`."""

    overrides = expected_today or {}
    results: list[CheckResult] = []

    for raw_root in repo_roots:
        root = Path(raw_root)
        subject = str(root)
        entries = _component_entries(root)
        if not entries:
            results.append(
                _OWNERSHIP_AGREES.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    detail="no readable schema-1.0 copilot.lock.json component entry",
                    expected_today=_resolve_expected(subject, Verdict.SKIP, overrides),
                )
            )
            continue

        evidence: list[Evidence] = []
        for component, entry in sorted(entries.items()):
            files = entry.get("files")
            if not isinstance(files, list):
                continue
            for file_info in files:
                if not isinstance(file_info, dict):
                    continue
                if file_info.get("ownership") != "framework":
                    continue
                rel_path = file_info.get("path")
                if not isinstance(rel_path, str) or not rel_path:
                    continue
                declared = _frontmatter_owner(root / rel_path)
                if declared == "project":
                    evidence.append(
                        Evidence(
                            kind="ownership-contradiction",
                            path=rel_path,
                            expected="ownership: project (matching the file's own frontmatter)",
                            actual="ownership: framework",
                            detail=(
                                f"{component}: the lock records this file as "
                                "framework-owned, but its own frontmatter "
                                "declares owner: project"
                            ),
                        )
                    )

        if evidence:
            results.append(
                _OWNERSHIP_AGREES.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=tuple(evidence),
                    expected_today=_resolve_expected(subject, Verdict.FAIL, overrides),
                )
            )
        else:
            results.append(
                _OWNERSHIP_AGREES.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=_resolve_expected(subject, Verdict.PASS, overrides),
                )
            )
    return tuple(results)


# ---------------------------------------------------------------------------
# LI-4 -- lock.waiver.ready_requires_required_paths
# ---------------------------------------------------------------------------

_NO_WAIVED_READY = register_check(
    id="lock.waiver.ready_requires_required_paths",
    layer=Layer.LOCK,
    severity="S0",
    scope=Scope.PER_REPO,
    mode=Mode.FAST,
    summary=(
        "a component whose cc classification is fully-installed must not "
        "have reached that classification only because ownership_mode: "
        "customized-preserve waived one or more required lock paths."
    ),
    remediation=(
        "project_integration.py:539 sets absent_required=[] under "
        "ownership_mode: customized-preserve, so the lock is both the "
        "claim and the yardstick -- record the required paths independent "
        "of the waiver, or the classification must not read as "
        "fully-installed (see EXISTING-VERIFICATION.md section 2)."
    ),
    expected_today=ExpectedToday.FAIL,
)


def check_lock_waiver_ready_requires_required_paths(
    repo_roots: Iterable[Path | str],
    *,
    expected_today: Mapping[str, ExpectedToday] | None = None,
) -> tuple[CheckResult, ...]:
    """LI-4. The Divergence-4 trap (`EXISTING-VERIFICATION.md` section 2):
    `inspect_project_integration` (wrapped here, never recomputed) supplies
    the CLASSIFICATION -- this check independently answers the question
    that classification's own `customized-preserve` branch skips: would
    the required-path condition have held WITHOUT the waiver? A component
    that is not classified `ready` is outside this check's scope entirely
    (the waiver-detection question presupposes readiness was reached) and
    is reported SKIP.

    Two live proofs this check is built to reproduce: this repo
    (`copilot-control-tower`) classifies claude `ready` with only 2 of the
    4 required paths recorded under `customized-preserve`; and a synthetic
    minimum -- `CLAUDE.md` + `.mcp.json` + a lock with `files: []` under
    `customized-preserve` -- classifies claude `ready` with ZERO agents,
    skills, or commands on disk (`EXISTING-VERIFICATION.md` "Proof 2")."""

    overrides = expected_today or {}
    results: list[CheckResult] = []

    for raw_root in repo_roots:
        root = Path(raw_root)
        subject = str(root)
        entries = _component_entries(root)
        if not entries:
            results.append(
                _NO_WAIVED_READY.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    detail="no readable schema-1.0 copilot.lock.json component entry",
                    expected_today=_resolve_expected(subject, Verdict.SKIP, overrides),
                )
            )
            continue

        report = inspect_project_integration(root, detail=False)
        classifications = {
            item.get("component"): item.get("classification")
            for item in report.get("components", [])
            if isinstance(item, dict)
        }

        evidence: list[Evidence] = []
        applicable = False
        for component, entry in sorted(entries.items()):
            if classifications.get(component) != "ready":
                continue
            applicable = True
            mode = _ownership_mode(entry)
            if mode != "customized-preserve":
                continue  # reached ready (honestly) via the full required-path check
            recorded = _recorded_paths(entry)
            required = _REQUIRED_PATHS_BY_COMPONENT.get(component, ())
            absent = [path for path in required if path not in recorded]
            if absent:
                evidence.append(
                    Evidence(
                        kind="ready-by-waiver",
                        path=str(root / PROJECT_LOCK_FILENAME),
                        expected=(
                            f"all of {list(required)} recorded, or "
                            "ownership_mode: full"
                        ),
                        actual=(
                            f"ownership_mode: customized-preserve, "
                            f"{len(recorded)} file(s) recorded"
                        ),
                        detail=(
                            f"{component}: classification ready (by waiver, "
                            f"{len(recorded)} files) while never recording "
                            + ", ".join(absent)
                        ),
                    )
                )

        if evidence:
            results.append(
                _NO_WAIVED_READY.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=tuple(evidence),
                    expected_today=_resolve_expected(subject, Verdict.FAIL, overrides),
                )
            )
        elif applicable:
            results.append(
                _NO_WAIVED_READY.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=_resolve_expected(subject, Verdict.PASS, overrides),
                )
            )
        else:
            results.append(
                _NO_WAIVED_READY.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    detail=(
                        "no component reaches ready (classification below "
                        "fully-installed) -- waiver check not triggered"
                    ),
                    expected_today=_resolve_expected(subject, Verdict.SKIP, overrides),
                )
            )
    return tuple(results)


# ---------------------------------------------------------------------------
# LI-5 -- lock.required_paths.full_mode_complete
# ---------------------------------------------------------------------------

_FULL_MODE_REQUIRED_PATHS = register_check(
    id="lock.required_paths.full_mode_complete",
    layer=Layer.LOCK,
    severity="S0",
    scope=Scope.PER_REPO,
    mode=Mode.FAST,
    summary=(
        "every ownership_mode: full lock entry -- including one with no "
        "ownership_mode key at all, which defaults to full -- must record "
        "all of that component's required lock paths."
    ),
    remediation=(
        "Wire the installer to lock .claude/hooks/copilot-hook.sh (and the "
        "other _CLAUDE_REQUIRED_LOCK_PATHS / _CODEX_REQUIRED_LOCK_PATHS "
        "entries) whenever it installs them -- RC-1's consequence restated "
        "at the lock-schema level, kept as its own check because a future "
        "fix could satisfy the filesystem-level D4 check without updating "
        "the installer's lock-writing code."
    ),
    expected_today=ExpectedToday.FAIL,
)


def check_lock_full_mode_records_required_paths(
    repo_roots: Iterable[Path | str],
    *,
    expected_today: Mapping[str, ExpectedToday] | None = None,
) -> tuple[CheckResult, ...]:
    """LI-5. `ownership_mode` is absent from 12 of 13 real locks measured
    for this work package and defaults to `"full"` per
    `_verify_lock_entry`'s own `entry.get("ownership_mode", "full")` --
    handled explicitly here via `_ownership_mode`, never assumed present.
    A `customized-preserve` entry's bounded subset is a distinct, narrower
    contract (LI-4) and is out of this check's scope."""

    overrides = expected_today or {}
    results: list[CheckResult] = []

    for raw_root in repo_roots:
        root = Path(raw_root)
        subject = str(root)
        entries = _component_entries(root)
        if not entries:
            results.append(
                _FULL_MODE_REQUIRED_PATHS.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    detail="no readable schema-1.0 copilot.lock.json component entry",
                    expected_today=_resolve_expected(subject, Verdict.SKIP, overrides),
                )
            )
            continue

        evidence: list[Evidence] = []
        absent_paths: list[str] = []
        applicable = False
        for component, entry in sorted(entries.items()):
            if _ownership_mode(entry) != "full":
                continue
            applicable = True
            recorded = _recorded_paths(entry)
            required = _REQUIRED_PATHS_BY_COMPONENT.get(component, ())
            absent = [path for path in required if path not in recorded]
            for path in absent:
                absent_paths.append(path)
                on_disk = (root / path).exists()
                evidence.append(
                    Evidence(
                        kind="required-lock-path",
                        path=path,
                        expected="recorded in copilot.lock.json's files[]",
                        actual="on disk but not recorded" if on_disk else "not recorded, not on disk",
                        detail=f"{component}: ownership_mode full never records {path}",
                    )
                )

        if evidence:
            root_cause = (
                "rc.rc1"
                if any(path.endswith("copilot-hook.sh") for path in absent_paths)
                else None
            )
            results.append(
                _FULL_MODE_REQUIRED_PATHS.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    evidence=tuple(evidence),
                    expected_today=_resolve_expected(subject, Verdict.FAIL, overrides),
                    root_cause=root_cause,
                )
            )
        elif applicable:
            results.append(
                _FULL_MODE_REQUIRED_PATHS.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=_resolve_expected(subject, Verdict.PASS, overrides),
                )
            )
        else:
            results.append(
                _FULL_MODE_REQUIRED_PATHS.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    detail="no ownership_mode: full component entry present",
                    expected_today=_resolve_expected(subject, Verdict.SKIP, overrides),
                )
            )
    return tuple(results)


# ---------------------------------------------------------------------------
# Convenience: run every Layer-4 check together
# ---------------------------------------------------------------------------

LOCK_CHECKS: tuple[Callable[..., tuple[CheckResult, ...]], ...] = (
    check_lock_template_uniqueness,
    check_lock_records_match_disk,
    check_lock_ownership_frontmatter_agrees,
    check_lock_waiver_ready_requires_required_paths,
    check_lock_full_mode_records_required_paths,
)


def run_lock_checks(
    repo_roots: Iterable[Path | str],
    *,
    expected_today: Mapping[str, ExpectedToday] | None = None,
) -> tuple[CheckResult, ...]:
    """Run all five Layer-4 checks against the same repo set and
    concatenate their results -- the one-call seam a fleet sweep (Layer 3's
    orchestration) or the `cc conformance` CLI surface can use without
    knowing the individual check ids."""

    roots = list(repo_roots)
    results: list[CheckResult] = []
    for check in LOCK_CHECKS:
        results.extend(check(roots, expected_today=expected_today))
    return tuple(results)


__all__ = [
    "LOCK_CHECKS",
    "check_lock_full_mode_records_required_paths",
    "check_lock_ownership_frontmatter_agrees",
    "check_lock_records_match_disk",
    "check_lock_template_uniqueness",
    "check_lock_waiver_ready_requires_required_paths",
    "run_lock_checks",
]
