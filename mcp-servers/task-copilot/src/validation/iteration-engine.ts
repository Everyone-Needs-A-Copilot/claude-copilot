/**
 * Ralph Wiggum Iteration Validation Engine
 *
 * Validates iteration completion criteria using configurable rules
 */

import { exec } from 'child_process';
import { promisify } from 'util';
import { readFile, access } from 'fs/promises';
import { constants } from 'fs';
import { resolve } from 'path';
import type {
  IterationValidationRule,
  IterationValidationResult,
  IterationValidationReport,
  CommandRule,
  ContentPatternRule,
  CoverageRule,
  FileExistenceRule,
  CustomRule,
  IterationValidationConfig,
} from './iteration-types.js';

const execAsync = promisify(exec);

/**
 * Custom validator function type
 */
type CustomValidator = (
  rule: CustomRule,
  context: ValidationContext
) => Promise<IterationValidationResult>;

/**
 * Validation context passed to validators
 */
export interface ValidationContext {
  taskId: string;
  workingDirectory: string;
  agentOutput?: string;
  taskNotes?: string;
  latestWorkProduct?: string;
}

/**
 * Iteration Validation Engine
 */
export class IterationValidationEngine {
  private customValidators: Map<string, CustomValidator> = new Map();
  private defaultTimeout: number = 60000; // 60 seconds
  private maxConcurrentValidations: number = 5;

  constructor(config?: Partial<IterationValidationConfig>) {
    if (config?.defaultTimeout) {
      this.defaultTimeout = config.defaultTimeout;
    }
    if (config?.maxConcurrentValidations) {
      this.maxConcurrentValidations = config.maxConcurrentValidations;
    }
  }

  /**
   * Register a custom validator
   */
  registerCustomValidator(id: string, validator: CustomValidator): void {
    this.customValidators.set(id, validator);
  }

  /**
   * Validate all rules for an iteration
   */
  async validate(
    rules: IterationValidationRule[],
    context: ValidationContext,
    taskId: string,
    iterationNumber: number = 1
  ): Promise<IterationValidationReport> {
    const startTime = Date.now();
    const results: IterationValidationResult[] = [];

    // Filter enabled rules
    const enabledRules = rules.filter(r => r.enabled);

    // Process rules in batches to respect concurrency limit
    for (let i = 0; i < enabledRules.length; i += this.maxConcurrentValidations) {
      const batch = enabledRules.slice(i, i + this.maxConcurrentValidations);
      const batchResults = await Promise.all(
        batch.map(rule => this.validateRule(rule, context))
      );
      results.push(...batchResults);
    }

    const totalDuration = Date.now() - startTime;
    const passedRules = results.filter(r => r.passed && !r.error).length;
    const failedRules = results.filter(r => !r.passed && !r.error).length;
    const erroredRules = results.filter(r => r.error).length;

    return {
      taskId,
      iterationNumber,
      results,
      overallPassed: failedRules === 0 && erroredRules === 0 && results.length > 0,
      totalRules: results.length,
      passedRules,
      failedRules,
      erroredRules,
      totalDuration,
      validatedAt: new Date().toISOString(),
    };
  }

  /**
   * Validate a single rule
   */
  private async validateRule(
    rule: IterationValidationRule,
    context: ValidationContext
  ): Promise<IterationValidationResult> {
    const startTime = Date.now();

    try {
      let result: IterationValidationResult;

      switch (rule.type) {
        case 'command':
          result = await this.validateCommand(rule, context);
          break;
        case 'content_pattern':
          result = await this.validateContentPattern(rule, context);
          break;
        case 'coverage':
          result = await this.validateCoverage(rule, context);
          break;
        case 'file_existence':
          result = await this.validateFileExistence(rule, context);
          break;
        case 'custom':
          result = await this.validateCustom(rule, context);
          break;
        default: {
          const unknownRule = rule as { type: string; name: string };
          result = {
            ruleName: unknownRule.name,
            passed: false,
            message: `Unknown rule type: ${unknownRule.type}`,
            duration: Date.now() - startTime,
            timestamp: new Date().toISOString(),
            error: 'Unknown rule type',
          };
          break;
        }
      }

      return result;
    } catch (error) {
      return {
        ruleName: rule.name,
        passed: false,
        message: `Validation error: ${error instanceof Error ? error.message : String(error)}`,
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * Command validator - Execute shell command and check exit code
   */
  async validateCommand(
    rule: CommandRule,
    context: ValidationContext
  ): Promise<IterationValidationResult> {
    const startTime = Date.now();

    try {
      const timeout = rule.timeout || this.defaultTimeout;
      const cwd = rule.workingDirectory || context.workingDirectory;
      const env = rule.env ? { ...process.env, ...rule.env } : process.env;

      const { stdout, stderr } = await execAsync(rule.command, {
        cwd,
        env,
        timeout,
        maxBuffer: 10 * 1024 * 1024, // 10MB buffer
      });

      // Command executed successfully (exit code 0)
      const passed = rule.expectedExitCode === 0;

      return {
        ruleName: rule.name,
        passed,
        message: passed
          ? `Command executed successfully`
          : `Command exit code mismatch (expected ${rule.expectedExitCode}, got 0)`,
        details: {
          command: rule.command,
          exitCode: 0,
          expectedExitCode: rule.expectedExitCode,
          stdout: stdout.substring(0, 1000), // Truncate to 1000 chars
          stderr: stderr.substring(0, 1000),
        },
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
      };
    } catch (error: any) {
      // Command failed with non-zero exit code
      const exitCode = error.code || -1;
      const passed = exitCode === rule.expectedExitCode;

      return {
        ruleName: rule.name,
        passed,
        message: passed
          ? `Command failed as expected (exit code ${exitCode})`
          : `Command exit code mismatch (expected ${rule.expectedExitCode}, got ${exitCode})`,
        details: {
          command: rule.command,
          exitCode,
          expectedExitCode: rule.expectedExitCode,
          stdout: error.stdout?.substring(0, 1000),
          stderr: error.stderr?.substring(0, 1000),
          error: error.message,
        },
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
        ...(error.killed && { error: `Command timeout after ${rule.timeout}ms` }),
      };
    }
  }

  /**
   * Content pattern validator - Regex matching in output
   */
  async validateContentPattern(
    rule: ContentPatternRule,
    context: ValidationContext
  ): Promise<IterationValidationResult> {
    const startTime = Date.now();

    try {
      // Get target content
      let content: string | undefined;
      switch (rule.target) {
        case 'agent_output':
          content = context.agentOutput;
          break;
        case 'task_notes':
          content = context.taskNotes;
          break;
        case 'work_product_latest':
          content = context.latestWorkProduct;
          break;
      }

      if (!content) {
        return {
          ruleName: rule.name,
          passed: false,
          message: `Target content not available: ${rule.target}`,
          duration: Date.now() - startTime,
          timestamp: new Date().toISOString(),
          error: 'Target content not available',
        };
      }

      // Create regex with optional flags
      const flags = rule.flags || '';
      const pattern = new RegExp(rule.pattern, flags);
      const matches = content.match(pattern);
      const found = matches !== null;

      const passed = rule.mustMatch ? found : !found;

      return {
        ruleName: rule.name,
        passed,
        message: passed
          ? rule.mustMatch
            ? `Pattern found in ${rule.target}`
            : `Pattern not found in ${rule.target} (as expected)`
          : rule.mustMatch
          ? `Pattern not found in ${rule.target}`
          : `Pattern found in ${rule.target} (unexpected)`,
        details: {
          pattern: rule.pattern,
          target: rule.target,
          mustMatch: rule.mustMatch,
          matchCount: matches ? matches.length : 0,
          matches: matches ? matches.slice(0, 5) : [], // First 5 matches
        },
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
      };
    } catch (error) {
      return {
        ruleName: rule.name,
        passed: false,
        message: `Pattern validation error: ${error instanceof Error ? error.message : String(error)}`,
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * Coverage validator - Parse coverage reports
   */
  async validateCoverage(
    rule: CoverageRule,
    context: ValidationContext
  ): Promise<IterationValidationResult> {
    const startTime = Date.now();

    try {
      const reportPath = resolve(context.workingDirectory, rule.reportPath);
      const reportContent = await readFile(reportPath, 'utf-8');

      let coverage: number;

      switch (rule.reportFormat) {
        case 'lcov':
          coverage = await this.parseLcovCoverage(reportContent, rule.scope);
          break;
        case 'json':
          coverage = await this.parseJsonCoverage(reportContent, rule.scope);
          break;
        case 'cobertura':
          coverage = await this.parseCoberturaCoverage(reportContent, rule.scope);
          break;
        default:
          throw new Error(`Unsupported coverage format: ${rule.reportFormat}`);
      }

      const passed = coverage >= rule.minCoverage;

      return {
        ruleName: rule.name,
        passed,
        message: passed
          ? `Coverage ${coverage.toFixed(2)}% meets minimum ${rule.minCoverage}%`
          : `Coverage ${coverage.toFixed(2)}% below minimum ${rule.minCoverage}%`,
        details: {
          coverage: coverage.toFixed(2),
          minCoverage: rule.minCoverage,
          reportPath: rule.reportPath,
          reportFormat: rule.reportFormat,
          scope: rule.scope || 'lines',
        },
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
      };
    } catch (error) {
      return {
        ruleName: rule.name,
        passed: false,
        message: `Coverage validation error: ${error instanceof Error ? error.message : String(error)}`,
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * File existence validator - Check if files exist
   */
  async validateFileExistence(
    rule: FileExistenceRule,
    context: ValidationContext
  ): Promise<IterationValidationResult> {
    const startTime = Date.now();

    try {
      const existenceChecks = await Promise.all(
        rule.paths.map(async (path) => {
          const fullPath = resolve(context.workingDirectory, path);
          try {
            await access(fullPath, constants.F_OK);
            return { path, exists: true };
          } catch {
            return { path, exists: false };
          }
        })
      );

      const existingFiles = existenceChecks.filter(c => c.exists);
      const missingFiles = existenceChecks.filter(c => !c.exists);

      const passed = rule.allMustExist
        ? missingFiles.length === 0
        : existingFiles.length > 0;

      return {
        ruleName: rule.name,
        passed,
        message: rule.allMustExist
          ? passed
            ? `All ${rule.paths.length} files exist`
            : `Missing ${missingFiles.length} of ${rule.paths.length} files`
          : passed
          ? `Found ${existingFiles.length} of ${rule.paths.length} files`
          : `None of the ${rule.paths.length} files exist`,
        details: {
          totalFiles: rule.paths.length,
          existingFiles: existingFiles.length,
          missingFiles: missingFiles.length,
          existing: existingFiles.map(f => f.path),
          missing: missingFiles.map(f => f.path),
          allMustExist: rule.allMustExist,
        },
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
      };
    } catch (error) {
      return {
        ruleName: rule.name,
        passed: false,
        message: `File existence validation error: ${error instanceof Error ? error.message : String(error)}`,
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * Custom validator - Use registered custom validator
   */
  async validateCustom(
    rule: CustomRule,
    context: ValidationContext
  ): Promise<IterationValidationResult> {
    const startTime = Date.now();

    const validator = this.customValidators.get(rule.validatorId);
    if (!validator) {
      return {
        ruleName: rule.name,
        passed: false,
        message: `Custom validator not found: ${rule.validatorId}`,
        duration: Date.now() - startTime,
        timestamp: new Date().toISOString(),
        error: 'Custom validator not registered',
      };
    }

    return await validator(rule, context);
  }

  // ============================================================================
  // COVERAGE PARSERS
  // ============================================================================

  /**
   * Parse LCOV format coverage report
   */
  private async parseLcovCoverage(content: string, scope?: string): Promise<number> {
    const lines = content.split('\n');
    let totalFound = 0;
    let totalHit = 0;

    const scopeKey = scope === 'branches' ? 'BRF' :
                     scope === 'functions' ? 'FNF' :
                     'LF'; // lines is default

    const hitKey = scope === 'branches' ? 'BRH' :
                   scope === 'functions' ? 'FNH' :
                   'LH';

    for (const line of lines) {
      if (line.startsWith(scopeKey + ':')) {
        totalFound += parseInt(line.substring(scopeKey.length + 1), 10);
      } else if (line.startsWith(hitKey + ':')) {
        totalHit += parseInt(line.substring(hitKey.length + 1), 10);
      }
    }

    return totalFound > 0 ? (totalHit / totalFound) * 100 : 0;
  }

  /**
   * Parse JSON format coverage report (e.g., Jest)
   */
  private async parseJsonCoverage(content: string, scope?: string): Promise<number> {
    const data = JSON.parse(content);

    // Handle common JSON coverage formats
    if (data.total) {
      const key = scope || 'lines';
      const metric = data.total[key];
      if (metric && typeof metric.pct === 'number') {
        return metric.pct;
      }
    }

    throw new Error('Unsupported JSON coverage format');
  }

  /**
   * Parse Cobertura XML format coverage report
   */
  private async parseCoberturaCoverage(content: string, scope?: string): Promise<number> {
    // Simple regex-based parsing for line-rate or branch-rate
    const scopeAttr = scope === 'branches' ? 'branch-rate' : 'line-rate';
    const regex = new RegExp(`${scopeAttr}="([\\d.]+)"`, 'i');
    const match = content.match(regex);

    if (match && match[1]) {
      return parseFloat(match[1]) * 100; // Convert from 0-1 to 0-100
    }

    throw new Error(`Could not parse ${scopeAttr} from Cobertura report`);
  }
}

// Singleton instance
let engineInstance: IterationValidationEngine | null = null;

export function getIterationEngine(): IterationValidationEngine {
  if (!engineInstance) {
    engineInstance = new IterationValidationEngine();
  }
  return engineInstance;
}

export function initIterationEngine(config?: Partial<IterationValidationConfig>): void {
  engineInstance = new IterationValidationEngine(config);
}
