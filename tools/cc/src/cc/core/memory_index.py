"""Full-text (FTS5 keyword) index for memory entries (local cache only, gitignored).

Architecture: a SearchBackend protocol defines the seam between callers and the
underlying search implementation.  The only backend shipped here is FTS5Backend
(SQLite FTS5 / BM25 keyword search).  A future embedding-based backend can be
added by implementing SearchBackend and passing it to the functions below.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from cc.core.entry_format import EntryValidationError, parse_frontmatter
from cc.core.entry_store import entries_dir

_DB_NAME = "memory.db"
_SCHEMA = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    id,
    type,
    tags,
    content
);
"""


# ---------------------------------------------------------------------------
# SearchBackend protocol — the pluggable seam
# ---------------------------------------------------------------------------

@runtime_checkable
class SearchBackend(Protocol):
    """Interface every search backend must satisfy.

    Implementations:
        FTS5Backend  — SQLite FTS5 keyword/BM25 (default, shipped here)
        (future)     — embedding / vector backend (TASK-43, out of scope now)
    """

    def index(
        self,
        entry_id: str,
        entry_type: str,
        tags: list[str],
        content: str,
        memory_root: Path,
    ) -> None:
        """Insert or replace a single entry in the search index."""
        ...

    def remove(self, entry_id: str, memory_root: Path) -> None:
        """Remove a single entry from the search index."""
        ...

    def rebuild(self, memory_root: Path) -> dict[str, int]:
        """Drop and rebuild the full index from entries on disk.

        Returns {"indexed": <count>, "errors": <count>}.
        """
        ...

    def search(self, query: str, memory_root: Path) -> list[dict[str, Any]]:
        """Keyword search; returns list of dicts with id, type, tags, content."""
        ...

    def status(self, memory_root: Path) -> dict[str, Any]:
        """Return {"files": n, "indexed": n, "in_sync": bool}."""
        ...


# ---------------------------------------------------------------------------
# FTS5Backend — SQLite FTS5 keyword / BM25 implementation
# ---------------------------------------------------------------------------

class FTS5Backend:
    """SQLite FTS5 full-text keyword search (BM25 ranking).

    This is the default and only backend shipped with the framework.
    It stores a local SQLite cache (gitignored) alongside the committed
    .claude/memory/entries/ directory.
    """

    # -- internal helpers -----------------------------------------------

    @staticmethod
    def _db_path(memory_root: Path) -> Path:
        return memory_root / _DB_NAME

    @classmethod
    def _open_db(cls, db_path: Path) -> sqlite3.Connection:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.commit()
        return conn

    # -- SearchBackend implementation -----------------------------------

    def index(
        self,
        entry_id: str,
        entry_type: str,
        tags: list[str],
        content: str,
        memory_root: Path,
    ) -> None:
        """Insert or replace a single entry in the FTS5 index."""
        db_path = self._db_path(memory_root)
        conn = self._open_db(db_path)
        try:
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (entry_id,))
            conn.execute(
                "INSERT INTO memory_fts(id, type, tags, content) VALUES (?, ?, ?, ?)",
                (entry_id, entry_type, " ".join(tags), content),
            )
            conn.commit()
        finally:
            conn.close()

    def remove(self, entry_id: str, memory_root: Path) -> None:
        """Remove a single entry from the FTS5 index."""
        db_path = self._db_path(memory_root)
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("DELETE FROM memory_fts WHERE id = ?", (entry_id,))
            conn.commit()
        finally:
            conn.close()

    def rebuild(self, memory_root: Path) -> dict[str, int]:
        """Drop and rebuild the FTS5 index from all .md files in entries/."""
        e_dir = entries_dir(memory_root)
        db_path = self._db_path(memory_root)

        conn = self._open_db(db_path)
        try:
            conn.execute("DELETE FROM memory_fts")
            conn.commit()

            indexed = 0
            errors = 0

            if e_dir.exists():
                for path in sorted(e_dir.glob("*.md")):
                    try:
                        text = path.read_text(encoding="utf-8")
                        fm, body = parse_frontmatter(text)
                        tags_str = " ".join(fm.get("tags") or [])
                        conn.execute(
                            "INSERT INTO memory_fts(id, type, tags, content) VALUES (?, ?, ?, ?)",
                            (fm.get("id", ""), fm.get("type", ""), tags_str, body),
                        )
                        indexed += 1
                    except (EntryValidationError, OSError):
                        errors += 1

            conn.commit()
        finally:
            conn.close()

        return {"indexed": indexed, "errors": errors}

    def search(self, query: str, memory_root: Path) -> list[dict[str, Any]]:
        """FTS5 keyword search (BM25) against the SQLite index.

        Returns list of dicts with id, type, tags, content snippet.
        Falls back to empty list if DB doesn't exist.
        """
        db_path = self._db_path(memory_root)
        if not db_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(db_path))
            try:
                rows = conn.execute(
                    "SELECT id, type, tags, content FROM memory_fts WHERE memory_fts MATCH ?",
                    (query,),
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []

        return [
            {"id": r[0], "type": r[1], "tags": r[2].split() if r[2] else [], "content": r[3]}
            for r in rows
        ]

    def status(self, memory_root: Path) -> dict[str, Any]:
        """Compare file count vs indexed entry count."""
        e_dir = entries_dir(memory_root)
        file_count = len(list(e_dir.glob("*.md"))) if e_dir.exists() else 0

        db_path = self._db_path(memory_root)
        if not db_path.exists():
            return {"files": file_count, "indexed": 0, "in_sync": file_count == 0}

        try:
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()
                indexed_count = row[0] if row else 0
            finally:
                conn.close()
        except sqlite3.Error:
            return {"files": file_count, "indexed": 0, "in_sync": False}

        return {
            "files": file_count,
            "indexed": indexed_count,
            "in_sync": file_count == indexed_count,
        }


# ---------------------------------------------------------------------------
# Module-level default backend
# ---------------------------------------------------------------------------

_default_backend: SearchBackend = FTS5Backend()


def get_default_backend() -> SearchBackend:
    """Return the active default backend (FTS5 keyword/BM25)."""
    return _default_backend


def set_default_backend(backend: SearchBackend) -> None:
    """Override the default backend (used by tests or future embedding backend)."""
    global _default_backend
    _default_backend = backend


# ---------------------------------------------------------------------------
# Public module-level functions (thin wrappers; callers unchanged)
# ---------------------------------------------------------------------------

def rebuild_index(memory_root: Path, *, backend: SearchBackend | None = None) -> dict[str, int]:
    """Drop and rebuild the full-text index from all entries on disk.

    Returns {"indexed": <count>, "errors": <count>}.
    """
    return (backend or _default_backend).rebuild(memory_root)


def index_status(memory_root: Path, *, backend: SearchBackend | None = None) -> dict[str, Any]:
    """Compare file count vs indexed entry count.

    Returns {"files": <n>, "indexed": <n>, "in_sync": <bool>}.
    """
    return (backend or _default_backend).status(memory_root)


def search_index(query: str, memory_root: Path, *, backend: SearchBackend | None = None) -> list[dict[str, Any]]:
    """Full-text keyword (FTS5/BM25) search against the index.

    Returns list of dicts with id, type, tags, content snippet.
    Falls back to empty list if index does not exist.
    """
    return (backend or _default_backend).search(query, memory_root)


def index_entry(
    entry_id: str,
    entry_type: str,
    tags: list[str],
    content: str,
    memory_root: Path,
    *,
    backend: SearchBackend | None = None,
) -> None:
    """Insert or replace a single entry in the index."""
    (backend or _default_backend).index(entry_id, entry_type, tags, content, memory_root)


def remove_from_index(
    entry_id: str,
    memory_root: Path,
    *,
    backend: SearchBackend | None = None,
) -> None:
    """Remove a single entry from the index."""
    (backend or _default_backend).remove(entry_id, memory_root)
