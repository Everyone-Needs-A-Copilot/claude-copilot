# Iteration Safety Guards

## Overview

The iteration safety guards prevent runaway loops in the Ralph Wiggum iteration pattern by implementing multiple defensive mechanisms. These guards detect and prevent:

1. **Max Iterations** - Hard limit on iteration count
2. **Circuit Breaker** - Consecutive validation failures
3. **Quality Regression** - Declining validation scores
4. **Thrashing** - Repeated file modifications without progress

## Guard Functions

### 1. checkMaxIterations

**Purpose:** Enforce hard limit on iteration count.

```typescript
function checkMaxIterations(
  currentIteration: number,
  maxIterations: number
): SafetyCheckResult
```

**Behavior:**
- Returns `allowed: false` when `currentIteration > maxIterations`
- This is the highest priority check (always runs first)

**Example:**
```typescript
const result = checkMaxIterations(6, 5);
// { allowed: false, message: "Iteration 6 exceeds maximum of 5..." }
```

---

### 2. checkCircuitBreaker

**Purpose:** Detect consecutive validation failures and halt iteration.

```typescript
function checkCircuitBreaker(
  iterationHistory: IterationHistoryEntry[],
  threshold: number = 3
): CircuitBreakerResult
```

**Behavior:**
- Counts consecutive failures from the end of history
- Opens circuit breaker when consecutive failures >= threshold
- Resets counter on any successful validation
- Default threshold: 3 consecutive failures

**Example:**
```typescript
const history = [
  { iteration: 1, validationResult: { passed: false } },
  { iteration: 2, validationResult: { passed: false } },
  { iteration: 3, validationResult: { passed: false } }
];

const result = checkCircuitBreaker(history, 3);
// { open: true, consecutiveFailures: 3, message: "Circuit breaker OPEN..." }
```

---

### 3. checkQualityRegression

**Purpose:** Detect declining validation quality over recent iterations.

```typescript
function checkQualityRegression(
  iterationHistory: IterationHistoryEntry[]
): QualityRegressionResult
```

**Behavior:**
- Analyzes last 3 iterations for declining pass rates
- Triggers if validation scores decrease 3 consecutive times
- Uses validation pass/fail as quality metric
- Requires minimum 3 iterations to detect

**Detection Logic:**
```
Iteration 1: passed = true  (score: 1)
Iteration 2: passed = false (score: 0) ← decline
Iteration 3: passed = false (score: 0) ← decline
Iteration 4: passed = false (score: 0) ← decline

Result: regression = true (3 consecutive declines)
```

**Example:**
```typescript
const history = [
  { iteration: 1, validationResult: { passed: true } },
  { iteration: 2, validationResult: { passed: false } },
  { iteration: 3, validationResult: { passed: false } },
  { iteration: 4, validationResult: { passed: false } }
];

const result = checkQualityRegression(history);
// { regression: true, consecutiveDeclines: 2, message: "Quality regression detected..." }
```

---

### 4. checkThrashing

**Purpose:** Detect when same files are modified repeatedly without progress.

```typescript
function checkThrashing(
  iterationHistory: IterationHistoryEntry[],
  threshold: number = 5
): ThrashingResult
```

**Behavior:**
- Extracts file paths from validation flag messages
- Counts how many times each file appears
- Triggers if any file appears >= threshold times
- Default threshold: 5 modifications

**File Path Extraction:**
- Looks for pattern: `file: /path/to/file` in validation messages
- Case-insensitive matching
- Handles multiple files per iteration

**Example:**
```typescript
const history = [
  {
    iteration: 1,
    validationResult: {
      flags: [{ message: 'Error in file: /src/api.ts' }]
    }
  },
  // ... same file appears 4 more times ...
];

const result = checkThrashing(history, 5);
// { thrashing: true, affectedFiles: ['/src/api.ts'], message: "Thrashing detected..." }
```

---

### 5. runSafetyChecks (Combined)

**Purpose:** Run all safety checks in priority order and return first failure.

```typescript
function runSafetyChecks(
  iterationNumber: number,
  config: IterationConfig,
  history: IterationHistoryEntry[]
): CombinedSafetyResult
```

**Check Order (by priority):**
1. Max iterations (hard stop)
2. Circuit breaker (consecutive failures)
3. Quality regression (declining scores)
4. Thrashing (repeated modifications)

**Returns:**
```typescript
{
  canContinue: boolean;
  blockedBy?: 'max_iterations' | 'circuit_breaker' | 'quality_regression' | 'thrashing';
  message?: string;
}
```

**Example:**
```typescript
const config = {
  maxIterations: 10,
  completionPromises: ['All tests pass'],
  circuitBreakerThreshold: 3
};

const result = runSafetyChecks(11, config, history);
// { canContinue: false, blockedBy: 'max_iterations', message: "..." }
```

---

## Integration with Iteration Tools

### In `iteration_next` (Future Phase)

```typescript
import { runSafetyChecks } from './iteration-guards.js';

// Before executing next iteration
const safetyCheck = runSafetyChecks(
  checkpoint.iteration_number + 1,
  config,
  iterationHistory
);

if (!safetyCheck.canContinue) {
  // Log safety guard trigger
  console.error(`Safety guard triggered: ${safetyCheck.blockedBy}`);
  console.error(safetyCheck.message);

  // Update task status to blocked
  db.updateTask({
    id: taskId,
    status: 'blocked',
    blockedReason: `Iteration safety guard: ${safetyCheck.blockedBy}`
  });

  // Store final checkpoint with error state
  db.insertCheckpoint({
    // ... checkpoint data ...
    trigger: 'error',
    agent_context: JSON.stringify({
      safetyGuardTriggered: safetyCheck.blockedBy,
      message: safetyCheck.message
    })
  });

  return {
    error: safetyCheck.message,
    blockedBy: safetyCheck.blockedBy
  };
}

// Safety checks passed - proceed with iteration
```

---

## Configuration

Safety guards use configuration from `IterationConfig`:

```typescript
interface IterationConfig {
  maxIterations: number;               // Hard limit (required)
  completionPromises: string[];        // Not used by guards
  validationRules?: Array<...>;        // Not used by guards
  circuitBreakerThreshold?: number;    // Default: 3
}
```

**Defaults:**
- `circuitBreakerThreshold`: 3 consecutive failures
- `thrashingThreshold`: 5 modifications (function parameter)
- `qualityRegressionWindow`: 3 iterations (internal constant)

---

## Logging

Guards generate descriptive messages for each trigger:

### Max Iterations
```
Iteration 11 exceeds maximum of 10. Circuit breaker triggered.
```

### Circuit Breaker
```
Circuit breaker OPEN: 3 consecutive validation failures (threshold: 3). Manual intervention required.
```

### Quality Regression
```
Quality regression detected: Validation scores declined 2 consecutive times. Consider changing approach.
```

### Thrashing
```
Thrashing detected: 1 file(s) modified 5+ times without progress: /src/api.ts
```

---

## Testing

Run tests with:
```bash
cd mcp-servers/task-copilot
npm run build
node dist/tools/iteration-guards.test.js
```

Test coverage:
- ✅ Max iterations (within limit, at limit, exceeds)
- ✅ Quality regression (insufficient data, no regression, regression detected, reset)
- ✅ Thrashing (insufficient iterations, different files, same file, custom threshold)
- ✅ Circuit breaker (no history, all passing, consecutive failures, streak broken)
- ✅ Combined checks (all pass, priority order, each block type)

---

## Future Enhancements

1. **File Thrashing Resolution Hints**
   - Analyze which files are thrashing
   - Suggest alternative approaches
   - Recommend architectural changes

2. **Adaptive Thresholds**
   - Adjust thresholds based on task complexity
   - Learn from historical performance
   - Context-aware circuit breaker

3. **Recovery Strategies**
   - Auto-suggest checkpoint rollback points
   - Provide remediation steps per guard type
   - Integration with agent routing for expert help

4. **Metrics & Analytics**
   - Track which guards trigger most often
   - Measure time saved by early termination
   - Identify patterns in blocked iterations

---

## References

- Parent Task: TASK-RW-014
- Related: `iteration.ts` (Phase 1: iteration_start)
- Next: `iteration_next.ts` (Phase 3: uses these guards)
