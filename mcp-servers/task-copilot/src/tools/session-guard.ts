/**
 * Session Guard tool implementation
 *
 * Helps enforce main session guardrails to prevent context bloat.
 */

import type { DatabaseClient } from '../database.js';

/**
 * Session Guard Input
 */
export interface SessionGuardInput {
  action: 'check' | 'report';
  context?: {
    filesRead?: number;
    codeWritten?: boolean;
    agentUsed?: string;
    responseTokens?: number;
  };
}

/**
 * Session Guard Output
 */
export interface SessionGuardOutput {
  allowed: boolean;
  violations: string[];
  warnings: string[];
  suggestions: string[];
}

/**
 * Generic agents that bypass Task Copilot
 */
const GENERIC_AGENTS = ['Explore', 'Plan', 'general-purpose'];

/**
 * Framework agents that integrate with Task Copilot
 */
const FRAMEWORK_AGENTS = [
  'agent-ta',   // Tech Architect
  'agent-me',   // Engineer
  'agent-qa',   // QA Engineer
  'agent-sec',  // Security
  'agent-doc',  // Documentation
  'agent-do',   // DevOps
  'agent-sd',   // Service Designer
  'agent-uxd',  // UX Designer
  'agent-uids', // UI Designer
  'agent-uid',  // UI Developer
  'agent-cw',   // Copywriter
  'agent-kc'    // Knowledge Copilot
];

/**
 * Guardrail limits
 */
const LIMITS = {
  MAX_FILES_READ: 3,
  RESPONSE_TOKEN_WARNING: 500,
  RESPONSE_TOKEN_ERROR: 1000
};

/**
 * Perform session guard check
 */
export function sessionGuard(
  db: DatabaseClient,
  input: SessionGuardInput
): SessionGuardOutput {
  if (input.action === 'report') {
    return generateReport(db, input.context);
  }

  // Check action
  return performCheck(input.context);
}

/**
 * Perform guardrail checks
 */
function performCheck(context?: SessionGuardInput['context']): SessionGuardOutput {
  const violations: string[] = [];
  const warnings: string[] = [];
  const suggestions: string[] = [];

  if (!context) {
    return {
      allowed: true,
      violations,
      warnings,
      suggestions: ['Provide context for meaningful guardrail checks']
    };
  }

  // Rule 1: filesRead > 3 → violation
  if (context.filesRead !== undefined && context.filesRead > LIMITS.MAX_FILES_READ) {
    violations.push(
      `Exceeded ${LIMITS.MAX_FILES_READ}-file limit (read: ${context.filesRead}). Delegate to framework agent.`
    );
    suggestions.push(
      'Use @agent-me for code implementation',
      'Use @agent-ta for architecture analysis',
      'Use @agent-doc for documentation review'
    );
  }

  // Rule 2: codeWritten === true → violation
  if (context.codeWritten === true) {
    violations.push('Code should be written by @agent-me, not main session.');
    suggestions.push('Delegate code implementation to @agent-me');
  }

  // Rule 3: responseTokens > 500 → warning, > 1000 → violation
  if (context.responseTokens !== undefined) {
    if (context.responseTokens > LIMITS.RESPONSE_TOKEN_ERROR) {
      violations.push(
        `Response exceeds ${LIMITS.RESPONSE_TOKEN_ERROR} tokens (estimated: ${context.responseTokens}). Store details in work product.`
      );
      suggestions.push(
        'Store detailed analysis in work product using work_product_store',
        'Return only summary (~100 tokens) to main session'
      );
    } else if (context.responseTokens > LIMITS.RESPONSE_TOKEN_WARNING) {
      warnings.push(
        `Response exceeds ${LIMITS.RESPONSE_TOKEN_WARNING} tokens (estimated: ${context.responseTokens}). Consider storing in work product.`
      );
      suggestions.push('Keep main session responses concise (<500 tokens)');
    }
  }

  // Rule 4: agentUsed in generic agents → violation
  if (context.agentUsed && GENERIC_AGENTS.includes(context.agentUsed)) {
    violations.push(
      `Generic agent "${context.agentUsed}" bypasses Task Copilot. Use framework agents.`
    );
    suggestions.push(
      'Replace "Explore" with @agent-ta or @agent-me',
      'Replace "Plan" with @agent-ta for PRD creation',
      'Replace "general-purpose" with specific framework agent'
    );
  }

  // Provide positive feedback if using framework agents
  if (context.agentUsed && FRAMEWORK_AGENTS.includes(context.agentUsed)) {
    suggestions.push(`Good: Using framework agent ${context.agentUsed} (integrates with Task Copilot)`);
  }

  const allowed = violations.length === 0;

  return {
    allowed,
    violations,
    warnings,
    suggestions
  };
}

/**
 * Generate session guard report
 */
function generateReport(
  db: DatabaseClient,
  context?: SessionGuardInput['context']
): SessionGuardOutput {
  const violations: string[] = [];
  const warnings: string[] = [];
  const suggestions: string[] = [];

  // Get current initiative stats
  const currentInitiative = db.getCurrentInitiative();
  if (!currentInitiative) {
    suggestions.push('No active initiative. Run /protocol to start work.');
    return {
      allowed: true,
      violations,
      warnings,
      suggestions
    };
  }

  // Get task statistics
  const stats = db.getStats();

  suggestions.push(
    `Current initiative: ${currentInitiative.title}`,
    `Total tasks: ${stats.taskCount}`,
    `Work products: ${stats.workProductCount}`
  );

  // Perform context check if provided
  if (context) {
    const checkResult = performCheck(context);
    violations.push(...checkResult.violations);
    warnings.push(...checkResult.warnings);
    suggestions.push(...checkResult.suggestions);
  }

  // Add general best practices
  suggestions.push(
    '',
    '=== Session Guardrails ===',
    '1. Read max 3 files in main session',
    '2. Delegate code to @agent-me',
    '3. Keep responses <500 tokens',
    '4. Use framework agents only',
    '5. Store details in work products'
  );

  return {
    allowed: violations.length === 0,
    violations,
    warnings,
    suggestions
  };
}

/**
 * Helper: Estimate token count from character count
 * Rough estimate: 1 token ≈ 4 characters
 */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}
