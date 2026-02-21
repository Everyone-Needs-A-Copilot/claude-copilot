"""Database connection management for Task Copilot CLI."""

import sqlite3
from pathlib import Path
from typing import Optional

from .schema import SCHEMA_SQL
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

    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()

    return path
