/**
 * Checkpoint tool implementations
 *
 * Provides mid-task recovery capabilities through checkpoint snapshots.
 */

import { v4 as uuidv4 } from 'uuid';
import type { DatabaseClient } from '../database.js';
import type {
  CheckpointCreateInput,
  CheckpointCreateOutput,
  CheckpointGetInput,
  CheckpointGetOutput,
  CheckpointResumeInput,
  CheckpointResumeOutput,
  CheckpointListInput,
  CheckpointListOutput,
  CheckpointCleanupInput,
  CheckpointCleanupOutput,
  CheckpointTrigger,
  TaskStatus,
  WorkProductType,
} from '../types.js';

const MAX_CHECKPOINTS_PER_TASK = 5;
const DEFAULT_EXPIRY_MINUTES = 24 * 60; // 24 hours
const MANUAL_EXPIRY_MINUTES = 7 * 24 * 60; // 7 days

/**
 * Create a checkpoint for a task
 */
export function checkpointCreate(
  db: DatabaseClient,
  input: CheckpointCreateInput
): CheckpointCreateOutput {
  const task = db.getTask(input.taskId);
  if (!task) {
    throw new Error(`Task not found: ${input.taskId}`);
  }

  const now = new Date().toISOString();
  const id = `CP-${uuidv4()}`;
  const sequence = db.getNextCheckpointSequence(input.taskId);
  const trigger: CheckpointTrigger = input.trigger || 'manual';

  // Calculate expiry (manual checkpoints live longer)
  const expiryMinutes = input.expiresIn ||
    (trigger === 'manual' ? MANUAL_EXPIRY_MINUTES : DEFAULT_EXPIRY_MINUTES);
  const expiresAt = new Date(Date.now() + expiryMinutes * 60 * 1000).toISOString();

  // Merge pause metadata into agent context if provided
  let agentContext = input.agentContext || {};
  if (input.pauseMetadata) {
    agentContext = {
      ...agentContext,
      pauseReason: input.pauseMetadata.pauseReason,
      pausedBy: input.pauseMetadata.pausedBy,
      nextSteps: input.pauseMetadata.nextSteps,
      blockers: input.pauseMetadata.blockers,
      keyFiles: input.pauseMetadata.keyFiles,
      estimatedResumeTime: input.pauseMetadata.estimatedResumeTime,
      pausedAt: now
    };
  }

  // Get subtask states
  const subtasks = db.listTasks({ parentId: input.taskId });
  const subtaskStates = subtasks.map(st => ({
    id: st.id,
    status: st.status
  }));

  // Truncate draft content if too large (max 50KB)
  const MAX_DRAFT_SIZE = 50 * 1024;
  let draftContent = input.draftContent || null;
  if (draftContent && draftContent.length > MAX_DRAFT_SIZE) {
    draftContent = draftContent.substring(0, MAX_DRAFT_SIZE) + '\n\n[TRUNCATED]';
  }

  db.insertCheckpoint({
    id,
    task_id: input.taskId,
    sequence,
    trigger,
    task_status: task.status,
    task_notes: task.notes,
    task_metadata: task.metadata,
    blocked_reason: task.blocked_reason,
    assigned_agent: task.assigned_agent,
    execution_phase: input.executionPhase || null,
    execution_step: input.executionStep || null,
    agent_context: agentContext ? JSON.stringify(agentContext) : null,
    draft_content: draftContent,
    draft_type: input.draftType || null,
    subtask_states: JSON.stringify(subtaskStates),
    created_at: now,
    expires_at: expiresAt,
    // Ralph Wiggum iteration fields
    iteration_config: input.iterationConfig ? JSON.stringify(input.iterationConfig) : null,
    iteration_number: input.iterationNumber ?? 0,
    iteration_history: '[]',
    completion_promises: '[]',
    validation_state: null
  });

  // Prune old checkpoints if exceeding max
  const count = db.getCheckpointCount(input.taskId);
  if (count > MAX_CHECKPOINTS_PER_TASK) {
    db.deleteOldestCheckpoints(input.taskId, count - MAX_CHECKPOINTS_PER_TASK);
  }

  return {
    id,
    taskId: input.taskId,
    sequence,
    trigger,
    createdAt: now,
    expiresAt
  };
}

/**
 * Get a specific checkpoint by ID
 */
export function checkpointGet(
  db: DatabaseClient,
  input: CheckpointGetInput
): CheckpointGetOutput | null {
  const checkpoint = db.getCheckpoint(input.id);
  if (!checkpoint) {
    return null;
  }

  // Get the associated task
  const task = db.getTask(checkpoint.task_id);
  if (!task) {
    throw new Error(`Task not found for checkpoint: ${checkpoint.task_id}`);
  }

  // Parse stored JSON fields
  const agentContext = checkpoint.agent_context
    ? JSON.parse(checkpoint.agent_context)
    : null;
  const taskMetadata = JSON.parse(checkpoint.task_metadata);
  const subtaskStates = JSON.parse(checkpoint.subtask_states) as Array<{ id: string; status: string }>;

  return {
    id: checkpoint.id,
    taskId: checkpoint.task_id,
    taskTitle: task.title,
    sequence: checkpoint.sequence,
    trigger: checkpoint.trigger as CheckpointTrigger,
    taskStatus: checkpoint.task_status as TaskStatus,
    taskNotes: checkpoint.task_notes,
    taskMetadata,
    blockedReason: checkpoint.blocked_reason,
    assignedAgent: checkpoint.assigned_agent,
    executionPhase: checkpoint.execution_phase,
    executionStep: checkpoint.execution_step,
    agentContext,
    draftContent: checkpoint.draft_content,
    draftType: checkpoint.draft_type as WorkProductType | null,
    subtaskStates,
    createdAt: checkpoint.created_at,
    expiresAt: checkpoint.expires_at
  };
}

/**
 * Resume a task from a checkpoint
 */
export function checkpointResume(
  db: DatabaseClient,
  input: CheckpointResumeInput
): CheckpointResumeOutput | null {
  const task = db.getTask(input.taskId);
  if (!task) {
    throw new Error(`Task not found: ${input.taskId}`);
  }

  // Get checkpoint (specific or latest)
  const checkpoint = input.checkpointId
    ? db.getCheckpoint(input.checkpointId)
    : db.getLatestCheckpoint(input.taskId);

  if (!checkpoint) {
    return null;
  }

  // Check if checkpoint has expired
  if (checkpoint.expires_at && new Date(checkpoint.expires_at) < new Date()) {
    return null;
  }

  // Parse stored JSON fields
  const agentContext = checkpoint.agent_context
    ? JSON.parse(checkpoint.agent_context)
    : null;
  const subtaskStates = JSON.parse(checkpoint.subtask_states) as Array<{ id: string; status: string }>;

  // Parse Ralph Wiggum iteration fields
  const iterationConfig = checkpoint.iteration_config
    ? JSON.parse(checkpoint.iteration_config)
    : null;
  const iterationHistory = JSON.parse(checkpoint.iteration_history) as Array<{
    iteration: number;
    timestamp: string;
    validationResult: {
      passed: boolean;
      flags: Array<{
        ruleId: string;
        message: string;
        severity: string;
      }>;
    };
    checkpointId: string;
  }>;
  const completionPromises = JSON.parse(checkpoint.completion_promises) as string[];
  const validationState = checkpoint.validation_state
    ? JSON.parse(checkpoint.validation_state)
    : null;

  // Calculate subtask summary
  const subtaskSummary = {
    total: subtaskStates.length,
    completed: subtaskStates.filter(s => s.status === 'completed').length,
    pending: subtaskStates.filter(s => s.status === 'pending').length,
    blocked: subtaskStates.filter(s => s.status === 'blocked').length
  };

  // Generate resume instructions
  const resumeInstructions = generateResumeInstructions(task, checkpoint);

  // Extract pause metadata if present
  let pauseMetadata: CheckpointResumeOutput['pauseMetadata'];
  if (agentContext && (agentContext.pausedBy || agentContext.pauseReason)) {
    pauseMetadata = {
      pauseReason: agentContext.pauseReason as string | undefined,
      pausedBy: agentContext.pausedBy as 'user' | 'system' | undefined,
      nextSteps: agentContext.nextSteps as string | undefined,
      blockers: agentContext.blockers as string[] | undefined,
      keyFiles: agentContext.keyFiles as string[] | undefined,
      estimatedResumeTime: agentContext.estimatedResumeTime as string | undefined
    };
  }

  return {
    taskId: input.taskId,
    taskTitle: task.title,
    checkpointId: checkpoint.id,
    checkpointCreatedAt: checkpoint.created_at,
    restoredStatus: checkpoint.task_status as TaskStatus,
    restoredPhase: checkpoint.execution_phase,
    restoredStep: checkpoint.execution_step,
    agentContext,
    hasDraft: !!checkpoint.draft_content,
    draftType: checkpoint.draft_type as WorkProductType | null,
    draftPreview: checkpoint.draft_content
      ? checkpoint.draft_content.substring(0, 200) + (checkpoint.draft_content.length > 200 ? '...' : '')
      : null,
    subtaskSummary,
    resumeInstructions,
    // Ralph Wiggum iteration state
    iterationConfig,
    iterationNumber: checkpoint.iteration_number,
    iterationHistory,
    completionPromises,
    validationState,
    // Pause metadata (if checkpoint was from /pause)
    pauseMetadata
  };
}

/**
 * List checkpoints for a task
 */
export function checkpointList(
  db: DatabaseClient,
  input: CheckpointListInput
): CheckpointListOutput {
  const checkpoints = db.listCheckpoints(
    input.taskId,
    input.limit || 5,
    input.iterationNumber,
    input.hasIteration
  );

  return {
    taskId: input.taskId,
    checkpoints: checkpoints.map(cp => ({
      id: cp.id,
      sequence: cp.sequence,
      trigger: cp.trigger as CheckpointTrigger,
      phase: cp.execution_phase,
      step: cp.execution_step,
      hasDraft: !!cp.draft_content,
      createdAt: cp.created_at,
      expiresAt: cp.expires_at
    }))
  };
}

/**
 * Clean up old or expired checkpoints
 */
export function checkpointCleanup(
  db: DatabaseClient,
  input: CheckpointCleanupInput
): CheckpointCleanupOutput {
  let deletedCount = 0;

  // Delete expired checkpoints first
  deletedCount += db.deleteExpiredCheckpoints();

  // If olderThan specified, delete checkpoints older than that
  if (input.olderThan) {
    deletedCount += db.deleteCheckpointsOlderThan(input.olderThan, input.taskId);
  }

  // If keepLatest specified for a specific task, prune excess
  if (input.taskId && input.keepLatest) {
    const count = db.getCheckpointCount(input.taskId);
    if (count > input.keepLatest) {
      deletedCount += db.deleteOldestCheckpoints(input.taskId, count - input.keepLatest);
    }
  }

  const remainingCount = db.getTotalCheckpointCount();

  return {
    deletedCount,
    remainingCount
  };
}

/**
 * Generate human-readable resume instructions
 */
function generateResumeInstructions(
  task: { title: string; status: string; assigned_agent: string | null },
  checkpoint: {
    execution_phase: string | null;
    execution_step: number | null;
    draft_content: string | null;
    draft_type: string | null;
    blocked_reason: string | null;
  }
): string {
  const lines: string[] = [];

  lines.push(`Resuming task: "${task.title}"`);

  if (checkpoint.execution_phase) {
    lines.push(`Phase: ${checkpoint.execution_phase}`);
    if (checkpoint.execution_step) {
      lines.push(`Step: ${checkpoint.execution_step}`);
    }
  }

  if (checkpoint.blocked_reason) {
    lines.push(`Previously blocked: ${checkpoint.blocked_reason}`);
  }

  if (checkpoint.draft_content) {
    lines.push(`Draft ${checkpoint.draft_type || 'content'} available - review and continue from there`);
  }

  if (task.assigned_agent) {
    lines.push(`Assigned to: @agent-${task.assigned_agent}`);
  }

  lines.push('');
  lines.push('Next steps:');
  lines.push('1. Review the checkpoint state above');
  lines.push('2. If draft content exists, use it as your starting point');
  lines.push('3. Continue from where you left off');

  return lines.join('\n');
}
