"""Tests for tc.services.* and tc.api / tc.db.exceptions.

Verifies:
- Typed exceptions in tc.db.exceptions are importable.
- transaction() context manager commits on success, rolls back on error.
- create_task / create_prd / store_wp / add_dependency return correct dicts.
- Typed exceptions are raised for bad inputs.
- Batched ops in a single transaction() commit atomically.
- tc.api facade imports without touching the FS (import-side-effect-free).
- All __all__ symbols in tc.api are importable.
- CLI backward-compat: existing CLI commands still produce the same output
  (tests delegated to the existing test_task.py / test_prd.py / test_wp.py suites).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures  (mirror conftest.py pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    """Fresh initialised DB in tmp dir."""
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
# tc.db.exceptions — importability
# ---------------------------------------------------------------------------


def test_exceptions_importable():
    from tc.db.exceptions import (
        TcError,
        TaskNotFound,
        PrdNotFound,
        WorkProductNotFound,
        ValidationError,
        ConflictError,
        DatabaseError,
    )

    # All are subclasses of TcError (except DatabaseError is also TcError)
    assert issubclass(TaskNotFound, TcError)
    assert issubclass(PrdNotFound, TcError)
    assert issubclass(WorkProductNotFound, TcError)
    assert issubclass(ValidationError, TcError)
    assert issubclass(ConflictError, TcError)
    assert issubclass(DatabaseError, TcError)


# ---------------------------------------------------------------------------
# transaction() context manager
# ---------------------------------------------------------------------------


def test_transaction_commits_on_success(db_path):
    from tc.db.connection import get_db, transaction
    from tc.services.tasks import create_task

    conn = get_db(db_path)
    try:
        with transaction(conn):
            task = create_task(title="Commit test", conn=conn)
    finally:
        conn.close()

    # Verify row persisted
    conn2 = get_db(db_path)
    row = conn2.execute("SELECT * FROM tasks WHERE id = ?", (task["id"],)).fetchone()
    conn2.close()
    assert row is not None
    assert row["title"] == "Commit test"


def test_transaction_rolls_back_on_error(db_path):
    from tc.db.connection import get_db, transaction
    from tc.services.tasks import create_task

    conn = get_db(db_path)
    task_id = None
    try:
        with pytest.raises(RuntimeError):
            with transaction(conn):
                task = create_task(title="Should be rolled back", conn=conn)
                task_id = task["id"]
                raise RuntimeError("intentional error")
    finally:
        conn.close()

    # Row must NOT be persisted
    conn2 = get_db(db_path)
    row = conn2.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn2.close()
    assert row is None


# ---------------------------------------------------------------------------
# tc.services.tasks.create_task
# ---------------------------------------------------------------------------


def test_create_task_returns_dict(db_path):
    from tc.services.tasks import create_task

    task = create_task(title="New task", db_path=db_path)
    assert isinstance(task, dict)
    assert task["title"] == "New task"
    assert task["id"] is not None
    assert task["status"] == "pending"


def test_create_task_with_all_fields(db_path):
    from tc.services.tasks import create_task

    task = create_task(
        title="Full task",
        agent="me",
        priority=1,
        description="Task description",
        metadata={"tags": ["PERF"]},
        db_path=db_path,
    )
    assert task["agent"] == "me"
    assert task["priority"] == 1
    assert task["description"] == "Task description"


def test_create_task_priority_validation(db_path):
    from tc.services.tasks import create_task
    from tc.db.exceptions import ValidationError

    with pytest.raises(ValidationError, match="priority"):
        create_task(title="Bad priority", priority=5, db_path=db_path)


def test_create_task_empty_title_raises(db_path):
    from tc.services.tasks import create_task
    from tc.db.exceptions import ValidationError

    with pytest.raises(ValidationError, match="title"):
        create_task(title="", db_path=db_path)


def test_create_task_invalid_metadata_raises(db_path):
    from tc.services.tasks import create_task
    from tc.db.exceptions import ValidationError

    with pytest.raises(ValidationError, match="metadata"):
        create_task(title="Bad meta", metadata="not-valid-json", db_path=db_path)


# ---------------------------------------------------------------------------
# tc.services.tasks.add_dependency
# ---------------------------------------------------------------------------


def test_add_dependency_success(db_path):
    from tc.services.tasks import create_task, add_dependency

    t1 = create_task(title="Task 1", db_path=db_path)
    t2 = create_task(title="Task 2", db_path=db_path)
    result = add_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)
    assert result["status"] == "added"
    assert result["task_id"] == t2["id"]
    assert result["depends_on"] == t1["id"]


def test_add_dependency_self_raises(db_path):
    from tc.services.tasks import create_task, add_dependency
    from tc.db.exceptions import ValidationError

    task = create_task(title="Self dep", db_path=db_path)
    with pytest.raises(ValidationError, match="itself"):
        add_dependency(task_id=task["id"], depends_on=task["id"], db_path=db_path)


def test_add_dependency_missing_task_raises(db_path):
    from tc.services.tasks import create_task, add_dependency
    from tc.db.exceptions import TaskNotFound

    task = create_task(title="Real task", db_path=db_path)
    with pytest.raises(TaskNotFound):
        add_dependency(task_id=task["id"], depends_on=99999, db_path=db_path)


def test_add_dependency_duplicate_raises(db_path):
    from tc.services.tasks import create_task, add_dependency
    from tc.db.exceptions import ConflictError

    t1 = create_task(title="T1", db_path=db_path)
    t2 = create_task(title="T2", db_path=db_path)
    add_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)
    with pytest.raises(ConflictError, match="already exists"):
        add_dependency(task_id=t2["id"], depends_on=t1["id"], db_path=db_path)


# ---------------------------------------------------------------------------
# tc.services.prds.create_prd
# ---------------------------------------------------------------------------


def test_create_prd_returns_dict(db_path):
    from tc.services.prds import create_prd

    prd = create_prd(title="My PRD", db_path=db_path)
    assert isinstance(prd, dict)
    assert prd["title"] == "My PRD"
    assert prd["id"] is not None


def test_create_prd_with_description_and_content(db_path):
    from tc.services.prds import create_prd

    prd = create_prd(
        title="Full PRD",
        description="Short desc",
        content="Full content here",
        db_path=db_path,
    )
    assert prd["description"] == "Short desc"
    assert prd["content"] == "Full content here"


def test_create_prd_empty_title_raises(db_path):
    from tc.services.prds import create_prd
    from tc.db.exceptions import ValidationError

    with pytest.raises(ValidationError, match="title"):
        create_prd(title="", db_path=db_path)


# ---------------------------------------------------------------------------
# tc.services.wp.store_wp
# ---------------------------------------------------------------------------


def test_store_wp_inline_returns_dict(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp

    task = create_task(title="WP task", db_path=db_path)
    wp = store_wp(
        task_id=task["id"],
        type_="analysis",
        title="My WP",
        content="Short content",
        db_path=db_path,
    )
    assert isinstance(wp, dict)
    assert wp["title"] == "My WP"
    assert wp["content"] == "Short content"
    assert wp["file_path"] is None


def test_store_wp_large_content_writes_file(db_path, tmp_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp
    from tc import WP_CONTENT_SIZE_THRESHOLD

    task = create_task(title="WP large task", db_path=db_path)
    large_content = "x" * (WP_CONTENT_SIZE_THRESHOLD + 100)
    wp = store_wp(
        task_id=task["id"],
        type_="analysis",
        title="Large WP",
        content=large_content,
        db_path=db_path,
    )
    assert wp["file_path"] is not None
    from pathlib import Path

    assert Path(wp["file_path"]).exists()


def test_store_wp_missing_task_raises(db_path):
    from tc.services.wp import store_wp
    from tc.db.exceptions import TaskNotFound

    with pytest.raises(TaskNotFound):
        store_wp(task_id=99999, type_="analysis", title="Orphan WP", db_path=db_path)


def test_store_wp_empty_title_raises(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp
    from tc.db.exceptions import ValidationError

    task = create_task(title="WP task", db_path=db_path)
    with pytest.raises(ValidationError, match="title"):
        store_wp(task_id=task["id"], type_="analysis", title="", db_path=db_path)


def test_store_wp_empty_type_raises(db_path):
    from tc.services.tasks import create_task
    from tc.services.wp import store_wp
    from tc.db.exceptions import ValidationError

    task = create_task(title="WP task", db_path=db_path)
    with pytest.raises(ValidationError, match="type"):
        store_wp(task_id=task["id"], type_="", title="Valid title", db_path=db_path)


# ---------------------------------------------------------------------------
# Batch transaction: create_prd + N tasks + wire deps in one transaction
# ---------------------------------------------------------------------------


def test_batch_prd_tasks_deps_in_transaction(db_path):
    """The headline token-win use case: PRD + tasks + deps in one conn."""
    from tc.db.connection import get_db, transaction
    from tc.services.prds import create_prd
    from tc.services.tasks import create_task, add_dependency

    conn = get_db(db_path)
    try:
        with transaction(conn):
            prd = create_prd(title="Batch PRD", conn=conn)
            specs = [
                {"title": f"Task {i}", "priority": 0, "agent": "me"} for i in range(5)
            ]
            ids = [create_task(prd=prd["id"], **s, conn=conn)["id"] for s in specs]
            for prev, cur in zip(ids, ids[1:]):
                add_dependency(task_id=cur, depends_on=prev, conn=conn)
    finally:
        conn.close()

    # Verify everything persisted
    conn2 = get_db(db_path)
    task_count = conn2.execute(
        "SELECT COUNT(*) FROM tasks WHERE prd_id = ?", (prd["id"],)
    ).fetchone()[0]
    dep_count = conn2.execute("SELECT COUNT(*) FROM task_dependencies").fetchone()[0]
    conn2.close()

    assert task_count == 5
    assert dep_count == 4  # 5 tasks -> 4 sequential deps


def test_batch_rollback_on_error_leaves_no_partial_state(db_path):
    """If an error occurs mid-batch, the whole batch rolls back."""
    from tc.db.connection import get_db, transaction
    from tc.services.prds import create_prd
    from tc.services.tasks import create_task

    conn = get_db(db_path)
    try:
        with pytest.raises(RuntimeError):
            with transaction(conn):
                prd = create_prd(title="Partial PRD", conn=conn)
                create_task(title="Task 1", prd=prd["id"], conn=conn)
                raise RuntimeError("mid-batch failure")
    finally:
        conn.close()

    conn2 = get_db(db_path)
    prd_count = conn2.execute("SELECT COUNT(*) FROM prds").fetchone()[0]
    task_count = conn2.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn2.close()

    assert prd_count == 0
    assert task_count == 0


# ---------------------------------------------------------------------------
# tc.api facade — import side-effect free + __all__
# ---------------------------------------------------------------------------


def test_tc_api_import_no_side_effects(tmp_path, monkeypatch):
    """Importing tc.api must NOT touch the filesystem."""
    import sys

    for key in list(sys.modules):
        if key == "tc.api":
            del sys.modules[key]

    monkeypatch.chdir(tmp_path)  # no DB in tmp_path

    import tc.api  # must not raise FileNotFoundError

    assert tc.api is not None


def test_tc_api_all_exports_importable():
    import tc.api

    for name in tc.api.__all__:
        assert hasattr(tc.api, name), f"tc.api missing __all__ member: {name}"


def test_tc_api_facade_functions_accessible():
    from tc.api import create_task, create_prd, add_dependency, store_wp, transaction

    assert callable(create_task)
    assert callable(create_prd)
    assert callable(add_dependency)
    assert callable(store_wp)
    assert callable(transaction)


def test_tc_api_create_task_end_to_end(db_path):
    from tc.api import create_task

    task = create_task(title="Via facade", priority=0, db_path=db_path)
    assert task["title"] == "Via facade"
    assert task["priority"] == 0


def test_tc_api_create_prd_end_to_end(db_path):
    from tc.api import create_prd

    prd = create_prd(title="Facade PRD", db_path=db_path)
    assert prd["title"] == "Facade PRD"


def test_tc_api_store_wp_end_to_end(db_path):
    from tc.api import create_task, store_wp

    task = create_task(title="WP facade task", db_path=db_path)
    wp = store_wp(
        task_id=task["id"], type_="implementation", title="Impl notes", db_path=db_path
    )
    assert wp["task_id"] == task["id"]
    assert wp["type"] == "implementation"


def test_tc_api_exceptions_accessible():
    from tc.api import (
        TcError,
        TaskNotFound,
        PrdNotFound,
        WorkProductNotFound,
        ValidationError,
        ConflictError,
        DatabaseError,
    )

    # Sanity check they are all exceptions
    for exc_cls in (
        TcError,
        TaskNotFound,
        PrdNotFound,
        WorkProductNotFound,
        ValidationError,
        ConflictError,
        DatabaseError,
    ):
        assert issubclass(exc_cls, Exception)
