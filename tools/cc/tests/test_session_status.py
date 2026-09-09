"""Focused behavior of the read-only projection, using real local observations."""

import json
from pathlib import Path
import socket
import subprocess

import pytest
import typer
from typer.testing import CliRunner

from cc.commands.status import status_cmd
from cc.core.session_status import build_session_status
from cc.core.verification import build_plan, run_plan


@pytest.fixture
def project(tmp_path):
    (tmp_path / "check.py").write_text("print('private-log-sentinel')\n")
    (tmp_path / "verification.json").write_text(json.dumps({
        "schemaVersion": 1, "inputs": ["check.py"], "fallbackLanes": ["focused"],
        "lanes": [{"id": "focused", "description": "private-description-sentinel", "paths": ["check.py"],
                   "argv": ["{python}", "check.py"], "cwd": ".", "timeoutSeconds": 3, "hermetic": True}],
    }))
    return tmp_path


def _cli():
    app = typer.Typer()
    app.command("status")(status_cmd)
    return app


def _record(project, *, reuse=False, task="TASK-67"):
    return run_plan(project, build_plan(project, changed=["check.py"], task=task), reuse=reuse)


def test_empty_explicit_project_is_read_only_and_unknown(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    before = list(other.iterdir())
    result = CliRunner().invoke(_cli(), ["--project", str(other), "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["project"] == str(other)
    assert report["readOnly"] is True
    assert report["cc"]["installed"] is True
    assert report["verification"] == {"state": "not-observed", "run": None}
    assert all(value is None for value in report["metrics"].values())
    assert all(runtime["activated"] == runtime["running"] == runtime["blocked"] == "unknown" for runtime in report["foundation"]["runtimes"])
    assert list(other.iterdir()) == before


def test_installation_registration_are_not_activation_and_values_do_not_leak(project):
    (project / ".claude/hooks").mkdir(parents=True)
    (project / ".claude/hooks/copilot-hook.sh").write_text("# project shim\n")
    (project / ".claude/settings.json").write_text(json.dumps({"hooks": {"SessionStart": [{"command": "private-command-sentinel"}]}, "env": {"TOKEN": "private-setting-sentinel"}}))
    report = build_session_status(project)
    claude = next(r for r in report["foundation"]["runtimes"] if r["runtime"] == "claude")
    assert claude["installed"] == "files-present"
    assert claude["registered"] == "project-declaration-present"
    assert claude["activated"] == claude["running"] == claude["blocked"] == "unknown"
    output = json.dumps(report)
    assert "private-command-sentinel" not in output and "private-setting-sentinel" not in output


def test_completed_run_plan_human_and_json_projection_without_double_counting(project):
    recorded = _record(project)
    report = build_session_status(project)
    run = report["verification"]["run"]
    assert run["id"] == recorded["runId"] and run["lastStatus"] == "passed"
    assert run["task"] == "TASK-67"
    assert run["plan"]["scope"] == "declared-paths"
    assert run["plan"]["lanes"] == [{"id": "focused", "capSeconds": 3}]
    assert run["wallSecondsLastObserved"] == round(recorded["finishedAt"] - recorded["startedAt"], 3)
    assert run["processLiveness"] == "unknown" and not run["needsAttention"]
    for sentinel in ("private-log-sentinel", "private-description-sentinel", "argv", "check.py"):
        assert sentinel not in json.dumps(report)
    result = CliRunner().invoke(_cli(), ["--root", str(project)])
    assert result.exit_code == 0
    assert "last observed, process liveness unknown" in result.stdout
    assert "unknown (not zero)" in result.stdout
    assert "API estimates are not subscription charges" in result.stdout


def test_historical_running_snapshot_never_implies_live_agent_or_elapsed_now(project, monkeypatch):
    recorded = _record(project)
    path = Path(recorded["artifactPath"]) / "status.json"
    snapshot = {k: v for k, v in recorded.items() if k not in {"finishedAt", "resultHash", "artifactHashes"}}
    snapshot.update(status="running", startedAt=100, heartbeatAt=112,
                    current={"id": "focused", "elapsedSeconds": 10, "timeoutSeconds": 30})
    path.write_text(json.dumps(snapshot))
    monkeypatch.setattr("cc.core.session_status.time.time", lambda: 10000)
    report = build_session_status(project)
    run = report["verification"]["run"]
    assert run["lastStatus"] == "running"
    assert run["processLiveness"] == "unknown"
    assert run["wallSecondsLastObserved"] == 12
    assert run["observationAgeSeconds"] == 9888
    assert run["currentLaneLastObserved"]["elapsedSeconds"] == 10
    assert report["metrics"]["agentTimeSeconds"] is None


def test_failed_incomplete_and_reused_observations_are_not_approval(project):
    first = _record(project)
    reused = _record(project, reuse=True, task="68")
    run = build_session_status(project)["verification"]["run"]
    assert run["id"] == reused["runId"] and run["executionReused"] is True
    assert run["wallSecondsLastObserved"] == round(reused["finishedAt"] - reused["startedAt"], 3)
    assert first["runId"] not in json.dumps(build_session_status(project))
    (project / "check.py").write_text("raise SystemExit(4)\n")
    _record(project)
    report = build_session_status(project)
    assert report["verification"]["run"]["needsAttention"] is True
    assert report["verification"]["run"]["lastStatus"] == "failed"
    assert all(r["blocked"] == "unknown" for r in report["foundation"]["runtimes"])
    (project / "check.py").write_text("from pathlib import Path\nPath('check.py').write_text('changed')\n")
    _record(project)
    assert build_session_status(project)["verification"]["run"]["lastStatus"] == "incomplete"


def test_malformed_latest_evidence_is_visible_instead_of_older_green(project):
    _record(project)
    latest = project / ".copilot/verification/newer"
    latest.mkdir()
    (latest / "status.json").write_text('{"status":"passed", "secret":"private-status-sentinel"}')
    report = build_session_status(project)
    assert report["verification"]["state"] == "unavailable"
    assert report["verification"]["run"] is None
    assert "private-status-sentinel" not in json.dumps(report)


def test_unsafe_observation_sources_are_not_followed(project, tmp_path_factory):
    outside = tmp_path_factory.mktemp("private-store")
    secret = outside / "credentials.json"
    secret.write_text("private-credential-sentinel")
    (project / ".claude").mkdir()
    (project / ".claude/settings.json").symlink_to(secret)
    assert build_session_status(project)["foundation"]["state"] == "unavailable"
    (project / ".copilot").symlink_to(outside, target_is_directory=True)
    report = build_session_status(project)
    assert report["verification"]["state"] == "unavailable"
    assert "private-credential-sentinel" not in json.dumps(report)


def test_status_does_not_write_spawn_network_probe_or_read_credential_store(project, monkeypatch):
    _record(project)
    before = {p.relative_to(project).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in project.rglob("*") if p.is_file()}
    monkeypatch.setenv("COPILOT_PRIVATE_SENTINEL", "private-environment-sentinel")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Status crossed a read-only boundary")

    original_open = Path.open

    def guarded_open(path, mode="r", *args, **kwargs):
        assert all(flag not in mode for flag in ("w", "a", "+"))
        assert path.resolve().is_relative_to(project)
        assert not any(part in {"secrets.env", "credentials.json", ".ssh"} for part in path.parts)
        return original_open(path, mode, *args, **kwargs)

    # Scope the outbound guard to the operation under test, not pytest's own
    # configuration-restoration teardown (which reads the machine config).
    with monkeypatch.context() as guard:
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr("cc.core.runtime_evidence._probe_codex", forbidden)
        guard.setattr(Path, "open", guarded_open)
        result = CliRunner().invoke(_cli(), ["--project", str(project), "--json"])
        assert result.exit_code == 0, result.output
        assert "private-environment-sentinel" not in result.stdout
    after = {p.relative_to(project).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in project.rglob("*") if p.is_file()}
    assert before == after


def test_invalid_project_exits_nonzero(tmp_path):
    result = CliRunner().invoke(_cli(), ["--project", str(tmp_path / "missing"), "--json"])
    assert result.exit_code == 2
    assert "error" in json.loads(result.stdout)


@pytest.mark.parametrize("field", ["current", "selection"])
def test_malformed_running_metadata_is_unavailable(project, field):
    recorded = _record(project)
    directory = Path(recorded["artifactPath"])
    snapshot = {k: v for k, v in recorded.items() if k not in {"finishedAt", "resultHash", "artifactHashes"}}
    snapshot["status"] = "running"
    if field == "current":
        snapshot["current"] = ["private-invalid-metadata"]
    else:
        plan_path = directory / "plan.json"
        plan = json.loads(plan_path.read_text())
        plan["selection"] = ["private-invalid-metadata"]
        plan_path.write_text(json.dumps(plan))
    (directory / "status.json").write_text(json.dumps(snapshot))
    report = build_session_status(project)
    assert report["verification"]["state"] == "unavailable"
    assert "private-invalid-metadata" not in json.dumps(report)


@pytest.mark.parametrize("limit", ["_MAX_ARTIFACT_ENTRIES", "_MAX_ARTIFACT_BYTES"])
def test_excessive_artifacts_are_rejected_before_integrity_reader(project, monkeypatch, limit):
    _record(project)
    monkeypatch.setattr("cc.core.session_status." + limit, 1)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unbounded integrity reader was called")

    monkeypatch.setattr("cc.core.session_status.read_status", forbidden)
    assert build_session_status(project)["verification"]["state"] == "unavailable"


def test_main_command_registration_and_explicit_project(tmp_path):
    from cc.main import app

    result = CliRunner().invoke(app, ["status", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["project"] == str(tmp_path)
