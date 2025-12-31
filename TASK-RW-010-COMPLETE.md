# TASK-RW-010: Stop Hook Integration into Iteration Flow - COMPLETE

## Task ID
TASK-b9a26c98-9739-416c-a54d-e7ae67e6cca2

## Problem Statement
The stop hook system was implemented (hooks, MCP tools, tests, docs) but NOT integrated into the iteration validation flow. The `iteration_validate()` function did not call `evaluateStopHooks()`, so hooks had no effect on iteration loops.

## Solution
Wired stop hooks into the iteration validation flow. The `iteration_validate()` function now calls `evaluateStopHooks()` when hooks are registered for a task, allowing hooks to influence the completion signal.

## Changes Made

### 1. Modified `iteration.ts`

**File:** `/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/src/tools/iteration.ts`

#### Imports
- Added `evaluateStopHooks` and `getTaskHooks` from `./stop-hooks.js`

#### Type Updates
- Added optional `hookDecision` field to `IterationValidateOutput`:
  ```typescript
  hookDecision?: {
    hookId: string;
    action: 'complete' | 'continue' | 'escalate';
    reason: string;
    nextPrompt?: string;
  };
  ```

#### Logic Changes in `iterationValidate()`
1. **Check for registered hooks** after safety checks pass
2. **Call `evaluateStopHooks()`** if hooks exist and safety checks pass
3. **Store hook decision** in output
4. **Allow hooks to influence completion signal** when signal is still `CONTINUE`:
   - Hook action `'complete'` → set signal to `COMPLETE`
   - Hook action `'escalate'` → set signal to `ESCALATE`
   - Hook action `'continue'` with `nextPrompt` → add guidance to feedback
5. **Include `hookDecision` in both return paths** (with/without validation rules)

### 2. Added Integration Test

**File:** `/Users/pabs/Sites/COPILOT/claude-copilot/mcp-servers/task-copilot/src/tools/iteration.integration.test.ts`

Added `testStopHookIntegration()` test that:
- Registers a stop hook for a task
- Starts an iteration loop
- Validates hook is called during `iteration_validate()`
- Verifies hook decision is included in output
- Confirms hook call count increases with each iteration
- Cleans up hooks after test

Test is added to the `runAllTests()` suite.

## Key Design Decisions

### Hook Evaluation Timing
Hooks are evaluated **after** safety checks but **before** final validation rules. This ensures:
- Safety guards (max iterations, circuit breaker) take precedence
- Explicit promises (BLOCKED, COMPLETE) take precedence
- Hooks only run when it's safe to continue

### Priority Order
The completion signal priority remains:
1. BLOCKED promise (highest)
2. COMPLETE promise
3. ESCALATE from safety guards
4. **Hook decisions** (new)
5. Validation results
6. CONTINUE (default)

### Backward Compatibility
- **No hooks registered** = current behavior (no changes)
- **hookDecision field is optional** = existing code continues to work
- **Hooks only influence signal when it's CONTINUE** = doesn't override explicit promises or safety guards

## Testing Strategy

### Unit Test Coverage
- Integration test verifies hook is called
- Integration test verifies hookDecision appears in output
- Integration test verifies hook call count is correct

### Manual Testing Needed
To fully test hook integration:
1. Create a task with iteration loop
2. Register a hook using `registerStopHook()`
3. Run `iteration_validate()` multiple times
4. Verify hook decision influences completion signal
5. Verify hook can force completion or escalation

## Files Modified

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `src/tools/iteration.ts` | ~40 | Add hook integration |
| `src/tools/iteration.integration.test.ts` | ~115 | Add integration test |

## Next Steps

This completes RW-010. Future enhancements could include:

1. **Hook persistence**: Store hook configurations in database for resumption
2. **Hook chaining**: Allow multiple hooks with defined priority
3. **Hook telemetry**: Track hook performance and decision patterns
4. **Preset hooks**: Package common hook patterns (e.g., test coverage thresholds)

## Integration Flow

### Before This Change
```
iteration_validate()
  ├── Parse checkpoint
  ├── Detect BLOCKED/COMPLETE promises
  ├── Run safety checks
  ├── Determine completion signal (BLOCKED > COMPLETE > ESCALATE > CONTINUE)
  └── Run validation rules
```
**Problem:** Hooks existed but were never called!

### After This Change
```
iteration_validate()
  ├── Parse checkpoint
  ├── Detect BLOCKED/COMPLETE promises
  ├── Run safety checks
  ├── ✨ Evaluate stop hooks (NEW)
  │    ├── Check if hooks registered for task
  │    ├── Call evaluateStopHooks()
  │    ├── Store hook decision in output
  │    └── Allow hooks to influence completion signal
  ├── Determine completion signal (BLOCKED > COMPLETE > ESCALATE > HOOK > CONTINUE)
  └── Run validation rules
```
**Fixed:** Hooks are now called and influence the iteration flow!

## Verification Checklist

- [x] Hooks are imported into iteration.ts
- [x] `getTaskHooks()` is called to check for registered hooks
- [x] `evaluateStopHooks()` is called when hooks exist
- [x] Hook decision is stored in output
- [x] Hook decision influences completion signal
- [x] Return type includes optional hookDecision field
- [x] Both return paths include hookDecision
- [x] Integration test added
- [x] Test verifies hook is called
- [x] Test verifies decision is in output
- [x] Backward compatibility maintained
