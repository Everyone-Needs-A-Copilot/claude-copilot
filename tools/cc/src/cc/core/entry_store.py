"""Entry store: read/write UUID-named markdown files for memory entries.

Source of truth is the .md files; SQLite is a local-only search cache.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from cc.core.content_guard import scan_and_neutralize
from cc.core.entry_format import (
    EntryValidationError,
    build_frontmatter,
    parse_frontmatter,
    parse_tags,
    render_entry,
    validate_entry_type,
)
from cc.core.write_guard import assert_write_is_isolated

_GITIGNORE_CONTENT = "memory.db\nmemory.db-shm\nmemory.db-wal\n"

# Overrides the "global" memory root (normally `~/.claude/memory`). Honored
# by `resolve_memory_root("global")` below -- the SAME env-var-seam idiom
# `core/config_paths.py`'s `CC_MACHINE_ROOT` already uses for
# `machine_config_path()`/`machine_secrets_path()`, applied here for the
# identical reason: this function is reached through a long fan-out call
# chain (commands/memory.py, commands/mcp_serve.py, core/memory_index.py,
# core/locking.py's `lock_path()`, core/ecosystem/lockfile.py, and more --
# see git blame / D2 for the full list), so a `_root` keyword-injection
# convention would need threading through every one of those call sites
# (present and future) to actually reach this module. A single
# process-wide env var closes the seam at its one true source instead.
#
# Unlike `CC_MACHINE_ROOT`, this seam did NOT exist before this fix: no test
# exercised `scope="global"` for real (tests only ever patched `_git_root`,
# which affects `scope="project"`), so nothing caught `resolve_memory_root`
# resolving straight to the developer's real `~/.claude/memory` -- a
# directory that, unlike the machine config, was already known to hold real
# cross-project entries. tests/conftest.py's `_isolate_machine_config`
# fixture now also sets this env var for every test, mirroring its
# `CC_MACHINE_ROOT` handling.
_GLOBAL_MEMORY_ROOT_ENV = "CC_GLOBAL_MEMORY_ROOT"


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
    - "global":  ~/.claude/memory/ (or `CC_GLOBAL_MEMORY_ROOT` when set --
      see the module-level comment above `_GLOBAL_MEMORY_ROOT_ENV`)
    """
    if scope == "project":
        root = _git_root()
        if root is None:
            raise ValueError(
                "Cannot resolve project scope: not inside a git repository."
            )
        return root / ".claude" / "memory"
    if scope == "global":
        override = os.environ.get(_GLOBAL_MEMORY_ROOT_ENV)
        if override:
            return Path(override).expanduser()
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
    assert_write_is_isolated(e_dir)
    e_dir.mkdir(parents=True, exist_ok=True)

    gitignore = memory_root / ".gitignore"
    if not gitignore.exists():
        assert_write_is_isolated(gitignore)
        gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")

    return e_dir


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via tmpfile + rename."""
    assert_write_is_isolated(path)
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

    `content` is passed through `core.content_guard.scan_and_neutralize()`
    first: injection-shaped markup is defanged in place and secrets are
    redacted, never silently dropped. The write always proceeds -- on a
    scanner error the ORIGINAL content is stored unscanned rather than lost,
    and the frontmatter `guard` field plus a stderr warning record what
    happened either way. Applied here (not in `commands/memory.py`) so every
    caller reaching this function -- the CLI, `cc mcp-serve`'s memory_store
    tool, and `cc.api` -- is covered, not just the CLI argument path.

    Returns {"id": <uuid>, "path": <str>, "guard": <summary token>}. `guard`
    is "clean", "modified:<pattern-id>[,...]", or "scan_error" -- surfaced
    directly to the caller, not only to a later reader of the file, so a
    programmatic caller can react to it without re-reading and re-parsing
    the entry it just wrote.
    """
    resolved_scope = scope or default_scope()
    validate_entry_type(entry_type)
    tag_list = parse_tags(tags or [])

    guard_result = scan_and_neutralize(content)
    for line in guard_result.warning_lines("content"):
        print(line, file=sys.stderr)

    entry_id = str(uuid.uuid4())
    memory_root = resolve_memory_root(resolved_scope)
    e_dir = _ensure_entries_dir(memory_root)

    fm = build_frontmatter(
        entry_id=entry_id,
        entry_type=entry_type,
        tags=tag_list,
        scope=resolved_scope,
        guard=guard_result.summary_token(),
    )
    file_text = render_entry(fm, guard_result.text)
    entry_path = e_dir / f"{entry_id}.md"
    _atomic_write(entry_path, file_text)

    return {
        "id": entry_id,
        "path": str(entry_path),
        "guard": guard_result.summary_token(),
    }


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

    assert_write_is_isolated(path)
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
