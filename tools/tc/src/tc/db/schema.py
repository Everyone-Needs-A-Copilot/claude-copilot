"""Full SQL schema for Task Copilot database.

FTS5 virtual table and triggers are created via fts5_core builders (called from
connection.init_db) rather than inline DDL strings.  Constants below expose
the FTS5 table / column configuration so callers can reference them without
hard-coding names.
"""

# FTS5 configuration constants — referenced by connection.init_db and wp.py
WP_FTS_TABLE = "work_products_fts"
WP_FTS_COLUMNS = ["title", "content", "type", "agent"]
WP_BASE_TABLE = "work_products"
WP_BASE_ROWID = "id"

# Base schema: all tables, indexes, and version row — FTS5 DDL excluded here
# so that fts5_core builders in init_db are the single source of truth for the
# FTS5 virtual table and trigger definitions.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    content TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'archived')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    prd_id INTEGER REFERENCES prds(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'paused', 'completed', 'archived')),
    worktree_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prd_id INTEGER REFERENCES prds(id),
    stream_id INTEGER REFERENCES streams(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'blocked', 'cancelled')),
    agent TEXT,
    claimed_by TEXT,
    claimed_at TEXT,
    priority INTEGER NOT NULL DEFAULT 2 CHECK(priority BETWEEN 0 AND 3),
    parent_task_id INTEGER REFERENCES tasks(id),
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    depends_on INTEGER NOT NULL REFERENCES tasks(id),
    PRIMARY KEY (task_id, depends_on),
    CHECK(task_id != depends_on)
);

CREATE TABLE IF NOT EXISTS work_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    file_path TEXT,
    agent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    stream_id INTEGER REFERENCES streams(id),
    task_id INTEGER REFERENCES tasks(id),
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent);
CREATE INDEX IF NOT EXISTS idx_tasks_stream ON tasks(stream_id);
CREATE INDEX IF NOT EXISTS idx_tasks_prd ON tasks(prd_id);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_wp_task ON work_products(task_id);
CREATE INDEX IF NOT EXISTS idx_wp_type ON work_products(type);
CREATE INDEX IF NOT EXISTS idx_log_agent ON agent_log(agent);
CREATE INDEX IF NOT EXISTS idx_log_stream ON agent_log(stream_id);
CREATE INDEX IF NOT EXISTS idx_log_task ON agent_log(task_id);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
"""

# Outcome Ledger (W-1, Phase 4 outcome program): the Solution entity + its two
# append-only logs. Kept as a separate script (rather than folded into
# SCHEMA_SQL) so it can be re-run standalone via ensure_solutions_schema() --
# the lazy bootstrap `tc.services.solutions` calls on every connection it
# opens, so sibling repos' pre-existing tasks.db stores (created before this
# addition) gain these tables the first time any `tc solution` command
# touches them, with zero required migration step from the user. `tc init`
# also executes it directly for brand-new stores (see connection.init_db) --
# both paths converge on this single string, so there is one source of truth
# for the DDL. Every statement is IF NOT EXISTS: additive-only, never touches
# `tasks`/`prds`/`streams`/etc.
SOLUTIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS solutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    beneficiary TEXT,
    repo_path TEXT,
    components_used TEXT,
    brief TEXT,
    brief_locked_at TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK(status IN ('in_progress', 'shipped', 'abandoned', 'in_use', 'retired')),
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    t_working TEXT,
    t_loveable TEXT,
    sessions_count INTEGER NOT NULL DEFAULT 0,
    tokens_total INTEGER NOT NULL DEFAULT 0,
    post_ship_fixes INTEGER NOT NULL DEFAULT 0,
    post_ship_features INTEGER NOT NULL DEFAULT 0,
    post_ship_window_days INTEGER,
    closed_at TEXT,
    outcome_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only: a scope-change/edit attempt made AFTER brief_locked_at. The
-- locked brief text itself is never rewritten (O-2 measures completeness
-- against the brief as locked at the start); attempted changes are recorded
-- here instead, so drift is visible rather than silently absorbed.
CREATE TABLE IF NOT EXISTS solution_scope_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solution_id INTEGER NOT NULL REFERENCES solutions(id),
    logged_at TEXT NOT NULL DEFAULT (datetime('now')),
    note TEXT NOT NULL
);

-- Append-only: usage/fix/feature events logged after a solution ships.
-- kind='usage' is sustained-use evidence (first one flips shipped -> in_use,
-- O-5); kind='fix'/'feature' accumulate the O-2 post-ship fix-vs-feature
-- ratio. sessions_delta/tokens_delta roll up into solutions.sessions_count /
-- solutions.tokens_total.
CREATE TABLE IF NOT EXISTS solution_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solution_id INTEGER NOT NULL REFERENCES solutions(id),
    kind TEXT NOT NULL DEFAULT 'usage' CHECK(kind IN ('usage', 'fix', 'feature')),
    logged_at TEXT NOT NULL DEFAULT (datetime('now')),
    sessions_delta INTEGER NOT NULL DEFAULT 0,
    tokens_delta INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

-- Append-only (W-2, Phase 4 outcome program, token & session joins): one row
-- per `tc solution` mutating command invoked while a CLAUDE_CODE_SESSION_ID
-- is present in the environment (i.e. running inside a live Claude Code
-- session) -- see tc.services.solutions._record_session_touch. Carries the
-- repo+time+session-id join keys phase-4-outcome-program-prd.md par.3 W-2
-- names: cse-bench's economy collector uses DISTINCT session_id per
-- solution to independently sum that session's own transcript token usage
-- and cross-check it against solutions.tokens_total (the self-reported
-- ledger figure). Multiple rows per (solution_id, session_id) are expected
-- and harmless -- callers dedupe by session_id when computing totals.
CREATE TABLE IF NOT EXISTS solution_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solution_id INTEGER NOT NULL REFERENCES solutions(id),
    session_id TEXT NOT NULL,
    repo_path TEXT,
    logged_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_solutions_status ON solutions(status);
CREATE INDEX IF NOT EXISTS idx_solution_scope_log_solution ON solution_scope_log(solution_id);
CREATE INDEX IF NOT EXISTS idx_solution_usage_log_solution ON solution_usage_log(solution_id);
CREATE INDEX IF NOT EXISTS idx_solution_sessions_solution ON solution_sessions(solution_id);
CREATE INDEX IF NOT EXISTS idx_solution_sessions_session_id ON solution_sessions(session_id);
"""
