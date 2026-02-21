"""Task Copilot CLI - Main entry point."""

from pathlib import Path
from typing import Optional

import typer

from tc import __version__
from tc.commands.prd import prd_app
from tc.commands.stream import stream_app
from tc.commands.task import task_app
from tc.commands.wp import wp_app
from tc.commands.db_cmd import db_app

app = typer.Typer(
    name="tc",
    help="Agent-agnostic task management CLI for AI development workflows.",
    no_args_is_help=True,
)

# Register command groups
app.add_typer(prd_app, name="prd")
app.add_typer(stream_app, name="stream")
app.add_typer(task_app, name="task")
app.add_typer(wp_app, name="wp")
app.add_typer(db_app, name="db")


@app.command("init")
def init(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        help="Directory to initialize in (default: current directory).",
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Initialize a new Task Copilot database in the current directory."""
    from tc.db.connection import init_db
    from tc.formatting import output_json

    target = path or Path.cwd()
    db_file = target / ".copilot" / "tasks.db"

    created = init_db(db_file)

    if json:
        output_json({"status": "initialized", "path": str(created)})
    else:
        print(f"Initialized database at: {created}")


@app.command("version")
def version() -> None:
    """Show the tc version."""
    print(f"tc version {__version__}")


@app.command("progress")
def progress(
    stream: Optional[int] = typer.Option(None, "--stream", help="Filter by stream ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show task progress summary by status per stream and totals."""
    from tc.db.connection import get_db
    from tc.formatting import output_json, output_table
    from tc.utils.errors import require_db

    db_path = require_db()
    conn = get_db(db_path)

    query = """
        SELECT stream_id, status, COUNT(*) as count
        FROM tasks
        WHERE 1=1
    """
    params: list = []
    if stream is not None:
        query += " AND stream_id = ?"
        params.append(stream)
    query += " GROUP BY stream_id, status ORDER BY stream_id, status"

    rows = conn.execute(query, params).fetchall()

    total_query = "SELECT status, COUNT(*) as count FROM tasks"
    total_params: list = []
    if stream is not None:
        total_query += " WHERE stream_id = ?"
        total_params.append(stream)
    total_query += " GROUP BY status"

    total_rows = conn.execute(total_query, total_params).fetchall()
    stream_rows = conn.execute("SELECT id, name FROM streams ORDER BY id").fetchall()
    stream_map = {r["id"]: r["name"] for r in stream_rows}
    conn.close()

    by_stream: dict = {}
    for row in rows:
        sid = row["stream_id"]
        if sid not in by_stream:
            by_stream[sid] = {}
        by_stream[sid][row["status"]] = row["count"]

    totals: dict = {}
    for row in total_rows:
        totals[row["status"]] = row["count"]

    if json:
        result = {
            "by_stream": [
                {
                    "stream_id": sid,
                    "stream_name": stream_map.get(sid, "unassigned"),
                    "counts": counts,
                }
                for sid, counts in by_stream.items()
            ],
            "totals": totals,
        }
        output_json(result)
    else:
        statuses = ["pending", "in_progress", "completed", "blocked", "cancelled"]
        table_rows = []
        for sid, counts in by_stream.items():
            row_dict = {"stream": stream_map.get(sid, f"#{sid}" if sid else "unassigned")}
            for s in statuses:
                row_dict[s] = counts.get(s, 0)
            table_rows.append(row_dict)

        if table_rows:
            output_table(["stream"] + statuses, table_rows, title="Progress by Stream")

        print("\nTotals:")
        for s in statuses:
            count = totals.get(s, 0)
            if count:
                print(f"  {s}: {count}")


@app.command("handoff")
def handoff(
    from_agent: str = typer.Option(..., "--from", help="Handing-off agent."),
    to_agent: str = typer.Option(..., "--to", help="Receiving agent."),
    task: int = typer.Option(..., "--task", help="Task ID being handed off."),
    context: str = typer.Option(..., "--context", help="Handoff context (max 200 chars)."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Log an agent handoff and update the task's assigned agent."""
    from tc.db.connection import get_db
    from tc.formatting import output_json
    from tc.utils.errors import require_db, error_exit, EXIT_NOT_FOUND

    if len(context) > 200:
        context = context[:200]

    db_path = require_db()
    conn = get_db(db_path)

    task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task,)).fetchone()
    if task_row is None:
        conn.close()
        error_exit(f"Task #{task} not found", EXIT_NOT_FOUND)

    details = f"{from_agent} -> {to_agent}: {context}"
    conn.execute(
        "INSERT INTO agent_log (agent, stream_id, task_id, action, details) VALUES (?, ?, ?, ?, ?)",
        (from_agent, task_row["stream_id"], task, "handoff", details),
    )
    conn.execute(
        "UPDATE tasks SET agent = ?, updated_at = datetime('now') WHERE id = ?",
        (to_agent, task),
    )
    conn.commit()
    conn.close()

    result = {
        "task_id": task,
        "from": from_agent,
        "to": to_agent,
        "context": context,
        "status": "handed_off",
    }

    if json:
        output_json(result)
    else:
        print(f"Task #{task} handed off from {from_agent} to {to_agent}")
        print(f"Context: {context}")


@app.command("log")
def log_cmd(
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent."),
    stream: Optional[int] = typer.Option(None, "--stream", help="Filter by stream ID."),
    task: Optional[int] = typer.Option(None, "--task", help="Filter by task ID."),
    limit: int = typer.Option(50, "--limit", help="Maximum entries to return."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List agent activity log entries."""
    from tc.db.connection import get_db
    from tc.formatting import output_json, output_table
    from tc.utils.errors import require_db

    db_path = require_db()
    conn = get_db(db_path)

    query = "SELECT * FROM agent_log WHERE 1=1"
    params: list = []

    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if stream is not None:
        query += " AND stream_id = ?"
        params.append(stream)
    if task is not None:
        query += " AND task_id = ?"
        params.append(task)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    data = [dict(r) for r in rows]

    if json:
        output_json(data)
    else:
        output_table(
            ["id", "agent", "action", "task_id", "stream_id", "details", "created_at"],
            data,
            title="Agent Log",
        )


@app.command("watch")
def watch_cmd(
    refresh: int = typer.Option(5, "--refresh", "-r", help="Refresh interval in seconds."),
    compact: bool = typer.Option(False, "--compact", help="Simplified view without activity log."),
    stream: Optional[int] = typer.Option(None, "--stream", "-s", help="Filter to single stream."),
) -> None:
    """Live dashboard showing task progress, agents, and activity."""
    from tc.commands.watch import watch

    watch(refresh=refresh, compact=compact, stream_filter=stream)


if __name__ == "__main__":
    app()
