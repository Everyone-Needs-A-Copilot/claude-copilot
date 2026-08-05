"""Docs cache path helpers (mirror of the memory-root / gitignore pattern).

The docs cache lives at docs.cache_dir (default ~/.claude/cache/docs).
It is gitignored because it is a local-only derived artifact — just like memory.db.
"""

from __future__ import annotations

from pathlib import Path

from cc.core.config import resolve_key

_GITIGNORE_CONTENT = "# docs cache — local derived artifact, not committed\n*.db\n"


def docs_cache_dir(*, _override: Path | None = None) -> Path:
    """Return the resolved docs cache directory (creates it if needed).

    Args:
        _override: Bypass config resolution (used in tests).
    """
    if _override is not None:
        root = _override
    else:
        raw = resolve_key("docs.cache_dir")
        root = Path(raw).expanduser() if raw else Path.home() / ".claude" / "cache" / "docs"

    root.mkdir(parents=True, exist_ok=True)

    # Write a .gitignore inside the cache dir so SQLite files are never committed.
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")

    return root


def docs_cache_ttl_hours() -> int:
    """Return the configured cache TTL in hours (default 168 = one week)."""
    raw = resolve_key("docs.cache_ttl_hours")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 168


def docs_source_order() -> list[str]:
    """Return the ordered list of source backend names from config.

    Default is ['local', 'fetch'].
    """
    raw = resolve_key("docs.source_order")
    if not raw:
        return ["local", "fetch"]
    return [s.strip() for s in str(raw).split(",") if s.strip()]
