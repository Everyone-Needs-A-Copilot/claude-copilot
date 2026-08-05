from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.commands import reconcile as command
from cc.core.ecosystem.reconciliation import ReconciliationError
from jsonschema import Draft202012Validator
from typer.testing import CliRunner


def _validator() -> Draft202012Validator:
    path = Path(__file__).parent / "fixtures" / "schemas" / "reconcile.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def test_missing_request_and_plan_id_use_versioned_error_contract() -> None:
    runner = CliRunner()

    for arguments in (["plan", "--json"], ["apply", "--json"], ["verify", "--json"]):
        result = runner.invoke(command.reconcile_app, arguments)
        assert result.exit_code == 2
        report = json.loads(result.stdout)
        assert report == {
            "error": {
                "code": "invalid-request",
                "detail": (
                    "Provide the exact reviewed plan identifier."
                    if arguments[0] == "apply"
                    else "Provide the explicit reconciliation request."
                ),
            },
            "exit_code": 2,
            "phase": "error",
            "result": "error",
            "schema_version": "1.0",
        }
        assert not list(_validator().iter_errors(report))


def test_malformed_plan_id_fails_before_request_or_inspection() -> None:
    result = CliRunner().invoke(
        command.reconcile_app,
        ["apply", "--plan-id", "../../not-a-plan", "--json"],
    )

    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["error"] == {
        "code": "invalid-request",
        "detail": "Provide the exact reviewed plan identifier.",
    }
    assert not list(_validator().iter_errors(report))


def test_unexpected_failure_never_serializes_exception_detail(monkeypatch) -> None:
    sentinel = "sk-this-must-never-appear-in-json"

    def fail() -> dict:
        raise RuntimeError(sentinel)

    monkeypatch.setattr(command, "assess_reconciliation", fail)
    result = CliRunner().invoke(command.reconcile_app, ["assess", "--json"])

    assert result.exit_code == 2
    assert sentinel not in result.stdout
    report = json.loads(result.stdout)
    assert report["error"] == {
        "code": "environment-error",
        "detail": "The reconciliation workflow could not inspect this Mac safely.",
    }
    assert not list(_validator().iter_errors(report))


def test_normal_business_block_returns_exit_one_without_error_envelope(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        command,
        "assess_reconciliation",
        lambda: {"phase": "assess", "result": "blocked"},
    )
    result = CliRunner().invoke(command.reconcile_app, ["assess", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {"phase": "assess", "result": "blocked"}


@pytest.mark.parametrize(
    "recipe_id",
    ["unknown-reviewed-recipe-v1", "codex-project-update-v1"],
)
def test_valid_shaped_unknown_or_mismatched_recipe_is_invalid_recipe_json(
    tmp_path, monkeypatch, recipe_id: str
) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "roots": ["/projects"],
                "projects": [
                    {
                        "path": "/projects/example",
                        "components": ["claude"],
                        "recipe_ids": {"claude": recipe_id},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def reject(parsed_request):
        assert parsed_request.projects[0].recipe_ids["claude"] == recipe_id
        raise ReconciliationError(
            "invalid-recipe",
            "The selected recipe id is unknown or does not apply to this component state. Choose an option returned by the fresh assessment.",
            exit_code=2,
        )

    monkeypatch.setattr(command, "build_plan_report", reject)
    result = CliRunner().invoke(
        command.reconcile_app,
        ["plan", "--request", str(request), "--json"],
    )

    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["error"]["code"] == "invalid-recipe"
    assert report["exit_code"] == 2
    assert "environment-error" not in result.stdout
    assert not list(_validator().iter_errors(report))


def test_unavailable_authoritative_recipe_source_is_business_block_json(
    tmp_path, monkeypatch
) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "roots": ["/projects"],
                "projects": [
                    {
                        "path": "/projects/example",
                        "components": ["claude"],
                        "recipe_ids": {"claude": "claude-project-update-v1"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def unavailable(_request):
        raise ReconciliationError(
            "recipe-unavailable",
            "The selected reviewed recipe is not available from the verified framework source. Repair the framework source, then assess again.",
            exit_code=1,
        )

    monkeypatch.setattr(command, "build_plan_report", unavailable)
    result = CliRunner().invoke(
        command.reconcile_app,
        ["plan", "--request", str(request), "--json"],
    )

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["error"]["code"] == "recipe-unavailable"
    assert report["exit_code"] == 1
    assert "environment-error" not in result.stdout
    assert not list(_validator().iter_errors(report))


@pytest.mark.parametrize(("result_state", "exit_code"), [("ready", 0), ("blocked", 1)])
def test_recover_command_emits_its_strict_schema_branch(
    monkeypatch, result_state: str, exit_code: int
) -> None:
    monkeypatch.setattr(
        command,
        "build_recover_report",
        lambda: {
            "schema_version": "1.0",
            "phase": "recover",
            "result": result_state,
            "run_id": "run_" + "1" * 32,
            "generated_at": "2026-08-04T18:00:00Z",
            "recoveries": [],
            "next_actions": ["No interrupted reconciliation requires recovery."],
        },
    )

    invocation = CliRunner().invoke(command.reconcile_app, ["recover", "--json"])

    assert invocation.exit_code == exit_code
    report = json.loads(invocation.stdout)
    assert report["phase"] == "recover"
    assert not list(_validator().iter_errors(report))
