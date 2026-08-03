"""Docs cache: SQLite-backed key/value store for DocResult objects.

Cache key: (ecosystem/lang, package, version, topic-hash)
TTL:       docs.cache_ttl_hours (default 168 = 1 week)

Design constraints (from ADR WP-105):
- Cache miss or corruption MUST NEVER block the caller.
- All public functions are best-effort: they return None / silently swallow errors.
- Mirrors the memory.db pattern: gitignored, local-only derived artifact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

_DB_NAME = "docs_cache.db"

_CREATE_DDL = """
CREATE TABLE IF NOT EXISTS docs_cache (
    cache_key   TEXT PRIMARY KEY,
    package     TEXT NOT NULL,
    version     TEXT NOT NULL,
    topic_hash  TEXT NOT NULL,
    source      TEXT NOT NULL,
    content     TEXT NOT NULL,
    url         TEXT,
    metadata    TEXT,
    stored_at   REAL NOT NULL,
    ttl_hours   INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _topic_hash(topic: str) -> str:
    return hashlib.sha256(topic.encode("utf-8")).hexdigest()[:16]


def _cache_key(pkg: str, version: str, topic: str) -> str:
    return f"{pkg}::{version}::{_topic_hash(topic)}"


def _db_path(cache_dir: Optional[Path] = None) -> Path:
    from cc.core.docs_paths import docs_cache_dir

    root = docs_cache_dir(_override=cache_dir) if cache_dir else docs_cache_dir()
    return root / _DB_NAME


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute(_CREATE_DDL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cache_get(
    pkg: str,
    version: str,
    topic: str,
    *,
    cache_dir: Optional[Path] = None,
) -> Optional["DocResult"]:  # noqa: F821
    """Look up a cached DocResult. Returns None on miss, expiry, or any error.

    Never raises — callers can rely on None meaning "not cached".
    """
    from cc.core.docs_resolver import DocResult

    try:
        key = _cache_key(pkg, version, topic)
        db_path = _db_path(cache_dir)
        if not db_path.exists():
            return None

        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT content, source, url, metadata, stored_at, ttl_hours FROM docs_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return None

        content, source, url, metadata_json, stored_at, ttl_hours = row

        # TTL check
        age_hours = (time.time() - stored_at) / 3600.0
        if age_hours > ttl_hours:
            _log.debug("docs cache: TTL expired for key %r (age=%.1fh ttl=%dh)", key, age_hours, ttl_hours)
            return None

        metadata = {}
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                pass

        return DocResult(
            package=pkg,
            version=version,
            topic=topic,
            content=content,
            source=source,
            url=url,
            cached=True,
            metadata=metadata,
        )

    except Exception:
        _log.debug("docs cache_get failed; returning None", exc_info=True)
        return None


def cache_put(
    pkg: str,
    version: str,
    topic: str,
    result: "DocResult",  # noqa: F821
    *,
    cache_dir: Optional[Path] = None,
    ttl_hours: Optional[int] = None,
) -> None:
    """Store a DocResult in the cache. Silently no-ops on any error."""
    from cc.core.docs_paths import docs_cache_ttl_hours

    try:
        ttl = ttl_hours if ttl_hours is not None else docs_cache_ttl_hours()
        key = _cache_key(pkg, version, topic)
        db_path = _db_path(cache_dir)
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO docs_cache
                    (cache_key, package, version, topic_hash, source, content, url, metadata, stored_at, ttl_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    pkg,
                    version,
                    _topic_hash(topic),
                    result.source,
                    result.content,
                    result.url,
                    json.dumps(result.metadata) if result.metadata else None,
                    time.time(),
                    ttl,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    except Exception:
        _log.debug("docs cache_put failed; continuing without cache", exc_info=True)


def cache_invalidate(
    pkg: str,
    version: str,
    topic: str,
    *,
    cache_dir: Optional[Path] = None,
) -> bool:
    """Remove a single cache entry. Returns True if a row was deleted."""
    try:
        key = _cache_key(pkg, version, topic)
        db_path = _db_path(cache_dir)
        if not db_path.exists():
            return False
        conn = _connect(db_path)
        try:
            cur = conn.execute("DELETE FROM docs_cache WHERE cache_key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except Exception:
        _log.debug("docs cache_invalidate failed", exc_info=True)
        return False


def cache_clear(*, cache_dir: Optional[Path] = None) -> int:
    """Delete all cache entries. Returns the number of rows deleted."""
    try:
        db_path = _db_path(cache_dir)
        if not db_path.exists():
            return 0
        conn = _connect(db_path)
        try:
            cur = conn.execute("DELETE FROM docs_cache")
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
    except Exception:
        _log.debug("docs cache_clear failed", exc_info=True)
        return 0


def cache_stats(*, cache_dir: Optional[Path] = None) -> dict:
    """Return {"total": n, "expired": n, "fresh": n}. Best-effort — returns zeros on error."""
    try:
        db_path = _db_path(cache_dir)
        if not db_path.exists():
            return {"total": 0, "expired": 0, "fresh": 0}
        conn = _connect(db_path)
        try:
            now = time.time()
            rows = conn.execute(
                "SELECT stored_at, ttl_hours FROM docs_cache"
            ).fetchall()
        finally:
            conn.close()

        total = len(rows)
        expired = sum(1 for stored_at, ttl_hours in rows if (now - stored_at) / 3600.0 > ttl_hours)
        return {"total": total, "expired": expired, "fresh": total - expired}
    except Exception:
        _log.debug("docs cache_stats failed", exc_info=True)
        return {"total": 0, "expired": 0, "fresh": 0}
