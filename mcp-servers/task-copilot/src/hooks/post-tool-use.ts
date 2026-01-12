/**
 * PostToolUse Lifecycle Hooks
 *
 * Fires after a tool completes execution.
 * Supports:
 * - Result transformation (modify, enrich, or filter tool output)
 * - Logging (activity logging, analytics, audit trails)
 * - Error enrichment (add context to errors for better debugging)
 * - Side effects (trigger follow-up actions based on results)
 *
 * Part of the Lifecycle Hooks system (PRD-6df7cc11).
 */

// ============================================================================
// TYPES
// ============================================================================

/**
 * Hook action for post-tool processing
 */
export enum PostToolAction {
  PASSTHROUGH = 0,  // Return result unchanged
  TRANSFORM = 1,    // Transform the result
  ENRICH = 2,       // Enrich with additional data
  SUPPRESS = 3      // Suppress the result (return empty/minimal)
}

/**
 * Tool execution result context
 */
export interface ToolResultContext {
  toolName: string;
  toolInput: Record<string, unknown>;
  toolOutput: unknown;
  success: boolean;
  error?: Error;
  executionTime: number; // milliseconds
  timestamp: string;
  metadata?: Record<string, unknown>;
  // Enriched context
  sessionId?: string;
  agentId?: string;
  taskId?: string;
  iterationNumber?: number;
}

/**
 * Hook rule evaluation result
 */
export interface PostToolHookResult {
  action: PostToolAction;
  ruleName: string;
  reason: string;
  // For TRANSFORM/ENRICH actions
  transformedOutput?: unknown;
  // For logging hooks
  logEntry?: LogEntry;
  // Additional metadata
  metadata?: Record<string, unknown>;
}

/**
 * Log entry created by logging hooks
 */
export interface LogEntry {
  level: 'debug' | 'info' | 'warn' | 'error';
  message: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

/**
 * PostToolUse hook rule definition
 */
export interface PostToolUseRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  priority: number; // Higher priority rules evaluated first (1-100)
  category: 'transformation' | 'logging' | 'error' | 'analytics' | 'custom';
  evaluate: (context: ToolResultContext) => PostToolHookResult | null | Promise<PostToolHookResult | null>;
}

/**
 * Overall hook evaluation result
 */
export interface PostToolUseResult {
  finalOutput: unknown;
  transformations: PostToolHookResult[];
  logEntries: LogEntry[];
  errors: PostToolHookResult[];
  executionTime: number; // milliseconds
}

// ============================================================================
// RULE REGISTRY
// ============================================================================

const ruleRegistry: Map<string, PostToolUseRule> = new Map();

/**
 * Register a PostToolUse rule
 */
export function registerPostToolUseRule(rule: PostToolUseRule): void {
  ruleRegistry.set(rule.id, rule);
}

/**
 * Unregister a rule
 */
export function unregisterPostToolUseRule(ruleId: string): boolean {
  return ruleRegistry.delete(ruleId);
}

/**
 * Get all registered rules sorted by priority
 */
export function getPostToolUseRules(category?: PostToolUseRule['category']): PostToolUseRule[] {
  const rules = Array.from(ruleRegistry.values())
    .filter(rule => rule.enabled);

  if (category) {
    return rules
      .filter(rule => rule.category === category)
      .sort((a, b) => b.priority - a.priority);
  }

  return rules.sort((a, b) => b.priority - a.priority);
}

/**
 * Get specific rule by ID
 */
export function getPostToolUseRule(ruleId: string): PostToolUseRule | undefined {
  return ruleRegistry.get(ruleId);
}

/**
 * Enable/disable a rule
 */
export function togglePostToolUseRule(ruleId: string, enabled: boolean): boolean {
  const rule = ruleRegistry.get(ruleId);
  if (!rule) return false;

  rule.enabled = enabled;
  return true;
}

/**
 * Clear all rules
 */
export function clearAllPostToolUseRules(): number {
  const count = ruleRegistry.size;
  ruleRegistry.clear();
  return count;
}

/**
 * Get rules by category
 */
export function getRulesByCategory(): Record<string, number> {
  const counts: Record<string, number> = {
    transformation: 0,
    logging: 0,
    error: 0,
    analytics: 0,
    custom: 0
  };

  for (const rule of ruleRegistry.values()) {
    if (rule.enabled) {
      counts[rule.category]++;
    }
  }

  return counts;
}

// ============================================================================
// HOOK EVALUATION
// ============================================================================

/**
 * Evaluate all PostToolUse rules against a tool result
 */
export async function evaluatePostToolUse(
  toolName: string,
  toolInput: Record<string, unknown>,
  toolOutput: unknown,
  success: boolean,
  executionTime: number,
  error?: Error,
  metadata?: Record<string, unknown>
): Promise<PostToolUseResult> {
  const startTime = Date.now();

  const context: ToolResultContext = {
    toolName,
    toolInput,
    toolOutput,
    success,
    error,
    executionTime,
    timestamp: new Date().toISOString(),
    metadata,
    // Extract enriched context from metadata if available
    sessionId: metadata?.sessionId as string | undefined,
    agentId: metadata?.agentId as string | undefined,
    taskId: metadata?.taskId as string | undefined,
    iterationNumber: metadata?.iterationNumber as number | undefined
  };

  const transformations: PostToolHookResult[] = [];
  const logEntries: LogEntry[] = [];
  const errors: PostToolHookResult[] = [];
  let currentOutput = toolOutput;

  const rules = getPostToolUseRules();

  // Evaluate each rule in priority order
  for (const rule of rules) {
    try {
      const result = await rule.evaluate({
        ...context,
        toolOutput: currentOutput // Use potentially transformed output
      });

      if (result) {
        switch (result.action) {
          case PostToolAction.TRANSFORM:
          case PostToolAction.ENRICH:
            if (result.transformedOutput !== undefined) {
              currentOutput = result.transformedOutput;
              transformations.push(result);
            }
            break;
          case PostToolAction.SUPPRESS:
            currentOutput = null;
            transformations.push(result);
            break;
          // PASSTHROUGH - no action needed
        }

        // Collect log entries
        if (result.logEntry) {
          logEntries.push(result.logEntry);
        }
      }
    } catch (err) {
      console.error(`Error evaluating post-tool rule ${rule.id}:`, err);
      errors.push({
        action: PostToolAction.PASSTHROUGH,
        ruleName: rule.id,
        reason: `Rule evaluation failed: ${err instanceof Error ? err.message : String(err)}`,
        metadata: { error: err instanceof Error ? err.message : String(err) }
      });
    }
  }

  const evalTime = Date.now() - startTime;

  return {
    finalOutput: currentOutput,
    transformations,
    logEntries,
    errors,
    executionTime: evalTime
  };
}

// ============================================================================
// BUILT-IN RULES
// ============================================================================

/**
 * Create a basic logging rule
 * Logs all tool executions at info level
 */
export function createBasicLoggingRule(): PostToolUseRule {
  return {
    id: 'basic-logging',
    name: 'Basic Logging',
    description: 'Logs all tool executions',
    enabled: false, // Disabled by default - opt-in
    priority: 10,
    category: 'logging',
    evaluate: (context) => {
      return {
        action: PostToolAction.PASSTHROUGH,
        ruleName: 'basic-logging',
        reason: 'Logged tool execution',
        logEntry: {
          level: context.success ? 'info' : 'error',
          message: `Tool ${context.toolName} ${context.success ? 'completed' : 'failed'} in ${context.executionTime}ms`,
          data: {
            toolName: context.toolName,
            success: context.success,
            executionTime: context.executionTime,
            inputKeys: Object.keys(context.toolInput)
          },
          timestamp: context.timestamp
        }
      };
    }
  };
}

/**
 * Create an error enrichment rule
 * Adds context to error messages
 */
export function createErrorEnrichmentRule(): PostToolUseRule {
  return {
    id: 'error-enrichment',
    name: 'Error Enrichment',
    description: 'Enriches error messages with context information',
    enabled: true,
    priority: 90,
    category: 'error',
    evaluate: (context) => {
      if (context.success || !context.error) {
        return null;
      }

      // Enrich error with context
      const enrichedOutput = {
        error: true,
        message: context.error.message,
        toolName: context.toolName,
        executionTime: context.executionTime,
        timestamp: context.timestamp,
        context: {
          agentId: context.agentId,
          taskId: context.taskId,
          iterationNumber: context.iterationNumber
        },
        originalError: context.toolOutput
      };

      return {
        action: PostToolAction.ENRICH,
        ruleName: 'error-enrichment',
        reason: 'Enriched error with context',
        transformedOutput: enrichedOutput,
        logEntry: {
          level: 'error',
          message: `Tool ${context.toolName} failed: ${context.error.message}`,
          data: enrichedOutput,
          timestamp: context.timestamp
        }
      };
    }
  };
}

/**
 * Create an execution time warning rule
 * Warns when tools take longer than expected
 */
export function createSlowExecutionRule(thresholdMs: number = 5000): PostToolUseRule {
  return {
    id: 'slow-execution',
    name: 'Slow Execution Warning',
    description: `Warns when tool execution exceeds ${thresholdMs}ms`,
    enabled: true,
    priority: 50,
    category: 'analytics',
    evaluate: (context) => {
      if (context.executionTime <= thresholdMs) {
        return null;
      }

      return {
        action: PostToolAction.PASSTHROUGH,
        ruleName: 'slow-execution',
        reason: `Tool ${context.toolName} took ${context.executionTime}ms (threshold: ${thresholdMs}ms)`,
        logEntry: {
          level: 'warn',
          message: `Slow tool execution: ${context.toolName} took ${context.executionTime}ms`,
          data: {
            toolName: context.toolName,
            executionTime: context.executionTime,
            threshold: thresholdMs,
            inputSize: JSON.stringify(context.toolInput).length
          },
          timestamp: context.timestamp
        }
      };
    }
  };
}

/**
 * Create a result sanitization rule
 * Removes sensitive data from results before logging
 */
export function createResultSanitizationRule(): PostToolUseRule {
  const sensitivePatterns = [
    /password/i,
    /secret/i,
    /token/i,
    /api[_-]?key/i,
    /credential/i,
    /auth/i
  ];

  return {
    id: 'result-sanitization',
    name: 'Result Sanitization',
    description: 'Sanitizes sensitive data from tool results',
    enabled: false, // Disabled by default - opt-in
    priority: 95,
    category: 'transformation',
    evaluate: (context) => {
      if (typeof context.toolOutput !== 'object' || context.toolOutput === null) {
        return null;
      }

      const sanitize = (obj: Record<string, unknown>): Record<string, unknown> => {
        const result: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(obj)) {
          const isSensitive = sensitivePatterns.some(p => p.test(key));
          if (isSensitive) {
            result[key] = '[REDACTED]';
          } else if (typeof value === 'object' && value !== null) {
            result[key] = sanitize(value as Record<string, unknown>);
          } else {
            result[key] = value;
          }
        }
        return result;
      };

      const sanitized = sanitize(context.toolOutput as Record<string, unknown>);

      return {
        action: PostToolAction.TRANSFORM,
        ruleName: 'result-sanitization',
        reason: 'Sanitized sensitive data from result',
        transformedOutput: sanitized
      };
    }
  };
}

/**
 * Create an activity tracking rule
 * Records tool usage for analytics
 */
export function createActivityTrackingRule(): PostToolUseRule {
  // In-memory activity buffer (would be persisted in production)
  const activities: Array<{
    toolName: string;
    success: boolean;
    executionTime: number;
    timestamp: string;
  }> = [];

  return {
    id: 'activity-tracking',
    name: 'Activity Tracking',
    description: 'Tracks tool usage for analytics',
    enabled: false, // Disabled by default - opt-in
    priority: 5,
    category: 'analytics',
    evaluate: (context) => {
      activities.push({
        toolName: context.toolName,
        success: context.success,
        executionTime: context.executionTime,
        timestamp: context.timestamp
      });

      // Keep only last 1000 activities
      while (activities.length > 1000) {
        activities.shift();
      }

      return {
        action: PostToolAction.PASSTHROUGH,
        ruleName: 'activity-tracking',
        reason: 'Tracked tool activity',
        metadata: {
          totalActivities: activities.length,
          recentSuccess: activities.slice(-10).filter(a => a.success).length,
          recentFailures: activities.slice(-10).filter(a => !a.success).length
        }
      };
    }
  };
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize PostToolUse hook system with default rules
 */
export function initializePostToolUseHooks(): void {
  // Register built-in rules
  registerPostToolUseRule(createBasicLoggingRule());
  registerPostToolUseRule(createErrorEnrichmentRule());
  registerPostToolUseRule(createSlowExecutionRule(5000));
  registerPostToolUseRule(createResultSanitizationRule());
  registerPostToolUseRule(createActivityTrackingRule());
}
