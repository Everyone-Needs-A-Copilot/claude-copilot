"""Managed synthetic test resources. State belongs to the shared framework."""

import json
import subprocess
from pathlib import Path

import typer

from cc.core.docker_resources import PROFILES, Docker, Hold, Manager

resources_app = typer.Typer(
    no_args_is_help=True,
    help="Bound and clean newly managed synthetic Docker test servers.",
)


def invoke(action):
    try:
        return action()
    except (Hold, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        typer.echo(f"Test resources held: {exc}", err=True)
        raise typer.Exit(1) from exc


@resources_app.command(
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "allow_interspersed_args": False,
    }
)
def run(
    ctx: typer.Context,
    project: Path = typer.Option(Path(".")),
    task: str = typer.Option(...),
    profile: str = typer.Option("postgres"),
):
    """Run COMMAND after -- with a fresh server; success cleans, failure retains 48h."""
    if profile not in PROFILES:
        raise typer.BadParameter("Profile must be ops, convoco or postgres.")
    command = list(ctx.args)
    if command and command[0] == "--":
        command.pop(0)
    result = invoke(lambda: Manager().run(project, task, profile, command))
    raise typer.Exit(result)


@resources_app.command()
def status():
    """Show managed runs, ownership and live database counts (read-only)."""
    typer.echo(json.dumps(invoke(lambda: Manager().status()), indent=2))


@resources_app.command()
def capacity():
    """Measure Docker filesystem usage and enforce 70/85 percent thresholds."""
    typer.echo(json.dumps({"docker_disk_percent": invoke(lambda: Docker().capacity())}))


@resources_app.command()
def sweep():
    """Clean only expired, stopped, verified synthetic runs; report holds."""
    results = invoke(lambda: Manager().sweep())
    typer.echo(json.dumps(results, indent=2))
    if any(item["status"] == "hold" for item in results):
        raise typer.Exit(1)


@resources_app.command()
def finish(run_id: str):
    """Dispose of a stopped managed run now, after inspecting its retained evidence."""
    invoke(lambda: Manager().finish(run_id))
    typer.echo("Managed run cleaned.")


@resources_app.command("validate-env")
def validate_env(project: Path = typer.Option(Path("."))):
    """Refuse provisioning unless PG* settings match this managed test server."""
    invoke(lambda: Manager().validate_environment(project))


@resources_app.command()
def maintain():
    """Scheduled sweep and capacity audit; write a bounded local maintenance report."""
    report = invoke(lambda: Manager().maintain())
    if report.get("hold") or any(
        item["status"] == "hold" for item in report.get("sweep", [])
    ):
        raise typer.Exit(1)


@resources_app.command()
def audit():
    """Read-only database-server inventory, including unmanaged test candidates."""
    typer.echo(json.dumps(invoke(lambda: Manager().audit()), indent=2))
