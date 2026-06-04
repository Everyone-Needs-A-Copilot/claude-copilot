"""tc.services.prds — domain logic for PRD operations.

All functions accept an optional ``conn`` parameter for transaction batching.
This module has ZERO import-time side effects.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import PrdNotFound, ValidationError

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
        Dict matching ``tc prd create --json`` output shape.

    Raises:
        ValidationError: if title is empty.
    """
    if not title or not title.strip():
        raise ValidationError("title must not be empty")

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        cursor = conn.execute(
            "INSERT INTO prds (title, description, content) VALUES (?, ?, ?)",
            (title, description, content),
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
        row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
        if row is None:
            raise PrdNotFound(f"PRD #{prd_id} not found")

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
