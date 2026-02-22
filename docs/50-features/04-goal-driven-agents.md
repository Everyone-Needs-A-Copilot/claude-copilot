# Goal-Driven Agents

Goal-driven agents use an iterative refinement loop where success is verified through observables, not assumed from execution. Instead of "do X then Y," agents verify "X is done" before proceeding.

> **Note:** The dedicated MCP iteration tools (`iteration_start`, `iteration_validate`, `iteration_next`, `iteration_complete`) have been removed. Agents now self-manage their iteration loops using standard tooling (run tests via Bash, check results, iterate). The goal-driven philosophy remains the same -- only the mechanism has changed.

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
│ Define success        │ ← Success criteria from task
│ criteria              │
│ - maxIterations: N   │
│ - validation checks  │
└──────────────────────┘
        │
        ▼
    ┌───────────────────────────┐
    │   Make changes / work     │
    └───────────────────────────┘
        │
        ▼
┌──────────────────────┐
│ Validate via Bash     │ ← Check observables
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
        │         Analyze gap           │
        │         Refine approach       │
        │         Try again             │
        │                 │             │
        │                 └─────────────┘
        │                       │
        ▼                       │
┌──────────────────────┐       │
│ Store work product    │ ←─────┘
│ Update task status    │
└──────────────────────┘
```

## Agent Schema

Agents define their iteration approach in their YAML frontmatter:

```yaml
---
name: me
description: Feature implementation agent
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---
```

Agents self-manage iteration loops without dedicated MCP tools. The iteration pattern is documented in the agent's workflow section.

### Validation Checks

Common validation checks for different agent types:

| Agent | Validation Checks | Meaning |
|-------|-----------------|---------|
| `me` | Run tests, compile, lint | All tests pass, code compiles, no lint errors |
| `ta` | Check PRD exists, tasks exist | PRD created, tasks created via `tc` CLI |
| `qa` | Check test coverage, run tests | Tests created, coverage threshold met, tests pass |
| `doc` | Check docs exist, validate links | Docs exist, no broken links, examples execute |

Validation checks are executed via Bash commands. Agents can define custom checks based on their domain.

## Goal-Driven Workflow

### Example: Implementation Agent (me.md)

```markdown
## Workflow

1. Check task state: `tc task get <id> --json`
2. Use `skill_evaluate({ files, text })` to load relevant skills
3. Read existing code to understand patterns
4. FOR EACH iteration (up to max retries):
   - Make changes to code
   - Run tests via Bash
   - IF all tests pass AND lint clean: BREAK (success)
   - IF blocked by external dependency: Update task status, BREAK
   - ELSE: Analyze failure, refine approach
5. Store work product: `tc wp store --task <id> --type implementation --title "..." --content "..." --json`
6. Update task: `tc task update <id> --status completed --json`
```

### Example: Test-Driven Development

```markdown
Agent: me
Task: Add authentication middleware

Iteration 1:
- Write initial middleware code
- Run tests via Bash -> 4 failures
- Analyze test failures

Iteration 2:
- Fix token validation logic
- Run tests via Bash -> 2 failures, compiles OK
- Fix edge cases

Iteration 3:
- Handle expired tokens
- Run tests via Bash -> all pass, compiles OK, lint clean
- Store work product: tc wp store --task <id> ...
- Update task: tc task update <id> --status completed --json
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
- **Validation:** Conflict detected in database migrations (checked via `git diff`)
- **Next:** Resolve conflict with Stream-B

**Iteration 2:**
- Adjust migration strategy to avoid conflict
- Recreate tasks with updated dependencies via `tc task create ...`
- **Validation:** No conflicts (checked via `git diff`), tasks created
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

1. FOR EACH iteration (up to max retries):
   - Make changes
   - Run validation checks via Bash (tests, compile, lint)
   - IF success: store work product via `tc wp store ...`, update task via `tc task update <id> --status completed --json`
   - IF blocked: update task via `tc task update <id> --status blocked --json`
   - ELSE: analyze failure, refine approach
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

When the maximum number of attempts is reached without success:

1. Store work product with detailed analysis via `tc wp store --task <id> ...`:
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
2. Update task status to "blocked" with human-readable summary: `tc task update <id> --status blocked --json`

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

1. Store work product explaining blocker: `tc wp store --task <id> --type other --title "Blocked: ..." --content "..." --json`
2. Update task with blocker details: `tc task update <id> --status blocked --json`

## Configuration

### Agent-Level Defaults

Agents define their iteration approach directly in their workflow instructions. The max retry count and validation checks are documented as part of the agent's markdown file.

### Task-Level Context

Task metadata provides context for the agent's iteration decisions:

```bash
# Agent retrieves task details to understand scope
tc task get TASK-xxx --json
# Returns metadata including complexity, files, acceptance criteria
```

### Project-Level Configuration

Quality gates in `.claude/quality-gates.json` define project-level validation checks that run on task completion.

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

Between iterations, agents should:
- Review validation failure messages from test/compile output
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

**Step 1: Update agent tools**

Remove iteration MCP tools from the tools list. Agents use standard tools (Read, Write, Edit, Bash, Grep, Glob) plus `tc` CLI commands.

**Step 2: Transform workflow to success criteria**

Change from procedural steps to verifiable outcomes:

```diff
- 1. Read files
- 2. Make changes
- 3. Write files
+ 1. Verify code compiles (run compiler via Bash)
+ 2. Verify tests pass (run test suite via Bash)
+ 3. Verify meets acceptance criteria
```

**Step 3: Add self-managed iteration loop**

```markdown
## Workflow

1. tc task get <id> --json
2. FOR EACH attempt (up to max retries):
   - Do work
   - Run validation checks via Bash
   - IF all pass: store work product, update task, BREAK
   - IF blocked: update task status to blocked, BREAK
   - ELSE: analyze failure, refine approach
3. tc wp store --task <id> --type <t> --title "..." --content "..." --json
4. tc task update <id> --status completed --json
```

**Step 4: Test with real tasks**

Run agent on actual tasks and verify:
- Iterations converge to success
- Blocked states are detected
- Max retries prevent infinite loops

## Related Documentation

- [Agent Development Guide](../../CLAUDE.md)
- [Task Management (`tc` CLI)](../../CLAUDE_REFERENCE.md#tc-cli)
- [Lifecycle Hooks](./lifecycle-hooks.md)
- [Testing Patterns](./testing-patterns.md)
