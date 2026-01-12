/**
 * PreToolUse Lifecycle Hooks
 *
 * Intercepts and validates tool calls before execution.
 * Supports:
 * - Pre-execution validation (security, permissions)
 * - Argument preprocessing (transformation, enrichment)
 * - Permission checks
 * - Custom rule registration
 *
 * Part of the Lifecycle Hooks system (PRD-6df7cc11).
 */

// ============================================================================
// TYPES
// ============================================================================

/**
 * Hook action levels
 */
export enum HookAction {
  ALLOW = 0,    // Tool call is safe, proceed
  WARN = 1,     // Potential issue, but allow with warning
  BLOCK = 2,    // Issue detected, prevent execution
  TRANSFORM = 3 // Transform arguments and continue
}

/**
 * Tool call context provided to hooks
 */
export interface ToolCallContext {
  toolName: string;
  toolInput: Record<string, unknown>;
  timestamp: string;
  metadata?: Record<string, unknown>;
  // Enriched context
  sessionId?: string;
  agentId?: string;
  taskId?: string;
  iterationNumber?: number;
}

/**
 * Rule evaluation result
 */
export interface HookRuleResult {
  action: HookAction;
  ruleName: string;
  reason: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  matchedPattern?: string;
  recommendation?: string;
  // For TRANSFORM action
  transformedInput?: Record<string, unknown>;
}

/**
 * Hook rule definition
 */
export interface PreToolUseRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  priority: number; // Higher priority rules evaluated first (1-100)
  category: 'security' | 'validation' | 'preprocessing' | 'permission' | 'custom';
  evaluate: (context: ToolCallContext) => HookRuleResult | null | Promise<HookRuleResult | null>;
}

/**
 * Hook evaluation result
 */
export interface PreToolUseResult {
  allowed: boolean;
  action: HookAction;
  violations: HookRuleResult[];
  warnings: HookRuleResult[];
  transformations: HookRuleResult[];
  finalInput: Record<string, unknown>;
  executionTime: number; // milliseconds
}

// ============================================================================
// BACKWARD COMPATIBILITY ALIASES
// ============================================================================

/**
 * @deprecated Use HookAction instead
 */
export const SecurityAction = HookAction;
export type SecurityAction = HookAction;

/**
 * @deprecated Use HookRuleResult instead
 */
export type SecurityRuleResult = HookRuleResult;

/**
 * @deprecated Use PreToolUseRule instead
 */
export type SecurityRule = PreToolUseRule;

// ============================================================================
// RULE REGISTRY
// ============================================================================

const ruleRegistry: Map<string, PreToolUseRule> = new Map();

/**
 * Register a PreToolUse rule
 */
export function registerPreToolUseRule(rule: PreToolUseRule): void {
  ruleRegistry.set(rule.id, rule);
}

/**
 * Register a security rule (alias for backward compatibility)
 */
export function registerSecurityRule(rule: PreToolUseRule): void {
  registerPreToolUseRule(rule);
}

/**
 * Unregister a rule
 */
export function unregisterPreToolUseRule(ruleId: string): boolean {
  return ruleRegistry.delete(ruleId);
}

/**
 * Unregister a security rule (alias for backward compatibility)
 */
export function unregisterSecurityRule(ruleId: string): boolean {
  return unregisterPreToolUseRule(ruleId);
}

/**
 * Get all registered rules sorted by priority
 */
export function getPreToolUseRules(category?: PreToolUseRule['category']): PreToolUseRule[] {
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
 * Get all security rules (alias for backward compatibility)
 */
export function getSecurityRules(): PreToolUseRule[] {
  return getPreToolUseRules('security');
}

/**
 * Get specific rule by ID
 */
export function getPreToolUseRule(ruleId: string): PreToolUseRule | undefined {
  return ruleRegistry.get(ruleId);
}

/**
 * Get specific security rule (alias for backward compatibility)
 */
export function getSecurityRule(ruleId: string): PreToolUseRule | undefined {
  return getPreToolUseRule(ruleId);
}

/**
 * Enable/disable a rule
 */
export function togglePreToolUseRule(ruleId: string, enabled: boolean): boolean {
  const rule = ruleRegistry.get(ruleId);
  if (!rule) return false;

  rule.enabled = enabled;
  return true;
}

/**
 * Toggle security rule (alias for backward compatibility)
 */
export function toggleSecurityRule(ruleId: string, enabled: boolean): boolean {
  return togglePreToolUseRule(ruleId, enabled);
}

/**
 * Clear all rules
 */
export function clearAllRules(): number {
  const count = ruleRegistry.size;
  ruleRegistry.clear();
  return count;
}

/**
 * Get rules by category
 */
export function getRulesByCategory(): Record<string, number> {
  const counts: Record<string, number> = {
    security: 0,
    validation: 0,
    preprocessing: 0,
    permission: 0,
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
 * Evaluate all PreToolUse rules against a tool call
 */
export async function evaluatePreToolUse(
  toolName: string,
  toolInput: Record<string, unknown>,
  metadata?: Record<string, unknown>
): Promise<PreToolUseResult> {
  const startTime = Date.now();

  const context: ToolCallContext = {
    toolName,
    toolInput,
    timestamp: new Date().toISOString(),
    metadata,
    // Extract enriched context from metadata if available
    sessionId: metadata?.sessionId as string | undefined,
    agentId: metadata?.agentId as string | undefined,
    taskId: metadata?.taskId as string | undefined,
    iterationNumber: metadata?.iterationNumber as number | undefined
  };

  const violations: HookRuleResult[] = [];
  const warnings: HookRuleResult[] = [];
  const transformations: HookRuleResult[] = [];
  let currentInput = { ...toolInput };

  const rules = getPreToolUseRules();

  // Evaluate each rule in priority order
  for (const rule of rules) {
    try {
      const result = await rule.evaluate({
        ...context,
        toolInput: currentInput // Use potentially transformed input
      });

      if (result) {
        switch (result.action) {
          case HookAction.BLOCK:
            violations.push(result);
            break;
          case HookAction.WARN:
            warnings.push(result);
            break;
          case HookAction.TRANSFORM:
            if (result.transformedInput) {
              currentInput = result.transformedInput;
              transformations.push(result);
            }
            break;
          // ALLOW - no action needed
        }
      }
    } catch (error) {
      console.error(`Error evaluating rule ${rule.id}:`, error);
      // Don't let rule errors block execution
    }
  }

  const executionTime = Date.now() - startTime;
  const allowed = violations.length === 0;
  const action = violations.length > 0
    ? HookAction.BLOCK
    : warnings.length > 0
    ? HookAction.WARN
    : transformations.length > 0
    ? HookAction.TRANSFORM
    : HookAction.ALLOW;

  return {
    allowed,
    action,
    violations,
    warnings,
    transformations,
    finalInput: currentInput,
    executionTime
  };
}

/**
 * Test rules without executing (for dry-run testing)
 */
export async function testPreToolUseRules(
  toolName: string,
  toolInput: Record<string, unknown>
): Promise<PreToolUseResult> {
  return evaluatePreToolUse(toolName, toolInput, { dryRun: true });
}

/**
 * Test security rules (alias for backward compatibility)
 */
export async function testSecurityRules(
  toolName: string,
  toolInput: Record<string, unknown>
): Promise<PreToolUseResult> {
  return testPreToolUseRules(toolName, toolInput);
}

// ============================================================================
// BUILT-IN PREPROCESSING RULES
// ============================================================================

/**
 * Create a path normalization rule
 * Normalizes file paths to absolute paths
 */
export function createPathNormalizationRule(): PreToolUseRule {
  return {
    id: 'path-normalization',
    name: 'Path Normalization',
    description: 'Normalizes relative file paths to absolute paths',
    enabled: true,
    priority: 95,
    category: 'preprocessing',
    evaluate: (context) => {
      const input = context.toolInput;
      const pathFields = ['file_path', 'path', 'filePath'];
      let transformed = false;
      const newInput = { ...input };

      for (const field of pathFields) {
        const value = input[field];
        if (typeof value === 'string' && !value.startsWith('/')) {
          // Normalize relative path
          const cwd = process.cwd();
          newInput[field] = `${cwd}/${value}`;
          transformed = true;
        }
      }

      if (transformed) {
        return {
          action: HookAction.TRANSFORM,
          ruleName: 'path-normalization',
          reason: 'Normalized relative path to absolute path',
          severity: 'low',
          transformedInput: newInput
        };
      }

      return null;
    }
  };
}

/**
 * Create a metadata enrichment rule
 * Adds timestamp and context to tool inputs
 */
export function createMetadataEnrichmentRule(): PreToolUseRule {
  return {
    id: 'metadata-enrichment',
    name: 'Metadata Enrichment',
    description: 'Adds timestamp and context metadata to tool inputs',
    enabled: false, // Disabled by default - opt-in
    priority: 90,
    category: 'preprocessing',
    evaluate: (context) => {
      if (context.toolName === 'work_product_store') {
        const metadata = (context.toolInput.metadata as Record<string, unknown>) || {};
        return {
          action: HookAction.TRANSFORM,
          ruleName: 'metadata-enrichment',
          reason: 'Added enriched metadata',
          severity: 'low',
          transformedInput: {
            ...context.toolInput,
            metadata: {
              ...metadata,
              _enrichedAt: context.timestamp,
              _agentId: context.agentId,
              _taskId: context.taskId
            }
          }
        };
      }
      return null;
    }
  };
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Extract string content from tool input for pattern matching
 */
export function extractStringContent(input: Record<string, unknown>): string[] {
  const content: string[] = [];

  function extract(obj: unknown): void {
    if (typeof obj === 'string') {
      content.push(obj);
    } else if (Array.isArray(obj)) {
      obj.forEach(extract);
    } else if (obj !== null && typeof obj === 'object') {
      Object.values(obj as Record<string, unknown>).forEach(extract);
    }
  }

  extract(input);
  return content;
}

/**
 * Check if tool call involves file writes
 */
export function isFileWriteTool(toolName: string): boolean {
  const writeTools = ['Edit', 'Write', 'work_product_store'];
  return writeTools.includes(toolName);
}

/**
 * Check if tool call involves command execution
 */
export function isCommandExecutionTool(toolName: string): boolean {
  const commandTools = ['Bash', 'Run', 'Execute'];
  return commandTools.includes(toolName);
}

/**
 * Extract file paths from tool input
 */
export function extractFilePaths(input: Record<string, unknown>): string[] {
  const paths: string[] = [];

  if (typeof input.file_path === 'string') {
    paths.push(input.file_path);
  }
  if (typeof input.path === 'string') {
    paths.push(input.path);
  }
  if (Array.isArray(input.files)) {
    paths.push(...input.files.filter((f): f is string => typeof f === 'string'));
  }

  return paths;
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize PreToolUse hook system with default preprocessing rules
 */
export function initializePreToolUseHooks(): void {
  // Register built-in preprocessing rules
  registerPreToolUseRule(createPathNormalizationRule());
  registerPreToolUseRule(createMetadataEnrichmentRule());
}
