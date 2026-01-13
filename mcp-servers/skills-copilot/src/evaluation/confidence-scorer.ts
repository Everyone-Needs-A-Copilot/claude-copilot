/**
 * Confidence Scoring System
 *
 * Combines pattern matching and keyword detection into a unified confidence score.
 * Implements threshold filtering with configurable cutoff.
 */

import type { SkillMeta } from '../types.js';
import { PatternMatcher, type PatternMatchResult } from './pattern-matcher.js';
import { KeywordDetector, type KeywordMatchResult } from './keyword-detector.js';

/**
 * Unified evaluation result
 */
export interface SkillEvaluation {
  skillName: string;
  /** Combined confidence score 0-1 */
  confidence: number;
  /** Confidence level category */
  level: 'high' | 'medium' | 'low';
  /** Pattern matching results */
  patternMatch?: PatternMatchResult;
  /** Keyword matching results */
  keywordMatch?: KeywordMatchResult;
  /** Human-readable explanation */
  reason: string;
  /** Whether this skill has quality-focused content */
  hasQualityKeywords?: boolean;
  /** Number of quality keywords in the skill */
  qualityKeywordCount?: number;
}

/**
 * Evaluation context input
 */
export interface EvaluationContext {
  /** File paths to analyze */
  files?: string[];
  /** Text content (prompt, conversation, etc.) */
  text?: string;
  /** Recent activity keywords */
  recentActivity?: string[];
}

/**
 * Scorer configuration options
 */
export interface ScorerOptions {
  /** Minimum confidence threshold (default: 0.3) */
  threshold?: number;
  /** Weight for pattern matching (default: 0.5) */
  patternWeight?: number;
  /** Weight for keyword matching (default: 0.5) */
  keywordWeight?: number;
  /** Maximum results to return (default: 10) */
  limit?: number;
  /** Boost for skills matching recent activity (default: 1.2) */
  activityBoost?: number;
}

const DEFAULT_OPTIONS: Required<ScorerOptions> = {
  threshold: 0.3,
  patternWeight: 0.5,
  keywordWeight: 0.5,
  limit: 10,
  activityBoost: 1.2,
};

/**
 * Confidence level thresholds
 */
const CONFIDENCE_LEVELS = {
  high: 0.7,
  medium: 0.4,
};

/**
 * Confidence Scorer class
 *
 * Combines pattern matching and keyword detection to produce
 * unified skill recommendations with confidence scores.
 */
export class ConfidenceScorer {
  private patternMatcher: PatternMatcher;
  private keywordDetector: KeywordDetector;
  private skills: Map<string, SkillMeta> = new Map();
  private indexed = false;

  constructor() {
    this.patternMatcher = new PatternMatcher();
    this.keywordDetector = new KeywordDetector();
  }

  /**
   * Set skills to evaluate against
   *
   * @param skills - Map of skill name to metadata
   */
  setSkills(skills: Map<string, SkillMeta>): void {
    this.skills = skills;
    this.keywordDetector.buildIndex(skills);
    this.indexed = true;
  }

  /**
   * Evaluate context against all skills
   *
   * @param context - Files and/or text to analyze
   * @param options - Scoring options
   * @returns Ranked list of skill evaluations above threshold
   */
  evaluate(
    context: EvaluationContext,
    options: ScorerOptions = {}
  ): SkillEvaluation[] {
    const opts = { ...DEFAULT_OPTIONS, ...options };

    if (!this.indexed || this.skills.size === 0) {
      return [];
    }

    // Get pattern matches if files provided
    const patternResults = context.files && context.files.length > 0
      ? this.patternMatcher.match(context.files, this.skills)
      : [];

    // Get keyword matches if text provided
    const keywordResults = context.text
      ? this.keywordDetector.match(context.text, this.skills)
      : [];

    // Combine results
    const combined = this.combineResults(
      patternResults,
      keywordResults,
      opts,
      context.recentActivity
    );

    // Filter by threshold and limit
    return combined
      .filter(r => r.confidence >= opts.threshold)
      .slice(0, opts.limit);
  }

  /**
   * Quick check if any skill matches context above threshold
   *
   * @param context - Context to check
   * @param threshold - Minimum confidence (default: 0.5)
   * @returns True if any skill matches above threshold
   */
  hasMatch(context: EvaluationContext, threshold = 0.5): boolean {
    const results = this.evaluate(context, { threshold, limit: 1 });
    return results.length > 0;
  }

  /**
   * Get the best matching skill for context
   *
   * @param context - Context to check
   * @param threshold - Minimum confidence (default: 0.3)
   * @returns Best matching skill or null
   */
  getBestMatch(context: EvaluationContext, threshold = 0.3): SkillEvaluation | null {
    const results = this.evaluate(context, { threshold, limit: 1 });
    return results.length > 0 ? results[0] : null;
  }

  /**
   * Combine pattern and keyword results into unified evaluations
   */
  private combineResults(
    patternResults: PatternMatchResult[],
    keywordResults: KeywordMatchResult[],
    options: Required<ScorerOptions>,
    recentActivity?: string[]
  ): SkillEvaluation[] {
    // Create maps for quick lookup
    const patternMap = new Map<string, PatternMatchResult>();
    for (const result of patternResults) {
      patternMap.set(result.skillName, result);
    }

    const keywordMap = new Map<string, KeywordMatchResult>();
    for (const result of keywordResults) {
      keywordMap.set(result.skillName, result);
    }

    // Get all unique skill names
    const allSkills = new Set([
      ...patternMap.keys(),
      ...keywordMap.keys(),
    ]);

    // Create recent activity set for boosting
    const activitySet = new Set(
      (recentActivity || []).map(a => a.toLowerCase())
    );

    // Combine scores
    const evaluations: SkillEvaluation[] = [];

    for (const skillName of allSkills) {
      const patternMatch = patternMap.get(skillName);
      const keywordMatch = keywordMap.get(skillName);

      // Calculate combined confidence
      let confidence = this.calculateCombinedConfidence(
        patternMatch?.confidence || 0,
        keywordMatch?.confidence || 0,
        options.patternWeight,
        options.keywordWeight
      );

      // Apply activity boost if skill name matches recent activity
      if (activitySet.has(skillName.toLowerCase())) {
        confidence = Math.min(confidence * options.activityBoost, 1);
      }

      // Determine confidence level
      const level = this.getConfidenceLevel(confidence);

      // Extract quality information from keyword match
      const hasQualityKeywords = keywordMatch?.hasQualityKeywords ?? false;
      const qualityKeywordCount = keywordMatch?.qualityKeywordCount ?? 0;

      // Generate explanation
      const reason = this.generateReason(patternMatch, keywordMatch, confidence);

      evaluations.push({
        skillName,
        confidence,
        level,
        patternMatch,
        keywordMatch,
        reason,
        hasQualityKeywords,
        qualityKeywordCount,
      });
    }

    // Sort by confidence descending
    return evaluations.sort((a, b) => b.confidence - a.confidence);
  }

  /**
   * Calculate combined confidence from pattern and keyword scores
   *
   * Uses weighted combination with bonus for multi-signal matches
   */
  private calculateCombinedConfidence(
    patternConfidence: number,
    keywordConfidence: number,
    patternWeight: number,
    keywordWeight: number
  ): number {
    // If only one signal, use it directly (scaled slightly lower)
    if (patternConfidence === 0 && keywordConfidence > 0) {
      return keywordConfidence * 0.9;
    }
    if (keywordConfidence === 0 && patternConfidence > 0) {
      return patternConfidence * 0.9;
    }

    // Weighted combination
    const weighted = (patternConfidence * patternWeight) +
                    (keywordConfidence * keywordWeight);

    // Bonus for multi-signal agreement (both signals present)
    // This rewards skills that match on multiple dimensions
    const agreementBonus = Math.min(patternConfidence, keywordConfidence) * 0.1;

    return Math.min(weighted + agreementBonus, 1);
  }

  /**
   * Get confidence level category
   */
  private getConfidenceLevel(confidence: number): 'high' | 'medium' | 'low' {
    if (confidence >= CONFIDENCE_LEVELS.high) return 'high';
    if (confidence >= CONFIDENCE_LEVELS.medium) return 'medium';
    return 'low';
  }

  /**
   * Generate human-readable explanation for the match
   */
  private generateReason(
    patternMatch?: PatternMatchResult,
    keywordMatch?: KeywordMatchResult,
    confidence?: number
  ): string {
    const parts: string[] = [];

    if (patternMatch && patternMatch.matchedPatterns.length > 0) {
      const patterns = patternMatch.matchedPatterns
        .slice(0, 3)
        .map(p => p.pattern);
      parts.push(`File patterns: ${patterns.join(', ')}`);
    }

    if (keywordMatch && keywordMatch.matchedKeywords.length > 0) {
      const keywords = keywordMatch.matchedKeywords
        .slice(0, 5)
        .map(k => k.keyword);
      parts.push(`Keywords: ${keywords.join(', ')}`);
    }

    if (parts.length === 0) {
      return 'No specific match details';
    }

    return parts.join(' | ');
  }
}

/**
 * Default singleton instance
 */
export const confidenceScorer = new ConfidenceScorer();

/**
 * Helper function to format evaluation results for display
 */
export function formatEvaluationResults(
  results: SkillEvaluation[],
  showDetails = false
): string {
  if (results.length === 0) {
    return 'No skills matched the current context.';
  }

  // Separate quality skills for highlighting
  const qualitySkills = results.filter(r => r.hasQualityKeywords);
  const hasQualityContext = qualitySkills.length > 0;

  let output = `## Skill Evaluation Results (${results.length} matched)\n\n`;

  // Quality skills section
  if (hasQualityContext && qualitySkills.length > 0) {
    output += '### Quality-Focused Skills\n';
    output += '| Skill | Confidence | Quality Keywords | Reason |\n';
    output += '|-------|------------|-----------------|--------|\n';

    for (const result of qualitySkills.slice(0, 5)) {
      const confPercent = (result.confidence * 100).toFixed(0);
      const qualityCount = result.qualityKeywordCount || 0;
      const truncatedReason = result.reason.length > 40
        ? result.reason.slice(0, 37) + '...'
        : result.reason;

      output += `| ${result.skillName} | ${confPercent}% | ${qualityCount} | ${truncatedReason} |\n`;
    }
    output += '\n';
  }

  // All matches section
  output += '### All Matches\n';
  output += '| Skill | Confidence | Level | Reason |\n';
  output += '|-------|------------|-------|--------|\n';

  for (const result of results) {
    const confPercent = (result.confidence * 100).toFixed(0);
    const levelEmoji = result.level === 'high' ? '' :
                       result.level === 'medium' ? '' : '';
    const qualityIndicator = result.hasQualityKeywords ? ' [Q]' : '';
    const truncatedReason = result.reason.length > 50
      ? result.reason.slice(0, 47) + '...'
      : result.reason;

    output += `| ${result.skillName}${qualityIndicator} | ${confPercent}% | ${levelEmoji} ${result.level} | ${truncatedReason} |\n`;
  }

  if (showDetails && results.length > 0) {
    output += '\n### Match Details\n\n';
    for (const result of results.slice(0, 3)) {
      output += `**${result.skillName}** (${(result.confidence * 100).toFixed(0)}%)`;
      if (result.hasQualityKeywords) {
        output += ` - Quality skill (${result.qualityKeywordCount} quality keywords)`;
      }
      output += `\n- ${result.reason}\n\n`;
    }
  }

  output += '\n[Q] = Quality-focused skill with anti-patterns, best practices, or validation rules.\n';
  output += '\nUse `skill_get(name)` to load a skill.';

  return output;
}
