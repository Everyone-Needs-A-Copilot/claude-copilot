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
    rollback: bool = typer.Option(False, "--rollback", help="Undo a migration from its backup manifest (latest by default)."),
    manifest: Optional[str] = typer.Option(None, "--manifest", help="With --rollback: the run id or backup folder to restore."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Convert a synced project to the central model. Dry run unless --apply."""
    from cc.core.project_migrate import (
        MigrateError, apply_migration, find_manifest, plan_migration, render_plan, render_receipt,
        rollback_migration,
    )

    try:
        if rollback or manifest:
            if apply or commit_branch:
                raise MigrateError("bad-options", "--rollback cannot be combined with --apply or --commit-branch")
            if not rollback:
                raise MigrateError("bad-options", "--manifest is only used with --rollback")
            found = find_manifest(path, manifest)
            owner = json.loads((found / "manifest.json" if found.is_dir() else found).read_text(encoding="utf-8"))
            if Path(owner.get("project", "")).resolve() != path.expanduser().resolve():
                raise MigrateError("wrong-project", f"that backup belongs to {owner.get('project')}, not {path}")
            result = rollback_migration(found)
            if json_output:
                typer.echo(json.dumps(result))
            else:
                typer.echo(f"Rolled back {result['project']}: {len(result['restored'])} path(s) restored.")
                for c in result["conflicts"]:
                    typer.echo(f"left in place: {c}")
            raise typer.Exit(1 if result["conflicts"] else 0)
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
