"""Supplementary coverage must never reset the existing task's budget/failures."""
import json
import sys

import pytest
from typer.testing import CliRunner

from tc import api
from tc.commands.execution import execution_app, execute_command
from tc.db.connection import get_db
from tc.db.exceptions import ValidationError
from tc.services import execution as ex


@pytest.fixture
def guarded(db_path):
    root = db_path.parent.parent
    (root / "code.py").write_text("value = 1\n")
    contract = {"schemaVersion": 2, "criteria": [{"id": "DELIVERY", "expected": "A usable result arrives."}], "sources": ["code.py"]}
    task = api.create_task(title="Coverage fixture", metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
    return task["id"], root, contract


def register(db_path, guarded, attempts=5):
    return ex.register_limits(task_id=guarded[0], attempts=attempts, calls=10, cost_usd=2,
                              authority=["owner-message:test-approval"], timeout_seconds=30,
                              stale_seconds=1, db_path=db_path)


def start(db_path, guarded, label="attempt"):
    return ex.begin_attempt(task_id=guarded[0], criterion="DELIVERY", label=label,
                            reserve_calls=1, reserve_usd=".2", db_path=db_path)


def finish(db_path, guarded, attempt, success=False, **kwargs):
    path = guarded[1] / (attempt["token"] + ".log")
    path.write_text("Observed fixture result\n")
    return ex.settle_attempt(token=attempt["token"], succeeded=success, artifact=path,
                             db_path=db_path, **kwargs)


def add(db_path, guarded, **overrides):
    return ex.add_source_coverage(
        task_id=guarded[0], sources=overrides.get("sources", ["omitted.py"]),
        authority=overrides.get("authority", ["owner-message:test-approval"]),
        reason=overrides.get("reason", "Actual failed harness dependency was omitted"),
        db_path=db_path,
    )


def test_coverage_preserves_contract_caps_receipts_and_failure_block(db_path, guarded):
    register(db_path, guarded)
    (guarded[1] / "omitted.py").write_text("corrected = True\n")
    for label in ("one", "two"):
        finish(db_path, guarded, start(db_path, guarded, label), calls=1, cost_usd=".1")
    before = ex.execution_status(task_id=guarded[0], db_path=db_path)
    with get_db(db_path) as conn:
        original = conn.execute("SELECT policy FROM execution_limits").fetchone()[0]
    result = add(db_path, guarded)
    after = ex.execution_status(task_id=guarded[0], db_path=db_path)
    assert result["sources"] == ["code.py", "omitted.py"]
    assert result["coverage_correction"]["added_manifest"][0]["path"] == "omitted.py"
    assert after["usage"] == before["usage"]
    assert after["remaining"] == before["remaining"]
    assert after["attempts"] == before["attempts"]
    assert after["blocker"] == "diagnosis_required:DELIVERY"
    for key in ("attempts", "calls", "micros", "criteria", "contract_sha256", "root", "authority", "timeout_seconds", "stale_seconds"):
        assert after["limits"][key] == before["limits"][key]
    with get_db(db_path) as conn:
        assert conn.execute("SELECT policy FROM execution_limits").fetchone()[0] == original
    assert json.loads(api.get_task(task_id=guarded[0], db_path=db_path)["metadata"])["acceptanceContract"] == guarded[2]
    with pytest.raises(ValidationError, match="Two failed"):
        start(db_path, guarded, "still blocked")


@pytest.mark.parametrize("sources", [[], ["code.py"], ["missing.py"], ["."], ["../other.py"], ["/tmp/outside"], ["omitted.py", "omitted.py"]])
def test_invalid_or_nonadditive_paths_leave_lineage_unchanged(db_path, guarded, sources):
    register(db_path, guarded)
    (guarded[1] / "omitted.py").write_text("x=1")
    with pytest.raises(ValidationError):
        add(db_path, guarded, sources=sources)
    assert ex.execution_status(task_id=guarded[0], db_path=db_path)["round"] == 1


def test_rejects_symlink_and_active_attempt(db_path, guarded):
    register(db_path, guarded)
    (guarded[1] / "omitted.py").symlink_to(guarded[1] / "code.py")
    with pytest.raises(ValidationError, match="symlink"):
        add(db_path, guarded)
    start(db_path, guarded)
    with pytest.raises(ValidationError, match="unsettled"):
        add(db_path, guarded)


@pytest.mark.parametrize("authority,reason", [([], "why"), (["new spending authority"], "why"), (["owner-message:test-approval"], "")])
def test_requires_existing_authority_and_reason(db_path, guarded, authority, reason):
    register(db_path, guarded)
    with pytest.raises(ValidationError):
        add(db_path, guarded, authority=authority, reason=reason)


def test_cap_exhaustion_cannot_be_reset_by_coverage(db_path, guarded):
    register(db_path, guarded, attempts=1)
    finish(db_path, guarded, start(db_path, guarded), success=True)
    (guarded[1] / "omitted.py").write_text("x=1")
    add(db_path, guarded)
    assert ex.execution_status(task_id=guarded[0], db_path=db_path)["blocker"] == "cumulative_limit"
    with pytest.raises(ValidationError, match="Cumulative"):
        start(db_path, guarded)


def test_old_proof_is_stale_and_fresh_proof_requires_explicit_diagnosis(db_path, guarded):
    register(db_path, guarded)
    for _ in range(2):
        finish(db_path, guarded, start(db_path, guarded))
    old = execute_command(db_path=db_path, task=guarded[0], criterion="DELIVERY", label="old", calls=0, usd=0, command=[sys.executable, "-c", "pass"], offline=True)
    (guarded[1] / "omitted.py").write_text("x=1")
    add(db_path, guarded)
    with pytest.raises(ValidationError, match="recorded by tc execution prove"):
        ex.diagnosis_checkpoint(task_id=guarded[0], criterion="DELIVERY", regression=old["artifact"], db_path=db_path)
    fresh = execute_command(db_path=db_path, task=guarded[0], criterion="DELIVERY", label="fresh", calls=0, usd=0, command=[sys.executable, "-c", "pass"], offline=True)
    assert ex.execution_status(task_id=guarded[0], db_path=db_path)["blocker"] == "diagnosis_required:DELIVERY"
    ex.diagnosis_checkpoint(task_id=guarded[0], criterion="DELIVERY", regression=fresh["artifact"], db_path=db_path)
    assert ex.execution_status(task_id=guarded[0], db_path=db_path)["blocker"] is None


def test_cli_routes_to_additive_api(db_path, guarded, monkeypatch):
    register(db_path, guarded)
    (guarded[1] / "omitted.py").write_text("x=1")
    monkeypatch.setattr("tc.commands.execution.require_db", lambda: db_path)
    result = CliRunner().invoke(execution_app, ["add-coverage", str(guarded[0]), "--source", "omitted.py", "--authority", "owner-message:test-approval", "--reason", "omitted harness"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["round"] == 2
