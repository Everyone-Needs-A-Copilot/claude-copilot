"""Canonical FTS5 mechanism helpers — shared (vendored) between cc and tc.

This module is the CANONICAL COPY. The copy at tc/db/fts5_core.py MUST remain
byte-identical; a byte-identity guard test in both suites catches drift in CI.

Provides:
    create_fts()               — CREATE VIRTUAL TABLE DDL for standalone or
                                 external-content FTS5 tables.
    create_content_triggers()  — INSERT/DELETE/UPDATE trigger trio for
                                 external-content FTS5 (tc form).
    escape_fts_query()         — Sanitise a raw search string into a safe
                                 FTS5 MATCH expression (phrase-quote unknown
                                 operators so malformed input never raises).
    fts_match()                — One MATCH + ORDER BY rank (BM25) query path
                                 with optional snippet() and LIMIT.

Design notes:
    - stdlib-only (sqlite3, pathlib): works in either tool's install env with
      zero additional dependencies.
    - ZERO import-time side effects (no DB open, no file I/O).
    - TASK-43: an embedding backend slots under cc's SearchBackend seam; this
      module is the FTS5 (keyword/BM25) half of that seam only.
    - Vendored copy lives at tools/tc/src/tc/db/fts5_core.py — keep in sync
      via the byte-identity guard test in both suites.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Optional


# ---------------------------------------------------------------------------
# DDL builders
# ---------------------------------------------------------------------------

def create_fts(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    *,
    content_table: Optional[str] = None,
    content_rowid: Optional[str] = None,
    tokenizer: str = "unicode61",
) -> None:
    """Emit CREATE VIRTUAL TABLE IF NOT EXISTS for an FTS5 table.

    Args:
        conn:          Open SQLite connection.
        table:         Name for the FTS5 virtual table.
        columns:       Ordered list of column names to index.
        content_table: If set, creates an external-content FTS5 table that
                       mirrors *content_table* (tc form).  Requires
                       *content_rowid* to also be set.
        content_rowid: Rowid column name on *content_table* (e.g. ``'id'``).
        tokenizer:     FTS5 tokenizer; defaults to ``unicode61``.

    The generated DDL is idempotent (IF NOT EXISTS).
    """
    col_list = ", ".join(columns)
    options = [f"tokenize='{tokenizer}'"]
    if content_table is not None:
        options.append(f"content='{content_table}'")
    if content_rowid is not None:
        options.append(f"content_rowid='{content_rowid}'")
    options_sql = ", ".join(options)
    ddl = (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5("
        f"{col_list}, {options_sql})"
    )
    conn.execute(ddl)


def create_content_triggers(
    conn: sqlite3.Connection,
    table: str,
    fts_table: str,
    columns: list[str],
    *,
    rowid: str = "id",
) -> None:
    """Emit INSERT / DELETE / UPDATE triggers for an external-content FTS5 table.

    Generates the canonical three-trigger pattern required by SQLite's
    external-content FTS5: wp_fts_insert, wp_fts_delete, wp_fts_update.
    All triggers are created with IF NOT EXISTS.

    Args:
        conn:      Open SQLite connection.
        table:     Base (content) table name.
        fts_table: FTS5 virtual table name.
        columns:   Column names to keep in sync (same order as in create_fts).
        rowid:     Primary-key / rowid column on *table* (default ``'id'``).
    """
    col_list = ", ".join(columns)
    new_vals = ", ".join(f"new.{c}" for c in columns)
    old_vals = ", ".join(f"old.{c}" for c in columns)

    conn.executescript(f"""
    CREATE TRIGGER IF NOT EXISTS {table}_fts_insert
    AFTER INSERT ON {table} BEGIN
        INSERT INTO {fts_table}(rowid, {col_list})
        VALUES (new.{rowid}, {new_vals});
    END;

    CREATE TRIGGER IF NOT EXISTS {table}_fts_delete
    AFTER DELETE ON {table} BEGIN
        INSERT INTO {fts_table}({fts_table}, rowid, {col_list})
        VALUES ('delete', old.{rowid}, {old_vals});
    END;

    CREATE TRIGGER IF NOT EXISTS {table}_fts_update
    AFTER UPDATE ON {table} BEGIN
        INSERT INTO {fts_table}({fts_table}, rowid, {col_list})
        VALUES ('delete', old.{rowid}, {old_vals});
        INSERT INTO {fts_table}(rowid, {col_list})
        VALUES (new.{rowid}, {new_vals});
    END;
    """)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

_BARE_OPERATOR = re.compile(
    r'\b(AND|OR|NOT)\b'          # bare FTS5 boolean operators
    r'|\*',                       # trailing star (prefix query)
    re.ASCII,
)


def escape_fts_query(query: str) -> str:
    """Convert a raw search string into a safe FTS5 MATCH expression.

    Strategy: if the query contains any FTS5 meta-syntax (boolean operators,
    unbalanced quotes, bare ``*``), wrap the whole thing in double-quotes so
    SQLite treats it as a phrase query.  Plain alphanumeric queries are left
    unchanged.  Properly quoted phrase queries (even double-quote count) are
    also left unchanged, as SQLite FTS5 handles them natively.

    Args:
        query: Raw user input (may be empty or contain FTS5 syntax).

    Returns:
        A string safe to pass as the right-hand side of a MATCH clause.
        Never raises.
    """
    if not query or not query.strip():
        return '""'

    stripped = query.strip()

    # Check for unbalanced quotes (odd count means unclosed phrase)
    quote_count = stripped.count('"')
    if quote_count % 2 != 0:
        # Unbalanced — wrap entire thing as phrase, escaping inner quotes
        escaped = stripped.replace('"', '""')
        return f'"{escaped}"'

    # Check for bare FTS5 operators or wildcards
    if _BARE_OPERATOR.search(stripped):
        escaped = stripped.replace('"', '""')
        return f'"{escaped}"'

    # Balanced quotes (0 or even count) or plain text — safe to pass through
    return stripped


def fts_match(
    conn: sqlite3.Connection,
    fts_table: str,
    query: str,
    *,
    select: str,
    join: Optional[str] = None,
    limit: Optional[int] = None,
    snippet_col: Optional[int] = None,
    snippet_markers: tuple[str, str] = ("[", "]"),
    snippet_ellipsis: str = "...",
    snippet_tokens: int = 20,
) -> list[tuple[Any, ...]]:
    """Execute a MATCH query with BM25 ORDER BY rank.

    Args:
        conn:             Open SQLite connection.
        fts_table:        FTS5 virtual table name.
        query:            Raw user query (will be escaped via escape_fts_query).
        select:           SELECT clause, e.g. ``'wp.*, snippet(...) as snippet'``.
                          Must not include the FROM keyword.
        join:             Optional JOIN clause appended after the FTS table
                          reference.  E.g. ``'JOIN work_products wp ON wp.id =
                          work_products_fts.rowid'``.
        limit:            Optional LIMIT n.
        snippet_col:      If set, appends a ``snippet()`` column for the given
                          zero-based FTS column index.  The alias is ``snippet``.
        snippet_markers:  ``(open, close)`` markers for snippet highlighting.
        snippet_ellipsis: Ellipsis string between non-contiguous fragments.
        snippet_tokens:   Approximate number of tokens per snippet fragment.

    Returns:
        List of raw tuples as returned by sqlite3 (row_factory not assumed).

    Raises:
        sqlite3.Error: if the escaped query is still somehow malformed
                       (propagated to caller for handling).
    """
    safe_query = escape_fts_query(query)

    # Build snippet() expression if requested
    if snippet_col is not None:
        open_m, close_m = snippet_markers
        snip_expr = (
            f"snippet({fts_table}, {snippet_col}, "
            f"'{open_m}', '{close_m}', '{snippet_ellipsis}', {snippet_tokens})"
            f" as snippet"
        )
        full_select = f"{select}, {snip_expr}"
    else:
        full_select = select

    sql = f"SELECT {full_select} FROM {fts_table}"
    if join:
        sql += f" {join}"
    sql += f" WHERE {fts_table} MATCH ?"
    sql += " ORDER BY rank"
    if limit is not None:
        sql += f" LIMIT {limit}"

    return conn.execute(sql, (safe_query,)).fetchall()
