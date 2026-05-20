"""Progress summary commands for Task Copilot CLI."""

from typing import Optional

import typer

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

    from tc.services.progress import get_progress as _get_progress

    db_path = require_db()
    result = _get_progress(stream=stream, db_path=db_path)

    if json:
        output_json(result)
    else:
        statuses = ["pending", "in_progress", "completed", "blocked", "cancelled"]

        # Per-stream table
        table_rows = []
        for entry in result["by_stream"]:
            sid = entry["stream_id"]
            counts = entry["counts"]
            row_dict = {"stream": entry["stream_name"] if entry["stream_name"] else (f"#{sid}" if sid else "unassigned")}
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
        totals = result["totals"]
        print("\nTotals:")
        for s in statuses:
            count = totals.get(s, 0)
            if count:
                print(f"  {s}: {count}")
