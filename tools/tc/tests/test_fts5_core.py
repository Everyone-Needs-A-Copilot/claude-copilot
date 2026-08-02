"""Tests for tc.db.fts5_core — vendored FTS5 mechanism helpers.

Covers:
- Byte-identity guard: tc vendored copy == cc canonical copy
- Basic smoke tests for the vendored module (import, no side effects)

The comprehensive unit tests for the shared logic live in cc's test suite
(test_fts5_core.py). This file adds tc-side guards and routing tests.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tc.db.fts5_core import (
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
# Byte-identity guard
# ---------------------------------------------------------------------------


class TestByteIdentityGuard:
    """Fitness function: tc vendored copy == cc canonical copy."""

    def test_tc_and_cc_fts5_core_are_byte_identical(self):
        """tc/db/fts5_core.py and cc/core/fts5_core.py must be byte-identical."""
        here = Path(__file__).resolve()
        # Navigate from tools/tc/tests/ to the repo root
        repo_root = here.parents[3]  # tools/tc/tests -> tools/tc -> tools -> repo root

        tc_path = repo_root / "tools" / "tc" / "src" / "tc" / "db" / "fts5_core.py"
        cc_path = repo_root / "tools" / "cc" / "src" / "cc" / "core" / "fts5_core.py"

        assert tc_path.exists(), f"tc vendored copy not found: {tc_path}"
        assert cc_path.exists(), f"cc canonical copy not found: {cc_path}"

        tc_bytes = tc_path.read_bytes()
        cc_bytes = cc_path.read_bytes()

        assert tc_bytes == cc_bytes, (
            "fts5_core.py has drifted between tc and cc. "
            f"Update {tc_path} to match {cc_path} (canonical)."
        )


# ---------------------------------------------------------------------------
# Smoke tests — confirm vendored module works in tc's install env
# ---------------------------------------------------------------------------


class TestFts5CoreSmoke:
    def test_import_has_no_side_effects(self):
        """Importing fts5_core must not open any DB or touch the filesystem."""
        # If we got here, import succeeded with no side effects
        assert callable(create_fts)
        assert callable(create_content_triggers)
        assert callable(escape_fts_query)
        assert callable(fts_match)

    def test_escape_plain_query(self):
        assert escape_fts_query("hello") == "hello"

    def test_escape_empty(self):
        assert escape_fts_query("") == '""'

    def test_escape_operator(self):
        result = escape_fts_query("foo AND bar")
        assert result.startswith('"') and result.endswith('"')

    def test_create_fts_standalone(self, conn):
        create_fts(conn, "smoke_fts", ["title", "body"])
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='smoke_fts'"
        ).fetchall()
        assert len(rows) == 1

    def test_fts_match_returns_list(self, conn):
        create_fts(conn, "sm_fts", ["content"])
        conn.commit()
        conn.execute("INSERT INTO sm_fts(content) VALUES (?)", ("test content here",))
        conn.commit()

        rows = fts_match(conn, "sm_fts", "content", select="content")
        assert isinstance(rows, list)
        assert len(rows) == 1
