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


@project_app.command("status")
def status_command(
    path: Optional[Path] = typer.Argument(None, help="Inspect exactly this folder (default: current)."),
    all_projects: bool = typer.Option(False, "--all", help="Registered projects and approved folders only."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Read thin project wiring without changing files or checking machine health."""
    from cc.core.project_init.status import project_status

    if all_projects and path is not None:
        body = {"schema_version": "1.0", "result": "blocked", "projects": [],
                "discovery": {"state": "not-granted", "roots": []},
                "errors": ["Choose one project folder or --all, not both."]}
    else:
        body = project_status(path, all_projects=all_projects)
    if json_output:
        typer.echo(json.dumps(body))
    else:
        for row in body["projects"]:
            typer.echo(f"{row['state']}: {row['name']} — {row['detail']}")
        for error in body["errors"]:
            typer.echo(error)
    if body["result"] == "blocked":
        raise typer.Exit(1)


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
    source_repo: bool = typer.Option(False, "--source-repo", help="Treat PATH as a framework source repo: remove only consumer artefacts (locks, synced copies outside protected source paths) and write the marker. Release components are detected automatically."),
    rollback: bool = typer.Option(False, "--rollback", help="Undo a migration from its backup manifest (latest by default)."),
    manifest: Optional[str] = typer.Option(None, "--manifest", help="With --rollback: the run id or backup folder to restore."),
    scan: bool = typer.Option(False, "--scan", help="Report copied framework files and locks per project (PATH, or --all); exit 1 if any."),
    scan_all: bool = typer.Option(False, "--all", help="With --scan: every project in the machine registry."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """Convert a synced project to the central model. Dry run unless --apply."""
    from cc.core.project_migrate import (
        MigrateError, apply_migration, find_manifest, plan_migration, render_plan, render_receipt,
        rollback_migration,
    )

    if scan or scan_all:
        _scan(path, scan_all, json_output, apply or rollback or bool(manifest) or bool(commit_branch))
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
        plan = plan_migration(path, allow_missing_codex=allow_missing_codex, source_repo=source_repo)
        if not apply:
            typer.echo(json.dumps(plan.to_dict()) if json_output else render_plan(plan))
            raise typer.Exit(1 if plan.refused else 0)
        receipt = apply_migration(path, plan=plan, commit_branch=commit_branch,
                                  allow_missing_codex=allow_missing_codex, source_repo=source_repo)
    except MigrateError as exc:
        body = {"schema_version": "1.0", "result": "error", "error": {"code": exc.code, "message": exc.message}}
        typer.echo(json.dumps(body) if json_output else f"error: {exc.message}")
        raise typer.Exit(1)
    typer.echo(json.dumps(receipt) if json_output else render_receipt(receipt))


def _scan(path: Path, scan_all: bool, json_output: bool, mixed: bool) -> None:
    from cc.core.project_init.registry import default_registry
    from cc.core.project_migrate import scan_projects

    if mixed or (scan_all and path != Path(".")):
        typer.echo("error: --scan is read-only and cannot be combined with --apply, --rollback, --commit-branch, or a path with --all")
        raise typer.Exit(1)
    if scan_all:
        try:
            roots = [Path(p) for p in json.loads(default_registry().read_text(encoding="utf-8")).get("projects", [])]
        except (OSError, ValueError, AttributeError):
            roots = []
    else:
        roots = [path]
    report = scan_projects(roots, depth=2)
    dirty = report["lock_files"] or report["copied_files"] or report["hook_registrations"]
    if json_output:
        typer.echo(json.dumps(report))
    else:
        for r in report["projects"]:
            typer.echo(f"{'clean' if r['clean'] else 'DIRTY'}: {r['project']} - {r['copied_files']} copied framework file(s), "
                       f"locks {r['locks'] or 'none'}, {r['hook_registrations']} hook registration(s)")
            for c in r["copied_paths"]:
                typer.echo(f"    {c}")
        typer.echo(f"{report['total']} project(s): {report['clean']} clean, {report['copied_files']} copied file(s), "
                   f"{report['lock_files']} lock(s), {report['protected']} protected source path(s) kept")
    raise typer.Exit(1 if dirty else 0)
