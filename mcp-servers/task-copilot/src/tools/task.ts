/**
 * Task tool implementations
 */

import { v4 as uuidv4 } from 'uuid';
import type { DatabaseClient } from '../database.js';
import type {
  TaskCreateInput,
  TaskUpdateInput,
  TaskGetInput,
  TaskListInput,
  TaskRow,
  TaskStatus,
  TaskMetadata,
  PerformanceRow,
  PerformanceOutcome,
  CheckpointTrigger,
} from '../types.js';
import { validateStreamDependencies } from './stream.js';
import { detectActivationMode, isValidActivationMode } from '../utils/mode-detection.js';
import { executeQualityGates, shouldEnforceQualityGates } from './quality-gates.js';
import { requiresVerification, validateTaskCompletion } from '../validation/verification-rules.js';
import { validateActivationMode, shouldValidateActivationMode } from '../validation/activation-mode-rules.js';
import { WorktreeManager } from '../utils/worktree-manager.js';
import { eventBus } from '../events/event-bus.js';
import type { TaskChange } from '../events/types.js';

export async function taskCreate(
  db: DatabaseClient,
  input: TaskCreateInput
): Promise<{ id: string; prdId?: string; parentId?: string; status: TaskStatus; createdAt: string }> {
  const now = new Date().toISOString();
  const id = `TASK-${uuidv4()}`;

  // Check scope lock if creating task under a PRD
  if (input.prdId) {
    const prd = db.getPrd(input.prdId);
    if (prd) {
      const prdMetadata = JSON.parse(prd.metadata);
      if (prdMetadata.scopeLocked === true) {
        // Scope is locked - only @agent-ta can create tasks
        const assignedAgent = input.assignedAgent;
        if (assignedAgent !== 'ta') {
          throw new Error(
            `Scope is locked for PRD ${input.prdId}. Only @agent-ta can create tasks. ` +
            `Use scope_change_request to request scope changes.`
          );
        }
      }
    }
  }

  const metadata = input.metadata || {};

  // Auto-detect activation mode if not explicitly provided
  // Explicit override takes precedence over auto-detection
  if (metadata.activationMode === undefined) {
    const detectedMode = detectActivationMode(input.title, input.description || undefined);
    if (detectedMode) {
      metadata.activationMode = detectedMode;
    } else {
      metadata.activationMode = null;
    }
  } else if (metadata.activationMode !== null && !isValidActivationMode(metadata.activationMode as string)) {
    // Validate explicit mode if provided
    throw new Error(`Invalid activationMode: "${metadata.activationMode}". Must be one of: ultrawork, analyze, quick, thorough, or null`);
  }

  // Default verificationRequired to true for complex tasks
  // Only auto-set if not explicitly provided
  if (metadata.verificationRequired === undefined) {
    const complexity = metadata.complexity;
    if (complexity === 'High' || complexity === 'Very High') {
      metadata.verificationRequired = true;
    }
  }

  // Validate stream dependencies if streamId and streamDependencies are provided
  if (metadata.streamId && metadata.streamDependencies && Array.isArray(metadata.streamDependencies)) {
    const typedMetadata = metadata as TaskMetadata;

    // Build map of existing stream dependencies
    const allStreams = new Map<string, string[]>();

    // Query existing tasks with stream metadata
    const sql = `
      SELECT metadata
      FROM tasks
      WHERE json_extract(metadata, '$.streamId') IS NOT NULL
    `;
    const existingTasks = db.getDb().prepare(sql).all() as Array<{ metadata: string }>;

    for (const taskRow of existingTasks) {
      const taskMeta = JSON.parse(taskRow.metadata) as TaskMetadata;
      if (taskMeta.streamId) {
        allStreams.set(taskMeta.streamId, taskMeta.streamDependencies || []);
      }
    }

    // Validate the new task's dependencies
    // Use metadata.streamId directly (already narrowed by the if check above)
    const error = validateStreamDependencies(
      metadata.streamId as string,
      metadata.streamDependencies as string[],
      allStreams
    );

    if (error) {
      throw new Error(error);
    }
  }

  const task: TaskRow = {
    id,
    prd_id: input.prdId || null,
    parent_id: input.parentId || null,
    title: input.title,
    description: input.description || null,
    assigned_agent: input.assignedAgent || null,
    status: 'pending',
    blocked_reason: null,
    notes: null,
    metadata: JSON.stringify(metadata),
    created_at: now,
    updated_at: now,
    archived: 0,
    archived_at: null,
    archived_by_initiative_id: null
  };

  db.insertTask(task);

  // Log activity (need initiative ID - get from PRD or parent)
  let initiativeId: string | undefined;
  if (input.prdId) {
    const prd = db.getPrd(input.prdId);
    if (prd) initiativeId = prd.initiative_id;
  } else if (input.parentId) {
    const parent = db.getTask(input.parentId);
    if (parent?.prd_id) {
      const prd = db.getPrd(parent.prd_id);
      if (prd) initiativeId = prd.initiative_id;
    }
  }

  if (initiativeId) {
    db.insertActivity({
      id: uuidv4(),
      initiative_id: initiativeId,
      type: 'task_created',
      entity_id: id,
      entity_type: 'task',
      summary: `Created task: ${input.title}`,
      metadata: JSON.stringify({
        taskId: id,
        prdId: input.prdId,
        parentId: input.parentId,
        assignedAgent: input.assignedAgent,
        activationMode: metadata.activationMode
      }),
      created_at: now
    });
  }

  // Validate activation mode constraints on parent task (if this is a subtask)
  let activationModeWarning: string | undefined;
  if (input.parentId) {
    const parentTask = db.getTask(input.parentId);
    if (parentTask && shouldValidateActivationMode(parentTask)) {
      const validationResult = validateActivationMode(db, parentTask);
      if (validationResult.warnings.length > 0) {
        activationModeWarning = validationResult.actionableFeedback;
      }
    }
  }

  // Emit task created event
  eventBus.emitTaskCreated(id, {
    taskId: id,
    taskTitle: input.title,
    assignedAgent: input.assignedAgent,
    streamId: metadata.streamId as string | undefined,
    createdAt: now,
  });

  return {
    id,
    prdId: input.prdId,
    parentId: input.parentId,
    status: 'pending',
    createdAt: now,
    ...(activationModeWarning && { activationModeWarning })
  };
}

export async function taskUpdate(
  db: DatabaseClient,
  input: TaskUpdateInput
): Promise<{
  id: string;
  status: TaskStatus;
  updatedAt: string;
  autoCommitRequested?: boolean;
  suggestedCommitMessage?: string;
} | null> {
  const task = db.getTask(input.id);
  if (!task) return null;

  // Block updates to archived tasks
  if (task.archived === 1) {
    const metadata = JSON.parse(task.metadata) as TaskMetadata;
    throw new Error(
      `Cannot update archived task ${input.id}. ` +
      `This task belongs to stream "${metadata.streamId || 'unknown'}" which was archived ` +
      `when switching to initiative ${task.archived_by_initiative_id}. ` +
      `Use stream_unarchive to restore the stream first.`
    );
  }

  const now = new Date().toISOString();
  const updates: Partial<TaskRow> = {
    updated_at: now
  };

  if (input.status !== undefined) {
    updates.status = input.status;
  }
  if (input.assignedAgent !== undefined) {
    updates.assigned_agent = input.assignedAgent;
  }
  if (input.notes !== undefined) {
    updates.notes = input.notes;
  }
  if (input.blockedReason !== undefined) {
    updates.blocked_reason = input.blockedReason;
  }
  if (input.metadata !== undefined) {
    const existingMetadata = JSON.parse(task.metadata);
    const mergedMetadata = { ...existingMetadata, ...input.metadata };
    updates.metadata = JSON.stringify(mergedMetadata);
  }

  // Validate activation mode if mode was updated
  let activationModeWarning: string | undefined;
  if (input.metadata?.activationMode !== undefined) {
    // Create a temporary updated task for validation
    const tempTask: TaskRow = {
      ...task,
      metadata: updates.metadata || task.metadata
    };

    if (shouldValidateActivationMode(tempTask)) {
      const validationResult = validateActivationMode(db, tempTask);
      if (validationResult.warnings.length > 0) {
        activationModeWarning = validationResult.actionableFeedback;
      }
    }
  }

  // Check verification requirements before allowing completion
  if (input.status === 'completed' && requiresVerification(task)) {
    // Create a temporary updated task for validation that includes pending updates
    const tempTask: TaskRow = {
      ...task,
      notes: updates.notes !== undefined ? updates.notes : task.notes,
      blocked_reason: updates.blocked_reason !== undefined ? updates.blocked_reason : task.blocked_reason,
      metadata: updates.metadata || task.metadata
    };

    const verificationResult = validateTaskCompletion(db, tempTask);

    if (!verificationResult.allowed) {
      // Verification failed - block completion
      throw new Error(
        verificationResult.actionableFeedback ||
        'Task cannot be completed: verification requirements not met'
      );
    }
  }

  // Check quality gates before allowing completion
  if (shouldEnforceQualityGates(task, input.status)) {
    const projectRoot = process.cwd();
    const gateReport = await executeQualityGates(db, task, projectRoot);

    if (!gateReport.allPassed) {
      // Quality gates failed - block completion
      const failedGates = gateReport.results
        .filter(r => !r.passed)
        .map(r => r.gateName)
        .join(', ');

      const blockedReason = `Quality gates failed: ${failedGates}. ${gateReport.failedGates} of ${gateReport.totalGates} gates failed.`;

      // Update to blocked instead of completed
      updates.status = 'blocked';
      updates.blocked_reason = blockedReason;

      // Add gate failure details to notes
      const gateDetails = gateReport.results
        .filter(r => !r.passed)
        .map(r => `- ${r.gateName}: ${r.message}`)
        .join('\n');

      updates.notes = task.notes
        ? `${task.notes}\n\nQuality Gate Failures:\n${gateDetails}`
        : `Quality Gate Failures:\n${gateDetails}`;
    }
  }

  // Track agent reassignment before update (for performance tracking)
  const previousAgent = task.assigned_agent;
  const isReassignment = input.assignedAgent !== undefined &&
    input.assignedAgent !== previousAgent &&
    previousAgent !== null;

  db.updateTask(input.id, updates);

  // Get updated task for event emission
  const updatedTask = db.getTask(input.id);
  const updatedMetadata = updatedTask ? JSON.parse(updatedTask.metadata) as TaskMetadata : undefined;

  // Calculate changes for event
  const changes: TaskChange[] = [];
  if (input.status !== undefined && input.status !== task.status) {
    changes.push({ field: 'status', oldValue: task.status, newValue: input.status });
  }
  if (input.assignedAgent !== undefined && input.assignedAgent !== task.assigned_agent) {
    changes.push({ field: 'assignedAgent', oldValue: task.assigned_agent, newValue: input.assignedAgent });
  }
  if (input.notes !== undefined && input.notes !== task.notes) {
    changes.push({ field: 'notes', oldValue: task.notes, newValue: input.notes });
  }
  if (input.blockedReason !== undefined && input.blockedReason !== task.blocked_reason) {
    changes.push({ field: 'blockedReason', oldValue: task.blocked_reason, newValue: input.blockedReason });
  }

  // Emit task updated event
  eventBus.emitTaskUpdated(input.id, {
    taskId: input.id,
    taskTitle: task.title,
    status: (input.status || task.status) as TaskStatus,
    assignedAgent: input.assignedAgent || task.assigned_agent || undefined,
    streamId: updatedMetadata?.streamId,
    changes,
    updatedAt: now,
  });

  // Record performance on agent reassignment
  if (isReassignment && previousAgent) {
    recordPerformance(db, task, 'reassigned', now);
  }

  // Handle status changes
  if (input.status && input.status !== task.status) {
    // Emit status changed event
    eventBus.emitTaskStatusChanged(input.id, {
      taskId: input.id,
      taskTitle: task.title,
      oldStatus: task.status as TaskStatus,
      newStatus: input.status,
      statusChangedAt: now,
    });

    // Emit specific status events
    if (input.status === 'blocked') {
      eventBus.emitTaskBlocked(input.id, {
        taskId: input.id,
        taskTitle: task.title,
        blockedReason: input.blockedReason || 'Unknown',
        blockedAt: now,
      });
    } else if (input.status === 'completed') {
      eventBus.emitTaskCompleted(input.id, {
        taskId: input.id,
        taskTitle: task.title,
        completedAt: now,
      });
    }

    // Log activity
    if (task.prd_id) {
      const prd = db.getPrd(task.prd_id);
      if (prd) {
        const eventType = input.status === 'completed' ? 'task_completed' : 'task_updated';
        db.insertActivity({
          id: uuidv4(),
          initiative_id: prd.initiative_id,
          type: eventType,
          entity_id: input.id,
          entity_type: 'task',
          summary: `Task ${task.title}: ${task.status} → ${input.status}`,
          metadata: JSON.stringify({
            taskId: input.id,
            previousStatus: task.status,
            newStatus: input.status,
            assignedAgent: task.assigned_agent,
            blockedReason: input.blockedReason
          }),
          created_at: now
        });
      }
    }

    // Track agent activity
    const taskMetadata = JSON.parse(updates.metadata || task.metadata) as TaskMetadata;
    const assignedAgent = updates.assigned_agent || task.assigned_agent;

    if (input.status === 'in_progress' && assignedAgent) {
      // Start tracking activity when task goes in_progress
      const streamId = taskMetadata.streamId || 'default';
      db.upsertAgentActivity({
        stream_id: streamId,
        agent_id: assignedAgent,
        task_id: input.id,
        activity_description: task.title,
        phase: taskMetadata.phase
      });
    } else if (input.status === 'completed') {
      // Mark activity as complete
      db.completeAgentActivity(input.id);
    }

    // Handle worktree lifecycle on status transitions
    const metadata = JSON.parse(updates.metadata || task.metadata) as TaskMetadata;
    if (metadata.isolatedWorktree) {
      await handleWorktreeLifecycle(db, task, input.id, input.status, metadata);
    }

    // Record performance based on status transition
    if (input.status === 'completed' && task.assigned_agent) {
      recordPerformance(db, task, 'success', now);
    } else if (input.status === 'blocked' && task.assigned_agent) {
      recordPerformance(db, task, 'blocked', now);
    } else if (input.status === 'cancelled' && task.assigned_agent) {
      recordPerformance(db, task, 'failure', now);
    }

    // Auto-checkpoint on status transitions to in_progress or blocked
    if (input.status === 'in_progress' || input.status === 'blocked') {
      createAutoCheckpoint(db, task, input.status === 'blocked' ? input.blockedReason : undefined, now);
    }

    // Recalculate and emit stream progress if task is in a stream
    if (updatedMetadata?.streamId) {
      emitStreamProgressIfNeeded(db, updatedMetadata.streamId);
    }
  }

  // Check if auto-commit is requested on completion
  let autoCommitRequested = false;
  let suggestedCommitMessage: string | undefined;

  if (input.status === 'completed' && task.status !== 'completed') {
    // Task is transitioning TO completed (not already completed)
    const updatedMetadata = JSON.parse(updates.metadata || task.metadata) as TaskMetadata;

    // Check if autoCommitOnComplete is enabled
    if (updatedMetadata.autoCommitOnComplete === true) {
      autoCommitRequested = true;
      suggestedCommitMessage = `feat(${input.id}): ${task.title}`;
    }
  }

  return {
    id: input.id,
    status: (input.status || task.status) as TaskStatus,
    updatedAt: now,
    ...(activationModeWarning && { activationModeWarning }),
    ...(autoCommitRequested && {
      autoCommitRequested,
      suggestedCommitMessage
    })
  };
}

/**
 * Record agent performance for a task
 */
function recordPerformance(
  db: DatabaseClient,
  task: TaskRow,
  outcome: PerformanceOutcome,
  timestamp: string
): void {
  if (!task.assigned_agent) return;

  // Extract work product type from task metadata or infer from work products
  const metadata = JSON.parse(task.metadata);
  let workProductType: string | null = metadata.workProductType || null;

  // If not specified, check if task has work products and use the most recent type
  if (!workProductType) {
    const workProducts = db.listWorkProducts(task.id);
    if (workProducts.length > 0) {
      workProductType = workProducts[0].type;
    }
  }

  const perf: PerformanceRow = {
    id: uuidv4(),
    agent_id: task.assigned_agent,
    task_id: task.id,
    work_product_type: workProductType,
    complexity: metadata.complexity || null,
    outcome,
    duration_ms: null, // Could calculate from timestamps if needed
    created_at: timestamp
  };

  db.insertPerformance(perf);
}

/**
 * Create an automatic checkpoint for a task
 */
function createAutoCheckpoint(
  db: DatabaseClient,
  task: TaskRow,
  blockedReason: string | undefined,
  timestamp: string
): void {
  const MAX_CHECKPOINTS = 5;
  const DEFAULT_EXPIRY_HOURS = 24;

  // Get next sequence number
  const sequence = db.getNextCheckpointSequence(task.id);

  // Calculate expiry
  const expiresAt = new Date(Date.now() + DEFAULT_EXPIRY_HOURS * 60 * 60 * 1000).toISOString();

  // Get subtask states
  const subtasks = db.listTasks({ parentId: task.id });
  const subtaskStates = subtasks.map(st => ({
    id: st.id,
    status: st.status
  }));

  // Determine trigger type
  const trigger: CheckpointTrigger = 'auto_status';

  db.insertCheckpoint({
    id: `CP-${uuidv4()}`,
    task_id: task.id,
    sequence,
    trigger,
    task_status: task.status,
    task_notes: task.notes,
    task_metadata: task.metadata,
    blocked_reason: blockedReason || task.blocked_reason,
    assigned_agent: task.assigned_agent,
    execution_phase: null,
    execution_step: null,
    agent_context: null,
    draft_content: null,
    draft_type: null,
    subtask_states: JSON.stringify(subtaskStates),
    created_at: timestamp,
    expires_at: expiresAt,
    // Ralph Wiggum Iteration Support (v4)
    iteration_config: null,
    iteration_number: 0,
    iteration_history: '[]',
    completion_promises: '[]',
    validation_state: null
  });

  // Prune old checkpoints if exceeding max
  const count = db.getCheckpointCount(task.id);
  if (count > MAX_CHECKPOINTS) {
    db.deleteOldestCheckpoints(task.id, count - MAX_CHECKPOINTS);
  }
}

/**
 * Handle worktree lifecycle on task status transitions
 *
 * - On transition to in_progress: create worktree
 * - On transition to completed: merge and cleanup worktree
 */
async function handleWorktreeLifecycle(
  db: DatabaseClient,
  task: TaskRow,
  taskId: string,
  newStatus: TaskStatus,
  metadata: TaskMetadata
): Promise<void> {
  const projectRoot = process.cwd();
  const worktreeManager = new WorktreeManager(projectRoot);

  try {
    // Create worktree on transition to in_progress
    if (newStatus === 'in_progress' && !metadata.worktreePath) {
      const worktreeInfo = await worktreeManager.createTaskWorktree(taskId);

      // Update task metadata with worktree info
      const updatedMetadata = {
        ...metadata,
        worktreePath: worktreeInfo.path,
        branchName: worktreeInfo.branch
      };

      db.updateTask(taskId, {
        metadata: JSON.stringify(updatedMetadata),
        notes: task.notes
          ? `${task.notes}\n\nWorktree created: ${worktreeInfo.path} (branch: ${worktreeInfo.branch})`
          : `Worktree created: ${worktreeInfo.path} (branch: ${worktreeInfo.branch})`
      });
    }

    // Merge and cleanup on completion
    if (newStatus === 'completed' && metadata.worktreePath) {
      // Attempt to merge the worktree branch
      const mergeResult = await worktreeManager.mergeTaskWorktree(taskId);

      if (mergeResult.merged) {
        // Merge successful, cleanup worktree
        const cleanupResult = await worktreeManager.cleanupTaskWorktree(taskId);

        const cleanupNote = `\n\nWorktree merged and cleaned up: ${mergeResult.message}`;
        db.updateTask(taskId, {
          notes: task.notes ? `${task.notes}${cleanupNote}` : cleanupNote
        });
      } else if (mergeResult.conflicts && mergeResult.conflicts.length > 0) {
        // Merge conflicts detected - block completion
        const conflictList = mergeResult.conflicts.join(', ');
        const blockedReason = `Merge conflicts detected: ${conflictList}. Manual resolution required.`;

        // Update task to blocked with conflict info
        db.updateTask(taskId, {
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
      }
    }
  } catch (error: any) {
    // Log error to task notes but don't fail the status transition
    const errorNote = `\n\nWorktree operation failed: ${error.message}`;
    db.updateTask(taskId, {
      notes: task.notes ? `${task.notes}${errorNote}` : errorNote
    });
  }
}

export function taskGet(
  db: DatabaseClient,
  input: TaskGetInput
): any | null {
  const task = db.getTask(input.id);
  if (!task) return null;

  const result: any = {
    id: task.id,
    prdId: task.prd_id || undefined,
    parentId: task.parent_id || undefined,
    title: task.title,
    description: task.description || undefined,
    assignedAgent: task.assigned_agent || undefined,
    status: task.status,
    blockedReason: task.blocked_reason || undefined,
    notes: task.notes || undefined,
    metadata: JSON.parse(task.metadata),
    createdAt: task.created_at,
    updatedAt: task.updated_at
  };

  if (input.includeSubtasks) {
    const subtasks = db.listTasks({ parentId: task.id });
    result.subtasks = subtasks.map(st => ({
      id: st.id,
      title: st.title,
      status: st.status,
      assignedAgent: st.assigned_agent || undefined
    }));
  }

  if (input.includeWorkProducts) {
    const workProducts = db.listWorkProducts(task.id);
    result.workProducts = workProducts.map(wp => ({
      id: wp.id,
      type: wp.type,
      title: wp.title,
      createdAt: wp.created_at
    }));
  }

  return result;
}

export function taskList(
  db: DatabaseClient,
  input: TaskListInput
): Array<{
  id: string;
  title: string;
  status: TaskStatus;
  assignedAgent?: string;
  subtaskCount: number;
  completedSubtasks: number;
  hasWorkProducts: boolean;
}> {
  const tasks = db.listTasks({
    prdId: input.prdId,
    parentId: input.parentId,
    status: input.status,
    assignedAgent: input.assignedAgent
  });

  return tasks.map(task => {
    const subtaskCounts = db.getTaskSubtaskCount(task.id);
    const hasWorkProducts = db.hasWorkProducts(task.id);

    return {
      id: task.id,
      title: task.title,
      status: task.status as TaskStatus,
      assignedAgent: task.assigned_agent || undefined,
      subtaskCount: subtaskCounts.total,
      completedSubtasks: subtaskCounts.completed,
      hasWorkProducts
    };
  });
}

/**
 * Helper function to recalculate and emit stream progress event
 */
function emitStreamProgressIfNeeded(db: DatabaseClient, streamId: string | undefined): void {
  if (!streamId) return;

  // Get all tasks for this stream
  const sql = `
    SELECT id, status, metadata
    FROM tasks
    WHERE json_extract(metadata, '$.streamId') = ?
      AND archived = 0
  `;
  const streamTasks = db.getDb().prepare(sql).all(streamId) as Array<{
    id: string;
    status: TaskStatus;
    metadata: string;
  }>;

  if (streamTasks.length === 0) return;

  // Calculate stream progress
  const totalTasks = streamTasks.length;
  const completedTasks = streamTasks.filter(t => t.status === 'completed').length;
  const inProgressTasks = streamTasks.filter(t => t.status === 'in_progress').length;
  const blockedTasks = streamTasks.filter(t => t.status === 'blocked').length;
  const progressPercentage = totalTasks > 0 ? (completedTasks / totalTasks) * 100 : 0;

  // Get stream name from first task
  const firstTaskMetadata = JSON.parse(streamTasks[0].metadata) as TaskMetadata;
  const streamName = firstTaskMetadata.streamName || streamId;

  // Emit stream progress event
  eventBus.emitStreamProgress(streamId, {
    streamId,
    streamName,
    totalTasks,
    completedTasks,
    inProgressTasks,
    blockedTasks,
    progressPercentage,
    lastUpdated: new Date().toISOString(),
  });

  // Check if stream is completed
  if (completedTasks === totalTasks && totalTasks > 0) {
    eventBus.emitStreamCompleted(streamId, {
      streamId,
      streamName,
      totalTasks,
      completedAt: new Date().toISOString(),
      duration: 0, // Could calculate if we tracked stream start time
    });
  }

  // Check if stream is blocked
  if (blockedTasks > 0) {
    const blockedTaskIds = streamTasks
      .filter(t => t.status === 'blocked')
      .map(t => t.id);

    eventBus.emitStreamBlocked(streamId, {
      streamId,
      streamName,
      blockedReason: `${blockedTasks} task(s) blocked`,
      blockedTaskIds,
    });
  }
}
