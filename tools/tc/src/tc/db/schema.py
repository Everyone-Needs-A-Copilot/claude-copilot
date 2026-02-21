"""Full SQL schema for Task Copilot database."""

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

CREATE VIRTUAL TABLE IF NOT EXISTS work_products_fts USING fts5(
    title, content, type, agent,
    content='work_products', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS wp_fts_insert AFTER INSERT ON work_products BEGIN
    INSERT INTO work_products_fts(rowid, title, content, type, agent)
    VALUES (new.id, new.title, new.content, new.type, new.agent);
END;

CREATE TRIGGER IF NOT EXISTS wp_fts_delete AFTER DELETE ON work_products BEGIN
    INSERT INTO work_products_fts(work_products_fts, rowid, title, content, type, agent)
    VALUES ('delete', old.id, old.title, old.content, old.type, old.agent);
END;

CREATE TRIGGER IF NOT EXISTS wp_fts_update AFTER UPDATE ON work_products BEGIN
    INSERT INTO work_products_fts(work_products_fts, rowid, title, content, type, agent)
    VALUES ('delete', old.id, old.title, old.content, old.type, old.agent);
    INSERT INTO work_products_fts(rowid, title, content, type, agent)
    VALUES (new.id, new.title, new.content, new.type, new.agent);
END;

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
