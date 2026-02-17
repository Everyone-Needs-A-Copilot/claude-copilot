# Auto-Checkpoint Hooks

## Overview

The auto-checkpoint system automatically creates recovery points during iteration loops without requiring manual `checkpoint_create()` calls from agents. This simplifies agent prompts while maintaining robust recovery capabilities.

## Motivation

**Before (Manual Checkpointing):**
- Agents had to remember to call `checkpoint_create()` before each iteration
- Inconsistent checkpoint creation across different agents
- Verbose agent prompts with checkpoint management logic
- Easy to forget checkpoint calls, leading to poor recovery

**After (Automatic Checkpointing):**
- Checkpoints automatically created at strategic points in iteration loops
- Consistent behavior across all agents
- Simplified agent prompts focused on task logic
- Guaranteed recovery points for every iteration

## Architecture

### Hook System

The auto-checkpoint system uses internal hooks that trigger at key moments:

```typescript
// src/hooks/auto-checkpoint.ts
export class AutoCheckpointHooks {
  onIterationStart(taskId, iterationNumber)    // When iteration starts
  onIterationFailure(taskId, iterationNumber)  // When validation fails
  onTaskStatusChange(taskId, oldStatus, newStatus)
  onWorkProductStore(taskId, workProductId)
}
```

### Integration Points

1. **iteration_start()** → Triggers `onIterationStart` for iteration 1
2. **iteration_next()** → Triggers `onIterationStart` for subsequent iterations
3. **iteration_validate()** → Triggers `onIterationFailure` if validation fails (optional)

### Configuration

Default configuration in `mcp-servers/task-copilot/src/index.ts`:

```typescript
initializeAutoCheckpointHooks(db, {
  enabled: true,
  triggers: {
    iterationStart: true,      // ✅ Checkpoint at start of each iteration
    iterationFailure: true,     // ✅ Checkpoint after validation failures
    taskStatusChange: false,    // ❌ Too noisy
    workProductStore: false,    // ❌ Work products are checkpoints
  },
});
```

## Benefits

### For Agent Developers

- **Simpler prompts**: Remove checkpoint_create() instructions from iteration loops
- **Consistent behavior**: All agents get checkpoints automatically
- **Less error-prone**: Can't forget to create checkpoints

### For Users

- **Transparent**: Checkpoints work automatically, no manual intervention
- **Better recovery**: Resume from any iteration point
- **Debugging**: Automatic failure checkpoints help diagnose issues

### For System

- **Predictable**: Checkpoints created at consistent points
- **Maintainable**: Hook logic centralized, not scattered across agents
- **Extensible**: Easy to add new checkpoint triggers

## Blocked Stream Compaction

When an iteration signals `<promise>BLOCKED</promise>`, the default stop hook creates a compact checkpoint summary. This keeps stalled streams lighter by storing a short summary instead of full context.

Behavior:
- Summary derived from draft content (preferred) or agent output
- Stored as a checkpoint with a short, token-efficient draft
- Used as a compact recovery anchor when resuming

## Usage

### For Agents

**Iteration loop (simplified):**

```markdown
FOR EACH iteration:
  # Do work (checkpoint created automatically)
  - Read files
  - Make changes
  - Run tests

  # Validate
  result = iteration_validate({ taskId })

  # Handle result
  IF result.completionSignal === 'COMPLETE':
    iteration_complete({ taskId, completionPromise: result.detectedPromise })
    BREAK
  ELSE:
    iteration_next({ taskId })
```

**Manual checkpoint (optional, for non-iteration workflows):**

```typescript
// Before risky operation outside iteration loop
checkpoint_create({
  taskId: 'TASK-123',
  trigger: 'manual',
  executionPhase: 'database_migration',
  agentContext: { migrationScript: 'v2_schema.sql' }
})
```

### For Users

**Resume from checkpoint:**

```typescript
// Resume from latest checkpoint (automatic or manual)
checkpoint_resume({ taskId: 'TASK-123' })

// Resume from specific iteration
checkpoint_resume({
  taskId: 'TASK-123',
  checkpointId: 'IT-1234567890-abc123'
})
```

## Checkpoint Types

| Type | Trigger | Created By | Use Case |
|------|---------|------------|----------|
| Iteration | `auto_iteration` | Auto-hook | TDD loops, build-fix cycles |
| Manual | `manual` | Agent call | Non-iteration recovery points |
| Pause | `manual` | `/pause` command | Context switching |

## Implementation Details

### Hook Lifecycle

```
1. iteration_start(taskId)
   ↓
2. AutoCheckpointHooks.onIterationStart(taskId, 1)
   ↓
3. checkpoint_create({ taskId, trigger: 'auto_iteration', ... })
   ↓
4. Checkpoint stored in database
   ↓
5. Agent continues with iteration
```

### Checkpoint Metadata

Auto-created checkpoints include:

```typescript
{
  trigger: 'auto_iteration',
  executionPhase: 'iteration',
  executionStep: <iteration-number>,
  agentContext: {
    iterationStarted: '2026-01-12T10:30:00Z',
    autoCreated: true
  }
}
```

### Failure Checkpoints

When validation fails (optional trigger):

```typescript
{
  trigger: 'auto_iteration',
  executionPhase: 'iteration_failed',
  executionStep: <iteration-number>,
  agentContext: {
    validationResult: { ... },
    iterationFailed: '2026-01-12T10:35:00Z',
    autoCreated: true
  },
  draftContent: <agent-output>,
  draftType: 'implementation'
}
```

## Backwards Compatibility

### Existing Functionality Preserved

- ✅ Manual `checkpoint_create()` still works
- ✅ `checkpoint_resume()` unchanged
- ✅ All existing checkpoints remain valid
- ✅ Checkpoint cleanup works on both auto and manual checkpoints

### Migration Path

**No breaking changes:**
- Agents can continue using manual checkpoints
- Auto-checkpoints supplement, don't replace manual calls
- Gradual adoption: simplify prompts over time

## Performance

- **Overhead**: <1ms per checkpoint creation
- **Storage**: ~2KB per checkpoint (pruned automatically)
- **Cleanup**: Keeps last 5 checkpoints per task
- **Expiry**: Iteration checkpoints don't expire (cleaned on task completion)

## Configuration

### Environment Variables

```bash
# Disable auto-checkpoints (default: true)
export AUTO_CHECKPOINT_ENABLED=false
```

### Runtime Configuration

Modify `src/index.ts` to change triggers:

```typescript
initializeAutoCheckpointHooks(db, {
  enabled: true,
  triggers: {
    iterationStart: true,
    iterationFailure: false,  // Disable failure checkpoints
    taskStatusChange: true,   // Enable status checkpoints
    workProductStore: false,
  },
});
```

## Testing

### Verify Auto-Checkpoints

```typescript
// Start iteration
iteration_start({
  taskId: 'TASK-123',
  maxIterations: 5,
  completionPromises: ['<promise>COMPLETE</promise>']
})

// Check checkpoint created
const checkpoints = checkpoint_list({ taskId: 'TASK-123' })
// Should have 1 checkpoint with trigger: 'auto_iteration'
```

### Verify Iteration Hook

```typescript
// Progress to next iteration
iteration_next({ iterationId: 'IT-xxx' })

// Check new checkpoint created
const checkpoints = checkpoint_list({ taskId: 'TASK-123' })
// Should have 2 checkpoints, one for each iteration
```

## Troubleshooting

### Checkpoints Not Created

**Symptom:** No automatic checkpoints appearing

**Solution:**
1. Check `AUTO_CHECKPOINT_ENABLED` environment variable
2. Verify hooks initialized: check server startup logs
3. Confirm iteration loop active (not manual workflow)

### Too Many Checkpoints

**Symptom:** Checkpoint count growing rapidly

**Solution:**
1. Automatic pruning keeps last 5 per task
2. Run `checkpoint_cleanup({ taskId: 'TASK-123', keepLatest: 3 })`
3. Disable `iterationFailure` trigger if too noisy

### Can't Resume

**Symptom:** `checkpoint_resume()` returns null

**Solution:**
1. Check checkpoint not expired (iteration checkpoints don't expire)
2. Verify taskId correct
3. List checkpoints: `checkpoint_list({ taskId: 'TASK-123' })`

## Future Enhancements

- [ ] Hook for work product storage (link checkpoints to deliverables)
- [ ] Configurable checkpoint retention policies
- [ ] Checkpoint compression for long-running iterations
- [ ] Checkpoint comparison/diff tools
- [ ] Automatic checkpoint restore on agent crash

## Related Documentation

- [Checkpoint System](../50-features/checkpoint-system.md) - Core checkpoint functionality
- [Iteration Protocol](./.claude/agents/me.md) - Agent iteration guidelines
- [Hooks System](./.claude/hooks/README.md) - Complete hooks documentation
