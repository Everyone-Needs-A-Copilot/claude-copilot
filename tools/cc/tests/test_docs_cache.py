"""Tests for Task 99 (part 2): docs cache store — TTL, corruption, round-trip.

Covers:
  - cache_put / cache_get round-trip
  - Cache miss (key not present)
  - TTL expiry: expired entry returns None
  - Corruption: garbled DB returns None without raising
  - cache_invalidate removes single entry
  - cache_clear removes all entries
  - cache_stats counts fresh vs expired
  - Offline: all cache ops work with no network
"""

from __future__ import annotations

import socket
import sqlite3
import time
from pathlib import Path

import pytest

from cc.core.docs_cache import (
    cache_clear,
    cache_get,
    cache_invalidate,
    cache_put,
    cache_stats,
)
from cc.core.docs_resolver import DocResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache(tmp_path):
    """Return a fresh tmp_path to use as cache_dir."""
    return tmp_path


def _result(pkg="requests", version="2.31.0", topic="session", source="local", content="## Requests docs") -> DocResult:
    return DocResult(
        package=pkg,
        version=version,
        topic=topic,
        content=content,
        source=source,
        url="https://docs.python-requests.org",
        metadata={"type": "api"},
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_put_then_get_returns_entry(cache):
    r = _result()
    cache_put(r.package, r.version, r.topic, r, cache_dir=cache)
    got = cache_get(r.package, r.version, r.topic, cache_dir=cache)

    assert got is not None
    assert got.package == "requests"
    assert got.version == "2.31.0"
    assert got.content == "## Requests docs"
    assert got.url == "https://docs.python-requests.org"
    assert got.metadata == {"type": "api"}
    assert got.cached is True


def test_cache_miss_returns_none(cache):
    result = cache_get("nonexistent-pkg", "0.0.0", "anything", cache_dir=cache)
    assert result is None


def test_cache_miss_before_any_db(tmp_path):
    """cache_get returns None when the DB file does not yet exist."""
    absent_dir = tmp_path / "no_db_here"
    # Do NOT call docs_cache_dir — so no DB is created
    result = cache_get("pkg", "1.0.0", "topic", cache_dir=absent_dir)
    assert result is None


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


def test_expired_entry_returns_none(cache, monkeypatch):
    """An entry whose TTL has elapsed returns None."""
    r = _result()
    # Store with TTL of 1 hour
    cache_put(r.package, r.version, r.topic, r, cache_dir=cache, ttl_hours=1)

    # Advance time by 2 hours
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 7200)

    got = cache_get(r.package, r.version, r.topic, cache_dir=cache)
    assert got is None


def test_fresh_entry_is_returned(cache, monkeypatch):
    """An entry within TTL is returned."""
    r = _result()
    cache_put(r.package, r.version, r.topic, r, cache_dir=cache, ttl_hours=168)

    # No time travel — entry is fresh
    got = cache_get(r.package, r.version, r.topic, cache_dir=cache)
    assert got is not None


# ---------------------------------------------------------------------------
# Corruption
# ---------------------------------------------------------------------------


def test_corrupted_db_returns_none(cache):
    """Corrupt SQLite file causes cache_get to return None without raising."""
    from cc.core.docs_cache import _DB_NAME
    from cc.core.docs_paths import docs_cache_dir

    # Create the cache dir so the path exists
    cache_root = docs_cache_dir(_override=cache)
    db_path = cache_root / _DB_NAME
    db_path.write_bytes(b"this is not sqlite data!!!")

    result = cache_get("any", "1.0.0", "topic", cache_dir=cache)
    assert result is None  # Must not raise


def test_corrupted_metadata_json_still_returns_entry(cache):
    """If metadata JSON is corrupt, the entry is still returned (metadata defaults to {})."""
    r = _result()
    cache_put(r.package, r.version, r.topic, r, cache_dir=cache)

    # Corrupt the metadata column directly
    from cc.core.docs_cache import _DB_NAME, _cache_key
    from cc.core.docs_paths import docs_cache_dir

    db_path = docs_cache_dir(_override=cache) / _DB_NAME
    key = _cache_key(r.package, r.version, r.topic)
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE docs_cache SET metadata = ? WHERE cache_key = ?", ("{{not json", key))
    conn.commit()
    conn.close()

    got = cache_get(r.package, r.version, r.topic, cache_dir=cache)
    assert got is not None
    assert got.metadata == {}  # Fallback to empty dict


# ---------------------------------------------------------------------------
# cache_invalidate
# ---------------------------------------------------------------------------


def test_invalidate_removes_entry(cache):
    r = _result()
    cache_put(r.package, r.version, r.topic, r, cache_dir=cache)

    removed = cache_invalidate(r.package, r.version, r.topic, cache_dir=cache)
    assert removed is True

    got = cache_get(r.package, r.version, r.topic, cache_dir=cache)
    assert got is None


def test_invalidate_returns_false_for_missing_key(cache):
    removed = cache_invalidate("no-pkg", "0.0.0", "nothing", cache_dir=cache)
    assert removed is False


# ---------------------------------------------------------------------------
# cache_clear
# ---------------------------------------------------------------------------


def test_clear_removes_all_entries(cache):
    for i in range(3):
        r = _result(pkg=f"pkg{i}", topic=f"topic{i}")
        cache_put(r.package, r.version, r.topic, r, cache_dir=cache)

    count = cache_clear(cache_dir=cache)
    assert count == 3

    stats = cache_stats(cache_dir=cache)
    assert stats["total"] == 0


def test_clear_on_empty_cache_returns_zero(cache):
    count = cache_clear(cache_dir=cache)
    assert count == 0


# ---------------------------------------------------------------------------
# cache_stats
# ---------------------------------------------------------------------------


def test_stats_fresh_and_expired(cache, monkeypatch):
    r1 = _result(pkg="pkg-a", topic="a")
    r2 = _result(pkg="pkg-b", topic="b")

    cache_put(r1.package, r1.version, r1.topic, r1, cache_dir=cache, ttl_hours=1)
    cache_put(r2.package, r2.version, r2.topic, r2, cache_dir=cache, ttl_hours=168)

    # Advance time so r1 is expired
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 7200)

    stats = cache_stats(cache_dir=cache)
    assert stats["total"] == 2
    assert stats["expired"] == 1
    assert stats["fresh"] == 1


def test_stats_no_db_returns_zeros(tmp_path):
    absent = tmp_path / "absent_stats"
    stats = cache_stats(cache_dir=absent)
    assert stats == {"total": 0, "expired": 0, "fresh": 0}


# ---------------------------------------------------------------------------
# insert_or_replace (PUT twice updates entry)
# ---------------------------------------------------------------------------


def test_put_twice_updates_entry(cache):
    r = _result(content="old content")
    cache_put(r.package, r.version, r.topic, r, cache_dir=cache)

    r2 = _result(content="new content")
    cache_put(r2.package, r2.version, r2.topic, r2, cache_dir=cache)

    got = cache_get(r.package, r.version, r.topic, cache_dir=cache)
    assert got is not None
    assert got.content == "new content"


# ---------------------------------------------------------------------------
# Offline test
# ---------------------------------------------------------------------------


def test_cache_offline(cache, monkeypatch):
    """All cache ops work with no network access."""
    original_socket = socket.socket

    def no_network(*args, **kwargs):
        raise OSError("Network access forbidden in offline test")

    monkeypatch.setattr(socket, "socket", no_network)

    r = _result()
    cache_put(r.package, r.version, r.topic, r, cache_dir=cache)
    got = cache_get(r.package, r.version, r.topic, cache_dir=cache)
    assert got is not None

    stats = cache_stats(cache_dir=cache)
    assert stats["total"] == 1

    cache_invalidate(r.package, r.version, r.topic, cache_dir=cache)
    assert cache_get(r.package, r.version, r.topic, cache_dir=cache) is None
