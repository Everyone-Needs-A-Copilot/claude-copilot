"""CLI-contract tests for `cc settings-hook` -- exit-code mapping and JSON
shape. The underlying ledger/merge logic is covered by
`test_mutations_ledger.py`; this file only exercises the thin Typer layer
(argument threading, `--json`, exit codes per status), monkeypatching the
core calls the same way `test_reconcile_command.py` does.
"""

from __future__ import annotations

import json

from cc.commands import settings_hook as command
from cc.core.ecosystem.mutations import ApplyOutcome, RemoveResult, RollbackResult
from cc.main import app
from typer.testing import CliRunner

runner = CliRunner()


def invoke(*args):
    return runner.invoke(app, list(args))


def test_settings_hook_help_lists_subcommands():
    result = invoke("settings-hook", "--help")
    assert result.exit_code == 0
    assert "add" in result.output
    assert "remove" in result.output
    assert "rollback" in result.output
    assert "list-sources" in result.output


def test_add_applied_exits_zero_and_emits_json(monkeypatch, tmp_path):
    def fake_apply(*args, **kwargs):
        return ApplyOutcome(
            "applied",
            {"id": "mut_deadbeef", "kind": "settings-hook"},
            "Mutation applied.",
            (),
        )

    monkeypatch.setattr(command, "apply_settings_hook", fake_apply)
    result = invoke("settings-hook", "add", "--project", str(tmp_path), "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "applied"
    assert payload["mutation"]["id"] == "mut_deadbeef"


def test_add_conflict_exits_one(monkeypatch, tmp_path):
    def fake_apply(*args, **kwargs):
        return ApplyOutcome("conflict", {"id": "mut_deadbeef"}, "changed since applied", ())

    monkeypatch.setattr(command, "apply_settings_hook", fake_apply)
    result = invoke("settings-hook", "add", "--project", str(tmp_path), "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "conflict"


def test_remove_not_found_exits_one(monkeypatch, tmp_path):
    def fake_remove(*args, **kwargs):
        return RemoveResult("not-found", None, "No such mutation is recorded.")

    monkeypatch.setattr(command, "remove_settings_hook", fake_remove)
    result = invoke(
        "settings-hook", "remove", "--id", "mut_deadbeef", "--project", str(tmp_path), "--json"
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "not-found"


def test_rollback_conflict_exits_one_and_never_claims_restored(monkeypatch, tmp_path):
    def fake_rollback(*args, **kwargs):
        return RollbackResult("conflict", {"id": "mut_deadbeef"}, "changed since applied")

    monkeypatch.setattr(command, "rollback_settings_hook", fake_rollback)
    result = invoke(
        "settings-hook", "rollback", "--id", "mut_deadbeef", "--project", str(tmp_path), "--json"
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "conflict"


def test_rollback_restored_exits_zero(monkeypatch, tmp_path):
    def fake_rollback(*args, **kwargs):
        return RollbackResult("restored", {"id": "mut_deadbeef"}, "restored")

    monkeypatch.setattr(command, "rollback_settings_hook", fake_rollback)
    result = invoke(
        "settings-hook", "rollback", "--id", "mut_deadbeef", "--project", str(tmp_path), "--json"
    )
    assert result.exit_code == 0


def test_list_sources_reports_orphaned_with_attention_exit_code(monkeypatch, tmp_path):
    def fake_list_sources(*args, **kwargs):
        return {
            "schema_version": "1.0",
            "path": str(tmp_path),
            "hooks": [
                {
                    "target": ".claude/settings.json",
                    "event": "PreToolUse",
                    "matcher": "Bash",
                    "command": "echo hi",
                    "classification": "orphaned",
                    "mutation_id": None,
                }
            ],
        }

    monkeypatch.setattr(command, "list_sources", fake_list_sources)
    result = invoke("settings-hook", "list-sources", "--project", str(tmp_path), "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["hooks"][0]["classification"] == "orphaned"


def test_list_sources_clean_exits_zero(monkeypatch, tmp_path):
    def fake_list_sources(*args, **kwargs):
        return {"schema_version": "1.0", "path": str(tmp_path), "hooks": []}

    monkeypatch.setattr(command, "list_sources", fake_list_sources)
    result = invoke("settings-hook", "list-sources", "--project", str(tmp_path), "--json")
    assert result.exit_code == 0
