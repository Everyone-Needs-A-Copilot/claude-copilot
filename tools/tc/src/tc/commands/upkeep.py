"""Upkeep commands for Task Copilot CLI — maintenance-session tagging
(O-9 upkeep tax, Phase 4 outcome program).

Two ways to tag, both registered under claims.yaml definitions.upkeep_tax:
  - `tc upkeep tag-task`: exact, one task at a time (also captures the live
    session id, if any -- the token-accountable method).
  - `tc upkeep tag-prd`: heuristic, bulk-applies to every task already
    filed under a PRD -- the retrospective-computability method, since it
    covers tasks that existed before this feature did.

See tc.services.upkeep for the domain logic.
"""
from typing import Optional

import typer

from tc.formatting import output_json, output_table, output_error_json
from tc.utils.errors import (
    error_exit,
    require_db,
    EXIT_NOT_FOUND,
    EXIT_VALIDATION,
)
from tc.db.exceptions import PrdNotFound, TaskNotFound, ValidationError

upkeep_app = typer.Typer(
    name="upkeep", help="O-9 upkeep tax: tag work as maintenance vs solution-producing."
)


@upkeep_app.command("tag-task")
def upkeep_tag_task(
    task_id: int = typer.Argument(..., help="Task ID."),
    kind: str = typer.Option(
        "other", "--kind", help="framework, knowledge, cli, registry, or other."
    ),
    note: Optional[str] = typer.Option(None, "--note", help="Free-text note."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Explicitly tag one task as upkeep work. Wins over any prior
    `tag-prd` sweep for this task."""
    from tc.services.upkeep import tag_task as _tag_task

    db_path = require_db()
    try:
        row = _tag_task(task_id=task_id, kind=kind, note=note, db_path=db_path)
    except TaskNotFound:
        if json:
            output_error_json(f"Task #{task_id} not found", EXIT_NOT_FOUND)
        error_exit(f"Task #{task_id} not found", EXIT_NOT_FOUND)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(row)
    else:
        print(f"Task #{task_id} tagged upkeep [{row['kind']}] (method: {row['method']})")


@upkeep_app.command("tag-prd")
def upkeep_tag_prd(
    prd_id: int = typer.Argument(..., help="PRD ID."),
    kind: str = typer.Option(
        "other", "--kind", help="framework, knowledge, cli, registry, or other."
    ),
    note: Optional[str] = typer.Option(None, "--note", help="Free-text note."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Flag a PRD as maintenance-producing and bulk-tag every task already
    filed under it (the retrospective-computability path). Idempotent:
    safe to re-run as new tasks land under the PRD; never overwrites a
    task explicitly tagged via `tag-task`."""
    from tc.services.upkeep import tag_prd as _tag_prd

    db_path = require_db()
    try:
        row = _tag_prd(prd_id=prd_id, kind=kind, note=note, db_path=db_path)
    except PrdNotFound:
        if json:
            output_error_json(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)
        error_exit(f"PRD #{prd_id} not found", EXIT_NOT_FOUND)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(row)
    else:
        print(
            f"PRD #{prd_id} flagged upkeep [{row['kind']}]: "
            f"{row['tasks_tagged']}/{row['tasks_under_prd']} tasks tagged"
        )


@upkeep_app.command("list")
def upkeep_list(
    kind: Optional[str] = typer.Option(None, "--kind", help="Filter by kind."),
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List every tagged task."""
    from tc.services.upkeep import list_upkeep as _list_upkeep

    db_path = require_db()
    try:
        data = _list_upkeep(kind=kind, db_path=db_path)
    except ValidationError as exc:
        error_exit(str(exc), EXIT_VALIDATION)

    if json:
        output_json(data)
    else:
        output_table(
            ["task_id", "title", "status", "kind", "method", "tagged_at"],
            data,
            title="Upkeep-tagged tasks",
        )


@upkeep_app.command("summary")
def upkeep_summary(
    json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Aggregate upkeep-tag totals for this store: task-count share,
    by-kind/by-method breakdown, PRDs flagged, sessions captured."""
    from tc.services.upkeep import summary as _summary

    db_path = require_db()
    data = _summary(db_path=db_path)

    if json:
        output_json(data)
    else:
        for k, v in data.items():
            print(f"{k}: {v}")
