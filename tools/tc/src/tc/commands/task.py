"""Task commands for Task Copilot CLI."""

import json as json_mod
from typing import Optional

import typer

from tc.db.connection import get_db
from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import (
    error_exit,
    require_db,
    EXIT_NOT_FOUND,
    EXIT_CONFLICT,
    EXIT_VALIDATION,
)

task_app = typer.Typer(name="task", help="Task management commands.")


def _row_to_dict(row) -> dict:
    return dict(row)


def _log_action(conn, agent: str, task_id: int, action: str, details: str = None,
                stream_id: int = None) -> None:
    """Log an agent action to agent_log."""
    conn.execute(
        "INSERT INTO agent_log (agent, stream_id, task_id, action, details) VALUES (?, ?, ?, ?, ?)",
        (agent, stream_id, task_id, action, details),
    )


@task_app.command("create")
def task_create(
    title: str = typer.Option(..., "--title", help="Task title."),
    prd: Optional[int] = typer.Option(None, "--prd", help="Associated PRD ID."),
    stream: Optional[int] = typer.Option(None, "--stream", help="Associated stream ID."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Assigned agent."),
    priority: int = typer.Option(2, "--priority", help="Priority 0-3 (0=highest)."),
    parent: Optional[int] = typer.Option(None, "--parent", help="Parent task ID."),
    description: Optional[str] = typer.Option(None, "--description", help="Task description."),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="JSON metadata string."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Create a new task."""
    if priority < 0 or priority > 3:
        error_exit("Priority must be between 0 and 3", EXIT_VALIDATION)

    if metadata:
        try:
            json_mod.loads(metadata)
        except json_mod.JSONDecodeError as e:
            error_exit(f"Invalid metadata JSON: {e}", EXIT_VALIDATION)

    db_path = require_db()
    conn = get_db(db_path)

    cursor = conn.execute(
        """INSERT INTO tasks (prd_id, stream_id, title, description, agent, priority, parent_task_id, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (prd, stream, title, description, agent, priority, parent, metadata),
    )
    conn.commit()
    task_id = cursor.lastrowid

    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()

    if json:
        output_json(_row_to_dict(row))
    else:
        print(f"Created task #{row['id']}: {row['title']}")


@task_app.command("list")
def task_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent."),
    stream: Optional[int] = typer.Option(None, "--stream", help="Filter by stream ID."),
    prd: Optional[int] = typer.Option(None, "--prd", help="Filter by PRD ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List tasks with optional filters."""
    db_path = require_db()
    conn = get_db(db_path)

    query = "SELECT * FROM tasks WHERE 1=1"
    params: list = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if stream is not None:
        query += " AND stream_id = ?"
        params.append(stream)
    if prd is not None:
        query += " AND prd_id = ?"
        params.append(prd)

    query += " ORDER BY priority ASC, id ASC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    data = [_row_to_dict(r) for r in rows]

    if json:
        output_json(data)
    else:
        output_table(
            ["id", "title", "status", "agent", "priority", "stream_id"],
            data,
            title="Tasks",
        )


@task_app.command("get")
def task_get(
    task_id: int = typer.Argument(..., help="Task ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get a task by ID."""
    db_path = require_db()
    conn = get_db(db_path)

    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    if row is None:
        conn.close()
        if json:
            output_error_json(f"Task #{task_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)

    # Get dependencies
    deps = conn.execute(
        "SELECT depends_on FROM task_dependencies WHERE task_id = ?", (task_id,)
    ).fetchall()
    conn.close()

    d = _row_to_dict(row)
    d["dependencies"] = [r["depends_on"] for r in deps]

    if json:
        output_json(d)
    else:
        for k, v in d.items():
            print(f"{k}: {v}")


@task_app.command("update")
def task_update(
    task_id: int = typer.Argument(..., help="Task ID."),
    status: Optional[str] = typer.Option(None, "--status", help="New status."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Assigned agent."),
    description: Optional[str] = typer.Option(None, "--description", help="New description."),
    priority: Optional[int] = typer.Option(None, "--priority", help="New priority 0-3."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Update a task."""
    valid_statuses = {"pending", "in_progress", "completed", "blocked", "cancelled"}
    if status and status not in valid_statuses:
        error_exit(
            f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}",
            EXIT_VALIDATION,
        )
    if priority is not None and (priority < 0 or priority > 3):
        error_exit("Priority must be between 0 and 3", EXIT_VALIDATION)

    db_path = require_db()
    conn = get_db(db_path)

    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        conn.close()
        if json:
            output_error_json(f"Task #{task_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)

    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if agent is not None:
        updates.append("agent = ?")
        params.append(agent)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)

    if not updates:
        conn.close()
        if json:
            output_json(_row_to_dict(row))
        else:
            print("Nothing to update.")
        return

    updates.append("updated_at = datetime('now')")
    params.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)

    # Log completion
    if status == "completed" and row["agent"]:
        _log_action(conn, row["agent"], task_id, "completed",
                    stream_id=row["stream_id"])

    conn.commit()

    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()

    if json:
        output_json(_row_to_dict(row))
    else:
        print(f"Updated task #{row['id']}: {row['title']} [{row['status']}]")


@task_app.command("claim")
def task_claim(
    task_id: int = typer.Argument(..., help="Task ID."),
    agent: str = typer.Option(..., "--agent", help="Agent claiming the task."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Atomically claim a task for an agent."""
    db_path = require_db()
    conn = get_db(db_path)

    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """UPDATE tasks
               SET claimed_by = ?,
                   claimed_at = datetime('now'),
                   status = 'in_progress',
                   agent = ?,
                   updated_at = datetime('now')
               WHERE id = ?
                 AND (claimed_by IS NULL OR claimed_by = ?)
                 AND status = 'pending'""",
            (agent, agent, task_id, agent),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            conn.close()
            if json:
                output_error_json(
                    f"Task #{task_id} could not be claimed (not found, already claimed, or not pending)",
                    EXIT_CONFLICT,
                )
            error_exit(
                f"Task #{task_id} could not be claimed: not found, already claimed, or not pending.",
                EXIT_CONFLICT,
            )

        # Log claim
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        _log_action(conn, agent, task_id, "claimed",
                    details=f"Claimed by {agent}",
                    stream_id=row["stream_id"] if row else None)

        conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()

        if json:
            output_json(_row_to_dict(row))
        else:
            print(f"Task #{task_id} claimed by {agent}")

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        error_exit(str(e))


@task_app.command("next")
def task_next(
    stream: Optional[int] = typer.Option(None, "--stream", help="Filter by stream ID."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get the next highest-priority pending task with all dependencies completed."""
    db_path = require_db()
    conn = get_db(db_path)

    query = """
        SELECT t.* FROM tasks t
        WHERE t.status = 'pending'
          AND NOT EXISTS (
              SELECT 1 FROM task_dependencies td
              JOIN tasks dep ON dep.id = td.depends_on
              WHERE td.task_id = t.id
                AND dep.status != 'completed'
          )
    """
    params: list = []

    if stream is not None:
        query += " AND t.stream_id = ?"
        params.append(stream)
    if agent is not None:
        query += " AND (t.agent = ? OR t.agent IS NULL)"
        params.append(agent)

    query += " ORDER BY t.priority ASC, t.id ASC LIMIT 1"

    row = conn.execute(query, params).fetchone()
    conn.close()

    if row is None:
        if json:
            output_json(None)
        else:
            print("No pending tasks available.")
        return

    if json:
        output_json(_row_to_dict(row))
    else:
        d = _row_to_dict(row)
        for k, v in d.items():
            print(f"{k}: {v}")


# Dependency subcommands
deps_app = typer.Typer(name="deps", help="Task dependency management.")
task_app.add_typer(deps_app)


@deps_app.command("add")
def deps_add(
    task_id: int = typer.Argument(..., help="Task ID."),
    depends_on: int = typer.Option(..., "--depends-on", help="Dependency task ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Add a dependency to a task."""
    if task_id == depends_on:
        error_exit("A task cannot depend on itself.", EXIT_VALIDATION)

    db_path = require_db()
    conn = get_db(db_path)

    # Verify both tasks exist
    t = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    d = conn.execute("SELECT id FROM tasks WHERE id = ?", (depends_on,)).fetchone()

    if t is None:
        conn.close()
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)
    if d is None:
        conn.close()
        error_exit(f"Task #{depends_on} not found", EXIT_NOT_FOUND)

    try:
        conn.execute(
            "INSERT INTO task_dependencies (task_id, depends_on) VALUES (?, ?)",
            (task_id, depends_on),
        )
        conn.commit()
    except Exception as e:
        conn.close()
        if "UNIQUE constraint" in str(e) or "PRIMARY KEY" in str(e):
            error_exit(f"Dependency already exists: task #{task_id} depends on #{depends_on}", EXIT_VALIDATION)
        error_exit(str(e))

    conn.close()

    result = {"task_id": task_id, "depends_on": depends_on, "status": "added"}
    if json:
        output_json(result)
    else:
        print(f"Task #{task_id} now depends on task #{depends_on}")


@deps_app.command("remove")
def deps_remove(
    task_id: int = typer.Argument(..., help="Task ID."),
    depends_on: int = typer.Option(..., "--depends-on", help="Dependency task ID to remove."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Remove a dependency from a task."""
    db_path = require_db()
    conn = get_db(db_path)

    cursor = conn.execute(
        "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on = ?",
        (task_id, depends_on),
    )
    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        error_exit(
            f"No dependency found: task #{task_id} -> #{depends_on}",
            EXIT_NOT_FOUND,
        )

    result = {"task_id": task_id, "depends_on": depends_on, "status": "removed"}
    if json:
        output_json(result)
    else:
        print(f"Removed dependency: task #{task_id} no longer depends on task #{depends_on}")
