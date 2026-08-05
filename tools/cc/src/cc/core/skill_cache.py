"""Skill frontmatter cache: SQLite-backed key/value store for parsed
SKILL.md frontmatter dicts.

WP-372 P2.2 perf note: the knowledge repo's skill tree alone is ~280
files. `cc skill list`/`search` re-scan every configured source (project,
machine, and now knowledge) on every invocation; re-reading and re-parsing
every unchanged file's frontmatter on every call is needless work once a
machine has run `cc skill` once. This mirrors `core/docs_cache.py`'s
pattern almost exactly (SQLite, gitignored, local-only derived artifact,
best-effort/never-blocks), simplified for this module's cache key: a
file's `(path, mtime, size)` tuple IS the invalidation signal (the same
staleness check `make`/`ccache` use) -- no separate TTL-driven expiry is
needed for CORRECTNESS (an edited file's mtime/size changes, so the cache
naturally misses), but `skills.cache_ttl_hours` (already a reserved config
key with no consumer before this) is still honored as a secondary safety
net against a pathological mtime-preserving edit.

Cache key: sha256(absolute path) -- one row per file, not per (path, mtime)
pair, so a file that changes N times only ever occupies one row (INSERT OR
REPLACE), never accumulating stale rows for paths that keep changing.

Design constraints (mirrors docs_cache.py's ADR WP-105 constraints):
- Cache miss or corruption MUST NEVER block the caller.
- All public functions are best-effort: they return None / silently
  swallow errors.
- Mirrors the memory.db / docs_cache.db pattern: gitignored, local-only
  derived artifact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from cc.core.config import resolve_key

_log = logging.getLogger(__name__)

_DB_NAME = "skill_frontmatter_cache.db"

_GITIGNORE_CONTENT = "# skill frontmatter cache -- local derived artifact, not committed\n*.db\n"

_CREATE_DDL = """
CREATE TABLE IF NOT EXISTS skill_frontmatter_cache (
    cache_key     TEXT PRIMARY KEY,
    path          TEXT NOT NULL,
    mtime         REAL NOT NULL,
    size          INTEGER NOT NULL,
    frontmatter   TEXT NOT NULL,
    stored_at     REAL NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cache_key(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute(_CREATE_DDL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Path / TTL helpers (mirrors core/docs_paths.py)
# ---------------------------------------------------------------------------


def skill_cache_dir(*, _override: Optional[Path] = None) -> Path:
    """Return the resolved skill cache directory (creates it if needed).

    Args:
        _override: Bypass config resolution (used in tests -- never resolves
            `paths.knowledge_repo`-style config or `Path.home()` when given).
    """
    if _override is not None:
        root = _override
    else:
        raw = resolve_key("skills.cache_dir")
        root = Path(raw).expanduser() if raw else Path.home() / ".claude" / "cache" / "skills"

    root.mkdir(parents=True, exist_ok=True)

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE_CONTENT, encoding="utf-8")

    return root


def skill_cache_ttl_hours() -> int:
    """Return the configured cache TTL in hours (default 24)."""
    raw = resolve_key("skills.cache_ttl_hours")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 24


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cache_get_frontmatter(
    path: Path,
    *,
    mtime: float,
    size: int,
    cache_dir: Path,
    ttl_hours: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """
    Look up a cached, already-parsed frontmatter dict for `path`. Returns
    `None` on a cache miss, a stale `(mtime, size)` mismatch (the file
    changed since it was cached), TTL expiry, or any error -- never raises.
    """
    try:
        db_path = cache_dir / _DB_NAME
        if not db_path.exists():
            return None

        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT mtime, size, frontmatter, stored_at "
                "FROM skill_frontmatter_cache WHERE cache_key = ?",
                (_cache_key(path),),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        cached_mtime, cached_size, frontmatter_json, stored_at = row

        if cached_mtime != mtime or cached_size != size:
            return None  # file changed on disk since it was cached

        ttl = ttl_hours if ttl_hours is not None else skill_cache_ttl_hours()
        age_hours = (time.time() - stored_at) / 3600.0
        if age_hours > ttl:
            return None

        return json.loads(frontmatter_json)

    except Exception:
        _log.debug("skill cache_get_frontmatter failed; returning None", exc_info=True)
        return None


def cache_put_frontmatter(
    path: Path,
    *,
    mtime: float,
    size: int,
    frontmatter: dict[str, Any],
    cache_dir: Path,
) -> None:
    """Store a parsed frontmatter dict for `path`. Silently no-ops on any
    error (a cache write failure must never block skill discovery)."""
    try:
        db_path = cache_dir / _DB_NAME
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO skill_frontmatter_cache
                    (cache_key, path, mtime, size, frontmatter, stored_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (_cache_key(path), str(path), mtime, size, json.dumps(frontmatter), time.time()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        _log.debug("skill cache_put_frontmatter failed; continuing without cache", exc_info=True)


def cache_clear(*, cache_dir: Path) -> int:
    """Delete all cache entries. Returns the number of rows deleted (0 on
    any error, including a not-yet-created cache)."""
    try:
        db_path = cache_dir / _DB_NAME
        if not db_path.exists():
            return 0
        conn = _connect(db_path)
        try:
            cur = conn.execute("DELETE FROM skill_frontmatter_cache")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
    except Exception:
        _log.debug("skill cache_clear failed", exc_info=True)
        return 0
