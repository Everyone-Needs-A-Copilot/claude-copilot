"""Entry store: read/write UUID-named markdown files for memory entries.

Source of truth is the .md files; SQLite is a local-only search cache.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from cc.core.entry_format import (
    EntryValidationError,
    build_frontmatter,
    parse_frontmatter,
    parse_tags,
    render_entry,
    validate_entry_type,
)

_GITIGNORE_CONTENT = "memory.db\nmemory.db-shm\nmemory.db-wal\n"


def _git_root() -> Path | None:
    """Return the git repository root, or None if not inside a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def resolve_memory_root(scope: str) -> Path:
    """
    Resolve the memory root directory for a given scope.

    - "project": <git root>/.claude/memory/
    - "global":  ~/.claude/memory/
    """
    if scope == "project":
        root = _git_root()
        if root is None:
            raise ValueError(
                "Cannot resolve project scope: not inside a git repository."
            )
        return root / ".claude" / "memory"
    if scope == "global":
        return Path.home() / ".claude" / "memory"
    raise ValueError(f"Unknown scope {scope!r}. Must be 'project' or 'global'.")


def default_scope() -> str:
    """Return 'project' if inside a git repo, else 'global'."""
    return "project" if _git_root() is not None else "global"


def entries_dir(memory_root: Path) -> Path:
    return memory_root / "entries"


def _ensure_entries_dir(memory_root: Path) -> Path:
    """Create entries/ and .gitignore on first use."""
    e_dir = entries_dir(memory_root)
    e_dir.mkdir(parents=True, exist_ok=True)

    gitignore = memory_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")

    return e_dir


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via tmpfile + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def store_entry(
    *,
    entry_type: str,
    content: str,
    tags: list[str] | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """
    Write a new memory entry to disk.

    Returns {"id": <uuid>, "path": <str>}.
    """
    resolved_scope = scope or default_scope()
    validate_entry_type(entry_type)
    tag_list = parse_tags(tags or [])

    entry_id = str(uuid.uuid4())
    memory_root = resolve_memory_root(resolved_scope)
    e_dir = _ensure_entries_dir(memory_root)

    fm = build_frontmatter(
        entry_id=entry_id,
        entry_type=entry_type,
        tags=tag_list,
        scope=resolved_scope,
    )
    file_text = render_entry(fm, content)
    entry_path = e_dir / f"{entry_id}.md"
    _atomic_write(entry_path, file_text)

    return {"id": entry_id, "path": str(entry_path)}


def _find_entry_path(memory_root: Path, entry_id: str) -> Path | None:
    """Locate an entry by full or prefix UUID match."""
    e_dir = entries_dir(memory_root)
    if not e_dir.exists():
        return None

    # Exact match first
    exact = e_dir / f"{entry_id}.md"
    if exact.exists():
        return exact

    # Prefix match
    matches = [
        p for p in e_dir.iterdir() if p.name.startswith(entry_id) and p.suffix == ".md"
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous prefix {entry_id!r} matches {len(matches)} entries."
        )
    return None


def get_entry(entry_id: str, scope: str | None = None) -> dict[str, Any] | None:
    """
    Read a memory entry by full or prefix UUID.

    Returns parsed dict or None if not found.
    """
    resolved_scope = scope or default_scope()
    memory_root = resolve_memory_root(resolved_scope)
    path = _find_entry_path(memory_root, entry_id)
    if path is None:
        return None

    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    return {**fm, "content": body, "path": str(path)}


def list_entries(
    *,
    scope: str | None = None,
    entry_type: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """
    List entries, optionally filtered by type and/or tag.
    """
    resolved_scope = scope or default_scope()
    memory_root = resolve_memory_root(resolved_scope)
    e_dir = entries_dir(memory_root)
    if not e_dir.exists():
        return []

    results = []
    for path in sorted(e_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)
        except (EntryValidationError, OSError):
            continue

        if entry_type and fm.get("type") != entry_type:
            continue
        if tag:
            entry_tags = fm.get("tags") or []
            if tag not in entry_tags:
                continue

        results.append({**fm, "content": body, "path": str(path)})

    return results


def delete_entry(entry_id: str, scope: str | None = None) -> bool:
    """
    Delete a memory entry by full or prefix UUID.

    Returns True if deleted, False if not found.
    """
    resolved_scope = scope or default_scope()
    memory_root = resolve_memory_root(resolved_scope)
    path = _find_entry_path(memory_root, entry_id)
    if path is None:
        return False

    path.unlink()
    return True


def search_entries_files(
    query: str,
    *,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    """
    Keyword search across entry content + frontmatter (file-based, no SQLite needed).

    Case-insensitive substring match across the full file text.
    """
    resolved_scope = scope or default_scope()
    memory_root = resolve_memory_root(resolved_scope)
    e_dir = entries_dir(memory_root)
    if not e_dir.exists():
        return []

    query_lower = query.lower()
    results = []
    for path in sorted(e_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        if query_lower in text.lower():
            try:
                fm, body = parse_frontmatter(text)
            except EntryValidationError:
                continue
            results.append({**fm, "content": body, "path": str(path)})

    return results
