from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cc.commands import workspaces as workspaces_command
from cc.core.ecosystem.workspaces import (
    RECENTLY_SET_UP_WINDOW_HOURS,
    ActivationError,
    RevertError,
    activate_components,
    associate_personal_project,
    detect_candidate_roots,
    discover_workspaces,
    forget_root_grant,
    is_project_excluded,
    project_id,
    read_known_projects_registry,
    read_personal_registry,
    recently_set_up,
    record_automatic_setup,
    record_root_grant,
    revert_project,
    undo_status,
    workspace_status,
    write_declaration,
    write_install_lock,
)

from cc.core.ecosystem import workspaces as core_workspaces


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


def test_recommendations_use_gui_safe_executable_resolver(monkeypatch, tmp_path):
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(0o755)
    monkeypatch.setattr(
        core_workspaces,
        "resolve_executable",
        lambda command: claude if command == "claude" else None,
    )

    assert core_workspaces.recommended_components(tmp_path) == ["claude"]


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


def test_root_approval_is_explicit_idempotent_and_names_are_for_display(monkeypatch, capsys, tmp_path):
    selected = tmp_path / "Projects"
    selected.mkdir()
    written = []
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda key, value: written.append((key, value)),
    )
    monkeypatch.setattr(core_workspaces, "default_known_projects_registry", lambda: tmp_path / "known-projects.json")

    workspaces_command.approve_root(
        path=str(selected), apply=True, output_json=True
    )
    payload = json.loads(capsys.readouterr().out)

    assert written == [("projects.roots", str(selected.resolve()))]
    assert payload["result"] == "applied"
    assert payload["root"]["name"] == "Projects"
    # The path round-trips to the CLI (e.g. for forget-root) but is never the
    # thing the app renders -- `name` is.
    assert payload["root"]["path"] == str(selected.resolve())


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


# ---------------------------------------------------------------------------
# Candidate root detection ("always find the user's projects")
# ---------------------------------------------------------------------------


def test_detect_candidate_roots_finds_nothing_when_no_conventional_folder_has_a_project(monkeypatch, tmp_path):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    assert detect_candidate_roots() == []


def test_detect_candidate_roots_finds_several_conventional_folders(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    developer = home / "Developer"
    _git_init(developer / "widget")
    sites = home / "Sites"
    _git_init(sites / "site-one")
    _git_init(sites / "site-two")
    (home / "Projects").mkdir()  # exists, but holds no Git project -- not a candidate
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    candidates = {item["label"]: item for item in detect_candidate_roots()}

    assert set(candidates) == {"Developer", "Sites"}
    assert candidates["Developer"] == {"path": str(developer.resolve()), "label": "Developer", "project_count": 1}
    assert candidates["Sites"]["project_count"] == 2


def test_detect_candidate_roots_excludes_an_already_approved_folder(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    developer = home / "Developer"
    _git_init(developer / "widget")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda key: [str(developer)] if key == "projects.roots" else [])

    assert detect_candidate_roots() == []


def test_roots_command_reports_no_folders_and_no_candidates(monkeypatch, capsys, tmp_path):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    workspaces_command.roots(output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "schema_version": "1.0",
        "mode": "status",
        "result": "action-required",
        "roots": [],
        "candidates": [],
    }


def test_roots_command_reports_already_configured_folders_and_new_candidates(monkeypatch, capsys, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    approved = home / "Work"
    _git_init(approved / "one")
    developer = home / "Developer"
    _git_init(developer / "two")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda key: [str(approved)] if key == "projects.roots" else [])

    workspaces_command.roots(output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload["result"] == "ready"
    assert payload["roots"] == [{"name": "Work", "path": str(approved.resolve()), "project_count": 1}]
    assert payload["candidates"] == [{"path": str(developer.resolve()), "label": "Developer", "project_count": 1}]


# ---------------------------------------------------------------------------
# `configure --apply-all`
# ---------------------------------------------------------------------------


def test_apply_all_plans_every_project_that_needs_setup_and_skips_ready_ones(monkeypatch, capsys, tmp_path):
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    already_ready = tmp_path / "gamma"
    _git_init(alpha)
    _git_init(beta)
    _git_init(already_ready)
    (already_ready / ".claude/commands").mkdir(parents=True)
    (already_ready / ".claude/commands/protocol.md").write_text("framework")
    (already_ready / ".mcp.json").write_text("{}")
    monkeypatch.setattr(workspaces_command, "discover_workspaces", lambda: [alpha, already_ready, beta])

    workspaces_command.configure(
        project=None,
        apply_all=True,
        components="claude",
        share_with_project=False,
        associate_personal=True,
        apply=False,
        output_json=True,
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "plan"
    paths = {item["path"] for item in payload["workspaces"]}
    assert paths == {str(alpha.resolve()), str(beta.resolve())}
    assert payload["summary"]["total"] == 2


def test_apply_all_applies_every_project_and_collects_a_per_project_failure(monkeypatch, capsys, tmp_path):
    ok_project = tmp_path / "ok"
    failing_project = tmp_path / "failing"
    _git_init(ok_project)
    _git_init(failing_project)
    monkeypatch.setattr(workspaces_command, "discover_workspaces", lambda: [failing_project, ok_project])

    def fake_activate(root, components):
        if root == failing_project:
            raise ActivationError("Existing project setup needs review before Claude Copilot can add shared files.")
        return list(components)

    monkeypatch.setattr(workspaces_command, "activate_components", fake_activate)
    monkeypatch.setattr(workspaces_command, "write_install_lock", lambda *_a, **_k: None)

    # One project genuinely failing exits non-zero (result: blocked); the
    # report is still emitted and the other project's own outcome is intact.
    try:
        workspaces_command.configure(
            project=None,
            apply_all=True,
            components="claude",
            share_with_project=False,
            associate_personal=False,
            apply=True,
            output_json=True,
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "Exit"
    payload = json.loads(capsys.readouterr().out)

    by_path = {item["path"]: item for item in payload["workspaces"]}
    assert by_path[str(ok_project.resolve())]["state"] != "blocked"
    assert by_path[str(failing_project.resolve())]["state"] == "blocked"
    assert by_path[str(failing_project.resolve())]["detail"] == "Existing project setup needs review before Claude Copilot can add shared files."
    assert payload["result"] == "blocked"


# ---------------------------------------------------------------------------
# `forget-root`
# ---------------------------------------------------------------------------


def test_forget_root_removes_an_approved_folder_and_is_idempotent(monkeypatch, capsys, tmp_path):
    approved = tmp_path / "Projects"
    approved.mkdir()
    configured = [str(approved)]
    written = []
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: list(configured))

    def fake_remove(key, value):
        written.append((key, value))
        configured.remove(value)

    monkeypatch.setattr(workspaces_command, "remove_from_list_config", fake_remove)
    monkeypatch.setattr(core_workspaces, "default_known_projects_registry", lambda: tmp_path / "known-projects.json")

    workspaces_command.forget_root(path=str(approved), apply=True, output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert written == [("projects.roots", str(approved.resolve()))]
    assert payload["result"] == "applied"
    assert payload["root"] == {
        "name": "Projects",
        "path": str(approved.resolve()),
        "state": "removed",
        "detail": "Control Tower stopped looking in this folder. Nothing inside it was changed.",
    }

    # Calling again now that it is already removed is a safe no-op.
    written.clear()
    workspaces_command.forget_root(path=str(approved), apply=True, output_json=True)
    payload_again = json.loads(capsys.readouterr().out)

    assert written == []
    assert payload_again["result"] == "ready"
    assert payload_again["root"]["state"] == "removed"


# ---------------------------------------------------------------------------
# `decline`
# ---------------------------------------------------------------------------


def test_decline_records_the_opt_out_and_is_idempotent(monkeypatch, capsys, tmp_path):
    state = {"declined": False, "roots": []}

    def fake_resolve_key(key):
        if key == "projects.declined":
            return state["declined"]
        if key == "projects.roots":
            return state["roots"]
        return None

    def fake_write_config(key, value):
        assert key == "projects.declined"
        state["declined"] = value

    monkeypatch.setattr(workspaces_command, "resolve_key", fake_resolve_key)
    monkeypatch.setattr(core_workspaces, "resolve_key", fake_resolve_key)
    monkeypatch.setattr(workspaces_command, "write_config", fake_write_config)

    workspaces_command.decline(apply=True, output_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "applied"
    assert payload["discovery"]["state"] == "declined"

    # Declining twice is a safe no-op.
    workspaces_command.decline(apply=True, output_json=True)
    payload_again = json.loads(capsys.readouterr().out)
    assert payload_again["result"] == "ready"
    assert payload_again["discovery"]["state"] == "declined"


def test_approving_a_root_reverses_a_previous_decline(monkeypatch, capsys, tmp_path):
    selected = tmp_path / "Projects"
    selected.mkdir()
    state = {"declined": True, "roots": []}
    unset_calls = []

    def fake_resolve_key(key):
        if key == "projects.declined":
            return state["declined"]
        if key == "projects.roots":
            return state["roots"]
        return None

    def fake_unset_config(key):
        unset_calls.append(key)
        state["declined"] = False
        return True

    monkeypatch.setattr(workspaces_command, "resolve_key", fake_resolve_key)
    monkeypatch.setattr(workspaces_command, "add_to_list_config", lambda key, value: state["roots"].append(value))
    monkeypatch.setattr(workspaces_command, "unset_config", fake_unset_config)
    monkeypatch.setattr(core_workspaces, "default_known_projects_registry", lambda: tmp_path / "known-projects.json")

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
    capsys.readouterr()

    assert unset_calls == ["projects.declined"]
    assert state["declined"] is False


# ---------------------------------------------------------------------------
# `revert` / undo
# ---------------------------------------------------------------------------


def test_undo_status_reports_nothing_to_undo_for_a_project_never_set_up(tmp_path):
    project = tmp_path / "plain"
    _git_init(project)

    assert undo_status(project) == {"available": False, "detail": "There's nothing here to undo yet."}


def test_revert_removes_only_recorded_files_and_excludes_the_project_from_automatic_setup(tmp_path):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Revert.git")
    repo_parent = Path(__file__).resolve().parents[4]
    claude_root = repo_parent / "claude-copilot"
    codex_root = repo_parent / "codex-copilot"

    activate_components(project, ("claude", "codex"), claude_root=claude_root, codex_root=codex_root)
    write_install_lock(project, ("claude", "codex"), claude_root=claude_root, codex_root=codex_root)
    exclude_registry = tmp_path / "excluded-projects.json"

    plan = undo_status(project)
    assert plan == {"available": True, "detail": "Removes only what I added. Your own files are left alone."}

    outcome = revert_project(project, exclude_registry=exclude_registry)

    assert set(outcome["removed"]) == {"claude", "codex"}
    assert outcome["detail"] == "Removed. Your own files were left alone, and I won't set this project up again unless you ask."
    assert not (project / ".claude/commands/protocol.md").exists()
    assert not (project / "plugins/codex-copilot/.codex-plugin/plugin.json").exists()
    assert (project / ".git").is_dir()  # the person's own repository is untouched

    lock = json.loads((project / "copilot.lock.json").read_text())
    assert lock["components"] == []
    assert is_project_excluded(project, registry=exclude_registry)

    status_after = workspace_status(project, exclude_registry=exclude_registry)
    assert status_after["installed_components"] == []
    assert status_after["setup_policy"] == "excluded"
    assert status_after["undo"] == {"available": False, "detail": "There's nothing here to undo yet."}


def test_revert_refuses_when_a_recorded_file_was_edited_since(tmp_path):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/Edited.git")
    repo_parent = Path(__file__).resolve().parents[4]
    claude_root = repo_parent / "claude-copilot"
    codex_root = repo_parent / "codex-copilot"

    activate_components(project, ("claude",), claude_root=claude_root, codex_root=codex_root)
    write_install_lock(project, ("claude",), claude_root=claude_root, codex_root=codex_root)
    (project / ".claude/commands/protocol.md").write_text("edited by the person")

    plan = undo_status(project)
    assert plan == {"available": False, "detail": "You've changed these files since, so I'll leave them alone."}

    try:
        revert_project(project)
    except RevertError as exc:
        assert str(exc) == "You've changed these files since, so I'll leave them alone."
    else:
        raise AssertionError("an edited recorded file should block revert")

    assert (project / ".claude/commands/protocol.md").read_text() == "edited by the person"


def test_revert_command_plan_then_apply_shapes(monkeypatch, capsys, tmp_path):
    project = tmp_path / "project"
    _git_init(project, "git@github.com:Example/CliRevert.git")
    repo_parent = Path(__file__).resolve().parents[4]
    claude_root = repo_parent / "claude-copilot"
    codex_root = repo_parent / "codex-copilot"
    activate_components(project, ("claude",), claude_root=claude_root, codex_root=codex_root)
    write_install_lock(project, ("claude",), claude_root=claude_root, codex_root=codex_root)
    monkeypatch.setattr(core_workspaces, "default_excluded_registry", lambda: tmp_path / "excluded-projects.json")

    workspaces_command.revert(project=str(project), apply=False, output_json=True)
    plan_payload = json.loads(capsys.readouterr().out)
    assert plan_payload["mode"] == "plan"
    assert plan_payload["result"] == "action-required"
    assert plan_payload["revert"]["detail"] == "Removes only what I added. Your own files are left alone."

    workspaces_command.revert(project=str(project), apply=True, output_json=True)
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["mode"] == "apply"
    assert apply_payload["result"] == "applied"
    assert apply_payload["revert"]["removed"] == ["claude"]
    assert apply_payload["workspaces"][0]["state"] == "setup-available"
    assert apply_payload["workspaces"][0]["setup_policy"] == "excluded"


# ---------------------------------------------------------------------------
# `setup_policy: "automatic"` for a brand-new project (B3)
# ---------------------------------------------------------------------------


def _repo_roots():
    repo_parent = Path(__file__).resolve().parents[4]
    return repo_parent / "claude-copilot", repo_parent / "codex-copilot"


def test_project_present_at_grant_time_is_always_ask(tmp_path):
    root = tmp_path / "Projects"
    existing_project = root / "already-here"
    _git_init(existing_project)
    known_registry = tmp_path / "known-projects.json"
    claude_root, codex_root = _repo_roots()

    record_root_grant(root, registry=known_registry)

    report = workspace_status(
        existing_project,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert report["setup_policy"] == "ask"
    assert report["policy_detail"] == "You'll be asked before anything is added here."


def test_project_created_after_the_root_was_granted_is_automatic(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    known_registry = tmp_path / "known-projects.json"
    claude_root, codex_root = _repo_roots()

    record_root_grant(root, registry=known_registry)  # nothing here yet

    new_project = root / "brand-new"
    _git_init(new_project)  # created after the grant

    report = workspace_status(
        new_project,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    assert report["can_apply_now"] is True
    assert report["setup_policy"] == "automatic"
    assert report["policy_detail"] == "This project is new, so I'll set it up for you without asking."


def test_project_outside_any_granted_root_keeps_the_honest_ask_default(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    known_registry = tmp_path / "known-projects.json"
    record_root_grant(root, registry=known_registry)

    elsewhere = tmp_path / "elsewhere"
    _git_init(elsewhere)

    report = workspace_status(
        elsewhere,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
    )

    assert report["setup_policy"] == "ask"


def test_dirty_tree_still_holds_so_a_new_project_falls_back_to_ask(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    known_registry = tmp_path / "known-projects.json"
    claude_root, codex_root = _repo_roots()
    record_root_grant(root, registry=known_registry)  # nothing here yet

    new_project = root / "wip"
    _git_init(new_project)
    (new_project / "notes.md").write_text("mid-edit, not committed yet")

    report = workspace_status(
        new_project,
        personal_registry=tmp_path / "personal.json",
        known_projects_registry=known_registry,
        configured_roots=[root],
        claude_root=claude_root,
        codex_root=codex_root,
    )

    # Nothing collides by filename, so `can_apply_now` alone would pass --
    # but the working tree already has unsaved content, so this still
    # falls back to being asked rather than being set up silently.
    assert report["setup_policy"] == "ask"


def test_known_projects_snapshot_survives_a_fresh_read_from_disk(tmp_path):
    root = tmp_path / "Projects"
    existing = root / "already-here"
    _git_init(existing)
    known_registry = tmp_path / "known-projects.json"

    record_root_grant(root, registry=known_registry)

    # A brand-new read from disk, as if the process had restarted: nothing
    # about this snapshot lives only in memory.
    reloaded = read_known_projects_registry(known_registry)
    assert reloaded["roots"][str(root.resolve())] == [str(existing.resolve())]


def test_forgetting_a_root_clears_its_known_projects_snapshot(tmp_path):
    root = tmp_path / "Projects"
    existing = root / "already-here"
    _git_init(existing)
    known_registry = tmp_path / "known-projects.json"

    record_root_grant(root, registry=known_registry)
    assert str(root.resolve()) in read_known_projects_registry(known_registry)["roots"]

    forget_root_grant(root, registry=known_registry)
    assert str(root.resolve()) not in read_known_projects_registry(known_registry)["roots"]


def test_approving_a_root_snapshots_its_existing_projects_as_known(monkeypatch, capsys, tmp_path):
    selected = tmp_path / "Projects"
    existing = selected / "already-here"
    _git_init(existing)
    known_registry = tmp_path / "known-projects.json"
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(workspaces_command, "add_to_list_config", lambda *_args: None)
    monkeypatch.setattr(core_workspaces, "default_known_projects_registry", lambda: known_registry)

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
    capsys.readouterr()

    snapshot = read_known_projects_registry(known_registry)["roots"][str(selected.resolve())]
    assert snapshot == [str(existing.resolve())]


def test_automatic_setup_is_recorded_and_fully_revertible(monkeypatch, tmp_path):
    project = tmp_path / "convoco"
    _git_init(project, "git@github.com:Example/Convoco.git")
    claude_root, codex_root = _repo_roots()
    automatic_registry = tmp_path / "automatic-setups.json"
    exclude_registry = tmp_path / "excluded-projects.json"
    monkeypatch.setattr(core_workspaces, "default_automatic_setups_registry", lambda: automatic_registry)

    before = workspace_status(
        project,
        personal_registry=tmp_path / "personal.json",
        claude_root=claude_root,
        codex_root=codex_root,
    )
    before = {**before, "setup_policy": "automatic"}  # a genuinely new project's policy

    # `_apply_selected` is the exact function `configure --apply` uses; it
    # takes the same real activation path for an automatic setup as it does
    # for one the person explicitly asked for, and (per the module-level
    # `default_automatic_setups_registry` patch above) records it the same
    # way `configure --apply` would once the app calls it for a new project.
    error = workspaces_command._apply_selected(
        project, before, ["claude"], share_with_project=False, associate_personal=False
    )

    assert error is None
    assert (project / ".claude/commands/protocol.md").is_file()
    assert recently_set_up(registry=automatic_registry) == [
        {"name": "convoco", "detail": "Set your copilots up in convoco."}
    ]

    outcome = revert_project(project, exclude_registry=exclude_registry, automatic_setups_registry=automatic_registry)

    assert outcome["removed"] == ["claude"]
    assert not (project / ".claude/commands/protocol.md").exists()
    assert is_project_excluded(project, registry=exclude_registry)
    assert recently_set_up(registry=automatic_registry) == []


def test_recently_set_up_populates_and_ages_out(tmp_path):
    registry = tmp_path / "automatic-setups.json"
    project = tmp_path / "convoco"
    _git_init(project)
    start = 1_700_000_000.0

    record_automatic_setup(project, name="Convoco", registry=registry, now=start)

    fresh = recently_set_up(registry=registry, now=start + 3600)
    assert fresh == [{"name": "Convoco", "detail": "Set your copilots up in Convoco."}]

    aged_out = recently_set_up(registry=registry, now=start + RECENTLY_SET_UP_WINDOW_HOURS * 3600 + 1)
    assert aged_out == []
