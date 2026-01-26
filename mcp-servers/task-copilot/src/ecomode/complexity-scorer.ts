/**
 * Complexity Scoring Algorithm for Ecomode
 *
 * Analyzes task complexity using multiple signals:
 * - Keyword patterns (bug fix vs architecture redesign)
 * - File patterns (single file vs 10+ files)
 * - Agent type (qa vs ta)
 * - Domain complexity (auth, payments, etc.)
 * - Architectural impact (isolated vs system-wide)
 *
 * Normalizes scores to 0.0-1.0 range for model routing decisions.
 *
 * @see PRD-6df7cc11-c4d4-4f48-9e0c-1275cf6fb327 (OMC Features - Ecomode)
 */

import { ComplexityScore, ComplexityLevel } from '../types/omc-features.js';

// ============================================================================
// SCORING WEIGHTS
// ============================================================================

const WEIGHTS = {
  keywords: 0.35,        // Task description keywords
  filePatterns: 0.25,    // Number and type of files
  agentType: 0.20,       // Agent complexity level
  domainComplexity: 0.15, // Domain-specific complexity
  architecturalImpact: 0.05, // System-wide impact
};

// ============================================================================
// KEYWORD SCORING
// ============================================================================

interface KeywordPattern {
  keywords: string[];
  score: number;
  reasoning: string;
}

const KEYWORD_PATTERNS: KeywordPattern[] = [
  // Trivial (0.0 - 0.2)
  {
    keywords: ['typo', 'spelling', 'whitespace', 'formatting', 'comment', 'log'],
    score: 0.1,
    reasoning: 'Trivial change (formatting/comments)',
  },
  {
    keywords: ['rename', 'move file', 'update version'],
    score: 0.15,
    reasoning: 'Simple refactoring',
  },

  // Simple (0.2 - 0.4)
  {
    keywords: ['bug fix', 'fix', 'broken', 'not working', 'quick fix'],
    score: 0.25,
    reasoning: 'Bug fix (isolated scope)',
  },
  {
    keywords: ['add test', 'test coverage', 'unit test'],
    score: 0.3,
    reasoning: 'Test addition',
  },
  {
    keywords: ['update dependency', 'upgrade package', 'version bump'],
    score: 0.35,
    reasoning: 'Dependency management',
  },

  // Moderate (0.4 - 0.6)
  {
    keywords: ['feature', 'implement', 'add functionality', 'new capability'],
    score: 0.5,
    reasoning: 'Feature implementation',
  },
  {
    keywords: ['refactor', 'restructure', 'improve code'],
    score: 0.55,
    reasoning: 'Code refactoring',
  },
  {
    keywords: ['integration', 'connect', 'api integration'],
    score: 0.6,
    reasoning: 'System integration',
  },

  // Complex (0.6 - 0.8)
  {
    keywords: ['architecture', 'design system', 'framework'],
    score: 0.7,
    reasoning: 'Architectural design',
  },
  {
    keywords: ['performance', 'optimize', 'scale', 'bottleneck'],
    score: 0.72,
    reasoning: 'Performance optimization',
  },
  {
    keywords: ['security', 'auth', 'authentication', 'authorization', 'encryption'],
    score: 0.75,
    reasoning: 'Security implementation',
  },
  {
    keywords: ['migration', 'upgrade major version', 'database migration'],
    score: 0.78,
    reasoning: 'Major migration',
  },

  // Expert (0.8 - 1.0)
  {
    keywords: ['multi-agent', 'parallel streams', 'orchestration'],
    score: 0.85,
    reasoning: 'Multi-agent orchestration',
  },
  {
    keywords: ['complete rewrite', 'rebuild from scratch', 'ground up'],
    score: 0.9,
    reasoning: 'Complete rewrite',
  },
  {
    keywords: ['distributed system', 'microservices', 'event-driven'],
    score: 0.95,
    reasoning: 'Distributed system design',
  },
];

/**
 * Score task complexity based on keywords in description
 */
function scoreKeywords(description: string): number {
  const lowerDesc = description.toLowerCase();
  let maxScore = 0;
  let matchedPattern: KeywordPattern | undefined;

  for (const pattern of KEYWORD_PATTERNS) {
    for (const keyword of pattern.keywords) {
      if (lowerDesc.includes(keyword)) {
        if (pattern.score > maxScore) {
          maxScore = pattern.score;
          matchedPattern = pattern;
        }
      }
    }
  }

  // Default to simple if no keywords match
  return maxScore || 0.3;
}

// ============================================================================
// FILE PATTERN SCORING
// ============================================================================

interface FileComplexity {
  minFiles: number;
  maxFiles?: number;
  score: number;
}

const FILE_COMPLEXITY: FileComplexity[] = [
  { minFiles: 0, maxFiles: 1, score: 0.1 },   // Single file
  { minFiles: 2, maxFiles: 3, score: 0.25 },  // 2-3 files
  { minFiles: 4, maxFiles: 5, score: 0.4 },   // 4-5 files
  { minFiles: 6, maxFiles: 10, score: 0.6 },  // 6-10 files
  { minFiles: 11, maxFiles: 20, score: 0.75 }, // 11-20 files
  { minFiles: 21, score: 0.9 },                // 20+ files
];

/**
 * Score complexity based on number of files involved
 */
function scoreFileCount(fileCount: number): number {
  for (const complexity of FILE_COMPLEXITY) {
    if (fileCount >= complexity.minFiles) {
      if (!complexity.maxFiles || fileCount <= complexity.maxFiles) {
        return complexity.score;
      }
    }
  }
  return 0.3; // Default
}

/**
 * Additional scoring for lines of code
 */
function scoreLinesOfCode(linesOfCode?: number): number {
  if (!linesOfCode) return 0.5; // Unknown, assume moderate

  if (linesOfCode < 50) return 0.1;
  if (linesOfCode < 200) return 0.3;
  if (linesOfCode < 500) return 0.5;
  if (linesOfCode < 1000) return 0.7;
  return 0.9;
}

// ============================================================================
// AGENT TYPE SCORING
// ============================================================================

const AGENT_COMPLEXITY: Record<string, number> = {
  // Trivial
  'qa': 0.2,   // Testing (usually focused)
  'doc': 0.15, // Documentation

  // Simple
  'me': 0.35,  // Implementation (variable)
  'uid': 0.3,  // UI implementation
  'cw': 0.25,  // Copywriting

  // Moderate
  'uxd': 0.5,  // UX design
  'uids': 0.5, // UI design
  'sd': 0.55,  // Service design

  // Complex
  'ta': 0.7,   // Technical architecture
  'do': 0.65,  // DevOps
  'sec': 0.75, // Security

  // Expert
  'cco': 0.8,  // Creative direction (holistic)
};

/**
 * Score complexity based on agent type
 */
function scoreAgentType(agentId?: string): number {
  if (!agentId) return 0.5; // Unknown, assume moderate
  return AGENT_COMPLEXITY[agentId] || 0.5;
}

// ============================================================================
// DOMAIN COMPLEXITY SCORING
// ============================================================================

const DOMAIN_SCORES: Record<string, number> = {
  low: 0.2,
  medium: 0.5,
  high: 0.8,
};

/**
 * Detect domain complexity from task description
 */
function detectDomainComplexity(description: string): 'low' | 'medium' | 'high' {
  const lowerDesc = description.toLowerCase();

  // High complexity domains
  const highComplexityKeywords = [
    'payment', 'transaction', 'money', 'billing',
    'auth', 'authentication', 'authorization', 'security',
    'encryption', 'cryptography', 'compliance', 'gdpr',
    'real-time', 'websocket', 'streaming', 'event-driven',
  ];

  // Medium complexity domains
  const mediumComplexityKeywords = [
    'database', 'migration', 'cache', 'api',
    'integration', 'webhook', 'notification',
    'file upload', 'image processing', 'video',
  ];

  for (const keyword of highComplexityKeywords) {
    if (lowerDesc.includes(keyword)) return 'high';
  }

  for (const keyword of mediumComplexityKeywords) {
    if (lowerDesc.includes(keyword)) return 'medium';
  }

  return 'low';
}

/**
 * Score domain complexity
 */
function scoreDomainComplexity(domain: 'low' | 'medium' | 'high'): number {
  return DOMAIN_SCORES[domain];
}

// ============================================================================
// ARCHITECTURAL IMPACT SCORING
// ============================================================================

const ARCHITECTURAL_SCORES: Record<string, number> = {
  isolated: 0.1,    // Single component, no dependencies
  component: 0.4,   // Multiple components, limited scope
  system: 0.7,      // System-wide changes
  critical: 0.95,   // Critical infrastructure
};

/**
 * Detect architectural impact from task description
 */
function detectArchitecturalImpact(
  description: string,
  fileCount: number
): 'isolated' | 'component' | 'system' | 'critical' {
  const lowerDesc = description.toLowerCase();

  // Critical infrastructure
  if (
    lowerDesc.includes('infrastructure') ||
    lowerDesc.includes('core system') ||
    lowerDesc.includes('framework') ||
    lowerDesc.includes('breaking change')
  ) {
    return 'critical';
  }

  // System-wide
  if (
    lowerDesc.includes('system-wide') ||
    lowerDesc.includes('architecture') ||
    lowerDesc.includes('refactor all') ||
    fileCount > 15
  ) {
    return 'system';
  }

  // Component-level
  if (
    lowerDesc.includes('component') ||
    lowerDesc.includes('module') ||
    fileCount > 3
  ) {
    return 'component';
  }

  // Isolated
  return 'isolated';
}

/**
 * Score architectural impact
 */
function scoreArchitecturalImpact(impact: 'isolated' | 'component' | 'system' | 'critical'): number {
  return ARCHITECTURAL_SCORES[impact];
}

// ============================================================================
// COMPLEXITY LEVEL CLASSIFICATION
// ============================================================================

/**
 * Map normalized score (0.0-1.0) to complexity level
 */
function classifyComplexity(score: number): ComplexityLevel {
  if (score < 0.2) return 'trivial';
  if (score < 0.4) return 'simple';
  if (score < 0.6) return 'moderate';
  if (score < 0.8) return 'complex';
  return 'expert';
}

// ============================================================================
// MAIN SCORING FUNCTION
// ============================================================================

export interface ScoreComplexityInput {
  /** Task description */
  description: string;

  /** Number of files involved */
  fileCount?: number;

  /** Lines of code to process */
  linesOfCode?: number;

  /** Agent type (id) */
  agentId?: string;

  /** Whether task involves multiple agents */
  multiAgent?: boolean;
}

/**
 * Score task complexity using multiple signals
 *
 * Returns ComplexityScore with normalized score (0.0-1.0),
 * confidence level, and detailed reasoning.
 *
 * @param input - Task information for scoring
 * @returns ComplexityScore with level, confidence, factors, reasoning
 */
export function scoreComplexity(input: ScoreComplexityInput): ComplexityScore {
  const startTime = performance.now();

  // Extract factors
  const fileCount = input.fileCount || 1;
  const linesOfCode = input.linesOfCode;
  const domainComplexity = detectDomainComplexity(input.description);
  const architecturalImpact = detectArchitecturalImpact(input.description, fileCount);

  // Calculate component scores
  const keywordScore = scoreKeywords(input.description);
  const fileScore = scoreFileCount(fileCount);
  const locScore = scoreLinesOfCode(linesOfCode);
  const agentScore = scoreAgentType(input.agentId);
  const domainScore = scoreDomainComplexity(domainComplexity);
  const impactScore = scoreArchitecturalImpact(architecturalImpact);

  // Weighted average
  const normalizedScore =
    keywordScore * WEIGHTS.keywords +
    ((fileScore + locScore) / 2) * WEIGHTS.filePatterns +
    agentScore * WEIGHTS.agentType +
    domainScore * WEIGHTS.domainComplexity +
    impactScore * WEIGHTS.architecturalImpact;

  // Multi-agent boost
  const finalScore = input.multiAgent
    ? Math.min(1.0, normalizedScore + 0.15)
    : normalizedScore;

  // Classify complexity level
  const level = classifyComplexity(finalScore);

  // Calculate confidence based on signal agreement
  const scores = [keywordScore, fileScore, agentScore, domainScore, impactScore];
  const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
  const variance = scores.reduce((acc, score) => acc + Math.pow(score - mean, 2), 0) / scores.length;
  const stdDev = Math.sqrt(variance);

  // Lower variance = higher confidence
  const confidence = Math.max(0.5, 1.0 - stdDev);

  // Build reasoning
  const reasoningParts: string[] = [];

  if (keywordScore > 0.6) {
    reasoningParts.push(`High-complexity keywords detected (${keywordScore.toFixed(2)})`);
  }

  if (fileCount > 10) {
    reasoningParts.push(`Large file scope (${fileCount} files)`);
  }

  if (domainComplexity === 'high') {
    reasoningParts.push(`High-complexity domain (${domainComplexity})`);
  }

  if (architecturalImpact === 'system' || architecturalImpact === 'critical') {
    reasoningParts.push(`Significant architectural impact (${architecturalImpact})`);
  }

  if (input.multiAgent) {
    reasoningParts.push('Multi-agent collaboration required');
  }

  const reasoning = reasoningParts.length > 0
    ? reasoningParts.join('. ') + '.'
    : `Standard ${level} task based on keyword analysis.`;

  // Verify performance requirement (<50ms)
  const duration = performance.now() - startTime;
  if (duration > 50) {
    console.warn(`[Complexity Scorer] Scoring took ${duration.toFixed(2)}ms (exceeds 50ms target)`);
  }

  return {
    level,
    confidence,
    factors: {
      fileCount,
      linesOfCode,
      domainComplexity,
      architecturalImpact,
      multiAgent: input.multiAgent,
    },
    reasoning,
    scoredAt: new Date().toISOString(),
  };
}

/**
 * Batch score multiple tasks
 *
 * @param inputs - Array of tasks to score
 * @returns Array of ComplexityScores
 */
export function scoreComplexityBatch(inputs: ScoreComplexityInput[]): ComplexityScore[] {
  return inputs.map(input => scoreComplexity(input));
}

/**
 * Get human-readable complexity summary
 *
 * @param score - ComplexityScore to summarize
 * @returns Human-readable summary string
 */
export function summarizeComplexity(score: ComplexityScore): string {
  const confidencePercent = (score.confidence * 100).toFixed(0);
  return `${score.level.toUpperCase()} (${confidencePercent}% confident) - ${score.reasoning}`;
}
