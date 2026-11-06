"""`cc project init` (wired into main.py by the integration stream)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cc.core.project_init import InitError, init_project

project_app = typer.Typer(help="Initialise and inspect project Copilot state.", no_args_is_help=True)


@project_app.callback()
def _root() -> None:
    """Project Copilot state."""


@project_app.command("init")
def init_command(
    path: Path = typer.Argument(Path("."), help="Project folder (default: current)."),
    codex_config: Optional[Path] = typer.Option(None, "--codex-config", hidden=True),
    force: bool = typer.Option(False, "--force", help="Back up and recreate a corrupt copilot.project.json."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Write the marker, thin CLAUDE.md/AGENTS.md sections and Codex trust."""
    try:
        report = init_project(path, codex_config=codex_config, force=force)
    except InitError as exc:
        body = {"schema_version": "1.0", "result": "error", "error": {"code": exc.code, "message": exc.message}}
        typer.echo(json.dumps(body) if json_output else f"error: {exc.message}")
        raise typer.Exit(1)
    typer.echo(json.dumps(report) if json_output else f"{report['result']}: {report['project']}")


@project_app.command("migrate")
def migrate_command(
    path: Path = typer.Argument(Path("."), help="Project folder (default: current)."),
    apply: bool = typer.Option(False, "--apply", help="Write the changes. Default is a dry run that only prints the plan."),
    commit_branch: Optional[str] = typer.Option(None, "--commit-branch", help="With --apply: commit the migration on a new branch."),
    allow_missing_codex: bool = typer.Option(False, "--allow-missing-codex", help="Proceed when no Codex root resolves; Codex files are kept."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Convert a synced project to the central model. Dry run unless --apply."""
    from cc.core.project_migrate import (
        MigrateError, apply_migration, plan_migration, render_plan, render_receipt,
    )

    try:
        plan = plan_migration(path, allow_missing_codex=allow_missing_codex)
        if not apply:
            typer.echo(json.dumps(plan.to_dict()) if json_output else render_plan(plan))
            raise typer.Exit(1 if plan.refused else 0)
        receipt = apply_migration(path, plan=plan, commit_branch=commit_branch,
                                  allow_missing_codex=allow_missing_codex)
    except MigrateError as exc:
        body = {"schema_version": "1.0", "result": "error", "error": {"code": exc.code, "message": exc.message}}
        typer.echo(json.dumps(body) if json_output else f"error: {exc.message}")
        raise typer.Exit(1)
    typer.echo(json.dumps(receipt) if json_output else render_receipt(receipt))
