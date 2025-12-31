/**
 * Token Measurement Tooling for Benchmark Scenarios
 *
 * This module provides simple tools for measuring token usage across
 * different points in the Claude Copilot framework workflow.
 *
 * @example
 * ```typescript
 * import { createMeasurementTracker } from './benchmark/index.js';
 *
 * const tracker = createMeasurementTracker('BENCH-1', 'Feature Implementation');
 *
 * // Measure at different points
 * tracker.measure('main_input', userRequest);
 * tracker.measure('agent_output', agentResponse);
 * tracker.measure('main_return', summary);
 *
 * // Get metrics
 * const metrics = tracker.calculateMetrics();
 * console.log(`Context Reduction: ${metrics.percentages.contextReductionPct.toFixed(1)}%`);
 *
 * // Export to JSON
 * const results = tracker.toJSON();
 * ```
 */

export {
  countTokens,
  countCharacters,
  countWords,
  countLines,
} from './token-counter.js';

export {
  MeasurementTracker,
  createMeasurementTracker,
  type MeasurementPoint,
  type Measurement,
  type MeasurementSet,
  type EfficiencyMetrics,
} from './measurement-tracker.js';
