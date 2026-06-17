"""cc.api — flat, importable facade for code-execution use.

This is the single documented import surface for agents running multi-step
memory and skill operations in a single python3 block.  All functions:

  - Return plain Python dicts / lists-of-dicts.
  - Raise typed exceptions (never print, never sys.exit).
  - Are import-side-effect-free: no DB opened, no FS touched at import time.

CRITICAL: cc and tc live in separate installed environments.  Keep each
code-execution block scoped to ONE tool (cc-only OR tc-only).

Usage pattern (single Bash call composing multiple ops):
    python3 - << 'PY'
    from cc.api import memory_store, memory_search, memory_list
    eid = memory_store(entry_type="decision", content="Use WAL mode for SQLite")
    results = memory_search("WAL SQLite")
    print(f"stored {eid['id'][:8]}, search returned {len(results)} hits")
    PY

For single one-shot ops, the CLI is simpler:
    cc memory search "WAL SQLite"
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class MemoryError(Exception):
    """Base exception for cc.api memory operations."""


class EntryNotFound(MemoryError):
    """Raised when a requested entry does not exist."""


class EntryValidationError(MemoryError):
    """Raised when entry data fails validation (bad type, empty content, etc.)."""


class SkillNotFound(Exception):
    """Raised when a requested skill cannot be located."""


class DocsError(Exception):
    """Base exception for cc.api docs operations."""


class DocSourceUnavailable(DocsError):
    """Raised when no backend can satisfy the request (all miss or unavailable)."""


# ---------------------------------------------------------------------------
# Memory: store / get / list / delete
# ---------------------------------------------------------------------------


def memory_store(
    *,
    entry_type: str,
    content: str,
    tags: list[str] | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Write a new memory entry to disk and (best-effort) update the FTS index.

    Returns ``{"id": "<uuid>", "path": "<abs-path>"}``.

    Raises:
        EntryValidationError: if *entry_type* is invalid or *content* is empty.
    """
    from cc.core.entry_store import store_entry
    from cc.core.entry_format import EntryValidationError as _CoreValidation

    if not content or not content.strip():
        raise EntryValidationError("content must not be empty")

    try:
        result = store_entry(
            entry_type=entry_type,
            content=content,
            tags=tags or [],
            scope=scope,
        )
    except _CoreValidation as exc:
        raise EntryValidationError(str(exc)) from exc
    except ValueError as exc:
        raise EntryValidationError(str(exc)) from exc

    # Best-effort index update (never blocks or raises)
    try:
        from cc.core.entry_store import resolve_memory_root, default_scope
        from cc.core.memory_index import index_entry
        from cc.core.entry_format import parse_tags

        resolved_scope = scope or default_scope()
        memory_root = resolve_memory_root(resolved_scope)
        db_path = memory_root / "memory.db"
        if db_path.exists():
            tag_list = parse_tags(tags or [])
            index_entry(result["id"], entry_type, tag_list, content, memory_root)
    except Exception:
        pass

    return result


def memory_get(entry_id: str, *, scope: str | None = None) -> dict[str, Any]:
    """Retrieve a memory entry by full or prefix UUID.

    Returns the entry dict (including ``"content"`` and ``"path"`` keys).

    Raises:
        EntryNotFound: if no entry with the given id exists.
        EntryValidationError: if the id prefix is ambiguous.
    """
    from cc.core.entry_store import get_entry

    try:
        entry = get_entry(entry_id, scope=scope)
    except ValueError as exc:
        raise EntryValidationError(str(exc)) from exc

    if entry is None:
        raise EntryNotFound(f"No entry found for id {entry_id!r}")

    return entry


def memory_list(
    *,
    scope: str | None = None,
    entry_type: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """List memory entries, optionally filtered by type and/or tag.

    Returns a list of entry dicts (sorted by filename, i.e. creation order).

    Raises:
        EntryValidationError: if scope is invalid.
    """
    from cc.core.entry_store import list_entries

    try:
        return list_entries(scope=scope, entry_type=entry_type, tag=tag)
    except ValueError as exc:
        raise EntryValidationError(str(exc)) from exc


def memory_delete(entry_id: str, *, scope: str | None = None) -> bool:
    """Delete a memory entry by full or prefix UUID.

    Returns ``True`` if deleted, ``False`` if not found.

    Raises:
        EntryValidationError: if the id prefix is ambiguous.
    """
    from cc.core.entry_store import delete_entry, resolve_memory_root, default_scope
    from cc.core.memory_index import remove_from_index

    try:
        deleted = delete_entry(entry_id, scope=scope)
    except ValueError as exc:
        raise EntryValidationError(str(exc)) from exc

    if deleted:
        try:
            resolved_scope = scope or default_scope()
            memory_root = resolve_memory_root(resolved_scope)
            remove_from_index(entry_id, memory_root)
        except Exception:
            pass

    return deleted


# ---------------------------------------------------------------------------
# Memory: unified search (FTS index preferred, file-based fallback)
# ---------------------------------------------------------------------------


def memory_search(
    query: str,
    *,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    """Search memory entries — FTS5 index when available, file-based fallback.

    This is the single recommended search entry point.  It mirrors the
    ``cc memory search`` CLI behaviour exactly:

    1. Try FTS5 index (SQLite BM25 ranking).
    2. If the DB doesn't exist *or* returns no results, fall back to
       case-insensitive substring search across all .md files so that
       partial-index gaps never hide results.

    Returns a list of matching entry dicts.

    Raises:
        EntryValidationError: if scope is invalid.
    """
    from cc.core.entry_store import (
        resolve_memory_root,
        default_scope,
        search_entries_files,
    )
    from cc.core.memory_index import search_index

    try:
        resolved_scope = scope or default_scope()
        memory_root = resolve_memory_root(resolved_scope)
    except ValueError as exc:
        raise EntryValidationError(str(exc)) from exc

    # Mirror the CLI's search strategy exactly
    results = search_index(query, memory_root)
    used_index = bool(results) or (memory_root / "memory.db").exists()

    if not used_index:
        results = search_entries_files(query, scope=resolved_scope)
    elif not results:
        # DB exists but returned nothing — also try file fallback
        results = search_entries_files(query, scope=resolved_scope)

    return results


# ---------------------------------------------------------------------------
# Skills: get / search
# ---------------------------------------------------------------------------


def skill_get(name: str) -> dict[str, Any]:
    """Return metadata + content for a skill by name (case-insensitive).

    Resolution order: project → machine.

    Returns a dict with keys: ``name``, ``description``, ``tags``, ``version``,
    ``source``, ``path``, ``content``.

    Raises:
        SkillNotFound: if no matching skill is found.
    """
    from cc.core.skill_store import (
        default_skill_paths,
        discover_skills_with_sources,
        find_skill_by_name,
        get_skill_content,
    )

    path_pairs = default_skill_paths()
    skills = discover_skills_with_sources(path_pairs)
    skill = find_skill_by_name(name, skills)

    if skill is None:
        raise SkillNotFound(f"Skill {name!r} not found")

    return {
        "name": skill.name,
        "description": skill.description,
        "tags": skill.tags,
        "version": skill.version,
        "source": skill.source,
        "path": str(skill.path),
        "content": get_skill_content(skill),
    }


def skill_search(query: str) -> list[dict[str, Any]]:
    """Search skills by keyword against name, description, and tags.

    Returns a list of skill metadata dicts (without ``content`` to keep
    the result compact — call ``skill_get(name)`` for full content).
    """
    from cc.core.skill_store import (
        default_skill_paths,
        discover_skills_with_sources,
        search_skills,
    )

    path_pairs = default_skill_paths()
    skills = discover_skills_with_sources(path_pairs)
    matches = search_skills(query, skills)

    return [
        {
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "version": s.version,
            "source": s.source,
            "path": str(s.path),
        }
        for s in matches
    ]


# ---------------------------------------------------------------------------
# Docs: resolve / get / search
# ---------------------------------------------------------------------------


def docs_resolve(
    pkg: str,
    lang: str | None = None,
) -> dict[str, Any]:
    """Detect the installed/declared version of a package.

    Args:
        pkg:  Package name (e.g. "react", "requests").
        lang: Ecosystem hint: "js"/"npm" or "python"/"pip".
              When omitted both ecosystems are probed in order: python, js.

    Returns:
        Dict with keys: ``name``, ``version``, ``version_source``, ``exact``.

    Raises:
        DocSourceUnavailable: if the version cannot be determined.
    """
    from cc.core.docs_resolver import detect_version

    langs = [lang] if lang else ["python", "js"]
    for l in langs:
        result = detect_version(pkg, l)
        if result is not None:
            return {
                "name": result.name,
                "version": result.version,
                "version_source": result.version_source,
                "exact": result.exact,
            }

    raise DocSourceUnavailable(f"version not found for package {pkg!r}")


def docs_get(
    pkg: str,
    *,
    topic: str | None = None,
    lang: str | None = None,
    source: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch documentation for a package.

    Args:
        pkg:     Package name.
        topic:   Documentation topic / query string (defaults to pkg name).
        lang:    Ecosystem hint: "js"/"npm" or "python"/"pip".
        source:  Override source_order: "local", "fetch", or None (config default).
        refresh: Bypass cache and fetch fresh docs.

    Returns:
        Dict with keys: ``package``, ``version``, ``topic``, ``source``,
        ``cached``, ``url``, ``metadata``, ``content``.

    Raises:
        DocSourceUnavailable: if no backend can return docs for the package.
    """
    from cc.core.docs_resolver import detect_version, resolve_docs

    langs = [lang] if lang else ["python", "js"]
    version_result = None
    for l in langs:
        version_result = detect_version(pkg, l)
        if version_result is not None:
            break

    version = version_result.version if version_result else "unknown"

    source_order: list[str] | None = [source] if source else None

    result = resolve_docs(
        pkg,
        version,
        topic or pkg,
        source_order=source_order,
        refresh=refresh,
    )

    if result is None:
        raise DocSourceUnavailable(f"no docs found for package {pkg!r}")

    return {
        "package": result.package,
        "version": result.version,
        "topic": result.topic,
        "source": result.source,
        "cached": result.cached,
        "url": result.url,
        "metadata": result.metadata,
        "content": result.content,
    }


def docs_search(
    pkg: str,
    query: str,
    *,
    lang: str | None = None,
) -> dict[str, Any]:
    """Search package documentation for a query/topic.

    Thin wrapper over :func:`docs_get` — returns the same dict structure.

    Raises:
        DocSourceUnavailable: if no docs are found.
    """
    return docs_get(pkg, topic=query, lang=lang)


# ---------------------------------------------------------------------------
# Public re-exports (flat surface)
# ---------------------------------------------------------------------------

__all__ = [
    # exceptions
    "MemoryError",
    "EntryNotFound",
    "EntryValidationError",
    "SkillNotFound",
    "DocsError",
    "DocSourceUnavailable",
    # memory ops
    "memory_store",
    "memory_get",
    "memory_list",
    "memory_delete",
    "memory_search",
    # skill ops
    "skill_get",
    "skill_search",
    # docs ops
    "docs_resolve",
    "docs_get",
    "docs_search",
]
