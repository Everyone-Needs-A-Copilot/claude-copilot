# Working Protocol

> **Purpose:** HARD GATE - Execute agents BEFORE responding to user requests
> **Applies to:** All product repositories
> **Token Budget:** ~800 tokens

## Core Principle

**Your FIRST action on ANY request must be to invoke the appropriate agent. Do NOT write a response first. Execute agents, wait for results, then respond with findings.**

---

## Protocol Declaration — RETIRED (2026-07-14, DEC-2)

The `[PROTOCOL: ...]` prefix formerly required on every response is retired. Measured adoption was 0.0% (`protocol-declaration-rate-baseline`), and nothing in the hook pipeline (`.claude/hooks/user-prompt-submit.sh`) ever checked for it — the requirement was unenforced, not too heavy for real turns. **Omitting it is not a violation.**

The discipline the declaration was meant to signal — invoke the right specialist before responding, never substitute the main session for a specialist — is retained in full (see Request Classification and Phase 1 below) and is measured directly by `delegation-rate-baseline` (tool-share median ~40.5–40.9%), not by a prefix convention.

---

## Request Classification

| Type | Indicators | First Agent |
|------|------------|-------------|
| **Defect/Bug** | "broken", "not working", "error", unexpected behavior | `@agent-qa` |
| **Experience** | UI, UX, feature, user-facing change | `@agent-sd` + `@agent-uxd` |
| **Technical** | Architecture, backend, refactor, performance | `@agent-ta` |
| **Question** | "How does...", "Where is...", "Explain..." | None (respond directly) |

---

## Phase 1: Execute Understanding Agent (BEFORE RESPONDING)

### Defect/Bug
```
1. If no reproduction info → ASK for screenshot/URL/steps
2. Once you have info → INVOKE @agent-qa to reproduce
3. WAIT for results
4. THEN respond with findings
```

### Experience Request
```
1. INVOKE @agent-sd (map user journey)
2. INVOKE @agent-uxd (interaction + task flow design)
3. WAIT for results
4. THEN respond with recommendations/questions
```

### Technical Request
```
1. INVOKE @agent-ta (assess approach)
2. WAIT for results
3. THEN respond with plan
```

---

## Phase 2: Present Findings + Plan (AFTER agent completes)

Your response MUST include:
1. **Summary**: "Based on @agent-X's investigation..."
2. **Root cause/Recommendation**: Specific file:line or approach
3. **Proposed plan**: Files to modify, agents to use
4. **Pre-Execution Checklist**: Filled with real data
5. **Ask**: "Shall I proceed with this plan?"

### Pre-Execution Checklist

```
## Pre-Execution Checklist

### Understanding
- [x] Request type: [Defect / Experience / Technical]
- [x] Agent used: @agent-___
- [x] Finding: [what agent discovered at file:line]

### Planning
- [ ] Files to modify: [list with line numbers]
- [ ] Execution agents: @agent-___ for [task]

### Approval
- [ ] User approved: AWAITING
```

**Do NOT proceed until user confirms.**

---

## Phase 3: Execute (with specialized agents)

1. Use Task Copilot CLI to track work:
   - Create tasks with `tc task create --title "..." --prd <id> --json`
   - Update status with `tc task update <id> --status in_progress --json`
   - Store outputs with `tc wp store --task <id> --type <t> --title "..." --content "..." --json` for details over 500 chars
2. Launch specialized agents:
   - Stack-specific agents for implementation (see Agent Reference below)
   - `@agent-qa` for testing
3. Track progress, don't batch completions

---

## Phase 4: Verify (MANDATORY GATE — NEVER SKIP)

1. @agent-qa MUST run after every @agent-me implementation — automatic, not optional
2. @agent-qa MUST write new tests for changed/added code:
   - Backend changes: unit tests + integration tests
   - Frontend changes: Playwright E2E tests (zero console errors, user interactions, data flow)
   - Both: all test types required
3. All tests must pass before task is marked complete
4. If visual verification also needed, ask user AFTER automated tests pass
5. **Task is NOT done until automated tests pass AND user confirms**

**Artifact-gated verdicts (5.10.0+):** A bare `VERDICT: APPROVED` no longer unblocks the gate. @agent-qa and @agent-sec MUST include an `ARTIFACT:` line citing real evidence:

```
VERDICT: APPROVED
ARTIFACT: test-run|pytest tests/ exit=0 "47 passed, 0 failed"
```

If the gate is not unblocking, check that the agent included an `ARTIFACT:` line. Escape hatch: `COPILOT_QA_GATE=off`. After 3 consecutive failures the gate auto-unblocks with an advisory. See [hooks/README.md](../../.claude/hooks/README.md).

---

## Anti-Patterns (NEVER DO THESE)

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| "Let me investigate..." then reading files yourself | You're not the investigator, agents are |
| "I'll use @agent-qa" without invoking it | Saying ≠ Doing |
| Writing a plan before running understanding agent | Plan should be based on agent findings |
| Skipping to code changes | No understanding = wrong fix |
| Declaring "done" after build success | Build passing ≠ bug fixed |
| Skipping QA after implementation | Tests catch regressions and verify correctness |
| Relying only on existing tests passing | New code needs new tests |

---

## Agent Reference (Quick Lookup)

### Understanding Phase

| Task | Agent | Purpose |
|------|-------|---------|
| Reproduce bugs | `@agent-qa` | Confirm issue exists, document steps |
| Map user journey | `@agent-sd` | Service design, experience mapping |
| Assess approach | `@agent-ta` | Architecture, technical feasibility |

### Execution Phase

| Task | Agent | Purpose |
|------|-------|---------|
| Code implementation | `@agent-me` | Features, bug fixes, refactoring |
| DevOps/Infrastructure | `@agent-do` | Deployment, Docker, CI/CD |
| Documentation | `@agent-doc` | Technical writing, API docs |

### Design Phase

| Task | Agent | Purpose |
|------|-------|---------|
| Interaction + Task Flow Design | `@agent-uxd` | Task flows, wireframes, usability |
| Visual Design System | `@agent-uids` | Color, typography, design tokens |
| Component Specs | `@agent-uid` | Component implementation blueprints |

### Verification Phase

| Task | Agent | Purpose |
|------|-------|---------|
| Test writing | `@agent-qa` | Unit, integration, E2E tests |
| Security review | load `security/stride-dread` skill | STRIDE/DREAD analysis — not a dedicated agent |

---

## Project-Specific Overrides

Projects may extend this protocol with custom agents or rules via the extension system. See [the Extension Spec](../40-extensions/00-extension-spec.md) for details.

---

_Last Updated: December 2025_
