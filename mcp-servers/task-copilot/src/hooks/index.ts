/**
 * Lifecycle Hooks System - Index
 *
 * Unified export for all lifecycle hooks:
 * - PreToolUse: Before tool execution
 * - PostToolUse: After tool execution
 * - UserPromptSubmit: Before prompt processing
 * - Stop: On completion signal (existing, in stop-hooks.ts)
 * - AutoCheckpoint: Automatic checkpoint creation
 *
 * Part of the Lifecycle Hooks system (PRD-6df7cc11).
 */

// ============================================================================
// PreToolUse Hook Exports
// ============================================================================

export {
  // Types
  HookAction,
  type ToolCallContext,
  type HookRuleResult,
  type PreToolUseRule,
  type PreToolUseResult,
  // Backward compatibility aliases
  SecurityAction,
  type SecurityRuleResult,
  type SecurityRule,
  // Registry functions
  registerPreToolUseRule,
  registerSecurityRule,
  unregisterPreToolUseRule,
  unregisterSecurityRule,
  getPreToolUseRules,
  getSecurityRules,
  getPreToolUseRule,
  getSecurityRule,
  togglePreToolUseRule,
  toggleSecurityRule,
  clearAllRules as clearAllPreToolUseRules,
  getRulesByCategory as getPreToolUseRulesByCategory,
  // Evaluation
  evaluatePreToolUse,
  testPreToolUseRules,
  testSecurityRules,
  // Built-in rules
  createPathNormalizationRule,
  createMetadataEnrichmentRule,
  // Helpers
  extractStringContent,
  isFileWriteTool,
  isCommandExecutionTool,
  extractFilePaths,
  // Initialization
  initializePreToolUseHooks
} from './pre-tool-use.js';

// ============================================================================
// PostToolUse Hook Exports
// ============================================================================

export {
  // Types
  PostToolAction,
  type ToolResultContext,
  type PostToolHookResult,
  type LogEntry,
  type PostToolUseRule,
  type PostToolUseResult,
  // Registry functions
  registerPostToolUseRule,
  unregisterPostToolUseRule,
  getPostToolUseRules,
  getPostToolUseRule,
  togglePostToolUseRule,
  clearAllPostToolUseRules,
  getRulesByCategory as getPostToolUseRulesByCategory,
  // Evaluation
  evaluatePostToolUse,
  // Built-in rules
  createBasicLoggingRule,
  createErrorEnrichmentRule,
  createSlowExecutionRule,
  createResultSanitizationRule,
  createActivityTrackingRule,
  // Initialization
  initializePostToolUseHooks
} from './post-tool-use.js';

// ============================================================================
// UserPromptSubmit Hook Exports
// ============================================================================

export {
  // Types
  PromptAction,
  type PromptContext,
  type PromptHookResult,
  type SkillSignal,
  type UserPromptSubmitRule,
  type UserPromptSubmitResult,
  // Registry functions
  registerUserPromptSubmitRule,
  unregisterUserPromptSubmitRule,
  getUserPromptSubmitRules,
  getUserPromptSubmitRule,
  toggleUserPromptSubmitRule,
  clearAllUserPromptSubmitRules,
  getRulesByCategory as getUserPromptSubmitRulesByCategory,
  // Evaluation
  evaluateUserPromptSubmit,
  // Built-in rules
  createWhitespaceNormalizationRule,
  createFilePatternDetectionRule,
  createKeywordDetectionRule,
  createTaskContextInjectionRule,
  createExplicitSkillRequestRule,
  // Initialization
  initializeUserPromptSubmitHooks
} from './user-prompt-submit.js';

// ============================================================================
// Auto-Checkpoint Hook Exports
// ============================================================================

export {
  type AutoCheckpointConfig,
  DEFAULT_AUTO_CHECKPOINT_CONFIG,
  AutoCheckpointHooks,
  initializeAutoCheckpointHooks,
  getAutoCheckpointHooks
} from './auto-checkpoint.js';

// ============================================================================
// Security Rules Exports
// ============================================================================

export {
  initializeDefaultSecurityRules,
  getDefaultRuleIds
} from './security-rules.js';

// ============================================================================
// Unified Initialization
// ============================================================================

/**
 * Initialize all lifecycle hook systems
 */
export function initializeAllHooks(): void {
  // Import and call initialization functions
  const { initializePreToolUseHooks } = require('./pre-tool-use.js');
  const { initializePostToolUseHooks } = require('./post-tool-use.js');
  const { initializeUserPromptSubmitHooks } = require('./user-prompt-submit.js');
  const { initializeDefaultSecurityRules } = require('./security-rules.js');

  initializePreToolUseHooks();
  initializePostToolUseHooks();
  initializeUserPromptSubmitHooks();
  initializeDefaultSecurityRules();
}

/**
 * Get summary of all registered hooks
 */
export function getHooksSummary(): {
  preToolUse: { total: number; enabled: number; byCategory: Record<string, number> };
  postToolUse: { total: number; enabled: number; byCategory: Record<string, number> };
  userPromptSubmit: { total: number; enabled: number; byCategory: Record<string, number> };
} {
  const { getPreToolUseRules, getPreToolUseRulesByCategory } = require('./pre-tool-use.js');
  const { getPostToolUseRules, getPostToolUseRulesByCategory } = require('./post-tool-use.js');
  const { getUserPromptSubmitRules, getUserPromptSubmitRulesByCategory } = require('./user-prompt-submit.js');

  return {
    preToolUse: {
      total: getPreToolUseRules().length,
      enabled: getPreToolUseRules().filter((r: { enabled: boolean }) => r.enabled).length,
      byCategory: getPreToolUseRulesByCategory()
    },
    postToolUse: {
      total: getPostToolUseRules().length,
      enabled: getPostToolUseRules().filter((r: { enabled: boolean }) => r.enabled).length,
      byCategory: getPostToolUseRulesByCategory()
    },
    userPromptSubmit: {
      total: getUserPromptSubmitRules().length,
      enabled: getUserPromptSubmitRules().filter((r: { enabled: boolean }) => r.enabled).length,
      byCategory: getUserPromptSubmitRulesByCategory()
    }
  };
}
