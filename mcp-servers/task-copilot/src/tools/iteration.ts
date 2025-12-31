/**
 * Ralph Wiggum iteration tool implementations
 *
 * Phase 1: iteration_start - Initialize a new iteration loop
 * Phase 2: iteration_validate, iteration_next, iteration_complete
 */

import type { DatabaseClient } from '../database.js';
import type { IterationConfig, IterationHistoryEntry, ValidationState, CompletionSignal } from '../types.js';
import { getIterationEngine } from '../validation/iteration-engine.js';
import type { IterationValidationRule } from '../validation/iteration-types.js';
import { runSafetyChecks } from './iteration-guards.js';
import { validateIterationConfigOrThrow } from '../validation/iteration-config-validator.js';
import { evaluateStopHooks, getTaskHooks } from './stop-hooks.js';

// ============================================================================
// INPUT/OUTPUT TYPES
// ============================================================================

export interface IterationStartInput {
  taskId: string;
  maxIterations: number;
  completionPromises: string[];
  validationRules?: Array<{
    type: string;
    name: string;
    config: Record<string, unknown>;
  }>;
  circuitBreakerThreshold?: number;
}

export interface IterationStartOutput {
  iterationId: string;
  taskId: string;
  iterationNumber: number;
  maxIterations: number;
  config: IterationConfig;
  createdAt: string;
}

export interface IterationValidateInput {
  iterationId: string;
  agentOutput?: string;
}

export interface IterationValidateOutput {
  iterationId: string;
  iterationNumber: number;
  validationPassed: boolean;
  completionSignal: CompletionSignal;
  detectedPromise?: string;
  feedback: string[];
  results: Array<{
    ruleName: string;
    passed: boolean;
    message: string;
  }>;
  completionPromisesDetected: string[];
  hookDecision?: {
    hookId: string;
    action: 'complete' | 'continue' | 'escalate';
    reason: string;
    nextPrompt?: string;
  };
}

export interface IterationNextInput {
  iterationId: string;
  validationResult?: object;
  agentContext?: object;
}

export interface IterationNextOutput {
  iterationId: string;
  iterationNumber: number;
  remainingIterations: number;
  config: IterationConfig;
}

export interface IterationCompleteInput {
  iterationId: string;
  completionPromise: string;
  workProductId?: string;
}

export interface IterationCompleteOutput {
  iterationId: string;
  taskId: string;
  completedAt: string;
  totalIterations: number;
  completionPromise: string;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 3;

// ============================================================================
// TOOL IMPLEMENTATIONS
// ============================================================================

/**
 * Initialize a new iteration loop
 *
 * Creates a checkpoint with iteration_number = 1 and stores the iteration
 * configuration. This checkpoint serves as the iteration session.
 */
export function iterationStart(
  db: DatabaseClient,
  input: IterationStartInput
): IterationStartOutput {
  // Validate task exists
  const task = db.getTask(input.taskId);
  if (!task) {
    throw new Error(`Task not found: ${input.taskId}`);
  }

  // Validate iteration configuration using JSON schema validator
  // This validates maxIterations, completionPromises, validationRules, and circuitBreakerThreshold
  const validatedConfig = validateIterationConfigOrThrow({
    maxIterations: input.maxIterations,
    completionPromises: input.completionPromises,
    validationRules: input.validationRules,
    circuitBreakerThreshold: input.circuitBreakerThreshold
  });

  // Build iteration config with validated values and defaults
  const config: IterationConfig = {
    maxIterations: validatedConfig.maxIterations,
    completionPromises: validatedConfig.completionPromises,
    validationRules: validatedConfig.validationRules,
    circuitBreakerThreshold: validatedConfig.circuitBreakerThreshold ?? DEFAULT_CIRCUIT_BREAKER_THRESHOLD
  };

  const now = new Date().toISOString();
  const iterationId = `IT-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

  // Create checkpoint with iteration metadata using internal database method
  db.insertCheckpoint({
    id: iterationId,
    task_id: input.taskId,
    sequence: db.getNextCheckpointSequence(input.taskId),
    trigger: 'manual',
    task_status: task.status,
    task_notes: task.notes || null,
    task_metadata: JSON.stringify(task.metadata),
    blocked_reason: task.blocked_reason || null,
    assigned_agent: task.assigned_agent || null,
    execution_phase: 'iteration',
    execution_step: 1,
    agent_context: null,
    draft_content: null,
    draft_type: null,
    subtask_states: '[]',
    created_at: now,
    expires_at: null, // Iteration checkpoints don't expire
    // Ralph Wiggum iteration fields
    iteration_config: JSON.stringify(config),
    iteration_number: 1,
    iteration_history: '[]',
    completion_promises: JSON.stringify(input.completionPromises),
    validation_state: null
  });

  return {
    iterationId,
    taskId: input.taskId,
    iterationNumber: 1,
    maxIterations: input.maxIterations,
    config,
    createdAt: now
  };
}

/**
 * Validate current iteration
 *
 * Runs validation rules against the current iteration output and detects
 * completion promises in agent output. Integrates safety guards to determine
 * completion signal (CONTINUE/COMPLETE/BLOCKED/ESCALATE).
 */
export async function iterationValidate(
  db: DatabaseClient,
  input: IterationValidateInput
): Promise<IterationValidateOutput> {
  // Get checkpoint
  const checkpoint = db.getCheckpoint(input.iterationId);
  if (!checkpoint) {
    throw new Error(`Iteration checkpoint not found: ${input.iterationId}`);
  }

  if (!checkpoint.iteration_config) {
    throw new Error(`Checkpoint ${input.iterationId} is not an iteration checkpoint`);
  }

  // Parse iteration config and history
  const config: IterationConfig = JSON.parse(checkpoint.iteration_config);
  const iterationNumber = checkpoint.iteration_number;
  const history: IterationHistoryEntry[] = JSON.parse(checkpoint.iteration_history);

  // Detect completion promises using XML tag patterns
  const completePromise = detectPromiseByTag(input.agentOutput || '', 'COMPLETE');
  const blockedPromise = detectPromiseByTag(input.agentOutput || '', 'BLOCKED');

  // Run safety checks to detect ESCALATE conditions
  const safetyResult = runSafetyChecks(iterationNumber, config, history);

  // Initialize feedback array
  const feedback: string[] = [];
  let completionSignal: CompletionSignal = 'CONTINUE';
  let detectedPromise: string | undefined;
  let hookDecision: IterationValidateOutput['hookDecision'] = undefined;

  // Priority order: BLOCKED > COMPLETE > ESCALATE > CONTINUE

  // 1. Check for BLOCKED promise (highest priority)
  if (blockedPromise) {
    completionSignal = 'BLOCKED';
    detectedPromise = blockedPromise;
    feedback.push('Agent signaled BLOCKED state - requires human intervention');
  }
  // 2. Check for COMPLETE promise
  else if (completePromise) {
    completionSignal = 'COMPLETE';
    detectedPromise = completePromise;
    feedback.push('Agent signaled successful completion');
  }
  // 3. Check for ESCALATE from safety guards
  else if (!safetyResult.canContinue) {
    completionSignal = 'ESCALATE';
    feedback.push(safetyResult.message || 'Safety guard triggered');
    if (safetyResult.blockedBy) {
      feedback.push(`Blocked by: ${safetyResult.blockedBy}`);
    }
  }

  // 4. Evaluate stop hooks (if registered and safety checks passed)
  const hooks = getTaskHooks(checkpoint.task_id);
  if (hooks.length > 0 && safetyResult.canContinue) {
    const hookResult = await evaluateStopHooks(db, {
      iterationId: input.iterationId,
      agentOutput: input.agentOutput
    });

    // Store hook decision in output
    hookDecision = {
      hookId: hookResult.hookId,
      action: hookResult.action,
      reason: hookResult.reason,
      nextPrompt: hookResult.nextPrompt
    };

    // Allow hooks to influence completion signal (if not already set)
    if (completionSignal === 'CONTINUE') {
      if (hookResult.action === 'complete') {
        completionSignal = 'COMPLETE';
        feedback.push(`Hook decision: ${hookResult.reason}`);
      } else if (hookResult.action === 'escalate') {
        completionSignal = 'ESCALATE';
        feedback.push(`Hook decision: ${hookResult.reason}`);
      } else if (hookResult.action === 'continue' && hookResult.nextPrompt) {
        feedback.push(`Hook guidance: ${hookResult.reason}`);
      }
    }
  }

  // If no validation rules provided, just check completion promises
  if (!config.validationRules || config.validationRules.length === 0) {
    const completionPromisesDetected = detectCompletionPromises(
      input.agentOutput || '',
      config.completionPromises
    );

    return {
      iterationId: input.iterationId,
      iterationNumber,
      validationPassed: completionPromisesDetected.length > 0,
      completionSignal,
      detectedPromise,
      feedback,
      results: [],
      completionPromisesDetected,
      hookDecision
    };
  }

  // Convert validation rules to iteration validation rules
  const rules: IterationValidationRule[] = config.validationRules.map(r => ({
    ...r.config,
    type: r.type,
    name: r.name || r.type,
    enabled: true
  } as IterationValidationRule));

  // Get task for context
  const task = db.getTask(checkpoint.task_id);
  if (!task) {
    throw new Error(`Task not found: ${checkpoint.task_id}`);
  }

  // Get latest work product for validation context
  const workProducts = db.listWorkProducts(checkpoint.task_id);
  const latestWorkProduct = workProducts.length > 0 ? workProducts[0].content : undefined;

  // Run validation engine
  const engine = getIterationEngine();
  const validationReport = await engine.validate(
    rules,
    {
      taskId: checkpoint.task_id,
      workingDirectory: process.cwd(),
      agentOutput: input.agentOutput,
      taskNotes: task.notes ?? undefined,
      latestWorkProduct
    },
    checkpoint.task_id,
    iterationNumber
  );

  // Add validation failures to feedback (if not already BLOCKED or COMPLETE)
  if (completionSignal === 'CONTINUE' || completionSignal === 'ESCALATE') {
    const validationFeedback = validationReport.results
      .filter(r => !r.passed)
      .map(r => `${r.ruleName}: ${r.message}`);
    feedback.push(...validationFeedback);
  }

  // Detect completion promises (legacy format)
  const completionPromisesDetected = detectCompletionPromises(
    input.agentOutput || '',
    config.completionPromises
  );

  // Store validation state
  const validationState: ValidationState = {
    lastRun: new Date().toISOString(),
    passed: validationReport.overallPassed,
    results: validationReport.results.map(r => ({
      ruleId: r.ruleName,
      passed: r.passed,
      message: r.message
    }))
  };

  db.updateCheckpointIteration(
    input.iterationId,
    iterationNumber,
    checkpoint.iteration_history,
    JSON.stringify(validationState)
  );

  return {
    iterationId: input.iterationId,
    iterationNumber,
    validationPassed: validationReport.overallPassed,
    completionSignal,
    detectedPromise,
    feedback,
    results: validationReport.results.map(r => ({
      ruleName: r.ruleName,
      passed: r.passed,
      message: r.message
    })),
    completionPromisesDetected,
    hookDecision
  };
}

/**
 * Advance to next iteration
 *
 * Increments iteration number and updates history. Throws if max iterations reached.
 */
export function iterationNext(
  db: DatabaseClient,
  input: IterationNextInput
): IterationNextOutput {
  // Get checkpoint
  const checkpoint = db.getCheckpoint(input.iterationId);
  if (!checkpoint) {
    throw new Error(`Iteration checkpoint not found: ${input.iterationId}`);
  }

  if (!checkpoint.iteration_config) {
    throw new Error(`Checkpoint ${input.iterationId} is not an iteration checkpoint`);
  }

  // Parse iteration config
  const config: IterationConfig = JSON.parse(checkpoint.iteration_config);
  const currentIteration = checkpoint.iteration_number;

  // Check if max iterations reached
  if (currentIteration >= config.maxIterations) {
    throw new Error(
      `Maximum iterations (${config.maxIterations}) reached. Use iteration_complete or increase maxIterations.`
    );
  }

  // Parse existing history
  const history: IterationHistoryEntry[] = JSON.parse(checkpoint.iteration_history);

  // Add current iteration to history
  if (input.validationResult) {
    history.push({
      iteration: currentIteration,
      timestamp: new Date().toISOString(),
      validationResult: input.validationResult as any,
      checkpointId: input.iterationId
    });
  }

  // Increment iteration number
  const nextIteration = currentIteration + 1;

  // Update checkpoint
  db.updateCheckpointIteration(
    input.iterationId,
    nextIteration,
    JSON.stringify(history),
    checkpoint.validation_state
  );

  return {
    iterationId: input.iterationId,
    iterationNumber: nextIteration,
    remainingIterations: config.maxIterations - nextIteration,
    config
  };
}

/**
 * Complete iteration loop
 *
 * Marks the iteration as complete and optionally links a final work product.
 * Updates task status to completed.
 */
export function iterationComplete(
  db: DatabaseClient,
  input: IterationCompleteInput
): IterationCompleteOutput {
  // Get checkpoint
  const checkpoint = db.getCheckpoint(input.iterationId);
  if (!checkpoint) {
    throw new Error(`Iteration checkpoint not found: ${input.iterationId}`);
  }

  if (!checkpoint.iteration_config) {
    throw new Error(`Checkpoint ${input.iterationId} is not an iteration checkpoint`);
  }

  // Parse iteration config
  const config: IterationConfig = JSON.parse(checkpoint.iteration_config);

  // Validate completion promise
  if (!config.completionPromises.includes(input.completionPromise)) {
    throw new Error(
      `Invalid completion promise: ${input.completionPromise}. Must be one of: ${config.completionPromises.join(', ')}`
    );
  }

  // Update task to completed
  const task = db.getTask(checkpoint.task_id);
  if (!task) {
    throw new Error(`Task not found: ${checkpoint.task_id}`);
  }

  const now = new Date().toISOString();

  // Add completion metadata to task
  const existingMetadata = task.metadata ? JSON.parse(task.metadata) : {};
  const completionMetadata: Record<string, unknown> = {
    ...existingMetadata,
    iterationComplete: {
      completedAt: now,
      totalIterations: checkpoint.iteration_number,
      completionPromise: input.completionPromise,
      workProductId: input.workProductId
    }
  };

  db.updateTask(checkpoint.task_id, {
    status: 'completed',
    notes: task.notes
      ? `${task.notes}\n\nIteration completed: ${input.completionPromise}`
      : `Iteration completed: ${input.completionPromise}`,
    metadata: JSON.stringify(completionMetadata)
  });

  return {
    iterationId: input.iterationId,
    taskId: checkpoint.task_id,
    completedAt: now,
    totalIterations: checkpoint.iteration_number,
    completionPromise: input.completionPromise
  };
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Detect completion promise using XML tag pattern: <promise>TYPE</promise>
 *
 * @param output - Agent output to search
 * @param promiseType - Type of promise to detect (e.g., 'COMPLETE', 'BLOCKED')
 * @returns The full promise text if detected (including any trailing context), undefined otherwise
 */
function detectPromiseByTag(output: string, promiseType: string): string | undefined {
  // Match <promise>TYPE</promise> with optional trailing text until next line
  const pattern = new RegExp(
    `<promise>${promiseType}</promise>([\\s\\S]*?)(?=\\n\\n|$)`,
    'i'
  );

  const match = output.match(pattern);
  if (match) {
    // Return the tag plus any trailing context (trimmed)
    return `<promise>${promiseType}</promise>${match[1] || ''}`.trim();
  }

  return undefined;
}

/**
 * Detect which completion promises are mentioned in agent output (legacy format)
 */
function detectCompletionPromises(output: string, promises: string[]): string[] {
  const detected: string[] = [];
  const lowerOutput = output.toLowerCase();

  for (const promise of promises) {
    // Simple keyword detection - check if promise text appears in output
    const lowerPromise = promise.toLowerCase();
    if (lowerOutput.includes(lowerPromise)) {
      detected.push(promise);
    }
  }

  return detected;
}
