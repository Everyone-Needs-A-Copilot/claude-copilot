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

There used to be a third site, `.claude/bin/discord-dispatch.sh`. It is gone --
chat delivery moved to CLI Copilot as `copilot discord dispatch`, so this repo
no longer builds a command line on behalf of a chat provider. The boundary is
guarded by `tests/test_budget_dispatch.py::TestNoChatIntegrationInThisFramework`.

Skips (does not fail) when the `claude` binary is not on PATH -- this is an
environment-completeness gate (like skipping a git test with no `git`
installed), not a loosened correctness check: there is nothing in this repo
that can make the assertions pass without a real CLI to validate against.

Historical note, kept because it is the reason this file exists. The removed
`discord-dispatch.sh` used to build a `HARNESS_CMD` string ("claude --print
--max-budget-usd $N") and pass it to `copilot discord handoff --harness`. That
flag is a free-text thread-routing LABEL (verified: `copilot discord handoff
--help` -> "codex, claude, or another label."), never parsed or executed -- so
the constructed command never ran and no budget cap was ever enforced, and the
suite stayed green because the only check was a grep. Two lessons outlived the
script: validate constructed command lines against the target CLI's real
`--help` (this file), and do not let a framework build command lines for
another product's surface (that concern now lives entirely in CLI Copilot).
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
