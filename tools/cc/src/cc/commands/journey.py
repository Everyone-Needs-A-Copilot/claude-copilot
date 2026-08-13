"""Machine-readable production journey witness commands."""

from __future__ import annotations

import json
import sys

import typer

from cc.core.evaluation.journey_runtime import begin_run, prepare_run, verify_dispatch_hook

journey_app = typer.Typer(help="Record protocol routes and actual agent dispatch receipts.", no_args_is_help=True)


@journey_app.command("begin")
def journey_begin(
    task: int = typer.Option(..., "--task"),
    runtime: str = typer.Option(..., "--runtime"),
    classification: str = typer.Option(..., "--classification"),
    specialists_json: str = typer.Option(..., "--specialists-json"),
    events_json: str = typer.Option(..., "--events-json"),
    prompt_sha256: str = typer.Option(..., "--prompt-sha256"),
    session_id: str = typer.Option("", "--session-id", hidden=True),
) -> None:
    try:
        value = begin_run(
            task_id=task,
            runtime=runtime,
            classification=classification,
            specialists=json.loads(specialists_json),
            events=json.loads(events_json),
            prompt_sha256=prompt_sha256,
            session_id=session_id,
        )
    except (RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(json.dumps({"error": str(exc)}))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(value))


@journey_app.command("prepare")
def journey_prepare(
    run: str = typer.Option(..., "--run"),
    specialist: str = typer.Option(..., "--specialist"),
) -> None:
    try:
        value = prepare_run(run, specialist).public_dict()
    except (RuntimeError, TypeError, ValueError) as exc:
        typer.echo(json.dumps({"error": str(exc)}))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(value))


@journey_app.command("verify-hook", hidden=True)
def journey_verify_hook() -> None:
    """Validate a real PreToolUse Agent payload read from stdin."""
    try:
        payload = json.load(sys.stdin)
        result = verify_dispatch_hook(payload)
    except (RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(json.dumps({"allowed": False, "error": str(exc)}))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result))
