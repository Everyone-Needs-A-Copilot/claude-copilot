"""User-level hook shim: registration (temp HOME only), marker gate, no double
fire, policy markers, coordinator-guard coexistence, reversibility."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem.mutations import (
    USER_ENV,
    apply_user_settings,
    remove_user_settings,
    user_hook_entries,
)

REPO = Path(__file__).resolve().parents[4]
SHIM = REPO / ".claude/hooks/copilot-hook.sh"
GUARD = REPO / ".claude/hooks/coordinator-guard.sh"
EVENTS = ("SessionStart", "PreToolUse", "SubagentStop", "UserPromptSubmit", "PreCompact")
GUARD_GROUP = {
    "matcher": "Bash|Read|Grep|Glob|Edit|Write|NotebookEdit|MultiEdit",
    "hooks": [{"type": "command", "command": '"$HOME/.claude/hooks/coordinator-guard.sh"', "timeout": 5}],
}
OWNER = {
    "cleanupPeriodDays": 120,
    "env": {"CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION": "1000"},
    "permissions": {"defaultMode": "auto"},
    "hooks": {"PreToolUse": [GUARD_GROUP], "Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
    "statusLine": {"type": "command", "command": "s"},
}


def _settings(home: Path) -> dict:
    return json.loads((home / ".claude/settings.json").read_text())


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".claude/settings.json").write_text(json.dumps(OWNER, indent=2) + "\n")
    return h


@pytest.fixture
def release(home: Path) -> Path:
    """A fake release behind ~/.copilot/current whose pretool-check logs its run."""
    rel = home / ".copilot/releases/r1"
    hooks = rel / "claude-copilot/.claude/hooks"
    hooks.mkdir(parents=True)
    shutil.copy(SHIM, hooks / "copilot-hook.sh")
    for name in ("session-start", "pretool-check", "subagent-stop", "user-prompt-submit", "pre-compact-handoff"):
        s = hooks / f"{name}.sh"
        s.write_text('#!/usr/bin/env bash\necho "RAN:$1:$(basename "$(dirname "$(dirname "$(dirname "$COPILOT_HOOK_STATE_DIR")")")")" >> "$HOME/ran.log"\n')
        s.chmod(0o755)
    os.symlink(rel, home / ".copilot/current")
    return rel


def _command(event: str) -> str:
    for e in user_hook_entries():
        if e.event == event:
            return e.command
    raise AssertionError(event)


def _run(home: Path, project: Path, event="PreToolUse", cwd=None, **env):
    e = {**os.environ, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(project)}
    e.pop("COPILOT_HOOKS_ROOT", None)
    e.update(env)
    return subprocess.run(["bash", "-c", _command(event)], input="{}", text=True,
                          capture_output=True, env=e, cwd=cwd or project, timeout=30)


def _ran(home: Path) -> list[str]:
    log = home / "ran.log"
    return log.read_text().split() if log.exists() else []


def _project(tmp_path: Path, marked=True) -> Path:
    p = tmp_path / "proj"
    p.mkdir(exist_ok=True)
    if marked:
        (p / "copilot.project.json").write_text("{}")
    return p


# USER-REGISTRATION ---------------------------------------------------------


def test_registers_five_events_once_and_preserves_owner_keys(home):
    out = apply_user_settings(home)
    assert out.status == "applied" and out.backup and Path(out.backup).exists()
    s = _settings(home)
    for key in ("cleanupPeriodDays", "permissions", "statusLine"):
        assert s[key] == OWNER[key]
    assert s["env"]["CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION"] == "1000"
    assert s["env"]["SLASH_COMMAND_TOOL_CHAR_BUDGET"] == USER_ENV["SLASH_COMMAND_TOOL_CHAR_BUDGET"]
    assert s["hooks"]["Stop"] == OWNER["hooks"]["Stop"]
    for event in EVENTS:
        cmds = [h["command"] for g in s["hooks"][event] for h in g["hooks"] if "copilot-hook.sh" in h["command"]]
        assert cmds == [_command(event)]
        assert ".copilot/current/claude-copilot/.claude/hooks/copilot-hook.sh" in cmds[0]


def test_idempotent_and_no_extra_backup_when_unchanged(home):
    apply_user_settings(home)
    before = (home / ".claude/settings.json").read_bytes()
    again = apply_user_settings(home)
    assert again.status == "unchanged" and again.backup is None
    assert (home / ".claude/settings.json").read_bytes() == before


def test_existing_budget_value_is_owners_and_survives_removal(home):
    doc = dict(OWNER, env={"SLASH_COMMAND_TOOL_CHAR_BUDGET": "5"})
    (home / ".claude/settings.json").write_text(json.dumps(doc))
    apply_user_settings(home)
    assert _settings(home)["env"]["SLASH_COMMAND_TOOL_CHAR_BUDGET"] == "5"
    remove_user_settings(home)
    assert _settings(home)["env"]["SLASH_COMMAND_TOOL_CHAR_BUDGET"] == "5"


def test_remove_restores_owner_settings_exactly(home):
    apply_user_settings(home)
    out = remove_user_settings(home)
    assert out.status == "removed"
    assert _settings(home) == OWNER
    assert remove_user_settings(home).status == "not-installed"


def test_missing_settings_created_and_removed_cleanly(tmp_path):
    h = tmp_path / "h2"
    h.mkdir()
    assert apply_user_settings(h).status == "applied"
    assert remove_user_settings(h).status == "removed"
    assert _settings(h) == {}


def test_invalid_json_blocks_without_writing(home):
    p = home / ".claude/settings.json"
    p.write_text("{nope")
    assert apply_user_settings(home).status == "blocked"
    assert p.read_text() == "{nope"


def test_dry_run_writes_nothing(home):
    before = (home / ".claude/settings.json").read_bytes()
    apply_user_settings(home, dry_run=True)
    assert (home / ".claude/settings.json").read_bytes() == before
    assert not list((home / ".claude").glob("*.copilot-backup-*"))


# MARKER-GATE ---------------------------------------------------------------


def test_unmarked_directory_is_silent_noop(home, release, tmp_path):
    r = _run(home, _project(tmp_path, marked=False))
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert _ran(home) == []


def test_marked_directory_runs_release_hook(home, release, tmp_path):
    r = _run(home, _project(tmp_path))
    assert r.returncode == 0
    assert _ran(home) == ["RAN:pretool-check:proj"]


def test_marker_found_from_subdirectory(home, release, tmp_path):
    proj = _project(tmp_path)
    sub = proj / "a/b"
    sub.mkdir(parents=True)
    _run(home, sub)
    assert _ran(home) == ["RAN:pretool-check:proj"]


def test_release_flip_changes_logic_not_command(home, release, tmp_path):
    proj = _project(tmp_path)
    cmd = _command("PreToolUse")
    rel2 = home / ".copilot/releases/r2"
    shutil.copytree(release, rel2, symlinks=True)
    (rel2 / "claude-copilot/.claude/hooks/pretool-check.sh").write_text(
        '#!/usr/bin/env bash\necho "R2" >> "$HOME/ran.log"\n')
    (home / ".copilot/current").unlink()
    os.symlink(rel2, home / ".copilot/current")
    r = _run(home, proj)
    assert r.returncode == 0 and _ran(home) == ["R2"] and cmd == _command("PreToolUse")


# NO-DOUBLE-FIRE ------------------------------------------------------------


def test_legacy_project_registration_defers_to_project(home, release, tmp_path):
    proj = _project(tmp_path)
    (proj / ".claude").mkdir()
    (proj / ".claude/settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
        {"type": "command", "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/copilot-hook.sh" pretool-check'}]}]}}))
    r = _run(home, proj)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert _ran(home) == []


def test_vendored_shim_still_runs_in_legacy_project(home, release, tmp_path):
    proj = _project(tmp_path)
    (proj / ".claude/hooks").mkdir(parents=True)
    shutil.copy(SHIM, proj / ".claude/hooks/copilot-hook.sh")
    e = {**os.environ, "HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj),
         "COPILOT_HOOKS_ROOT": str(release / "claude-copilot/.claude/hooks")}
    r = subprocess.run(["bash", str(proj / ".claude/hooks/copilot-hook.sh"), "pretool-check"],
                       input="{}", text=True, capture_output=True, env=e, cwd=proj, timeout=30)
    assert r.returncode == 0 and _ran(home) == ["RAN:pretool-check:proj"]


# POLICY-MARKERS ------------------------------------------------------------


def test_hooks_disabled_marker_disables(home, release, tmp_path):
    proj = _project(tmp_path)
    (proj / ".claude").mkdir()
    (proj / ".claude/copilot-hooks-disabled").write_text("")
    r = _run(home, proj)
    assert r.returncode == 0 and _ran(home) == []


def test_missing_pointer_fails_open_without_required(home, tmp_path):
    r = _run(home, _project(tmp_path))
    assert r.returncode == 0


def test_missing_pointer_fails_closed_with_required(home, tmp_path):
    proj = _project(tmp_path)
    (proj / ".claude").mkdir()
    (proj / ".claude/copilot-required").write_text("")
    r = _run(home, proj)
    assert r.returncode == 2 and "release pointer missing" in r.stderr


def test_dangling_pointer_does_not_block_bash(home, tmp_path):
    os.symlink(home / "nowhere", home / ".copilot/current") if (home / ".copilot").exists() else None
    r = _run(home, _project(tmp_path), event="PreToolUse")
    assert r.returncode == 0


def test_broken_release_fails_open_for_marked_bash_but_closed_with_required(home, release, tmp_path):
    (release / "claude-copilot/.claude/hooks/pretool-check.sh").unlink()
    proj = _project(tmp_path)
    r = _run(home, proj)
    assert r.returncode == 0
    (proj / ".claude").mkdir()
    (proj / ".claude/copilot-required").write_text("")
    assert _run(home, proj).returncode == 2


# GUARD-UNGATED -------------------------------------------------------------


def test_coordinator_guard_registration_unchanged_and_still_blocks(home, tmp_path):
    apply_user_settings(home)
    groups = _settings(home)["hooks"]["PreToolUse"]
    assert groups[0] == GUARD_GROUP
    unmarked = _project(tmp_path, marked=False)
    payload = json.dumps({"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "ls /x"}})
    env = {k: v for k, v in os.environ.items() if k != "COPILOT_COORDINATOR"}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(unmarked))
    r = subprocess.run([str(GUARD)], input=payload, text=True, capture_output=True, env=env,
                       cwd=unmarked, timeout=30)
    assert r.returncode == 2 and "Coordinator rule" in r.stderr


def test_cli_user_add_and_remove(home):
    from cc.commands.settings_hook import settings_hook_app
    from typer.testing import CliRunner

    runner = CliRunner()
    r = runner.invoke(settings_hook_app, ["user-add", "--home", str(home), "--json"])
    assert r.exit_code == 0 and json.loads(r.stdout)["status"] == "applied"
    r = runner.invoke(settings_hook_app, ["user-remove", "--home", str(home), "--json"])
    assert r.exit_code == 0 and json.loads(r.stdout)["status"] == "removed"
    assert _settings(home) == OWNER
