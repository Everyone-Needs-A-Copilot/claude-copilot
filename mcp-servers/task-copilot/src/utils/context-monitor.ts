/**
 * Context monitoring utility for automatic compaction
 *
 * Agents use this to estimate token usage and trigger automatic
 * compaction when responses exceed threshold.
 */

/**
 * Estimate token count from text
 * Conservative approach: 1 token ≈ 4 characters
 * This underestimates to leave safety buffer
 */
export function estimateTokens(text: string): number {
  if (!text || text.trim().length === 0) {
    return 0;
  }

  // Conservative estimate: 1 token ≈ 4 characters
  return Math.ceil(text.length / 4);
}

/**
 * Check if response size exceeds threshold
 *
 * @param text - Response text to check
 * @param threshold - Percentage threshold (0.0-1.0), default 0.85
 * @param maxTokens - Maximum tokens allowed, default 4096
 * @returns true if threshold exceeded
 */
export function exceedsThreshold(
  text: string,
  threshold: number = 0.85,
  maxTokens: number = 4096
): boolean {
  const estimatedTokens = estimateTokens(text);
  const thresholdTokens = Math.floor(maxTokens * threshold);

  return estimatedTokens >= thresholdTokens;
}

/**
 * Get context usage summary
 *
 * @param text - Response text to analyze
 * @param threshold - Percentage threshold (0.0-1.0), default 0.85
 * @param maxTokens - Maximum tokens allowed, default 4096
 * @returns Usage summary with token counts and warnings
 */
export function getContextUsage(
  text: string,
  threshold: number = 0.85,
  maxTokens: number = 4096
): {
  estimatedTokens: number;
  thresholdTokens: number;
  maxTokens: number;
  percentage: number;
  exceedsThreshold: boolean;
  shouldCompact: boolean;
} {
  const estimatedTokens = estimateTokens(text);
  const thresholdTokens = Math.floor(maxTokens * threshold);
  const percentage = (estimatedTokens / maxTokens) * 100;
  const shouldCompact = estimatedTokens >= thresholdTokens;

  return {
    estimatedTokens,
    thresholdTokens,
    maxTokens,
    percentage,
    exceedsThreshold: shouldCompact,
    shouldCompact
  };
}

/**
 * Extract summary from detailed content
 * Helper for creating compact summaries
 *
 * @param content - Full content to summarize
 * @param maxTokens - Maximum tokens for summary, default 100
 * @returns Truncated summary
 */
export function extractSummary(
  content: string,
  maxTokens: number = 100
): string {
  const maxChars = maxTokens * 4; // Conservative estimate

  if (content.length <= maxChars) {
    return content;
  }

  // Truncate at sentence boundary if possible
  const truncated = content.substring(0, maxChars);
  const lastPeriod = truncated.lastIndexOf('.');
  const lastNewline = truncated.lastIndexOf('\n');
  const breakPoint = Math.max(lastPeriod, lastNewline);

  if (breakPoint > maxChars * 0.5) {
    return truncated.substring(0, breakPoint + 1).trim();
  }

  return truncated.trim() + '...';
}
