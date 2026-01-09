/**
 * Stream Management Tools
 *
 * Provides utilities for managing independent work streams in parallel sessions.
 * Streams enable semantic organization of tasks with file-based conflict detection.
 *
 * ## What Are Streams?
 *
 * Streams are semantic work units that group related tasks together. They enable:
 * 1. **Parallel development**: Multiple Claude Code sessions working simultaneously
 * 2. **File conflict detection**: Prevent multiple streams from modifying the same files
 * 3. **Dependency management**: Enforce ordering when work must be sequential
 *
 * ## Stream Naming Convention
 *
 * Streams are auto-generated with IDs like "Stream-A", "Stream-B", etc., but have
 * human-readable names like "foundation", "auth-api", "dashboard-ui".
 *
 * ## Stream Phases
 *
 * - **foundation**: Must complete before parallel streams can start
 * - **parallel**: Independent streams that can run simultaneously
 * - **integration**: Combines work from parallel streams, runs last
 *
 * ## Example Usage
 *
 * ```typescript
 * // Create tasks with stream metadata
 * await task_create({
 *   title: "Implement stream metadata schema",
 *   prdId: "PRD-001",
 *   assignedAgent: "me",
 *   metadata: {
 *     streamId: "Stream-A",
 *     streamName: "foundation",
 *     streamPhase: "foundation",
 *     files: [
 *       "mcp-servers/task-copilot/src/types.ts",
 *       "mcp-servers/task-copilot/src/tools/stream.ts"
 *     ],
 *     streamDependencies: [] // Foundation has no dependencies
 *   }
 * });
 *
 * // Check for file conflicts before starting work
 * const conflicts = await stream_conflict_check({
 *   files: ["mcp-servers/task-copilot/src/types.ts"],
 *   excludeStreamId: "Stream-A"
 * });
 *
 * if (conflicts.hasConflict) {
 *   console.log("File conflict detected - another stream is working on this file");
 * }
 *
 * // List all streams
 * const { streams } = await stream_list();
 * // Returns: [{ streamId: "Stream-A", streamName: "foundation", ... }]
 * ```
 *
 * ## Dependency Validation
 *
 * The system prevents circular dependencies using DAG validation:
 * - Stream-A → Stream-B → Stream-A ❌ (circular)
 * - Stream-A → Stream-B → Stream-C ✅ (valid chain)
 * - Stream-B depends on Stream-A (foundation) ✅ (valid)
 */

import { v4 as uuidv4 } from 'uuid';
import type { DatabaseClient } from '../database.js';
import type {
  StreamListInput,
  StreamListOutput,
  StreamGetInput,
  StreamGetOutput,
  StreamConflictCheckInput,
  StreamConflictCheckOutput,
  StreamArchiveAllInput,
  StreamArchiveAllOutput,
  StreamInfo,
  Task,
  TaskStatus,
  TaskMetadata
} from '../types.js';

/**
 * Validate stream dependencies for circular references
 * Returns error message if cycle detected, null if valid
 */
export function validateStreamDependencies(
  streamId: string,
  dependencies: string[],
  allStreams: Map<string, string[]>
): string | null {
  // Simple cycle detection using DFS
  const visited = new Set<string>();
  const recursionStack = new Set<string>();

  function hasCycle(current: string): boolean {
    if (recursionStack.has(current)) {
      return true; // Cycle detected
    }
    if (visited.has(current)) {
      return false; // Already processed
    }

    visited.add(current);
    recursionStack.add(current);

    const deps = allStreams.get(current) || [];
    for (const dep of deps) {
      if (hasCycle(dep)) {
        return true;
      }
    }

    recursionStack.delete(current);
    return false;
  }

  // Add the new stream to the map temporarily
  const testMap = new Map(allStreams);
  testMap.set(streamId, dependencies);

  // Check for cycles starting from the new stream
  if (hasCycle(streamId)) {
    return `Circular dependency detected: ${streamId} creates a cycle in stream dependencies`;
  }

  return null;
}

/**
 * List all streams for an initiative
 */
export function streamList(db: DatabaseClient, input: StreamListInput): StreamListOutput {
  const { initiativeId, prdId, includeArchived = false } = input;

  // Get current initiative if not specified
  let targetInitiativeId = initiativeId;
  if (!targetInitiativeId && !prdId) {
    const currentInitiative = db.getCurrentInitiative();
    if (!currentInitiative) {
      return { streams: [] };
    }
    targetInitiativeId = currentInitiative.id;
  }

  // Build query to get all tasks with stream metadata
  let sql = `
    SELECT t.*
    FROM tasks t
  `;
  const params: unknown[] = [];

  if (prdId) {
    sql += ' WHERE t.prd_id = ?';
    params.push(prdId);
  } else if (targetInitiativeId) {
    sql += `
      JOIN prds p ON t.prd_id = p.id
      WHERE p.initiative_id = ?
    `;
    params.push(targetInitiativeId);
  }

  sql += ' AND json_extract(t.metadata, \'$.streamId\') IS NOT NULL';

  // Filter archived streams unless explicitly included
  if (!includeArchived) {
    sql += ' AND (t.archived IS NULL OR t.archived = 0)';
  }

  sql += ' ORDER BY t.created_at ASC';

  const tasks = db.getDb().prepare(sql).all(...params) as Array<{
    id: string;
    prd_id: string | null;
    parent_id: string | null;
    title: string;
    description: string | null;
    assigned_agent: string | null;
    status: string;
    blocked_reason: string | null;
    notes: string | null;
    metadata: string;
    created_at: string;
    updated_at: string;
  }>;

  // Group tasks by streamId
  const streamMap = new Map<string, {
    streamId: string;
    streamName: string;
    streamPhase: 'foundation' | 'parallel' | 'integration';
    tasks: Array<{
      id: string;
      status: TaskStatus;
      metadata: TaskMetadata;
    }>;
    filesSet: Set<string>;
    dependenciesSet: Set<string>;
  }>();

  for (const taskRow of tasks) {
    const metadata = JSON.parse(taskRow.metadata) as TaskMetadata;
    const streamId = metadata.streamId;

    if (!streamId) continue;

    if (!streamMap.has(streamId)) {
      streamMap.set(streamId, {
        streamId,
        streamName: metadata.streamName || streamId,
        streamPhase: metadata.streamPhase || 'parallel',
        tasks: [],
        filesSet: new Set(),
        dependenciesSet: new Set()
      });
    }

    const stream = streamMap.get(streamId)!;
    stream.tasks.push({
      id: taskRow.id,
      status: taskRow.status as TaskStatus,
      metadata
    });

    // Collect files
    if (metadata.files) {
      metadata.files.forEach(f => stream.filesSet.add(f));
    }

    // Collect dependencies
    if (metadata.streamDependencies) {
      metadata.streamDependencies.forEach(d => stream.dependenciesSet.add(d));
    }
  }

  // Convert to StreamInfo array
  const streams: StreamInfo[] = Array.from(streamMap.values()).map(stream => {
    const totalTasks = stream.tasks.length;
    const completedTasks = stream.tasks.filter(t => t.status === 'completed').length;
    const inProgressTasks = stream.tasks.filter(t => t.status === 'in_progress').length;
    const blockedTasks = stream.tasks.filter(t => t.status === 'blocked').length;
    const pendingTasks = stream.tasks.filter(t => t.status === 'pending').length;

    // Extract worktree metadata from first task (all tasks in stream share same worktree)
    const firstTask = stream.tasks[0];
    const worktreePath = firstTask?.metadata?.worktreePath;
    const branchName = firstTask?.metadata?.branchName;

    return {
      streamId: stream.streamId,
      streamName: stream.streamName,
      streamPhase: stream.streamPhase,
      totalTasks,
      completedTasks,
      inProgressTasks,
      blockedTasks,
      pendingTasks,
      files: Array.from(stream.filesSet),
      dependencies: Array.from(stream.dependenciesSet),
      worktreePath,
      branchName
    };
  });

  // Sort by phase: foundation -> parallel -> integration
  const phaseOrder = { foundation: 1, parallel: 2, integration: 3 };
  streams.sort((a, b) => {
    const phaseA = phaseOrder[a.streamPhase];
    const phaseB = phaseOrder[b.streamPhase];
    if (phaseA !== phaseB) return phaseA - phaseB;
    return a.streamName.localeCompare(b.streamName);
  });

  return { streams };
}

/**
 * Get all tasks for a specific stream
 */
export function streamGet(db: DatabaseClient, input: StreamGetInput): StreamGetOutput | null {
  const { streamId, initiativeId, includeArchived = false } = input;

  // Build query
  let sql = `
    SELECT t.*
    FROM tasks t
  `;
  const params: unknown[] = [];

  if (initiativeId) {
    sql += `
      JOIN prds p ON t.prd_id = p.id
      WHERE p.initiative_id = ?
        AND json_extract(t.metadata, '$.streamId') = ?
    `;
    params.push(initiativeId, streamId);
  } else {
    sql += `
      WHERE json_extract(t.metadata, '$.streamId') = ?
    `;
    params.push(streamId);
  }

  // Filter archived unless explicitly included
  if (!includeArchived) {
    sql += ' AND (t.archived IS NULL OR t.archived = 0)';
  }

  sql += ' ORDER BY t.created_at ASC';

  const taskRows = db.getDb().prepare(sql).all(...params) as Array<{
    id: string;
    prd_id: string | null;
    parent_id: string | null;
    title: string;
    description: string | null;
    assigned_agent: string | null;
    status: string;
    blocked_reason: string | null;
    notes: string | null;
    metadata: string;
    created_at: string;
    updated_at: string;
  }>;

  if (taskRows.length === 0) {
    return null;
  }

  // Parse first task to get stream metadata
  const firstMetadata = JSON.parse(taskRows[0].metadata) as TaskMetadata;
  const streamName = firstMetadata.streamName || streamId;
  const streamPhase = firstMetadata.streamPhase || 'parallel';
  const dependencies = firstMetadata.streamDependencies || [];

  // Convert to Task objects
  const tasks: Task[] = taskRows.map(row => ({
    id: row.id,
    prdId: row.prd_id || undefined,
    parentId: row.parent_id || undefined,
    title: row.title,
    description: row.description || undefined,
    assignedAgent: row.assigned_agent || undefined,
    status: row.status as TaskStatus,
    blockedReason: row.blocked_reason || undefined,
    notes: row.notes || undefined,
    metadata: JSON.parse(row.metadata) as TaskMetadata,
    createdAt: row.created_at,
    updatedAt: row.updated_at
  }));

  // Determine stream status
  const allCompleted = tasks.every(t => t.status === 'completed');
  const anyInProgress = tasks.some(t => t.status === 'in_progress');
  const anyBlocked = tasks.some(t => t.status === 'blocked');

  let status: 'pending' | 'in_progress' | 'completed' | 'blocked';
  if (allCompleted) {
    status = 'completed';
  } else if (anyBlocked) {
    status = 'blocked';
  } else if (anyInProgress) {
    status = 'in_progress';
  } else {
    status = 'pending';
  }

  // Extract worktree metadata from first task (all tasks in stream share same worktree)
  const worktreePath = tasks[0]?.metadata?.worktreePath;
  const branchName = tasks[0]?.metadata?.branchName;

  // Check if stream is archived (all tasks have archived flag set)
  const firstTaskRow = taskRows[0];
  const archived = firstTaskRow && (firstTaskRow as any).archived === 1;
  const archivedAt = archived ? (firstTaskRow as any).archived_at : undefined;
  const archivedByInitiativeId = archived ? (firstTaskRow as any).archived_by_initiative_id : undefined;

  return {
    streamId,
    streamName,
    streamPhase,
    tasks,
    dependencies,
    status,
    worktreePath,
    branchName,
    archived,
    archivedAt,
    archivedByInitiativeId
  };
}

/**
 * Unarchive a stream and link it to current or specified initiative
 */
export function streamUnarchive(
  db: DatabaseClient,
  input: { streamId: string; initiativeId?: string; prdId?: string }
): { streamId: string; tasksUnarchived: number; newInitiativeId: string } {
  const { streamId, initiativeId, prdId } = input;

  // Get current initiative if not specified
  let targetInitiativeId = initiativeId;
  if (!targetInitiativeId) {
    const currentInitiative = db.getCurrentInitiative();
    if (!currentInitiative) {
      throw new Error('No current initiative found. Please specify initiativeId or link an initiative first.');
    }
    targetInitiativeId = currentInitiative.id;
  }

  // Build unarchive query with optional prdId filter
  let sql = `
    UPDATE tasks
    SET archived = 0,
        archived_at = NULL,
        archived_by_initiative_id = NULL
    WHERE json_extract(metadata, '$.streamId') = ?
      AND archived = 1
  `;
  const params: unknown[] = [streamId];

  if (prdId) {
    sql += ' AND prd_id = ?';
    params.push(prdId);
  }

  const result = db.getDb().prepare(sql).run(...params);
  const tasksUnarchived = result.changes || 0;

  if (tasksUnarchived === 0) {
    const prdFilter = prdId ? ` for PRD ${prdId}` : '';
    throw new Error(`No archived tasks found for stream: ${streamId}${prdFilter}`);
  }

  // Log activity
  const now = new Date().toISOString();
  db.insertActivity({
    id: uuidv4(),
    initiative_id: targetInitiativeId,
    type: 'stream_unarchived',
    entity_id: streamId,
    entity_type: 'stream',
    summary: `Unarchived stream ${streamId} (${tasksUnarchived} tasks) and linked to initiative ${targetInitiativeId}${prdId ? ` (PRD: ${prdId})` : ''}`,
    metadata: JSON.stringify({
      streamId,
      tasksUnarchived,
      targetInitiativeId,
      prdId
    }),
    created_at: now
  });

  return {
    streamId,
    tasksUnarchived,
    newInitiativeId: targetInitiativeId
  };
}

/**
 * Archive all active streams (one-time cleanup for legacy data)
 *
 * Used after updating to auto-archive feature to clean up existing streams
 * from old initiatives. Requires confirm=true as a safety check.
 */
export function streamArchiveAll(
  db: DatabaseClient,
  input: StreamArchiveAllInput
): StreamArchiveAllOutput {
  const { confirm, initiativeId, prdId } = input;

  // Safety check
  if (!confirm) {
    throw new Error('Must set confirm=true to archive all streams');
  }

  const now = new Date().toISOString();

  // Get current initiative if not specified and no prdId provided
  let targetInitiativeId = initiativeId;
  if (!targetInitiativeId && !prdId) {
    const currentInitiative = db.getCurrentInitiative();
    if (currentInitiative) {
      targetInitiativeId = currentInitiative.id;
    }
  }

  // Build query to archive tasks with streamIds
  let sql = `
    UPDATE tasks
    SET archived = 1,
        archived_at = ?,
        archived_by_initiative_id = ?
    WHERE json_extract(metadata, '$.streamId') IS NOT NULL
      AND (archived IS NULL OR archived = 0)
  `;
  const params: unknown[] = [now, targetInitiativeId || prdId || 'manual'];

  // Add prdId filter if specified (takes precedence over initiativeId)
  if (prdId) {
    sql += ' AND prd_id = ?';
    params.push(prdId);
  } else if (targetInitiativeId) {
    sql += `
      AND prd_id IN (
        SELECT id FROM prds WHERE initiative_id = ?
      )
    `;
    params.push(targetInitiativeId);
  }

  const result = db.getDb().prepare(sql).run(...params);
  const tasksArchived = result.changes || 0;

  // Count unique streams archived
  let countSql = `
    SELECT COUNT(DISTINCT json_extract(metadata, '$.streamId')) as count
    FROM tasks
    WHERE archived = 1
      AND archived_at = ?
  `;
  const countParams: unknown[] = [now];

  if (prdId) {
    countSql += ' AND prd_id = ?';
    countParams.push(prdId);
  } else if (targetInitiativeId) {
    countSql += `
      AND prd_id IN (
        SELECT id FROM prds WHERE initiative_id = ?
      )
    `;
    countParams.push(targetInitiativeId);
  }

  const countResult = db.getDb().prepare(countSql).get(...countParams) as { count: number };
  const streamsArchived = countResult.count;

  // Log activity
  if (targetInitiativeId || prdId) {
    const scopeDesc = prdId ? `PRD ${prdId}` : `initiative ${targetInitiativeId}`;
    db.insertActivity({
      id: uuidv4(),
      initiative_id: targetInitiativeId || 'unknown',
      type: 'stream_archive_all',
      entity_id: 'bulk',
      entity_type: 'stream',
      summary: `Archived all streams for ${scopeDesc} (${streamsArchived} streams, ${tasksArchived} tasks)`,
      metadata: JSON.stringify({
        streamsArchived,
        tasksArchived,
        targetInitiativeId,
        prdId
      }),
      created_at: now
    });
  }

  return {
    streamsArchived,
    tasksArchived,
    archivedAt: now
  };
}

/**
 * Check for file conflicts between streams
 *
 * Note: Streams with worktrees are isolated and won't conflict with other streams.
 * Only streams sharing the same worktree (main or no worktree) can have conflicts.
 */
export function streamConflictCheck(
  db: DatabaseClient,
  input: StreamConflictCheckInput
): StreamConflictCheckOutput {
  const { files, excludeStreamId, initiativeId } = input;

  if (files.length === 0) {
    return { hasConflict: false, conflicts: [] };
  }

  // If checking for an excluded stream, check if it has a worktree
  // If it does, it's isolated and won't conflict
  if (excludeStreamId) {
    const streamInfo = streamGet(db, { streamId: excludeStreamId, initiativeId });
    if (streamInfo?.worktreePath) {
      // Stream has worktree isolation, no conflicts possible
      return { hasConflict: false, conflicts: [] };
    }
  }

  const conflicts: StreamConflictCheckOutput['conflicts'] = [];

  // For each file, search for tasks that touch it
  for (const file of files) {
    let sql = `
      SELECT t.id, t.title, t.status, t.metadata
      FROM tasks t
    `;
    const params: unknown[] = [];

    if (initiativeId) {
      sql += `
        JOIN prds p ON t.prd_id = p.id
        WHERE p.initiative_id = ?
          AND json_extract(t.metadata, '$.files') LIKE ?
          AND t.status IN ('in_progress', 'completed')
      `;
      params.push(initiativeId, `%"${file}"%`);
    } else {
      sql += `
        WHERE json_extract(t.metadata, '$.files') LIKE ?
          AND t.status IN ('in_progress', 'completed')
      `;
      params.push(`%"${file}"%`);
    }

    if (excludeStreamId) {
      sql += ' AND json_extract(t.metadata, \'$.streamId\') != ?';
      params.push(excludeStreamId);
    }

    sql += ' ORDER BY t.updated_at DESC';

    const conflictingTasks = db.getDb().prepare(sql).all(...params) as Array<{
      id: string;
      title: string;
      status: string;
      metadata: string;
    }>;

    for (const task of conflictingTasks) {
      const metadata = JSON.parse(task.metadata) as TaskMetadata;
      if (metadata.streamId) {
        // Skip if conflicting stream has worktree isolation
        if (metadata.worktreePath) {
          continue;
        }

        conflicts.push({
          file,
          streamId: metadata.streamId,
          streamName: metadata.streamName || metadata.streamId,
          taskId: task.id,
          taskTitle: task.title,
          taskStatus: task.status as TaskStatus
        });
      }
    }
  }

  return {
    hasConflict: conflicts.length > 0,
    conflicts
  };
}
