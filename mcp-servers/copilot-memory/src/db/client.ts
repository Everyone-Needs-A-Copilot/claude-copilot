/**
 * SQLite database client with sqlite-vec support
 */

import Database from 'better-sqlite3';
import * as sqliteVec from 'sqlite-vec';
import { createHash } from 'crypto';
import { existsSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { homedir } from 'os';

import { SCHEMA_SQL, VECTOR_SCHEMA_SQL, MIGRATION_TABLE_SQL, CURRENT_VERSION, MIGRATION_V2_SQL, MIGRATION_V3_SQL } from './schema.js';
import type { MemoryRow, InitiativeRow, EmbeddingVector } from '../types.js';
import type { CorrectionRow, CorrectionStatus, CorrectionTarget } from '../types/corrections.js';

export class DatabaseClient {
  private db: Database.Database;
  private projectId: string;

  constructor(projectPath: string, memoryBasePath?: string, workspaceId?: string) {
    // Use workspaceId if provided, otherwise hash the project path
    this.projectId = workspaceId?.trim() || this.hashProjectPath(projectPath);
    const dbPath = this.getDbPath(this.projectId, memoryBasePath);

    // Ensure directory exists
    const dbDir = dirname(dbPath);
    if (!existsSync(dbDir)) {
      mkdirSync(dbDir, { recursive: true });
    }

    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');

    // Load sqlite-vec extension
    sqliteVec.load(this.db);

    // Run migrations
    this.migrate();
  }

  private hashProjectPath(projectPath: string): string {
    return createHash('md5').update(projectPath).digest('hex').substring(0, 12);
  }

  private getDbPath(projectId: string, memoryBasePath?: string): string {
    const basePath = memoryBasePath || join(homedir(), '.claude', 'memory');
    return join(basePath, projectId, 'memory.db');
  }

  private migrate(): void {
    // Create migration table
    this.db.exec(MIGRATION_TABLE_SQL);

    // Check current version
    const row = this.db.prepare('SELECT MAX(version) as version FROM migrations').get() as { version: number | null };
    const currentVersion = row?.version || 0;

    if (currentVersion < 1) {
      // Run initial schema
      this.db.exec(SCHEMA_SQL);

      // Run vector schema separately (different virtual table syntax)
      try {
        this.db.exec(VECTOR_SCHEMA_SQL);
      } catch (err) {
        // Vector table might already exist
        console.warn('Vector table creation warning:', err);
      }

      // Record migration
      this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
        1,
        new Date().toISOString()
      );
    }

    if (currentVersion < 2) {
      // Run migration v2: Add slim initiative fields
      // Only add columns if they don't already exist
      try {
        // Check if columns already exist (they would if schema was created fresh from v2)
        const tableInfo = this.db.pragma('table_info(initiatives)') as Array<{ name: string }>;
        const hasTaskCopilotLinked = tableInfo.some(col => col.name === 'task_copilot_linked');

        if (!hasTaskCopilotLinked) {
          // Columns don't exist, run migration
          this.db.exec(MIGRATION_V2_SQL);
        }

        // Always record migration as applied
        this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
          2,
          new Date().toISOString()
        );
      } catch (err) {
        console.warn('Migration v2 warning:', err);
      }
    }

    if (currentVersion < 3) {
      // Run migration v3: Add corrections table
      try {
        // Check if corrections table already exists
        const tables = this.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='corrections'").all();

        if (tables.length === 0) {
          // Table doesn't exist, run migration
          this.db.exec(MIGRATION_V3_SQL);
        }

        // Always record migration as applied
        this.db.prepare('INSERT INTO migrations (version, applied_at) VALUES (?, ?)').run(
          3,
          new Date().toISOString()
        );
      } catch (err) {
        console.warn('Migration v3 warning:', err);
      }
    }
  }

  getProjectId(): string {
    return this.projectId;
  }

  // Memory operations
  insertMemory(memory: Omit<MemoryRow, 'project_id'>): void {
    this.db.prepare(`
      INSERT INTO memories (id, project_id, content, type, tags, metadata, created_at, updated_at, session_id)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      memory.id,
      this.projectId,
      memory.content,
      memory.type,
      memory.tags,
      memory.metadata,
      memory.created_at,
      memory.updated_at,
      memory.session_id
    );
  }

  updateMemory(id: string, updates: Partial<MemoryRow>): void {
    const sets: string[] = [];
    const values: unknown[] = [];

    if (updates.content !== undefined) {
      sets.push('content = ?');
      values.push(updates.content);
    }
    if (updates.tags !== undefined) {
      sets.push('tags = ?');
      values.push(updates.tags);
    }
    if (updates.metadata !== undefined) {
      sets.push('metadata = ?');
      values.push(updates.metadata);
    }

    sets.push('updated_at = ?');
    values.push(new Date().toISOString());
    values.push(id);
    values.push(this.projectId);

    this.db.prepare(`
      UPDATE memories SET ${sets.join(', ')} WHERE id = ? AND project_id = ?
    `).run(...values);
  }

  deleteMemory(id: string): void {
    this.db.prepare('DELETE FROM memories WHERE id = ? AND project_id = ?').run(id, this.projectId);
  }

  getMemory(id: string): MemoryRow | undefined {
    return this.db.prepare('SELECT * FROM memories WHERE id = ? AND project_id = ?').get(id, this.projectId) as MemoryRow | undefined;
  }

  listMemories(options: { type?: string; tags?: string[]; agentId?: string; limit?: number; offset?: number }): MemoryRow[] {
    let sql = 'SELECT * FROM memories WHERE project_id = ?';
    const params: unknown[] = [this.projectId];

    if (options.type) {
      sql += ' AND type = ?';
      params.push(options.type);
    }

    if (options.tags && options.tags.length > 0) {
      // Match any of the tags
      const tagConditions = options.tags.map(() => "tags LIKE ?").join(' OR ');
      sql += ` AND (${tagConditions})`;
      options.tags.forEach(tag => params.push(`%"${tag}"%`));
    }

    if (options.agentId) {
      // Filter by agentId in metadata (for agent_improvement type)
      sql += ' AND metadata LIKE ?';
      params.push(`%"agentId":"${options.agentId}"%`);
    }

    sql += ' ORDER BY created_at DESC';

    if (options.limit) {
      sql += ' LIMIT ?';
      params.push(options.limit);
    }

    if (options.offset) {
      sql += ' OFFSET ?';
      params.push(options.offset);
    }

    return this.db.prepare(sql).all(...params) as MemoryRow[];
  }

  // Embedding operations
  insertEmbedding(memoryId: string, embedding: EmbeddingVector): void {
    this.db.prepare(`
      INSERT INTO memory_embeddings (memory_id, embedding)
      VALUES (?, ?)
    `).run(memoryId, Buffer.from(embedding.buffer));
  }

  deleteEmbedding(memoryId: string): void {
    this.db.prepare('DELETE FROM memory_embeddings WHERE memory_id = ?').run(memoryId);
  }

  searchByEmbedding(
    queryEmbedding: EmbeddingVector,
    options: { type?: string; agentId?: string; limit?: number; threshold?: number }
  ): Array<MemoryRow & { distance: number }> {
    const limit = options.limit || 10;
    const threshold = options.threshold || 0.7;

    let sql = `
      SELECT
        m.*,
        e.distance
      FROM memory_embeddings e
      JOIN memories m ON m.id = e.memory_id
      WHERE m.project_id = ?
        AND e.embedding MATCH ?
        AND k = ?
    `;
    const params: unknown[] = [this.projectId, Buffer.from(queryEmbedding.buffer), limit];

    if (options.type) {
      sql += ' AND m.type = ?';
      params.push(options.type);
    }

    if (options.agentId) {
      sql += ' AND m.metadata LIKE ?';
      params.push(`%"agentId":"${options.agentId}"%`);
    }

    sql += ` ORDER BY e.distance`;

    const results = this.db.prepare(sql).all(...params) as Array<MemoryRow & { distance: number }>;
    return results.filter(r => r.distance <= threshold);
  }

  // Initiative operations
  getInitiative(): InitiativeRow | undefined {
    return this.db.prepare('SELECT * FROM initiatives WHERE project_id = ?').get(this.projectId) as InitiativeRow | undefined;
  }

  upsertInitiative(initiative: Omit<InitiativeRow, 'project_id'>): void {
    this.db.prepare(`
      INSERT INTO initiatives (
        id, project_id, name, goal, status,
        task_copilot_linked, active_prd_ids,
        decisions, lessons, key_files,
        current_focus, next_action,
        completed, in_progress, blocked, resume_instructions,
        created_at, updated_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(project_id) DO UPDATE SET
        name = excluded.name,
        goal = excluded.goal,
        status = excluded.status,
        task_copilot_linked = excluded.task_copilot_linked,
        active_prd_ids = excluded.active_prd_ids,
        decisions = excluded.decisions,
        lessons = excluded.lessons,
        key_files = excluded.key_files,
        current_focus = excluded.current_focus,
        next_action = excluded.next_action,
        completed = excluded.completed,
        in_progress = excluded.in_progress,
        blocked = excluded.blocked,
        resume_instructions = excluded.resume_instructions,
        updated_at = excluded.updated_at
    `).run(
      initiative.id,
      this.projectId,
      initiative.name,
      initiative.goal,
      initiative.status,
      initiative.task_copilot_linked,
      initiative.active_prd_ids,
      initiative.decisions,
      initiative.lessons,
      initiative.key_files,
      initiative.current_focus,
      initiative.next_action,
      initiative.completed,
      initiative.in_progress,
      initiative.blocked,
      initiative.resume_instructions,
      initiative.created_at,
      initiative.updated_at
    );
  }

  archiveInitiative(): void {
    const initiative = this.getInitiative();
    if (!initiative) return;

    // Copy to archive
    this.db.prepare(`
      INSERT INTO initiatives_archive (
        id, project_id, name, goal, status,
        task_copilot_linked, active_prd_ids,
        decisions, lessons, key_files,
        current_focus, next_action,
        completed, in_progress, blocked, resume_instructions,
        created_at, updated_at, archived_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      initiative.id,
      initiative.project_id,
      initiative.name,
      initiative.goal,
      initiative.status,
      initiative.task_copilot_linked,
      initiative.active_prd_ids,
      initiative.decisions,
      initiative.lessons,
      initiative.key_files,
      initiative.current_focus,
      initiative.next_action,
      initiative.completed,
      initiative.in_progress,
      initiative.blocked,
      initiative.resume_instructions,
      initiative.created_at,
      initiative.updated_at,
      new Date().toISOString()
    );

    // Delete from active
    this.db.prepare('DELETE FROM initiatives WHERE project_id = ?').run(this.projectId);
  }

  // Full-text search
  searchFullText(query: string, limit: number = 10): MemoryRow[] {
    return this.db.prepare(`
      SELECT m.* FROM memories m
      JOIN memories_fts fts ON m.rowid = fts.rowid
      WHERE m.project_id = ? AND memories_fts MATCH ?
      ORDER BY rank
      LIMIT ?
    `).all(this.projectId, query, limit) as MemoryRow[];
  }

  // Stats
  getStats(): { memoryCount: number; initiativeActive: boolean; lastUpdated: string | null; correctionCount?: number } {
    const memoryCount = (this.db.prepare('SELECT COUNT(*) as count FROM memories WHERE project_id = ?').get(this.projectId) as { count: number }).count;
    const initiative = this.getInitiative();
    const lastMemory = this.db.prepare('SELECT MAX(updated_at) as last FROM memories WHERE project_id = ?').get(this.projectId) as { last: string | null };

    // Get correction count
    let correctionCount = 0;
    try {
      correctionCount = (this.db.prepare('SELECT COUNT(*) as count FROM corrections WHERE project_id = ?').get(this.projectId) as { count: number }).count;
    } catch {
      // Table might not exist in older databases
    }

    return {
      memoryCount,
      initiativeActive: !!initiative,
      lastUpdated: lastMemory.last || initiative?.updated_at || null,
      correctionCount
    };
  }

  // Correction operations
  insertCorrection(correction: Omit<CorrectionRow, 'project_id'>): void {
    this.db.prepare(`
      INSERT INTO corrections (
        id, project_id, session_id, task_id, agent_id,
        original_content, corrected_content, raw_user_message,
        matched_patterns, extracted_what, extracted_why, extracted_how,
        target, target_id, target_section, confidence, status,
        created_at, updated_at, reviewed_at, applied_at, expires_at, review_metadata
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      correction.id,
      this.projectId,
      correction.session_id,
      correction.task_id,
      correction.agent_id,
      correction.original_content,
      correction.corrected_content,
      correction.raw_user_message,
      correction.matched_patterns,
      correction.extracted_what,
      correction.extracted_why,
      correction.extracted_how,
      correction.target,
      correction.target_id,
      correction.target_section,
      correction.confidence,
      correction.status,
      correction.created_at,
      correction.updated_at,
      correction.reviewed_at,
      correction.applied_at,
      correction.expires_at,
      correction.review_metadata
    );
  }

  updateCorrection(id: string, updates: Partial<CorrectionRow>): void {
    const sets: string[] = [];
    const values: unknown[] = [];

    if (updates.status !== undefined) {
      sets.push('status = ?');
      values.push(updates.status);
    }
    if (updates.reviewed_at !== undefined) {
      sets.push('reviewed_at = ?');
      values.push(updates.reviewed_at);
    }
    if (updates.applied_at !== undefined) {
      sets.push('applied_at = ?');
      values.push(updates.applied_at);
    }
    if (updates.review_metadata !== undefined) {
      sets.push('review_metadata = ?');
      values.push(updates.review_metadata);
    }

    sets.push('updated_at = ?');
    values.push(new Date().toISOString());
    values.push(id);
    values.push(this.projectId);

    this.db.prepare(`
      UPDATE corrections SET ${sets.join(', ')} WHERE id = ? AND project_id = ?
    `).run(...values);
  }

  getCorrection(id: string): CorrectionRow | undefined {
    return this.db.prepare('SELECT * FROM corrections WHERE id = ? AND project_id = ?').get(id, this.projectId) as CorrectionRow | undefined;
  }

  listCorrections(options: {
    status?: CorrectionStatus;
    agentId?: string;
    target?: CorrectionTarget;
    limit?: number;
    offset?: number;
    includeExpired?: boolean;
  }): CorrectionRow[] {
    let sql = 'SELECT * FROM corrections WHERE project_id = ?';
    const params: unknown[] = [this.projectId];

    if (options.status) {
      sql += ' AND status = ?';
      params.push(options.status);
    }

    if (options.agentId) {
      sql += ' AND agent_id = ?';
      params.push(options.agentId);
    }

    if (options.target) {
      sql += ' AND target = ?';
      params.push(options.target);
    }

    if (!options.includeExpired) {
      sql += ' AND (expires_at IS NULL OR expires_at > ?)';
      params.push(new Date().toISOString());
    }

    sql += ' ORDER BY created_at DESC';

    if (options.limit) {
      sql += ' LIMIT ?';
      params.push(options.limit);
    }

    if (options.offset) {
      sql += ' OFFSET ?';
      params.push(options.offset);
    }

    return this.db.prepare(sql).all(...params) as CorrectionRow[];
  }

  getCorrectionStats(): {
    total: number;
    pending: number;
    approved: number;
    rejected: number;
    applied: number;
    expired: number;
  } {
    const stats = this.db.prepare(`
      SELECT
        COUNT(*) as total,
        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
        SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
        SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
        SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) as applied,
        SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) as expired
      FROM corrections WHERE project_id = ?
    `).get(this.projectId) as {
      total: number;
      pending: number;
      approved: number;
      rejected: number;
      applied: number;
      expired: number;
    };

    return stats;
  }

  expireOldCorrections(): number {
    const result = this.db.prepare(`
      UPDATE corrections
      SET status = 'expired', updated_at = ?
      WHERE project_id = ?
        AND status = 'pending'
        AND expires_at IS NOT NULL
        AND expires_at < ?
    `).run(
      new Date().toISOString(),
      this.projectId,
      new Date().toISOString()
    );

    return result.changes;
  }

  close(): void {
    this.db.close();
  }
}
