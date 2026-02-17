/**
 * Stop Hook System for Ralph Wiggum Phase 2
 *
 * Enables completion signal interception to support loop continuation.
 * Hooks can analyze agent context and decide whether to complete, continue, or escalate.
 */

import type { DatabaseClient } from '../database.js';
import type {
  CompletionSignal,
  IterationConfig,
  IterationHistoryEntry,
  ValidationState,
  WorkProductType
} from '../types.js';
import { extractSummary, estimateTokens as estimateContextTokens } from '../utils/context-monitor.js';

// ============================================================================
// TYPES
// ============================================================================

/**
 * Agent execution context provided to hooks
 */
export interface AgentContext {
  taskId: string;
  iteration: number;
  executionPhase: string | null;
  filesModified: string[];
  validationResults: ValidationResult[];
  completionPromises: CompletionPromise[];
  agentOutput?: string;
  draftContent?: string;
  draftType?: WorkProductType | null;
}

/**
 * Validation result from iteration validation
 */
export interface ValidationResult {
  ruleName: string;
  passed: boolean;
  message: string;
}

/**
 * Completion promise detected in agent output
 */
export interface CompletionPromise {
  type: 'COMPLETE' | 'BLOCKED' | 'ESCALATE';
  detected: boolean;
  content: string;
  detectedAt?: string;
}

/**
 * Result of hook evaluation
 */
export interface StopHookResult {
  action: 'complete' | 'continue' | 'escalate';
  reason: string;
  nextPrompt?: string;
  checkpointData?: CheckpointData;
  metadata?: Record<string, unknown>;
}

/**
 * Optional checkpoint data to create before next iteration
 */
export interface CheckpointData {
  executionPhase?: string;
  executionStep?: number;
  agentContext?: Record<string, unknown>;
  draftContent?: string;
  draftType?: WorkProductType;
}

/**
 * Hook configuration
 */
export interface StopHook {
  id: string;
  taskId: string;
  enabled: boolean;
  onComplete: (context: AgentContext) => StopHookResult | Promise<StopHookResult>;
  metadata?: Record<string, unknown>;
}

/**
 * Hook registration input
 */
export interface HookRegisterInput {
  taskId: string;
  hookId?: string;
  enabled?: boolean;
  metadata?: Record<string, unknown>;
}

/**
 * Hook evaluation input
 */
export interface HookEvaluateInput {
  iterationId: string;
  agentOutput?: string;
  filesModified?: string[];
  draftContent?: string;
  draftType?: WorkProductType;
}

/**
 * Hook evaluation output
 */
export interface HookEvaluateOutput {
  hookId: string;
  taskId: string;
  iteration: number;
  action: 'complete' | 'continue' | 'escalate';
  reason: string;
  nextPrompt?: string;
  checkpointCreated?: boolean;
  checkpointId?: string;
  metadata?: Record<string, unknown>;
}

// ============================================================================
// IN-MEMORY HOOK REGISTRY
// ============================================================================

/**
 * In-memory registry of hooks by task ID
 *
 * Note: Hooks are session-scoped and not persisted to the database.
 * This aligns with the MCP server lifecycle - hooks are registered
 * when an agent starts an iteration loop and cleared when the loop completes.
 */
const hookRegistry = new Map<string, StopHook>();

// ============================================================================
// HOOK REGISTRATION
// ============================================================================

/**
 * Register a stop hook for a task
 *
 * Hooks are registered by agents at the start of an iteration loop and
 * invoked during iteration_validate to determine loop continuation.
 *
 * @param input - Hook registration input
 * @param onComplete - Hook callback function
 * @returns Registered hook ID
 */
export function registerStopHook(
  input: HookRegisterInput,
  onComplete: (context: AgentContext) => StopHookResult | Promise<StopHookResult>
): string {
  const hookId = input.hookId || `HOOK-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

  const hook: StopHook = {
    id: hookId,
    taskId: input.taskId,
    enabled: input.enabled !== undefined ? input.enabled : true,
    onComplete,
    metadata: input.metadata
  };

  hookRegistry.set(hookId, hook);

  return hookId;
}

/**
 * Unregister a stop hook
 *
 * @param hookId - Hook ID to unregister
 * @returns True if hook was found and removed
 */
export function unregisterStopHook(hookId: string): boolean {
  return hookRegistry.delete(hookId);
}

/**
 * Get a registered hook by ID
 *
 * @param hookId - Hook ID to retrieve
 * @returns Hook if found, undefined otherwise
 */
export function getStopHook(hookId: string): StopHook | undefined {
  return hookRegistry.get(hookId);
}

/**
 * Get all hooks for a task
 *
 * @param taskId - Task ID to get hooks for
 * @returns Array of hooks for the task
 */
export function getTaskHooks(taskId: string): StopHook[] {
  const hooks: StopHook[] = [];
  for (const hook of hookRegistry.values()) {
    if (hook.taskId === taskId) {
      hooks.push(hook);
    }
  }
  return hooks;
}

/**
 * Clear all hooks for a task
 *
 * @param taskId - Task ID to clear hooks for
 * @returns Number of hooks cleared
 */
export function clearTaskHooks(taskId: string): number {
  let cleared = 0;
  for (const [hookId, hook] of hookRegistry.entries()) {
    if (hook.taskId === taskId) {
      hookRegistry.delete(hookId);
      cleared++;
    }
  }
  return cleared;
}

/**
 * Clear all registered hooks
 *
 * @returns Number of hooks cleared
 */
export function clearAllHooks(): number {
  const count = hookRegistry.size;
  hookRegistry.clear();
  return count;
}

// ============================================================================
// HOOK EVALUATION
// ============================================================================

/**
 * Evaluate stop hooks for an iteration
 *
 * This function is called during iteration_validate to determine whether
 * the loop should complete, continue, or escalate based on agent context.
 *
 * If multiple hooks are registered for a task, they are evaluated in
 * registration order. The first hook to return 'complete' or 'escalate'
 * will stop the evaluation chain.
 *
 * @param db - Database client
 * @param input - Hook evaluation input
 * @returns Hook evaluation result
 */
export async function evaluateStopHooks(
  db: DatabaseClient,
  input: HookEvaluateInput
): Promise<HookEvaluateOutput> {
  // Get checkpoint
  const checkpoint = db.getCheckpoint(input.iterationId);
  if (!checkpoint) {
    throw new Error(`Iteration checkpoint not found: ${input.iterationId}`);
  }

  if (!checkpoint.iteration_config) {
    throw new Error(`Checkpoint ${input.iterationId} is not an iteration checkpoint`);
  }

  // Parse iteration state
  const config: IterationConfig = JSON.parse(checkpoint.iteration_config);
  const iterationNumber = checkpoint.iteration_number;
  const history: IterationHistoryEntry[] = JSON.parse(checkpoint.iteration_history);
  const validationState: ValidationState | null = checkpoint.validation_state
    ? JSON.parse(checkpoint.validation_state)
    : null;

  // Get registered hooks for this task
  const hooks = getTaskHooks(checkpoint.task_id);

  // If no hooks registered, default to continue
  if (hooks.length === 0) {
    return {
      hookId: 'default',
      taskId: checkpoint.task_id,
      iteration: iterationNumber,
      action: 'continue',
      reason: 'No hooks registered for this task'
    };
  }

  // Build agent context
  const agentContext: AgentContext = {
    taskId: checkpoint.task_id,
    iteration: iterationNumber,
    executionPhase: checkpoint.execution_phase,
    filesModified: input.filesModified || [],
    validationResults: validationState?.results.map(r => ({
      ruleName: r.ruleId,
      passed: r.passed,
      message: r.message || ''
    })) || [],
    completionPromises: parseCompletionPromises(input.agentOutput || ''),
    agentOutput: input.agentOutput,
    draftContent: input.draftContent,
    draftType: input.draftType
  };

  // Evaluate hooks in order
  for (const hook of hooks) {
    if (!hook.enabled) {
      continue;
    }

    try {
      const result = await hook.onComplete(agentContext);

      // If hook returns 'complete' or 'escalate', stop evaluation
      if (result.action === 'complete' || result.action === 'escalate') {
        // Create checkpoint if requested
        let checkpointCreated = false;
        let checkpointId: string | undefined;

        if (result.checkpointData) {
          checkpointId = await createHookCheckpoint(db, checkpoint.task_id, result.checkpointData);
          checkpointCreated = true;
        }

        return {
          hookId: hook.id,
          taskId: checkpoint.task_id,
          iteration: iterationNumber,
          action: result.action,
          reason: result.reason,
          nextPrompt: result.nextPrompt,
          checkpointCreated,
          checkpointId,
          metadata: result.metadata
        };
      }

      // If hook returns 'continue', continue to next hook
      // (unless this is the last hook)
      if (hooks.indexOf(hook) === hooks.length - 1) {
        // Last hook returned 'continue'
        return {
          hookId: hook.id,
          taskId: checkpoint.task_id,
          iteration: iterationNumber,
          action: result.action,
          reason: result.reason,
          nextPrompt: result.nextPrompt,
          metadata: result.metadata
        };
      }
    } catch (error) {
      // Hook evaluation failed - escalate
      return {
        hookId: hook.id,
        taskId: checkpoint.task_id,
        iteration: iterationNumber,
        action: 'escalate',
        reason: `Hook evaluation failed: ${error instanceof Error ? error.message : String(error)}`,
        metadata: {
          error: error instanceof Error ? error.message : String(error)
        }
      };
    }
  }

  // All hooks evaluated without returning - default to continue
  return {
    hookId: 'default',
    taskId: checkpoint.task_id,
    iteration: iterationNumber,
    action: 'continue',
    reason: 'All hooks completed evaluation'
  };
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Parse completion promises from agent output
 */
function parseCompletionPromises(output: string): CompletionPromise[] {
  const promises: CompletionPromise[] = [];

  // Detect <promise>COMPLETE</promise>
  const completeMatch = output.match(/<promise>COMPLETE<\/promise>/i);
  if (completeMatch) {
    promises.push({
      type: 'COMPLETE',
      detected: true,
      content: completeMatch[0],
      detectedAt: new Date().toISOString()
    });
  }

  // Detect <promise>BLOCKED</promise>
  const blockedMatch = output.match(/<promise>BLOCKED<\/promise>/i);
  if (blockedMatch) {
    promises.push({
      type: 'BLOCKED',
      detected: true,
      content: blockedMatch[0],
      detectedAt: new Date().toISOString()
    });
  }

  // Detect <promise>ESCALATE</promise>
  const escalateMatch = output.match(/<promise>ESCALATE<\/promise>/i);
  if (escalateMatch) {
    promises.push({
      type: 'ESCALATE',
      detected: true,
      content: escalateMatch[0],
      detectedAt: new Date().toISOString()
    });
  }

  return promises;
}

/**
 * Create a checkpoint from hook data
 */
async function createHookCheckpoint(
  db: DatabaseClient,
  taskId: string,
  data: CheckpointData
): Promise<string> {
  const task = db.getTask(taskId);
  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }

  const now = new Date().toISOString();
  const checkpointId = `CP-HOOK-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;

  db.insertCheckpoint({
    id: checkpointId,
    task_id: taskId,
    sequence: db.getNextCheckpointSequence(taskId),
    trigger: 'manual',
    task_status: task.status,
    task_notes: task.notes || null,
    task_metadata: JSON.stringify(task.metadata),
    blocked_reason: task.blocked_reason || null,
    assigned_agent: task.assigned_agent || null,
    execution_phase: data.executionPhase || null,
    execution_step: data.executionStep || null,
    agent_context: data.agentContext ? JSON.stringify(data.agentContext) : null,
    draft_content: data.draftContent || null,
    draft_type: data.draftType || null,
    subtask_states: '[]',
    created_at: now,
    expires_at: null,
    iteration_config: null,
    iteration_number: 0,
    iteration_history: '[]',
    completion_promises: '[]',
    validation_state: null
  });

  return checkpointId;
}

// ============================================================================
// PRESET HOOK FACTORIES
// ============================================================================

/**
 * Create a simple validation-based hook
 *
 * Completes if all validation rules pass, continues otherwise.
 */
export function createValidationHook(taskId: string): string {
  return registerStopHook(
    { taskId },
    (context: AgentContext): StopHookResult => {
      const allPassed = context.validationResults.every(r => r.passed);

      if (allPassed && context.validationResults.length > 0) {
        return {
          action: 'complete',
          reason: 'All validation rules passed'
        };
      }

      const failedRules = context.validationResults.filter(r => !r.passed);
      return {
        action: 'continue',
        reason: `${failedRules.length} validation rule(s) failed`,
        nextPrompt: failedRules.length > 0
          ? `Continue iteration. Fix the following validation failures:\n${failedRules.map(r => `- ${r.ruleName}: ${r.message}`).join('\n')}`
          : undefined
      };
    }
  );
}

/**
 * Create a promise-based hook
 *
 * Completes if COMPLETE promise detected, escalates if ESCALATE detected.
 */
export function createPromiseHook(taskId: string): string {
  return registerStopHook(
    { taskId },
    (context: AgentContext): StopHookResult => {
      const completePromise = context.completionPromises.find(p => p.type === 'COMPLETE');
      if (completePromise) {
        return {
          action: 'complete',
          reason: 'Agent signaled completion via <promise>COMPLETE</promise>'
        };
      }

      const escalatePromise = context.completionPromises.find(p => p.type === 'ESCALATE');
      if (escalatePromise) {
        return {
          action: 'escalate',
          reason: 'Agent signaled escalation via <promise>ESCALATE</promise>'
        };
      }

      const blockedPromise = context.completionPromises.find(p => p.type === 'BLOCKED');
      if (blockedPromise) {
        return {
          action: 'escalate',
          reason: 'Agent signaled blocked state via <promise>BLOCKED</promise>'
        };
      }

      return {
        action: 'continue',
        reason: 'No completion promise detected'
      };
    }
  );
}

/**
 * Create a combined hook that checks both validation and promises
 *
 * This is the recommended default hook for most iteration scenarios.
 */
export function createDefaultHook(taskId: string): string {
  return registerStopHook(
    { taskId },
    (context: AgentContext): StopHookResult => {
      const buildBlockedCheckpoint = (): CheckpointData | undefined => {
        const source = context.draftContent || context.agentOutput;
        if (!source) return undefined;

        const summary = extractSummary(source, 200);
        return {
          executionPhase: 'blocked',
          agentContext: {
            autoCompacted: true,
            summaryTokens: estimateContextTokens(summary),
            summarySource: context.draftContent ? 'draftContent' : 'agentOutput',
            summaryCreatedAt: new Date().toISOString(),
          },
          draftContent: summary,
          draftType: context.draftType || 'other'
        };
      };

      // 1. Check for explicit promises first (highest priority)
      const completePromise = context.completionPromises.find(p => p.type === 'COMPLETE');
      if (completePromise) {
        return {
          action: 'complete',
          reason: 'Agent signaled completion via <promise>COMPLETE</promise>'
        };
      }

      const escalatePromise = context.completionPromises.find(p => p.type === 'ESCALATE');
      if (escalatePromise) {
        return {
          action: 'escalate',
          reason: 'Agent signaled escalation via <promise>ESCALATE</promise>'
        };
      }

      const blockedPromise = context.completionPromises.find(p => p.type === 'BLOCKED');
      if (blockedPromise) {
        return {
          action: 'escalate',
          reason: 'Agent signaled blocked state via <promise>BLOCKED</promise>',
          checkpointData: buildBlockedCheckpoint()
        };
      }

      // 2. Check validation results
      if (context.validationResults.length > 0) {
        const allPassed = context.validationResults.every(r => r.passed);

        if (allPassed) {
          return {
            action: 'complete',
            reason: 'All validation rules passed'
          };
        }

        const failedRules = context.validationResults.filter(r => !r.passed);
        return {
          action: 'continue',
          reason: `${failedRules.length} validation rule(s) failed`,
          nextPrompt: `Continue iteration. Fix the following validation failures:\n${failedRules.map(r => `- ${r.ruleName}: ${r.message}`).join('\n')}`
        };
      }

      // 3. No promises and no validation - continue by default
      return {
        action: 'continue',
        reason: 'Iteration in progress'
      };
    }
  );
}
