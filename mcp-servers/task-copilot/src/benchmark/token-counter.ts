/**
 * Simple token counter for benchmark measurements
 * Uses word-based approximation: tokens ≈ words * 1.3
 *
 * This is intentionally simple - for internal testing only, not production use.
 */

/**
 * Count approximate tokens in text
 * Uses the common heuristic: tokens ≈ words * 1.3
 */
export function countTokens(text: string): number {
  if (!text || text.trim().length === 0) {
    return 0;
  }

  // Split on whitespace and filter empty strings
  const words = text.trim().split(/\s+/).filter(w => w.length > 0);

  // Apply 1.3x multiplier for token approximation
  return Math.round(words.length * 1.3);
}

/**
 * Count characters in text (for alternate metrics)
 */
export function countCharacters(text: string): number {
  return text.length;
}

/**
 * Get word count (for reference)
 */
export function countWords(text: string): number {
  if (!text || text.trim().length === 0) {
    return 0;
  }
  return text.trim().split(/\s+/).filter(w => w.length > 0).length;
}

/**
 * Count lines in text
 */
export function countLines(text: string): number {
  if (!text || text.trim().length === 0) {
    return 0;
  }
  return text.split('\n').length;
}
