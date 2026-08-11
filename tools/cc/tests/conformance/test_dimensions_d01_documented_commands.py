"""Regression tests for `dimensions/d01_claude.py`'s
`repo.d01.documented_commands_exist` check.

**Why this file exists.** The check used to inspect only a repo's own
`.claude/commands/` directory, with no model of the global machine command
search path (`~/.claude/commands/` -- `setup-project.md`, `update-project.md`,
`update-copilot.md`, `setup-copilot.md`, `knowledge-copilot.md`, `setup.md`,
per VERSION.json's `machineCommands`, documented as "work anywhere" in
`docs/01-getting-started/01-user-journey.md`). A genuine reference to one of
those -- e.g. `` `/setup-project` `` inside a project's own CLAUDE.md -- was
reported as a missing command on every one of the 63-repo fleet, because a
machine command is deliberately never copied into a project. The fix teaches
the check the real two-rung resolution (project-local OR machine-global)
without turning it into a check that can never fail -- see
`test_fail_when_reference_resolves_in_neither_location` below, the fixture
proof that a genuinely bogus `` `/command` `` reference still FAILs.

Same two layers of coverage as the file's `test_dimensions_d05_d09.py`
sibling: direct `check_d01_documented_commands_exist(repo, ...)` calls for
precision, and one `TestRunContract` class proving `run(context)` agrees.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.conformance.classes import ClassificationEntry, RepoClass
from cc.core.conformance.dimensions import RepoContext
from cc.core.conformance.dimensions.d01_claude import (
    check_d01_documented_commands_exist,
)
from cc.core.conformance.dimensions.d01_claude import run as run_d01
from cc.core.conformance.types import ExpectedToday, Mode, Verdict

pytestmark = pytest.mark.filterwarnings("ignore")

# The real machineCommands roster (VERSION.json, verified 2026-08-10: 6
# entries, not the 9 an earlier rubric draft claimed) -- fixtures below build
# their own throwaway framework root rather than depending on this
# machine's real `~/.claude/copilot`, so this suite stays hermetic.
_MACHINE_COMMANDS = [
    "setup.md",
    "setup-project.md",
    "update-project.md",
    "update-copilot.md",
    "setup-copilot.md",
    "knowledge-copilot.md",
]


def _write(path: Path, relative: str, content: str) -> Path:
    target = path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _framework_root(tmp_path: Path, *, machine_commands: list[str] | None = None) -> Path:
    """A throwaway framework source directory with just enough of a
    VERSION.json for `_machine_commands()` to resolve -- never the real
    `~/.claude/copilot`."""

    root = tmp_path / "framework-source"
    manifest = {
        "framework": "0.0.0-test",
        "components": {
            "agents": {"frameworkAgents": ["cw"], "retired": []},
            "commands": {
                "projectCommands": ["protocol.md", "continue.md"],
                "machineCommands": (
                    _MACHINE_COMMANDS if machine_commands is None else machine_commands
                ),
            },
        },
    }
    _write(root, "VERSION.json", json.dumps(manifest))
    return root


def _context(repo: Path, *, rubric_class: str = "A") -> RepoContext:
    classification = ClassificationEntry(
        key=repo.name, repo_class=RepoClass.PRODUCT, rationale="test fixture"
    )
    return RepoContext.build(
        repo,
        classification=classification,
        is_git_root=(repo / ".git").exists(),
        mode=Mode.FAST,
    )


class TestD01DocumentedCommandsExist:
    def test_skip_when_no_claude_md(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = check_d01_documented_commands_exist(repo)
        assert result.verdict is Verdict.SKIP

    def test_skip_when_no_command_references(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, "CLAUDE.md", "# CLAUDE.md\n\nNo slash commands mentioned here.\n")
        result = check_d01_documented_commands_exist(repo)
        assert result.verdict is Verdict.SKIP

    def test_pass_when_reference_is_a_project_local_command(self, tmp_path):
        """The common case never needs a framework root at all -- resolved
        entirely from the repo's own `.claude/commands/`."""

        repo = tmp_path / "repo"
        _write(repo, "CLAUDE.md", "Run `/protocol` to start working.\n")
        _write(repo, ".claude/commands/protocol.md", "# Protocol\n")
        result = check_d01_documented_commands_exist(repo, claude_root="/nonexistent-unused")
        assert result.verdict is Verdict.PASS

    def test_pass_when_reference_is_a_machine_command_not_installed_locally(self, tmp_path):
        """The regression fixture: `/setup-project` and `/knowledge-copilot`
        are genuine machine commands (VERSION.json's `machineCommands`,
        `~/.claude/commands/` -- never copied into a project) and must PASS
        even though `.claude/commands/` has neither file on disk."""

        repo = tmp_path / "repo"
        _write(
            repo,
            "CLAUDE.md",
            "Run `/setup-project` for a new project or `/knowledge-copilot` "
            "to configure shared knowledge -- both work anywhere.\n",
        )
        framework_root = _framework_root(tmp_path)
        result = check_d01_documented_commands_exist(repo, claude_root=framework_root)
        assert result.verdict is Verdict.PASS
        assert "machineCommands" in result.detail or "machine command" in result.detail

    def test_fail_when_reference_resolves_in_neither_location(self, tmp_path):
        """Proof the fix did not turn this into a check that can never
        fail (the exact defect found in `check_h6_declared_skill_paths_exist`):
        a genuinely bogus `` `/command` `` reference still FAILs."""

        repo = tmp_path / "repo"
        _write(repo, "CLAUDE.md", "Run `/totally-bogus-command` to do the thing.\n")
        framework_root = _framework_root(tmp_path)
        result = check_d01_documented_commands_exist(repo, claude_root=framework_root)
        assert result.verdict is Verdict.FAIL
        assert result.evidence
        assert result.evidence[0].path == ".claude/commands/totally-bogus-command.md"
        assert "totally-bogus-command" in result.detail

    def test_fail_mixes_real_and_bogus_references_correctly(self, tmp_path):
        """A project command, a machine command, and a bogus command in the
        same CLAUDE.md: only the bogus one is reported missing."""

        repo = tmp_path / "repo"
        _write(
            repo,
            "CLAUDE.md",
            "Use `/protocol` daily. `/setup-project` sets up a new repo. "
            "`/nonexistent-thing` is not real.\n",
        )
        _write(repo, ".claude/commands/protocol.md", "# Protocol\n")
        framework_root = _framework_root(tmp_path)
        result = check_d01_documented_commands_exist(repo, claude_root=framework_root)
        assert result.verdict is Verdict.FAIL
        missing = {entry.path for entry in result.evidence}
        assert missing == {".claude/commands/nonexistent-thing.md"}

    def test_could_not_run_when_framework_root_unresolved(self, tmp_path):
        """An unresolved reference with no usable framework root is
        `COULD_NOT_RUN` (a harness precondition failure), never a fabricated
        PASS or FAIL -- matches every sibling D1 check's own pattern."""

        repo = tmp_path / "repo"
        _write(repo, "CLAUDE.md", "Run `/setup-project` first.\n")
        result = check_d01_documented_commands_exist(
            repo, claude_root=tmp_path / "does-not-exist"
        )
        assert result.verdict is Verdict.COULD_NOT_RUN

    def test_could_not_run_on_unreadable_manifest(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, "CLAUDE.md", "Run `/setup-project` first.\n")
        framework_root = tmp_path / "framework-source"
        _write(framework_root, "VERSION.json", "{not valid json")
        result = check_d01_documented_commands_exist(repo, claude_root=framework_root)
        assert result.verdict is Verdict.COULD_NOT_RUN


class TestRunContract:
    def test_run_skips_class_e_explicitly(self, tmp_path):
        repo = tmp_path / "scratch-dir"
        repo.mkdir()
        context = RepoContext.build(
            repo,
            classification=ClassificationEntry(
                key=repo.name,
                repo_class=RepoClass.SCRATCH_ARCHIVE,
                rationale="test fixture",
            ),
            is_git_root=False,
            mode=Mode.FAST,
        )
        results = tuple(run_d01(context))
        matching = [r for r in results if r.id == "repo.d01.documented_commands_exist"]
        assert len(matching) == 1
        assert matching[0].verdict is Verdict.SKIP

    def test_run_passes_for_a_project_local_reference(self, tmp_path):
        repo = tmp_path / "repo"
        _write(repo, "CLAUDE.md", "Run `/protocol` to start working.\n")
        _write(repo, ".claude/commands/protocol.md", "# Protocol\n")
        context = _context(repo, rubric_class="A")
        results = tuple(run_d01(context))
        matching = [r for r in results if r.id == "repo.d01.documented_commands_exist"]
        assert len(matching) == 1
        assert matching[0].verdict is Verdict.PASS
        assert matching[0].expected_today is ExpectedToday.PASS
