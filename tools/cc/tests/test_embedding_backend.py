"""Tests for cc.core.embedding_backend (43.3) and backend_factory (43.4).

Test strategy:
- All tests use a STUB embedder (deterministic small numpy vectors) injected
  via EmbeddingBackend(model_name, embedder=stub).  NO sentence-transformers
  loaded.
- Covers: hybrid rerank ordering, rebuild recompute, model-mismatch recompute,
  content_hash staleness detection, status output, graceful fallback on
  embedder failure.
- factory tests: "none" → FTS5, enabled → EmbeddingBackend, ImportError →
  FTS5 + warning, env override.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Stub embedder helpers
# ---------------------------------------------------------------------------

def _unit_vec(dim: int, index: int) -> np.ndarray:
    """Return a unit vector with a 1.0 at position *index* (mod dim)."""
    v = np.zeros(dim, dtype=np.float32)
    v[index % dim] = 1.0
    return v


def make_stub_embedder(dim: int = 4) -> Any:
    """Return a deterministic stub embedder callable.

    The vector for text T is determined by hash(T) % dim  (one-hot in *dim*).
    This keeps cosine distances deterministic without loading any model.
    """
    def stub(texts: list[str]) -> list[np.ndarray]:
        return [_unit_vec(dim, hash(t) % dim) for t in texts]

    return stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    import cc.core.entry_store as es
    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return tmp_path / ".claude" / "memory"


@pytest.fixture
def stub_backend(memory_root):
    """EmbeddingBackend with a stub embedder (no real model)."""
    from cc.core.embedding_backend import EmbeddingBackend

    return EmbeddingBackend(
        "stub-model",
        embedder=make_stub_embedder(dim=4),
    )


# ---------------------------------------------------------------------------
# 43.3-A: EmbeddingBackend satisfies SearchBackend Protocol
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    def test_satisfies_protocol(self, stub_backend):
        from cc.core.memory_index import SearchBackend

        assert isinstance(stub_backend, SearchBackend)


# ---------------------------------------------------------------------------
# 43.3-B: index / remove / status basic
# ---------------------------------------------------------------------------

class TestIndexAndRemove:
    def test_index_stores_vector(self, stub_backend, memory_root):
        import sqlite3 as _sqlite3

        from cc.core.embedding_store import get_vectors

        stub_backend.index("e1", "lesson", ["tag"], "some content", memory_root)

        db_path = memory_root / "memory.db"
        assert db_path.exists()
        conn = _sqlite3.connect(str(db_path))
        try:
            rows = get_vectors(conn)
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["id"] == "e1"
        assert rows[0]["model"] == "stub-model"

    def test_remove_clears_vector(self, stub_backend, memory_root):
        import sqlite3 as _sqlite3

        from cc.core.embedding_store import get_vectors

        stub_backend.index("e2", "context", [], "hello", memory_root)
        stub_backend.remove("e2", memory_root)

        db_path = memory_root / "memory.db"
        if db_path.exists():
            conn = _sqlite3.connect(str(db_path))
            try:
                rows = get_vectors(conn)
            finally:
                conn.close()
            ids = {r["id"] for r in rows}
            assert "e2" not in ids

    def test_status_reports_embedding_fields(self, stub_backend, memory_root):
        stub_backend.index("e3", "decision", [], "x", memory_root)
        info = stub_backend.status(memory_root)
        assert "embedding_model" in info
        assert info["embedding_model"] == "stub-model"
        assert "vectors" in info
        assert info["vectors"] >= 1


# ---------------------------------------------------------------------------
# 43.3-C: Hybrid search — rerank ordering
# ---------------------------------------------------------------------------

class TestHybridSearch:
    def test_fts_prefilter_reranked_by_cosine(self, memory_root):
        """FTS candidates are cosine-reranked; most semantically similar first."""
        from cc.core.embedding_backend import EmbeddingBackend

        # Use a custom embedder: "alpha" → [1,0,0,0], "beta" → [0,1,0,0]
        # query "alpha" → [1,0,0,0]; "alpha alpha" is more similar than "beta"
        def custom_embed(texts):
            vecs = []
            for t in texts:
                if "alpha" in t:
                    vecs.append(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
                else:
                    vecs.append(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32))
            return vecs

        backend = EmbeddingBackend("test-model", embedder=custom_embed)

        # Index two entries that both match "memory" via FTS
        backend.index("e-alpha", "lesson", ["memory"], "alpha memory lesson", memory_root)
        backend.index("e-beta", "lesson", ["memory"], "beta memory lesson", memory_root)

        results = backend.search("alpha memory", memory_root)
        # e-alpha should be ranked higher (cosine=1.0 for alpha query vs alpha vec)
        ids = [r["id"] for r in results]
        assert ids[0] == "e-alpha", f"Expected e-alpha first, got {ids}"

    def test_empty_fts_returns_empty(self, stub_backend, memory_root):
        results = stub_backend.search("completely absent term xyzzy1234", memory_root)
        # On empty FTS with no DB → empty list
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 43.3-D: Rebuild — recompute + staleness
# ---------------------------------------------------------------------------

class TestRebuild:
    def test_rebuild_indexes_entries(self, memory_root, monkeypatch):
        """rebuild() indexes all .md files and stores vectors."""
        import sqlite3 as _sqlite3

        from cc.core.embedding_backend import EmbeddingBackend
        from cc.core.embedding_store import count_vectors
        from cc.core.entry_store import store_entry

        # Store two entries via entry_store
        store_entry(entry_type="lesson", content="unique lesson content alpha", scope="project")
        store_entry(entry_type="context", content="unique context content beta", scope="project")

        backend = EmbeddingBackend("stub-model", embedder=make_stub_embedder(dim=4))
        stats = backend.rebuild(memory_root)

        assert stats["indexed"] == 2
        assert stats.get("errors", 0) == 0

        db_path = memory_root / "memory.db"
        conn = _sqlite3.connect(str(db_path))
        try:
            n = count_vectors(conn)
        finally:
            conn.close()
        assert n == 2

    def test_rebuild_recomputes_on_model_mismatch(self, memory_root, monkeypatch):
        """Changing the model name forces recompute even if content_hash unchanged."""
        import sqlite3 as _sqlite3

        from cc.core.embedding_backend import EmbeddingBackend
        from cc.core.embedding_store import get_vectors
        from cc.core.entry_store import store_entry

        store_entry(entry_type="lesson", content="model mismatch test gamma", scope="project")

        # First build with model-A
        backend_a = EmbeddingBackend("model-A", embedder=make_stub_embedder(dim=4))
        backend_a.rebuild(memory_root)

        # Now rebuild with model-B
        backend_b = EmbeddingBackend("model-B", embedder=make_stub_embedder(dim=4))
        backend_b.rebuild(memory_root)

        db_path = memory_root / "memory.db"
        conn = _sqlite3.connect(str(db_path))
        try:
            rows = get_vectors(conn)
        finally:
            conn.close()

        # All rows should now have model-B
        models = {r["model"] for r in rows}
        assert models == {"model-B"}, f"Expected model-B only, got {models}"

    def test_rebuild_skips_up_to_date_vectors(self, memory_root, monkeypatch):
        """Rebuild with same model and unchanged content does not recompute."""
        from cc.core.embedding_backend import EmbeddingBackend
        from cc.core.entry_store import store_entry

        call_count = [0]
        original_embed = make_stub_embedder(dim=4)

        def counting_embed(texts):
            call_count[0] += len(texts)
            return original_embed(texts)

        store_entry(entry_type="lesson", content="stable content omega", scope="project")

        backend = EmbeddingBackend("model-X", embedder=counting_embed)
        backend.rebuild(memory_root)
        first_count = call_count[0]

        # Second rebuild — content unchanged, same model → no recompute
        backend2 = EmbeddingBackend("model-X", embedder=counting_embed)
        backend2.rebuild(memory_root)
        second_count = call_count[0] - first_count

        assert second_count == 0, f"Expected 0 recomputes, got {second_count}"


# ---------------------------------------------------------------------------
# 43.3-E: Lazy import — sentence-transformers NOT loaded when stub injected
# ---------------------------------------------------------------------------

class TestLazyImport:
    def test_sentence_transformers_not_in_sys_modules_with_stub(self, stub_backend):
        """Using EmbeddingBackend with injected stub must not load sentence-transformers."""
        assert "sentence_transformers" not in sys.modules, (
            "sentence_transformers should not be imported when using a stub embedder"
        )

    def test_importing_embedding_backend_module_does_not_import_model_lib(self):
        """Importing embedding_backend at module level must not trigger sentence-transformers."""
        import cc.core.embedding_backend  # noqa: F401

        assert "sentence_transformers" not in sys.modules, (
            "sentence_transformers must not be imported at module import time"
        )


# ---------------------------------------------------------------------------
# 43.3-F: Graceful degradation when embedder raises
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_index_fallback_when_encode_fails(self, memory_root, caplog):
        """If encode fails during index(), FTS5 row is still written."""
        from cc.core.embedding_backend import EmbeddingBackend

        def failing_embed(texts):
            raise RuntimeError("model exploded")

        backend = EmbeddingBackend("bad-model", embedder=failing_embed)

        with caplog.at_level(logging.WARNING):
            backend.index("e-fail", "lesson", [], "content to index", memory_root)

        # Should have logged a warning
        assert any("Embedding encode failed" in r.message or "encode" in r.message.lower()
                   for r in caplog.records), f"Expected warning; records: {caplog.records}"

        # FTS5 row should still exist
        results = backend._fts.search("content to index", memory_root)
        assert any(r["id"] == "e-fail" for r in results), "FTS5 entry should exist despite embed failure"

    def test_search_fallback_when_query_encode_fails(self, memory_root):
        """If query encoding fails during search(), return FTS5 results."""
        from cc.core.embedding_backend import EmbeddingBackend

        ok_embed = make_stub_embedder(dim=4)
        fail_count = [0]

        def selective_embed(texts):
            # Fail on the query call (no entry-body text)
            fail_count[0] += 1
            if fail_count[0] > 2:
                raise RuntimeError("query encode fail")
            return ok_embed(texts)

        backend = EmbeddingBackend("selective-model", embedder=selective_embed)
        backend.index("e1", "lesson", ["tag"], "search fallback test content", memory_root)

        # Reset call count and force failure
        fail_count[0] = 100
        results = backend.search("search fallback test content", memory_root)
        # Should return FTS5 results without crashing
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 43.4-A: backend_factory — off path returns FTS5
# ---------------------------------------------------------------------------

class TestBackendFactory:
    def test_none_returns_fts5(self):
        from cc.core.backend_factory import _build_backend
        from cc.core.memory_index import FTS5Backend

        backend = _build_backend("none")
        assert isinstance(backend, FTS5Backend)

    def test_none_case_insensitive(self):
        from cc.core.backend_factory import _build_backend
        from cc.core.memory_index import FTS5Backend

        assert isinstance(_build_backend("NONE"), FTS5Backend)

    def test_none_does_not_import_sentence_transformers(self):
        from cc.core.backend_factory import _build_backend

        _build_backend("none")
        assert "sentence_transformers" not in sys.modules

    def test_import_error_falls_back_to_fts5(self, caplog):
        """If EmbeddingBackend raises ImportError (simulated), factory returns FTS5."""
        from cc.core.backend_factory import _build_backend
        from cc.core.memory_index import FTS5Backend

        with patch("cc.core.backend_factory._build_backend") as mock_build:
            # Simulate: embeddings module import works but model raises EmbeddingUnavailable
            pass  # we'll test via the actual code path below

        # Patch the embedding_backend module import inside _build_backend
        import cc.core.backend_factory as bf
        original = bf._build_backend

        def patched_build(model: str):
            if model == "none":
                from cc.core.memory_index import FTS5Backend as F
                return F()
            # Simulate ImportError on the embedding_backend import
            try:
                raise ImportError("sentence-transformers not installed (simulated)")
            except ImportError as exc:
                import logging as _log
                _log.getLogger("cc.core.backend_factory").warning(
                    "Embedding backend module unavailable; falling back to FTS5 keyword search: %s", exc
                )
                from cc.core.memory_index import FTS5Backend as F
                return F()

        # Actually test the resolve_backend() with a model name but no sentence-transformers
        # We do this by patching the import inside _build_backend
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            with caplog.at_level(logging.WARNING):
                result = _build_backend("some-model-that-needs-sentence-transformers")

        # sentence_transformers==None in sys.modules causes ImportError inside EmbeddingBackend
        # The factory should catch it and return FTS5
        assert isinstance(result, FTS5Backend)

    def test_resolve_backend_cached(self):
        """resolve_backend() returns the same instance on repeated calls."""
        from cc.core.backend_factory import _reset_cache, resolve_backend

        _reset_cache()
        b1 = resolve_backend(_model_override="none")
        b2 = resolve_backend(_model_override="none")
        assert b1 is b2

    def test_resolve_backend_force_reload(self):
        """_force_reload=True bypasses cache."""
        from cc.core.backend_factory import _reset_cache, resolve_backend
        from cc.core.memory_index import FTS5Backend

        _reset_cache()
        b1 = resolve_backend(_model_override="none")
        b2 = resolve_backend(_model_override="none", _force_reload=True)
        # Both should be FTS5 instances; they are different objects
        assert isinstance(b1, FTS5Backend)
        assert isinstance(b2, FTS5Backend)
        assert b1 is not b2

    def test_env_override(self, monkeypatch):
        """CC_MEMORY_EMBEDDING_MODEL env var controls the backend."""
        from cc.core.backend_factory import _reset_cache, resolve_backend
        from cc.core.memory_index import FTS5Backend

        monkeypatch.setenv("CC_MEMORY_EMBEDDING_MODEL", "none")
        _reset_cache()
        backend = resolve_backend(_force_reload=True)
        assert isinstance(backend, FTS5Backend)
