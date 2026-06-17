"""Database connection management for Task Copilot CLI."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from .fts5_core import create_content_triggers, create_fts
from .schema import (
    SCHEMA_SQL,
    WP_BASE_ROWID,
    WP_BASE_TABLE,
    WP_FTS_COLUMNS,
    WP_FTS_TABLE,
)
from tc import DEFAULT_DB_DIR, DEFAULT_DB_NAME


def find_db_path() -> Optional[Path]:
    """Walk up from cwd to find .copilot/tasks.db. Returns Path or None."""
    current = Path.cwd()
    while True:
        candidate = current / DEFAULT_DB_DIR / DEFAULT_DB_NAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            return None
        current = parent


def get_db(path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a configured sqlite3 Connection.

    Args:
        path: Explicit path to database file. If None, uses find_db_path().

    Returns:
        sqlite3.Connection with WAL mode, busy timeout, foreign keys enabled.
    """
    if path is None:
        path = find_db_path()
    if path is None:
        raise FileNotFoundError(
            "No tasks.db found. Run `tc init` to create a database."
        )

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for explicit transaction management.

    Commits on normal exit; rolls back on any exception so the batch is
    all-or-nothing — safer than today's partial-progress across N CLI calls.

    Usage::

        with transaction(conn) as conn:
            create_task(title="...", conn=conn)
            create_task(title="...", conn=conn)
            add_dependency(task_id=..., depends_on=..., conn=conn)
        # committed once here

    Note: ``conn`` is yielded back for ergonomic use in ``with`` blocks, but
    callers may also close it after the block if they hold the only reference.
    """
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(path: Optional[Path] = None) -> Path:
    """Create .copilot/ directory and database with full schema.

    Args:
        path: Explicit path for the database. Defaults to .copilot/tasks.db in cwd.

    Returns:
        Path to the created database.
    """
    if path is None:
        path = Path.cwd() / DEFAULT_DB_DIR / DEFAULT_DB_NAME

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")

    # Base tables, indexes, schema_version row
    conn.executescript(SCHEMA_SQL)

    # FTS5 virtual table + trigger trio via shared fts5_core builders
    # (IF NOT EXISTS — safe on existing databases, no schema_version bump needed)
    create_fts(
        conn,
        WP_FTS_TABLE,
        WP_FTS_COLUMNS,
        content_table=WP_BASE_TABLE,
        content_rowid=WP_BASE_ROWID,
    )
    create_content_triggers(
        conn,
        WP_BASE_TABLE,
        WP_FTS_TABLE,
        WP_FTS_COLUMNS,
        rowid=WP_BASE_ROWID,
    )
    conn.commit()
    conn.close()

    return path
