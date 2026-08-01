"""PRD (Product Requirements Document) commands for Task Copilot CLI."""

from pathlib import Path
from typing import Optional

import typer

from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND, EXIT_VALIDATION
from tc.db.exceptions import ValidationError

prd_app = typer.Typer(name="prd", help="PRD management commands.")


@prd_app.command("create")
def prd_create(
    title: str = typer.Option(..., "--title", help="PRD title."),
    description: Optional[str] = typer.Option(
        None, "--description", help="Short description."
    ),
    content: Optional[str] = typer.Option(None, "--content", help="Full PRD content."),
    file: Optional[Path] = typer.Option(None, "--file", help="Read content from file."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Create a new PRD."""
    from tc.services.prds import create_prd as _create_prd

    if file is not None:
        if not file.exists():
            error_exit(f"File not found: {file}", EXIT_VALIDATION)
        content = file.read_text(encoding="utf-8")

    db_path = require_db()
    try:
        row = _create_prd(
            title=title,
            description=description,
            content=content,
            db_path=db_path,
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(row)
    else:
        print(f"Created PRD #{row['id']}: {row['title']}")


@prd_app.command("list")
def prd_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all PRDs."""
    from tc.services.prds import list_prds as _list_prds

    db_path = require_db()
    try:
        data = _list_prds(status=status, db_path=db_path)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

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
    from tc.services.prds import get_prd as _get_prd
    from tc.db.exceptions import PrdNotFound

    db_path = require_db()
    try:
        d = _get_prd(prd_id=prd_id, db_path=db_path)
    except PrdNotFound:
        if json:
            output_error_json(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)
        error_exit(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)

    if json:
        output_json(d)
    else:
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
    from tc.services.prds import update_prd as _update_prd
    from tc.db.exceptions import PrdNotFound

    if file is not None:
        if not file.exists():
            error_exit(f"File not found: {file}", EXIT_VALIDATION)
        content = file.read_text(encoding="utf-8")

    db_path = require_db()
    try:
        row = _update_prd(
            prd_id=prd_id,
            title=title,
            status=status,
            content=content,
            db_path=db_path,
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except PrdNotFound:
        if json:
            output_error_json(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)
        error_exit(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)

    if json:
        output_json(row)
    else:
        if title is None and status is None and content is None and file is None:
            print("Nothing to update.")
        else:
            print(f"Updated PRD #{row['id']}: {row['title']}")
