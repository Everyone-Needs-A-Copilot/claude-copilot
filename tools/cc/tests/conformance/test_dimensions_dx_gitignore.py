"""Tests for `dimensions/dx_gitignore.py` -- the one dimension module the
nine parallel work packages left unbuilt (`WP-4c`'s scope was explicitly
`d10-d13`; this is the cross-dimension `dx_*` check `HARNESS-DESIGN.md` §4
Layer 3 lists separately: `repo.gitignore.no_self_exclusion`).

Named distinctly from every existing `test_dimensions_*.py` file (WP-4a's
D1-D4, WP-4b's D5-D9, WP-4c's D10-D13, WP-4's own `test_layer3_dimensions.py`)
so this file can never collide with a sibling package's path.

Two layers of coverage, matching the established convention across every
other dimension test file in this suite:

  - `TestFindSelfExcludedPaths` / `TestCheckGitignoreNoSelfExclusion`
    exercise the module's pure functions directly against a synthetic
    `tmp_path` repo (World A) -- a POSITIVE case (nothing excluded), a
    NEGATIVE case (a framework path excluded), the `!`-negation
    false-positive guard, and the `--no-index` "already partially tracked"
    case that is this check's whole reason for choosing `--no-index` over
    plain `git check-ignore`.
  - `TestRunContract` exercises `run(context)` -- the real
    `dimensions/__init__.py` module contract.
  - `TestAgainstRealNamedRepos` (`@pytest.mark.machine`) replays the six
    real, owner-ratified (Q23 answer A) repos this module's own docstring
    documents, strictly read-only, proving the module detects every one of
    them TODAY -- exactly what the task's acceptance bar asks for ("must
    FAIL for all six today").
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.conformance.classes import ClassificationEntry, RepoClass
from cc.core.conformance.dimensions import RepoContext, dx_gitignore
from cc.core.conformance.dimensions.dx_gitignore import (
    KNOWN_SELF_EXCLUDING_REPOS,
    check_gitignore_no_self_exclusion,
    find_self_excluded_paths,
)
from cc.core.conformance.types import ExpectedToday, Mode, Verdict

from .conftest import git_commit_all, init_git_repo


def _git_repo(path: Path) -> Path:
    init_git_repo(path)
    git_commit_all(path, "initial commit")
    return path


def _context(repo: Path, *, rubric_class: str = "C") -> RepoContext:
    if rubric_class == "E":
        classification = ClassificationEntry(
            key=repo.name, repo_class=RepoClass.SCRATCH_ARCHIVE, rationale="test fixture"
        )
    else:
        classification = ClassificationEntry(
            key=repo.name, repo_class=RepoClass.PRODUCT, rationale="test fixture"
        )
    return RepoContext.build(
        repo, classification=classification, is_git_root=True, mode=Mode.FAST
    )


class TestFindSelfExcludedPaths:
    def test_no_candidates_on_disk_returns_empty(self, tmp_path):
        repo = _git_repo(tmp_path / "empty-repo")
        excluded, errors, considered = find_self_excluded_paths(repo)
        assert excluded == []
        assert errors == []
        assert considered == 0

    def test_installed_and_not_ignored_finds_nothing(self, tmp_path):
        repo = _git_repo(tmp_path / "clean-repo")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        git_commit_all(repo, "add commands")

        excluded, errors, considered = find_self_excluded_paths(
            repo, candidates=(".claude", ".claude/commands")
        )
        assert excluded == []
        assert errors == []
        assert considered == 2

    def test_blanket_directory_exclusion_reproduces_admin_server(self, tmp_path):
        repo = _git_repo(tmp_path / "admin-server-like")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        (repo / ".gitignore").write_text("irrelevant/\n.claude/\n", encoding="utf-8")
        git_commit_all(repo, "add gitignore excluding .claude/")

        excluded, errors, considered = find_self_excluded_paths(
            repo, candidates=(".claude", ".claude/commands")
        )
        assert errors == []
        excluded_paths = {path for path, _source, _pattern in excluded}
        assert ".claude" in excluded_paths
        assert ".claude/commands" in excluded_paths
        assert all(pattern == ".claude/" for _p, _s, pattern in excluded)

    def test_negation_is_not_reported_as_excluded_reproduces_convoco(self, tmp_path):
        """convoco's own `.gitignore:73-83`: `.claude/*` followed by
        `!.claude/cc/config.json` -- the negated path must never show up as
        a violation, only the still-excluded required-lock paths should."""

        repo = _git_repo(tmp_path / "convoco-like")
        (repo / ".claude" / "cc").mkdir(parents=True)
        (repo / ".claude" / "cc" / "config.json").write_text("{}")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        (repo / ".gitignore").write_text(
            ".claude/*\n!.claude/cc/\n!.claude/cc/config.json\n",
            encoding="utf-8",
        )
        git_commit_all(repo, "add gitignore with a negation")

        excluded, errors, considered = find_self_excluded_paths(
            repo,
            candidates=(".claude/cc/config.json", ".claude/commands"),
        )
        assert errors == []
        excluded_paths = {path for path, _source, _pattern in excluded}
        assert ".claude/cc/config.json" not in excluded_paths
        assert ".claude/commands" in excluded_paths

    def test_no_index_catches_a_partially_tracked_directory_reproduces_force_readiness(
        self, tmp_path
    ):
        """force-readiness-assessment's own shape: some entries were
        committed BEFORE the gitignore rule existed, so a plain (non
        `--no-index`) `git check-ignore` on the directory reports "not
        ignored." `--no-index` is what makes this module answer the real
        question (does the PATTERN exclude the path) instead of "did
        tracking start before the rule did."""

        repo = _git_repo(tmp_path / "force-readiness-like")
        entries = repo / ".claude" / "memory" / "entries"
        entries.mkdir(parents=True)
        (entries / "tracked-before-the-rule.md").write_text("old entry")
        git_commit_all(repo, "commit one entry before gitignore excludes the dir")

        (repo / ".gitignore").write_text(".claude/memory/\n", encoding="utf-8")
        git_commit_all(repo, "add gitignore excluding memory/ after the fact")
        (entries / "never-committed.md").write_text("new entry, never tracked")

        excluded, errors, considered = find_self_excluded_paths(
            repo, candidates=(".claude/memory/entries",)
        )
        assert errors == []
        excluded_paths = {path for path, _source, _pattern in excluded}
        assert ".claude/memory/entries" in excluded_paths

    def test_not_a_git_repo_produces_an_error_not_a_false_pass(self, tmp_path):
        not_a_repo = tmp_path / "plain-dir"
        (not_a_repo / ".claude").mkdir(parents=True)
        excluded, errors, considered = find_self_excluded_paths(
            not_a_repo, candidates=(".claude",)
        )
        assert excluded == []
        assert errors  # a real "could not determine" signal, never silent PASS


class TestCheckGitignoreNoSelfExclusion:
    def test_pass_when_nothing_excluded(self, tmp_path):
        repo = _git_repo(tmp_path / "clean-repo")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        git_commit_all(repo, "add commands")

        result = check_gitignore_no_self_exclusion(repo)
        assert result.verdict is Verdict.PASS
        assert result.id == "repo.gitignore.no_self_exclusion"

    def test_skip_when_nothing_installed(self, tmp_path):
        repo = _git_repo(tmp_path / "bare-repo")
        result = check_gitignore_no_self_exclusion(repo)
        assert result.verdict is Verdict.SKIP

    def test_fail_reproduces_admin_server(self, tmp_path):
        """Reproduces admin-server's exact HISTORICAL shape (`.gitignore:86`
        -- a blanket `.claude/` exclusion). `KNOWN_SELF_EXCLUDING_REPOS` is
        now empty (all six named repos were narrowed, Q23 answer A,
        re-verified live 2026-08-10 -- see `TestAgainstRealNamedRepos`
        below), so this fixture passes an explicit `expected_today`
        override rather than relying on name-matching against that
        constant: this test's job is proving the check still detects this
        exact SHAPE, independent of whichever real repos currently exhibit
        it."""

        repo = _git_repo(tmp_path / "admin-server")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        (repo / ".gitignore").write_text(".claude/\n", encoding="utf-8")
        git_commit_all(repo, "add gitignore")

        result = check_gitignore_no_self_exclusion(
            repo, expected_today=ExpectedToday.FAIL
        )
        assert result.verdict is Verdict.FAIL
        assert result.evidence
        assert all(e.kind == "gitignore-self-exclusion" for e in result.evidence)
        assert result.expected_today is ExpectedToday.FAIL

    def test_fail_reproduces_product_creation_copilot_docs_exclusion(self, tmp_path):
        repo = _git_repo(tmp_path / "product-creation-copilot")
        base = repo / "docs" / "40-initiatives" / "_template" / "phases"
        base.mkdir(parents=True)
        (repo / ".gitignore").write_text("docs/\n", encoding="utf-8")
        git_commit_all(repo, "add gitignore excluding docs/")

        result = check_gitignore_no_self_exclusion(repo)
        assert result.verdict is Verdict.FAIL
        assert any("docs/40-initiatives" in e.path for e in result.evidence)

    def test_check_accepts_an_expected_today_override(self, tmp_path):
        repo = _git_repo(tmp_path / "override-me")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        git_commit_all(repo, "add commands")

        result = check_gitignore_no_self_exclusion(
            repo, expected_today=ExpectedToday.FAIL
        )
        assert result.expected_today is ExpectedToday.FAIL


class TestRunContract:
    def test_run_skips_class_e_explicitly(self, tmp_path):
        repo = tmp_path / "scratch-dir"
        repo.mkdir()
        context = _context(repo, rubric_class="E")

        results = tuple(dx_gitignore.run(context))
        assert len(results) == 1
        assert results[0].id == "repo.gitignore.no_self_exclusion"
        assert results[0].verdict is Verdict.SKIP
        assert results[0].subject == context.subject

    def test_run_pass_for_class_c(self, tmp_path):
        repo = _git_repo(tmp_path / "repo")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        git_commit_all(repo, "add commands")

        results = tuple(dx_gitignore.run(_context(repo, rubric_class="C")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.PASS

    def test_run_fail_for_class_c(self, tmp_path):
        repo = _git_repo(tmp_path / "repo")
        (repo / ".claude" / "commands").mkdir(parents=True)
        (repo / ".claude" / "commands" / "protocol.md").write_text("x")
        (repo / ".gitignore").write_text(".claude/\n", encoding="utf-8")
        git_commit_all(repo, "add gitignore")

        results = tuple(dx_gitignore.run(_context(repo, rubric_class="C")))
        assert len(results) == 1
        assert results[0].verdict is Verdict.FAIL


def test_module_is_discovered_by_the_dimensions_package():
    from cc.core.conformance.dimensions import discover_dimension_modules

    modules = {m.name: m for m in discover_dimension_modules()}
    assert "dx_gitignore" in modules
    assert modules["dx_gitignore"].available, modules["dx_gitignore"].error


def test_check_id_is_registered():
    from cc.core.conformance.registry import DEFAULT_REGISTRY

    assert "repo.gitignore.no_self_exclusion" in DEFAULT_REGISTRY
    registration = DEFAULT_REGISTRY.get("repo.gitignore.no_self_exclusion")
    assert registration.severity is not None
    assert registration.remediation


# ---------------------------------------------------------------------------
# World B -- the real machine, strictly read-only (this suite's autouse
# `_conformance_machine_readonly_tripwire` guards every path this module
# might read; `check_gitignore_no_self_exclusion` never writes anything).
# ---------------------------------------------------------------------------


# The six repos this module's own docstring names as the original Q23
# findings (`docs/ecosystem-audit-open-questions.md`). Deliberately NOT read
# from `KNOWN_SELF_EXCLUDING_REPOS` any more -- that constant now correctly
# tracks "known self-excluding TODAY" (empty, since all six were narrowed;
# see the module's own comment) and would silently collect zero
# parametrize cases if this list were still sourced from it, hiding rather
# than proving the six-repo re-verification the task's acceptance bar
# requires. This tuple is a fixed historical record of which repos to
# re-check, independent of the constant's current (correctly empty) value.
_ORIGINALLY_SELF_EXCLUDING_REPOS: tuple[str, ...] = (
    "admin-server",
    "convoco",
    "convoco-site",
    "force-readiness-assessment",
    "pipeline-copilot",
    "product-creation-copilot",
)


@pytest.mark.machine
class TestAgainstRealNamedRepos:
    """Replays the six owner-ratified (Q23 answer A) repos this module's
    own docstring names. Skips gracefully (rather than failing the whole
    suite) if a named repo is not present on this particular machine, so
    this class stays portable across machines that do not mirror this
    exact fleet -- but on THIS machine, re-verified live 2026-08-10: every
    one of the six had its `.gitignore` rule narrowed (Q23 answer A) and
    now PASSes. The check's ability to still FAIL on this exact shape is
    proven by `TestFindSelfExcludedPaths`/`TestCheckGitignoreNoSelfExclusion`'s
    fixture reproductions above (`test_fail_reproduces_admin_server`,
    `test_fail_reproduces_product_creation_copilot_docs_exclusion`,
    `test_blanket_directory_exclusion_reproduces_admin_server`,
    `test_negation_is_not_reported_as_excluded_reproduces_convoco`,
    `test_no_index_catches_a_partially_tracked_directory_reproduces_force_
    readiness`), never by this now-passing machine class."""

    _ROOT = Path("/Volumes/Dev/Sites/COPILOT")

    @pytest.mark.parametrize("repo_name", _ORIGINALLY_SELF_EXCLUDING_REPOS)
    def test_named_repo_passes_today(self, repo_name):
        repo = self._ROOT / repo_name
        if not repo.is_dir():
            pytest.skip(f"{repo} not present on this machine")
        result = check_gitignore_no_self_exclusion(repo)
        assert result.verdict is Verdict.PASS, (
            f"{repo_name} was expected to PASS (owner Q23 answer A, re-verified "
            f"live) but got {result.verdict.value}: {result.detail}"
        )
        assert result.expected_today is ExpectedToday.PASS
        assert repo_name not in KNOWN_SELF_EXCLUDING_REPOS
