"""Link generator tests: temp HOME only, fabricated release directory."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cc.core.release.engine import layout
from cc.core.release.links import apply_plan, build_plan, plan_from_json, plan_to_json, remove_all, write_plan
from cc.core.release.links.apply import BLOCK_BEGIN, CODEX_BUDGET_BYTES
from cc.core.release.links.plan import FRAMEWORK_RULES_IMPORT


def skill(base: Path, rel: str, name: str, desc: str = "d") -> None:
    d = base / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\nbody\n")


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def release(home):
    rel = layout.release_dir("20261106T000000Z-aaa", home)
    ks = Path("03-ai-enabling/01-skills")
    skill(rel / "knowledge/foundation" / ks, "cat/shared", "shared", "foundation version")
    skill(rel / "knowledge/foundation" / ks, "cat/found-only", "found-only", "abcde")
    skill(rel / "knowledge/organization" / ks, "shared", "shared", "org version")
    skill(rel / "knowledge/personal" / ks, "mine", "mine")
    skill(rel / "knowledge/personal" / ks, "_archive/old", "old")
    skill(rel / "claude-copilot/.claude/skills", "architecture", "architecture", "fw")
    skill(rel / "codex-copilot/plugins/codex-copilot/skills", "architecture", "architecture")
    ag = rel / "claude-copilot/.claude/agents"
    (ag / "_shared").mkdir(parents=True)
    (ag / "_shared/work-lifecycle.md").write_text("wl")
    (ag / "me.md").write_text("me")
    (ag / "manifest.json").write_text("{}")
    cm = rel / "claude-copilot/.claude/commands"
    cm.mkdir(parents=True)
    (cm / "map.md").write_text("map")
    (cm / "protocol.md").write_text("protocol")
    (rel / "claude-copilot/templates").mkdir(parents=True)
    (rel / "claude-copilot/templates/framework-rules.md").write_text("rules")
    (rel / layout.CODEX_AGENTS_BLOCK_NAME).write_text("framework block\n")
    cur = layout.current_path(home)
    cur.parent.mkdir(parents=True, exist_ok=True)
    cur.symlink_to(rel)
    return rel


def link_names(plan, runtime, kind):
    return {e.name for e in plan.entries if e.runtime == runtime and e.kind == kind}


def test_all_content_both_runtimes(home, release):
    plan = build_plan(release, home)
    assert link_names(plan, "claude", "skill") == {"shared", "found-only", "mine", "architecture"}
    # codex plugin already serves 'architecture': avoided, with a warning
    assert link_names(plan, "codex", "skill") == {"shared", "found-only", "mine"}
    assert any("architecture" in w for w in plan.warnings)
    assert link_names(plan, "claude", "agent") == {"me.md", "_shared"}
    assert link_names(plan, "claude", "command") == {"map.md", "protocol.md"}


def test_nearest_tier_wins_and_shadow_reported(home, release):
    plan = build_plan(release, home)
    shared = next(e for e in plan.entries if e.name == "shared" and e.runtime == "claude")
    assert shared.source == "knowledge/organization"
    assert any(s["name"] == "shared" and s["shadowed"] == "knowledge/foundation" for s in plan.shadowed)


def test_targets_go_through_current(home, release):
    plan = build_plan(release, home)
    current = str(layout.current_path(home))
    assert plan.entries and all(e.target.startswith(current + "/") for e in plan.entries)
    assert not any(".worktrees" in e.target for e in plan.entries)
    assert not any("releases" in e.target for e in plan.entries)


def test_apply_resolves_and_flip_changes_content_without_relinking(home, release):
    apply_plan(build_plan(release, home), home)
    link = home / ".claude/skills/shared"
    assert link.is_symlink() and "org version" in (link / "SKILL.md").read_text()
    assert (home / ".claude/agents/_shared/work-lifecycle.md").read_text() == "wl"
    # second release, flip the pointer: same link, new content
    rel2 = release.with_name("20261106T010000Z-bbb")
    os.system(f"cp -R '{release}' '{rel2}'")
    (rel2 / "knowledge/organization/03-ai-enabling/01-skills/shared/SKILL.md").write_text(
        "---\nname: shared\ndescription: v2\n---\n")
    before = os.readlink(link)
    tmp = layout.current_path(home).with_name("cur.tmp")
    tmp.symlink_to(rel2)
    os.replace(tmp, layout.current_path(home))
    assert os.readlink(link) == before and "v2" in (link / "SKILL.md").read_text()


def test_idempotent(home, release):
    plan = build_plan(release, home)
    first = apply_plan(plan, home)
    assert first.created and first.ok
    second = apply_plan(plan, home)
    assert not second.created and not second.updated and not second.removed
    assert len(second.unchanged) == len(first.created)


def test_never_clobbers_owner_items(home, release):
    owner_dir = home / ".claude/skills/mine"
    owner_dir.mkdir(parents=True)
    (owner_dir / "SKILL.md").write_text("owner")
    owner_link = home / ".claude/agents/me.md"
    owner_link.parent.mkdir(parents=True)
    owner_link.symlink_to("/elsewhere")
    report = apply_plan(build_plan(release, home), home)
    assert {s["path"] for s in report.skipped} >= {".claude/skills/mine", ".claude/agents/me.md"}
    assert (owner_dir / "SKILL.md").read_text() == "owner"
    assert os.readlink(owner_link) == "/elsewhere"
    # a second run must not adopt them either
    again = apply_plan(build_plan(release, home), home)
    assert {s["path"] for s in again.skipped} >= {".claude/skills/mine"}


def test_stale_links_removed_only_if_ours(home, release):
    plan = build_plan(release, home)
    apply_plan(plan, home)
    owner = home / ".claude/skills/owner-skill"
    owner.mkdir()
    import shutil
    shutil.rmtree(release / "knowledge/personal/03-ai-enabling/01-skills/mine")
    report = apply_plan(build_plan(release, home), home)
    assert ".claude/skills/mine" in report.removed and ".codex/skills/mine" in report.removed
    assert not (home / ".claude/skills/mine").is_symlink() and owner.is_dir()


def test_stale_link_modified_by_owner_left(home, release):
    apply_plan(build_plan(release, home), home)
    mine = home / ".claude/skills/mine"
    mine.unlink()
    mine.symlink_to("/owner/choice")
    import shutil
    shutil.rmtree(release / "knowledge/personal/03-ai-enabling/01-skills/mine")
    report = apply_plan(build_plan(release, home), home)
    assert os.readlink(mine) == "/owner/choice"
    assert any(s["path"] == ".claude/skills/mine" for s in report.skipped)


def test_claude_md_import_added_once_owner_text_unchanged(home, release):
    md = home / ".claude/CLAUDE.md"
    md.parent.mkdir(parents=True)
    owner = "# Mine\nno trailing newline"
    md.write_text(owner)
    plan = build_plan(release, home)
    apply_plan(plan, home)
    text = md.read_text()
    assert text.startswith(owner) and text.count(FRAMEWORK_RULES_IMPORT) == 1
    apply_plan(plan, home)
    assert md.read_text() == text
    remove_all(home)
    assert md.read_text() == owner


def test_codex_block_budget_and_owner_text(home, release):
    agents = home / ".codex/AGENTS.md"
    agents.parent.mkdir(parents=True)
    owner = "# Global\n\nrules\n"
    agents.write_text(owner)
    plan = build_plan(release, home)
    report = apply_plan(plan, home)
    text = agents.read_text()
    assert report.agents_md == "added" and text.startswith(owner) and text.count(BLOCK_BEGIN) == 1
    assert report.codex_combined_bytes == len(text.encode()) and report.codex_budget_bytes == 32768
    plan.agents_block = "changed\n"
    assert apply_plan(plan, home).agents_md == "updated"
    assert agents.read_text().count(BLOCK_BEGIN) == 1 and agents.read_text().startswith(owner)
    remove_all(home)
    assert agents.read_text() == owner


def test_codex_block_over_budget_not_written(home, release):
    agents = home / ".codex/AGENTS.md"
    agents.parent.mkdir(parents=True)
    agents.write_text("x" * (CODEX_BUDGET_BYTES - 10))
    report = apply_plan(build_plan(release, home), home)
    assert not report.ok and report.agents_md == "over-budget"
    assert agents.read_text() == "x" * (CODEX_BUDGET_BYTES - 10)


def test_reports_description_chars_and_project_collisions(home, release, tmp_path):
    proj = tmp_path / "proj"
    skill(proj / ".claude/skills", "shared", "shared")
    skill(proj / ".agents/skills", "mine", "mine")
    plan = build_plan(release, home, project_roots=[proj])
    report = apply_plan(plan, home)
    assert report.description_chars["claude"] > report.description_chars["codex"] > 0
    pairs = {(c["runtime"], c["name"]) for c in report.project_collisions}
    assert pairs == {("claude", "shared"), ("codex", "mine")}


def test_commands_emitted_as_skills_when_overridable(home, release):
    plan = build_plan(release, home, command_skill_names={"map"})
    assert "map.md" not in link_names(plan, "claude", "command")
    apply_plan(plan, home)
    assert "/map" in (home / ".claude/skills/map/SKILL.md").read_text()
    assert (home / ".codex/skills/map/SKILL.md").is_file()
    assert not (home / ".claude/commands/map.md").exists()


def test_worktree_backed_tier_is_skipped(home, tmp_path):
    rel = layout.release_dir("20261106T000000Z-ccc", home)
    wt = tmp_path / ".worktrees" / "live"
    skill(wt / "03-ai-enabling/01-skills", "bad", "bad")
    (rel / "knowledge").mkdir(parents=True)
    (rel / "knowledge/personal").symlink_to(wt)
    plan = build_plan(rel, home)
    assert not plan.entries and any(".worktrees" in w for w in plan.warnings)


def test_plan_json_roundtrip_and_receipt(home, release):
    plan = build_plan(release, home)
    path = write_plan(plan, release)
    assert path.name == layout.LINK_PLAN_NAME
    back = plan_from_json(plan_to_json(plan))
    assert back.entries == plan.entries
    apply_plan(back, home)
    assert layout.links_receipt_path(home).is_file()
    remove_all(home)
    assert not (home / ".claude/skills/shared").is_symlink()
    assert not layout.links_receipt_path(home).exists()


def test_framework_rules_template_ships():
    root = Path(__file__).resolve().parents[4]
    text = (root / "templates/framework-rules.md").read_text()
    assert "{{" not in text and "No time estimates" in text and "~/.claude/agents/_shared/work-lifecycle.md" in text
