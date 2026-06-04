"""Hybrid FTS5 + semantic embedding backend for cc memory (TASK-43).

EmbeddingBackend implements the SearchBackend Protocol by wrapping
FTS5Backend and layering semantic vector ranking on top.

Architecture:
    - WRAPS FTS5Backend: every write (index/rebuild/remove) also updates
      the FTS5 table so keyword search keeps working in parallel.
    - HYBRID SEARCH: FTS5 BM25 prefilter → embed query once → cosine
      rerank candidates → bounded full-scan fallback (threshold-gated).
    - LAZY IMPORT: sentence-transformers is imported INSIDE __init__
      (or via an injected embedder callable for tests).  Never at module
      top-level.  Importing this module does NOT import sentence-transformers.
    - GRACEFUL DEGRADATION: all failure paths raise EmbeddingUnavailable
      which the backend_factory catches and falls back to FTS5.

Dependency injection for testing:
    EmbeddingBackend accepts an optional *embedder* callable:
        embedder(texts: list[str]) -> list[np.ndarray]
    When provided, the real sentence-transformers model is NOT loaded.
    Tests pass a deterministic stub function.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

from cc.core.embedding_store import (
    content_hash,
    cosine_rerank,
    count_vectors,
    delete_vector,
    ensure_embeddings_table,
    get_vectors,
    upsert_vector,
)
from cc.core.memory_index import FTS5Backend

_DB_NAME = "memory.db"
_log = logging.getLogger(__name__)

# Default threshold for full-scan fallback (from config default)
_DEFAULT_THRESHOLD = 0.7
# Maximum candidates returned from a full-scan fallback
_FULL_SCAN_CAP = 50


class EmbeddingUnavailable(Exception):
    """Raised when the embedding model cannot be loaded or used.

    The backend_factory catches this and falls back to FTS5.
    """


# ---------------------------------------------------------------------------
# EmbeddingBackend
# ---------------------------------------------------------------------------


class EmbeddingBackend:
    """Hybrid FTS5 + vector embedding SearchBackend.

    Parameters:
        model_name:  sentence-transformers model id (e.g. 'all-MiniLM-L6-v2').
        embedder:    Optional callable (list[str]) -> list[np.ndarray].
                     If provided, skips sentence-transformers loading entirely
                     (used in unit tests for deterministic stub embeddings).
        threshold:   Minimum cosine for full-scan fallback path.
    """

    def __init__(
        self,
        model_name: str,
        *,
        embedder: Callable[[list[str]], list[Any]] | None = None,
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        self._model_name = model_name
        self._threshold = threshold
        self._fts = FTS5Backend()

        if embedder is not None:
            # DI path (tests): use the provided callable directly
            self._embedder: Callable[[list[str]], list[Any]] = embedder
        else:
            # Production path: lazy-load sentence-transformers
            self._embedder = self._load_model(model_name)

    @staticmethod
    def _load_model(model_name: str) -> Callable[[list[str]], list[Any]]:
        """Load a sentence-transformers model; raise EmbeddingUnavailable on failure."""
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
        except ImportError as exc:
            raise EmbeddingUnavailable(
                f"sentence-transformers not installed (pip install 'claude-cli[embeddings]'): {exc}"
            ) from exc
        try:
            model = SentenceTransformer(model_name)
        except Exception as exc:
            raise EmbeddingUnavailable(
                f"Failed to load embedding model '{model_name}': {exc}"
            ) from exc

        def _encode(texts: list[str]) -> list[Any]:
            return model.encode(texts, convert_to_numpy=True)

        return _encode

    # -- internal helpers -----------------------------------------------

    @staticmethod
    def _db_path(memory_root: Path) -> Path:
        return memory_root / _DB_NAME

    def _open_db(self, db_path: Path) -> sqlite3.Connection:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        ensure_embeddings_table(conn)
        return conn

    def _encode_one(self, text: str) -> Any:
        """Encode a single text; raise EmbeddingUnavailable on failure."""
        try:
            results = self._embedder([text])
            return results[0]
        except Exception as exc:
            raise EmbeddingUnavailable(f"Embedding encode failed: {exc}") from exc

    def _encode_body(
        self, entry_id: str, entry_type: str, tags: list[str], content: str
    ) -> str:
        """Compose the text body that gets embedded (same formula for store + rebuild)."""
        tag_str = " ".join(tags) if tags else ""
        return f"{entry_type} {tag_str} {content}".strip()

    # -- SearchBackend implementation -----------------------------------

    def index(
        self,
        entry_id: str,
        entry_type: str,
        tags: list[str],
        content: str,
        memory_root: Path,
    ) -> None:
        """Insert/replace in FTS5 AND compute + store vector."""
        # Always keep FTS5 in sync
        self._fts.index(entry_id, entry_type, tags, content, memory_root)

        body = self._encode_body(entry_id, entry_type, tags, content)
        db_path = self._db_path(memory_root)
        try:
            vec = self._encode_one(body)
            conn = self._open_db(db_path)
            try:
                upsert_vector(conn, entry_id, self._model_name, vec, body)
                conn.commit()
            finally:
                conn.close()
        except EmbeddingUnavailable as exc:
            _log.warning(
                "Embedding encode failed for %s; FTS5 index kept: %s", entry_id, exc
            )

    def remove(self, entry_id: str, memory_root: Path) -> None:
        """Remove from FTS5 AND from embeddings table."""
        self._fts.remove(entry_id, memory_root)
        db_path = self._db_path(memory_root)
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        try:
            delete_vector(conn, entry_id)
            conn.commit()
        finally:
            conn.close()

    def rebuild(self, memory_root: Path) -> dict[str, int]:
        """Rebuild FTS5 index AND recompute all vectors.

        Detects model-column mismatch (different model stored) and forces
        full recompute.  Uses content_hash to skip up-to-date vectors.
        """
        from cc.core.entry_format import EntryValidationError, parse_frontmatter
        from cc.core.entry_store import entries_dir

        # First rebuild FTS (base pass)
        stats = self._fts.rebuild(memory_root)

        e_dir = entries_dir(memory_root)
        db_path = self._db_path(memory_root)
        conn = self._open_db(db_path)

        try:
            # Load existing vectors to detect staleness / model mismatch
            existing = {r["id"]: r for r in get_vectors(conn)}

            errors = 0
            recomputed = 0

            if e_dir.exists():
                for path in sorted(e_dir.glob("*.md")):
                    try:
                        text = path.read_text(encoding="utf-8")
                        fm, body_text = parse_frontmatter(text)
                        entry_id = fm.get("id", "")
                        if not entry_id:
                            continue
                        entry_type = fm.get("type", "")
                        tag_list = fm.get("tags") or []
                        body = self._encode_body(
                            entry_id, entry_type, tag_list, body_text
                        )
                        chash = content_hash(body)

                        # Check staleness: missing, model mismatch, or content changed
                        existing_row = existing.get(entry_id)
                        if (
                            existing_row is None
                            or existing_row["model"] != self._model_name
                            or existing_row["content_hash"] != chash
                        ):
                            vec = self._encode_one(body)
                            upsert_vector(conn, entry_id, self._model_name, vec, body)
                            recomputed += 1
                    except (EntryValidationError, OSError, EmbeddingUnavailable) as exc:
                        _log.warning("Skipping vector for %s: %s", path.name, exc)
                        errors += 1

            # Remove orphaned vectors (entries deleted since last rebuild)
            existing_ids = set(existing.keys())
            file_ids: set[str] = set()
            if e_dir.exists():
                for path in e_dir.glob("*.md"):
                    try:
                        text = path.read_text(encoding="utf-8")
                        fm, _ = parse_frontmatter(text)
                        eid = fm.get("id", "")
                        if eid:
                            file_ids.add(eid)
                    except (Exception,):
                        pass
            for orphan_id in existing_ids - file_ids:
                delete_vector(conn, orphan_id)

            conn.commit()
        finally:
            conn.close()

        return {
            "indexed": stats["indexed"],
            "errors": stats["errors"] + errors,
            "vectors_recomputed": recomputed,
        }

    def search(self, query: str, memory_root: Path) -> list[dict[str, Any]]:
        """Hybrid FTS5 prefilter + cosine rerank + bounded fallback.

        Steps:
        1. FTS5 BM25 prefilter — get keyword-matched candidates.
        2. Embed the query once.
        3. Cosine rerank the candidates.
        4. If prefilter returned nothing, do a bounded full-scan (cosine
           over all stored vectors, capped at _FULL_SCAN_CAP), gated by
           self._threshold.
        5. On any embedding failure, fall back silently to FTS5 results.
        """
        # Step 1: FTS5 prefilter
        fts_results = self._fts.search(query, memory_root)

        db_path = self._db_path(memory_root)
        if not db_path.exists():
            return fts_results  # no vectors yet; pure FTS5

        try:
            query_vec = self._encode_one(query)
        except EmbeddingUnavailable:
            _log.debug("Query encode failed; returning FTS5 results only")
            return fts_results

        conn = sqlite3.connect(str(db_path))
        try:
            if fts_results:
                # Step 2+3: rerank the FTS candidates
                fts_ids = [r["id"] for r in fts_results]
                stored = get_vectors(conn, fts_ids)
            else:
                # Step 4: bounded full-scan fallback
                stored = get_vectors(conn)
        finally:
            conn.close()

        if not stored:
            return fts_results

        # Build id→content map for result reconstruction
        id_to_fts: dict[str, dict] = {r["id"]: r for r in fts_results}

        # For full-scan path, we need content from FTS (may be empty set)
        # Build a combined map: stored vectors + content from FTS if present
        candidates = []
        for sv in stored:
            fts_row = id_to_fts.get(sv["id"])
            if fts_row:
                candidates.append({**sv, **fts_row})
            else:
                # Full-scan: no FTS row, include vector-only candidate
                candidates.append(sv)

        ranked = cosine_rerank(query_vec, candidates)

        if not fts_results:
            # Full-scan: apply threshold gate
            ranked = [r for r in ranked if r.get("score", 0.0) >= self._threshold]
            ranked = ranked[:_FULL_SCAN_CAP]

        # Reconstruct result dicts matching the FTS5 output shape
        # (id, type, tags, content) — for full-scan entries missing FTS content,
        # we need to fetch from disk or skip (keep only what we have)
        output = []
        for r in ranked:
            if "content" in r:
                output.append(
                    {
                        "id": r["id"],
                        "type": r.get("type", ""),
                        "tags": r.get("tags", []),
                        "content": r.get("content", ""),
                    }
                )
            # If content missing (pure vector-only full-scan hit without FTS row),
            # skip — we can't reconstruct the full dict without reading disk here.
            # This is a rare edge case; next rebuild will sync them.

        return output

    def status(self, memory_root: Path) -> dict[str, Any]:
        """FTS5 status + embedding-specific fields."""
        base = self._fts.status(memory_root)

        db_path = self._db_path(memory_root)
        if not db_path.exists():
            return {
                **base,
                "embedding_model": self._model_name,
                "vectors": 0,
                "vectors_in_sync": False,
            }

        try:
            conn = sqlite3.connect(str(db_path))
            try:
                vec_count = count_vectors(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            vec_count = 0

        files = base.get("files", 0)
        return {
            **base,
            "embedding_model": self._model_name,
            "vectors": vec_count,
            "vectors_in_sync": vec_count == files,
        }
