/**
 * Worktree tool implementations for conflict management and lifecycle
 */

import type { DatabaseClient } from '../database.js';
import { WorktreeManager, type WorktreeInfo } from '../utils/worktree-manager.js';
import type { TaskMetadata } from '../types.js';

export interface WorktreeCreateInput {
  taskId: string;
  baseBranch?: string;
}

export interface WorktreeListInput {
  // No parameters - lists all task worktrees
}

export interface WorktreeCleanupInput {
  taskId: string;
  force?: boolean;
}

export interface WorktreeMergeInput {
  taskId: string;
  targetBranch?: string;
}

export interface WorktreeConflictStatusInput {
  taskId: string;
}

export interface WorktreeConflictResolveInput {
  taskId: string;
  strategy?: 'ours' | 'theirs' | 'manual';
  targetBranch?: string;
}

export type ConflictType = 'content' | 'rename' | 'delete' | 'add-add' | 'modify-delete';

export interface ConflictDetail {
  file: string;
  type: ConflictType;
  hasConflictMarkers: boolean;
  suggestedStrategy: 'ours' | 'theirs' | 'manual';
}

/**
 * Check conflict status for a task worktree
 *
 * Returns detailed conflict information including type classification,
 * conflict markers detection, and suggested resolution strategies.
 */
export async function worktreeConflictStatus(
  db: DatabaseClient,
  input: WorktreeConflictStatusInput
): Promise<{
  taskId: string;
  hasConflicts: boolean;
  conflicts: ConflictDetail[];
  summary: string;
  suggestedAction: string;
} | null> {
  const task = db.getTask(input.taskId);
  if (!task) return null;

  const metadata = JSON.parse(task.metadata) as TaskMetadata;

  // Check if task uses isolated worktree
  if (!metadata.isolatedWorktree || !metadata.worktreePath) {
    return {
      taskId: input.taskId,
      hasConflicts: false,
      conflicts: [],
      summary: 'Task does not use isolated worktree',
      suggestedAction: 'No action needed'
    };
  }

  const projectRoot = process.cwd();
  const worktreeManager = new WorktreeManager(projectRoot);

  // Get current conflicting files
  const currentConflicts = await worktreeManager.getConflictingFiles();

  if (currentConflicts.length === 0) {
    return {
      taskId: input.taskId,
      hasConflicts: false,
      conflicts: [],
      summary: 'No conflicts detected',
      suggestedAction: 'Ready to merge'
    };
  }

  // Analyze each conflict in detail
  const conflictDetails: ConflictDetail[] = [];

  for (const file of currentConflicts) {
    const detail = await worktreeManager.analyzeConflict(file);
    conflictDetails.push(detail);
  }

  // Generate summary and suggested action
  const contentConflicts = conflictDetails.filter(c => c.type === 'content').length;
  const deleteConflicts = conflictDetails.filter(c => c.type === 'delete' || c.type === 'modify-delete').length;
  const renameConflicts = conflictDetails.filter(c => c.type === 'rename').length;
  const addAddConflicts = conflictDetails.filter(c => c.type === 'add-add').length;

  const summaryParts: string[] = [];
  if (contentConflicts > 0) summaryParts.push(`${contentConflicts} content conflict(s)`);
  if (deleteConflicts > 0) summaryParts.push(`${deleteConflicts} delete conflict(s)`);
  if (renameConflicts > 0) summaryParts.push(`${renameConflicts} rename conflict(s)`);
  if (addAddConflicts > 0) summaryParts.push(`${addAddConflicts} add-add conflict(s)`);

  const summary = summaryParts.join(', ');

  // Determine suggested action
  const manualConflicts = conflictDetails.filter(c => c.suggestedStrategy === 'manual').length;
  let suggestedAction: string;

  if (manualConflicts === 0) {
    suggestedAction = 'All conflicts can be auto-resolved. Use worktree_conflict_resolve with strategy: ours/theirs';
  } else if (manualConflicts === conflictDetails.length) {
    suggestedAction = 'All conflicts require manual resolution. Edit files to remove conflict markers, then use worktree_conflict_resolve';
  } else {
    suggestedAction = `${manualConflicts} conflict(s) require manual resolution. Resolve manually, then use worktree_conflict_resolve`;
  }

  return {
    taskId: input.taskId,
    hasConflicts: true,
    conflicts: conflictDetails,
    summary,
    suggestedAction
  };
}

/**
 * Resolve merge conflicts using specified strategy
 *
 * Supports three resolution strategies:
 * - 'ours': Keep our changes (task branch)
 * - 'theirs': Keep their changes (target branch)
 * - 'manual': Verify conflicts are manually resolved
 *
 * After resolution, validates all conflicts are resolved before completing merge.
 * If successful, updates task status to completed and cleans up worktree.
 */
export async function worktreeConflictResolve(
  db: DatabaseClient,
  input: WorktreeConflictResolveInput
): Promise<{
  success: boolean;
  completed: boolean;
  resolvedFiles: string[];
  message: string;
}> {
  const task = db.getTask(input.taskId);
  if (!task) {
    throw new Error(`Task not found: ${input.taskId}`);
  }

  const metadata = JSON.parse(task.metadata) as TaskMetadata;

  // Check if task uses isolated worktree
  if (!metadata.isolatedWorktree || !metadata.worktreePath) {
    throw new Error(`Task ${input.taskId} does not use isolated worktree`);
  }

  // Check if task is blocked by merge conflicts
  if (task.status !== 'blocked' || !metadata.mergeConflicts) {
    throw new Error(
      `Task ${input.taskId} is not blocked by merge conflicts. Status: ${task.status}`
    );
  }

  const projectRoot = process.cwd();
  const worktreeManager = new WorktreeManager(projectRoot);
  const strategy = input.strategy || 'manual';

  // Get current conflicting files
  const conflictingFiles = await worktreeManager.getConflictingFiles();

  if (conflictingFiles.length === 0) {
    // No conflicts, proceed directly to merge completion
    return await completeMergeAfterResolution(
      db,
      worktreeManager,
      task,
      metadata,
      input.targetBranch,
      []
    );
  }

  // Apply resolution strategy
  const resolvedFiles: string[] = [];

  if (strategy === 'manual') {
    // Verify all conflicts are manually resolved (no conflict markers)
    const stillHasMarkers = await worktreeManager.hasConflictMarkers(conflictingFiles);
    if (stillHasMarkers.length > 0) {
      return {
        success: false,
        completed: false,
        resolvedFiles: [],
        message: `Conflicts still exist in ${stillHasMarkers.length} file(s): ${stillHasMarkers.join(', ')}. Remove conflict markers before resolving.`
      };
    }

    // Mark all files as resolved
    for (const file of conflictingFiles) {
      await worktreeManager.markConflictResolved(file);
      resolvedFiles.push(file);
    }
  } else {
    // Apply automatic resolution strategy (ours/theirs)
    for (const file of conflictingFiles) {
      try {
        await worktreeManager.resolveConflictWithStrategy(file, strategy);
        resolvedFiles.push(file);
      } catch (error: any) {
        return {
          success: false,
          completed: false,
          resolvedFiles,
          message: `Failed to resolve ${file} with strategy '${strategy}': ${error.message}`
        };
      }
    }
  }

  // Verify all conflicts are now resolved
  const remainingConflicts = await worktreeManager.getConflictingFiles();
  if (remainingConflicts.length > 0) {
    return {
      success: false,
      completed: false,
      resolvedFiles,
      message: `Conflicts still exist in ${remainingConflicts.length} file(s): ${remainingConflicts.join(', ')}`
    };
  }

  // All conflicts resolved, complete the merge
  return await completeMergeAfterResolution(
    db,
    worktreeManager,
    task,
    metadata,
    input.targetBranch,
    resolvedFiles
  );
}

/**
 * Complete merge after all conflicts are resolved
 */
async function completeMergeAfterResolution(
  db: DatabaseClient,
  worktreeManager: WorktreeManager,
  task: any,
  metadata: TaskMetadata,
  targetBranch: string | undefined,
  resolvedFiles: string[]
): Promise<{
  success: boolean;
  completed: boolean;
  resolvedFiles: string[];
  message: string;
}> {
  try {
    // Conflicts resolved, retry merge
    const mergeResult = await worktreeManager.mergeTaskWorktree(
      task.id,
      targetBranch
    );

    if (mergeResult.merged) {
      // Merge successful, cleanup worktree
      await worktreeManager.cleanupTaskWorktree(task.id);

      // Update task to completed
      const resolutionNote = resolvedFiles.length > 0
        ? `\n\nConflicts resolved (${resolvedFiles.length} file(s)). Worktree merged and cleaned up: ${mergeResult.message}`
        : `\n\nWorktree merged and cleaned up: ${mergeResult.message}`;

      // Remove conflict metadata
      const updatedMetadata = { ...metadata };
      delete updatedMetadata.mergeConflicts;
      delete updatedMetadata.mergeConflictTimestamp;

      db.updateTask(task.id, {
        status: 'completed',
        blocked_reason: null,
        notes: task.notes ? `${task.notes}${resolutionNote}` : resolutionNote,
        metadata: JSON.stringify(updatedMetadata)
      });

      return {
        success: true,
        completed: true,
        resolvedFiles,
        message: `Merge successful. Resolved ${resolvedFiles.length} file(s). Task completed and worktree cleaned up.`
      };
    } else if (mergeResult.conflicts && mergeResult.conflicts.length > 0) {
      // New conflicts appeared
      return {
        success: false,
        completed: false,
        resolvedFiles,
        message: `New conflicts detected: ${mergeResult.conflicts.join(', ')}`
      };
    } else {
      // Unexpected state
      return {
        success: false,
        completed: false,
        resolvedFiles,
        message: 'Merge failed for unknown reason'
      };
    }
  } catch (error: any) {
    return {
      success: false,
      completed: false,
      resolvedFiles,
      message: `Merge failed: ${error.message}`
    };
  }
}

/**
 * Create a worktree for a task
 *
 * Manually create a worktree for a task. This is useful when:
 * - Task was created without requiresWorktree but needs isolation
 * - Recreating a worktree after cleanup
 */
export async function worktreeCreate(
  db: DatabaseClient,
  input: WorktreeCreateInput
): Promise<{
  taskId: string;
  worktreePath: string;
  branchName: string;
  message: string;
}> {
  const task = db.getTask(input.taskId);
  if (!task) {
    throw new Error(`Task not found: ${input.taskId}`);
  }

  const metadata = JSON.parse(task.metadata) as TaskMetadata;

  // Check if worktree already exists
  if (metadata.worktreePath) {
    return {
      taskId: input.taskId,
      worktreePath: metadata.worktreePath,
      branchName: metadata.branchName || '',
      message: 'Worktree already exists for this task'
    };
  }

  const projectRoot = process.cwd();
  const worktreeManager = new WorktreeManager(projectRoot);

  // Create worktree
  const worktreeInfo = await worktreeManager.createTaskWorktree(
    input.taskId,
    input.baseBranch
  );

  // Update task metadata
  const updatedMetadata = {
    ...metadata,
    isolatedWorktree: true,
    worktreePath: worktreeInfo.path,
    branchName: worktreeInfo.branch
  };

  db.updateTask(input.taskId, {
    metadata: JSON.stringify(updatedMetadata),
    notes: task.notes
      ? `${task.notes}\n\nWorktree created: ${worktreeInfo.path} (branch: ${worktreeInfo.branch})`
      : `Worktree created: ${worktreeInfo.path} (branch: ${worktreeInfo.branch})`
  });

  return {
    taskId: input.taskId,
    worktreePath: worktreeInfo.path,
    branchName: worktreeInfo.branch,
    message: 'Worktree created successfully'
  };
}

/**
 * List all task worktrees
 *
 * Returns information about all worktrees managed by Task Copilot.
 */
export async function worktreeList(
  db: DatabaseClient,
  input: WorktreeListInput
): Promise<{
  worktrees: Array<{
    taskId: string;
    taskTitle?: string;
    taskStatus?: string;
    worktreePath: string;
    branchName: string;
  }>;
  totalCount: number;
}> {
  const projectRoot = process.cwd();
  const worktreeManager = new WorktreeManager(projectRoot);

  // Get all worktrees from git
  const worktrees = await worktreeManager.listTaskWorktrees();

  // Enrich with task information
  const enrichedWorktrees = worktrees.map(wt => {
    const taskId = wt.streamId; // streamId is actually taskId for task worktrees
    const task = db.getTask(taskId);

    return {
      taskId,
      taskTitle: task?.title,
      taskStatus: task?.status,
      worktreePath: wt.path,
      branchName: wt.branch
    };
  });

  return {
    worktrees: enrichedWorktrees,
    totalCount: enrichedWorktrees.length
  };
}

/**
 * Clean up a task worktree
 *
 * Removes the worktree and deletes the associated branch.
 * Use this to manually clean up after task completion or to force cleanup.
 */
export async function worktreeCleanup(
  db: DatabaseClient,
  input: WorktreeCleanupInput
): Promise<{
  taskId: string;
  worktreeRemoved: boolean;
  branchDeleted: boolean;
  message: string;
}> {
  const task = db.getTask(input.taskId);
  if (!task) {
    throw new Error(`Task not found: ${input.taskId}`);
  }

  const metadata = JSON.parse(task.metadata) as TaskMetadata;

  const projectRoot = process.cwd();
  const worktreeManager = new WorktreeManager(projectRoot);

  // Clean up worktree
  const cleanupResult = await worktreeManager.cleanupTaskWorktree(
    input.taskId,
    input.force || false
  );

  // Update task metadata to remove worktree info
  if (cleanupResult.worktreeRemoved) {
    const updatedMetadata = { ...metadata };
    delete updatedMetadata.worktreePath;
    delete updatedMetadata.branchName;
    delete updatedMetadata.isolatedWorktree;

    db.updateTask(input.taskId, {
      metadata: JSON.stringify(updatedMetadata),
      notes: task.notes
        ? `${task.notes}\n\nWorktree cleaned up (removed: ${cleanupResult.worktreeRemoved}, branch deleted: ${cleanupResult.branchDeleted})`
        : `Worktree cleaned up (removed: ${cleanupResult.worktreeRemoved}, branch deleted: ${cleanupResult.branchDeleted})`
    });
  }

  return {
    taskId: input.taskId,
    worktreeRemoved: cleanupResult.worktreeRemoved,
    branchDeleted: cleanupResult.branchDeleted,
    message: cleanupResult.worktreeRemoved
      ? 'Worktree cleaned up successfully'
      : 'No worktree found to clean up'
  };
}

/**
 * Merge a task worktree
 *
 * Merges the task's worktree branch into the target branch.
 * If conflicts occur, task is marked as blocked.
 */
export async function worktreeMerge(
  db: DatabaseClient,
  input: WorktreeMergeInput
): Promise<{
  taskId: string;
  merged: boolean;
  conflicts?: string[];
  message: string;
}> {
  const task = db.getTask(input.taskId);
  if (!task) {
    throw new Error(`Task not found: ${input.taskId}`);
  }

  const metadata = JSON.parse(task.metadata) as TaskMetadata;

  if (!metadata.worktreePath) {
    throw new Error(`Task ${input.taskId} does not have a worktree`);
  }

  const projectRoot = process.cwd();
  const worktreeManager = new WorktreeManager(projectRoot);

  // Attempt merge
  const mergeResult = await worktreeManager.mergeTaskWorktree(
    input.taskId,
    input.targetBranch
  );

  if (mergeResult.merged) {
    // Merge successful
    db.updateTask(input.taskId, {
      notes: task.notes
        ? `${task.notes}\n\nWorktree merged: ${mergeResult.message}`
        : `Worktree merged: ${mergeResult.message}`
    });

    return {
      taskId: input.taskId,
      merged: true,
      message: mergeResult.message
    };
  } else if (mergeResult.conflicts && mergeResult.conflicts.length > 0) {
    // Merge conflicts detected
    const conflictList = mergeResult.conflicts.join(', ');
    const blockedReason = `Merge conflicts detected: ${conflictList}`;

    // Update task to blocked
    db.updateTask(input.taskId, {
      status: 'blocked',
      blocked_reason: blockedReason,
      notes: task.notes
        ? `${task.notes}\n\nMerge conflicts in ${mergeResult.conflicts.length} file(s):\n${mergeResult.conflicts.map(f => `- ${f}`).join('\n')}`
        : `Merge conflicts in ${mergeResult.conflicts.length} file(s):\n${mergeResult.conflicts.map(f => `- ${f}`).join('\n')}`,
      metadata: JSON.stringify({
        ...metadata,
        mergeConflicts: mergeResult.conflicts,
        mergeConflictTimestamp: new Date().toISOString()
      })
    });

    return {
      taskId: input.taskId,
      merged: false,
      conflicts: mergeResult.conflicts,
      message: mergeResult.message
    };
  } else {
    // Unexpected state
    return {
      taskId: input.taskId,
      merged: false,
      message: 'Merge failed for unknown reason'
    };
  }
}
