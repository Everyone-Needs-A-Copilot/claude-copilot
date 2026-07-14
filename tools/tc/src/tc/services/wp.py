"""tc.services.wp — domain logic for work product operations.

All functions accept an optional ``conn`` parameter for transaction batching.
This module has ZERO import-time side effects.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import TaskNotFound, ValidationError
from tc.db.fts5_core import fts_match
from tc.db.schema import WP_FTS_COLUMNS, WP_FTS_TABLE


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


def _get_wp_file_dir(db_path: Path) -> Path:
    """Return the work product file directory relative to the .copilot dir."""
    return db_path.parent / "wp"


def store_wp(
    *,
    task_id: Optional[int] = None,
    type_: str,
    title: str,
    content: Optional[str] = None,
    agent: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Store a work product using hybrid inline/file storage.

    Content <= WP_CONTENT_SIZE_THRESHOLD bytes is stored inline in the DB.
    Larger content is written to .copilot/wp/<id>.md and the DB row stores
    the file path (file_path column set, content NULL).

    Args:
        task_id: Associated task ID, or None to store a standalone work
            product not attached to any task. The schema's
            ``work_products.task_id`` column has always been nullable
            (``INTEGER REFERENCES tasks(id)``, no ``NOT NULL``) -- this
            just exposes that existing capability at the service/CLI layer.
            Standalone WPs are the closer-to-the-metal fix for the
            "no task ID exists" externalization-skip gap: an agent invoked
            without a task to attach to previously had no way to store a
            work product at all (`--task` was a required CLI option); now
            it stores one with ``task_id = NULL`` instead of skipping
            storage entirely. Still fully listable/gettable/searchable
            (`tc wp list`, `tc wp get`, `tc wp search`) -- it just doesn't
            join to a task.
        type_:   Work product type string.
        title:   Work product title (required, non-empty).
        content: Work product content (may be None for placeholder rows).
        agent:   Authoring agent slug.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict matching ``tc wp store --json`` output shape.

    Raises:
        ValidationError: if title is empty or type_ is empty.
        TaskNotFound:    if task_id is given but does not exist.
    """
    if not title or not title.strip():
        raise ValidationError("title must not be empty")
    if not type_ or not type_.strip():
        raise ValidationError("type must not be empty")

    from tc import WP_CONTENT_SIZE_THRESHOLD

    owns_conn = conn is None
    resolved_db: Optional[Path] = None

    if owns_conn:
        resolved_db = _require_db_path(db_path)
        conn = _open_conn(resolved_db)
    else:
        # We need db_path for file storage; derive from find_db_path if not given
        if db_path is not None:
            resolved_db = db_path
        else:
            from tc.db.connection import find_db_path

            resolved_db = find_db_path()

    try:
        # Verify task exists -- only when one was given; task_id is None for
        # a standalone work product (no task to verify against).
        if task_id is not None:
            task_row = conn.execute(
                "SELECT id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise TaskNotFound(f"task #{task_id} not found")

        # Hybrid storage decision
        if content and len(content.encode("utf-8")) > WP_CONTENT_SIZE_THRESHOLD:
            # Large content — write file first, then insert DB row so a
            # mid-write failure never leaves a committed row with a missing file.
            if resolved_db is not None:
                wp_dir = _get_wp_file_dir(resolved_db)
                wp_dir.mkdir(parents=True, exist_ok=True)
                # We need the future WP id to name the file; use a temp name
                # then rename after we have the id.
                import tempfile as _tf

                tmp_fd, tmp_path_str = _tf.mkstemp(dir=wp_dir, suffix=".md.tmp")
                try:
                    import os as _os

                    _os.write(tmp_fd, content.encode("utf-8"))
                    _os.close(tmp_fd)
                except Exception:
                    try:
                        import os as _os2

                        _os2.close(tmp_fd)
                    except Exception:
                        pass
                    import os as _os3

                    _os3.unlink(tmp_path_str)
                    raise

                # File is safely on disk — now insert the DB row
                cursor = conn.execute(
                    "INSERT INTO work_products (task_id, type, title, content, file_path, agent)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (task_id, type_, title, None, None, agent),
                )
                wp_id = cursor.lastrowid

                import os as _os4

                final_path = wp_dir / f"{wp_id}.md"
                _os4.rename(tmp_path_str, str(final_path))

                conn.execute(
                    "UPDATE work_products SET file_path = ? WHERE id = ?",
                    (str(final_path), wp_id),
                )
                if owns_conn:
                    conn.commit()
            else:
                # No resolved_db — fall back to inline storage (shouldn't happen
                # in normal usage but keeps the branch safe)
                cursor = conn.execute(
                    "INSERT INTO work_products (task_id, type, title, content, file_path, agent)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (task_id, type_, title, content, None, agent),
                )
                wp_id = cursor.lastrowid
                if owns_conn:
                    conn.commit()

            row = conn.execute(
                "SELECT * FROM work_products WHERE id = ?", (wp_id,)
            ).fetchone()
        else:
            # Normal inline storage
            cursor = conn.execute(
                "INSERT INTO work_products (task_id, type, title, content, file_path, agent)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, type_, title, content, None, agent),
            )
            wp_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM work_products WHERE id = ?", (wp_id,)
            ).fetchone()
            if owns_conn:
                conn.commit()

        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def get_wp(
    *,
    wp_id: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a work product dict by ID, reading file content if stored externally.

    Args:
        wp_id:   Work product ID to fetch.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict with ``content`` populated (read from file if stored externally).

    Raises:
        WorkProductNotFound: if wp_id does not exist.
    """
    from tc.db.exceptions import WorkProductNotFound

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        row = conn.execute(
            "SELECT * FROM work_products WHERE id = ?", (wp_id,)
        ).fetchone()
        if row is None:
            raise WorkProductNotFound(f"work product #{wp_id} not found")

        d = _row_to_dict(row)
        # Read from file if content is stored externally
        if d.get("file_path") and not d.get("content"):
            fp = Path(d["file_path"])
            if fp.exists():
                d["content"] = fp.read_text(encoding="utf-8")
            else:
                d["content"] = f"[File not found: {d['file_path']}]"
        return d
    finally:
        if owns_conn:
            conn.close()


def list_wps(
    *,
    task: Optional[int] = None,
    type_: Optional[str] = None,
    agent: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return a list of work product dicts with optional filters.

    Args:
        task:    Filter by task_id.
        type_:   Filter by type string.
        agent:   Filter by agent slug.
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        List of work product dicts ordered by id DESC.
    """
    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        query = "SELECT * FROM work_products WHERE 1=1"
        params: list = []

        if task is not None:
            query += " AND task_id = ?"
            params.append(task)
        if type_ is not None:
            query += " AND type = ?"
            params.append(type_)
        if agent is not None:
            query += " AND agent = ?"
            params.append(agent)

        query += " ORDER BY id DESC"

        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        if owns_conn:
            conn.close()


def search_wps(
    *,
    query: str,
    limit: int = 10,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Search work products using FTS5 full-text search.

    Args:
        query:   FTS5 MATCH expression.
        limit:   Maximum number of results (default 10).
        conn:    Existing connection for batching; if None, opens own.
        db_path: Explicit DB path; if None, walks up from cwd.

    Returns:
        List of work product dicts (with ``snippet`` field) ordered by rank.

    Raises:
        DatabaseError: if the FTS query is malformed.
    """
    from tc.db.exceptions import DatabaseError

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    try:
        # content column is index 1 in WP_FTS_COLUMNS: ["title", "content", "type", "agent"]
        content_col_idx = WP_FTS_COLUMNS.index("content")
        rows = fts_match(
            conn,
            WP_FTS_TABLE,
            query,
            select="wp.*",
            join="JOIN work_products wp ON wp.id = work_products_fts.rowid",
            limit=limit,
            snippet_col=content_col_idx,
        )
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        raise DatabaseError(f"search error: {exc}") from exc
    finally:
        if owns_conn:
            conn.close()
