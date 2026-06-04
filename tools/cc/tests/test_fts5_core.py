"""Tests for cc.core.fts5_core — canonical FTS5 mechanism helpers.

Covers:
- create_fts(): standalone form (cc) and external-content form (tc)
- create_content_triggers(): insert/delete/update trigger trio
- escape_fts_query(): adversarial input handling
- fts_match(): BM25 ORDER BY rank, snippet, limit
- Byte-identity guard: cc canonical copy == tc vendored copy
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cc.core.fts5_core import (
    create_content_triggers,
    create_fts,
    escape_fts_query,
    fts_match,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn():
    """In-memory SQLite connection for isolation."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA journal_mode=WAL")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# 39.1 Tests: DDL builders
# ---------------------------------------------------------------------------


class TestCreateFts:
    def test_standalone_table_created(self, conn):
        """create_fts() without content_table creates a standalone FTS5 table."""
        create_fts(conn, "test_fts", ["id", "type", "content"])
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_fts'"
        ).fetchall()
        assert len(rows) == 1

    def test_standalone_insert_and_query(self, conn):
        """Standalone FTS5 table supports INSERT and MATCH."""
        create_fts(conn, "mem_fts", ["id", "content"])
        conn.commit()
        conn.execute(
            "INSERT INTO mem_fts(id, content) VALUES (?, ?)", ("abc", "hello world")
        )
        conn.commit()
        rows = conn.execute(
            "SELECT id FROM mem_fts WHERE mem_fts MATCH ? ORDER BY rank", ("hello",)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "abc"

    def test_external_content_table_created(self, conn):
        """create_fts() with content_table creates an external-content FTS5 table."""
        conn.execute("CREATE TABLE wp (id INTEGER PRIMARY KEY, title TEXT, body TEXT)")
        create_fts(
            conn,
            "wp_fts",
            ["title", "body"],
            content_table="wp",
            content_rowid="id",
        )
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='wp_fts'"
        ).fetchall()
        assert len(rows) == 1

    def test_idempotent_if_not_exists(self, conn):
        """create_fts() can be called twice without error (IF NOT EXISTS)."""
        create_fts(conn, "idempotent_fts", ["content"])
        conn.commit()
        create_fts(conn, "idempotent_fts", ["content"])  # must not raise
        conn.commit()

    def test_custom_tokenizer_in_ddl(self, conn):
        """create_fts() with a custom tokenizer name does not raise."""
        create_fts(conn, "tok_fts", ["content"], tokenizer="ascii")
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='tok_fts'"
        ).fetchall()
        assert len(rows) == 1


class TestCreateContentTriggers:
    def test_triggers_created(self, conn):
        """create_content_triggers() creates the three expected triggers."""
        conn.execute(
            "CREATE TABLE base (id INTEGER PRIMARY KEY, title TEXT, body TEXT)"
        )
        create_fts(
            conn,
            "base_fts",
            ["title", "body"],
            content_table="base",
            content_rowid="id",
        )
        create_content_triggers(conn, "base", "base_fts", ["title", "body"])
        conn.commit()

        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
        names = {r[0] for r in triggers}
        assert "base_fts_insert" in names
        assert "base_fts_delete" in names
        assert "base_fts_update" in names

    def test_insert_trigger_indexes_new_row(self, conn):
        """Inserting into base table populates FTS5 via trigger."""
        conn.execute(
            "CREATE TABLE base (id INTEGER PRIMARY KEY, title TEXT, body TEXT)"
        )
        create_fts(
            conn,
            "base_fts",
            ["title", "body"],
            content_table="base",
            content_rowid="id",
        )
        create_content_triggers(conn, "base", "base_fts", ["title", "body"])
        conn.commit()

        conn.execute(
            "INSERT INTO base (title, body) VALUES (?, ?)", ("Hello", "World content")
        )
        conn.commit()

        rows = conn.execute(
            "SELECT base.title FROM base "
            "JOIN base_fts ON base.id = base_fts.rowid "
            "WHERE base_fts MATCH ? ORDER BY rank",
            ("World",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Hello"

    def test_delete_trigger_removes_from_fts(self, conn):
        """Deleting from base table removes from FTS5 via trigger."""
        conn.execute(
            "CREATE TABLE base (id INTEGER PRIMARY KEY, title TEXT, body TEXT)"
        )
        create_fts(
            conn,
            "base_fts",
            ["title", "body"],
            content_table="base",
            content_rowid="id",
        )
        create_content_triggers(conn, "base", "base_fts", ["title", "body"])
        conn.commit()

        conn.execute(
            "INSERT INTO base (title, body) VALUES (?, ?)", ("Gone", "ephemeral")
        )
        conn.commit()
        conn.execute("DELETE FROM base WHERE title = 'Gone'")
        conn.commit()

        rows = conn.execute(
            "SELECT rowid FROM base_fts WHERE base_fts MATCH ? ORDER BY rank",
            ("ephemeral",),
        ).fetchall()
        assert len(rows) == 0

    def test_update_trigger_refreshes_fts(self, conn):
        """Updating base table refreshes FTS5 via trigger."""
        conn.execute(
            "CREATE TABLE base (id INTEGER PRIMARY KEY, title TEXT, body TEXT)"
        )
        create_fts(
            conn,
            "base_fts",
            ["title", "body"],
            content_table="base",
            content_rowid="id",
        )
        create_content_triggers(conn, "base", "base_fts", ["title", "body"])
        conn.commit()

        conn.execute(
            "INSERT INTO base (title, body) VALUES (?, ?)", ("Old title", "old body")
        )
        conn.commit()
        conn.execute(
            "UPDATE base SET title='New title', body='new body' WHERE title='Old title'"
        )
        conn.commit()

        old_rows = conn.execute(
            "SELECT rowid FROM base_fts WHERE base_fts MATCH ? ORDER BY rank",
            ("old",),
        ).fetchall()
        new_rows = conn.execute(
            "SELECT rowid FROM base_fts WHERE base_fts MATCH ? ORDER BY rank",
            ("new",),
        ).fetchall()
        assert len(new_rows) == 1
        # "old" should no longer match (body was replaced)
        assert len(old_rows) == 0

    def test_triggers_idempotent(self, conn):
        """create_content_triggers() can be called twice without error."""
        conn.execute("CREATE TABLE base2 (id INTEGER PRIMARY KEY, title TEXT)")
        create_fts(
            conn, "base2_fts", ["title"], content_table="base2", content_rowid="id"
        )
        create_content_triggers(conn, "base2", "base2_fts", ["title"])
        conn.commit()
        create_content_triggers(conn, "base2", "base2_fts", ["title"])  # must not raise
        conn.commit()


# ---------------------------------------------------------------------------
# 39.1 Tests: escape_fts_query
# ---------------------------------------------------------------------------


class TestEscapeFtsQuery:
    def test_plain_query_unchanged(self):
        assert escape_fts_query("hello") == "hello"

    def test_multi_word_plain_unchanged(self):
        result = escape_fts_query("python search")
        assert result == "python search"

    def test_empty_string_returns_safe(self):
        result = escape_fts_query("")
        assert result == '""'

    def test_whitespace_only_returns_safe(self):
        result = escape_fts_query("   ")
        assert result == '""'

    def test_bare_AND_operator_is_escaped(self):
        result = escape_fts_query("foo AND bar")
        assert result.startswith('"') and result.endswith('"')

    def test_bare_OR_operator_is_escaped(self):
        result = escape_fts_query("foo OR bar")
        assert result.startswith('"') and result.endswith('"')

    def test_bare_NOT_operator_is_escaped(self):
        result = escape_fts_query("NOT foo")
        assert result.startswith('"') and result.endswith('"')

    def test_star_wildcard_is_escaped(self):
        result = escape_fts_query("foo*")
        assert result.startswith('"') and result.endswith('"')

    def test_unbalanced_quote_is_escaped(self):
        result = escape_fts_query('unbalanced "quote')
        assert result.startswith('"') and result.endswith('"')

    def test_balanced_quoted_phrase_preserved(self):
        """A properly quoted phrase should not be double-quoted."""
        result = escape_fts_query('"exact phrase"')
        # Balanced quotes — should be left as-is
        assert result == '"exact phrase"'

    def test_escaped_query_does_not_raise_in_fts5(self, conn):
        """Escaped queries must never cause SQLite DatabaseError."""
        create_fts(conn, "escape_fts", ["content"])
        conn.commit()
        conn.execute("INSERT INTO escape_fts(content) VALUES (?)", ("test content",))
        conn.commit()

        adversarial = [
            'unbalanced "quote',
            "foo AND",
            "OR bar",
            "NOT",
            "foo*",
            "** invalid **",
            "",
            '"',
        ]
        for raw in adversarial:
            safe = escape_fts_query(raw)
            # Must not raise
            conn.execute(
                "SELECT content FROM escape_fts WHERE escape_fts MATCH ?",
                (safe,),
            ).fetchall()


# ---------------------------------------------------------------------------
# 39.1 Tests: fts_match
# ---------------------------------------------------------------------------


class TestFtsMatch:
    def test_basic_match_returns_results(self, conn):
        """fts_match returns rows for a matching query."""
        create_fts(conn, "fm_fts", ["id", "content"])
        conn.commit()
        conn.execute(
            "INSERT INTO fm_fts(id, content) VALUES (?, ?)", ("id-1", "unique_term_xyz")
        )
        conn.execute(
            "INSERT INTO fm_fts(id, content) VALUES (?, ?)", ("id-2", "other content")
        )
        conn.commit()

        rows = fts_match(
            conn,
            "fm_fts",
            "unique_term_xyz",
            select="id, content",
        )
        assert len(rows) == 1
        assert rows[0][0] == "id-1"

    def test_order_by_rank_bm25(self, conn):
        """fts_match orders results by BM25 rank (highest relevance first)."""
        create_fts(conn, "rank_fts", ["content"])
        conn.commit()
        # "relevance" appears once in each; second row has it twice
        conn.execute(
            "INSERT INTO rank_fts(content) VALUES (?)", ("relevance mentioned once",)
        )
        conn.execute(
            "INSERT INTO rank_fts(content) VALUES (?)",
            ("relevance relevance twice here",),
        )
        conn.commit()

        rows = fts_match(conn, "rank_fts", "relevance", select="content")
        assert len(rows) == 2
        # The row with "relevance" appearing twice should rank first
        assert "twice" in rows[0][0]

    def test_limit_caps_results(self, conn):
        """fts_match with limit= returns at most that many rows."""
        create_fts(conn, "lim_fts", ["content"])
        conn.commit()
        for i in range(5):
            conn.execute(
                "INSERT INTO lim_fts(content) VALUES (?)", (f"item number {i}",)
            )
        conn.commit()

        rows = fts_match(conn, "lim_fts", "item", select="content", limit=3)
        assert len(rows) <= 3

    def test_snippet_col_appended(self, conn):
        """fts_match with snippet_col= appends a snippet column."""
        create_fts(conn, "snip_fts", ["content"])
        conn.commit()
        conn.execute(
            "INSERT INTO snip_fts(content) VALUES (?)",
            ("The quick brown fox jumps over the lazy dog",),
        )
        conn.commit()

        rows = fts_match(
            conn,
            "snip_fts",
            "fox",
            select="content",
            snippet_col=0,
        )
        assert len(rows) == 1
        # Row is (content, snippet) — snippet column should contain "fox"
        assert "fox" in rows[0][1].lower()

    def test_no_match_returns_empty(self, conn):
        """fts_match returns empty list when nothing matches."""
        create_fts(conn, "empty_fts", ["content"])
        conn.commit()
        conn.execute("INSERT INTO empty_fts(content) VALUES (?)", ("something",))
        conn.commit()

        rows = fts_match(conn, "empty_fts", "zyxqvw", select="content")
        assert rows == []

    def test_join_form(self, conn):
        """fts_match supports a JOIN clause for external-content tables."""
        conn.execute(
            "CREATE TABLE base (id INTEGER PRIMARY KEY, title TEXT, body TEXT)"
        )
        create_fts(
            conn,
            "base_fts",
            ["title", "body"],
            content_table="base",
            content_rowid="id",
        )
        create_content_triggers(conn, "base", "base_fts", ["title", "body"])
        conn.commit()

        conn.execute(
            "INSERT INTO base (title, body) VALUES (?, ?)",
            ("join test", "xyzzy content"),
        )
        conn.commit()

        rows = fts_match(
            conn,
            "base_fts",
            "xyzzy",
            select="base.*",
            join="JOIN base ON base.id = base_fts.rowid",
        )
        assert len(rows) == 1
        assert rows[0][1] == "join test"


# ---------------------------------------------------------------------------
# 39.2 Byte-identity guard
# ---------------------------------------------------------------------------


class TestByteIdentityGuard:
    """Fitness function: canonical cc copy == vendored tc copy.

    This test will fail in CI if the two files drift, forcing a manual sync.
    """

    def test_cc_and_tc_fts5_core_are_byte_identical(self):
        """cc/core/fts5_core.py and tc/db/fts5_core.py must be byte-identical."""
        here = Path(__file__).resolve()
        # Navigate from tools/cc/tests/ to the repo root
        repo_root = here.parents[3]  # tools/cc/tests -> tools/cc -> tools -> repo root

        cc_path = repo_root / "tools" / "cc" / "src" / "cc" / "core" / "fts5_core.py"
        tc_path = repo_root / "tools" / "tc" / "src" / "tc" / "db" / "fts5_core.py"

        assert cc_path.exists(), f"cc canonical copy not found: {cc_path}"
        assert tc_path.exists(), f"tc vendored copy not found: {tc_path}"

        cc_bytes = cc_path.read_bytes()
        tc_bytes = tc_path.read_bytes()

        assert cc_bytes == tc_bytes, (
            "fts5_core.py has drifted between cc and tc. "
            f"Update {tc_path} to match {cc_path} (canonical)."
        )
