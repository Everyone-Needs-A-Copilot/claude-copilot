"""tc.services.tasks.update_task's QA completion gate, end to end.

New file. Recovers the four cases from the unreviewed
`archive/enforcement-20260907` overlay's `tools/tc/tests/test_qa_completion.py`
(git blob 65cfd2f53f809eda7ec4d2a7e752cb70bf272ed2, tree c6600ea...) as a
starting point -- see wp-a-evidence.md section 3.3/5.2 -- adapted to the v1
evidence packet (adding IDENTITY/BASELINE/etc., since the archived PASS
string was pre-v1/legacy-shaped and would now be rejected for a
not-yet-completed task by the legacy policy in `tc.services.qa`; see
test_qa_legacy_migration.py for that policy's own coverage). Extended with
new cases for defects 5 (multi-work-product criterion sets) and 7 (shared
transaction under `tc.api.transaction`).
"""

from __future__ import annotations

import pytest

from tc import api
from .qa_fixtures import bind_packet
from tc.db.exceptions import ValidationError
from tc.services.qa import check_task_qa

PASS = (
    "CRITERION: guarded behavior holds\n"
    "EXPECTED: completion is blocked without evidence\n"
    "OBSERVED: completion was blocked as expected\n"
    "IDENTITY: fixture rev=abc1234, clean\n"
    "BASELINE: unavailable, fresh fixture database\n"
    'ARTIFACT: test-run|pytest tests/test_x.py exit=0 "1 passed"\n'
    "UNTESTED: none\n"
    "VERDICT: APPROVED\n"
)


def test_completion_requires_current_task_bound_evidence(db_path):
    task = api.create_task(title="Guarded", metadata={"requiresQa": True}, db_path=db_path)
    other = api.create_task(title="Other", db_path=db_path)
    api.store_wp(task_id=other["id"], type_="test", title="Other QA", content=bind_packet(other, db_path, PASS), db_path=db_path)

    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(
            task_id=task["id"], status="completed", metadata={"qaStatus": "approved"}, db_path=db_path
        )
    assert api.get_task(task_id=task["id"], db_path=db_path)["status"] == "pending"

    api.store_wp(task_id=task["id"], type_="test", title="QA", content=bind_packet(task, db_path, PASS), db_path=db_path)
    assert check_task_qa(task_id=task["id"], db_path=db_path)["approved"]
    assert api.update_task(task_id=task["id"], status="completed", db_path=db_path)["status"] == "completed"


@pytest.mark.parametrize(
    "new_type,content",
    [("test", "VERDICT: REJECTED"), ("code", "Changed implementation, no new evidence stored")],
)
def test_later_rejection_or_implementation_invalidates_qa(db_path, new_type, content):
    task = api.create_task(title="Guarded", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="Old QA", content=bind_packet(task, db_path, PASS), db_path=db_path)
    api.store_wp(task_id=task["id"], type_=new_type, title="New evidence", content=content, db_path=db_path)

    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=task["id"], status="completed", db_path=db_path)
    assert not check_task_qa(task_id=task["id"], db_path=db_path)["approved"]


def test_metadata_downgrade_cannot_bypass_completion_check(db_path):
    task = api.create_task(title="Guarded", metadata={"requiresQa": True}, db_path=db_path)
    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(
            task_id=task["id"], status="completed", metadata={"requiresQa": False}, db_path=db_path
        )
    assert api.get_task(task_id=task["id"], db_path=db_path)["status"] == "pending"


def test_ordinary_task_remains_completable(db_path):
    task = api.create_task(title="Ordinary", db_path=db_path)
    assert api.update_task(task_id=task["id"], status="completed", db_path=db_path)["status"] == "completed"


def test_check_qa_command_reports_not_found_task(db_path):
    with pytest.raises(Exception):
        check_task_qa(task_id=999999, db_path=db_path)


# ---------------------------------------------------------------------------
# Defect 5: a criterion set spread across several work products.
# ---------------------------------------------------------------------------


def test_criterion_set_spread_across_multiple_work_products_passes(db_path):
    task = api.create_task(title="Multi-WP QA", metadata={"requiresQa": True}, db_path=db_path)
    combined = bind_packet(task, db_path,
        "CRITERION: area one\nEXPECTED: e1\nOBSERVED: o1\nARTIFACT: test-run|pytest a1 exit=0\n"
        "CRITERION: area two\nEXPECTED: e2\nOBSERVED: o2\n"
        "IDENTITY: fixture\nBASELINE: unavailable, fresh fixture\n"
        "ARTIFACT: test-run|pytest a2 exit=0\nUNTESTED: none\nVERDICT: APPROVED\n")
    first, second = combined.split("CRITERION: area_two", 1)
    api.store_wp(task_id=task["id"], type_="test", title="Area 1", content=first, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="Area 2 + verdict", content="CRITERION: area_two" + second, db_path=db_path)
    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"], result["reason"]
    assert api.update_task(task_id=task["id"], status="completed", db_path=db_path)["status"] == "completed"


def test_prior_rejected_round_does_not_bleed_into_new_approved_round(db_path):
    """A resolved earlier failure must not resurface as a "conflicting
    verdict" once a later, self-contained round passes."""
    task = api.create_task(title="Retried QA", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(
        task_id=task["id"], type_="test", title="Round 1 (failed)",
        content="CRITERION: c\nEXPECTED: e\nOBSERVED: wrong\nVERDICT: REJECTED\n",
        db_path=db_path,
    )
    api.store_wp(task_id=task["id"], type_="test", title="Round 2 (passed)", content=bind_packet(task, db_path, PASS), db_path=db_path)
    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"], result["reason"]


# ---------------------------------------------------------------------------
# Defect 7: the check and the write share one immediate transaction
# regardless of connection ownership.
# ---------------------------------------------------------------------------


def test_gate_enforced_when_caller_supplies_its_own_connection(db_path):
    """A caller batching through `tc.api.transaction` must get the same
    completion gate a standalone call gets -- not just an unenforced
    write."""
    from tc.db.connection import get_db

    conn = get_db(db_path)
    try:
        with api.transaction(conn):
            task = api.create_task(title="Batched", metadata={"requiresQa": True}, conn=conn)
        with pytest.raises(ValidationError, match="QA gate"):
            with api.transaction(conn):
                api.update_task(task_id=task["id"], status="completed", conn=conn)
    finally:
        conn.close()

    assert api.get_task(task_id=task["id"], db_path=db_path)["status"] == "pending"


# ---------------------------------------------------------------------------
# QA-authored additions (task 27/B5): handoff acceptance cases not yet
# exercised above -- wrong/missing task ID, metadata-only approval, one
# task's pass leaving another pending, concurrent updates, and the CLI
# entry point (not just tc.api). "Never trust the implementer's own tests
# as sufficient" -- these are independent, adversarial cases against the
# same predicate.
# ---------------------------------------------------------------------------


def test_missing_task_id_raises_not_found_not_a_silent_pass(db_path):
    """A wrong/missing task ID must surface as an error, never as
    `approved=True` by falling through some default."""
    from tc.db.exceptions import TaskNotFound

    with pytest.raises(TaskNotFound):
        check_task_qa(task_id=987654, db_path=db_path)


def test_metadata_only_approval_without_any_work_product_fails(db_path):
    """Setting qaStatus/verdict-shaped metadata directly, with NO test work
    product stored at all, must never satisfy the gate. The predicate reads
    work products, never task metadata, for evidence."""
    task = api.create_task(
        title="Metadata-only claim",
        metadata={
            "requiresQa": True,
            "qaStatus": "approved",
            "verdict": "APPROVED",
            "artifact": "test-run|pytest exit=0",
        },
        db_path=db_path,
    )
    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"] is False
    assert result["reason"] == "No task-bound evidence"

    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=task["id"], status="completed", db_path=db_path)
    assert api.get_task(task_id=task["id"], db_path=db_path)["status"] == "pending"


def test_one_tasks_pass_leaves_a_second_qa_required_task_pending(db_path):
    """Two independent QA-required tasks in the same database: approving
    one via a real evidence packet must never affect the other's gate."""
    task_a = api.create_task(title="A", metadata={"requiresQa": True}, db_path=db_path)
    task_b = api.create_task(title="B", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task_a["id"], type_="test", title="QA for A", content=bind_packet(task_a, db_path, PASS), db_path=db_path)

    assert check_task_qa(task_id=task_a["id"], db_path=db_path)["approved"] is True
    assert check_task_qa(task_id=task_b["id"], db_path=db_path)["approved"] is False

    assert api.update_task(task_id=task_a["id"], status="completed", db_path=db_path)["status"] == "completed"
    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=task_b["id"], status="completed", db_path=db_path)
    assert api.get_task(task_id=task_b["id"], db_path=db_path)["status"] == "pending"


def test_concurrent_work_product_writes_for_two_tasks_preserve_both_records(db_path):
    """Two threads writing evidence for two DIFFERENT tasks against the
    same database file concurrently must not lose either write (TOCTOU /
    defect 7 territory extended to the WP-store path, not just the
    completion write)."""
    import threading

    task_a = api.create_task(title="Concurrent A", metadata={"requiresQa": True}, db_path=db_path)
    task_b = api.create_task(title="Concurrent B", metadata={"requiresQa": True}, db_path=db_path)
    errors: list[Exception] = []
    packets = {t["id"]: bind_packet(t, db_path, PASS) for t in (task_a, task_b)}

    def _store(task_id: int, label: str) -> None:
        try:
            api.store_wp(task_id=task_id, type_="test", title=label, content=packets[task_id], db_path=db_path)
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [
        threading.Thread(target=_store, args=(task_a["id"], "A evidence")),
        threading.Thread(target=_store, args=(task_b["id"], "B evidence")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert check_task_qa(task_id=task_a["id"], db_path=db_path)["approved"] is True
    assert check_task_qa(task_id=task_b["id"], db_path=db_path)["approved"] is True
    assert api.update_task(task_id=task_a["id"], status="completed", db_path=db_path)["status"] == "completed"
    assert api.update_task(task_id=task_b["id"], status="completed", db_path=db_path)["status"] == "completed"


def test_cli_check_qa_and_api_check_qa_agree_on_the_same_task(db_path, cli):
    """The CLI entry point (`tc task check-qa --json`), not just
    `tc.api.check_task_qa`, must reach the identical predicate and result
    for the same task/database -- the handoff's explicit "verify both
    CLI/API completion and the native hook adapter, not just a parser
    helper" requirement. Uses the `cli` fixture (chdir'd to this test's own
    database directory, per conftest.py) so `require_db()`'s directory walk
    resolves to the same disposable database `tc.api` was given directly --
    never the project database."""
    import json as _json

    import tc.services.qa as qa_module

    task = api.create_task(title="CLI parity", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="QA", content=bind_packet(task, db_path, PASS), db_path=db_path)

    api_result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert qa_module.__name__ == "tc.services.qa"  # module path this side exercised

    cli_result = cli(["task", "check-qa", str(task["id"]), "--json"])
    assert cli_result.exit_code == 0, cli_result.output
    cli_payload = _json.loads(cli_result.output)

    assert cli_payload["task_id"] == api_result["task_id"]
    assert cli_payload["approved"] == api_result["approved"] is True
    assert cli_payload["work_product_id"] == api_result["work_product_id"]
    assert cli_payload["reason"] == api_result["reason"]

    # Same parity check on the FAILING side, so agreement is not an
    # artifact of the happy path only.
    other = api.create_task(title="CLI parity (unapproved)", metadata={"requiresQa": True}, db_path=db_path)
    api_fail = check_task_qa(task_id=other["id"], db_path=db_path)
    cli_fail = cli(["task", "check-qa", str(other["id"]), "--json"])
    assert cli_fail.exit_code == 1
    cli_fail_payload = _json.loads(cli_fail.output)
    assert cli_fail_payload["approved"] == api_fail["approved"] is False
    assert cli_fail_payload["reason"] == api_fail["reason"]
