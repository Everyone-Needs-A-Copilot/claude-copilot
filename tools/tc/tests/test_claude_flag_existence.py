"""Static check: every flag this repo builds into a `claude` invocation must
actually exist in `claude --help`.

This is the generalizable check for Gap 4: `tc worker` built `claude --print
--message ...`. `--message` is not a real flag (verified live: `claude
--print --message "say hi"` -> `error: unknown option '--message'`), so every
non-dry-run dispatch errored out before an agent ever started. The bug
shipped with a passing test suite because the only check was a grep for the
string `"--max-budget-usd"` -- satisfiable by a command that cannot execute.
This test instead parses the CLI's real `--help` output and validates every
site in this repo that constructs a `claude` command line against it:

  - `tc worker`'s dispatch command (tools/tc/src/tc/commands/worker.py)
  - `/orchestrate start`'s printed `claude --bg ...` dispatch line
    (.claude/commands/orchestrate.md)

`discord-dispatch.sh` no longer builds its own `claude` command line at all
(see below) -- it shells out to `tc worker`, so its flags are checked against
`tc worker --help` in `TestDiscordDispatchDelegatesToTcWorker`, not against
`claude --help`.

Skips (does not fail) when the `claude` binary is not on PATH -- this is an
environment-completeness gate (like skipping a git test with no `git`
installed), not a loosened correctness check: there is nothing in this repo
that can make the assertions pass without a real CLI to validate against.

Historical note on `discord-dispatch.sh`: it used to build a `HARNESS_CMD`
string ("claude --print --max-budget-usd $N") and pass it to `copilot discord
handoff --harness`. That flag is a free-text thread-routing LABEL (verified:
`copilot discord handoff --help` -> "codex, claude, or another label."), never
parsed or executed -- so the constructed command never ran and no budget cap
was ever enforced. The fix moves real dispatch into a `tc worker` subprocess
call (already covered by `TestTcWorkerDispatchFlagsAreReal` above) and uses
`copilot discord handoff --harness claude` only as the genuine label it is.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATE_MD = REPO_ROOT / ".claude/commands/orchestrate.md"
DISCORD_DISPATCH_SH = REPO_ROOT / ".claude/bin/discord-dispatch.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="claude CLI not on PATH -- cannot verify flags against `claude --help`",
)

_LONG_FLAG_RE = re.compile(r"(--[a-zA-Z][a-zA-Z-]*)")
# A *whole* shell token that is a flag -- used once a line has been tokenized
# with shlex, so quoted prompt text (which often mentions other CLIs' flags,
# e.g. "Run: tc task list --stream <id>") is never mistaken for a claude flag.
_FLAG_TOKEN_RE = re.compile(r"^--[a-zA-Z][a-zA-Z-]*$")


def _valid_claude_flags() -> set[str]:
    """Every long flag (`--foo`) claude --help documents, for either the top
    level invocation or the `agents` subcommand (both are dispatch surfaces
    used by this repo)."""
    top = subprocess.run(
        ["claude", "--help"], capture_output=True, text=True, timeout=30
    )
    agents = subprocess.run(
        ["claude", "agents", "--help"], capture_output=True, text=True, timeout=30
    )
    return set(_LONG_FLAG_RE.findall(top.stdout)) | set(
        _LONG_FLAG_RE.findall(agents.stdout)
    )


def _claude_lines_in_markdown(text: str) -> list[str]:
    """Every fenced-code-block line that invokes `claude` directly.

    Deliberately narrow: `tc worker ...` lines are tc's own CLI (already
    covered by the worker.py test below), not a claude invocation.
    """
    lines = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and stripped.startswith("claude "):
            lines.append(stripped)
    return lines


def _flag_tokens(line: str) -> list[str]:
    """Tokenize a shell line and return only *whole* flag tokens.

    Using shlex (not a raw substring regex) matters: a quoted prompt argument
    can legitimately mention another CLI's flags (e.g. `"Run: tc task list
    --stream <id>"`), and a substring match would misreport those as claude
    flags. A whole-token match never does.
    """
    try:
        tokens = shlex.split(line)
    except ValueError:
        return []
    return [tok for tok in tokens if _FLAG_TOKEN_RE.match(tok)]


def _tc_worker_flags_in_discord_dispatch(text: str) -> set[str]:
    """Flags folded into DISPATCH_CMD across its seed assignment and any
    conditional appends (bash array syntax, not a single literal) --
    the `tc worker` invocation discord-dispatch.sh delegates real dispatch
    to. Uses the broad substring regex (not the whole-token `_flag_tokens`
    helper): bash array-append syntax like `DISPATCH_CMD+=(--json)` isn't a
    clean shlex token, but this file's DISPATCH_CMD lines never contain
    quoted natural-language text that could produce a false positive."""
    flags: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("DISPATCH_CMD=(") or stripped.startswith("DISPATCH_CMD+=("):
            flags.update(_LONG_FLAG_RE.findall(stripped))
    return flags


class TestRegressionWouldHaveCaughtTheBug:
    def test_message_is_not_a_real_flag(self):
        """The exact defect this check exists for: `--message` was never a
        real claude flag. This is the assertion that would have failed
        against the pre-fix worker.py dispatch command at authoring time."""
        assert "--message" not in _valid_claude_flags()


class TestTcWorkerDispatchFlagsAreReal:
    def test_full_flag_set_exists_in_claude_help(self):
        from tc.commands.worker import _build_dispatch_cmd

        valid = _valid_claude_flags()
        cmd = _build_dispatch_cmd(
            42, max_budget_usd=2.50, model="sonnet", agent="qa"
        )
        assert cmd[0] == "claude"
        flags = [tok for tok in cmd if tok.startswith("--")]
        assert flags, "expected the dispatch command to use at least one flag"
        missing = [f for f in flags if f not in valid]
        assert not missing, (
            f"tc worker dispatch cmd uses unknown claude flag(s) {missing}: {cmd}"
        )

    def test_no_flag_set_omits_optional_flags_cleanly(self):
        from tc.commands.worker import _build_dispatch_cmd

        valid = _valid_claude_flags()
        cmd = _build_dispatch_cmd(1, max_budget_usd=None, model=None, agent=None)
        flags = [tok for tok in cmd if tok.startswith("--")]
        missing = [f for f in flags if f not in valid]
        assert not missing, f"unknown claude flag(s) {missing}: {cmd}"


class TestOrchestrateDispatchFlagsAreReal:
    def test_claude_bg_line_flags_exist_in_claude_help(self):
        valid = _valid_claude_flags()
        text = ORCHESTRATE_MD.read_text(encoding="utf-8")
        claude_lines = _claude_lines_in_markdown(text)
        assert claude_lines, (
            "expected at least one literal `claude ...` dispatch line in "
            "orchestrate.md's `start` section"
        )
        for line in claude_lines:
            flags = _flag_tokens(line)
            missing = [f for f in flags if f not in valid]
            assert not missing, (
                f"orchestrate.md uses unknown claude flag(s) {missing}: {line}"
            )


class TestDiscordDispatchDelegatesToTcWorker:
    """discord-dispatch.sh must not construct its own `claude` command line.

    That is exactly how the original bug shipped: a hand-built HARNESS_CMD
    string was stored as a `--harness` thread-routing label (verified live:
    `copilot discord handoff --help` -> "--harness TEXT codex, claude, or
    another label.") and never executed -- no process ran, no budget cap was
    enforced. The fix: real dispatch happens via a `tc worker` subprocess
    call (whose own flags are already covered by
    TestTcWorkerDispatchFlagsAreReal above), and `--harness` is passed a
    genuine label.
    """

    def test_no_longer_builds_a_harness_cmd_string(self):
        text = DISCORD_DISPATCH_SH.read_text(encoding="utf-8")
        assert "HARNESS_CMD" not in text, (
            "discord-dispatch.sh must not reconstruct HARNESS_CMD -- that "
            "string was only ever stored as a --harness label, never executed"
        )

    def test_invokes_tc_worker_for_real_dispatch(self):
        text = DISCORD_DISPATCH_SH.read_text(encoding="utf-8")
        assert "worker" in text and "TC_BIN" in text, (
            "discord-dispatch.sh must delegate real dispatch to `tc worker` "
            "(the one dispatch path that actually runs `claude --print` and "
            "enforces --max-budget-usd)"
        )

    def test_dispatch_cmd_flags_exist_in_tc_worker_help(self):
        from tc.main import app
        from typer.testing import CliRunner

        result = CliRunner().invoke(app, ["worker", "--help"])
        valid = set(_LONG_FLAG_RE.findall(result.stdout))

        text = DISCORD_DISPATCH_SH.read_text(encoding="utf-8")
        flags = _tc_worker_flags_in_discord_dispatch(text)
        assert flags, (
            "expected discord-dispatch.sh's tc worker invocation to build "
            "at least one flag"
        )
        missing = flags - valid
        assert not missing, (
            f"discord-dispatch.sh's tc worker invocation uses unknown "
            f"flag(s) {missing} (not in `tc worker --help`)"
        )

    def test_harness_flag_is_a_plain_label_not_a_constructed_command(self):
        """The exact defect this check exists for: --harness must be a
        plain label (e.g. "claude"), never a constructed `claude ...`
        command string passed through as if it would be executed."""
        text = DISCORD_DISPATCH_SH.read_text(encoding="utf-8")
        harness_lines = [ln for ln in text.splitlines() if "--harness" in ln]
        assert harness_lines, (
            "expected a --harness argument to `copilot discord handoff`"
        )
        for ln in harness_lines:
            assert "claude --print" not in ln and "$HARNESS_CMD" not in ln, (
                f"--harness must be a plain label, not a constructed "
                f"claude command: {ln!r}"
            )
