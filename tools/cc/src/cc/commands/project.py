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
