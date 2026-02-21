"""Progress summary commands for Task Copilot CLI."""

from typing import Optional

import typer

from tc.db.connection import get_db
from tc.formatting import output_json, output_table
from tc.utils.errors import require_db

progress_app = typer.Typer(name="progress", help="Progress summary commands.")


@progress_app.callback(invoke_without_command=True)
def progress_summary(
    ctx: typer.Context,
    stream: Optional[int] = typer.Option(None, "--stream", help="Filter by stream ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show task progress summary by status per stream and totals."""
    if ctx.invoked_subcommand is not None:
        return

    db_path = require_db()
    conn = get_db(db_path)

    query = """
        SELECT
            stream_id,
            status,
            COUNT(*) as count
        FROM tasks
        WHERE 1=1
    """
    params: list = []
    if stream is not None:
        query += " AND stream_id = ?"
        params.append(stream)

    query += " GROUP BY stream_id, status ORDER BY stream_id, status"

    rows = conn.execute(query, params).fetchall()

    # Build totals
    total_query = "SELECT status, COUNT(*) as count FROM tasks"
    total_params: list = []
    if stream is not None:
        total_query += " WHERE stream_id = ?"
        total_params.append(stream)
    total_query += " GROUP BY status"

    total_rows = conn.execute(total_query, total_params).fetchall()

    # Stream info
    stream_rows = conn.execute("SELECT id, name FROM streams ORDER BY id").fetchall()
    stream_map = {r["id"]: r["name"] for r in stream_rows}

    conn.close()

    # Organize by stream
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

        # Per-stream table
        table_rows = []
        for sid, counts in by_stream.items():
            row_dict = {"stream": stream_map.get(sid, f"#{sid}" if sid else "unassigned")}
            for s in statuses:
                row_dict[s] = counts.get(s, 0)
            table_rows.append(row_dict)

        if table_rows:
            output_table(
                ["stream"] + statuses,
                table_rows,
                title="Progress by Stream",
            )

        # Totals
        print("\nTotals:")
        for s in statuses:
            count = totals.get(s, 0)
            if count:
                print(f"  {s}: {count}")
