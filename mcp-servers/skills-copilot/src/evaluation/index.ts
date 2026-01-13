/**
 * Evaluation Module Exports
 *
 * Provides skill evaluation based on context analysis:
 * - Pattern matching for file-based triggers
 * - Keyword detection with TF-IDF scoring
 * - Quality skill detection with context-aware boosting
 * - Unified confidence scoring
 */

export { PatternMatcher, patternMatcher } from './pattern-matcher.js';
export type { PatternMatchResult, MatchedPattern } from './pattern-matcher.js';

export { KeywordDetector, keywordDetector } from './keyword-detector.js';
export type { KeywordMatchResult, MatchedKeyword } from './keyword-detector.js';

export {
  ConfidenceScorer,
  confidenceScorer,
  formatEvaluationResults,
} from './confidence-scorer.js';
export type {
  SkillEvaluation,
  EvaluationContext,
  ScorerOptions,
} from './confidence-scorer.js';
