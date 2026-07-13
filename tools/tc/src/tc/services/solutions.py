"""tc.services.solutions — domain logic for the Outcome Ledger (W-1, Phase 4
outcome program).

A Solution is the CSE's unit of value: a completed artifact that resolves a
real person's real problem. This module implements its lifecycle:

    create -> lock-brief -> mark-working -> mark-loveable -> log-usage -> close

feeding the ratified outcome bars:
  - O-1 (TTFLS): t_working, t_loveable timestamps.
  - O-2 (Completeness): brief locked at start (immutable -- later edit
    attempts are recorded to solution_scope_log, never silently rewritten),
    sessions/tokens to done, post-ship fix-vs-feature ratio.
  - O-3 (Speed, observed only): started_at/t_working/t_loveable/closed_at are
    the raw timestamps the cse-bench solutions collector derives observed
    elapsed-time metrics from. No counterfactual (bare-harness) comparison
    happens here -- that's the ladder harness, W-3.
  - O-5 (Survival): started -> shipped -> in_use, tracked via status plus the
    append-only solution_usage_log.

W-2 (Phase 4 outcome program, token & session joins): every public function
below that touches a specific solution_id also calls
_record_session_touch(), which appends a row to the additive
solution_sessions table (repo_path + session_id + logged_at) whenever
CLAUDE_CODE_SESSION_ID is set in the environment -- i.e. this call is
running inside a live Claude Code session. That is "tc solution records the
session id when invoked inside one" (phase-4-outcome-program-prd.md par.3
W-2): the repo+time+session-id join keys the cse-bench economy collector
uses to independently cross-check solutions.tokens_total (the self-reported
ledger figure) against each joined session's own transcript token usage. A
no-op outside a live session (scripts, tests, CI) -- absence is the honest
no-signal state, not an error.

Every dict this module returns carries the storage-layer flat fields
(``brief``, ``brief_locked_at``, ``post_ship_fixes``, ``post_ship_features``,
``post_ship_window_days``) AND the PRD's literal entity shape as additive,
derived keys: ``brief_lock: {text, locked_at}`` and
``post_ship: {fixes, features, window_days}`` (see phase-4-outcome-program-prd.md
§3 W-1). ``components_used`` is decoded from its JSON-text storage form to an
actual list before being returned.

All functions accept an optional ``conn`` parameter (batching pattern shared
with tc.services.tasks/streams) and call ensure_solutions_schema() on every
connection they touch -- see db/connection.py's docstring for why: it is
the lazy-migration path so pre-existing tasks.db stores never need a manual
migration step.

This module has ZERO import-time side effects -- no DB opened, no env read.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional, Union

from tc.db.exceptions import ConflictError, SolutionNotFound, ValidationError

# W-2: the env var Claude Code exports to every tool invocation inside a
# live session (confirmed present via `env` inside an active Claude Code
# session; not documented elsewhere in this repo as of this writing).
_SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"

_VALID_COMPONENTS = {"framework", "knowledge", "integration"}
_VALID_LOG_KINDS = {"usage", "fix", "feature"}
_CLOSEABLE_STATUSES = {"shipped", "abandoned", "retired"}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Shape a `solutions` row into the PRD's literal entity shape.

    Storage stays flat (SQLite columns); the returned dict adds the PRD's
    nested `brief_lock`/`post_ship` views ADDITIVELY, alongside (never
    replacing) the flat fields already relied on elsewhere in this module
    and by existing callers. `components_used` is decoded from its
    JSON-text storage form to an actual list.
    """
    d = dict(row)

    if "components_used" in d and d["components_used"] is not None:
        d["components_used"] = json.loads(d["components_used"])

    if "brief" in d or "brief_locked_at" in d:
        d["brief_lock"] = {"text": d.get("brief"), "locked_at": d.get("brief_locked_at")}

    if "post_ship_fixes" in d or "post_ship_features" in d or "post_ship_window_days" in d:
        d["post_ship"] = {
            "fixes": d.get("post_ship_fixes"),
            "features": d.get("post_ship_features"),
            "window_days": d.get("post_ship_window_days"),
        }

    return d


def _open_conn(db_path: Path) -> sqlite3.Connection:
    from tc.db.connection import get_db

    return get_db(db_path)


def _require_db_path(db_path: Optional[Path]) -> Path:
    if db_path is not None:
        return db_path
    from tc.db.connection import find_db_path

    found = find_db_path()
    if found is None:
        raise FileNotFoundError(
            "No tasks.db found. Run `tc init` to create a database."
        )
    return found


def _resolve_conn(
    conn: Optional[sqlite3.Connection], db_path: Optional[Path]
) -> tuple[sqlite3.Connection, bool]:
    """Resolve a usable connection and whether this call owns it (and
    therefore must commit/close). Ensures the Outcome Ledger tables exist on
    whatever connection is returned -- see module docstring.
    """
    from tc.db.connection import ensure_solutions_schema

    owns_conn = conn is None
    if owns_conn:
        resolved = _require_db_path(db_path)
        conn = _open_conn(resolved)

    ensure_solutions_schema(conn)
    return conn, owns_conn


def _parse_components(components: Optional[Union[str, list]]) -> Optional[str]:
    """Normalise --components input to a JSON array string, or None.

    Accepts a comma-separated string ("framework,knowledge") or a list.
    """
    if components is None:
        return None
    if isinstance(components, str):
        items = [c.strip() for c in components.split(",") if c.strip()]
    else:
        items = list(components)

    invalid = sorted(set(items) - _VALID_COMPONENTS)
    if invalid:
        raise ValidationError(
            f"invalid components_used {invalid}. Must be from: "
            f"{', '.join(sorted(_VALID_COMPONENTS))}"
        )
    return json.dumps(items)


def _get_solution_row(conn: sqlite3.Connection, solution_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM solutions WHERE id = ?", (solution_id,)).fetchone()
    if row is None:
        raise SolutionNotFound(f"solution #{solution_id} not found")
    return row


def _record_session_touch(conn: sqlite3.Connection, solution_id: int) -> None:
    """Append a solution_sessions row (W-2) when this call is running
    inside a live Claude Code session (CLAUDE_CODE_SESSION_ID set) -- see
    module docstring. A no-op otherwise; absence of a session id is the
    honest no-signal state, not an error.
    """
    session_id = os.environ.get(_SESSION_ID_ENV)
    if not session_id:
        return
    conn.execute(
        "INSERT INTO solution_sessions (solution_id, session_id, repo_path) VALUES (?, ?, ?)",
        (solution_id, session_id, os.getcwd()),
    )


def create_solution(
    *,
    title: str,
    brief: Optional[str] = None,
    beneficiary: Optional[str] = None,
    repo_path: Optional[str] = None,
    components_used: Optional[Union[str, list]] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Create a new solution and return the inserted row as a dict.

    Args:
        title:           Solution title (required, non-empty).
        brief:           Draft brief text. Not locked yet -- call
                         lock_brief() to freeze it (O-2's intent contract).
        beneficiary:     Who the solution is for.
        repo_path:       Repo/path the solution lives in.
        components_used: Comma-separated string or list, subset of
                         {framework, knowledge, integration}.
        conn:            Existing connection for batching; if None, opens own.
        db_path:         Explicit DB path; if None, walks up from cwd.

    Returns:
        Dict matching ``tc solution create --json`` output shape.

    Raises:
        ValidationError: on empty title or an unrecognised component name.
    """
    if not title or not title.strip():
        raise ValidationError("title must not be empty")

    components_str = _parse_components(components_used)

    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        cursor = conn.execute(
            """INSERT INTO solutions (title, brief, beneficiary, repo_path, components_used)
               VALUES (?, ?, ?, ?, ?)""",
            (title, brief, beneficiary, repo_path, components_str),
        )
        solution_id = cursor.lastrowid
        _record_session_touch(conn, solution_id)
        row = _get_solution_row(conn, solution_id)

        if owns_conn:
            conn.commit()

        return _row_to_dict(row)
    finally:
        if owns_conn:
            conn.close()


def lock_brief(
    *,
    solution_id: int,
    brief: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Lock the brief (the intent contract O-2 measures completeness
    against). Idempotent by design, never destructive:

      - First call: freezes `brief` (using the provided text if given, else
        whatever was set at create time) and stamps brief_locked_at.
      - Any later call: the brief is immutable -- the attempted new text is
        appended to solution_scope_log instead of overwriting brief_lock,
        and the returned dict carries scope_change_recorded=True so the
        caller knows nothing was rewritten.

    Raises:
        SolutionNotFound: if solution_id does not exist.
        ValidationError:  if no brief text exists yet at first lock (neither
                          create's --brief nor this call's --brief was set).
    """
    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        row = _get_solution_row(conn, solution_id)

        if row["brief_locked_at"] is not None:
            # Already locked: record the scope change, never rewrite history.
            note = brief if brief else "(lock-brief called again after lock; no new text given)"
            conn.execute(
                "INSERT INTO solution_scope_log (solution_id, note) VALUES (?, ?)",
                (solution_id, note),
            )
            _record_session_touch(conn, solution_id)
            if owns_conn:
                conn.commit()
            result = _row_to_dict(_get_solution_row(conn, solution_id))
            result["scope_change_recorded"] = True
            return result

        final_brief = brief if brief is not None else row["brief"]
        if not final_brief or not final_brief.strip():
            raise ValidationError(
                "no brief text to lock -- pass --brief here or at `solution create`"
            )

        conn.execute(
            """UPDATE solutions
               SET brief = ?, brief_locked_at = datetime('now'), updated_at = datetime('now')
               WHERE id = ?""",
            (final_brief, solution_id),
        )
        _record_session_touch(conn, solution_id)
        if owns_conn:
            conn.commit()

        result = _row_to_dict(_get_solution_row(conn, solution_id))
        result["scope_change_recorded"] = False
        return result
    finally:
        if owns_conn:
            conn.close()


def mark_working(
    *,
    solution_id: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Stamp t_working (O-1's first timestamp: "does the job").

    Raises:
        SolutionNotFound: if solution_id does not exist.
        ConflictError:    if t_working is already set (a fact, recorded once).
    """
    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        row = _get_solution_row(conn, solution_id)
        if row["t_working"] is not None:
            raise ConflictError(
                f"solution #{solution_id} already marked working at {row['t_working']}"
            )

        conn.execute(
            "UPDATE solutions SET t_working = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (solution_id,),
        )
        _record_session_touch(conn, solution_id)
        if owns_conn:
            conn.commit()

        return _row_to_dict(_get_solution_row(conn, solution_id))
    finally:
        if owns_conn:
            conn.close()


def mark_loveable(
    *,
    solution_id: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Stamp t_loveable (O-1's second timestamp: meets expectations -- MLP
    not MVP). The t_loveable - t_working gap isolates the design chain's
    measurable value.

    Raises:
        SolutionNotFound: if solution_id does not exist.
        ValidationError:  if t_working has not been marked yet.
        ConflictError:    if t_loveable is already set.
    """
    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        row = _get_solution_row(conn, solution_id)
        if row["t_working"] is None:
            raise ValidationError(
                f"solution #{solution_id} must be marked working before loveable "
                "(O-1 measures the loveable gap relative to working)"
            )
        if row["t_loveable"] is not None:
            raise ConflictError(
                f"solution #{solution_id} already marked loveable at {row['t_loveable']}"
            )

        conn.execute(
            "UPDATE solutions SET t_loveable = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (solution_id,),
        )
        _record_session_touch(conn, solution_id)
        if owns_conn:
            conn.commit()

        return _row_to_dict(_get_solution_row(conn, solution_id))
    finally:
        if owns_conn:
            conn.close()


def log_usage(
    *,
    solution_id: int,
    kind: str = "usage",
    sessions: int = 0,
    tokens: int = 0,
    note: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Append a usage/fix/feature event against a shipped solution.

    kind='usage' is sustained-use evidence (O-5): the first usage entry
    logged after shipping flips status shipped -> in_use. kind='fix' and
    kind='feature' accumulate O-2's post-ship fix-vs-feature ratio.
    sessions/tokens deltas roll into solutions.sessions_count/tokens_total.

    Raises:
        SolutionNotFound: if solution_id does not exist.
        ValidationError:  on an unrecognised kind.
        ConflictError:    if the solution hasn't shipped yet (in_progress,
                          abandoned, or retired cannot accrue usage).
    """
    if kind not in _VALID_LOG_KINDS:
        raise ValidationError(
            f"invalid kind '{kind}'. Must be one of: {', '.join(sorted(_VALID_LOG_KINDS))}"
        )

    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        row = _get_solution_row(conn, solution_id)
        if row["status"] not in ("shipped", "in_use"):
            raise ConflictError(
                f"solution #{solution_id} has status '{row['status']}' -- "
                "usage can only be logged against a shipped or in_use solution"
            )

        conn.execute(
            """INSERT INTO solution_usage_log (solution_id, kind, sessions_delta, tokens_delta, note)
               VALUES (?, ?, ?, ?, ?)""",
            (solution_id, kind, sessions, tokens, note),
        )

        updates = ["sessions_count = sessions_count + ?", "tokens_total = tokens_total + ?"]
        params: list = [sessions, tokens]
        if kind == "fix":
            updates.append("post_ship_fixes = post_ship_fixes + 1")
        elif kind == "feature":
            updates.append("post_ship_features = post_ship_features + 1")
        elif kind == "usage" and row["status"] == "shipped":
            updates.append("status = 'in_use'")

        updates.append("updated_at = datetime('now')")
        conn.execute(
            f"UPDATE solutions SET {', '.join(updates)} WHERE id = ?",
            (*params, solution_id),
        )
        _record_session_touch(conn, solution_id)

        if owns_conn:
            conn.commit()

        return _row_to_dict(_get_solution_row(conn, solution_id))
    finally:
        if owns_conn:
            conn.close()


def close_solution(
    *,
    solution_id: int,
    status: str,
    notes: Optional[str] = None,
    post_ship_window_days: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Close a solution with a terminal (or transitional-terminal) outcome.

    Valid targets and their allowed source statuses:
      - 'shipped':   from 'in_progress' only; requires the brief to be
                     locked first (O-2 measures completeness against it).
      - 'abandoned': from 'in_progress' only.
      - 'retired':   from 'shipped' or 'in_use' only (decommissioning a
                     solution that was already delivered).

    Raises:
        SolutionNotFound: if solution_id does not exist.
        ValidationError:  on an unrecognised target status, or shipping
                          without a locked brief.
        ConflictError:    on a disallowed status transition.
    """
    if status not in _CLOSEABLE_STATUSES:
        raise ValidationError(
            f"invalid close status '{status}'. Must be one of: "
            f"{', '.join(sorted(_CLOSEABLE_STATUSES))}"
        )

    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        row = _get_solution_row(conn, solution_id)
        current = row["status"]

        if status in ("shipped", "abandoned") and current != "in_progress":
            raise ConflictError(
                f"solution #{solution_id} cannot close as '{status}' from status "
                f"'{current}' (only from 'in_progress')"
            )
        if status == "retired" and current not in ("shipped", "in_use"):
            raise ConflictError(
                f"solution #{solution_id} cannot retire from status '{current}' "
                "(only from 'shipped' or 'in_use')"
            )
        if status == "shipped" and row["brief_locked_at"] is None:
            raise ValidationError(
                f"solution #{solution_id} cannot ship without a locked brief "
                "(O-2 measures completeness against the brief locked at start; "
                "run `tc solution lock-brief` first)"
            )

        updates = ["status = ?", "closed_at = datetime('now')", "updated_at = datetime('now')"]
        params: list = [status]
        if notes is not None:
            updates.append("outcome_notes = ?")
            params.append(notes)
        if post_ship_window_days is not None:
            updates.append("post_ship_window_days = ?")
            params.append(post_ship_window_days)

        params.append(solution_id)
        conn.execute(f"UPDATE solutions SET {', '.join(updates)} WHERE id = ?", params)
        _record_session_touch(conn, solution_id)

        if owns_conn:
            conn.commit()

        return _row_to_dict(_get_solution_row(conn, solution_id))
    finally:
        if owns_conn:
            conn.close()


def get_solution(
    *,
    solution_id: int,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a solution dict with its scope_log, usage_log, and (W-2)
    sessions entries.

    Raises:
        SolutionNotFound: if solution_id does not exist.
    """
    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        row = _get_solution_row(conn, solution_id)
        d = _row_to_dict(row)

        scope_rows = conn.execute(
            "SELECT * FROM solution_scope_log WHERE solution_id = ? ORDER BY id",
            (solution_id,),
        ).fetchall()
        usage_rows = conn.execute(
            "SELECT * FROM solution_usage_log WHERE solution_id = ? ORDER BY id",
            (solution_id,),
        ).fetchall()
        session_rows = conn.execute(
            "SELECT * FROM solution_sessions WHERE solution_id = ? ORDER BY id",
            (solution_id,),
        ).fetchall()

        d["scope_log"] = [_row_to_dict(r) for r in scope_rows]
        d["usage_log"] = [_row_to_dict(r) for r in usage_rows]
        d["sessions"] = [_row_to_dict(r) for r in session_rows]
        return d
    finally:
        if owns_conn:
            conn.close()


def list_solutions(
    *,
    status: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return a list of solution dicts, optionally filtered by status.

    Raises:
        ValidationError: if status is not a recognised status string.
    """
    valid_statuses = {"in_progress", "shipped", "abandoned", "in_use", "retired"}
    if status is not None and status not in valid_statuses:
        raise ValidationError(
            f"invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}"
        )

    conn, owns_conn = _resolve_conn(conn, db_path)
    try:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM solutions WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM solutions ORDER BY id DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        if owns_conn:
            conn.close()
