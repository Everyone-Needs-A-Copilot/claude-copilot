/**
 * Iteration Configuration Examples
 *
 * Demonstrates how to create and validate iteration configurations
 * for different agent scenarios.
 */

import type { IterationConfigInput } from './iteration-config-validator.js';

// ============================================================================
// ENGINEER (@agent-me) EXAMPLES
// ============================================================================

/**
 * Example 1: Basic TDD Iteration Loop
 *
 * Simple configuration for test-driven development with build and lint checks.
 */
export const engineerTDDBasic: IterationConfigInput = {
  maxIterations: 15,
  completionPromises: [
    '<promise>COMPLETE</promise>',
    '<promise>BLOCKED</promise>',
  ],
  validationRules: [
    {
      type: 'command',
      name: 'tests_pass',
      config: {
        command: 'npm test',
        expectedExitCode: 0,
        timeout: 120000, // 2 minutes
      },
    },
    {
      type: 'command',
      name: 'build_succeeds',
      config: {
        command: 'npm run build',
        timeout: 180000, // 3 minutes
      },
    },
    {
      type: 'command',
      name: 'lint_clean',
      config: {
        command: 'npm run lint',
        timeout: 60000,
      },
    },
  ],
  circuitBreakerThreshold: 3,
};

/**
 * Example 2: TypeScript Project with Type Checking
 *
 * Includes TypeScript compilation check alongside tests.
 */
export const engineerTypeScript: IterationConfigInput = {
  maxIterations: 12,
  completionPromises: ['<promise>COMPLETE</promise>'],
  validationRules: [
    {
      type: 'command',
      name: 'type_check',
      config: {
        command: 'tsc --noEmit',
        timeout: 90000,
      },
    },
    {
      type: 'command',
      name: 'tests_pass',
      config: {
        command: 'npm test',
        timeout: 120000,
      },
    },
    {
      type: 'file_existence',
      name: 'implementation_files',
      config: {
        paths: ['src/feature.ts', 'src/feature.test.ts'],
        allMustExist: true,
      },
    },
  ],
  circuitBreakerThreshold: 4,
};

// ============================================================================
// QA ENGINEER (@agent-qa) EXAMPLES
// ============================================================================

/**
 * Example 3: Coverage-Driven Test Improvement
 *
 * Iterate until test coverage threshold is met.
 */
export const qaEngineerCoverage: IterationConfigInput = {
  maxIterations: 10,
  completionPromises: ['<promise>COMPLETE</promise>'],
  validationRules: [
    {
      type: 'command',
      name: 'tests_pass',
      config: {
        command: 'npm test',
        timeout: 120000,
      },
    },
    {
      type: 'coverage',
      name: 'coverage_threshold',
      config: {
        minCoverage: 80,
        format: 'lcov',
        reportPath: 'coverage/lcov.info',
        scope: 'lines',
      },
    },
    {
      type: 'command',
      name: 'no_flaky_tests',
      config: {
        command: 'npm test -- --repeat=3',
        timeout: 300000, // 5 minutes for repeated runs
      },
    },
  ],
  circuitBreakerThreshold: 5,
};

/**
 * Example 4: Branch Coverage Focus
 *
 * Ensures branch coverage meets threshold.
 */
export const qaEngineerBranchCoverage: IterationConfigInput = {
  maxIterations: 8,
  completionPromises: ['<promise>COMPLETE</promise>', '<promise>BLOCKED</promise>'],
  validationRules: [
    {
      type: 'coverage',
      name: 'branch_coverage',
      config: {
        minCoverage: 75,
        format: 'json',
        reportPath: 'coverage/coverage-final.json',
        scope: 'branches',
      },
    },
    {
      type: 'command',
      name: 'tests_pass',
      config: {
        command: 'npm test',
        timeout: 120000,
      },
    },
  ],
  circuitBreakerThreshold: 3,
};

// ============================================================================
// SECURITY ENGINEER (@agent-sec) EXAMPLES
// ============================================================================

/**
 * Example 5: Security Vulnerability Remediation
 *
 * Iterate until security scans pass.
 */
export const securityEngineer: IterationConfigInput = {
  maxIterations: 10,
  completionPromises: ['<promise>COMPLETE</promise>', '<promise>BLOCKED</promise>'],
  validationRules: [
    {
      type: 'command',
      name: 'security_audit',
      config: {
        command: 'npm audit --audit-level=moderate',
        successExitCodes: [0], // Must have no vulnerabilities
        timeout: 90000,
      },
    },
    {
      type: 'content_pattern',
      name: 'no_hardcoded_secrets',
      config: {
        pattern: '(password|secret|api[_-]?key)\\s*=\\s*["\'][^"\']+["\']',
        target: 'work_product_latest',
        flags: 'i',
        mustMatch: false, // Must NOT match (no secrets)
      },
    },
    {
      type: 'command',
      name: 'sast_scan',
      config: {
        command: 'npm run security:scan',
        timeout: 180000,
      },
    },
  ],
  circuitBreakerThreshold: 3,
};

// ============================================================================
// DOCUMENTATION WRITER (@agent-doc) EXAMPLES
// ============================================================================

/**
 * Example 6: Documentation Quality Iteration
 *
 * Ensure documentation has proper structure and examples.
 */
export const documentationWriter: IterationConfigInput = {
  maxIterations: 6,
  completionPromises: ['<promise>COMPLETE</promise>'],
  validationRules: [
    {
      type: 'content_pattern',
      name: 'has_code_examples',
      config: {
        pattern: '```[\\s\\S]*?```',
        target: 'work_product_latest',
        mustMatch: true,
      },
    },
    {
      type: 'content_pattern',
      name: 'has_proper_headings',
      config: {
        pattern: '^#{1,3}\\s+.+$',
        target: 'work_product_latest',
        flags: 'm',
        mustMatch: true,
      },
    },
    {
      type: 'content_pattern',
      name: 'has_table_of_contents',
      config: {
        pattern: '## Table of Contents|##\\s*Contents',
        target: 'work_product_latest',
        flags: 'i',
        mustMatch: true,
      },
    },
  ],
  circuitBreakerThreshold: 2,
};

// ============================================================================
// DEVOPS ENGINEER (@agent-do) EXAMPLES
// ============================================================================

/**
 * Example 7: Infrastructure Validation
 *
 * Ensure infrastructure code builds and passes validation.
 */
export const devopsEngineer: IterationConfigInput = {
  maxIterations: 8,
  completionPromises: ['<promise>COMPLETE</promise>', '<promise>BLOCKED</promise>'],
  validationRules: [
    {
      type: 'command',
      name: 'docker_build',
      config: {
        command: 'docker build -t test-image .',
        timeout: 300000, // 5 minutes
        env: {
          DOCKER_BUILDKIT: '1',
        },
      },
    },
    {
      type: 'file_existence',
      name: 'required_configs',
      config: {
        paths: [
          '.github/workflows/ci.yml',
          'Dockerfile',
          'docker-compose.yml',
        ],
        allMustExist: false, // At least one must exist
      },
    },
    {
      type: 'command',
      name: 'terraform_validate',
      config: {
        command: 'terraform validate',
        timeout: 60000,
        workingDirectory: './infrastructure',
      },
    },
  ],
  circuitBreakerThreshold: 3,
};

// ============================================================================
// UI DEVELOPER (@agent-uid) EXAMPLES
// ============================================================================

/**
 * Example 8: UI Component Development
 *
 * Validate UI tests and component existence.
 */
export const uiDeveloper: IterationConfigInput = {
  maxIterations: 10,
  completionPromises: ['<promise>COMPLETE</promise>'],
  validationRules: [
    {
      type: 'command',
      name: 'ui_tests_pass',
      config: {
        command: 'npm run test:ui',
        timeout: 120000,
      },
    },
    {
      type: 'command',
      name: 'storybook_build',
      config: {
        command: 'npm run build-storybook',
        timeout: 180000,
      },
    },
    {
      type: 'file_existence',
      name: 'component_files',
      config: {
        paths: [
          'src/components/MyComponent.tsx',
          'src/components/MyComponent.test.tsx',
          'src/components/MyComponent.stories.tsx',
        ],
        allMustExist: true,
      },
    },
  ],
  circuitBreakerThreshold: 4,
};

// ============================================================================
// CUSTOM VALIDATOR EXAMPLE
// ============================================================================

/**
 * Example 9: Custom Validator Integration
 *
 * Demonstrates using a custom validator alongside standard rules.
 */
export const customValidatorExample: IterationConfigInput = {
  maxIterations: 10,
  completionPromises: ['<promise>COMPLETE</promise>'],
  validationRules: [
    {
      type: 'command',
      name: 'tests_pass',
      config: {
        command: 'npm test',
        timeout: 120000,
      },
    },
    {
      type: 'custom',
      name: 'performance_benchmark',
      config: {
        validatorId: 'performance-validator',
        maxResponseTime: 100,
        minThroughput: 1000,
      },
    },
    {
      type: 'custom',
      name: 'accessibility_check',
      config: {
        validatorId: 'a11y-validator',
        wcagLevel: 'AA',
        checkContrast: true,
      },
    },
  ],
  circuitBreakerThreshold: 3,
};

// ============================================================================
// MINIMAL CONFIGURATION
// ============================================================================

/**
 * Example 10: Minimal Configuration
 *
 * The absolute minimum required for iteration.
 */
export const minimalConfig: IterationConfigInput = {
  maxIterations: 5,
  completionPromises: ['<promise>COMPLETE</promise>'],
};

// ============================================================================
// COMPLEX MULTI-STAGE VALIDATION
// ============================================================================

/**
 * Example 11: Multi-Stage Validation Pipeline
 *
 * Comprehensive validation with multiple rule types.
 */
export const complexPipeline: IterationConfigInput = {
  maxIterations: 20,
  completionPromises: [
    '<promise>COMPLETE</promise>',
    '<promise>BLOCKED</promise>',
    '<promise>ESCALATE</promise>',
  ],
  validationRules: [
    // Stage 1: Build and type checking
    {
      type: 'command',
      name: 'type_check',
      config: {
        command: 'tsc --noEmit',
        timeout: 90000,
      },
    },
    {
      type: 'command',
      name: 'build',
      config: {
        command: 'npm run build',
        timeout: 180000,
      },
    },
    // Stage 2: Testing and coverage
    {
      type: 'command',
      name: 'unit_tests',
      config: {
        command: 'npm run test:unit',
        timeout: 120000,
      },
    },
    {
      type: 'command',
      name: 'integration_tests',
      config: {
        command: 'npm run test:integration',
        timeout: 300000,
      },
    },
    {
      type: 'coverage',
      name: 'coverage_check',
      config: {
        minCoverage: 85,
        format: 'lcov',
        reportPath: 'coverage/lcov.info',
        scope: 'lines',
      },
    },
    // Stage 3: Code quality
    {
      type: 'command',
      name: 'lint',
      config: {
        command: 'npm run lint',
        timeout: 60000,
      },
    },
    {
      type: 'command',
      name: 'format_check',
      config: {
        command: 'npm run format:check',
        timeout: 30000,
      },
    },
    // Stage 4: Security and validation
    {
      type: 'command',
      name: 'security_audit',
      config: {
        command: 'npm audit --audit-level=high',
        timeout: 90000,
      },
    },
    {
      type: 'content_pattern',
      name: 'no_todos',
      config: {
        pattern: '//\\s*TODO|//\\s*FIXME',
        target: 'work_product_latest',
        mustMatch: false,
      },
    },
    // Stage 5: File validation
    {
      type: 'file_existence',
      name: 'required_files',
      config: {
        paths: [
          'README.md',
          'package.json',
          'tsconfig.json',
          '.gitignore',
        ],
        allMustExist: true,
      },
    },
  ],
  circuitBreakerThreshold: 5,
};

// ============================================================================
// EXPORTS
// ============================================================================

export const examples = {
  engineerTDDBasic,
  engineerTypeScript,
  qaEngineerCoverage,
  qaEngineerBranchCoverage,
  securityEngineer,
  documentationWriter,
  devopsEngineer,
  uiDeveloper,
  customValidatorExample,
  minimalConfig,
  complexPipeline,
};

export default examples;
