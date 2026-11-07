"""`cc workspace` -- project-folder roots for Control Tower.

Kept: `roots`, `approve-root`, `forget-root`, `decline` (which folders hold projects; nothing is
copied or locked). Retired: the status report, `configure`, `finish`, `verify`, `plan`,
`migrate`, `hold` and `revert`, which inspected framework copies against `copilot.lock.json`
and activated or reverted them. `cc project init` is the one project writer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from cc.commands.retired import refuse, register_retired
from cc.core.config import add_to_list_config, remove_from_list_config, resolve_key, unset_config, write_config
from cc.core.ecosystem.workspaces import (
    detect_candidate_roots,
    forget_root_grant,
    list_configured_roots,
    record_root_grant,
)

SCHEMA_VERSION = "1.1"
workspaces_app = typer.Typer(help="Project folders for Control Tower (activation is `cc project init`).", invoke_without_command=True)


@workspaces_app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,
    project: Optional[str] = typer.Option(None, "--project", help="Retired."),
    all_projects: bool = typer.Option(False, "--all", help="Retired."),
    output_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """The per-project status report is retired; see the subcommands for project folders."""
    if ctx.invoked_subcommand is not None:
        return
    raise refuse("workspace", output_json=output_json, detail="The copy-and-lock status report no longer exists.")


for _retired in ("configure", "finish", "verify", "plan", "migrate", "hold", "revert"):
    register_retired(workspaces_app, _retired, display=f"workspace {_retired}")


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
