"""Tests for Increment C service extractions and tc.api fitness checks.

Covers:
- tc.services.tasks: get_task, list_tasks, update_task, claim_task, next_task,
  remove_dependency
- tc.services.prds: get_prd, list_prds, update_prd
- tc.services.wp: get_wp, list_wps, search_wps
- tc.services.handoff: handoff_task
- tc.services.log: list_log
- tc.services.progress: get_progress
- tc.services.streams: create_stream, get_stream, list_streams
- tc.api: full __all__ surface importable, services compose under transaction()
- Fitness check: CLI handlers are thin wrappers (no SQL in command bodies)
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    from tc.db.connection import init_db
    path = tmp_path / ".copilot" / "tasks.db"
    init_db(path)
    return path


@pytest.fixture
def conn(db_path):
    from tc.db.connection import get_db
    c = get_db(db_path)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# tc.services.tasks — get_task
# ---------------------------------------------------------------------------

def test_get_task_returns_dict_with_dependencies(db_path):
    from tc.services.tasks import create_task, add_dependency, get_task
    t1 = create_task(title="Dep", db_path=db_path)
    t2 = create_task(title="Main", db_path=db_path)
    add_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)
    result = get_task(task_id=t2["id"], db_path=db_path)
    assert isinstance(result, dict)
    assert result["title"] == "Main"
    assert t1["id"] in result["dependencies"]


def test_get_task_raises_not_found(db_path):
    from tc.services.tasks import get_task
    from tc.db.exceptions import TaskNotFound
    with pytest.raises(TaskNotFound):
        get_task(task_id=99999, db_path=db_path)


# ---------------------------------------------------------------------------
# tc.services.tasks — list_tasks
# ---------------------------------------------------------------------------

def test_list_tasks_empty(db_path):
    from tc.services.tasks import list_tasks
    result = list_tasks(db_path=db_path)
    assert result == []


def test_list_tasks_filter_by_status(db_path):
    from tc.services.tasks import create_task, list_tasks
    create_task(title="Pending 1", db_path=db_path)
    create_task(title="Pending 2", db_path=db_path)
    result = list_tasks(status="pending", db_path=db_path)
    assert len(result) == 2
    assert all(r["status"] == "pending" for r in result)


def test_list_tasks_filter_by_agent(db_path):
    from tc.services.tasks import create_task, list_tasks
    create_task(title="Me task", agent="me", db_path=db_path)
    create_task(title="Other task", agent="qa", db_path=db_path)
    result = list_tasks(agent="me", db_path=db_path)
    assert len(result) == 1
    assert result[0]["agent"] == "me"


def test_list_tasks_invalid_status_raises(db_path):
    from tc.services.tasks import list_tasks
    from tc.db.exceptions import ValidationError
    with pytest.raises(ValidationError, match="invalid status"):
        list_tasks(status="not_a_real_status", db_path=db_path)


def test_list_tasks_ordered_by_priority_then_id(db_path):
    from tc.services.tasks import create_task, list_tasks
    create_task(title="Low prio", priority=3, db_path=db_path)
    create_task(title="High prio", priority=0, db_path=db_path)
    result = list_tasks(db_path=db_path)
    assert result[0]["priority"] <= result[1]["priority"]


# ---------------------------------------------------------------------------
# tc.services.tasks — update_task
# ---------------------------------------------------------------------------

def test_update_task_status(db_path):
    from tc.services.tasks import create_task, update_task
    task = create_task(title="Update me", db_path=db_path)
    updated = update_task(task_id=task["id"], status="in_progress", db_path=db_path)
    assert updated["status"] == "in_progress"


def test_update_task_metadata_merges(db_path):
    from tc.services.tasks import create_task, update_task
    task = create_task(title="Meta task", metadata={"a": 1}, db_path=db_path)
    updated = update_task(task_id=task["id"], metadata={"b": 2}, db_path=db_path)
    import json
    meta = json.loads(updated["metadata"])
    assert meta == {"a": 1, "b": 2}


def test_update_task_invalid_status_raises(db_path):
    from tc.services.tasks import create_task, update_task
    from tc.db.exceptions import ValidationError
    task = create_task(title="Bad status", db_path=db_path)
    with pytest.raises(ValidationError, match="invalid status"):
        update_task(task_id=task["id"], status="flying", db_path=db_path)


def test_update_task_invalid_priority_raises(db_path):
    from tc.services.tasks import create_task, update_task
    from tc.db.exceptions import ValidationError
    task = create_task(title="Bad prio", db_path=db_path)
    with pytest.raises(ValidationError, match="priority"):
        update_task(task_id=task["id"], priority=9, db_path=db_path)


def test_update_task_empty_title_raises(db_path):
    from tc.services.tasks import create_task, update_task
    from tc.db.exceptions import ValidationError
    task = create_task(title="Valid", db_path=db_path)
    with pytest.raises(ValidationError, match="empty"):
        update_task(task_id=task["id"], title="", db_path=db_path)


def test_update_task_not_found_raises(db_path):
    from tc.services.tasks import update_task
    from tc.db.exceptions import TaskNotFound
    with pytest.raises(TaskNotFound):
        update_task(task_id=99999, status="completed", db_path=db_path)


def test_update_task_no_fields_returns_unchanged(db_path):
    from tc.services.tasks import create_task, update_task
    task = create_task(title="No-op", db_path=db_path)
    result = update_task(task_id=task["id"], db_path=db_path)
    assert result["id"] == task["id"]
    assert result["title"] == "No-op"


def test_update_task_completion_logs_action(db_path):
    from tc.services.tasks import create_task, update_task
    from tc.db.connection import get_db
    task = create_task(title="Log test", agent="me", db_path=db_path)
    update_task(task_id=task["id"], status="completed", db_path=db_path)
    conn = get_db(db_path)
    log = conn.execute(
        "SELECT * FROM agent_log WHERE task_id = ? AND action = 'completed'", (task["id"],)
    ).fetchone()
    conn.close()
    assert log is not None


# ---------------------------------------------------------------------------
# tc.services.tasks — claim_task
# ---------------------------------------------------------------------------

def test_claim_task_success(db_path):
    from tc.services.tasks import create_task, claim_task
    task = create_task(title="Claimable", db_path=db_path)
    result = claim_task(task_id=task["id"], agent="me", db_path=db_path)
    assert result["status"] == "in_progress"
    assert result["claimed_by"] == "me"


def test_claim_task_already_claimed_raises(db_path):
    from tc.services.tasks import create_task, claim_task
    from tc.db.exceptions import ConflictError
    task = create_task(title="Race task", db_path=db_path)
    claim_task(task_id=task["id"], agent="me", db_path=db_path)
    with pytest.raises(ConflictError):
        claim_task(task_id=task["id"], agent="qa", db_path=db_path)


def test_claim_task_not_found_raises(db_path):
    from tc.services.tasks import claim_task
    from tc.db.exceptions import ConflictError
    with pytest.raises(ConflictError):
        claim_task(task_id=99999, agent="me", db_path=db_path)


# ---------------------------------------------------------------------------
# tc.services.tasks — next_task
# ---------------------------------------------------------------------------

def test_next_task_returns_none_when_empty(db_path):
    from tc.services.tasks import next_task
    result = next_task(db_path=db_path)
    assert result is None


def test_next_task_returns_highest_priority(db_path):
    from tc.services.tasks import create_task, next_task
    create_task(title="Low", priority=3, db_path=db_path)
    create_task(title="High", priority=0, db_path=db_path)
    result = next_task(db_path=db_path)
    assert result is not None
    assert result["title"] == "High"


def test_next_task_respects_deps(db_path):
    from tc.services.tasks import create_task, add_dependency, next_task, update_task
    t1 = create_task(title="Blocker", priority=0, db_path=db_path)
    t2 = create_task(title="Blocked", priority=1, db_path=db_path)
    add_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)
    # Only t1 should be returned (t2 has unresolved deps)
    result = next_task(db_path=db_path)
    assert result is not None
    assert result["id"] == t1["id"]
    # Complete t1 → t2 becomes available
    update_task(task_id=t1["id"], status="completed", db_path=db_path)
    result2 = next_task(db_path=db_path)
    assert result2 is not None
    assert result2["id"] == t2["id"]


# ---------------------------------------------------------------------------
# tc.services.tasks — remove_dependency
# ---------------------------------------------------------------------------

def test_remove_dependency_success(db_path):
    from tc.services.tasks import create_task, add_dependency, remove_dependency
    t1 = create_task(title="A", db_path=db_path)
    t2 = create_task(title="B", db_path=db_path)
    add_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)
    result = remove_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)
    assert result["status"] == "removed"


def test_remove_dependency_not_found_raises(db_path):
    from tc.services.tasks import create_task, remove_dependency
    from tc.db.exceptions import TaskNotFound
    t1 = create_task(title="X", db_path=db_path)
    t2 = create_task(title="Y", db_path=db_path)
    with pytest.raises(TaskNotFound, match="no dependency found"):
        remove_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)


# ---------------------------------------------------------------------------
# tc.services.prds — get_prd, list_prds, update_prd
# ---------------------------------------------------------------------------

def test_get_prd_success(db_path):
    from tc.services.prds import create_prd, get_prd
    prd = create_prd(title="My PRD", db_path=db_path)
    result = get_prd(prd_id=prd["id"], db_path=db_path)
    assert result["title"] == "My PRD"


def test_get_prd_not_found_raises(db_path):
    from tc.services.prds import get_prd
    from tc.db.exceptions import PrdNotFound
    with pytest.raises(PrdNotFound):
        get_prd(prd_id=99999, db_path=db_path)


def test_list_prds_empty(db_path):
    from tc.services.prds import list_prds
    result = list_prds(db_path=db_path)
    assert result == []


def test_list_prds_with_status_filter(db_path):
    from tc.services.prds import create_prd, list_prds, update_prd
    p1 = create_prd(title="Active PRD", db_path=db_path)
    p2 = create_prd(title="Archived PRD", db_path=db_path)
    update_prd(prd_id=p2["id"], status="archived", db_path=db_path)
    result = list_prds(status="active", db_path=db_path)
    assert len(result) == 1
    assert result[0]["id"] == p1["id"]


def test_list_prds_invalid_status_raises(db_path):
    from tc.services.prds import list_prds
    from tc.db.exceptions import ValidationError
    with pytest.raises(ValidationError, match="invalid status"):
        list_prds(status="broken", db_path=db_path)


def test_update_prd_success(db_path):
    from tc.services.prds import create_prd, update_prd
    prd = create_prd(title="Old Title", db_path=db_path)
    updated = update_prd(prd_id=prd["id"], title="New Title", status="completed", db_path=db_path)
    assert updated["title"] == "New Title"
    assert updated["status"] == "completed"


def test_update_prd_not_found_raises(db_path):
    from tc.services.prds import update_prd
    from tc.db.exceptions import PrdNotFound
    with pytest.raises(PrdNotFound):
        update_prd(prd_id=99999, title="Ghost", db_path=db_path)


def test_update_prd_invalid_status_raises(db_path):
    from tc.services.prds import create_prd, update_prd
    from tc.db.exceptions import ValidationError
    prd = create_prd(title="Status test", db_path=db_path)
    with pytest.raises(ValidationError, match="invalid status"):
        update_prd(prd_id=prd["id"], status="broken", db_path=db_path)


def test_update_prd_no_fields_returns_unchanged(db_path):
    from tc.services.prds import create_prd, update_prd
    prd = create_prd(title="No-op PRD", db_path=db_path)
    result = update_prd(prd_id=prd["id"], db_path=db_path)
    assert result["title"] == "No-op PRD"


# ---------------------------------------------------------------------------
# tc.services.wp — get_wp, list_wps, search_wps
# ---------------------------------------------------------------------------

def test_get_wp_inline_content(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp, get_wp
    task = create_task(title="WP task", db_path=db_path)
    stored = store_wp(task_id=task["id"], type_="analysis", title="Notes", content="hello world", db_path=db_path)
    result = get_wp(wp_id=stored["id"], db_path=db_path)
    assert result["content"] == "hello world"


def test_get_wp_file_content(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp, get_wp
    from tc import WP_CONTENT_SIZE_THRESHOLD
    task = create_task(title="Big WP task", db_path=db_path)
    large = "x" * (WP_CONTENT_SIZE_THRESHOLD + 1)
    stored = store_wp(task_id=task["id"], type_="analysis", title="Big Notes", content=large, db_path=db_path)
    result = get_wp(wp_id=stored["id"], db_path=db_path)
    assert result["content"] == large


def test_get_wp_not_found_raises(db_path):
    from tc.services.wp import get_wp
    from tc.db.exceptions import WorkProductNotFound
    with pytest.raises(WorkProductNotFound):
        get_wp(wp_id=99999, db_path=db_path)


def test_list_wps_empty(db_path):
    from tc.services.wp import list_wps
    result = list_wps(db_path=db_path)
    assert result == []


def test_list_wps_filter_by_task(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp, list_wps
    t1 = create_task(title="T1", db_path=db_path)
    t2 = create_task(title="T2", db_path=db_path)
    store_wp(task_id=t1["id"], type_="analysis", title="WP1", db_path=db_path)
    store_wp(task_id=t2["id"], type_="analysis", title="WP2", db_path=db_path)
    result = list_wps(task=t1["id"], db_path=db_path)
    assert len(result) == 1
    assert result[0]["task_id"] == t1["id"]


def test_list_wps_filter_by_type(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp, list_wps
    task = create_task(title="T", db_path=db_path)
    store_wp(task_id=task["id"], type_="implementation", title="Impl", db_path=db_path)
    store_wp(task_id=task["id"], type_="analysis", title="Anal", db_path=db_path)
    result = list_wps(type_="implementation", db_path=db_path)
    assert len(result) == 1
    assert result[0]["type"] == "implementation"


def test_search_wps_returns_results(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp, search_wps
    task = create_task(title="Search task", db_path=db_path)
    store_wp(task_id=task["id"], type_="analysis", title="Unique keyword: xyzzy123", content="xyzzy123 content", db_path=db_path)
    results = search_wps(query="xyzzy123", db_path=db_path)
    assert len(results) >= 1


def test_search_wps_no_results(db_path):
    from tc.services.wp import search_wps
    results = search_wps(query="zzznomatch99999", db_path=db_path)
    assert results == []


# ---------------------------------------------------------------------------
# tc.services.handoff — handoff_task
# ---------------------------------------------------------------------------

def test_handoff_task_success(db_path):
    from tc.services.tasks import create_task
    from tc.services.handoff import handoff_task
    task = create_task(title="Handoff task", agent="me", db_path=db_path)
    result = handoff_task(task_id=task["id"], from_agent="me", to_agent="qa",
                          context="Ready for review", db_path=db_path)
    assert result["status"] == "handed_off"
    assert result["from"] == "me"
    assert result["to"] == "qa"
    assert result["context"] == "Ready for review"


def test_handoff_task_context_truncated(db_path):
    from tc.services.tasks import create_task
    from tc.services.handoff import handoff_task
    task = create_task(title="Truncate task", db_path=db_path)
    long_context = "x" * 300
    result = handoff_task(task_id=task["id"], from_agent="me", to_agent="qa",
                          context=long_context, db_path=db_path)
    assert len(result["context"]) == 200


def test_handoff_task_updates_agent(db_path):
    from tc.services.tasks import create_task, get_task
    from tc.services.handoff import handoff_task
    task = create_task(title="Agent update", agent="me", db_path=db_path)
    handoff_task(task_id=task["id"], from_agent="me", to_agent="qa",
                 context="Done", db_path=db_path)
    updated = get_task(task_id=task["id"], db_path=db_path)
    assert updated["agent"] == "qa"


def test_handoff_task_not_found_raises(db_path):
    from tc.services.handoff import handoff_task
    from tc.db.exceptions import TaskNotFound
    with pytest.raises(TaskNotFound):
        handoff_task(task_id=99999, from_agent="me", to_agent="qa",
                     context="nope", db_path=db_path)


def test_handoff_task_logs_action(db_path):
    from tc.services.tasks import create_task
    from tc.services.handoff import handoff_task
    from tc.db.connection import get_db
    task = create_task(title="Log handoff", db_path=db_path)
    handoff_task(task_id=task["id"], from_agent="me", to_agent="qa",
                 context="ctx", db_path=db_path)
    conn = get_db(db_path)
    log = conn.execute(
        "SELECT * FROM agent_log WHERE task_id = ? AND action = 'handoff'", (task["id"],)
    ).fetchone()
    conn.close()
    assert log is not None


# ---------------------------------------------------------------------------
# tc.services.log — list_log
# ---------------------------------------------------------------------------

def test_list_log_empty(db_path):
    from tc.services.log import list_log
    result = list_log(db_path=db_path)
    assert result == []


def test_list_log_filter_by_task(db_path):
    from tc.services.tasks import create_task
    from tc.services.handoff import handoff_task
    from tc.services.log import list_log
    t1 = create_task(title="Task A", db_path=db_path)
    t2 = create_task(title="Task B", db_path=db_path)
    handoff_task(task_id=t1["id"], from_agent="me", to_agent="qa", context="a", db_path=db_path)
    handoff_task(task_id=t2["id"], from_agent="me", to_agent="qa", context="b", db_path=db_path)
    result = list_log(task=t1["id"], db_path=db_path)
    assert len(result) == 1
    assert result[0]["task_id"] == t1["id"]


def test_list_log_limit(db_path):
    from tc.services.tasks import create_task
    from tc.services.handoff import handoff_task
    from tc.services.log import list_log
    task = create_task(title="T", db_path=db_path)
    for i in range(5):
        handoff_task(task_id=task["id"], from_agent="me", to_agent="qa",
                     context=f"ctx {i}", db_path=db_path)
    result = list_log(limit=3, db_path=db_path)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# tc.services.progress — get_progress
# ---------------------------------------------------------------------------

def test_get_progress_empty(db_path):
    from tc.services.progress import get_progress
    result = get_progress(db_path=db_path)
    assert "by_stream" in result
    assert "totals" in result
    assert result["by_stream"] == []
    assert result["totals"] == {}


def test_get_progress_counts_tasks(db_path):
    from tc.services.tasks import create_task, update_task
    from tc.services.progress import get_progress
    create_task(title="P1", db_path=db_path)
    t2 = create_task(title="P2", db_path=db_path)
    update_task(task_id=t2["id"], status="completed", db_path=db_path)
    result = get_progress(db_path=db_path)
    totals = result["totals"]
    assert totals.get("pending", 0) >= 1
    assert totals.get("completed", 0) >= 1


# ---------------------------------------------------------------------------
# tc.services.streams — create_stream, list_streams, get_stream
# ---------------------------------------------------------------------------

def test_create_stream_success(db_path):
    from tc.services.prds import create_prd
    from tc.services.streams import create_stream
    prd = create_prd(title="PRD for streams", db_path=db_path)
    stream = create_stream(name="feature-x", prd=prd["id"], db_path=db_path)
    assert stream["name"] == "feature-x"
    assert stream["prd_id"] == prd["id"]


def test_create_stream_prd_not_found_raises(db_path):
    from tc.services.streams import create_stream
    from tc.db.exceptions import PrdNotFound
    with pytest.raises(PrdNotFound):
        create_stream(name="orphan", prd=99999, db_path=db_path)


def test_create_stream_duplicate_name_raises(db_path):
    from tc.services.prds import create_prd
    from tc.services.streams import create_stream
    from tc.db.exceptions import ConflictError
    prd = create_prd(title="PRD", db_path=db_path)
    create_stream(name="dup-stream", prd=prd["id"], db_path=db_path)
    with pytest.raises(ConflictError):
        create_stream(name="dup-stream", prd=prd["id"], db_path=db_path)


def test_list_streams_empty(db_path):
    from tc.services.streams import list_streams
    assert list_streams(db_path=db_path) == []


def test_list_streams_filter_by_status(db_path):
    from tc.services.prds import create_prd
    from tc.services.streams import create_stream, list_streams
    prd = create_prd(title="P", db_path=db_path)
    create_stream(name="s1", prd=prd["id"], db_path=db_path)
    result = list_streams(status="active", db_path=db_path)
    assert len(result) == 1


def test_get_stream_by_id(db_path):
    from tc.services.prds import create_prd
    from tc.services.streams import create_stream, get_stream
    prd = create_prd(title="PRD", db_path=db_path)
    created = create_stream(name="by-id", prd=prd["id"], db_path=db_path)
    result = get_stream(name_or_id=str(created["id"]), db_path=db_path)
    assert result["name"] == "by-id"


def test_get_stream_by_name(db_path):
    from tc.services.prds import create_prd
    from tc.services.streams import create_stream, get_stream
    prd = create_prd(title="PRD", db_path=db_path)
    create_stream(name="named-stream", prd=prd["id"], db_path=db_path)
    result = get_stream(name_or_id="named-stream", db_path=db_path)
    assert result["name"] == "named-stream"


def test_get_stream_not_found_raises(db_path):
    from tc.services.streams import get_stream, StreamNotFound
    with pytest.raises(StreamNotFound):
        get_stream(name_or_id="ghost-stream", db_path=db_path)


# ---------------------------------------------------------------------------
# tc.api — full __all__ surface accessible
# ---------------------------------------------------------------------------

def test_tc_api_full_all_importable():
    import tc.api
    for name in tc.api.__all__:
        assert hasattr(tc.api, name), f"tc.api missing __all__ member: {name}"


def test_tc_api_new_ops_callable():
    from tc.api import (
        get_task, list_tasks, update_task, claim_task, next_task,
        remove_dependency, get_prd, list_prds, update_prd,
        get_wp, list_wps, search_wps, handoff_task, list_log,
        get_progress, create_stream, get_stream, list_streams,
    )
    for fn in (
        get_task, list_tasks, update_task, claim_task, next_task,
        remove_dependency, get_prd, list_prds, update_prd,
        get_wp, list_wps, search_wps, handoff_task, list_log,
        get_progress, create_stream, get_stream, list_streams,
    ):
        assert callable(fn), f"{fn!r} is not callable"


def test_tc_api_import_still_side_effect_free(tmp_path, monkeypatch):
    import sys
    for key in list(sys.modules):
        if key.startswith("tc.api"):
            del sys.modules[key]
    monkeypatch.chdir(tmp_path)
    import tc.api  # must not raise FileNotFoundError
    assert tc.api is not None


# ---------------------------------------------------------------------------
# tc.api — services compose under one transaction()
# ---------------------------------------------------------------------------

def test_services_compose_in_transaction(db_path):
    """create_prd + create_task + handoff_task all share one conn via transaction()."""
    from tc.db.connection import get_db, transaction
    from tc.services.prds import create_prd
    from tc.services.tasks import create_task, update_task
    from tc.services.handoff import handoff_task

    conn = get_db(db_path)
    try:
        with transaction(conn):
            prd = create_prd(title="Batch PRD", conn=conn)
            task = create_task(title="Batch task", prd=prd["id"], agent="me", conn=conn)
            update_task(task_id=task["id"], status="in_progress", conn=conn)
            handoff_task(task_id=task["id"], from_agent="me", to_agent="qa",
                         context="done", conn=conn)
    finally:
        conn.close()

    # Verify everything persisted
    conn2 = get_db(db_path)
    t = conn2.execute("SELECT * FROM tasks WHERE id = ?", (task["id"],)).fetchone()
    log = conn2.execute(
        "SELECT * FROM agent_log WHERE task_id = ? AND action = 'handoff'", (task["id"],)
    ).fetchone()
    conn2.close()
    assert t is not None
    assert t["status"] == "in_progress"
    assert log is not None


def test_transaction_rollback_across_services(db_path):
    """A mid-batch failure leaves no partial state."""
    from tc.db.connection import get_db, transaction
    from tc.services.prds import create_prd
    from tc.services.tasks import create_task

    conn = get_db(db_path)
    try:
        with pytest.raises(RuntimeError):
            with transaction(conn):
                prd = create_prd(title="Will be rolled back", conn=conn)
                create_task(title="Also rolled back", prd=prd["id"], conn=conn)
                raise RuntimeError("intentional failure")
    finally:
        conn.close()

    conn2 = get_db(db_path)
    prd_count = conn2.execute("SELECT COUNT(*) FROM prds").fetchone()[0]
    task_count = conn2.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn2.close()
    assert prd_count == 0
    assert task_count == 0


# ---------------------------------------------------------------------------
# Fitness check: CLI handlers must not contain raw SQL
# ---------------------------------------------------------------------------

def test_cli_command_bodies_have_no_raw_sql():
    """Verify that refactored CLI command modules contain no raw SQL queries.

    This catches logic drift: if someone puts SQL back into a command body,
    this test fails, reminding them to put it in the service layer instead.

    We check for the characteristic pattern of .execute(" with SQL keywords
    directly in the command source (rather than service source).
    """
    import ast
    import re
    from pathlib import Path

    commands_dir = Path(__file__).parent.parent / "src" / "tc" / "commands"
    # Files that should only contain thin wrappers
    files_to_check = [
        "task.py",
        "prd.py",
        "wp.py",
        "handoff.py",
        "log_cmd.py",
        "progress.py",
        "stream.py",
    ]

    sql_keywords = re.compile(
        r'\.execute\s*\(',
        re.IGNORECASE,
    )

    violations = []
    for fname in files_to_check:
        fpath = commands_dir / fname
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        if sql_keywords.search(source):
            violations.append(fname)

    assert violations == [], (
        f"Command files still contain raw .execute() SQL calls (should be in services): "
        f"{violations}"
    )


# ---------------------------------------------------------------------------
# wp.py ordering fix: file written before commit
# ---------------------------------------------------------------------------

def test_large_wp_file_exists_after_store(db_path):
    """After store_wp with large content, the file must exist on disk."""
    from pathlib import Path
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp
    from tc import WP_CONTENT_SIZE_THRESHOLD

    task = create_task(title="File ordering test", db_path=db_path)
    large = "y" * (WP_CONTENT_SIZE_THRESHOLD + 100)
    wp = store_wp(task_id=task["id"], type_="impl", title="Order test", content=large, db_path=db_path)

    assert wp["file_path"] is not None
    fp = Path(wp["file_path"])
    assert fp.exists(), f"Expected file at {fp} but it does not exist"
    assert fp.read_text(encoding="utf-8") == large
