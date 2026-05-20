"""cc memory — memory management commands."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from cc.core.entry_store import (
    _atomic_write,
    _ensure_entries_dir,
    default_scope,
    delete_entry,
    get_entry,
    list_entries,
    resolve_memory_root,
    search_entries_files,
    store_entry,
)
from cc.core.memory_index import (
    index_entry,
    index_status,
    rebuild_index,
    remove_from_index,
    search_index,
)

_log = logging.getLogger(__name__)

memory_app = typer.Typer(
    name="memory",
    help="Manage persistent memory entries (store, get, list, delete, search, index).",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


def _resolve_scope(scope: Optional[str]) -> str:
    return scope or default_scope()


@memory_app.command("store")
def memory_store(
    content: str = typer.Argument(..., help="Memory content to store."),
    entry_type: str = typer.Option(
        "context",
        "--type",
        "-t",
        help="Entry type: decision|context|lesson|reference|person",
    ),
    tags: Optional[str] = typer.Option(
        None,
        "--tags",
        help="Comma-separated tags, e.g. --tags auth,security",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        help="Scope: project (default if in git repo) or global.",
    ),
    output_json: bool = typer.Option(False, "--json", help="Output result as JSON."),
) -> None:
    """Store a new memory entry as a UUID-named markdown file."""
    from cc.core.entry_format import parse_tags

    tag_list = parse_tags(tags or "")
    resolved_scope = _resolve_scope(scope)

    try:
        result = store_entry(
            entry_type=entry_type,
            content=content,
            tags=tag_list,
            scope=resolved_scope,
        )
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    # Update index (first-class incremental: auto-creates DB on first write)
    # Never blocks the file write — errors are logged at DEBUG, not swallowed silently.
    memory_root = resolve_memory_root(resolved_scope)
    try:
        index_entry(result["id"], entry_type, tag_list, content, memory_root)
    except Exception as exc:
        _log.debug("Incremental index update failed for %s: %s", result["id"], exc)

    if output_json:
        typer.echo(json.dumps(result))
    else:
        console.print(f"[green]Stored[/green] {result['id']}")
        console.print(f"Path: {result['path']}")


@memory_app.command("get")
def memory_get(
    entry_id: str = typer.Argument(..., help="Entry UUID (full or prefix)."),
    scope: Optional[str] = typer.Option(None, "--scope", "-s"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Retrieve a memory entry by UUID (full or prefix match)."""
    resolved_scope = _resolve_scope(scope)

    try:
        entry = get_entry(entry_id, scope=resolved_scope)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if entry is None:
        err_console.print(f"[yellow]Not found:[/yellow] {entry_id}")
        raise typer.Exit(1)

    if output_json:
        typer.echo(json.dumps(entry))
    else:
        console.print(f"[bold]{entry.get('id')}[/bold]  [{entry.get('type')}]")
        console.print(f"Tags: {', '.join(entry.get('tags') or []) or '(none)'}")
        console.print(f"Created: {entry.get('created')}  Updated: {entry.get('updated')}")
        console.print()
        console.print(entry.get("content", "").strip())


@memory_app.command("list")
def memory_list(
    entry_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type."),
    tag: Optional[str] = typer.Option(None, "--tags", help="Filter by tag."),
    scope: Optional[str] = typer.Option(None, "--scope", "-s"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List memory entries, optionally filtered by type or tag."""
    resolved_scope = _resolve_scope(scope)

    try:
        entries = list_entries(scope=resolved_scope, entry_type=entry_type, tag=tag)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if output_json:
        typer.echo(json.dumps(entries))
        return

    if not entries:
        console.print("[dim]No entries found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID (prefix)", style="cyan", no_wrap=True)
    table.add_column("Type")
    table.add_column("Tags")
    table.add_column("Created")

    for e in entries:
        table.add_row(
            e.get("id", "")[:8],
            e.get("type", ""),
            ", ".join(e.get("tags") or []),
            e.get("created", ""),
        )

    console.print(table)


@memory_app.command("delete")
def memory_delete(
    entry_id: str = typer.Argument(..., help="Entry UUID (full or prefix)."),
    scope: Optional[str] = typer.Option(None, "--scope", "-s"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a memory entry file."""
    resolved_scope = _resolve_scope(scope)

    if not yes:
        typer.confirm(f"Delete entry {entry_id}?", abort=True)

    try:
        memory_root = resolve_memory_root(resolved_scope)
        deleted = delete_entry(entry_id, scope=resolved_scope)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not deleted:
        err_console.print(f"[yellow]Not found:[/yellow] {entry_id}")
        raise typer.Exit(1)

    # Remove from index too (best-effort: DB may not exist yet)
    try:
        remove_from_index(entry_id, memory_root)
    except Exception as exc:
        _log.debug("Incremental index remove failed for %s: %s", entry_id, exc)

    console.print(f"[green]Deleted[/green] {entry_id}")


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query."),
    scope: Optional[str] = typer.Option(None, "--scope", "-s"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Search memory entries (FTS index when available, file-based fallback)."""
    resolved_scope = _resolve_scope(scope)

    try:
        memory_root = resolve_memory_root(resolved_scope)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    # Prefer SQLite FTS when index exists
    results = search_index(query, memory_root)
    used_index = bool(results) or (memory_root / "memory.db").exists()

    if not used_index:
        results = search_entries_files(query, scope=resolved_scope)
    elif not results:
        # DB exists but returned nothing — also try file fallback so partial-index gaps don't hide results
        results = search_entries_files(query, scope=resolved_scope)

    if output_json:
        typer.echo(json.dumps(results))
        return

    if not results:
        console.print("[dim]No results.[/dim]")
        return

    for entry in results:
        console.print(f"[bold cyan]{entry.get('id', '')[:8]}[/bold cyan]  [{entry.get('type', '')}]  {', '.join(entry.get('tags') or [])}")
        snippet = (entry.get("content") or "").strip()[:120]
        console.print(f"  {snippet}")
        console.print()


@memory_app.command("index")
def memory_index(
    rebuild: bool = typer.Option(False, "--rebuild", help="Rebuild the FTS index from files."),
    status: bool = typer.Option(False, "--status", help="Show index freshness."),
    scope: Optional[str] = typer.Option(None, "--scope", "-s"),
) -> None:
    """Manage the SQLite FTS search index (local cache, gitignored)."""
    if not rebuild and not status:
        err_console.print("[red]Error:[/red] Pass --rebuild or --status.")
        raise typer.Exit(1)

    resolved_scope = _resolve_scope(scope)

    try:
        memory_root = resolve_memory_root(resolved_scope)
    except ValueError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if rebuild:
        stats = rebuild_index(memory_root)
        console.print(f"[green]Index rebuilt.[/green] Indexed: {stats['indexed']}  Errors: {stats['errors']}")
        if "vectors_recomputed" in stats:
            console.print(f"  Vectors recomputed: {stats['vectors_recomputed']}")

    if status:
        info = index_status(memory_root)
        sync_label = "[green]in sync[/green]" if info["in_sync"] else "[yellow]out of sync[/yellow]"
        console.print(
            f"Files: {info['files']}  Indexed: {info['indexed']}  Status: {sync_label}"
        )
        # Embedding-specific fields (present only when EmbeddingBackend active)
        if "embedding_model" in info:
            model_label = info["embedding_model"]
            vec_sync = "[green]in sync[/green]" if info.get("vectors_in_sync") else "[yellow]out of sync[/yellow]"
            console.print(
                f"  Backend: embedding  Model: {model_label}"
                f"  Vectors: {info.get('vectors', 0)}  Vectors: {vec_sync}"
            )
        else:
            console.print("  Backend: fts5 (embedding disabled)")
        if not info["in_sync"]:
            raise typer.Exit(3)


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

# Old SQLite types → new entry format types
_TYPE_MAP: dict[str, str] = {
    "decision": "decision",
    "lesson": "lesson",
    "context": "context",
    "discussion": "context",
    "file": "reference",
    "initiative": "context",
    "agent_improvement": "lesson",
}

_LEGACY_MEMORY_DIR = Path.home() / ".claude" / "memory"


def _find_legacy_dbs() -> list[Path]:
    """Scan ~/.claude/memory/*/memory.db for legacy copilot-memory databases."""
    if not _LEGACY_MEMORY_DIR.exists():
        return []
    return sorted(_LEGACY_MEMORY_DIR.glob("*/memory.db"))


def _count_entries(db_path: Path) -> int:
    """Return the number of rows in the memories table."""
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        finally:
            conn.close()
        return count
    except Exception:
        return 0


def _read_legacy_entries(db_path: Path) -> list[dict]:
    """Read all rows from the memories table of a legacy database."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, content, type, tags, metadata, created_at, updated_at, project_id "
            "FROM memories ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _existing_content_hashes(entries_path: Path) -> set[str]:
    """Collect SHA-256 hashes of all existing entry content bodies."""
    from cc.core.entry_format import parse_frontmatter, EntryValidationError

    hashes: set[str] = set()
    if not entries_path.exists():
        return hashes
    for md_file in entries_path.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
            _, body = parse_frontmatter(text)
            hashes.add(_content_hash(body.strip()))
        except (EntryValidationError, OSError):
            continue
    return hashes


def _migrate_entries(
    rows: list[dict],
    scope: str,
    dry_run: bool,
) -> dict[str, int]:
    """
    Migrate a list of legacy memory rows to UUID .md files.

    Returns {"migrated": n, "skipped": n, "errors": n}.
    """
    from cc.core.entry_format import build_frontmatter, render_entry, parse_tags

    memory_root = resolve_memory_root(scope)
    entries_path = memory_root / "entries"
    existing_hashes = _existing_content_hashes(entries_path)

    migrated = 0
    skipped = 0
    errors = 0

    for row in rows:
        raw_content = (row.get("content") or "").strip()
        if not raw_content:
            skipped += 1
            continue

        ch = _content_hash(raw_content)
        if ch in existing_hashes:
            skipped += 1
            continue

        # Map old type to new type
        old_type = (row.get("type") or "context").lower()
        new_type = _TYPE_MAP.get(old_type, "context")

        # Parse tags — stored as JSON array string in old schema
        raw_tags = row.get("tags") or "[]"
        try:
            tag_list = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
            if not isinstance(tag_list, list):
                tag_list = []
        except (json.JSONDecodeError, TypeError):
            tag_list = []
        tag_list = sorted(str(t).strip() for t in tag_list if str(t).strip())

        created_at = row.get("created_at") or ""
        updated_at = row.get("updated_at") or ""

        # Reuse original id if it looks like a UUID, else generate new one
        import re
        import uuid as _uuid
        original_id = row.get("id") or ""
        if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", original_id, re.IGNORECASE):
            entry_id = original_id
        else:
            entry_id = str(_uuid.uuid4())

        if dry_run:
            console.print(
                f"  [dim]would migrate[/dim] [cyan]{entry_id[:8]}[/cyan]  "
                f"[{new_type}]  {raw_content[:60]!r}"
            )
            existing_hashes.add(ch)
            migrated += 1
            continue

        try:
            e_dir = _ensure_entries_dir(memory_root)
            fm = build_frontmatter(
                entry_id=entry_id,
                entry_type=new_type,
                tags=tag_list,
                scope=scope,
                created=created_at or None,
                updated=updated_at or None,
            )
            file_text = render_entry(fm, raw_content)
            _atomic_write(e_dir / f"{entry_id}.md", file_text)
            existing_hashes.add(ch)
            migrated += 1
        except Exception as exc:
            err_console.print(f"  [red]Error[/red] migrating {entry_id[:8]}: {exc}")
            errors += 1

    return {"migrated": migrated, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# cc memory migrate command
# ---------------------------------------------------------------------------

@memory_app.command("migrate")
def memory_migrate(
    from_global: bool = typer.Option(
        False,
        "--from-global",
        help="Migrate from legacy ~/.claude/memory/*/memory.db databases.",
    ),
    show_status: bool = typer.Option(
        False,
        "--status",
        help="Show migration status: source DB entry count vs existing .md files.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be migrated without writing files.",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        "-s",
        help="Target scope: project (default if in git repo) or global.",
    ),
    all_dbs: bool = typer.Option(
        False,
        "--all",
        help="Migrate from all discovered legacy databases without prompting.",
    ),
) -> None:
    """Migrate legacy copilot-memory SQLite entries to the new file-per-entry format."""
    if not from_global and not show_status:
        err_console.print("[red]Error:[/red] Pass --from-global or --status.")
        raise typer.Exit(1)

    if show_status:
        dbs = _find_legacy_dbs()
        if not dbs:
            console.print("[dim]No legacy databases found in ~/.claude/memory/.[/dim]")
        else:
            for db_path in dbs:
                count = _count_entries(db_path)
                console.print(f"  [cyan]{db_path}[/cyan]  entries: {count}")

        resolved_scope = _resolve_scope(scope)
        try:
            memory_root = resolve_memory_root(resolved_scope)
        except ValueError:
            memory_root = None

        if memory_root is not None:
            entries_path = memory_root / "entries"
            existing = len(list(entries_path.glob("*.md"))) if entries_path.exists() else 0
            console.print(f"\nTarget ({resolved_scope}): {memory_root / 'entries'}  files: {existing}")
        return

    # --from-global migration flow
    dbs = _find_legacy_dbs()
    if not dbs:
        console.print("[yellow]No legacy databases found in ~/.claude/memory/.[/yellow]")
        raise typer.Exit(0)

    # Select which DB(s) to migrate
    selected_dbs: list[Path]
    if all_dbs or len(dbs) == 1:
        selected_dbs = dbs
    else:
        console.print("[bold]Multiple legacy databases found:[/bold]")
        for i, db_path in enumerate(dbs, 1):
            count = _count_entries(db_path)
            console.print(f"  {i}. {db_path}  ({count} entries)")
        raw = typer.prompt("Enter number(s) to migrate (comma-separated, or 'all')")
        if raw.strip().lower() == "all":
            selected_dbs = dbs
        else:
            chosen: list[Path] = []
            for token in raw.split(","):
                token = token.strip()
                try:
                    idx = int(token) - 1
                    if 0 <= idx < len(dbs):
                        chosen.append(dbs[idx])
                    else:
                        err_console.print(f"[red]Invalid selection:[/red] {token}")
                        raise typer.Exit(1)
                except ValueError:
                    err_console.print(f"[red]Invalid selection:[/red] {token}")
                    raise typer.Exit(1)
            selected_dbs = chosen

    resolved_scope = _resolve_scope(scope)

    if dry_run:
        console.print(f"[bold yellow]Dry run[/bold yellow] — no files will be written. Target scope: {resolved_scope}")

    total_migrated = 0
    total_skipped = 0
    total_errors = 0

    for db_path in selected_dbs:
        console.print(f"\nMigrating [cyan]{db_path}[/cyan]…")
        try:
            rows = _read_legacy_entries(db_path)
        except Exception as exc:
            err_console.print(f"  [red]Failed to read database:[/red] {exc}")
            total_errors += 1
            continue

        stats = _migrate_entries(rows, resolved_scope, dry_run)
        total_migrated += stats["migrated"]
        total_skipped += stats["skipped"]
        total_errors += stats["errors"]
        console.print(
            f"  migrated: {stats['migrated']}  "
            f"skipped (duplicates/empty): {stats['skipped']}  "
            f"errors: {stats['errors']}"
        )

    console.print(
        f"\n[bold]Total:[/bold] migrated={total_migrated}  "
        f"skipped={total_skipped}  errors={total_errors}"
    )
    if total_errors:
        raise typer.Exit(1)
