"""Independent stage/sweep contracts, with real SQLite and Git and no providers."""
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from tc.db.exceptions import ConflictError, ValidationError
from tc.services import cycles, cycle_stages
from tests.cycle_stage_fixtures import make_world, git

REFUSAL = (ConflictError, ValidationError)


def test_inventory_needs_independent_review_before_dispatch(tmp_path):
    w = make_world(tmp_path)
    with pytest.raises(REFUSAL):
        w.start("q1")
    with pytest.raises(REFUSAL):
        w.advance("inventory-frozen", actor="same", reviewer="same")
    assert not w.status()["running"]
    w.freeze()
    assert w.status()["ready"] == ["q1", "q2", "q3"]


def test_five_items_refill_three_slots_without_waiting_for_whole_wave(tmp_path):
    w = make_world(tmp_path)
    w.freeze()
    for stream in ("q1", "q2", "q3"):
        w.start(stream)
    assert set(w.status()["running"]) == {"q1", "q2", "q3"}
    with pytest.raises(REFUSAL):
        w.start("q4")
    w.result("q1", "C1")
    # Result alone cannot free the slot; native shutdown is still unproven.
    with pytest.raises(REFUSAL):
        w.start("q4")
    w.stop("q1")
    assert "q4" in w.status()["ready"]
    w.start("q4")
    assert set(w.status()["running"]) == {"q2", "q3", "q4"}
    w.result("q4", "C4")
    w.stop("q4")
    w.start("q5")
    assert set(w.status()["running"]) == {"q2", "q3", "q5"}
    for i in (2, 3, 5):
        w.result(f"q{i}", f"C{i}")
        w.stop(f"q{i}")
    w.collect()
    w.accept()
    assert cycle_stages.check_cycle(cycle=w.cycle, phase="source-ready", db_path=w.db)["approved"]


def test_concurrent_claims_never_exceed_capacity(tmp_path):
    w = make_world(tmp_path)
    w.freeze()
    def claim(i):
        try:
            return cycles.claim_stream(cycle=w.cycle, stream=f"q{i}", agent=f"a{i}",
                                       cwd=w.root, db_path=w.db)
        except REFUSAL:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(claim, range(1, 6)))
    assert sum(r is not None for r in results) == 3
    assert len(w.status()["running"]) == 3


def test_failure_does_not_cancel_rest_of_partition_or_other_shards(tmp_path):
    def config(plan, root, db):
        additional = copy.deepcopy(plan["checks"][0])
        additional["id"] = "C1-adjacent"
        plan["checks"].append(additional)
    w = make_world(tmp_path, configure=config)
    w.freeze()
    w.start("q1")
    w.result("q1", "C1", "failed", defect="D-shared")
    w.result("q1", "C1-adjacent")
    w.stop("q1")
    with pytest.raises(REFUSAL):
        w.collect()
    for i in (2, 3, 4, 5):
        w.start(f"q{i}")
        if i == 3:
            w.result("q3", "C3", "error", defect="D-runner")
        else:
            w.result(f"q{i}", f"C{i}")
        w.stop(f"q{i}")
    w.collect()
    assert set(w.status()["checkResults"]) == {"C1", "C1-adjacent", "C2", "C3", "C4", "C5"}
    assert not cycle_stages.check_cycle(cycle=w.cycle, phase="source-ready", db_path=w.db)["approved"]
    with pytest.raises(REFUSAL):
        w.accept()


def test_complete_catalogue_required_before_repair_dispatch(tmp_path):
    def config(plan, root, db):
        plan["stages"].append({"id": "fix", "kind": "repair", "owner": "builder",
                               "dependsOn": ["qa"], "phase": "source-ready"})
        plan["streams"][1]["stage"] = "fix"
        plan["streams"][1]["role"] = "me"
        plan["checks"][1]["stage"] = "fix"
    w = make_world(tmp_path, count=2, configure=config)
    w.freeze()
    with pytest.raises(REFUSAL):
        w.start("q2")
    with pytest.raises(REFUSAL):
        w.advance("repair-plan-frozen", stage="fix", defects=[])
    w.start("q1")
    w.result("q1", "C1", "failed", defect="D1")
    w.stop("q1")
    w.collect()
    with pytest.raises(REFUSAL):
        w.advance("repair-plan-frozen", stage="fix", defects=[])
    w.advance("repair-plan-frozen", stage="fix",
              defects=[{"id": "D1", "cases": ["C1"], "owner": "builder"}])
    w.start("q2")


@pytest.mark.parametrize("outcome", ["failed", "error"])
def test_failure_requires_defect_and_cannot_be_relabelled_in_same_generation(tmp_path, outcome):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.start("q1")
    with pytest.raises(REFUSAL):
        w.result("q1", "C1", outcome)
    w.result("q1", "C1", outcome, defect="D1")
    with pytest.raises(REFUSAL):
        w.result("q1", "C1", "passed")


def test_blocked_is_collected_but_never_accepted(tmp_path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.start("q1")
    w.result("q1", "C1", "blocked")
    w.stop("q1")
    w.collect()
    assert not cycle_stages.check_cycle(cycle=w.cycle, phase="source-ready", db_path=w.db)["approved"]


def test_permit_consumption_is_not_evidence_native_started(tmp_path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    c = w.start("q1", native=False)
    with pytest.raises(REFUSAL):
        w.result("q1", "C1")
    w.advance("native-started", stream="q1", leaseToken=c["token"],
              nativeId="synthetic-adapter-observation-not-live-model-proof")
    w.result("q1", "C1")


def test_wrong_stream_and_stale_lease_cannot_report_another_case(tmp_path):
    w = make_world(tmp_path, count=2)
    w.freeze()
    c = w.start("q1")
    with pytest.raises(REFUSAL):
        w.result("q1", "C2")
    with pytest.raises(REFUSAL):
        w.advance("result-recorded", stream="q1", leaseToken="stale-token", check="C1",
                  outcome="passed")
    assert c["token"] != "stale-token"
    assert not w.status()["checkResults"]


def test_event_replay_and_stale_revision_preserve_history(tmp_path):
    w = make_world(tmp_path, count=1)
    receipt = {"operationId": "freeze-once", "generation": 1, "actor": "planner",
               "reviewer": "reviewer", "artifact": w.artifact()}
    first = cycle_stages.advance_cycle(cycle=w.cycle, event="inventory-frozen",
                                      receipt=receipt, db_path=w.db)
    revision = w.status()["revision"]
    cycle_stages.advance_cycle(cycle=w.cycle, event="inventory-frozen", receipt=receipt, db_path=w.db)
    assert w.status()["revision"] == revision
    changed = {**receipt, "reviewer": "other-reviewer"}
    with pytest.raises(REFUSAL):
        cycle_stages.advance_cycle(cycle=w.cycle, event="inventory-frozen", receipt=changed, db_path=w.db)
    with pytest.raises(REFUSAL):
        cycle_stages.advance_cycle(cycle=w.cycle, event="held", db_path=w.db,
                                  expect_revision=revision-1,
                                  receipt={"operationId": "stale", "generation": 1,
                                           "stage": "qa", "reason": "stale client", "artifact": w.artifact()})
    assert w.status()["revision"] == revision
    assert first is not None


def test_crash_after_dispatch_ack_requires_reconciliation_not_new_permit(tmp_path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.start("q1", native=False)
    # New public call reads persisted state, not an in-memory recovery object.
    assert cycles.cycle_status(cycle=w.cycle, db_path=w.db)["running"] == ["q1"]
    with pytest.raises(REFUSAL):
        cycles.verify_dispatch(cycle=w.cycle, stream="q1", role="qa", cwd=w.root, db_path=w.db)
    with pytest.raises(REFUSAL):
        w.advance("resume-reconciled", stage="qa")
    with pytest.raises(REFUSAL):
        w.advance("candidate-integrated")


def test_transitive_changed_and_failed_checks_rerun_but_unrelated_pass_retained(tmp_path):
    def config(plan, root, db):
        plan["checks"][1]["dependsOn"] = ["C1"]
        plan["checks"][2]["dependsOn"] = ["C2"]
    w = make_world(tmp_path, count=4, configure=config)
    w.freeze()
    w.run_all()
    prior = copy.deepcopy(w.status()["checkResults"]["C4"])
    (w.root / "src/item1.py").write_text("VALUE = 99\n")
    assert not cycle_stages.check_cycle(cycle=w.cycle, phase="source-ready", db_path=w.db)["approved"]
    w.advance("candidate-integrated")
    after = w.status()
    assert after["generation"] == 2
    assert set(after["checkResults"]) == {"C4"}
    assert after["checkResults"]["C4"] == prior
    assert not cycle_stages.check_cycle(cycle=w.cycle, phase="source-ready", db_path=w.db)["approved"]


@pytest.mark.parametrize("path", ["src/item1.py", "tests/item1.txt"])
def test_changed_source_or_test_invalidates_result_before_acceptance(tmp_path, path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.start("q1")
    w.result("q1", "C1")
    w.stop("q1")
    w.collect()
    (w.root / path).write_text("changed valid contract input\n")
    with pytest.raises(REFUSAL):
        w.accept()


def test_missing_required_coverage_cannot_be_hidden_by_exclusion(tmp_path):
    def invalid(plan, root, db):
        plan["checks"][0]["required"] = False
    with pytest.raises(REFUSAL):
        make_world(tmp_path, count=1, configure=invalid)


def test_capacity_claim_cannot_exceed_observed_runtime(tmp_path):
    def invalid(plan, root, db):
        plan["capacity"] = 4
    with pytest.raises(REFUSAL):
        make_world(tmp_path, count=1, configure=invalid)


def test_ordered_stages_can_reuse_path_but_unordered_writers_refuse(tmp_path):
    def configure(plan, root, db):
        plan["stages"].append({"id": "fix", "kind": "repair", "owner": "builder",
                               "dependsOn": ["qa"], "phase": "source-ready"})
        plan["streams"][1]["stage"] = "fix"
        plan["checks"][1]["stage"] = "fix"
        for i, spec in enumerate(plan["streams"], 1):
            wt = root.parent / f"writer{i}"
            git(root, "worktree", "add", "-b", f"writer{i}", str(wt))
            spec.update(kind="code", role="me", readOnly=False, paths=["src/shared.py"],
                        worktree=str(wt), branch=f"writer{i}")
    w = make_world(tmp_path, count=2, configure=configure)
    assert len(w.plan["streams"]) == 2
    unordered = copy.deepcopy(w.plan)
    unordered["stages"][1]["dependsOn"] = []
    with pytest.raises(REFUSAL):
        cycles.validate_plan(unordered)
    w.freeze()
    w.start("q1")
    with pytest.raises(REFUSAL):
        w.start("q2")


def test_cross_cycle_writers_cannot_evade_ownership_with_different_worktree_cwd(tmp_path):
    from tc import api
    from tests.cycle_stage_fixtures import StageWorld
    def writer(plan, root, db):
        wt = root.parent / "first-writer"
        git(root, "worktree", "add", "-b", "first-writer", str(wt))
        plan["streams"][0].update(kind="code", role="me", readOnly=False,
                                  paths=["src/shared.py"], worktree=str(wt), branch="first-writer")
    first = make_world(tmp_path, count=1, configure=writer)
    first.freeze()
    first.start("q1")
    second_plan = copy.deepcopy(first.plan)
    second_plan["id"] = "another-cycle"
    second_plan["task"] = api.create_task(title="Second independent root", db_path=first.db)["id"]
    second_plan["streams"][0]["task"] = api.create_task(title="Second writer", db_path=first.db)["id"]
    wt = first.root.parent / "second-writer"
    git(first.root, "worktree", "add", "-b", "second-writer", str(wt))
    second_plan["streams"][0].update(worktree=str(wt), branch="second-writer")
    cycles.create_cycle(plan=second_plan, db_path=first.db)
    second = StageWorld(first.root, first.db, second_plan)
    # Give each evidence writer a distinct sequence namespace.
    second.sequence = 1000
    second.freeze()
    with pytest.raises(REFUSAL):
        second.start("q1")
    assert not second.status()["running"]


def test_same_native_agent_can_take_new_scope_only_after_observed_stop(tmp_path):
    w = make_world(tmp_path, count=2)
    w.freeze()
    first = w.start("q1", native=False)
    w.advance("native-started", stream="q1", leaseToken=first["token"], nativeId="fixture-agent-reused")
    second = w.start("q2", native=False)
    with pytest.raises(REFUSAL):
        w.advance("native-started", stream="q2", leaseToken=second["token"], nativeId="fixture-agent-reused")
    w.result("q1", "C1")
    w.stop("q1")
    w.advance("native-started", stream="q2", leaseToken=second["token"], nativeId="fixture-agent-reused")
    w.result("q2", "C2")
    w.stop("q2")
    audit = cycle_stages.audit_cycle(cycle=w.cycle, db_path=w.db)
    assert audit["assurance"] == "coordinator-observed; not provider-attested"
    intervals = audit["nativeIntervals"]
    assert len(intervals) == 2
    assert {row["nativeId"] for row in intervals} == {"fixture-agent-reused"}
    assert all(row["seconds"] >= 0 and row["stopped"] >= row["started"] for row in intervals)
    assert not audit["unresolvedNative"]
    assert audit["elapsedSeconds"] >= max(row["seconds"] for row in intervals)


def test_missing_native_observation_remains_unknown_in_audit(tmp_path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.start("q1", native=False)
    audit = cycle_stages.audit_cycle(cycle=w.cycle, db_path=w.db)
    assert not audit["nativeIntervals"]
    assert audit["unresolvedNative"]


def test_source_changed_during_check_cannot_be_blessed_by_fresh_result_hash(tmp_path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.start("q1")
    (w.root / "src/item1.py").write_text("VALUE = 2  # changed during the check\n")
    with pytest.raises(REFUSAL):
        w.result("q1", "C1")
    assert not w.status()["checkResults"]


def test_prior_generation_receipt_is_not_accepted_after_candidate_integration(tmp_path):
    w = make_world(tmp_path, count=1)
    w.freeze()
    w.run_all()
    (w.root / "src/item1.py").write_text("VALUE = 2\n")
    w.advance("candidate-integrated")
    assert w.status()["inventoryFrozen"]
    with pytest.raises(REFUSAL):
        w.advance("held", generation=1, stage="qa", reason="stale generation")


def test_source_and_packaged_stages_cannot_share_one_source_only_approval(tmp_path):
    def config(plan, root, db):
        plan["stages"].append({"id": "packaged", "kind": "package", "owner": "packager",
                               "dependsOn": ["qa"], "phase": "package-ready"})
        plan["streams"][1]["stage"] = "packaged"
        plan["checks"][1]["stage"] = "packaged"
    w = make_world(tmp_path, count=2, configure=config)
    w.freeze()
    w.start("q1")
    w.result("q1", "C1")
    w.stop("q1")
    w.collect()
    w.accept()
    assert cycle_stages.check_cycle(cycle=w.cycle, phase="source-ready", db_path=w.db)["approved"]
    assert not cycle_stages.check_cycle(cycle=w.cycle, phase="package-ready", db_path=w.db)["approved"]
    w.start("q2")
    w.result("q2", "C2")
    w.stop("q2")
    w.collect("packaged")
    w.accept("packaged")
    assert cycle_stages.check_cycle(cycle=w.cycle, phase="package-ready", db_path=w.db)["approved"]


def test_audit_distinguishes_ready_idle_from_capacity_wait(tmp_path):
    w = make_world(tmp_path)
    w.freeze()
    for sid in ("q1", "q2", "q3"):
        w.start(sid)
    w.result("q1", "C1")
    w.stop("q1")
    w.start("q4")
    audit = cycle_stages.audit_cycle(cycle=w.cycle, db_path=w.db)
    intervals = audit["queueIntervals"]
    assert any(x["state"] == "ready" for x in intervals)
    assert any(x["reason"] == "worker-capacity" for x in intervals)
    assert all(x["seconds"] >= 0 for x in intervals)
    event_ids = [x["id"] for x in audit["events"]]
    assert event_ids == sorted(set(event_ids))
    again = cycle_stages.audit_cycle(cycle=w.cycle, db_path=w.db)
    assert again == audit  # Re-reading evidence must not invent a new scheduling event.


def test_clock_regression_is_disclosed_not_negative_or_fabricated_elapsed(tmp_path, monkeypatch):
    import time
    now = [time.time()]
    monkeypatch.setattr(time, "time", lambda: now[0])
    w = make_world(tmp_path, count=1)
    now[0] -= 60
    w.freeze()
    audit = cycle_stages.audit_cycle(cycle=w.cycle, db_path=w.db)
    assert audit["elapsedSeconds"] is None or audit["elapsedSeconds"] >= 0
    assert any("clock" in item.lower() for item in audit["unknown"])
