"""Agent handoff commands for Task Copilot CLI."""

import typer

from tc.db.connection import get_db
from tc.formatting import output_json, output_table
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

    if len(context) > 200:
        context = context[:200]

    db_path = require_db()
    conn = get_db(db_path)

    task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task,)).fetchone()
    if task_row is None:
        conn.close()
        error_exit(f"Task #{task} not found", EXIT_NOT_FOUND)

    details = f"{from_agent} -> {to_agent}: {context}"

    # Log the handoff
    conn.execute(
        "INSERT INTO agent_log (agent, stream_id, task_id, action, details) VALUES (?, ?, ?, ?, ?)",
        (from_agent, task_row["stream_id"], task, "handoff", details),
    )

    # Update task's assigned agent
    conn.execute(
        "UPDATE tasks SET agent = ?, updated_at = datetime('now') WHERE id = ?",
        (to_agent, task),
    )
    conn.commit()

    result = {
        "task_id": task,
        "from": from_agent,
        "to": to_agent,
        "context": context,
        "status": "handed_off",
    }

    conn.close()

    if json:
        output_json(result)
    else:
        print(f"Task #{task} handed off from {from_agent} to {to_agent}")
        print(f"Context: {context}")
