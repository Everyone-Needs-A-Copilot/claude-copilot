"""D4 — Enforcement hook (`.claude/hooks/copilot-hook.sh`).

`RUBRIC.md` §D4 / `HARNESS-DESIGN.md` §4 Layer 3
(`repo.d04.hook_present_and_locked`, S0, applies to classes A/B/C/D) — "This
dimension is the machine's dominant failure and deserves its own line in
the audit output":

  PRESENT — `.claude/hooks/copilot-hook.sh` exists, is executable, **and**
  is recorded in `copilot.lock.json` with a matching checksum. All three
  conditions are compound and every one is independently evidenced below.
  PARTIAL — `.claude/settings.json` declares hooks but the artifact is not
  present (a settings entry with no artifact behind it), or the file is
  present but unlocked.
  ABSENT — neither.

Ground truth, verified directly on this machine (2026-08-10), not assumed:
at the time this module was written, `claude-copilot`'s own
`.claude/hooks/copilot-hook.sh` existed and was executable, but its own
`copilot.lock.json` claude entry recorded 19 files and none of them was
`.claude/hooks/copilot-hook.sh` — so even the ONE repo on the machine with
the file present still failed the compound requirement. That was RC-1
(`grep -c copilot-hook setup-project.md update-project.md` returned 0 in
both files — no sanctioned command installed the file at all), measured at
**0 of 76** directories machine-wide satisfying the compound PRESENT test.
RC-1 has since been fixed upstream (`setup-project.md` Step 6B /
`update-project.md` Step 7B now vendor and lock the hook on every install
or update) — re-verify live counts with `cc conformance check --json
--full` rather than trusting the 0/76 figure above, which is a
point-in-time fact about this module's own authoring, not a standing
invariant. This check's registration `expected_today=ExpectedToday.FAIL`
default is deliberately NOT relaxed just because most repos now pass it
live — weakening the registered default to PASS would misreport a repo
that genuinely still fails (never re-installed since RC-1 landed) as
"expected", which is the same "known-broken ecosystem reported healthy"
failure mode in reverse (`WP1-INTERFACES.md`).

The lock lookup reuses `project_integration._lock_state` and `._checksum`
directly (wrapped, never re-implemented — `HARNESS-DESIGN.md` §3.2 rule 1)
so "is it locked, with a matching checksum" can never silently diverge from
what `cc workspace verify` itself would compute for the same file.

Real repos are read-only: a plain filesystem stat/exec-bit check plus a
lock-file read and a sha256 recompute — no git access, no network, no
write-shaped call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

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
from cc.core.ecosystem.project_integration import _checksum, _lock_state

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

HOOK_RELATIVE_PATH = ".claude/hooks/copilot-hook.sh"
CLAUDE_MD_RELATIVE_PATH = "CLAUDE.md"
AGENTS_MD_RELATIVE_PATH = "AGENTS.md"

_APPLIES_TO = ("A", "B", "C", "D")
_ROOT_CAUSE = "RC-1"

_D04_HOOK_REGISTRATION = register_check(
    id="repo.d04.hook_present_and_locked",
    layer=Layer.REPO,
    severity=Severity.S0,
    scope=Scope.PER_REPO,
    summary=(
        "`.claude/hooks/copilot-hook.sh` exists, is executable, and is "
        "recorded in the claude component of `copilot.lock.json` with a "
        "checksum that matches disk right now (all three, compound)."
    ),
    remediation=(
        "RC-1: no sanctioned command installs or locks this file today "
        "(`grep -c copilot-hook setup-project.md update-project.md` == 0 "
        "in both). The repair recipe exists "
        "(`reconciliation_recipes.py:1061-1074`, 'Install the missing "
        "framework-owned .claude/hooks/copilot-hook.sh file') but is "
        "unreachable from any sanctioned command "
        "(`can_apply_now: false` everywhere) -- this is an upstream "
        "installer fix, not a per-repo one; fixing `setup-project.md` / "
        "`update-project.md` converts this from an S0 (no repair path) to "
        "an S1 (fan-out) for every repo at once."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.FAIL,
)


def check_d04_hook_present_and_locked(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    registration = _D04_HOOK_REGISTRATION

    hook_path = repo / HOOK_RELATIVE_PATH
    exists = hook_path.is_file()
    executable = exists and os.access(hook_path, os.X_OK)

    lock_state, lock_entries, _ = _lock_state(repo)
    claude_entry = lock_entries.get("claude") if lock_state == "verified" else None
    recorded_checksum: str | None = None
    if isinstance(claude_entry, dict):
        for file_info in claude_entry.get("files") or []:
            if isinstance(file_info, dict) and file_info.get("path") == HOOK_RELATIVE_PATH:
                candidate = file_info.get("checksum")
                recorded_checksum = candidate if isinstance(candidate, str) else None
                break

    actual_checksum: str | None = None
    if exists:
        try:
            actual_checksum = _checksum(hook_path)
        except (FileNotFoundError, OSError):
            actual_checksum = None

    locked = recorded_checksum is not None and recorded_checksum == actual_checksum

    if exists and executable and locked:
        return registration.result(
            subject=subject_name,
            verdict=Verdict.PASS,
            detail="present, executable, and locked with a matching checksum",
            expected_today=expected_today,
            root_cause=_ROOT_CAUSE,
        )

    evidence: list[Evidence] = []
    if not exists:
        evidence.append(
            Evidence(
                kind="hook-missing",
                path=HOOK_RELATIVE_PATH,
                expected="present",
                actual="missing",
            )
        )
    elif not executable:
        evidence.append(
            Evidence(
                kind="hook-not-executable",
                path=HOOK_RELATIVE_PATH,
                expected="executable",
                actual="present, not executable",
            )
        )
    if not locked:
        evidence.append(
            Evidence(
                kind="hook-not-locked",
                path=HOOK_RELATIVE_PATH,
                expected="recorded in the claude lock entry with a matching checksum",
                actual="not recorded" if recorded_checksum is None else "recorded checksum does not match disk",
            )
        )

    detail = (
        "RC-1: the enforcement hook is installed by nothing "
        "(setup-project.md/update-project.md reference copilot-hook 0 "
        "times) -- 0/76 repos machine-wide satisfy this compound "
        "requirement today, including claude-copilot itself (has the "
        "file, does not lock it)."
    )
    return registration.result(
        subject=subject_name,
        verdict=Verdict.FAIL,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
        root_cause=_ROOT_CAUSE,
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` for `repo.d04.hook_present_and_locked`, for
    every repo -- a `Verdict.SKIP` for class E (D4 applies to A/B/C/D), and
    a second, narrower `Verdict.SKIP` for a repo that is genuinely not a
    Claude Copilot project at all.

    D4 checks a Claude Code-specific artifact (`.claude/hooks/`), so
    `applies_to_classes` alone is not a sufficient applicability gate: a
    rubric-A/B/C/D directory can still be a member of the CODEX ladder
    rather than the CLAUDE one (`classes.py`'s own docstring: "one of the
    four synced framework families' tier ladder" -- the Codex family and
    the Claude family are different ladders sharing the same rubric
    letters). `codex-copilot` is the confirmed live case: a `COMPONENT`/
    `foundation` (rubric A) directory with `AGENTS.md` and no `CLAUDE.md`
    at all -- verified against every other `codex-*` tier variant on this
    machine, which DO carry both files (they consume both frameworks) and
    are correctly still graded here. This is evidence-based, never a
    hardcoded repo name (`classes.py`'s own warning against the
    "`-internal`/`test-pilot` trap"): any directory with `AGENTS.md` and
    no `CLAUDE.md` reads the same way, because a directory that has never
    declared itself a Claude Code project cannot be missing a Claude Code
    artifact -- there is nothing to be ABSENT or PARTIAL about. A directory
    that DOES carry `CLAUDE.md` (even alongside `AGENTS.md`, i.e. a
    dual-stack project) is unaffected and keeps being graded as before."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _D04_HOOK_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D4 applies "
                    "to classes A/B/C/D, not E."
                ),
            ),
        )
    has_claude_md = (context.path / CLAUDE_MD_RELATIVE_PATH).is_file()
    has_agents_md = (context.path / AGENTS_MD_RELATIVE_PATH).is_file()
    if not has_claude_md and has_agents_md:
        return (
            _D04_HOOK_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    "N/A -- Codex-native (AGENTS.md present, no CLAUDE.md): "
                    "not a Claude Copilot project, so the Claude Code "
                    "enforcement hook this check grades does not apply."
                ),
            ),
        )
    return (check_d04_hook_present_and_locked(context.path, subject=context.subject),)


__all__ = [
    "HOOK_RELATIVE_PATH",
    "check_d04_hook_present_and_locked",
    "run",
]
