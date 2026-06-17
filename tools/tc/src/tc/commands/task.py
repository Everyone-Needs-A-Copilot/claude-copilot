"""Task commands for Task Copilot CLI."""

from typing import Optional

import typer

from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import (
    error_exit,
    require_db,
    EXIT_NOT_FOUND,
    EXIT_CONFLICT,
    EXIT_VALIDATION,
)
from tc.db.exceptions import ConflictError, TaskNotFound, ValidationError

task_app = typer.Typer(name="task", help="Task management commands.")


@task_app.command("create")
def task_create(
    title: str = typer.Option(..., "--title", help="Task title."),
    prd: Optional[int] = typer.Option(None, "--prd", help="Associated PRD ID."),
    stream: Optional[int] = typer.Option(
        None, "--stream", help="Associated stream ID."
    ),
    agent: Optional[str] = typer.Option(None, "--agent", help="Assigned agent."),
    priority: int = typer.Option(2, "--priority", help="Priority 0-3 (0=highest)."),
    parent: Optional[int] = typer.Option(None, "--parent", help="Parent task ID."),
    description: Optional[str] = typer.Option(
        None, "--description", help="Task description."
    ),
    metadata: Optional[str] = typer.Option(
        None, "--metadata", help="JSON metadata string."
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Create a new task."""
    from tc.services.tasks import create_task as _create_task

    db_path = require_db()
    try:
        row = _create_task(
            title=title,
            prd=prd,
            stream=stream,
            agent=agent,
            priority=priority,
            parent=parent,
            description=description,
            metadata=metadata,
            db_path=db_path,
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(row)
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
    from tc.services.tasks import list_tasks as _list_tasks

    db_path = require_db()
    try:
        data = _list_tasks(
            status=status, agent=agent, stream=stream, prd=prd, db_path=db_path
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

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
    from tc.services.tasks import get_task as _get_task

    db_path = require_db()
    try:
        d = _get_task(task_id=task_id, db_path=db_path)
    except TaskNotFound:
        if json:
            output_error_json(f"Task #{task_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)

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
    description: Optional[str] = typer.Option(
        None, "--description", help="New description."
    ),
    priority: Optional[int] = typer.Option(
        None, "--priority", help="New priority 0-3."
    ),
    title: Optional[str] = typer.Option(None, "--title", help="New title."),
    metadata: Optional[str] = typer.Option(
        None, "--metadata", help="JSON metadata to merge into existing metadata."
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Update a task."""
    from tc.services.tasks import update_task as _update_task

    db_path = require_db()
    try:
        row = _update_task(
            task_id=task_id,
            status=status,
            agent=agent,
            description=description,
            priority=priority,
            title=title,
            metadata=metadata,
            db_path=db_path,
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except TaskNotFound:
        if json:
            output_error_json(f"Task #{task_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)

    if json:
        output_json(row)
    else:
        if (
            status is None
            and agent is None
            and description is None
            and priority is None
            and title is None
            and metadata is None
        ):
            print("Nothing to update.")
        else:
            print(f"Updated task #{row['id']}: {row['title']} [{row['status']}]")


@task_app.command("claim")
def task_claim(
    task_id: int = typer.Argument(..., help="Task ID."),
    agent: str = typer.Option(..., "--agent", help="Agent claiming the task."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Atomically claim a task for an agent."""
    from tc.services.tasks import claim_task as _claim_task

    db_path = require_db()
    try:
        row = _claim_task(task_id=task_id, agent=agent, db_path=db_path)
    except ConflictError as exc:
        if json:
            output_error_json(str(exc), EXIT_CONFLICT)
        error_exit(str(exc), EXIT_CONFLICT)
    except Exception as exc:
        error_exit(str(exc))

    if json:
        output_json(row)
    else:
        print(f"Task #{task_id} claimed by {agent}")


@task_app.command("next")
def task_next(
    stream: Optional[int] = typer.Option(None, "--stream", help="Filter by stream ID."),
    agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get the next highest-priority pending task with all dependencies completed."""
    from tc.services.tasks import next_task as _next_task

    db_path = require_db()
    row = _next_task(stream=stream, agent=agent, db_path=db_path)

    if row is None:
        if json:
            output_json(None)
        else:
            print("No pending tasks available.")
        return

    if json:
        output_json(row)
    else:
        for k, v in row.items():
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
    from tc.services.tasks import add_dependency as _add_dependency

    db_path = require_db()
    try:
        result = _add_dependency(
            task_id=task_id,
            depends_on=depends_on,
            db_path=db_path,
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except TaskNotFound as exc:
        error_exit(str(exc), EXIT_NOT_FOUND)
    except ConflictError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(result)
    else:
        print(f"Task #{task_id} now depends on task #{depends_on}")


@deps_app.command("remove")
def deps_remove(
    task_id: int = typer.Argument(..., help="Task ID."),
    depends_on: int = typer.Option(
        ..., "--depends-on", help="Dependency task ID to remove."
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Remove a dependency from a task."""
    from tc.services.tasks import remove_dependency as _remove_dependency

    db_path = require_db()
    try:
        result = _remove_dependency(
            task_id=task_id, depends_on=depends_on, db_path=db_path
        )
    except TaskNotFound as exc:
        error_exit(str(exc), EXIT_NOT_FOUND)

    if json:
        output_json(result)
    else:
        print(
            f"Removed dependency: task #{task_id} no longer depends on task #{depends_on}"
        )
