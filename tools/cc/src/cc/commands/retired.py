"""Refusing stubs for commands that wrote framework copies or locks into projects.

Central resolution (ADR-001, initiative 06-central-resolution) serves every project from
the release pointer, so nothing may copy framework files, per-file lock checksums or hook
registrations into a project any more. The old commands stay registered only to say so,
with a stable machine-readable error, instead of failing as "no such command" or, worse,
quietly re-copying files into a migrated project.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import typer

SCHEMA_VERSION = "1.0"
EXIT_RETIRED = 2

POINTER = "Use `cc project init` to set a project up and `cc release` to publish or roll back the framework; `cc doctor` verifies the machine."


def retired_message(command: str, detail: Optional[str] = None) -> str:
    base = f"`cc {command}` is retired: the framework is resolved centrally from the release pointer, and nothing is copied into projects."
    return f"{base} {detail + ' ' if detail else ''}{POINTER}"


def refuse(command: str, *, output_json: bool = False, detail: Optional[str] = None) -> "typer.Exit":
    """Print the retirement notice and return the Exit to raise."""
    message = retired_message(command, detail)
    if output_json:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "error": {"code": "retired", "message": message},
        }
        typer.echo(json.dumps(payload))
    else:
        typer.echo(message, err=True)
    return typer.Exit(EXIT_RETIRED)


def wants_json(args: list[str]) -> bool:
    return "--json" in args


def register_retired(app: typer.Typer, name: str, *, display: Optional[str] = None, detail: Optional[str] = None) -> None:
    """Register `name` on `app` so it refuses with any arguments and any subcommand.

    `display` is the full command shown in the message (default: `name`)."""
    shown = display or name

    @app.command(
        name,
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
        help=f"RETIRED. {retired_message(shown, detail)}",
    )
    def _retired(ctx: typer.Context) -> None:
        raise refuse(shown, output_json=wants_json(list(ctx.args)), detail=detail)
