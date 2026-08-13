"""D2 — Codex Copilot install conformance.

`RUBRIC.md` §D2 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d02.*`, applies to
classes A/B/C — optional for D — not E):

  PRESENT — all of: `AGENTS.md` contains **both** `## Codex Copilot` and
  `./plugins/codex-copilot`; `plugins/codex-copilot/.codex-plugin/plugin.json`
  has `name == "codex-copilot"`; `.claude/skills/codex-copilot` is a
  symlink whose readlink is `../../plugins/codex-copilot/skills` and which
  resolves inside the project; `scripts/copilot-gate.sh` is present and
  executable; `.agents/plugins/marketplace.json` is present;
  `.codex-copilot.json` has `installType` in `{copy, link}`.
  PARTIAL — `installType: "symlink"` into a shared checkout (the
  `codex-legacy-linked-v1` topology — keeps working, but the moving target
  invalidates the lock forever); plugin content diverged from the pinned
  mirror; or the skill bridge is missing/dangling/pointing outside.
  ABSENT — no `AGENTS.md` and no `plugins/codex-copilot/`.

Ground truth verified directly on this machine (2026-08-10), not trusted
from rubric prose: `plugins/codex-copilot/` under the pinned mirror
(`~/.copilot/mirrors/codex-foundation` by default) and under a correctly
installed project (`TSM/hermes`) both contain exactly **61 files**;
`scripts/copilot-gate.sh` lives OUTSIDE `plugins/` — so the correct count
of locked codex paths is **61 + 1 = 62**, not "62 files [inside
plugins/codex-copilot]" as an earlier draft stated
(`TEST-MATRIX.md`: "Rubric error #2").

Dangling-symlink handling (task-mandated): a `.claude/skills/codex-copilot`
symlink whose readlink text is exactly right but whose target does not yet
exist is genuinely ambiguous (mid-install vs. actually broken) and MUST
report `Verdict.COULD_NOT_RUN`, never a fabricated `PASS` and never a bare
structural `FAIL` — this module detects that exact case by wrapping
(never re-implementing) `project_integration._verify_internal_skill_link`,
whose own fingerprint literally names it `"contained-target-missing"`.
This also gets the recognized `_configured_external_claude_skills_root`
topology (an org-wide `.claude/skills` hierarchy) correct for free, since
that function already accounts for it.

Real repos are read-only: every check here is a plain filesystem
read/compare (`pathlib`, `json.loads`, a recursive file-set diff against
the local pinned mirror) — no git access, no network, no write-shaped call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

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
from cc.core.ecosystem.project_integration import (
    _checksum,
    _framework_root,
    _lock_state,
    _verify_internal_skill_link,
)

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

AGENTS_MD_RELATIVE_PATH = "AGENTS.md"
AGENTS_MD_HEADING = "## Codex Copilot"
AGENTS_MD_PLUGIN_REFERENCE = "./plugins/codex-copilot"
PLUGIN_MANIFEST_RELATIVE_PATH = "plugins/codex-copilot/.codex-plugin/plugin.json"
PLUGIN_TREE_RELATIVE_DIR = "plugins/codex-copilot"
SKILL_BRIDGE_RELATIVE_PATH = ".claude/skills/codex-copilot"
COPILOT_GATE_RELATIVE_PATH = "scripts/copilot-gate.sh"
MARKETPLACE_RELATIVE_PATH = ".agents/plugins/marketplace.json"
CODEX_CONFIG_RELATIVE_PATH = ".codex-copilot.json"

_APPLIES_TO = ("A", "B", "C")
_DANGLING_FINGERPRINT_TAG = "contained-target-missing"


# ---------------------------------------------------------------------------
# repo.d02.codex_entry_contract — the compound 6-condition IC-D2-CODEX check
# ---------------------------------------------------------------------------

_D02_ENTRY_CONTRACT_REGISTRATION = register_check(
    id="repo.d02.codex_entry_contract",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "TEST-MATRIX.md IC-D2-CODEX, all 6 conditions: AGENTS.md contains "
        "both `## Codex Copilot` and `./plugins/codex-copilot`; the plugin "
        "manifest names `codex-copilot`; the skill bridge symlink resolves "
        "inside the project; `scripts/copilot-gate.sh` is executable; "
        "`.agents/plugins/marketplace.json` is present; "
        "`.codex-copilot.json` has `installType` in `{copy, link}`."
    ),
    remediation=(
        "Re-run the Codex `setup-project.sh` procedure for the missing "
        "condition(s); note `codex-copilot` itself fails this contract "
        "today (AGENTS.md is missing the `./` prefix on the plugin "
        "reference)."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def check_d02_codex_entry_contract(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    evidence: list[Evidence] = []
    dangling_only = False

    # (a) AGENTS.md
    agents_md = repo / AGENTS_MD_RELATIVE_PATH
    try:
        text: str | None = agents_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None
    agents_ok = bool(
        text and AGENTS_MD_HEADING in text and AGENTS_MD_PLUGIN_REFERENCE in text
    )
    if not agents_ok:
        evidence.append(
            Evidence(
                kind="agents-md-contract",
                path=AGENTS_MD_RELATIVE_PATH,
                expected=f"contains {AGENTS_MD_HEADING!r} and {AGENTS_MD_PLUGIN_REFERENCE!r}",
                actual="missing" if text is None else "one or both substrings absent",
            )
        )

    # (b) plugin manifest
    manifest = _read_json(repo / PLUGIN_MANIFEST_RELATIVE_PATH)
    manifest_ok = isinstance(manifest, dict) and manifest.get("name") == "codex-copilot"
    if not manifest_ok:
        evidence.append(
            Evidence(
                kind="plugin-manifest-invalid",
                path=PLUGIN_MANIFEST_RELATIVE_PATH,
                expected='name == "codex-copilot"',
                actual="missing/unreadable" if manifest is None else f"name={manifest.get('name')!r}",
            )
        )

    # (c) skill bridge
    bridge_ok, bridge_detail, bridge_fingerprint = _verify_internal_skill_link(repo)
    if not bridge_ok:
        dangling = bool(bridge_fingerprint) and bridge_fingerprint[-1] == _DANGLING_FINGERPRINT_TAG
        dangling_only = dangling
        evidence.append(
            Evidence(
                kind="skill-bridge-dangling" if dangling else "skill-bridge-invalid",
                path=SKILL_BRIDGE_RELATIVE_PATH,
                expected="../../plugins/codex-copilot/skills, resolving inside the project",
                actual="correct relative target, but the target does not exist yet"
                if dangling
                else bridge_detail,
            )
        )

    # (d) copilot-gate.sh
    gate = repo / COPILOT_GATE_RELATIVE_PATH
    gate_ok = gate.is_file() and os.access(gate, os.X_OK)
    if not gate_ok:
        evidence.append(
            Evidence(
                kind="copilot-gate-missing",
                path=COPILOT_GATE_RELATIVE_PATH,
                expected="present, executable",
                actual="missing" if not gate.is_file() else "present, not executable",
            )
        )

    # (e) marketplace.json
    marketplace = repo / MARKETPLACE_RELATIVE_PATH
    if not marketplace.is_file():
        evidence.append(
            Evidence(
                kind="marketplace-missing",
                path=MARKETPLACE_RELATIVE_PATH,
                expected="present",
                actual="missing",
            )
        )

    # (f) .codex-copilot.json installType
    config = _read_json(repo / CODEX_CONFIG_RELATIVE_PATH)
    install_type = config.get("installType") if isinstance(config, dict) else None
    config_ok = install_type in ("copy", "link")
    if not config_ok:
        evidence.append(
            Evidence(
                kind="codex-config-invalid",
                path=CODEX_CONFIG_RELATIVE_PATH,
                expected='installType in {"copy", "link"}',
                actual="missing/unreadable" if config is None else f"installType={install_type!r}",
            )
        )

    if not evidence:
        return _D02_ENTRY_CONTRACT_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail="all 6 conditions verified",
            expected_today=expected_today,
        )

    only_dangling = dangling_only and len(evidence) == 1
    verdict = Verdict.COULD_NOT_RUN if only_dangling else Verdict.FAIL
    return _D02_ENTRY_CONTRACT_REGISTRATION.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=f"{len(evidence)} of 6 condition(s) unmet.",
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d02.plugin_tree_matches_pinned_mirror
# ---------------------------------------------------------------------------

_D02_PLUGIN_TREE_REGISTRATION = register_check(
    id="repo.d02.plugin_tree_matches_pinned_mirror",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "TEST-MATRIX.md IC-D2-VERSION: `plugins/codex-copilot/` byte-"
        "matches the pinned mirror (`paths.codex_copilot_root`, "
        "`~/.copilot/mirrors/codex-foundation` by default) — 61 files, no "
        "extras, no content drift."
    ),
    remediation="Re-run the Codex setup/install procedure to refresh the plugin copy from the pinned mirror.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d02_plugin_tree_matches_pinned_mirror(
    repo: Path,
    *,
    codex_root: Path | str | None = None,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D02_PLUGIN_TREE_REGISTRATION

    mirror_root = _framework_root("codex", codex_root)
    if mirror_root is None:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.COULD_NOT_RUN,
            evidence=(
                Evidence(
                    kind="mirror-root-unresolved",
                    path="paths.codex_copilot_root",
                    expected="a resolvable codex mirror checkout",
                    actual="unresolved or not a directory",
                ),
            ),
            detail="codex mirror root unresolved",
            expected_today=expected_today,
        )

    mirror_plugin = mirror_root / PLUGIN_TREE_RELATIVE_DIR
    if not mirror_plugin.is_dir():
        return registration.result(
            subject=subject_name,
            verdict=Verdict.COULD_NOT_RUN,
            evidence=(
                Evidence(
                    kind="mirror-plugin-missing",
                    path=str(mirror_plugin),
                    expected="present",
                    actual="missing",
                ),
            ),
            detail="no plugins/codex-copilot under the resolved mirror -- nothing to compare against",
            expected_today=expected_today,
        )

    target_plugin = repo / PLUGIN_TREE_RELATIVE_DIR
    if not target_plugin.is_dir():
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="plugin-tree-missing",
                    path=PLUGIN_TREE_RELATIVE_DIR,
                    expected=f"present, matching {mirror_plugin}",
                    actual="missing",
                ),
            ),
            detail="plugins/codex-copilot absent from this project",
            expected_today=expected_today,
        )

    mirror_files = {
        p.relative_to(mirror_plugin).as_posix(): p
        for p in sorted(mirror_plugin.rglob("*"))
        if p.is_file()
    }
    target_files = {
        p.relative_to(target_plugin).as_posix(): p
        for p in sorted(target_plugin.rglob("*"))
        if p.is_file()
    }
    missing = sorted(set(mirror_files) - set(target_files))
    extra = sorted(set(target_files) - set(mirror_files))
    mismatched = sorted(
        rel
        for rel in set(mirror_files) & set(target_files)
        if _checksum(mirror_files[rel]) != _checksum(target_files[rel])
    )

    if not (missing or extra or mismatched):
        return registration.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=f"{len(target_files)} file(s) byte-match the pinned mirror ({mirror_root})",
            expected_today=expected_today,
        )

    evidence = (
        tuple(
            Evidence(
                kind="plugin-tree-missing-file",
                path=f"{PLUGIN_TREE_RELATIVE_DIR}/{rel}",
                expected="present (in mirror)",
                actual="missing",
            )
            for rel in missing[:20]
        )
        + tuple(
            Evidence(
                kind="plugin-tree-extra-file",
                path=f"{PLUGIN_TREE_RELATIVE_DIR}/{rel}",
                expected="absent (not in mirror)",
                actual="present",
            )
            for rel in extra[:20]
        )
        + tuple(
            Evidence(
                kind="plugin-tree-content-mismatch",
                path=f"{PLUGIN_TREE_RELATIVE_DIR}/{rel}",
                expected="checksum matches mirror",
                actual="checksum differs",
            )
            for rel in mismatched[:20]
        )
    )
    detail = (
        f"{len(target_files)} local files vs {len(mirror_files)} in mirror "
        f"({mirror_root}): {len(missing)} missing, {len(extra)} extra, "
        f"{len(mismatched)} content-mismatched."
    )
    return registration.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=detail,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d02.skill_bridge_internal_symlink
# ---------------------------------------------------------------------------

_D02_SKILL_BRIDGE_REGISTRATION = register_check(
    id="repo.d02.skill_bridge_internal_symlink",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        "`.claude/skills/codex-copilot` is a symlink whose readlink is "
        "`../../plugins/codex-copilot/skills` and which resolves inside "
        "the project. A dangling symlink (correct text, missing target) "
        "reports could-not-verify, never a fabricated pass."
    ),
    remediation="Re-run the Codex setup procedure to (re)create the internal skill bridge symlink; a dangling link usually means the plugin tree copy has not finished/landed yet.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d02_skill_bridge_internal_symlink(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D02_SKILL_BRIDGE_REGISTRATION

    valid, detail_message, fingerprint = _verify_internal_skill_link(repo)
    if valid:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=detail_message,
            expected_today=expected_today,
        )

    dangling = bool(fingerprint) and fingerprint[-1] == _DANGLING_FINGERPRINT_TAG
    if dangling:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.COULD_NOT_RUN,
            evidence=(
                Evidence(
                    kind="skill-bridge-dangling",
                    path=SKILL_BRIDGE_RELATIVE_PATH,
                    expected="../../plugins/codex-copilot/skills, target present",
                    actual="correct relative target, but the target does not exist yet (dangling)",
                ),
            ),
            detail="dangling symlink -- correct shape, unverifiable target",
            expected_today=expected_today,
        )

    return registration.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=(
            Evidence(
                kind="skill-bridge-invalid",
                path=SKILL_BRIDGE_RELATIVE_PATH,
                expected="../../plugins/codex-copilot/skills, resolving inside the project",
                actual=str(fingerprint),
            ),
        ),
        detail=detail_message,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d02.install_type_not_legacy_symlink
# ---------------------------------------------------------------------------

_D02_INSTALL_TYPE_REGISTRATION = register_check(
    id="repo.d02.install_type_not_legacy_symlink",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        "`.codex-copilot.json` `installType` is `copy` or `link`, never "
        "`symlink` into a shared checkout (the `codex-legacy-linked-v1` "
        "topology: keeps working, but the moving target invalidates the "
        "lock forever — RUBRIC.md D2 PARTIAL, never PRESENT)."
    ),
    remediation="Migrate the legacy symlink install to a portable project-local `copy`/`link` plugin (reviewed migration, not an automatic rewrite).",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d02_install_type_not_legacy_symlink(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D02_INSTALL_TYPE_REGISTRATION

    config = _read_json(repo / CODEX_CONFIG_RELATIVE_PATH)
    if not isinstance(config, dict):
        return registration.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail=".codex-copilot.json absent, unreadable, or not an object -- nothing to evaluate",
            expected_today=expected_today,
        )

    install_type = config.get("installType")
    if install_type == "symlink":
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="install-type-legacy-symlink",
                    path=CODEX_CONFIG_RELATIVE_PATH,
                    expected='installType in {"copy", "link"}',
                    actual="symlink",
                ),
            ),
            detail="codex-legacy-linked-v1 topology (RUBRIC.md D2 PARTIAL)",
            expected_today=expected_today,
        )
    if install_type in ("copy", "link"):
        return registration.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=f"installType={install_type!r}",
            expected_today=expected_today,
        )
    return registration.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=(
            Evidence(
                kind="install-type-invalid",
                path=CODEX_CONFIG_RELATIVE_PATH,
                expected='installType in {"copy", "link", "symlink"}',
                actual=repr(install_type),
            ),
        ),
        detail=f"unrecognized installType {install_type!r}",
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d02.declared_version_matches_lock
# ---------------------------------------------------------------------------

_D02_DECLARED_VERSION_REGISTRATION = register_check(
    id="repo.d02.declared_version_matches_lock",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        "`.codex-copilot.json` `frameworkVersion` equals the codex "
        "component's `version` in `copilot.lock.json`. Named failures: "
        "`method-copilot` (0.5.0 vs 0.6.1), `saas-financial-model`, "
        "`knowledge-copilot-internal`."
    ),
    remediation="Re-run the Codex setup/update procedure so `.codex-copilot.json` and `copilot.lock.json` are written from the same install.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d02_declared_version_matches_lock(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D02_DECLARED_VERSION_REGISTRATION

    config = _read_json(repo / CODEX_CONFIG_RELATIVE_PATH)
    declared = config.get("frameworkVersion") if isinstance(config, dict) else None
    if not isinstance(declared, str) or not declared:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="declared-version-missing",
                    path=CODEX_CONFIG_RELATIVE_PATH,
                    expected="a frameworkVersion string",
                    actual="missing or unreadable",
                ),
            ),
            detail="no declared frameworkVersion to compare",
            expected_today=expected_today,
        )

    lock_state, lock_entries, _ = _lock_state(repo)
    codex_entry = lock_entries.get("codex") if lock_state == "verified" else None
    locked_version = codex_entry.get("version") if isinstance(codex_entry, dict) else None
    if not isinstance(locked_version, str) or not locked_version:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="lock-version-missing",
                    path="copilot.lock.json",
                    expected="a codex component entry with a version",
                    actual=f"lock_state={lock_state}",
                ),
            ),
            detail="no codex lock entry to compare against",
            expected_today=expected_today,
        )

    if declared == locked_version:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=f"{declared} == {locked_version}",
            expected_today=expected_today,
        )

    return registration.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=(
            Evidence(
                kind="version-mismatch",
                path=CODEX_CONFIG_RELATIVE_PATH,
                expected=f"frameworkVersion == lock version ({locked_version!r})",
                actual=repr(declared),
            ),
        ),
        detail=f"declared {declared!r} != locked {locked_version!r}.",
        expected_today=expected_today,
    )


# Every registration this module owns, in the order `run()` evaluates them
# -- used only for the class-SKIP branch (`dimensions/__init__.py`'s
# contract: "a Verdict.SKIP result ... for any check whose
# applies_to_classes excludes context.rubric_class").
_D02_REGISTRATIONS: tuple[Any, ...] = (
    _D02_ENTRY_CONTRACT_REGISTRATION,
    _D02_PLUGIN_TREE_REGISTRATION,
    _D02_SKILL_BRIDGE_REGISTRATION,
    _D02_INSTALL_TYPE_REGISTRATION,
    _D02_DECLARED_VERSION_REGISTRATION,
)


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` per check id this module registered, for
    every repo -- a `Verdict.SKIP` for classes D/E (D2 applies to A/B/C;
    "optional for D" per RUBRIC.md is honored as SKIP-not-mandatory here,
    same as an unambiguous N/A)."""

    if context.rubric_class not in _APPLIES_TO:
        skip_detail = f"N/A for class {context.rubric_class} -- D2 applies to classes A/B/C (optional for D)."
        return tuple(
            registration.result(
                subject=context.subject, verdict=Verdict.SKIP, detail=skip_detail
            )
            for registration in _D02_REGISTRATIONS
        )

    return (
        check_d02_codex_entry_contract(context.path, subject=context.subject),
        check_d02_plugin_tree_matches_pinned_mirror(context.path, subject=context.subject),
        check_d02_skill_bridge_internal_symlink(context.path, subject=context.subject),
        check_d02_install_type_not_legacy_symlink(context.path, subject=context.subject),
        check_d02_declared_version_matches_lock(context.path, subject=context.subject),
    )


__all__ = [
    "AGENTS_MD_HEADING",
    "AGENTS_MD_PLUGIN_REFERENCE",
    "AGENTS_MD_RELATIVE_PATH",
    "CODEX_CONFIG_RELATIVE_PATH",
    "COPILOT_GATE_RELATIVE_PATH",
    "MARKETPLACE_RELATIVE_PATH",
    "PLUGIN_MANIFEST_RELATIVE_PATH",
    "PLUGIN_TREE_RELATIVE_DIR",
    "SKILL_BRIDGE_RELATIVE_PATH",
    "check_d02_codex_entry_contract",
    "check_d02_declared_version_matches_lock",
    "check_d02_install_type_not_legacy_symlink",
    "check_d02_plugin_tree_matches_pinned_mirror",
    "check_d02_skill_bridge_internal_symlink",
    "run",
]
