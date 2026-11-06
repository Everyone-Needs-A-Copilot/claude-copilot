"""Source-repo guard: a release component's own files are never planned for removal."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cc.core.project_migrate import Known, apply_migration, plan_migration
from cc.core.project_migrate.source_guard import SOURCE_LABEL, build_guard, live_link_targets
from tests.project_migrate.conftest import _w, build_project, make_known, sha, tree_state

COMPONENTS = {
    "claude-copilot": "claude-copilot", "codex-copilot": "codex-copilot", "cli-copilot": "cli-copilot",
    "product-creation-copilot": "product-creation-copilot", "knowledge-copilot-internal": "knowledge/organization",
    "codex-copilot-internal": "codex/organization", "cli-copilot-internal": "cli/organization",
}


def release(tmp: Path, repos: Path, links: list[dict] | None = None) -> Path:
    rel = tmp / "current"
    comps = []
    for repo, name in COMPONENTS.items():
        (rel / name).mkdir(parents=True, exist_ok=True)
        comps.append({"name": name, "path": name, "source": str(repos / repo), "tier": "x"})
    (rel / "release.json").write_text(json.dumps({"components": comps}))
    (rel / "links.json").write_text(json.dumps({"entries": links or []}))
    return rel


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    repos = tmp_path / "repos"
    repos.mkdir()
    return tmp_path, repos


def source_repo(repos: Path, name: str, own: dict[str, bytes]) -> tuple[Path, Known]:
    root = build_project(repos, name, git=False)
    known = make_known()
    for rel, data in own.items():
        _w(root, rel, data)
        known.file_hashes[rel] = {sha(data)}  # the index treats the repo's own file as a framework copy
    return root, known


def removed(plan) -> set[str]:
    return {a.path for a in plan.actions if a.kind in ("delete", "unlink")}


def kept_as_source(plan) -> set[str]:
    return {k.path for k in plan.keeps if k.reason.startswith(SOURCE_LABEL)}


def test_claude_copilot_only_locks_are_removable(env):
    tmp, repos = env
    root, known = source_repo(repos, "claude-copilot", {"plugins/codex-copilot/skills/me/SKILL.md": b"me\n"})
    rel = release(tmp, repos)
    plan = plan_migration(root, known=known, release_dir=rel, allow_missing_codex=True)
    assert plan.source_repo
    assert removed(plan) == {"copilot.lock.json", ".codex-copilot.json"}
    assert {".claude/skills/codex-copilot", ".claude/fitness-check.sh", "scripts/copilot-gate.sh",
            "plugins/codex-copilot/skills/me/SKILL.md", ".claude/settings.json", ".mcp.json"} <= kept_as_source(plan)
    assert not [a for a in plan.actions if a.kind in ("edit-json", "edit-text")]


def test_claude_copilot_apply_removes_locks_writes_marker_only(env):
    tmp, repos = env
    root, known = source_repo(repos, "claude-copilot", {})
    rel = release(tmp, repos)
    before = tree_state(root)
    apply_migration(root, known=known, release_dir=rel, allow_missing_codex=True, backup_root=tmp / "bk",
                    codex_config=tmp / "codex.toml", registry=tmp / "reg.json")
    after = tree_state(root)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {"copilot.lock.json", ".codex-copilot.json", "copilot.project.json"}
    assert not (tmp / "codex.toml").exists()
    assert (root / ".claude/skills/codex-copilot").is_symlink()


@pytest.mark.parametrize("name,own,drop", [
    ("cli-copilot", ["scripts/e2e.sh", ".claude/skills/skill-authoring/SKILL.md", ".claude/rules/r.md"], ".claude/agents/me.md"),
    ("cli-copilot-internal", [".claude/skills/new-service/SKILL.md", ".claude/rules/r.md"], ".claude/agents/qa.md"),
    ("product-creation-copilot", [".claude/rules/facilitation.md", "scripts/preflight.sh"], ".claude/agents/ta.md"),
    ("knowledge-copilot-internal", [".claude/extensions/do.extension.md", ".claude/rules/r.md"], ".claude/commands/pause.md"),
    ("codex-copilot-internal", ["plugins/codex-copilot-internal/skills/x/SKILL.md"], ".claude/commands/continue.md"),
])
def test_named_source_repos_keep_their_own_paths(env, name, own, drop):
    tmp, repos = env
    root, known = source_repo(repos, name, {p: f"own {p}\n".encode() for p in own})
    plan = plan_migration(root, known=known, release_dir=release(tmp, repos), allow_missing_codex=True)
    assert set(own) <= kept_as_source(plan)
    assert not removed(plan) & set(own)
    assert drop in removed(plan)  # a synced copy outside the protected paths still goes


def test_control_tower_fixtures_are_protected_by_name(env):
    tmp, repos = env
    root, known = source_repo(repos, "copilot-control-tower", {"scripts/tests/fixtures/workspaces/a.json": b"{}\n"})
    plan = plan_migration(root, known=known, release_dir=release(tmp, repos), allow_missing_codex=True)
    assert "scripts/tests/fixtures/workspaces/a.json" in kept_as_source(plan)
    assert ".claude/agents/ta.md" in removed(plan)


def test_edited_lock_copies_of_a_source_repo_are_consumer_copies(env):
    tmp, repos = env
    root, known = source_repo(repos, "codex-copilot-internal", {})
    (root / ".claude/agents/ta.md").write_text("---\nname: ta\n---\nolder fan-out text\n")
    plan = plan_migration(root, known=known, release_dir=release(tmp, repos), allow_missing_codex=True)
    assert ".claude/agents/ta.md" in removed(plan)
    assert ".claude/agents/ta.md" not in {h.path for h in plan.holds}
    plain = build_project(repos, "other", git=False)
    (plain / ".claude/agents/ta.md").write_text("---\nname: ta\n---\nolder fan-out text\n")
    assert ".claude/agents/ta.md" in {h.path for h in plan_migration(plain, known=known, release_dir=release(tmp, repos),
                                                                      allow_missing_codex=True).holds}


def test_live_link_target_is_protected(env):
    tmp, repos = env
    root, known = source_repo(repos, "codex-copilot-internal", {"extra/tool.md": b"tool\n"})
    rel = release(tmp, repos)
    (rel / "codex/organization/extra").mkdir()
    (rel / "codex/organization/extra/tool.md").write_text("tool\n")
    link = {"target": f"{tmp}/home/.copilot/current/codex/organization/extra/tool.md"}
    (rel / "links.json").write_text(json.dumps({"entries": [link]}))
    assert "extra/tool.md" in live_link_targets(rel)["codex/organization"]
    guard = build_guard(root, rel)
    assert guard.protects("extra/tool.md") and not guard.protects("extra/other.md")


def test_bridge_resolved_through_a_link_is_protected(env):
    tmp, repos = env
    rel = release(tmp, repos)
    skills = rel / "claude-copilot/plugins/codex-copilot/skills/me"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("me\n")
    (rel / "claude-copilot/.claude/skills").mkdir(parents=True)
    (rel / "claude-copilot/.claude/skills/codex-copilot").symlink_to("../../plugins/codex-copilot/skills")
    link = {"target": f"{tmp}/h/.copilot/current/claude-copilot/.claude/skills/codex-copilot/me"}
    (rel / "links.json").write_text(json.dumps({"entries": [link]}))
    found = live_link_targets(rel)["claude-copilot"]
    assert {".claude/skills/codex-copilot/me", "plugins/codex-copilot/skills/me"} <= found


def test_project_declared_protected_paths(env):
    tmp, repos = env
    root = build_project(repos, "plainrepo", git=False)
    known = make_known()
    plan = plan_migration(root, known=known, release_dir=release(tmp, repos), allow_missing_codex=True)
    assert ".claude/fitness-check.sh" in removed(plan) and not plan.source_repo
    marker = json.loads((root / "copilot.project.json").read_text())
    marker["protectedPaths"] = [".claude/fitness-check.sh", "scripts/*"]
    (root / "copilot.project.json").write_text(json.dumps(marker))
    plan = plan_migration(root, known=known, release_dir=release(tmp, repos), allow_missing_codex=True)
    assert {".claude/fitness-check.sh", "scripts/copilot-gate.sh"} <= kept_as_source(plan)
    assert ".claude/fitness-check.sh" not in removed(plan)


def test_explicit_source_repo_mode_touches_consumer_artefacts_and_marker_only(env):
    tmp, repos = env
    root = build_project(repos, "mystery", git=False)
    known = make_known()
    rel = release(tmp, repos)
    assert not plan_migration(root, known=known, release_dir=rel, allow_missing_codex=True).source_repo
    plan = plan_migration(root, known=known, release_dir=rel, allow_missing_codex=True, source_repo=True)
    assert plan.source_repo and not [a for a in plan.actions if a.kind in ("edit-json", "edit-text")]
    assert [a.path for a in plan.actions if a.kind == "write"] == ["copilot.project.json"]
    claude_md = (root / "CLAUDE.md").read_bytes()
    apply_migration(root, known=known, release_dir=rel, allow_missing_codex=True, source_repo=True,
                    backup_root=tmp / "bk", codex_config=tmp / "c.toml", registry=tmp / "r.json")
    assert (root / "CLAUDE.md").read_bytes() == claude_md
    assert not (root / "copilot.lock.json").exists() and not (tmp / "c.toml").exists()


def test_scan_reports_protected_separately(env):
    tmp, repos = env
    from cc.core.project_migrate import scan_project

    root, known = source_repo(repos, "cli-copilot", {"scripts/own.sh": b"own\n"})
    row = scan_project(root, known, release(tmp, repos))
    assert "scripts/own.sh" not in row["copied_paths"] and row["protected"] >= 1


# -- real source repos, read-only ------------------------------------------------------------------
REAL = Path("/Volumes/Dev/Sites/CSE")
RELEASE = Path.home() / ".copilot" / "current"
REAL_REPOS = ["claude-copilot", "codex-copilot", "cli-copilot", "cli-copilot-internal", "copilot-control-tower",
              "product-creation-copilot", "knowledge-copilot-internal", "codex-copilot-internal"]
needs_real = pytest.mark.skipif(not (RELEASE / "release.json").is_file() or not all((REAL / r).is_dir() for r in REAL_REPOS),
                                reason="needs the installed release and the real source repos")


@needs_real
def test_release_link_plan_unchanged_by_migrating_every_source_repo():
    from cc.core.release.links.plan import build_plan, plan_to_json

    def link_plan() -> bytes:
        return json.dumps(plan_to_json(build_plan(RELEASE.resolve())), sort_keys=True).encode()

    before = link_plan()
    links = live_link_targets(RELEASE)
    manifest = json.loads((RELEASE / "release.json").read_text())
    paths = {c["source"]: c["path"] for c in manifest["components"]}
    for repo in REAL_REPOS:
        plan = plan_migration(REAL / repo, allow_missing_codex=True, release_dir=RELEASE)
        assert plan.source_repo, repo
        comp = paths.get(str(REAL / repo))
        for rel in removed(plan):
            assert not any(rel == p or rel.startswith(p + "/") for p in links.get(comp, ())), (repo, rel)
        if repo in ("claude-copilot", "codex-copilot"):
            assert removed(plan) <= {"copilot.lock.json", ".codex-copilot.json"}, repo
    assert link_plan() == before


@needs_real
def test_real_claude_copilot_keeps_the_codex_skill_bridge():
    plan = plan_migration(REAL / "claude-copilot", allow_missing_codex=True, release_dir=RELEASE)
    assert removed(plan) == {"copilot.lock.json", ".codex-copilot.json"}
    assert ".claude/skills/codex-copilot" in kept_as_source(plan)
