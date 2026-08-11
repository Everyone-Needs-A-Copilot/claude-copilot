"""Database connection management for Task Copilot CLI."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from tc import DEFAULT_DB_DIR, DEFAULT_DB_NAME

from .fts5_core import create_content_triggers, create_fts
from .schema import (
    SCHEMA_SQL,
    WP_BASE_ROWID,
    WP_BASE_TABLE,
    WP_FTS_COLUMNS,
    WP_FTS_TABLE,
)

# Tables + column added by the content guard (item 3): the content-guard
# summary token ("clean" | "modified:<pattern-id>[,...]" | "scan_error") for
# whatever guarded text that row carries. There is no migration framework in
# this codebase (schema_version exists but nothing walks it), so this is a
# minimal, idempotent self-healing step run on every connection open rather
# than a one-shot migration: cheap (`PRAGMA table_info` + a guarded `ALTER
# TABLE`), and it means an already-`tc init`'d database from before this
# change gains the column the next time anything opens it, with no separate
# "run this migration" step for the 46 existing projects to remember.
_GUARD_COLUMN_TABLES = ("tasks", "prds", "work_products")


def _ensure_guard_columns(conn: sqlite3.Connection) -> None:
    for table in _GUARD_COLUMN_TABLES:
        try:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.OperationalError:
            # Table doesn't exist yet (e.g. called before executescript on a
            # brand-new file) -- SCHEMA_SQL already defines the column for
            # tables it creates, so there's nothing to backfill here.
            continue
        if columns and "guard" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN guard TEXT")


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
    _ensure_guard_columns(conn)
    conn.commit()
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
