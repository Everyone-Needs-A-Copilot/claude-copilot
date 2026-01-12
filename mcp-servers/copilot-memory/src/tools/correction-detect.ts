/**
 * Correction Detection Tool
 *
 * Auto-detects correction patterns in user messages and extracts
 * old/new values with confidence scoring for the two-stage workflow.
 *
 * @see PRD-6df7cc11-c4d4-4f48-9e0c-1275cf6fb327
 */

import { v4 as uuidv4 } from 'uuid';
import type {
  CorrectionPattern,
  CorrectionPatternType,
  MatchedCorrectionPattern,
  CorrectionCapture,
  CorrectionDetectInput,
  CorrectionDetectOutput,
  CorrectionTarget,
} from '../types/corrections.js';

// ============================================================================
// DEFAULT CORRECTION PATTERNS
// ============================================================================

/**
 * Built-in correction patterns for detection
 */
export const DEFAULT_PATTERNS: CorrectionPattern[] = [
  // Explicit corrections
  {
    id: 'explicit_correction_1',
    type: 'explicit_correction',
    pattern: '(?:^|\\s)correction:?\\s+(.+)',
    description: 'Explicit "correction:" prefix',
    examples: ['Correction: the API endpoint should be /v2/users', 'correction the file is in src/'],
    weight: 0.95,
    enabled: true,
  },
  {
    id: 'explicit_correction_2',
    type: 'explicit_correction',
    pattern: '(?:^|\\s)(?:that(?:\'s| is)|this is)\\s+(?:wrong|incorrect|not right)',
    description: 'Explicit "that\'s wrong" statements',
    examples: ['That\'s wrong', 'This is incorrect', 'that is not right'],
    weight: 0.9,
    enabled: true,
  },

  // Negation patterns
  {
    id: 'negation_1',
    type: 'negation',
    pattern: '(?:^|\\s)no,?\\s+(?:that(?:\'s| is)|it(?:\'s| is)|this(?:\'s| is))?\\s*(?:not|wrong|incorrect)',
    description: 'Negation with "no" prefix',
    examples: ['No, that\'s not right', 'no it\'s wrong', 'No, this is incorrect'],
    weight: 0.85,
    enabled: true,
  },
  {
    id: 'negation_2',
    type: 'negation',
    pattern: '(?:^|\\s)(?:don\'t|do not|never)\\s+(?:use|do|make|call|create)',
    description: 'Instruction negation',
    examples: ['Don\'t use that pattern', 'Do not call that API', 'Never create files there'],
    weight: 0.8,
    enabled: true,
  },

  // Replacement patterns
  {
    id: 'replacement_1',
    type: 'replacement',
    pattern: '(?:^|\\s)actually,?\\s+(?:it(?:\'s| is|should be)|use|the)',
    description: 'Replacement with "actually"',
    examples: ['Actually, it should be X', 'actually use Y instead', 'Actually the correct way is'],
    weight: 0.85,
    enabled: true,
  },
  {
    id: 'replacement_2',
    type: 'replacement',
    pattern: '(?:^|\\s)(?:use|it(?:\'s| is)|should be)\\s+(.+?)\\s+(?:instead of|not|rather than)\\s+(.+)',
    description: 'Explicit replacement "X instead of Y"',
    examples: ['Use TypeScript instead of JavaScript', 'It should be /api/v2 instead of /api/v1'],
    weight: 0.95,
    enabled: true,
  },
  {
    id: 'replacement_3',
    type: 'replacement',
    pattern: '(?:^|\\s)(?:change|replace|switch|swap)\\s+(.+?)\\s+(?:to|with|for)\\s+(.+)',
    description: 'Explicit change instruction',
    examples: ['Change foo to bar', 'Replace X with Y', 'Switch to the new API'],
    weight: 0.9,
    enabled: true,
  },

  // Clarification patterns
  {
    id: 'clarification_1',
    type: 'clarification',
    pattern: '(?:^|\\s)(?:what I (?:meant|mean)|I meant|I mean)\\s+(?:was|is|to say)?',
    description: 'Clarification of intent',
    examples: ['What I meant was...', 'I meant to say', 'I mean the other one'],
    weight: 0.8,
    enabled: true,
  },
  {
    id: 'clarification_2',
    type: 'clarification',
    pattern: '(?:^|\\s)(?:to clarify|let me clarify|to be clear)',
    description: 'Explicit clarification',
    examples: ['To clarify, I want X', 'Let me clarify', 'To be clear, we should'],
    weight: 0.75,
    enabled: true,
  },

  // Preference patterns
  {
    id: 'preference_1',
    type: 'preference',
    pattern: '(?:^|\\s)(?:I prefer|I\'d prefer|I would prefer|prefer to)\\s+(.+?)\\s+(?:over|instead of|rather than)',
    description: 'Explicit preference statement',
    examples: ['I prefer tabs over spaces', 'I\'d prefer async/await instead of promises'],
    weight: 0.85,
    enabled: true,
  },
  {
    id: 'preference_2',
    type: 'preference',
    pattern: '(?:^|\\s)(?:always|never)\\s+(?:use|do|make)',
    description: 'Always/never preference',
    examples: ['Always use const', 'Never use var', 'Always make functions pure'],
    weight: 0.8,
    enabled: true,
  },

  // Factual error patterns
  {
    id: 'factual_error_1',
    type: 'factual_error',
    pattern: '(?:^|\\s)(?:that(?:\'s| is)|this(?:\'s| is))\\s+(?:incorrect|inaccurate|false|not true)',
    description: 'Factual error indication',
    examples: ['That\'s incorrect', 'This is inaccurate', 'That is not true'],
    weight: 0.9,
    enabled: true,
  },
  {
    id: 'factual_error_2',
    type: 'factual_error',
    pattern: '(?:^|\\s)(?:the (?:correct|right|actual)|in fact)',
    description: 'Factual correction',
    examples: ['The correct answer is', 'The right way is', 'In fact, it works like'],
    weight: 0.85,
    enabled: true,
  },

  // Style preference patterns
  {
    id: 'style_preference_1',
    type: 'style_preference',
    pattern: '(?:^|\\s)(?:please (?:don\'t|do not)|stop)\\s+(?:using|doing|making)',
    description: 'Style correction request',
    examples: ['Please don\'t use semicolons', 'Stop using var', 'Please do not make inline styles'],
    weight: 0.8,
    enabled: true,
  },
  {
    id: 'style_preference_2',
    type: 'style_preference',
    pattern: '(?:^|\\s)(?:I (?:want|like)|we (?:want|use))\\s+(.+?)\\s+(?:style|format|convention)',
    description: 'Style preference',
    examples: ['I want camelCase style', 'We use kebab-case format'],
    weight: 0.75,
    enabled: true,
  },
];

// ============================================================================
// PATTERN MATCHING ENGINE
// ============================================================================

/**
 * Match patterns against user message
 */
function matchPatterns(
  message: string,
  patterns: CorrectionPattern[]
): MatchedCorrectionPattern[] {
  const matches: MatchedCorrectionPattern[] = [];
  const normalizedMessage = message.toLowerCase();

  for (const pattern of patterns) {
    if (!pattern.enabled) continue;

    try {
      const regex = new RegExp(pattern.pattern, 'gi');
      let match: RegExpExecArray | null;

      while ((match = regex.exec(normalizedMessage)) !== null) {
        const captures: Record<string, string> = {};

        // Extract capture groups
        if (match.length > 1) {
          for (let i = 1; i < match.length; i++) {
            if (match[i]) {
              captures[`group${i}`] = match[i];
            }
          }
        }

        matches.push({
          patternId: pattern.id,
          type: pattern.type,
          matchedText: match[0],
          position: {
            start: match.index,
            end: match.index + match[0].length,
          },
          captures: Object.keys(captures).length > 0 ? captures : undefined,
        });
      }
    } catch (error) {
      // Skip invalid patterns
      console.error(`Invalid pattern ${pattern.id}: ${error}`);
    }
  }

  return matches;
}

/**
 * Calculate confidence score from matched patterns
 */
function calculateConfidence(
  matches: MatchedCorrectionPattern[],
  patterns: CorrectionPattern[]
): number {
  if (matches.length === 0) return 0;

  // Create pattern lookup
  const patternLookup = new Map(patterns.map((p) => [p.id, p]));

  // Calculate weighted average
  let totalWeight = 0;
  let weightedSum = 0;

  for (const match of matches) {
    const pattern = patternLookup.get(match.patternId);
    if (pattern) {
      weightedSum += pattern.weight;
      totalWeight += 1;
    }
  }

  // Base confidence from pattern weights
  const baseConfidence = totalWeight > 0 ? weightedSum / totalWeight : 0;

  // Boost for multiple pattern matches (max 0.1 boost)
  const multiMatchBoost = Math.min(0.1, (matches.length - 1) * 0.03);

  // Cap at 0.99
  return Math.min(0.99, baseConfidence + multiMatchBoost);
}

/**
 * Extract old and new values from correction
 */
function extractValues(
  message: string,
  matches: MatchedCorrectionPattern[]
): { oldValue?: string; newValue?: string } {
  // Look for explicit captures first
  for (const match of matches) {
    if (match.captures) {
      // "X instead of Y" pattern
      if (match.captures.group1 && match.captures.group2) {
        return {
          newValue: match.captures.group1.trim(),
          oldValue: match.captures.group2.trim(),
        };
      }
    }
  }

  // Try to extract from message context
  const insteadOfMatch = message.match(/(.+?)\s+instead of\s+(.+?)(?:\.|$)/i);
  if (insteadOfMatch) {
    return {
      newValue: insteadOfMatch[1].trim(),
      oldValue: insteadOfMatch[2].trim(),
    };
  }

  const notXButYMatch = message.match(/not\s+(.+?)\s+but\s+(.+?)(?:\.|$)/i);
  if (notXButYMatch) {
    return {
      oldValue: notXButYMatch[1].trim(),
      newValue: notXButYMatch[2].trim(),
    };
  }

  return {};
}

/**
 * Determine correction target based on context
 */
function determineTarget(
  message: string,
  agentId?: string
): { target: CorrectionTarget; targetId?: string } {
  const lowerMessage = message.toLowerCase();

  // Check for skill-related keywords
  if (
    lowerMessage.includes('skill') ||
    lowerMessage.includes('workflow') ||
    lowerMessage.includes('pattern')
  ) {
    return { target: 'skill' };
  }

  // Check for agent-related keywords
  if (
    lowerMessage.includes('agent') ||
    lowerMessage.includes('instruction') ||
    agentId
  ) {
    return { target: 'agent', targetId: agentId };
  }

  // Check for preference keywords
  if (
    lowerMessage.includes('prefer') ||
    lowerMessage.includes('always') ||
    lowerMessage.includes('never') ||
    lowerMessage.includes('style')
  ) {
    return { target: 'preference' };
  }

  // Default to memory (lesson)
  return { target: 'memory' };
}

// ============================================================================
// MAIN DETECTION FUNCTION
// ============================================================================

/**
 * Detect corrections in user message
 */
export function detectCorrections(
  input: CorrectionDetectInput,
  customPatterns?: CorrectionPattern[]
): CorrectionDetectOutput {
  const patterns = customPatterns || DEFAULT_PATTERNS;
  const threshold = input.threshold ?? 0.5;

  // Match patterns
  const matches = matchPatterns(input.userMessage, patterns);

  // Calculate confidence
  const confidence = calculateConfidence(matches, patterns);

  // If below threshold, return no detection
  if (confidence < threshold) {
    return {
      detected: false,
      corrections: [],
      patternMatchCount: matches.length,
      maxConfidence: confidence,
      suggestedAction: 'ignore',
    };
  }

  // Extract values
  const { oldValue, newValue } = extractValues(input.userMessage, matches);

  // Determine target
  const { target, targetId } = determineTarget(
    input.userMessage,
    input.agentId
  );

  // Create correction capture
  const correction: CorrectionCapture = {
    id: uuidv4(),
    projectId: '', // Will be set by caller
    sessionId: undefined,
    taskId: input.taskId,
    agentId: input.agentId,
    originalContent: input.previousAgentOutput || oldValue || '',
    correctedContent: newValue || '',
    rawUserMessage: input.userMessage,
    matchedPatterns: matches,
    extractedWhat: oldValue,
    extractedWhy: undefined, // Could be enhanced with NLP
    extractedHow: newValue,
    target,
    targetId,
    targetSection: undefined,
    confidence,
    status: 'pending',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(), // 7 days
  };

  // Determine suggested action
  let suggestedAction: 'auto_capture' | 'prompt_user' | 'ignore';
  if (confidence >= 0.85) {
    suggestedAction = 'auto_capture';
  } else if (confidence >= 0.5) {
    suggestedAction = 'prompt_user';
  } else {
    suggestedAction = 'ignore';
  }

  return {
    detected: true,
    corrections: [correction],
    patternMatchCount: matches.length,
    maxConfidence: confidence,
    suggestedAction,
  };
}

/**
 * Get all available patterns
 */
export function getPatterns(includeDisabled = false): CorrectionPattern[] {
  if (includeDisabled) {
    return [...DEFAULT_PATTERNS];
  }
  return DEFAULT_PATTERNS.filter((p) => p.enabled);
}

/**
 * Validate a custom pattern
 */
export function validatePattern(pattern: CorrectionPattern): {
  valid: boolean;
  error?: string;
} {
  try {
    new RegExp(pattern.pattern);
    if (!pattern.id || pattern.id.length === 0) {
      return { valid: false, error: 'Pattern ID is required' };
    }
    if (pattern.weight < 0 || pattern.weight > 1) {
      return { valid: false, error: 'Weight must be between 0 and 1' };
    }
    return { valid: true };
  } catch (error) {
    return {
      valid: false,
      error: `Invalid regex: ${error instanceof Error ? error.message : 'Unknown error'}`,
    };
  }
}
