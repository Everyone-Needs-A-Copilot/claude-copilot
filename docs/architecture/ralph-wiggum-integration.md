# Ralph Wiggum Iterative Loop Integration with Task Copilot

## Executive Summary

This document provides architectural analysis for integrating Ralph Wiggum-style iterative execution loops with Claude Copilot's Task Copilot checkpoint system. The integration would enable autonomous, unattended task completion while maintaining the framework's token efficiency goals and leveraging existing checkpoint infrastructure.

**Key Finding:** The integration is highly synergistic. Task Copilot's checkpoint system provides the exact persistence and recovery mechanisms needed for safe iterative loops, while Ralph Wiggum patterns solve the autonomous execution gap in the current framework.

---

## 1. Integration Architecture

### 1.1 Core Concept

Ralph Wiggum's self-referential feedback loop pattern integrates with Task Copilot through three key mechanisms:

```
┌─────────────────────────────────────────────────────────────┐
│                    Iterative Task Loop                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐                        ┌────────────────┐ │
│  │   Iteration  │───checkpoint_create───▶│   Checkpoint   │ │
│  │   Execution  │                        │     Store      │ │
│  │              │◀──checkpoint_resume────│   (Task DB)    │ │
│  └──────┬───────┘                        └────────────────┘ │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐                        ┌────────────────┐ │
│  │  Quality     │                        │   Performance  │ │
│  │  Validation  │───track_iteration────▶│    Tracking    │ │
│  │  & Promises  │                        │                │ │
│  └──────┬───────┘                        └────────────────┘ │
│         │                                                    │
│         ├─────COMPLETE────▶ Exit Loop                       │
│         └─────CONTINUE────▶ Next Iteration                  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Architectural Components

| Component | Current State | Enhancement Needed | Priority |
|-----------|--------------|-------------------|----------|
| **Checkpoint System** | ✅ Exists | Add iteration metadata | P0 |
| **Agent Execution** | ✅ Exists | Add loop hooks | P0 |
| **Performance Tracking** | ✅ Exists | Add iteration metrics | P1 |
| **Validation System** | ✅ Exists | Add promise detection | P0 |
| **Stop Hooks** | ❌ Missing | Create new system | P0 |
| **Max Iteration Guard** | ❌ Missing | Add to checkpoint | P0 |

### 1.3 Data Flow

**Iteration Lifecycle:**

1. **Initialization**
   - Agent receives task via `task_get`
   - Creates initial checkpoint with `iteration: 0`
   - Stores loop configuration (max iterations, validation rules)

2. **Execution Loop**
   ```
   for iteration in 1..max_iterations:
     ├─ Load checkpoint state
     ├─ Execute agent logic (read/edit/write files)
     ├─ Create checkpoint with current state
     ├─ Check for completion promise
     ├─ Validate quality gates
     └─ If not complete: Continue to next iteration
   ```

3. **Termination**
   - **Success:** Completion promise detected → Store final work product
   - **Max iterations:** Exceeded → Mark as blocked, escalate to human
   - **Error:** Exception thrown → Create error checkpoint, rollback

### 1.4 Integration Points

**Existing Task Copilot Tools (No Changes Needed):**
- `checkpoint_create` - Already stores execution phase/step
- `checkpoint_resume` - Already restores full agent context
- `work_product_store` - Already stores final outputs
- `agent_performance_get` - Already tracks success/failure

**New Tools Required:**

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `iteration_start` | Initialize loop config | taskId, maxIterations, validationRules | iterationId |
| `iteration_next` | Advance to next iteration | taskId, previousCheckpointId | newCheckpointId |
| `iteration_validate` | Check completion/quality | taskId, checkpointId | validationResult |
| `iteration_complete` | Finalize loop | taskId, completionPromise | workProductId |

---

## 2. Hook Implementation

### 2.1 Stop Hook Architecture

**Concept:** Intercept agent completion signals to enable loop continuation.

```typescript
interface StopHook {
  id: string;
  taskId: string;
  enabled: boolean;

  // Called when agent signals completion
  onComplete: (context: AgentContext) => StopHookResult;
}

interface StopHookResult {
  action: 'complete' | 'continue' | 'escalate';
  reason: string;
  nextPrompt?: string;
  checkpoint?: CheckpointData;
}

interface AgentContext {
  taskId: string;
  iteration: number;
  executionPhase: string;
  filesModified: string[];
  validationResults: ValidationResult[];
  completionPromises: CompletionPromise[];
}
```

### 2.2 Hook Registration

**Agent Modification Pattern:**

```markdown
## Agent: me.md (Engineer)

### Task Copilot Integration

When starting iterative work:

1. task_get(taskId)
2. iteration_start({
     taskId,
     maxIterations: 10,
     validationRules: ['tests_pass', 'no_errors']
   })
3. FOR EACH ITERATION:
   a. checkpoint_create() - before risky operations
   b. Execute implementation logic
   c. iteration_validate() - check quality/promises
   d. If complete: iteration_complete()
   e. If continue: iteration_next()
```

### 2.3 Agent-Specific Hooks

| Agent | Primary Use Case | Validation Rules | Max Iterations |
|-------|-----------------|------------------|----------------|
| **@agent-me** | TDD loop | tests_pass, compiles, no_lint_errors | 15 |
| **@agent-qa** | Test refinement | coverage_met, flaky_tests_fixed | 8 |
| **@agent-ta** | Architecture iteration | constraints_met, trade_offs_documented | 5 |
| **@agent-doc** | Doc quality | readability_score, completeness_check | 6 |
| **@agent-sec** | Vulnerability remediation | vulns_fixed, scans_clean | 10 |

**Common Pattern:**
```
WHILE NOT validation_passed AND iteration < max_iterations:
  ├─ Analyze current state
  ├─ Make improvements
  ├─ Checkpoint state
  └─ Re-validate
```

---

## 3. Checkpoint Strategy for Iterations

### 3.1 Enhanced Checkpoint Schema

**Extension to existing `CheckpointRow`:**

```typescript
interface IterativeCheckpointRow extends CheckpointRow {
  // Existing fields remain unchanged

  // New iteration-specific fields
  iteration_config: string | null;     // JSON: { maxIterations, validationRules }
  iteration_number: number | null;     // Current iteration (0 = initial)
  iteration_history: string | null;    // JSON: Array of iteration summaries
  completion_promises: string | null;  // JSON: Array of detected promises
  validation_state: string | null;     // JSON: Latest validation results
}
```

**Migration SQL:**
```sql
-- Add iteration columns to checkpoints table
ALTER TABLE checkpoints ADD COLUMN iteration_config TEXT;
ALTER TABLE checkpoints ADD COLUMN iteration_number INTEGER DEFAULT 0;
ALTER TABLE checkpoints ADD COLUMN iteration_history TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN completion_promises TEXT DEFAULT '[]';
ALTER TABLE checkpoints ADD COLUMN validation_state TEXT DEFAULT '{}';

CREATE INDEX idx_checkpoints_iteration ON checkpoints(task_id, iteration_number DESC);
```

### 3.2 Checkpoint Cadence

**Strategy:** Balance recovery granularity with storage efficiency.

| Trigger | When | Retention | Purpose |
|---------|------|-----------|---------|
| **iteration_start** | Before loop begins | 7 days | Rollback to pre-loop state |
| **iteration_checkpoint** | After each iteration | 24 hours | Resume mid-loop |
| **iteration_milestone** | Every 3rd iteration | 7 days | Coarse recovery points |
| **iteration_error** | On exception | 7 days | Debug failure state |
| **iteration_complete** | Loop exit | 7 days | Final state snapshot |

**Auto-pruning:** Keep latest 3 per iteration type, delete older than retention period.

### 3.3 State Preservation

**Critical state to capture per iteration:**

```typescript
interface IterationState {
  iteration: number;
  startedAt: string;

  // Execution context
  executionPhase: string;         // e.g., "implementation", "testing"
  executionStep: number;          // Step within phase

  // File state
  filesModified: string[];        // Paths of changed files
  gitCommit?: string;             // Git SHA if using VCS

  // Validation results
  validationResults: {
    rule: string;                 // e.g., "tests_pass"
    passed: boolean;
    details: string;
    checkedAt: string;
  }[];

  // Completion signals
  completionPromises: {
    type: 'complete' | 'blocked' | 'escalate';
    detected: boolean;
    content: string;
    detectedAt?: string;
  }[];

  // Agent-specific context
  agentContext: Record<string, unknown>;

  // Performance
  iterationDurationMs: number;
  cumulativeDurationMs: number;
}
```

---

## 4. Token Efficiency

### 4.1 Context Bloat Prevention

**Problem:** Long-running loops accumulate context, triggering compaction.

**Solutions:**

| Strategy | Token Savings | Implementation Complexity | Trade-off |
|----------|--------------|--------------------------|-----------|
| **Checkpoint rotation** | ~80% | Low | Lose deep history |
| **Diff-based storage** | ~60% | Medium | Reconstruction cost |
| **Summary compression** | ~70% | Low | Lose granularity |
| **External file state** | ~90% | High | Requires VCS integration |

### 4.2 Recommended Approach: Tiered State Storage

**Tier 1: Always in Context (≤2KB)**
- Current iteration number
- Latest validation results
- Completion promises
- Current execution phase/step
- Last 3 files modified

**Tier 2: Checkpoint Storage (≤50KB per checkpoint)**
- Full iteration state
- All validation results
- Complete file list
- Agent context
- Draft content

**Tier 3: Work Product Archive (unlimited)**
- Full iteration history (all checkpoints)
- Complete file snapshots
- Detailed logs
- Performance metrics

**Token Budget per Iteration:**
```
Base agent context:        ~1,000 tokens
Current task state:        ~500 tokens
Tier 1 iteration state:    ~300 tokens
Checkpoint restoration:    ~200 tokens
─────────────────────────────────────
Total per iteration:       ~2,000 tokens
Max iterations (15):       ~30,000 tokens
```

**Mitigation:** After 10 iterations, trigger checkpoint compaction:
- Summarize iterations 1-7 into single summary (~500 tokens)
- Keep full state for iterations 8-10
- Continue with compressed history

### 4.3 Validation Efficiency

**Lazy validation:** Only run expensive checks when necessary.

```typescript
const validationStrategy = {
  cheap: ['syntax_check', 'promise_detection'],     // Every iteration
  moderate: ['lint', 'type_check'],                 // Every 2 iterations
  expensive: ['full_test_suite', 'security_scan'],  // Every 3 iterations or final
};
```

---

## 5. Safety Mechanisms

### 5.1 Guardrails Beyond Max Iterations

| Guardrail | Trigger | Action | Rationale |
|-----------|---------|--------|-----------|
| **Quality regression** | Validation score decreases 3x in row | Escalate to human | Loop may be degrading solution |
| **Token budget** | Approaching context limit | Force checkpoint compaction | Prevent compact mode trigger |
| **Thrashing detection** | Same files modified 5+ times | Mark as blocked | Likely stuck in loop |
| **Time limit** | Elapsed time > 30 min | Pause for human review | Prevent runaway costs |
| **Error threshold** | 3 consecutive errors | Rollback to last good checkpoint | System instability |
| **Validation stall** | No progress for 3 iterations | Escalate with diagnosis | May need different approach |

### 5.2 Runaway Loop Prevention

**Circuit breaker pattern:**

```typescript
interface CircuitBreaker {
  state: 'closed' | 'open' | 'half_open';
  failureCount: number;
  failureThreshold: number;
  resetTimeout: number;
  lastFailure?: Date;
}

// Example: Testing loop circuit breaker
const testCircuitBreaker: CircuitBreaker = {
  state: 'closed',
  failureCount: 0,
  failureThreshold: 3,        // Open after 3 test failures
  resetTimeout: 5 * 60 * 1000 // Try again after 5 minutes
};
```

**Implementation in iteration loop:**

```
Before each iteration:
  IF circuitBreaker.state === 'open':
    ├─ Check if resetTimeout elapsed
    ├─ If yes: Set to 'half_open', try one iteration
    └─ If no: Escalate to human immediately

  Execute iteration

  IF iteration failed:
    ├─ Increment failureCount
    ├─ IF failureCount >= failureThreshold:
    │   └─ Set state to 'open', create error checkpoint
    └─ Create checkpoint and continue

  IF iteration succeeded:
    └─ Reset failureCount to 0, set state to 'closed'
```

### 5.3 Quality Degradation Detection

**Metric tracking across iterations:**

```typescript
interface QualityMetrics {
  testCoverage: number;       // 0-100
  lintErrors: number;
  typeErrors: number;
  complexityScore: number;    // Cyclomatic complexity
  fileSize: number;           // Lines of code
  validationScore: number;    // Composite 0-100
}

// Detect degradation
function isQualityDegrading(history: QualityMetrics[]): boolean {
  const recent = history.slice(-3);
  const trend = calculateTrend(recent.map(m => m.validationScore));
  return trend < -5; // More than 5 point decline
}
```

---

## 6. Agent Modifications

### 6.1 Agents That Benefit Most

**Priority 1: High Iteration Value**

| Agent | Use Case | Benefit | Complexity |
|-------|----------|---------|------------|
| **@agent-me** | TDD loops, refactoring | ⭐⭐⭐⭐⭐ | Medium |
| **@agent-qa** | Test refinement, flaky test fixing | ⭐⭐⭐⭐⭐ | Low |
| **@agent-sec** | Vulnerability remediation | ⭐⭐⭐⭐ | Medium |

**Priority 2: Moderate Iteration Value**

| Agent | Use Case | Benefit | Complexity |
|-------|----------|---------|------------|
| **@agent-doc** | Documentation quality improvement | ⭐⭐⭐ | Low |
| **@agent-ta** | Architecture constraint validation | ⭐⭐⭐ | High |
| **@agent-do** | Infrastructure convergence loops | ⭐⭐⭐ | High |

**Priority 3: Lower Iteration Value** (not recommended initially)

| Agent | Reason |
|-------|--------|
| **@agent-sd, @agent-uxd, @agent-uids, @agent-uid** | Design tasks less amenable to automated iteration |
| **@agent-cw** | Content quality subjective, hard to validate |

### 6.2 Required Agent Changes

**Minimal agent modification pattern:**

```markdown
## New Section: Iterative Execution (add to agents)

### When to Use Iterative Mode

Use iteration loops when:
- ✅ Clear validation criteria exist (tests, lints, security scans)
- ✅ Incremental improvements are possible
- ✅ Task can run unattended (no human input needed)
- ❌ Avoid for subjective/creative tasks
- ❌ Avoid when requirements are unclear

### Iteration Protocol

1. **Initialize:**
   ```
   task_get(taskId)
   iteration_start({
     taskId,
     maxIterations: <agent-specific>,
     validationRules: [<agent-specific>]
   })
   ```

2. **Execute Loop:**
   ```
   FOR iteration in 1..maxIterations:
     checkpoint_create({
       trigger: 'auto_iteration',
       executionPhase: <current-phase>
     })

     <AGENT IMPLEMENTATION LOGIC>

     result = iteration_validate({ taskId })

     IF result.completed:
       iteration_complete({ completionPromise: result.promise })
       BREAK

     iteration_next({ taskId })
   ```

3. **Store Results:**
   ```
   work_product_store({
     taskId,
     type: <agent-type>,
     content: <final-output>
   })
   ```
```

**Agent-specific validation rules:**

**@agent-me (Engineer):**
```json
{
  "validationRules": [
    { "id": "tests_pass", "type": "command", "command": "npm test" },
    { "id": "compiles", "type": "command", "command": "tsc --noEmit" },
    { "id": "lint_clean", "type": "command", "command": "eslint ." },
    { "id": "promise_detected", "type": "content", "pattern": "<promise>COMPLETE</promise>" }
  ],
  "maxIterations": 15
}
```

**@agent-qa (QA Engineer):**
```json
{
  "validationRules": [
    { "id": "tests_pass", "type": "command", "command": "npm test" },
    { "id": "coverage_met", "type": "coverage", "threshold": 80 },
    { "id": "no_flaky", "type": "command", "command": "npm test -- --repeat=3" }
  ],
  "maxIterations": 8
}
```

**@agent-sec (Security):**
```json
{
  "validationRules": [
    { "id": "vulns_fixed", "type": "command", "command": "npm audit" },
    { "id": "sast_clean", "type": "command", "command": "semgrep --config=auto" },
    { "id": "secrets_clean", "type": "command", "command": "gitleaks detect" }
  ],
  "maxIterations": 10
}
```

---

## 7. Phased Implementation Plan

### Phase 1: Foundation (Complexity: Medium)

**Goal:** Add iteration support to checkpoint system without changing agents.

**Tasks:**

1. **Database Migration**
   - Add iteration columns to checkpoints table
   - Create indexes for iteration queries
   - Test migration on existing data
   - **Acceptance:** Schema updated, no data loss

2. **Checkpoint Enhancement**
   - Update `checkpoint_create` to accept iteration metadata
   - Update `checkpoint_resume` to restore iteration state
   - Add iteration filtering to `checkpoint_list`
   - **Acceptance:** Iteration data persists correctly

3. **Validation Framework**
   - Create validation rule engine
   - Implement command-based validators
   - Implement content-pattern validators (promise detection)
   - **Acceptance:** Can validate against configurable rules

4. **Iteration Tools**
   - Implement `iteration_start` tool
   - Implement `iteration_validate` tool
   - Implement `iteration_next` tool
   - Implement `iteration_complete` tool
   - **Acceptance:** Tools available via MCP server

**Dependencies:** None
**Risk:** Low - extends existing systems without breaking changes

---

### Phase 2: Agent Integration (Complexity: High)

**Goal:** Enable one agent (@agent-me) to use iterative loops.

**Tasks:**

1. **Stop Hook System**
   - Design hook registration mechanism
   - Implement completion signal interception
   - Create hook configuration schema
   - **Acceptance:** Can intercept and redirect agent completion

2. **@agent-me Enhancement**
   - Add iteration protocol section to agent
   - Define validation rules for common scenarios
   - Create TDD loop example
   - Test with simple refactoring task
   - **Acceptance:** Successfully completes TDD loop unattended

3. **Safety Guards**
   - Implement max iteration limit
   - Implement quality regression detection
   - Implement thrashing detection
   - Add circuit breaker for error handling
   - **Acceptance:** All guardrails trigger appropriately

4. **Performance Tracking**
   - Extend agent_performance table with iteration metrics
   - Track iteration count, duration per iteration
   - Track validation pass/fail per iteration
   - **Acceptance:** Performance metrics captured per iteration

**Dependencies:** Phase 1
**Risk:** Medium - requires careful hook implementation to avoid infinite loops

---

### Phase 3: Multi-Agent Rollout (Complexity: Medium)

**Goal:** Enable @agent-qa and @agent-sec for iterative execution.

**Tasks:**

1. **@agent-qa Enhancement**
   - Add test refinement iteration protocol
   - Define coverage and flakiness validation rules
   - Test with coverage improvement task
   - **Acceptance:** Improves test coverage iteratively

2. **@agent-sec Enhancement**
   - Add vulnerability remediation iteration protocol
   - Define security scan validation rules
   - Test with vulnerability fixing task
   - **Acceptance:** Fixes security issues iteratively

3. **Token Efficiency Optimization**
   - Implement tiered state storage
   - Add checkpoint compaction after 10 iterations
   - Implement lazy validation strategy
   - **Acceptance:** Iterations stay within token budget

4. **Monitoring & Observability**
   - Add iteration dashboard to progress_summary
   - Log iteration events to activity log
   - Create iteration performance reports
   - **Acceptance:** Can monitor iteration health in real-time

**Dependencies:** Phase 2
**Risk:** Low - reusing proven patterns from Phase 2

---

### Phase 4: Advanced Features (Complexity: High)

**Goal:** Add sophisticated iteration capabilities.

**Tasks:**

1. **Parallel Iterations**
   - Design parallel task spawning
   - Implement iteration coordination
   - Handle merge conflicts
   - **Acceptance:** Can run independent iterations in parallel

2. **Adaptive Iteration Limits**
   - Implement learning from past iterations
   - Adjust maxIterations based on task complexity
   - Use agent_performance data for predictions
   - **Acceptance:** Max iterations adapt to task characteristics

3. **External Tool Integration**
   - VCS integration for file snapshots
   - CI/CD integration for validation
   - External quality tools (SonarQube, etc.)
   - **Acceptance:** Validates using external systems

4. **Human-in-the-Loop**
   - Pause iteration for human approval
   - Request human input mid-loop
   - Review-and-continue workflow
   - **Acceptance:** Can pause and resume with human input

**Dependencies:** Phase 3
**Risk:** High - complex coordination and external dependencies

---

## 8. Trade-offs and Decision Rationale

### 8.1 Key Architectural Decisions

| Decision | Alternatives Considered | Rationale |
|----------|------------------------|-----------|
| **Extend checkpoints vs. new table** | Create separate `iterations` table | Checkpoint system already has needed recovery features; avoid duplication |
| **Stop hooks vs. agent rewrite** | Completely rewrite agent execution model | Hooks preserve existing agent logic; lower migration risk |
| **Tiered storage vs. full history** | Store complete history in work products | Balance recovery capability with token efficiency |
| **Validation rules in DB vs. code** | Hard-code validation per agent | Database storage enables runtime configuration without deploys |
| **Max iterations per agent vs. global** | Single global limit | Different agents have different iteration characteristics |

### 8.2 Failure Mode Analysis

| Failure Mode | Impact | Mitigation | Recovery |
|--------------|--------|------------|----------|
| **Infinite loop** | HIGH: Runaway costs | Circuit breaker, max iterations | Manual termination, rollback |
| **Quality degradation** | MEDIUM: Poor output | Quality regression detection | Rollback to best checkpoint |
| **Token exhaustion** | HIGH: Context overflow | Checkpoint compaction, tiered storage | Force compact mode |
| **Validation false positive** | MEDIUM: Premature completion | Multiple validation rules, human review | Manual restart |
| **Validation false negative** | LOW: Extra iterations | Max iteration limit prevents runaway | Natural termination |
| **Checkpoint corruption** | HIGH: Cannot resume | Checkpoint versioning, multiple retention | Restart from earlier checkpoint |

### 8.3 Performance Considerations

**Benefits:**
- ✅ Autonomous execution reduces human wait time
- ✅ Iterative refinement improves output quality
- ✅ Checkpoint system enables recovery from errors
- ✅ Performance tracking identifies problematic patterns

**Costs:**
- ❌ Multiple iterations consume more tokens than single-shot
- ❌ Checkpoint storage grows with iteration count
- ❌ Validation overhead per iteration
- ❌ Complexity in agent logic and error handling

**Net Assessment:** Benefits outweigh costs for tasks with clear validation criteria and high rework probability (TDD, testing, security remediation). Not cost-effective for creative/subjective tasks.

---

## 9. Success Metrics

### 9.1 Quantitative Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Autonomous completion rate** | >70% for TDD tasks | Tasks completed without human intervention |
| **Average iterations to completion** | <8 iterations | Mean iteration count across all loops |
| **Token efficiency** | <2x single-shot cost | Token cost per iteration vs. non-iterative |
| **Quality improvement** | +20% validation score | Comparison of iteration 1 vs. final |
| **Checkpoint recovery success** | >95% | Successful resumes from checkpoints |

### 9.2 Qualitative Metrics

- **Developer satisfaction:** Do developers trust the system to run unattended?
- **Output quality:** Does iterative refinement produce better results?
- **Error handling:** Are errors caught and recovered gracefully?
- **Token budget compliance:** Do iterations stay within budget?

---

## 10. Recommended Approach

### 10.1 Start Small

**Pilot Program:**
1. **Single agent:** @agent-me only
2. **Single use case:** TDD loop (write test → implement → run tests → fix → repeat)
3. **Single project:** Claude Copilot itself (dogfooding)
4. **Limited scope:** Max 5 iterations, simple validation rules

**Success criteria before expansion:**
- ✅ Completes at least 3 TDD tasks end-to-end
- ✅ No runaway loops or infinite iterations
- ✅ Token usage stays within 3x single-shot budget
- ✅ All checkpoints can be resumed successfully

### 10.2 Iterative Rollout

**Timeline (Complexity-based, not time-based):**

```
Phase 1: Foundation
├─ Complexity: Medium
├─ Prerequisites: None
└─ Deliverable: Iteration-capable checkpoint system

Phase 2: Agent Integration (@agent-me)
├─ Complexity: High
├─ Prerequisites: Phase 1
└─ Deliverable: Working TDD loops

Phase 3: Multi-Agent Rollout (@agent-qa, @agent-sec)
├─ Complexity: Medium
├─ Prerequisites: Phase 2 validated
└─ Deliverable: Multiple iteration patterns

Phase 4: Advanced Features (Optional)
├─ Complexity: High
├─ Prerequisites: Phase 3 validated
└─ Deliverable: Parallel, adaptive, human-in-loop
```

### 10.3 Critical Path

**Must-have for MVP:**
- ✅ Iteration metadata in checkpoints (Phase 1)
- ✅ Basic validation engine (Phase 1)
- ✅ Stop hook system (Phase 2)
- ✅ Max iteration safety guard (Phase 2)
- ✅ One working agent (@agent-me) (Phase 2)

**Nice-to-have (defer to later):**
- ⏸️ Token optimization (Phase 3)
- ⏸️ Advanced safety guards (Phase 2-3)
- ⏸️ Multiple agents (Phase 3)
- ⏸️ All advanced features (Phase 4)

---

## 11. Open Questions

1. **Completion Promise Format:** Should we standardize on `<promise>COMPLETE</promise>` or allow custom patterns per agent?

2. **Checkpoint Compaction Strategy:** When should we trigger compaction? Token threshold, iteration count, or time-based?

3. **Validation Rule Distribution:** Should rules live in agent markdown, database, or separate config files?

4. **Error Recovery Philosophy:** Aggressive retry with rollback, or conservative early escalation?

5. **Performance vs. Quality:** Should we optimize for fewer iterations (faster) or better outcomes (more iterations)?

6. **Human Intervention Points:** Should humans approve iteration plans upfront, mid-loop, or only on failure?

---

## 12. Appendix: Reference Implementation

### 12.1 Example TDD Loop with @agent-me

```markdown
## Task: Implement User Authentication

**Validation Rules:**
- tests_pass: `npm test -- auth.test.ts`
- compiles: `tsc --noEmit`
- lint_clean: `eslint src/auth.ts`
- promise: `<promise>COMPLETE</promise>`

**Iteration Log:**

Iteration 1:
├─ Wrote failing test for login()
├─ Validation: tests_pass=false (expected)
└─ Checkpoint: CP-001

Iteration 2:
├─ Implemented basic login() logic
├─ Validation: tests_pass=true, compiles=true, lint_clean=false
└─ Checkpoint: CP-002

Iteration 3:
├─ Fixed ESLint errors (missing return type)
├─ Validation: All rules pass
├─ Detected: <promise>COMPLETE</promise>
└─ Completed: WP-123
```

### 12.2 Checkpoint Structure Example

```json
{
  "id": "CP-002",
  "task_id": "TASK-456",
  "sequence": 2,
  "trigger": "auto_iteration",

  "iteration_config": {
    "maxIterations": 15,
    "validationRules": [
      { "id": "tests_pass", "type": "command", "command": "npm test" },
      { "id": "compiles", "type": "command", "command": "tsc --noEmit" }
    ]
  },

  "iteration_number": 2,
  "iteration_history": [
    {
      "iteration": 1,
      "validationResults": [
        { "rule": "tests_pass", "passed": false, "details": "1 test failed" }
      ],
      "durationMs": 45000
    },
    {
      "iteration": 2,
      "validationResults": [
        { "rule": "tests_pass", "passed": true },
        { "rule": "compiles", "passed": true }
      ],
      "durationMs": 38000
    }
  ],

  "completion_promises": [],
  "validation_state": {
    "tests_pass": { "passed": true, "lastCheck": "2025-12-30T10:23:45Z" },
    "compiles": { "passed": true, "lastCheck": "2025-12-30T10:23:50Z" }
  },

  "agent_context": {
    "lastFileEdited": "src/auth.ts",
    "testCommand": "npm test -- auth.test.ts"
  },

  "created_at": "2025-12-30T10:23:50Z",
  "expires_at": "2025-12-31T10:23:50Z"
}
```

---

## 13. Conclusion

The integration of Ralph Wiggum iterative loops with Task Copilot's checkpoint system is **highly feasible and architecturally sound**. The existing checkpoint infrastructure provides 80% of the required functionality; the remaining 20% involves:

1. Adding iteration metadata to checkpoints
2. Creating a validation engine
3. Implementing stop hooks for loop control
4. Enhancing 1-3 agents with iteration protocols

**Recommendation:** Proceed with **Phase 1 and Phase 2** as a proof-of-concept. Focus on @agent-me TDD loops as the highest-value, lowest-risk pilot. Validate assumptions about token efficiency and autonomous completion rates before expanding to additional agents.

**Risk Assessment:** LOW to MEDIUM
- Low risk in Phase 1 (extends existing systems)
- Medium risk in Phase 2 (hook system is novel)
- High value if successful (autonomous task completion)

**Next Steps:**
1. Review this architecture with stakeholders
2. Approve/modify Phase 1 task breakdown
3. Create detailed technical design for checkpoint schema changes
4. Prototype validation engine independently
5. Begin Phase 1 implementation

---

**Document Metadata:**
- **Author:** Claude Code (@agent-ta)
- **Date:** 2025-12-30
- **Version:** 1.0
- **Status:** Proposal
- **Target Audience:** Claude Copilot development team
- **Estimated Reading Time:** 20 minutes
- **Word Count:** ~5,200 words
