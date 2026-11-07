"""Central status and activation contracts; all reads/writes use private fixtures."""

from __future__ import annotations

import json
import tomllib

import pytest
from typer.testing import CliRunner

from cc.commands.project import project_app
from cc.core.project_init import InitError, init_project
from cc.core.project_init.marker import MARKER_FILENAME
from cc.core.project_init.sections import SECTION_BEGIN, SECTION_END
from cc.core.project_init.status import project_status


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path.resolve() / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("COPILOT_HOME", str(home / ".copilot"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    config = {"projects.roots": [], "projects.declined": False}
    monkeypatch.setattr("cc.core.config.resolve_key", lambda key: config.get(key))
    return home, config


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_status_init_status_is_read_only_and_preserves_owner_rules(tmp_path, isolated):
    project = tmp_path.resolve() / "project"
    project.mkdir()
    owner = b"# My project\nKeep this rule.\n"
    (project / "CLAUDE.md").write_bytes(owner)
    before = snapshot(tmp_path)
    row = project_status(project)["projects"][0]
    assert row["state"] == "needs-init" and row["can_initialize"]
    assert snapshot(tmp_path) == before
    initialized = CliRunner().invoke(project_app, ["init", str(project), "--json"])
    assert initialized.exit_code == 0, initialized.output
    assert json.loads(initialized.output)["runtimes"] == ["claude", "codex"]
    assert (project / "CLAUDE.md").read_bytes().startswith(owner)
    after_init = snapshot(tmp_path)
    status = CliRunner().invoke(project_app, ["status", str(project), "--json"])
    assert status.exit_code == 0, status.output
    row = json.loads(status.output)["projects"][0]
    assert row["state"] == "initialized" and not row["can_initialize"]
    assert row["runtimes"] == ["claude", "codex"] and row["issues"] == []
    assert "Machine health is checked separately" in row["detail"]
    assert snapshot(tmp_path) == after_init


@pytest.mark.parametrize("missing", ["marker", "section", "trust", "register"])
def test_missing_thin_state_requires_init_not_a_false_initialized(tmp_path, isolated, missing):
    home, _ = isolated
    project = tmp_path.resolve() / "project"
    project.mkdir()
    init_project(project)
    if missing == "marker":
        (project / MARKER_FILENAME).write_text("{}")
    elif missing == "section":
        (project / "AGENTS.md").write_text("# Owner rules\n")
    elif missing == "trust":
        (home / ".codex/config.toml").write_text("")
    else:
        (home / ".copilot/registered-projects.json").write_text('{"projects": []}')
    before = snapshot(tmp_path)
    row = project_status(project)["projects"][0]
    assert row["state"] == "needs-init" and row["can_initialize"]
    assert snapshot(tmp_path) == before
    init_project(project)
    assert project_status(project)["projects"][0]["state"] == "initialized"


@pytest.mark.parametrize("broken", ["marker", "register", "codex", "untrusted", "section", "end-only", "reversed-section"])
def test_corrupt_or_owner_decision_state_is_blocked_and_never_changed(tmp_path, isolated, broken):
    home, _ = isolated
    project = tmp_path.resolve() / "project"
    project.mkdir()
    init_project(project)
    if broken == "marker":
        (project / MARKER_FILENAME).write_text("invalid-json")
    elif broken == "register":
        (home / ".copilot/registered-projects.json").write_text('{"projects": ["/kept"], BROKEN')
    elif broken == "codex":
        (home / ".codex/config.toml").write_text("invalid = [toml")
    elif broken == "untrusted":
        (home / ".codex/config.toml").write_text(f'[projects."{project}"]\ntrust_level = "untrusted"\n')
    else:
        section = {"section": SECTION_BEGIN, "end-only": SECTION_END,
                   "reversed-section": f"{SECTION_END}\n{SECTION_BEGIN}"}[broken]
        (project / "CLAUDE.md").write_text(f"# Owner\n{section}\n")
    before = snapshot(tmp_path)
    result = CliRunner().invoke(project_app, ["status", str(project), "--json"])
    assert result.exit_code == 1, result.output
    row = json.loads(result.output)["projects"][0]
    assert row["state"] == "blocked" and not row["can_initialize"] and row["issues"]
    assert snapshot(tmp_path) == before
    if broken in {"register", "codex", "untrusted", "marker"}:
        with pytest.raises(InitError):
            init_project(project)
        assert snapshot(tmp_path) == before


def test_scoped_status_never_traverses_discovery_roots(tmp_path, isolated, monkeypatch):
    _, config = isolated
    project = tmp_path.resolve() / "only-project"
    project.mkdir()
    config["projects.roots"] = [str(tmp_path / "never-inspect")]
    def forbidden(*args, **kwargs):
        pytest.fail("a scoped status must not discover other projects")
    monkeypatch.setattr("cc.core.ecosystem.workspaces._scan_root", forbidden)
    monkeypatch.setattr("cc.core.ecosystem.workspaces.detect_candidate_roots", forbidden)
    result = project_status(project)
    assert [row["path"] for row in result["projects"]] == [str(project)]


def test_all_status_is_bounded_to_approved_and_registered_projects(tmp_path, isolated, monkeypatch):
    _, config = isolated
    approved = tmp_path.resolve() / "approved"
    approved.mkdir()
    included = approved / "one"
    included.mkdir()
    (included / ".git").mkdir()
    too_deep = approved / "a/b/c/d/project"
    too_deep.mkdir(parents=True)
    (too_deep / ".git").mkdir()
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    (outside / ".git").mkdir()
    (approved / "linked").symlink_to(outside, target_is_directory=True)
    registered = tmp_path.resolve() / "registered-plain-folder"
    registered.mkdir()
    init_project(registered)
    config["projects.roots"] = [str(approved)]
    def forbidden(*args, **kwargs):
        pytest.fail("status must not inspect home/candidate roots")
    monkeypatch.setattr("cc.core.ecosystem.workspaces.detect_candidate_roots", forbidden)
    before = snapshot(tmp_path)
    report = project_status(all_projects=True)
    assert {row["path"] for row in report["projects"]} == {str(included), str(registered)}
    assert report["discovery"]["state"] == "granted"
    assert snapshot(tmp_path) == before
    config["projects.roots"] = [str(approved / "linked")]
    blocked = project_status(all_projects=True)
    assert blocked["result"] == "blocked" and blocked["errors"]
    assert [row["path"] for row in blocked["projects"]] == [str(registered)]
    assert snapshot(tmp_path) == before


def test_decline_prevents_discovery_and_explicit_path_cannot_mix_with_all(tmp_path, isolated):
    _, config = isolated
    approved = tmp_path.resolve() / "approved"
    (approved / "project/.git").mkdir(parents=True)
    config.update({"projects.roots": [str(approved)], "projects.declined": True})
    assert project_status(all_projects=True)["projects"] == []
    result = CliRunner().invoke(project_app, ["status", str(approved), "--all", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["errors"]


def test_invalid_register_and_untrusted_preflight_before_first_project_write(tmp_path, isolated):
    home, _ = isolated
    project = tmp_path.resolve() / "new-project"
    project.mkdir()
    register = home / ".copilot/registered-projects.json"
    register.parent.mkdir()
    register.write_text("existing but invalid")
    before = snapshot(tmp_path)
    with pytest.raises(InitError) as exc:
        init_project(project)
    assert exc.value.code == "registry-invalid" and snapshot(tmp_path) == before
    register.write_text('{"projects": []}')
    codex = home / ".codex/config.toml"
    codex.parent.mkdir()
    codex.write_text(f'[projects."{project}"]\ntrust_level = "untrusted"\n')
    before = snapshot(tmp_path)
    with pytest.raises(InitError):
        init_project(project)
    assert snapshot(tmp_path) == before
    assert tomllib.loads(codex.read_text())["projects"][str(project)]["trust_level"] == "untrusted"
