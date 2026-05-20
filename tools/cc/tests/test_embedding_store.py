"""Tests for cc.core.embedding_store (43.2).

Verifies:
- embeddings table DDL (CREATE TABLE IF NOT EXISTS)
- upsert / get_vectors / delete_vector round-trip
- content_hash determinism
- cosine_similarity correctness
- cosine_rerank ordering
- table coexists with memory_fts (FTS5Backend)
- numpy is never imported at module import time (only inside functions)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_mem_db() -> sqlite3.Connection:
    """In-memory SQLite connection for isolated tests."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# 43.2-A: Table DDL
# ---------------------------------------------------------------------------

class TestEnsureEmbeddingsTable:
    def test_creates_table(self):
        from cc.core.embedding_store import ensure_embeddings_table

        conn = _open_mem_db()
        ensure_embeddings_table(conn)

        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
        ).fetchone()
        assert row is not None, "embeddings table should exist after ensure_embeddings_table()"
        conn.close()

    def test_idempotent(self):
        """Calling twice must not raise."""
        from cc.core.embedding_store import ensure_embeddings_table

        conn = _open_mem_db()
        ensure_embeddings_table(conn)
        ensure_embeddings_table(conn)  # second call — must not raise
        conn.close()

    def test_columns_exist(self):
        from cc.core.embedding_store import ensure_embeddings_table

        conn = _open_mem_db()
        ensure_embeddings_table(conn)
        info = conn.execute("PRAGMA table_info(embeddings)").fetchall()
        col_names = {r[1] for r in info}
        assert {"id", "model", "dim", "vector", "content_hash"} == col_names
        conn.close()


# ---------------------------------------------------------------------------
# 43.2-B: content_hash
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_deterministic(self):
        from cc.core.embedding_store import content_hash

        assert content_hash("hello") == content_hash("hello")

    def test_differs_for_different_inputs(self):
        from cc.core.embedding_store import content_hash

        assert content_hash("hello") != content_hash("world")

    def test_hex_string(self):
        from cc.core.embedding_store import content_hash

        h = content_hash("test")
        assert len(h) == 64  # sha256 hex = 64 chars
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# 43.2-C: upsert / get / delete
# ---------------------------------------------------------------------------

class TestUpsertGetDelete:
    def test_upsert_and_get(self):
        import numpy as np

        from cc.core.embedding_store import ensure_embeddings_table, get_vectors, upsert_vector

        conn = _open_mem_db()
        ensure_embeddings_table(conn)

        vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        upsert_vector(conn, "id-1", "test-model", vec, "hello world")
        conn.commit()

        rows = get_vectors(conn)
        assert len(rows) == 1
        r = rows[0]
        assert r["id"] == "id-1"
        assert r["model"] == "test-model"
        assert r["dim"] == 3
        assert np.allclose(r["vector"], vec)
        conn.close()

    def test_upsert_overwrites(self):
        import numpy as np

        from cc.core.embedding_store import ensure_embeddings_table, get_vectors, upsert_vector

        conn = _open_mem_db()
        ensure_embeddings_table(conn)

        v1 = np.array([1.0, 0.0], dtype=np.float32)
        v2 = np.array([0.0, 1.0], dtype=np.float32)

        upsert_vector(conn, "id-x", "model-a", v1, "text a")
        conn.commit()
        upsert_vector(conn, "id-x", "model-b", v2, "text b")
        conn.commit()

        rows = get_vectors(conn)
        assert len(rows) == 1
        assert rows[0]["model"] == "model-b"
        assert np.allclose(rows[0]["vector"], v2)
        conn.close()

    def test_get_filtered_by_ids(self):
        import numpy as np

        from cc.core.embedding_store import ensure_embeddings_table, get_vectors, upsert_vector

        conn = _open_mem_db()
        ensure_embeddings_table(conn)

        for i in range(3):
            upsert_vector(conn, f"id-{i}", "m", np.array([float(i)], dtype=np.float32), f"text {i}")
        conn.commit()

        rows = get_vectors(conn, ["id-0", "id-2"])
        ids = {r["id"] for r in rows}
        assert ids == {"id-0", "id-2"}
        conn.close()

    def test_delete(self):
        import numpy as np

        from cc.core.embedding_store import (
            delete_vector,
            ensure_embeddings_table,
            get_vectors,
            upsert_vector,
        )

        conn = _open_mem_db()
        ensure_embeddings_table(conn)

        upsert_vector(conn, "del-me", "m", np.array([1.0], dtype=np.float32), "text")
        conn.commit()
        delete_vector(conn, "del-me")
        conn.commit()

        rows = get_vectors(conn)
        assert rows == []
        conn.close()

    def test_delete_nonexistent_is_noop(self):
        from cc.core.embedding_store import delete_vector, ensure_embeddings_table

        conn = _open_mem_db()
        ensure_embeddings_table(conn)
        delete_vector(conn, "does-not-exist")  # must not raise
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 43.2-D: cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        import numpy as np

        from cc.core.embedding_store import cosine_similarity

        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        import numpy as np

        from cc.core.embedding_store import cosine_similarity

        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        import numpy as np

        from cc.core.embedding_store import cosine_similarity

        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([-1.0, 0.0], dtype=np.float32)
        assert abs(cosine_similarity(a, b) + 1.0) < 1e-6

    def test_zero_vector_returns_zero(self):
        import numpy as np

        from cc.core.embedding_store import cosine_similarity

        zero = np.array([0.0, 0.0], dtype=np.float32)
        v = np.array([1.0, 2.0], dtype=np.float32)
        assert cosine_similarity(zero, v) == 0.0

    def test_known_value(self):
        import numpy as np

        from cc.core.embedding_store import cosine_similarity

        # [1,1] vs [1,0]: cos = 1/sqrt(2) ≈ 0.7071
        a = np.array([1.0, 1.0], dtype=np.float32)
        b = np.array([1.0, 0.0], dtype=np.float32)
        assert abs(cosine_similarity(a, b) - (1.0 / (2 ** 0.5))) < 1e-5


# ---------------------------------------------------------------------------
# 43.2-E: cosine_rerank
# ---------------------------------------------------------------------------

class TestCosineRerank:
    def test_order_descending(self):
        import numpy as np

        from cc.core.embedding_store import cosine_rerank

        query = np.array([1.0, 0.0], dtype=np.float32)
        candidates = [
            {"id": "a", "vector": np.array([0.0, 1.0], dtype=np.float32)},  # score ~0
            {"id": "b", "vector": np.array([1.0, 0.0], dtype=np.float32)},  # score 1.0
            {"id": "c", "vector": np.array([0.707, 0.707], dtype=np.float32)},  # score ~0.707
        ]
        ranked = cosine_rerank(query, candidates)
        ids = [r["id"] for r in ranked]
        assert ids[0] == "b"
        assert ids[1] == "c"
        assert ids[2] == "a"

    def test_score_key_added(self):
        import numpy as np

        from cc.core.embedding_store import cosine_rerank

        query = np.array([1.0], dtype=np.float32)
        candidates = [{"id": "x", "vector": np.array([1.0], dtype=np.float32)}]
        ranked = cosine_rerank(query, candidates)
        assert "score" in ranked[0]

    def test_empty_candidates(self):
        import numpy as np

        from cc.core.embedding_store import cosine_rerank

        query = np.array([1.0, 0.0], dtype=np.float32)
        assert cosine_rerank(query, []) == []


# ---------------------------------------------------------------------------
# 43.2-F: Coexistence with memory_fts (FTS5Backend)
# ---------------------------------------------------------------------------

class TestCoexistenceWithFTS5:
    def test_embeddings_table_coexists_with_memory_fts(self, tmp_path):
        """Both tables can live in the same SQLite database."""
        import sqlite3 as _sqlite3

        from cc.core.embedding_store import ensure_embeddings_table
        from cc.core.fts5_core import create_fts

        db_path = tmp_path / "memory.db"
        conn = _sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

        # Create FTS5 table (as FTS5Backend does)
        create_fts(conn, "memory_fts", ["id", "type", "tags", "content"])
        # Then embeddings table
        ensure_embeddings_table(conn)
        conn.commit()

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "memory_fts" in tables
        assert "embeddings" in tables
        conn.close()


# ---------------------------------------------------------------------------
# 43.2-G: No model lib imported when using embedding_store
# ---------------------------------------------------------------------------

class TestNoModelLibImport:
    def test_sentence_transformers_not_imported_after_module_import(self):
        """Importing embedding_store must NOT import sentence_transformers."""
        # This module-level import happens at collection time; check sys.modules
        import cc.core.embedding_store  # noqa: F401

        assert "sentence_transformers" not in sys.modules, (
            "sentence_transformers must NOT be imported when embedding_store is loaded"
        )
