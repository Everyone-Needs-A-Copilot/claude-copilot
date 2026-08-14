"""cc extensions — resolve knowledge-repository agent extensions.

Replaces the nine-step hand-executed algorithm `.claude/commands/
protocol.md` used to document (read two hardcoded manifest paths, compare
ranks, verify skills, apply fallback) with one deterministic command.
See `cc.core.extensions_resolver` for the resolution/composition logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

extensions_app = typer.Typer(
    name="extensions",
    help="Resolve knowledge-repository agent extensions (override/extension/skills).",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)

# Exit code reserved for fallbackBehavior=fail -- distinct from the normal
# 0, so a caller (e.g. /protocol) can tell "resolved, apply/fallback" apart
# from "resolved, but the manifest says stop and explain the missing
# skills". Never used for a missing/malformed manifest -- those are
# skipped silently and never block invocation.
_EXIT_FALLBACK_FAIL = 3


def _discover_agent_ids(repo_root: Path) -> list[str]:
    """Agent IDs materialized in this repo's `.claude/agents/*.md` --
    the same roster `cc eval --list-agents` and the fitness check
    consult. Used only by `--all`; `--agent <id>` never needs the roster
    (an arbitrary ID resolves fine, or resolves to nothing)."""
    agents_dir = repo_root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return []
    return sorted(p.stem for p in agents_dir.glob("*.md"))


def _git_root() -> Path:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except Exception:
        return Path.cwd()


@extensions_app.command("resolve")
def extensions_resolve(
    agent: Optional[str] = typer.Option(
        None, "--agent", help="Agent ID to resolve (e.g. sd, cw, ta)."
    ),
    all_agents: bool = typer.Option(
        False, "--all", help="Resolve every agent ID found in .claude/agents/."
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Resolve the winning knowledge-repo extension for one agent (or all).

    Walks the real configured knowledge repos (CC_KNOWLEDGE_REPOS order --
    personal-over-org precedence falls out of that order), matches
    extensions[] entries by agent id, verifies requiredSkills, and applies
    fallbackBehavior. Never raises on a missing/malformed manifest.
    """
    from cc.core.config import resolve_knowledge_repos
    from cc.core.extensions_resolver import (
        ACTION_FALLBACK_FAIL,
        ExtensionSkillBindings,
        prepare_extension_source_bindings,
        resolve_extension,
    )

    if not agent and not all_agents:
        err_console.print("[red]Error:[/red] pass --agent <id> or --all")
        raise typer.Exit(2)

    agent_ids = _discover_agent_ids(_git_root()) if all_agents else [agent]  # type: ignore[list-item]

    if all_agents and not agent_ids:
        err_console.print("[yellow]No agents found under .claude/agents/ -- nothing to resolve.[/yellow]")

    knowledge_repos = resolve_knowledge_repos()
    source_bindings = prepare_extension_source_bindings(knowledge_repos)
    skill_bindings = ExtensionSkillBindings(tuple(knowledge_repos), source_bindings)
    results = [
        resolve_extension(
            a,
            knowledge_repos=knowledge_repos,
            source_bindings=source_bindings,
            skill_bindings=skill_bindings,
        )
        for a in agent_ids
    ]

    if output_json:
        payload = [r.to_dict() for r in results]
        typer.echo(json.dumps(payload if all_agents else (payload[0] if payload else {})))
    else:
        for r in results:
            if not r.matched:
                console.print(f"[dim]{r.agent}: no extension[/dim]")
                continue
            console.print(
                f"{r.agent}: [cyan]{r.type}[/cyan] from {r.source_repo} "
                f"[bold]{r.action}[/bold]"
            )
            if r.warning:
                console.print(f"  [yellow]{r.warning}[/yellow]")

    if any(r.action == ACTION_FALLBACK_FAIL for r in results):
        raise typer.Exit(_EXIT_FALLBACK_FAIL)
    raise typer.Exit(0)
