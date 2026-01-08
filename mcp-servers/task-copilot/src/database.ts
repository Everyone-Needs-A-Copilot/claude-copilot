/**
 * SQLite database client for Task Copilot
 */

import Database from 'better-sqlite3';
import { createHash } from 'crypto';
import { existsSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { homedir } from 'os';

import type {
  InitiativeRow,
  PrdRow,
  TaskRow,
  WorkProductRow,
  ActivityLogRow,
  TaskStatus,
  PrdStatus,
  PerformanceRow,
  CheckpointRow,
} from './types.js';

// Schema definition
const SCHEMA_SQL = `
-- initiatives table (lightweight link to Memory Copilot)
CREATE TABLE IF NOT EXISTS initiatives (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- prds table
CREATE TABLE IF NOT EXISTS prds (
  id TEXT PRIMARY KEY,
  initiative_id TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  content TEXT NOT NULL,
  metadata TEXT DEFAULT '{}',
  status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived', 'cancelled')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (initiative_id) REFERENCES initiatives(id)
);

-- tasks table
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  prd_id TEXT,
  parent_id TEXT,
  title TEXT NOT NULL,
  description TEXT,
  assigned_agent TEXT,
  status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'blocked', 'completed', 'cancelled')),
  blocked_reason TEXT,
  notes TEXT,
  metadata TEXT DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (prd_id) REFERENCES prds(id),
  FOREIGN KEY (parent_id) REFERENCES tasks(id)
);

-- work_products table
CREATE TABLE IF NOT EXISTS work_products (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('technical_design', 'implementation', 'test_plan', 'security_review', 'documentation', 'architecture', 'other')),
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

-- activity_log table
CREATE TABLE IF NOT EXISTS activity_log (
  id TEXT PRIMARY KEY,
  initiative_id TEXT NOT NULL,
  type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  entity_type TEXT,
  summary TEXT NOT NULL,
  metadata TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (initiative_id) REFERENCES initiatives(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prds_initiative ON prds(initiative_id);
CREATE INDEX IF NOT EXISTS idx_tasks_prd ON tasks(prd_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(assigned_agent);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_work_products_task ON work_products(task_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_initiative ON activity_log(initiative_id);
`;

// Migration SQL for version 2: Agent Performance Tracking
const MIGRATION_V2_SQL = `
-- agent_performance table
CREATE TABLE IF NOT EXISTS agent_performance (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  work_product_type TEXT,
  complexity TEXT,
  outcome TEXT NOT NULL CHECK(outcome IN ('success', 'failure', 'blocked', 'reassigned')),
  duration_ms INTEGER,
  created_at TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_agent_perf_agent ON agent_performance(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_perf_outcome ON agent_performance(agent_id, outcome);
CREATE INDEX IF NOT EXISTS idx_agent_perf_type ON agent_performance(agent_id, work_product_type);
CREATE INDEX IF NOT EXISTS idx_agent_perf_created ON agent_performance(created_at DESC);
`;

// Migration SQL for version 3: Checkpoint System
const MIGRATION_V3_SQL = `
-- checkpoints table
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  trigger TEXT NOT NULL CHECK(trigger IN ('auto_status', 'auto_subtask', 'manual', 'error')),
  task_status TEXT NOT NULL,
  task_notes TEXT,
  task_metadata TEXT,
  blocked_reason TEXT,
  assigned_agent TEXT,
  execution_phase TEXT,
  execution_step INTEGER,
  agent_context TEXT,
  draft_content TEXT,
  draft_type TEXT,
  subtask_states TEXT DEFAULT '[]',
  created_at TEXT NOT NULL,
  expires_at TEXT,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_task ON checkpoints(task_id, sequence DESC);
CREATE INDEX IF NOT EXISTS idx_checkpoints_expires ON checkpoints(expires_at);
`;

// Migration SQL for version 4: Ralph Wiggum Iteration Support
const MIGRATION_V4_SQL = `
-- Add iteration support columns to checkpoints table
ALTER TABLE checkpoints ADD COLUMN iteration_config TEXT DEFAULT NULL;
ALTER TABLE checkpoints ADD COLUMN iteration_number INTEGER DEFAULT 0;
ALTER TABLE checkpoints ADD COLUMN iteration_history TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN completion_promises TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN validation_state TEXT DEFAULT NULL;

-- Index for efficient iteration queries
CREATE INDEX IF NOT EXISTS idx_checkpoints_iteration ON checkpoints(task_id, iteration_number DESC);
`;

// Migration SQL for version 5: Hierarchical Agent Handoffs
const MIGRATION_V5_SQL = `
-- agent_handoffs table
CREATE TABLE IF NOT EXISTS agent_handoffs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  work_product_id TEXT NOT NULL,
  handoff_context TEXT NOT NULL,
  chain_position INTEGER NOT NULL,
  chain_length INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_handoffs_task ON agent_handoffs(task_id, chain_position ASC);
CREATE INDEX IF NOT EXISTS idx_handoffs_agents ON agent_handoffs(from_agent, to_agent);
`;

// Migration SQL for version 6: Stream Archival
const MIGRATION_V6_SQL = `
-- Add archival support to tasks
ALTER TABLE tasks ADD COLUMN archived INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN archived_at TEXT DEFAULT NULL;
ALTER TABLE tasks ADD COLUMN archived_by_initiative_id TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_archived ON tasks(archived);
`;

// Migration SQL for version 7: Scope Change Requests (P3.3)
const MIGRATION_V7_SQL = `
-- scope_change_requests table
CREATE TABLE IF NOT EXISTS scope_change_requests (
  id TEXT PRIMARY KEY,
  prd_id TEXT NOT NULL,
  request_type TEXT NOT NULL CHECK(request_type IN ('add_task', 'modify_task', 'remove_task')),
  description TEXT NOT NULL,
  rationale TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
  created_at TEXT NOT NULL,
  reviewed_at TEXT,
  reviewed_by TEXT,
  review_notes TEXT,
  FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scope_requests_prd ON scope_change_requests(prd_id);
CREATE INDEX IF NOT EXISTS idx_scope_requests_status ON scope_change_requests(status);
CREATE INDEX IF NOT EXISTS idx_scope_requests_created ON scope_change_requests(created_at DESC);
`;

// Migration SQL for version 8: Agent Activity Tracking
const MIGRATION_V8_SQL = `
-- agent_activity table
CREATE TABLE IF NOT EXISTS agent_activity (
  id TEXT PRIMARY KEY,
  stream_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  activity_description TEXT,
  phase TEXT,
  started_at TEXT NOT NULL,
  last_heartbeat TEXT NOT NULL,
  completed_at TEXT,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_activity_stream ON agent_activity(stream_id);
CREATE INDEX IF NOT EXISTS idx_agent_activity_task ON agent_activity(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_activity_heartbeat ON agent_activity(last_heartbeat DESC);
`;

const MIGRATION_TABLE_SQL = `
CREATE TABLE IF NOT EXISTS migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
`;

const CURRENT_VERSION = 8;

export class DatabaseClient {
  private db: Database.Database;
  private workspaceId: string;

  constructor(projectPath: string, taskBasePath?: string, workspaceId?: string) {
    // Use workspaceId if provided, otherwise hash the project path
    this.workspaceId = workspaceId?.trim() || this.hashProjectPath(projectPath);
    const dbPath = this.getDbPath(this.workspaceId, taskBasePath);

    // Ensure directory exists
    const dbDir = dirname(dbPath);
    if (!existsSync(dbDir)) {
      mkdirSync(dbDir, { recursive: true });
    }

    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');

    // Run migrations
    this.migrate();
  }

  private hashProjectPath(projectPath: string): string {
    return createHash('md5').update(projectPath).digest('hex').substring(0, 12);
  }

  private getDbPath(workspaceId: string, taskBasePath?: string): string {
    const basePath = taskBasePath || join(homedir(), '.claude', 'tasks');
    return join(basePath, workspaceId, 'tasks.db');
  }

  private migrate(): void {
    // Create migration table
    this.db.exec(MIGRATION_TABLE_SQL);

    // Check current version
    const row = this.db.prepare('SELECT MAX(version) as version FROM migrations').get() as { version: number | null };
    const currentVersion = row?.version || 0;

    // Run initial schema (version 1)
    if (currentVersion < 1) {
      this.db.exec(SCHEMA_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        1,
        new Date().toISOString()
      );
    }

    // Migration v2: Agent Performance Tracking
    if (currentVersion < 2) {
      this.db.exec(MIGRATION_V2_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        2,
        new Date().toISOString()
      );
    }

    // Migration v3: Checkpoint System
    if (currentVersion < 3) {
      this.db.exec(MIGRATION_V3_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        3,
        new Date().toISOString()
      );
    }

    // Migration v4: Ralph Wiggum Iteration Support
    if (currentVersion < 4) {
      this.db.exec(MIGRATION_V4_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        4,
        new Date().toISOString()
      );
    }

    // Migration v5: Hierarchical Agent Handoffs
    if (currentVersion < 5) {
      this.db.exec(MIGRATION_V5_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        5,
        new Date().toISOString()
      );
    }

    // Migration v6: Stream Archival
    if (currentVersion < 6) {
      this.db.exec(MIGRATION_V6_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        6,
        new Date().toISOString()
      );
    }

    // Migration v7: Scope Change Requests (P3.3)
    if (currentVersion < 7) {
      this.db.exec(MIGRATION_V7_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        7,
        new Date().toISOString()
      );
    }

    // Migration v8: Agent Activity Tracking
    if (currentVersion < 8) {
      this.db.exec(MIGRATION_V8_SQL);
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        8,
        new Date().toISOString()
      );
    }
  }

  getWorkspaceId(): string {
    return this.workspaceId;
  }

  getDb(): Database.Database {
    return this.db;
  }

  // Initiative operations
  upsertInitiative(initiative: InitiativeRow): void {
    this.db.prepare(`
      INSERT INTO initiatives (id, title, description, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        title = excluded.title,
        description = excluded.description,
        updated_at = excluded.updated_at
    `).run(
      initiative.id,
      initiative.title,
      initiative.description,
      initiative.created_at,
      initiative.updated_at
    );
  }

  getInitiative(id: string): InitiativeRow | undefined {
    return this.db.prepare('SELECT * FROM initiatives WHERE id = ?').get(id) as InitiativeRow | undefined;
  }

  getCurrentInitiative(): InitiativeRow | undefined {
    return this.db.prepare('SELECT * FROM initiatives ORDER BY updated_at DESC LIMIT 1').get() as InitiativeRow | undefined;
  }

  // PRD operations
  insertPrd(prd: PrdRow): void {
    this.db.prepare(`
      INSERT INTO prds (id, initiative_id, title, description, content, metadata, status, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      prd.id,
      prd.initiative_id,
      prd.title,
      prd.description,
      prd.content,
      prd.metadata,
      prd.status,
      prd.created_at,
      prd.updated_at
    );
  }

  getPrd(id: string): PrdRow | undefined {
    return this.db.prepare('SELECT * FROM prds WHERE id = ?').get(id) as PrdRow | undefined;
  }

  listPrds(options: { initiativeId?: string; status?: PrdStatus }): PrdRow[] {
    let sql = 'SELECT * FROM prds WHERE 1=1';
    const params: unknown[] = [];

    if (options.initiativeId) {
      sql += ' AND initiative_id = ?';
      params.push(options.initiativeId);
    }

    if (options.status) {
      sql += ' AND status = ?';
      params.push(options.status);
    }

    sql += ' ORDER BY created_at DESC';

    return this.db.prepare(sql).all(...params) as PrdRow[];
  }

  getPrdTaskCount(prdId: string): { total: number; completed: number } {
    const result = this.db.prepare(`
      SELECT
        COUNT(*) as total,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
      FROM tasks
      WHERE prd_id = ?
    `).get(prdId) as { total: number; completed: number };
    return result;
  }

  // Task operations
  insertTask(task: TaskRow): void {
    this.db.prepare(`
      INSERT INTO tasks (id, prd_id, parent_id, title, description, assigned_agent, status, blocked_reason, notes, metadata, created_at, updated_at, archived, archived_at, archived_by_initiative_id)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      task.id,
      task.prd_id,
      task.parent_id,
      task.title,
      task.description,
      task.assigned_agent,
      task.status,
      task.blocked_reason,
      task.notes,
      task.metadata,
      task.created_at,
      task.updated_at,
      task.archived,
      task.archived_at,
      task.archived_by_initiative_id
    );
  }

  updateTask(id: string, updates: Partial<TaskRow>): void {
    const sets: string[] = [];
    const values: unknown[] = [];

    if (updates.status !== undefined) {
      sets.push('status = ?');
      values.push(updates.status);
    }
    if (updates.assigned_agent !== undefined) {
      sets.push('assigned_agent = ?');
      values.push(updates.assigned_agent);
    }
    if (updates.notes !== undefined) {
      sets.push('notes = ?');
      values.push(updates.notes);
    }
    if (updates.blocked_reason !== undefined) {
      sets.push('blocked_reason = ?');
      values.push(updates.blocked_reason);
    }
    if (updates.metadata !== undefined) {
      sets.push('metadata = ?');
      values.push(updates.metadata);
    }

    if (sets.length === 0) return;

    sets.push('updated_at = ?');
    values.push(new Date().toISOString());
    values.push(id);

    this.db.prepare(`
      UPDATE tasks SET ${sets.join(', ')} WHERE id = ?
    `).run(...values);
  }

  getTask(id: string): TaskRow | undefined {
    return this.db.prepare('SELECT * FROM tasks WHERE id = ?').get(id) as TaskRow | undefined;
  }

  listTasks(options: { prdId?: string; parentId?: string; status?: TaskStatus; assignedAgent?: string }): TaskRow[] {
    let sql = 'SELECT * FROM tasks WHERE 1=1';
    const params: unknown[] = [];

    if (options.prdId) {
      sql += ' AND prd_id = ?';
      params.push(options.prdId);
    }

    if (options.parentId !== undefined) {
      if (options.parentId === null) {
        sql += ' AND parent_id IS NULL';
      } else {
        sql += ' AND parent_id = ?';
        params.push(options.parentId);
      }
    }

    if (options.status) {
      sql += ' AND status = ?';
      params.push(options.status);
    }

    if (options.assignedAgent) {
      sql += ' AND assigned_agent = ?';
      params.push(options.assignedAgent);
    }

    sql += ' ORDER BY created_at ASC';

    return this.db.prepare(sql).all(...params) as TaskRow[];
  }

  getTaskSubtaskCount(taskId: string): { total: number; completed: number } {
    const result = this.db.prepare(`
      SELECT
        COUNT(*) as total,
        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
      FROM tasks
      WHERE parent_id = ?
    `).get(taskId) as { total: number; completed: number };
    return result;
  }

  /**
   * Get completed tasks within a time period (for velocity tracking)
   */
  getCompletedTasksInPeriod(startDate: string, endDate: string): TaskRow[] {
    return this.db.prepare(`
      SELECT * FROM tasks
      WHERE status = 'completed'
        AND updated_at >= ?
        AND updated_at <= ?
        AND archived = 0
      ORDER BY updated_at ASC
    `).all(startDate, endDate) as TaskRow[];
  }

  // Work Product operations
  insertWorkProduct(wp: WorkProductRow): void {
    this.db.prepare(`
      INSERT INTO work_products (id, task_id, type, title, content, metadata, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(
      wp.id,
      wp.task_id,
      wp.type,
      wp.title,
      wp.content,
      wp.metadata,
      wp.created_at
    );
  }

  getWorkProduct(id: string): WorkProductRow | undefined {
    return this.db.prepare('SELECT * FROM work_products WHERE id = ?').get(id) as WorkProductRow | undefined;
  }

  listWorkProducts(taskId: string): WorkProductRow[] {
    return this.db.prepare('SELECT * FROM work_products WHERE task_id = ? ORDER BY created_at DESC').all(taskId) as WorkProductRow[];
  }

  hasWorkProducts(taskId: string): boolean {
    const result = this.db.prepare('SELECT COUNT(*) as count FROM work_products WHERE task_id = ?').get(taskId) as { count: number };
    return result.count > 0;
  }

  // Activity Log operations
  insertActivity(activity: ActivityLogRow): void {
    this.db.prepare(`
      INSERT INTO activity_log (id, initiative_id, type, entity_id, entity_type, summary, metadata, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      activity.id,
      activity.initiative_id,
      activity.type,
      activity.entity_id,
      activity.entity_type || null,
      activity.summary,
      activity.metadata || null,
      activity.created_at
    );
  }

  listActivityLogs(initiativeId: string, limit?: number): ActivityLogRow[] {
    const sql = `SELECT * FROM activity_log WHERE initiative_id = ? ORDER BY created_at DESC ${limit ? `LIMIT ${limit}` : ''}`;
    return this.db.prepare(sql).all(initiativeId) as ActivityLogRow[];
  }

  // Initiative wipe operations
  wipeInitiativeData(initiativeId: string): { prds: number; tasks: number; workProducts: number; activityLogs: number } {
    // Get all PRD IDs for this initiative
    const prds = this.listPrds({ initiativeId });
    const prdIds = prds.map(p => p.id);

    // Get all task IDs related to these PRDs
    const allTasks: string[] = [];
    for (const prdId of prdIds) {
      const tasks = this.listTasks({ prdId });
      allTasks.push(...tasks.map(t => t.id));
    }

    // Count before deletion
    const prdCount = prds.length;
    const taskCount = allTasks.length;

    let workProductCount = 0;
    for (const taskId of allTasks) {
      const wps = this.listWorkProducts(taskId);
      workProductCount += wps.length;
    }

    const activityCount = this.listActivityLogs(initiativeId).length;

    // Delete in order: work_products -> tasks -> prds -> activity_log
    // Work products
    for (const taskId of allTasks) {
      this.db.prepare('DELETE FROM work_products WHERE task_id = ?').run(taskId);
    }

    // Tasks
    for (const prdId of prdIds) {
      this.db.prepare('DELETE FROM tasks WHERE prd_id = ?').run(prdId);
    }

    // PRDs
    this.db.prepare('DELETE FROM prds WHERE initiative_id = ?').run(initiativeId);

    // Activity logs
    this.db.prepare('DELETE FROM activity_log WHERE initiative_id = ?').run(initiativeId);

    return {
      prds: prdCount,
      tasks: taskCount,
      workProducts: workProductCount,
      activityLogs: activityCount
    };
  }

  // Stats
  getStats(): { prdCount: number; taskCount: number; completedTasks: number; workProductCount: number } {
    const prdCount = (this.db.prepare('SELECT COUNT(*) as count FROM prds').get() as { count: number }).count;
    const taskCount = (this.db.prepare('SELECT COUNT(*) as count FROM tasks').get() as { count: number }).count;
    const completedTasks = (this.db.prepare("SELECT COUNT(*) as count FROM tasks WHERE status = 'completed'").get() as { count: number }).count;
    const workProductCount = (this.db.prepare('SELECT COUNT(*) as count FROM work_products').get() as { count: number }).count;

    return {
      prdCount,
      taskCount,
      completedTasks,
      workProductCount
    };
  }

  // ============================================================================
  // AGENT PERFORMANCE TRACKING
  // ============================================================================

  insertPerformance(perf: PerformanceRow): void {
    this.db.prepare(`
      INSERT INTO agent_performance (id, agent_id, task_id, work_product_type, complexity, outcome, duration_ms, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      perf.id,
      perf.agent_id,
      perf.task_id,
      perf.work_product_type,
      perf.complexity,
      perf.outcome,
      perf.duration_ms,
      perf.created_at
    );
  }

  getPerformanceRecords(options: {
    agentId?: string;
    workProductType?: string;
    complexity?: string;
    sinceDays?: number;
  }): PerformanceRow[] {
    let sql = 'SELECT * FROM agent_performance WHERE 1=1';
    const params: unknown[] = [];

    if (options.agentId) {
      sql += ' AND agent_id = ?';
      params.push(options.agentId);
    }

    if (options.workProductType) {
      sql += ' AND work_product_type = ?';
      params.push(options.workProductType);
    }

    if (options.complexity) {
      sql += ' AND complexity = ?';
      params.push(options.complexity);
    }

    if (options.sinceDays) {
      const sinceDate = new Date();
      sinceDate.setDate(sinceDate.getDate() - options.sinceDays);
      sql += ' AND created_at >= ?';
      params.push(sinceDate.toISOString());
    }

    sql += ' ORDER BY created_at DESC';

    return this.db.prepare(sql).all(...params) as PerformanceRow[];
  }

  getPerformanceStats(): {
    totalRecords: number;
    oldestRecord: string | null;
    newestRecord: string | null;
  } {
    const count = (this.db.prepare('SELECT COUNT(*) as count FROM agent_performance').get() as { count: number }).count;
    const oldest = this.db.prepare('SELECT MIN(created_at) as oldest FROM agent_performance').get() as { oldest: string | null };
    const newest = this.db.prepare('SELECT MAX(created_at) as newest FROM agent_performance').get() as { newest: string | null };

    return {
      totalRecords: count,
      oldestRecord: oldest.oldest,
      newestRecord: newest.newest
    };
  }

  // ============================================================================
  // CHECKPOINT SYSTEM
  // ============================================================================

  insertCheckpoint(checkpoint: CheckpointRow): void {
    this.db.prepare(`
      INSERT INTO checkpoints (
        id, task_id, sequence, trigger, task_status, task_notes, task_metadata,
        blocked_reason, assigned_agent, execution_phase, execution_step,
        agent_context, draft_content, draft_type, subtask_states, created_at, expires_at,
        iteration_config, iteration_number, iteration_history, completion_promises, validation_state
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      checkpoint.id,
      checkpoint.task_id,
      checkpoint.sequence,
      checkpoint.trigger,
      checkpoint.task_status,
      checkpoint.task_notes,
      checkpoint.task_metadata,
      checkpoint.blocked_reason,
      checkpoint.assigned_agent,
      checkpoint.execution_phase,
      checkpoint.execution_step,
      checkpoint.agent_context,
      checkpoint.draft_content,
      checkpoint.draft_type,
      checkpoint.subtask_states,
      checkpoint.created_at,
      checkpoint.expires_at,
      checkpoint.iteration_config,
      checkpoint.iteration_number,
      checkpoint.iteration_history,
      checkpoint.completion_promises,
      checkpoint.validation_state
    );
  }

  getCheckpoint(id: string): CheckpointRow | undefined {
    return this.db.prepare('SELECT * FROM checkpoints WHERE id = ?').get(id) as CheckpointRow | undefined;
  }

  getLatestCheckpoint(taskId: string): CheckpointRow | undefined {
    return this.db.prepare(
      'SELECT * FROM checkpoints WHERE task_id = ? ORDER BY sequence DESC LIMIT 1'
    ).get(taskId) as CheckpointRow | undefined;
  }

  listCheckpoints(
    taskId: string,
    limit?: number,
    iterationNumber?: number,
    hasIteration?: boolean
  ): CheckpointRow[] {
    const whereClauses: string[] = ['task_id = ?'];
    const params: (string | number)[] = [taskId];

    // Add iteration number filter
    if (iterationNumber !== undefined) {
      whereClauses.push('iteration_number = ?');
      params.push(iterationNumber);
    }

    // Add hasIteration filter
    if (hasIteration !== undefined) {
      if (hasIteration) {
        whereClauses.push('iteration_config IS NOT NULL');
      } else {
        whereClauses.push('iteration_config IS NULL');
      }
    }

    const whereClause = whereClauses.join(' AND ');
    const sql = `SELECT * FROM checkpoints WHERE ${whereClause} ORDER BY sequence DESC ${limit ? `LIMIT ${limit}` : ''}`;
    return this.db.prepare(sql).all(...params) as CheckpointRow[];
  }

  getNextCheckpointSequence(taskId: string): number {
    const result = this.db.prepare(
      'SELECT MAX(sequence) as maxSeq FROM checkpoints WHERE task_id = ?'
    ).get(taskId) as { maxSeq: number | null };
    return (result.maxSeq || 0) + 1;
  }

  getCheckpointCount(taskId: string): number {
    const result = this.db.prepare(
      'SELECT COUNT(*) as count FROM checkpoints WHERE task_id = ?'
    ).get(taskId) as { count: number };
    return result.count;
  }

  deleteOldestCheckpoints(taskId: string, count: number): number {
    // Delete the oldest 'count' checkpoints for a task
    const result = this.db.prepare(`
      DELETE FROM checkpoints
      WHERE id IN (
        SELECT id FROM checkpoints
        WHERE task_id = ?
        ORDER BY sequence ASC
        LIMIT ?
      )
    `).run(taskId, count);
    return result.changes;
  }

  deleteExpiredCheckpoints(): number {
    const now = new Date().toISOString();
    const result = this.db.prepare(
      'DELETE FROM checkpoints WHERE expires_at IS NOT NULL AND expires_at < ?'
    ).run(now);
    return result.changes;
  }

  deleteCheckpointsForTask(taskId: string): number {
    const result = this.db.prepare('DELETE FROM checkpoints WHERE task_id = ?').run(taskId);
    return result.changes;
  }

  deleteCheckpointsOlderThan(minutes: number, taskId?: string): number {
    const cutoff = new Date(Date.now() - minutes * 60 * 1000).toISOString();
    let sql = 'DELETE FROM checkpoints WHERE created_at < ?';
    const params: unknown[] = [cutoff];

    if (taskId) {
      sql += ' AND task_id = ?';
      params.push(taskId);
    }

    const result = this.db.prepare(sql).run(...params);
    return result.changes;
  }

  updateCheckpointIteration(
    id: string,
    iterationNumber: number,
    iterationHistory: string,
    validationState: string | null
  ): void {
    this.db.prepare(`
      UPDATE checkpoints
      SET iteration_number = ?,
          iteration_history = ?,
          validation_state = ?
      WHERE id = ?
    `).run(iterationNumber, iterationHistory, validationState, id);
  }

  getTotalCheckpointCount(): number {
    const result = this.db.prepare('SELECT COUNT(*) as count FROM checkpoints').get() as { count: number };
    return result.count;
  }

  /**
   * Get latest checkpoint for any task in a stream
   * Used for context exhaustion recovery
   */
  getLatestCheckpointForStream(streamId: string): CheckpointRow | undefined {
    const sql = `
      SELECT cp.*
      FROM checkpoints cp
      JOIN tasks t ON cp.task_id = t.id
      WHERE t.metadata LIKE ?
        AND (cp.expires_at IS NULL OR cp.expires_at > datetime('now'))
      ORDER BY cp.created_at DESC
      LIMIT 1
    `;
    // Stream ID is stored in task.metadata as JSON: {"streamId": "Stream-A"}
    return this.db.prepare(sql).get(`%"streamId":"${streamId}"%`) as CheckpointRow | undefined;
  }

  /**
   * Get recent activities for a stream (for health check)
   * Used to detect stalled sessions
   */
  getActivitiesByStream(streamId: string, limit: number = 10): ActivityLogRow[] {
    const sql = `
      SELECT a.*
      FROM activity_log a
      WHERE (a.entity_type = 'task' AND a.entity_id IN (
        SELECT id FROM tasks WHERE metadata LIKE ?
      ))
      OR (a.entity_type = 'stream' AND a.entity_id = ?)
      ORDER BY a.created_at DESC
      LIMIT ?
    `;
    return this.db.prepare(sql).all(`%"streamId":"${streamId}"%`, streamId, limit) as ActivityLogRow[];
  }

  // ============================================================================
  // ITERATION METRICS (for performance tracking)
  // ============================================================================

  /**
   * Get all iteration checkpoints for performance analysis
   */
  getIterationCheckpoints(options: {
    agentId?: string;
    sinceDays?: number;
  }): CheckpointRow[] {
    let sql = `
      SELECT c.*
      FROM checkpoints c
      JOIN tasks t ON c.task_id = t.id
      WHERE c.iteration_config IS NOT NULL
    `;
    const params: unknown[] = [];

    if (options.agentId) {
      sql += ' AND t.assigned_agent = ?';
      params.push(options.agentId);
    }

    if (options.sinceDays) {
      const sinceDate = new Date();
      sinceDate.setDate(sinceDate.getDate() - options.sinceDays);
      sql += ' AND c.created_at >= ?';
      params.push(sinceDate.toISOString());
    }

    sql += ' ORDER BY c.created_at DESC';

    return this.db.prepare(sql).all(...params) as CheckpointRow[];
  }

  /**
   * Get iteration statistics for a specific agent
   */
  getIterationStats(agentId?: string, sinceDays?: number): {
    totalSessions: number;
    completedSessions: number;
    totalIterations: number;
    avgIterationsPerSession: number;
  } {
    let sql = `
      SELECT
        COUNT(DISTINCT c.id) as totalSessions,
        SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as completedSessions,
        SUM(c.iteration_number) as totalIterations
      FROM checkpoints c
      JOIN tasks t ON c.task_id = t.id
      WHERE c.iteration_config IS NOT NULL
    `;
    const params: unknown[] = [];

    if (agentId) {
      sql += ' AND t.assigned_agent = ?';
      params.push(agentId);
    }

    if (sinceDays) {
      const sinceDate = new Date();
      sinceDate.setDate(sinceDate.getDate() - sinceDays);
      sql += ' AND c.created_at >= ?';
      params.push(sinceDate.toISOString());
    }

    const result = this.db.prepare(sql).get(...params) as {
      totalSessions: number;
      completedSessions: number;
      totalIterations: number;
    };

    const avgIterationsPerSession = result.totalSessions > 0
      ? result.totalIterations / result.totalSessions
      : 0;

    return {
      totalSessions: result.totalSessions || 0,
      completedSessions: result.completedSessions || 0,
      totalIterations: result.totalIterations || 0,
      avgIterationsPerSession
    };
  }

  // ============================================================================
  // AGENT HANDOFFS
  // ============================================================================

  insertHandoff(handoff: {
    id: string;
    task_id: string;
    from_agent: string;
    to_agent: string;
    work_product_id: string;
    handoff_context: string;
    chain_position: number;
    chain_length: number;
    created_at: string;
  }): void {
    this.db.prepare(`
      INSERT INTO agent_handoffs (id, task_id, from_agent, to_agent, work_product_id, handoff_context, chain_position, chain_length, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      handoff.id,
      handoff.task_id,
      handoff.from_agent,
      handoff.to_agent,
      handoff.work_product_id,
      handoff.handoff_context,
      handoff.chain_position,
      handoff.chain_length,
      handoff.created_at
    );
  }

  getHandoffChain(taskId: string): Array<{
    id: string;
    task_id: string;
    from_agent: string;
    to_agent: string;
    work_product_id: string;
    handoff_context: string;
    chain_position: number;
    chain_length: number;
    created_at: string;
  }> {
    return this.db.prepare(
      'SELECT * FROM agent_handoffs WHERE task_id = ? ORDER BY chain_position ASC'
    ).all(taskId) as Array<{
      id: string;
      task_id: string;
      from_agent: string;
      to_agent: string;
      work_product_id: string;
      handoff_context: string;
      chain_position: number;
      chain_length: number;
      created_at: string;
    }>;
  }

  // ============================================================================
  // STREAM ARCHIVAL
  // ============================================================================

  /**
   * Archive all tasks with a streamId that belong to a specific initiative
   * Returns count of archived tasks
   */
  archiveStreamsForInitiative(currentInitiativeId: string, newInitiativeId: string): number {
    const now = new Date().toISOString();

    // Archive tasks that have streamId and belong to current initiative (via PRD join)
    const result1 = this.db.prepare(`
      UPDATE tasks
      SET archived = 1,
          archived_at = ?,
          archived_by_initiative_id = ?
      WHERE json_extract(metadata, '$.streamId') IS NOT NULL
        AND prd_id IN (
          SELECT id FROM prds WHERE initiative_id = ?
        )
        AND archived = 0
    `).run(now, newInitiativeId, currentInitiativeId);

    // Also archive orphaned stream tasks (no PRD) created before initiative switch
    const result2 = this.db.prepare(`
      UPDATE tasks
      SET archived = 1,
          archived_at = ?,
          archived_by_initiative_id = ?
      WHERE json_extract(metadata, '$.streamId') IS NOT NULL
        AND prd_id IS NULL
        AND archived = 0
    `).run(now, newInitiativeId);

    return result1.changes + result2.changes;
  }

  /**
   * Unarchive all tasks for a specific streamId
   * Returns count of unarchived tasks
   */
  unarchiveStream(streamId: string): number {
    const result = this.db.prepare(`
      UPDATE tasks
      SET archived = 0,
          archived_at = NULL,
          archived_by_initiative_id = NULL
      WHERE json_extract(metadata, '$.streamId') = ?
        AND archived = 1
    `).run(streamId);

    return result.changes;
  }

  // ============================================================================
  // SCOPE CHANGE REQUESTS (P3.3)
  // ============================================================================

  insertScopeChangeRequest(request: {
    id: string;
    prd_id: string;
    request_type: string;
    description: string;
    rationale: string;
    requested_by: string;
    status: string;
    created_at: string;
  }): void {
    this.db.prepare(`
      INSERT INTO scope_change_requests (id, prd_id, request_type, description, rationale, requested_by, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      request.id,
      request.prd_id,
      request.request_type,
      request.description,
      request.rationale,
      request.requested_by,
      request.status,
      request.created_at
    );
  }

  getScopeChangeRequest(id: string): {
    id: string;
    prd_id: string;
    request_type: string;
    description: string;
    rationale: string;
    requested_by: string;
    status: string;
    created_at: string;
    reviewed_at: string | null;
    reviewed_by: string | null;
    review_notes: string | null;
  } | undefined {
    return this.db.prepare('SELECT * FROM scope_change_requests WHERE id = ?').get(id) as {
      id: string;
      prd_id: string;
      request_type: string;
      description: string;
      rationale: string;
      requested_by: string;
      status: string;
      created_at: string;
      reviewed_at: string | null;
      reviewed_by: string | null;
      review_notes: string | null;
    } | undefined;
  }

  listScopeChangeRequests(options: {
    prdId?: string;
    status?: string;
  }): Array<{
    id: string;
    prd_id: string;
    request_type: string;
    description: string;
    rationale: string;
    requested_by: string;
    status: string;
    created_at: string;
    reviewed_at: string | null;
    reviewed_by: string | null;
    review_notes: string | null;
  }> {
    let sql = 'SELECT * FROM scope_change_requests WHERE 1=1';
    const params: unknown[] = [];

    if (options.prdId) {
      sql += ' AND prd_id = ?';
      params.push(options.prdId);
    }

    if (options.status) {
      sql += ' AND status = ?';
      params.push(options.status);
    }

    sql += ' ORDER BY created_at DESC';

    return this.db.prepare(sql).all(...params) as Array<{
      id: string;
      prd_id: string;
      request_type: string;
      description: string;
      rationale: string;
      requested_by: string;
      status: string;
      created_at: string;
      reviewed_at: string | null;
      reviewed_by: string | null;
      review_notes: string | null;
    }>;
  }

  updateScopeChangeRequest(id: string, updates: {
    status: string;
    reviewed_at: string;
    reviewed_by?: string;
    review_notes?: string;
  }): void {
    this.db.prepare(`
      UPDATE scope_change_requests
      SET status = ?,
          reviewed_at = ?,
          reviewed_by = ?,
          review_notes = ?
      WHERE id = ?
    `).run(
      updates.status,
      updates.reviewed_at,
      updates.reviewed_by || null,
      updates.review_notes || null,
      id
    );
  }

  // ============================================================================
  // AGENT ACTIVITY TRACKING
  // ============================================================================

  /**
   * Upsert agent activity record
   * Creates new record or updates existing one for the task
   */
  upsertAgentActivity(data: {
    stream_id: string;
    agent_id: string;
    task_id: string;
    activity_description?: string;
    phase?: string;
  }): void {
    const now = new Date().toISOString();
    const id = `ACTIVITY-${data.task_id}`;

    this.db.prepare(`
      INSERT INTO agent_activity (id, stream_id, agent_id, task_id, activity_description, phase, started_at, last_heartbeat, completed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
      ON CONFLICT(id) DO UPDATE SET
        stream_id = excluded.stream_id,
        agent_id = excluded.agent_id,
        activity_description = excluded.activity_description,
        phase = excluded.phase,
        last_heartbeat = excluded.last_heartbeat
    `).run(
      id,
      data.stream_id,
      data.agent_id,
      data.task_id,
      data.activity_description || null,
      data.phase || null,
      now,
      now
    );
  }

  /**
   * Update heartbeat timestamp for a task (for long-running tasks)
   */
  updateAgentHeartbeat(taskId: string, phase?: string): void {
    const now = new Date().toISOString();
    const id = `ACTIVITY-${taskId}`;

    if (phase !== undefined) {
      this.db.prepare(`
        UPDATE agent_activity
        SET last_heartbeat = ?, phase = ?
        WHERE id = ?
      `).run(now, phase, id);
    } else {
      this.db.prepare(`
        UPDATE agent_activity
        SET last_heartbeat = ?
        WHERE id = ?
      `).run(now, id);
    }
  }

  /**
   * Mark agent activity as complete
   */
  completeAgentActivity(taskId: string): void {
    const now = new Date().toISOString();
    const id = `ACTIVITY-${taskId}`;

    this.db.prepare(`
      UPDATE agent_activity
      SET completed_at = ?
      WHERE id = ?
    `).run(now, id);
  }

  /**
   * Get agent activities
   * By default, returns only active (incomplete) activities
   */
  getAgentActivities(options: {
    streamId?: string;
    activeOnly?: boolean;
  }): Array<{
    id: string;
    stream_id: string;
    agent_id: string;
    task_id: string;
    activity_description: string | null;
    phase: string | null;
    started_at: string;
    last_heartbeat: string;
    completed_at: string | null;
  }> {
    let sql = 'SELECT * FROM agent_activity WHERE 1=1';
    const params: unknown[] = [];

    if (options.streamId) {
      sql += ' AND stream_id = ?';
      params.push(options.streamId);
    }

    // Default: only show active (incomplete) activities
    if (options.activeOnly !== false) {
      sql += ' AND completed_at IS NULL';
    }

    sql += ' ORDER BY last_heartbeat DESC';

    return this.db.prepare(sql).all(...params) as Array<{
      id: string;
      stream_id: string;
      agent_id: string;
      task_id: string;
      activity_description: string | null;
      phase: string | null;
      started_at: string;
      last_heartbeat: string;
      completed_at: string | null;
    }>;
  }

  close(): void {
    this.db.close();
  }
}
