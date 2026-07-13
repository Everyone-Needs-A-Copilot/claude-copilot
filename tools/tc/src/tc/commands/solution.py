"""Solution commands for Task Copilot CLI — the Outcome Ledger (W-1).

Lifecycle: create -> lock-brief -> mark-working -> mark-loveable ->
log-usage -> close. See tc.services.solutions for the domain logic and the
outcome bars (O-1 TTFLS, O-2 Completeness, O-5 Survival) each field serves.
"""
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
from tc.db.exceptions import ConflictError, SolutionNotFound, ValidationError

solution_app = typer.Typer(name="solution", help="Outcome Ledger: track solutions end-to-end.")


@solution_app.command("create")
def solution_create(
    title: str = typer.Option(..., "--title", help="Solution title."),
    brief: Optional[str] = typer.Option(
        None, "--brief", help="Draft brief text (lock it later with `lock-brief`)."
    ),
    beneficiary: Optional[str] = typer.Option(
        None, "--beneficiary", help="Who this solution is for."
    ),
    repo_path: Optional[str] = typer.Option(
        None, "--repo-path", help="Repo or path the solution lives in."
    ),
    components: Optional[str] = typer.Option(
        None,
        "--components",
        help="Comma-separated subset of: framework, knowledge, integration.",
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Create a new solution (status: in_progress)."""
    from tc.services.solutions import create_solution as _create_solution

    db_path = require_db()
    try:
        row = _create_solution(
            title=title,
            brief=brief,
            beneficiary=beneficiary,
            repo_path=repo_path,
            components_used=components,
            db_path=db_path,
        )
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(row)
    else:
        print(f"Created solution #{row['id']}: {row['title']} [in_progress]")


@solution_app.command("lock-brief")
def solution_lock_brief(
    solution_id: int = typer.Argument(..., help="Solution ID."),
    brief: Optional[str] = typer.Option(
        None, "--brief", help="Brief text to lock (defaults to the text set at create)."
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Lock the brief -- the intent contract O-2 measures completeness
    against. Immutable once locked: calling this again records the
    attempted edit as a scope change instead of rewriting it."""
    from tc.services.solutions import lock_brief as _lock_brief

    db_path = require_db()
    try:
        row = _lock_brief(solution_id=solution_id, brief=brief, db_path=db_path)
    except SolutionNotFound:
        if json:
            output_error_json(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(row)
    elif row.get("scope_change_recorded"):
        print(
            f"Solution #{solution_id}: brief already locked at {row['brief_locked_at']} -- "
            "recorded as a scope change, original brief unchanged."
        )
    else:
        print(f"Solution #{solution_id}: brief locked at {row['brief_locked_at']}")


@solution_app.command("mark-working")
def solution_mark_working(
    solution_id: int = typer.Argument(..., help="Solution ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Stamp t_working (O-1: "does the job")."""
    from tc.services.solutions import mark_working as _mark_working

    db_path = require_db()
    try:
        row = _mark_working(solution_id=solution_id, db_path=db_path)
    except SolutionNotFound:
        if json:
            output_error_json(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
    except ConflictError as exc:
        if json:
            output_error_json(str(exc), EXIT_CONFLICT)
        error_exit(str(exc), EXIT_CONFLICT)

    if json:
        output_json(row)
    else:
        print(f"Solution #{solution_id} marked working at {row['t_working']}")


@solution_app.command("mark-loveable")
def solution_mark_loveable(
    solution_id: int = typer.Argument(..., help="Solution ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Stamp t_loveable (O-1: meets expectations -- MLP not MVP)."""
    from tc.services.solutions import mark_loveable as _mark_loveable

    db_path = require_db()
    try:
        row = _mark_loveable(solution_id=solution_id, db_path=db_path)
    except SolutionNotFound:
        if json:
            output_error_json(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except ConflictError as exc:
        if json:
            output_error_json(str(exc), EXIT_CONFLICT)
        error_exit(str(exc), EXIT_CONFLICT)

    if json:
        output_json(row)
    else:
        print(f"Solution #{solution_id} marked loveable at {row['t_loveable']}")


@solution_app.command("log-usage")
def solution_log_usage(
    solution_id: int = typer.Argument(..., help="Solution ID."),
    kind: str = typer.Option(
        "usage", "--kind", help="usage (sustained-use signal), fix, or feature."
    ),
    sessions: int = typer.Option(0, "--sessions", help="Sessions to add to sessions_count."),
    tokens: int = typer.Option(0, "--tokens", help="Tokens to add to tokens_total."),
    note: Optional[str] = typer.Option(None, "--note", help="Free-text note for this entry."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Log a usage/fix/feature event against a shipped solution. The first
    usage entry after shipping flips status to in_use (O-5)."""
    from tc.services.solutions import log_usage as _log_usage

    db_path = require_db()
    try:
        row = _log_usage(
            solution_id=solution_id,
            kind=kind,
            sessions=sessions,
            tokens=tokens,
            note=note,
            db_path=db_path,
        )
    except SolutionNotFound:
        if json:
            output_error_json(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except ConflictError as exc:
        if json:
            output_error_json(str(exc), EXIT_CONFLICT)
        error_exit(str(exc), EXIT_CONFLICT)

    if json:
        output_json(row)
    else:
        print(f"Solution #{solution_id}: logged {kind} (status: {row['status']})")


@solution_app.command("close")
def solution_close(
    solution_id: int = typer.Argument(..., help="Solution ID."),
    status: str = typer.Option(
        ..., "--status", help="Target status: shipped, abandoned, or retired."
    ),
    notes: Optional[str] = typer.Option(None, "--notes", help="Outcome notes."),
    post_ship_window_days: Optional[int] = typer.Option(
        None,
        "--post-ship-window-days",
        help="Review window (days) for the post-ship fix-vs-feature ratio.",
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Close a solution with a terminal outcome (shipped/abandoned) or
    retire a previously-shipped one."""
    from tc.services.solutions import close_solution as _close_solution

    db_path = require_db()
    try:
        row = _close_solution(
            solution_id=solution_id,
            status=status,
            notes=notes,
            post_ship_window_days=post_ship_window_days,
            db_path=db_path,
        )
    except SolutionNotFound:
        if json:
            output_error_json(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)
    except ConflictError as exc:
        if json:
            output_error_json(str(exc), EXIT_CONFLICT)
        error_exit(str(exc), EXIT_CONFLICT)

    if json:
        output_json(row)
    else:
        print(f"Solution #{solution_id} closed: {row['status']}")


@solution_app.command("get")
def solution_get(
    solution_id: int = typer.Argument(..., help="Solution ID."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get a solution by ID, including its scope and usage logs."""
    from tc.services.solutions import get_solution as _get_solution

    db_path = require_db()
    try:
        d = _get_solution(solution_id=solution_id, db_path=db_path)
    except SolutionNotFound:
        if json:
            output_error_json(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Solution #{solution_id} not found", EXIT_NOT_FOUND)

    if json:
        output_json(d)
    else:
        for k, v in d.items():
            if k not in ("scope_log", "usage_log"):
                print(f"{k}: {v}")
        print(f"scope_log: {len(d['scope_log'])} entries")
        print(f"usage_log: {len(d['usage_log'])} entries")


@solution_app.command("list")
def solution_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List solutions with optional status filter."""
    from tc.services.solutions import list_solutions as _list_solutions

    db_path = require_db()
    try:
        data = _list_solutions(status=status, db_path=db_path)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(data)
    else:
        output_table(
            ["id", "title", "status", "started_at", "t_working", "t_loveable"],
            data,
            title="Solutions",
        )
