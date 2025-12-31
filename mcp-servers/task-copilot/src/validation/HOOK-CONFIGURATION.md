# Ralph Wiggum Iteration Hook Configuration

## Overview

Hooks provide lifecycle control and safety mechanisms for iterative agent workflows. The hook system supports four types of hooks:

1. **Stop Hooks** - Validation-based iteration termination
2. **Pre-Iteration Hooks** - Actions run before each iteration
3. **Post-Iteration Hooks** - Actions run after each iteration
4. **Circuit Breaker Hooks** - Safety mechanisms to prevent runaway iterations

## Architecture

```
iteration_start
    ↓
┌─────────────────────────┐
│  PRE-ITERATION HOOKS    │ ← Setup, validation prep
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  AGENT ITERATION        │ ← Agent performs work
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  POST-ITERATION HOOKS   │ ← Cleanup, metrics
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  STOP HOOKS             │ ← Check completion
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  CIRCUIT BREAKERS       │ ← Safety checks
└─────────────────────────┘
    ↓
  CONTINUE / COMPLETE / ESCALATE
```

## Hook Types

### 1. Stop Hooks

Stop hooks determine when iteration should terminate. They use validation rules to check completion criteria.

**Use Cases:**
- All tests passing
- Code compiles without errors
- Coverage threshold met
- Linting passes
- Performance benchmarks met

**Example:**
```typescript
const stopHook: StopHook = {
  type: 'stop',
  name: 'tests_pass',
  description: 'Stop when all tests pass',
  enabled: true,
  validationRules: [
    {
      type: 'command',
      name: 'run_tests',
      command: 'npm test',
      expectedExitCode: 0,
      timeout: 30000,
      enabled: true
    }
  ],
  action: 'complete',
  priority: 1,
  message: 'All tests passing - iteration complete'
};
```

### 2. Pre-Iteration Hooks

Run before each iteration starts. Useful for setup, cleanup, or validation prep.

**Use Cases:**
- Clean build artifacts
- Reset test database
- Fetch latest dependencies
- Create checkpoint
- Log iteration start

**Example:**
```typescript
const preHook: PreIterationHook = {
  type: 'pre_iteration',
  name: 'clean_build',
  description: 'Clean build artifacts before iteration',
  enabled: true,
  trigger: 'always',
  actions: [
    {
      type: 'command',
      command: 'npm',
      args: ['run', 'clean'],
      timeout: 10000
    },
    {
      type: 'checkpoint',
      operation: 'create'
    }
  ],
  failOnError: false,
  timeout: 15000
};
```

### 3. Post-Iteration Hooks

Run after each iteration completes. Useful for cleanup, metrics, or artifact collection.

**Use Cases:**
- Collect coverage reports
- Archive build artifacts
- Update metrics
- Clean up temporary files
- Log iteration results

**Example:**
```typescript
const postHook: PostIterationHook = {
  type: 'post_iteration',
  name: 'collect_coverage',
  description: 'Collect coverage data after iteration',
  enabled: true,
  trigger: 'on_success',
  actions: [
    {
      type: 'command',
      command: 'npm',
      args: ['run', 'coverage:report']
    },
    {
      type: 'metric',
      metricName: 'iteration_coverage',
      value: 'from_report',
      operation: 'set'
    }
  ],
  failOnError: false
};
```

### 4. Circuit Breaker Hooks

Safety mechanisms to prevent runaway iterations and detect problematic patterns.

**Strategies:**
- **Thrashing** - Detects repeated similar failures
- **Quality Regression** - Detects declining quality metrics
- **Timeout** - Enforces time limits
- **Custom** - Custom detection logic

**Example: Thrashing Detection**
```typescript
const circuitBreaker: CircuitBreakerHook = {
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
```

**Example: Quality Regression**
```typescript
const qualityBreaker: CircuitBreakerHook = {
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
```

**Example: Timeout**
```typescript
const timeoutBreaker: CircuitBreakerHook = {
  type: 'circuit_breaker',
  name: 'iteration_timeout',
  description: 'Enforce maximum iteration time',
  enabled: true,
  strategy: 'timeout',
  config: {
    strategy: 'timeout',
    maxTotalDuration: 1800000, // 30 minutes
    maxIterationDuration: 300000 // 5 minutes per iteration
  },
  action: 'escalate',
  message: 'Iteration timeout exceeded'
};
```

## Complete Configuration Example

```typescript
import type { IterationConfig } from '../types.js';

const fullIterationConfig: IterationConfig = {
  maxIterations: 15,
  completionPromises: [
    'All tests pass',
    'Code compiles without errors',
    'Coverage above 80%'
  ],
  circuitBreakerThreshold: 3,

  // Validation rules (Phase 1 format)
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

  // Hook configuration (Phase 2)
  hooks: {
    // Stop when completion criteria met
    stopHooks: [
      {
        name: 'all_checks_pass',
        validationRules: [
          {
            type: 'command',
            name: 'tests',
            config: { command: 'npm test', expectedExitCode: 0, timeout: 30000 }
          },
          {
            type: 'command',
            name: 'lint',
            config: { command: 'npm run lint', expectedExitCode: 0, timeout: 10000 }
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
        action: 'complete',
        priority: 1
      }
    ],

    // Pre-iteration setup
    preIterationHooks: [
      {
        name: 'setup',
        actions: [
          {
            type: 'command',
            config: { command: 'npm run clean' }
          },
          {
            type: 'checkpoint',
            config: { operation: 'create' }
          }
        ],
        trigger: 'always'
      }
    ],

    // Post-iteration cleanup and metrics
    postIterationHooks: [
      {
        name: 'collect_metrics',
        actions: [
          {
            type: 'command',
            config: { command: 'npm run coverage:report' }
          },
          {
            type: 'metric',
            config: {
              metricName: 'iteration_duration',
              operation: 'set'
            }
          }
        ],
        trigger: 'always'
      }
    ],

    // Safety mechanisms
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
        name: 'timeout_guard',
        strategy: 'timeout',
        config: {
          maxTotalDuration: 1800000, // 30 min
          maxIterationDuration: 300000 // 5 min
        },
        action: 'escalate'
      }
    ]
  }
};
```

## Usage with iteration_start

```typescript
// Start iteration with hook configuration
const result = await iteration_start({
  taskId: 'TASK-123',
  maxIterations: 15,
  completionPromises: ['All tests pass'],

  // Phase 1: Validation rules
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

  // Phase 2: Stop hooks (when RW-010 is complete)
  hooks: {
    stopHooks: [
      {
        name: 'tests_pass',
        validationRules: [/* ... */],
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
          similarityThreshold: 0.8,
          windowSize: 5
        },
        action: 'escalate'
      }
    ]
  }
});
```

## Hook Execution Order

Within each phase, hooks execute in priority order:

1. **Pre-Iteration Hooks** (ascending priority)
2. **Agent Work**
3. **Post-Iteration Hooks** (ascending priority)
4. **Stop Hooks** (ascending priority, first match wins)
5. **Circuit Breakers** (ascending priority, first trip wins)

## Hook Actions

### Supported Action Types

| Type | Description | Config Fields |
|------|-------------|---------------|
| `command` | Execute shell command | `command`, `args`, `workingDirectory`, `env`, `timeout` |
| `notification` | Send notification | `channel`, `message`, `severity` |
| `checkpoint` | Create/cleanup checkpoint | `operation`, `config` |
| `metric` | Record metric | `metricName`, `value`, `operation` |
| `custom` | Custom action | `actionId`, `config` |

### Action Context

All actions have access to context:
- `taskId` - Current task ID
- `iterationNumber` - Current iteration number
- `hookType` - Type of hook executing
- `trigger` - Hook trigger condition

## Hook Triggers

| Trigger | When Executed |
|---------|---------------|
| `always` | Every iteration |
| `on_success` | Only when previous validation passed |
| `on_failure` | Only when previous validation failed |
| `conditional` | When custom condition evaluates to true |

## Conditional Triggers

For `conditional` triggers, provide a JavaScript expression in the `condition` field:

```typescript
{
  type: 'post_iteration',
  name: 'milestone_checkpoint',
  trigger: 'conditional',
  condition: 'iteration % 5 === 0', // Every 5th iteration
  actions: [
    { type: 'checkpoint', config: { operation: 'create' } }
  ]
}
```

Available variables in condition:
- `iteration` - Current iteration number
- `config` - Full iteration config
- `history` - Iteration history array

## Error Handling

Hooks can be configured to fail gracefully or fail the iteration:

```typescript
{
  failOnError: false // Continue even if hook fails
}
```

Global error handling:
```typescript
{
  global: {
    continueOnError: true,
    maxHooksPerIteration: 20,
    maxHookDuration: 60000
  }
}
```

## Best Practices

1. **Keep Stop Hooks Simple** - Focus on objective criteria (tests pass, builds succeed)
2. **Use Priority Wisely** - Higher priority (lower number) for critical checks
3. **Set Reasonable Timeouts** - Prevent hooks from blocking indefinitely
4. **Fail Gracefully** - Use `failOnError: false` for non-critical hooks
5. **Circuit Breakers First** - Add thrashing detection to all complex iterations
6. **Log Everything** - Use notification actions for debugging
7. **Test Hooks Separately** - Validate hook config before using in production

## Migration Path

**Phase 1 (Current)**: Use `validationRules` in `IterationConfig`
```typescript
{
  validationRules: [
    { type: 'command', name: 'tests', config: {...} }
  ]
}
```

**Phase 2 (After RW-010)**: Migrate to `hooks.stopHooks`
```typescript
{
  hooks: {
    stopHooks: [
      {
        name: 'tests_pass',
        validationRules: [
          { type: 'command', name: 'tests', config: {...} }
        ],
        action: 'complete',
        priority: 1
      }
    ]
  }
}
```

Both formats are supported for backward compatibility.

## Related Files

- **Type Definitions**: `src/validation/iteration-hook-types.ts`
- **Validation Rules**: `src/validation/iteration-types.ts`
- **Config Examples**: `src/validation/iteration-config-examples.ts`
- **Iteration Tools**: `src/tools/iteration.ts`
