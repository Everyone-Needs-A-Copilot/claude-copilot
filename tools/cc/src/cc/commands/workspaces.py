"""Versioned CLI contract for invisible, bounded workspace activation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cc.core.config import add_to_list_config, resolve_key
from cc.core.ecosystem.workspaces import (
    ActivationError,
    SUPPORTED_COMPONENTS,
    activate_components,
    associate_personal_project,
    default_personal_registry,
    discover_workspaces,
    workspace_status,
    write_declaration,
    write_install_lock,
)

SCHEMA_VERSION = "1.0"
workspaces_app = typer.Typer(help="Discover and activate project Copilot setup.", invoke_without_command=True)


def _report(mode: str, workspaces: list[dict]) -> dict:
    counts = {state: sum(item["state"] == state for item in workspaces) for state in ("ready", "setup-available", "activation-required", "blocked")}
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "result": "blocked" if counts["blocked"] else ("action-required" if counts["setup-available"] or counts["activation-required"] else "ready"),
        "workspaces": workspaces,
        "summary": {**counts, "total": len(workspaces)},
    }


def build_workspaces_report(*, projects: list[Path]) -> dict:
    return _report("status", [workspace_status(project) for project in projects])


@workspaces_app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    project: Optional[str] = typer.Option(None, "--project", help="Inspect one project workspace."),
    all_projects: bool = typer.Option(False, "--all", help="Inspect Git projects under approved roots."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned workspace report."),
) -> None:
    """Read workspace activation state. Never writes or installs anything."""
    if ctx.invoked_subcommand is not None:
        return
    if bool(project) == bool(all_projects):
        message = "Choose exactly one of --project or --all."
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "invalid-argument", "message": message}}))
        raise typer.Exit(2)
    projects = [Path(project)] if project else discover_workspaces()
    report = build_workspaces_report(projects=projects)
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {report['summary']['total']} workspace(s)")
    if report["result"] == "blocked":
        raise typer.Exit(1)


@workspaces_app.command("configure")
def configure(
    project: str = typer.Option(..., "--project", help="Project workspace to configure."),
    components: str = typer.Option("auto", "--components", help="auto or comma-separated claude,codex."),
    share_with_project: bool = typer.Option(False, "--share-with-project", help="Write the portable shared project declaration."),
    associate_personal: bool = typer.Option(True, "--associate-personal/--no-associate-personal", help="Associate the opaque project id with the private personal-profile seam."),
    apply: bool = typer.Option(False, "--apply", help="Apply the explicit declaration/personal association plan."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned workspace report."),
) -> None:
    """Plan or apply the safe workspace declaration and personal association."""
    root = Path(project).expanduser()
    before = workspace_status(root)
    if components == "auto":
        selected = before["recommended_components"]
    else:
        selected = list(dict.fromkeys(part.strip().lower() for part in components.split(",") if part.strip()))
    invalid = [item for item in selected if item not in SUPPORTED_COMPONENTS]
    if not selected or invalid:
        message = f"Unsupported copilots: {', '.join(invalid) or 'none'}."
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "invalid-argument", "message": message}}))
        raise typer.Exit(2)

    actions = []
    missing = [item for item in selected if item not in before["installed_components"]]
    if missing:
        actions.append({"id": "activate-components", "scope": "project", "status": "planned", "detail": "Add the selected Copilot setup without replacing existing project files."})
    if share_with_project and before["declared_components"] != selected:
        actions.append({"id": "share-project-setup", "scope": "project", "status": "planned", "detail": "Share this project's Copilot choices with collaborators."})
    key = before["project_id"]
    if associate_personal and key and before["personal_profile"]["state"] != "associated":
        actions.append({"id": "associate-personal", "scope": "personal", "status": "planned", "detail": "Use your private preferences with this project on this Mac."})

    activation_error = None
    if apply and before["state"] != "blocked":
        try:
            activate_components(root, selected)
            write_install_lock(root, selected)
            if share_with_project:
                write_declaration(root, selected)
            if associate_personal and key:
                associate_personal_project(key, selected, registry=default_personal_registry())
            actions = [{**action, "status": "applied"} for action in actions]
        except ActivationError as exc:
            activation_error = str(exc)

    after = workspace_status(root)
    if activation_error:
        after["state"] = "blocked"
        after["detail"] = activation_error
    report = _report("apply" if apply else "plan", [after if apply else before])
    report["actions"] = actions
    # Writing a declaration is not installation proof. Preserve the honest
    # activation-required result until component-owned installers create their
    # explicit markers/lock state.
    if apply and actions and report["result"] == "ready":
        report["result"] = "applied"
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {root.name}")
    if report["result"] == "blocked":
        raise typer.Exit(1)


@workspaces_app.command("approve-root")
def approve_root(
    path: str = typer.Option(..., "--path", help="Folder the user selected for project discovery."),
    apply: bool = typer.Option(False, "--apply", help="Add this folder to bounded workspace discovery."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned root-approval report."),
) -> None:
    """Plan or approve one project folder; never scans outside that folder."""
    candidate = Path(path).expanduser()
    try:
        valid = candidate.is_dir() and not candidate.is_symlink()
        canonical = candidate.resolve() if valid else None
    except OSError:
        valid, canonical = False, None
    if not valid or canonical is None:
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": "apply" if apply else "plan",
            "result": "blocked",
            "root": {"name": candidate.name or "Selected folder", "state": "blocked", "detail": "That folder is not available for project discovery."},
        }
    else:
        raw_roots = resolve_key("projects.roots") or []
        if isinstance(raw_roots, str):
            raw_roots = [raw_roots]
        configured = []
        for value in raw_roots:
            try:
                configured.append(str(Path(value).expanduser().resolve()))
            except (OSError, TypeError, ValueError):
                continue
        existing = str(canonical) in configured
        if apply and not existing:
            add_to_list_config("projects.roots", str(canonical))
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": "apply" if apply else "plan",
            "result": "ready" if existing else ("applied" if apply else "action-required"),
            "root": {"name": canonical.name, "state": "approved" if (existing or apply) else "available", "detail": "Control Tower will look for projects only inside this folder."},
        }
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {report['root']['name']}")
    if report["result"] == "blocked":
        raise typer.Exit(1)
