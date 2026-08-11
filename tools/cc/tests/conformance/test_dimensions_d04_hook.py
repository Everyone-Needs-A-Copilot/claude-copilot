"""Tests for `dimensions/d04_hook.py` (`repo.d04.hook_present_and_locked`).

No dedicated test module existed for D4 before this one -- added alongside
the fix that gave `run()` a second applicability gate (a Codex-native repo,
`AGENTS.md` present and no `CLAUDE.md`, is not a Claude Copilot project at
all, so the Claude Code enforcement hook this check grades does not apply
to it -- confirmed live against `codex-copilot`, verified against every
other `codex-*` tier variant on the machine which DO carry `CLAUDE.md` and
are correctly still graded). Follows this package's own "every check gets
a POSITIVE test and at least one NEGATIVE test" convention
(`test_dimensions_d05_d09.py`'s module docstring).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.conformance.classes import ClassificationEntry, RepoClass
from cc.core.conformance.dimensions import RepoContext
from cc.core.conformance.dimensions.d04_hook import (
    check_d04_hook_present_and_locked,
)
from cc.core.conformance.dimensions.d04_hook import run as run_d04
from cc.core.conformance.types import Mode, Verdict

pytestmark = pytest.mark.filterwarnings("ignore")


def _context(repo: Path, *, rubric_class: str) -> RepoContext:
    if rubric_class == "E":
        classification = ClassificationEntry(
            key=repo.name, repo_class=RepoClass.SCRATCH_ARCHIVE, rationale="test fixture"
        )
    else:
        classification = ClassificationEntry(
            key=repo.name, repo_class=RepoClass.PRODUCT, rationale="test fixture"
        )
    assert classification.rubric_letter == rubric_class
    return RepoContext.build(
        repo, classification=classification, is_git_root=(repo / ".git").exists(), mode=Mode.FAST
    )


class TestCheckD04HookPresentAndLocked:
    def test_fail_when_hook_missing(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = check_d04_hook_present_and_locked(repo, subject=str(repo))
        assert result.verdict is Verdict.FAIL
        assert any(e.kind == "hook-missing" for e in result.evidence)

    def test_fail_when_present_but_not_locked(self, tmp_path):
        repo = tmp_path / "repo"
        hook = repo / ".claude" / "hooks" / "copilot-hook.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\necho hook\n", encoding="utf-8")
        hook.chmod(0o755)
        result = check_d04_hook_present_and_locked(repo, subject=str(repo))
        assert result.verdict is Verdict.FAIL
        assert any(e.kind == "hook-not-locked" for e in result.evidence)

    def test_fail_when_present_but_not_executable(self, tmp_path):
        repo = tmp_path / "repo"
        hook = repo / ".claude" / "hooks" / "copilot-hook.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\necho hook\n", encoding="utf-8")
        hook.chmod(0o644)
        result = check_d04_hook_present_and_locked(repo, subject=str(repo))
        assert result.verdict is Verdict.FAIL
        assert any(e.kind == "hook-not-executable" for e in result.evidence)


class TestRunContract:
    def test_skip_for_class_e(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        context = _context(repo, rubric_class="E")
        (results,) = tuple(run_d04(context))
        assert results.verdict is Verdict.SKIP
        assert "class E" in results.detail

    def test_skip_for_codex_native_repo_with_no_claude_md(self, tmp_path):
        """The confirmed live case: `AGENTS.md` present, no `CLAUDE.md` --
        a directory that never declared itself a Claude Copilot project
        cannot be missing a Claude Code artifact."""

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "AGENTS.md").write_text("## Codex Copilot\n", encoding="utf-8")
        context = _context(repo, rubric_class="C")
        (result,) = tuple(run_d04(context))
        assert result.verdict is Verdict.SKIP
        assert "Codex-native" in result.detail

    def test_still_grades_dual_stack_repo_with_claude_md_and_agents_md(self, tmp_path):
        """A repo carrying BOTH files is unaffected by the new gate and is
        graded normally -- confirmed live against every `codex-*` tier
        variant except the `codex-copilot` foundation itself."""

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text("# CLAUDE.md\n", encoding="utf-8")
        (repo / "AGENTS.md").write_text("## Codex Copilot\n", encoding="utf-8")
        context = _context(repo, rubric_class="C")
        (result,) = tuple(run_d04(context))
        # No hook installed in this fixture -- the check still RUNS (and
        # correctly fails), it is just no longer skipped as inapplicable.
        assert result.verdict is Verdict.FAIL
        assert result.id == "repo.d04.hook_present_and_locked"

    def test_still_grades_ordinary_claude_only_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "CLAUDE.md").write_text("# CLAUDE.md\n", encoding="utf-8")
        context = _context(repo, rubric_class="C")
        (result,) = tuple(run_d04(context))
        assert result.verdict is Verdict.FAIL
        assert any(e.kind == "hook-missing" for e in result.evidence)

    def test_still_fails_absent_project_with_neither_file(self, tmp_path):
        """A repo with neither `CLAUDE.md` nor `AGENTS.md` is not covered
        by the new Codex-native gate (that gate requires `AGENTS.md`
        present) -- it keeps failing D4 exactly as before, an ordinary
        never-onboarded project, not an inapplicable one."""

        repo = tmp_path / "repo"
        repo.mkdir()
        context = _context(repo, rubric_class="C")
        (result,) = tuple(run_d04(context))
        assert result.verdict is Verdict.FAIL
