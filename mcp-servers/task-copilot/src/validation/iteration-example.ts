/**
 * Example usage of Iteration Validation Engine
 *
 * This file demonstrates how to use the validation engine
 * to validate iteration completion criteria.
 */

import { getIterationEngine, type ValidationContext } from './iteration-engine.js';
import { DEFAULT_ITERATION_CONFIG } from './iteration-default-config.js';
import type { IterationValidationRule } from './iteration-types.js';

/**
 * Example 1: Validate QA agent iteration
 */
export async function exampleQAValidation() {
  const engine = getIterationEngine();
  const qaConfig = DEFAULT_ITERATION_CONFIG.agentRules['qa'];

  const context: ValidationContext = {
    taskId: 'TASK-QA-001',
    workingDirectory: process.cwd(),
    agentOutput: `
      Test execution complete.
      All 47 tests passing.
      Coverage: 87.3% lines, 82.1% branches

      <promise>COMPLETE</promise>
    `,
    taskNotes: 'Completed test suite for user authentication',
    latestWorkProduct: '# Test Plan\n\nValidated all edge cases...',
  };

  console.log('Running QA validation...');
  const report = await engine.validate(
    qaConfig.rules,
    context,
    'TASK-QA-001',
    1
  );

  console.log('\nValidation Report:');
  console.log(`Overall passed: ${report.overallPassed}`);
  console.log(`Total rules: ${report.totalRules}`);
  console.log(`Passed: ${report.passedRules}`);
  console.log(`Failed: ${report.failedRules}`);
  console.log(`Errors: ${report.erroredRules}`);
  console.log(`Duration: ${report.totalDuration}ms`);

  console.log('\nIndividual Results:');
  for (const result of report.results) {
    console.log(`\n  ${result.ruleName}:`);
    console.log(`    Passed: ${result.passed}`);
    console.log(`    Message: ${result.message}`);
    console.log(`    Duration: ${result.duration}ms`);
    if (result.error) {
      console.log(`    Error: ${result.error}`);
    }
  }

  return report;
}

/**
 * Example 2: Validate Engineer iteration with custom rules
 */
export async function exampleEngineerValidation() {
  const engine = getIterationEngine();

  // Custom rules for specific task
  const customRules: IterationValidationRule[] = [
    {
      type: 'command',
      name: 'build_succeeds',
      description: 'TypeScript builds without errors',
      command: 'npm run build',
      expectedExitCode: 0,
      timeout: 60000,
      enabled: true,
    },
    {
      type: 'file_existence',
      name: 'implementation_files',
      description: 'Implementation files created',
      paths: [
        'src/validation/iteration-engine.ts',
        'src/validation/iteration-types.ts',
      ],
      allMustExist: true,
      enabled: true,
    },
    {
      type: 'content_pattern',
      name: 'has_error_handling',
      description: 'Code includes error handling',
      pattern: 'try\\s*{[\\s\\S]*?}\\s*catch',
      target: 'work_product_latest',
      mustMatch: true,
      enabled: true,
    },
  ];

  const context: ValidationContext = {
    taskId: 'TASK-RW-006',
    workingDirectory: process.cwd(),
    agentOutput: 'Implementation complete.',
    taskNotes: 'Built validation engine with 5 validator types',
    latestWorkProduct: `
      try {
        const result = await executeCommand();
      } catch (error) {
        return handleError(error);
      }
    `,
  };

  console.log('Running Engineer validation...');
  const report = await engine.validate(
    customRules,
    context,
    'TASK-RW-006',
    1
  );

  console.log(`\nValidation ${report.overallPassed ? 'PASSED' : 'FAILED'}`);
  return report;
}

/**
 * Example 3: Register and use custom validator
 */
export async function exampleCustomValidator() {
  const engine = getIterationEngine();

  // Register custom validator for API contract validation
  engine.registerCustomValidator('api_contract', async (rule, context) => {
    const startTime = Date.now();

    // Simulate API contract validation
    const isValid = context.latestWorkProduct?.includes('openapi: 3.0') || false;

    return {
      ruleName: rule.name,
      passed: isValid,
      message: isValid
        ? 'API contract is valid OpenAPI 3.0'
        : 'API contract missing or invalid',
      details: {
        format: 'openapi',
        version: '3.0',
      },
      duration: Date.now() - startTime,
      timestamp: new Date().toISOString(),
    };
  });

  // Use custom validator
  const customRules: IterationValidationRule[] = [
    {
      type: 'custom',
      name: 'api_contract_valid',
      description: 'Validate OpenAPI contract',
      validatorId: 'api_contract',
      config: {
        schemaPath: 'api/openapi.yaml',
      },
      enabled: true,
    },
  ];

  const context: ValidationContext = {
    taskId: 'TASK-API-001',
    workingDirectory: process.cwd(),
    latestWorkProduct: 'openapi: 3.0.0\ninfo:\n  title: My API\n...',
  };

  const report = await engine.validate(customRules, context, 'TASK-API-001', 1);
  console.log('Custom validation result:', report.results[0]);
  return report;
}

/**
 * Example 4: Handle validation failures gracefully
 */
export async function exampleErrorHandling() {
  const engine = getIterationEngine();

  const rules: IterationValidationRule[] = [
    {
      type: 'command',
      name: 'nonexistent_command',
      description: 'This will fail',
      command: 'this-command-does-not-exist',
      expectedExitCode: 0,
      timeout: 5000,
      enabled: true,
    },
    {
      type: 'coverage',
      name: 'missing_coverage_report',
      description: 'This will error',
      reportPath: 'nonexistent/coverage.info',
      reportFormat: 'lcov',
      minCoverage: 80,
      enabled: true,
    },
  ];

  const context: ValidationContext = {
    taskId: 'TASK-ERROR-001',
    workingDirectory: process.cwd(),
  };

  console.log('Testing error handling...');
  const report = await engine.validate(rules, context, 'TASK-ERROR-001', 1);

  console.log(`\nErrored rules: ${report.erroredRules}`);
  for (const result of report.results) {
    if (result.error) {
      console.log(`\n  ${result.ruleName}:`);
      console.log(`    Error: ${result.error}`);
      console.log(`    Message: ${result.message}`);
    }
  }

  return report;
}

/**
 * Run all examples
 */
export async function runAllExamples() {
  console.log('='.repeat(80));
  console.log('Iteration Validation Engine Examples');
  console.log('='.repeat(80));

  try {
    console.log('\n\n1. QA Agent Validation Example');
    console.log('-'.repeat(80));
    await exampleQAValidation();

    console.log('\n\n2. Engineer Validation Example');
    console.log('-'.repeat(80));
    await exampleEngineerValidation();

    console.log('\n\n3. Custom Validator Example');
    console.log('-'.repeat(80));
    await exampleCustomValidator();

    console.log('\n\n4. Error Handling Example');
    console.log('-'.repeat(80));
    await exampleErrorHandling();

    console.log('\n\n' + '='.repeat(80));
    console.log('Examples complete!');
    console.log('='.repeat(80));
  } catch (error) {
    console.error('Example failed:', error);
    throw error;
  }
}

// Uncomment to run examples:
// runAllExamples().catch(console.error);
