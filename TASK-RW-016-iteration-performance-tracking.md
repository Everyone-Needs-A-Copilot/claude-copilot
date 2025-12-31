# TASK-RW-016: Iteration Performance Tracking - COMPLETE

**Task ID:** TASK-aca04811-62bf-492b-bb11-67fd57fcfa4f
**Status:** COMPLETED
**Completed:** 2025-12-30

---

## Summary

Extended the existing agent performance tracking system with iteration-specific metrics. All requirements have been implemented and verified.

---

## Implementation Overview

### 1. Database Schema (MIGRATION_V4)

**Location:** `mcp-servers/task-copilot/src/database.ts` (lines 148-159)

Added iteration tracking columns to the `checkpoints` table:

```sql
ALTER TABLE checkpoints ADD COLUMN iteration_config TEXT DEFAULT NULL;
ALTER TABLE checkpoints ADD COLUMN iteration_number INTEGER DEFAULT 0;
ALTER TABLE checkpoints ADD COLUMN iteration_history TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN completion_promises TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN validation_state TEXT DEFAULT NULL;

CREATE INDEX idx_checkpoints_iteration ON checkpoints(task_id, iteration_number DESC);
```

**Key Fields:**
- `iteration_config`: Stores IterationConfig as JSON (maxIterations, completionPromises, validationRules, circuitBreakerThreshold)
- `iteration_number`: Current iteration count (starts at 1)
- `iteration_history`: Array of IterationHistoryEntry objects tracking validation results per iteration
- `completion_promises`: Array of strings defining completion criteria
- `validation_state`: Latest ValidationState as JSON

---

### 2. Database Methods for Iteration Metrics

**Location:** `mcp-servers/task-copilot/src/database.ts` (lines 771-855)

**`getIterationCheckpoints(options)`** - Lines 778-804
- Retrieves all iteration checkpoints for performance analysis
- Filters by agentId and sinceDays
- Joins with tasks table to filter by assigned_agent
- Returns CheckpointRow[] with iteration data

**`getIterationStats(agentId?, sinceDays?)`** - Lines 810-855
- Aggregates iteration statistics for an agent
- Returns:
  - `totalSessions`: Count of distinct iteration checkpoints
  - `completedSessions`: Tasks with status='completed'
  - `totalIterations`: Sum of all iteration_number values
  - `avgIterationsPerSession`: Average iterations per session

**`updateCheckpointIteration(id, iterationNumber, iterationHistory, validationState)`** - Lines 751-764
- Updates iteration state during iteration_next and iteration_validate
- Increments iteration_number
- Appends to iteration_history
- Updates validation_state

---

### 3. Performance Tracking with Iteration Metrics

**Location:** `mcp-servers/task-copilot/src/tools/performance.ts`

**`calculateIterationMetrics(db, agentId, sinceDays?)`** - Lines 190-358

Returns `IterationMetrics`:

```typescript
{
  averageIterationsToCompletion: number,
  successRateByIterationCount: Record<number, number>,  // Success rate at each iteration count
  safetyGuardTriggers: {
    maxIterations: number,       // Count of sessions hitting max iterations
    circuitBreaker: number,       // Count of consecutive failure patterns
    qualityRegression: number,   // Count of pass→fail patterns
    thrashing: number            // Count of alternating pass/fail patterns
  },
  iterationCompletionRate: number,
  totalIterationSessions: number,
  totalIterationsRun: number,
  averageDurationPerIteration: number | null  // Milliseconds between iterations
}
```

**Key Logic:**

1. **Safety Guard Detection** (lines 257-320):
   - Parses iteration_config and iteration_history from checkpoints
   - Detects maxIterations trigger by comparing iteration_number >= config.maxIterations
   - Detects circuit breaker by counting consecutive failures in history
   - Detects quality regression when earlier iterations passed but later ones failed
   - Detects thrashing when >50% of transitions alternate between pass/fail

2. **Duration Calculation** (lines 322-355):
   - Groups checkpoints by task_id
   - Sorts by iteration_number
   - Calculates time difference between consecutive checkpoints
   - Filters reasonable durations (1 second to 1 hour)
   - Returns average in milliseconds

**Integration with `agentPerformanceGet`** - Lines 46-50:
```typescript
const iterationMetrics = calculateIterationMetrics(db, agentId, input.sinceDays);
if (iterationMetrics.totalIterationSessions > 0) {
  agentResult.iterationMetrics = iterationMetrics;
}
```

---

### 4. Type Definitions

**Location:** `mcp-servers/task-copilot/src/types.ts` (lines 293-306, 335-396)

**`IterationMetrics`** - Lines 293-306:
- Defines the structure returned by calculateIterationMetrics
- Included in AgentPerformanceResult as optional field

**`IterationConfig`** - Lines 338-346:
- Configuration stored in checkpoint.iteration_config
- Defines validation rules, max iterations, completion promises

**`IterationHistoryEntry`** - Lines 348-360:
- Single entry in iteration_history array
- Tracks iteration number, timestamp, validation result, checkpoint ID

**`ValidationState`** - Lines 362-370:
- Current validation state stored in checkpoint.validation_state
- Tracks last run time, pass/fail status, individual rule results

**`CheckpointRow`** - Lines 372-396:
- Database row type with iteration fields added in lines 390-395

---

### 5. Iteration Tools (Phase 1 & 2)

**Location:** `mcp-servers/task-copilot/src/tools/iteration.ts`

Tools available via MCP:
- `iteration_start`: Initialize iteration loop (creates checkpoint with iteration_number=1)
- `iteration_validate`: Run validation rules and detect completion signals
- `iteration_next`: Advance to next iteration (increments iteration_number, updates history)
- `iteration_complete`: Mark iteration as complete (updates task status)

These tools automatically create checkpoints with iteration data that feeds into performance tracking.

---

## Verification

### Test Coverage

**Location:** `mcp-servers/task-copilot/src/tools/performance.test.ts`

The test creates 3 iteration sessions:
1. **Task 1**: Completes in 2 iterations (1 failure, then success)
2. **Task 2**: Completes in 4 iterations with quality regression (fail, pass, fail, pass)
3. **Task 3**: Hits max iterations (3) with circuit breaker pattern

**Validated Metrics:**
- ✓ Total sessions = 3
- ✓ Completed sessions = 2 (Task 3 incomplete)
- ✓ Quality regression detected (Task 2)
- ✓ Max iterations trigger detected (Task 3)
- ✓ Circuit breaker data collected
- ✓ Average iterations calculated
- ✓ Duration per iteration tracked

---

## Acceptance Criteria - VERIFIED

### ✅ 1. Iteration count tracked per task
- **Implementation:** `checkpoints.iteration_number` column (INTEGER)
- **Tracking:** Starts at 1, incremented by `iteration_next()`
- **Query:** `getIterationStats()` aggregates total iterations

### ✅ 2. Duration per iteration recorded
- **Implementation:** `calculateIterationMetrics()` lines 322-355
- **Method:** Calculates time difference between consecutive checkpoint.created_at timestamps
- **Output:** `averageDurationPerIteration` in milliseconds (null if insufficient data)

### ✅ 3. Validation results per iteration stored
- **Implementation:** `checkpoints.iteration_history` column (TEXT/JSON)
- **Structure:** Array of IterationHistoryEntry with validationResult per iteration
- **Storage:** Updated by `iteration_next()` and `iteration_validate()`

### ✅ 4. Can query iteration performance via agent_performance_get
- **Tool:** `agent_performance_get` returns `AgentPerformanceResult` with optional `iterationMetrics` field
- **Data:** Includes all metrics defined in IterationMetrics type
- **Filtering:** Supports agentId, workProductType, complexity, sinceDays

---

## Files Modified

### Core Implementation
1. **`mcp-servers/task-copilot/src/database.ts`**
   - Added MIGRATION_V4_SQL with iteration columns
   - Added `getIterationCheckpoints()` method
   - Added `getIterationStats()` method
   - Added `updateCheckpointIteration()` method
   - Modified `listCheckpoints()` to support iteration filters

2. **`mcp-servers/task-copilot/src/tools/performance.ts`**
   - Added `calculateIterationMetrics()` function
   - Integrated iteration metrics into `agentPerformanceGet()`
   - Added safety guard detection logic
   - Added duration calculation logic

3. **`mcp-servers/task-copilot/src/types.ts`**
   - Added `IterationMetrics` interface
   - Added `IterationConfig` interface
   - Added `IterationHistoryEntry` interface
   - Added `ValidationState` interface
   - Extended `CheckpointRow` with iteration fields
   - Extended `AgentPerformanceResult` with optional iterationMetrics

### Testing
4. **`mcp-servers/task-copilot/src/tools/performance.test.ts`**
   - Comprehensive integration test covering all metrics
   - Tests 3 scenarios: normal completion, regression, max iterations
   - Validates all iteration metrics are correctly calculated

---

## Usage Example

```typescript
// Query iteration performance for agent "me"
const performance = agentPerformanceGet(db, {
  agentId: 'me',
  sinceDays: 30
});

const agent = performance.agents.find(a => a.agentId === 'me');
if (agent?.iterationMetrics) {
  console.log(`Average iterations to completion: ${agent.iterationMetrics.averageIterationsToCompletion}`);
  console.log(`Iteration completion rate: ${agent.iterationMetrics.iterationCompletionRate}`);
  console.log(`Total iteration sessions: ${agent.iterationMetrics.totalIterationSessions}`);
  console.log(`Safety guard triggers:`, agent.iterationMetrics.safetyGuardTriggers);
  console.log(`Avg duration per iteration: ${agent.iterationMetrics.averageDurationPerIteration}ms`);
}
```

---

## Design Decisions

### 1. Storage in Checkpoints Table
**Rationale:** Iteration data is stored in the existing `checkpoints` table rather than a new table because:
- Iterations are inherently checkpoint-based (each iteration creates/updates a checkpoint)
- Avoids data duplication and complex joins
- Simplifies queries (single table scan)
- Maintains atomicity of iteration state with checkpoint state

### 2. JSON Storage for History and Config
**Rationale:** `iteration_history` and `iteration_config` are stored as JSON TEXT:
- Flexible schema for validation rules and results
- Efficient for append-only history (no need for separate rows)
- Simplifies checkpoint creation (single insert)
- SQLite JSON functions available if needed for future queries

### 3. Performance Metrics Calculation on Query
**Rationale:** Metrics are calculated at query time rather than pre-aggregated:
- Simpler schema (no denormalization)
- Always accurate (no cache invalidation)
- Flexible filtering (sinceDays, agentId)
- Acceptable performance with indexed queries

### 4. Duration Filtering (1s to 1h)
**Rationale:** Only durations between 1 second and 1 hour are included in averages:
- Excludes test data with instant iterations
- Excludes abandoned sessions (days/weeks between iterations)
- Focuses on realistic agent work patterns

### 5. Safety Guard Detection Patterns
**Rationale:** Four distinct patterns tracked:
- `maxIterations`: Hard limit enforcement
- `circuitBreaker`: Consecutive failures (default: 3)
- `qualityRegression`: Success followed by failure (indicates instability)
- `thrashing`: >50% alternating pass/fail (indicates oscillation)

---

## Next Steps

### Phase 3 Considerations (Future Work)
If deeper iteration analytics are needed:
1. Add visualization tools for iteration trends
2. Create alerts for high thrashing rates
3. Add machine learning to predict iteration count from task complexity
4. Export iteration data for external analytics tools

### Potential Optimizations
1. Add materialized views for frequently queried metrics
2. Pre-calculate cumulative metrics during iteration_complete
3. Add caching layer for expensive metric calculations
4. Add periodic aggregation job for historical data

---

## Conclusion

All acceptance criteria met. The iteration performance tracking system is fully functional and integrated with the existing agent performance tracking infrastructure. The implementation leverages the existing checkpoint system, providing comprehensive metrics without significant schema changes.

**Status:** COMPLETE ✅
