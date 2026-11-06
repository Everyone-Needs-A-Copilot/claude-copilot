from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cc.core.project_migrate import (
    MigrateError, apply_migration, plan_migration, render_plan, rollback_migration, scan_projects,
)
from tests.project_migrate.conftest import (
    CLAUDE_BLOCK, FW_SECTION, Fx, build_project, make_known, tree_state,
)


def paths(items) -> set[str]:
    return {i.path for i in items}


def acts(plan, kind: str) -> set[str]:
    return {a.path for a in plan.actions if a.kind == kind}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def test_dry_run_writes_nothing_and_lists_everything(fx: Fx):
    before = tree_state(fx.root)
    plan = plan_migration(fx.root, known=fx.known)
    text = render_plan(plan)
    assert tree_state(fx.root) == before
    assert not fx.codex_config.exists() and not fx.backup_root.exists()
    assert ".claude/commands/protocol.md" in acts(plan, "delete")
    assert "REMOVE" in text and "KEEP" in text and ".claude/commands/protocol.md" in text


def test_only_checksum_matching_unowned_files_are_deleted(fx: Fx):
    plan = plan_migration(fx.root, known=fx.known)
    deleted = acts(plan, "delete")
    assert "scripts/copilot-gate.sh" in deleted  # unmodified in default fixture
    (fx.root / "scripts").chmod(0o755)
    gate = fx.root / "scripts/copilot-gate.sh"
    gate.chmod(0o755)
    gate.write_text("#!/bin/bash\nproject-owned gate\n")
    (fx.root / ".claude/agents/ta.md").write_text("---\nname: ta\nowner: project\n---\nmine\n")
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qam", "edit"], check=True)
    plan = plan_migration(fx.root, known=fx.known)
    assert "scripts/copilot-gate.sh" in paths(plan.holds)
    assert "scripts/copilot-gate.sh" not in acts(plan, "delete")
    assert ".claude/agents/ta.md" in paths(plan.keeps)
    assert ".claude/agents/ta.md" not in acts(plan, "delete")
    assert ".claude/agents/mine.md" in paths(plan.keeps)  # not in any lock


def test_apply_retires_locks_and_preserves_project_state(fx: Fx):
    state_before = tree_state(fx.root)
    receipt = apply_migration(fx.root, **fx.kw())
    r = fx.root
    for gone in ("copilot.lock.json", ".codex-copilot.json", ".mcp.json", ".claude/fitness-check.sh",
                 ".claude/commands/protocol.md", ".claude/agents/me.md", "plugins/codex-copilot/plugin.json",
                 ".agents/plugins/marketplace.json", ".claude/hooks/copilot-hook.sh"):
        assert not (r / gone).exists(), gone
    assert not (r / ".claude/skills/codex-copilot").is_symlink()
    assert not (r / "plugins/codex-copilot").exists()  # emptied dirs pruned
    marker = json.loads((r / "copilot.project.json").read_text())
    assert marker["runtimes"] == ["claude", "codex"] and marker["tier"] == "x"
    for kept in (".claude/memory/entries/m1.md", ".copilot/tasks.db", ".copilot/wp/1.md", ".claude/cc/config.json",
                 ".claude/skills/launch/SKILL.md", ".claude/agents/mine.md", "SOUL.md"):
        assert tree_state(r)[kept] == state_before[kept], kept
    assert str(r.resolve()) in fx.codex_config.read_text()
    assert receipt["commit"] == "" and git(r, "log", "--oneline").count("\n") == 1  # never commits by default


def test_settings_keeps_non_framework_keys_and_hooks(fx: Fx):
    apply_migration(fx.root, **fx.kw())
    s = json.loads((fx.root / ".claude/settings.json").read_text())
    assert s["permissions"] == {"allow": ["Bash(ls)"]}
    group = s["hooks"]["SessionStart"][0]
    assert [h["command"] for h in group["hooks"]] == ["echo project-hook"]
    assert "PreCompact" not in s["hooks"]


def test_settings_created_by_framework_is_removed_when_empty(fx: Fx):
    (fx.root / ".claude/settings.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "x", "_copilot_source": "claude-copilot"}]}]}}))
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qam", "s"], check=True)
    apply_migration(fx.root, **fx.kw())
    assert not (fx.root / ".claude/settings.json").exists()


def test_untagged_shim_lookalike_hook_is_held(fx: Fx):
    s = json.loads((fx.root / ".claude/settings.json").read_text())
    s["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "bash other/copilot-hook.sh stop"}]}]
    (fx.root / ".claude/settings.json").write_text(json.dumps(s))
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qam", "s"], check=True)
    plan = plan_migration(fx.root, known=fx.known)
    assert any("untagged" in h.reason for h in plan.holds)
    apply_migration(fx.root, plan=plan, **fx.kw())
    assert "Stop" in json.loads((fx.root / ".claude/settings.json").read_text())["hooks"]


def test_instruction_files_thin_and_hold_edited_sections(fx: Fx):
    (fx.root / "AGENTS.md").write_text(
        "# app\n\n## Project Overview\n\nOurs.\n\n" + FW_SECTION + "\n## Work Lifecycle\n\n- Edited by the project.\n")
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qam", "a"], check=True)
    plan = plan_migration(fx.root, known=fx.known)
    assert any(h.path == "AGENTS.md: ## Work Lifecycle" for h in plan.holds)
    apply_migration(fx.root, plan=plan, **fx.kw())
    agents = (fx.root / "AGENTS.md").read_text()
    assert "Lead with the answer" not in agents and "Edited by the project" in agents and "Ours." in agents
    claude = (fx.root / "CLAUDE.md").read_text()
    assert CLAUDE_BLOCK.strip() not in claude and "Task Acceptance" not in claude
    assert "- Be kind." in claude and "Ours." in claude and "framework-section:begin" in claude


def test_dirty_affected_path_is_refused_but_unrelated_dirt_is_fine(fx: Fx):
    (fx.root / "notes.txt").write_text("unrelated\n")
    assert not plan_migration(fx.root, known=fx.known).refused
    (fx.root / "CLAUDE.md").write_text("local edit\n")
    plan = plan_migration(fx.root, known=fx.known)
    assert plan.refused and "CLAUDE.md" in plan.dirty
    assert any(h.reason.startswith("uncommitted") for h in plan.holds)
    before = tree_state(fx.root)
    with pytest.raises(MigrateError) as exc:
        apply_migration(fx.root, **fx.kw())
    assert exc.value.code == "dirty" and tree_state(fx.root) == before


def test_commit_on_named_branch_is_opt_in_and_scoped(fx: Fx):
    (fx.root / "notes.txt").write_text("unrelated\n")
    receipt = apply_migration(fx.root, **fx.kw(commit_branch="chore/central-resolution"))
    assert receipt["branch"] == "chore/central-resolution" and receipt["commit"]
    assert git(fx.root, "branch", "--show-current").strip() == "chore/central-resolution"
    assert git(fx.root, "log", "--oneline").count("\n") == 2
    assert "notes.txt" not in git(fx.root, "show", "--stat", "--format=", "HEAD")
    assert "?? notes.txt" in git(fx.root, "status", "--porcelain")
    assert any("git" in r for r in receipt["recovery"])


def test_rollback_restores_byte_identical_tree(fx: Fx):
    before = tree_state(fx.root)
    receipt = apply_migration(fx.root, **fx.kw())
    assert tree_state(fx.root) != before
    result = rollback_migration(receipt["backup_dir"])
    assert result["conflicts"] == []
    assert tree_state(fx.root) == before


def test_rollback_leaves_files_changed_since_migration(fx: Fx):
    receipt = apply_migration(fx.root, **fx.kw())
    (fx.root / "CLAUDE.md").write_text("rewritten later\n")
    result = rollback_migration(receipt["backup_dir"])
    assert any(c.startswith("CLAUDE.md") for c in result["conflicts"])
    assert (fx.root / "CLAUDE.md").read_text() == "rewritten later\n"


def test_apply_is_idempotent_afterwards(fx: Fx):
    apply_migration(fx.root, **fx.kw())
    subprocess.run(["git", "-C", str(fx.root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qm", "m"], check=True)
    plan = plan_migration(fx.root, known=fx.known)
    assert not [a for a in plan.actions if a.kind in ("delete", "unlink", "edit-json", "edit-text")]


def test_drift_between_plan_and_apply_aborts_before_writing(fx: Fx):
    plan = plan_migration(fx.root, known=fx.known)
    (fx.root / "CLAUDE.md").write_text("changed after plan\n")
    before = tree_state(fx.root)
    with pytest.raises(MigrateError) as exc:
        apply_migration(fx.root, plan=plan, **fx.kw())
    assert exc.value.code == "drifted" and tree_state(fx.root) == before


def test_non_git_project_migrates_and_rolls_back(tmp_path: Path):
    f = Fx(root=build_project(tmp_path / "s", git=False), known=make_known(), codex_config=tmp_path / "c.toml",
           registry=tmp_path / "r.json", packs_root=tmp_path / "p", backup_root=tmp_path / "b")
    before = tree_state(f.root)
    plan = plan_migration(f.root, known=f.known)
    assert not plan.git and any("not a Git" in n for n in plan.notes)
    receipt = apply_migration(f.root, **f.kw())
    rollback_migration(receipt["backup_dir"])
    assert tree_state(f.root) == before


@pytest.mark.parametrize("shape", ["convoco", "gtm", "pipeline", "creative"])
def test_fixture_shapes(tmp_path: Path, shape: str):
    root = build_project(tmp_path / "s", shape=shape)
    f = Fx(root=root, known=make_known(), codex_config=tmp_path / "c.toml", registry=tmp_path / "r.json",
           packs_root=tmp_path / "p", backup_root=tmp_path / "b")
    before = tree_state(root)
    plan = plan_migration(root, known=f.known)
    if shape == "convoco":
        assert "scripts/copilot-gate.sh" in paths(plan.holds) or "scripts/copilot-gate.sh" in paths(plan.keeps) or "scripts/copilot-gate.sh" in acts(plan, "delete")
    apply_migration(root, **f.kw())
    after = tree_state(root)
    if shape == "gtm":
        for p in ("docs/plugins/codex-copilot/plugin.json", "plugins/gtm-copilot/.codex-plugin/plugin.json",
                  "plugins/gtm-copilot/skills/gtm/SKILL.md"):
            assert after[p] == before[p]
    if shape == "creative":
        assert (root / ".claude/commands/protocol.md").read_text() == "# protocol edited by project\n"
        assert ".claude/commands/protocol.md" in paths(plan.holds)
    if shape == "pipeline":
        marker = json.loads((root / "copilot.project.json").read_text())
        assert marker["activePacks"] == [{"name": "writing-legal", "activatedBy": "./plugins/pipeline-copilot"}]
        assert not any(k.startswith("plugins/pipeline-copilot/skills/") and v[0] == "link" for k, v in after.items())
        assert not (root / "copilot.lock.json").exists()
    if shape == "convoco":
        assert (root / "scripts/copilot-gate.sh").read_text().find("project-owned gate") >= 0
    rollback_migration(next((tmp_path / "b" / "app").iterdir()))
    assert tree_state(root) == before


def test_other_broken_symlinks_are_held_not_removed(fx: Fx):
    (fx.root / "weird").symlink_to("/nonexistent/place")
    subprocess.run(["git", "-C", str(fx.root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qm", "l"], check=True)
    plan = plan_migration(fx.root, known=fx.known)
    assert "weird" in paths(plan.holds) and "weird" not in acts(plan, "unlink")


def test_unreadable_lock_deletes_no_lock_listed_file(fx: Fx):
    (fx.root / "copilot.lock.json").write_text("{not json")
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qam", "bad"], check=True)
    plan = plan_migration(fx.root, known=fx.known)
    assert ".claude/commands/protocol.md" not in acts(plan, "delete")
    assert any("unreadable" in n for n in plan.notes)


def test_scan_reports_then_zero_after_migration(tmp_path: Path):
    root = tmp_path / "fleet"
    kn = make_known()
    projects = [build_project(root, f"p{i}", shape=s) for i, s in enumerate(("convoco", "gtm", "pipeline", "creative"))]
    before = scan_projects([root], known=kn)
    assert before["total"] == 4 and before["lock_files"] == 8 and before["copied_files"] > 0 and before["clean"] == 0
    for p in projects:
        apply_migration(p, known=kn, codex_config=tmp_path / "c.toml", registry=tmp_path / "r.json",
                        packs_root=tmp_path / "pk", backup_root=tmp_path / "b")
    after = scan_projects([root], known=kn)
    assert after["total"] == 4 and after["lock_files"] == 0 and after["hook_registrations"] == 0
    # creative's edited protocol.md is a hold: never deleted, never counted as a copy without a lock
    assert after["copied_files"] == 0 and after["clean"] == 4


def test_no_runtime_reads_of_retired_locks_outside_migrate():
    """Dependency direction: the migrate library is the only reader of the retired lock names here."""
    import re
    src = Path(__file__).resolve().parents[2] / "src/cc/core/project_init"
    pattern = re.compile(r"copilot\.lock\.json|\.codex-copilot\.json")
    assert not [p for p in src.rglob("*.py") if pattern.search(p.read_text())]
