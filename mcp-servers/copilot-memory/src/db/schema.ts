/**
 * SQLite schema definitions for the Copilot Memory server
 * Uses sqlite-vec for vector similarity search
 */

export const SCHEMA_SQL = `
-- Core memory table
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  content TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('decision', 'lesson', 'discussion', 'file', 'initiative', 'context', 'agent_improvement')),
  tags TEXT DEFAULT '[]',
  metadata TEXT DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  session_id TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(project_id, type);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(project_id, created_at DESC);

-- Current initiative state (one per project)
CREATE TABLE IF NOT EXISTS initiatives (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  goal TEXT,
  status TEXT DEFAULT 'IN PROGRESS' CHECK(status IN ('NOT STARTED', 'IN PROGRESS', 'BLOCKED', 'READY FOR REVIEW', 'COMPLETE')),

  -- NEW: Task Copilot integration
  task_copilot_linked INTEGER DEFAULT 0,
  active_prd_ids TEXT DEFAULT '[]',

  -- KEEP: Permanent knowledge
  decisions TEXT DEFAULT '[]',
  lessons TEXT DEFAULT '[]',
  key_files TEXT DEFAULT '[]',

  -- NEW: Slim resume context
  current_focus TEXT,
  next_action TEXT,

  -- DEPRECATED: Use Task Copilot instead
  completed TEXT DEFAULT '[]',
  in_progress TEXT DEFAULT '[]',
  blocked TEXT DEFAULT '[]',
  resume_instructions TEXT,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Session tracking
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id, started_at DESC);

-- Archived initiatives
CREATE TABLE IF NOT EXISTS initiatives_archive (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  goal TEXT,
  status TEXT,

  -- NEW: Task Copilot integration
  task_copilot_linked INTEGER DEFAULT 0,
  active_prd_ids TEXT DEFAULT '[]',

  -- KEEP: Permanent knowledge
  decisions TEXT,
  lessons TEXT,
  key_files TEXT,

  -- NEW: Slim resume context
  current_focus TEXT,
  next_action TEXT,

  -- DEPRECATED
  completed TEXT,
  in_progress TEXT,
  blocked TEXT,
  resume_instructions TEXT,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT NOT NULL
);

-- Corrections table for two-stage correction workflow
CREATE TABLE IF NOT EXISTS corrections (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT,
  task_id TEXT,
  agent_id TEXT,
  original_content TEXT NOT NULL,
  corrected_content TEXT NOT NULL,
  raw_user_message TEXT NOT NULL,
  matched_patterns TEXT DEFAULT '[]',
  extracted_what TEXT,
  extracted_why TEXT,
  extracted_how TEXT,
  target TEXT NOT NULL CHECK(target IN ('skill', 'agent', 'memory', 'preference')),
  target_id TEXT,
  target_section TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'applied', 'expired')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  reviewed_at TEXT,
  applied_at TEXT,
  expires_at TEXT,
  review_metadata TEXT DEFAULT '{}'
);

-- Indexes for corrections
CREATE INDEX IF NOT EXISTS idx_corrections_project ON corrections(project_id);
CREATE INDEX IF NOT EXISTS idx_corrections_status ON corrections(project_id, status);
CREATE INDEX IF NOT EXISTS idx_corrections_agent ON corrections(project_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_corrections_target ON corrections(project_id, target);
CREATE INDEX IF NOT EXISTS idx_corrections_expires ON corrections(expires_at);

-- Full-text search on memory content
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
  content,
  tags,
  content=memories,
  content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, content, tags) VALUES (new.rowid, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES('delete', old.rowid, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES('delete', old.rowid, old.content, old.tags);
  INSERT INTO memories_fts(rowid, content, tags) VALUES (new.rowid, new.content, new.tags);
END;
`;

// Vector table creation (separate because sqlite-vec uses different syntax)
export const VECTOR_SCHEMA_SQL = `
-- Vector embeddings for semantic search
-- sqlite-vec virtual table with 384-dimension vectors (all-MiniLM-L6-v2)
CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vec0(
  memory_id TEXT PRIMARY KEY,
  embedding FLOAT[384]
);
`;

// Migration version tracking
export const MIGRATION_TABLE_SQL = `
CREATE TABLE IF NOT EXISTS migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
`;

export const CURRENT_VERSION = 3;

// Migration for version 2: Add slim initiative fields
export const MIGRATION_V2_SQL = `
-- Add new Task Copilot integration fields
ALTER TABLE initiatives ADD COLUMN task_copilot_linked INTEGER DEFAULT 0;
ALTER TABLE initiatives ADD COLUMN active_prd_ids TEXT DEFAULT '[]';

-- Add new slim resume context fields
ALTER TABLE initiatives ADD COLUMN current_focus TEXT;
ALTER TABLE initiatives ADD COLUMN next_action TEXT;

-- Add same fields to archive table
ALTER TABLE initiatives_archive ADD COLUMN task_copilot_linked INTEGER DEFAULT 0;
ALTER TABLE initiatives_archive ADD COLUMN active_prd_ids TEXT DEFAULT '[]';
ALTER TABLE initiatives_archive ADD COLUMN current_focus TEXT;
ALTER TABLE initiatives_archive ADD COLUMN next_action TEXT;
`;

// Migration for version 3: Add corrections table
export const MIGRATION_V3_SQL = `
-- Corrections table for two-stage correction workflow
CREATE TABLE IF NOT EXISTS corrections (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT,
  task_id TEXT,
  agent_id TEXT,
  original_content TEXT NOT NULL,
  corrected_content TEXT NOT NULL,
  raw_user_message TEXT NOT NULL,
  matched_patterns TEXT DEFAULT '[]',
  extracted_what TEXT,
  extracted_why TEXT,
  extracted_how TEXT,
  target TEXT NOT NULL CHECK(target IN ('skill', 'agent', 'memory', 'preference')),
  target_id TEXT,
  target_section TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'applied', 'expired')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  reviewed_at TEXT,
  applied_at TEXT,
  expires_at TEXT,
  review_metadata TEXT DEFAULT '{}'
);

-- Indexes for corrections
CREATE INDEX IF NOT EXISTS idx_corrections_project ON corrections(project_id);
CREATE INDEX IF NOT EXISTS idx_corrections_status ON corrections(project_id, status);
CREATE INDEX IF NOT EXISTS idx_corrections_agent ON corrections(project_id, agent_id);
CREATE INDEX IF NOT EXISTS idx_corrections_target ON corrections(project_id, target);
CREATE INDEX IF NOT EXISTS idx_corrections_expires ON corrections(expires_at);
`;
