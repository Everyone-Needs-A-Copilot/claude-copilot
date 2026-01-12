/**
 * Correction Detection Tools for Memory Copilot
 *
 * Implements auto-detection of correction patterns in user messages
 * with confidence scoring and extraction of old/new values.
 *
 * @see PRD-6df7cc11-c4d4-4f48-9e0c-1275cf6fb327
 */

import { v4 as uuidv4 } from 'uuid';
import type { DatabaseClient } from '../db/client.js';
import type {
  CorrectionPattern,
  CorrectionPatternType,
  MatchedCorrectionPattern,
  CorrectionCapture,
  CorrectionDetectInput,
  CorrectionDetectOutput,
  CorrectionStatus,
  CorrectionTarget
} from '../types/corrections.js';

// ============================================================================
// PATTERN DEFINITIONS
// ============================================================================

/**
 * Built-in correction patterns with confidence weights
 */
export const CORRECTION_PATTERNS: CorrectionPattern[] = [
  // Explicit corrections
  {
    id: 'explicit-correction',
    type: 'explicit_correction',
    pattern: '(?:^|\\s)(?:correction|CORRECTION)[:\\s]+(.+)',
    description: 'Explicit correction prefix',
    examples: ['Correction: use X instead', 'CORRECTION: the file is Y'],
    weight: 0.95,
    enabled: true
  },
  {
    id: 'actually-instead',
    type: 'replacement',
    pattern: '(?:^|\\s)(?:actually|Actually)[,\\s]+(?:use|it should be|I meant|you should use)\\s+([^.]+?)(?:\\s+instead(?:\\s+of\\s+([^.]+))?)?',
    description: 'Actually use X instead of Y',
    examples: ['Actually, use TypeScript instead of JavaScript', 'Actually I meant the other file'],
    weight: 0.85,
    enabled: true
  },
  {
    id: 'no-wrong',
    type: 'negation',
    pattern: '(?:^|\\s)(?:no|No|NO)[,\\s]+(?:that\'?s?|this is|it\'?s?)\\s+(?:wrong|incorrect|not right|not what I)',
    description: 'No, that\'s wrong pattern',
    examples: ['No, that\'s wrong', 'No this is incorrect'],
    weight: 0.90,
    enabled: true
  },
  {
    id: 'not-x-but-y',
    type: 'replacement',
    pattern: '(?:not|NOT)\\s+([^,]+)[,\\s]+(?:but|rather|instead)\\s+([^.]+)',
    description: 'Not X, but Y pattern',
    examples: ['Not src/index.ts, but src/main.ts', 'NOT camelCase, but snake_case'],
    weight: 0.90,
    enabled: true
  },
  {
    id: 'should-be',
    type: 'explicit_correction',
    pattern: '(?:it|this|that)\\s+should\\s+(?:be|have been)\\s+([^,]+?)(?:[,\\s]+not\\s+([^.]+))?',
    description: 'It should be X, not Y',
    examples: ['It should be async, not sync', 'This should be private'],
    weight: 0.85,
    enabled: true
  },
  {
    id: 'use-x-not-y',
    type: 'replacement',
    pattern: '(?:use|Use)\\s+([^,]+)[,\\s]+(?:not|instead of|rather than)\\s+([^.]+)',
    description: 'Use X, not Y',
    examples: ['Use useState, not useReducer', 'Use fetch instead of axios'],
    weight: 0.90,
    enabled: true
  },
  {
    id: 'i-prefer',
    type: 'preference',
    pattern: '(?:I|i)\\s+(?:prefer|would prefer|\'d prefer|like)\\s+([^.]+?)(?:\\s+(?:over|to|instead of)\\s+([^.]+))?',
    description: 'I prefer X over Y',
    examples: ['I prefer tabs over spaces', 'I\'d prefer async/await'],
    weight: 0.75,
    enabled: true
  },
  {
    id: 'dont-use',
    type: 'style_preference',
    pattern: '(?:don\'t|do not|Do not|Don\'t|please don\'t)\\s+(?:use|do)\\s+([^,]+?)(?:[,\\s]+(?:use|do)\\s+([^.]+))?',
    description: 'Don\'t use X, use Y',
    examples: ['Don\'t use var, use const', 'Please don\'t use console.log'],
    weight: 0.85,
    enabled: true
  },
  {
    id: 'what-i-meant',
    type: 'clarification',
    pattern: '(?:what I (?:meant|mean)|What I (?:meant|mean))\\s+(?:was|is)\\s+([^.]+)',
    description: 'What I meant was X',
    examples: ['What I meant was the config file', 'What I mean is the test folder'],
    weight: 0.80,
    enabled: true
  },
  {
    id: 'thats-incorrect',
    type: 'factual_error',
    pattern: '(?:that\'?s|this is|it\'?s)\\s+(?:incorrect|wrong|not correct|inaccurate)[.!,]?\\s*(?:the (?:correct|actual|right)\\s+(?:one|answer|way|value) is\\s+)?([^.]*)?',
    description: 'That\'s incorrect, the correct one is X',
    examples: ['That\'s incorrect, the correct path is /src', 'This is wrong. The actual value is 42'],
    weight: 0.90,
    enabled: true
  },
  {
    id: 'i-said',
    type: 'clarification',
    pattern: '(?:I said|i said)\\s+([^,]+)[,\\s]+not\\s+([^.]+)',
    description: 'I said X, not Y',
    examples: ['I said TypeScript, not JavaScript', 'I said 3 retries, not 5'],
    weight: 0.90,
    enabled: true
  },
  {
    id: 'never-always',
    type: 'style_preference',
    pattern: '(?:never|Never|always|Always)\\s+(?:use|do|write)\\s+([^.]+)',
    description: 'Never/Always use X',
    examples: ['Never use any type', 'Always use strict mode'],
    weight: 0.80,
    enabled: true
  }
];

// ============================================================================
// PATTERN MATCHING
// ============================================================================

/**
 * Match all correction patterns against user message
 */
export function matchCorrectionPatterns(
  userMessage: string
): MatchedCorrectionPattern[] {
  const matches: MatchedCorrectionPattern[] = [];

  for (const pattern of CORRECTION_PATTERNS) {
    if (!pattern.enabled) continue;

    try {
      const regex = new RegExp(pattern.pattern, 'gi');
      let match: RegExpExecArray | null;

      while ((match = regex.exec(userMessage)) !== null) {
        const captures: Record<string, string> = {};

        // Extract captured groups
        for (let i = 1; i < match.length; i++) {
          if (match[i]) {
            captures[`group${i}`] = match[i].trim();
          }
        }

        matches.push({
          patternId: pattern.id,
          type: pattern.type,
          matchedText: match[0].trim(),
          position: {
            start: match.index,
            end: match.index + match[0].length
          },
          captures: Object.keys(captures).length > 0 ? captures : undefined
        });
      }
    } catch (error) {
      // Skip invalid regex patterns
      console.error(`Invalid pattern ${pattern.id}:`, error);
    }
  }

  return matches;
}

// ============================================================================
// CONFIDENCE SCORING
// ============================================================================

/**
 * Calculate overall confidence score from matched patterns
 */
export function calculateConfidence(
  matches: MatchedCorrectionPattern[],
  userMessage: string,
  previousAgentOutput?: string
): number {
  if (matches.length === 0) return 0;

  // Base score from pattern weights
  let score = 0;
  const seenTypes = new Set<CorrectionPatternType>();

  for (const match of matches) {
    const pattern = CORRECTION_PATTERNS.find(p => p.id === match.patternId);
    if (pattern) {
      // Only count highest weight for each pattern type
      if (!seenTypes.has(match.type)) {
        score += pattern.weight;
        seenTypes.add(match.type);
      }
    }
  }

  // Normalize by number of unique pattern types (max would be ~0.9 avg)
  score = Math.min(score / Math.max(seenTypes.size, 1), 1.0);

  // Boost for multiple different pattern types (cross-validation)
  if (seenTypes.size >= 2) {
    score = Math.min(score * 1.1, 1.0);
  }

  // Boost if message is short and focused (likely intentional correction)
  if (userMessage.length < 100) {
    score = Math.min(score * 1.05, 1.0);
  }

  // Boost if previous agent output exists (context available)
  if (previousAgentOutput && previousAgentOutput.length > 0) {
    score = Math.min(score * 1.05, 1.0);
  }

  // Slight reduction for very long messages (might be embedded in other content)
  if (userMessage.length > 500) {
    score *= 0.9;
  }

  return Math.round(score * 100) / 100; // Round to 2 decimal places
}

// ============================================================================
// VALUE EXTRACTION
// ============================================================================

/**
 * Extract old and new values from matched patterns
 */
export function extractValues(
  matches: MatchedCorrectionPattern[]
): { oldValue?: string; newValue?: string } {
  let oldValue: string | undefined;
  let newValue: string | undefined;

  // Priority order for extraction: explicit corrections first
  const priorityOrder: CorrectionPatternType[] = [
    'explicit_correction',
    'replacement',
    'negation',
    'factual_error',
    'clarification',
    'preference',
    'style_preference',
    'direct_overwrite'
  ];

  // Sort matches by priority
  const sortedMatches = [...matches].sort((a, b) => {
    return priorityOrder.indexOf(a.type) - priorityOrder.indexOf(b.type);
  });

  for (const match of sortedMatches) {
    if (!match.captures) continue;

    // Extract based on capture groups
    // group1 is typically the new/correct value
    // group2 is typically the old/incorrect value (when present)
    if (match.captures.group1 && !newValue) {
      newValue = match.captures.group1;
    }
    if (match.captures.group2 && !oldValue) {
      oldValue = match.captures.group2;
    }

    // For some patterns, group order is reversed (check by patternId)
    if (match.patternId === 'not-x-but-y' || match.patternId === 'i-said') {
      // "Not X, but Y" - group1 is old, group2 is new
      if (match.captures.group1 && !oldValue) {
        oldValue = match.captures.group1;
      }
      if (match.captures.group2 && !newValue) {
        newValue = match.captures.group2;
      }
    }
  }

  return { oldValue, newValue };
}

// ============================================================================
// TARGET INFERENCE
// ============================================================================

/**
 * Infer correction target from context
 */
export function inferTarget(
  userMessage: string,
  agentId?: string
): { target: CorrectionTarget; targetId?: string } {
  const lowerMessage = userMessage.toLowerCase();

  // Check for agent-specific corrections
  if (agentId) {
    // Code-related agents
    if (['me', 'uid'].includes(agentId)) {
      return { target: 'skill', targetId: `agent-${agentId}` };
    }
    // Documentation agents
    if (['doc', 'cw'].includes(agentId)) {
      return { target: 'skill', targetId: `agent-${agentId}` };
    }
    // Design agents
    if (['sd', 'uxd', 'uids'].includes(agentId)) {
      return { target: 'skill', targetId: `agent-${agentId}` };
    }
    // Architecture/QA
    if (['ta', 'qa', 'sec', 'do'].includes(agentId)) {
      return { target: 'agent', targetId: agentId };
    }
  }

  // Check for skill-related keywords
  if (lowerMessage.includes('skill') || lowerMessage.includes('pattern') || lowerMessage.includes('template')) {
    return { target: 'skill' };
  }

  // Check for preference-related keywords
  if (lowerMessage.includes('prefer') || lowerMessage.includes('style') || lowerMessage.includes('always') || lowerMessage.includes('never')) {
    return { target: 'preference' };
  }

  // Check for memory/knowledge keywords
  if (lowerMessage.includes('remember') || lowerMessage.includes('note') || lowerMessage.includes('important')) {
    return { target: 'memory' };
  }

  // Default to memory (safest option)
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
  projectId: string
): CorrectionDetectOutput {
  const threshold = input.threshold ?? 0.5;

  // Match patterns
  const matches = matchCorrectionPatterns(input.userMessage);

  // Calculate confidence
  const confidence = calculateConfidence(
    matches,
    input.userMessage,
    input.previousAgentOutput
  );

  // If below threshold, return no detections
  if (confidence < threshold) {
    return {
      detected: false,
      corrections: [],
      patternMatchCount: matches.length,
      maxConfidence: confidence,
      suggestedAction: 'ignore'
    };
  }

  // Extract values
  const { oldValue, newValue } = extractValues(matches);

  // Infer target
  const { target, targetId } = inferTarget(input.userMessage, input.agentId);

  // Create correction capture
  const correction: CorrectionCapture = {
    id: uuidv4(),
    projectId,
    sessionId: undefined, // Will be set by caller
    taskId: input.taskId,
    agentId: input.agentId,
    originalContent: oldValue || input.previousAgentOutput || '',
    correctedContent: newValue || '',
    rawUserMessage: input.userMessage,
    matchedPatterns: matches,
    extractedWhat: oldValue ? `Incorrect: ${oldValue}` : undefined,
    extractedWhy: undefined, // Could be enhanced with semantic analysis
    extractedHow: newValue ? `Use: ${newValue}` : undefined,
    target,
    targetId,
    confidence,
    status: 'pending' as CorrectionStatus,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString() // 7 days
  };

  // Determine suggested action
  let suggestedAction: 'auto_capture' | 'prompt_user' | 'ignore';
  if (confidence >= 0.85) {
    suggestedAction = 'auto_capture';
  } else if (confidence >= threshold) {
    suggestedAction = 'prompt_user';
  } else {
    suggestedAction = 'ignore';
  }

  return {
    detected: true,
    corrections: [correction],
    patternMatchCount: matches.length,
    maxConfidence: confidence,
    suggestedAction
  };
}

// ============================================================================
// CORRECTION STORAGE
// ============================================================================

/**
 * Store a correction in the database
 */
export function storeCorrection(
  db: DatabaseClient,
  correction: CorrectionCapture,
  sessionId?: string
): CorrectionCapture {
  // Update session ID
  const correctionWithSession: CorrectionCapture = {
    ...correction,
    sessionId: sessionId || correction.sessionId
  };

  // Store in corrections table
  db.insertCorrection({
    id: correction.id,
    session_id: sessionId || null,
    task_id: correction.taskId || null,
    agent_id: correction.agentId || null,
    original_content: correction.originalContent,
    corrected_content: correction.correctedContent,
    raw_user_message: correction.rawUserMessage,
    matched_patterns: JSON.stringify(correction.matchedPatterns),
    extracted_what: correction.extractedWhat || null,
    extracted_why: correction.extractedWhy || null,
    extracted_how: correction.extractedHow || null,
    target: correction.target,
    target_id: correction.targetId || null,
    target_section: correction.targetSection || null,
    confidence: correction.confidence,
    status: correction.status,
    created_at: correction.createdAt,
    updated_at: correction.updatedAt,
    reviewed_at: correction.reviewedAt || null,
    applied_at: correction.appliedAt || null,
    expires_at: correction.expiresAt || null,
    review_metadata: correction.reviewMetadata ? JSON.stringify(correction.reviewMetadata) : null
  });

  return correctionWithSession;
}

/**
 * Update a correction's status
 */
export function updateCorrectionStatus(
  db: DatabaseClient,
  correctionId: string,
  status: CorrectionStatus,
  reviewMetadata?: Record<string, unknown>
): boolean {
  const existing = db.getCorrection(correctionId);
  if (!existing) return false;

  const updates: Partial<import('../types/corrections.js').CorrectionRow> = {
    status
  };

  if (status === 'approved' || status === 'rejected') {
    updates.reviewed_at = new Date().toISOString();
  }

  if (status === 'applied') {
    updates.applied_at = new Date().toISOString();
  }

  if (reviewMetadata) {
    updates.review_metadata = JSON.stringify(reviewMetadata);
  }

  db.updateCorrection(correctionId, updates);
  return true;
}

/**
 * List corrections with filters
 */
export function listCorrections(
  db: DatabaseClient,
  options: {
    status?: CorrectionStatus;
    agentId?: string;
    target?: CorrectionTarget;
    limit?: number;
    includeExpired?: boolean;
  }
): CorrectionCapture[] {
  const rows = db.listCorrections(options);

  return rows.map(row => ({
    id: row.id,
    projectId: row.project_id,
    sessionId: row.session_id || undefined,
    taskId: row.task_id || undefined,
    agentId: row.agent_id || undefined,
    originalContent: row.original_content,
    correctedContent: row.corrected_content,
    rawUserMessage: row.raw_user_message,
    matchedPatterns: JSON.parse(row.matched_patterns),
    extractedWhat: row.extracted_what || undefined,
    extractedWhy: row.extracted_why || undefined,
    extractedHow: row.extracted_how || undefined,
    target: row.target as CorrectionTarget,
    targetId: row.target_id || undefined,
    targetSection: row.target_section || undefined,
    confidence: row.confidence,
    status: row.status as CorrectionStatus,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    reviewedAt: row.reviewed_at || undefined,
    appliedAt: row.applied_at || undefined,
    expiresAt: row.expires_at || undefined,
    reviewMetadata: row.review_metadata ? JSON.parse(row.review_metadata) : undefined
  }));
}

/**
 * Get correction statistics
 */
export function getCorrectionStats(db: DatabaseClient): {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  applied: number;
  expired: number;
} {
  return db.getCorrectionStats();
}
