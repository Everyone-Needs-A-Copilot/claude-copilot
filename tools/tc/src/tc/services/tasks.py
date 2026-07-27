"""tc.services.tasks — domain logic for task and dependency operations.

All functions accept an optional ``conn`` parameter:
  - conn=None (default): open, use, commit, close own connection per call.
  - conn=<existing>: use caller's connection without commit/close so the
    caller can batch multiple ops inside one transaction() block.

This module has ZERO import-time side effects — no DB opened, no env read.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import (
    ConflictError,
    TaskNotFound,
    ValidationError,
)

_VALID_STATUSES = {"pending", "in_progress", "completed", "blocked", "cancelled"}
_VALID_PRIORITIES = range(0, 4)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _open_conn(db_path: Path) -> sqlite3.Connection:
    from tc.db.connection import get_db

    return get_db(db_path)


def _require_db_path(db_path: Optional[Path]) -> Path:
    if db_path is not None:
        return db_path
    from tc.db.connection import find_db_path

    found = find_db_path()
    if found is None:
        raise FileNotFoundError(
            "No tasks.db found. Run `tc init` to create a database."
        )
    return found


def create_task(
    *,
    title: str,
    prd: Optional[int] = None,
    stream: Optional[int] = None,
    agent: Optional[str] = None,
    priority: int = 2,
    parent: Optional[int] = None,
    description: Optional[str] = None,
    metadata: Optional[dict | str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Create a new task and return the inserted row as a dict.

    Args:
        title:       Task title (required, non-empty).
        prd:         Associated PRD ID.
        stream:      Associated stream ID.
        agent:       Assigned agent slug.
        priority:    Priority 0-3 (0=highest).  Default 2.
        parent:      Parent task ID.
        description: Long-form description.
        metadata:    JSON-serialisable dict OR pre-serialised JSON string.
        conn:        Existing connection for batching; if None, opens own.
        db_path:     Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict matching ``tc task create --json`` output shape.

    Raises:
        ValidationError: on bad priority, empty title, or invalid metadata.
    """
    if not title or not title.strip():
        raise ValidationError("title must not be empty")
    if priority < 0 or priority > 3:
        raise ValidationError("priority must be between 0 and 3")

    # Normalise metadata to a JSON string or None
    metadata_str: Optional[str]
    if metadata is None:
        metadata_str = None
    elif isinstance(metadata, str):
        try:
            json.loads(metadata)  # validate
        except json.JSONDecodeError as exc:
            raise ValidationError(f"invalid metadata JSON: {exc}") from exc
        metadata_str = metadata
    else:
        try:
            metadata_str = json.dumps(metadata)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"metadata is not JSON-serialisable: {exc}") from exc

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        cursor = conn.execute(
            """INSERT INTO tasks (prd_id, stream_id, title, description, agent,
                                  priority, parent_task_id, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (prd, stream, title, description, agent, priority, parent, metadata_str),
        )
        task_id = cursor.lastrowid

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

        if owns_conn:
            conn.commit()

        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def get_task(
    *,
    task_id: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a task dict with a ``dependencies`` list, or raise TaskNotFound.

    Args:
        task_id: The task ID to fetch.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict matching ``tc task get --json`` output, plus ``dependencies`` list.

    Raises:
        TaskNotFound: if task_id does not exist.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(f"task #{task_id} not found")

        deps = conn.execute(
            "SELECT depends_on FROM task_dependencies WHERE task_id = ?", (task_id,)
        ).fetchall()

        d = _row_to_dict(row)
        d["dependencies"] = [r["depends_on"] for r in deps]
        return d
    finally:
        if owns_conn:
            conn.close()


def list_tasks(
    *,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    stream: Optional[int] = None,
    prd: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return a list of task dicts with optional filters.

    Args:
        status:  Filter by status string.
        agent:   Filter by assigned agent.
        stream:  Filter by stream_id.
        prd:     Filter by prd_id.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        List of task dicts ordered by priority ASC, id ASC.

    Raises:
        ValidationError: if status is not a valid status string.
    """
    if status is not None and status not in _VALID_STATUSES:
        raise ValidationError(
            f"invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
        )

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list = []

        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if agent is not None:
            query += " AND agent = ?"
            params.append(agent)
        if stream is not None:
            query += " AND stream_id = ?"
            params.append(stream)
        if prd is not None:
            query += " AND prd_id = ?"
            params.append(prd)

        query += " ORDER BY priority ASC, id ASC"

        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        if owns_conn:
            conn.close()


def update_task(
    *,
    task_id: int,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[int] = None,
    title: Optional[str] = None,
    metadata: Optional[dict | str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Update fields on an existing task and return the updated row.

    Args:
        task_id:     Task ID to update.
        status:      New status string.
        agent:       New assigned agent.
        description: New description.
        priority:    New priority 0-3.
        title:       New title (must be non-empty if provided).
        metadata:    JSON-serialisable dict or pre-serialised string to *merge*
                     into existing metadata (not replace).
        conn:        Existing connection for batching; if None, opens own.
        db_path:     Explicit DB path; if None, walks up from cwd.

    Returns:
        Updated task dict.

    Raises:
        TaskNotFound:    if task_id does not exist.
        ValidationError: if any field value is invalid.
    """
    if status is not None and status not in _VALID_STATUSES:
        raise ValidationError(
            f"invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
        )
    if priority is not None and priority not in _VALID_PRIORITIES:
        raise ValidationError("priority must be between 0 and 3")
    if title is not None and not title.strip():
        raise ValidationError("title cannot be empty")

    # Normalise metadata to a dict (for merging)
    new_metadata: Optional[dict] = None
    if metadata is not None:
        if isinstance(metadata, str):
            try:
                new_metadata = json.loads(metadata)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"invalid metadata JSON: {exc}") from exc
        else:
            new_metadata = metadata

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(f"task #{task_id} not found")

        updates = []
        params = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if agent is not None:
            updates.append("agent = ?")
            params.append(agent)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if new_metadata is not None:
            existing_raw = row["metadata"]
            existing: dict = json.loads(existing_raw) if existing_raw else {}
            merged = {**existing, **new_metadata}
            updates.append("metadata = ?")
            params.append(json.dumps(merged))

        if not updates:
            return _row_to_dict(row)

        updates.append("updated_at = datetime('now')")
        params.append(task_id)
        conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)

        # Log completion if status changed to completed and agent is set
        if status == "completed" and row["agent"]:
            conn.execute(
                "INSERT INTO agent_log (agent, stream_id, task_id, action, details)"
                " VALUES (?, ?, ?, ?, ?)",
                (row["agent"], row["stream_id"], task_id, "completed", None),
            )

        if owns_conn:
            conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def claim_task(
    *,
    task_id: int,
    agent: str,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Atomically claim a pending task for an agent.

    Uses an IMMEDIATE transaction so only one agent wins the race.

    Args:
        task_id: Task to claim.
        agent:   Agent slug claiming the task.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Updated task dict with status='in_progress'.

    Raises:
        ConflictError: if task is not found, already claimed, or not pending.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """UPDATE tasks
               SET claimed_by = ?,
                   claimed_at = datetime('now'),
                   status = 'in_progress',
                   agent = ?,
                   updated_at = datetime('now')
               WHERE id = ?
                 AND (claimed_by IS NULL OR claimed_by = ?)
                 AND status = 'pending'""",
            (agent, agent, task_id, agent),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            raise ConflictError(
                f"task #{task_id} could not be claimed: not found, already claimed, or not pending"
            )

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.execute(
            "INSERT INTO agent_log (agent, stream_id, task_id, action, details)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                agent,
                row["stream_id"] if row else None,
                task_id,
                "claimed",
                f"Claimed by {agent}",
            ),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row)
    except ConflictError:
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if owns_conn:
            conn.close()


def next_task(
    *,
    stream: Optional[int] = None,
    agent: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Return the next highest-priority pending task with all deps completed.

    Args:
        stream:  Restrict to tasks in this stream_id.
        agent:   Restrict to tasks assigned to this agent (or unassigned).
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Task dict, or None if no eligible task is available.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        query = """
            SELECT t.* FROM tasks t
            WHERE t.status = 'pending'
              AND NOT EXISTS (
                  SELECT 1 FROM task_dependencies td
                  JOIN tasks dep ON dep.id = td.depends_on
                  WHERE td.task_id = t.id
                    AND dep.status != 'completed'
              )
        """
        params: list = []

        if stream is not None:
            query += " AND t.stream_id = ?"
            params.append(stream)
        if agent is not None:
            query += " AND (t.agent = ? OR t.agent IS NULL)"
            params.append(agent)

        query += " ORDER BY t.priority ASC, t.id ASC LIMIT 1"

        row = conn.execute(query, params).fetchone()
        return _row_to_dict(row) if row is not None else None
    finally:
        if owns_conn:
            conn.close()


def remove_dependency(
    *,
    task_id: int,
    depends_on: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Remove a dependency link between two tasks.

    Returns ``{"task_id": int, "depends_on": int, "status": "removed"}``.

    Raises:
        TaskNotFound: if the dependency link does not exist.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        cursor = conn.execute(
            "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on = ?",
            (task_id, depends_on),
        )
        if cursor.rowcount == 0:
            raise TaskNotFound(f"no dependency found: task #{task_id} -> #{depends_on}")

        if owns_conn:
            conn.commit()

        return {"task_id": task_id, "depends_on": depends_on, "status": "removed"}
    finally:
        if owns_conn:
            conn.close()


def add_dependency(
    *,
    task_id: int,
    depends_on: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Wire a dependency: task_id depends on depends_on.

    Returns ``{"task_id": int, "depends_on": int, "status": "added"}``.

    Raises:
        ValidationError:  if task_id == depends_on.
        TaskNotFound:     if either task does not exist.
        ConflictError:    if the dependency already exists.
    """
    if task_id == depends_on:
        raise ValidationError("a task cannot depend on itself")

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        t = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if t is None:
            raise TaskNotFound(f"task #{task_id} not found")

        d = conn.execute("SELECT id FROM tasks WHERE id = ?", (depends_on,)).fetchone()
        if d is None:
            raise TaskNotFound(f"task #{depends_on} not found")

        try:
            conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on) VALUES (?, ?)",
                (task_id, depends_on),
            )
        except Exception as exc:
            msg = str(exc)
            if "UNIQUE constraint" in msg or "PRIMARY KEY" in msg:
                raise ConflictError(
                    f"dependency already exists: task #{task_id} depends on #{depends_on}"
                ) from exc
            raise

        if owns_conn:
            conn.commit()

        return {"task_id": task_id, "depends_on": depends_on, "status": "added"}
    finally:
        if owns_conn:
            conn.close()
