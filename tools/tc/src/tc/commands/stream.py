"""Stream commands for Task Copilot CLI."""

from typing import Optional

import typer

from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND, EXIT_VALIDATION
from tc.db.exceptions import ConflictError, PrdNotFound

stream_app = typer.Typer(name="stream", help="Stream management commands.")


@stream_app.command("create")
def stream_create(
    name: str = typer.Option(..., "--name", help="Stream name (unique)."),
    prd: int = typer.Option(..., "--prd", help="Associated PRD ID."),
    worktree_path: Optional[str] = typer.Option(
        None, "--worktree-path", help="Git worktree path."
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Create a new stream."""
    from tc.services.streams import create_stream as _create_stream

    db_path = require_db()
    try:
        row = _create_stream(
            name=name, prd=prd, worktree_path=worktree_path, db_path=db_path
        )
    except PrdNotFound:
        error_exit(f"PRD #{prd} not found", EXIT_NOT_FOUND)
    except ConflictError:
        error_exit(f"Stream '{name}' already exists", EXIT_VALIDATION)

    if json:
        output_json(row)
    else:
        print(f"Created stream #{row['id']}: {row['name']}")


@stream_app.command("list")
def stream_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all streams."""
    from tc.services.streams import list_streams as _list_streams

    db_path = require_db()
    data = _list_streams(status=status, db_path=db_path)

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
    from tc.services.streams import get_stream as _get_stream, StreamNotFound

    db_path = require_db()
    try:
        d = _get_stream(name_or_id=name_or_id, db_path=db_path)
    except StreamNotFound:
        if json:
            output_error_json(f"Stream '{name_or_id}' not found", EXIT_NOT_FOUND)
        error_exit(f"Stream '{name_or_id}' not found", EXIT_NOT_FOUND)

    if json:
        output_json(d)
    else:
        for k, v in d.items():
            print(f"{k}: {v}")


@stream_app.command("conflicts")
def stream_conflicts(
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Find files claimed by more than one active/paused stream's tasks.

    Reads each stream's tasks' `metadata.files` (written by `/orchestrate
    generate`) and reports any file more than one stream claims. Exits
    non-zero when a conflict is found so `/orchestrate start` can use this as
    a hard precondition before creating worktrees for parallel streams.
    """
    from tc.services.streams import find_conflicts as _find_conflicts

    db_path = require_db()
    conflicts = _find_conflicts(db_path=db_path)

    if json:
        output_json(conflicts)
    else:
        if not conflicts:
            print("No file conflicts between streams.")
        else:
            for c in conflicts:
                names = ", ".join(f"{s['name']} (#{s['id']})" for s in c["streams"])
                print(f"CONFLICT: {c['file']} claimed by {names}")

    if conflicts:
        raise typer.Exit(1)
