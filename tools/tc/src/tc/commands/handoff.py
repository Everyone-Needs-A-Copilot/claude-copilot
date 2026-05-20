"""Agent handoff commands for Task Copilot CLI."""

import typer

from tc.formatting import output_json
from tc.utils.errors import error_exit, require_db, EXIT_NOT_FOUND

handoff_app = typer.Typer(name="handoff", help="Agent handoff commands.")


@handoff_app.callback(invoke_without_command=True)
def handoff(
    ctx: typer.Context,
    from_agent: str = typer.Option(..., "--from", help="Handing-off agent."),
    to_agent: str = typer.Option(..., "--to", help="Receiving agent."),
    task: int = typer.Option(..., "--task", help="Task ID being handed off."),
    context: str = typer.Option(..., "--context", help="Handoff context (max 200 chars)."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Log a handoff between agents and update the task's assigned agent."""
    if ctx.invoked_subcommand is not None:
        return

    from tc.services.handoff import handoff_task as _handoff_task
    from tc.db.exceptions import TaskNotFound

    db_path = require_db()
    try:
        result = _handoff_task(
            task_id=task,
            from_agent=from_agent,
            to_agent=to_agent,
            context=context,
            db_path=db_path,
        )
    except TaskNotFound:
        error_exit(f"Task #{task} not found", EXIT_NOT_FOUND)

    if json:
        output_json(result)
    else:
        print(f"Task #{task} handed off from {from_agent} to {to_agent}")
        print(f"Context: {result['context']}")
