# Working Protocol

> **Purpose:** HARD GATE - Execute agents BEFORE responding to user requests
> **Applies to:** All product repositories
> **Token Budget:** ~800 tokens

## Core Principle

**Your FIRST action on ANY request must be to invoke the appropriate agent. Do NOT write a response first. Execute agents, wait for results, then respond with findings.**

---

## REQUIRED: Protocol Declaration

**Before ANY other output, you MUST emit this declaration:**

```
[PROTOCOL: <TYPE> | Agent: @agent-<name> | Action: <INVOKING|ASKING|RESPONDING>]
```

**Examples:**
- `[PROTOCOL: DEFECT | Agent: @agent-qa | Action: INVOKING]`
- `[PROTOCOL: DEFECT | Agent: none | Action: ASKING]` (when you need info first)
- `[PROTOCOL: EXPERIENCE | Agent: @agent-sd, @agent-uxd | Action: INVOKING]`
- `[PROTOCOL: TECHNICAL | Agent: @agent-ta | Action: INVOKING]`
- `[PROTOCOL: QUESTION | Agent: none | Action: RESPONDING]`

**If your response does not start with `[PROTOCOL: ...]`, you are violating the protocol.**

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
2. INVOKE @agent-uxd (interaction design) - parallel
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

1. Use Task Copilot to track work:
   - Create tasks with `task_create()`
   - Update status with `task_update({ id, status: "in_progress" })`
   - Store outputs with `work_product_store()` for details over 500 chars
2. Launch specialized agents:
   - Stack-specific agents for implementation (see Agent Reference below)
   - `@agent-qa` for testing
3. Track progress, don't batch completions

---

## Phase 4: Verify (NEVER SKIP)

1. Use `@agent-qa` to verify changes work as expected
2. If visual verification needed, ask user to test specific URL
3. **Do NOT declare "done" until user confirms it works**

---

## Anti-Patterns (NEVER DO THESE)

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| "Let me investigate..." then reading files yourself | You're not the investigator, agents are |
| "I'll use @agent-qa" without invoking it | Saying ≠ Doing |
| Writing a plan before running understanding agent | Plan should be based on agent findings |
| Skipping to code changes | No understanding = wrong fix |
| Declaring "done" after build success | Build passing ≠ bug fixed |

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
| UX/Interaction | `@agent-uxd` | Task flows, wireframes, usability |
| Visual Design | `@agent-uids` | Colors, typography, visual hierarchy |
| UI Implementation | `@agent-uid` | CSS, Tailwind, component styling |
| Content/Copy | `@agent-cw` | Microcopy, error messages, UI text |

### Verification Phase

| Task | Agent | Purpose |
|------|-------|---------|
| Test writing | `@agent-qa` | Unit, integration, E2E tests |
| Security review | `@agent-sec` | Vulnerability assessment |

---

## Project-Specific Overrides

Projects may extend this protocol with custom agents or rules via the extension system. See [EXTENSION-SPEC.md](../EXTENSION-SPEC.md) for details.

---

_Last Updated: December 2025_
