/**
 * Quality Gates Tool
 *
 * Load and execute quality gate checks before task completion.
 * Reuses iteration validation infrastructure for command execution.
 */

import { readFile, access } from 'fs/promises';
import { constants } from 'fs';
import { resolve } from 'path';
import type { DatabaseClient } from '../database.js';
import type { TaskRow } from '../types.js';
import { getIterationEngine } from '../validation/iteration-engine.js';
import type { IterationValidationRule } from '../validation/iteration-types.js';

// ============================================================================
// TYPES
// ============================================================================

export interface QualityGateConfig {
  version: string;
  defaultGates: string[];
  gates: Record<string, QualityGate>;
}

export interface QualityGate {
  name: string;
  description: string;
  command: string;
  expectedExitCode?: number;
  timeout?: number;
  workingDirectory?: string;
  env?: Record<string, string>;
}

export interface QualityGateResult {
  gateName: string;
  passed: boolean;
  message: string;
  command: string;
  exitCode?: number;
  stdout?: string;
  stderr?: string;
  error?: string;
}

export interface QualityGateReport {
  taskId: string;
  totalGates: number;
  passedGates: number;
  failedGates: number;
  allPassed: boolean;
  results: QualityGateResult[];
  executedAt: string;
}

// ============================================================================
// CONFIG LOADING
// ============================================================================

let cachedConfig: QualityGateConfig | null = null;

/**
 * Load quality gates configuration from .claude/quality-gates.json
 *
 * Searches in:
 * 1. Project root (.claude/quality-gates.json)
 * 2. Fallback to empty config if not found
 */
export async function loadQualityGatesConfig(projectRoot: string): Promise<QualityGateConfig> {
  // Return cached config if available
  if (cachedConfig) {
    return cachedConfig;
  }

  const configPath = resolve(projectRoot, '.claude', 'quality-gates.json');

  try {
    // Check if file exists
    await access(configPath, constants.F_OK);

    // Read and parse config
    const configContent = await readFile(configPath, 'utf-8');
    const config = JSON.parse(configContent) as QualityGateConfig;

    // Validate config structure
    if (!config.version || !config.gates) {
      throw new Error('Invalid quality gates config: missing version or gates');
    }

    cachedConfig = config;
    return config;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      // Config file not found - return empty config
      const emptyConfig: QualityGateConfig = {
        version: '1.0',
        defaultGates: [],
        gates: {}
      };
      cachedConfig = emptyConfig;
      return emptyConfig;
    }

    // Re-throw other errors (parsing errors, etc.)
    throw new Error(
      `Failed to load quality gates config: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Clear cached config (useful for testing)
 */
export function clearConfigCache(): void {
  cachedConfig = null;
}

// ============================================================================
// GATE EXECUTION
// ============================================================================

/**
 * Execute quality gates for a task
 *
 * @param db - Database client
 * @param task - Task to check gates for
 * @param projectRoot - Project root directory
 * @returns Quality gate report
 */
export async function executeQualityGates(
  db: DatabaseClient,
  task: TaskRow,
  projectRoot: string
): Promise<QualityGateReport> {
  const startTime = new Date().toISOString();

  // Load config
  const config = await loadQualityGatesConfig(projectRoot);

  // Get gates to execute
  const metadata = JSON.parse(task.metadata);
  const gateNames = (metadata.qualityGates as string[] | undefined) || config.defaultGates;

  // If no gates configured, return success
  if (gateNames.length === 0) {
    return {
      taskId: task.id,
      totalGates: 0,
      passedGates: 0,
      failedGates: 0,
      allPassed: true,
      results: [],
      executedAt: startTime
    };
  }

  // Convert gates to validation rules
  const rules: IterationValidationRule[] = [];
  for (const gateName of gateNames) {
    const gate = config.gates[gateName];
    if (!gate) {
      throw new Error(`Quality gate not found in config: ${gateName}`);
    }

    rules.push({
      type: 'command',
      name: gate.name,
      enabled: true,
      command: gate.command,
      expectedExitCode: gate.expectedExitCode ?? 0,
      timeout: gate.timeout,
      workingDirectory: gate.workingDirectory,
      env: gate.env
    });
  }

  // Execute gates using iteration validation engine
  const engine = getIterationEngine();
  const validationReport = await engine.validate(
    rules,
    {
      taskId: task.id,
      workingDirectory: projectRoot,
      taskNotes: task.notes ?? undefined
    },
    task.id,
    0 // Not part of an iteration
  );

  // Convert validation results to quality gate results
  const results: QualityGateResult[] = validationReport.results.map(r => ({
    gateName: r.ruleName,
    passed: r.passed,
    message: r.message,
    command: (r.details as any)?.command || 'unknown',
    exitCode: (r.details as any)?.exitCode,
    stdout: (r.details as any)?.stdout,
    stderr: (r.details as any)?.stderr,
    error: r.error
  }));

  return {
    taskId: task.id,
    totalGates: results.length,
    passedGates: results.filter(r => r.passed).length,
    failedGates: results.filter(r => !r.passed).length,
    allPassed: validationReport.overallPassed,
    results,
    executedAt: startTime
  };
}

/**
 * Check if quality gates should be enforced for a task update
 *
 * @param task - Task being updated
 * @param newStatus - Status being set
 * @returns True if gates should be checked
 */
export function shouldEnforceQualityGates(task: TaskRow, newStatus?: string): boolean {
  // Only enforce when transitioning to 'completed'
  if (newStatus !== 'completed') {
    return false;
  }

  // Don't enforce if already completed (idempotent updates)
  if (task.status === 'completed') {
    return false;
  }

  return true;
}
