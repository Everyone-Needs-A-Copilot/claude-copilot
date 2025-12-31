# Ralph Wiggum Hook Configuration System

## Overview

The Ralph Wiggum hook system provides lifecycle control and safety mechanisms for iterative agent workflows. Hooks allow you to:

- **Stop iterations** when specific criteria are met (validation-based completion)
- **Execute actions** before/after each iteration (setup, cleanup, metrics)
- **Prevent runaway iterations** with circuit breakers (safety mechanisms)
- **Customize iteration behavior** per agent or task type

## Quick Start

### Basic Usage (Phase 1)

```typescript
import { iteration_start } from './tools/iteration.js';

const result = await iteration_start({
  taskId: 'TASK-123',
  maxIterations: 15,
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
  ]
});
```

### With Hooks (Phase 2 - After RW-010)

```typescript
const result = await iteration_start({
  taskId: 'TASK-123',
  maxIterations: 15,
  completionPromises: ['All tests pass'],

  hooks: {
    stopHooks: [
      {
        name: 'tests_pass',
        validationRules: [
          {
            type: 'command',
            name: 'tests',
            config: { command: 'npm test', expectedExitCode: 0 }
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
          similarityThreshold: 0.8,
          windowSize: 5
        },
        action: 'escalate'
      }
    ]
  }
});
```

## File Structure

```
src/validation/
├── iteration-hook-types.ts      # TypeScript type definitions
├── iteration-hook-examples.ts   # Practical configuration examples
├── HOOK-CONFIGURATION.md        # Complete documentation
├── HOOK-README.md              # This file (quick reference)
└── iteration-types.ts          # Validation rule types
```

## Hook Types

### 1. Stop Hooks
Determine when to terminate iteration based on validation rules.

**Common Use Cases:**
- Tests passing
- Build succeeding
- Coverage thresholds met
- No linting errors

**Example:**
```typescript
{
  name: 'tests_pass',
  validationRules: [
    { type: 'command', name: 'tests', config: {...} }
  ],
  action: 'complete',
  priority: 1
}
```

### 2. Pre-Iteration Hooks
Execute actions before each iteration.

**Common Use Cases:**
- Clean build artifacts
- Reset test database
- Create checkpoint
- Setup test environment

**Example:**
```typescript
{
  name: 'clean_build',
  actions: [
    { type: 'command', config: { command: 'npm run clean' } }
  ],
  trigger: 'always'
}
```

### 3. Post-Iteration Hooks
Execute actions after each iteration.

**Common Use Cases:**
- Collect metrics
- Archive artifacts
- Cleanup temporary files
- Generate reports

**Example:**
```typescript
{
  name: 'collect_metrics',
  actions: [
    { type: 'metric', config: { metricName: 'iteration_count', operation: 'increment' } }
  ],
  trigger: 'always'
}
```

### 4. Circuit Breaker Hooks
Safety mechanisms to prevent runaway iterations.

**Strategies:**
- **Thrashing**: Detect repeated similar failures
- **Quality Regression**: Detect declining quality metrics
- **Timeout**: Enforce time limits
- **Custom**: Custom detection logic

**Example:**
```typescript
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
```

## Validation Rules

Validation rules are used by stop hooks to check completion criteria.

### Available Rule Types

| Type | Description | Config Fields |
|------|-------------|---------------|
| `command` | Execute shell command | `command`, `expectedExitCode`, `timeout` |
| `content_pattern` | Regex matching in output | `pattern`, `target`, `mustMatch` |
| `coverage` | Parse coverage reports | `reportPath`, `reportFormat`, `minCoverage` |
| `file_existence` | Check file existence | `paths`, `allMustExist` |
| `custom` | Custom validator | `validatorId`, `config` |

### Examples

**Command Validation:**
```typescript
{
  type: 'command',
  name: 'tests',
  config: {
    command: 'npm test',
    expectedExitCode: 0,
    timeout: 30000
  }
}
```

**Coverage Validation:**
```typescript
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
```

**Content Pattern Validation:**
```typescript
{
  type: 'content_pattern',
  name: 'success_message',
  config: {
    pattern: 'Build succeeded',
    target: 'agent_output',
    mustMatch: true
  }
}
```

## Hook Actions

Actions that can be executed by pre/post iteration hooks.

### Available Action Types

| Type | Description | Config Fields |
|------|-------------|---------------|
| `command` | Execute shell command | `command`, `args`, `workingDirectory`, `timeout` |
| `notification` | Send notification | `channel`, `message`, `severity` |
| `checkpoint` | Create/cleanup checkpoint | `operation`, `config` |
| `metric` | Record metric | `metricName`, `value`, `operation` |
| `custom` | Custom action | `actionId`, `config` |

### Examples

**Command Action:**
```typescript
{
  type: 'command',
  config: {
    command: 'npm',
    args: ['run', 'clean'],
    timeout: 10000
  }
}
```

**Metric Action:**
```typescript
{
  type: 'metric',
  config: {
    metricName: 'iteration_count',
    value: 1,
    operation: 'increment'
  }
}
```

**Checkpoint Action:**
```typescript
{
  type: 'checkpoint',
  config: {
    operation: 'create'
  }
}
```

## Hook Triggers

Control when hooks execute.

| Trigger | When Executed |
|---------|---------------|
| `always` | Every iteration |
| `on_success` | Only when previous validation passed |
| `on_failure` | Only when previous validation failed |
| `conditional` | When custom condition is true |

**Conditional Example:**
```typescript
{
  trigger: 'conditional',
  condition: 'iteration % 5 === 0' // Every 5th iteration
}
```

## Circuit Breaker Strategies

### Thrashing Detection
Detects when the agent repeats similar failures.

```typescript
{
  strategy: 'thrashing',
  config: {
    consecutiveFailures: 3,
    similarityThreshold: 0.8,
    windowSize: 5
  }
}
```

### Quality Regression
Detects when quality metrics decline over iterations.

```typescript
{
  strategy: 'quality_regression',
  config: {
    metric: 'test_pass_rate',
    minValue: 0.8,
    consecutiveRegressions: 2
  }
}
```

### Timeout
Enforces maximum time limits.

```typescript
{
  strategy: 'timeout',
  config: {
    maxTotalDuration: 1800000, // 30 minutes total
    maxIterationDuration: 300000 // 5 minutes per iteration
  }
}
```

## Complete Examples

### Engineer Agent Config
```typescript
{
  maxIterations: 15,
  completionPromises: ['All tests pass', 'Code compiles'],

  hooks: {
    stopHooks: [
      {
        name: 'engineering_complete',
        validationRules: [
          { type: 'command', name: 'tests', config: {...} },
          { type: 'command', name: 'compile', config: {...} },
          { type: 'command', name: 'lint', config: {...} }
        ],
        action: 'complete',
        priority: 1
      }
    ],
    circuitBreakerHooks: [
      {
        name: 'detect_thrashing',
        strategy: 'thrashing',
        config: { consecutiveFailures: 3, similarityThreshold: 0.85 },
        action: 'escalate'
      }
    ]
  }
}
```

### QA Agent Config
```typescript
{
  maxIterations: 10,
  completionPromises: ['All tests pass', 'Coverage met'],

  hooks: {
    stopHooks: [
      {
        name: 'qa_complete',
        validationRules: [
          { type: 'command', name: 'tests', config: {...} },
          { type: 'coverage', name: 'coverage', config: {...} }
        ],
        action: 'complete',
        priority: 1
      }
    ],
    preIterationHooks: [
      {
        name: 'reset_test_env',
        actions: [{ type: 'command', config: { command: 'npm run test:reset' } }],
        trigger: 'always'
      }
    ]
  }
}
```

## Best Practices

1. **Keep Stop Hooks Simple** - Focus on objective, measurable criteria
2. **Use Priority Wisely** - Lower number = higher priority (1 runs before 2)
3. **Set Reasonable Timeouts** - Prevent hooks from blocking indefinitely
4. **Fail Gracefully** - Use `failOnError: false` for non-critical hooks
5. **Add Circuit Breakers** - Always include thrashing detection for complex iterations
6. **Log Everything** - Use notification actions for debugging
7. **Test Independently** - Validate hook configurations before production use

## Migration Path

**Phase 1 (Current):**
```typescript
{
  validationRules: [
    { type: 'command', name: 'tests', config: {...} }
  ]
}
```

**Phase 2 (After RW-010):**
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

## See Also

- **Full Documentation**: `HOOK-CONFIGURATION.md`
- **Type Definitions**: `iteration-hook-types.ts`
- **Validation Rules**: `iteration-types.ts`
- **Examples**: `iteration-hook-examples.ts`
- **Iteration Tools**: `../tools/iteration.ts`

## Support

For issues or questions:
1. Check `HOOK-CONFIGURATION.md` for detailed documentation
2. Review `iteration-hook-examples.ts` for practical examples
3. Consult type definitions in `iteration-hook-types.ts`
