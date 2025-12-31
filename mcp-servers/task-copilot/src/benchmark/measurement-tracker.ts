/**
 * Tracks token measurements at different points in a workflow
 * Calculates efficiency metrics for benchmark scenarios
 */

import { countTokens, countCharacters, countWords, countLines } from './token-counter.js';

/**
 * Measurement points in the framework workflow
 * Based on the technical design (WP-e06d5be3-8595-4dbd-a6bd-2c7d5d15a1b4)
 */
export type MeasurementPoint =
  | 'main_input'        // User's initial request to main session
  | 'main_context'      // Total context loaded in main session
  | 'agent_output'      // Full content produced by agent
  | 'main_return'       // Summary returned to main session
  | 'storage'           // Content stored in Task Copilot
  | 'retrieval';        // Content retrieved from Task Copilot

/**
 * Single measurement at a point in time
 */
export interface Measurement {
  point: MeasurementPoint;
  text: string;
  tokens: number;
  characters: number;
  words: number;
  lines: number;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

/**
 * Collection of measurements for a scenario
 */
export interface MeasurementSet {
  scenarioId: string;
  scenarioName: string;
  measurements: Measurement[];
  startTime: string;
  endTime?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Efficiency metrics calculated from measurements
 */
export interface EfficiencyMetrics {
  // Context Reduction: (agent_output - main_return) / agent_output
  contextReduction: number;

  // Storage Overhead: (storage - agent_output) / agent_output
  storageOverhead: number;

  // Compression Ratio: agent_output / storage
  compressionRatio: number;

  // Main Session Load: main_context / (main_input + main_return)
  mainSessionLoad: number;

  // Total tokens at each measurement point
  totalTokens: {
    mainInput: number;
    mainContext: number;
    agentOutput: number;
    mainReturn: number;
    storage: number;
    retrieval: number;
  };

  // Percentage breakdowns
  percentages: {
    contextReductionPct: number;
    storageOverheadPct: number;
    mainReturnVsAgentOutputPct: number;
  };
}

/**
 * Track measurements for a workflow scenario
 */
export class MeasurementTracker {
  private measurements: Map<MeasurementPoint, Measurement> = new Map();
  private scenarioId: string;
  private scenarioName: string;
  private startTime: string;
  private metadata: Record<string, unknown>;

  constructor(scenarioId: string, scenarioName: string, metadata?: Record<string, unknown>) {
    this.scenarioId = scenarioId;
    this.scenarioName = scenarioName;
    this.startTime = new Date().toISOString();
    this.metadata = metadata || {};
  }

  /**
   * Record a measurement at a specific point
   */
  measure(point: MeasurementPoint, text: string, metadata?: Record<string, unknown>): Measurement {
    const measurement: Measurement = {
      point,
      text,
      tokens: countTokens(text),
      characters: countCharacters(text),
      words: countWords(text),
      lines: countLines(text),
      timestamp: new Date().toISOString(),
      metadata,
    };

    this.measurements.set(point, measurement);
    return measurement;
  }

  /**
   * Get a specific measurement
   */
  getMeasurement(point: MeasurementPoint): Measurement | undefined {
    return this.measurements.get(point);
  }

  /**
   * Get all measurements
   */
  getAllMeasurements(): Measurement[] {
    return Array.from(this.measurements.values());
  }

  /**
   * Calculate efficiency metrics from collected measurements
   */
  calculateMetrics(): EfficiencyMetrics {
    const mainInput = this.measurements.get('main_input')?.tokens || 0;
    const mainContext = this.measurements.get('main_context')?.tokens || 0;
    const agentOutput = this.measurements.get('agent_output')?.tokens || 0;
    const mainReturn = this.measurements.get('main_return')?.tokens || 0;
    const storage = this.measurements.get('storage')?.tokens || 0;
    const retrieval = this.measurements.get('retrieval')?.tokens || 0;

    // Context Reduction: how much we reduced the agent output before returning to main
    const contextReduction = agentOutput > 0
      ? (agentOutput - mainReturn) / agentOutput
      : 0;

    // Storage Overhead: additional metadata/structure added during storage
    const storageOverhead = agentOutput > 0
      ? (storage - agentOutput) / agentOutput
      : 0;

    // Compression Ratio: how efficiently we stored the output
    const compressionRatio = storage > 0
      ? agentOutput / storage
      : 0;

    // Main Session Load: total context vs inputs
    const mainSessionLoad = (mainInput + mainReturn) > 0
      ? mainContext / (mainInput + mainReturn)
      : 0;

    return {
      contextReduction,
      storageOverhead,
      compressionRatio,
      mainSessionLoad,
      totalTokens: {
        mainInput,
        mainContext,
        agentOutput,
        mainReturn,
        storage,
        retrieval,
      },
      percentages: {
        contextReductionPct: contextReduction * 100,
        storageOverheadPct: storageOverhead * 100,
        mainReturnVsAgentOutputPct: agentOutput > 0 ? (mainReturn / agentOutput) * 100 : 0,
      },
    };
  }

  /**
   * Export to JSON format
   */
  toJSON(): {
    scenarioId: string;
    scenarioName: string;
    startTime: string;
    endTime: string;
    metadata: Record<string, unknown>;
    measurements: Measurement[];
    metrics: EfficiencyMetrics;
  } {
    return {
      scenarioId: this.scenarioId,
      scenarioName: this.scenarioName,
      startTime: this.startTime,
      endTime: new Date().toISOString(),
      metadata: this.metadata,
      measurements: this.getAllMeasurements(),
      metrics: this.calculateMetrics(),
    };
  }

  /**
   * Generate a human-readable summary
   */
  generateSummary(): string {
    const metrics = this.calculateMetrics();
    const lines: string[] = [];

    lines.push(`Scenario: ${this.scenarioName} (${this.scenarioId})`);
    lines.push('');
    lines.push('Token Counts:');
    lines.push(`  Main Input:    ${metrics.totalTokens.mainInput.toLocaleString()}`);
    lines.push(`  Main Context:  ${metrics.totalTokens.mainContext.toLocaleString()}`);
    lines.push(`  Agent Output:  ${metrics.totalTokens.agentOutput.toLocaleString()}`);
    lines.push(`  Main Return:   ${metrics.totalTokens.mainReturn.toLocaleString()}`);
    lines.push(`  Storage:       ${metrics.totalTokens.storage.toLocaleString()}`);
    lines.push(`  Retrieval:     ${metrics.totalTokens.retrieval.toLocaleString()}`);
    lines.push('');
    lines.push('Efficiency Metrics:');
    lines.push(`  Context Reduction:      ${metrics.percentages.contextReductionPct.toFixed(1)}%`);
    lines.push(`  Storage Overhead:       ${metrics.percentages.storageOverheadPct.toFixed(1)}%`);
    lines.push(`  Compression Ratio:      ${metrics.compressionRatio.toFixed(2)}x`);
    lines.push(`  Main Session Load:      ${metrics.mainSessionLoad.toFixed(2)}x`);
    lines.push(`  Return vs Output:       ${metrics.percentages.mainReturnVsAgentOutputPct.toFixed(1)}%`);

    return lines.join('\n');
  }
}

/**
 * Simple factory for creating trackers
 */
export function createMeasurementTracker(
  scenarioId: string,
  scenarioName: string,
  metadata?: Record<string, unknown>
): MeasurementTracker {
  return new MeasurementTracker(scenarioId, scenarioName, metadata);
}
