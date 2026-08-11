"""tc.services.streams — domain logic for stream operations.

All functions accept an optional ``conn`` parameter for transaction batching.
This module has ZERO import-time side effects.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import ConflictError, PrdNotFound, ValidationError


class StreamNotFound(Exception):
    """Raised when a stream ID or name does not exist."""


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


def create_stream(
    *,
    name: str,
    prd: int,
    worktree_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Create a new stream and return the inserted row as a dict.

    Args:
        name:          Stream name (must be unique).
        prd:           Associated PRD ID (must exist).
        worktree_path: Optional git worktree path.
        conn:          Existing connection for batching; if None, opens own.
        db_path:       Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict matching ``tc stream create --json`` output shape.

    Raises:
        PrdNotFound:  if prd does not exist.
        ConflictError: if a stream with this name already exists.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        prd_row = conn.execute("SELECT id FROM prds WHERE id = ?", (prd,)).fetchone()
        if prd_row is None:
            raise PrdNotFound(f"PRD #{prd} not found")

        try:
            cursor = conn.execute(
                "INSERT INTO streams (name, prd_id, worktree_path) VALUES (?, ?, ?)",
                (name, prd, worktree_path),
            )
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                raise ConflictError(f"stream '{name}' already exists") from exc
            raise

        stream_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM streams WHERE id = ?", (stream_id,)
        ).fetchone()

        if owns_conn:
            conn.commit()

        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def list_streams(
    *,
    status: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return a list of stream dicts, optionally filtered by status.

    Args:
        status:  Filter by status string.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        List of stream dicts ordered by id DESC.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM streams WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM streams ORDER BY id DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        if owns_conn:
            conn.close()


def get_stream(
    *,
    name_or_id: str,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a stream dict by name or numeric ID.

    Args:
        name_or_id: Stream name or numeric ID string.
        conn:       Existing connection for batching; if None, opens own.
        db_path:    Explicit DB path; if None, walks up from cwd.

    Returns:
        Stream dict.

    Raises:
        StreamNotFound: if no stream matches the given name or ID.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        row = None
        if str(name_or_id).isdigit():
            row = conn.execute(
                "SELECT * FROM streams WHERE id = ?", (int(name_or_id),)
            ).fetchone()

        if row is None:
            row = conn.execute(
                "SELECT * FROM streams WHERE name = ?", (name_or_id,)
            ).fetchone()

        if row is None:
            raise StreamNotFound(f"stream '{name_or_id}' not found")

        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def find_conflicts(
    *,
    statuses: Optional[list[str]] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Find files referenced by more than one stream's task metadata.

    The ``streams`` table itself has no ``files`` column -- file ownership is
    declared per-task in ``tasks.metadata.files`` (a list of paths), which is
    exactly what ``/orchestrate generate`` already writes when it creates each
    stream's tasks. This aggregates that existing data rather than requiring a
    schema migration.

    Args:
        statuses: Stream statuses to include (default: ``["active", "paused"]``
                   -- completed/archived streams are no longer running in
                   parallel with anything, so their file claims cannot
                   collide with a stream that is about to start).
        conn:     Existing connection for batching; if None, opens own.
        db_path:  Explicit DB path; if None, walks up from cwd.

    Returns:
        A list of ``{"file": str, "streams": [{"id": int, "name": str}, ...]}``
        dicts, one per file claimed by more than one stream. Empty when there
        are no conflicts.
    """
    if statuses is None:
        statuses = ["active", "paused"]

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        if not statuses:
            return []

        placeholders = ", ".join("?" for _ in statuses)
        stream_rows = conn.execute(
            f"SELECT id, name FROM streams WHERE status IN ({placeholders})",
            statuses,
        ).fetchall()

        file_to_streams: dict[str, dict[int, str]] = {}
        for stream_row in stream_rows:
            stream_id = stream_row["id"]
            stream_name = stream_row["name"]
            task_rows = conn.execute(
                "SELECT metadata FROM tasks WHERE stream_id = ?", (stream_id,)
            ).fetchall()
            for task_row in task_rows:
                raw = task_row["metadata"]
                if not raw:
                    continue
                try:
                    meta = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                files = meta.get("files") if isinstance(meta, dict) else None
                if not isinstance(files, list):
                    continue
                for f in files:
                    if isinstance(f, str):
                        file_to_streams.setdefault(f, {})[stream_id] = stream_name

        conflicts = []
        for f, streams_map in sorted(file_to_streams.items()):
            if len(streams_map) > 1:
                conflicts.append(
                    {
                        "file": f,
                        "streams": [
                            {"id": sid, "name": streams_map[sid]}
                            for sid in sorted(streams_map)
                        ],
                    }
                )
        return conflicts
    finally:
        if owns_conn:
            conn.close()
