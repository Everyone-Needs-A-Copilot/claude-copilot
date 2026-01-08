/**
 * Quality Gates Tool
 *
 * Load and execute quality gate checks before task completion.
 * Reuses iteration validation infrastructure for command execution.
 */

import { readFile, access } from 'fs/promises';
import { constants } from 'fs';
import { resolve, dirname, join } from 'path';
import { existsSync } from 'fs';
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
// WORKING DIRECTORY DETECTION
// ============================================================================

/**
 * Find the appropriate working directory for executing quality gates
 *
 * Strategy:
 * 1. Check gate config for explicit workingDirectory
 * 2. For npm/yarn/pnpm commands, find nearest package.json from task files
 * 3. Check task metadata for files array - use common parent directory
 * 4. Fall back to project root
 *
 * @param task - Task being validated
 * @param projectRoot - Project root directory
 * @param command - Command being executed (used to detect npm/yarn/pnpm)
 * @param gateWorkingDir - Explicit working directory from gate config
 * @returns Absolute path to working directory
 */
function findWorkingDirectory(
  task: TaskRow,
  projectRoot: string,
  command: string,
  gateWorkingDir?: string
): string {
  // If gate specifies explicit working directory, use it
  if (gateWorkingDir) {
    return resolve(projectRoot, gateWorkingDir);
  }

  const metadata = JSON.parse(task.metadata);

  // For npm/yarn/pnpm commands, find nearest package.json
  const isPackageManager = /^(npm|yarn|pnpm)\s/.test(command);

  if (isPackageManager && metadata.files && Array.isArray(metadata.files) && metadata.files.length > 0) {
    // Start from the first file's directory
    const firstFile = metadata.files[0];
    let currentDir = dirname(resolve(projectRoot, firstFile));

    // Walk up directory tree looking for package.json
    while (currentDir.startsWith(projectRoot) && currentDir !== projectRoot) {
      const packageJsonPath = join(currentDir, 'package.json');
      if (existsSync(packageJsonPath)) {
        return currentDir;
      }

      const parentDir = dirname(currentDir);
      if (parentDir === currentDir) {
        // Reached filesystem root
        break;
      }
      currentDir = parentDir;
    }

    // Check project root itself
    if (existsSync(join(projectRoot, 'package.json'))) {
      return projectRoot;
    }
  }

  // For non-package-manager commands, use task files common directory
  if (metadata.files && Array.isArray(metadata.files) && metadata.files.length > 0) {
    const firstFile = metadata.files[0];
    return dirname(resolve(projectRoot, firstFile));
  }

  // Fall back to project root
  return projectRoot;
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

  // Convert gates to validation rules with smart working directory detection
  const rules: IterationValidationRule[] = [];
  for (const gateName of gateNames) {
    const gate = config.gates[gateName];
    if (!gate) {
      throw new Error(`Quality gate not found in config: ${gateName}`);
    }

    // Determine working directory for this gate
    const workingDir = findWorkingDirectory(
      task,
      projectRoot,
      gate.command,
      gate.workingDirectory
    );

    rules.push({
      type: 'command',
      name: gate.name,
      enabled: true,
      command: gate.command,
      expectedExitCode: gate.expectedExitCode ?? 0,
      timeout: gate.timeout ?? 60000,
      workingDirectory: workingDir,
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
