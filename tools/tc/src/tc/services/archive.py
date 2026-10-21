"""tc.services.archive — move finished work out of tasks.db into a history file.

The live database keeps current work; finished tasks older than a cutoff move,
with their activity log, work products and dependency rows, into
``.copilot/tasks.db-history`` next to it. That file has the same schema, so the
history stays complete and searchable, and nothing is ever deleted: a moved
task can be restored. Task IDs are not reused (tasks.id is AUTOINCREMENT), so a
TASK-n in old notes still resolves, in one file or the other.

A finished task stays live while any task left in tasks.db still points at it
(as parent, or as a dependency), so live work never references something that
has moved.

The history file uses a rollback journal rather than WAL: it is written rarely,
and this leaves no -wal/-shm files beside it. Because tasks.db is in WAL mode a
transaction across both files is not atomic, so every move copies first
(INSERT OR REPLACE, committed) and deletes second. An interruption between the
two leaves rows in both files, which the next run reconciles.

This module has ZERO import-time side effects.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import TaskNotFound, ValidationError

HISTORY_SUFFIX = "-history"
DEFAULT_ARCHIVE_DAYS = 14
_STAMP_SUFFIX = "-archive-stamp"
_AUTO_INTERVAL_SECONDS = 24 * 3600

# Moved for each task, children before parents so deletes never orphan a row.
_TASK_OWNED = (
    ("task_dependencies", "task_id"),
    ("agent_log", "task_id"),
    ("work_products", "task_id"),
)


def history_path(db_path: Path) -> Path:
    return Path(str(db_path) + HISTORY_SUFFIX)


def _require_db_path(db_path: Optional[Path]) -> Path:
    if db_path is not None:
        return Path(db_path)
    from tc.db.connection import find_db_path

    found = find_db_path()
    if found is None:
        raise FileNotFoundError("No tasks.db found. Run `tc init` to create a database.")
    return found


def _ensure_history(db_path: Path) -> Path:
    """Create the history file if needed, with the same columns as tasks.db."""
    from tc.db.connection import _ensure_guard_columns, init_db

    path = history_path(db_path)
    if not path.exists():
        init_db(path, wal=False)
    conn = sqlite3.connect(str(path))
    try:
        _ensure_guard_columns(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _open_pair(db_path: Path, create: bool) -> Optional[sqlite3.Connection]:
    """A connection to tasks.db with the history file attached as ``h``.

    Foreign keys are off on this connection: history rows may point at a
    parent or PRD that is still live, and the live side is guarded by the
    reference closure in ``archivable_ids`` instead.
    """
    from tc.db.connection import get_db

    hist = _ensure_history(db_path) if create else history_path(db_path)
    if not hist.exists():
        return None
    conn = get_db(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ATTACH DATABASE ? AS h", (str(hist),))
    return conn


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _copy(conn: sqlite3.Connection, src: str, dst: str, table: str, where: str, params: list) -> int:
    cols = [c for c in _columns(conn, src, table) if c in set(_columns(conn, dst, table))]
    col_list = ", ".join(cols)
    cur = conn.execute(
        f"INSERT OR REPLACE INTO {dst}.{table} ({col_list}) SELECT {col_list} FROM {src}.{table} WHERE {where}",
        params,
    )
    return cur.rowcount


def _in(ids: list[int]) -> str:
    return "(" + ",".join("?" * len(ids)) + ")"


def archivable_ids(conn: sqlite3.Connection, days: int) -> list[int]:
    """Finished tasks idle for ``days`` days that nothing staying live points at."""
    cutoff = conn.execute("SELECT datetime('now', ?)", (f"-{days} days",)).fetchone()[0]
    candidates = {
        r[0]
        for r in conn.execute(
            """
            SELECT t.id FROM tasks t
            WHERE t.status IN ('completed', 'cancelled')
              AND MAX(t.updated_at, COALESCE(
                    (SELECT MAX(created_at) FROM agent_log WHERE task_id = t.id), '')) <= ?
            """,
            (cutoff,),
        )
    }
    parent_of = [(r[0], r[1]) for r in conn.execute(
        "SELECT id, parent_task_id FROM tasks WHERE parent_task_id IS NOT NULL")]
    depends = [(r[0], r[1]) for r in conn.execute("SELECT task_id, depends_on FROM task_dependencies")]
    # Drop any candidate referenced by a task that stays; repeat until stable,
    # since dropping one can make its own parent or dependency stay too.
    changed = True
    while changed:
        changed = False
        for child, parent in parent_of:
            if parent in candidates and child not in candidates:
                candidates.discard(parent)
                changed = True
        for task, dep in depends:
            if dep in candidates and task not in candidates:
                candidates.discard(dep)
                changed = True
    return sorted(candidates)


def _move(conn: sqlite3.Connection, src: str, dst: str, ids: list[int]) -> dict[str, int]:
    """Copy tasks ``ids`` and everything they own from src to dst, then delete from src."""
    counts: dict[str, int] = {}
    where = f"id IN {_in(ids)}"
    # Copy, committed, before any delete.
    conn.execute("BEGIN IMMEDIATE")
    for table, ref in (("prds", "id"), ("streams", "id")):
        fk = "prd_id" if table == "prds" else "stream_id"
        _copy(conn, src, dst, table,
              f"{ref} IN (SELECT {fk} FROM {src}.tasks WHERE {where} AND {fk} IS NOT NULL)"
              f" AND {ref} NOT IN (SELECT {ref} FROM {dst}.{table})", ids)
    counts["tasks"] = _copy(conn, src, dst, "tasks", where, ids)
    for table, col in _TASK_OWNED:
        counts[table] = _copy(conn, src, dst, table, f"{col} IN {_in(ids)}", ids)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    for table, col in _TASK_OWNED:
        conn.execute(f"DELETE FROM {src}.{table} WHERE {col} IN {_in(ids)}", ids)
    conn.execute(f"DELETE FROM {src}.tasks WHERE {where}", ids)
    conn.commit()
    return counts


def archive(
    *,
    days: int = DEFAULT_ARCHIVE_DAYS,
    dry_run: bool = False,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Move finished tasks idle for ``days`` days into the history file."""
    if days < 0:
        raise ValidationError("days must be >= 0")
    db_path = _require_db_path(db_path)
    from tc.db.connection import get_db

    probe = get_db(db_path)
    try:
        ids = archivable_ids(probe, days)
    finally:
        probe.close()
    result: dict[str, Any] = {
        "days": days, "dry_run": dry_run, "task_ids": ids, "history": str(history_path(db_path)), "moved": {},
    }
    if dry_run or not ids:
        return result
    conn = _open_pair(db_path, create=True)
    try:
        result["moved"] = _move(conn, "main", "h", ids)
    finally:
        conn.close()
    return result


def restore(*, task_ids: list[int], db_path: Optional[Path] = None) -> dict[str, Any]:
    """Move archived tasks back into tasks.db."""
    if not task_ids:
        raise ValidationError("no task IDs given")
    db_path = _require_db_path(db_path)
    conn = _open_pair(db_path, create=False)
    if conn is None:
        raise TaskNotFound("no history file; nothing has been archived")
    try:
        found = {r[0] for r in conn.execute(f"SELECT id FROM h.tasks WHERE id IN {_in(task_ids)}", task_ids)}
        missing = [i for i in task_ids if i not in found]
        if missing:
            raise TaskNotFound(f"not in history: {', '.join(f'#{i}' for i in missing)}")
        moved = _move(conn, "h", "main", list(task_ids))
    finally:
        conn.close()
    return {"task_ids": list(task_ids), "moved": moved}


def history_list(
    *,
    query: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Archived tasks, newest first. ``query`` matches titles and work products."""
    db_path = _require_db_path(db_path)
    hist = history_path(db_path)
    if not hist.exists():
        return []
    conn = sqlite3.connect(f"file:{hist}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT id, title, status, agent, prd_id, updated_at FROM tasks"
        params: list = []
        if query:
            sql += """ WHERE title LIKE ? OR id IN (
                SELECT task_id FROM work_products WHERE id IN (
                    SELECT rowid FROM work_products_fts WHERE work_products_fts MATCH ?))"""
            params = [f"%{query}%", _fts_query(query)]
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def history_get(*, task_id: int, db_path: Optional[Path] = None) -> dict[str, Any]:
    """One archived task with its log and work-product summaries."""
    db_path = _require_db_path(db_path)
    hist = history_path(db_path)
    if not hist.exists():
        raise TaskNotFound(f"task #{task_id} is not in history")
    conn = sqlite3.connect(f"file:{hist}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(f"task #{task_id} is not in history")
        d = dict(row)
        d["log"] = [dict(r) for r in conn.execute(
            "SELECT * FROM agent_log WHERE task_id = ? ORDER BY id", (task_id,))]
        d["work_products"] = [dict(r) for r in conn.execute(
            "SELECT id, type, title, agent, file_path, created_at FROM work_products WHERE task_id = ? ORDER BY id",
            (task_id,))]
        return d
    finally:
        conn.close()


def _fts_query(text: str) -> str:
    """Quote each word so user text is never parsed as FTS5 syntax."""
    return " ".join('"' + w.replace('"', '""') + '"' for w in text.split()) or '""'


def maybe_auto_archive(db_path: Optional[Path]) -> None:
    """Archive at most once a day after a writing command. Never raises.

    Off with TC_AUTO_ARCHIVE=0; the age cutoff is TC_ARCHIVE_DAYS (default 14).
    """
    if os.environ.get("TC_AUTO_ARCHIVE", "1") == "0" or db_path is None:
        return
    try:
        stamp = Path(str(db_path) + _STAMP_SUFFIX)
        if stamp.exists() and time.time() - stamp.stat().st_mtime < _AUTO_INTERVAL_SECONDS:
            return
        stamp.touch()
        archive(days=int(os.environ.get("TC_ARCHIVE_DAYS", DEFAULT_ARCHIVE_DAYS)), db_path=Path(db_path))
    except Exception:
        return
