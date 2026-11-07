from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from cc.core.project_migrate import (
    Known, MigrateError, apply_migration, find_manifest, plan_migration, render_plan, rollback_migration, scan_projects,
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
    assert any("no framework tag" in h.reason for h in plan.holds)
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
    assert any("uncommitted changes" in h.reason for h in plan.holds)
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


# -- QA WP-262 defect fixes ---------------------------------------------------

CODEX_FW_CMD = "/bin/bash -c 'exec fw-hook' _ user-prompt-protocol.sh"


def _commit_all(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "more"], check=True)


def _codex_hooks(root: Path, *, extra: bool, created: bool, tagged: bool = False) -> None:
    hooks = [{"type": "command", "command": CODEX_FW_CMD}]
    if tagged:
        hooks = [{"type": "command", "command": "other-fw", "_copilot_source": "claude-copilot"}]
    if extra:
        hooks.append({"type": "command", "command": "echo project-codex-hook"})
    (root / ".codex").mkdir(exist_ok=True)
    (root / ".codex/hooks.json").write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": hooks}]}}))
    lock = json.loads((root / "copilot.lock.json").read_text())
    lock["mutations"].append({"kind": "settings-hook", "target": ".codex/hooks.json",
                              "target_existed_before": not created, "entries": [{"command": CODEX_FW_CMD, "event": "UserPromptSubmit"}]})
    (root / "copilot.lock.json").write_text(json.dumps(lock))
    _commit_all(root)


def test_codex_hooks_framework_entries_removed_project_entries_kept(fx: Fx):
    _codex_hooks(fx.root, extra=True, created=False)
    plan = plan_migration(fx.root, known=fx.known)
    assert ".codex/hooks.json" in acts(plan, "edit-json")
    apply_migration(fx.root, **fx.kw())
    data = json.loads((fx.root / ".codex/hooks.json").read_text())
    cmds = [h["command"] for g in data["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
    assert cmds == ["echo project-codex-hook"]


def test_codex_hooks_file_deleted_only_when_empty_and_framework_created(fx: Fx):
    _codex_hooks(fx.root, extra=False, created=True)
    apply_migration(fx.root, **fx.kw())
    assert not (fx.root / ".codex/hooks.json").exists()


def test_codex_hooks_empty_but_preexisting_file_is_kept(fx: Fx):
    _codex_hooks(fx.root, extra=False, created=False)
    apply_migration(fx.root, **fx.kw())
    assert json.loads((fx.root / ".codex/hooks.json").read_text()) == {}


def test_codex_hooks_identified_by_framework_manifest_not_name(fx: Fx):
    _codex_hooks(fx.root, extra=True, created=False)
    data = json.loads((fx.root / ".codex/hooks.json").read_text())
    data["hooks"]["UserPromptSubmit"][0]["hooks"].append({"type": "command", "command": "fw-lookalike copilot-hook.sh"})
    (fx.root / ".codex/hooks.json").write_text(json.dumps(data))
    _commit_all(fx.root)
    apply_migration(fx.root, **fx.kw())
    text = (fx.root / ".codex/hooks.json").read_text()
    assert "fw-lookalike" in text and "project-codex-hook" in text and "fw-hook" not in text


def test_codex_hooks_removed_via_framework_hooks_json_when_no_lock_entry(fx: Fx):
    _codex_hooks(fx.root, extra=True, created=False)
    lock = json.loads((fx.root / "copilot.lock.json").read_text())
    lock["mutations"].pop()
    (fx.root / "copilot.lock.json").write_text(json.dumps(lock))
    _commit_all(fx.root)
    fx.known.codex_hook_commands = {CODEX_FW_CMD}
    apply_migration(fx.root, **fx.kw())
    assert "fw-hook" not in (fx.root / ".codex/hooks.json").read_text()


def test_missing_codex_root_is_a_planning_error_unless_overridden(fx: Fx):
    fx.known.codex_resolved = False
    before = tree_state(fx.root)
    plan = plan_migration(fx.root, known=fx.known)
    assert plan.refused and plan.errors
    assert "PLANNING ERROR" in render_plan(plan) and "codex-copilot root" in render_plan(plan)
    with pytest.raises(MigrateError) as exc:
        apply_migration(fx.root, **fx.kw())
    assert exc.value.code == "plan-error" and tree_state(fx.root) == before
    ok = plan_migration(fx.root, known=fx.known, allow_missing_codex=True)
    assert not ok.refused and any("override" in n for n in ok.notes)
    apply_migration(fx.root, **fx.kw(allow_missing_codex=True))


def test_existing_branch_name_fails_before_any_write(fx: Fx):
    subprocess.run(["git", "-C", str(fx.root), "branch", "taken"], check=True)
    before = tree_state(fx.root)
    with pytest.raises(MigrateError) as exc:
        apply_migration(fx.root, **fx.kw(commit_branch="taken"))
    assert exc.value.code == "git-branch" and tree_state(fx.root) == before
    assert not fx.backup_root.exists() and not fx.codex_config.exists()


def test_unwritable_backup_location_fails_before_any_write(fx: Fx, tmp_path: Path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        before = tree_state(fx.root)
        with pytest.raises(MigrateError) as exc:
            apply_migration(fx.root, **{**fx.kw(), "backup_root": ro / "b"})
        assert exc.value.code == "backup-unwritable" and tree_state(fx.root) == before
    finally:
        ro.chmod(0o700)


def test_unwritable_project_directory_fails_before_any_write(fx: Fx):
    before = tree_state(fx.root)
    d = fx.root / ".claude/commands"
    d.chmod(0o500)
    try:
        with pytest.raises(MigrateError) as exc:
            apply_migration(fx.root, **fx.kw())
        assert exc.value.code == "not-writable" and tree_state(fx.root) == before
    finally:
        d.chmod(0o755)


def test_mid_apply_failure_rolls_back_automatically(fx: Fx, monkeypatch):
    import cc.core.project_migrate.apply as ap

    def boom(*a, **k):
        raise RuntimeError("init exploded")

    monkeypatch.setattr(ap, "init_project", boom)
    before = tree_state(fx.root)
    with pytest.raises(MigrateError) as exc:
        apply_migration(fx.root, **fx.kw())
    assert exc.value.code == "apply-failed" and "rolled back" in exc.value.message
    assert tree_state(fx.root) == before


def test_commit_failure_restores_branch_and_files(fx: Fx, monkeypatch):
    import cc.core.project_migrate.apply as ap

    real = ap._git

    def flaky(root, *args):
        if args[:1] == ("commit",):
            return subprocess.CompletedProcess(args, 1, "", "hook rejected")
        return real(root, *args)

    monkeypatch.setattr(ap, "_git", flaky)
    before = tree_state(fx.root)
    with pytest.raises(MigrateError) as exc:
        apply_migration(fx.root, **fx.kw(commit_branch="mig"))
    assert exc.value.code == "git-commit"
    assert tree_state(fx.root) == before
    assert git(fx.root, "branch", "--show-current").strip() == "main"
    assert "mig" not in git(fx.root, "branch", "--list")


# -- rollback is byte-identical, including symlinks and machine state ---------------------

def _pack_root(tmp: Path) -> Path:
    for skill in ("legal-nda", "cw"):
        (tmp / "packs" / "writing-legal" / "skills" / skill).mkdir(parents=True)
    return tmp / "packs"


def _pipeline_fx(tmp: Path) -> Fx:
    root = build_project(tmp / "s", shape="pipeline")
    # build_project supplies identity only to its initial commit. Later fixture
    # commits must also work on CI without a developer's global Git identity.
    git(root, "config", "user.name", "Migration fixture")
    git(root, "config", "user.email", "migration-fixture@example.invalid")
    # a valid link, a link to a missing file that is NOT a pack link, an unrelated broken pack-shaped link kept in git
    (root / "valid-link").symlink_to("CLAUDE.md")
    (root / "weird").symlink_to("/nonexistent/place")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts/run.sh").chmod(0o755) if (root / "scripts/run.sh").exists() else None
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "links"], check=True)
    return Fx(root=root, known=make_known(), codex_config=tmp / "codex" / "config.toml",
              registry=tmp / "home" / "registry.json", packs_root=_pack_root(tmp), backup_root=tmp / "b")


def test_rollback_restores_pack_symlinks_and_machine_state(tmp_path: Path):
    f = _pipeline_fx(tmp_path)
    f.codex_config.parent.mkdir(parents=True)
    f.codex_config.write_text('model = "x"\n')
    f.registry.parent.mkdir(parents=True)
    f.registry.write_text(json.dumps({"schema_version": "1.0", "projects": ["/other"]}))
    machine_before = {p: p.read_bytes() for p in (f.codex_config, f.registry)}
    listing_before = sorted(p.name for p in f.codex_config.parent.iterdir()) + sorted(p.name for p in f.registry.parent.iterdir())
    before = tree_state(f.root)
    receipt = apply_migration(f.root, **f.kw())
    after = tree_state(f.root)
    assert any(v[0] == "link" and k.startswith("plugins/pipeline-copilot/skills/") for k, v in after.items()), \
        "init relinks the packs at the same paths; the originals must still come back"
    assert 'trust_level = "trusted"' in f.codex_config.read_text()
    result = rollback_migration(receipt["backup_dir"])
    assert result["conflicts"] == []
    assert tree_state(f.root) == before
    for name in ("legal-nda", "cw"):
        link = f.root / "plugins/pipeline-copilot/skills" / name
        assert os.readlink(link) == f"../../../../codex-copilot/packs/writing-legal/skills/{name}" and not link.exists()
    assert (f.root / "weird").is_symlink() and os.readlink(f.root / "valid-link") == "CLAUDE.md"
    assert {p: p.read_bytes() for p in machine_before} == machine_before
    assert sorted(p.name for p in f.codex_config.parent.iterdir()) + sorted(p.name for p in f.registry.parent.iterdir()) == listing_before
    assert git(f.root, "status", "--porcelain") == ""


def test_rollback_removes_machine_files_and_folders_it_created(tmp_path: Path):
    f = _pipeline_fx(tmp_path)
    receipt = apply_migration(f.root, **f.kw())
    assert f.codex_config.exists() and f.registry.exists()
    rollback_migration(receipt["backup_dir"])
    assert not f.codex_config.parent.exists() and not f.registry.parent.exists()
    assert rollback_migration(receipt["backup_dir"])["conflicts"] == []  # a second run changes nothing


def test_rollback_leaves_machine_state_that_changed_since(tmp_path: Path):
    f = _pipeline_fx(tmp_path)
    receipt = apply_migration(f.root, **f.kw())
    f.registry.write_text(json.dumps({"schema_version": "1.0", "projects": ["/someone-else"]}))
    result = rollback_migration(receipt["backup_dir"])
    assert any(str(f.registry) in c for c in result["conflicts"])
    assert "someone-else" in f.registry.read_text()


def test_rollback_restores_a_project_file_that_was_a_symlink(fx: Fx):
    (fx.root / "real-claude.md").write_text((fx.root / "CLAUDE.md").read_text())
    (fx.root / "CLAUDE.md").unlink()
    (fx.root / "CLAUDE.md").symlink_to("real-claude.md")
    subprocess.run(["git", "-C", str(fx.root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qm", "ln"], check=True)
    before = tree_state(fx.root)
    receipt = apply_migration(fx.root, **fx.kw())
    rollback_migration(receipt["backup_dir"])
    assert tree_state(fx.root) == before


# -- the printed rollback command exists ---------------------------------------------------

def test_printed_rollback_hint_is_a_working_command(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    from cc.main import app

    f = _pipeline_fx(tmp_path)
    before = tree_state(f.root)
    receipt = apply_migration(f.root, **f.kw())
    hint = receipt["recovery"][0]
    assert hint.startswith("cc project migrate ") and "--rollback" in hint
    argv = hint.split()[1:]
    assert argv == ["project", "migrate", str(f.root), "--rollback", "--manifest", receipt["backup_dir"]]
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert tree_state(f.root) == before


def test_cli_rollback_defaults_to_latest_run_and_accepts_a_run_id(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner
    from cc.main import app

    f = _pipeline_fx(tmp_path)
    monkeypatch.setenv("CC_MIGRATE_BACKUP_ROOT", str(f.backup_root))
    before = tree_state(f.root)
    receipt = apply_migration(f.root, **f.kw())
    assert find_manifest(f.root) == Path(receipt["backup_dir"])
    assert find_manifest(f.root, receipt["id"]) == Path(receipt["backup_dir"])
    out = CliRunner().invoke(app, ["project", "migrate", str(f.root), "--rollback"])
    assert out.exit_code == 0, out.output
    assert tree_state(f.root) == before
    again = CliRunner().invoke(app, ["project", "migrate", str(f.root), "--rollback"])
    assert again.exit_code == 1 and "no applied migration" in again.output  # nothing left to roll back


def test_rollback_flags_are_validated(tmp_path: Path):
    from typer.testing import CliRunner
    from cc.main import app

    f = _pipeline_fx(tmp_path)
    out = CliRunner().invoke(app, ["project", "migrate", str(f.root), "--rollback", "--apply"])
    assert out.exit_code == 1 and "cannot be combined" in out.output
    out = CliRunner().invoke(app, ["project", "migrate", str(f.root), "--manifest", "x"])
    assert out.exit_code == 1 and "only used with --rollback" in out.output


# -- AGENTS.md framework sections ----------------------------------------------------------

OLD_LIFECYCLE = "## Work Lifecycle\n\nApply the old\nlifecycle text,\nwrapped differently.\n"


def _digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def test_agents_sections_of_an_older_release_are_removed_and_edited_ones_held(fx: Fx):
    known = Known(file_hashes=fx.known.file_hashes, tree_hashes={}, sections={},
                  section_hashes={"## Work Lifecycle": {_digest(OLD_LIFECYCLE)}, "## Framework Rules": {_digest("## Framework Rules\n\n- a\n")}})
    (fx.root / "AGENTS.md").write_text(
        "# app\n\n## Project Overview\n\nOurs.\n\n## Work Lifecycle\n\nApply the old lifecycle text, wrapped differently.\n\n"
        "## Framework Rules\n\n- a but edited here\n")
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qam", "a"], check=True)
    fx.known = known
    plan = plan_migration(fx.root, known=known)
    assert "AGENTS.md: ## Framework Rules" in paths(plan.holds)
    assert "AGENTS.md: ## Work Lifecycle" not in paths(plan.holds)
    apply_migration(fx.root, plan=plan, **fx.kw())
    text = (fx.root / "AGENTS.md").read_text()
    assert "Apply the old lifecycle" not in text and "but edited here" in text and "Ours." in text


def test_bundled_history_knows_older_codex_sections():
    from cc.core.project_migrate.known import build_known

    known = build_known(claude_root=Path("/nonexistent"), codex_root=Path("/nonexistent-codex"))
    for key in ("## Codex Copilot", "## Output Contract", "## Framework Rules", "## Work Lifecycle"):
        assert known.section_hashes.get(key), key


def test_codex_framework_block_is_a_known_section_source(tmp_path: Path):
    from cc.core.project_migrate.known import build_known

    codex = tmp_path / "current" / "codex-copilot"
    codex.mkdir(parents=True)
    (tmp_path / "current" / "codex-AGENTS.block.md").write_text("## Framework Rules\n\n- current rule\n")
    known = build_known(claude_root=tmp_path, codex_root=codex)
    assert known.sections["## Framework Rules"] == {"## Framework Rules\n\n- current rule"}


# -- every held item is listed in plain words ----------------------------------------------

def test_plan_lists_every_hold_with_a_plain_reason(fx: Fx):
    (fx.root / "weird").symlink_to("/nonexistent/place")
    (fx.root / "AGENTS.md").write_text("# app\n\n## Work Lifecycle\n\n- Edited by the project.\n")
    subprocess.run(["git", "-C", str(fx.root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(fx.root), "commit", "-qm", "h"], check=True)
    plan = plan_migration(fx.root, known=fx.known)
    text = render_plan(plan)
    assert plan.counts()["hold"] == len(plan.holds) >= 2
    for h in plan.holds:
        assert f"{h.path}: {h.reason}" in text and len(h.reason.split()) >= 6
