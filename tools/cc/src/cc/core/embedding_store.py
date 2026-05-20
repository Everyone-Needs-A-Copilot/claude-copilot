"""Vector store helpers for the optional embeddings backend.

Manages the `embeddings` table inside the existing memory.db (same file as
the FTS5 index — same disposable-cache lifecycle, same gitignore entry).

Schema:
    embeddings(id TEXT PRIMARY KEY, model TEXT, dim INTEGER,
               vector BLOB, content_hash TEXT)

    - vector: raw float32 bytes (numpy tobytes / frombuffer)
    - content_hash: sha256 hex of the indexed body (staleness detection)

Design constraints (CRITICAL):
    - stdlib + numpy ONLY — no sentence-transformers import here.
    - ZERO import-time side effects (no DB open, no file I/O at import).
    - numpy is imported lazily inside each function so that the off-path
      (embeddings disabled) never touches it even if this module is imported.
    - Table is created with CREATE TABLE IF NOT EXISTS — off-path callers
      never create it.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np  # type-only; never executed at runtime on off-path

_TABLE = "embeddings"
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Table lifecycle
# ---------------------------------------------------------------------------

def ensure_embeddings_table(conn: sqlite3.Connection) -> None:
    """Create the embeddings table if it does not yet exist.

    Called ONLY from the enabled path (EmbeddingBackend).  The off-path
    (FTS5Backend / embeddings disabled) never calls this.
    """
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id           TEXT PRIMARY KEY,
            model        TEXT NOT NULL,
            dim          INTEGER NOT NULL,
            vector       BLOB NOT NULL,
            content_hash TEXT NOT NULL
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    """Return sha256 hex digest of *text* (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def upsert_vector(
    conn: sqlite3.Connection,
    entry_id: str,
    model: str,
    vector: "np.ndarray",  # float32 1-D
    body: str,
) -> None:
    """Insert or replace a vector row for *entry_id*.

    Args:
        conn:     Open SQLite connection (embeddings table must exist).
        entry_id: Memory entry UUID.
        model:    sentence-transformers model name used to produce the vector.
        vector:   float32 numpy array (1-D).
        body:     The text that was encoded (used to derive content_hash).
    """
    import numpy as _np  # lazy — only on enabled path

    vec = _np.asarray(vector, dtype=_np.float32)
    conn.execute(
        f"""
        INSERT INTO {_TABLE}(id, model, dim, vector, content_hash)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            model=excluded.model,
            dim=excluded.dim,
            vector=excluded.vector,
            content_hash=excluded.content_hash
        """,
        (entry_id, model, int(vec.shape[0]), vec.tobytes(), content_hash(body)),
    )


def get_vectors(
    conn: sqlite3.Connection,
    entry_ids: list[str] | None = None,
) -> list[dict]:
    """Fetch vector rows, optionally filtered to *entry_ids*.

    Returns list of dicts: {id, model, dim, vector (np.ndarray float32),
    content_hash}.
    """
    import numpy as _np  # lazy

    if entry_ids is not None:
        placeholders = ",".join("?" * len(entry_ids))
        rows = conn.execute(
            f"SELECT id, model, dim, vector, content_hash FROM {_TABLE}"
            f" WHERE id IN ({placeholders})",
            entry_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT id, model, dim, vector, content_hash FROM {_TABLE}"
        ).fetchall()

    return [
        {
            "id": r[0],
            "model": r[1],
            "dim": r[2],
            "vector": _np.frombuffer(r[3], dtype=_np.float32).copy(),
            "content_hash": r[4],
        }
        for r in rows
    ]


def delete_vector(conn: sqlite3.Connection, entry_id: str) -> None:
    """Delete the vector row for *entry_id* (no-op if absent)."""
    conn.execute(f"DELETE FROM {_TABLE} WHERE id = ?", (entry_id,))


def get_all_models(conn: sqlite3.Connection) -> set[str]:
    """Return the set of distinct model names stored in the embeddings table."""
    rows = conn.execute(f"SELECT DISTINCT model FROM {_TABLE}").fetchall()
    return {r[0] for r in rows}


def count_vectors(conn: sqlite3.Connection) -> int:
    """Return the number of stored vector rows."""
    row = conn.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def cosine_similarity(a: "np.ndarray", b: "np.ndarray") -> float:
    """Cosine similarity between two 1-D float32 arrays.

    Returns a float in [-1, 1].  Returns 0.0 for zero-norm inputs.
    """
    import numpy as _np  # lazy

    a = _np.asarray(a, dtype=_np.float32)
    b = _np.asarray(b, dtype=_np.float32)
    norm_a = float(_np.linalg.norm(a))
    norm_b = float(_np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(_np.dot(a, b) / (norm_a * norm_b))


def cosine_rerank(
    query_vec: "np.ndarray",
    candidates: list[dict],
) -> list[dict]:
    """Re-rank *candidates* by cosine similarity to *query_vec* (descending).

    Each candidate dict must contain a ``vector`` key (np.ndarray float32).
    The ``score`` key is added/replaced with the cosine value.
    Does NOT filter by threshold — caller decides the cutoff.
    """
    scored = [
        {**c, "score": cosine_similarity(query_vec, c["vector"])}
        for c in candidates
    ]
    return sorted(scored, key=lambda x: x["score"], reverse=True)
