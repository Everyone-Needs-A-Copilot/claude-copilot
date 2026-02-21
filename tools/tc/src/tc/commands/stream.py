"""Stream commands for Task Copilot CLI."""

from typing import Optional

import typer

from tc.db.connection import get_db
from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND, EXIT_VALIDATION

stream_app = typer.Typer(name="stream", help="Stream management commands.")


def _row_to_dict(row) -> dict:
    return dict(row)


@stream_app.command("create")
def stream_create(
    name: str = typer.Option(..., "--name", help="Stream name (unique)."),
    prd: int = typer.Option(..., "--prd", help="Associated PRD ID."),
    worktree_path: Optional[str] = typer.Option(None, "--worktree-path", help="Git worktree path."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Create a new stream."""
    db_path = require_db()
    conn = get_db(db_path)

    # Verify PRD exists
    prd_row = conn.execute("SELECT id FROM prds WHERE id = ?", (prd,)).fetchone()
    if prd_row is None:
        conn.close()
        error_exit(f"PRD #{prd} not found", EXIT_NOT_FOUND)

    try:
        cursor = conn.execute(
            "INSERT INTO streams (name, prd_id, worktree_path) VALUES (?, ?, ?)",
            (name, prd, worktree_path),
        )
        conn.commit()
    except Exception as e:
        conn.close()
        if "UNIQUE constraint" in str(e):
            error_exit(f"Stream '{name}' already exists", EXIT_VALIDATION)
        error_exit(str(e))

    stream_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM streams WHERE id = ?", (stream_id,)).fetchone()
    conn.close()

    if json:
        output_json(_row_to_dict(row))
    else:
        print(f"Created stream #{row['id']}: {row['name']}")


@stream_app.command("list")
def stream_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all streams."""
    db_path = require_db()
    conn = get_db(db_path)

    if status:
        rows = conn.execute(
            "SELECT * FROM streams WHERE status = ? ORDER BY id DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM streams ORDER BY id DESC").fetchall()

    conn.close()
    data = [_row_to_dict(r) for r in rows]

    if json:
        output_json(data)
    else:
        output_table(
            ["id", "name", "prd_id", "status", "worktree_path", "created_at"],
            data,
            title="Streams",
        )


@stream_app.command("get")
def stream_get(
    name_or_id: str = typer.Argument(..., help="Stream name or ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get a stream by name or ID."""
    db_path = require_db()
    conn = get_db(db_path)

    # Try numeric ID first
    row = None
    if name_or_id.isdigit():
        row = conn.execute("SELECT * FROM streams WHERE id = ?", (int(name_or_id),)).fetchone()

    if row is None:
        row = conn.execute("SELECT * FROM streams WHERE name = ?", (name_or_id,)).fetchone()

    conn.close()

    if row is None:
        if json:
            output_error_json(f"Stream '{name_or_id}' not found", EXIT_NOT_FOUND)
        error_exit(f"Stream '{name_or_id}' not found", EXIT_NOT_FOUND)

    if json:
        output_json(_row_to_dict(row))
    else:
        d = _row_to_dict(row)
        for k, v in d.items():
            print(f"{k}: {v}")
