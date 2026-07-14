"""tc.services.upkeep — domain logic for maintenance-session tagging (O-9,
Phase 4 outcome program, "the upkeep tax").

O-9 asks: what share of ecosystem effort is spent MAINTAINING the CSE
itself (registry, links, freshness, parity sweeps, claim upkeep) rather
than producing solutions -- netted against the value delivered. This
module implements the tagging primitive two ways, both additive and both
registered under claims.yaml definitions.upkeep_tax:

  - EXACT, per-task/per-session (tag_task): a person or agent explicitly
    marks ONE task as upkeep work. If this call is running inside a live
    Claude Code session (CLAUDE_CODE_SESSION_ID set), it also appends a
    row to upkeep_sessions -- the same session-touch mechanism
    tc.services.solutions._record_session_touch uses for solution_sessions
    -- so cse-bench's upkeep collector can independently sum that
    session's own transcript token usage. This is prospective by
    construction: it only ever captures sessions from the moment this
    feature exists onward.
  - HEURISTIC, per-PRD (tag_prd): a person or agent marks an ENTIRE PRD,
    once, as maintenance-producing. Every task already filed under that
    PRD -- created before this feature existed, no less -- is bulk-tagged
    in the same call (method='prd-heuristic'). This is what makes the
    upkeep tax computable from task/PRD data that ALREADY EXISTS, not
    only from now on: no one had to tag anything as it happened. It is
    coarser than tag_task (task-count, not token-exact -- see
    claims.yaml definitions.upkeep_tax for the honest limitation) and
    never overrides a task someone has explicitly tagged (an existing
    method='explicit' row wins; see _bulk_tag_prd_tasks).

Every dict this module returns carries the storage-layer flat fields. All
functions accept an optional ``conn`` parameter (batching pattern shared
with tc.services.tasks/solutions) and call ensure_upkeep_schema() on every
connection they touch -- the lazy-migration path so pre-existing tasks.db
stores never need a manual migration step.

This module has ZERO import-time side effects -- no DB opened, no env read.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import PrdNotFound, TaskNotFound, ValidationError

# Same env var tc.services.solutions._record_session_touch keys off of --
# see that module's docstring for provenance.
_SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"

_VALID_KINDS = {"framework", "knowledge", "cli", "registry", "other"}


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


def _resolve_conn(
    conn: Optional[sqlite3.Connection], db_path: Optional[Path]
) -> tuple[sqlite3.Connection, bool]:
    """Resolve a usable connection and whether this call owns it. Ensures
    the upkeep tables exist on whatever connection is returned -- see
    module docstring."""
    from tc.db.connection import ensure_upkeep_schema

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    ensure_upkeep_schema(conn)
    return conn, owns_conn


def _validate_kind(kind: str) -> str:
    if kind not in _VALID_KINDS:
        raise ValidationError(
            f"invalid kind '{kind}'. Must be one of: {', '.join(sorted(_VALID_KINDS))}"
        )
    return kind


def _require_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise TaskNotFound(f"task #{task_id} not found")
    return row


def _require_prd(conn: sqlite3.Connection, prd_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
    if row is None:
        raise PrdNotFound(f"PRD #{prd_id} not found")
    return row


def _record_upkeep_session_touch(
    conn: sqlite3.Connection, task_id: int, kind: str
) -> None:
    """Append an upkeep_sessions row when this call is running inside a
    live Claude Code session -- mirrors
    tc.services.solutions._record_session_touch exactly. A no-op
    otherwise; absence of a session id is the honest no-signal state, not
    an error."""
    session_id = os.environ.get(_SESSION_ID_ENV)
    if not session_id:
        return
    conn.execute(
        """INSERT INTO upkeep_sessions (task_id, session_id, repo_path, kind)
           VALUES (?, ?, ?, ?)""",
        (task_id, session_id, os.getcwd(), kind),
    )


def tag_task(
    *,
    task_id: int,
    kind: str = "other",
    note: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Explicitly tag ONE task as upkeep work (method='explicit').

    Idempotent and authoritative: calling this again re-tags the same task
    (kind/note/tagged_at updated) and always wins over a prior
    method='prd-heuristic' row from `tag_prd` -- an explicit human/agent
    judgment about a specific task outranks a PRD-wide sweep.

    Raises:
        TaskNotFound:    if task_id does not exist.
        ValidationError: on an unrecognised kind.
    """
    _validate_kind(kind)

    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        _require_task(conn, task_id)

        conn.execute(
            """INSERT INTO upkeep_tags (task_id, kind, method, note)
               VALUES (?, ?, 'explicit', ?)
               ON CONFLICT(task_id) DO UPDATE SET
                   kind = excluded.kind,
                   method = 'explicit',
                   note = excluded.note,
                   tagged_at = datetime('now')""",
            (task_id, kind, note),
        )
        _record_upkeep_session_touch(conn, task_id, kind)

        if owns_conn:
            conn.commit()

        row = conn.execute(
            "SELECT * FROM upkeep_tags WHERE task_id = ?", (task_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def tag_prd(
    *,
    prd_id: int,
    kind: str = "other",
    note: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Flag an entire PRD as maintenance-producing, and bulk-tag every
    task currently filed under it (method='prd-heuristic') -- the
    retrospective-computability path (see module docstring).

    Never overwrites a task's method='explicit' tag: only tasks with no
    tag yet, or with an existing method='prd-heuristic' tag, are
    (re-)written by the sweep.

    Idempotent: safe to re-run as new tasks land under an already-flagged
    PRD -- it only ever adds/refreshes prd-heuristic rows, never removes
    an explicit one.

    Raises:
        PrdNotFound:     if prd_id does not exist.
        ValidationError: on an unrecognised kind.
    """
    _validate_kind(kind)

    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        _require_prd(conn, prd_id)

        conn.execute(
            """INSERT INTO prd_upkeep_flags (prd_id, kind, note)
               VALUES (?, ?, ?)
               ON CONFLICT(prd_id) DO UPDATE SET
                   kind = excluded.kind,
                   note = excluded.note,
                   flagged_at = datetime('now')""",
            (prd_id, kind, note),
        )

        task_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM tasks WHERE prd_id = ?", (prd_id,)
            ).fetchall()
        ]
        for tid in task_ids:
            conn.execute(
                """INSERT INTO upkeep_tags (task_id, kind, method, note)
                   VALUES (?, ?, 'prd-heuristic', ?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       kind = excluded.kind,
                       note = excluded.note,
                       tagged_at = datetime('now')
                   WHERE method = 'prd-heuristic'""",
                (tid, kind, note),
            )

        if owns_conn:
            conn.commit()

        flag_row = conn.execute(
            "SELECT * FROM prd_upkeep_flags WHERE prd_id = ?", (prd_id,)
        ).fetchone()
        tagged_count = conn.execute(
            """SELECT COUNT(*) AS n FROM upkeep_tags
               WHERE task_id IN (SELECT id FROM tasks WHERE prd_id = ?)""",
            (prd_id,),
        ).fetchone()["n"]

        result = _row_to_dict(flag_row)
        result["tasks_under_prd"] = len(task_ids)
        result["tasks_tagged"] = tagged_count
        return result
    finally:
        if owns_conn:
            conn.close()


def list_upkeep(
    *,
    kind: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return every tagged task, joined with its title/status/prd_id, most
    recently tagged first.

    Raises:
        ValidationError: if kind is not a recognised kind string.
    """
    if kind is not None:
        _validate_kind(kind)

    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        query = """
            SELECT ut.task_id, ut.kind, ut.method, ut.note, ut.tagged_at,
                   t.title, t.status, t.prd_id
            FROM upkeep_tags ut
            JOIN tasks t ON t.id = ut.task_id
        """
        params: list = []
        if kind is not None:
            query += " WHERE ut.kind = ?"
            params.append(kind)
        query += " ORDER BY ut.tagged_at DESC"

        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        if owns_conn:
            conn.close()


def summary(
    *,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Aggregate view of this store's upkeep tagging: the task-count
    heuristic share, a by-kind/by-method breakdown, PRDs flagged, and
    distinct sessions captured by the exact method. See claims.yaml
    definitions.upkeep_tax -- this is the same computation cse-bench's
    upkeep collector performs, exposed here for ad-hoc inspection.
    """
    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        total_tasks = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
        upkeep_tasks = conn.execute(
            "SELECT COUNT(*) AS n FROM upkeep_tags"
        ).fetchone()["n"]

        by_kind = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM upkeep_tags GROUP BY kind"
            ).fetchall()
        }
        by_method = {
            r["method"]: r["n"]
            for r in conn.execute(
                "SELECT method, COUNT(*) AS n FROM upkeep_tags GROUP BY method"
            ).fetchall()
        }
        prds_flagged = conn.execute(
            "SELECT COUNT(*) AS n FROM prd_upkeep_flags"
        ).fetchone()["n"]
        distinct_sessions = conn.execute(
            "SELECT COUNT(DISTINCT session_id) AS n FROM upkeep_sessions"
        ).fetchone()["n"]

        return {
            "total_tasks": total_tasks,
            "upkeep_tasks": upkeep_tasks,
            "task_count_share": (upkeep_tasks / total_tasks) if total_tasks else None,
            "by_kind": by_kind,
            "by_method": by_method,
            "prds_flagged": prds_flagged,
            "sessions_tagged": distinct_sessions,
        }
    finally:
        if owns_conn:
            conn.close()
