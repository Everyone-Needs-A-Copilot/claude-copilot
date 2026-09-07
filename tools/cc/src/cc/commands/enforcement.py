"""Shared policy CLI; host-specific adapters own lifecycle decisions."""
import json
from pathlib import Path
import sys
import re
from typing import Optional

import typer

from cc.core.enforcement import evaluate

enforcement_app = typer.Typer(help="Evaluate shared safety policy without executing commands.")


@enforcement_app.command("status")
def status_cmd(
    project: Path = typer.Option(Path("."), "--project"),
    codex: str = typer.Option("codex", "--codex"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect discovery and trust; does not activate hooks or claim live coverage."""
    from cc.core.enforcement_status import codex_status
    try:
        result = codex_status(project.resolve(), codex)
    except Exception as exc:
        typer.echo(json.dumps({"status": "unavailable", "runtime_enforcement": "unverified",
                               "error_type": type(exc).__name__}))
        raise typer.Exit(2)
    typer.echo(json.dumps(result))
    if result["status"] != "discovered" or result.get("errors"):
        raise typer.Exit(1)


@enforcement_app.command("evaluate")
def evaluate_cmd(
    rules: Optional[Path] = typer.Option(None, "--rules", help="Explicit shared security-rules.json path."),
    destructive_action: str = typer.Option("block", "--destructive-action", help="block or warn"),
    output_json: bool = typer.Option(False, "--json", help="Machine-readable decision (also the default)."),
) -> None:
    """Read a schema-1 shell request on stdin and return allow, warn, or deny."""
    try:
        if rules is None:
            from cc.core.config import resolve_key
            root = resolve_key("paths.claude_copilot_root", scope="machine")
            if not isinstance(root, str) or not root:
                raise ValueError("No shared framework root configured")
            rules = Path(root) / ".claude/hooks/security-rules.json"
        text = sys.stdin.read(1_000_001)
        if len(text) > 1_000_000:
            raise ValueError("Enforcement request exceeds input limit")
        result = evaluate(json.loads(text), rules, destructive_action=destructive_action)
    except (OSError, ValueError, TypeError, re.error) as exc:
        # Never echo the command/payload: it may contain credentials.
        typer.echo(json.dumps({"schema_version": 1, "decision": "error",
                               "reason": "Shared safety evaluation unavailable",
                               "error_type": type(exc).__name__}))
        raise typer.Exit(2)
    typer.echo(json.dumps(result))
