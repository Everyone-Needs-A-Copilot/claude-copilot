/**
 * Safety guards for Ralph Wiggum iteration loops
 *
 * Phase 2: Prevent runaway iteration loops with multiple safety mechanisms
 */

import type { IterationConfig, IterationHistoryEntry } from '../types.js';

// ============================================================================
// TYPES
// ============================================================================

export interface SafetyCheckResult {
  allowed: boolean;
  message?: string;
}

export interface QualityRegressionResult {
  regression: boolean;
  consecutiveDeclines: number;
  message?: string;
}

export interface ThrashingResult {
  thrashing: boolean;
  affectedFiles?: string[];
  message?: string;
}

export interface CircuitBreakerResult {
  open: boolean;
  consecutiveFailures: number;
  message?: string;
}

export interface CombinedSafetyResult {
  canContinue: boolean;
  blockedBy?: string;
  message?: string;
}

// ============================================================================
// CONSTANTS
// ============================================================================

const DEFAULT_THRASHING_THRESHOLD = 5;
const DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 3;
const QUALITY_REGRESSION_WINDOW = 3;

// ============================================================================
// GUARD FUNCTIONS
// ============================================================================

/**
 * Check if current iteration exceeds max allowed
 *
 * @param currentIteration - Current iteration number (1-based)
 * @param maxIterations - Maximum allowed iterations
 * @returns Safety check result
 */
export function checkMaxIterations(
  currentIteration: number,
  maxIterations: number
): SafetyCheckResult {
  if (currentIteration > maxIterations) {
    return {
      allowed: false,
      message: `Iteration ${currentIteration} exceeds maximum of ${maxIterations}. Circuit breaker triggered.`
    };
  }

  return { allowed: true };
}

/**
 * Detect quality regression by analyzing validation scores
 *
 * Triggers if validation score (pass rate) decreases 3 consecutive times.
 *
 * @param iterationHistory - Full iteration history
 * @returns Quality regression result
 */
export function checkQualityRegression(
  iterationHistory: IterationHistoryEntry[]
): QualityRegressionResult {
  if (iterationHistory.length < QUALITY_REGRESSION_WINDOW) {
    // Not enough data to detect regression
    return {
      regression: false,
      consecutiveDeclines: 0
    };
  }

  // Calculate pass rates for recent iterations
  const recentHistory = iterationHistory.slice(-QUALITY_REGRESSION_WINDOW);
  const passRates = recentHistory.map(entry => {
    const total = entry.validationResult.flags.length || 1; // Avoid division by zero
    const passed = entry.validationResult.passed ? 1 : 0;
    return passed;
  });

  // Check for consecutive declines
  let consecutiveDeclines = 0;
  for (let i = 1; i < passRates.length; i++) {
    if (passRates[i] < passRates[i - 1]) {
      consecutiveDeclines++;
    } else {
      // Reset on improvement
      consecutiveDeclines = 0;
    }
  }

  const isRegressing = consecutiveDeclines >= QUALITY_REGRESSION_WINDOW - 1;

  if (isRegressing) {
    return {
      regression: true,
      consecutiveDeclines,
      message: `Quality regression detected: Validation scores declined ${consecutiveDeclines} consecutive times. Consider changing approach.`
    };
  }

  return {
    regression: false,
    consecutiveDeclines
  };
}

/**
 * Detect thrashing - same files being modified repeatedly without progress
 *
 * Analyzes iteration history metadata for file modification patterns.
 * Triggers if the same files appear in more than `threshold` iterations.
 *
 * @param iterationHistory - Full iteration history
 * @param threshold - Number of repetitions to trigger (default: 5)
 * @returns Thrashing result
 */
export function checkThrashing(
  iterationHistory: IterationHistoryEntry[],
  threshold: number = DEFAULT_THRASHING_THRESHOLD
): ThrashingResult {
  if (iterationHistory.length < threshold) {
    // Not enough iterations to detect thrashing
    return { thrashing: false };
  }

  // Extract file paths from validation metadata
  // Note: This assumes validation results contain file information
  // in the metadata. If not present, we skip thrashing detection.
  const fileModifications = new Map<string, number>();

  for (const entry of iterationHistory) {
    // Check if validation flags contain file information
    for (const flag of entry.validationResult.flags) {
      // Extract file paths from message if present (pattern: "file: /path/to/file")
      const fileMatch = flag.message.match(/file:\s*([^\s,]+)/i);
      if (fileMatch) {
        const file = fileMatch[1];
        fileModifications.set(file, (fileModifications.get(file) || 0) + 1);
      }
    }
  }

  // Find files that appear more than threshold times
  const thrashedFiles: string[] = [];
  for (const [file, count] of fileModifications.entries()) {
    if (count >= threshold) {
      thrashedFiles.push(file);
    }
  }

  if (thrashedFiles.length > 0) {
    return {
      thrashing: true,
      affectedFiles: thrashedFiles,
      message: `Thrashing detected: ${thrashedFiles.length} file(s) modified ${threshold}+ times without progress: ${thrashedFiles.slice(0, 3).join(', ')}${thrashedFiles.length > 3 ? '...' : ''}`
    };
  }

  return { thrashing: false };
}

/**
 * Circuit breaker - open after consecutive failures
 *
 * Tracks consecutive validation failures and opens circuit breaker
 * after threshold is exceeded.
 *
 * @param iterationHistory - Full iteration history
 * @param threshold - Number of consecutive failures to trigger (default: 3)
 * @returns Circuit breaker result
 */
export function checkCircuitBreaker(
  iterationHistory: IterationHistoryEntry[],
  threshold: number = DEFAULT_CIRCUIT_BREAKER_THRESHOLD
): CircuitBreakerResult {
  if (iterationHistory.length === 0) {
    return {
      open: false,
      consecutiveFailures: 0
    };
  }

  // Count consecutive failures from the end
  let consecutiveFailures = 0;
  for (let i = iterationHistory.length - 1; i >= 0; i--) {
    if (!iterationHistory[i].validationResult.passed) {
      consecutiveFailures++;
    } else {
      // Stop counting on first success
      break;
    }
  }

  const isOpen = consecutiveFailures >= threshold;

  if (isOpen) {
    return {
      open: true,
      consecutiveFailures,
      message: `Circuit breaker OPEN: ${consecutiveFailures} consecutive validation failures (threshold: ${threshold}). Manual intervention required.`
    };
  }

  return {
    open: false,
    consecutiveFailures
  };
}

/**
 * Run all safety checks and return combined result
 *
 * Checks are run in order of severity:
 * 1. Max iterations (hard limit)
 * 2. Circuit breaker (consecutive failures)
 * 3. Quality regression (declining scores)
 * 4. Thrashing (repeated file modifications)
 *
 * @param iterationNumber - Current iteration number (1-based)
 * @param config - Iteration configuration
 * @param history - Iteration history
 * @returns Combined safety result
 */
export function runSafetyChecks(
  iterationNumber: number,
  config: IterationConfig,
  history: IterationHistoryEntry[]
): CombinedSafetyResult {
  // 1. Check max iterations (hard stop)
  const maxCheck = checkMaxIterations(iterationNumber, config.maxIterations);
  if (!maxCheck.allowed) {
    return {
      canContinue: false,
      blockedBy: 'max_iterations',
      message: maxCheck.message
    };
  }

  // 2. Check circuit breaker (consecutive failures)
  const circuitCheck = checkCircuitBreaker(
    history,
    config.circuitBreakerThreshold || DEFAULT_CIRCUIT_BREAKER_THRESHOLD
  );
  if (circuitCheck.open) {
    return {
      canContinue: false,
      blockedBy: 'circuit_breaker',
      message: circuitCheck.message
    };
  }

  // 3. Check quality regression (declining scores)
  const regressionCheck = checkQualityRegression(history);
  if (regressionCheck.regression) {
    return {
      canContinue: false,
      blockedBy: 'quality_regression',
      message: regressionCheck.message
    };
  }

  // 4. Check thrashing (repeated modifications)
  const thrashingCheck = checkThrashing(history);
  if (thrashingCheck.thrashing) {
    return {
      canContinue: false,
      blockedBy: 'thrashing',
      message: thrashingCheck.message
    };
  }

  // All checks passed
  return {
    canContinue: true
  };
}
