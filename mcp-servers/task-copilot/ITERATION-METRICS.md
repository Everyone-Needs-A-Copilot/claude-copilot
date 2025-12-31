# Iteration Metrics - Performance Tracking Extension

## Overview

This document describes the iteration metrics extension to the agent performance tracking system, integrated as part of Ralph Wiggum Phase 2.

## Purpose

Track and analyze iteration-specific performance metrics to provide actionable insights into:
- How many iterations agents typically need to complete tasks
- Success rates at different iteration counts
- Safety guard trigger frequency and patterns
- Average time per iteration
- Common failure patterns

## Architecture

### Database Extensions

**Existing Schema**: The checkpoint system already tracks iteration data via Migration v4:
- `iteration_config`: JSON-serialized IterationConfig
- `iteration_number`: Current iteration number (0-N)
- `iteration_history`: JSON array of IterationHistoryEntry
- `completion_promises`: JSON array of completion criteria
- `validation_state`: JSON-serialized ValidationState

**New Query Methods** (added to `DatabaseClient`):
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

### Type Definitions

**IterationMetrics Interface** (added to `types.ts`):
```typescript
interface IterationMetrics {
  // Average number of iterations needed to complete tasks
  averageIterationsToCompletion: number;

  // Success rate broken down by iteration count
  // e.g., { 1: 0.8, 2: 0.6, 3: 0.4 }
  successRateByIterationCount: Record<number, number>;

  // Safety guard trigger counts
  safetyGuardTriggers: {
    maxIterations: number;        // Hit max iteration limit
    circuitBreaker: number;        // Consecutive failures threshold
    qualityRegression: number;     // Success then degradation
    thrashing: number;             // Alternating pass/fail
  };

  // Percentage of iteration sessions that complete successfully
  iterationCompletionRate: number;

  // Total number of iteration sessions started
  totalIterationSessions: number;

  // Total number of individual iterations run
  totalIterationsRun: number;

  // Average milliseconds per iteration (null if no timing data)
  averageDurationPerIteration: number | null;
}
```

**Updated AgentPerformanceResult**:
```typescript
interface AgentPerformanceResult {
  agentId: string;
  metrics: AgentMetrics;
  byType: Record<string, { total: number; successRate: number }>;
  byComplexity: Record<string, { total: number; successRate: number }>;
  recentTrend: 'improving' | 'stable' | 'declining' | 'insufficient_data';
  iterationMetrics?: IterationMetrics;  // NEW: Only present if agent has iteration data
}
```

### Performance Tool Updates

**Function**: `calculateIterationMetrics(db, agentId, sinceDays?)`

**Location**: `src/tools/performance.ts`

**Logic**:
1. Query all iteration checkpoints for the agent
2. Calculate aggregate statistics:
   - Average iterations to completion
   - Success rate by iteration count
   - Iteration completion rate
3. Analyze safety guard triggers:
   - **maxIterations**: Count checkpoints where `iteration_number >= maxIterations`
   - **circuitBreaker**: Analyze iteration history for consecutive failures >= threshold
   - **qualityRegression**: Detect success followed by failure in later iterations
   - **thrashing**: Detect alternating pass/fail patterns (>50% transitions)
4. Calculate average iteration duration from checkpoint timestamps
5. Return comprehensive metrics

**Integration**:
- Called from `agentPerformanceGet()` for each agent
- Only adds `iterationMetrics` if agent has iteration sessions (`totalIterationSessions > 0`)

## Usage

### Getting Agent Performance with Iteration Metrics

```typescript
// Get performance for all agents (includes iteration metrics if available)
const performance = await agent_performance_get({});

// Get performance for specific agent
const mePerformance = await agent_performance_get({
  agentId: 'me'
});

// Filter by time period
const recentPerformance = await agent_performance_get({
  agentId: 'qa',
  sinceDays: 30
});
```

### Example Output

```json
{
  "agents": [
    {
      "agentId": "me",
      "metrics": {
        "total": 45,
        "success": 38,
        "failure": 5,
        "blocked": 2,
        "reassigned": 0,
        "successRate": 0.84,
        "completionRate": 0.84
      },
      "byType": { ... },
      "byComplexity": { ... },
      "recentTrend": "improving",
      "iterationMetrics": {
        "averageIterationsToCompletion": 2.3,
        "successRateByIterationCount": {
          "1": 0.75,
          "2": 0.85,
          "3": 0.60,
          "4": 0.40
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
  ],
  "summary": {
    "totalRecords": 45,
    "periodStart": "2025-01-01T00:00:00Z",
    "periodEnd": "2025-12-30T12:00:00Z"
  }
}
```

## Metrics Interpretation

### averageIterationsToCompletion
- **Lower is better** (indicates efficient completion)
- Target: < 3 iterations
- Warning: > 5 iterations may indicate task complexity mismatch

### successRateByIterationCount
- Shows whether additional iterations improve outcomes
- **Expected pattern**: Higher iterations = lower success (diminishing returns)
- **Red flag**: Iteration 1 success < 50% suggests poor initial prompting

### safetyGuardTriggers

**maxIterations**:
- How often the iteration limit was hit
- High count = tasks may need higher limits OR are too complex

**circuitBreaker**:
- Consecutive failures triggering automatic stop
- High count = systematic validation issues

**qualityRegression**:
- Success followed by failure (going backwards)
- Indicates instability or incomplete validation

**thrashing**:
- Alternating pass/fail pattern
- Suggests conflicting requirements or unstable validation

### iterationCompletionRate
- Percentage of started iterations that complete successfully
- Target: > 0.75
- Warning: < 0.50 suggests iteration pattern may not be appropriate

### averageDurationPerIteration
- Milliseconds per iteration cycle
- Useful for estimating task completion time
- High variance may indicate blocking issues

## Safety Guard Detection Algorithms

### Circuit Breaker Detection
```typescript
// Track consecutive failures in iteration history
let consecutiveFailures = 0;
let maxConsecutiveFailures = 0;

for (const entry of history) {
  if (!entry.validationResult?.passed) {
    consecutiveFailures++;
    maxConsecutiveFailures = Math.max(maxConsecutiveFailures, consecutiveFailures);
  } else {
    consecutiveFailures = 0;
  }
}

if (maxConsecutiveFailures >= circuitBreakerThreshold) {
  metrics.safetyGuardTriggers.circuitBreaker++;
}
```

### Quality Regression Detection
```typescript
// Check for success followed by failure
const hadSuccess = history.some(e => e.validationResult?.passed);
const latestFailed = history[history.length - 1]?.validationResult?.passed === false;

if (hadSuccess && latestFailed && history.length >= 3) {
  metrics.safetyGuardTriggers.qualityRegression++;
}
```

### Thrashing Detection
```typescript
// Count alternations in pass/fail pattern
let alternations = 0;
for (let i = 1; i < history.length; i++) {
  const prev = history[i - 1].validationResult?.passed;
  const curr = history[i].validationResult?.passed;
  if (prev !== curr) {
    alternations++;
  }
}

// If >50% of transitions are alternations, flag as thrashing
if (alternations / (history.length - 1) > 0.5) {
  metrics.safetyGuardTriggers.thrashing++;
}
```

## Implementation Notes

### Data Sources
- **Checkpoints table**: Primary source (already contains iteration data)
- **Tasks table**: For completion status and agent assignment
- **No new tables required**: Uses existing schema from Migration v4

### Performance Considerations
- Queries filter by `iteration_config IS NOT NULL` to only process iteration checkpoints
- Agent filtering uses indexed `assigned_agent` column on tasks
- Date filtering uses indexed `created_at` column on checkpoints
- JSON parsing only happens for relevant checkpoints

### Backward Compatibility
- `iterationMetrics` is optional on `AgentPerformanceResult`
- Only present if agent has iteration data
- Existing performance queries work unchanged
- New metrics automatically appear as agents adopt iteration pattern

## Future Enhancements

### Potential Additions
1. **Iteration metrics by task type**: Break down by work product type
2. **Iteration metrics by complexity**: Analyze correlation with task complexity
3. **Validation rule effectiveness**: Track which rules catch most issues
4. **Completion promise analysis**: Which promises are most commonly met
5. **Time-based trends**: Track how iteration patterns change over time

### Separate Tool (Optional)
Could add dedicated `iteration_metrics_get` tool for deeper analysis:
```typescript
iteration_metrics_get({
  agentId?: string;
  taskType?: string;
  complexity?: string;
  sinceDays?: number;
  includeHistograms?: boolean;
})
```

## Testing

### Manual Testing Steps
1. Create iteration sessions using `iteration_start`
2. Run multiple iterations with `iteration_next`
3. Complete some iterations, let others hit max iterations
4. Query `agent_performance_get` for the agent
5. Verify `iterationMetrics` appears with correct values

### Expected Behavior
- Agents without iterations: no `iterationMetrics` field
- Agents with iterations: `iterationMetrics` with all fields populated
- Safety guard counters reflect actual iteration patterns
- Success rates match actual completion outcomes

## References

- **PRD**: PRD-RW-001 (Ralph Wiggum Iteration Pattern Integration)
- **Inspiration**: https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum
- **Database Schema**: `database.ts` Migration v4
- **Iteration Tools**: `src/tools/iteration.ts`
- **Performance Tools**: `src/tools/performance.ts`
