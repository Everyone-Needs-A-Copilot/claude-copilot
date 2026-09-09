"""One read-only view of local observations; no live-runtime inference."""

from pathlib import Path
import json

import typer

from cc.core.session_status import build_session_status


def status_cmd(
    project: Path = typer.Option(Path("."), "--project", "--root", help="Project to inspect (default: current directory)."),
    output_json: bool = typer.Option(False, "--json", help="Output local observations as JSON."),
) -> None:
    """Show installation observations and the last verification run, without probes."""
    try:
        report = build_session_status(project)
    except (OSError, ValueError) as exc:
        if output_json:
            typer.echo(json.dumps({"schemaVersion": 1, "error": "Project must be a readable existing directory"}))
        else:
            typer.echo("status: project must be a readable existing directory", err=True)
        raise typer.Exit(2) from exc
    if output_json:
        typer.echo(json.dumps(report, sort_keys=True))
        return
    typer.echo(f"Project: {report['project']}")
    typer.echo(f"cc: {report['cc']['version']} (executing local package)")
    for runtime in report["foundation"]["runtimes"]:
        typer.echo(f"{runtime['runtime']}: installation={runtime['installed']}, registration={runtime['registered']}; activated/running/blocked=unknown")
    verification = report["verification"]
    run = verification["run"]
    if run:
        typer.echo(f"Verification: {run['lastStatus']} (last observed, process liveness unknown), run {run['id']}")
        typer.echo(f"  Scope: {run['plan']['scope']}; lanes: {', '.join(lane['id'] for lane in run['plan']['lanes'])}")
        typer.echo(f"  Observed wall interval: {run['wallSecondsLastObserved']}s; execution reused: {run['executionReused']}")
        if run["currentLaneLastObserved"]:
            lane = run["currentLaneLastObserved"]
            typer.echo(f"  Last operation: {lane['id']} ({lane['elapsedSeconds']}s observed, cap {lane['capSeconds']}s)")
        if run["needsAttention"]:
            typer.echo("  Needs attention: failed or incomplete verification evidence.")
        typer.echo(f"  Artifacts: {run['artifactPath']}")
    else:
        typer.echo(f"Verification: {verification['state']}")
    for observation in (report["foundation"], verification):
        if "reason" in observation:
            typer.echo(observation["reason"])
    typer.echo("Installation/registration observations do not prove activation or live dispatch.")
    typer.echo("Agent time, context, tokens and billing: unknown (not zero); API estimates are not subscription charges.")
    typer.echo("Read-only local observations; no probes or task approval.")
