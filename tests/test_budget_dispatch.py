"""Tests for Task 143: --max-budget-usd dispatch flag plumbing.

Acceptance criteria:
  AC: grep proves non-interactive tc/orchestrate dispatch passes
      --max-budget-usd when set.

Tests:
  - tc worker: builds correct cmd with --max-budget-usd when set
  - tc worker: omits --max-budget-usd when not set
  - tc worker: dry-run prints cmd without executing
  - tc worker --json dry-run: returns JSON with cmd list
  - Grep proof: --max-budget-usd appears in both dispatch paths
  - Does NOT touch pretool-check.sh (isolation check)
  - Boundary: this framework carries no chat-integration code at all

WAS THREE DISPATCH PATHS, NOW TWO. `.claude/bin/discord-dispatch.sh` was the
third. It has been removed from this repo entirely: the Discord half of
"dispatch some work and tell me how it went" is CLI Copilot's concern, and
now lives there as `copilot discord dispatch`, which runs whatever argv it is
handed and knows nothing about `tc`. That verb's own tests cover the reporting
contract. What remains here is the part that was always this framework's:
`tc worker` and `/orchestrate`, and the budget flag they plumb.

`TestNoChatIntegrationInThisFramework` below is the regression guard for that
boundary -- it is the reason a future "just add a small notify script" cannot
quietly re-couple the framework to a chat provider.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_PY = REPO_ROOT / "tools/tc/src/tc/commands/worker.py"
ORCHESTRATE_MD = REPO_ROOT / ".claude/commands/orchestrate.md"
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
        """Persona selection uses the native --agent flag, not prompt text.

        Was "@agent-me" embedded in the --message prompt; --message is not a
        real claude flag (see tests/test_claude_flag_existence.py under
        tools/tc/tests/), so the persona is now selected via --agent, which
        `claude --help` documents and `.claude/agents/me.md` backs.
        """
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "me"

    def test_custom_agent_used_as_agent_flag(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent="qa")
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "qa"

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
    """Grep-based acceptance tests proving --max-budget-usd is in all dispatch paths.

    NOTE: grep presence alone does not prove a dispatch path is executable --
    that is exactly how the original --message bug shipped with a green suite
    (grep found "--max-budget-usd" in a command that also contained a flag
    that does not exist). The functional check -- every flag these paths
    build actually exists in `claude --help` -- lives in
    tools/tc/tests/test_claude_flag_existence.py. Keep both: this class still
    proves the flag is *mentioned* on both paths.
    """

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

    def test_all_dispatch_paths_have_flag(self):
        """Umbrella: every dispatch path this framework owns carries the flag."""
        paths = [WORKER_PY, ORCHESTRATE_MD]
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



# ---------------------------------------------------------------------------
# Boundary: this framework owns dispatch, not chat delivery.
#
# `.claude/bin/discord-dispatch.sh` used to live here and is gone. It coupled
# an instruction layer to one chat provider's CLI surface, and it is where the
# original defect lived: it built a "claude --print --max-budget-usd $N" string
# and handed it to `copilot discord handoff --harness`, which is a free-text
# thread-routing LABEL and is never executed -- so no process ran and no budget
# cap was ever enforced, while the suite stayed green on a grep.
#
# The reporting half now lives in CLI Copilot as `copilot discord dispatch`,
# which runs whatever argv it is handed and knows nothing about `tc`. This class
# guards the boundary in the only direction this repo can guard: that no chat
# integration comes back in here.
# ---------------------------------------------------------------------------

CHAT_PROVIDERS = ("discord", "slack", "telegram")

# Places a chat integration would actually have to live to run: shipped scripts,
# hooks, commands, and the two CLIs. Excludes docs, CHANGELOG and this test file,
# where naming a provider is history or explanation rather than a dependency.
_EXECUTABLE_TREES = (
    ".claude/bin",
    ".claude/hooks",
    ".claude/commands",
    "tools/tc/src",
    "tools/cc/src",
)

# NAMING A PROVIDER IS ALLOWED. CALLING ONE IS NOT.
#
# The first version of this guard matched the bare provider name anywhere in the
# tree and failed on two files that are entirely legitimate:
# `content_guard.py` carries a `slack-token` redaction pattern (`xox[baprs]-`),
# which is a secret-leak defence, and `cc connections`' docstring names the
# `discord` service's `DISCORD_BOT_TOKEN` as its worked example of a
# keychain-hinted secret -- `cc` reads CLI Copilot's declared service roster,
# which is the correct direction of that dependency.
#
# A blunter guard than the rule it enforces is worse than no guard: it fails on
# correct code, gets an exclusion bolted on, and then means nothing. So this
# matches invocation shapes only -- shelling out to a provider verb, or an API
# or webhook host. Those are what create the coupling.
_INVOCATION_PATTERNS = (
    r"copilot\s+{provider}\b",          # shelling out to CLI Copilot's provider verb
    r"{provider}\s*(?:handoff|notify|send|post)\b",
    r"https?://[\w.-]*{provider}[\w.-]*\.(?:com|net|org)",
    r"{provider}\.(?:com|net|org)/api",
    r"webhooks?/{provider}",
)


def _code_only(path: Path) -> str:
    """File text with comments and docstrings stripped.

    The point of the boundary is that a provider may be *discussed* in this repo
    (history, rationale, the reason a script was removed) and never *called*. A
    check that cannot tell prose from code cannot express that, so strip prose.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if path.suffix == ".py":
        import ast

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    text = text.replace(doc, "")
        return "\n".join(
            line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
            for line in text.splitlines()
        )
    # Shell and markdown: drop whole comment lines. Markdown prose is not
    # executable, but fenced command blocks are what a reader would copy, so it
    # is deliberately still searched.
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


class TestNoChatIntegrationInThisFramework:
    """No chat-provider integration may live in this repo's executable surface."""

    def test_discord_dispatch_script_is_gone(self):
        assert not (REPO_ROOT / ".claude/bin/discord-dispatch.sh").exists(), (
            "discord-dispatch.sh is back. Chat delivery belongs to CLI Copilot "
            "(`copilot discord dispatch`), which owns the Discord contract."
        )

    @pytest.mark.parametrize("provider", CHAT_PROVIDERS)
    def test_no_provider_is_invoked_from_executable_surface(self, provider):
        patterns = [
            re.compile(p.format(provider=provider), re.IGNORECASE)
            for p in _INVOCATION_PATTERNS
        ]
        offenders = []
        for tree in _EXECUTABLE_TREES:
            root = REPO_ROOT / tree
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix in {".json", ".pyc"}:
                    continue
                if "__pycache__" in path.parts or "state" in path.parts:
                    continue
                code = _code_only(path)
                for pattern in patterns:
                    match = pattern.search(code)
                    if match:
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}: {match.group(0)!r}"
                        )
                        break
        assert not offenders, (
            f"This framework invokes {provider}: {offenders}. Chat delivery belongs "
            f"in CLI Copilot (`copilot discord dispatch`), which owns and tests the "
            f"provider contract. Naming a provider is fine; calling one is not."
        )
