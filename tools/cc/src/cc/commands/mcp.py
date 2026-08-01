"""cc mcp — MCP server management commands."""

from __future__ import annotations

import json
import shutil
import sys

import typer

mcp_app = typer.Typer(
    name="mcp",
    help="Manage MCP server integration (serve, config).",
    no_args_is_help=True,
)


def _cc_bin_path() -> str:
    """Return the absolute path to the cc binary."""
    found = shutil.which("cc")
    if found:
        return found
    # Fallback: use sys.argv[0] (the running binary)
    return sys.argv[0]


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the cc MCP server on stdio (requires cc[mcp] extra).

    Register with Claude Code by running:
        cc mcp config
    """
    try:
        from cc.commands.mcp_serve import run_server
    except ImportError:
        typer.echo("MCP support requires: pip install 'cc[mcp]'", err=True)
        raise typer.Exit(1)

    import asyncio

    asyncio.run(run_server())


@mcp_app.command("config")
def mcp_config() -> None:
    """Print the .mcp.json snippet to register cc as an MCP server.

    Paste the output into your project's .mcp.json file:

        cc mcp config >> .mcp.json   # or paste manually
    """
    snippet = {
        "cc": {
            "command": _cc_bin_path(),
            "args": ["mcp", "serve"],
        }
    }
    typer.echo(json.dumps(snippet, indent=2))
