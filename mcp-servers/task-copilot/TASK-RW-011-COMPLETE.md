# TASK RW-011: Hook Config Schema - Implementation Complete

## Task Summary

**Task ID**: TASK-ac6b41ec-2802-4227-8076-30685893bf9b
**Title**: RW-011 Hook Config Schema
**Status**: Complete
**Phase**: Phase 2 of Ralph Wiggum Integration

## Objective

Create comprehensive hook configuration schema for iteration control, including:
- Stop hooks (validation-based completion)
- Pre/Post iteration hooks (lifecycle callbacks)
- Circuit breaker hooks (safety mechanisms)
- Complete TypeScript type definitions
- Documentation and examples

## Implementation

### Files Created

1. **`src/validation/iteration-hook-types.ts`** (340 lines)
   - Complete TypeScript type definitions for all hook types
   - Stop hooks, pre/post iteration hooks, circuit breaker hooks
   - Hook actions (command, notification, checkpoint, metric, custom)
   - Hook execution results and reports
   - Hook registry for custom validators and circuit breakers
   - Context types for validation and execution

2. **`src/validation/HOOK-CONFIGURATION.md`** (500+ lines)
   - Comprehensive documentation of hook system
   - Architecture diagram and execution flow
   - Detailed explanation of each hook type
   - Complete configuration examples
   - Best practices and migration guide

3. **`src/validation/iteration-hook-examples.ts`** (600+ lines)
   - Practical, ready-to-use examples for all hook types
   - Agent-specific configurations (Engineer, QA)
   - Minimal, standard, and full-featured configs
   - Real-world use cases

4. **`src/validation/HOOK-README.md`** (400+ lines)
   - Quick reference guide
   - Quick start examples
   - Tables of hook types, actions, triggers
   - Migration path documentation

### Files Modified

1. **`src/types.ts`**
   - Enhanced `IterationConfig` interface with optional `hooks` field
   - Added backward-compatible hook configuration structure
   - Maintains compatibility with Phase 1 `validationRules` format
   - Added documentation comments

2. **`src/validation/index.ts`**
   - Added export for `iteration-hook-types.ts`
   - Makes hook types available to consumers

## Type Definitions

### Core Hook Types

```typescript
// Hook types
type HookType = 'stop' | 'pre_iteration' | 'post_iteration' | 'circuit_breaker';
type HookTrigger = 'always' | 'on_failure' | 'on_success' | 'conditional';

// Stop hooks (validation-based completion)
interface StopHook {
  type: 'stop';
  name: string;
  validationRules: IterationValidationRule[];
  action: 'complete' | 'blocked' | 'escalate';
  priority: number;
}

// Pre-iteration hooks
interface PreIterationHook {
  type: 'pre_iteration';
  name: string;
  trigger: HookTrigger;
  actions: HookAction[];
  failOnError: boolean;
}

// Post-iteration hooks
interface PostIterationHook {
  type: 'post_iteration';
  name: string;
  trigger: HookTrigger;
  actions: HookAction[];
  failOnError: boolean;
}

// Circuit breaker hooks
interface CircuitBreakerHook {
  type: 'circuit_breaker';
  name: string;
  strategy: 'thrashing' | 'quality_regression' | 'timeout' | 'custom';
  config: CircuitBreakerConfig;
  action: 'escalate' | 'blocked';
}
```

### Hook Actions

```typescript
type HookAction =
  | CommandAction        // Execute shell command
  | NotificationAction   // Send notification
  | CheckpointAction     // Create/cleanup checkpoint
  | MetricAction         // Record metric
  | CustomAction;        // Custom action executor
```

### Circuit Breaker Strategies

```typescript
// Detect repeated failures
interface ThrashingDetectorConfig {
  consecutiveFailures: number;
  similarityThreshold: number;
  windowSize: number;
}

// Detect quality decline
interface QualityRegressionConfig {
  metric: string;
  minValue: number;
  consecutiveRegressions: number;
}

// Enforce time limits
interface TimeoutConfig {
  maxTotalDuration: number;
  maxIterationDuration?: number;
}
```

### Complete Hook Configuration

```typescript
interface IterationHookConfig {
  version: string;
  stopHooks: StopHook[];
  preIterationHooks: PreIterationHook[];
  postIterationHooks: PostIterationHook[];
  circuitBreakerHooks: CircuitBreakerHook[];
  global: {
    maxHooksPerIteration: number;
    maxHookDuration: number;
    parallelExecution: boolean;
    continueOnError: boolean;
  };
}
```

## Integration with IterationConfig

The `IterationConfig` type in `src/types.ts` now supports an optional `hooks` field:

```typescript
interface IterationConfig {
  maxIterations: number;
  completionPromises: string[];
  validationRules?: Array<{...}>; // Phase 1 (backward compatible)
  circuitBreakerThreshold?: number;

  // Phase 2 hook configuration
  hooks?: {
    stopHooks?: Array<{...}>;
    preIterationHooks?: Array<{...}>;
    postIterationHooks?: Array<{...}>;
    circuitBreakerHooks?: Array<{...}>;
  };
}
```

This design:
- ✅ Maintains backward compatibility with Phase 1
- ✅ Allows gradual migration to Phase 2 hooks
- ✅ Supports both formats simultaneously
- ✅ Stored as JSON in `checkpoint.iteration_config`

## Usage Examples

### Basic Stop Hook
```typescript
const stopHook: StopHook = {
  type: 'stop',
  name: 'tests_pass',
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
  priority: 1
};
```

### Pre-Iteration Hook
```typescript
const preHook: PreIterationHook = {
  type: 'pre_iteration',
  name: 'clean_build',
  trigger: 'always',
  actions: [
    {
      type: 'command',
      command: 'npm',
      args: ['run', 'clean']
    }
  ],
  failOnError: false
};
```

### Circuit Breaker
```typescript
const circuitBreaker: CircuitBreakerHook = {
  type: 'circuit_breaker',
  name: 'detect_thrashing',
  strategy: 'thrashing',
  config: {
    strategy: 'thrashing',
    consecutiveFailures: 3,
    similarityThreshold: 0.8,
    windowSize: 5
  },
  action: 'escalate'
};
```

### Full Iteration Config
```typescript
const config: IterationConfig = {
  maxIterations: 15,
  completionPromises: ['All tests pass'],
  hooks: {
    stopHooks: [stopHook],
    preIterationHooks: [preHook],
    circuitBreakerHooks: [circuitBreaker]
  }
};
```

## Architecture

### Hook Execution Flow

```
iteration_start
    ↓
┌─────────────────────────┐
│  PRE-ITERATION HOOKS    │ ← Setup, cleanup, checkpoints
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  AGENT ITERATION        │ ← Agent performs work
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  POST-ITERATION HOOKS   │ ← Metrics, artifacts, cleanup
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  STOP HOOKS             │ ← Check completion criteria
└─────────────────────────┘
    ↓
┌─────────────────────────┐
│  CIRCUIT BREAKERS       │ ← Safety checks
└─────────────────────────┘
    ↓
  CONTINUE / COMPLETE / ESCALATE
```

### Hook Priority

Within each phase, hooks execute in priority order:
1. **Pre-Iteration Hooks** (ascending priority)
2. **Agent Work**
3. **Post-Iteration Hooks** (ascending priority)
4. **Stop Hooks** (ascending priority, first match wins)
5. **Circuit Breakers** (ascending priority, first trip wins)

## Validation Rules

Validation rules are used by stop hooks to check completion criteria.

### Rule Types

| Type | Description | Use Case |
|------|-------------|----------|
| `command` | Execute shell command, check exit code | Tests, builds, linting |
| `content_pattern` | Regex match in agent output | Success messages, error patterns |
| `coverage` | Parse coverage reports | Code coverage thresholds |
| `file_existence` | Check if files exist | Build artifacts, reports |
| `custom` | Custom validator function | Complex business logic |

## Hook Actions

Actions that can be executed by pre/post iteration hooks.

### Action Types

| Type | Description | Use Case |
|------|-------------|----------|
| `command` | Execute shell command | Build, test, deploy |
| `notification` | Send notification | Logging, alerts |
| `checkpoint` | Create/cleanup checkpoint | Recovery points |
| `metric` | Record metric | Performance tracking |
| `custom` | Custom action function | Integration with external systems |

## Circuit Breaker Strategies

### 1. Thrashing Detection
Detects when agent repeats similar failures (stuck in a loop).

**Config:**
- `consecutiveFailures`: Number of failures to detect
- `similarityThreshold`: How similar failures must be (0-1)
- `windowSize`: Number of iterations to check

### 2. Quality Regression
Detects when quality metrics decline over iterations.

**Config:**
- `metric`: Metric to track (e.g., 'test_pass_rate')
- `minValue`: Minimum acceptable value
- `consecutiveRegressions`: Number of declines to trigger

### 3. Timeout
Enforces maximum time limits.

**Config:**
- `maxTotalDuration`: Total time for all iterations
- `maxIterationDuration`: Time per iteration

### 4. Custom
Custom detection logic via registered function.

**Config:**
- `breakerId`: ID of registered circuit breaker
- `config`: Custom configuration object

## Migration Path

### Phase 1 (Current)
```typescript
{
  validationRules: [
    { type: 'command', name: 'tests', config: {...} }
  ]
}
```

### Phase 2 (After RW-010)
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

**Both formats are supported for backward compatibility.**

## Documentation

### Primary Documentation
- **`HOOK-CONFIGURATION.md`**: Complete documentation (500+ lines)
  - Architecture and execution flow
  - Detailed hook type explanations
  - Configuration examples
  - Best practices
  - Migration guide

### Quick Reference
- **`HOOK-README.md`**: Quick start guide (400+ lines)
  - Quick start examples
  - Tables of hook types and actions
  - Common use cases
  - Migration path

### Examples
- **`iteration-hook-examples.ts`**: Ready-to-use examples (600+ lines)
  - Stop hooks for various scenarios
  - Pre/post iteration hooks
  - Circuit breakers
  - Agent-specific configurations
  - Complete iteration configs

## Exports

All hook types are exported from the validation module:

```typescript
// From src/validation/index.ts
export * from './iteration-hook-types.js';

// Available exports:
// - HookType, HookTrigger
// - StopHook, PreIterationHook, PostIterationHook, CircuitBreakerHook
// - HookAction (CommandAction, NotificationAction, CheckpointAction, MetricAction, CustomAction)
// - CircuitBreakerConfig (ThrashingDetectorConfig, QualityRegressionConfig, TimeoutConfig)
// - IterationHookConfig
// - HookExecutionResult, HookExecutionReport
// - HookRegistry, CustomValidator, CustomCircuitBreaker, CustomActionExecutor
// - ValidationContext, CircuitBreakerContext, ActionContext
```

## Integration Points

### With Existing Code

1. **`src/types.ts`**
   - Enhanced `IterationConfig` with optional `hooks` field
   - Backward compatible with Phase 1 format

2. **`src/tools/checkpoint.ts`**
   - Checkpoint storage already supports iteration fields
   - Hook execution results can be stored in checkpoint

3. **`src/tools/iteration.ts`**
   - Ready to integrate hook execution (when RW-010 is complete)
   - Validation rules already working

4. **`src/validation/iteration-engine.ts`**
   - Validation engine supports all rule types
   - Ready for hook integration

### For RW-010 (Stop Hook System)

The types defined here provide the foundation for RW-010:

1. **Stop Hook Execution**
   - Use `StopHook` type for configuration
   - Use `IterationValidationRule` for validation
   - Use `HookExecutionResult` for results

2. **Circuit Breaker Implementation**
   - Use `CircuitBreakerHook` type
   - Implement strategies: thrashing, quality regression, timeout
   - Use `CircuitBreakerContext` and `CircuitBreakerResult`

3. **Pre/Post Hook Execution**
   - Use `PreIterationHook` and `PostIterationHook` types
   - Implement action executors
   - Use `HookExecutionReport` for tracking

## Testing Considerations

### Unit Tests Needed
- [ ] Hook configuration validation
- [ ] Hook priority sorting
- [ ] Action execution
- [ ] Circuit breaker strategies
- [ ] Hook trigger conditions

### Integration Tests Needed
- [ ] Full iteration with hooks
- [ ] Stop hook termination
- [ ] Circuit breaker triggering
- [ ] Pre/post hook execution
- [ ] Error handling and recovery

## Best Practices

1. **Keep Stop Hooks Simple**
   - Focus on objective criteria (tests pass, builds succeed)
   - Avoid complex logic in validation rules

2. **Use Priority Wisely**
   - Lower number = higher priority (1 runs before 2)
   - Critical checks first, nice-to-haves later

3. **Set Reasonable Timeouts**
   - Prevent hooks from blocking indefinitely
   - Consider CI/CD environment constraints

4. **Fail Gracefully**
   - Use `failOnError: false` for non-critical hooks
   - Log failures for debugging

5. **Circuit Breakers First**
   - Add thrashing detection to all complex iterations
   - Set conservative thresholds initially

6. **Log Everything**
   - Use notification actions for debugging
   - Record metrics for analysis

7. **Test Hooks Separately**
   - Validate hook configurations before production
   - Test circuit breakers with intentional failures

## Next Steps

### For RW-010 Implementation

1. **Implement Hook Execution Engine**
   - Hook runner that executes hooks in priority order
   - Action executors for each action type
   - Circuit breaker implementations

2. **Integrate with Iteration Tools**
   - Modify `iteration_validate` to execute stop hooks
   - Add pre/post hook execution to iteration flow
   - Implement circuit breaker checks

3. **Add Hook Registry**
   - Custom validator registration
   - Custom circuit breaker registration
   - Custom action executor registration

4. **Update Database Schema**
   - Hook execution results in checkpoint
   - Circuit breaker state tracking
   - Hook metrics

5. **Testing**
   - Unit tests for hook execution
   - Integration tests with real iterations
   - Circuit breaker edge cases

### Documentation Updates Needed

- [ ] Add hook execution flow to architecture docs
- [ ] Update iteration tool documentation
- [ ] Add hook debugging guide
- [ ] Create troubleshooting guide

## Acceptance Criteria

- ✅ TypeScript interfaces defined for all hook config types
- ✅ Hook actions defined (command, notification, checkpoint, metric, custom)
- ✅ Circuit breaker strategies defined (thrashing, quality regression, timeout)
- ✅ Configuration examples documented
- ✅ Types exported from validation module
- ✅ Enhanced `IterationConfig` with optional hooks field
- ✅ Backward compatible with Phase 1 format
- ✅ Comprehensive documentation created
- ✅ Ready-to-use examples provided
- ✅ Quick reference guide created

## Summary

This implementation provides a complete, well-documented hook configuration schema for the Ralph Wiggum iteration system. The schema supports:

- **Four hook types**: Stop, Pre-Iteration, Post-Iteration, Circuit Breaker
- **Five action types**: Command, Notification, Checkpoint, Metric, Custom
- **Four circuit breaker strategies**: Thrashing, Quality Regression, Timeout, Custom
- **Backward compatibility**: Works with Phase 1 validation rules
- **Extensibility**: Custom validators, circuit breakers, and actions
- **Documentation**: 1500+ lines of documentation and examples

The types are production-ready and can be used immediately by RW-010 for implementing the stop hook system.
