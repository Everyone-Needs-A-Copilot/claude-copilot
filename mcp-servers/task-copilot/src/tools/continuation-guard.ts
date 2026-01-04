/**
 * Continuation Guard for Ralph Wiggum Phase 2
 *
 * Detects premature agent stops (missing completion signals) and provides
 * automatic continuation prompts or iteration resumption.
 */

import type { DatabaseClient } from '../database.js';
import type { IterationConfig, IterationHistoryEntry, TaskMetadata } from '../types.js';

// ============================================================================
// TYPES
// ============================================================================

/**
 * Continuation detection result
 */
export interface ContinuationDetectionResult {
  incomplete: boolean;
  hasCompletionSignal: boolean;
  hasBlockedSignal: boolean;
  hasExplicitContinuation: boolean;
  lastNChars: string;
  reason?: string;
}

/**
 * Continuation decision result
 */
export interface ContinuationDecisionResult {
  shouldContinue: boolean;
  action: 'auto_resume' | 'prompt_user' | 'complete' | 'blocked';
  reason: string;
  prompt?: string;
  warning?: string;
}

/**
 * Continuation tracking metadata
 */
export interface ContinuationMetadata {
  continuationCount: number;
  lastContinuedAt: string;
  continuationReasons: string[];
}

// ============================================================================
// CONSTANTS
// ============================================================================

const COMPLETION_CHECK_CHARS = 100; // Check last 100 chars for completion signals
const MAX_CONTINUATIONS = 5; // Warn after 5 continuations
const RUNAWAY_THRESHOLD = 10; // Hard stop after 10 continuations

// ============================================================================
// DETECTION FUNCTIONS
// ============================================================================

/**
 * Detect if agent output lacks completion signals
 *
 * Checks the last N characters of agent output for:
 * - <promise>COMPLETE</promise>
 * - <promise>BLOCKED</promise>
 * - <thinking>CONTINUATION_NEEDED</thinking> (explicit continuation signal)
 *
 * @param agentOutput - Full agent output text
 * @param checkChars - Number of chars from end to check (default: 100)
 * @returns Detection result
 */
export function detectIncompleteStop(
  agentOutput: string,
  checkChars: number = COMPLETION_CHECK_CHARS
): ContinuationDetectionResult {
  if (!agentOutput || agentOutput.trim().length === 0) {
    return {
      incomplete: true,
      hasCompletionSignal: false,
      hasBlockedSignal: false,
      hasExplicitContinuation: false,
      lastNChars: '',
      reason: 'Empty agent output'
    };
  }

  // Get last N characters
  const lastNChars = agentOutput.slice(-checkChars);

  // Check for completion signals
  const hasCompleteSignal = /<promise>COMPLETE<\/promise>/i.test(lastNChars);
  const hasBlockedSignal = /<promise>BLOCKED<\/promise>/i.test(lastNChars);
  const hasExplicitContinuation = /<thinking>CONTINUATION_NEEDED<\/thinking>/i.test(lastNChars);

  // If any completion signal present, not incomplete
  if (hasCompleteSignal || hasBlockedSignal) {
    return {
      incomplete: false,
      hasCompletionSignal: hasCompleteSignal,
      hasBlockedSignal: hasBlockedSignal,
      hasExplicitContinuation: false,
      lastNChars
    };
  }

  // If explicit continuation signal, mark as incomplete
  if (hasExplicitContinuation) {
    return {
      incomplete: true,
      hasCompletionSignal: false,
      hasBlockedSignal: false,
      hasExplicitContinuation: true,
      lastNChars,
      reason: 'Agent explicitly signaled continuation needed'
    };
  }

  // No completion signals found - incomplete stop
  return {
    incomplete: true,
    hasCompletionSignal: false,
    hasBlockedSignal: false,
    hasExplicitContinuation: false,
    lastNChars,
    reason: 'No completion signal detected in last 100 characters'
  };
}

/**
 * Decide whether to auto-resume, prompt user, or complete
 *
 * Decision logic:
 * - If active iteration loop: auto-resume with iteration_next()
 * - If no iteration loop: prompt user to continue
 * - If continuation count > MAX_CONTINUATIONS: warn about possible runaway
 * - If continuation count > RUNAWAY_THRESHOLD: escalate/block
 *
 * @param db - Database client
 * @param taskId - Task ID
 * @param iterationId - Iteration ID (if in iteration loop)
 * @param detectionResult - Continuation detection result
 * @returns Continuation decision
 */
export function decideContinuation(
  db: DatabaseClient,
  taskId: string,
  iterationId: string | null,
  detectionResult: ContinuationDetectionResult
): ContinuationDecisionResult {
  // If not incomplete, no continuation needed
  if (!detectionResult.incomplete) {
    return {
      shouldContinue: false,
      action: detectionResult.hasCompletionSignal ? 'complete' : 'blocked',
      reason: detectionResult.hasCompletionSignal
        ? 'Agent completed successfully'
        : 'Agent blocked - requires intervention'
    };
  }

  // Get task to check continuation count
  const task = db.getTask(taskId);
  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }

  // Get continuation metadata from task
  const metadata = task.metadata as TaskMetadata & { continuation?: ContinuationMetadata };
  const continuation = metadata.continuation || {
    continuationCount: 0,
    lastContinuedAt: '',
    continuationReasons: []
  };

  // Check for runaway condition
  if (continuation.continuationCount >= RUNAWAY_THRESHOLD) {
    return {
      shouldContinue: false,
      action: 'blocked',
      reason: `Runaway detected: ${continuation.continuationCount} continuations exceed threshold of ${RUNAWAY_THRESHOLD}`,
      warning: `Task has been continued ${continuation.continuationCount} times without completion. Manual intervention required.`
    };
  }

  // Check if in active iteration loop
  if (iterationId) {
    const checkpoint = db.getCheckpoint(iterationId);
    if (checkpoint && checkpoint.iteration_config) {
      const config: IterationConfig = JSON.parse(checkpoint.iteration_config);
      const iterationNumber = checkpoint.iteration_number;

      // Check if max iterations reached
      if (iterationNumber >= config.maxIterations) {
        return {
          shouldContinue: false,
          action: 'blocked',
          reason: `Max iterations (${config.maxIterations}) reached without completion`,
          warning: `Agent stopped without completion signal after ${iterationNumber} iterations`
        };
      }

      // Auto-resume iteration
      const warning = continuation.continuationCount >= MAX_CONTINUATIONS
        ? `Warning: ${continuation.continuationCount} continuations detected. Possible runaway loop.`
        : undefined;

      return {
        shouldContinue: true,
        action: 'auto_resume',
        reason: `Active iteration loop detected (${iterationNumber}/${config.maxIterations})`,
        prompt: detectionResult.reason
          ? `Continuing iteration ${iterationNumber + 1}. Previous issue: ${detectionResult.reason}`
          : `Continuing iteration ${iterationNumber + 1}`,
        warning
      };
    }
  }

  // No active iteration - prompt user
  const warning = continuation.continuationCount >= MAX_CONTINUATIONS
    ? `Warning: ${continuation.continuationCount} continuations detected. Possible runaway loop.`
    : undefined;

  return {
    shouldContinue: true,
    action: 'prompt_user',
    reason: 'No active iteration loop - user confirmation needed',
    prompt: detectionResult.hasExplicitContinuation
      ? 'Agent signaled continuation needed. Continue? [y/n]'
      : 'Agent stopped without completion signal. Continue? [y/n]',
    warning
  };
}

/**
 * Track continuation in task metadata
 *
 * Increments continuation count and updates tracking metadata.
 *
 * @param db - Database client
 * @param taskId - Task ID
 * @param reason - Reason for continuation
 */
export function trackContinuation(
  db: DatabaseClient,
  taskId: string,
  reason: string
): void {
  const task = db.getTask(taskId);
  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }

  const metadata = task.metadata as TaskMetadata & { continuation?: ContinuationMetadata };
  const continuation = metadata.continuation || {
    continuationCount: 0,
    lastContinuedAt: '',
    continuationReasons: []
  };

  // Update continuation metadata
  const updatedContinuation: ContinuationMetadata = {
    continuationCount: continuation.continuationCount + 1,
    lastContinuedAt: new Date().toISOString(),
    continuationReasons: [
      ...continuation.continuationReasons.slice(-9), // Keep last 10 reasons
      reason
    ]
  };

  // Update task metadata
  db.updateTask(taskId, {
    metadata: {
      ...metadata,
      continuation: updatedContinuation
    }
  });
}

/**
 * Reset continuation counter
 *
 * Called when task completes successfully or is manually reset.
 *
 * @param db - Database client
 * @param taskId - Task ID
 */
export function resetContinuationCounter(
  db: DatabaseClient,
  taskId: string
): void {
  const task = db.getTask(taskId);
  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }

  const metadata = task.metadata as TaskMetadata & { continuation?: ContinuationMetadata };

  // Remove continuation metadata
  const { continuation, ...cleanMetadata } = metadata;

  db.updateTask(taskId, {
    metadata: cleanMetadata as TaskMetadata
  });
}

/**
 * Get continuation status for a task
 *
 * @param db - Database client
 * @param taskId - Task ID
 * @returns Continuation metadata or null if no continuations tracked
 */
export function getContinuationStatus(
  db: DatabaseClient,
  taskId: string
): ContinuationMetadata | null {
  const task = db.getTask(taskId);
  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }

  const metadata = task.metadata as TaskMetadata & { continuation?: ContinuationMetadata };
  return metadata.continuation || null;
}

// ============================================================================
// INTEGRATION HELPERS
// ============================================================================

/**
 * Check agent output and decide on continuation
 *
 * Convenience function that combines detection and decision logic.
 * Used by iteration_validate to handle incomplete stops.
 *
 * @param db - Database client
 * @param taskId - Task ID
 * @param iterationId - Iteration ID (if in iteration loop)
 * @param agentOutput - Agent output text
 * @returns Continuation decision
 */
export function checkAndDecideContinuation(
  db: DatabaseClient,
  taskId: string,
  iterationId: string | null,
  agentOutput: string
): ContinuationDecisionResult {
  // Detect incomplete stop
  const detection = detectIncompleteStop(agentOutput);

  // Decide on continuation
  const decision = decideContinuation(db, taskId, iterationId, detection);

  // Track continuation if auto-resuming
  if (decision.shouldContinue && decision.action === 'auto_resume') {
    trackContinuation(db, taskId, detection.reason || 'Incomplete stop detected');
  }

  return decision;
}
