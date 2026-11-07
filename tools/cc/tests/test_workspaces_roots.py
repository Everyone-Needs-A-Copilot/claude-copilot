"""`cc workspace`: project-folder roots stay; the copy-and-lock surface is retired.

Old expectation (retired): `cc workspace` reported per-project activation state by checking framework
copies against `copilot.lock.json`, and `configure` / `finish` / `verify` / `plan` / `migrate` / `hold` /
`revert` activated, verified or reverted those copies. New expectation: those commands exit 2 with a
`retired` error that points at `cc project init`; `roots`, `approve-root`, `forget-root` and `decline`
(which folders hold projects) are unchanged. Reason: central resolution copies nothing into a project.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.commands import workspaces as workspaces_command
from cc.core.ecosystem import workspaces as core_workspaces
from cc.core.ecosystem.workspaces import (
    detect_candidate_roots,
    forget_root_grant,
    read_known_projects_registry,
    record_root_grant,
)
from typer.testing import CliRunner

from cc.main import app


def _git_init(path: Path, remote: str | None = None) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True)


@pytest.mark.parametrize(
    "argv",
    [
        ["workspace", "--all", "--json"],
        ["workspace", "--project", "{p}", "--json"],
        ["workspace", "configure", "--project", "{p}", "--apply", "--json"],
        ["workspace", "finish", "--project", "{p}", "--action-id", "x", "--json"],
        ["workspace", "verify", "--project", "{p}", "--json"],
        ["workspace", "plan", "--project", "{p}", "--json"],
        ["workspace", "migrate", "--json"],
        ["workspace", "hold", "--project", "{p}", "--json"],
        ["workspace", "revert", "--project", "{p}", "--apply", "--json"],
    ],
)
def test_copy_and_lock_commands_refuse_and_write_nothing(argv, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    result = CliRunner().invoke(app, [a.format(p=project) for a in argv])
    assert result.exit_code == 2, result.output
    error = json.loads(result.output)["error"]
    assert error["code"] == "retired" and "cc project init" in error["message"]
    assert list(project.iterdir()) == []


def test_root_approval_is_explicit_idempotent_and_names_are_for_display(
    monkeypatch, capsys, tmp_path
):
    selected = tmp_path / "Projects"
    selected.mkdir()
    written = []
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda key, value: written.append((key, value)),
    )
    monkeypatch.setattr(
        core_workspaces,
        "default_known_projects_registry",
        lambda: tmp_path / "known-projects.json",
    )

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
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


def test_detect_candidate_roots_finds_nothing_when_no_conventional_folder_has_a_project(
    monkeypatch, tmp_path
):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    assert detect_candidate_roots() == []


def test_detect_candidate_roots_finds_several_conventional_folders(
    monkeypatch, tmp_path
):
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
    assert candidates["Developer"] == {
        "path": str(developer.resolve()),
        "label": "Developer",
        "project_count": 1,
    }
    assert candidates["Sites"]["project_count"] == 2


def test_detect_candidate_roots_excludes_an_already_approved_folder(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    developer = home / "Developer"
    _git_init(developer / "widget")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        core_workspaces,
        "resolve_key",
        lambda key: [str(developer)] if key == "projects.roots" else [],
    )

    assert detect_candidate_roots() == []


def test_roots_command_reports_no_folders_and_no_candidates(
    monkeypatch, capsys, tmp_path
):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(core_workspaces, "resolve_key", lambda _key: [])

    workspaces_command.roots(output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "schema_version": "1.1",
        "mode": "status",
        "result": "action-required",
        "roots": [],
        "candidates": [],
    }


def test_roots_command_reports_already_configured_folders_and_new_candidates(
    monkeypatch, capsys, tmp_path
):
    home = tmp_path / "home"
    home.mkdir()
    approved = home / "Work"
    _git_init(approved / "one")
    developer = home / "Developer"
    _git_init(developer / "two")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        core_workspaces,
        "resolve_key",
        lambda key: [str(approved)] if key == "projects.roots" else [],
    )

    workspaces_command.roots(output_json=True)
    payload = json.loads(capsys.readouterr().out)

    assert payload["result"] == "ready"
    assert payload["roots"] == [
        {"name": "Work", "path": str(approved.resolve()), "project_count": 1}
    ]
    assert payload["candidates"] == [
        {"path": str(developer.resolve()), "label": "Developer", "project_count": 1}
    ]


def test_forget_root_removes_an_approved_folder_and_is_idempotent(
    monkeypatch, capsys, tmp_path
):
    approved = tmp_path / "Projects"
    approved.mkdir()
    configured = [str(approved)]
    written = []
    monkeypatch.setattr(
        workspaces_command, "resolve_key", lambda _key: list(configured)
    )

    def fake_remove(key, value):
        written.append((key, value))
        configured.remove(value)

    monkeypatch.setattr(workspaces_command, "remove_from_list_config", fake_remove)
    monkeypatch.setattr(
        core_workspaces,
        "default_known_projects_registry",
        lambda: tmp_path / "known-projects.json",
    )

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
    monkeypatch.setattr(
        workspaces_command,
        "add_to_list_config",
        lambda key, value: state["roots"].append(value),
    )
    monkeypatch.setattr(workspaces_command, "unset_config", fake_unset_config)
    monkeypatch.setattr(
        core_workspaces,
        "default_known_projects_registry",
        lambda: tmp_path / "known-projects.json",
    )

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
    capsys.readouterr()

    assert unset_calls == ["projects.declined"]
    assert state["declined"] is False


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
    assert (
        str(root.resolve()) not in read_known_projects_registry(known_registry)["roots"]
    )


def test_approving_a_root_snapshots_its_existing_projects_as_known(
    monkeypatch, capsys, tmp_path
):
    selected = tmp_path / "Projects"
    existing = selected / "already-here"
    _git_init(existing)
    known_registry = tmp_path / "known-projects.json"
    monkeypatch.setattr(workspaces_command, "resolve_key", lambda _key: [])
    monkeypatch.setattr(workspaces_command, "add_to_list_config", lambda *_args: None)
    monkeypatch.setattr(
        core_workspaces, "default_known_projects_registry", lambda: known_registry
    )

    workspaces_command.approve_root(path=str(selected), apply=True, output_json=True)
    capsys.readouterr()

    snapshot = read_known_projects_registry(known_registry)["roots"][
        str(selected.resolve())
    ]
    assert snapshot == [str(existing.resolve())]
