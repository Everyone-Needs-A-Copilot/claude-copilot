"""D3 — Project lock (`copilot.lock.json`): presence and shape only.

`RUBRIC.md` §D3 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d03.*`, applies to
classes A/B/C/D):

  PRESENT — `schema_version == "1.0"`, `components` is a list, every
  recorded checksum matches disk right now, and for `ownership_mode: full`
  entries every path in `_CLAUDE_REQUIRED_LOCK_PATHS` /
  `_CODEX_REQUIRED_LOCK_PATHS` is recorded.
  PARTIAL — `ownership_mode: customized-preserve` (a bounded waiver, not a
  pass — RUBRIC.md is explicit this is PARTIAL, never PRESENT), a
  mismatched/missing recorded checksum, or only one of the two components
  locked despite both being installed.
  ABSENT — file missing, or present but shaped like the *machine*
  ecosystem lock (a filename collision, not a project lock).

Deliberately shallow by design (`WP1-INTERFACES.md`'s task brief for this
work package): deep lock-integrity questions — is a `ready` verdict
achieved only by an abusive waiver (LI-4), does any lock hash collide with
another repo's (`lock.template.uniqueness`, RC-4), is an unowned extra
locked as `ownership: "framework"` (LI-3) — are WP-5's Layer 4 (`lock.py`).
This module asserts only what RUBRIC.md's own D3 text defines at the
per-repo install-conformance layer: checksums matching disk, and required
paths present **per `ownership_mode`** (i.e. `customized-preserve` entries
are correctly SKIPPED for the required-path assertion here, exactly as
RUBRIC.md scores them PARTIAL rather than FAIL — re-litigating whether that
waiver is being abused is explicitly out of scope for this module).

Every constant used here (`_CLAUDE_REQUIRED_LOCK_PATHS`,
`_CODEX_REQUIRED_LOCK_PATHS`, `_lock_state`, `_checksum`,
`_existing_component_paths`) is imported directly from
`cc.core.ecosystem.project_integration` rather than re-typed, so this
module cannot silently drift from the contract it verifies
(`HARNESS-DESIGN.md` §3.2 rule 1, ADR-002).

Real repos are read-only: every check here is a plain filesystem read
(`pathlib`, `json.loads` via the wrapped `_lock_state`, `hashlib.sha256`
via the wrapped `_checksum`) — no git access, no network, no write-shaped
call.
"""

from __future__ import annotations

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
    _CLAUDE_REQUIRED_LOCK_PATHS,
    _CODEX_REQUIRED_LOCK_PATHS,
    _checksum,
    _existing_component_paths,
    _lock_state,
)
from cc.core.ecosystem.projects import PROJECT_LOCK_FILENAME

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

_APPLIES_TO = ("A", "B", "C", "D")
_SUPPORTED_COMPONENTS = ("claude", "codex")
_REQUIRED_PATHS_BY_COMPONENT = {
    "claude": _CLAUDE_REQUIRED_LOCK_PATHS,
    "codex": _CODEX_REQUIRED_LOCK_PATHS,
}


# ---------------------------------------------------------------------------
# repo.d03.lock_schema_and_checksums
# ---------------------------------------------------------------------------

_D03_SCHEMA_CHECKSUMS_REGISTRATION = register_check(
    id="repo.d03.lock_schema_and_checksums",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "TEST-MATRIX.md IC-D3-SCHEMA/LI-2 (per-repo instance): "
        "`copilot.lock.json` exists, `schema_version == \"1.0\"`, "
        "`components` is a list, and every recorded file checksum matches "
        "the file on disk right now."
    ),
    remediation="Regenerate the project lock via a fresh `/setup-project` + `/update-project` (or the Codex install procedure) rather than hand-editing `copilot.lock.json`.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d03_lock_schema_and_checksums(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D03_SCHEMA_CHECKSUMS_REGISTRATION

    lock_state, lock_entries, _ = _lock_state(repo)

    if lock_state == "missing":
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="lock-missing",
                    path=PROJECT_LOCK_FILENAME,
                    expected='present, schema_version "1.0"',
                    actual="missing",
                ),
            ),
            detail="no copilot.lock.json (IC-D3-SCHEMA)",
            expected_today=expected_today,
        )
    if lock_state == "ecosystem-collision":
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="lock-ecosystem-collision",
                    path=PROJECT_LOCK_FILENAME,
                    expected='a project lock (schema_version "1.0")',
                    actual="shaped like the machine ecosystem lock (filename collision)",
                ),
            ),
            detail="ecosystem-lock filename collision, not a project lock (RUBRIC.md D3 ABSENT)",
            expected_today=expected_today,
        )
    if lock_state == "unreadable":
        return registration.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=(
                Evidence(
                    kind="lock-unreadable",
                    path=PROJECT_LOCK_FILENAME,
                    expected='valid JSON, schema_version "1.0", components: list',
                    actual="unreadable, malformed, or unsupported shape",
                ),
            ),
            detail="lock present but does not parse as a project lock",
            expected_today=expected_today,
        )

    evidence: list[Evidence] = []
    checked = 0
    for component, entry in sorted(lock_entries.items()):
        files = entry.get("files")
        if not isinstance(files, list):
            continue
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            rel_path = file_info.get("path")
            expected_checksum = file_info.get("checksum")
            if (
                not isinstance(rel_path, str)
                or not rel_path
                or not isinstance(expected_checksum, str)
            ):
                continue
            checked += 1
            target = repo / rel_path
            try:
                actual_checksum: str | None = _checksum(target)
            except (FileNotFoundError, OSError):
                actual_checksum = None
            if actual_checksum != expected_checksum:
                evidence.append(
                    Evidence(
                        kind="lock-checksum-mismatch",
                        path=rel_path,
                        expected=expected_checksum,
                        actual=actual_checksum or "missing",
                        detail=f"recorded under component={component!r}",
                    )
                )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    if checked == 0:
        detail = "structurally valid; 0 files recorded (nothing to checksum)"
    elif verdict is Verdict.PASS:
        detail = f"{checked}/{checked} recorded checksums match disk"
    else:
        detail = f"{checked - len(evidence)}/{checked} recorded checksums match disk"
    return registration.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d03.all_installed_components_locked
# ---------------------------------------------------------------------------

_D03_ALL_LOCKED_REGISTRATION = register_check(
    id="repo.d03.all_installed_components_locked",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        "Every installed component (claude and/or codex, by on-disk "
        "evidence) has a lock entry. Named failure: "
        "`knowledge-copilot-internal` locks codex only, despite 16 agents "
        "+ 15 commands on disk."
    ),
    remediation="Run the missing component's install/update procedure so its lock entry is generated rather than left absent.",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def check_d03_all_installed_components_locked(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D03_ALL_LOCKED_REGISTRATION

    lock_state, lock_entries, _ = _lock_state(repo)
    locked = set(lock_entries) if lock_state == "verified" else set()

    unlocked_installed: list[tuple[str, list[str]]] = []
    installed_any = False
    for component in _SUPPORTED_COMPONENTS:
        existing_paths, _readable = _existing_component_paths(repo, component)
        if not existing_paths:
            continue
        installed_any = True
        if component not in locked:
            unlocked_installed.append((component, existing_paths))

    if not installed_any:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail="neither claude nor codex has any relevant path on disk",
            expected_today=expected_today,
        )
    if not unlocked_installed:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail=f"{sorted(locked)} all locked, matching what is installed",
            expected_today=expected_today,
        )

    evidence = tuple(
        Evidence(
            kind="component-unlocked",
            path=paths[0],
            expected=f"a {component!r} entry in {PROJECT_LOCK_FILENAME}",
            actual=f"no lock entry ({len(paths)} on-disk artifact(s) present)",
        )
        for component, paths in unlocked_installed
    )
    detail = ", ".join(f"{component} installed but unlocked" for component, _ in unlocked_installed)
    return registration.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=detail,
        expected_today=expected_today,
    )


# ---------------------------------------------------------------------------
# repo.d03.required_paths_present_when_full
# ---------------------------------------------------------------------------

_D03_REQUIRED_PATHS_REGISTRATION = register_check(
    id="repo.d03.required_paths_present_when_full",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "RUBRIC.md D3 PRESENT bullet, per-repo: for every lock entry with "
        "`ownership_mode: full` (the default), every path in "
        "`_CLAUDE_REQUIRED_LOCK_PATHS`/`_CODEX_REQUIRED_LOCK_PATHS` is "
        "recorded. `customized-preserve` entries are correctly SKIPPED "
        "here (a bounded waiver at THIS dimension per RUBRIC.md — whether "
        "the waiver is abused is WP-5 Layer 4's LI-4/LI-5, not this check)."
    ),
    remediation="Run `/update-project` (claude) or the Codex install procedure so the generated lock records every required path; this is expected to fail machine-wide until `.claude/hooks/copilot-hook.sh` is installed by something (RC-1).",
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.FAIL,
)


def check_d03_required_paths_present_when_full(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D03_REQUIRED_PATHS_REGISTRATION

    lock_state, lock_entries, _ = _lock_state(repo)
    if lock_state != "verified":
        return registration.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail=f"no verified lock to evaluate (lock_state={lock_state})",
            expected_today=expected_today,
        )

    evidence: list[Evidence] = []
    evaluated_any = False
    for component, entry in sorted(lock_entries.items()):
        ownership_mode = entry.get("ownership_mode", "full")
        if ownership_mode == "customized-preserve":
            continue
        evaluated_any = True
        files = entry.get("files") if isinstance(entry.get("files"), list) else []
        recorded = {f.get("path") for f in files if isinstance(f, dict)}
        for path in _REQUIRED_PATHS_BY_COMPONENT.get(component, ()):
            if path not in recorded:
                evidence.append(
                    Evidence(
                        kind="required-lock-path-missing",
                        path=path,
                        expected=f"recorded in the {component!r} lock entry (ownership_mode={ownership_mode!r})",
                        actual="not recorded",
                    )
                )

    if not evaluated_any:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.SKIP,
            detail="every locked component is customized-preserve (waived at this layer; see Layer 4)",
            expected_today=expected_today,
        )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        "all full-mode components record every required path"
        if verdict is Verdict.PASS
        else f"{len(evidence)} required path(s) unrecorded across full-mode component(s)"
    )
    return registration.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


# Every registration this module owns, in the order `run()` evaluates them
# -- used only for the class-SKIP branch (`dimensions/__init__.py`'s
# contract: "a Verdict.SKIP result ... for any check whose
# applies_to_classes excludes context.rubric_class").
_D03_REGISTRATIONS: tuple[Any, ...] = (
    _D03_SCHEMA_CHECKSUMS_REGISTRATION,
    _D03_ALL_LOCKED_REGISTRATION,
    _D03_REQUIRED_PATHS_REGISTRATION,
)


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` per check id this module registered, for
    every repo -- a `Verdict.SKIP` for class E (D3 applies to A/B/C/D)."""

    if context.rubric_class not in _APPLIES_TO:
        skip_detail = f"N/A for class {context.rubric_class} -- D3 applies to classes A/B/C/D, not E."
        return tuple(
            registration.result(
                subject=context.subject, verdict=Verdict.SKIP, detail=skip_detail
            )
            for registration in _D03_REGISTRATIONS
        )

    return (
        check_d03_lock_schema_and_checksums(context.path, subject=context.subject),
        check_d03_all_installed_components_locked(context.path, subject=context.subject),
        check_d03_required_paths_present_when_full(context.path, subject=context.subject),
    )


__all__ = [
    "check_d03_all_installed_components_locked",
    "check_d03_lock_schema_and_checksums",
    "check_d03_required_paths_present_when_full",
    "run",
]
