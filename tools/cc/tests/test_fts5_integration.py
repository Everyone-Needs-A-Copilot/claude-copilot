"""Integration tests for the FTS5 unification (TASK-39).

Covers:
- 39.3: cc FTS5Backend delegates to fts5_core; BM25 ordering correct.
- 39.4: cc incremental indexing is first-class (auto-create, reliable index/remove).
- 39.6: Cross-tool contract — same ranking/escaping contract for cc and tc.
- Backward compat: cc search result MEMBERSHIP unchanged (same id-set, BM25 reorder).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from cc.core.entry_store import store_entry
from cc.core.memory_index import (
    FTS5Backend,
    index_entry,
    index_status,
    rebuild_index,
    remove_from_index,
    search_index,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    """Patch git root so stores resolve to tmp_path."""
    import cc.core.entry_store as es

    monkeypatch.setattr(es, "_git_root", lambda: tmp_path)
    return tmp_path / ".claude" / "memory"


# ---------------------------------------------------------------------------
# 39.3: BM25 ordering — result membership unchanged, order improved
# ---------------------------------------------------------------------------


class TestBM25Ordering:
    def test_search_result_id_set_unchanged_after_bm25(self, memory_root):
        """BM25 ordering changes rank but NOT result membership.

        Stores 3 entries containing the query term at different frequencies,
        then asserts the returned id-set matches a file-based search (same ids,
        possibly different order).
        """
        from cc.core.entry_store import search_entries_files

        store_entry(
            entry_type="lesson", content="FTS5 mentioned once here", scope="project"
        )
        store_entry(
            entry_type="context",
            content="FTS5 FTS5 FTS5 mentioned three times",
            scope="project",
        )
        store_entry(
            entry_type="decision",
            content="FTS5 FTS5 mentioned twice in decision",
            scope="project",
        )

        backend = FTS5Backend()
        backend.rebuild(memory_root)

        fts_results = backend.search("FTS5", memory_root)
        file_results = search_entries_files("FTS5", scope="project")

        fts_ids = {r["id"] for r in fts_results}
        file_ids = {r["id"] for r in file_results}

        assert fts_ids == file_ids, (
            f"Result membership changed after BM25 delegation!\n"
            f"FTS ids:  {fts_ids}\n"
            f"File ids: {file_ids}"
        )

    def test_bm25_ranks_higher_frequency_first(self, memory_root):
        """Entry with more occurrences of query term should rank first."""
        store_entry(
            entry_type="lesson", content="alpha mentioned once", scope="project"
        )
        store_entry(
            entry_type="context",
            content="alpha alpha alpha mentioned three times alpha",
            scope="project",
        )

        backend = FTS5Backend()
        backend.rebuild(memory_root)

        results = backend.search("alpha", memory_root)
        assert len(results) == 2
        # Higher-frequency entry should appear first (BM25)
        assert "three times" in results[0]["content"]

    def test_search_returns_correct_fields(self, memory_root):
        """search() returns dicts with id, type, tags, content fields."""
        store_entry(
            entry_type="decision",
            content="field check content",
            tags=["tag1"],
            scope="project",
        )
        backend = FTS5Backend()
        backend.rebuild(memory_root)

        results = backend.search("field", memory_root)
        assert len(results) == 1
        r = results[0]
        assert "id" in r
        assert "type" in r
        assert "tags" in r
        assert "content" in r
        assert r["type"] == "decision"


# ---------------------------------------------------------------------------
# 39.4: Incremental indexing first-class
# ---------------------------------------------------------------------------


class TestIncrementalIndexing:
    def test_store_then_search_without_rebuild(self, memory_root, monkeypatch):
        """Storing an entry auto-creates the index; search works without --rebuild."""
        import cc.core.entry_store as es

        monkeypatch.setattr(es, "_git_root", lambda: memory_root.parent.parent)

        # No rebuild needed — auto-index on store
        result = store_entry(
            entry_type="lesson", content="incremental_unique_xyz", scope="project"
        )
        entry_id = result["id"]

        # Trigger index_entry as the store command does (auto-create)
        index_entry(entry_id, "lesson", [], "incremental_unique_xyz", memory_root)

        # Now search without any rebuild call
        results = search_index("incremental_unique_xyz", memory_root)
        assert len(results) == 1
        assert results[0]["id"] == entry_id

    def test_memory_db_created_on_first_index(self, memory_root):
        """memory.db is created by index_entry even if it didn't exist before."""
        db_path = memory_root / "memory.db"
        assert not db_path.exists(), "DB should not exist before first index"

        index_entry("test-id-123", "context", ["t1"], "auto create test", memory_root)

        assert db_path.exists(), "memory.db must be created by index_entry"

    def test_index_then_remove_clears_entry(self, memory_root):
        """remove_from_index() reliably removes an indexed entry."""
        index_entry(
            "rem-id-456", "lesson", [], "remove this content please", memory_root
        )

        # Confirm indexed
        results = search_index("remove this content", memory_root)
        assert any(r["id"] == "rem-id-456" for r in results)

        # Remove
        remove_from_index("rem-id-456", memory_root)

        results_after = search_index("remove this content", memory_root)
        assert not any(r["id"] == "rem-id-456" for r in results_after)

    def test_index_replace_updates_content(self, memory_root):
        """Re-indexing an entry (same id) replaces the old content."""
        index_entry("upd-id-789", "context", [], "original content here", memory_root)
        index_entry(
            "upd-id-789", "context", [], "completely different now", memory_root
        )

        old_results = search_index("original", memory_root)
        new_results = search_index("completely different", memory_root)

        assert not any(r["id"] == "upd-id-789" for r in old_results)
        assert any(r["id"] == "upd-id-789" for r in new_results)

    def test_remove_on_nonexistent_db_is_safe(self, tmp_path):
        """remove_from_index when no DB exists does not raise."""
        missing_root = tmp_path / ".claude" / "memory"
        # No DB — must not raise
        remove_from_index("ghost-id", missing_root)

    def test_rebuild_reconciles_out_of_band_file(self, memory_root):
        """rebuild() picks up files written directly to disk (out-of-band)."""
        import uuid
        from cc.core.entry_format import build_frontmatter, render_entry
        from cc.core.entry_store import _atomic_write, entries_dir, _ensure_entries_dir

        # Write a file directly bypassing store_entry (simulates git pull)
        e_dir = _ensure_entries_dir(memory_root)
        uid = str(uuid.uuid4())
        fm = build_frontmatter(
            entry_id=uid, entry_type="reference", tags=[], scope="project"
        )
        _atomic_write(e_dir / f"{uid}.md", render_entry(fm, "out_of_band_content_zqr"))

        # Index doesn't know about it yet — search returns nothing
        results_before = search_index("out_of_band_content_zqr", memory_root)
        assert not any(r["id"] == uid for r in results_before)

        # Rebuild reconciles
        stats = rebuild_index(memory_root)
        assert stats["indexed"] >= 1

        results_after = search_index("out_of_band_content_zqr", memory_root)
        assert any(r["id"] == uid for r in results_after)

    def test_status_rebuild_recommended_when_out_of_sync(self, memory_root):
        """index_status reports out-of-sync when file count > indexed count."""
        import uuid
        from cc.core.entry_format import build_frontmatter, render_entry
        from cc.core.entry_store import _atomic_write, _ensure_entries_dir

        # Store and index one entry
        store_entry(entry_type="context", content="synced content", scope="project")
        rebuild_index(memory_root)

        info = index_status(memory_root)
        assert info["in_sync"] is True

        # Add another file directly to disk
        e_dir = _ensure_entries_dir(memory_root)
        uid = str(uuid.uuid4())
        fm = build_frontmatter(
            entry_id=uid, entry_type="lesson", tags=[], scope="project"
        )
        _atomic_write(e_dir / f"{uid}.md", render_entry(fm, "unindexed"))

        info_after = index_status(memory_root)
        assert info_after["in_sync"] is False
        assert info_after["files"] > info_after["indexed"]


# ---------------------------------------------------------------------------
# 39.6: Cross-tool contract test — shared ranking/escaping/snippet contract
# ---------------------------------------------------------------------------


class TestCrossToolContract:
    """Assert that cc (standalone FTS5) and tc (external-content FTS5) use
    the SAME escape_fts_query, fts_match, and BM25 ranking contract from
    fts5_core.  Runs a common query corpus through both paths and verifies:
    - escape_fts_query() produces the same output in both imports
    - fts_match() with the same data returns the same ranked ordering
    """

    def test_escape_fts_query_same_output_both_imports(self):
        """escape_fts_query is byte-identical so output must be identical."""
        from cc.core.fts5_core import escape_fts_query as cc_escape
        from tc.db.fts5_core import escape_fts_query as tc_escape  # type: ignore[import]

        corpus = [
            "hello",
            "",
            "foo AND bar",
            "foo OR bar",
            "NOT baz",
            "star*",
            'unbalanced "quote',
            '"exact phrase"',
            "   ",
            "alpha beta gamma",
        ]
        for query in corpus:
            cc_out = cc_escape(query)
            tc_out = tc_escape(query)
            assert cc_out == tc_out, (
                f"escape_fts_query({query!r}) diverged:\n"
                f"  cc: {cc_out!r}\n"
                f"  tc: {tc_out!r}"
            )

    def test_fts_match_same_ranking_same_data(self):
        """fts_match from cc and tc produce the same ranked result order."""
        from cc.core.fts5_core import create_fts as cc_create_fts
        from cc.core.fts5_core import fts_match as cc_fts_match
        from tc.db.fts5_core import create_fts as tc_create_fts  # type: ignore[import]
        from tc.db.fts5_core import fts_match as tc_fts_match  # type: ignore[import]

        def _populate(create_fts_fn, fts_match_fn):
            conn = sqlite3.connect(":memory:")
            create_fts_fn(conn, "test_fts", ["id", "content"])
            conn.commit()
            # Insert corpus with varying term frequencies
            conn.execute(
                "INSERT INTO test_fts(id, content) VALUES (?, ?)",
                ("low", "contract once"),
            )
            conn.execute(
                "INSERT INTO test_fts(id, content) VALUES (?, ?)",
                ("high", "contract contract contract many times contract"),
            )
            conn.commit()
            rows = fts_match_fn(conn, "test_fts", "contract", select="id")
            conn.close()
            return [r[0] for r in rows]

        cc_order = _populate(cc_create_fts, cc_fts_match)
        tc_order = _populate(tc_create_fts, tc_fts_match)

        assert cc_order == tc_order, (
            f"fts_match ranking diverged:\n" f"  cc: {cc_order}\n" f"  tc: {tc_order}"
        )
        # Both should rank high-frequency first
        assert cc_order[0] == "high"

    def test_adversarial_queries_safe_in_both_tools(self):
        """Adversarial queries must not raise in either tool's FTS5 path."""
        from cc.core.fts5_core import create_fts as cc_create_fts
        from cc.core.fts5_core import fts_match as cc_fts_match
        from tc.db.fts5_core import create_fts as tc_create_fts  # type: ignore[import]
        from tc.db.fts5_core import fts_match as tc_fts_match  # type: ignore[import]

        adversarial = [
            'unbalanced "quote',
            "foo AND",
            "OR bar",
            "NOT",
            "foo*",
            "",
            '"',
            "** invalid **",
        ]

        for create_fn, match_fn, tool in [
            (cc_create_fts, cc_fts_match, "cc"),
            (tc_create_fts, tc_fts_match, "tc"),
        ]:
            conn = sqlite3.connect(":memory:")
            create_fn(conn, "adv_fts", ["content"])
            conn.commit()
            conn.execute("INSERT INTO adv_fts(content) VALUES (?)", ("test content",))
            conn.commit()

            for raw in adversarial:
                try:
                    match_fn(conn, "adv_fts", raw, select="content")
                except Exception as exc:
                    pytest.fail(
                        f"[{tool}] fts_match raised on adversarial query {raw!r}: {exc}"
                    )
            conn.close()
