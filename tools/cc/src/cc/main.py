"""Claude Copilot CLI — main entry point."""

from typing import Optional

import typer

from cc import __version__
from cc.commands.memory import memory_app
from cc.commands.skill import skill_app
from cc.commands.config import config_app
from cc.commands.mcp import mcp_app
from cc.core.config import resolve_key

app = typer.Typer(
    name="cc",
    help="Unified Claude Copilot CLI — memory, skills, config, and MCP in one tool.",
    no_args_is_help=True,
)

# Register subcommand groups
app.add_typer(memory_app, name="memory")
app.add_typer(skill_app, name="skill")
app.add_typer(config_app, name="config")
app.add_typer(mcp_app, name="mcp")


@app.command("env")
def env_cmd(
    include_secrets: bool = typer.Option(
        False,
        "--include-secrets",
        help="Also emit values from secrets.env files. CAUTION: exposes secrets to shell history.",
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Output JSON instead of shell exports."
    ),
) -> None:
    """Emit shell-eval-able CC_* exports for the effective config.

    Agents call:  eval "$(cc env)"
    to hydrate CC_* environment variables for the current session.
    """
    from cc.commands.env import run_env
    import json as _json

    exports = run_env(include_secrets=include_secrets, output_json=False)

    if output_json:
        typer.echo(_json.dumps(exports))
        return

    for name in sorted(exports.keys()):
        value = exports[name]
        safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
        typer.echo(f'export {name}="{safe_value}"')


@app.command("resolve")
def resolve_cmd(
    key: str = typer.Argument(
        ..., help="Dotted config key to resolve (e.g. paths.shared_docs)."
    ),
    scope: Optional[str] = typer.Option(
        None, "--scope", help="machine | project | effective"
    ),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Print the resolved value of a single config key (for template substitution)."""
    import json as _json

    value = resolve_key(key, scope=scope)

    if output_json:
        typer.echo(_json.dumps({"key": key, "value": value}))
        return

    if value is None:
        raise typer.Exit(1)

    typer.echo(str(value))


@app.command("version")
def version() -> None:
    """Show the cc version."""
    typer.echo(f"cc version {__version__}")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"cc version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show the cc version and exit.",
    ),
) -> None:
    """Claude Copilot CLI."""


if __name__ == "__main__":
    app()
