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


def _auto_archive(db_path) -> None:
    """Daily, silent move of old finished work to the history file (see tc archive)."""
    from tc.services.archive import maybe_auto_archive

    maybe_auto_archive(db_path)


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
    include_parked: bool = typer.Option(
        False, "--include-parked", help="Also list parked tasks (hidden by default)."
    ),
    parked_only: bool = typer.Option(False, "--parked", help="List only parked tasks."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List tasks with optional filters. Parked tasks are hidden unless asked for."""
    from tc.services.tasks import list_tasks as _list_tasks

    db_path = require_db()
    parked = True if parked_only else (None if include_parked else False)
    try:
        data = _list_tasks(
            status=status, agent=agent, stream=stream, prd=prd, parked=parked, db_path=db_path
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
    _auto_archive(db_path)


@task_app.command("check-qa")
def task_check_qa(
    task_id: int = typer.Argument(..., help="Task ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Check task-bound QA evidence using the completion predicate.

    Read-only inspector: reports what `tc task update --status completed`
    would decide for this task right now, without changing anything. Exits
    1 when the evidence does not currently support approval.
    """
    from tc.services.qa import check_task_qa as _check_task_qa

    db_path = require_db()
    try:
        result = _check_task_qa(task_id=task_id, db_path=db_path)
    except TaskNotFound:
        if json:
            output_error_json(f"Task #{task_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)
    except ValidationError as exc:
        if json:
            output_error_json(str(exc), EXIT_VALIDATION)
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(result)
    else:
        print(result["reason"])
    if not result["approved"]:
        raise typer.Exit(1)


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


# Stale triage: find open work nobody is moving, then park, cancel or keep it.


def _resolve_ids(ids: list[int], stale: bool, days: int, db_path) -> list[int]:
    from tc.services.tasks import stale_tasks as _stale_tasks

    if stale:
        if ids:
            error_exit("give task IDs or --stale, not both", EXIT_VALIDATION)
        return [t["id"] for t in _stale_tasks(days=days, db_path=db_path)]
    if not ids:
        error_exit("give one or more task IDs, or --stale", EXIT_VALIDATION)
    return ids


@task_app.command("stale")
def task_stale(
    days: int = typer.Option(30, "--days", help="Idle for at least this many days."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List open, unparked tasks with no activity for --days days (oldest first)."""
    from tc.services.tasks import stale_tasks as _stale_tasks

    db_path = require_db()
    try:
        data = _stale_tasks(days=days, db_path=db_path)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    if json:
        output_json(data)
    else:
        output_table(["id", "title", "status", "agent", "idle_days"], data, title=f"Stale tasks (idle {days}+ days)")


@task_app.command("park")
def task_park(
    task_ids: list[int] = typer.Argument(None, help="Task IDs to park."),
    reason: str = typer.Option(..., "--reason", help="Why it is set aside."),
    stale: bool = typer.Option(False, "--stale", help="Park every stale task instead of listed IDs."),
    days: int = typer.Option(30, "--days", help="With --stale: idle threshold in days."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Set open tasks aside without closing them. Hidden from `list` and `next`; undo with `unpark`."""
    from tc.services.tasks import park_tasks as _park_tasks

    db_path = require_db()
    ids = _resolve_ids(task_ids or [], stale, days, db_path)
    if not ids:
        output_json([]) if json else print("No tasks to park.")
        return
    try:
        rows = _park_tasks(task_ids=ids, reason=reason, db_path=db_path)
    except (ValidationError, TaskNotFound) as exc:
        error_exit(str(exc), EXIT_VALIDATION if isinstance(exc, ValidationError) else EXIT_NOT_FOUND)
    output_json(rows) if json else print(f"Parked {len(rows)} task(s): {', '.join(f'#{r['id']}' for r in rows)}")
    _auto_archive(db_path)


@task_app.command("unpark")
def task_unpark(
    task_ids: list[int] = typer.Argument(..., help="Task IDs to return to the active list."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Return parked tasks to the active list."""
    from tc.services.tasks import unpark_tasks as _unpark_tasks

    db_path = require_db()
    try:
        rows = _unpark_tasks(task_ids=task_ids, db_path=db_path)
    except (ValidationError, TaskNotFound) as exc:
        error_exit(str(exc), EXIT_VALIDATION if isinstance(exc, ValidationError) else EXIT_NOT_FOUND)
    output_json(rows) if json else print(f"Unparked {len(rows)} task(s): {', '.join(f'#{r['id']}' for r in rows)}")
    _auto_archive(db_path)


@task_app.command("cancel")
def task_cancel(
    task_ids: list[int] = typer.Argument(None, help="Task IDs to cancel."),
    reason: str = typer.Option(..., "--reason", help="Why it will not be done."),
    stale: bool = typer.Option(False, "--stale", help="Cancel every stale task instead of listed IDs."),
    days: int = typer.Option(30, "--days", help="With --stale: idle threshold in days."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Cancel tasks with a recorded reason (metadata.cancelReason)."""
    from tc.db.connection import get_db, transaction
    from tc.services.tasks import update_task as _update_task

    db_path = require_db()
    if not reason.strip():
        error_exit("a reason is required to cancel a task", EXIT_VALIDATION)
    ids = _resolve_ids(task_ids or [], stale, days, db_path)
    if not ids:
        output_json([]) if json else print("No tasks to cancel.")
        return
    conn = get_db(db_path)
    try:
        with transaction(conn):
            rows = [
                _update_task(task_id=i, status="cancelled", metadata={"cancelReason": reason}, conn=conn)
                for i in ids
            ]
    except (ValidationError, TaskNotFound) as exc:
        error_exit(str(exc), EXIT_VALIDATION if isinstance(exc, ValidationError) else EXIT_NOT_FOUND)
    finally:
        conn.close()
    output_json(rows) if json else print(f"Cancelled {len(rows)} task(s): {', '.join(f'#{r['id']}' for r in rows)}")
    _auto_archive(db_path)


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


@task_app.command("contract")
def task_contract(
    task_id: int = typer.Argument(...),
    file: Optional[str] = typer.Option(None, "--file", help="JSON acceptance contract: schemaVersion 2 (criteria, sources), 3 (adds externalSources: [{repo, ref, paths}] for registered repos; see tc repo add) or 4 (kind, optional sources, lane, excluded, assumptions)."),
    from_done_block: Optional[str] = typer.Option(None, "--from-done-block", help="Text file with the five done-block lines; registers a schemaVersion 4 contract and execution limits."),
    kind: str = typer.Option("software", "--kind", help="With --from-done-block: software, document, design, research or automation."),
    source: Optional[list[str]] = typer.Option(None, "--source", help="With --from-done-block: project-relative source (repeatable)."),
    criterion: Optional[list[str]] = typer.Option(None, "--criterion", help="With --from-done-block: extra criterion as ID=expected (repeatable)."),
    lane_focused: Optional[str] = typer.Option(None, "--lane-focused", help="Focused check command."),
    lane_affected: Optional[str] = typer.Option(None, "--lane-affected", help="Affected check command."),
    cap_seconds: Optional[int] = typer.Option(None, "--cap-seconds", help="Lane cap in seconds."),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Register observable acceptance criteria before implementation/QA."""
    import json as json_module
    from pathlib import Path
    from tc.services.tasks import update_task
    from tc.services.qa_contract import validate_contract
    if (file is None) == (from_done_block is None):
        error_exit("give exactly one of --file or --from-done-block", EXIT_VALIDATION)
    limits_note = None
    try:
        db_path = require_db()
        path = Path(file or from_done_block)
        if path.stat().st_size > 128 * 1024:
            raise ValidationError("Acceptance contract exceeds size limit")
        if file is not None:
            contract = validate_contract(json_module.loads(path.read_text()))
        else:
            from tc.services.done_block import build_contract
            lane_given = [v is not None for v in (lane_focused, lane_affected, cap_seconds)]
            if any(lane_given) and not all(lane_given):
                raise ValidationError("--lane-focused, --lane-affected and --cap-seconds go together")
            lane = {"focused": lane_focused, "affected": lane_affected, "cap_seconds": cap_seconds} if all(lane_given) else None
            contract = validate_contract(build_contract(path.read_text(), kind=kind, sources=source, criteria=criterion, lane=lane))
        derived_note = None
        if contract.get("schemaVersion") == 4 and "lane" not in contract and contract.get("sources"):
            from tc.services.test_map import derive_lane
            derived, derived_note = derive_lane(db_path, contract["sources"])
            if derived:
                contract = validate_contract({**contract, "lane": derived})
                derived_note = f"Lane derived from the test map: {derived['lane']}, cap {derived['cap_seconds']} s" + (f" ({derived_note})" if derived_note else "")
        registered = None
        if from_done_block is not None:
            from tc.services.done_block import limits_registered
            registered = limits_registered(task_id, db_path)
        row = update_task(task_id=task_id, metadata={"requiresQa": True, "acceptanceContract": contract}, db_path=db_path)
        if from_done_block is not None:
            if registered:
                limits_note = "Execution limits were already registered; left unchanged"
            else:
                from tc.services.execution import register_limits
                register_limits(task_id=task_id, db_path=db_path)
                limits_note = "Registered execution limits (policy v2)"
    except (OSError, ValueError, ValidationError, TaskNotFound) as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    if json:
        output_json(row)
    else:
        print(f"Registered acceptance contract for task #{task_id}")
        if derived_note:
            print(derived_note)
        if limits_note:
            print(limits_note)


@task_app.command("review")
def task_review(
    task_id: Optional[int] = typer.Argument(None, help="Task ID to record the close-out review on."),
    scope_recovered: bool = typer.Option(False, "--scope-recovered/--no-scope-recovered"),
    completion_recovered: bool = typer.Option(False, "--completion-recovered/--no-completion-recovered"),
    authorization_repeated: bool = typer.Option(False, "--authorization-repeated/--no-authorization-repeated"),
    rework_from_assumption: bool = typer.Option(False, "--rework-from-assumption/--no-rework-from-assumption"),
    note: Optional[str] = typer.Option(None, "--note", help="Short free-text note."),
    summary: bool = typer.Option(False, "--summary", help="Print this project's review counts instead of recording."),
    since: Optional[str] = typer.Option(None, "--since", help="With --summary: only tasks completed on or after YYYY-MM-DD."),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Record the four close-out booleans on a task, or summarise them for this project."""
    from tc.services import review as rv
    db_path = require_db()
    try:
        if summary:
            if task_id is not None:
                error_exit("--summary takes no task ID", EXIT_VALIDATION)
            data = rv.review_summary(since=since, db_path=db_path)
            if json:
                output_json(data)
            else:
                output_table(["tasksCompleted", "tasksReviewed", *rv.FLAGS], [data], title="Task reviews")
            return
        if task_id is None or since is not None:
            error_exit("give a task ID to record a review (--since belongs to --summary)", EXIT_VALIDATION)
        flags = {"scopeRecovered": scope_recovered, "completionRecovered": completion_recovered,
                 "authorizationRepeated": authorization_repeated, "reworkFromAssumption": rework_from_assumption}
        row = rv.record_review(task_id=task_id, flags=flags, note=note, db_path=db_path)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except TaskNotFound:
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)
    output_json(row) if json else print(f"Recorded review for task #{task_id}")


@task_app.command("evidence-identity")
def task_evidence_identity(
    task_id: int = typer.Argument(...),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Capture task/source/runtime identity BEFORE running verification."""
    from tc.services.qa_contract import capture_qa_identity
    try:
        receipt = capture_qa_identity(task_id=task_id, db_path=require_db())
    except (OSError, ValidationError, TaskNotFound) as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    output_json(receipt) if json else print(receipt["identity_line"])
