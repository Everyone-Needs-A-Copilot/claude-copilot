# Iteration Metrics Implementation Summary

## Overview

Extended agent performance tracking to include iteration-specific metrics for Ralph Wiggum Phase 2 integration.

## Files Modified

### 1. `/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/src/types.ts`
**Changes**:
- Added `IterationMetrics` interface with 7 key metrics
- Extended `AgentPerformanceResult` to include optional `iterationMetrics` field

**New Types**:
```typescript
interface IterationMetrics {
  averageIterationsToCompletion: number;
  successRateByIterationCount: Record<number, number>;
  safetyGuardTriggers: {
    maxIterations: number;
    circuitBreaker: number;
    qualityRegression: number;
    thrashing: number;
  };
  iterationCompletionRate: number;
  totalIterationSessions: number;
  totalIterationsRun: number;
  averageDurationPerIteration: number | null;
}
```

### 2. `/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/src/database.ts`
**Changes**:
- Added `getIterationCheckpoints()` method for querying iteration data
- Added `getIterationStats()` method for aggregate statistics

**New Methods**:
```typescript
getIterationCheckpoints(options: {
  agentId?: string;
  sinceDays?: number;
}): CheckpointRow[]

getIterationStats(agentId?: string, sinceDays?: number): {
  totalSessions: number;
  completedSessions: number;
  totalIterations: number;
  avgIterationsPerSession: number;
}
```

### 3. `/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/src/tools/performance.ts`
**Changes**:
- Updated imports to include iteration-related types
- Modified `agentPerformanceGet()` to call `calculateIterationMetrics()`
- Added `calculateIterationMetrics()` function with full metric calculation logic

**New Function**:
```typescript
function calculateIterationMetrics(
  db: DatabaseClient,
  agentId: string,
  sinceDays?: number
): IterationMetrics
```

**Logic Implemented**:
1. Query iteration checkpoints filtered by agent and time period
2. Calculate aggregate statistics (avg iterations, completion rate)
3. Analyze success rate by iteration count
4. Detect safety guard triggers:
   - **maxIterations**: Count when iteration_number >= maxIterations
   - **circuitBreaker**: Detect consecutive failures >= threshold
   - **qualityRegression**: Find success followed by failure patterns
   - **thrashing**: Identify alternating pass/fail patterns (>50% alternations)
5. Calculate average iteration duration from checkpoint timestamps
6. Return comprehensive metrics

## Files Created

### 1. `/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/ITERATION-METRICS.md`
**Purpose**: Comprehensive documentation
**Contents**:
- Architecture overview
- Type definitions
- Usage examples
- Metrics interpretation guide
- Safety guard detection algorithms
- Implementation notes
- Future enhancements

### 2. `/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/src/tools/performance.test.ts`
**Purpose**: Integration test for iteration metrics
**Contents**:
- Creates test database with iteration sessions
- Simulates various iteration patterns:
  - Quick completion (2 iterations)
  - Regression pattern (4 iterations)
  - Max iterations hit (circuit breaker)
- Validates metric calculations
- Provides usage example

## Key Features

### 1. Zero Schema Changes Required
- Uses existing `checkpoints` table from Migration v4
- All iteration data already stored in:
  - `iteration_config`
  - `iteration_number`
  - `iteration_history`
  - `completion_promises`
  - `validation_state`

### 2. Backward Compatible
- `iterationMetrics` is optional on `AgentPerformanceResult`
- Only appears when agent has iteration data
- Existing performance queries work unchanged
- No breaking changes to API

### 3. Automatic Integration
- No new tools required
- Metrics automatically appear in `agent_performance_get` output
- Filters by agent, time period, work product type, complexity (all existing filters)

### 4. Actionable Insights
Provides answers to:
- "How many iterations do agents typically need?"
- "Do additional iterations improve success rate?"
- "Which safety guards trigger most often?"
- "Are iterations getting faster over time?"
- "Which agents benefit most from iteration patterns?"

## Safety Guard Detection

### Max Iterations
```typescript
if (checkpoint.iteration_number >= config.maxIterations) {
  metrics.safetyGuardTriggers.maxIterations++;
}
```

### Circuit Breaker
Tracks consecutive validation failures:
```typescript
let consecutiveFailures = 0;
for (const entry of history) {
  if (!entry.validationResult?.passed) {
    consecutiveFailures++;
    if (consecutiveFailures >= threshold) {
      metrics.safetyGuardTriggers.circuitBreaker++;
      break;
    }
  } else {
    consecutiveFailures = 0;
  }
}
```

### Quality Regression
Detects backward progress:
```typescript
const hadSuccess = history.some(e => e.validationResult?.passed);
const latestFailed = !history[history.length - 1]?.validationResult?.passed;
if (hadSuccess && latestFailed && history.length >= 3) {
  metrics.safetyGuardTriggers.qualityRegression++;
}
```

### Thrashing
Identifies unstable iteration patterns:
```typescript
let alternations = 0;
for (let i = 1; i < history.length; i++) {
  if (history[i-1].passed !== history[i].passed) {
    alternations++;
  }
}
if (alternations / (history.length - 1) > 0.5) {
  metrics.safetyGuardTriggers.thrashing++;
}
```

## Usage Example

### Query Performance with Iteration Metrics
```typescript
const performance = await agent_performance_get({
  agentId: 'me',
  sinceDays: 30
});

// Check if agent has iteration metrics
if (performance.agents[0].iterationMetrics) {
  const metrics = performance.agents[0].iterationMetrics;

  console.log(`Average iterations: ${metrics.averageIterationsToCompletion}`);
  console.log(`Completion rate: ${metrics.iterationCompletionRate * 100}%`);
  console.log(`Safety guards triggered: ${
    metrics.safetyGuardTriggers.maxIterations +
    metrics.safetyGuardTriggers.circuitBreaker +
    metrics.safetyGuardTriggers.qualityRegression +
    metrics.safetyGuardTriggers.thrashing
  }`);
}
```

### Sample Output
```json
{
  "agents": [
    {
      "agentId": "me",
      "metrics": {
        "total": 45,
        "success": 38,
        "successRate": 0.84
      },
      "iterationMetrics": {
        "averageIterationsToCompletion": 2.3,
        "successRateByIterationCount": {
          "1": 0.75,
          "2": 0.85,
          "3": 0.60
        },
        "safetyGuardTriggers": {
          "maxIterations": 2,
          "circuitBreaker": 1,
          "qualityRegression": 3,
          "thrashing": 1
        },
        "iterationCompletionRate": 0.82,
        "totalIterationSessions": 12,
        "totalIterationsRun": 28,
        "averageDurationPerIteration": 45000
      }
    }
  ]
}
```

## Testing

### Manual Testing
1. Build the server: `npm run build`
2. Create iteration sessions using `iteration_start`
3. Run iterations with `iteration_next`
4. Complete or let them hit max iterations
5. Query `agent_performance_get` to see metrics

### Automated Testing
```bash
cd mcp-servers/task-copilot
npm run build
node dist/tools/performance.test.js
```

Expected output:
```
✓ Total sessions: 3 == 3
✓ Completed sessions: 2 == 2
✓ Has quality regression: true == true
✓ Has max iterations trigger: true == true
✓ Has circuit breaker data: true == true

✓ All tests PASSED
```

## Performance Considerations

### Query Efficiency
- Uses indexed columns: `assigned_agent`, `created_at`
- Filters early with `iteration_config IS NOT NULL`
- JSON parsing only on relevant checkpoints
- No N+1 queries (uses batch queries with joins)

### Memory Usage
- Processes checkpoints in batches
- Groups data by task to avoid redundant processing
- Only calculates metrics for agents with iteration data

### Scalability
- Database queries are O(n) where n = matching checkpoints
- Safety guard detection is O(m) where m = history entries per checkpoint
- Scales well with thousands of checkpoints

## Future Enhancements

### Potential Additions
1. **Breakdown by task type**: `iterationMetricsByType`
2. **Breakdown by complexity**: `iterationMetricsByComplexity`
3. **Time-based trends**: Track metric changes over time
4. **Validation rule effectiveness**: Which rules catch most issues
5. **Completion promise analysis**: Which promises are most common

### Dedicated Tool
Could add `iteration_metrics_get` for deeper analysis:
```typescript
iteration_metrics_get({
  agentId?: string;
  taskType?: string;
  complexity?: string;
  sinceDays?: number;
  includeHistograms?: boolean;
  groupBy?: 'agent' | 'taskType' | 'complexity' | 'timeWeek';
})
```

## Dependencies

### Existing
- `@modelcontextprotocol/sdk`: ^1.0.0
- `better-sqlite3`: ^12.5.0
- `typescript`: ^5.4.0

### New
- None (uses existing dependencies)

## Version

- **Task Copilot Version**: 2.0.0
- **Feature**: Iteration Metrics for Performance Tracking
- **Implementation Date**: 2025-12-30
- **Migration**: Uses existing v4 schema (no migration required)

## References

- **PRD**: PRD-RW-001 (Ralph Wiggum Iteration Pattern Integration)
- **Inspiration**: https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum
- **Database Schema**: Migration v4 (MIGRATION_V4_SQL in database.ts)
- **Iteration Tools**: src/tools/iteration.ts
- **Performance Tools**: src/tools/performance.ts
