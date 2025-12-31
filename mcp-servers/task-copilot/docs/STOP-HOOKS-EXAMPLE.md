# Stop Hook System - Agent Integration Example

**Purpose:** Demonstrates how agents use stop hooks in Ralph Wiggum iteration loops.

## Example 1: Simple TDD Loop (@agent-me)

### Agent Workflow

```markdown
## Task: Implement User Authentication

### Step 1: Initialize Iteration

task_get(taskId: "TASK-AUTH-001")

hook_register({
  taskId: "TASK-AUTH-001",
  hookType: "default"
})

iteration_start({
  taskId: "TASK-AUTH-001",
  maxIterations: 10,
  completionPromises: ["COMPLETE", "BLOCKED"],
  validationRules: [
    {
      type: "command",
      name: "tests_pass",
      config: { command: "npm test -- auth.test.ts" }
    },
    {
      type: "command",
      name: "compiles",
      config: { command: "tsc --noEmit" }
    }
  ]
})

### Step 2: Iteration Loop

**Iteration 1:**
- Write failing test for login()
- iteration_validate({ iterationId, agentOutput: "Wrote test case" })
  → completionSignal: CONTINUE (tests fail as expected)
- iteration_next({ iterationId })

**Iteration 2:**
- Implement basic login() logic
- iteration_validate({ iterationId, agentOutput: "Implemented login()" })
  → completionSignal: CONTINUE (tests pass, but lint errors)
- iteration_next({ iterationId })

**Iteration 3:**
- Fix lint errors
- iteration_validate({
    iterationId,
    agentOutput: "Fixed lint errors. <promise>COMPLETE</promise>"
  })
  → completionSignal: COMPLETE (hook detected promise)
- iteration_complete({
    iterationId,
    completionPromise: "COMPLETE",
    workProductId: "WP-AUTH-001"
  })
- hook_clear({ taskId: "TASK-AUTH-001" })

### Result

✅ Task completed in 3 iterations
✅ All validation rules pass
✅ Work product stored
```

## Example 2: Security Remediation Loop (@agent-sec)

### Agent Workflow

```markdown
## Task: Fix OWASP Vulnerabilities

### Step 1: Initialize with Custom Hook

task_get(taskId: "TASK-SEC-002")

// Custom hook with security-specific logic
hook_register({
  taskId: "TASK-SEC-002",
  hookType: "default"
})

iteration_start({
  taskId: "TASK-SEC-002",
  maxIterations: 15,
  completionPromises: ["COMPLETE", "BLOCKED"],
  validationRules: [
    {
      type: "command",
      name: "vulns_fixed",
      config: { command: "npm audit --audit-level=high" }
    },
    {
      type: "command",
      name: "sast_clean",
      config: { command: "semgrep --config=auto --error" }
    }
  ],
  circuitBreakerThreshold: 3
})

### Step 2: Iteration Loop

**Iteration 1:**
- Fix SQL injection vulnerability in auth.ts
- iteration_validate({ iterationId, agentOutput: "Fixed SQL injection" })
  → completionSignal: CONTINUE (SAST still reports issues)
- iteration_next({ iterationId })

**Iteration 2:**
- Fix XSS vulnerability in profile.ts
- iteration_validate({ iterationId, agentOutput: "Fixed XSS" })
  → completionSignal: CONTINUE (npm audit still fails)
- iteration_next({ iterationId })

**Iteration 3:**
- Update dependencies to patch known vulnerabilities
- iteration_validate({ iterationId, agentOutput: "Updated deps" })
  → completionSignal: CONTINUE (some dependencies have breaking changes)
- iteration_next({ iterationId })

**Iteration 4:**
- Handle breaking changes from dependency updates
- iteration_validate({
    iterationId,
    agentOutput: "All tests pass. <promise>COMPLETE</promise>"
  })
  → completionSignal: COMPLETE (all validation rules pass + promise)
- iteration_complete({
    iterationId,
    completionPromise: "COMPLETE",
    workProductId: "WP-SEC-002"
  })
- hook_clear({ taskId: "TASK-SEC-002" })

### Result

✅ Task completed in 4 iterations
✅ All vulnerabilities remediated
✅ Tests still pass
```

## Example 3: Blocked State Handling (@agent-me)

### Agent Workflow

```markdown
## Task: Refactor Legacy Module

### Step 1: Initialize

task_get(taskId: "TASK-REFACTOR-003")

hook_register({
  taskId: "TASK-REFACTOR-003",
  hookType: "default"
})

iteration_start({
  taskId: "TASK-REFACTOR-003",
  maxIterations: 8,
  completionPromises: ["COMPLETE", "BLOCKED"],
  validationRules: [
    {
      type: "command",
      name: "tests_pass",
      config: { command: "npm test" }
    }
  ]
})

### Step 2: Iteration Loop

**Iteration 1:**
- Attempt to refactor legacy code
- iteration_validate({ iterationId, agentOutput: "Refactored 30%" })
  → completionSignal: CONTINUE (tests fail)
- iteration_next({ iterationId })

**Iteration 2:**
- Fix test failures
- iteration_validate({ iterationId, agentOutput: "Fixed tests" })
  → completionSignal: CONTINUE (tests pass but coverage dropped)
- iteration_next({ iterationId })

**Iteration 3:**
- Discover missing documentation for legacy behavior
- iteration_validate({
    iterationId,
    agentOutput: "Need documentation. <promise>BLOCKED</promise> - Missing specs for legacy edge cases"
  })
  → completionSignal: ESCALATE (hook detected BLOCKED promise)
- task_update({
    id: "TASK-REFACTOR-003",
    status: "blocked",
    blockedReason: "Missing specs for legacy edge cases"
  })
- hook_clear({ taskId: "TASK-REFACTOR-003" })

### Result

⚠️ Task blocked after 3 iterations
⚠️ Escalated to human for specification
✅ Progress preserved in checkpoint
```

## Example 4: Safety Guard Escalation

### Agent Workflow

```markdown
## Task: Optimize Database Query

### Step 1: Initialize

task_get(taskId: "TASK-PERF-004")

hook_register({
  taskId: "TASK-PERF-004",
  hookType: "default"
})

iteration_start({
  taskId: "TASK-PERF-004",
  maxIterations: 5,
  completionPromises: ["COMPLETE"],
  validationRules: [
    {
      type: "command",
      name: "perf_test",
      config: { command: "npm run perf-test" }
    }
  ],
  circuitBreakerThreshold: 3
})

### Step 2: Iteration Loop

**Iteration 1:**
- Add index to users table
- iteration_validate({ iterationId, agentOutput: "Added index" })
  → completionSignal: CONTINUE (perf test fails - query still slow)
- iteration_next({ iterationId })

**Iteration 2:**
- Rewrite query with JOIN
- iteration_validate({ iterationId, agentOutput: "Rewrote query" })
  → completionSignal: CONTINUE (perf test fails - slower than before!)
- iteration_next({ iterationId })

**Iteration 3:**
- Revert JOIN, try different approach
- iteration_validate({ iterationId, agentOutput: "Tried new approach" })
  → completionSignal: CONTINUE (perf test fails - quality regression detected)
- iteration_next({ iterationId })

**Iteration 4:**
- Another attempt
- iteration_validate({ iterationId, agentOutput: "Fourth attempt" })
  → completionSignal: ESCALATE (safety guard: quality regression triggered)
- task_update({
    id: "TASK-PERF-004",
    status: "blocked",
    blockedReason: "Quality regression detected - may need different optimization strategy"
  })
- hook_clear({ taskId: "TASK-PERF-004" })

### Result

⚠️ Escalated after 4 iterations (safety guard)
⚠️ Quality degradation detected
✅ Progress preserved for human review
```

## Example 5: Multiple Hook Evaluation

### Custom Hook Registration

```typescript
// Example: Custom quality gate hook
const qualityGateHook = registerStopHook(
  {
    taskId: "TASK-QA-005",
    hookId: "quality-gate",
    metadata: { description: "Enforce quality thresholds" }
  },
  (context) => {
    const coverage = context.validationResults.find(
      r => r.ruleName === 'coverage_threshold'
    );

    const complexity = context.validationResults.find(
      r => r.ruleName === 'complexity_check'
    );

    // Strict quality requirements
    if (coverage?.passed && complexity?.passed) {
      return {
        action: 'complete',
        reason: 'Quality gates passed',
        metadata: {
          coverage: coverage.message,
          complexity: complexity.message
        }
      };
    }

    if (context.iteration >= 8) {
      return {
        action: 'escalate',
        reason: 'Cannot meet quality gates within iteration limit'
      };
    }

    return {
      action: 'continue',
      reason: 'Quality gates not met',
      nextPrompt: `Improve:\n- ${!coverage?.passed ? 'Test coverage' : ''}\n- ${!complexity?.passed ? 'Code complexity' : ''}`
    };
  }
);
```

### Agent Workflow

```markdown
## Task: Improve Test Coverage

task_get(taskId: "TASK-QA-005")

// Register multiple hooks
hook_register({ taskId: "TASK-QA-005", hookType: "promise" })
// Custom hook registered via TypeScript

iteration_start({
  taskId: "TASK-QA-005",
  maxIterations: 10,
  completionPromises: ["COMPLETE"],
  validationRules: [
    {
      type: "coverage",
      name: "coverage_threshold",
      config: { threshold: 85 }
    },
    {
      type: "command",
      name: "complexity_check",
      config: { command: "complexity-reporter --max=10" }
    }
  ]
})

**Iteration Flow:**
1. Promise hook evaluates first (no promise → continue)
2. Quality gate hook evaluates second (coverage 70% → continue with feedback)
3. Agent improves coverage to 88%
4. Next iteration: Promise hook (no promise → continue)
5. Quality gate hook (coverage + complexity pass → complete)
```

## Hook Evaluation Decision Tree

```
┌─────────────────────────────────────────────────┐
│         iteration_validate called                │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │  Get Task Hooks      │
        └──────────┬───────────┘
                   │
         ┌─────────▼─────────┐
         │  Any hooks?       │
         └─────┬─────────┬───┘
               │ No      │ Yes
               │         │
               ▼         ▼
         ┌─────────┐  ┌──────────────┐
         │ CONTINUE│  │ Evaluate     │
         └─────────┘  │ hooks in     │
                      │ order        │
                      └──────┬───────┘
                             │
                   ┌─────────▼─────────┐
                   │ Hook returns:     │
                   │ - complete?       │
                   │ - escalate?       │
                   └─────┬─────────┬───┘
                         │ Yes     │ No
                         │         │
                         ▼         ▼
                   ┌─────────┐  ┌──────────┐
                   │ RETURN  │  │ Next     │
                   │ ACTION  │  │ Hook     │
                   └─────────┘  └────┬─────┘
                                     │
                               ┌─────▼──────┐
                               │ More hooks?│
                               └─┬─────────┬┘
                                 │ No      │ Yes
                                 │         │
                                 ▼         └─→ Loop
                           ┌─────────┐
                           │ RETURN  │
                           │ CONTINUE│
                           └─────────┘
```

## Best Practices

### 1. Always Clear Hooks

```typescript
// ✅ Good
try {
  hook_register({ taskId, hookType: 'default' });
  // ... iteration loop ...
} finally {
  hook_clear({ taskId });
}

// ❌ Bad (hooks leak across tasks)
hook_register({ taskId, hookType: 'default' });
// ... iteration loop ...
// Forgot to clear!
```

### 2. Use Default Hook Unless Specific Need

```typescript
// ✅ Good (most cases)
hook_register({ taskId, hookType: 'default' });

// ⚠️ Use only for specific cases
hook_register({ taskId, hookType: 'validation' }); // Testing only
hook_register({ taskId, hookType: 'promise' });    // No validation rules
```

### 3. Provide Clear Reasons

```typescript
// ✅ Good
return {
  action: 'continue',
  reason: 'Test coverage at 65% (target: 80%)',
  nextPrompt: 'Add tests for auth.ts and profile.ts'
};

// ❌ Bad
return {
  action: 'continue',
  reason: 'Not done'
};
```

### 4. Handle Edge Cases

```typescript
// ✅ Good
if (!context.validationResults || context.validationResults.length === 0) {
  return {
    action: 'continue',
    reason: 'No validation results available'
  };
}

// ❌ Bad (assumes validation results exist)
const allPassed = context.validationResults.every(r => r.passed);
```

### 5. Use Checkpoint Data for Recovery

```typescript
return {
  action: 'continue',
  reason: 'Halfway through optimization',
  checkpointData: {
    executionPhase: 'optimization',
    executionStep: context.iteration,
    agentContext: {
      optimizationStrategy: 'index-based',
      completedSteps: ['analyze', 'plan']
    }
  }
};
```

## Troubleshooting

### Hook Not Evaluated

**Symptom:** `iteration_validate` returns CONTINUE but hook should have returned COMPLETE.

**Diagnosis:**
```typescript
// Check if hook is registered
hook_list({ taskId })

// Check if hook is enabled
const hooks = hook_list({ taskId });
console.log(hooks.hooks.find(h => h.enabled === false));
```

**Fix:** Re-register hook or enable it.

### Hook Returns Wrong Action

**Symptom:** Hook returns CONTINUE when it should return COMPLETE.

**Diagnosis:**
```typescript
// Manually evaluate hook to see context
hook_evaluate({
  iterationId,
  agentOutput: "...",
  filesModified: [...]
});

// Check validation results
console.log(context.validationResults);
```

**Fix:** Adjust hook logic or validation rules.

### Multiple Hooks Conflict

**Symptom:** Hook A returns COMPLETE but Hook B returns CONTINUE.

**Diagnosis:**
```typescript
// Hooks evaluate in registration order
// First hook to return complete/escalate wins
hook_list({ taskId });
```

**Fix:** Register hooks in priority order or use single default hook.

## See Also

- **Stop Hooks Documentation:** `STOP-HOOKS.md`
- **Iteration Tools:** `ITERATION-VALIDATION.md`
- **Ralph Wiggum Architecture:** `/docs/architecture/ralph-wiggum-integration.md`
