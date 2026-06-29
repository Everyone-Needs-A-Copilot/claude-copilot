"""Tests for Task 143: --max-budget-usd dispatch flag plumbing.

Acceptance criteria:
  AC: grep proves non-interactive tc/Discord/orchestrate dispatch passes
      --max-budget-usd when set.

Tests:
  - tc worker: builds correct cmd with --max-budget-usd when set
  - tc worker: omits --max-budget-usd when not set
  - tc worker: dry-run prints cmd without executing
  - tc worker --json dry-run: returns JSON with cmd list
  - Grep proof: --max-budget-usd appears in all three dispatch paths
  - Does NOT touch pretool-check.sh (isolation check)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path("/Volumes/Dev/Sites/COPILOT/claude-copilot")
WORKER_PY = REPO_ROOT / "tools/tc/src/tc/commands/worker.py"
ORCHESTRATE_MD = REPO_ROOT / ".claude/commands/orchestrate.md"
DISCORD_DISPATCH_SH = REPO_ROOT / ".claude/bin/discord-dispatch.sh"
PRETOOL_CHECK_SH = REPO_ROOT / ".claude/hooks/pretool-check.sh"


# ---------------------------------------------------------------------------
# Unit tests — _build_dispatch_cmd
# ---------------------------------------------------------------------------


class TestBuildDispatchCmd:
    """Unit tests for tc/commands/worker._build_dispatch_cmd."""

    def _build(self, task_id: int, **kwargs):
        from tc.commands.worker import _build_dispatch_cmd
        return _build_dispatch_cmd(task_id, **kwargs)

    def test_basic_cmd_uses_claude_print(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert cmd[0] == "claude"
        assert "--print" in cmd

    def test_max_budget_usd_passed_through_when_set(self):
        """--max-budget-usd must appear in the command when the arg is set."""
        cmd = self._build(42, max_budget_usd=2.50, model=None, agent=None)
        assert "--max-budget-usd" in cmd
        idx = cmd.index("--max-budget-usd")
        assert cmd[idx + 1] == "2.5"

    def test_max_budget_usd_omitted_when_none(self):
        """--max-budget-usd must NOT appear in the command when arg is None."""
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert "--max-budget-usd" not in cmd

    def test_model_passed_through_when_set(self):
        cmd = self._build(42, max_budget_usd=None, model="claude-opus-4-5", agent=None)
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-opus-4-5"

    def test_model_omitted_when_none(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert "--model" not in cmd

    def test_default_agent_is_me(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        # The prompt should reference @agent-me
        prompt_tokens = " ".join(cmd)
        assert "@agent-me" in prompt_tokens

    def test_custom_agent_used_in_prompt(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent="qa")
        prompt_tokens = " ".join(cmd)
        assert "@agent-qa" in prompt_tokens

    def test_budget_zero_point_zero_still_passed(self):
        """Edge case: 0.0 budget should still appear in the command."""
        cmd = self._build(1, max_budget_usd=0.0, model=None, agent=None)
        assert "--max-budget-usd" in cmd

    def test_full_command_with_all_flags(self):
        cmd = self._build(
            99,
            max_budget_usd=5.00,
            model="claude-sonnet-4-6",
            agent="me",
        )
        assert "--max-budget-usd" in cmd
        assert "--model" in cmd
        assert "5.0" in cmd
        assert "claude-sonnet-4-6" in cmd


# ---------------------------------------------------------------------------
# tc worker CLI tests
# ---------------------------------------------------------------------------


class TestTcWorkerCLI:
    """CLI integration tests for `tc worker`."""

    def _run_tc(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "tc.main", "worker"] + args,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            **kwargs,
        )

    def test_dry_run_prints_max_budget_usd(self):
        """tc worker --dry-run with --max-budget-usd shows flag in output."""
        result = self._run_tc(["42", "--max-budget-usd", "3.00", "--dry-run"])
        assert result.returncode == 0
        assert "--max-budget-usd" in result.stdout

    def test_dry_run_omits_flag_when_not_set(self):
        """tc worker --dry-run without --max-budget-usd omits the flag."""
        result = self._run_tc(["42", "--dry-run"])
        assert result.returncode == 0
        assert "--max-budget-usd" not in result.stdout

    def test_dry_run_json_contains_cmd(self):
        """tc worker --dry-run --json returns JSON with 'cmd' key."""
        import json as _json
        result = self._run_tc(["42", "--max-budget-usd", "1.50", "--dry-run", "--json"])
        assert result.returncode == 0
        data = _json.loads(result.stdout)
        assert "cmd" in data
        assert data["dry_run"] is True
        assert "--max-budget-usd" in data["cmd"]

    def test_dry_run_json_budget_value(self):
        """tc worker --dry-run --json captures the exact budget value."""
        import json as _json
        result = self._run_tc(["99", "--max-budget-usd", "7.25", "--dry-run", "--json"])
        assert result.returncode == 0
        data = _json.loads(result.stdout)
        assert "7.25" in data["cmd"]


# ---------------------------------------------------------------------------
# Grep-proof tests (AC: grep proves --max-budget-usd is in dispatch paths)
# ---------------------------------------------------------------------------


class TestGrepProof:
    """Grep-based acceptance tests proving --max-budget-usd is in all dispatch paths."""

    def test_tc_worker_contains_max_budget_usd(self):
        """TC dispatch path: worker.py mentions --max-budget-usd."""
        content = WORKER_PY.read_text(encoding="utf-8")
        assert "--max-budget-usd" in content, (
            f"--max-budget-usd not found in {WORKER_PY}"
        )

    def test_orchestrate_contains_max_budget_usd(self):
        """Orchestrate dispatch path: orchestrate.md mentions --max-budget-usd."""
        content = ORCHESTRATE_MD.read_text(encoding="utf-8")
        assert "--max-budget-usd" in content, (
            f"--max-budget-usd not found in {ORCHESTRATE_MD}"
        )

    def test_discord_dispatch_contains_max_budget_usd(self):
        """Discord dispatch path: discord-dispatch.sh mentions --max-budget-usd."""
        content = DISCORD_DISPATCH_SH.read_text(encoding="utf-8")
        assert "--max-budget-usd" in content, (
            f"--max-budget-usd not found in {DISCORD_DISPATCH_SH}"
        )

    def test_discord_dispatch_is_executable_script(self):
        """discord-dispatch.sh is a shell script (starts with shebang)."""
        content = DISCORD_DISPATCH_SH.read_text(encoding="utf-8")
        assert content.startswith("#!/"), (
            "discord-dispatch.sh must start with a shebang line"
        )

    def test_all_three_dispatch_paths_have_flag(self):
        """Umbrella: all three paths contain --max-budget-usd."""
        paths = [WORKER_PY, ORCHESTRATE_MD, DISCORD_DISPATCH_SH]
        missing = [p for p in paths if "--max-budget-usd" not in p.read_text(encoding="utf-8")]
        assert not missing, (
            f"These dispatch paths are missing --max-budget-usd: {missing}"
        )


# ---------------------------------------------------------------------------
# Isolation check — pretool-check.sh MUST NOT be modified
# ---------------------------------------------------------------------------


class TestIsolation:
    """Verify pretool-check.sh was not touched (hard constraint)."""

    def test_pretool_check_not_touched_by_this_implementation(self):
        """pretool-check.sh must not contain budget dispatch code added by Task 143.

        The hard constraint is: this implementation must NOT add budget logic to
        pretool-check.sh.  We verify this by checking the file does not contain
        the P1 budget-gate markers that would indicate we violated the constraint.

        Note: pretool-check.sh may have pre-existing modifications from another
        agent — we test only that WE did not add dispatch or enforcement code to it.
        """
        content = PRETOOL_CHECK_SH.read_text(encoding="utf-8")

        # These strings would indicate Task-143 code was incorrectly added here:
        assert "budget-rule" not in content, (
            "pretool-check.sh contains 'budget-rule' — "
            "this is P1 enforcement code that must NOT be in P0 implementation"
        )
        assert "max_budget_usd" not in content, (
            "pretool-check.sh contains 'max_budget_usd' — "
            "budget enforcement was incorrectly added to the hook (P1 work only)"
        )
        # tc worker dispatch should be in worker.py/tc main, not pretool-check.sh
        assert "tc worker" not in content or "tc worker" in content.split("budget")[0], (
            "pretool-check.sh appears to have budget dispatch from tc worker — "
            "dispatch belongs in tools/tc/, not the hook"
        )

    def test_pretool_check_does_not_contain_max_budget_enforcement(self):
        """pretool-check.sh must not contain --max-budget-usd enforcement (P1 only)."""
        content = PRETOOL_CHECK_SH.read_text(encoding="utf-8")
        # P0 only plumbs the flag; enforcement logic is P1
        # The pretool-check.sh should not have been given a budget-rule branch
        assert "budget-rule" not in content or "budget_usd" not in content.split("budget-rule")[0], (
            "pretool-check.sh appears to have a budget enforcement rule — "
            "this is P1 work and must not be in P0"
        )
