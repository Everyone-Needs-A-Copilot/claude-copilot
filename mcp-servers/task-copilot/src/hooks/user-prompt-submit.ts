/**
 * UserPromptSubmit Lifecycle Hooks
 *
 * Fires before user prompt is processed.
 * Supports:
 * - Prompt preprocessing (transformation, cleanup)
 * - Context injection (add relevant context to prompt)
 * - Skill evaluation triggers (signal skill detection system)
 * - Input validation (check for required patterns)
 *
 * Part of the Lifecycle Hooks system (PRD-6df7cc11).
 */

// ============================================================================
// TYPES
// ============================================================================

/**
 * Hook action for prompt processing
 */
export enum PromptAction {
  PASSTHROUGH = 0,  // Process prompt unchanged
  TRANSFORM = 1,    // Transform the prompt
  INJECT = 2,       // Inject context into prompt
  REJECT = 3        // Reject the prompt (requires explicit handling)
}

/**
 * User prompt context
 */
export interface PromptContext {
  prompt: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
  // Enriched context
  sessionId?: string;
  agentId?: string;
  taskId?: string;
  iterationNumber?: number;
  // History context
  previousPrompts?: string[];
  previousToolCalls?: Array<{
    toolName: string;
    timestamp: string;
  }>;
  // File context
  activeFiles?: string[];
  recentFiles?: string[];
}

/**
 * Hook rule evaluation result
 */
export interface PromptHookResult {
  action: PromptAction;
  ruleName: string;
  reason: string;
  // For TRANSFORM/INJECT actions
  transformedPrompt?: string;
  injectedContext?: string;
  // Skill evaluation signals
  skillSignals?: SkillSignal[];
  // Additional metadata
  metadata?: Record<string, unknown>;
}

/**
 * Signal to skill evaluation system
 */
export interface SkillSignal {
  type: 'file_pattern' | 'keyword' | 'intent' | 'explicit';
  pattern: string;
  confidence: number; // 0-1
  suggestedSkill?: string;
}

/**
 * UserPromptSubmit hook rule definition
 */
export interface UserPromptSubmitRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  priority: number; // Higher priority rules evaluated first (1-100)
  category: 'preprocessing' | 'context' | 'skill' | 'validation' | 'custom';
  evaluate: (context: PromptContext) => PromptHookResult | null | Promise<PromptHookResult | null>;
}

/**
 * Overall hook evaluation result
 */
export interface UserPromptSubmitResult {
  finalPrompt: string;
  injectedContext: string[];
  transformations: PromptHookResult[];
  skillSignals: SkillSignal[];
  rejected: boolean;
  rejectReason?: string;
  executionTime: number; // milliseconds
}

// ============================================================================
// RULE REGISTRY
// ============================================================================

const ruleRegistry: Map<string, UserPromptSubmitRule> = new Map();

/**
 * Register a UserPromptSubmit rule
 */
export function registerUserPromptSubmitRule(rule: UserPromptSubmitRule): void {
  ruleRegistry.set(rule.id, rule);
}

/**
 * Unregister a rule
 */
export function unregisterUserPromptSubmitRule(ruleId: string): boolean {
  return ruleRegistry.delete(ruleId);
}

/**
 * Get all registered rules sorted by priority
 */
export function getUserPromptSubmitRules(category?: UserPromptSubmitRule['category']): UserPromptSubmitRule[] {
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
export function getUserPromptSubmitRule(ruleId: string): UserPromptSubmitRule | undefined {
  return ruleRegistry.get(ruleId);
}

/**
 * Enable/disable a rule
 */
export function toggleUserPromptSubmitRule(ruleId: string, enabled: boolean): boolean {
  const rule = ruleRegistry.get(ruleId);
  if (!rule) return false;

  rule.enabled = enabled;
  return true;
}

/**
 * Clear all rules
 */
export function clearAllUserPromptSubmitRules(): number {
  const count = ruleRegistry.size;
  ruleRegistry.clear();
  return count;
}

/**
 * Get rules by category
 */
export function getRulesByCategory(): Record<string, number> {
  const counts: Record<string, number> = {
    preprocessing: 0,
    context: 0,
    skill: 0,
    validation: 0,
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
 * Evaluate all UserPromptSubmit rules against a prompt
 */
export async function evaluateUserPromptSubmit(
  prompt: string,
  metadata?: Record<string, unknown>,
  previousPrompts?: string[],
  activeFiles?: string[]
): Promise<UserPromptSubmitResult> {
  const startTime = Date.now();

  const context: PromptContext = {
    prompt,
    timestamp: new Date().toISOString(),
    metadata,
    // Extract enriched context from metadata if available
    sessionId: metadata?.sessionId as string | undefined,
    agentId: metadata?.agentId as string | undefined,
    taskId: metadata?.taskId as string | undefined,
    iterationNumber: metadata?.iterationNumber as number | undefined,
    previousPrompts,
    activeFiles
  };

  const transformations: PromptHookResult[] = [];
  const injectedContext: string[] = [];
  const allSkillSignals: SkillSignal[] = [];
  let currentPrompt = prompt;
  let rejected = false;
  let rejectReason: string | undefined;

  const rules = getUserPromptSubmitRules();

  // Evaluate each rule in priority order
  for (const rule of rules) {
    if (rejected) break; // Stop if prompt was rejected

    try {
      const result = await rule.evaluate({
        ...context,
        prompt: currentPrompt // Use potentially transformed prompt
      });

      if (result) {
        switch (result.action) {
          case PromptAction.TRANSFORM:
            if (result.transformedPrompt !== undefined) {
              currentPrompt = result.transformedPrompt;
              transformations.push(result);
            }
            break;
          case PromptAction.INJECT:
            if (result.injectedContext) {
              injectedContext.push(result.injectedContext);
              transformations.push(result);
            }
            break;
          case PromptAction.REJECT:
            rejected = true;
            rejectReason = result.reason;
            transformations.push(result);
            break;
          // PASSTHROUGH - no action needed
        }

        // Collect skill signals
        if (result.skillSignals) {
          allSkillSignals.push(...result.skillSignals);
        }
      }
    } catch (err) {
      console.error(`Error evaluating prompt rule ${rule.id}:`, err);
      // Don't let rule errors block prompt processing
    }
  }

  // Apply injected context to prompt
  if (injectedContext.length > 0 && !rejected) {
    currentPrompt = `${injectedContext.join('\n\n')}\n\n${currentPrompt}`;
  }

  const evalTime = Date.now() - startTime;

  return {
    finalPrompt: currentPrompt,
    injectedContext,
    transformations,
    skillSignals: allSkillSignals,
    rejected,
    rejectReason,
    executionTime: evalTime
  };
}

// ============================================================================
// BUILT-IN RULES
// ============================================================================

/**
 * Create a whitespace normalization rule
 * Cleans up excessive whitespace in prompts
 */
export function createWhitespaceNormalizationRule(): UserPromptSubmitRule {
  return {
    id: 'whitespace-normalization',
    name: 'Whitespace Normalization',
    description: 'Cleans up excessive whitespace in prompts',
    enabled: false, // Disabled by default
    priority: 95,
    category: 'preprocessing',
    evaluate: (context) => {
      const normalized = context.prompt
        .replace(/\r\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .replace(/[ \t]+$/gm, '')
        .trim();

      if (normalized !== context.prompt) {
        return {
          action: PromptAction.TRANSFORM,
          ruleName: 'whitespace-normalization',
          reason: 'Normalized whitespace',
          transformedPrompt: normalized
        };
      }

      return null;
    }
  };
}

/**
 * Create a file pattern detection rule for skill signals
 * Detects file patterns in prompt and generates skill signals
 */
export function createFilePatternDetectionRule(): UserPromptSubmitRule {
  const filePatterns = [
    { pattern: /\.tsx?$/i, skill: 'typescript', confidence: 0.8 },
    { pattern: /\.jsx?$/i, skill: 'javascript', confidence: 0.8 },
    { pattern: /\.py$/i, skill: 'python', confidence: 0.8 },
    { pattern: /\.rs$/i, skill: 'rust', confidence: 0.8 },
    { pattern: /\.go$/i, skill: 'golang', confidence: 0.8 },
    { pattern: /\.md$/i, skill: 'documentation', confidence: 0.6 },
    { pattern: /\.ya?ml$/i, skill: 'yaml', confidence: 0.7 },
    { pattern: /\.json$/i, skill: 'json', confidence: 0.7 },
    { pattern: /\.(spec|test)\.(ts|js|tsx|jsx)$/i, skill: 'testing', confidence: 0.9 },
    { pattern: /Dockerfile/i, skill: 'docker', confidence: 0.9 },
    { pattern: /\.sql$/i, skill: 'sql', confidence: 0.8 }
  ];

  return {
    id: 'file-pattern-detection',
    name: 'File Pattern Detection',
    description: 'Detects file patterns and generates skill signals',
    enabled: true,
    priority: 80,
    category: 'skill',
    evaluate: (context) => {
      const signals: SkillSignal[] = [];

      // Check prompt for file references
      const fileMatches = context.prompt.match(/[a-zA-Z0-9_\-./]+\.[a-zA-Z]+/g) || [];

      for (const file of fileMatches) {
        for (const { pattern, skill, confidence } of filePatterns) {
          if (pattern.test(file)) {
            signals.push({
              type: 'file_pattern',
              pattern: file,
              confidence,
              suggestedSkill: skill
            });
            break;
          }
        }
      }

      // Also check active files
      if (context.activeFiles) {
        for (const file of context.activeFiles) {
          for (const { pattern, skill, confidence } of filePatterns) {
            if (pattern.test(file)) {
              // Boost confidence for active files
              signals.push({
                type: 'file_pattern',
                pattern: file,
                confidence: Math.min(confidence + 0.1, 1),
                suggestedSkill: skill
              });
              break;
            }
          }
        }
      }

      if (signals.length > 0) {
        return {
          action: PromptAction.PASSTHROUGH,
          ruleName: 'file-pattern-detection',
          reason: `Detected ${signals.length} file patterns`,
          skillSignals: signals
        };
      }

      return null;
    }
  };
}

/**
 * Create a keyword detection rule for skill signals
 * Detects keywords in prompt and generates skill signals
 */
export function createKeywordDetectionRule(): UserPromptSubmitRule {
  const keywordPatterns = [
    { keywords: ['test', 'spec', 'unit', 'integration', 'e2e', 'coverage'], skill: 'testing', confidence: 0.7 },
    { keywords: ['deploy', 'ci', 'cd', 'pipeline', 'docker', 'kubernetes'], skill: 'devops', confidence: 0.7 },
    { keywords: ['security', 'auth', 'permission', 'vulnerability', 'xss', 'injection'], skill: 'security', confidence: 0.8 },
    { keywords: ['api', 'rest', 'graphql', 'endpoint', 'route'], skill: 'api-design', confidence: 0.6 },
    { keywords: ['database', 'sql', 'query', 'schema', 'migration'], skill: 'database', confidence: 0.7 },
    { keywords: ['component', 'ui', 'css', 'style', 'layout', 'responsive'], skill: 'ui', confidence: 0.6 },
    { keywords: ['refactor', 'clean', 'optimize', 'performance'], skill: 'refactoring', confidence: 0.6 },
    { keywords: ['document', 'readme', 'comment', 'jsdoc', 'docstring'], skill: 'documentation', confidence: 0.7 }
  ];

  return {
    id: 'keyword-detection',
    name: 'Keyword Detection',
    description: 'Detects keywords and generates skill signals',
    enabled: true,
    priority: 75,
    category: 'skill',
    evaluate: (context) => {
      const signals: SkillSignal[] = [];
      const promptLower = context.prompt.toLowerCase();

      for (const { keywords, skill, confidence } of keywordPatterns) {
        const matchCount = keywords.filter(kw => promptLower.includes(kw)).length;
        if (matchCount > 0) {
          // Boost confidence based on number of keyword matches
          const boostedConfidence = Math.min(confidence + (matchCount - 1) * 0.1, 0.95);
          signals.push({
            type: 'keyword',
            pattern: keywords.filter(kw => promptLower.includes(kw)).join(', '),
            confidence: boostedConfidence,
            suggestedSkill: skill
          });
        }
      }

      if (signals.length > 0) {
        return {
          action: PromptAction.PASSTHROUGH,
          ruleName: 'keyword-detection',
          reason: `Detected ${signals.length} keyword patterns`,
          skillSignals: signals
        };
      }

      return null;
    }
  };
}

/**
 * Create a task context injection rule
 * Injects current task context into prompts when task ID is available
 */
export function createTaskContextInjectionRule(): UserPromptSubmitRule {
  return {
    id: 'task-context-injection',
    name: 'Task Context Injection',
    description: 'Injects current task context into prompts',
    enabled: false, // Disabled by default - requires task integration
    priority: 60,
    category: 'context',
    evaluate: (context) => {
      if (!context.taskId) {
        return null;
      }

      const injectedContext = `[Current Task: ${context.taskId}]${context.iterationNumber ? ` [Iteration: ${context.iterationNumber}]` : ''}`;

      return {
        action: PromptAction.INJECT,
        ruleName: 'task-context-injection',
        reason: 'Injected task context',
        injectedContext
      };
    }
  };
}

/**
 * Create an explicit skill request detection rule
 * Detects when user explicitly requests a skill (e.g., "use the testing skill")
 */
export function createExplicitSkillRequestRule(): UserPromptSubmitRule {
  return {
    id: 'explicit-skill-request',
    name: 'Explicit Skill Request Detection',
    description: 'Detects explicit skill requests in prompts',
    enabled: true,
    priority: 100, // Highest priority - explicit requests should be honored
    category: 'skill',
    evaluate: (context) => {
      // Match patterns like "use the X skill" or "apply X skill"
      const patterns = [
        /use\s+(?:the\s+)?(\w+)\s+skill/i,
        /apply\s+(?:the\s+)?(\w+)\s+skill/i,
        /with\s+(\w+)\s+skill/i,
        /@skill[:\s]+(\w+)/i,
        /load\s+skill[:\s]+(\w+)/i
      ];

      const signals: SkillSignal[] = [];

      for (const pattern of patterns) {
        const match = context.prompt.match(pattern);
        if (match && match[1]) {
          signals.push({
            type: 'explicit',
            pattern: match[0],
            confidence: 1.0, // Explicit requests have full confidence
            suggestedSkill: match[1].toLowerCase()
          });
        }
      }

      if (signals.length > 0) {
        return {
          action: PromptAction.PASSTHROUGH,
          ruleName: 'explicit-skill-request',
          reason: `Detected ${signals.length} explicit skill request(s)`,
          skillSignals: signals
        };
      }

      return null;
    }
  };
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize UserPromptSubmit hook system with default rules
 */
export function initializeUserPromptSubmitHooks(): void {
  // Register built-in rules
  registerUserPromptSubmitRule(createWhitespaceNormalizationRule());
  registerUserPromptSubmitRule(createFilePatternDetectionRule());
  registerUserPromptSubmitRule(createKeywordDetectionRule());
  registerUserPromptSubmitRule(createTaskContextInjectionRule());
  registerUserPromptSubmitRule(createExplicitSkillRequestRule());
}
