"""cc config — two-layer configuration management commands."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from cc.core.config import (
    get_resolved_config,
    load_machine_config,
    load_project_config,
    resolve_key,
    unset_config,
    where_key,
    write_config,
    _flatten,
)
from cc.core.config_paths import (
    machine_config_path,
    project_config_path,
)

config_app = typer.Typer(
    name="config",
    help="Manage cc configuration (get, set, list, where, validate, edit, init, doctor, export).",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)

# Default template written by cc config init
_MACHINE_TEMPLATE = {
    "$schema": "cc-config-v1",
    "version": 1,
    "paths": {
        "memory": "~/.claude/memory",
        "shared_docs": None,
        "knowledge_repo": None,
        "global_skills_dir": "~/.claude/skills",
        "embedding_cache": "~/.claude/cache/models",
    },
    "memory": {
        "embedding_model": "none",
        "default_threshold": 0.7,
    },
    "skills": {
        "cache_ttl_hours": 24,
    },
    "telemetry": {
        "enabled": False,
    },
}

_PROJECT_TEMPLATE = {
    "$schema": "cc-config-v1",
    "version": 1,
    "paths": {
        "shared_docs": "@machine",
        "knowledge_repo": "@machine",
    },
}


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Dotted config key (e.g. paths.shared_docs)."),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="Restrict to: machine | project | effective (default).",
    ),
    raw: bool = typer.Option(
        False, "--raw", help="Print raw value without formatting."
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Get a resolved configuration value."""
    value = resolve_key(key, scope=scope)

    if output_json:
        typer.echo(json.dumps({"key": key, "value": value}))
        return

    if raw:
        if value is None:
            raise typer.Exit(1)
        typer.echo(str(value))
        return

    if value is None:
        console.print(f"[dim]{key}[/dim]: [italic]not set[/italic]")
    else:
        console.print(f"[cyan]{key}[/cyan]: {value}")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Dotted config key."),
    value: str = typer.Argument(..., help="Value to set."),
    project: bool = typer.Option(
        False,
        "--project",
        help="Write to project config instead of machine config.",
    ),
) -> None:
    """Set a configuration value (machine config by default)."""
    try:
        written_path = write_config(key, value, project=project)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    layer = "project" if project else "machine"
    console.print(f"[green]Set[/green] {key} = {value!r}  ({layer}: {written_path})")


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(..., help="Dotted config key to remove."),
    project: bool = typer.Option(
        False, "--project", help="Remove from project config."
    ),
) -> None:
    """Remove a key from machine or project config."""
    try:
        removed = unset_config(key, project=project)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not removed:
        err_console.print(f"[yellow]Key not found:[/yellow] {key}")
        raise typer.Exit(1)

    layer = "project" if project else "machine"
    console.print(f"[green]Unset[/green] {key} ({layer})")


@config_app.command("list")
def config_list(
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="Show: machine | project | effective (default).",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List configuration keys and values with source annotation."""
    if scope == "machine":
        data = {
            k: v
            for k, v in _flatten(load_machine_config()).items()
            if k not in ("$schema", "version")
        }
        source_label = "machine"
    elif scope == "project":
        data = {
            k: v
            for k, v in _flatten(load_project_config()).items()
            if k not in ("$schema", "version")
        }
        source_label = "project"
    else:
        data = get_resolved_config()
        source_label = "effective"

    if output_json:
        typer.echo(json.dumps(data))
        return

    if not data:
        console.print("[dim]No configuration found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value")
    if scope is None:
        table.add_column("Source", style="dim")

    for k in sorted(data.keys()):
        v = data[k]
        display_val = str(v) if v is not None else "[dim]not set[/dim]"
        if scope is None:
            info = where_key(k)
            table.add_row(k, display_val, info["source"])
        else:
            table.add_row(k, display_val)

    console.print(table)


@config_app.command("where")
def config_where(
    key: str = typer.Argument(..., help="Dotted config key."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show which config layer provides a key's value."""
    info = where_key(key)

    if output_json:
        typer.echo(json.dumps(info))
        return

    console.print(f"[cyan]{key}[/cyan]")
    console.print(f"  value:  {info['value']}")
    console.print(f"  source: [bold]{info['source']}[/bold]")
    console.print(f"  reason: {info['reason']}")


@config_app.command("validate")
def config_validate(
    scope: str = typer.Option(
        "both", "--scope", help="Validate: machine | project | both."
    ),
) -> None:
    """Validate config files against the schema."""
    errors: list[str] = []

    if scope in ("machine", "both"):
        path = machine_config_path()
        if path.exists():
            try:
                import json as _json

                data = _json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    errors.append(
                        f"Machine config: expected object, got {type(data).__name__}"
                    )
            except _json.JSONDecodeError as exc:
                errors.append(f"Machine config JSON parse error: {exc}")
        else:
            console.print("[dim]Machine config not found (using defaults).[/dim]")

    if scope in ("project", "both"):
        path = project_config_path()
        if path and path.exists():
            try:
                import json as _json

                data = _json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    errors.append(
                        f"Project config: expected object, got {type(data).__name__}"
                    )
            except _json.JSONDecodeError as exc:
                errors.append(f"Project config JSON parse error: {exc}")
        else:
            console.print("[dim]Project config not found.[/dim]")

    if errors:
        for err in errors:
            err_console.print(f"[red]Error:[/red] {err}")
        raise typer.Exit(3)

    console.print("[green]Config valid.[/green]")


@config_app.command("edit")
def config_edit(
    project: bool = typer.Option(False, "--project", help="Edit project config."),
) -> None:
    """Open the config file in $EDITOR."""
    if project:
        path = project_config_path()
        if path is None:
            err_console.print("[red]Error:[/red] Not inside a git repository.")
            raise typer.Exit(1)
    else:
        path = machine_config_path()

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        template = _PROJECT_TEMPLATE if project else _MACHINE_TEMPLATE
        path.write_text(json.dumps(template, indent=2), encoding="utf-8")

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
    subprocess.run([editor, str(path)])


@config_app.command("init")
def config_init(
    machine: bool = typer.Option(
        False, "--machine", help="Create machine config template."
    ),
    project: bool = typer.Option(
        False, "--project", help="Create project config template."
    ),
) -> None:
    """Write a default config template to machine or project config."""
    if not machine and not project:
        # Default: machine
        machine = True

    if machine:
        path = machine_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            console.print(f"[yellow]Already exists:[/yellow] {path}")
        else:
            path.write_text(json.dumps(_MACHINE_TEMPLATE, indent=2), encoding="utf-8")
            console.print(f"[green]Created[/green] machine config: {path}")

    if project:
        cfg_path = project_config_path()
        if cfg_path is None:
            err_console.print("[red]Error:[/red] Not inside a git repository.")
            raise typer.Exit(1)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        if cfg_path.exists():
            console.print(f"[yellow]Already exists:[/yellow] {cfg_path}")
        else:
            cfg_path.write_text(
                json.dumps(_PROJECT_TEMPLATE, indent=2), encoding="utf-8"
            )
            console.print(f"[green]Created[/green] project config: {cfg_path}")


@config_app.command("export")
def config_export(
    machine: bool = typer.Option(
        False, "--machine", help="Export machine config only."
    ),
    mask_secrets: bool = typer.Option(
        False, "--mask-secrets", help="Mask secret values."
    ),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Export the effective (or machine-only) config for sharing or debugging."""
    if machine:
        data = {
            k: v
            for k, v in _flatten(load_machine_config()).items()
            if k not in ("$schema", "version")
        }
    else:
        data = get_resolved_config()

    if mask_secrets:
        for k in list(data.keys()):
            if any(
                word in k.lower()
                for word in ("secret", "token", "password", "key", "url")
            ):
                if data[k] is not None:
                    data[k] = "***"

    if output_json:
        typer.echo(json.dumps(data))
        return

    for k in sorted(data.keys()):
        v = data[k]
        typer.echo(f"{k}={v}")


@config_app.command("doctor")
def config_doctor() -> None:
    """Run config health checks: paths, files, gitignore, permissions."""
    from cc.commands.doctor import run_doctor

    result = run_doctor()

    if result.errors:
        for msg in result.errors:
            err_console.print(f"[red]Error:[/red] {msg}")
        for msg in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {msg}")
        raise typer.Exit(3)

    if result.warnings:
        for msg in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {msg}")
        raise typer.Exit(1)

    console.print("[green]All config checks passed.[/green]")
