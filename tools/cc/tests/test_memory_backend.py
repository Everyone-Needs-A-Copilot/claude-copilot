"""Tests for the pluggable SearchBackend seam introduced in TASK-32.

Verifies:
- SearchBackend is a Protocol (runtime_checkable)
- FTS5Backend satisfies the protocol
- set_default_backend / get_default_backend work
- A stub backend can be injected and its methods are called
- Module-level helpers (rebuild_index, search_index, etc.) delegate to the backend
- FTS5 remains the default after reset
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cc.core.memory_index import (
    FTS5Backend,
    SearchBackend,
    get_default_backend,
    index_entry,
    index_status,
    rebuild_index,
    remove_from_index,
    search_index,
    set_default_backend,
)
from cc.core.entry_store import store_entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    """Patch git root so stores resolve to tmp_path."""
    import cc.core.entry_store as es
    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return tmp_path / ".claude" / "memory"


@pytest.fixture(autouse=True)
def reset_default_backend():
    """Restore the default backend after each test that swaps it."""
    original = get_default_backend()
    yield
    set_default_backend(original)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestSearchBackendProtocol:
    def test_fts5_backend_satisfies_protocol(self):
        """FTS5Backend must satisfy the SearchBackend Protocol at runtime."""
        backend = FTS5Backend()
        assert isinstance(backend, SearchBackend)

    def test_stub_backend_satisfies_protocol(self):
        """A stub that implements the four methods satisfies SearchBackend."""

        class StubBackend:
            def index(self, entry_id, entry_type, tags, content, memory_root):
                pass

            def remove(self, entry_id, memory_root):
                pass

            def rebuild(self, memory_root):
                return {"indexed": 0, "errors": 0}

            def search(self, query, memory_root):
                return []

            def status(self, memory_root):
                return {"files": 0, "indexed": 0, "in_sync": True}

        assert isinstance(StubBackend(), SearchBackend)

    def test_incomplete_class_does_not_satisfy_protocol(self):
        """A class missing a required method does NOT satisfy SearchBackend."""

        class IncompleteBackend:
            def index(self, entry_id, entry_type, tags, content, memory_root):
                pass
            # missing remove, rebuild, search, status

        assert not isinstance(IncompleteBackend(), SearchBackend)


# ---------------------------------------------------------------------------
# Default backend registry
# ---------------------------------------------------------------------------

class TestDefaultBackendRegistry:
    def test_default_is_fts5(self):
        backend = get_default_backend()
        assert isinstance(backend, FTS5Backend)

    def test_set_then_get(self):
        class DummyBackend:
            def index(self, *a, **kw): pass
            def remove(self, *a, **kw): pass
            def rebuild(self, memory_root): return {"indexed": 0, "errors": 0}
            def search(self, query, memory_root): return []
            def status(self, memory_root): return {"files": 0, "indexed": 0, "in_sync": True}

        dummy = DummyBackend()
        set_default_backend(dummy)
        assert get_default_backend() is dummy


# ---------------------------------------------------------------------------
# Backend injection into module-level helpers
# ---------------------------------------------------------------------------

class TestBackendInjection:
    """Verify that passing a backend= to module helpers routes to that backend."""

    def test_rebuild_delegates_to_injected_backend(self, memory_root, tmp_path):
        called_with = []

        class RecordingBackend:
            def index(self, *a, **kw): pass
            def remove(self, *a, **kw): pass
            def rebuild(self, mr):
                called_with.append(("rebuild", mr))
                return {"indexed": 0, "errors": 0}
            def search(self, q, mr): return []
            def status(self, mr): return {"files": 0, "indexed": 0, "in_sync": True}

        backend = RecordingBackend()
        rebuild_index(memory_root, backend=backend)
        assert len(called_with) == 1
        assert called_with[0][0] == "rebuild"
        assert called_with[0][1] == memory_root

    def test_search_delegates_to_injected_backend(self, memory_root):
        queries_seen = []

        class RecordingBackend:
            def index(self, *a, **kw): pass
            def remove(self, *a, **kw): pass
            def rebuild(self, mr): return {"indexed": 0, "errors": 0}
            def search(self, q, mr):
                queries_seen.append(q)
                return [{"id": "fake", "type": "context", "tags": [], "content": "injected"}]
            def status(self, mr): return {"files": 0, "indexed": 0, "in_sync": True}

        backend = RecordingBackend()
        results = search_index("hello", memory_root, backend=backend)
        assert "hello" in queries_seen
        assert results[0]["content"] == "injected"

    def test_index_entry_delegates_to_injected_backend(self, memory_root):
        indexed = []

        class RecordingBackend:
            def index(self, entry_id, entry_type, tags, content, mr):
                indexed.append({"id": entry_id, "type": entry_type})
            def remove(self, *a, **kw): pass
            def rebuild(self, mr): return {"indexed": 0, "errors": 0}
            def search(self, q, mr): return []
            def status(self, mr): return {"files": 0, "indexed": 0, "in_sync": True}

        backend = RecordingBackend()
        index_entry("abc-123", "decision", ["tag"], "content", memory_root, backend=backend)
        assert len(indexed) == 1
        assert indexed[0]["id"] == "abc-123"
        assert indexed[0]["type"] == "decision"

    def test_remove_delegates_to_injected_backend(self, memory_root):
        removed = []

        class RecordingBackend:
            def index(self, *a, **kw): pass
            def remove(self, entry_id, mr):
                removed.append(entry_id)
            def rebuild(self, mr): return {"indexed": 0, "errors": 0}
            def search(self, q, mr): return []
            def status(self, mr): return {"files": 0, "indexed": 0, "in_sync": True}

        backend = RecordingBackend()
        remove_from_index("abc-123", memory_root, backend=backend)
        assert "abc-123" in removed


# ---------------------------------------------------------------------------
# FTS5 keyword search behavior (unchanged from before the refactor)
# ---------------------------------------------------------------------------

class TestFTS5BackendBehavior:
    def test_rebuild_and_search(self, memory_root):
        store_entry(entry_type="lesson", content="unique phrase zorp", scope="project")
        backend = FTS5Backend()
        stats = backend.rebuild(memory_root)
        assert stats["indexed"] == 1
        results = backend.search("zorp", memory_root)
        assert len(results) == 1
        assert "zorp" in results[0]["content"]

    def test_search_empty_returns_empty(self, memory_root):
        backend = FTS5Backend()
        results = backend.search("anything", memory_root)
        assert results == []

    def test_status_in_sync(self, memory_root):
        store_entry(entry_type="context", content="x", scope="project")
        backend = FTS5Backend()
        backend.rebuild(memory_root)
        info = backend.status(memory_root)
        assert info["in_sync"] is True

    def test_module_rebuild_uses_fts5_by_default(self, memory_root):
        """Module-level rebuild_index with no backend= uses FTS5 (default)."""
        store_entry(entry_type="decision", content="fts5 default test", scope="project")
        stats = rebuild_index(memory_root)
        assert stats["indexed"] == 1

    def test_module_search_uses_fts5_by_default(self, memory_root):
        """Module-level search_index with no backend= uses FTS5 (default)."""
        store_entry(entry_type="context", content="fts5 keyword here", scope="project")
        rebuild_index(memory_root)
        results = search_index("keyword", memory_root)
        assert len(results) == 1
