"""Tests for `tc worker` -- dispatch command construction, spend measurement,
and budget-breach handling.

Regression coverage for Gap 4: worker.py built a `claude --print --message
...` invocation. `--message` is not a real claude flag (verified live:
`claude --print --message "say hi"` -> `error: unknown option '--message'`,
exit 1). The dispatch path had never actually run. These tests prove the
rebuilt command is real (matches `claude --help`'s flag surface) and that
spend measurement / breach handling behave correctly against the exact
result-wrapper shape the harness returns (verified live, see below).

Live-verified shapes this suite's mocks are built from:

  Success (`claude --print --output-format json "reply with exactly: pong"`):
    {"is_error": false, "stop_reason": "end_turn", "total_cost_usd": 0.24,
     "terminal_reason": "completed", "subtype": "success", "num_turns": 1, ...}

  Budget breach (`claude --print --output-format json --max-budget-usd 0.001
  --model haiku "reply with exactly: pong"`, real exit code 1):
    {"is_error": true, "total_cost_usd": 0.0404804,
     "terminal_reason": "budget_exhausted", "subtype": "error_max_budget_usd",
     "errors": ["Reached maximum budget ($0.001)"], ...}
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _build_dispatch_cmd -- the flag bug itself
# ---------------------------------------------------------------------------


class TestBuildDispatchCmd:
    def _build(self, task_id: int, **kwargs):
        from tc.commands.worker import _build_dispatch_cmd

        return _build_dispatch_cmd(task_id, **kwargs)

    def test_no_message_flag(self):
        """--message is not a real claude flag; it must never appear."""
        cmd = self._build(42, max_budget_usd=2.5, model="sonnet", agent="qa")
        assert "--message" not in cmd

    def test_prompt_is_positional_not_flagged(self):
        """The prompt must be a bare positional arg, not attached to a flag."""
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert cmd[-1].startswith("Work on task 42")
        assert not cmd[-1].startswith("-")

    def test_uses_claude_print_and_json_output(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert cmd[0] == "claude"
        assert "--print" in cmd
        assert "--output-format" in cmd
        assert cmd[cmd.index("--output-format") + 1] == "json"

    def test_default_agent_uses_native_agent_flag(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "me"

    def test_custom_agent_uses_native_agent_flag(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent="qa")
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "qa"

    def test_max_budget_usd_passed_through_when_set(self):
        cmd = self._build(42, max_budget_usd=2.50, model=None, agent=None)
        assert "--max-budget-usd" in cmd
        idx = cmd.index("--max-budget-usd")
        assert cmd[idx + 1] == "2.5"

    def test_max_budget_usd_omitted_when_none(self):
        cmd = self._build(42, max_budget_usd=None, model=None, agent=None)
        assert "--max-budget-usd" not in cmd

    def test_model_passed_through_when_set(self):
        cmd = self._build(42, max_budget_usd=None, model="claude-opus-4-5", agent=None)
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-opus-4-5"


# ---------------------------------------------------------------------------
# _parse_spend / is_budget_breach -- against real, live-verified shapes
# ---------------------------------------------------------------------------


_LIVE_SUCCESS_STDOUT = json.dumps(
    {
        "is_error": False,
        "duration_api_ms": 1467,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "session_id": "7351109f-0c9a-4bf8-a33a-06c23c70714a",
        "total_cost_usd": 0.24211349999999998,
        "terminal_reason": "completed",
        "subtype": "success",
        "result": "pong",
    }
)

_LIVE_BREACH_STDOUT = json.dumps(
    {
        "is_error": True,
        "duration_api_ms": 0,
        "num_turns": 1,
        "stop_reason": "end_turn",
        "total_cost_usd": 0.0404804,
        "terminal_reason": "budget_exhausted",
        "subtype": "error_max_budget_usd",
        "errors": ["Reached maximum budget ($0.001)"],
    }
)


class TestParseSpend:
    def test_parses_live_success_shape(self):
        from tc.commands.worker import _parse_spend

        spend = _parse_spend(_LIVE_SUCCESS_STDOUT)
        assert spend["total_cost_usd"] == pytest.approx(0.24211349999999998)
        assert spend["terminal_reason"] == "completed"
        assert spend["num_turns"] == 1

    def test_parses_live_breach_shape(self):
        from tc.commands.worker import _parse_spend

        spend = _parse_spend(_LIVE_BREACH_STDOUT)
        assert spend["terminal_reason"] == "budget_exhausted"
        assert spend["is_error"] is True

    def test_unparseable_stdout_returns_empty_dict(self):
        """A crashed/signalled run must not take down dispatch."""
        from tc.commands.worker import _parse_spend

        assert _parse_spend("") == {}
        assert _parse_spend("not json") == {}

    def test_non_dict_json_returns_empty_dict(self):
        from tc.commands.worker import _parse_spend

        assert _parse_spend("[1, 2, 3]") == {}

    def test_drops_keys_outside_allow_list(self):
        from tc.commands.worker import _parse_spend

        spend = _parse_spend(json.dumps({"total_cost_usd": 1.0, "session_id": "secret"}))
        assert "session_id" not in spend
        assert spend["total_cost_usd"] == 1.0


class TestIsBudgetBreach:
    def test_true_on_budget_exhausted(self):
        from tc.commands.worker import _parse_spend, is_budget_breach

        assert is_budget_breach(_parse_spend(_LIVE_BREACH_STDOUT)) is True

    def test_false_on_completed(self):
        from tc.commands.worker import _parse_spend, is_budget_breach

        assert is_budget_breach(_parse_spend(_LIVE_SUCCESS_STDOUT)) is False

    def test_false_on_empty_spend(self):
        from tc.commands.worker import is_budget_breach

        assert is_budget_breach({}) is False


# ---------------------------------------------------------------------------
# dispatch() -- measurement + breach handling against the DB
# ---------------------------------------------------------------------------


def _mock_result(returncode: int, stdout: str) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = ""
    return m


class TestDispatchMeasurementAndBreach:
    def _task(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        result = cli(
            ["task", "create", "--title", "Do the thing", "--stream", "1", "--json"]
        )
        task = json.loads(result.output)
        cli(["task", "claim", str(task["id"]), "--agent", "me"])
        return task["id"]

    def test_success_run_is_logged_and_task_untouched(self, cli, db_path):
        from tc.commands.worker import dispatch

        task_id = self._task(cli)

        with patch(
            "tc.commands.worker._subprocess.run",
            return_value=_mock_result(0, _LIVE_SUCCESS_STDOUT),
        ):
            outcome = dispatch(
                task_id, cmd=["claude", "--print"], agent="me", db_path=db_path
            )

        assert outcome["returncode"] == 0
        assert outcome["breached"] is False
        assert outcome["spend"]["total_cost_usd"] == pytest.approx(0.24211349999999998)

        log_result = cli(["log", "--task", str(task_id), "--json"])
        actions = [entry["action"] for entry in json.loads(log_result.output)]
        assert "worker_dispatch" in actions
        assert "budget_exhausted" not in actions

        task_result = cli(["task", "get", str(task_id), "--json"])
        task_row = json.loads(task_result.output)
        assert task_row["status"] == "in_progress"
        assert task_row["claimed_by"] == "me"

    def test_breach_releases_task_and_logs_reason(self, cli, db_path):
        from tc.commands.worker import dispatch

        task_id = self._task(cli)

        with patch(
            "tc.commands.worker._subprocess.run",
            return_value=_mock_result(1, _LIVE_BREACH_STDOUT),
        ):
            outcome = dispatch(
                task_id, cmd=["claude", "--print"], agent="me", db_path=db_path
            )

        assert outcome["returncode"] == 1
        assert outcome["breached"] is True

        task_result = cli(["task", "get", str(task_id), "--json"])
        task_row = json.loads(task_result.output)
        assert task_row["status"] == "pending"
        assert task_row["claimed_by"] is None
        assert task_row["claimed_at"] is None

        log_result = cli(["log", "--task", str(task_id), "--json"])
        actions = [entry["action"] for entry in json.loads(log_result.output)]
        assert "budget_exhausted" in actions

    def test_unparseable_output_does_not_crash_dispatch(self, cli, db_path):
        """A killed/signalled run (no JSON on stdout) must still return cleanly."""
        from tc.commands.worker import dispatch

        task_id = self._task(cli)

        with patch(
            "tc.commands.worker._subprocess.run",
            return_value=_mock_result(1, ""),
        ):
            outcome = dispatch(
                task_id, cmd=["claude", "--print"], agent="me", db_path=db_path
            )

        assert outcome["returncode"] == 1
        assert outcome["spend"] == {}
        assert outcome["breached"] is False


# ---------------------------------------------------------------------------
# `tc worker` CLI -- dry-run behavior (unchanged contract) + real dispatch
# wiring, mocked at the subprocess boundary.
# ---------------------------------------------------------------------------


class TestTcWorkerCLI:
    def test_dry_run_never_touches_message_flag(self, cli):
        result = cli(["worker", "42", "--max-budget-usd", "3.00", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "--message" not in data["cmd"]
        assert "--agent" in data["cmd"]

    def test_dry_run_omits_max_budget_usd_when_not_set(self, cli):
        result = cli(["worker", "42", "--dry-run"])
        assert result.exit_code == 0
        assert "--max-budget-usd" not in result.output

    def test_real_dispatch_emits_json_outcome(self, cli, db_path):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        task = json.loads(
            cli(["task", "create", "--title", "T", "--stream", "1", "--json"]).output
        )
        cli(["task", "claim", str(task["id"]), "--agent", "me"])

        with patch(
            "tc.commands.worker._subprocess.run",
            return_value=_mock_result(0, _LIVE_SUCCESS_STDOUT),
        ):
            result = cli(["worker", str(task["id"]), "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["breached"] is False
        assert data["spend"]["terminal_reason"] == "completed"

    def test_real_dispatch_breach_exits_nonzero_and_releases_task(self, cli, db_path):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s1", "--prd", "1"])
        task = json.loads(
            cli(["task", "create", "--title", "T", "--stream", "1", "--json"]).output
        )
        cli(["task", "claim", str(task["id"]), "--agent", "me"])

        with patch(
            "tc.commands.worker._subprocess.run",
            return_value=_mock_result(1, _LIVE_BREACH_STDOUT),
        ):
            result = cli(
                ["worker", str(task["id"]), "--max-budget-usd", "0.001"]
            )

        assert result.exit_code == 1
        assert "budget exhausted" in result.output.lower()

        task_row = json.loads(cli(["task", "get", str(task["id"]), "--json"]).output)
        assert task_row["status"] == "pending"


# ---------------------------------------------------------------------------
# tools/tc/README.md previously documented `tc worker run <id>` / `tc worker
# status <id>` subcommands and a `--max-budget-usd` flag on `tc task
# create`/`tc task claim` -- none of which exist (worker.py has always taken
# task_id as a direct positional argument; --max-budget-usd lives only on
# `tc worker`). Regression coverage: the documented-but-fake shapes fail, and
# the real, corrected shape works.
# ---------------------------------------------------------------------------


def _fenced_bash_blocks(text: str) -> list[str]:
    """Every fenced code block's content -- the runnable commands a reader
    would copy-paste, as opposed to prose that may legitimately *mention* a
    fake shape while explaining that it doesn't exist."""
    blocks = []
    in_fence = False
    current: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_fence:
                blocks.append("\n".join(current))
                current = []
            in_fence = not in_fence
            continue
        if in_fence:
            current.append(line)
    return blocks


class TestWorkerReadmeContentMatchesReality:
    """The doc defect itself (not just the CLI behavior it misdescribed):
    README.md's runnable command blocks must not present CLI shapes that
    don't exist as if they worked. Fails against the pre-fix README text
    (which showed `tc worker run <id>` as a runnable example), passes
    against the corrected text.
    """

    def _worker_section_code_blocks(self) -> str:
        from pathlib import Path

        readme = Path("/Volumes/Dev/Sites/COPILOT/claude-copilot/tools/tc/README.md")
        text = readme.read_text(encoding="utf-8")
        worker_section = text.split("### `tc worker`")[1].split("### `tc deploy`")[0]
        return "\n".join(_fenced_bash_blocks(worker_section))

    def test_readme_does_not_show_fake_worker_subcommands_as_runnable(self):
        code = self._worker_section_code_blocks()
        assert "tc worker run" not in code
        assert "tc worker status" not in code

    def test_readme_does_not_show_max_budget_usd_on_task_create_or_claim(self):
        code = self._worker_section_code_blocks()
        assert "task create" not in code
        assert "task claim" not in code

    def test_readme_shows_the_real_worker_shape_as_runnable(self):
        code = self._worker_section_code_blocks()
        assert "tc worker 42 --max-budget-usd" in code


class TestWorkerReadmeAccuracy:
    def test_worker_run_subcommand_does_not_exist(self, cli):
        result = cli(["worker", "run", "1", "--dry-run"])
        assert result.exit_code != 0

    def test_worker_status_subcommand_does_not_exist(self, cli):
        result = cli(["worker", "status", "1"])
        assert result.exit_code != 0

    def test_task_create_has_no_max_budget_usd_flag(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        result = cli(
            ["task", "create", "--title", "T", "--prd", "1", "--max-budget-usd", "0.5"]
        )
        assert result.exit_code != 0

    def test_task_claim_has_no_max_budget_usd_flag(self, cli):
        cli(["prd", "create", "--title", "PRD"])
        cli(["stream", "create", "--name", "s", "--prd", "1"])
        cli(["task", "create", "--title", "T", "--stream", "1"])
        result = cli(["task", "claim", "1", "--agent", "me", "--max-budget-usd", "0.5"])
        assert result.exit_code != 0

    def test_documented_worker_shape_actually_works(self, cli):
        """The corrected README shape:
        `tc worker <task_id> --max-budget-usd <float> --dry-run --json`."""
        result = cli(["worker", "42", "--max-budget-usd", "0.50", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "--max-budget-usd" in data["cmd"]
