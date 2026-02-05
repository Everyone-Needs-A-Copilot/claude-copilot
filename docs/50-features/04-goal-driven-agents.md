# Goal-Driven Agents

Goal-driven agents use an iterative refinement loop where success is verified through observables, not assumed from execution. Instead of "do X then Y," agents verify "X is done" before proceeding.

## Overview

Traditional agents execute procedural workflows: "Read file, make changes, write file." Goal-driven agents verify outcomes: "Verify tests pass, verify code compiles, verify acceptance criteria met."

| Traditional Agent | Goal-Driven Agent |
|------------------|-------------------|
| Execute steps 1, 2, 3 | Verify goal state achieved |
| Assume success after execution | Measure success through validation |
| Fail silently or abruptly | Iterate until success or max attempts |
| Manual debugging loops | Automatic refinement iterations |

## Architecture

```
Agent receives task
        │
        ▼
┌──────────────────────┐
│ iteration_start()    │ ← Define success criteria
│ - maxIterations: N   │
│ - completionPromises │
│ - validationRules    │
└──────────────────────┘
        │
        ▼
    ┌───────────────────────────┐
    │   Make changes / work     │
    └───────────────────────────┘
        │
        ▼
┌──────────────────────┐
│ iteration_validate() │ ← Check observables
│ - Run tests          │
│ - Check compiles     │
│ - Verify goals       │
└──────────────────────┘
        │
        ├─────────────────┐
        │                 │
        ▼                 ▼
    SUCCESS           NOT YET
        │                 │
        │                 ├──────────────┐
        │                 │              │
        │                 ▼              ▼
        │         maxIterations?    BLOCKED?
        │            reached?           │
        │                 │             │
        │                 │             ▼
        │                 │        Update task
        │                 │        status blocked
        │                 │             │
        │                 ▼             │
        │         iteration_next()      │
        │         - Analyze gap         │
        │         - Refine approach     │
        │         - Try again           │
        │                 │             │
        │                 └─────────────┘
        │                       │
        ▼                       │
┌──────────────────────┐       │
│ iteration_complete() │ ←─────┘
│ Emit COMPLETE        │
└──────────────────────┘
```

## Agent Schema

Agents declare iteration support in their YAML frontmatter:

```yaml
---
name: me
description: Feature implementation agent
tools: Read, Write, Edit, iteration_start, iteration_validate, iteration_next, iteration_complete
model: sonnet
iteration:
  enabled: true
  maxIterations: 15
  completionPromises:
    - "<promise>COMPLETE</promise>"
    - "<promise>BLOCKED</promise>"
  validationRules:
    - tests_pass
    - compiles
    - lint_clean
---
```

### Schema Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `enabled` | boolean | Iteration loop enabled | `true` |
| `maxIterations` | number | Max refinement attempts | `15` |
| `completionPromises` | string[] | Signals for completion | `["<promise>COMPLETE</promise>"]` |
| `validationRules` | string[] | Success criteria identifiers | `["tests_pass", "compiles"]` |

### Validation Rules

Common validation rules for different agent types:

| Agent | Validation Rules | Meaning |
|-------|-----------------|---------|
| `me` | `tests_pass`, `compiles`, `lint_clean` | All tests pass, code compiles, no lint errors |
| `ta` | `prd_created`, `tasks_created`, `no_conflicts` | PRD exists, tasks exist, no stream conflicts |
| `qa` | `tests_written`, `coverage_sufficient`, `tests_pass` | Tests created, coverage threshold met, tests pass |
| `doc` | `docs_generated`, `links_valid`, `examples_work` | Docs exist, no broken links, examples execute |

Validation rules are extensible. Agents can define custom rules based on their domain.

## Iteration Tools

### iteration_start

Begins an iteration loop with defined success criteria.

```typescript
const result = await iteration_start({
  taskId: "TASK-xxx",
  maxIterations: 15,
  completionPromises: [
    "<promise>COMPLETE</promise>",
    "<promise>BLOCKED</promise>"
  ],
  validationRules: ["tests_pass", "compiles", "lint_clean"]
});

// Returns:
{
  iterationId: "ITER-xxx",
  currentIteration: 0,
  maxIterations: 15,
  status: "active"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `taskId` | string | Yes | Task this iteration is for |
| `maxIterations` | number | Yes | Max refinement attempts |
| `completionPromises` | string[] | Yes | Signals indicating completion |
| `validationRules` | string[] | Yes | Success criteria to check |

### iteration_validate

Checks if success criteria are met.

```typescript
const result = await iteration_validate({
  iterationId: "ITER-xxx"
});

// Returns:
{
  iterationId: "ITER-xxx",
  currentIteration: 3,
  maxIterations: 15,
  validationResults: {
    tests_pass: { pass: true, message: "All 42 tests passed" },
    compiles: { pass: true, message: "No compilation errors" },
    lint_clean: { pass: false, message: "3 lint errors in src/auth.ts" }
  },
  completionSignal: null,  // or "COMPLETE" or "BLOCKED"
  shouldContinue: true,
  message: "Validation failed: lint_clean (3 errors)"
}
```

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| `validationResults` | object | Results for each validation rule |
| `completionSignal` | string\|null | Detected completion promise if any |
| `shouldContinue` | boolean | Whether to continue iterating |
| `message` | string | Human-readable status |

**Validation Logic:**

1. Check for completion promises in agent's recent output
2. Run validation rules (tests, compilation, etc.)
3. If all pass: return `completionSignal: "COMPLETE"`
4. If blocked signal detected: return `completionSignal: "BLOCKED"`
5. If max iterations reached: return `shouldContinue: false`
6. Otherwise: return `shouldContinue: true` with failure details

### iteration_next

Advances to the next iteration after analyzing failures.

```typescript
const result = await iteration_next({
  iterationId: "ITER-xxx"
});

// Returns:
{
  iterationId: "ITER-xxx",
  currentIteration: 4,
  maxIterations: 15,
  status: "active",
  message: "Iteration 4/15 started"
}
```

### iteration_complete

Marks iteration as complete and stores results.

```typescript
const result = await iteration_complete({
  iterationId: "ITER-xxx",
  outcome: "success",  // or "blocked" or "max_iterations"
  summary: "Successfully implemented auth with all tests passing"
});

// Returns:
{
  iterationId: "ITER-xxx",
  totalIterations: 5,
  outcome: "success",
  elapsedTime: "3m 42s"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `iterationId` | string | Yes | Iteration to complete |
| `outcome` | enum | Yes | `"success"`, `"blocked"`, `"max_iterations"` |
| `summary` | string | Yes | Human-readable completion summary |

## Goal-Driven Workflow

### Example: Implementation Agent (me.md)

```markdown
## Workflow

1. Run `preflight_check({ taskId })` before starting
2. Use `skill_evaluate({ files, text })` to load relevant skills
3. Read existing code to understand patterns
4. Start iteration loop:
   - `iteration_start({ taskId, maxIterations: 15, ... })`
5. FOR EACH iteration:
   - Make changes to code
   - Run `iteration_validate({ iterationId })`
   - IF `completionSignal === 'COMPLETE'`: Call `iteration_complete()`, BREAK
   - IF `completionSignal === 'BLOCKED'`: Update task status, BREAK
   - ELSE: Analyze failure, call `iteration_next()`, refine approach
6. Store work product: `work_product_store({ ... })`
7. Emit: `<promise>COMPLETE</promise>`
```

### Example: Test-Driven Development

```typescript
// Agent: me
// Task: Add authentication middleware

// Iteration 1:
// - Write initial middleware code
// - iteration_validate() → tests_pass: false (4 failures)
// - iteration_next() → Analyze test failures

// Iteration 2:
// - Fix token validation logic
// - iteration_validate() → tests_pass: false (2 failures), compiles: true
// - iteration_next() → Fix edge cases

// Iteration 3:
// - Handle expired tokens
// - iteration_validate() → tests_pass: true, compiles: true, lint_clean: true
// - completionSignal: "COMPLETE"
// - iteration_complete({ outcome: "success" })
```

## Practical Examples

### Example 1: Implementation with TDD

```markdown
## Task: Implement User Login Endpoint

### Iteration Loop

**Iteration 1:**
- Write login endpoint skeleton
- Add basic JWT generation
- Run tests: ❌ 5/12 passing
- **Validation:** `tests_pass: false`
- **Next:** Fix password validation

**Iteration 2:**
- Implement bcrypt password check
- Run tests: ❌ 8/12 passing
- **Validation:** `tests_pass: false`
- **Next:** Handle invalid credentials

**Iteration 3:**
- Add error handling for invalid credentials
- Run tests: ❌ 10/12 passing
- **Validation:** `tests_pass: false`
- **Next:** Fix token expiry edge case

**Iteration 4:**
- Implement token refresh logic
- Run tests: ✅ 12/12 passing
- **Validation:** `tests_pass: true`, `compiles: true`, `lint_clean: true`
- **Complete:** All criteria met

**Result:** Success in 4 iterations
```

### Example 2: Architecture Planning

```markdown
## Task: Design Multi-Tenant Architecture

### Iteration Loop

**Iteration 1:**
- Design initial schema with tenant isolation
- Create PRD and task breakdown
- **Validation:** `stream_conflict_check: conflict in database migrations`
- **Next:** Resolve conflict with Stream-B

**Iteration 2:**
- Adjust migration strategy to avoid conflict
- Recreate tasks with updated dependencies
- **Validation:** `no_conflicts: true`, `tasks_created: true`
- **Complete:** All criteria met

**Result:** Success in 2 iterations
```

### Example 3: Blocked State

```markdown
## Task: Fix Authentication Bug

### Iteration Loop

**Iteration 1:**
- Identify root cause: third-party API change
- Attempt workaround with updated API calls
- Run tests: ❌ Still failing with same error
- **Validation:** `tests_pass: false`
- **Next:** Try alternative approach

**Iteration 2:**
- Implement fallback authentication method
- Run tests: ❌ New error: "API key invalid"
- **Validation:** Agent detects external dependency failure
- **Emit:** `<promise>BLOCKED</promise>`
- **Complete:** Outcome = "blocked"

**Result:** Blocked - requires API key update from external team
```

## Success Criteria Format

### Transformation: Procedural → Goal-Driven

**Before (Procedural):**
```markdown
## Workflow

1. Read the existing code
2. Make the necessary changes
3. Write the updated code
4. Run the tests
5. Fix any errors
```

**After (Goal-Driven):**
```markdown
## Success Criteria

- [ ] Code compiles without errors
- [ ] All existing tests pass
- [ ] New tests cover added functionality
- [ ] Lint checks pass
- [ ] Code follows existing patterns

## Iteration Loop

1. iteration_start({ maxIterations: 15, validationRules: [...] })
2. FOR EACH iteration:
   - Make changes
   - iteration_validate()
   - IF success: iteration_complete(), emit COMPLETE
   - IF blocked: task_update(blocked), emit BLOCKED
   - ELSE: iteration_next(), analyze and refine
```

### Agent Instruction Patterns

**Replace "Do X" with "Verify X":**

| Procedural ❌ | Goal-Driven ✅ |
|-------------|--------------|
| "Run the tests" | "Verify all tests pass" |
| "Write documentation" | "Verify docs exist and links are valid" |
| "Create PRD and tasks" | "Verify PRD created and tasks exist with no conflicts" |
| "Fix the bug" | "Verify bug reproduction no longer occurs" |
| "Deploy to staging" | "Verify deployment successful and health checks pass" |

## Max Iteration Handling

When `maxIterations` is reached without success:

1. Call `iteration_complete({ outcome: "max_iterations" })`
2. Store work product with detailed analysis:
   ```markdown
   ## Iteration Limit Reached

   Attempted 15 iterations without achieving success criteria.

   ### What Was Tried
   - Iteration 1-5: Initial implementation approach
   - Iteration 6-10: Alternative error handling strategy
   - Iteration 11-15: Edge case fixes

   ### Remaining Issues
   - Test failure: "Token validation timing issue"
   - Likely cause: Race condition in async token refresh

   ### Recommended Next Steps
   - Review token refresh timing logic
   - Add synchronization mechanism
   - Consider involving @agent-sec for security review
   ```
3. Update task status to "blocked" with human-readable summary
4. Emit `<promise>BLOCKED</promise>`

## BLOCKED Signal Usage

Agents should emit `<promise>BLOCKED</promise>` when:

| Situation | Example |
|-----------|---------|
| External dependency failure | Third-party API down, missing credentials |
| Environmental issues | Database unreachable, missing permissions |
| Conflicting requirements | Contradictory acceptance criteria |
| Missing information | Unclear requirements, ambiguous specifications |
| Human decision needed | Architecture choice requires stakeholder input |

**When blocked:**

1. Emit `<promise>BLOCKED</promise>` in agent output
2. `iteration_validate()` detects the promise
3. Agent calls `iteration_complete({ outcome: "blocked" })`
4. Store work product explaining blocker
5. Update task with blocker details

## Configuration

### Agent-Level Defaults

Set in agent frontmatter:

```yaml
iteration:
  enabled: true
  maxIterations: 15
  completionPromises:
    - "<promise>COMPLETE</promise>"
    - "<promise>BLOCKED</promise>"
  validationRules:
    - tests_pass
    - compiles
```

### Task-Level Overrides

Override in `iteration_start()` call:

```typescript
iteration_start({
  taskId: "TASK-xxx",
  maxIterations: 25,  // Override agent default
  validationRules: ["custom_rule", "tests_pass"]  // Add custom rule
})
```

### Project-Level Configuration

Set environment variables (future):

```bash
ITERATION_MAX_DEFAULT=15
ITERATION_TIMEOUT=300000  # 5 minutes
ITERATION_VALIDATION_TIMEOUT=60000  # 1 minute
```

## Best Practices

### 1. Start with Clear Success Criteria

**Good:**
```typescript
validationRules: [
  "tests_pass",           // All tests pass
  "compiles",             // No compilation errors
  "lint_clean",           // No lint warnings
  "coverage_threshold"    // >80% code coverage
]
```

**Avoid:**
```typescript
validationRules: [
  "looks_good",  // Too vague
  "done"         // Not verifiable
]
```

### 2. Keep Iterations Small

Each iteration should make incremental progress:
- Fix one test failure
- Resolve one lint error
- Add one missing feature

Avoid trying to fix everything in one iteration.

### 3. Analyze Failures Between Iterations

Use `iteration_next()` to:
- Review validation failure messages
- Identify patterns in errors
- Adjust approach based on feedback
- Document what was learned

### 4. Set Realistic maxIterations

| Agent Type | Typical Max | Rationale |
|------------|-------------|-----------|
| `me` (implementation) | 15 | Most implementations converge within 10-15 attempts |
| `ta` (architecture) | 10 | Planning is less iterative than implementation |
| `qa` (testing) | 12 | Test writing may need several refinement rounds |
| `doc` (documentation) | 8 | Documentation is more deterministic |

### 5. Store Iteration History

In work products, include:
```markdown
## Iteration History

- **Iteration 1:** Initial implementation → 4 test failures
- **Iteration 2:** Fixed validation logic → 2 test failures
- **Iteration 3:** Added edge case handling → All tests pass ✅
```

## Metrics and Observability

Iteration data can be used for:

| Metric | Use Case |
|--------|----------|
| Average iterations to success | Measure task complexity |
| Blocked rate | Identify systemic issues |
| Common failure patterns | Improve validation rules |
| Time per iteration | Optimize validation speed |

Future: Dashboard showing iteration statistics across all tasks.

## Comparison with Traditional Agents

| Aspect | Traditional Agent | Goal-Driven Agent |
|--------|------------------|-------------------|
| **Success verification** | Assumed | Measured |
| **Error handling** | Manual retry | Automatic refinement |
| **Debugging** | Human-in-loop | Self-correcting |
| **Observable outcomes** | Implicit | Explicit validation rules |
| **Failure recovery** | Start over | Incremental refinement |
| **Context retention** | Lost between attempts | Maintained across iterations |

## Migration Guide

### Adapting Existing Agents

**Step 1: Add iteration schema to frontmatter**

```yaml
iteration:
  enabled: true
  maxIterations: 15
  completionPromises:
    - "<promise>COMPLETE</promise>"
    - "<promise>BLOCKED</promise>"
  validationRules:
    - domain_specific_rule
    - tests_pass
```

**Step 2: Transform workflow to success criteria**

Change from procedural steps to verifiable outcomes:

```diff
- 1. Read files
- 2. Make changes
- 3. Write files
+ 1. Verify code compiles
+ 2. Verify tests pass
+ 3. Verify meets acceptance criteria
```

**Step 3: Add iteration loop**

```markdown
## Workflow

1. preflight_check()
2. iteration_start({ taskId, maxIterations: 15, ... })
3. FOR EACH iteration:
   - Do work
   - iteration_validate()
   - IF complete: iteration_complete(), BREAK
   - ELSE: iteration_next(), refine
4. Emit <promise>COMPLETE</promise>
```

**Step 4: Test with real tasks**

Run agent on actual tasks and verify:
- Iterations converge to success
- Blocked states are detected
- Max iterations prevents infinite loops

## Related Documentation

- [Agent Development Guide](../../CLAUDE.md)
- [Task Copilot Integration](../../CLAUDE_REFERENCE.md#task-copilot)
- [Lifecycle Hooks](./lifecycle-hooks.md)
- [Testing Patterns](./testing-patterns.md)
