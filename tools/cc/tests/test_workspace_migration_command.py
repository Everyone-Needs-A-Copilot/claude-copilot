from __future__ import annotations

import json
from pathlib import Path

from cc.commands import workspaces as command
from jsonschema import Draft202012Validator
from typer.testing import CliRunner


def _candidate(project: Path) -> dict:
    opaque = "sha256:" + ("a" * 64)
    return {
        "path": str(project),
        "name": project.name,
        "classification": "guided-integration",
        "inspection_id": opaque,
        "migration_kinds": ["claude-canonical-entry-v1"],
        "state": "eligible",
        "automatable": True,
        "reason_code": None,
        "detail": "A deterministic update is available.",
        "action": {
            "id": opaque,
            "inspection_id": opaque,
            "migration_kinds": ["claude-canonical-entry-v1"],
            "will_change": [{"path": "CLAUDE.md", "operation": "append-bounded-entry"}],
            "will_preserve": [],
            "will_not_do": ["overwrite-project-instructions"],
        },
        "verification": {
            "command": ["cc", "workspace", "verify", "--json"],
            "expected": "Ready",
        },
    }


def test_apply_reports_overlap_and_persists_internal_action_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    candidate = _candidate(project)
    captured: dict = {}

    monkeypatch.setattr(command, "discover_workspaces", lambda: [project])
    monkeypatch.setattr(
        command,
        "workspace_status",
        lambda *_args, **_kwargs: {
            "classification": "guided-integration",
            "inspection": {"id": candidate["inspection_id"]},
        },
    )
    monkeypatch.setattr(
        command, "build_migration_candidate", lambda *_args, **_kwargs: candidate
    )
    monkeypatch.setattr(
        command,
        "apply_migration_action",
        lambda *_args, **_kwargs: {
            "path": str(project),
            "name": project.name,
            "action_id": candidate["action"]["id"],
            "status": "applied",
            "detail": "One component passed.",
            "completed_actions": [],
            "verification": "ready",
            "_diagnostic": {"project": str(project), "verification": "ready"},
        },
    )

    def persist(report, actions):
        captured["report"] = json.loads(json.dumps(report))
        captured["actions"] = actions
        return {
            "schema_version": "1.0",
            "id": "run",
            "state": "available",
            "path": str(tmp_path / "record.json"),
            "created_at": "2026-08-04T16:00:00Z",
            "detail": "Saved.",
        }

    monkeypatch.setattr(command, "write_workspace_migration_diagnostic", persist)
    runner = CliRunner()
    plan_result = runner.invoke(command.workspaces_app, ["migrate", "--all", "--json"])
    assert plan_result.exit_code == 0
    plan_id = json.loads(plan_result.stdout)["plan_id"]

    result = runner.invoke(
        command.workspaces_app,
        ["migrate", "--all", "--plan-id", plan_id, "--apply", "--json"],
    )

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["result"] == "partial"
    assert report["apply_summary"]["applied"] == 1
    assert report["apply_summary"]["remaining_guided"] == 1
    assert report["apply_summary"]["updated_still_guided"] == 1
    assert report["apply_summary"]["failed_still_guided"] == 0
    assert "still need guided setup" in report["apply_summary"]["detail"]
    assert report["diagnostics"]["state"] == "available"
    assert "_diagnostic" not in report["ledger"][0]
    assert captured["actions"] == [{"project": str(project), "verification": "ready"}]
    assert "diagnostics" not in captured["report"]
    schema_path = Path(__file__).parent / "fixtures/schemas/workspace-migrations.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(report))
