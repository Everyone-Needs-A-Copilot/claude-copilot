"""Personal-tier items that duplicate framework files must not shadow a release; the kept list is complete."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cc.core.release.engine import layout
from cc.core.release.links import apply_plan, build_plan, plan_from_json, plan_to_json
from cc.core.release.links.plan import FRAMEWORK_AGENT_FILES

from .test_links import home, release, skill  # noqa: F401  (fixtures)


@pytest.fixture
def personal(release):
    """Personal overlay: qa.md/protocol.md copy the framework, me.md differs, mine.md is new."""
    fw = release / "claude-copilot/.claude"
    (fw / "agents/qa.md").write_text("qa v2\n")
    (fw / "commands/protocol.md").write_text("protocol v2\n")
    (fw / "agents/me.md").write_text("me v2\n")
    base = release / "claude/personal/.claude"
    (base / "agents").mkdir(parents=True)
    (base / "commands").mkdir(parents=True)
    (base / "agents/qa.md").write_text("qa v2\n")  # identical to the framework
    (base / "agents/me.md").write_text("my own me\n")  # genuinely different
    (base / "agents/mine.md").write_text("only mine\n")
    (base / "commands/protocol.md").write_text("protocol v2\n")
    return base


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def entry(plan, kind, name):
    return next(e for e in plan.entries if e.kind == kind and e.name == name and e.runtime == "claude")


def test_identical_personal_copy_loses_to_the_release(home, release, personal):
    plan = build_plan(release, home)
    assert entry(plan, "agent", "qa.md").source == "claude-copilot"
    assert entry(plan, "command", "protocol.md").source == "claude-copilot"
    stale = {(s["kind"], s["name"]): s for s in plan.stale_copies}
    assert set(stale) == {("agent", "qa.md"), ("command", "protocol.md")}
    assert stale[("agent", "qa.md")]["source"] == "claude/personal"


def test_stale_copy_of_an_older_framework_version_also_loses(home, release, personal, tmp_path):
    repo = tmp_path / "fw"
    (repo / ".claude/agents").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".claude/agents/qa.md").write_text("qa v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "v1")
    (release / "claude/personal/.claude/agents/qa.md").write_text("qa v1\n")
    plan = build_plan(release, home, framework_repos=[repo])
    assert entry(plan, "agent", "qa.md").source == "claude-copilot"
    assert any(s["name"] == "qa.md" for s in plan.stale_copies)
    plan = build_plan(release, home)  # without the history the v1 copy is just different content
    assert entry(plan, "agent", "qa.md").source == "claude/personal"


def test_different_personal_item_overrides_and_is_listed(home, release, personal):
    plan = build_plan(release, home)
    assert entry(plan, "agent", "me.md").source == "claude/personal"
    assert entry(plan, "agent", "mine.md").source == "claude/personal"
    overrides = {(o["kind"], o["name"]): o for o in plan.personal_overrides}
    assert overrides[("agent", "me.md")]["shadows"] == "claude-copilot"
    assert overrides[("agent", "mine.md")]["shadows"] == ""
    assert ("agent", "qa.md") not in overrides


def test_personal_skill_identical_to_framework_skill_loses(home, release):
    skill(release / "claude/personal/.claude/skills", "architecture", "architecture", "fw")
    plan = build_plan(release, home)
    assert entry(plan, "skill", "architecture").source == "claude-copilot"
    skill(release / "claude/personal/.claude/skills", "architecture", "architecture", "mine differs")
    plan = build_plan(release, home)
    assert entry(plan, "skill", "architecture").source == "claude/personal"
    assert any(o["name"] == "architecture" for o in plan.personal_overrides)


def test_plan_json_roundtrip_keeps_both_lists(home, release, personal):
    plan = build_plan(release, home)
    back = plan_from_json(json.loads(json.dumps(plan_to_json(plan))))
    assert back.stale_copies == plan.stale_copies and back.personal_overrides == plan.personal_overrides


def test_receipt_and_report_list_personal_overrides(home, release, personal):
    report = apply_plan(build_plan(release, home), home)
    assert {o["name"] for o in report.personal_overrides if o["kind"] == "agent"} == {"me.md", "mine.md"}
    assert any(o["name"] == "mine" and o["kind"] == "skill" for o in report.personal_overrides)  # knowledge/personal
    receipt = json.loads(layout.links_receipt_path(home).read_text())
    assert {o["name"] for o in receipt["personal_overrides"] if o["kind"] == "agent"} == {"me.md", "mine.md"}
    assert {s["name"] for s in receipt["stale_copies"]} == {"qa.md", "protocol.md"}


def test_framework_agent_artifacts_are_linked(home, release):
    assert {"manifest.json", "manifest.schema.json"} <= set(FRAMEWORK_AGENT_FILES)
    (release / "claude-copilot/.claude/agents/manifest.schema.json").write_text("{}")
    plan = build_plan(release, home)
    names = {e.name for e in plan.entries if e.kind == "agent"}
    assert {"manifest.json", "manifest.schema.json"} <= names


def test_kept_list_covers_every_unlisted_real_entry(home, release):
    claude, codex = home / ".claude", home / ".codex"
    for d in ("agents/_archive", "commands/_archive", "skills/my-owner-skill"):
        (claude / d).mkdir(parents=True)
    (claude / "skills/my-owner-skill/SKILL.md").write_text("---\nname: my-owner-skill\ndescription: d\n---\nmine\n")
    (claude / "commands/gdoc.md").write_text("mine\n")
    (codex / "skills/.system").mkdir(parents=True)
    (codex / "skills/report-infographics").mkdir()
    (codex / "skills/report-infographics/SKILL.md").write_text("---\nname: r\ndescription: d\n---\nmine\n")
    (codex / "skills/my-owner-skill").symlink_to(claude / "skills/my-owner-skill")
    report = apply_plan(build_plan(release, home), home, adopt=True)
    kept = {k["path"]: k for k in report.kept}
    assert kept[".claude/agents/_archive"]["origin"] == "framework-archive"
    assert kept[".claude/commands/_archive"]["origin"] == "framework-archive"
    assert kept[".claude/skills/my-owner-skill"]["origin"] == "owner"
    assert kept[".claude/commands/gdoc.md"]["origin"] == "owner"
    assert kept[".codex/skills/report-infographics"]["origin"] == "owner"
    assert kept[".codex/skills/my-owner-skill"]["origin"] == "owner"
    assert kept[".codex/skills/.system"]["origin"] == "tool-managed"
    assert not any(p.endswith(".DS_Store") for p in kept)
    receipt = json.loads(layout.links_receipt_path(home).read_text())
    assert {k["path"] for k in receipt["kept"]} == set(kept)


def test_framework_links_and_adopted_copies_are_not_kept(home, release):
    (home / ".claude/commands").mkdir(parents=True)
    (home / ".claude/commands/map.md").write_text("map")  # framework copy: adopted, not kept
    report = apply_plan(build_plan(release, home), home, adopt=True)
    assert report.kept == []


def test_doctor_lists_personal_overrides(home, release, personal):
    from cc.core.release.publish import links_check

    apply_plan(build_plan(release, home), home)
    checks = {c.name: c for c in links_check(home)(release)}
    assert "agent:me.md" in checks["personal-overrides"].detail and "agent:qa.md" not in checks["personal-overrides"].detail
