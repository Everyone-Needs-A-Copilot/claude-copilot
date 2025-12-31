# Migration V4: Ralph Wiggum Iteration Support

**Version:** 4
**Date:** 2025-12-30
**Phase:** Phase 1 - Schema Foundation
**Status:** Complete

## Overview

This migration adds database schema support for Ralph Wiggum's iterative execution loop pattern to the Task Copilot checkpoints table. This is Phase 1 of the integration, establishing the data structures needed for future iteration functionality.

## Schema Changes

### New Columns Added to `checkpoints` Table

| Column Name | Type | Default | Nullable | Description |
|------------|------|---------|----------|-------------|
| `iteration_config` | TEXT | NULL | Yes | JSON configuration for iteration behavior |
| `iteration_number` | INTEGER | 0 | No | Current iteration count (0 = not iterating) |
| `iteration_history` | TEXT | '[]' | No | JSON array of iteration attempts and results |
| `completion_promises` | TEXT | '[]' | No | JSON array of detected completion signals |
| `validation_state` | TEXT | NULL | Yes | JSON object with current validation status |

### Data Structures

#### iteration_config (JSON)
```json
{
  "maxIterations": 15,
  "completionPromises": ["<promise>COMPLETE</promise>"],
  "validationRules": [
    {
      "type": "work_product_validation",
      "config": { "validateStructure": true }
    }
  ],
  "circuitBreakerThreshold": 3
}
```

#### iteration_history (JSON Array)
```json
[
  {
    "iteration": 1,
    "timestamp": "2025-12-30T12:00:00.000Z",
    "validationResult": {
      "passed": false,
      "flags": [
        {
          "ruleId": "wp_size_limit",
          "message": "Content exceeds size limit",
          "severity": "reject"
        }
      ]
    },
    "checkpointId": "CP-abc123"
  }
]
```

#### validation_state (JSON)
```json
{
  "lastRun": "2025-12-30T12:00:00.000Z",
  "passed": true,
  "results": [
    {
      "ruleId": "wp_size_limit",
      "passed": true,
      "message": "Size within limits"
    }
  ]
}
```

## TypeScript Types

### New Type Definitions

Added to `src/types.ts`:

```typescript
export interface IterationConfig {
  maxIterations: number;
  completionPromises: string[];
  validationRules?: Array<{
    type: string;
    config: Record<string, unknown>;
  }>;
  circuitBreakerThreshold?: number;
}

export interface IterationHistoryEntry {
  iteration: number;
  timestamp: string;
  validationResult: {
    passed: boolean;
    flags: Array<{
      ruleId: string;
      message: string;
      severity: string;
    }>;
  };
  checkpointId: string;
}

export interface ValidationState {
  lastRun: string;
  passed: boolean;
  results: Array<{
    ruleId: string;
    passed: boolean;
    message?: string;
  }>;
}
```

### Updated CheckpointRow

```typescript
export interface CheckpointRow {
  // ... existing fields ...

  // Ralph Wiggum Iteration Support (v4)
  iteration_config: string | null;
  iteration_number: number;
  iteration_history: string;
  completion_promises: string;
  validation_state: string | null;
}
```

## Migration Execution

### Automatic Migration

The migration runs automatically when the database client initializes:

1. Checks current version from `migrations` table
2. If version < 4, executes `MIGRATION_V4_SQL`
3. Records migration as complete with timestamp

### SQL Executed

```sql
ALTER TABLE checkpoints ADD COLUMN iteration_config TEXT DEFAULT NULL;
ALTER TABLE checkpoints ADD COLUMN iteration_number INTEGER DEFAULT 0;
ALTER TABLE checkpoints ADD COLUMN iteration_history TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN completion_promises TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN validation_state TEXT DEFAULT NULL;
```

## Backward Compatibility

### Existing Checkpoints
- All existing checkpoints receive default values:
  - `iteration_config`: `NULL`
  - `iteration_number`: `0`
  - `iteration_history`: `[]`
  - `completion_promises`: `[]`
  - `validation_state`: `NULL`

### New Checkpoints
- The `checkpointCreate` function in `src/tools/checkpoint.ts` populates defaults
- No breaking changes to existing checkpoint API
- Iteration fields are optional and ignored unless explicitly used

## Files Modified

1. **src/database.ts**
   - Added `MIGRATION_V4_SQL` constant
   - Updated `CURRENT_VERSION` to 4
   - Added migration execution in `migrate()` method
   - Updated `insertCheckpoint()` to include new fields

2. **src/types.ts**
   - Added `IterationConfig` interface
   - Added `IterationHistoryEntry` interface
   - Added `ValidationState` interface
   - Updated `CheckpointRow` interface with new fields

3. **src/tools/checkpoint.ts**
   - Updated `checkpointCreate()` to provide default values for new fields

4. **MIGRATION-V4.md** (this file)
   - Documentation of migration

## Testing Checklist

- [ ] Migration applies cleanly on new database
- [ ] Migration applies cleanly on existing database with checkpoints
- [ ] Existing checkpoints load without errors
- [ ] New checkpoints can be created with defaults
- [ ] TypeScript compilation succeeds
- [ ] All checkpoint tools continue to function
- [ ] No breaking changes to existing checkpoint APIs

## Next Steps (Future Phases)

### Phase 2: Iteration API
- Add checkpoint tools to set/update iteration config
- Add checkpoint tools to record iteration attempts
- Add completion promise detection logic

### Phase 3: Integration
- Integrate with Ralph Wiggum execution loop
- Connect validation system to iteration history
- Implement circuit breaker logic

### Phase 4: Ralph Wiggum Agent
- Create Ralph Wiggum agent that uses iteration checkpoints
- Implement auto-iteration with validation feedback
- Add performance tracking for iterations

## Notes

- All JSON fields use TEXT type with JSON string storage (SQLite standard practice)
- Default values ensure zero impact on existing functionality
- Schema is designed to support full Ralph Wiggum integration without further migrations
- Iteration number 0 indicates checkpoint is not part of an iteration loop
