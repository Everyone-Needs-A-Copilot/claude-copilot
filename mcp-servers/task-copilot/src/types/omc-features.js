/**
 * OMC Features Types - Shared TypeScript types for OMC learnings integration
 *
 * This module provides type definitions for 5 OMC-inspired features:
 * 1. Ecomode: Model routing based on task complexity
 * 2. Keyword modifiers: Magic keywords for model selection and task actions
 * 3. HUD: Heads-up display for real-time status
 * 4. Skill extraction: Pattern-based skill detection from work products
 * 5. Install orchestration: Dependency checking and platform detection
 *
 * @see PRD-omc-learnings (OMC Learnings Integration)
 */
// ============================================================================
// VALIDATION HELPERS
// ============================================================================
/**
 * Validates complexity score is within valid range
 */
export function isValidComplexityScore(score) {
    return score >= 0.0 && score <= 1.0;
}
/**
 * Validates model name
 */
export function isValidModel(model) {
    return ['haiku', 'sonnet', 'opus'].includes(model);
}
/**
 * Validates modifier keyword
 */
export function isValidModifier(keyword) {
    return ['eco', 'opus', 'fast', 'sonnet', 'haiku', 'auto', 'ralph'].includes(keyword);
}
/**
 * Validates action keyword
 */
export function isValidAction(keyword) {
    return ['fix', 'add', 'refactor', 'optimize', 'test', 'doc', 'deploy'].includes(keyword);
}
//# sourceMappingURL=omc-features.js.map