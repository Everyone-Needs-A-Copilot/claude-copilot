"""Database connection management for Task Copilot CLI."""

import os
import sqlite3
import subprocess
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


# SQLite's WAL-mode side files are machine-local and change on every
# connection. Left visible they made every tc-using project look dirty, and
# Claude Copilot holds updates for a dirty project. They go in the clone's own
# `.git/info/exclude` (never committed, so no new file to commit in each
# project) rather than the project's `.gitignore`.
_RUNTIME_EXCLUDES = (
    "**/.copilot/*.db-wal",
    "**/.copilot/*.db-shm",
    "**/.copilot/*-journal",
    "**/.copilot/tasks.db-archive-stamp",
)


def _exclude_runtime_files(db_dir: Path) -> None:
    """Best-effort: add the WAL/SHM patterns to the enclosing repo's exclude."""
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--git-path", "info/exclude"),
            cwd=db_dir, capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
        exclude = Path(result.stdout.strip())
        if not exclude.is_absolute():
            exclude = db_dir / exclude
        current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        lines = set(current.splitlines())
        missing = [pattern for pattern in _RUNTIME_EXCLUDES if pattern not in lines]
        if not missing:
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if not current or current.endswith("\n") else "\n"
        with exclude.open("a", encoding="utf-8") as handle:
            handle.write(prefix + "# tc: SQLite runtime files\n" + "".join(f"{p}\n" for p in missing))
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return


def _main_checkout(worktree: Path) -> Optional[Path]:
    """The main checkout of a linked git worktree, or None.

    A linked worktree's `.git` is a file ("gitdir: <repo>/.git/worktrees/<n>"),
    and that directory's `commondir` points at the shared `.git`. Submodules
    also have a `.git` file but no `commondir`, so they are not matched. Pure
    file reads: tc must not shell out to git on every command.
    """
    try:
        text = (worktree / ".git").read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:"):
            return None
        gitdir = Path(text[len("gitdir:"):].strip())
        if not gitdir.is_absolute():
            gitdir = worktree / gitdir
        common = (gitdir / "commondir").read_text(encoding="utf-8").strip()
        common_dir = Path(common) if Path(common).is_absolute() else gitdir / common
        common_dir = common_dir.resolve()
    except (OSError, UnicodeError):
        return None
    if common_dir.name != ".git":
        return None   # bare repository: no main checkout holds a database
    return common_dir.parent


def find_db_path() -> Optional[Path]:
    """Walk up from cwd to find .copilot/tasks.db. Returns Path or None.

    Inside a linked git worktree the task database is the main checkout's,
    so every worktree of a repository shares one task list. A worktree's own
    `.copilot/tasks.db` is only the committed snapshot its branch checked
    out; writing to it would fork the project's tasks. Set
    TC_WORKTREE_DB=local to use the worktree's own copy instead.
    """
    current = Path.cwd()
    local_only = os.environ.get("TC_WORKTREE_DB", "").lower() == "local"
    while True:
        if not local_only and (current / ".git").is_file():
            main = _main_checkout(current)
            if main is not None:
                shared = main / DEFAULT_DB_DIR / DEFAULT_DB_NAME
                if shared.exists():
                    return shared
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

    _exclude_runtime_files(Path(path).parent)
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


def init_db(path: Optional[Path] = None, *, wal: bool = True) -> Path:
    """Create .copilot/ directory and database with full schema.

    Args:
        path: Explicit path for the database. Defaults to .copilot/tasks.db in cwd.
        wal:  WAL journal (the default). The rarely written history file uses a
              rollback journal so it leaves no -wal/-shm files.

    Returns:
        Path to the created database.
    """
    if path is None:
        path = Path.cwd() / DEFAULT_DB_DIR / DEFAULT_DB_NAME

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _exclude_runtime_files(path.parent)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA journal_mode = {'WAL' if wal else 'DELETE'}")
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

    # A project's own task database is committed with the project (tc 2.4
    # standard); the history file created by `tc archive` is not a project root.
    if wal and path.name == DEFAULT_DB_NAME and path.parent.name == DEFAULT_DB_DIR:
        from tc.services.track import ensure_tracked

        try:
            ensure_tracked(path.parent.parent)
        except OSError:
            pass

    return path
