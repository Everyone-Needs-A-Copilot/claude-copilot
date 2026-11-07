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
    assert link_names(plan, "claude", "agent") == {"me.md", "_shared", "manifest.json"}  # manifest.json: framework artifact, linked since round 4
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


def test_receipt_accounts_for_owner_items_shadowing_planned_links(home, release):
    import json

    from cc.core.release.links import adopt

    for name in ("infographics", "data-visualization"):
        skill(release / "knowledge/organization/03-ai-enabling/01-skills", name, name)
    owner_paths = (".claude/skills/infographics", ".codex/skills/infographics",
                   ".codex/skills/data-visualization")
    for rel in owner_paths:
        skill(home, rel, Path(rel).name, "owner version")
    plan = build_plan(release, home)
    before = {rel: (home / rel / "SKILL.md").read_bytes() for rel in owner_paths}
    for _ in range(2):
        report = apply_plan(plan, home)
        assert report.ok
        receipt = json.loads(layout.links_receipt_path(home).read_text())
        kept = {row["path"]: row for row in receipt["kept"]}
        served = {row["path"] for row in receipt["links"]}
        assert {entry.link for entry in plan.entries} == served | set(owner_paths)
        assert set(owner_paths) <= kept.keys()
        for rel in owner_paths:
            assert kept[rel]["origin"] == "owner"
            assert "shadows a planned release link" in kept[rel]["reason"]
            assert not (home / rel).is_symlink()
            assert (home / rel / "SKILL.md").read_bytes() == before[rel]
    # Inventory must also cover an owner replacement of a formerly receipt-owned path.
    rows = receipt["links"]
    rows.append({"path": owner_paths[0], "target": "former-release-target"})
    layout.links_receipt_path(home).write_text(json.dumps(receipt))
    assert owner_paths[0] in {row["path"] for row in apply_plan(plan, home).kept}
    assert set(owner_paths) <= {row["path"] for row in adopt.inventory_kept(plan, home, served)}


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


def test_crlf_owner_text_preserved_byte_identical(home, release):
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    cmd = home / ".claude/CLAUDE.md"
    agm = home / ".codex/AGENTS.md"
    cmd.write_bytes(b"owner one\r\nowner two\r\n")
    agm.write_bytes(b"codex owner\r\nline\r\n")
    plan = build_plan(release, home)
    apply_plan(plan, home)
    c = cmd.read_bytes()
    a = agm.read_bytes()
    assert c.startswith(b"owner one\r\nowner two\r\n")
    assert c.endswith(FRAMEWORK_RULES_IMPORT.encode() + b"\r\n")
    assert b"\n" not in c.replace(b"\r\n", b"")
    assert a.startswith(b"codex owner\r\nline\r\n")
    assert b"\n" not in a.replace(b"\r\n", b"")
    # second run is idempotent; removal restores the owner bytes exactly
    apply_plan(plan, home)
    assert cmd.read_bytes() == c and agm.read_bytes() == a
    remove_all(home)
    assert cmd.read_bytes() == b"owner one\r\nowner two\r\n"
    assert agm.read_bytes() == b"codex owner\r\nline\r\n"


def test_symlinked_memory_files_edited_in_place_link_intact(home, release, tmp_path):
    (home / ".claude").mkdir()
    (home / ".codex").mkdir()
    real_c = tmp_path / "dotfiles/CLAUDE.md"
    real_a = tmp_path / "dotfiles/AGENTS.md"
    real_c.parent.mkdir()
    real_c.write_text("mine\n")
    real_a.write_text("codex mine\n")
    (home / ".claude/CLAUDE.md").symlink_to(real_c)
    (home / ".codex/AGENTS.md").symlink_to(real_a)
    apply_plan(build_plan(release, home), home)
    for link, real in (((home / ".claude/CLAUDE.md"), real_c), ((home / ".codex/AGENTS.md"), real_a)):
        assert link.is_symlink() and Path(os.readlink(link)) == real
    assert real_c.read_text().startswith("mine\n") and FRAMEWORK_RULES_IMPORT in real_c.read_text()
    assert BLOCK_BEGIN in real_a.read_text() and real_a.read_text().startswith("codex mine\n")


@pytest.mark.parametrize("bad", ["../../../escape", "a/b", "..", ".hidden", "x y", "/abs"])
def test_unsafe_skill_names_rejected_at_plan(home, release, bad):
    skill(release / "knowledge/personal/03-ai-enabling/01-skills", "evil", bad)
    plan = build_plan(release, home)
    assert all("escape" not in e.link and ".." not in e.link for e in plan.entries)
    assert not any(e.name == bad for e in plan.entries)
    assert any("unsafe" in w for w in plan.warnings)


def test_unsafe_link_in_plan_json_rejected_at_apply(home, release, tmp_path):
    from cc.core.release.links.plan import LinkEntry, LinkPlan
    plan = LinkPlan(release_id="r", entries=[
        LinkEntry("claude", "skill", "x", ".claude/skills/../../../escape", str(release), "s"),
        LinkEntry("claude", "skill", "y", "../outside", str(release), "s")])
    report = apply_plan(plan, home)
    assert not (home.parent / "escape").exists() and not (home.parent / "outside").is_symlink()
    assert not os.path.lexists(home.parent / "escape")
    assert len(report.skipped) == 2 and not report.ok


def test_framework_rules_text_matches_import_delivery():
    text = (Path(__file__).resolve().parents[4] / "templates/framework-rules.md").read_text()
    assert "~/.claude/rules" not in text
    assert "import line" in text and "~/.claude/CLAUDE.md" in text


def test_codex_root_level_skills_linked_for_both_runtimes(home, release):
    # Old expectation: root-level codex skills were codex-only (claude got them via claude-copilot's
    # plugins/codex-copilot bundle symlink). The bundle is retired (PRD-16), so claude takes them from the
    # codex-copilot component root as well.
    skill(release / "codex-copilot/skills", "codex-only", "codex-only")
    plan = build_plan(release, home)
    for runtime, rdir in (("codex", ".codex"), ("claude", ".claude")):
        assert "codex-only" in link_names(plan, runtime, "skill")
        entry = next(e for e in plan.entries if e.runtime == runtime and e.name == "codex-only")
        assert entry.link == f"{rdir}/skills/codex-only"
        assert entry.target.endswith("/current/codex-copilot/skills/codex-only")


REPO_ROOT = Path(__file__).resolve().parents[4]
LIVE_CLAUDE_SKILLS = Path(__file__).resolve().parents[1] / "fixtures/live-release-7-claude-skills.json"


def test_candidate_plan_keeps_every_live_release_7_claude_skill(home, tmp_path):
    import json
    import shutil

    live = json.loads(LIVE_CLAUDE_SKILLS.read_text())  # [[name, source]] captured from live release #7
    rel = layout.release_dir("20261106T000001Z-bbb", home)
    ks = Path("03-ai-enabling/01-skills")
    shutil.copytree(REPO_ROOT / ".claude/skills", rel / "claude-copilot/.claude/skills", symlinks=False)
    own = {p.name for p in (rel / "claude-copilot/.claude/skills").iterdir()}
    for name, source in live:
        if source == "claude-copilot":
            if name not in own:  # was served through the removed plugin bundle: codex-copilot root skills
                skill(rel / "codex-copilot/skills", name, name)
        elif source == "product-creation-copilot":
            skill(rel / source / "skills", name, name)
        elif source.startswith("knowledge/"):
            skill(rel / source / ks, name, name)
        else:
            skill(rel / source / "skills", name, name)
    plan = build_plan(rel, home)
    claude = {e.name for e in plan.entries if e.runtime == "claude" and e.kind == "skill"}
    assert {n for n, _ in live} <= claude
    assert len(plan.entries) >= len(live)
    for e in plan.entries:  # no dangling link in the candidate plan
        assert Path(e.target.replace(str(layout.current_path(home)), str(rel))).exists(), e.link


def test_tracked_skill_symlinks_do_not_dangle():
    import subprocess

    out = subprocess.run(["git", "ls-files", "-s", ".claude/skills"], cwd=REPO_ROOT, capture_output=True,
                         text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("120000"):
            path = REPO_ROOT / line.split("\t", 1)[1]
            assert path.exists(), f"dangling tracked symlink {path}"


# ---- adoption of framework-owned copies ----------------------------------------------------------

from cc.core.release.links import FrameworkIndex, classify  # noqa: E402


def _idx(*texts: str) -> FrameworkIndex:
    index = FrameworkIndex()
    for t in texts:
        index.add_bytes(t.encode(), "test")
    return index


def test_adopt_framework_copy_backs_up_and_links(home, release):
    agents = home / ".claude/agents"
    agents.mkdir(parents=True)
    (agents / "me.md").write_text("old me\r\n")          # old framework version, CRLF + no changes otherwise
    (home / ".claude/commands").mkdir(parents=True)
    (home / ".claude/commands/map.md").write_text("my map\n")  # owner-customized
    plan = build_plan(release, home)
    report = apply_plan(plan, home, adopt=_idx("old me\n"))
    link = agents / "me.md"
    assert link.is_symlink()
    assert [a["path"] for a in report.adopted] == [".claude/agents/me.md"]
    backup = Path(report.adopted[0]["backup"])
    assert backup.read_bytes() == b"old me\r\n"
    assert layout.copilot_home(home) / "rollback" / "adopted" in backup.parents
    assert not (home / ".claude/commands/map.md").is_symlink()
    [c] = report.customized
    assert (c["name"], c["path"]) == ("map.md", str(home / ".claude/commands/map.md"))
    assert "added" in c["diff"] and c["shadows"].endswith("commands/map.md")


def test_adopt_off_by_default_keeps_copy(home, release):
    (home / ".claude/agents").mkdir(parents=True)
    (home / ".claude/agents/me.md").write_text("old me\n")
    report = apply_plan(build_plan(release, home), home)
    assert not (home / ".claude/agents/me.md").is_symlink()
    assert report.adopted == [] and report.customized == []


def test_adopt_skill_dir_all_files_must_match(home, release):
    skills = home / ".claude/skills"
    for name, extra in (("shared", None), ("mine", "owner file")):
        d = skills / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: old\n---\nbody\n")
        (d / "__pycache__").mkdir()
        (d / "__pycache__/x.pyc").write_bytes(b"junk")
        if extra:
            (d / "notes.md").write_text(extra)
    index = _idx("---\nname: shared\ndescription: old\n---\nbody\n", "---\nname: mine\ndescription: old\n---\nbody\n")
    report = apply_plan(build_plan(release, home), home, adopt=index)
    assert (skills / "shared").is_symlink()
    assert (skills / "mine").is_dir() and not (skills / "mine").is_symlink()
    assert [c["name"] for c in report.customized] == ["mine"]
    assert "only in your copy" in report.customized[0]["diff"]


def test_adopt_category_folder_and_unrelated_ignored(home, release):
    skills = home / ".claude/skills"
    stale = "---\nname: architecture\ndescription: old\n---\nbody\n"
    (skills / "design/color").mkdir(parents=True)
    (skills / "design/color/SKILL.md").write_text(stale)
    (skills / "synced/x").mkdir(parents=True)
    (skills / "synced/x/SKILL.md").write_text("somebody else's")
    report = apply_plan(build_plan(release, home), home, adopt=_idx(stale))
    assert not (skills / "design").exists()
    assert (Path(report.adopted[0]["backup"]) / "color/SKILL.md").read_text() == stale
    assert (skills / "synced/x/SKILL.md").exists() and report.customized == []


def test_hidden_tool_managed_skill_folder_excluded(home, release):
    system = home / ".codex/skills/.system/architecture"
    system.mkdir(parents=True)
    (system / "SKILL.md").write_text("---\nname: architecture\n---\ncodex-managed\n")
    report = apply_plan(build_plan(release, home), home, adopt=True)
    assert (system / "SKILL.md").read_text().endswith("codex-managed\n")
    assert report.customized == [] and not any(".system" in a["path"] for a in report.adopted)


def test_adopt_dry_run_changes_nothing_and_classify_is_read_only(home, release):
    (home / ".claude/agents").mkdir(parents=True)
    (home / ".claude/agents/me.md").write_text("old me\n")
    plan = build_plan(release, home)
    result = classify(plan, home, _idx("old me\n"))
    assert [a.path for a in result.adopt] == [".claude/agents/me.md"]
    report = apply_plan(plan, home, dry_run=True, adopt=_idx("old me\n"))
    assert report.adopted and not (home / ".claude/agents/me.md").is_symlink()
    assert not (layout.copilot_home(home) / "rollback").exists()


def test_remove_all_restores_adopted_copy(home, release):
    (home / ".claude/agents").mkdir(parents=True)
    (home / ".claude/agents/me.md").write_text("old me\n")
    apply_plan(build_plan(release, home), home, adopt=_idx("old me\n"))
    remove_all(home)
    restored = home / ".claude/agents/me.md"
    assert not restored.is_symlink() and restored.read_text() == "old me\n"


def test_default_index_reads_git_history_and_lock_records(home, release, tmp_path):
    import subprocess
    repo = tmp_path / "fw"
    (repo / ".claude/agents").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    (repo / ".claude/agents/me.md").write_text("v1 me\n")
    run("add", "-A"); run("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "v1")
    (repo / ".claude/agents/me.md").write_text("v2 me\n")
    run("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qam", "v2")
    import hashlib
    record = hashlib.sha256(b"recorded content").hexdigest()
    (layout.copilot_home(home) / "framework-install.lock").write_text('{"x": {"sha256": "%s"}}' % record)
    from cc.core.release.links import default_index
    index = default_index(home, release, extra_repos=[repo])
    assert index.matches(b"v1 me\n") and index.matches(b"v2 me\r\n") and index.matches(b"recorded content")
    assert not index.matches(b"mine")


# ---- adoption of symlinks into covered checkouts -------------------------------------------------

def _dev_checkout(tmp_path: Path, name: str = "knowledge-dev") -> Path:
    repo = tmp_path / name
    skill(repo / "03-ai-enabling/01-skills", "cat/shared", "shared", "dev version")
    return repo


def test_symlink_into_covered_checkout_is_repointed_and_old_target_recorded(home, release, tmp_path):
    repo = _dev_checkout(tmp_path)
    old = repo / "03-ai-enabling/01-skills/cat/shared"
    link = home / ".claude/skills/shared"
    link.parent.mkdir(parents=True)
    link.symlink_to(old)
    index = FrameworkIndex()
    index.add_root(repo)
    plan = build_plan(release, home)
    report = apply_plan(plan, home, adopt=index)
    entry = next(e for e in plan.entries if e.link == ".claude/skills/shared")
    assert os.readlink(link) == entry.target
    [row] = [a for a in report.adopted if a["path"] == ".claude/skills/shared"]
    assert row["kind"] == "symlink" and row["old_target"] == str(old)
    saved = layout.links_receipt_path(home).read_text()
    assert str(old) in saved
    assert os.readlink(row["backup"]) == str(old)


def test_symlink_elsewhere_is_owner_content_kept_and_listed(home, release, tmp_path):
    other = tmp_path / "elsewhere" / "shared"
    skill(other.parent, "shared", "shared")
    link = home / ".claude/skills/shared"
    link.parent.mkdir(parents=True)
    link.symlink_to(other)
    index = FrameworkIndex()
    index.add_root(_dev_checkout(tmp_path))
    report = apply_plan(build_plan(release, home), home, adopt=index)
    assert os.readlink(link) == str(other)
    [c] = [c for c in report.customized if c["name"] == "shared"]
    assert str(other) in c["diff"] and not report.adopted


def test_symlink_into_a_worktree_of_a_covered_repo_is_adopted(home, release, tmp_path):
    import subprocess
    repo = _dev_checkout(tmp_path)
    run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",  # noqa: E731
                                     "-c", "commit.gpgsign=false", *a], check=True, capture_output=True)
    run("init", "-q"); run("add", "-A"); run("commit", "-qm", "x")
    wt = tmp_path / "wt"
    run("worktree", "add", "-q", str(wt), "-b", "side")
    link = home / ".claude/skills/shared"
    link.parent.mkdir(parents=True)
    link.symlink_to(wt / "03-ai-enabling/01-skills/cat/shared")
    manifest = layout.current_path(home) / layout.MANIFEST_NAME
    manifest.write_text('{"components": [{"source": "%s"}]}' % repo)
    from cc.core.release.links import default_index
    index = default_index(home, release)
    assert wt.resolve() in index.roots or wt in index.roots
    report = apply_plan(build_plan(release, home), home, adopt=index)
    assert link.is_symlink() and ".copilot" in os.readlink(link)
    assert [a["kind"] for a in report.adopted] == ["symlink"]


def test_codex_link_through_a_claude_link_follows_the_claude_decision(home, release, tmp_path):
    repo = _dev_checkout(tmp_path)
    claude = home / ".claude/skills/shared"
    codex = home / ".codex/skills/shared"
    claude.parent.mkdir(parents=True); codex.parent.mkdir(parents=True)
    claude.symlink_to(repo / "03-ai-enabling/01-skills/cat/shared")
    codex.symlink_to(claude)
    index = FrameworkIndex()
    index.add_root(repo)
    apply_plan(build_plan(release, home), home, adopt=index)
    assert ".copilot" in os.readlink(claude) and ".copilot" in os.readlink(codex)


def test_dry_run_symlink_adoption_changes_nothing(home, release, tmp_path):
    repo = _dev_checkout(tmp_path)
    link = home / ".claude/skills/shared"
    link.parent.mkdir(parents=True)
    old = repo / "03-ai-enabling/01-skills/cat/shared"
    link.symlink_to(old)
    index = FrameworkIndex()
    index.add_root(repo)
    report = apply_plan(build_plan(release, home), home, dry_run=True, adopt=index)
    assert report.adopted and os.readlink(link) == str(old)


def test_remove_all_restores_adopted_symlink_exactly(home, release, tmp_path):
    repo = _dev_checkout(tmp_path)
    link = home / ".claude/skills/shared"
    link.parent.mkdir(parents=True)
    old = repo / "03-ai-enabling/01-skills/cat/shared"
    link.symlink_to(old)
    index = FrameworkIndex()
    index.add_root(repo)
    apply_plan(build_plan(release, home), home, adopt=index)
    remove_all(home)
    assert os.readlink(link) == str(old)
