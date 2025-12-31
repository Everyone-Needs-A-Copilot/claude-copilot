/**
 * Ralph Wiggum Iteration Hook Configuration Types
 *
 * Defines hook configuration for iteration control lifecycle:
 * - Stop hooks (validation rules determining iteration completion)
 * - Pre/Post iteration hooks (lifecycle callbacks)
 * - Circuit breaker hooks (safety mechanisms)
 */

import type { IterationValidationRule } from './iteration-types.js';

// ============================================================================
// HOOK TYPES
// ============================================================================

export type HookType = 'stop' | 'pre_iteration' | 'post_iteration' | 'circuit_breaker';
export type HookTrigger = 'always' | 'on_failure' | 'on_success' | 'conditional';

// ============================================================================
// STOP HOOKS (Validation-based iteration termination)
// ============================================================================

/**
 * Stop hook - determines when iteration should stop
 * Uses validation rules to check completion criteria
 */
export interface StopHook {
  type: 'stop';
  name: string;
  description?: string;
  enabled: boolean;

  /**
   * Validation rules to check
   * All rules must pass for stop condition to be met
   */
  validationRules: IterationValidationRule[];

  /**
   * Action to take when stop condition is met
   */
  action: 'complete' | 'blocked' | 'escalate';

  /**
   * Priority (lower number = higher priority)
   * Used when multiple stop hooks match
   */
  priority: number;

  /**
   * Custom message to display when hook triggers
   */
  message?: string;
}

// ============================================================================
// LIFECYCLE HOOKS (Pre/Post iteration actions)
// ============================================================================

/**
 * Pre-iteration hook - runs before each iteration
 */
export interface PreIterationHook {
  type: 'pre_iteration';
  name: string;
  description?: string;
  enabled: boolean;
  trigger: HookTrigger;

  /**
   * Actions to execute
   */
  actions: HookAction[];

  /**
   * Whether to fail the iteration if hook fails
   */
  failOnError: boolean;

  /**
   * Timeout in milliseconds
   */
  timeout?: number;

  /**
   * Condition for conditional trigger (JavaScript expression)
   * Has access to: iteration, config, history
   */
  condition?: string;
}

/**
 * Post-iteration hook - runs after each iteration
 */
export interface PostIterationHook {
  type: 'post_iteration';
  name: string;
  description?: string;
  enabled: boolean;
  trigger: HookTrigger;

  /**
   * Actions to execute
   */
  actions: HookAction[];

  /**
   * Whether to fail the iteration if hook fails
   */
  failOnError: boolean;

  /**
   * Timeout in milliseconds
   */
  timeout?: number;

  /**
   * Condition for conditional trigger (JavaScript expression)
   */
  condition?: string;
}

// ============================================================================
// CIRCUIT BREAKER HOOKS (Safety mechanisms)
// ============================================================================

/**
 * Circuit breaker hook - safety mechanism to prevent runaway iterations
 */
export interface CircuitBreakerHook {
  type: 'circuit_breaker';
  name: string;
  description?: string;
  enabled: boolean;

  /**
   * Detection strategy
   */
  strategy: 'thrashing' | 'quality_regression' | 'timeout' | 'custom';

  /**
   * Configuration specific to strategy
   */
  config: CircuitBreakerConfig;

  /**
   * Action to take when breaker trips
   */
  action: 'escalate' | 'blocked';

  /**
   * Custom message to display when breaker trips
   */
  message?: string;
}

/**
 * Circuit breaker configuration by strategy
 */
export type CircuitBreakerConfig =
  | ThrashingDetectorConfig
  | QualityRegressionConfig
  | TimeoutConfig
  | CustomCircuitBreakerConfig;

export interface ThrashingDetectorConfig {
  strategy: 'thrashing';

  /**
   * Number of consecutive failures to detect
   */
  consecutiveFailures: number;

  /**
   * Similarity threshold for detecting repeated failures (0-1)
   * 1.0 = exact match, 0.0 = no similarity required
   */
  similarityThreshold: number;

  /**
   * Window size for checking failures
   */
  windowSize: number;
}

export interface QualityRegressionConfig {
  strategy: 'quality_regression';

  /**
   * Metric to track (e.g., 'test_pass_rate', 'coverage', 'lint_errors')
   */
  metric: string;

  /**
   * Minimum acceptable value for metric
   */
  minValue: number;

  /**
   * Number of consecutive regressions to trigger
   */
  consecutiveRegressions: number;
}

export interface TimeoutConfig {
  strategy: 'timeout';

  /**
   * Maximum total time for all iterations (milliseconds)
   */
  maxTotalDuration: number;

  /**
   * Maximum time per iteration (milliseconds)
   */
  maxIterationDuration?: number;
}

export interface CustomCircuitBreakerConfig {
  strategy: 'custom';

  /**
   * ID of registered custom circuit breaker
   */
  breakerId: string;

  /**
   * Configuration for custom breaker
   */
  config: Record<string, unknown>;
}

// ============================================================================
// HOOK ACTIONS
// ============================================================================

/**
 * Actions that can be executed by hooks
 */
export type HookAction =
  | CommandAction
  | NotificationAction
  | CheckpointAction
  | MetricAction
  | CustomAction;

export interface CommandAction {
  type: 'command';
  command: string;
  args?: string[];
  workingDirectory?: string;
  env?: Record<string, string>;
  timeout?: number;
}

export interface NotificationAction {
  type: 'notification';
  channel: 'log' | 'stderr' | 'custom';
  message: string;
  severity: 'info' | 'warn' | 'error';
}

export interface CheckpointAction {
  type: 'checkpoint';
  operation: 'create' | 'cleanup';
  config?: Record<string, unknown>;
}

export interface MetricAction {
  type: 'metric';
  metricName: string;
  value: number | string;
  operation: 'increment' | 'set' | 'append';
}

export interface CustomAction {
  type: 'custom';
  actionId: string;
  config: Record<string, unknown>;
}

// ============================================================================
// OVERALL HOOK CONFIGURATION
// ============================================================================

/**
 * Complete hook configuration for an iteration session
 */
export interface IterationHookConfig {
  version: string;

  /**
   * Stop hooks (validation-based completion)
   */
  stopHooks: StopHook[];

  /**
   * Pre-iteration hooks (run before each iteration)
   */
  preIterationHooks: PreIterationHook[];

  /**
   * Post-iteration hooks (run after each iteration)
   */
  postIterationHooks: PostIterationHook[];

  /**
   * Circuit breaker hooks (safety mechanisms)
   */
  circuitBreakerHooks: CircuitBreakerHook[];

  /**
   * Global hook configuration
   */
  global: {
    /**
     * Maximum total hooks that can run per iteration
     */
    maxHooksPerIteration: number;

    /**
     * Maximum total time for all hooks per iteration (milliseconds)
     */
    maxHookDuration: number;

    /**
     * Whether to run hooks in parallel (when possible)
     */
    parallelExecution: boolean;

    /**
     * Whether to continue on hook errors
     */
    continueOnError: boolean;
  };
}

// ============================================================================
// HOOK EXECUTION RESULT
// ============================================================================

/**
 * Result from executing a hook
 */
export interface HookExecutionResult {
  hookName: string;
  hookType: HookType;
  success: boolean;
  duration: number;
  timestamp: string;

  /**
   * Output from hook actions
   */
  output?: string;

  /**
   * Error if hook failed
   */
  error?: string;

  /**
   * Metadata from hook execution
   */
  metadata?: Record<string, unknown>;
}

/**
 * Report from executing all hooks for an iteration
 */
export interface HookExecutionReport {
  iterationNumber: number;
  totalHooksRun: number;
  successfulHooks: number;
  failedHooks: number;
  totalDuration: number;
  results: HookExecutionResult[];

  /**
   * Whether any stop hook was triggered
   */
  stopTriggered: boolean;

  /**
   * Stop hook that was triggered (if any)
   */
  triggeredStopHook?: string;

  /**
   * Whether any circuit breaker was triggered
   */
  circuitBreakerTriggered: boolean;

  /**
   * Circuit breaker that was triggered (if any)
   */
  triggeredCircuitBreaker?: string;
}

// ============================================================================
// HOOK REGISTRY
// ============================================================================

/**
 * Registry for custom hooks and validators
 */
export interface HookRegistry {
  /**
   * Registered custom validators
   */
  validators: Map<string, CustomValidator>;

  /**
   * Registered custom circuit breakers
   */
  circuitBreakers: Map<string, CustomCircuitBreaker>;

  /**
   * Registered custom actions
   */
  actions: Map<string, CustomActionExecutor>;
}

/**
 * Custom validator function signature
 */
export type CustomValidator = (
  context: ValidationContext
) => Promise<IterationValidationResult>;

/**
 * Custom circuit breaker function signature
 */
export type CustomCircuitBreaker = (
  context: CircuitBreakerContext
) => Promise<CircuitBreakerResult>;

/**
 * Custom action executor function signature
 */
export type CustomActionExecutor = (
  context: ActionContext,
  config: Record<string, unknown>
) => Promise<ActionResult>;

// ============================================================================
// CONTEXT TYPES
// ============================================================================

/**
 * Context passed to validation hooks
 */
export interface ValidationContext {
  taskId: string;
  iterationNumber: number;
  workingDirectory: string;
  agentOutput?: string;
  taskNotes?: string;
  latestWorkProduct?: string;
  history: IterationHistoryEntry[];
}

/**
 * Context passed to circuit breaker hooks
 */
export interface CircuitBreakerContext {
  taskId: string;
  iterationNumber: number;
  config: IterationConfig;
  history: IterationHistoryEntry[];
  startTime: string;
  currentTime: string;
}

/**
 * Context passed to action executors
 */
export interface ActionContext {
  taskId: string;
  iterationNumber: number;
  hookType: HookType;
  trigger: HookTrigger;
}

// ============================================================================
// RESULT TYPES
// ============================================================================

import type { IterationValidationResult } from './iteration-types.js';

/**
 * Result from custom circuit breaker
 */
export interface CircuitBreakerResult {
  tripped: boolean;
  reason?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Result from custom action
 */
export interface ActionResult {
  success: boolean;
  output?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

// ============================================================================
// IMPORTS FROM OTHER MODULES
// ============================================================================

import type { IterationConfig, IterationHistoryEntry } from '../types.js';
