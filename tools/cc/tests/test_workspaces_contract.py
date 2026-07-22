from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cc.commands import workspaces as workspaces_command
from cc.core.ecosystem.workspaces import (
    ActivationError,
    activate_components,
    associate_personal_project,
    discover_workspaces,
    project_id,
    read_personal_registry,
    workspace_status,
    write_declaration,
    write_install_lock,
)


def _git_init(path: Path, remote: str | None = None) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)


def test_discovery_finds_unconfigured_git_repositories_without_following_symlinks(tmp_path):
    root = tmp_path / "approved"
    configured = root / "team" / "configured"
    unconfigured = root / "new-clone"
    _git_init(configured)
    _git_init(unconfigured)
    write_declaration(configured, ("claude",))
    (root / "loop").symlink_to(root)

    assert discover_workspaces(roots=[root], registry=tmp_path / "missing.json") == [
        unconfigured.resolve(),
        configured.resolve(),
    ]


def test_no_roots_means_no_implicit_machine_scan(monkeypatch, tmp_path):
    monkeypatch.setattr("cc.core.ecosystem.workspaces.resolve_key", lambda key: [] if key == "projects.roots" else str(tmp_path / "missing.json"))
    assert discover_workspaces() == []


def test_status_distinguishes_shared_declaration_from_real_installation(tmp_path):
    project = tmp_path / "project"
    registry = tmp_path / "personal.json"
    _git_init(project, "git@github.com:Example/Widget.git")
    write_declaration(project, ("claude", "codex"))

    report = workspace_status(project, personal_registry=registry, which=lambda _name: None)
    assert report["state"] == "activation-required"
    assert report["declared_components"] == ["claude", "codex"]
    assert report["installed_components"] == []
    assert report["recommended_components"] == ["claude", "codex"]


def test_explicit_markers_are_ready_and_arbitrary_claude_folder_is_not(tmp_path):
    arbitrary = tmp_path / "arbitrary"
    ready = tmp_path / "ready"
    _git_init(arbitrary)
    _git_init(ready)
    (arbitrary / ".claude").mkdir()
    (arbitrary / ".claude/notes.md").write_text("mine")
    (ready / ".claude/commands").mkdir(parents=True)
    (ready / ".claude/commands/protocol.md").write_text("framework")
    (ready / ".mcp.json").write_text("{}")

    assert workspace_status(arbitrary, personal_registry=tmp_path / "a.json")["state"] == "setup-available"
    assert workspace_status(ready, personal_registry=tmp_path / "b.json")["state"] == "ready"


def test_project_identity_is_stable_across_github_transport_and_never_exposes_remote(tmp_path):
    ssh = tmp_path / "ssh"
    https = tmp_path / "https"
    _git_init(ssh, "git@github.com:Example/Widget.git")
    _git_init(https, "https://user:token@github.com/example/widget.git")

    assert project_id(ssh) == project_id(https)
    report = workspace_status(https, personal_registry=tmp_path / "personal.json")
    serialized = json.dumps(report)
    assert "token" not in serialized
    assert "github.com" not in serialized


def test_personal_association_stores_only_opaque_key_and_components(tmp_path):
    registry = tmp_path / "personal-projects.json"
    key = "sha256:" + "a" * 64
    associate_personal_project(key, ("claude",), registry=registry)
    payload = read_personal_registry(registry)

    assert payload == {
        "schema_version": "1.0",
        "projects": {key: {"components": ["claude"]}},
    }
    assert "path" not in registry.read_text()
    assert "remote" not in registry.read_text()


def test_local_only_project_never_gets_fabricated_portable_identity(tmp_path):
    project = tmp_path / "local"
    _git_init(project)
    report = workspace_status(project, personal_registry=tmp_path / "personal.json")
    assert report["project_id"] is None
    assert report["personal_profile"]["state"] == "local-only"


def test_activation_installs_both_products_and_only_then_becomes_ready(tmp_path):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Activation.git")
    repo_parent = Path(__file__).resolve().parents[4]
    claude_root = repo_parent / "claude-copilot"
    codex_root = repo_parent / "codex-copilot"

    activated = activate_components(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_install_lock(
        project,
        ("claude", "codex"),
        claude_root=claude_root,
        codex_root=codex_root,
    )
    write_declaration(project, ("claude", "codex"))
    report = workspace_status(project, personal_registry=tmp_path / "personal.json")

    assert activated == ["codex", "claude"]
    assert report["state"] == "ready"
    assert report["installed_components"] == ["claude", "codex"]
    assert (project / "AGENTS.md").is_file()
    assert (project / "CLAUDE.md").is_file()
    lock = json.loads((project / "copilot.lock.json").read_text())
    assert [entry["component"] for entry in lock["components"]] == ["claude", "codex"]
    assert all(entry["files"] for entry in lock["components"])
    assert all(
        file["checksum"].startswith("sha256:")
        for entry in lock["components"]
        for file in entry["files"]
    )


def test_activation_collision_blocks_before_any_selected_product_writes(tmp_path):
    project = tmp_path / "project"
    _git_init(project)
    (project / "AGENTS.md").write_text("project-owned")
    repo_parent = Path(__file__).resolve().parents[4]

    try:
        activate_components(
            project,
            ("claude", "codex"),
            claude_root=repo_parent / "claude-copilot",
            codex_root=repo_parent / "codex-copilot",
        )
    except ActivationError:
        pass
    else:
        raise AssertionError("collision should block activation")

    assert (project / "AGENTS.md").read_text() == "project-owned"
    assert not (project / "CLAUDE.md").exists()
    assert not (project / ".codex-copilot.json").exists()


def test_root_approval_is_explicit_idempotent_and_returns_only_display_name(monkeypatch, capsys, tmp_path):
    selected = tmp_path / "Projects"
    selected.mkdir()
    written = []
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda key, value: written.append((key, value)),
    )

    workspaces_command.approve_root(
        path=str(selected), apply=True, output_json=True
    )
    payload = json.loads(capsys.readouterr().out)

    assert written == [("projects.roots", str(selected.resolve()))]
    assert payload["result"] == "applied"
    assert payload["root"]["name"] == "Projects"
    assert str(selected.parent) not in json.dumps(payload)


def test_root_approval_refuses_symlink_without_writing(monkeypatch, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not write")),
    )

    try:
        workspaces_command.approve_root(path=str(link), apply=True, output_json=True)
    except SystemExit:
        pass
    except Exception as exc:
        # Typer raises its own Exit type rather than built-in SystemExit when
        # command functions are called directly.
        assert exc.__class__.__name__ == "Exit"
    else:
        raise AssertionError("symlink root should be blocked")
