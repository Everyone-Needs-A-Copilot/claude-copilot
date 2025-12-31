/**
 * Ralph Wiggum Iteration Validation Types
 *
 * Defines validation rules for iteration completion criteria
 */

// Base validation rule
export interface BaseIterationRule {
  type: string;
  name: string;
  description?: string;
  enabled: boolean;
}

// Command validator - Execute shell command and check exit code
export interface CommandRule extends BaseIterationRule {
  type: 'command';
  command: string;
  expectedExitCode: number;
  timeout: number; // milliseconds
  workingDirectory?: string;
  env?: Record<string, string>;
}

// Content pattern validator - Regex matching in output
export interface ContentPatternRule extends BaseIterationRule {
  type: 'content_pattern';
  pattern: string; // Regex pattern as string
  target: 'agent_output' | 'task_notes' | 'work_product_latest';
  flags?: string; // Regex flags (e.g., 'i' for case-insensitive)
  mustMatch: boolean; // true = must match, false = must not match
}

// Coverage validator - Parse coverage reports
export interface CoverageRule extends BaseIterationRule {
  type: 'coverage';
  reportPath: string;
  reportFormat: 'lcov' | 'json' | 'cobertura';
  minCoverage: number; // Percentage (0-100)
  scope?: 'lines' | 'branches' | 'functions' | 'statements';
}

// File existence validator - Check if files exist
export interface FileExistenceRule extends BaseIterationRule {
  type: 'file_existence';
  paths: string[];
  allMustExist: boolean; // true = all must exist, false = at least one must exist
}

// Custom function validator - For future extensibility
export interface CustomRule extends BaseIterationRule {
  type: 'custom';
  validatorId: string; // ID of registered custom validator
  config: Record<string, unknown>;
}

export type IterationValidationRule =
  | CommandRule
  | ContentPatternRule
  | CoverageRule
  | FileExistenceRule
  | CustomRule;

// Validation result for a single rule
export interface IterationValidationResult {
  ruleName: string;
  passed: boolean;
  message: string;
  details?: Record<string, unknown>;
  duration: number; // milliseconds
  timestamp: string;
  error?: string; // Error message if validation failed to execute
}

// Overall validation result for an iteration
export interface IterationValidationReport {
  taskId: string;
  iterationNumber: number;
  results: IterationValidationResult[];
  overallPassed: boolean;
  totalRules: number;
  passedRules: number;
  failedRules: number;
  erroredRules: number;
  totalDuration: number; // milliseconds
  validatedAt: string;
}

// Configuration for agent-specific rules
export interface AgentValidationConfig {
  agentId: string;
  rules: IterationValidationRule[];
  requireAllPass: boolean; // true = all must pass, false = at least one must pass
}

// Overall validation configuration
export interface IterationValidationConfig {
  version: string;
  globalRules: IterationValidationRule[];
  agentRules: Record<string, AgentValidationConfig>;
  defaultTimeout: number; // Default timeout for command validators (ms)
  maxConcurrentValidations: number; // Max parallel validations
}
