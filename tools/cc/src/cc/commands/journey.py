"""Machine-readable production journey witness commands."""

from __future__ import annotations

import json

import typer

from cc.core.evaluation.journey_runtime import (
    begin_run,
    bind_prompt,
    inspect_run,
    pause_run,
    prepare_run,
    resume_run,
    verify_dispatch,
)

journey_app = typer.Typer(
    help="Record explicit protocol routes and actual dispatch receipts.",
    no_args_is_help=True,
)


def _emit(call) -> None:
    try:
        value = call()
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(json.dumps({"schema_version": "2.1", "error": str(exc)}))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(value))


@journey_app.command("begin")
def journey_begin(
    task: int = typer.Option(..., "--task"),
    runtime: str = typer.Option(..., "--runtime"),
    classification: str = typer.Option(..., "--classification"),
    specialists_json: str = typer.Option(..., "--specialists-json"),
    events_json: str = typer.Option(..., "--events-json"),
    prompt_sha256: str = typer.Option(..., "--prompt-sha256"),
    session: str = typer.Option(..., "--session"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    del output_json
    _emit(lambda: begin_run(
        task_id=task, runtime=runtime, classification=classification,
        specialists=json.loads(specialists_json), events=json.loads(events_json),
        prompt_sha256=prompt_sha256, session_id=session,
    ))


@journey_app.command("prepare")
def journey_prepare(
    run: str = typer.Option(..., "--run"),
    specialist: str = typer.Option(..., "--specialist"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    del output_json
    _emit(lambda: prepare_run(run, specialist).public_dict())


@journey_app.command("inspect")
def journey_inspect(
    run: str = typer.Option(..., "--run"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    del output_json
    _emit(lambda: inspect_run(run))


@journey_app.command("bind-prompt")
def journey_bind_prompt(
    run: str = typer.Option(..., "--run"),
    specialist: str = typer.Option(..., "--specialist"),
    prompt_sha256: str = typer.Option(..., "--prompt-sha256"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Bind the exact complete Agent prompt before PreToolUse dispatch."""
    del output_json
    _emit(lambda: bind_prompt(run, specialist, prompt_sha256))


@journey_app.command("pause")
def journey_pause(
    run: str = typer.Option(..., "--run"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    del output_json
    _emit(lambda: pause_run(run))


@journey_app.command("resume")
def journey_resume(
    task: int = typer.Option(..., "--task"),
    run: str | None = typer.Option(None, "--run"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    del output_json
    _emit(lambda: resume_run(task, run_id=run))


@journey_app.command("verify-dispatch", hidden=True)
def journey_verify_dispatch(
    session: str = typer.Option(..., "--session"),
    subagent: str = typer.Option(..., "--subagent"),
    marker: str = typer.Option("", "--marker"),
    prompt_sha256: str = typer.Option(..., "--prompt-sha256"),
    knowledge_sha256: str = typer.Option("", "--knowledge-sha256"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    del output_json
    try:
        value = verify_dispatch(
            session_id=session, specialist=subagent, marker=marker,
            prompt_sha256=prompt_sha256, knowledge_sha256=knowledge_sha256,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        reason = str(exc) if str(exc) else "dispatch-verification-failed"
        typer.echo(json.dumps({
            "schema_version": "2.1", "state": "denied", "reason": reason,
            "recovery_command": "cc journey prepare --run <run> --specialist <next> --json",
        }))
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(value))
