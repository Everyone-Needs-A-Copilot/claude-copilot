/**
 * Iteration Configuration Validator
 *
 * Validates IterationConfig objects against the JSON schema.
 * Provides detailed error messages and type-safe validation.
 */

import AjvModule, { type ValidateFunction, type ErrorObject } from 'ajv';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import type { IterationConfig } from '../types.js';
import type { IterationValidationRule } from './iteration-types.js';

const Ajv = AjvModule.default || AjvModule;

// ============================================================================
// TYPES
// ============================================================================

export interface ValidationRuleInput {
  type: string;
  name: string;
  config: Record<string, unknown>;
}

export interface IterationConfigInput {
  maxIterations: number;
  completionPromises: string[];
  validationRules?: ValidationRuleInput[];
  circuitBreakerThreshold?: number;
}

export interface ValidationError {
  field: string;
  message: string;
  value?: unknown;
  constraint?: string;
}

export interface ValidationOutput {
  valid: boolean;
  errors: ValidationError[];
  config?: IterationConfig;
}

// ============================================================================
// VALIDATOR CLASS
// ============================================================================

export class IterationConfigValidator {
  private validate: ValidateFunction;
  private ajv: InstanceType<typeof Ajv>;

  constructor() {
    this.ajv = new Ajv({
      allErrors: true,
      verbose: true,
      strict: true,
      strictSchema: true,
      strictNumbers: true,
      strictTypes: true,
      strictTuples: true,
    });

    // Load schema - check both package root and project root paths
    const packageSchemaPath = join(process.cwd(), 'schemas', 'iteration-config.schema.json');
    const projectSchemaPath = join(process.cwd(), 'mcp-servers', 'task-copilot', 'schemas', 'iteration-config.schema.json');
    const schemaPath = existsSync(packageSchemaPath) ? packageSchemaPath : projectSchemaPath;

    let schema: object;
    try {
      const schemaContent = readFileSync(schemaPath, 'utf-8');
      schema = JSON.parse(schemaContent);
    } catch (error) {
      throw new Error(
        `Failed to load iteration config schema: ${error instanceof Error ? error.message : String(error)}`
      );
    }

    // Compile schema
    this.validate = this.ajv.compile(schema);
  }

  /**
   * Validate iteration configuration
   */
  validateConfig(input: IterationConfigInput): ValidationOutput {
    const valid = this.validate(input);

    if (valid) {
      return {
        valid: true,
        errors: [],
        config: input as IterationConfig,
      };
    }

    const errors = this.formatErrors(this.validate.errors || []);

    return {
      valid: false,
      errors,
    };
  }

  /**
   * Validate and throw on error (convenience method)
   */
  validateConfigOrThrow(input: IterationConfigInput): IterationConfig {
    const result = this.validateConfig(input);

    if (!result.valid) {
      const errorMessages = result.errors.map(
        (e) => `${e.field}: ${e.message}`
      );
      throw new Error(
        `Invalid iteration configuration:\n${errorMessages.join('\n')}`
      );
    }

    return result.config!;
  }

  /**
   * Format AJV errors into user-friendly messages
   */
  private formatErrors(ajvErrors: ErrorObject[]): ValidationError[] {
    return ajvErrors.map((error) => {
      const field = error.instancePath || error.schemaPath;
      let message = error.message || 'Unknown validation error';
      const value = error.data;
      const constraint = error.keyword;

      // Enhance error messages for common cases
      switch (error.keyword) {
        case 'minimum':
          message = `Must be at least ${error.params.limit}`;
          break;
        case 'maximum':
          message = `Must be at most ${error.params.limit}`;
          break;
        case 'minItems':
          message = `Must have at least ${error.params.limit} item(s)`;
          break;
        case 'maxItems':
          message = `Must have at most ${error.params.limit} item(s)`;
          break;
        case 'required':
          message = `Missing required property: ${error.params.missingProperty}`;
          break;
        case 'enum':
          message = `Must be one of: ${error.params.allowedValues.join(', ')}`;
          break;
        case 'pattern':
          message = `Must match pattern: ${error.params.pattern}`;
          break;
        case 'type':
          message = `Must be of type: ${error.params.type}`;
          break;
        case 'const':
          message = `Must be exactly: ${error.params.allowedValue}`;
          break;
        case 'uniqueItems':
          message = 'Items must be unique (no duplicates)';
          break;
        case 'oneOf':
          message = 'Must match exactly one of the allowed schemas';
          break;
      }

      return {
        field: field.replace(/^\//, '').replace(/\//g, '.') || 'root',
        message,
        value,
        constraint,
      };
    });
  }
}

// ============================================================================
// SINGLETON INSTANCE
// ============================================================================

let validatorInstance: IterationConfigValidator | null = null;

/**
 * Get singleton validator instance
 */
export function getIterationConfigValidator(): IterationConfigValidator {
  if (!validatorInstance) {
    validatorInstance = new IterationConfigValidator();
  }
  return validatorInstance;
}

// ============================================================================
// CONVENIENCE FUNCTIONS
// ============================================================================

/**
 * Validate iteration configuration (convenience function)
 */
export function validateIterationConfig(
  input: IterationConfigInput
): ValidationOutput {
  const validator = getIterationConfigValidator();
  return validator.validateConfig(input);
}

/**
 * Validate iteration configuration and throw on error (convenience function)
 */
export function validateIterationConfigOrThrow(
  input: IterationConfigInput
): IterationConfig {
  const validator = getIterationConfigValidator();
  return validator.validateConfigOrThrow(input);
}

// ============================================================================
// SPECIFIC VALIDATION RULES
// ============================================================================

/**
 * Validate completion promises format
 */
export function validateCompletionPromises(promises: string[]): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!promises || promises.length === 0) {
    errors.push({
      field: 'completionPromises',
      message: 'Must have at least one completion promise',
    });
    return errors;
  }

  const promisePattern = /^<promise>[A-Z]+<\/promise>$/;

  promises.forEach((promise, index) => {
    if (!promisePattern.test(promise)) {
      errors.push({
        field: `completionPromises[${index}]`,
        message: 'Must be in format: <promise>WORD</promise> (uppercase)',
        value: promise,
      });
    }
  });

  // Check for duplicates
  const uniquePromises = new Set(promises);
  if (uniquePromises.size !== promises.length) {
    errors.push({
      field: 'completionPromises',
      message: 'Contains duplicate promises',
    });
  }

  return errors;
}

/**
 * Validate command rule configuration
 */
export function validateCommandRule(config: Record<string, unknown>): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!config.command || typeof config.command !== 'string') {
    errors.push({
      field: 'config.command',
      message: 'Command is required and must be a string',
    });
  }

  if (config.timeout !== undefined) {
    const timeout = config.timeout as number;
    if (timeout < 1000 || timeout > 600000) {
      errors.push({
        field: 'config.timeout',
        message: 'Timeout must be between 1000ms and 600000ms',
        value: timeout,
      });
    }
  }

  return errors;
}

/**
 * Validate content pattern rule configuration
 */
export function validateContentPatternRule(
  config: Record<string, unknown>
): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!config.pattern || typeof config.pattern !== 'string') {
    errors.push({
      field: 'config.pattern',
      message: 'Pattern is required and must be a string',
    });
  }

  if (!config.target) {
    errors.push({
      field: 'config.target',
      message: 'Target is required',
    });
  } else {
    const validTargets = ['agent_output', 'task_notes', 'work_product_latest'];
    if (!validTargets.includes(config.target as string)) {
      errors.push({
        field: 'config.target',
        message: `Target must be one of: ${validTargets.join(', ')}`,
        value: config.target,
      });
    }
  }

  // Validate regex pattern
  if (config.pattern && typeof config.pattern === 'string') {
    try {
      new RegExp(config.pattern, config.flags as string | undefined);
    } catch (error) {
      errors.push({
        field: 'config.pattern',
        message: `Invalid regular expression: ${error instanceof Error ? error.message : String(error)}`,
        value: config.pattern,
      });
    }
  }

  return errors;
}

/**
 * Validate coverage rule configuration
 */
export function validateCoverageRule(config: Record<string, unknown>): ValidationError[] {
  const errors: ValidationError[] = [];

  if (config.minCoverage === undefined || typeof config.minCoverage !== 'number') {
    errors.push({
      field: 'config.minCoverage',
      message: 'minCoverage is required and must be a number',
    });
  } else if (config.minCoverage < 0 || config.minCoverage > 100) {
    errors.push({
      field: 'config.minCoverage',
      message: 'minCoverage must be between 0 and 100',
      value: config.minCoverage,
    });
  }

  if (!config.format) {
    errors.push({
      field: 'config.format',
      message: 'format is required',
    });
  } else {
    const validFormats = ['lcov', 'json', 'cobertura'];
    if (!validFormats.includes(config.format as string)) {
      errors.push({
        field: 'config.format',
        message: `format must be one of: ${validFormats.join(', ')}`,
        value: config.format,
      });
    }
  }

  return errors;
}

/**
 * Validate file existence rule configuration
 */
export function validateFileExistenceRule(
  config: Record<string, unknown>
): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!config.paths || !Array.isArray(config.paths)) {
    errors.push({
      field: 'config.paths',
      message: 'paths is required and must be an array',
    });
  } else if (config.paths.length === 0) {
    errors.push({
      field: 'config.paths',
      message: 'paths must contain at least one file path',
    });
  }

  return errors;
}

/**
 * Validate custom rule configuration
 */
export function validateCustomRule(config: Record<string, unknown>): ValidationError[] {
  const errors: ValidationError[] = [];

  if (!config.validatorId || typeof config.validatorId !== 'string') {
    errors.push({
      field: 'config.validatorId',
      message: 'validatorId is required and must be a string',
    });
  } else if (!/^[a-zA-Z0-9_-]+$/.test(config.validatorId as string)) {
    errors.push({
      field: 'config.validatorId',
      message: 'validatorId must contain only alphanumeric characters, hyphens, and underscores',
      value: config.validatorId,
    });
  }

  return errors;
}
