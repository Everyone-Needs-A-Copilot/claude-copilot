"""Root/child accounting contracts; all reservations are synthetic local records."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from tc import api
from tc.db.exceptions import ConflictError, ValidationError
from tc.services import execution as ex

REFUSAL = (ConflictError, ValidationError)


def scope(db_path, count=3, ceiling=2, seconds=21600):
    root = db_path.parent.parent
    (root / "code.py").write_text("VALUE = 1\n")
    contract = {"schemaVersion": 2, "criteria": [{"id": "DELIVERY", "expected": "The declared result is delivered."}],
                "sources": ["code.py"]}
    def task(name, parent=None):
        return api.create_task(title=name, parent=parent,
                               metadata={"requiresQa": True, "acceptanceContract": contract},
                               db_path=db_path)["id"]
    parent = task("Root execution authority")
    ex.register_limits(task_id=parent, ceiling_attempts=ceiling, ceiling_seconds=seconds, timeout_seconds=30, db_path=db_path)
    children = [task(f"Child shard {i}", parent) for i in range(count)]
    for child in children:
        ex.register_limits(task_id=child, ceiling_attempts=20, timeout_seconds=30, db_path=db_path)
        ex.bind_scope(root_task_id=parent, task_id=child, criterion_map={"DELIVERY": "DELIVERY"}, db_path=db_path)
    return root, parent, children


def begin(db, task, calls=0):
    return ex.begin_attempt(task_id=task, criterion="DELIVERY", label="bounded shard",
                            reserve_calls=calls, reserve_usd=0, db_path=db)


def settle(db, root, attempt, calls=0):
    path = root / f"result-{attempt['token']}.txt"
    path.write_text("actual synthetic observation\n")
    return ex.settle_attempt(token=attempt["token"], succeeded=True, calls=calls,
                             cost_usd=0, artifact=path, db_path=db)


def test_sibling_attempts_run_concurrently_without_multiplying_root_ceiling(db_path):
    root, parent, children = scope(db_path)
    first, second = begin(db_path, children[0]), begin(db_path, children[1])
    with pytest.raises(REFUSAL):
        begin(db_path, children[2])
    settle(db_path, root, first)
    settle(db_path, root, second)
    with pytest.raises(REFUSAL):
        begin(db_path, children[2])
    assert ex.execution_status(task_id=parent, db_path=db_path)["usage"]["attempts"] == 2


def test_concurrent_last_root_permit_is_reserved_atomically(db_path):
    root, parent, children = scope(db_path, count=3, ceiling=1)
    def attempt(task):
        try:
            return begin(db_path, task)
        except REFUSAL:
            return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(attempt, children))
    assert sum(x is not None for x in results) == 1
    assert ex.execution_status(task_id=parent, db_path=db_path)["usage"]["attempts"] == 1


def test_shared_paid_budget_is_charged_once_not_per_ancestry_level(db_path):
    root, parent, children = scope(db_path, ceiling=5)
    ex.set_budget(calls=2, cost_usd=0, authority=["Synthetic fixture allowance; no actual provider calls"], db_path=db_path)
    a, b = begin(db_path, children[0], calls=1), begin(db_path, children[1], calls=1)
    assert ex.budget_status(db_path=db_path)["used_calls"] == 2
    with pytest.raises(REFUSAL):
        begin(db_path, children[2], calls=1)
    settle(db_path, root, a, calls=1)
    settle(db_path, root, b, calls=1)
    assert ex.budget_status(db_path=db_path)["used_calls"] == 2
    assert ex.execution_status(task_id=parent, db_path=db_path)["usage"]["attempts"] == 2


def test_scope_retry_is_idempotent_and_reparenting_or_cycles_refuse(db_path):
    root, parent, children = scope(db_path, ceiling=3)
    ex.bind_scope(root_task_id=parent, task_id=children[0], criterion_map={"DELIVERY": "DELIVERY"}, db_path=db_path)
    with pytest.raises(REFUSAL):
        ex.bind_scope(root_task_id=children[0], task_id=parent, criterion_map={"DELIVERY": "DELIVERY"}, db_path=db_path)
    with pytest.raises(REFUSAL):
        ex.bind_scope(root_task_id=children[1], task_id=children[0], criterion_map={"DELIVERY": "DELIVERY"}, db_path=db_path)
    a = begin(db_path, children[0])
    settle(db_path, root, a)
    assert ex.execution_status(task_id=parent, db_path=db_path)["usage"]["attempts"] == 1


def test_unknown_criterion_mapping_and_unregistered_policy_refuse(db_path):
    root, parent, children = scope(db_path, count=1)
    fresh = api.create_task(title="No policy yet", db_path=db_path)["id"]
    with pytest.raises(REFUSAL):
        ex.bind_scope(root_task_id=parent, task_id=fresh, criterion_map={"DELIVERY": "DELIVERY"}, db_path=db_path)
    with pytest.raises(REFUSAL):
        ex.bind_scope(root_task_id=parent, task_id=children[0], criterion_map={"UNKNOWN": "DELIVERY"}, db_path=db_path)


def test_one_child_cannot_start_two_unsettled_attempts(db_path):
    root, parent, children = scope(db_path, ceiling=5)
    begin(db_path, children[0])
    with pytest.raises(REFUSAL):
        begin(db_path, children[0])
    assert ex.execution_status(task_id=parent, db_path=db_path)["usage"]["attempts"] == 1


def test_root_runtime_ceiling_counts_sibling_durations_once(db_path, monkeypatch):
    root, parent, children = scope(db_path, ceiling=10, seconds=10)
    # A fresh fixture isolates timing from prior settled/real project attempts.
    clock = [ex.time.time()]
    monkeypatch.setattr(ex.time, "time", lambda: clock[0])
    first = begin(db_path, children[0])
    clock[0] += 6
    settle(db_path, root, first)
    second = begin(db_path, children[1])
    clock[0] += 6
    settle(db_path, root, second)
    state = ex.execution_status(task_id=parent, db_path=db_path)
    assert state["usage"]["attempts"] == 2
    # The public cumulative scope report is separate from elapsed wall time.
    usage = ex.scope_usage(task_id=parent, db_path=db_path)
    assert usage["progress"]["runtime_seconds"] == pytest.approx(12)
    with pytest.raises(REFUSAL):
        begin(db_path, children[2])
