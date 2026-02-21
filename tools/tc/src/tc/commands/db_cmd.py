"""Database management commands for Task Copilot CLI."""

from pathlib import Path
from typing import Optional

import typer

from tc.db.connection import init_db, find_db_path, get_db
from tc.formatting import output_json, output_table
from tc.utils.errors import error_exit, require_db, EXIT_DB_ERROR

db_app = typer.Typer(name="db", help="Database management commands.")


@db_app.command("path")
def db_path() -> None:
    """Print the path to the current database."""
    found = find_db_path()
    if found is None:
        error_exit(
            "No tasks.db found. Run `tc init` to create a database.",
            EXIT_DB_ERROR,
        )
    print(str(found))


@db_app.command("stats")
def db_stats(
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show table row counts for the database."""
    db_path_val = require_db()
    conn = get_db(db_path_val)

    tables = ["prds", "streams", "tasks", "work_products", "agent_log", "task_dependencies"]
    stats: dict = {}
    for table in tables:
        row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
        stats[table] = row["count"]

    conn.close()

    if json:
        output_json(stats)
    else:
        rows = [{"table": t, "rows": c} for t, c in stats.items()]
        output_table(["table", "rows"], rows, title="Database Stats")
