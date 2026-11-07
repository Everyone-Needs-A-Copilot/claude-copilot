"""`cc settings-hook`: user-level registration stays; the per-project ledger commands refuse.

Old expectation (retired): `add` / `remove` / `rollback` / `list-sources` registered, reverted and
listed framework hooks in a project's `.claude/settings.json` through a `mutations[]` ledger in its
`copilot.lock.json`. New expectation: projects carry no registration (the shim is registered once
in `~/.claude/settings.json`), so those four commands exit 2 with a stable `retired` error that
points at the replacement. `user-add` / `user-remove` are unchanged.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from cc.main import app

runner = CliRunner()


def test_settings_hook_help_lists_subcommands():
    result = runner.invoke(app, ["settings-hook", "--help"])
    assert result.exit_code == 0
    for name in ("add", "remove", "rollback", "user-add", "user-remove", "list-sources"):
        assert name in result.output


@pytest.mark.parametrize("sub", ["add", "remove", "rollback", "list-sources"])
def test_project_ledger_commands_refuse_with_a_pointer(sub, tmp_path):
    result = runner.invoke(app, ["settings-hook", sub, "--project", str(tmp_path), "--json"])
    assert result.exit_code == 2
    error = json.loads(result.output)["error"]
    assert error["code"] == "retired"
    assert f"cc settings-hook {sub}" in error["message"]
    assert "cc settings-hook user-add" in error["message"]
    assert not (tmp_path / ".claude").exists()


def test_user_add_then_remove_round_trips_in_a_scratch_home(tmp_path):
    added = runner.invoke(app, ["settings-hook", "user-add", "--home", str(tmp_path), "--json"])
    assert added.exit_code == 0 and json.loads(added.output)["status"] == "applied"
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert {"SessionStart", "PreToolUse", "UserPromptSubmit"} <= set(settings["hooks"])
    removed = runner.invoke(app, ["settings-hook", "user-remove", "--home", str(tmp_path), "--json"])
    assert removed.exit_code == 0 and json.loads(removed.output)["status"] == "removed"
