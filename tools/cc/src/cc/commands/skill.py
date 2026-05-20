"""cc skill — skill discovery and retrieval commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

skill_app = typer.Typer(
    name="skill",
    help="Discover, search, and inspect reusable skills (SKILL.md files).",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


def _load_all_skills(scope: str = "all"):
    """Load skills according to the requested scope.

    scope values:
        "project"  — only .claude/skills/ in the current git repo
        "machine"  — only ~/.claude/skills/
        "all"      — project + machine (resolution order: project → machine)
    """
    from cc.core.skill_store import (
        _git_root,
        discover_skills_with_sources,
    )

    pairs: list[tuple[Path, str]] = []

    if scope in ("project", "all"):
        repo = _git_root()
        if repo is not None:
            project_skills = repo / ".claude" / "skills"
            if project_skills.exists():
                pairs.append((project_skills, "project"))

    if scope in ("machine", "all"):
        machine_skills = Path.home() / ".claude" / "skills"
        if machine_skills.exists():
            pairs.append((machine_skills, "machine"))

    return discover_skills_with_sources(pairs)


@skill_app.command("list")
def skill_list(
    scope: Optional[str] = typer.Option(
        "all",
        "--scope",
        help="Scope to scan: project | machine | all",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all discovered skills with name and description."""
    valid_scopes = {"project", "machine", "all"}
    if scope not in valid_scopes:
        err_console.print(f"[red]Error:[/red] --scope must be one of: {', '.join(sorted(valid_scopes))}")
        raise typer.Exit(1)

    skills = _load_all_skills(scope)

    if output_json:
        data = [
            {
                "name": s.name,
                "description": s.description,
                "tags": s.tags,
                "version": s.version,
                "source": s.source,
                "path": str(s.path),
            }
            for s in skills
        ]
        typer.echo(json.dumps(data))
        return

    if not skills:
        console.print("[dim]No skills found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Tags", style="dim")
    table.add_column("Source", style="dim", no_wrap=True)

    for skill in skills:
        table.add_row(
            skill.name,
            skill.description or "",
            ", ".join(skill.tags),
            skill.source,
        )

    console.print(table)


@skill_app.command("search")
def skill_search(
    query: str = typer.Argument(..., help="Search query (keyword match)."),
    scope: Optional[str] = typer.Option(
        "all",
        "--scope",
        help="Scope to scan: project | machine | all",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Search skills by keyword (matches name, description, tags)."""
    from cc.core.skill_store import search_skills

    valid_scopes = {"project", "machine", "all"}
    if scope not in valid_scopes:
        err_console.print(f"[red]Error:[/red] --scope must be one of: {', '.join(sorted(valid_scopes))}")
        raise typer.Exit(1)

    all_skills = _load_all_skills(scope)
    results = search_skills(query, all_skills)

    if output_json:
        data = [
            {
                "name": s.name,
                "description": s.description,
                "tags": s.tags,
                "source": s.source,
                "path": str(s.path),
            }
            for s in results
        ]
        typer.echo(json.dumps(data))
        return

    if not results:
        console.print("[dim]No matching skills.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Path", style="dim")

    for skill in results:
        table.add_row(skill.name, skill.description or "", str(skill.path))

    console.print(table)


@skill_app.command("get")
def skill_get(
    name: str = typer.Argument(..., help="Skill name (from frontmatter or directory name)."),
    scope: Optional[str] = typer.Option(
        "all",
        "--scope",
        help="Scope to scan: project | machine | all",
    ),
) -> None:
    """Print the full SKILL.md content (plain text, pipeable).

    Example:
        cc skill get security
        @include <(cc skill get stride-dread)
    """
    from cc.core.skill_store import find_skill_by_name, get_skill_content

    skills = _load_all_skills(scope)
    skill = find_skill_by_name(name, skills)

    if skill is None:
        err_console.print(f"[red]Skill not found:[/red] {name!r}")
        raise typer.Exit(2)

    # Plain text — deliberately no Rich markup so output is pipeable
    sys.stdout.write(get_skill_content(skill))


@skill_app.command("path")
def skill_path(
    name: str = typer.Argument(..., help="Skill name (from frontmatter or directory name)."),
    scope: Optional[str] = typer.Option(
        "all",
        "--scope",
        help="Scope to scan: project | machine | all",
    ),
) -> None:
    """Print the absolute path to a SKILL.md file (plain text, pipeable).

    Example:
        cc skill path stride-dread
        # → /path/to/.claude/skills/security/stride-dread/SKILL.md
        @include $(cc skill path stride-dread)
    """
    from cc.core.skill_store import find_skill_by_name

    skills = _load_all_skills(scope)
    skill = find_skill_by_name(name, skills)

    if skill is None:
        err_console.print(f"[red]Skill not found:[/red] {name!r}")
        raise typer.Exit(2)

    # Plain text — deliberately no newline decoration so output is pipeable
    typer.echo(str(skill.path))


