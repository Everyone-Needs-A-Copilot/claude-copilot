"""Legacy-evidence migration policy (wp-a-evidence.md section 3.4, migration
requirement): preserve history, never silently upgrade old evidence to
satisfy a contract it predates.

New file -- this policy did not exist before this task; there is nothing to
regress against.
"""

from __future__ import annotations

from tc import api
from tc.services.qa import check_task_qa

LEGACY_PASS = "ARTIFACT: test-run|pytest exit=0\nVERDICT: APPROVED\n"


def test_already_completed_task_with_legacy_evidence_is_not_retroactively_invalidated(db_path):
    """A task completed before EVIDENCE_SCHEMA_VERSION existed keeps its
    verdict -- inspecting it later must never manufacture a rejection."""
    task = api.create_task(title="Historical", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="Old-style QA", content=LEGACY_PASS, db_path=db_path)

    # Directly mark completed (bypassing the gate) to model a task that
    # completed under the PRIOR predicate, before IDENTITY existed at all.
    from tc.db.connection import get_db

    conn = get_db(db_path)
    conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task["id"],))
    conn.commit()
    conn.close()

    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"] is True
    assert result["legacy"] is True
    assert "not retroactively invalidated" in result["reason"]


def test_not_yet_completed_task_cannot_complete_on_legacy_evidence_alone(db_path):
    """Legacy-shaped evidence must never silently satisfy the stronger,
    current contract for a task that has not completed yet."""
    task = api.create_task(title="New work", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="Old-style QA", content=LEGACY_PASS, db_path=db_path)

    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"] is False
    assert result["legacy"] is True
    assert "does not satisfy" in result["reason"]

    from tc.db.exceptions import ValidationError
    import pytest

    with pytest.raises(ValidationError, match="QA gate"):
        api.update_task(task_id=task["id"], status="completed", db_path=db_path)
    assert api.get_task(task_id=task["id"], db_path=db_path)["status"] == "pending"


def test_pre_schema_completed_task_stays_fully_readable_via_api(db_path):
    """A pre-schema-v1 completed task must remain readable through the
    ordinary read paths (`api.get_task`, work product listing), not merely
    return an approved verdict from `check_task_qa` -- 'stays readable and
    valid' means the surrounding data survives untouched, not just that one
    predicate call succeeds."""
    task = api.create_task(title="Historical, fully readable", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="Old-style QA", content=LEGACY_PASS, db_path=db_path)

    from tc.db.connection import get_db

    conn = get_db(db_path)
    conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task["id"],))
    conn.commit()
    conn.close()

    read_back = api.get_task(task_id=task["id"], db_path=db_path)
    assert read_back["status"] == "completed"
    assert read_back["title"] == "Historical, fully readable"

    wps = api.list_wps(task=task["id"], db_path=db_path)
    assert len(wps) == 1
    assert wps[0]["content"] == LEGACY_PASS

    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"] is True
    assert result["legacy"] is True


def test_legacy_task_can_still_be_upgraded_with_new_style_evidence(db_path):
    """A not-yet-completed task with legacy-shaped evidence is blocked (see
    test_not_yet_completed_task_cannot_complete_on_legacy_evidence_alone),
    but the migration path forward must work: adding a current-shaped
    packet lets the SAME task complete normally, without needing to touch
    or discard the old work product."""
    task = api.create_task(title="Upgradeable", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(task_id=task["id"], type_="test", title="Old-style QA", content=LEGACY_PASS, db_path=db_path)
    assert check_task_qa(task_id=task["id"], db_path=db_path)["approved"] is False

    api.store_wp(
        task_id=task["id"],
        type_="test",
        title="Current-style QA",
        content=(
            "CRITERION: c\nEXPECTED: e\nOBSERVED: o\nIDENTITY: rev-xyz, clean\n"
            "BASELINE: unavailable, fresh fixture\nARTIFACT: test-run|pytest exit=0\n"
            "UNTESTED: none\nVERDICT: APPROVED\n"
        ),
        db_path=db_path,
    )
    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"] is True
    assert result["legacy"] is False
    assert api.update_task(task_id=task["id"], status="completed", db_path=db_path)["status"] == "completed"


def test_current_packet_evidence_is_not_flagged_legacy(db_path):
    task = api.create_task(title="Current work", metadata={"requiresQa": True}, db_path=db_path)
    api.store_wp(
        task_id=task["id"],
        type_="test",
        title="Current QA",
        content=(
            "CRITERION: c\nEXPECTED: e\nOBSERVED: o\nIDENTITY: rev-xyz\n"
            "BASELINE: unavailable, fresh fixture\nARTIFACT: test-run|pytest exit=0\n"
            "UNTESTED: none\nVERDICT: APPROVED\n"
        ),
        db_path=db_path,
    )
    result = check_task_qa(task_id=task["id"], db_path=db_path)
    assert result["approved"] is True
    assert result["legacy"] is False
