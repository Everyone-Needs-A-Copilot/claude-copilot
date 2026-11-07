"""Focused CR-S controls: runtime churn is ignored, framework changes are observed."""

import subprocess

from harness import FRAMEWORK_TOP, tracked_tree_digest


def test_project_sentinel_ignores_runtime_state_but_detects_framework_changes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".claude/hooks/state/\n")
    rules = tmp_path / "CLAUDE.md"
    rules.write_text("project rules\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore", "CLAUDE.md"], check=True)
    state = tmp_path / ".claude/hooks/state/session-turns.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"turn": 1}\n')
    before = tracked_tree_digest(tmp_path, FRAMEWORK_TOP)
    state.write_text('{"turn": 2}\n')
    assert tracked_tree_digest(tmp_path, FRAMEWORK_TOP) == before
    rules.write_text("changed project rules\n")
    changed = tracked_tree_digest(tmp_path, FRAMEWORK_TOP)
    assert changed != before
    added = tmp_path / ".claude/new-framework.md"
    added.write_text("new framework file\n")
    assert tracked_tree_digest(tmp_path, FRAMEWORK_TOP) != changed
