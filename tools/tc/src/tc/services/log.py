"""tc.services.log — domain logic for agent activity log operations.

All functions accept an optional ``conn`` parameter for transaction batching.
This module has ZERO import-time side effects.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional


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


def list_log(
    *,
    agent: Optional[str] = None,
    stream: Optional[int] = None,
    task: Optional[int] = None,
    limit: int = 50,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return agent activity log entries with optional filters.

    Args:
        agent:   Filter by agent slug.
        stream:  Filter by stream_id.
        task:    Filter by task_id.
        limit:   Maximum entries to return (default 50).
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        List of log entry dicts ordered by id DESC.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        query = "SELECT * FROM agent_log WHERE 1=1"
        params: list = []

        if agent is not None:
            query += " AND agent = ?"
            params.append(agent)
        if stream is not None:
            query += " AND stream_id = ?"
            params.append(stream)
        if task is not None:
            query += " AND task_id = ?"
            params.append(task)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        if owns_conn:
            conn.close()
