"""PRD (Product Requirements Document) commands for Task Copilot CLI."""

from pathlib import Path
from typing import Optional

import typer

from tc.db.connection import get_db
from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND, EXIT_VALIDATION

prd_app = typer.Typer(name="prd", help="PRD management commands.")


def _row_to_dict(row) -> dict:
    return dict(row)


@prd_app.command("create")
def prd_create(
    title: str = typer.Option(..., "--title", help="PRD title."),
    description: Optional[str] = typer.Option(None, "--description", help="Short description."),
    content: Optional[str] = typer.Option(None, "--content", help="Full PRD content."),
    file: Optional[Path] = typer.Option(None, "--file", help="Read content from file."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Create a new PRD."""
    if file is not None:
        if not file.exists():
            error_exit(f"File not found: {file}", EXIT_VALIDATION)
        content = file.read_text(encoding="utf-8")

    db_path = require_db()
    conn = get_db(db_path)

    cursor = conn.execute(
        "INSERT INTO prds (title, description, content) VALUES (?, ?, ?)",
        (title, description, content),
    )
    conn.commit()
    prd_id = cursor.lastrowid

    row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
    conn.close()

    if json:
        output_json(_row_to_dict(row))
    else:
        print(f"Created PRD #{row['id']}: {row['title']}")


@prd_app.command("list")
def prd_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all PRDs."""
    db_path = require_db()
    conn = get_db(db_path)

    if status:
        rows = conn.execute(
            "SELECT * FROM prds WHERE status = ? ORDER BY id DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM prds ORDER BY id DESC").fetchall()

    conn.close()

    data = [_row_to_dict(r) for r in rows]

    if json:
        output_json(data)
    else:
        output_table(
            ["id", "title", "status", "created_at"],
            data,
            title="PRDs",
        )


@prd_app.command("get")
def prd_get(
    prd_id: int = typer.Argument(..., help="PRD ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get a PRD by ID."""
    db_path = require_db()
    conn = get_db(db_path)

    row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
    conn.close()

    if row is None:
        if json:
            output_error_json(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)
        error_exit(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)

    if json:
        output_json(_row_to_dict(row))
    else:
        d = _row_to_dict(row)
        for k, v in d.items():
            print(f"{k}: {v}")


@prd_app.command("update")
def prd_update(
    prd_id: int = typer.Argument(..., help="PRD ID."),
    title: Optional[str] = typer.Option(None, "--title", help="New title."),
    status: Optional[str] = typer.Option(None, "--status", help="New status."),
    content: Optional[str] = typer.Option(None, "--content", help="New content."),
    file: Optional[Path] = typer.Option(None, "--file", help="Read content from file."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Update a PRD."""
    if file is not None:
        if not file.exists():
            error_exit(f"File not found: {file}", EXIT_VALIDATION)
        content = file.read_text(encoding="utf-8")

    valid_statuses = {"active", "completed", "archived"}
    if status and status not in valid_statuses:
        error_exit(f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}", EXIT_VALIDATION)

    db_path = require_db()
    conn = get_db(db_path)

    row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
    if row is None:
        conn.close()
        if json:
            output_error_json(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)
        error_exit(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)

    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if content is not None:
        updates.append("content = ?")
        params.append(content)

    if not updates:
        conn.close()
        if json:
            output_json(_row_to_dict(row))
        else:
            print("Nothing to update.")
        return

    updates.append("updated_at = datetime('now')")
    params.append(prd_id)
    conn.execute(f"UPDATE prds SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()

    row = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,)).fetchone()
    conn.close()

    if json:
        output_json(_row_to_dict(row))
    else:
        print(f"Updated PRD #{row['id']}: {row['title']}")
