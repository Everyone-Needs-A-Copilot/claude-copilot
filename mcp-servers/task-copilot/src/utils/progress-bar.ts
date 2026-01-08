/**
 * ASCII Progress Bar Utility
 *
 * Renders visual progress bars for task completion tracking
 */

export interface ProgressBarOptions {
  width?: number; // Total width in characters (default: 20)
  filled?: string; // Character for filled portion (default: '█')
  empty?: string; // Character for empty portion (default: '░')
  showPercentage?: boolean; // Show percentage label (default: true)
  showCount?: boolean; // Show count label like (8/20) (default: true)
}

/**
 * Render an ASCII progress bar
 *
 * @param completed - Number of completed items
 * @param total - Total number of items
 * @param options - Rendering options
 * @returns Formatted progress bar string
 *
 * @example
 * renderProgressBar(8, 20)
 * // Returns: "[████████░░░░░░░░░░░░] 40% (8/20)"
 */
export function renderProgressBar(
  completed: number,
  total: number,
  options: ProgressBarOptions = {}
): string {
  const {
    width = 20,
    filled = '█',
    empty = '░',
    showPercentage = true,
    showCount = true
  } = options;

  // Handle edge cases
  if (total === 0) {
    const bar = empty.repeat(width);
    return `[${bar}] 0%${showCount ? ' (0/0)' : ''}`;
  }

  // Clamp negative values to 0 for rendering (but preserve original for display)
  const clampedCompleted = Math.max(0, completed);
  const clampedTotal = Math.max(0, total);

  // Calculate percentage and filled width
  const percentage = Math.floor((clampedCompleted / clampedTotal) * 100);
  const filledWidth = Math.max(0, Math.floor((clampedCompleted / clampedTotal) * width));
  const emptyWidth = Math.max(0, width - filledWidth);

  // Build progress bar
  const filledPart = filled.repeat(filledWidth);
  const emptyPart = empty.repeat(emptyWidth);
  const bar = `[${filledPart}${emptyPart}]`;

  // Build labels (use original values for display)
  const labels: string[] = [];
  if (showPercentage) {
    labels.push(`${percentage}%`);
  }
  if (showCount) {
    labels.push(`(${completed}/${total})`);
  }

  return labels.length > 0 ? `${bar} ${labels.join(' ')}` : bar;
}

/**
 * Render multiple progress bars with labels
 *
 * @param items - Array of items with label, completed, and total
 * @param options - Rendering options
 * @returns Multi-line progress bar string
 *
 * @example
 * renderMultiProgressBars([
 *   { label: 'Frontend', completed: 5, total: 10 },
 *   { label: 'Backend', completed: 8, total: 10 }
 * ])
 * // Returns:
 * // "Frontend: [██████████░░░░░░░░░░] 50% (5/10)
 * //  Backend:  [████████████████░░░░] 80% (8/10)"
 */
export function renderMultiProgressBars(
  items: Array<{ label: string; completed: number; total: number }>,
  options: ProgressBarOptions = {}
): string {
  if (items.length === 0) {
    return '';
  }

  // Find longest label for alignment
  const maxLabelLength = Math.max(...items.map(item => item.label.length));

  // Render each bar with aligned labels
  return items
    .map(item => {
      const paddedLabel = item.label.padEnd(maxLabelLength);
      const bar = renderProgressBar(item.completed, item.total, {
        ...options,
        showPercentage: true,
        showCount: true
      });
      return `${paddedLabel}: ${bar}`;
    })
    .join('\n');
}

/**
 * Calculate trend indicator based on values
 *
 * @param current - Current value
 * @param previous - Previous value
 * @param threshold - Percentage threshold for change (default: 10%)
 * @returns Trend indicator: '↗', '→', or '↘'
 */
export function calculateTrendIndicator(
  current: number,
  previous: number,
  threshold: number = 0.1
): '↗' | '→' | '↘' {
  if (previous === 0) {
    return current > 0 ? '↗' : '→';
  }

  const change = (current - previous) / previous;

  if (change > threshold) return '↗'; // Improving
  if (change < -threshold) return '↘'; // Declining
  return '→'; // Stable
}
