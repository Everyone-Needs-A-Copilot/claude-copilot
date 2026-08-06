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
