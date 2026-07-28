"""Versioned CLI contract for invisible, bounded workspace activation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from cc.core.config import (
    add_to_list_config,
    remove_from_list_config,
    resolve_key,
    unset_config,
    write_config,
)
from cc.core.ecosystem.workspaces import (
    SUPPORTED_COMPONENTS,
    ActivationError,
    RevertError,
    activate_components,
    associate_personal_project,
    default_personal_registry,
    detect_candidate_roots,
    discover_workspaces,
    forget_root_grant,
    list_configured_roots,
    recently_set_up,
    record_automatic_setup,
    record_root_grant,
    revert_project,
    undo_status,
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


def _discovery_state() -> dict[str, Any]:
    """`granted` / `not-granted` / `declined` plus the approved folders, named
    for display but carrying their path only for round-tripping back to the
    CLI (never rendered)."""
    configured = list_configured_roots()
    if bool(resolve_key("projects.declined")):
        state = "declined"
    elif configured:
        state = "granted"
    else:
        state = "not-granted"
    return {
        "state": state,
        "roots": [{"name": item["name"], "path": item["path"]} for item in configured],
    }


def build_workspaces_report(*, projects: list[Path]) -> dict:
    report = _report("status", [workspace_status(project) for project in projects])
    report["discovery"] = _discovery_state()
    report["recently_set_up"] = recently_set_up()
    return report


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


def _selected_components(before: dict, components: str) -> tuple[list[str], Optional[str]]:
    """Resolve the `--components` argument against one project's own
    recommendation. Returns (selected, invalid_message); invalid_message is
    None when `selected` is usable."""
    if components == "auto":
        selected = before["recommended_components"]
    else:
        selected = list(dict.fromkeys(part.strip().lower() for part in components.split(",") if part.strip()))
    invalid = [item for item in selected if item not in SUPPORTED_COMPONENTS]
    if not selected or invalid:
        return [], f"Unsupported copilots: {', '.join(invalid) or 'none'}."
    return selected, None


def _planned_actions(before: dict, selected: list[str], share_with_project: bool, associate_personal: bool) -> list[dict]:
    actions = []
    missing = [item for item in selected if item not in before["installed_components"]]
    if missing:
        actions.append({"id": "activate-components", "scope": "project", "status": "planned", "detail": "Add the selected Copilot setup without replacing existing project files."})
    if share_with_project and before["declared_components"] != selected:
        actions.append({"id": "share-project-setup", "scope": "project", "status": "planned", "detail": "Share this project's Copilot choices with collaborators."})
    key = before["project_id"]
    if associate_personal and key and before["personal_profile"]["state"] != "associated":
        actions.append({"id": "associate-personal", "scope": "personal", "status": "planned", "detail": "Use your private preferences with this project on this Mac."})
    return actions


def _apply_selected(root: Path, before: dict, selected: list[str], share_with_project: bool, associate_personal: bool) -> Optional[str]:
    """Apply one project's activation plan. Returns the activation-error
    message, or None on success."""
    key = before["project_id"]
    try:
        activate_components(root, selected)
        write_install_lock(root, selected)
        if share_with_project:
            write_declaration(root, selected)
        if associate_personal and key:
            associate_personal_project(key, selected, registry=default_personal_registry())
        if before["setup_policy"] == "automatic":
            record_automatic_setup(root, name=before["name"])
        return None
    except ActivationError as exc:
        return str(exc)


def _configure_one(
    root: Path,
    *,
    components: str,
    share_with_project: bool,
    associate_personal: bool,
    apply: bool,
) -> tuple[dict, list[dict], Optional[str]]:
    """Plan or apply one project. Returns (report_item, actions, invalid_message)."""
    before = workspace_status(root)
    selected, invalid_message = _selected_components(before, components)
    if invalid_message:
        return before, [], invalid_message

    actions = _planned_actions(before, selected, share_with_project, associate_personal)
    activation_error = None
    if apply and before["state"] != "blocked":
        activation_error = _apply_selected(root, before, selected, share_with_project, associate_personal)
        if activation_error is None:
            actions = [{**action, "status": "applied"} for action in actions]

    after = workspace_status(root)
    if activation_error:
        after["state"] = "blocked"
        after["detail"] = activation_error
    return (after if apply else before), actions, None


@workspaces_app.command("configure")
def configure(
    project: Optional[str] = typer.Option(None, "--project", help="Project workspace to configure."),
    apply_all: bool = typer.Option(False, "--apply-all", help="Configure every discovered project that can be set up, in one call."),
    components: str = typer.Option("auto", "--components", help="auto or comma-separated claude,codex."),
    share_with_project: bool = typer.Option(False, "--share-with-project", help="Write the portable shared project declaration."),
    associate_personal: bool = typer.Option(True, "--associate-personal/--no-associate-personal", help="Associate the opaque project id with the private personal-profile seam."),
    apply: bool = typer.Option(False, "--apply", help="Apply the explicit declaration/personal association plan."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned workspace report."),
) -> None:
    """Plan or apply the safe workspace declaration and personal association."""
    if bool(project) == bool(apply_all):
        message = "Choose exactly one of --project or --apply-all."
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "invalid-argument", "message": message}}))
        raise typer.Exit(2)

    if apply_all:
        targets = [
            candidate
            for candidate in discover_workspaces()
            if workspace_status(candidate)["state"] in ("setup-available", "activation-required")
        ]
        items: list[dict] = []
        actions: list[dict] = []
        for candidate in targets:
            item, item_actions, invalid_message = _configure_one(
                candidate,
                components=components,
                share_with_project=share_with_project,
                associate_personal=associate_personal,
                apply=apply,
            )
            if invalid_message:
                if output_json:
                    typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "invalid-argument", "message": invalid_message}}))
                raise typer.Exit(2)
            items.append(item)
            actions.extend(item_actions)
        report = _report("apply" if apply else "plan", items)
        report["actions"] = actions
        if apply and actions and report["result"] == "ready":
            report["result"] = "applied"
        typer.echo(json.dumps(report) if output_json else f"{report['result']}: {len(items)} project(s)")
        if report["result"] == "blocked":
            raise typer.Exit(1)
        return

    root = Path(project).expanduser()
    item, actions, invalid_message = _configure_one(
        root,
        components=components,
        share_with_project=share_with_project,
        associate_personal=associate_personal,
        apply=apply,
    )
    if invalid_message:
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "invalid-argument", "message": invalid_message}}))
        raise typer.Exit(2)
    report = _report("apply" if apply else "plan", [item])
    report["actions"] = actions
    # Writing a declaration is not installation proof. Preserve the honest
    # activation-required result until component-owned installers create their
    # explicit markers/lock state.
    if apply and actions and report["result"] == "ready":
        report["result"] = "applied"
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {root.name}")
    if report["result"] == "blocked":
        raise typer.Exit(1)


def _configured_root_names() -> list[str]:
    raw_roots = resolve_key("projects.roots") or []
    if isinstance(raw_roots, str):
        raw_roots = [raw_roots]
    configured = []
    for value in raw_roots:
        try:
            configured.append(str(Path(value).expanduser().resolve()))
        except (OSError, TypeError, ValueError):
            continue
    return configured


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
            "root": {"name": candidate.name or "Selected folder", "path": None, "state": "blocked", "detail": "That folder is not available for project discovery."},
        }
    else:
        configured = _configured_root_names()
        existing = str(canonical) in configured
        if apply and not existing:
            add_to_list_config("projects.roots", str(canonical))
            # Snapshot what's already in this folder right now: everything
            # here is EXISTING (always asked about); anything that shows up
            # afterward is NEW (set up automatically). Only on a genuinely
            # new grant -- an already-approved folder keeps its original
            # snapshot, or a project added between two approvals of the
            # same folder would be wrongly reclassified as existing.
            record_root_grant(canonical)
        if apply and bool(resolve_key("projects.declined")):
            unset_config("projects.declined")
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": "apply" if apply else "plan",
            "result": "ready" if existing else ("applied" if apply else "action-required"),
            "root": {
                "name": canonical.name,
                "path": str(canonical),
                "state": "approved" if (existing or apply) else "available",
                "detail": "Control Tower will look for projects only inside this folder.",
            },
        }
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {report['root']['name']}")
    if report["result"] == "blocked":
        raise typer.Exit(1)


@workspaces_app.command("forget-root")
def forget_root(
    path: str = typer.Option(..., "--path", help="Folder to stop watching for projects."),
    apply: bool = typer.Option(False, "--apply", help="Remove this folder from bounded workspace discovery."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned root-approval report."),
) -> None:
    """Plan or apply removing one approved folder. Never deletes anything inside it."""
    candidate = Path(path).expanduser()
    try:
        canonical = candidate.resolve()
    except OSError:
        canonical = candidate
    existing = str(canonical) in _configured_root_names()
    if apply and existing:
        remove_from_list_config("projects.roots", str(canonical))
        # A folder approved again later starts from a fresh snapshot rather
        # than reusing whatever was known the first time it was granted.
        forget_root_grant(canonical)
    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "apply" if apply else "plan",
        "result": "ready" if not existing else ("applied" if apply else "action-required"),
        "root": {
            "name": canonical.name or "Selected folder",
            "path": str(canonical),
            "state": "removed" if (not existing or apply) else "approved",
            "detail": "Control Tower stopped looking in this folder. Nothing inside it was changed." if (existing and apply) else "Control Tower was not watching this folder.",
        },
    }
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {report['root']['name']}")
    if report["result"] == "blocked":
        raise typer.Exit(1)


@workspaces_app.command("roots")
def roots(
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned workspace-root report."),
) -> None:
    """Read configured project folders plus detected one-click candidates. Never writes."""
    configured = list_configured_roots()
    candidates = detect_candidate_roots()
    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "status",
        "result": "ready" if configured else "action-required",
        "roots": configured,
        "candidates": candidates,
    }
    if output_json:
        typer.echo(json.dumps(report))
    elif configured:
        typer.echo(f"{report['result']}: {len(configured)} folder(s) watched")
    elif candidates:
        typer.echo(f"{report['result']}: {len(candidates)} folder(s) found that could hold your projects")
    else:
        typer.echo(f"{report['result']}: no projects folder chosen yet")


@workspaces_app.command("decline")
def decline(
    apply: bool = typer.Option(False, "--apply", help="Record that Control Tower should not offer project setup on this Mac."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned workspace-root report."),
) -> None:
    """Plan or apply 'I don't keep projects on this Mac.' Reversible by approving a folder later."""
    declined_now = bool(resolve_key("projects.declined"))
    if apply and not declined_now:
        write_config("projects.declined", True)
    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "apply" if apply else "plan",
        "result": "ready" if declined_now else ("applied" if apply else "action-required"),
        "discovery": _discovery_state(),
    }
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: projects declined")
    if report["result"] == "blocked":
        raise typer.Exit(1)


@workspaces_app.command("revert")
def revert(
    project: str = typer.Option(..., "--project", help="Project to remove Copilot's own added files from."),
    apply: bool = typer.Option(False, "--apply", help="Remove only the framework files this Mac recorded, and stop offering automatic setup for this project."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned workspace report."),
) -> None:
    """Plan or apply removing only what Copilot itself added to one project. Never touches the person's own files."""
    root = Path(project).expanduser()
    if not apply:
        plan = undo_status(root)
        report = {
            "schema_version": SCHEMA_VERSION,
            "mode": "plan",
            "result": "action-required" if plan["available"] else "blocked",
            "workspaces": [workspace_status(root)],
            "revert": {"removed": [], "kept": [], "detail": plan["detail"]},
        }
        typer.echo(json.dumps(report) if output_json else f"{report['result']}: {root.name}")
        if report["result"] == "blocked":
            raise typer.Exit(1)
        return

    try:
        outcome = revert_project(root)
        result = "applied"
    except RevertError as exc:
        outcome = {"removed": [], "kept": [], "detail": str(exc)}
        result = "blocked"

    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": "apply",
        "result": result,
        "workspaces": [workspace_status(root)],
        "revert": outcome,
    }
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {root.name}")
    if report["result"] == "blocked":
        raise typer.Exit(1)
