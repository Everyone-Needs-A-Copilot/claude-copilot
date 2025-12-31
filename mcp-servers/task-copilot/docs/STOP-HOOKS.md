# Stop Hook System - Phase 2

**Status:** Implemented
**Version:** 1.0.0
**Date:** 2025-12-30

## Overview

The Stop Hook System enables completion signal interception in Ralph Wiggum iteration loops, allowing agents to decide whether to complete, continue, or escalate based on execution context.

## Architecture

### Core Concept

Hooks are callback functions registered for a task that evaluate agent context after each iteration and return an action decision:

```
┌─────────────────────────────────────────────────────────┐
│                   Iteration Loop                         │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  iteration_start → iteration_validate → [STOP HOOK]     │
│                                              │            │
│                                              ├─ complete  │
│                                              ├─ continue  │
│                                              └─ escalate  │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose | Storage |
|-----------|---------|---------|
| **Hook Registry** | In-memory map of hooks by ID | Session-scoped |
| **Hook Callback** | Function that evaluates agent context | User-provided |
| **Agent Context** | Execution state passed to hooks | Checkpoint data |
| **Hook Result** | Action decision and optional metadata | Returned to caller |

### Hook Lifecycle

1. **Registration** - Agent registers hook at iteration start
2. **Evaluation** - Hook called during `iteration_validate`
3. **Action** - Hook returns complete/continue/escalate
4. **Cleanup** - Hook cleared at iteration end

## Types

### AgentContext

Context provided to hooks for decision-making:

```typescript
interface AgentContext {
  taskId: string;                      // Task being iterated
  iteration: number;                   // Current iteration (1-based)
  executionPhase: string | null;       // Current phase (e.g., 'testing')
  filesModified: string[];             // Files changed this iteration
  validationResults: ValidationResult[]; // Validation rule results
  completionPromises: CompletionPromise[]; // Detected promises
  agentOutput?: string;                // Agent's output text
  draftContent?: string;               // Draft work product
  draftType?: WorkProductType;         // Draft type
}
```

### StopHookResult

Decision returned by hooks:

```typescript
interface StopHookResult {
  action: 'complete' | 'continue' | 'escalate';
  reason: string;                      // Human-readable explanation
  nextPrompt?: string;                 // Optional prompt for next iteration
  checkpointData?: CheckpointData;     // Optional checkpoint to create
  metadata?: Record<string, unknown>;  // Optional metadata
}
```

### CompletionPromise

Detected completion signals in agent output:

```typescript
interface CompletionPromise {
  type: 'COMPLETE' | 'BLOCKED' | 'ESCALATE';
  detected: boolean;
  content: string;                     // The promise text
  detectedAt?: string;                 // ISO timestamp
}
```

## MCP Tools

### hook_register

Register a stop hook for a task.

**Input:**
```json
{
  "taskId": "TASK-abc123",
  "hookType": "default",  // "default" | "validation" | "promise"
  "metadata": {
    "description": "Optional metadata"
  }
}
```

**Output:**
```json
{
  "hookId": "HOOK-1735567890-xyz",
  "taskId": "TASK-abc123",
  "hookType": "default",
  "enabled": true,
  "metadata": {}
}
```

**Hook Types:**

| Type | Behavior |
|------|----------|
| `default` | Checks promises first, then validation (recommended) |
| `validation` | Only checks validation rules |
| `promise` | Only checks completion promises |

### hook_evaluate

Evaluate registered hooks for an iteration (usually called by `iteration_validate`).

**Input:**
```json
{
  "iterationId": "IT-1735567890-abc",
  "agentOutput": "Implementation complete. <promise>COMPLETE</promise>",
  "filesModified": ["src/auth.ts", "tests/auth.test.ts"],
  "draftContent": "// Implementation code...",
  "draftType": "implementation"
}
```

**Output:**
```json
{
  "hookId": "HOOK-1735567890-xyz",
  "taskId": "TASK-abc123",
  "iteration": 3,
  "action": "complete",
  "reason": "Agent signaled completion via <promise>COMPLETE</promise>",
  "nextPrompt": null,
  "checkpointCreated": false,
  "metadata": {}
}
```

### hook_list

List all registered hooks for a task.

**Input:**
```json
{
  "taskId": "TASK-abc123"
}
```

**Output:**
```json
{
  "taskId": "TASK-abc123",
  "hookCount": 2,
  "hooks": [
    {
      "id": "HOOK-1735567890-xyz",
      "enabled": true,
      "metadata": { "type": "default" }
    },
    {
      "id": "HOOK-1735567891-abc",
      "enabled": false,
      "metadata": { "type": "custom" }
    }
  ]
}
```

### hook_clear

Clear all hooks for a task (should be called when iteration completes).

**Input:**
```json
{
  "taskId": "TASK-abc123"
}
```

**Output:**
```json
{
  "taskId": "TASK-abc123",
  "hooksCleared": 2
}
```

## Preset Hook Factories

### createDefaultHook

Recommended hook that checks promises first, then validation.

**Decision Logic:**

1. **Priority 1:** Check for `<promise>COMPLETE</promise>` → complete
2. **Priority 2:** Check for `<promise>ESCALATE</promise>` → escalate
3. **Priority 3:** Check for `<promise>BLOCKED</promise>` → escalate
4. **Priority 4:** Check validation results:
   - All pass → complete
   - Some fail → continue with feedback
5. **Default:** Continue (iteration in progress)

**Example:**

```typescript
import { createDefaultHook } from './tools/stop-hooks.js';

const hookId = createDefaultHook('TASK-abc123');
```

### createValidationHook

Hook that only considers validation rules.

**Decision Logic:**

1. All validation rules pass → complete
2. Some validation rules fail → continue with failure feedback
3. No validation rules → continue

**Example:**

```typescript
import { createValidationHook } from './tools/stop-hooks.js';

const hookId = createValidationHook('TASK-abc123');
```

### createPromiseHook

Hook that only considers completion promises.

**Decision Logic:**

1. `<promise>COMPLETE</promise>` detected → complete
2. `<promise>ESCALATE</promise>` detected → escalate
3. `<promise>BLOCKED</promise>` detected → escalate
4. No promise detected → continue

**Example:**

```typescript
import { createPromiseHook } from './tools/stop-hooks.js';

const hookId = createPromiseHook('TASK-abc123');
```

## Custom Hooks

You can register custom hooks with arbitrary logic:

```typescript
import { registerStopHook } from './tools/stop-hooks.js';

const hookId = registerStopHook(
  { taskId: 'TASK-abc123' },
  (context) => {
    // Custom decision logic
    if (context.iteration > 10) {
      return {
        action: 'escalate',
        reason: 'Too many iterations - may need different approach'
      };
    }

    if (context.filesModified.length === 0) {
      return {
        action: 'continue',
        reason: 'No files modified yet'
      };
    }

    return {
      action: 'complete',
      reason: 'Custom completion criteria met'
    };
  }
);
```

## Integration with Iteration Tools

### Typical Agent Flow

```markdown
1. task_get(taskId)

2. hook_register({
     taskId,
     hookType: 'default'
   })

3. iteration_start({
     taskId,
     maxIterations: 10,
     completionPromises: ['COMPLETE', 'BLOCKED']
   })

4. FOR EACH ITERATION:
   a. Execute agent logic (read/edit files)

   b. iteration_validate({
        iterationId,
        agentOutput: <agent-output>
      })
      → Internally calls hook_evaluate
      → Returns completionSignal: CONTINUE/COMPLETE/ESCALATE

   c. IF completionSignal === 'COMPLETE':
        iteration_complete({ iterationId, completionPromise: 'COMPLETE' })
        hook_clear({ taskId })
        BREAK

   d. IF completionSignal === 'ESCALATE':
        Mark task as blocked
        hook_clear({ taskId })
        BREAK

   e. IF completionSignal === 'CONTINUE':
        iteration_next({ iterationId })
        CONTINUE

5. hook_clear({ taskId })  // Cleanup on loop exit
```

## Hook Evaluation Order

When multiple hooks are registered for a task:

1. Hooks are evaluated in **registration order**
2. First hook to return `complete` or `escalate` **stops evaluation**
3. If all hooks return `continue`, the **last hook's result** is used
4. Disabled hooks are **skipped**

Example:

```typescript
// Hook 1 (evaluated first)
createValidationHook(taskId);

// Hook 2 (evaluated second)
createPromiseHook(taskId);

// Hook 3 (evaluated last)
createDefaultHook(taskId);
```

If Hook 1 returns `complete`, Hooks 2 and 3 are **not evaluated**.

## Safety and Error Handling

### Hook Failures

If a hook callback throws an error:

```json
{
  "action": "escalate",
  "reason": "Hook evaluation failed: <error message>",
  "metadata": {
    "error": "<error message>"
  }
}
```

### No Hooks Registered

If no hooks are registered for a task:

```json
{
  "hookId": "default",
  "action": "continue",
  "reason": "No hooks registered for this task"
}
```

### Hook Disabled

Disabled hooks are skipped during evaluation.

## Performance Considerations

### Session-Scoped Storage

Hooks are **not persisted** to the database. They exist only in the MCP server's memory for the current session.

**Benefits:**
- ✅ Fast evaluation (no database queries)
- ✅ Flexible callback logic (can't serialize functions)
- ✅ Automatic cleanup on server restart

**Limitations:**
- ❌ Hooks lost if server restarts mid-iteration
- ❌ Must re-register hooks on `checkpoint_resume`

### Memory Usage

Each hook stores:
- Hook ID (~20 bytes)
- Task ID (~20 bytes)
- Callback function reference (~8 bytes)
- Metadata (varies)

**Typical memory per hook:** ~100 bytes

**Max recommended hooks per task:** 5-10

## Common Patterns

### TDD Loop Hook

```typescript
const hookId = registerStopHook(
  { taskId },
  (context) => {
    // Check if tests pass
    const testsPass = context.validationResults.find(
      r => r.ruleName === 'tests_pass'
    )?.passed;

    if (testsPass) {
      return {
        action: 'complete',
        reason: 'All tests pass'
      };
    }

    return {
      action: 'continue',
      reason: 'Tests still failing',
      nextPrompt: 'Fix failing tests and run again'
    };
  }
);
```

### Security Remediation Hook

```typescript
const hookId = registerStopHook(
  { taskId },
  (context) => {
    const vulnsFixed = context.validationResults.find(
      r => r.ruleName === 'vulns_fixed'
    )?.passed;

    const scanClean = context.validationResults.find(
      r => r.ruleName === 'sast_clean'
    )?.passed;

    if (vulnsFixed && scanClean) {
      return {
        action: 'complete',
        reason: 'All vulnerabilities remediated'
      };
    }

    if (context.iteration >= 10) {
      return {
        action: 'escalate',
        reason: 'Max iterations reached - complex vulnerabilities may require manual review'
      };
    }

    return {
      action: 'continue',
      reason: 'Vulnerabilities remain'
    };
  }
);
```

### Checkpoint Creation Hook

```typescript
const hookId = registerStopHook(
  { taskId },
  (context) => {
    // Create checkpoint before risky operation
    if (context.iteration === 5) {
      return {
        action: 'continue',
        reason: 'Halfway checkpoint',
        checkpointData: {
          executionPhase: 'midpoint',
          executionStep: context.iteration,
          agentContext: {
            milestone: 'halfway'
          }
        }
      };
    }

    return {
      action: 'continue',
      reason: 'Iteration in progress'
    };
  }
);
```

## Testing

See `stop-hooks.test.ts` for comprehensive test suite covering:

- Hook registration and retrieval
- Hook unregistration and cleanup
- Preset hook factories
- Hook callback execution
- Async hooks
- Multiple hooks per task
- Error handling

**Run tests:**

```bash
cd mcp-servers/task-copilot
npm test -- stop-hooks.test.ts
```

## Migration from Phase 1

Phase 1 (iteration tools) is fully compatible. No changes required to existing iteration loops.

**To add stop hooks to existing iteration:**

```diff
  task_get(taskId)
+ hook_register({ taskId, hookType: 'default' })
  iteration_start({ taskId, maxIterations, completionPromises })

  FOR EACH ITERATION:
    iteration_validate({ iterationId, agentOutput })
    // Hook is automatically evaluated inside iteration_validate

  iteration_complete({ iterationId, completionPromise })
+ hook_clear({ taskId })
```

## Future Enhancements

Potential Phase 3+ features:

1. **Persistent Hooks** - Store hook configurations in database
2. **Hook Templates** - Pre-configured hooks for common scenarios
3. **Hook Chaining** - Compose multiple hooks with AND/OR logic
4. **Hook Metrics** - Track hook decision rates and accuracy
5. **Hook Debugging** - Detailed logging of hook evaluations
6. **Conditional Hooks** - Hooks that only activate under certain conditions

## References

- **Architecture Doc:** `/docs/architecture/ralph-wiggum-integration.md`
- **Iteration Tools:** `/src/tools/iteration.ts`
- **Safety Guards:** `/src/tools/iteration-guards.ts`
- **Phase 1 Implementation:** `TASK-RW-008-implementation.md`
