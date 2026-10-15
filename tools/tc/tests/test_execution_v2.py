"""Policy v2: project budget, progress/ceiling stops, auto-reconcile, migration.

Real SQLite and subprocess runs, mirroring test_execution_limits.py. v1 behavior is
covered there and must keep passing unchanged.
"""

import hashlib
import json
import sys

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
        "criteria": [
            {"id": "DELIVERY", "expected": "A usable result arrives."},
            {"id": "SECOND", "expected": "A second result arrives."},
        ],
        "sources": ["code.py"],
    }
    task = api.create_task(
        title="Fixed scope",
        metadata={"requiresQa": True, "acceptanceContract": contract},
        db_path=db_path,
    )
    return task["id"], root, contract


def make_task(db_path, root, title="another"):
    contract = {
        "schemaVersion": 2,
        "criteria": [{"id": "DELIVERY", "expected": "A usable result arrives."}],
        "sources": ["code.py"],
    }
    return api.create_task(
        title=title,
        metadata={"requiresQa": True, "acceptanceContract": contract},
        db_path=db_path,
    )["id"]


def v2(db_path, task_id, **kw):
    kw.setdefault("timeout_seconds", 30)
    return ex.register_limits(task_id=task_id, db_path=db_path, **kw)


def v1(db_path, task_id, attempts=5, calls=10, usd=2, authority=None):
    return ex.register_limits(
        task_id=task_id,
        attempts=attempts,
        calls=calls,
        cost_usd=usd,
        authority=authority or ["owner-message:test-approval"],
        timeout_seconds=30,
        db_path=db_path,
    )


def begin(db_path, task_id, label="x", criterion="DELIVERY", calls=0, usd=0):
    return ex.begin_attempt(
        task_id=task_id,
        criterion=criterion,
        label=label,
        reserve_calls=calls,
        reserve_usd=usd,
        db_path=db_path,
    )


def settle(db_path, root, attempt, success=True, text="same observed result\n", **kw):
    artifact = root / (attempt["token"] + ".log")
    artifact.write_text(text)
    return ex.settle_attempt(
        token=attempt["token"],
        succeeded=success,
        artifact=artifact,
        db_path=db_path,
        **kw,
    )


def status(db_path, task_id):
    return ex.execution_status(task_id=task_id, db_path=db_path)


def table_dump(db_path, *tables):
    with get_db(db_path) as conn:
        return {
            t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1,2")]
            for t in tables
        }


# --- T1: schema, validation, dispatch, project usage -------------------------------


def test_budget_table_is_additive_and_legacy_database_opens(db_path, guarded):
    with get_db(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS execution_budgets")
    v1(db_path, guarded[0])
    assert status(db_path, guarded[0])["state"] == "idle"
    with get_db(db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_budgets'"
        ).fetchone()


def test_v2_fields_validated_and_attempts_mirror_ceiling(db_path, guarded):
    p = v2(db_path, guarded[0], ceiling_attempts=7)
    assert p["policy_version"] == 2 and p["attempts"] == 7 == p["ceiling_attempts"]
    assert (p["no_progress_n"], p["ceiling_seconds"]) == (3, 6 * 3600)
    for bad in ({"no_progress_n": 0}, {"ceiling_attempts": 0}, {"ceiling_seconds": 0}):
        with pytest.raises(ValidationError):
            v2(db_path, guarded[0], **bad)
    with pytest.raises(ValidationError, match="project budget"):
        v2(db_path, guarded[0], calls=1)
    with pytest.raises(ValidationError, match="project budget"):
        v2(db_path, guarded[0], cost_usd=".5")


def test_v1_policy_is_unchanged_without_new_keys(db_path, guarded):
    p = v1(db_path, guarded[0])
    assert "policy_version" not in p and p["attempts"] == 5
    state = status(db_path, guarded[0])
    assert "budget" not in state and state["remaining"]["attempts"] == 5


def test_project_usage_matches_single_task_and_sums_across_tasks(db_path, guarded):
    other = make_task(db_path, guarded[1])
    v2(db_path, guarded[0])
    v2(db_path, other)
    ex.set_budget(calls=10, cost_usd=5, authority=["q1"], db_path=db_path)
    a = begin(db_path, guarded[0], calls=2, usd=".5")
    with get_db(db_path) as conn:
        project = ex._default_project(conn)
        single = ex._usage(ex._rows(conn, guarded[0]))
        assert ex._project_usage(conn, project) == {
            "calls": single["calls"],
            "micros": single["micros"],
        }
    settle(db_path, guarded[1], a, calls=1, cost_usd=".25")
    b = begin(db_path, other, calls=3, usd=".5")
    with get_db(db_path) as conn:
        total = ex._project_usage(conn, project)
    assert total == {"calls": 4, "micros": 750_000}
    settle(db_path, guarded[1], b, calls=3, cost_usd=".5")


def test_tasks_registered_against_different_roots_share_the_project_budget(
    db_path, guarded, tmp_path
):
    wt = tmp_path / "linked-worktree"
    wt.mkdir()
    (wt / "code.py").write_text("value = 1\n")
    other = make_task(db_path, guarded[1])
    v2(db_path, guarded[0])
    v2(db_path, other, root=wt)
    ex.set_budget(calls=3, cost_usd=1, authority=["q"], db_path=db_path)
    settle(db_path, guarded[1], begin(db_path, guarded[0], calls=2, usd=".5"), calls=2, cost_usd=".5")
    with pytest.raises(ValidationError, match="DECISION NEEDED"):
        begin(db_path, other, calls=2, usd=".1")  # 2 + 2 > 3 across both roots


# --- T4: project budget ------------------------------------------------------------


def test_missing_budget_means_zero_paid_but_local_work_runs(db_path, guarded):
    v2(db_path, guarded[0])
    settle(db_path, guarded[1], begin(db_path, guarded[0]))
    with pytest.raises(ValidationError, match="DECISION NEEDED"):
        begin(db_path, guarded[0], "x2", calls=1, usd=".1")


def test_budget_set_appends_rounds_and_refuses_repeat_or_lower(db_path, guarded):
    v2(db_path, guarded[0])
    first = ex.set_budget(calls=10, cost_usd=5, authority=["Pablo: $5"], db_path=db_path)
    assert first["round"] == 1 and first["cost_usd"] == 5
    with pytest.raises(ValidationError, match="DECISION NEEDED.*new verbatim"):
        ex.set_budget(calls=20, cost_usd=9, authority=["Pablo: $5"], db_path=db_path)
    with pytest.raises(ValidationError, match="only rise"):
        ex.set_budget(calls=5, cost_usd=9, authority=["Pablo: lower"], db_path=db_path)
    second = ex.set_budget(calls=20, cost_usd=9, authority=["Pablo: $9"], db_path=db_path)
    assert second["round"] == 2 and second["authority"] == ["Pablo: $5", "Pablo: $9"]


def test_spend_within_budget_is_silent_and_exceeding_asks(db_path, guarded):
    v2(db_path, guarded[0])
    ex.set_budget(calls=3, cost_usd="1.00", authority=["Pablo: $1"], db_path=db_path)
    a = begin(db_path, guarded[0], calls=2, usd=".6")  # no authority needed
    settle(db_path, guarded[1], a, calls=2, cost_usd=".6")
    with pytest.raises(ValidationError) as err:
        begin(db_path, guarded[0], "over", calls=2, usd=".6")
    message = str(err.value)
    assert message.startswith("DECISION NEEDED: $0.20 over")
    assert "1 more paid calls" in message and "task " in message
    view = ex.budget_status(db_path=db_path)
    assert view["used_calls"] == 2 and view["remaining_calls"] == 1


def test_spend_never_decreases_through_any_api(db_path, guarded):
    v2(db_path, guarded[0])
    ex.set_budget(calls=5, cost_usd=2, authority=["q"], db_path=db_path)
    a = begin(db_path, guarded[0], calls=2, usd=".5")
    settle(db_path, guarded[1], a, calls=2, cost_usd=".5")
    before = ex.budget_status(db_path=db_path)
    with pytest.raises(ValidationError):
        ex.set_budget(calls=1, cost_usd=0, authority=["lower"], db_path=db_path)
    ex.reopen_ceiling(task_id=guarded[0], decision="keep going", db_path=db_path)
    after = ex.budget_status(db_path=db_path)
    assert (after["used_calls"], after["used_cost_usd"]) == (
        before["used_calls"],
        before["used_cost_usd"],
    )


def test_paid_raise_needs_quote_but_local_reopen_does_not(db_path, guarded):
    v2(db_path, guarded[0], ceiling_attempts=1)
    settle(db_path, guarded[1], begin(db_path, guarded[0]))
    with pytest.raises(ValidationError, match="ceiling"):
        begin(db_path, guarded[0], "next")
    ex.set_budget(calls=1, cost_usd=1, authority=["Pablo: $1"], db_path=db_path)
    with pytest.raises(ValidationError, match="new verbatim owner authority"):
        ex.set_budget(calls=9, cost_usd=9, authority=["Pablo: $1"], db_path=db_path)
    ex.reopen_ceiling(task_id=guarded[0], decision="Pablo: continue", db_path=db_path)
    begin(db_path, guarded[0], "next")  # no quote involved
    with pytest.raises(ValidationError, match="budget set"):
        ex.succeed_limits(
            task_id=guarded[0],
            attempts=9,
            calls=1,
            cost_usd=1,
            authority=["x"],
            db_path=db_path,
        )


# --- T5: progress stop and ceiling ---------------------------------------------------


def test_no_fixed_attempt_cap_below_ceiling(db_path, guarded):
    v2(db_path, guarded[0], no_progress_n=100)
    for i in range(8):  # v1 default was 4-5; none of these is capped
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=str(i)))
    assert status(db_path, guarded[0])["usage"]["attempts"] == 8


def test_n_non_progress_attempts_stop_with_report_not_approval(db_path, guarded):
    v2(db_path, guarded[0])
    for i in range(4):  # first passes DELIVERY; the next three repeat it unchanged
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=str(i)))
    s = status(db_path, guarded[0])
    assert s["state"] == "no_progress" and s["blocker"] == "no_progress"
    assert s["progress"]["non_progress_streak"] == 3
    with pytest.raises(ValidationError) as err:
        begin(db_path, guarded[0], "again")
    assert str(err.value).startswith("STOPPED: no_progress")
    assert "DECISION NEEDED" not in str(err.value)
    assert "attempts used 4" in str(err.value)


def test_progress_signals_reset_the_window(db_path, guarded):
    v2(db_path, guarded[0])
    for i in range(3):
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=str(i)))
    assert status(db_path, guarded[0])["progress"]["non_progress_streak"] == 2
    # new passing criterion
    settle(db_path, guarded[1], begin(db_path, guarded[0], "s", "SECOND"))
    assert status(db_path, guarded[0])["progress"]["non_progress_streak"] == 0
    # new evidence
    for i in range(2):
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=f"r{i}"))
    settle(db_path, guarded[1], begin(db_path, guarded[0], label="e"), text="different\n")
    assert status(db_path, guarded[0])["progress"]["non_progress_streak"] == 0
    # new source
    for i in range(2):
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=f"q{i}"), text="different\n")
    (guarded[1] / "code.py").write_text("value = 2\n")
    settle(db_path, guarded[1], begin(db_path, guarded[0], label="src"), text="different\n")
    assert status(db_path, guarded[0])["progress"]["non_progress_streak"] == 0


def test_receipt_evidence_ignores_timings_and_counts(db_path, guarded):
    v2(db_path, guarded[0])
    for n in (11, 222, 3333, 44444):
        execute_command(
            task=guarded[0],
            criterion="DELIVERY",
            command=[sys.executable, "-c", f"print('took {n}.5s, {n} checks')"],
            db_path=db_path,
        )
    assert status(db_path, guarded[0])["state"] == "no_progress"


def test_diagnosis_checkpoint_on_changed_source_reopens_no_progress(db_path, guarded):
    v2(db_path, guarded[0])
    for i in range(2):
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=f"f{i}"), success=False)
    with pytest.raises(ValidationError, match="Two failed"):
        begin(db_path, guarded[0], "third")
    (guarded[1] / "code.py").write_text("value = 2\n")
    proof = execute_command(
        task=guarded[0],
        criterion="DELIVERY",
        command=[sys.executable, "-c", "assert True"],
        db_path=db_path,
        offline=True,
    )
    ex.diagnosis_checkpoint(
        task_id=guarded[0],
        criterion="DELIVERY",
        regression=proof["artifact"],
        db_path=db_path,
    )
    begin(db_path, guarded[0], "after-diagnosis")
    assert status(db_path, guarded[0])["state"] == "awaiting_result"


def test_ceiling_by_attempts_halts_and_needs_a_new_owner_decision(db_path, guarded):
    v2(db_path, guarded[0], ceiling_attempts=3, no_progress_n=50)
    for i in range(3):
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=str(i)))
    s = status(db_path, guarded[0])
    assert s["state"] == "ceiling_reached" and s["remaining"]["attempts"] == 0
    with pytest.raises(ValidationError) as err:
        begin(db_path, guarded[0], "more")
    assert str(err.value).startswith("DECISION NEEDED:")
    assert "STOPPED: ceiling_reached" in str(err.value)
    reopened = ex.reopen_ceiling(
        task_id=guarded[0], decision="Pablo: yes", ceiling_attempts=5, db_path=db_path
    )
    assert reopened["round"] == 2 and reopened["attempts"] == 5
    with pytest.raises(ValidationError, match="new owner decision"):
        ex.reopen_ceiling(task_id=guarded[0], decision="Pablo: yes", db_path=db_path)
    begin(db_path, guarded[0], "resumed")
    s = status(db_path, guarded[0])
    assert s["usage"]["attempts"] == 4 and s["lineage"][1]["kind"] == "reopen"
    assert s["lineage"][1]["decision"] == ["Pablo: yes"]


def test_ceiling_by_cumulative_runtime_halts(db_path, guarded):
    v2(db_path, guarded[0], ceiling_seconds=100, no_progress_n=50)
    a = begin(db_path, guarded[0])
    settle(db_path, guarded[1], a)
    with get_db(db_path) as conn:
        conn.execute("UPDATE execution_attempts SET started=ended-150")
    assert status(db_path, guarded[0])["state"] == "ceiling_reached"
    with pytest.raises(ValidationError, match="ceiling_reached"):
        begin(db_path, guarded[0], "more")
    with pytest.raises(ValidationError, match="can only rise"):
        ex.reopen_ceiling(
            task_id=guarded[0], decision="d", ceiling_seconds=50, db_path=db_path
        )


def test_reopen_refuses_v1_and_cannot_lower(db_path, guarded):
    v1(db_path, guarded[0])
    with pytest.raises(ValidationError, match="policy v2"):
        ex.reopen_ceiling(task_id=guarded[0], decision="d", db_path=db_path)


def test_two_failure_gate_is_unchanged_for_v2(db_path, guarded):
    v2(db_path, guarded[0], no_progress_n=50)
    for i in range(2):
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=str(i)), success=False, text=f"x{i}")
    with pytest.raises(ValidationError, match="Two failed"):
        begin(db_path, guarded[0], "third")
    assert status(db_path, guarded[0])["blocker"] == "diagnosis_required:DELIVERY"


# --- T6: auto-reconcile --------------------------------------------------------------


def age(db_path, token, seconds=10_000):
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE execution_attempts SET started=started-? WHERE token=?",
            (seconds, token),
        )


def test_timed_out_zero_paid_attempt_is_auto_abandoned_on_begin_and_status(db_path, guarded):
    v2(db_path, guarded[0])
    a = begin(db_path, guarded[0])
    with pytest.raises(ValidationError, match="unsettled"):
        begin(db_path, guarded[0], "too-soon")
    age(db_path, a["token"])
    s = status(db_path, guarded[0])
    row = s["attempts"][0]
    assert row["state"] == "abandoned"
    assert row["reason"] == "auto-reconciled: timed out, zero paid"
    b = begin(db_path, guarded[0], "next")
    assert b["token"] != a["token"]


def test_begin_reconciles_even_when_it_then_refuses(db_path, guarded):
    v2(db_path, guarded[0], ceiling_attempts=1)
    a = begin(db_path, guarded[0])
    age(db_path, a["token"])
    with pytest.raises(ValidationError, match="ceiling_reached"):
        begin(db_path, guarded[0], "x")
    with get_db(db_path) as conn:
        state = conn.execute("SELECT state FROM execution_attempts").fetchone()[0]
    assert state == "abandoned"


def test_paid_or_consumed_attempts_keep_lock_and_full_charge(db_path, guarded):
    v2(db_path, guarded[0])
    ex.set_budget(calls=5, cost_usd=2, authority=["q"], db_path=db_path)
    paid = begin(db_path, guarded[0], calls=2, usd=".5")
    age(db_path, paid["token"])
    assert status(db_path, guarded[0])["attempts"][0]["state"] == "running"
    with pytest.raises(ValidationError, match="unsettled"):
        begin(db_path, guarded[0], "blocked")
    assert ex.budget_status(db_path=db_path)["used_calls"] == 2


def test_auto_reconciled_attempts_count_toward_two_failure_rule(db_path, guarded):
    v2(db_path, guarded[0], no_progress_n=50)
    for i in range(2):
        a = begin(db_path, guarded[0], label=str(i))
        age(db_path, a["token"])
        status(db_path, guarded[0])
    with pytest.raises(ValidationError, match="Two failed"):
        begin(db_path, guarded[0], "third")


def test_v1_tasks_are_not_auto_reconciled(db_path, guarded):
    v1(db_path, guarded[0])
    a = begin(db_path, guarded[0])
    age(db_path, a["token"])
    assert status(db_path, guarded[0])["attempts"][0]["state"] == "running"


# --- T7: migration -------------------------------------------------------------------


LEDGER = ("execution_limits", "execution_attempts", "execution_checkpoints", "execution_rounds")


def seeded_v1(db_path, guarded):
    other = make_task(db_path, guarded[1])
    v1(db_path, guarded[0], attempts=3, calls=4, usd="1.5", authority=["quote A"])
    v1(db_path, other, attempts=2, calls=3, usd="0.5", authority=["quote B"])
    for i in range(3):
        a = begin(db_path, guarded[0], label=str(i), calls=1, usd=".1")
        settle(db_path, guarded[1], a, calls=1, cost_usd=".1", success=bool(i == 0))
    return other


def test_dry_run_writes_nothing_and_reports_every_v1_task(db_path, guarded):
    other = seeded_v1(db_path, guarded)
    before = table_dump(db_path, *LEDGER, "execution_budgets")
    report = ex.migrate_ledgers(db_path=db_path, dry_run=True)
    assert table_dump(db_path, *LEDGER, "execution_budgets") == before
    by_task = {t["task_id"]: t for t in report["tasks"]}
    assert by_task[guarded[0]]["prior_state"] == "exhausted"
    assert by_task[guarded[0]]["result"] == "would_migrate"
    assert by_task[other]["prior_state"] == "idle"
    assert report["budgets"][0]["add_calls"] == 7
    assert report["budgets"][0]["add_cost_usd"] == 2.0
    assert report["backup"] is None


def test_migration_appends_without_touching_history_and_preserves_spend(db_path, guarded):
    other = seeded_v1(db_path, guarded)
    before_usage = status(db_path, guarded[0])["usage"]
    contract_before = status(db_path, guarded[0])["limits"]["contract_sha256"]
    snapshot = table_dump(db_path, "execution_limits", "execution_attempts", "execution_checkpoints")
    report = ex.migrate_ledgers(db_path=db_path)
    assert report["backup"] and report["tasks"][0]["result"] == "migrated"
    after = table_dump(db_path, "execution_limits", "execution_attempts", "execution_checkpoints")
    assert after == snapshot  # round 1, attempts, checkpoints byte-identical
    with get_db(db_path) as conn:
        rounds = conn.execute(
            "SELECT task_id, round, predecessor_round, used_attempts, used_calls, used_micros FROM execution_rounds ORDER BY task_id"
        ).fetchall()
    assert [tuple(r) for r in rounds] == [
        (guarded[0], 2, 1, 3, 3, 300_000),
        (other, 2, 1, 0, 0, 0),
    ]
    s = status(db_path, guarded[0])
    assert s["usage"] == before_usage
    assert s["limits"]["contract_sha256"] == contract_before
    assert s["limits"]["policy_version"] == 2 and s["round"] == 2
    assert s["limits"]["attempts"] == 50  # old runtimes still see a sane cap
    # The v1 cap no longer blocks it; only the unchanged two-failure gate remains.
    assert s["blocker"] == "diagnosis_required:DELIVERY"
    assert s["remaining"]["attempts"] == 47
    budget = ex.budget_status(db_path=db_path)
    assert budget["calls"] == 7 and budget["cost_usd"] == 2.0
    assert budget["used_calls"] == 3 and budget["remaining_calls"] == 4
    assert {"quote A", "quote B"} <= set(budget["authority"])


def test_migration_is_idempotent(db_path, guarded):
    seeded_v1(db_path, guarded)
    ex.migrate_ledgers(db_path=db_path)
    state = table_dump(db_path, *LEDGER, "execution_budgets")
    second = ex.migrate_ledgers(db_path=db_path)
    assert {t["result"] for t in second["tasks"]} == {"already_v2"}
    assert table_dump(db_path, *LEDGER, "execution_budgets") == state


def test_migration_skips_paid_running_attempts_and_reconciles_dead_zero_paid(db_path, guarded):
    other = make_task(db_path, guarded[1])
    v1(db_path, guarded[0], calls=2, usd=1)
    v1(db_path, other, calls=0, usd=0)
    paid = begin(db_path, guarded[0], calls=1, usd=".5")
    dead = begin(db_path, other)
    age(db_path, dead["token"])
    report = {t["task_id"]: t for t in ex.migrate_ledgers(db_path=db_path)["tasks"]}
    assert report[guarded[0]]["result"] == "skipped_running_attempt"
    assert report[other]["result"] == "migrated" and report[other]["reconciled"] == 1
    assert status(db_path, guarded[0])["attempts"][0]["token"] == paid["token"]
    assert "policy_version" not in status(db_path, guarded[0])["limits"]


def test_migrated_task_keeps_qa_identity_and_still_runs(db_path, guarded):
    v1(db_path, guarded[0], attempts=1)
    settle(db_path, guarded[1], begin(db_path, guarded[0]), success=True)
    with pytest.raises(ValidationError, match="Cumulative"):
        begin(db_path, guarded[0], "capped")
    identity = api.capture_qa_identity(task_id=guarded[0], db_path=db_path)["identity_line"]
    ex.migrate_ledgers(db_path=db_path)
    assert api.capture_qa_identity(task_id=guarded[0], db_path=db_path)["identity_line"] == identity
    begin(db_path, guarded[0], "resumed")  # v1 cap no longer blocks local work


def test_task_already_past_ceiling_reports_it_after_migration(db_path, guarded):
    v1(db_path, guarded[0], attempts=60)
    for i in range(51):
        settle(db_path, guarded[1], begin(db_path, guarded[0], label=str(i)), text=f"e{i}")
    report = ex.migrate_ledgers(db_path=db_path, task_id=guarded[0])
    assert report["tasks"][0]["resulting_state"] == "ceiling_reached"
    assert status(db_path, guarded[0])["state"] == "ceiling_reached"


def test_cli_budget_migrate_and_reopen_commands(cli, db_path, guarded):
    reg = cli(["execution", "register", str(guarded[0]), "--timeout", "30"])
    assert reg.exit_code == 0, reg.output
    assert json.loads(reg.output)["policy_version"] == 2
    shown = cli(["execution", "budget", "show"])
    assert shown.exit_code == 0 and json.loads(shown.output)["calls"] == 0
    refused = cli(["execution", "budget", "set", "--calls", "1", "--usd", "1"])
    assert refused.exit_code != 0
    ok = cli(["execution", "budget", "set", "--calls", "5", "--usd", "2", "--authority", "Pablo: ok"])
    assert ok.exit_code == 0, ok.output
    dry = cli(["execution", "migrate", "--dry-run"])
    assert dry.exit_code == 0 and json.loads(dry.output)["tasks"][0]["result"] == "already_v2"
    reopened = cli(["execution", "reopen", str(guarded[0]), "--decision", "Pablo: go"])
    assert reopened.exit_code == 0, reopened.output


# --- T10: approval-surface fitness ---------------------------------------------------

OWNER_INPUT_MARKERS = (
    "owner authority",
    "new owner decision",
    "Cumulative task execution limit",
    "more paid calls",
)


def _message_text(node):
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_message_text(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        inner = node.value
        return "DECISION NEEDED: " if getattr(inner, "id", "") == "DECISION" else "{}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _message_text(node.left) + _message_text(node.right)
    if isinstance(node, ast.Name):
        return "DECISION NEEDED: " if node.id == "DECISION" else "{}"
    return "{}"


def owner_input_refusals(source):
    """Every ValidationError whose text asks for owner input -> (text, prefixed)."""
    import ast

    found = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "ValidationError"
            and node.args
        ):
            text = _message_text(node.args[0])
            if any(m in text for m in OWNER_INPUT_MARKERS):
                found.append((text, text.startswith("DECISION NEEDED: ")))
    return found


def test_every_owner_input_refusal_carries_the_decision_marker():
    from pathlib import Path

    refusals = owner_input_refusals(Path(ex.__file__).read_text())
    assert len(refusals) >= 5  # non-vacuous: successor, cumulative, budget x2, reopen
    unmarked = [text for text, prefixed in refusals if not prefixed]
    assert unmarked == []


def test_fitness_check_rejects_an_unmarked_owner_input_refusal():
    bad = 'raise ValidationError("A successor requires a new explicit owner authority")'
    good = 'raise ValidationError(DECISION + "a successor requires a new owner authority")'
    assert owner_input_refusals(bad) == [
        ("A successor requires a new explicit owner authority", False)
    ]
    assert owner_input_refusals(good)[0][1] is True
