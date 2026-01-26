/**
 * Keyword Parser with Validation
 *
 * Parses hybrid modifier+action pattern from command messages.
 * Example: "eco: fix the bug" -> { modifier: "eco", action: "fix", rest: "the bug" }
 */

export interface ParsedKeywords {
  modifier?: string;
  action?: string;
  rest: string;
}

export interface ValidationError {
  type: 'conflict' | 'duplicate' | 'invalid';
  message: string;
  keywords: string[];
}

export interface ParseResult {
  success: boolean;
  parsed?: ParsedKeywords;
  error?: ValidationError;
}

// Valid modifier keywords (model/speed preferences)
const MODIFIERS = ['eco', 'opus', 'fast', 'slow', 'thorough', 'quick'] as const;
type Modifier = typeof MODIFIERS[number];

// Valid action keywords (intent/task type)
const ACTIONS = ['fix', 'add', 'refactor', 'optimize', 'test', 'docs', 'security', 'design'] as const;
type Action = typeof ACTIONS[number];

// Conflicting modifier pairs
const CONFLICTS: Record<string, string[]> = {
  eco: ['opus'],
  opus: ['eco'],
  fast: ['slow', 'thorough'],
  slow: ['fast', 'quick'],
  thorough: ['fast', 'quick'],
  quick: ['slow', 'thorough'],
};

/**
 * Extracts keywords from the start of a message.
 * Uses word boundaries to prevent false positives like "economics:" matching "eco:".
 *
 * @param message - The input message to parse
 * @returns ParseResult with extracted keywords or validation errors
 */
export function parseKeywords(message: string): ParseResult {
  const trimmed = message.trim();
  if (!trimmed) {
    return { success: true, parsed: { rest: '' } };
  }

  // Extract all keyword: patterns from the start of the message
  // Use word boundary (\b) to ensure exact keyword match
  const keywordPattern = /^(\b\w+\b:\s*)+/;
  const match = trimmed.match(keywordPattern);

  if (!match) {
    return { success: true, parsed: { rest: trimmed } };
  }

  // Extract individual keywords (case-insensitive)
  const keywordString = match[0];
  const keywordMatches = keywordString.matchAll(/\b(\w+)\b:/g);
  const extractedKeywords = Array.from(keywordMatches, m => m[1].toLowerCase());

  if (extractedKeywords.length === 0) {
    return { success: true, parsed: { rest: trimmed } };
  }

  // Separate modifiers and actions
  const foundModifiers = extractedKeywords.filter(k => MODIFIERS.includes(k as Modifier));
  const foundActions = extractedKeywords.filter(k => ACTIONS.includes(k as Action));
  const unknownKeywords = extractedKeywords.filter(
    k => !MODIFIERS.includes(k as Modifier) && !ACTIONS.includes(k as Action)
  );

  // Validation: Check for unknown keywords
  if (unknownKeywords.length > 0) {
    return {
      success: false,
      error: {
        type: 'invalid',
        message: `Unknown keyword${unknownKeywords.length > 1 ? 's' : ''}: ${unknownKeywords.join(', ')}`,
        keywords: unknownKeywords,
      },
    };
  }

  // Validation: Max 1 modifier
  if (foundModifiers.length > 1) {
    return {
      success: false,
      error: {
        type: 'duplicate',
        message: `Multiple modifiers not allowed: ${foundModifiers.join(', ')}`,
        keywords: foundModifiers,
      },
    };
  }

  // Validation: Max 1 action
  if (foundActions.length > 1) {
    return {
      success: false,
      error: {
        type: 'duplicate',
        message: `Multiple actions not allowed: ${foundActions.join(', ')}`,
        keywords: foundActions,
      },
    };
  }

  // Validation: Check for conflicts
  const modifier = foundModifiers[0];
  const action = foundActions[0];

  if (modifier && CONFLICTS[modifier]) {
    const conflictsWith = foundModifiers.filter(m =>
      m !== modifier && CONFLICTS[modifier].includes(m)
    );

    if (conflictsWith.length > 0) {
      return {
        success: false,
        error: {
          type: 'conflict',
          message: `Conflicting modifiers: ${modifier} and ${conflictsWith.join(', ')}`,
          keywords: [modifier, ...conflictsWith],
        },
      };
    }
  }

  // Extract the remaining message after keywords
  let rest = trimmed.slice(keywordString.length).trim();
  let detectedAction = action;

  // If no action was found via colon syntax, check if rest starts with an action keyword
  if (!detectedAction && rest) {
    const firstWord = rest.split(/\s+/)[0]?.toLowerCase();
    if (firstWord && ACTIONS.includes(firstWord as Action)) {
      detectedAction = firstWord;
      rest = rest.slice(firstWord.length).trim();
    }
  }

  return {
    success: true,
    parsed: {
      modifier,
      action: detectedAction,
      rest,
    },
  };
}

/**
 * Formats a validation error as a user-friendly message.
 */
export function formatError(error: ValidationError): string {
  const suggestions: Record<ValidationError['type'], string> = {
    conflict: 'Choose only one modifier from each conflicting pair.',
    duplicate: 'Use at most one modifier and one action keyword.',
    invalid: `Valid modifiers: ${MODIFIERS.join(', ')}. Valid actions: ${ACTIONS.join(', ')}.`,
  };

  return `${error.message}\n${suggestions[error.type]}`;
}

/**
 * Helper to check if a keyword is valid (either modifier or action).
 */
export function isValidKeyword(keyword: string): boolean {
  const lower = keyword.toLowerCase();
  return MODIFIERS.includes(lower as Modifier) || ACTIONS.includes(lower as Action);
}

/**
 * Get list of all valid keywords.
 */
export function getValidKeywords(): { modifiers: readonly string[]; actions: readonly string[] } {
  return {
    modifiers: MODIFIERS,
    actions: ACTIONS,
  };
}
