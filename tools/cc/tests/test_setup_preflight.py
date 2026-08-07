from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path

from cc.commands import onboard
from cc.commands.onboard import _repository_permission
from cc.core.ecosystem.project_locking import project_lock
from cc.core.ecosystem.reconciliation import assess_reconciliation
from jsonschema import Draft202012Validator

from cc.core.ecosystem import setup_preflight


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args), cwd=repo, text=True, capture_output=True, check=False
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "product"
    repo.mkdir()
    assert _run(repo, "init", "-q").returncode == 0
    assert _run(repo, "config", "user.name", "Fixture").returncode == 0
    assert _run(repo, "config", "user.email", "fixture@example.invalid").returncode == 0
    (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
    assert _run(repo, "add", "tracked.txt").returncode == 0
    assert _run(repo, "commit", "-q", "-m", "initial").returncode == 0
    return repo


def _project(repo: Path) -> dict:
    return {"path": str(repo), "name": repo.name, "scope": {"kind": "product-project"}}


def _isolated_lock(monkeypatch, tmp_path: Path) -> None:
    @contextlib.contextmanager
    def locked(path):
        with project_lock(path, lock_root=tmp_path / "locks") as anchored:
            yield anchored

    monkeypatch.setattr(setup_preflight, "project_lock", locked)


def test_checkpoint_commits_all_current_product_work_locally(tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _isolated_lock(monkeypatch, tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    outcome = setup_preflight._checkpoint_project(
        _project(repo), "run_" + ("a" * 32)
    )

    assert outcome["status"] == "checkpointed"
    assert outcome["action"]["pushed"] is False
    assert outcome["action"]["residual_work"] is False
    assert _run(repo, "status", "--porcelain").stdout == ""
    assert "chore: save work before Copilot setup" in _run(
        repo, "log", "-1", "--pretty=%B"
    ).stdout
    assert set(_run(repo, "show", "--pretty=", "--name-only", "HEAD").stdout.split()) == {
        "new.txt",
        "tracked.txt",
    }


def test_failed_commit_restores_exact_index_and_preserves_work(tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _isolated_lock(monkeypatch, tmp_path)
    (repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
    assert _run(repo, "add", "tracked.txt").returncode == 0
    (repo / "new.txt").write_text("unstaged\n", encoding="utf-8")
    index = Path(_run(repo, "rev-parse", "--git-path", "index").stdout.strip())
    if not index.is_absolute():
        index = repo / index
    before_index = index.read_bytes()
    real_git = setup_preflight._git

    def fail_commit(root, *arguments, timeout=120.0):
        if arguments and arguments[0] == "commit":
            return subprocess.CompletedProcess(("git", *arguments), 1, b"", b"rejected")
        return real_git(root, *arguments, timeout=timeout)

    monkeypatch.setattr(setup_preflight, "_git", fail_commit)

    outcome = setup_preflight._checkpoint_project(
        _project(repo), "run_" + ("b" * 32)
    )

    assert outcome["status"] == "held"
    assert outcome["hold"]["code"] == "git-commit-failed"
    assert index.read_bytes() == before_index
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "staged\n"
    assert (repo / "new.txt").read_text(encoding="utf-8") == "unstaged\n"


def test_checkpoint_does_not_execute_repository_hooks(tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    _isolated_lock(monkeypatch, tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    outcome = setup_preflight._checkpoint_project(
        _project(repo), "run_" + ("e" * 32)
    )

    assert outcome["status"] == "checkpointed"
    assert not marker.exists()


def test_prepare_never_checkpoints_ecosystem_repositories(monkeypatch) -> None:
    projects = [
        {
            "path": "/projects/product",
            "name": "product",
            "scope": {"kind": "product-project"},
            "blockers": [{"code": "dirty-working-tree"}],
        },
        {
            "path": "/projects/foundation",
            "name": "foundation",
            "scope": {"kind": "ecosystem-repository"},
            "blockers": [{"code": "dirty-working-tree"}],
        },
    ]
    assessment = {
        "run_id": "run_" + ("c" * 32),
        "generated_at": "2026-08-06T12:00:00Z",
        "result": "ready",
        "projects": projects,
        "next_actions": [],
    }
    seen: list[str] = []

    def checkpoint(project, run_id):
        seen.append(project["path"])
        return {"status": "current"}

    monkeypatch.setattr(setup_preflight, "_checkpoint_project", checkpoint)
    setup_preflight.build_setup_prepare_report(
        assess_builder=lambda: assessment,
        refresh_builder=lambda: {
            "result": "ready",
            "completed_actions": [],
            "holds": [],
            "summary": {"checked": 0, "updated": 0, "current": 0, "held": 0},
            "authority": {"setup_access": "download-only", "author_capable": 0, "read_only": 0, "unknown": 0},
        },
    )

    assert seen == ["/projects/product"]


def test_prepare_checkpoints_repeat_safe_setup_outputs_even_without_blocker(
    tmp_path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    _isolated_lock(monkeypatch, tmp_path)
    (repo / "copilot.lock.json").write_text("{}\n", encoding="utf-8")
    assessment = {
        "run_id": "run_" + ("7" * 32),
        "generated_at": "2026-08-07T12:00:00Z",
        "result": "action-required",
        "projects": [{**_project(repo), "blockers": []}],
        "next_actions": [],
    }

    report = setup_preflight.build_setup_prepare_report(
        assess_builder=lambda: assessment,
        refresh_builder=lambda: {
            "result": "ready",
            "completed_actions": [],
            "holds": [],
            "summary": {"checked": 0, "updated": 0, "current": 0, "held": 0},
            "authority": {
                "setup_access": "download-only",
                "author_capable": 0,
                "read_only": 0,
                "unknown": 0,
            },
        },
    )

    assert report["project_checkpoints"]["checkpointed"] == 1
    assert _run(repo, "status", "--porcelain").stdout == ""


def test_prepare_refreshes_configured_org_without_discovery(monkeypatch) -> None:
    assessment = {
        "run_id": "run_" + ("f" * 32),
        "generated_at": "2026-08-07T12:00:00Z",
        "result": "ready",
        "projects": [],
        "next_actions": [],
    }
    seen: dict[str, str] = {}
    monkeypatch.setattr(setup_preflight, "resolve_key", lambda key: "Example-Org")

    def refresh(**kwargs):
        seen.update(kwargs)
        return {
            "result": "ready",
            "completed_actions": [],
            "holds": [],
            "summary": {"checked": 2, "updated": 0, "current": 2, "held": 0},
            "authority": {
                "setup_access": "download-only",
                "author_capable": 1,
                "read_only": 1,
                "unknown": 0,
            },
        }

    monkeypatch.setattr(setup_preflight, "build_shared_repository_refresh_report", refresh)

    setup_preflight.build_setup_prepare_report(assess_builder=lambda: assessment)

    assert seen == {"org": "Example-Org"}


def test_prepare_preserves_shared_refresh_diagnostic(monkeypatch) -> None:
    assessment = {
        "run_id": "run_" + ("1" * 32),
        "generated_at": "2026-08-07T12:00:00Z",
        "result": "ready",
        "projects": [],
        "next_actions": [],
    }

    def fail_refresh():
        raise RuntimeError("configured organization handoff is unavailable")

    report = setup_preflight.build_setup_prepare_report(
        assess_builder=lambda: assessment,
        refresh_builder=fail_refresh,
    )

    assert report["holds"][0] == {
        "code": "shared-refresh-unavailable",
        "detail": "Shared Copilot repositories could not be refreshed safely.",
        "diagnostic": "configured organization handoff is unavailable",
    }


def test_repository_permission_is_fail_closed_and_matches_github_grants() -> None:
    assert _repository_permission({}) == "unknown"
    assert _repository_permission({"permissions": {"pull": True}}) == "read"
    assert _repository_permission({"permissions": {"triage": True, "pull": True}}) == "triage"
    assert _repository_permission({"permissions": {"push": True, "pull": True}}) == "write"
    assert _repository_permission({"permissions": {"maintain": True, "push": True}}) == "maintain"
    assert _repository_permission({"permissions": {"admin": True}}) == "admin"


def test_shared_refresh_disables_repository_hooks_for_git(monkeypatch, tmp_path) -> None:
    row = {
        "id": "foundation-claude",
        "role": "foundation",
        "action": "repair",
        "detail": "behind",
        "repository_owner": "example",
        "repository_name": "foundation",
        "repository_permission": "read",
        "author_capable": False,
    }
    layer = {
        "id": row["id"],
        "rank": 10,
        "product": "claude",
        "source": {"path": str(tmp_path / "foundation"), "repo": "git@example.invalid:foundation.git", "ref": "main"},
    }
    monkeypatch.setattr(onboard, "_discover_org", lambda products, run: "example")
    monkeypatch.setattr(onboard, "_owner", lambda run: "person")
    monkeypatch.setattr(onboard, "_load_handoff", lambda org, products, run: {})
    monkeypatch.setattr(onboard, "_eligible_department_units", lambda handoff, org, owner, run: [])
    monkeypatch.setattr(onboard, "_layer_manifest", lambda *args, **kwargs: {"version": "1.0", "org": "example", "layers": [layer]})
    monkeypatch.setattr(onboard, "_topology_report_layers", lambda manifest, run: [row])
    commands: list[tuple[str, ...]] = []

    def base_run(command):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    def apply(manifest, rows, run):
        run(("git", "merge", "--ff-only", "FETCH_HEAD"))
        run(("gh", "api", "user"))
        rows[0]["action"] = "reuse"
        return True, None

    monkeypatch.setattr(onboard, "_apply_visible_topology", apply)

    report = onboard.build_shared_repository_refresh_report(
        products=("claude",), run=base_run, repository_root=tmp_path
    )

    assert report["mode"] == "download-only"
    assert commands[0] == (
        "git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "merge", "--ff-only", "FETCH_HEAD",
    )
    assert commands[1] == ("gh", "api", "user")


def test_shared_refresh_defaults_to_enabled_harness_products(monkeypatch, tmp_path) -> None:
    seen: dict[str, tuple[str, ...]] = {}

    def discover(products, run):
        seen["products"] = tuple(products)
        return "example"

    monkeypatch.setattr(onboard, "_discover_org", discover)
    monkeypatch.setattr(onboard, "_owner", lambda run: "person")
    monkeypatch.setattr(onboard, "_load_handoff", lambda org, products, run: {})
    monkeypatch.setattr(onboard, "_eligible_department_units", lambda *args, **kwargs: [])
    monkeypatch.setattr(onboard, "_layer_manifest", lambda *args, **kwargs: {"layers": []})
    monkeypatch.setattr(onboard, "_topology_report_layers", lambda manifest, run: [])

    report = onboard.build_shared_repository_refresh_report(
        run=lambda command: subprocess.CompletedProcess(command, 0, "", ""),
        repository_root=tmp_path,
    )

    assert seen["products"] == ("claude", "codex")
    assert report["summary"]["checked"] == 0


def test_prepare_report_validates_against_reconciliation_schema() -> None:
    machine = {
        "state": "ready",
        "helper": {"state": "ready", "version": "2.10.0", "path": "/cc", "detail": "ready"},
        "frameworks": [
            {
                "component": component,
                "state": "ready",
                "path": f"/{component}",
                "version": "1.0.0",
                "detail": "ready",
            }
            for component in ("claude", "codex")
        ],
        "configuration": {"state": "ready", "path": "/config", "approved_roots": [], "detail": "ready"},
        "authentication": {"state": "signed-in", "credential_state": "present", "detail": "ready"},
        "connectivity": {"state": "online", "detail": "ready"},
        "layers": {"state": "ready", "ready": 0, "total": 0, "detail": "ready"},
        "dependencies": [],
        "blockers": [],
        "next_action": "Nothing needs to be changed.",
    }
    assessment = assess_reconciliation(
        machine_builder=lambda: machine,
        census_builder=lambda detail=True: [],
        run_id="run_" + ("d" * 32),
    )
    report = setup_preflight.build_setup_prepare_report(
        assess_builder=lambda: assessment,
        refresh_builder=lambda: {
            "result": "ready",
            "completed_actions": [],
            "holds": [],
            "summary": {"checked": 12, "updated": 0, "current": 12, "held": 0},
            "authority": {"setup_access": "download-only", "author_capable": 4, "read_only": 7, "unknown": 1},
        },
    )
    schema = json.loads(
        (Path(__file__).parent / "fixtures" / "schemas" / "reconcile.schema.json").read_text(encoding="utf-8")
    )

    assert not list(Draft202012Validator(schema).iter_errors(report))
