"""tc.services.progress — domain logic for task progress summary.

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


def get_progress(
    *,
    stream: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a progress summary broken down by stream and totals.

    Args:
        stream:  Restrict to a single stream_id.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict::

            {
              "by_stream": [
                  {"stream_id": int|None, "stream_name": str, "counts": {status: count}},
                  ...
              ],
              "totals": {status: count}
            }
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        query = """
            SELECT
                stream_id,
                status,
                COUNT(*) as count
            FROM tasks
            WHERE 1=1
        """
        params: list = []
        if stream is not None:
            query += " AND stream_id = ?"
            params.append(stream)
        query += " GROUP BY stream_id, status ORDER BY stream_id, status"

        rows = conn.execute(query, params).fetchall()

        total_query = "SELECT status, COUNT(*) as count FROM tasks"
        total_params: list = []
        if stream is not None:
            total_query += " WHERE stream_id = ?"
            total_params.append(stream)
        total_query += " GROUP BY status"

        total_rows = conn.execute(total_query, total_params).fetchall()

        stream_rows = conn.execute(
            "SELECT id, name FROM streams ORDER BY id"
        ).fetchall()
        stream_map = {r["id"]: r["name"] for r in stream_rows}

        by_stream: dict = {}
        for row in rows:
            sid = row["stream_id"]
            if sid not in by_stream:
                by_stream[sid] = {}
            by_stream[sid][row["status"]] = row["count"]

        totals: dict = {row["status"]: row["count"] for row in total_rows}

        return {
            "by_stream": [
                {
                    "stream_id": sid,
                    "stream_name": stream_map.get(sid, "unassigned"),
                    "counts": counts,
                }
                for sid, counts in by_stream.items()
            ],
            "totals": totals,
        }
    finally:
        if owns_conn:
            conn.close()
