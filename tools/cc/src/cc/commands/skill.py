"""cc skill — skill discovery and retrieval commands."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

_log = logging.getLogger(__name__)

skill_app = typer.Typer(
    name="skill",
    help="Discover, search, and inspect reusable skills (SKILL.md files).",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)

# WP-372 P2.2: "knowledge" is a third scope, alongside project/machine --
# every configured paths.knowledge_repo entry's 03-ai-enabling/01-skills/
# tree (core/skill_store.py's knowledge_skill_paths()).
_VALID_SCOPES = frozenset({"project", "machine", "knowledge", "all"})


def _resolve_skill_cache_dir():
    """Real production cache dir (WP-372 P2.2), or `None` on any failure --
    a cache problem must never block `cc skill` from working. Deliberately
    NOT called by anything that runs during tests: this module's own tests
    monkeypatch `_load_all_skills` wholesale (see tests/test_skills.py's
    `patched_runner` fixture), and `core/skill_store.py`'s own tests call
    `discover_skills()`/`discover_skills_with_sources()` directly with no
    `cache_dir` (caching disabled by default) -- so this is only ever
    exercised against the real machine, never a test's tmp_path.
    """
    try:
        from cc.core.skill_cache import skill_cache_dir

        return skill_cache_dir()
    except OSError:
        _log.debug("skill cache dir resolution failed; discovery will run uncached", exc_info=True)
        return None


def _load_all_skills(scope: str = "all"):
    """Load skills according to the requested scope.

    scope values:
        "project"    — only .claude/skills/ in the current git repo
        "machine"    — only ~/.claude/skills/
        "knowledge"  — every configured paths.knowledge_repo entry's
                       03-ai-enabling/01-skills/ tree (WP-372 P2.2)
        "all"        — project + machine + knowledge
                       (resolution order: project → machine → knowledge)

    Delegates path-listing to `core/skill_store.py`'s `default_skill_paths()`
    (the single authoritative project/machine/knowledge root list --
    `cc.api`'s `skill_get`/`skill_search` use the exact same function, so
    both surfaces see the identical catalog) filtered to the requested
    scope, rather than re-implementing root discovery here.
    """
    from cc.core.skill_store import default_skill_paths, discover_skills_with_sources

    all_pairs = default_skill_paths()
    pairs = all_pairs if scope == "all" else [p for p in all_pairs if p[1] == scope]

    return discover_skills_with_sources(pairs, cache_dir=_resolve_skill_cache_dir())


def _load_trusted_skills(scope: str = "all"):
    """Map fail-closed Knowledge verification to a concise CLI error."""
    from cc.core.ecosystem.knowledge_skill_source import KnowledgeSkillSourceError

    try:
        return _load_all_skills(scope)
    except KnowledgeSkillSourceError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


def _skill_to_dict(s: Any, *, include_path: bool = True) -> dict[str, Any]:
    """Shared `--json` serialization for a `SkillMeta` (WP-372 P2.2): every
    frontmatter fact beyond the canonical named fields -- `triggers`
    (`{files: [...], keywords: [...]}`) most notably, but also anything
    else a SKILL.md declares (`allowed-tools`, `status`, ...) -- is
    surfaced so an AGENT can route from CLI-provided data. This module
    never curates which fields are "useful for routing"; it exposes what
    was declared (parse, never compute)."""
    data: dict[str, Any] = {
        "name": s.name,
        "description": s.description,
        "tags": s.tags,
        "version": s.version,
        "source": s.source,
        "triggers": s.extra.get("triggers"),
        "metadata": {k: v for k, v in s.extra.items() if k != "triggers"},
    }
    if include_path:
        data["path"] = str(s.path)
    return data


@skill_app.command("list")
def skill_list(
    scope: Optional[str] = typer.Option(
        "all",
        "--scope",
        help="Scope to scan: project | machine | knowledge | all",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all discovered skills with name and description."""
    if scope not in _VALID_SCOPES:
        err_console.print(
            f"[red]Error:[/red] --scope must be one of: {', '.join(sorted(_VALID_SCOPES))}"
        )
        raise typer.Exit(1)

    skills = _load_trusted_skills(scope)

    if output_json:
        data = [_skill_to_dict(s) for s in skills]
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
        help="Scope to scan: project | machine | knowledge | all",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Search skills by keyword (matches name, description, tags)."""
    from cc.core.skill_store import search_skills

    if scope not in _VALID_SCOPES:
        err_console.print(
            f"[red]Error:[/red] --scope must be one of: {', '.join(sorted(_VALID_SCOPES))}"
        )
        raise typer.Exit(1)

    all_skills = _load_trusted_skills(scope)
    results = search_skills(query, all_skills)

    if output_json:
        data = [_skill_to_dict(s) for s in results]
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
    name: str = typer.Argument(
        ..., help="Skill name (from frontmatter or directory name)."
    ),
    scope: Optional[str] = typer.Option(
        "all",
        "--scope",
        help="Scope to scan: project | machine | knowledge | all",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output content and provenance as JSON."),
) -> None:
    """Print the full SKILL.md content (plain text, pipeable).

    Example:
        cc skill get security
        @include <(cc skill get stride-dread)
    """
    from cc.core.skill_store import find_skill_by_name, get_skill_content_with_receipt

    skills = _load_trusted_skills(scope)
    skill = find_skill_by_name(name, skills)

    if skill is None:
        err_console.print(f"[red]Skill not found:[/red] {name!r}")
        raise typer.Exit(2)

    result = get_skill_content_with_receipt(skill)
    if output_json:
        payload = _skill_to_dict(skill, include_path=result.receipt is None)
        payload["content"] = result.content
        payload["receipt"] = (
            result.receipt.to_dict(include_content=False)
            if result.receipt is not None
            else None
        )
        typer.echo(json.dumps(payload))
        return
    # Plain text compatibility is deliberately preserved.
    sys.stdout.write(result.content)


@skill_app.command("path")
def skill_path(
    name: str = typer.Argument(
        ..., help="Skill name (from frontmatter or directory name)."
    ),
    scope: Optional[str] = typer.Option(
        "all",
        "--scope",
        help="Scope to scan: project | machine | knowledge | all",
    ),
) -> None:
    """Print the absolute path to a SKILL.md file (plain text, pipeable).

    Example:
        cc skill path stride-dread
        # → /path/to/.claude/skills/security/stride-dread/SKILL.md
        @include $(cc skill path stride-dread)
    """
    from cc.core.skill_store import find_skill_by_name, revalidate_skill_path

    skills = _load_trusted_skills(scope)
    skill = find_skill_by_name(name, skills)

    if skill is None:
        err_console.print(f"[red]Skill not found:[/red] {name!r}")
        raise typer.Exit(2)

    revalidate_skill_path(skill)

    # Plain text — deliberately no newline decoration so output is pipeable
    typer.echo(str(skill.path))
