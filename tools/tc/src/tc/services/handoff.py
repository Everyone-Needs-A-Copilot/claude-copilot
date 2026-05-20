"""tc.services.handoff — domain logic for agent handoff operations.

All functions accept an optional ``conn`` parameter for transaction batching.
This module has ZERO import-time side effects.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import TaskNotFound


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


def handoff_task(
    *,
    task_id: int,
    from_agent: str,
    to_agent: str,
    context: str,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Log a handoff between agents and update the task's assigned agent.

    The ``context`` string is silently truncated to 200 characters to match
    CLI behaviour.

    Args:
        task_id:    Task being handed off.
        from_agent: Agent handing off the task.
        to_agent:   Agent receiving the task.
        context:    Handoff context (max 200 chars).
        conn:       Existing connection for batching; if None, opens own.
        db_path:    Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict ``{"task_id", "from", "to", "context", "status": "handed_off"}``.

    Raises:
        TaskNotFound: if task_id does not exist.
    """
    context = context[:200]

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task_row is None:
            raise TaskNotFound(f"task #{task_id} not found")

        details = f"{from_agent} -> {to_agent}: {context}"

        conn.execute(
            "INSERT INTO agent_log (agent, stream_id, task_id, action, details)"
            " VALUES (?, ?, ?, ?, ?)",
            (from_agent, task_row["stream_id"], task_id, "handoff", details),
        )

        conn.execute(
            "UPDATE tasks SET agent = ?, updated_at = datetime('now') WHERE id = ?",
            (to_agent, task_id),
        )

        if owns_conn:
            conn.commit()

        return {
            "task_id": task_id,
            "from": from_agent,
            "to": to_agent,
            "context": context,
            "status": "handed_off",
        }
    finally:
        if owns_conn:
            conn.close()
