"""D6 — Memory (`.claude/memory/`).

`RUBRIC.md` §D6 / `HARNESS-DESIGN.md` §4 Layer 3 (`repo.d06.memory_entries_committed_db_ignored`,
S2, fast, applies to classes A/B/C/D — not E):

  PRESENT — `.claude/memory/entries/` exists (with `.gitkeep`) AND
  `memory.db`/`memory.db-*` are Git-ignored, not tracked. Content in
  `entries/` is committed; the SQLite index is not.
  PARTIAL — entries directory exists but `memory.db` is tracked, or the
  directory exists with no ignore rule.
  ABSENT — no `.claude/memory/entries/`.

The live failure this module exists to catch is worse than "no ignore
rule": a `.gitignore` rule that ignores too MUCH. `force-readiness-
assessment`'s `.gitignore:19` reads `.claude/memory/` (not
`.claude/memory/memory.db`), which — traced to the consumer, i.e. what
`git ls-files` actually reports as tracked, not what the rule's comment
above it claims — silently drops every entry under `entries/` from version
control, not merely the SQLite index the rule was written to exclude
(verified live on this machine, 2026-08-10: 62 entries on disk, only 12
tracked). `PERSONAL/thoughts` is the same root cause one level up: the
whole `.claude/` tree is gitignored, so nothing in `entries/` is ever
committed at all. This module's compound check therefore verifies BOTH
halves independently — `memory.db*` untracked, AND every on-disk entry
file tracked — because a repo can satisfy one while silently failing the
other, and RUBRIC.md's "no ignore rule" framing alone would miss the
force-readiness-assessment shape entirely (it DOES have an ignore rule;
the rule is simply too broad).

Real repos are read-only: all git access (`ls-files`, `check-ignore`) goes
through `fsguard.run_git_readonly`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable

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

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

MEMORY_DIR_RELATIVE_PATH = ".claude/memory"
ENTRIES_DIR_RELATIVE_PATH = ".claude/memory/entries"

# RUBRIC.md D6: "Applies to: A, B, C, D." -- not E.
_APPLIES_TO = ("A", "B", "C", "D")

_D06_REGISTRATION = register_check(
    id="repo.d06.memory_entries_committed_db_ignored",
    layer=Layer.REPO,
    severity=Severity.S2,
    scope=Scope.PER_REPO,
    summary=(
        "`.claude/memory/entries/` exists; every on-disk entry file is "
        "tracked in git; `memory.db`/`memory.db-*` are ignored and never "
        "tracked."
    ),
    remediation=(
        "Create `.claude/memory/entries/` (with `.gitkeep`); scope any "
        "`.gitignore` rule to `.claude/memory/memory.db*` specifically — "
        "never the whole `.claude/memory/` tree — and `git add` every "
        "existing entry under `entries/` so no memory is silently "
        "local-only."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _sample(paths: list[str], limit: int = 5) -> str:
    shown = ", ".join(paths[:limit])
    if len(paths) > limit:
        shown += f", … ({len(paths) - limit} more)"
    return shown


def check_d06_memory_entries_committed_db_ignored(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """Pure function of `repo` to a `CheckResult`. Git access is confined
    to the read-only allowlist (`ls-files`, `check-ignore`)."""

    repo = Path(repo)
    subject_name = subject if subject is not None else str(repo)
    entries_dir = repo / ENTRIES_DIR_RELATIVE_PATH
    evidence: list[Evidence] = []

    if not entries_dir.is_dir():
        evidence.append(
            Evidence(
                kind="memory-entries-missing",
                path=str(entries_dir),
                expected=f"{ENTRIES_DIR_RELATIVE_PATH}/ present",
                actual="missing",
                detail="RUBRIC.md D6 ABSENT.",
            )
        )
        return _D06_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.FAIL,
            evidence=tuple(evidence),
            detail="`.claude/memory/entries/` is absent.",
            expected_today=expected_today,
        )

    is_git_repo = (repo / ".git").exists()
    if not is_git_repo:
        # D6 applies only to classes A/B/C/D, which are all Git roots by
        # the class-assignment rule (`RUBRIC.md` §1) — this branch is a
        # defensive guard, not an expected production path. Trackedness
        # cannot be determined outside a git repo, so the harness must say
        # so rather than fabricate a verdict (`inv.no_fabricated_healthy`).
        return _D06_REGISTRATION.result(
            subject=subject_name,
            verdict=Verdict.COULD_NOT_RUN,
            detail=f"{repo} has no `.git` — trackedness cannot be determined.",
            expected_today=expected_today,
        )

    memory_dir = repo / MEMORY_DIR_RELATIVE_PATH
    db_candidates = sorted(memory_dir.glob("memory.db*"))
    for db_path in db_candidates:
        relative = db_path.relative_to(repo).as_posix()
        tracked = run_git_readonly(("ls-files", relative), cwd=repo)
        if tracked.stdout.strip():
            evidence.append(
                Evidence(
                    kind="memory-db-tracked",
                    path=str(db_path),
                    expected=f"{relative} ignored and untracked",
                    actual="tracked in git",
                    detail="the SQLite index must never be committed.",
                    command=f"git ls-files {relative}",
                    output=tracked.stdout.strip(),
                )
            )

    on_disk_entries = sorted(
        path.relative_to(repo).as_posix()
        for path in entries_dir.iterdir()
        if path.is_file()
    )
    tracked_result = run_git_readonly(
        ("ls-files", ENTRIES_DIR_RELATIVE_PATH), cwd=repo
    )
    tracked_entries = {
        line.strip() for line in tracked_result.stdout.splitlines() if line.strip()
    }
    untracked_entries = [
        entry for entry in on_disk_entries if entry not in tracked_entries
    ]

    if untracked_entries:
        offending_rule = run_git_readonly(
            ("check-ignore", "-v", untracked_entries[0]), cwd=repo
        )
        evidence.append(
            Evidence(
                kind="memory-entries-excluded",
                path=str(entries_dir),
                expected="every on-disk entry file tracked in git",
                actual=(
                    f"{len(untracked_entries)} of {len(on_disk_entries)} "
                    "on-disk entries are NOT tracked"
                ),
                detail=(
                    "silently local-only: "
                    f"{_sample(untracked_entries)}. Offending rule (sample): "
                    f"{offending_rule.stdout.strip() or '<no matching .gitignore rule found>'}"
                ),
                command=f"comm -23 <(ls {ENTRIES_DIR_RELATIVE_PATH}) <(git ls-files {ENTRIES_DIR_RELATIVE_PATH})",
            )
        )

    verdict = Verdict.FAIL if evidence else Verdict.PASS
    detail = (
        ""
        if verdict is Verdict.PASS
        else f"{len(evidence)} violation(s) of the memory-commit contract."
    )
    return _D06_REGISTRATION.result(
        subject=subject_name,
        verdict=verdict,
        evidence=tuple(evidence),
        detail=detail,
        expected_today=expected_today,
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: exactly one `CheckResult` for `repo.d06.memory_entries_
    committed_db_ignored`, for every repo (`Verdict.SKIP` for class E)."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _D06_REGISTRATION.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D6 applies to "
                    "classes A/B/C/D, not E."
                ),
            ),
        )
    return (
        check_d06_memory_entries_committed_db_ignored(
            context.path, subject=context.subject
        ),
    )


__all__ = [
    "ENTRIES_DIR_RELATIVE_PATH",
    "MEMORY_DIR_RELATIVE_PATH",
    "check_d06_memory_entries_committed_db_ignored",
    "run",
]
