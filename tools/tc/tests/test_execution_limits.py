"""Real SQLite/process regressions for persistent scope and attempt limits."""

import concurrent.futures
import json
import sys
from pathlib import Path

import pytest
from tc import api
from tc.commands.execution import execute_command
from tc.db.connection import get_db
from tc.db.exceptions import ValidationError
from tc.services import execution as ex


@pytest.fixture
def guarded(db_path):
    root = db_path.parent.parent
    (root / "code.py").write_text("value = 1\n")
    contract = {
        "schemaVersion": 2,
        "criteria": [{"id": "DELIVERY", "expected": "A usable result arrives."}],
        "sources": ["code.py"],
    }
    task = api.create_task(
        title="Fixed scope",
        metadata={"requiresQa": True, "acceptanceContract": contract},
        db_path=db_path,
    )
    return task["id"], root, contract


def register(db_path, guarded, **kwargs):
    return ex.register_limits(
        task_id=guarded[0],
        attempts=kwargs.get("attempts", 5),
        calls=kwargs.get("calls", 10),
        cost_usd=kwargs.get("usd", 2),
        authority=["owner-message:test-approval"],
        timeout_seconds=kwargs.get("timeout", 30),
        stale_seconds=1,
        db_path=db_path,
    )


def start(db_path, guarded, label="round1", calls=1, usd=".2"):
    return ex.begin_attempt(
        task_id=guarded[0],
        criterion="DELIVERY",
        label=label,
        reserve_calls=calls,
        reserve_usd=usd,
        db_path=db_path,
    )


def finish(db_path, guarded, attempt, success=False, **kwargs):
    artifact = guarded[1] / (attempt["token"] + ".log")
    artifact.write_text("observed test result\n")
    return ex.settle_attempt(
        token=attempt["token"],
        succeeded=success,
        artifact=artifact,
        db_path=db_path,
        **kwargs,
    )


def test_new_round_and_new_connection_cannot_reset_attempts(db_path, guarded):
    register(db_path, guarded, attempts=1)
    a = start(db_path, guarded)
    finish(db_path, guarded, a, success=True)
    with pytest.raises(ValidationError, match="Cumulative"):
        start(db_path, guarded, label="new-tranche-new-process")
    assert (
        ex.execution_status(task_id=guarded[0], db_path=db_path)["usage"]["attempts"]
        == 1
    )


def test_registration_and_metadata_cannot_widen_scope_or_caps(db_path, guarded):
    register(db_path, guarded)
    assert register(db_path, guarded)["attempts"] == 5
    with pytest.raises(ValidationError, match="immutable"):
        register(db_path, guarded, attempts=500)
    changed = {
        **guarded[2],
        "criteria": [{"id": "EASIER", "expected": "Anything returns."}],
    }
    with pytest.raises(ValidationError, match="frozen"):
        api.update_task(
            task_id=guarded[0],
            metadata={"acceptanceContract": changed},
            db_path=db_path,
        )
    with pytest.raises(ValidationError, match="outside"):
        ex.begin_attempt(
            task_id=guarded[0], criterion="EASIER", label="x", db_path=db_path
        )


def test_crash_reservation_and_concurrent_start_do_not_double_spend(db_path, guarded):
    register(db_path, guarded, attempts=3, calls=2, usd=".5")

    def begin():
        try:
            return start(db_path, guarded, calls=2, usd=".5")["token"]
        except ValidationError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(lambda _: begin(), range(2)))
    assert sum(t is not None for t in tokens) == 1
    state = ex.execution_status(task_id=guarded[0], db_path=db_path)
    assert state["usage"]["calls"] == 2 and state["usage"]["cost_usd"] == 0.5
    with pytest.raises(ValidationError, match="unsettled"):
        start(db_path, guarded)


def test_actual_spend_is_cumulative_and_missing_receipts_cost_full_reserve(
    db_path, guarded
):
    register(db_path, guarded, calls=3, usd=".3")
    a = start(db_path, guarded, usd=".2")
    finish(db_path, guarded, a, success=True)
    with pytest.raises(ValidationError, match="Cumulative"):
        start(db_path, guarded, usd=".2")
    b = start(db_path, guarded, usd=".1")
    finish(db_path, guarded, b, success=True, calls=1, cost_usd=".1")
    assert (
        ex.execution_status(task_id=guarded[0], db_path=db_path)["usage"]["cost_usd"]
        == 0.3
    )


def test_preflight_counts_retries_before_outbound_and_rejects_stale_token(
    db_path, guarded
):
    register(db_path, guarded)
    a = start(db_path, guarded)
    assert ex.consume_call(token=a["token"], db_path=db_path)["calls"] == 1
    with pytest.raises(ValidationError, match="exhausted"):
        ex.consume_call(token=a["token"], db_path=db_path)
    with pytest.raises(ValidationError, match="reduce"):
        finish(db_path, guarded, a, calls=0)
    finish(db_path, guarded, a, calls=1)
    with pytest.raises(ValidationError, match="settled"):
        ex.consume_call(token=a["token"], db_path=db_path)


def test_two_failures_need_changed_source_and_real_regression_without_reset(
    db_path, guarded
):
    register(db_path, guarded)
    for label in ("first", "new-tranche"):
        finish(db_path, guarded, start(db_path, guarded, label))
    with pytest.raises(ValidationError, match="Two failed"):
        start(db_path, guarded, "third")
    unchanged = execute_command(
        task=guarded[0],
        criterion="DELIVERY",
        command=[sys.executable, "-c", "assert 1 == 1"],
        db_path=db_path,
        offline=True,
    )
    with pytest.raises(ValidationError, match="unchanged"):
        ex.diagnosis_checkpoint(
            task_id=guarded[0],
            criterion="DELIVERY",
            regression=unchanged["artifact"],
            db_path=db_path,
        )
    (guarded[1] / "code.py").write_text("value = 2\n")
    with pytest.raises(ValidationError, match="Two failed"):
        start(db_path, guarded)
    proof = execute_command(
        task=guarded[0],
        criterion="DELIVERY",
        command=[sys.executable, "-c", "assert 1 == 1"],
        db_path=db_path,
        offline=True,
    )
    ex.diagnosis_checkpoint(
        task_id=guarded[0],
        criterion="DELIVERY",
        regression=proof["artifact"],
        db_path=db_path,
    )
    start(db_path, guarded, "corrected")
    state = ex.execution_status(task_id=guarded[0], db_path=db_path)
    assert state["usage"]["attempts"] == 3 and state["usage"]["calls"] == 3


def test_fake_or_modified_regression_and_failed_test_cannot_unlock(db_path, guarded):
    register(db_path, guarded)
    for _ in range(2):
        finish(db_path, guarded, start(db_path, guarded))
    (guarded[1] / "code.py").write_text("changed\n")
    proof = execute_command(
        task=guarded[0],
        criterion="DELIVERY",
        command=[sys.executable, "-c", "raise SystemExit(1)"],
        db_path=db_path,
        offline=True,
    )
    with pytest.raises(ValidationError, match="recorded"):
        ex.diagnosis_checkpoint(
            task_id=guarded[0],
            criterion="DELIVERY",
            regression=proof["artifact"],
            db_path=db_path,
        )
    data = json.loads(Path(proof["artifact"]).read_text())
    data["exit_code"] = 0
    Path(proof["artifact"]).write_text(json.dumps(data))
    with pytest.raises(ValidationError, match="recorded"):
        ex.diagnosis_checkpoint(
            task_id=guarded[0],
            criterion="DELIVERY",
            regression=proof["artifact"],
            db_path=db_path,
        )


def test_stale_session_preserves_authority_and_reserved_usage(db_path, guarded):
    register(db_path, guarded)
    a = start(db_path, guarded)
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE execution_attempts SET started=started-100 WHERE token=?",
            (a["token"],),
        )
    s = ex.execution_status(task_id=guarded[0], db_path=db_path)
    assert s["state"] == "stale_progress" and s["qa_approved"] is False
    assert s["authority"] == ["owner-message:test-approval"]
    assert s["usage"]["cost_usd"] == 0.2


def test_guarded_command_timeout_settles_conservatively(db_path, guarded):
    register(db_path, guarded, timeout=1)
    result = execute_command(
        task=guarded[0],
        criterion="DELIVERY",
        command=[sys.executable, "-c", "import time; time.sleep(20)"],
        calls=2,
        usd=".5",
        db_path=db_path,
    )
    assert result["exit_code"] == 124
    status = ex.execution_status(task_id=guarded[0], db_path=db_path)
    assert status["attempts"][0]["state"] == "failed"
    assert status["usage"]["calls"] == 2 and status["usage"]["cost_usd"] == 0.5


def test_cli_run_declines_exhausted_budget_before_child_starts(cli, db_path, guarded):
    register(db_path, guarded, attempts=1)
    first = cli(
        [
            "execution",
            "run",
            str(guarded[0]),
            "--criterion",
            "DELIVERY",
            "--",
            sys.executable,
            "-c",
            'print("checked")',
        ]
    )
    assert first.exit_code == 0, first.output
    marker = guarded[1] / "should-not-exist"
    second = cli(
        [
            "execution",
            "run",
            str(guarded[0]),
            "--criterion",
            "DELIVERY",
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ]
    )
    assert second.exit_code == 4 and not marker.exists()


@pytest.mark.parametrize("usd", ["NaN", "-1", "Infinity"])
def test_nonfinite_or_negative_budget_rejected(db_path, guarded, usd):
    with pytest.raises(ValidationError):
        register(db_path, guarded, usd=usd)


def test_source_change_during_attempt_blocks_next_live_call(db_path, guarded):
    register(db_path, guarded)
    a = start(db_path, guarded)
    (guarded[1] / "code.py").write_text("value = 3\n")
    with pytest.raises(ValidationError, match="Source changed"):
        ex.consume_call(token=a["token"], db_path=db_path)


def test_handoff_preserves_authority_and_running_state_in_api_and_cli(
    db_path, guarded, cli
):
    register(db_path, guarded)
    start(db_path, guarded)
    result = api.handoff_task(
        task_id=guarded[0],
        from_agent="me",
        to_agent="qa",
        context="Original test migration already authorized",
        db_path=db_path,
    )
    assert result["execution"]["state"] == "awaiting_result"
    assert result["execution"]["authority"] == ["owner-message:test-approval"]
    actual = cli(
        [
            "handoff",
            "--from",
            "qa",
            "--to",
            "me",
            "--task",
            str(guarded[0]),
            "--context",
            "Continue",
            "--json",
        ]
    )
    assert actual.exit_code == 0, actual.output
    assert json.loads(actual.output)["execution"]["usage"]["attempts"] == 1


def test_worker_requires_limits_and_blocks_exhausted_budget_before_launch(
    db_path, guarded
):
    from tc.commands.worker import dispatch

    cmd = [sys.executable, "-c", 'print("{}")', "--max-budget-usd", ".1"]
    with pytest.raises(ValidationError, match="registered"):
        dispatch(guarded[0], cmd=cmd, agent="me", criterion="DELIVERY", db_path=db_path)
    register(db_path, guarded, attempts=1)
    cmd = [
        sys.executable,
        "-c",
        "print('{\"total_cost_usd\": 0.02}')",
        "--max-budget-usd",
        ".1",
    ]
    result = dispatch(
        guarded[0], cmd=cmd, agent="me", criterion="DELIVERY", db_path=db_path
    )
    assert result["returncode"] == 0
    assert (
        ex.execution_status(task_id=guarded[0], db_path=db_path)["usage"]["cost_usd"]
        == 0.02
    )
    marker = guarded[1] / "worker-should-not-run"
    cmd = [
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(marker)!r}).touch()",
        "--max-budget-usd",
        ".1",
    ]
    with pytest.raises(ValidationError, match="Cumulative"):
        dispatch(guarded[0], cmd=cmd, agent="me", criterion="DELIVERY", db_path=db_path)
    assert not marker.exists()


def test_current_qa_prevents_reopening_and_repeating_passing_work(db_path, guarded):
    register(db_path, guarded)
    identity = api.capture_qa_identity(task_id=guarded[0], db_path=db_path)[
        "identity_line"
    ]
    body = (
        "CRITERION: DELIVERY\nEXPECTED: A usable result arrives.\nOBSERVED: delivered\n"
        + identity
        + "\nBASELINE: old failure\nARTIFACT: test-run|fixture exit=0\nUNTESTED: none\nVERDICT: APPROVED\n"
    )
    api.store_wp(
        task_id=guarded[0],
        type_="test",
        title="QA fixture",
        content=body,
        db_path=db_path,
    )
    with pytest.raises(ValidationError, match="already passes"):
        start(db_path, guarded)
    api.update_task(task_id=guarded[0], status="completed", db_path=db_path)
    with pytest.raises(ValidationError, match="do not reopen"):
        api.update_task(task_id=guarded[0], status="in_progress", db_path=db_path)
    # A source change invalidates the old approval, so justified repair can reopen.
    (guarded[1] / "code.py").write_text("changed\n")
    api.update_task(task_id=guarded[0], status="in_progress", db_path=db_path)
    start(db_path, guarded)


def test_reported_overrun_is_retained_and_blocks_subsequent_work(db_path, guarded):
    register(db_path, guarded, usd=".2")
    a = start(db_path, guarded)
    result = finish(db_path, guarded, a, success=True, calls=2, cost_usd=".3")
    assert result["state"] == "failed" and result["exceeded"]
    with pytest.raises(ValidationError, match="Cumulative"):
        start(db_path, guarded, calls=0, usd=0)
    assert (
        ex.execution_status(task_id=guarded[0], db_path=db_path)["usage"]["cost_usd"]
        == 0.3
    )
