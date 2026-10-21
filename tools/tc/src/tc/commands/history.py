"""Archive and history commands: keep tasks.db to current work, keep the past."""

from typing import Optional

import typer

from tc.db.exceptions import TaskNotFound, ValidationError
from tc.formatting import output_json, output_table
from tc.utils.errors import EXIT_NOT_FOUND, EXIT_VALIDATION, error_exit, require_db

history_app = typer.Typer(name="history", help="Archived tasks (.copilot/tasks.db-history).")


def archive_command(
    days: int = typer.Option(14, "--days", help="Archive finished tasks idle at least this many days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would move without moving it."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Move finished tasks (with their log and work products) into the history file."""
    from tc.services.archive import archive

    db_path = require_db()
    try:
        result = archive(days=days, dry_run=dry_run, db_path=db_path)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    if json:
        output_json(result)
        return
    ids = result["task_ids"]
    if not ids:
        print(f"Nothing to archive (no finished tasks idle {days}+ days that live work does not reference).")
    elif dry_run:
        print(f"Would archive {len(ids)} task(s): {', '.join(f'#{i}' for i in ids)}")
    else:
        print(f"Archived {len(ids)} task(s) to {result['history']}")


@history_app.command("list")
def history_list_cmd(
    limit: int = typer.Option(50, "--limit", help="Maximum rows."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List archived tasks, newest first."""
    from tc.services.archive import history_list

    rows = history_list(limit=limit, db_path=require_db())
    output_json(rows) if json else output_table(["id", "title", "status", "agent", "updated_at"], rows, title="History")


@history_app.command("search")
def history_search_cmd(
    query: str = typer.Argument(..., help="Words to match in titles and work products."),
    limit: int = typer.Option(50, "--limit", help="Maximum rows."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Search archived tasks by title and work-product text."""
    from tc.services.archive import history_list

    rows = history_list(query=query, limit=limit, db_path=require_db())
    output_json(rows) if json else output_table(["id", "title", "status", "agent", "updated_at"], rows, title="History")


@history_app.command("get")
def history_get_cmd(
    task_id: int = typer.Argument(..., help="Task ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show an archived task with its activity log and work products."""
    from tc.services.archive import history_get

    try:
        d = history_get(task_id=task_id, db_path=require_db())
    except TaskNotFound as exc:
        error_exit(str(exc), EXIT_NOT_FOUND)
    if json:
        output_json(d)
        return
    for k, v in d.items():
        if k not in ("log", "work_products"):
            print(f"{k}: {v}")
    print(f"log: {len(d['log'])} entries; work_products: {', '.join(f'WP-{w['id']}' for w in d['work_products']) or 'none'}")


@history_app.command("restore")
def history_restore_cmd(
    task_ids: list[int] = typer.Argument(..., help="Task IDs to move back into tasks.db."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Move archived tasks back into the live task list."""
    from tc.services.archive import restore

    try:
        result = restore(task_ids=task_ids, db_path=require_db())
    except (TaskNotFound, ValidationError) as exc:
        error_exit(str(exc), EXIT_NOT_FOUND if isinstance(exc, TaskNotFound) else EXIT_VALIDATION)
    output_json(result) if json else print(f"Restored {len(task_ids)} task(s): {', '.join(f'#{i}' for i in task_ids)}")
