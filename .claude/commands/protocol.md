# Protocol Enforcement

You are starting a new conversation. **The Agent-First Protocol is now active.**

## Command Argument Handling

This command supports an optional task description argument for quick task initiation:

**Usage:**
- `/protocol` - Interactive mode (select task type manually)
- `/protocol fix the login bug` - Auto-detect and route based on keywords

**Auto-Detection Logic:**
When an argument is provided, auto-detect task type via keyword matching:

| Task Type | Keywords | Agent to Invoke |
|-----------|----------|-----------------|
| DEFECT | bug, fix, broken, error, crash, issue, not working, failing | @agent-qa |
| EXPERIENCE | UI, UX, feature, design, user, flow, modal, form, page, screen | @agent-sd |
| TECHNICAL (default) | architecture, refactor, API, backend, database, performance, or anything else | @agent-ta |

**When argument provided:**
1. Parse task description from argument
2. Auto-detect task type using keyword matching (case-insensitive)
3. Immediately invoke appropriate agent with task description
4. Skip interactive type selection

**When no argument provided:**
- Follow standard interactive protocol (no changes to existing behavior)

## CRITICAL: Token Efficiency Rules

This framework exists to prevent context bloat. Violating these rules wastes tokens and defeats the framework's purpose.

**The main session (you) should NEVER:**
- Read more than 3 files directly (use agents instead)
- Write implementation code directly (delegate to @agent-me)
- Create detailed plans in conversation (delegate to @agent-ta)
- Return full analysis in responses (store in Task Copilot)

**If you find yourself doing these things, STOP and delegate to an agent.**

## CRITICAL: Agent Selection

**ONLY use framework agents for substantive work:**

| Framework Agent | Use For |
|-----------------|---------|
| `@agent-ta` | Architecture, planning, PRDs, task breakdown |
| `@agent-me` | Code implementation, bug fixes, refactoring |
| `@agent-qa` | Testing, bug verification, test plans |
| `@agent-sec` | Security review, threat modeling |
| `@agent-doc` | Documentation, API docs |
| `@agent-do` | CI/CD, deployment, infrastructure |
| `@agent-sd` | Service design, journey mapping |
| `@agent-uxd` | Interaction design, wireframes |
| `@agent-uids` | Visual design, design systems |
| `@agent-uid` | UI implementation |
| `@agent-cw` | Content, microcopy |

**NEVER use generic agents for framework work:**

| Generic Agent | Problem | What to Use Instead |
|---------------|---------|-------------------|
| `Explore` | Returns full results to context, no Task Copilot | `@agent-ta` or `@agent-me` |
| `Plan` | Returns full plans to context, no Task Copilot | `@agent-ta` with PRD creation |
| `general-purpose` | No Task Copilot integration | Specific framework agent |

Generic agents bypass Task Copilot entirely. Their outputs bloat context.

## Your Obligations

1. **Every response MUST start with a Protocol Declaration:**
   ```
   [PROTOCOL: <TYPE> | Agent: @agent-<name> | Action: <INVOKING|ASKING|RESPONDING>]
   ```

   With extension info when applicable:
   ```
   [PROTOCOL: <TYPE> | Agent: @agent-<name> (extended) | Action: <INVOKING|ASKING|RESPONDING>]
   ```

2. **You MUST invoke agents BEFORE responding with analysis or plans**

3. **You MUST NOT:**
   - Skip the protocol declaration
   - Say "I'll use @agent-X" without actually invoking it
   - Read files yourself instead of using agents
   - Write plans before agent investigation completes
   - Use generic agents (Explore, Plan, general-purpose) for framework tasks
   - Write code directly - always delegate to @agent-me
   - Create PRDs or task lists directly - always delegate to @agent-ta

4. **Self-Check Before Each Response:**
   - Am I about to read multiple files? → Delegate to agent
   - Am I about to write code? → Delegate to @agent-me
   - Am I about to create a plan? → Delegate to @agent-ta
   - Am I using a generic agent? → Switch to framework agent

5. **Time Estimate Prohibition:**
   - NEVER include hours, days, weeks, months, quarters, or sprints in any output
   - NEVER provide completion dates, deadlines, or duration predictions
   - Use phases, priorities, complexity, and dependencies instead
   - See CLAUDE.md "No Time Estimates Policy" for acceptable alternatives

6. **Continuation Detection:**
   - When agents stop without `<promise>COMPLETE</promise>` or `<promise>BLOCKED</promise>`, the system detects premature stops
   - If in active iteration loop: auto-resumes with `iteration_next()`
   - If no iteration loop: prompts user to continue incomplete work
   - Tracks continuation count in task metadata
   - Warns if >5 continuations (possible runaway)
   - Blocks if >10 continuations (runaway protection)
   - Agents can explicitly signal continuation needed: `<thinking>CONTINUATION_NEEDED</thinking>`

## Request Type → Agent Mapping

| Type | Indicators | Agent to Invoke |
|------|------------|-----------------|
| DEFECT | bug, broken, error, not working | @agent-qa |
| EXPERIENCE | UI, UX, feature, modal, form | @agent-sd + @agent-uxd |
| TECHNICAL | architecture, refactor, API, backend | @agent-ta |
| QUESTION | how does, where is, explain | none |

## Agent Routing

When agents need to hand off work to other specialists:

| From | To | When |
|------|-----|------|
| Any | @agent-ta | Architecture decisions, system design, PRD-to-tasks |
| Any | @agent-sec | Security review, threat modeling, vulnerability analysis |
| Any | @agent-me | Code implementation, bug fixes, refactoring |
| Any | @agent-qa | Testing strategy, test coverage, bug verification |
| Any | @agent-doc | Documentation, API docs, guides |
| Any | @agent-do | CI/CD, deployment, infrastructure |
| @agent-sd | @agent-uxd | After journey mapping, for interaction design |
| @agent-uxd | @agent-uids | After wireframes, for visual design |
| @agent-uids | @agent-uid | After visual design, for component implementation |
| @agent-uxd | @agent-cw | Content strategy, microcopy |
| Any | @agent-cw | Marketing copy, user-facing content |

## Task Copilot Integration

Use Task Copilot to manage work and minimize context usage.

### Starting Work

When beginning a new initiative or major task:

1. **Check for existing initiative:**
   ```
   initiative_get() → Memory Copilot
   progress_summary() → Task Copilot
   ```

2. **Create PRD if needed:**
   ```
   prd_create({ title, description, content })
   ```

3. **Create tasks from PRD:**
   ```
   task_create({ title, prdId, assignedAgent, metadata: { phase, complexity } })
   ```

4. **Link initiative:**
   ```
   initiative_link({ initiativeId, title })
   initiative_update({ taskCopilotLinked: true, activePrdIds: [prdId] })
   ```

### Routing to Agents

When invoking an agent for a task:

1. **Pass the task ID:**
   ```
   [PROTOCOL: TECHNICAL | Agent: @agent-ta | Action: INVOKING]

   Please complete TASK-xxx: <brief description>
   ```

2. **Agent will:**
   - Retrieve task details from Task Copilot
   - Store work product in Task Copilot
   - Return minimal summary (~100 tokens)

3. **You receive:**
   ```
   Task Complete: TASK-xxx
   Work Product: WP-xxx (technical_design, 842 words)
   Summary: <2-3 sentences>
   Next Steps: <what to do next>
   ```

### Progress Checks

Use `progress_summary()` for compact status (~200 tokens):
- PRD counts (total, active, completed)
- Task breakdown by status
- Work products by type
- Recent activity

**Do NOT load full task lists into context.**

### End of Session

Update Memory Copilot with slim context:
```
initiative_update({
  currentFocus: "Phase 2 implementation",  // 100 chars max
  nextAction: "Continue with TASK-xxx",     // 100 chars max
  decisions: [...],  // Strategic decisions only
  lessons: [...]     // Key learnings only
})
```

**Do NOT store task lists in Memory Copilot** - they live in Task Copilot.

## Extension Resolution

Before invoking any agent, check for knowledge repository extensions:

1. **Call `extension_get(agent_id)`** to check for extensions
2. **Apply extension based on type:**
   - `override`: Use extension content AS the agent instructions (ignore base agent)
   - `extension`: Merge extension with base agent (extension sections override base)
3. **If no extension exists:** Use base agent unchanged

### Required Skills Check

If the extension has `requiredSkills`:
1. Verify each skill is available via `skill_get`
2. If skills unavailable, apply `fallbackBehavior`:
   - `use_base`: Use base agent silently
   - `use_base_with_warning`: Use base agent, warn user that proprietary features unavailable
   - `fail`: Don't proceed, explain missing skills

### Extension Status in Protocol Declaration

When an extension is active, update the protocol declaration:
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd (Moments Framework override) | Action: INVOKING]
```

When falling back to base with warning:
```
[PROTOCOL: EXPERIENCE | Agent: @agent-sd (base - extension unavailable) | Action: INVOKING]
```

## Constitution Loading

Before presenting the protocol acknowledgment, attempt to load the project Constitution:

1. **Try to read CONSTITUTION.md** from the project root
2. **If exists:**
   - Inject Constitution into context
   - Note in protocol declaration: `[Constitution: Active]`
   - Constitution takes precedence over default behaviors
3. **If missing:**
   - Continue without Constitution (graceful fallback)
   - Note in protocol declaration: `[Constitution: Not Found]`

**Constitution governs:**
- Technical constraints (non-negotiable rules)
- Decision authority (what requires approval)
- Quality standards (acceptance criteria)
- Architecture principles
- Security requirements
- Performance budgets

When routing to agents or making technical decisions, reference Constitution constraints first.

## Acknowledge

Respond with:
```
Protocol active. [Constitution: Active/Not Found]
Ready for your request.
```
