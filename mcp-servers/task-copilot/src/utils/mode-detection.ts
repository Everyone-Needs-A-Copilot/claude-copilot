/**
 * Activation Mode Detection Utility
 *
 * Detects agent execution modes from task titles and descriptions
 * using keyword matching.
 */

export type ActivationMode = 'ultrawork' | 'analyze' | 'quick' | 'thorough';

/**
 * Keyword patterns for each activation mode
 * Patterns are case-insensitive and match word prefixes
 * (e.g., "thorough" matches "thorough", "thoroughly", "thoroughness")
 */
const MODE_PATTERNS: Record<ActivationMode, RegExp> = {
  // Ultrawork: atomic, focused tasks (matches GSD keywords)
  ultrawork: /\bultrawork\b|\bsimple|\bminor\b|\btypo|\bhotfix|\btweak/i,
  // Analyze: matches "analyze", "analysis", "analyzing", "analyzed", etc.
  analyze: /\banalyz|\banalys/i,
  // Quick: matches "quick", "quickly", "fast", "rapid", "rapidly"
  quick: /\bquick|\bfast|\brapid/i,
  // Thorough: complex, deep work (matches complex/architecture keywords)
  // Matches word prefixes for thorough, comprehensive, detailed, complex, architecture
  thorough: /\bthorough|\bcomprehensive|\bdetailed|\bin-depth\b|\bcomplex|\barchitecture|\brefactor|\bredesign|\bsystem\b/i
};

/**
 * Detect activation mode from text (title and/or description)
 *
 * Detection rules:
 * - Searches for keywords in order: ultrawork, analyze, quick, thorough
 * - Returns the LAST matching keyword if multiple are found (last wins)
 * - Returns null if no keywords are detected
 * - Case-insensitive matching
 * - Matches word prefixes (e.g., "analyze" matches "analyzing", "thorough" matches "thoroughly")
 * - Word boundary at start ensures "ultrawork" won't match "xultrawork"
 *
 * @param title - Task title
 * @param description - Optional task description
 * @returns Detected activation mode or null
 */
export function detectActivationMode(
  title: string,
  description?: string
): ActivationMode | null {
  const combinedText = description ? `${title} ${description}` : title;

  // Track all matches with their positions
  const matches: Array<{ mode: ActivationMode; position: number }> = [];

  for (const [mode, pattern] of Object.entries(MODE_PATTERNS) as Array<[ActivationMode, RegExp]>) {
    const match = pattern.exec(combinedText);
    if (match) {
      matches.push({ mode, position: match.index });
    }
  }

  // If no matches, return null
  if (matches.length === 0) {
    return null;
  }

  // Sort by position and return the last match (conflict resolution: last keyword wins)
  matches.sort((a, b) => a.position - b.position);
  return matches[matches.length - 1].mode;
}

/**
 * Validate if a string is a valid activation mode
 *
 * @param mode - String to validate
 * @returns True if valid activation mode
 */
export function isValidActivationMode(mode: string): mode is ActivationMode {
  return ['ultrawork', 'analyze', 'quick', 'thorough'].includes(mode);
}
