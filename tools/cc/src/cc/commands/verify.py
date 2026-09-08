"""Visible bounded verification; execution reports do not grant QA approval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from cc.core.verification import VerificationError, build_plan, read_status, run_plan

verify_app = typer.Typer(name="verify", help="Plan and run repository-owned bounded checks (opt-in).", no_args_is_help=True)


def _emit(value: dict, output_json: bool) -> None:
    if output_json:
        typer.echo(json.dumps(value, sort_keys=True))
    elif value.get("kind") == "verification-plan":
        typer.echo(f"Scope: {value['selection']['scope']}" + (" (explicit paths are not automatic whole-change discovery)" if value["selection"]["scope"] == "declared-paths" else ""))
        for lane in value["lanes"]:
            typer.echo(f"{lane['id']}: cap {lane['timeoutSeconds']}s — {'; '.join(lane['reasons'])}")
        typer.echo("Use --json to save an executable plan. tc alone grants task approval.")
    else:
        typer.echo(f"{value['runId']}: {value['status']} — {value['artifactPath']}")
        for lane in value.get("lanes", []):
            typer.echo(f"  {lane['id']}: {lane['status']} ({lane['elapsedSeconds']}s, exit {lane['exitCode']})")


def _error(exc: Exception, output_json: bool) -> None:
    if output_json:
        typer.echo(json.dumps({"schemaVersion": 1, "error": str(exc)}))
    else:
        typer.echo(f"verify: {exc}", err=True)
    raise typer.Exit(2)


@verify_app.command("plan")
def plan_cmd(
    root: Path = typer.Option(Path("."), "--root", help="Repository root."),
    manifest: str = typer.Option("verification.json", "--manifest", help="Repository-relative manifest."),
    changed: Optional[list[str]] = typer.Option(None, "--changed", help="Changed path; repeat as needed."),
    base: Optional[str] = typer.Option(None, "--base", help="Git review base; includes dirty and untracked files."),
    lane: Optional[list[str]] = typer.Option(None, "--lane", help="Explicit lane scope; repeat as needed."),
    task: Optional[str] = typer.Option(None, "--task", help="Task association only, not approval."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Select checks without executing manifest commands; unknown impact broadens."""
    try:
        if base is not None and changed is not None:
            raise VerificationError("Use either --base or --changed, not both")
        _emit(build_plan(root, manifest_name=manifest, changed=changed, lanes=lane, task=task, base=base), output_json)
    except (VerificationError, OSError) as exc:
        _error(exc, output_json)


@verify_app.command("run")
def run_cmd(
    plan: Path = typer.Option(..., "--plan", help="Saved JSON plan from cc verify plan."),
    root: Path = typer.Option(Path("."), "--root"),
    reuse: bool = typer.Option(False, "--reuse", help="Opt in to matching hermetic execution reuse; never approval reuse."),
    task: Optional[str] = typer.Option(None, "--task", help="Override execution's task association; not approval."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Execute a fresh manifest-bound plan and retain logs under .copilot/verification."""
    announced = False

    def progress(current: dict) -> None:
        nonlocal announced
        if not announced:
            typer.echo(f"verify run={current['runId']} artifacts={current['artifactPath']}", err=True)
            announced = True
        typer.echo(f"verify {current['id']}: {current['status']} elapsed={current['elapsedSeconds']}s "
                   f"cap={current['timeoutSeconds']}s logBytes={current['logBytes']}", err=True)
        if "tests" in current:
            typer.echo(f"verify {current['id']}: case counts {json.dumps(current['tests']['counts'], sort_keys=True)}", err=True)

    try:
        value = json.loads(plan.read_text())
        if not isinstance(value, dict):
            raise VerificationError("Plan must be a JSON object")
        if task is not None:
            value["task"] = task
        result = run_plan(root, value, reuse=reuse, progress=progress)
        _emit(result, output_json)
    except (VerificationError, OSError, ValueError) as exc:
        _error(exc, output_json)
    raise typer.Exit(0 if result["status"] == "passed" else 1)


@verify_app.command("status")
def status_cmd(
    run: str = typer.Option(..., "--run", help="Local run ID."),
    root: Path = typer.Option(Path("."), "--root"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Read durable status without a daemon or task-state changes."""
    try:
        result = read_status(root, run)
        _emit(result, output_json)
    except (VerificationError, OSError) as exc:
        _error(exc, output_json)
    raise typer.Exit(0 if result["status"] == "passed" else 1)
