"""`cc settings-hook` -- the reversible settings-mutation ledger's CLI
surface (WP-item-2, `mutations[]` in a project's own `copilot.lock.json`).

Mirrors the `commands/<verb>.py` build-report/execute/render split used by
`update.py`, `projects.py`, and `deprovision.py`: this module is a thin
JSON-contract shell over `core/ecosystem/mutations.py`'s pure/transactional
functions, which own every filesystem write.

Command surface (see `core/ecosystem/mutations.py`'s module docstring for
the underlying merge/revert contract):

    cc settings-hook add           [--project PATH] [--scope project|local] [--dry-run] [--json]
    cc settings-hook remove        --id MUT_ID       [--project PATH] [--json]
    cc settings-hook rollback      --id MUT_ID       [--project PATH] [--json]
    cc settings-hook list-sources  [--project PATH] [--json]
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

from cc import __version__
from cc.core.ecosystem.mutations import (
    DEFAULT_HOOK_ENTRIES,
    ApplyOutcome,
    RemoveResult,
    RollbackResult,
    apply_settings_hook,
    list_sources,
    remove_settings_hook,
    rollback_settings_hook,
)
from cc.core.ecosystem.project_locking import ProjectLockError

SCHEMA_VERSION = "1.0"
DEFAULT_SOURCE = "claude-copilot"
DEFAULT_COMPONENT = "claude"

settings_hook_app = typer.Typer(
    name="settings-hook",
    help="Register/revert framework hooks in a project's .claude/settings.json "
    "via the reversible mutations[] ledger.",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)

# Exit codes shared across every subcommand in this module.
_EXIT_OK = 0
_EXIT_ATTENTION = 1  # conflict / not-found / partial -- needs a human decision
_EXIT_ENVIRONMENT_ERROR = 2


def _project_path(project: Optional[str]) -> Path:
    return Path(project).expanduser() if project else Path.cwd()


def _emit(payload: dict[str, Any], *, output_json: bool, human: str) -> None:
    if output_json:
        typer.echo(_json.dumps(payload))
    else:
        typer.echo(human)


def _environment_error(command: str, exc: Exception, *, output_json: bool) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "error": {"code": "environment-error", "message": str(exc)},
    }
    _emit(payload, output_json=output_json, human=f"settings-hook {command}: {exc}")


@settings_hook_app.command("add")
def add_cmd(
    project: Optional[str] = typer.Option(
        None, "--project", help="Project root (defaults to the current directory)."
    ),
    scope: str = typer.Option(
        "project",
        "--scope",
        help="'project' writes .claude/settings.json (team-shared); "
        "'local' writes .claude/settings.local.json (personal, gitignored).",
    ),
    source: str = typer.Option(
        DEFAULT_SOURCE, "--source", help="Framework layer applying this mutation."
    ),
    component: str = typer.Option(
        DEFAULT_COMPONENT, "--component", help="Component this mutation belongs to."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Compute the merge WITHOUT writing anything."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Register even if this project was disabled via "
        "`cc settings-hook remove --disable` (clears the sticky opt-out's effect "
        "for this run, but does not remove the marker file itself).",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Idempotently register the framework's hook entries into the
    project's settings file, recording one `mutations[]` ledger row."""
    try:
        outcome: ApplyOutcome = apply_settings_hook(
            _project_path(project),
            entries=DEFAULT_HOOK_ENTRIES,
            source=source,
            component=component,
            scope=scope,
            applied_by=f"cc {__version__}",
            dry_run=dry_run,
            force=force,
        )
    except (ProjectLockError, ValueError) as exc:
        _environment_error("add", exc, output_json=output_json)
        raise typer.Exit(_EXIT_ENVIRONMENT_ERROR) from exc
    except Exception as exc:  # pragma: no cover - defensive
        _environment_error("add", exc, output_json=output_json)
        raise typer.Exit(_EXIT_ENVIRONMENT_ERROR) from exc

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": outcome.status,
        "detail": outcome.detail,
        "mutation": outcome.mutation,
        "actions": [
            {
                "event": a.event,
                "matcher": a.matcher,
                "command": a.command,
                "spec_fingerprint": a.spec_fingerprint,
                "action": a.action,
            }
            for a in outcome.actions
        ],
    }
    _emit(payload, output_json=output_json, human=f"settings-hook add: {outcome.status} -- {outcome.detail}")
    if outcome.status in {"applied", "adopted", "unchanged", "disabled"}:
        raise typer.Exit(_EXIT_OK)
    if outcome.status == "conflict":
        raise typer.Exit(_EXIT_ATTENTION)
    raise typer.Exit(_EXIT_ENVIRONMENT_ERROR)


@settings_hook_app.command("remove")
def remove_cmd(
    mutation_id: str = typer.Option(..., "--id", help="The mutations[] id to remove."),
    project: Optional[str] = typer.Option(
        None, "--project", help="Project root (defaults to the current directory)."
    ),
    disable: bool = typer.Option(
        False,
        "--disable",
        help="Clean, ONE-command uninstall: remove this registration AND write the "
        "sticky .claude/copilot-hooks-disabled marker, so a later `cc reconcile apply` "
        "/ `cc update --project` / `cc settings-hook add` does not silently re-add it.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Surgically strip this mutation's fingerprint-matched hook entries and
    drop its ledger row. Safe to run twice (the second run reports
    `not-found`, not an error)."""
    try:
        result: RemoveResult = remove_settings_hook(
            _project_path(project), mutation_id=mutation_id, disable=disable
        )
    except Exception as exc:  # pragma: no cover - defensive
        _environment_error("remove", exc, output_json=output_json)
        raise typer.Exit(_EXIT_ENVIRONMENT_ERROR) from exc

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": result.status,
        "detail": result.detail,
        "mutation": result.mutation,
        "removed_entries": list(result.removed_entries),
        "not_found_entries": list(result.not_found_entries),
    }
    _emit(payload, output_json=output_json, human=f"settings-hook remove: {result.status} -- {result.detail}")
    if result.status == "removed":
        raise typer.Exit(_EXIT_OK)
    if result.status == "not-found":
        raise typer.Exit(_EXIT_ATTENTION)
    raise typer.Exit(_EXIT_ENVIRONMENT_ERROR)


@settings_hook_app.command("rollback")
def rollback_cmd(
    mutation_id: str = typer.Option(..., "--id", help="The mutations[] id to roll back."),
    project: Optional[str] = typer.Option(
        None, "--project", help="Project root (defaults to the current directory)."
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Byte-exact revert: restore the target to precisely its pre-mutation
    content, refusing (status `conflict`) if the file has changed since."""
    try:
        result: RollbackResult = rollback_settings_hook(
            _project_path(project), mutation_id=mutation_id
        )
    except Exception as exc:  # pragma: no cover - defensive
        _environment_error("rollback", exc, output_json=output_json)
        raise typer.Exit(_EXIT_ENVIRONMENT_ERROR) from exc

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": result.status,
        "detail": result.detail,
        "mutation": result.mutation,
    }
    _emit(payload, output_json=output_json, human=f"settings-hook rollback: {result.status} -- {result.detail}")
    if result.status == "restored":
        raise typer.Exit(_EXIT_OK)
    if result.status in {"conflict", "not-found", "mismatch"}:
        raise typer.Exit(_EXIT_ATTENTION)
    raise typer.Exit(_EXIT_ENVIRONMENT_ERROR)


@settings_hook_app.command("list-sources")
def list_sources_cmd(
    project: Optional[str] = typer.Option(
        None, "--project", help="Project root (defaults to the current directory)."
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Read-only report of every hook entry in this project's settings
    files, classified ours / orphaned / foreign."""
    try:
        report = list_sources(_project_path(project))
    except Exception as exc:  # pragma: no cover - defensive
        _environment_error("list-sources", exc, output_json=output_json)
        raise typer.Exit(_EXIT_ENVIRONMENT_ERROR) from exc

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        rows = report.get("hooks", [])
        if not rows:
            console.print("[dim]No registered hooks found.[/dim]")
        for row in rows:
            classification = row.get("classification", "unknown")
            color = {"ours": "green", "orphaned": "yellow", "foreign": "cyan"}.get(
                classification, "white"
            )
            console.print(
                f"[{color}]{classification}[/{color}] {row.get('target')} "
                f"{row.get('event')} matcher={row.get('matcher')!r} "
                f"command={row.get('command')!r}"
            )
    orphaned = [r for r in report.get("hooks", []) if r.get("classification") == "orphaned"]
    raise typer.Exit(_EXIT_ATTENTION if orphaned else _EXIT_OK)


__all__ = ["settings_hook_app"]
