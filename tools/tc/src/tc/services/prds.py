"""tc.services.prds — domain logic for PRD operations.

All functions accept an optional ``conn`` parameter for transaction batching.
This module has ZERO import-time side effects.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import PrdNotFound, ValidationError
from tc.services.content_guard import (
    combine_field_summary,
    combine_field_warnings,
    scan_and_neutralize,
)

_VALID_STATUSES = {"active", "completed", "archived"}


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


def create_prd(
    *,
    title: str,
    description: Optional[str] = None,
    content: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Create a new PRD and return the inserted row as a dict.

    Args:
        title:       PRD title (required, non-empty).
        description: Short description.
        content:     Full PRD content.
        conn:        Existing connection for batching; if None, opens own.
        db_path:     Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict matching ``tc prd create --json`` output shape, plus a
        ``guard`` field (see `services/content_guard.py`).

    Raises:
        ValidationError: if title is empty.
    """
    if not title or not title.strip():
        raise ValidationError("title must not be empty")

    guard_title = scan_and_neutralize(title)
    guard_description = scan_and_neutralize(description) if description is not None else None
    guard_content = scan_and_neutralize(content) if content is not None else None
    guard_fields = {"title": guard_title}
    if guard_description is not None:
        guard_fields["description"] = guard_description
    if guard_content is not None:
        guard_fields["content"] = guard_content
    for line in combine_field_warnings(guard_fields):
        print(line, file=sys.stderr)
    guard_summary = combine_field_summary(guard_fields)
    title = guard_title.text
    description = guard_description.text if guard_description is not None else None
    content = guard_content.text if guard_content is not None else None

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        cursor = conn.execute(
            "INSERT INTO prds (title, description, content, guard) VALUES (?, ?, ?, ?)",
            (title, description, content, guard_summary),
        )
        prd_id = cursor.lastrowid

        row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()

        if owns_conn:
            conn.commit()

        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def get_prd(
    *,
    prd_id: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a PRD dict by ID.

    Args:
        prd_id:  PRD ID to fetch.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict matching ``tc prd get --json`` output shape.

    Raises:
        PrdNotFound: if prd_id does not exist.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
        if row is None:
            raise PrdNotFound(f"PRD #{prd_id} not found")
        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def list_prds(
    *,
    status: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return a list of PRD dicts, optionally filtered by status.

    Args:
        status:  Filter by status string (active, completed, archived).
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        List of PRD dicts ordered by id DESC.

    Raises:
        ValidationError: if status is not a valid PRD status.
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
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM prds WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM prds ORDER BY id DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        if owns_conn:
            conn.close()


def body_status(*, prd_id: int, conn=None, db_path=None) -> dict:
    """Resolve all direct, stream-associated and descendant tasks, preserving history."""
    owns = conn is None
    if owns:
        conn = _open_conn(_require_db_path(db_path))
    try:
        rows = conn.execute("""WITH RECURSIVE body(id) AS (
            SELECT id FROM tasks WHERE prd_id=? OR stream_id IN (SELECT id FROM streams WHERE prd_id=?)
            UNION SELECT t.id FROM tasks t JOIN body b ON t.parent_task_id=b.id
        ) SELECT t.* FROM tasks t JOIN body b ON t.id=b.id ORDER BY t.id""", (prd_id, prd_id)).fetchall()
        tasks = [dict(row) for row in rows]
        unresolved = [dict(id=t["id"], status=t["status"], claimed_by=t["claimed_by"]) for t in tasks
                      if t["status"] not in {"completed", "cancelled"} or t["claimed_by"]]
        active_workers = []
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='protocol_cycles'").fetchone()
        if table:
            import json
            ids = {t["id"] for t in tasks}
            for row in conn.execute("SELECT id,data FROM protocol_cycles"):
                data = json.loads(row["data"])
                for spec in data["plan"]["streams"]:
                    state = data["streams"][spec["id"]]
                    from tc.services.cycles import worker_is_active
                    if spec["task"] in ids and worker_is_active(data, spec["id"]):
                        active_workers.append({"cycle": row["id"], "stream": spec["id"], "task": spec["task"], "state": state["state"]})
        return {"prd": prd_id, "counts": {status: sum(t["status"] == status for t in tasks) for status in {"completed", "cancelled", "pending", "in_progress", "blocked"}},
                "openTasks": unresolved, "activeWorkers": active_workers, "canComplete": not unresolved and not active_workers}
    finally:
        if owns:
            conn.close()


def update_prd(
    *,
    prd_id: int,
    title: Optional[str] = None,
    status: Optional[str] = None,
    content: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Update fields on an existing PRD and return the updated row.

    Args:
        prd_id:  PRD ID to update.
        title:   New title.
        status:  New status (active, completed, archived).
        content: New full content.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Updated PRD dict.

    Raises:
        PrdNotFound:     if prd_id does not exist.
        ValidationError: if status is invalid.
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
        if status in {"completed", "archived"} and not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
        if row is None:
            raise PrdNotFound(f"PRD #{prd_id} not found")

        if status in {"completed", "archived"}:
            body = body_status(prd_id=prd_id, conn=conn)
            if not body["canComplete"]:
                raise ValidationError("PRD cannot close with unresolved tasks or active workers: " + str(body["openTasks"] + body["activeWorkers"]))
            conn.execute("UPDATE streams SET status='completed', updated_at=datetime('now') WHERE prd_id=? AND status IN ('active','paused')", (prd_id,))
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if content is not None:
            updates.append("content = ?")
            params.append(content)

        if not updates:
            return _row_to_dict(row)

        updates.append("updated_at = datetime('now')")
        params.append(prd_id)
        conn.execute(f"UPDATE prds SET {', '.join(updates)} WHERE id = ?", params)

        if owns_conn:
            conn.commit()

        row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()
