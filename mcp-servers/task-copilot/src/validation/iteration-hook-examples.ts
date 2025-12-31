/**
 * Ralph Wiggum Iteration Hook Configuration Examples
 *
 * Practical examples of hook configurations for common scenarios
 */

import type {
  StopHook,
  PreIterationHook,
  PostIterationHook,
  CircuitBreakerHook,
  IterationHookConfig
} from './iteration-hook-types.js';
import type { IterationConfig } from '../types.js';

// ============================================================================
// STOP HOOK EXAMPLES
// ============================================================================

/**
 * Example: Stop when all tests pass
 */
export const stopOnTestsPass: StopHook = {
  type: 'stop',
  name: 'tests_pass',
  description: 'Stop iteration when all tests pass',
  enabled: true,
  validationRules: [
    {
      type: 'command',
      name: 'run_tests',
      description: 'Execute test suite',
      enabled: true,
      command: 'npm test',
      expectedExitCode: 0,
      timeout: 30000
    }
  ],
  action: 'complete',
  priority: 1,
  message: 'All tests passing - ready to complete'
};

/**
 * Example: Stop when code compiles and lints
 */
export const stopOnCleanBuild: StopHook = {
  type: 'stop',
  name: 'clean_build',
  description: 'Stop when code compiles without errors and passes linting',
  enabled: true,
  validationRules: [
    {
      type: 'command',
      name: 'compile',
      description: 'TypeScript compilation check',
      enabled: true,
      command: 'tsc --noEmit',
      expectedExitCode: 0,
      timeout: 20000
    },
    {
      type: 'command',
      name: 'lint',
      description: 'ESLint check',
      enabled: true,
      command: 'eslint .',
      expectedExitCode: 0,
      timeout: 15000
    }
  ],
  action: 'complete',
  priority: 2
};

/**
 * Example: Stop when coverage threshold met
 */
export const stopOnCoverageThreshold: StopHook = {
  type: 'stop',
  name: 'coverage_threshold',
  description: 'Stop when test coverage exceeds 80%',
  enabled: true,
  validationRules: [
    {
      type: 'coverage',
      name: 'line_coverage',
      description: 'Check line coverage threshold',
      enabled: true,
      reportPath: './coverage/coverage-final.json',
      reportFormat: 'json',
      minCoverage: 80,
      scope: 'lines'
    }
  ],
  action: 'complete',
  priority: 3,
  message: 'Coverage threshold met - iteration complete'
};

/**
 * Example: Stop when all quality gates pass
 */
export const stopOnAllQualityGates: StopHook = {
  type: 'stop',
  name: 'all_quality_gates',
  description: 'Stop when all quality gates pass',
  enabled: true,
  validationRules: [
    {
      type: 'command',
      name: 'tests',
      enabled: true,
      command: 'npm test',
      expectedExitCode: 0,
      timeout: 30000
    },
    {
      type: 'command',
      name: 'compile',
      enabled: true,
      command: 'tsc --noEmit',
      expectedExitCode: 0,
      timeout: 20000
    },
    {
      type: 'command',
      name: 'lint',
      enabled: true,
      command: 'eslint .',
      expectedExitCode: 0,
      timeout: 15000
    },
    {
      type: 'coverage',
      name: 'coverage',
      enabled: true,
      reportPath: './coverage/coverage-final.json',
      reportFormat: 'json',
      minCoverage: 80
    }
  ],
  action: 'complete',
  priority: 1,
  message: 'All quality gates passed'
};

// ============================================================================
// PRE-ITERATION HOOK EXAMPLES
// ============================================================================

/**
 * Example: Clean build artifacts before iteration
 */
export const preCleanBuild: PreIterationHook = {
  type: 'pre_iteration',
  name: 'clean_build',
  description: 'Clean build artifacts and cache',
  enabled: true,
  trigger: 'always',
  actions: [
    {
      type: 'command',
      command: 'npm run clean',
      timeout: 10000
    },
    {
      type: 'notification',
      channel: 'log',
      message: 'Build artifacts cleaned',
      severity: 'info'
    }
  ],
  failOnError: false,
  timeout: 15000
};

/**
 * Example: Create checkpoint before iteration
 */
export const preCreateCheckpoint: PreIterationHook = {
  type: 'pre_iteration',
  name: 'create_checkpoint',
  description: 'Create recovery checkpoint before iteration',
  enabled: true,
  trigger: 'always',
  actions: [
    {
      type: 'checkpoint',
      operation: 'create'
    }
  ],
  failOnError: false
};

/**
 * Example: Reset test database
 */
export const preResetDatabase: PreIterationHook = {
  type: 'pre_iteration',
  name: 'reset_database',
  description: 'Reset test database to clean state',
  enabled: true,
  trigger: 'always',
  actions: [
    {
      type: 'command',
      command: 'npm run db:reset:test',
      timeout: 30000
    }
  ],
  failOnError: true,
  timeout: 35000
};

/**
 * Example: Conditional checkpoint (every 5th iteration)
 */
export const preMilestoneCheckpoint: PreIterationHook = {
  type: 'pre_iteration',
  name: 'milestone_checkpoint',
  description: 'Create checkpoint every 5 iterations',
  enabled: true,
  trigger: 'conditional',
  condition: 'iteration % 5 === 0',
  actions: [
    {
      type: 'checkpoint',
      operation: 'create'
    },
    {
      type: 'notification',
      channel: 'log',
      message: 'Milestone checkpoint created',
      severity: 'info'
    }
  ],
  failOnError: false
};

// ============================================================================
// POST-ITERATION HOOK EXAMPLES
// ============================================================================

/**
 * Example: Collect coverage after successful iteration
 */
export const postCollectCoverage: PostIterationHook = {
  type: 'post_iteration',
  name: 'collect_coverage',
  description: 'Collect coverage data after iteration',
  enabled: true,
  trigger: 'on_success',
  actions: [
    {
      type: 'command',
      command: 'npm run coverage:report',
      timeout: 10000
    }
  ],
  failOnError: false
};

/**
 * Example: Record metrics after every iteration
 */
export const postRecordMetrics: PostIterationHook = {
  type: 'post_iteration',
  name: 'record_metrics',
  description: 'Record iteration metrics',
  enabled: true,
  trigger: 'always',
  actions: [
    {
      type: 'metric',
      metricName: 'iteration_count',
      value: 1,
      operation: 'increment'
    }
  ],
  failOnError: false
};

/**
 * Example: Archive artifacts on failure
 */
export const postArchiveOnFailure: PostIterationHook = {
  type: 'post_iteration',
  name: 'archive_failure',
  description: 'Archive artifacts when iteration fails',
  enabled: true,
  trigger: 'on_failure',
  actions: [
    {
      type: 'command',
      command: 'tar',
      args: ['-czf', 'failure-artifacts.tar.gz', 'build/', 'logs/'],
      timeout: 30000
    },
    {
      type: 'notification',
      channel: 'stderr',
      message: 'Failure artifacts archived',
      severity: 'warn'
    }
  ],
  failOnError: false,
  timeout: 35000
};

/**
 * Example: Cleanup temporary files
 */
export const postCleanup: PostIterationHook = {
  type: 'post_iteration',
  name: 'cleanup',
  description: 'Clean up temporary files',
  enabled: true,
  trigger: 'always',
  actions: [
    {
      type: 'command',
      command: 'rm',
      args: ['-rf', 'tmp/*'],
      timeout: 5000
    }
  ],
  failOnError: false
};

// ============================================================================
// CIRCUIT BREAKER EXAMPLES
// ============================================================================

/**
 * Example: Detect thrashing (repeated failures)
 */
export const circuitBreakerThrashing: CircuitBreakerHook = {
  type: 'circuit_breaker',
  name: 'detect_thrashing',
  description: 'Stop if agent repeats same failures',
  enabled: true,
  strategy: 'thrashing',
  config: {
    strategy: 'thrashing',
    consecutiveFailures: 3,
    similarityThreshold: 0.8,
    windowSize: 5
  },
  action: 'escalate',
  message: 'Detected repeated failures - escalating to human'
};

/**
 * Example: Quality regression detection
 */
export const circuitBreakerQuality: CircuitBreakerHook = {
  type: 'circuit_breaker',
  name: 'quality_regression',
  description: 'Stop if code quality declines',
  enabled: true,
  strategy: 'quality_regression',
  config: {
    strategy: 'quality_regression',
    metric: 'test_pass_rate',
    minValue: 0.8,
    consecutiveRegressions: 2
  },
  action: 'escalate',
  message: 'Code quality declining - needs review'
};

/**
 * Example: Timeout enforcement
 */
export const circuitBreakerTimeout: CircuitBreakerHook = {
  type: 'circuit_breaker',
  name: 'timeout_guard',
  description: 'Enforce maximum iteration time',
  enabled: true,
  strategy: 'timeout',
  config: {
    strategy: 'timeout',
    maxTotalDuration: 1800000, // 30 minutes total
    maxIterationDuration: 300000 // 5 minutes per iteration
  },
  action: 'escalate',
  message: 'Iteration timeout exceeded - needs review'
};

// ============================================================================
// COMPLETE CONFIGURATION EXAMPLES
// ============================================================================

/**
 * Example: Minimal iteration config (Phase 1)
 */
export const minimalIterationConfig: IterationConfig = {
  maxIterations: 10,
  completionPromises: ['All tests pass'],
  validationRules: [
    {
      type: 'command',
      name: 'tests',
      config: {
        command: 'npm test',
        expectedExitCode: 0,
        timeout: 30000
      }
    }
  ],
  circuitBreakerThreshold: 3
};

/**
 * Example: Standard iteration config with hooks
 */
export const standardIterationConfig: IterationConfig = {
  maxIterations: 15,
  completionPromises: [
    'All tests pass',
    'Code compiles without errors',
    'Coverage above 80%'
  ],
  circuitBreakerThreshold: 3,

  validationRules: [
    {
      type: 'command',
      name: 'tests',
      config: {
        command: 'npm test',
        expectedExitCode: 0,
        timeout: 30000
      }
    }
  ],

  hooks: {
    stopHooks: [
      {
        name: 'all_quality_gates',
        validationRules: [
          {
            type: 'command',
            name: 'tests',
            config: { command: 'npm test', expectedExitCode: 0, timeout: 30000 }
          },
          {
            type: 'command',
            name: 'compile',
            config: { command: 'tsc --noEmit', expectedExitCode: 0, timeout: 20000 }
          }
        ],
        action: 'complete',
        priority: 1
      }
    ],

    preIterationHooks: [
      {
        name: 'clean_build',
        actions: [
          { type: 'command', config: { command: 'npm run clean' } }
        ],
        trigger: 'always'
      }
    ],

    postIterationHooks: [
      {
        name: 'collect_metrics',
        actions: [
          {
            type: 'metric',
            config: {
              metricName: 'iteration_count',
              operation: 'increment'
            }
          }
        ],
        trigger: 'always'
      }
    ],

    circuitBreakerHooks: [
      {
        name: 'thrashing_detector',
        strategy: 'thrashing',
        config: {
          consecutiveFailures: 3,
          similarityThreshold: 0.8,
          windowSize: 5
        },
        action: 'escalate'
      }
    ]
  }
};

/**
 * Example: Full featured iteration config
 */
export const fullFeaturedIterationConfig: IterationConfig = {
  maxIterations: 20,
  completionPromises: [
    'All tests pass',
    'Code compiles without errors',
    'Coverage above 90%',
    'Performance benchmarks met'
  ],
  circuitBreakerThreshold: 3,

  validationRules: [
    {
      type: 'command',
      name: 'tests',
      config: {
        command: 'npm test',
        expectedExitCode: 0,
        timeout: 30000
      }
    },
    {
      type: 'command',
      name: 'compile',
      config: {
        command: 'tsc --noEmit',
        expectedExitCode: 0,
        timeout: 20000
      }
    }
  ],

  hooks: {
    stopHooks: [
      {
        name: 'all_quality_gates',
        validationRules: [
          {
            type: 'command',
            name: 'tests',
            config: { command: 'npm test', expectedExitCode: 0, timeout: 30000 }
          },
          {
            type: 'command',
            name: 'compile',
            config: { command: 'tsc --noEmit', expectedExitCode: 0, timeout: 20000 }
          },
          {
            type: 'command',
            name: 'lint',
            config: { command: 'eslint .', expectedExitCode: 0, timeout: 15000 }
          },
          {
            type: 'coverage',
            name: 'coverage',
            config: {
              reportPath: './coverage/coverage-final.json',
              reportFormat: 'json',
              minCoverage: 90,
              scope: 'lines'
            }
          }
        ],
        action: 'complete',
        priority: 1
      },
      {
        name: 'minimal_viable',
        validationRules: [
          {
            type: 'command',
            name: 'tests',
            config: { command: 'npm test', expectedExitCode: 0, timeout: 30000 }
          },
          {
            type: 'command',
            name: 'compile',
            config: { command: 'tsc --noEmit', expectedExitCode: 0, timeout: 20000 }
          }
        ],
        action: 'complete',
        priority: 2
      }
    ],

    preIterationHooks: [
      {
        name: 'clean_and_checkpoint',
        actions: [
          { type: 'command', config: { command: 'npm run clean' } },
          { type: 'checkpoint', config: { operation: 'create' } },
          {
            type: 'notification',
            config: {
              channel: 'log',
              message: 'Starting iteration',
              severity: 'info'
            }
          }
        ],
        trigger: 'always'
      },
      {
        name: 'milestone_checkpoint',
        actions: [
          { type: 'checkpoint', config: { operation: 'create' } }
        ],
        trigger: 'conditional'
      }
    ],

    postIterationHooks: [
      {
        name: 'collect_coverage',
        actions: [
          { type: 'command', config: { command: 'npm run coverage:report' } }
        ],
        trigger: 'on_success'
      },
      {
        name: 'record_metrics',
        actions: [
          {
            type: 'metric',
            config: {
              metricName: 'iteration_count',
              operation: 'increment'
            }
          }
        ],
        trigger: 'always'
      },
      {
        name: 'cleanup',
        actions: [
          { type: 'command', config: { command: 'rm -rf tmp/*' } }
        ],
        trigger: 'always'
      }
    ],

    circuitBreakerHooks: [
      {
        name: 'thrashing_detector',
        strategy: 'thrashing',
        config: {
          consecutiveFailures: 3,
          similarityThreshold: 0.8,
          windowSize: 5
        },
        action: 'escalate'
      },
      {
        name: 'quality_regression',
        strategy: 'quality_regression',
        config: {
          metric: 'test_pass_rate',
          minValue: 0.8,
          consecutiveRegressions: 2
        },
        action: 'escalate'
      },
      {
        name: 'timeout_guard',
        strategy: 'timeout',
        config: {
          maxTotalDuration: 1800000, // 30 minutes
          maxIterationDuration: 300000 // 5 minutes
        },
        action: 'escalate'
      }
    ]
  }
};

/**
 * Example: Full hook config object
 */
export const fullHookConfig: IterationHookConfig = {
  version: '1.0.0',

  stopHooks: [
    stopOnAllQualityGates,
    stopOnTestsPass,
    stopOnCleanBuild
  ],

  preIterationHooks: [
    preCleanBuild,
    preCreateCheckpoint,
    preMilestoneCheckpoint
  ],

  postIterationHooks: [
    postCollectCoverage,
    postRecordMetrics,
    postCleanup
  ],

  circuitBreakerHooks: [
    circuitBreakerThrashing,
    circuitBreakerQuality,
    circuitBreakerTimeout
  ],

  global: {
    maxHooksPerIteration: 20,
    maxHookDuration: 300000, // 5 minutes total for all hooks
    parallelExecution: true,
    continueOnError: false
  }
};

// ============================================================================
// AGENT-SPECIFIC EXAMPLES
// ============================================================================

/**
 * Example: Engineer agent iteration config
 */
export const engineerIterationConfig: IterationConfig = {
  maxIterations: 15,
  completionPromises: [
    'All tests pass',
    'Code compiles without errors',
    'No linting errors'
  ],
  circuitBreakerThreshold: 3,

  validationRules: [
    {
      type: 'command',
      name: 'tests',
      config: { command: 'npm test', expectedExitCode: 0, timeout: 30000 }
    },
    {
      type: 'command',
      name: 'compile',
      config: { command: 'tsc --noEmit', expectedExitCode: 0, timeout: 20000 }
    },
    {
      type: 'command',
      name: 'lint',
      config: { command: 'eslint .', expectedExitCode: 0, timeout: 15000 }
    }
  ],

  hooks: {
    stopHooks: [
      {
        name: 'engineering_complete',
        validationRules: [
          {
            type: 'command',
            name: 'tests',
            config: { command: 'npm test', expectedExitCode: 0, timeout: 30000 }
          },
          {
            type: 'command',
            name: 'compile',
            config: { command: 'tsc --noEmit', expectedExitCode: 0, timeout: 20000 }
          },
          {
            type: 'command',
            name: 'lint',
            config: { command: 'eslint .', expectedExitCode: 0, timeout: 15000 }
          }
        ],
        action: 'complete',
        priority: 1
      }
    ],
    circuitBreakerHooks: [
      {
        name: 'detect_thrashing',
        strategy: 'thrashing',
        config: {
          consecutiveFailures: 3,
          similarityThreshold: 0.85,
          windowSize: 5
        },
        action: 'escalate'
      }
    ]
  }
};

/**
 * Example: QA agent iteration config
 */
export const qaIterationConfig: IterationConfig = {
  maxIterations: 10,
  completionPromises: [
    'All tests pass',
    'Coverage threshold met',
    'No flaky tests detected'
  ],
  circuitBreakerThreshold: 2,

  validationRules: [
    {
      type: 'command',
      name: 'tests',
      config: { command: 'npm test', expectedExitCode: 0, timeout: 60000 }
    },
    {
      type: 'coverage',
      name: 'coverage',
      config: {
        reportPath: './coverage/coverage-final.json',
        reportFormat: 'json',
        minCoverage: 80,
        scope: 'lines'
      }
    }
  ],

  hooks: {
    stopHooks: [
      {
        name: 'qa_complete',
        validationRules: [
          {
            type: 'command',
            name: 'tests',
            config: { command: 'npm test', expectedExitCode: 0, timeout: 60000 }
          },
          {
            type: 'coverage',
            name: 'coverage',
            config: {
              reportPath: './coverage/coverage-final.json',
              reportFormat: 'json',
              minCoverage: 80
            }
          }
        ],
        action: 'complete',
        priority: 1
      }
    ],
    preIterationHooks: [
      {
        name: 'reset_test_env',
        actions: [
          { type: 'command', config: { command: 'npm run test:reset' } }
        ],
        trigger: 'always'
      }
    ]
  }
};
