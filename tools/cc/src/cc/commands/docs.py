"""cc docs — documentation lookup commands.

Verbs
-----
  resolve <pkg> [--lang] [--json]
      Detect the installed/declared version of a package.

  get <pkg> [--topic] [--lang] [--source] [--refresh] [--json]
      Fetch documentation for a package (cache-first, layered backends).

  search <pkg> <query> [--lang] [--json]
      Search docs for a package (topic-based — thin wrapper over get).

  sources
      List registered backends and their availability.

  cache [--status | --clear [<pkg>]]
      Inspect or clear the docs cache.

Mirrors memory.py CLI conventions: Console, --json, err_console, Exit(1).
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

_log = logging.getLogger(__name__)

docs_app = typer.Typer(
    name="docs",
    help="Look up package documentation (local-first, network fallback).",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


class SourceChoice(str, Enum):
    auto = "auto"
    local = "local"
    fetch = "fetch"


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


@docs_app.command("resolve")
def docs_resolve(
    pkg: str = typer.Argument(..., help="Package name (e.g. 'react', 'requests')."),
    lang: Optional[str] = typer.Option(
        None,
        "--lang",
        "-l",
        help="Ecosystem: js|npm|python|pip  (auto-detected when omitted).",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Detect the installed/declared version of a package."""
    from cc.core.docs_resolver import detect_version

    langs = [lang] if lang else ["python", "js"]
    result = None
    for l in langs:
        result = detect_version(pkg, l)
        if result is not None:
            break

    if result is None:
        if output_json:
            typer.echo(json.dumps({"error": f"version not found for {pkg!r}"}))
            raise typer.Exit(1)
        err_console.print(f"[yellow]Version not found:[/yellow] {pkg}")
        raise typer.Exit(1)

    if output_json:
        typer.echo(
            json.dumps(
                {
                    "name": result.name,
                    "version": result.version,
                    "version_source": result.version_source,
                    "exact": result.exact,
                }
            )
        )
        return

    exact_label = "[green]exact[/green]" if result.exact else "[yellow]range[/yellow]"
    console.print(
        f"[bold]{result.name}[/bold]  [cyan]{result.version}[/cyan]  "
        f"{exact_label}  [dim]{result.version_source}[/dim]"
    )


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@docs_app.command("get")
def docs_get(
    pkg: str = typer.Argument(..., help="Package name."),
    topic: str = typer.Option(
        "",
        "--topic",
        "-t",
        help="Documentation topic / query string (optional).",
    ),
    lang: Optional[str] = typer.Option(
        None,
        "--lang",
        "-l",
        help="Ecosystem: js|npm|python|pip  (auto-detected when omitted).",
    ),
    source: SourceChoice = typer.Option(
        SourceChoice.auto,
        "--source",
        "-s",
        help="Backend: auto (local→fetch), local, or fetch.",
    ),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Bypass cache and fetch fresh docs."
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Fetch documentation for a package."""
    from cc.core.docs_resolver import detect_version, resolve_docs

    # Resolve version
    langs = [lang] if lang else ["python", "js"]
    version_result = None
    for l in langs:
        version_result = detect_version(pkg, l)
        if version_result is not None:
            break

    version = version_result.version if version_result else "unknown"

    # Determine source_order
    if source == SourceChoice.local:
        source_order = ["local"]
    elif source == SourceChoice.fetch:
        source_order = ["fetch"]
    else:
        source_order = None  # use config default

    result = resolve_docs(
        pkg,
        version,
        topic or pkg,
        source_order=source_order,
        refresh=refresh,
    )

    if result is None:
        if output_json:
            typer.echo(json.dumps({"error": f"no docs found for {pkg!r}"}))
            raise typer.Exit(1)
        err_console.print(f"[yellow]No docs found:[/yellow] {pkg}")
        raise typer.Exit(1)

    if output_json:
        typer.echo(
            json.dumps(
                {
                    "package": result.package,
                    "version": result.version,
                    "topic": result.topic,
                    "source": result.source,
                    "cached": result.cached,
                    "url": result.url,
                    "metadata": result.metadata,
                    "content": result.content,
                }
            )
        )
        return

    cached_label = " [dim](cached)[/dim]" if result.cached else ""
    console.print(
        f"[bold]{result.package}[/bold] [cyan]{result.version}[/cyan]"
        f"  source=[green]{result.source}[/green]{cached_label}"
    )
    if result.url:
        console.print(f"[dim]{result.url}[/dim]")
    console.print()
    console.print(result.content)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@docs_app.command("search")
def docs_search(
    pkg: str = typer.Argument(..., help="Package name."),
    query: str = typer.Argument(..., help="Search query / topic."),
    lang: Optional[str] = typer.Option(None, "--lang", "-l"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Search package documentation for a query topic."""
    from cc.core.docs_resolver import detect_version, resolve_docs

    langs = [lang] if lang else ["python", "js"]
    version_result = None
    for l in langs:
        version_result = detect_version(pkg, l)
        if version_result is not None:
            break

    version = version_result.version if version_result else "unknown"

    result = resolve_docs(pkg, version, query)

    if result is None:
        if output_json:
            typer.echo(json.dumps({"error": f"no docs found for {pkg!r} / {query!r}"}))
            raise typer.Exit(1)
        err_console.print(f"[yellow]No docs found:[/yellow] {pkg} / {query}")
        raise typer.Exit(1)

    if output_json:
        typer.echo(
            json.dumps(
                {
                    "package": result.package,
                    "version": result.version,
                    "topic": result.topic,
                    "source": result.source,
                    "cached": result.cached,
                    "content": result.content,
                }
            )
        )
        return

    console.print(
        f"[bold]{result.package}[/bold] [cyan]{result.version}[/cyan]"
        f"  topic=[dim]{result.topic}[/dim]  source=[green]{result.source}[/green]"
    )
    console.print()
    # Show a snippet (first 1000 chars) for search results
    content = result.content
    if len(content) > 1000:
        content = content[:1000] + "\n\n[dim]… (truncated)[/dim]"
    console.print(content)


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


@docs_app.command("sources")
def docs_sources(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List registered documentation source backends and their availability."""
    from cc.core.docs_resolver import _BACKEND_REGISTRY

    rows = []
    for key, backend in _BACKEND_REGISTRY.items():
        try:
            avail = backend.available
        except Exception:
            avail = False
        rows.append({"name": key, "available": avail})

    if output_json:
        typer.echo(json.dumps(rows))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Backend", style="cyan")
    table.add_column("Available")

    for row in rows:
        avail_label = "[green]yes[/green]" if row["available"] else "[red]no[/red]"
        table.add_row(row["name"], avail_label)

    console.print(table)


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------


@docs_app.command("cache")
def docs_cache(
    pkg: Optional[str] = typer.Argument(
        None,
        help="Package to operate on (optional — omit for all packages).",
    ),
    status: bool = typer.Option(False, "--status", help="Show cache statistics."),
    clear: bool = typer.Option(False, "--clear", help="Clear cached entries."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect or clear the docs cache.

    Examples:

        cc docs cache --status          # show totals
        cc docs cache --clear           # clear all
        cc docs cache --clear requests  # not yet supported (pkg-specific clear TBD)
    """
    if not status and not clear:
        err_console.print("[red]Error:[/red] Pass --status or --clear.")
        raise typer.Exit(1)

    from cc.core.docs_cache import cache_clear, cache_stats

    if status:
        stats = cache_stats()
        if output_json:
            typer.echo(json.dumps(stats))
        else:
            console.print(
                f"[bold]Cache:[/bold]  total={stats['total']}  "
                f"fresh=[green]{stats['fresh']}[/green]  "
                f"expired=[yellow]{stats['expired']}[/yellow]"
            )

    if clear:
        deleted = cache_clear()
        if output_json:
            typer.echo(json.dumps({"deleted": deleted}))
        else:
            console.print(f"[green]Cleared[/green] {deleted} cache entries.")
