/**
 * Keyword Parser for Magic Keywords
 *
 * Extracts and validates modifier and action keywords from user messages.
 *
 * Modifier keywords (model selection):
 * - eco: - Low effort, quick responses (effortLevel: low)
 * - fast: - Medium effort, standard responses (effortLevel: medium)
 * - max: - Maximum effort, deep reasoning (effortLevel: max)
 * - opus: - Force Claude Opus
 * - sonnet: - Force Claude Sonnet
 * - haiku: - Force Claude Haiku
 * - auto: - Auto-select (same as eco:)
 * - ralph: - Auto-select with cost optimization
 *
 * Action keywords (task type):
 * - fix: - Bug fix or defect
 * - add: - New feature or enhancement
 * - refactor: - Code refactoring
 * - optimize: - Performance optimization
 * - test: - Testing work
 * - doc: - Documentation
 * - deploy: - Deployment/DevOps
 *
 * Rules:
 * - Keywords must be at the start of the message
 * - Max 1 modifier keyword
 * - Max 1 action keyword
 * - Case-insensitive matching
 * - Must be exact keyword followed by colon (no false positives)
 *
 * @see PRD-omc-learnings (OMC Learnings Integration)
 */

import type {
  ModifierKeyword,
  ActionKeyword,
  ParsedCommand,
} from '../mcp-servers/task-copilot/src/types/omc-features.js';

// ============================================================================
// KEYWORD DEFINITIONS
// ============================================================================

/**
 * Valid modifier keywords with their target models and effort levels
 */
const MODIFIER_KEYWORDS: Record<string, { targetModel: ModifierKeyword['targetModel']; effortLevel: ModifierKeyword['effortLevel'] }> = {
  eco: { targetModel: null, effortLevel: 'low' }, // Low effort, quick responses
  fast: { targetModel: null, effortLevel: 'medium' }, // Medium effort, standard responses
  max: { targetModel: null, effortLevel: 'max' }, // Maximum effort, deep reasoning
  opus: { targetModel: 'opus', effortLevel: null }, // Model override, no effort level
  sonnet: { targetModel: 'sonnet', effortLevel: null }, // Model override, no effort level
  haiku: { targetModel: 'haiku', effortLevel: null }, // Model override, no effort level
  auto: { targetModel: null, effortLevel: null }, // Auto-select based on complexity
  ralph: { targetModel: null, effortLevel: null }, // Auto-select with cost optimization
};

/**
 * Valid action keywords with suggested agent routing
 */
const ACTION_KEYWORDS: Record<string, string | undefined> = {
  fix: 'qa', // Bug fixes → QA agent
  add: 'me', // New features → Engineer
  refactor: 'ta', // Refactoring → Tech Architect
  optimize: 'ta', // Optimization → Tech Architect
  test: 'qa', // Testing → QA agent
  doc: 'doc', // Documentation → Doc agent
  deploy: 'do', // Deployment → DevOps agent
};

/**
 * Conflicting modifier combinations
 */
const CONFLICTING_MODIFIERS: [string, string][] = [
  ['eco', 'opus'],
  ['eco', 'fast'],
  ['eco', 'max'],
  ['eco', 'sonnet'],
  ['eco', 'haiku'],
  ['opus', 'fast'],
  ['opus', 'max'],
  ['opus', 'sonnet'],
  ['opus', 'haiku'],
  ['sonnet', 'fast'],
  ['sonnet', 'max'],
  ['sonnet', 'haiku'],
  ['fast', 'haiku'],
  ['fast', 'max'],
  ['haiku', 'max'],
  ['auto', 'opus'],
  ['auto', 'fast'],
  ['auto', 'max'],
  ['auto', 'sonnet'],
  ['auto', 'haiku'],
  ['ralph', 'opus'],
  ['ralph', 'fast'],
  ['ralph', 'max'],
  ['ralph', 'sonnet'],
  ['ralph', 'haiku'],
];

// ============================================================================
// PARSING FUNCTIONS
// ============================================================================

/**
 * Extract modifier keyword from message start
 *
 * Returns null if no modifier found or if keyword is not at the start.
 */
function extractModifier(message: string): ModifierKeyword | null {
  // Must be at the start (after optional whitespace)
  const trimmed = message.trimStart();
  if (!trimmed) return null;

  // Case-insensitive matching
  const lowerMessage = trimmed.toLowerCase();

  for (const [keyword, { targetModel, effortLevel }] of Object.entries(MODIFIER_KEYWORDS)) {
    const pattern = `${keyword}:`;

    // Must be exact match at start (no partial matches like "economics:")
    if (lowerMessage.startsWith(pattern)) {
      // Ensure it's followed by whitespace or end of string
      const afterKeyword = lowerMessage.slice(pattern.length);
      if (afterKeyword === '' || /^\s/.test(afterKeyword)) {
        return {
          keyword: keyword as ModifierKeyword['keyword'],
          position: message.indexOf(trimmed),
          raw: trimmed.slice(0, pattern.length),
          targetModel,
          effortLevel,
        };
      }
    }
  }

  return null;
}

/**
 * Extract action keyword from message start (after modifier if present)
 *
 * Returns null if no action found.
 */
function extractAction(message: string, modifierLength: number = 0): ActionKeyword | null {
  // Skip modifier if present
  const searchStart = message.slice(modifierLength).trimStart();
  if (!searchStart) return null;

  // Case-insensitive matching
  const lowerMessage = searchStart.toLowerCase();

  for (const [keyword, suggestedAgent] of Object.entries(ACTION_KEYWORDS)) {
    const pattern = `${keyword}:`;

    // Must be exact match at start
    if (lowerMessage.startsWith(pattern)) {
      // Ensure it's followed by whitespace or end of string
      const afterKeyword = lowerMessage.slice(pattern.length);
      if (afterKeyword === '' || /^\s/.test(afterKeyword)) {
        return {
          keyword: keyword as ActionKeyword['keyword'],
          position: message.length - searchStart.length,
          raw: searchStart.slice(0, pattern.length),
          suggestedAgent,
        };
      }
    }
  }

  return null;
}

/**
 * Check for conflicting modifier keywords
 */
function hasConflictingModifiers(modifiers: ModifierKeyword[]): string | null {
  if (modifiers.length <= 1) return null;

  const keywords = modifiers.map((m) => m.keyword);

  for (const [k1, k2] of CONFLICTING_MODIFIERS) {
    if (keywords.includes(k1 as ModifierKeyword['keyword']) && keywords.includes(k2 as ModifierKeyword['keyword'])) {
      return `Conflicting modifiers: ${k1}: and ${k2}: cannot be used together`;
    }
  }

  // Generic conflict for same type
  if (modifiers.length > 1) {
    return `Multiple modifiers detected: ${keywords.map((k) => `${k}:`).join(', ')}. Use only one.`;
  }

  return null;
}

/**
 * Strip keywords from message to get clean text
 */
function stripKeywords(
  message: string,
  modifier: ModifierKeyword | null,
  action: ActionKeyword | null,
): string {
  let clean = message;

  // Remove modifier
  if (modifier) {
    clean = clean.slice(modifier.position + modifier.raw.length).trimStart();
  }

  // Remove action (adjust position if modifier was removed)
  if (action) {
    const actionPos = modifier ? action.position - (modifier.position + modifier.raw.length) : action.position;
    clean = clean.slice(actionPos + action.raw.length).trimStart();
  }

  return clean;
}

// ============================================================================
// PUBLIC API
// ============================================================================

/**
 * Parse message for magic keywords
 *
 * @param message - User message text
 * @returns Parsed command with extracted keywords and validation
 *
 * @example
 * ```typescript
 * // Valid examples
 * parseKeywords('eco: fix: the login bug')
 * // → { modifier: 'eco', action: 'fix', cleanMessage: 'the login bug', valid: true }
 *
 * parseKeywords('opus: add: dark mode feature')
 * // → { modifier: 'opus', action: 'add', cleanMessage: 'dark mode feature', valid: true }
 *
 * parseKeywords('fix: authentication error')
 * // → { modifier: null, action: 'fix', cleanMessage: 'authentication error', valid: true }
 *
 * // Invalid examples
 * parseKeywords('eco: opus: fix bug')
 * // → { errors: ['Conflicting modifiers: eco: and opus:'], valid: false }
 *
 * parseKeywords('economics: is a complex topic')
 * // → { modifier: null, action: null, cleanMessage: 'economics: is...', valid: true }
 * ```
 */
export function parseKeywords(message: string): ParsedCommand {
  const errors: string[] = [];

  // Extract modifier
  const modifier = extractModifier(message);

  // Extract action (after modifier if present)
  const modifierLength = modifier ? modifier.position + modifier.raw.length : 0;
  const action = extractAction(message, modifierLength);

  // Validate: no conflicting modifiers
  if (modifier) {
    const conflict = hasConflictingModifiers([modifier]);
    if (conflict) {
      errors.push(conflict);
    }
  }

  // Clean message
  const cleanMessage = stripKeywords(message, modifier, action);

  return {
    originalMessage: message,
    cleanMessage,
    modifier,
    action,
    errors,
    valid: errors.length === 0,
  };
}

/**
 * Check if message contains any keywords
 */
export function hasKeywords(message: string): boolean {
  const parsed = parseKeywords(message);
  return parsed.modifier !== null || parsed.action !== null;
}

/**
 * Extract only modifier keyword
 */
export function extractModifierOnly(message: string): ModifierKeyword | null {
  return extractModifier(message);
}

/**
 * Extract only action keyword
 */
export function extractActionOnly(message: string): ActionKeyword | null {
  return extractAction(message, 0);
}

/**
 * Validate keyword combination
 *
 * @param message - Message to validate
 * @returns Validation errors (empty array if valid)
 */
export function validateKeywords(message: string): string[] {
  const parsed = parseKeywords(message);
  return parsed.errors;
}

/**
 * Get suggested model from modifier keyword
 *
 * @param modifier - Modifier keyword or null
 * @returns Model name or null for auto-select
 */
export function getModelFromModifier(modifier: ModifierKeyword | null): 'haiku' | 'sonnet' | 'opus' | null {
  return modifier?.targetModel ?? null;
}

/**
 * Get suggested agent from action keyword
 *
 * @param action - Action keyword or null
 * @returns Agent ID or undefined
 */
export function getAgentFromAction(action: ActionKeyword | null): string | undefined {
  return action?.suggestedAgent;
}
