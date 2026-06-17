"""Tests for Task 99 (part 1): SourceBackend seam + layered resolver.

Covers:
  - SourceBackend Protocol structural checks
  - Backend registry: register_backend + unknown key skipped
  - Layered resolver: first hit wins, unavailable backends skipped
  - Unavailable-backend fall-through (e.g. httpx absent)
  - Resolver returns None when all backends miss
  - Cache integration: cache hit returned without calling backends
  - refresh=True bypasses cache read
  - Offline: resolver works with no network
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from cc.core.docs_resolver import (
    DocResult,
    FetchBackend,
    LocalBackend,
    SourceBackend,
    detect_version,
    register_backend,
    resolve_docs,
    _BACKEND_REGISTRY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(pkg="react", version="18.2.0", topic="hooks", source="fake", content="# docs") -> DocResult:
    return DocResult(package=pkg, version=version, topic=topic, content=content, source=source)


class _HitBackend:
    """Always returns a DocResult."""

    def __init__(self, name="hit"):
        self.name = name
        self.available = True

    def fetch(self, pkg, version, topic):
        return _make_result(pkg=pkg, version=version, topic=topic, source=self.name)


class _MissBackend:
    """Always returns None."""

    def __init__(self, name="miss"):
        self.name = name
        self.available = True

    def fetch(self, pkg, version, topic):
        return None


class _UnavailableBackend:
    """Reports itself as unavailable."""

    def __init__(self, name="unavail"):
        self.name = name
        self.available = False

    def fetch(self, pkg, version, topic):
        raise AssertionError("Should never be called when unavailable")


class _RaisingBackend:
    """Raises on every fetch call (simulates unexpected error)."""

    def __init__(self, name="raiser"):
        self.name = name
        self.available = True

    def fetch(self, pkg, version, topic):
        raise RuntimeError("unexpected backend error")


# ---------------------------------------------------------------------------
# SourceBackend protocol structural checks
# ---------------------------------------------------------------------------


def test_local_backend_satisfies_protocol():
    backend = LocalBackend()
    assert isinstance(backend, SourceBackend)
    assert backend.name == "local"
    assert backend.available is True


def test_fetch_backend_satisfies_protocol():
    backend = FetchBackend()
    assert isinstance(backend, SourceBackend)
    assert backend.name == "fetch"


def test_hit_backend_satisfies_protocol():
    backend = _HitBackend()
    assert isinstance(backend, SourceBackend)


# ---------------------------------------------------------------------------
# Layered resolver
# ---------------------------------------------------------------------------


def test_resolver_first_hit_wins(tmp_path):
    """First backend in order that returns a result wins."""
    register_backend("_test_hit1", _HitBackend("_test_hit1"))
    register_backend("_test_miss1", _MissBackend("_test_miss1"))

    result = resolve_docs(
        "react", "18.2.0", "hooks",
        source_order=["_test_hit1", "_test_miss1"],
        cache_dir=tmp_path,
    )
    assert result is not None
    assert result.source == "_test_hit1"


def test_resolver_falls_through_to_second(tmp_path):
    """When first backend misses, second backend is tried."""
    register_backend("_test_miss2", _MissBackend("_test_miss2"))
    register_backend("_test_hit2", _HitBackend("_test_hit2"))

    result = resolve_docs(
        "react", "18.2.0", "lifecycle",
        source_order=["_test_miss2", "_test_hit2"],
        cache_dir=tmp_path,
    )
    assert result is not None
    assert result.source == "_test_hit2"


def test_resolver_skips_unavailable_backend(tmp_path):
    """Unavailable backends are silently skipped, next backend tried."""
    register_backend("_test_unavail3", _UnavailableBackend("_test_unavail3"))
    register_backend("_test_hit3", _HitBackend("_test_hit3"))

    result = resolve_docs(
        "vue", "3.0.0", "reactivity",
        source_order=["_test_unavail3", "_test_hit3"],
        cache_dir=tmp_path,
    )
    assert result is not None
    assert result.source == "_test_hit3"


def test_resolver_skips_raising_backend(tmp_path):
    """Backend that raises is caught; resolver continues to next backend."""
    register_backend("_test_raiser4", _RaisingBackend("_test_raiser4"))
    register_backend("_test_hit4", _HitBackend("_test_hit4"))

    result = resolve_docs(
        "axios", "1.0.0", "interceptors",
        source_order=["_test_raiser4", "_test_hit4"],
        cache_dir=tmp_path,
    )
    assert result is not None
    assert result.source == "_test_hit4"


def test_resolver_returns_none_when_all_miss(tmp_path):
    register_backend("_test_miss5a", _MissBackend("_test_miss5a"))
    register_backend("_test_miss5b", _MissBackend("_test_miss5b"))

    result = resolve_docs(
        "unknown-pkg", "0.0.0", "anything",
        source_order=["_test_miss5a", "_test_miss5b"],
        cache_dir=tmp_path,
    )
    assert result is None


def test_resolver_skips_unknown_key_in_source_order(tmp_path):
    """Unknown keys in source_order are silently skipped."""
    register_backend("_test_hit6", _HitBackend("_test_hit6"))

    result = resolve_docs(
        "pkg", "1.0.0", "topic",
        source_order=["no_such_backend", "_test_hit6"],
        cache_dir=tmp_path,
    )
    assert result is not None
    assert result.source == "_test_hit6"


# ---------------------------------------------------------------------------
# FetchBackend unavailability when httpx absent
# ---------------------------------------------------------------------------


def test_fetch_backend_unavailable_when_httpx_absent(monkeypatch):
    """FetchBackend.available is False when httpx is not installed."""
    import importlib

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    backend = FetchBackend()
    assert backend.available is False


def test_resolver_skips_fetch_when_httpx_absent(tmp_path, monkeypatch):
    """Resolver skips 'fetch' backend without error when httpx is absent."""
    import importlib

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    register_backend("_test_hit7", _HitBackend("_test_hit7"))

    result = resolve_docs(
        "react", "18.0.0", "useState",
        source_order=["fetch", "_test_hit7"],
        cache_dir=tmp_path,
    )
    assert result is not None
    assert result.source == "_test_hit7"


# ---------------------------------------------------------------------------
# Cache integration
# ---------------------------------------------------------------------------


def test_resolver_returns_cached_result(tmp_path):
    """Cache hit is returned without calling any backend."""
    from cc.core.docs_cache import cache_put

    cached_result = _make_result(source="local")
    cache_put("react", "18.2.0", "hooks", cached_result, cache_dir=tmp_path)

    called = []

    class _TrackingBackend:
        name = "_test_tracker8"
        available = True

        def fetch(self, pkg, version, topic):
            called.append((pkg, version, topic))
            return _make_result(source="_test_tracker8")

    register_backend("_test_tracker8", _TrackingBackend())

    result = resolve_docs(
        "react", "18.2.0", "hooks",
        source_order=["_test_tracker8"],
        cache_dir=tmp_path,
    )

    assert result is not None
    assert result.cached is True
    assert len(called) == 0  # backend was NOT called


def test_resolver_refresh_bypasses_cache(tmp_path):
    """refresh=True reads from backend even when cache has a valid entry."""
    from cc.core.docs_cache import cache_put

    cached_result = _make_result(content="stale content", source="local")
    cache_put("lodash", "4.0.0", "map", cached_result, cache_dir=tmp_path)

    class _FreshBackend:
        name = "_test_fresh9"
        available = True

        def fetch(self, pkg, version, topic):
            return DocResult(pkg, version, topic, "fresh content", "_test_fresh9")

    register_backend("_test_fresh9", _FreshBackend())

    result = resolve_docs(
        "lodash", "4.0.0", "map",
        source_order=["_test_fresh9"],
        cache_dir=tmp_path,
        refresh=True,
    )

    assert result is not None
    assert result.content == "fresh content"
    assert result.cached is False


def test_resolver_writes_to_cache_on_hit(tmp_path):
    """After a backend hit, the result is cached for subsequent calls."""
    from cc.core.docs_cache import cache_get

    register_backend("_test_writer10", _HitBackend("_test_writer10"))

    # First call — no cache
    result1 = resolve_docs(
        "express", "4.18.0", "routing",
        source_order=["_test_writer10"],
        cache_dir=tmp_path,
    )
    assert result1 is not None

    # Cache should now contain the entry
    cached = cache_get("express", "4.18.0", "routing", cache_dir=tmp_path)
    assert cached is not None
    assert cached.package == "express"


# ---------------------------------------------------------------------------
# Offline test
# ---------------------------------------------------------------------------


def test_resolver_offline(tmp_path, monkeypatch):
    """Full offline check: resolver works with no network whatsoever."""
    original_socket = socket.socket

    def no_network(*args, **kwargs):
        raise OSError("Network access forbidden in offline test")

    monkeypatch.setattr(socket, "socket", no_network)

    register_backend("_test_offline11", _HitBackend("_test_offline11"))

    result = resolve_docs(
        "react", "18.0.0", "hooks",
        source_order=["_test_offline11"],
        cache_dir=tmp_path,
    )
    assert result is not None
    assert result.source == "_test_offline11"
