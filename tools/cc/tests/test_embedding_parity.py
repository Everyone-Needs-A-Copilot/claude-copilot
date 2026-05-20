"""Off-path parity + fitness tests (43.6).

Critical invariants:
1. PARITY: with embeddings off (model="none"), search results are BYTE-IDENTICAL
   (id-set + order) to FTS5Backend directly.
2. NO-IMPORT: importing memory_index and embedding_backend must NOT import
   sentence_transformers or numpy (stdlib-only at module level).
3. DEGRADATION: simulated ImportError → resolve_backend() returns FTS5 + logs
   a warning, never crashes.
4. DEFAULT-OFF: get_default_backend() returns FTS5Backend when no config set.
"""

from __future__ import annotations

import sys

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    import cc.core.entry_store as es
    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return tmp_path / ".claude" / "memory"


@pytest.fixture(autouse=True)
def reset_default_backend():
    """Restore default backend after each test."""
    from cc.core.memory_index import get_default_backend, set_default_backend

    original = get_default_backend()
    yield
    set_default_backend(original)


@pytest.fixture(autouse=True)
def reset_factory_cache():
    """Clear backend factory cache between tests."""
    from cc.core.backend_factory import _reset_cache

    _reset_cache()
    yield
    _reset_cache()


# ---------------------------------------------------------------------------
# 43.6-A: Parity test — off-path results == FTS5Backend directly
# ---------------------------------------------------------------------------

class TestOffPathParity:
    """With embedding_model='none', search results must be byte-identical to FTS5."""

    CORPUS = [
        ("lesson", ["python", "testing"], "pytest is the best python testing framework"),
        ("context", ["deployment", "ci"], "github actions runs our ci pipeline"),
        ("decision", ["architecture"], "we chose sqlite for local storage due to simplicity"),
        ("lesson", ["python"], "python type hints improve code clarity and refactoring"),
    ]

    def _seed_and_rebuild_fts(self, memory_root):
        """Store corpus entries and rebuild FTS index."""
        from cc.core.entry_store import store_entry
        from cc.core.memory_index import FTS5Backend

        for entry_type, tags, content in self.CORPUS:
            store_entry(entry_type=entry_type, content=content, tags=tags, scope="project")

        fts = FTS5Backend()
        fts.rebuild(memory_root)
        return fts

    def test_module_search_with_none_matches_fts5_directly(self, memory_root, monkeypatch):
        """search_index() with model=none gives identical results to FTS5Backend.search()."""
        from cc.core.backend_factory import _reset_cache
        from cc.core.memory_index import FTS5Backend, search_index, set_default_backend

        fts = self._seed_and_rebuild_fts(memory_root)

        # Ensure default backend is FTS5 (model=none)
        set_default_backend(FTS5Backend())

        queries = ["python", "testing", "sqlite", "ci pipeline", "xyzzy_nonexistent"]

        for q in queries:
            direct = fts.search(q, memory_root)
            via_module = search_index(q, memory_root)

            direct_ids = [r["id"] for r in direct]
            module_ids = [r["id"] for r in via_module]

            assert direct_ids == module_ids, (
                f"Parity failure for query={q!r}: "
                f"FTS5={direct_ids} vs module={module_ids}"
            )

    def test_rebuild_with_none_matches_fts5_directly(self, memory_root):
        """rebuild_index() with model=none gives identical stats to FTS5Backend.rebuild()."""
        from cc.core.entry_store import store_entry
        from cc.core.memory_index import FTS5Backend, rebuild_index, set_default_backend

        for entry_type, tags, content in self.CORPUS:
            store_entry(entry_type=entry_type, content=content, tags=tags, scope="project")

        fts = FTS5Backend()
        fts_stats = fts.rebuild(memory_root)

        set_default_backend(FTS5Backend())
        module_stats = rebuild_index(memory_root)

        assert module_stats["indexed"] == fts_stats["indexed"]
        assert module_stats["errors"] == fts_stats["errors"]

    def test_result_dict_shape_identical(self, memory_root):
        """Result dicts have same keys regardless of backend (when off)."""
        from cc.core.entry_store import store_entry
        from cc.core.memory_index import FTS5Backend, search_index, set_default_backend

        store_entry(entry_type="lesson", content="shape test content zork", scope="project")
        fts = FTS5Backend()
        fts.rebuild(memory_root)
        set_default_backend(FTS5Backend())

        direct = fts.search("zork", memory_root)
        via_module = search_index("zork", memory_root)

        assert len(direct) == 1
        assert len(via_module) == 1
        assert set(direct[0].keys()) == set(via_module[0].keys())
        assert direct[0]["id"] == via_module[0]["id"]
        assert direct[0]["content"] == via_module[0]["content"]


# ---------------------------------------------------------------------------
# 43.6-B: No-import fitness — sentence_transformers never imported on off-path
# ---------------------------------------------------------------------------

class TestNoImportFitness:
    def test_importing_memory_index_does_not_import_sentence_transformers(self):
        """cc.core.memory_index import must not trigger sentence_transformers."""
        import cc.core.memory_index  # noqa: F401

        assert "sentence_transformers" not in sys.modules, (
            "sentence_transformers must NOT be imported when cc.core.memory_index is imported"
        )

    def test_importing_embedding_backend_does_not_import_sentence_transformers(self):
        """cc.core.embedding_backend import must not trigger sentence_transformers."""
        import cc.core.embedding_backend  # noqa: F401

        assert "sentence_transformers" not in sys.modules, (
            "sentence_transformers must NOT be imported when cc.core.embedding_backend is imported"
        )

    def test_importing_backend_factory_does_not_import_sentence_transformers(self):
        """cc.core.backend_factory import must not trigger sentence_transformers."""
        import cc.core.backend_factory  # noqa: F401

        assert "sentence_transformers" not in sys.modules, (
            "sentence_transformers must NOT be imported when cc.core.backend_factory is imported"
        )

    def test_fts5_search_does_not_import_sentence_transformers(self, memory_root):
        """Running a full FTS5 search workflow must not import sentence_transformers."""
        from cc.core.entry_store import store_entry
        from cc.core.memory_index import FTS5Backend, rebuild_index, search_index, set_default_backend

        store_entry(entry_type="lesson", content="no import fitness test delta", scope="project")
        set_default_backend(FTS5Backend())
        rebuild_index(memory_root)
        search_index("fitness delta", memory_root)

        assert "sentence_transformers" not in sys.modules, (
            "sentence_transformers must NOT be imported on the off-path (FTS5 only)"
        )


# ---------------------------------------------------------------------------
# 43.6-C: Graceful degradation — simulated ImportError → FTS5 + warning
# ---------------------------------------------------------------------------

class TestGracefulDegradationFactory:
    def test_import_error_falls_back_to_fts5_with_warning(self, caplog):
        """When sentence-transformers is absent, resolve_backend warns + returns FTS5."""
        import logging
        from unittest.mock import patch

        from cc.core.backend_factory import _reset_cache, resolve_backend
        from cc.core.memory_index import FTS5Backend

        _reset_cache()

        # Simulate EmbeddingBackend raising EmbeddingUnavailable (which wraps ImportError)
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            with caplog.at_level(logging.WARNING, logger="cc.core.backend_factory"):
                backend = resolve_backend(_model_override="all-MiniLM-L6-v2", _force_reload=True)

        assert isinstance(backend, FTS5Backend), (
            f"Expected FTS5Backend on degradation, got {type(backend).__name__}"
        )

        # There should be a warning in the logs
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_messages, (
            "Expected at least one warning logged when embedding backend is unavailable"
        )

    def test_degraded_backend_still_searches(self, memory_root, caplog):
        """After degradation fallback, search still works (FTS5)."""
        import logging
        from unittest.mock import patch

        from cc.core.backend_factory import _reset_cache, resolve_backend
        from cc.core.entry_store import store_entry

        store_entry(entry_type="lesson", content="degradation search works gamma", scope="project")

        _reset_cache()
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            with caplog.at_level(logging.WARNING):
                backend = resolve_backend(_model_override="some-model", _force_reload=True)

        backend.rebuild(memory_root)
        results = backend.search("degradation gamma", memory_root)
        assert isinstance(results, list)
        assert any("degradation search works gamma" in r.get("content", "") for r in results)

    def test_no_crash_on_embedding_failure(self, memory_root, caplog):
        """Embedding encode failure during search must not raise (silent FTS5 fallback)."""
        import logging

        from cc.core.embedding_backend import EmbeddingBackend
        from cc.core.entry_store import store_entry

        store_entry(entry_type="lesson", content="crash safety test epsilon", scope="project")

        call_count = [0]

        def intermittent_embed(texts):
            call_count[0] += 1
            if call_count[0] > 3:
                raise ValueError("simulated GPU OOM")
            import numpy as _np
            return [_np.zeros(4, dtype=_np.float32) for _ in texts]

        backend = EmbeddingBackend("crash-test-model", embedder=intermittent_embed)
        backend.rebuild(memory_root)

        # Force the query encode to fail
        call_count[0] = 100
        with caplog.at_level(logging.DEBUG):
            results = backend.search("crash safety test epsilon", memory_root)

        assert isinstance(results, list), "search() must not raise even when encode fails"


# ---------------------------------------------------------------------------
# 43.6-D: Default-off guarantee
# ---------------------------------------------------------------------------

class TestDefaultOff:
    def test_default_backend_is_fts5_when_no_config(self, monkeypatch):
        """With default config (model=none), get_default_backend() returns FTS5Backend."""
        from cc.core.backend_factory import _reset_cache
        from cc.core.memory_index import FTS5Backend, get_default_backend, set_default_backend

        # Clear the cached backend to force re-resolution
        set_default_backend(None)  # type: ignore[arg-type]
        _reset_cache()

        # Ensure env var is not set
        monkeypatch.delenv("CC_MEMORY_EMBEDDING_MODEL", raising=False)

        backend = get_default_backend()
        assert isinstance(backend, FTS5Backend), (
            f"Default backend must be FTS5Backend; got {type(backend).__name__}"
        )

    def test_no_embeddings_table_created_when_off(self, memory_root, monkeypatch):
        """With embeddings off, memory.db must NOT contain an embeddings table."""
        from cc.core.entry_store import store_entry
        from cc.core.memory_index import FTS5Backend, rebuild_index, set_default_backend

        monkeypatch.delenv("CC_MEMORY_EMBEDDING_MODEL", raising=False)
        set_default_backend(FTS5Backend())

        store_entry(entry_type="lesson", content="off path no table test", scope="project")
        rebuild_index(memory_root)

        db_path = memory_root / "memory.db"
        assert db_path.exists()

        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
            ).fetchone()
        finally:
            conn.close()

        assert row is None, (
            "embeddings table must NOT be created when embedding backend is disabled"
        )
