/**
 * Default validation configuration for Ralph Wiggum iterations
 */

import type { IterationValidationConfig } from './iteration-types.js';

export const DEFAULT_ITERATION_CONFIG: IterationValidationConfig = {
  version: '1.0',
  defaultTimeout: 60000, // 60 seconds
  maxConcurrentValidations: 5,

  // Global rules apply to all iterations
  globalRules: [],

  // Agent-specific rules
  agentRules: {
    // QA Engineer - Test validation
    qa: {
      agentId: 'qa',
      requireAllPass: true,
      rules: [
        {
          type: 'command',
          name: 'tests_pass',
          description: 'All tests must pass',
          command: 'npm test',
          expectedExitCode: 0,
          timeout: 120000, // 2 minutes
          enabled: true,
        },
        {
          type: 'coverage',
          name: 'coverage_threshold',
          description: 'Minimum 80% line coverage',
          reportPath: 'coverage/lcov.info',
          reportFormat: 'lcov',
          minCoverage: 80,
          scope: 'lines',
          enabled: true,
        },
        {
          type: 'content_pattern',
          name: 'promise_complete',
          description: 'Check for completion promise in output',
          pattern: '<promise>COMPLETE</promise>',
          target: 'agent_output',
          mustMatch: true,
          enabled: false, // Disabled by default, enable per task
        },
      ],
    },

    // Engineer - Implementation validation
    me: {
      agentId: 'me',
      requireAllPass: true,
      rules: [
        {
          type: 'command',
          name: 'build_succeeds',
          description: 'Project builds successfully',
          command: 'npm run build',
          expectedExitCode: 0,
          timeout: 180000, // 3 minutes
          enabled: true,
        },
        {
          type: 'command',
          name: 'lint_passes',
          description: 'Code passes linting',
          command: 'npm run lint',
          expectedExitCode: 0,
          timeout: 60000,
          enabled: true,
        },
        {
          type: 'file_existence',
          name: 'implementation_files_exist',
          description: 'Implementation files are created',
          paths: [], // Populated per task
          allMustExist: true,
          enabled: false, // Enable per task with specific paths
        },
      ],
    },

    // Security Engineer - Security validation
    sec: {
      agentId: 'sec',
      requireAllPass: true,
      rules: [
        {
          type: 'command',
          name: 'security_scan',
          description: 'Security scan passes',
          command: 'npm audit --audit-level=moderate',
          expectedExitCode: 0,
          timeout: 90000,
          enabled: true,
        },
        {
          type: 'content_pattern',
          name: 'no_hardcoded_secrets',
          description: 'No hardcoded secrets detected',
          pattern: '(password|secret|api[_-]?key)\\s*=\\s*["\'][^"\']+["\']',
          target: 'work_product_latest',
          flags: 'i',
          mustMatch: false, // Must NOT match
          enabled: true,
        },
      ],
    },

    // DevOps Engineer - Infrastructure validation
    do: {
      agentId: 'do',
      requireAllPass: true,
      rules: [
        {
          type: 'command',
          name: 'docker_build',
          description: 'Docker image builds successfully',
          command: 'docker build -t test-image .',
          expectedExitCode: 0,
          timeout: 300000, // 5 minutes
          enabled: false, // Enable per task
        },
        {
          type: 'file_existence',
          name: 'config_files_exist',
          description: 'Required configuration files exist',
          paths: ['.github/workflows/ci.yml', 'Dockerfile'],
          allMustExist: false, // At least one must exist
          enabled: true,
        },
      ],
    },

    // Documentation Writer - Documentation validation
    doc: {
      agentId: 'doc',
      requireAllPass: true,
      rules: [
        {
          type: 'content_pattern',
          name: 'has_code_examples',
          description: 'Documentation includes code examples',
          pattern: '```[\\s\\S]*?```',
          target: 'work_product_latest',
          mustMatch: true,
          enabled: true,
        },
        {
          type: 'content_pattern',
          name: 'has_headings',
          description: 'Documentation has proper structure',
          pattern: '^#{1,3}\\s+.+$',
          target: 'work_product_latest',
          flags: 'm',
          mustMatch: true,
          enabled: true,
        },
        {
          type: 'file_existence',
          name: 'readme_exists',
          description: 'README file exists',
          paths: ['README.md'],
          allMustExist: true,
          enabled: false, // Enable per task
        },
      ],
    },

    // Tech Architect - Architecture validation
    ta: {
      agentId: 'ta',
      requireAllPass: false, // At least one should pass
      rules: [
        {
          type: 'content_pattern',
          name: 'has_architecture_diagram',
          description: 'Architecture includes diagrams',
          pattern: '```mermaid[\\s\\S]*?```',
          target: 'work_product_latest',
          mustMatch: true,
          enabled: true,
        },
        {
          type: 'content_pattern',
          name: 'has_decision_records',
          description: 'Architecture documents decisions',
          pattern: '(decision|rationale|trade-off)',
          target: 'work_product_latest',
          flags: 'i',
          mustMatch: true,
          enabled: true,
        },
      ],
    },

    // UI Developer - UI implementation validation
    uid: {
      agentId: 'uid',
      requireAllPass: true,
      rules: [
        {
          type: 'command',
          name: 'ui_tests_pass',
          description: 'UI tests pass',
          command: 'npm run test:ui',
          expectedExitCode: 0,
          timeout: 120000,
          enabled: true,
        },
        {
          type: 'file_existence',
          name: 'component_files',
          description: 'Component files created',
          paths: [], // Populated per task
          allMustExist: true,
          enabled: false,
        },
      ],
    },
  },
};
