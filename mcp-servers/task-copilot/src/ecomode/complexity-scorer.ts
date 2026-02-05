/**
 * Complexity Scoring Algorithm for Ecomode
 *
 * Analyzes task complexity based on:
 * - Keywords in title/description ("bug fix" → low, "architecture" → high)
 * - File count (single file → low, 10+ files → high)
 * - Agent type (@agent-qa → low, @agent-ta → medium/high)
 *
 * Normalizes scores to 0.0-1.0 range for TWO purposes:
 * 1. Model selection (which model: haiku/sonnet/opus)
 * 2. Effort level determination (how hard to think: low/medium/high/max)
 *
 * Effort level mapping (see model-router.ts):
 * - score < 0.3 → effort: low
 * - score 0.3-0.7 → effort: high
 * - score > 0.7 → effort: max
 *
 * @see PRD-omc-learnings (OMC Learnings Integration)
 */

import type { ComplexityScore } from '../types/omc-features.js';

// ============================================================================
// KEYWORD PATTERNS
// ============================================================================

/**
 * Keyword patterns with associated complexity weights
 */
const KEYWORD_PATTERNS = {
  /** Very low complexity (0.1-0.2) */
  trivial: [
    /\btypo\b/i,
    /\bspelling\b/i,
    /\bcomment\b/i,
    /\bdocstring\b/i,
    /\bwhitespace\b/i,
    /\bformatting\b/i,
  ],

  /** Low complexity (0.2-0.4) */
  low: [
    /\bbug\s*fix\b/i,
    /\bsmall\s*change\b/i,
    /\bminor\s*update\b/i,
    /\bquick\s*fix\b/i,
    /\bhotfix\b/i,
    /\bpatch\b/i,
    /\bcss\s*tweak\b/i,
    /\bstyle\s*update\b/i,
  ],

  /** Medium complexity (0.4-0.6) */
  medium: [
    /\bfeature\b/i,
    /\benhancement\b/i,
    /\bimprovement\b/i,
    /\brefactor\b/i,
    /\btest\s*coverage\b/i,
    /\bapi\s*endpoint\b/i,
    /\bcomponent\b/i,
  ],

  /** High complexity (0.6-0.8) */
  high: [
    /\barchitecture\b/i,
    /\bsystem\s*design\b/i,
    /\bmigration\b/i,
    /\bintegration\b/i,
    /\bperformance\s*optimization\b/i,
    /\bsecurity\s*review\b/i,
    /\bbreaking\s*change\b/i,
  ],

  /** Very high complexity (0.8-1.0) */
  veryHigh: [
    /\bfull\s*rewrite\b/i,
    /\bmajor\s*refactor\b/i,
    /\bplatform\s*migration\b/i,
    /\binfrastructure\s*overhaul\b/i,
    /\bcritical\s*security\b/i,
    /\bscalability\s*redesign\b/i,
  ],
};

/**
 * Agent complexity weights
 */
const AGENT_WEIGHTS: Record<string, number> = {
  // Low complexity agents
  qa: 0.2,
  doc: 0.2,
  cw: 0.2,

  // Medium complexity agents
  me: 0.4,
  uid: 0.4,
  uids: 0.5,
  uxd: 0.5,

  // High complexity agents
  ta: 0.7,
  sd: 0.6,
  sec: 0.7,
  do: 0.7,
  cco: 0.6,
};

// ============================================================================
// SCORING FUNCTIONS
// ============================================================================

/**
 * Analyze keywords in task text
 */
function scoreKeywords(text: string): number {
  const lowerText = text.toLowerCase();

  // Check from highest to lowest complexity
  for (const pattern of KEYWORD_PATTERNS.veryHigh) {
    if (pattern.test(lowerText)) return 0.85;
  }

  for (const pattern of KEYWORD_PATTERNS.high) {
    if (pattern.test(lowerText)) return 0.7;
  }

  for (const pattern of KEYWORD_PATTERNS.medium) {
    if (pattern.test(lowerText)) return 0.5;
  }

  for (const pattern of KEYWORD_PATTERNS.low) {
    if (pattern.test(lowerText)) return 0.25;
  }

  for (const pattern of KEYWORD_PATTERNS.trivial) {
    if (pattern.test(lowerText)) return 0.15;
  }

  // Default: medium-low if no patterns match
  return 0.4;
}

/**
 * Score based on file count
 */
function scoreFileCount(fileCount: number): number {
  if (fileCount === 0) return 0.3; // No files specified = medium-low
  if (fileCount === 1) return 0.2; // Single file = low
  if (fileCount <= 3) return 0.35; // Few files = medium-low
  if (fileCount <= 5) return 0.5; // Several files = medium
  if (fileCount <= 10) return 0.65; // Many files = medium-high
  return 0.8; // 10+ files = high
}

/**
 * Score based on agent type
 */
function scoreAgentType(agentId: string | undefined): number {
  if (!agentId) return 0.4; // Default medium-low if no agent

  // Remove @ prefix if present
  const cleanAgentId = agentId.replace(/^@agent-/, '').replace(/^@/, '');

  return AGENT_WEIGHTS[cleanAgentId] ?? 0.4;
}

/**
 * Normalize score to 0.0-1.0 range with weighted average
 */
function normalizeScore(keywordScore: number, fileScore: number, agentScore: number): number {
  // Weighted average: keywords = 50%, files = 30%, agent = 20%
  const weighted = keywordScore * 0.5 + fileScore * 0.3 + agentScore * 0.2;

  // Clamp to valid range
  return Math.max(0.0, Math.min(1.0, weighted));
}

/**
 * Map numeric score to complexity level
 */
function getComplexityLevel(score: number): ComplexityScore['level'] {
  if (score < 0.25) return 'trivial';
  if (score < 0.45) return 'low';
  if (score < 0.65) return 'medium';
  if (score < 0.85) return 'high';
  return 'very_high';
}

/**
 * Generate reasoning explanation
 */
function generateReasoning(
  keywordScore: number,
  fileScore: number,
  agentScore: number,
  fileCount: number,
  agentId: string | undefined,
): string {
  const reasons: string[] = [];

  // Keyword reasoning
  if (keywordScore >= 0.8) {
    reasons.push('Very high complexity keywords detected (architecture/migration/security)');
  } else if (keywordScore >= 0.6) {
    reasons.push('High complexity keywords detected (architecture/integration/performance)');
  } else if (keywordScore <= 0.3) {
    reasons.push('Low complexity keywords detected (bug fix/small change/typo)');
  }

  // File count reasoning
  if (fileCount === 1) {
    reasons.push('Single file modification');
  } else if (fileCount > 10) {
    reasons.push(`Large number of files (${fileCount}) indicates high complexity`);
  } else if (fileCount > 5) {
    reasons.push(`Multiple files (${fileCount}) indicates medium-high complexity`);
  }

  // Agent reasoning
  if (agentId) {
    const cleanAgentId = agentId.replace(/^@agent-/, '').replace(/^@/, '');
    const agentWeight = AGENT_WEIGHTS[cleanAgentId];

    if (agentWeight !== undefined) {
      if (agentWeight >= 0.7) {
        reasons.push(`High complexity agent (@agent-${cleanAgentId}) assigned`);
      } else if (agentWeight <= 0.3) {
        reasons.push(`Low complexity agent (@agent-${cleanAgentId}) assigned`);
      }
    }
  }

  return reasons.join('; ') || 'Default complexity based on task characteristics';
}

// ============================================================================
// PUBLIC API
// ============================================================================

/**
 * Input parameters for complexity scoring
 */
export interface ComplexityScoringInput {
  /** Task title */
  title: string;

  /** Task description (optional) */
  description?: string;

  /** Number of files involved */
  fileCount?: number;

  /** Agent assigned to task */
  agentId?: string;

  /** Additional context text */
  context?: string;
}

/**
 * Calculate complexity score for a task
 *
 * Returns a normalized score (0.0-1.0) used for:
 * 1. Model selection - determines which Claude model to use (haiku/sonnet/opus)
 * 2. Effort level - determines thinking budget (low/medium/high/max)
 *
 * The score is calculated from keywords, file count, and agent type, then
 * normalized to a 0.0-1.0 range. The model-router uses this score to select
 * both the appropriate model tier and the extended thinking effort level.
 *
 * @param input - Task information
 * @returns ComplexityScore with normalized score (0.0-1.0) and breakdown
 *
 * @example
 * ```typescript
 * const score = calculateComplexityScore({
 *   title: 'Fix login bug',
 *   fileCount: 1,
 *   agentId: 'qa'
 * });
 * // score.score = 0.23 (low complexity)
 * // score.level = 'low'
 * // → Model router will use: haiku model + low effort
 * ```
 */
export function calculateComplexityScore(input: ComplexityScoringInput): ComplexityScore {
  const startTime = performance.now();

  // Combine all text for keyword analysis
  const combinedText = [input.title, input.description, input.context].filter(Boolean).join(' ');

  // Calculate individual scores
  const keywordScore = scoreKeywords(combinedText);
  const fileScore = scoreFileCount(input.fileCount ?? 0);
  const agentScore = scoreAgentType(input.agentId);

  // Normalize to final score
  const finalScore = normalizeScore(keywordScore, fileScore, agentScore);

  // Generate level and reasoning
  const level = getComplexityLevel(finalScore);
  const reasoning = generateReasoning(keywordScore, fileScore, agentScore, input.fileCount ?? 0, input.agentId);

  const endTime = performance.now();
  const duration = endTime - startTime;

  // Ensure scoring completes in <50ms (acceptance criteria)
  if (duration > 50) {
    console.warn(`[complexity-scorer] Scoring took ${duration.toFixed(2)}ms (target: <50ms)`);
  }

  return {
    score: finalScore,
    factors: {
      keywords: keywordScore,
      fileCount: fileScore,
      agentType: agentScore,
    },
    level,
    reasoning,
  };
}

/**
 * Batch calculate complexity scores for multiple tasks
 *
 * Each score is used for model selection and effort level determination.
 * More efficient than calling calculateComplexityScore multiple times.
 */
export function calculateComplexityScores(inputs: ComplexityScoringInput[]): ComplexityScore[] {
  return inputs.map((input) => calculateComplexityScore(input));
}
