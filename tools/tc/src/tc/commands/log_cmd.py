"""Agent activity log commands for Task Copilot CLI."""

from typing import Optional

import typer

from tc.formatting import output_json, output_table
from tc.utils.errors import require_db

log_app = typer.Typer(name="log", help="Agent activity log commands.")


@log_app.callback(invoke_without_command=True)
def log_list(
    ctx: typer.Context,
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent."),
    stream: Optional[int] = typer.Option(None, "--stream", help="Filter by stream ID."),
    task: Optional[int] = typer.Option(None, "--task", help="Filter by task ID."),
    limit: int = typer.Option(50, "--limit", help="Maximum entries to return."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List agent activity log entries."""
    if ctx.invoked_subcommand is not None:
        return

    from tc.services.log import list_log as _list_log

    db_path = require_db()
    data = _list_log(
        agent=agent, stream=stream, task=task, limit=limit, db_path=db_path
    )

    if json:
        output_json(data)
    else:
        output_table(
            ["id", "agent", "action", "task_id", "stream_id", "details", "created_at"],
            data,
            title="Agent Log",
        )
