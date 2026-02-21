"""Exit codes and error helpers for Task Copilot CLI."""

import sys
from pathlib import Path
from typing import Optional

import typer

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_NOT_FOUND = 2
EXIT_CONFLICT = 3
EXIT_VALIDATION = 4
EXIT_DB_ERROR = 5


def error_exit(message: str, code: int = EXIT_ERROR) -> None:
    """Print error message to stderr and raise typer.Exit.

    Args:
        message: Human-readable error description.
        code: Exit code (default EXIT_ERROR = 1).
    """
    print(f"Error: {message}", file=sys.stderr)
    raise typer.Exit(code)


def require_db(path: Optional[Path] = None) -> Path:
    """Find the database path or exit with a helpful message.

    Args:
        path: Explicit path override. If None, walks up from cwd.

    Returns:
        Path to the database file.
    """
    from tc.db.connection import find_db_path

    if path is not None:
        resolved = Path(path)
        if not resolved.exists():
            error_exit(
                f"Database not found at {resolved}. Run `tc init` to create it.",
                EXIT_DB_ERROR,
            )
        return resolved

    found = find_db_path()
    if found is None:
        error_exit(
            "No tasks.db found in current directory or any parent directory.\n"
            "Run `tc init` to create a new database in the current directory.",
            EXIT_DB_ERROR,
        )
    return found  # type: ignore[return-value]
