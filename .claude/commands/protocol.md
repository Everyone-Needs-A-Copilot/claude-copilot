# Protocol Enforcement

You are starting a new conversation. **The Agent-First Protocol is now active.**

All guardrails, agent selection rules, token efficiency rules, and routing tables from CLAUDE.md apply. This file defines protocol-specific behavior only.

## Command Argument Handling

**Usage:**
- `/protocol` - Interactive mode (select task type manually)
- `/protocol [description]` - Auto-detect intent and route to appropriate agent chain
- `/protocol [modifier:] [action:] [description]` - Magic keywords for model selection and shortcuts

**Examples:**
```
/protocol add user voice profiles          → Experience Flow (sd → uxd → uids → ta → me)
/protocol fix login authentication bug     → Defect Flow (qa → me → qa)
/protocol refactor auth module             → Technical Flow (ta → me)
/protocol improve the dashboard            → Clarification Flow (ask user)
/protocol eco: fix: the login bug          → Auto-select model + Defect Flow
/protocol opus: add: dark mode feature     → Force Opus + Experience Flow
```

---

## Magic Keywords

Keywords must appear at the start of the message. Max 1 modifier + 1 action. Order: modifier, action, description. Case-insensitive.

**Modifier keywords:**

| Keyword | Effect |
|---------|--------|
| `eco:` | Low effort reasoning (cost-optimized, auto-select model) |
| `fast:` | Medium effort reasoning (auto-select model) |
| `max:` | Maximum reasoning depth (auto-select model) |
| `auto:` / `ralph:` | Auto-select model and effort |
| `opus:` | Force Claude Opus |
| `sonnet:` | Force Claude Sonnet |
| `haiku:` | Force Claude Haiku |

**Action keywords:**

| Keyword | Flow | Agent Chain |
|---------|------|-------------|
| `fix:` | Defect | qa → me → qa |
| `add:` | Experience | sd → uxd → uids → ta → me |
| `refactor:` | Technical | ta → me |
| `optimize:` | Technical | ta → me |
| `test:` | Direct | @agent-qa |
| `doc:` | Direct | @agent-doc |
| `deploy:` | Direct | @agent-do |

When keywords are detected, show `[KEYWORDS DETECTED]` with model and action info before the protocol declaration.

---

## Intent Detection & Flow Routing

When an argument is provided: parse magic keywords first, then use action keywords or text analysis to detect intent, then route to the appropriate agent chain.

### Flow Definitions

| Flow | Detection Keywords | Agent Chain | Checkpoints |
|------|-------------------|-------------|-------------|
| **A: Experience** (default) | add, create, build, feature, new, UI, UX, screen, page, component, dashboard, flow, journey, visual, layout, redesign | sd → uxd → uids → ta → me | After sd, uxd, uids |
| **B: Defect** | bug, broken, fix, error, crash, issue, not working, failing, regression, exception, 500, 404, timeout | qa → me → qa | After qa diagnosis, after me fix |
| **C: Technical** | refactor, optimize, architecture, performance, scale, database, API, backend, migrate, upgrade, decouple | ta → me | After ta planning |
| **D: Clarification** | improve, enhance, update, change, modify, better, faster, cleaner (ambiguous) | Ask user first | N/A |

### Clarification Prompt

When intent is ambiguous, present:
```
[PROTOCOL: CLARIFYING | Action: ASKING]

I detected an ambiguous request: "[description]"

What type of improvement?
1. User experience → Experience Flow
2. Technical → Technical Flow
3. Bug fix → Defect Flow
4. Not sure, help me decide
```

---

## Protocol Declaration

Every response MUST start with:
```
[PROTOCOL: <TYPE> | Agent: @agent-<name> | Action: <INVOKING|ASKING|RESPONDING|CHECKPOINT>]
```

With extension info when applicable: `@agent-<name> (extended)` or `@agent-<name> (base - extension unavailable)`.

---

## Checkpoint System

**Explicit approval required.** Never auto-proceed. User must explicitly approve to continue.

### Checkpoint Template

After each design stage, present:
```
[PROTOCOL: <TYPE> | Agent: @agent-<name> | Action: CHECKPOINT]

Task: TASK-xxx | WP: WP-xxx

[~100 token summary from agent]

Key decisions:
- [Decision 1]
- [Decision 2]

---
Does this align with your vision?

Options:
1. Yes, proceed to [next stage]
2. No, I need changes: [describe what to change]
3. Skip [next stage] (warning: you'll miss [benefit])
4. Go back to [previous stage]
5. Show me the full work product (WP-xxx)

[Wait for explicit user response]
```

**Verbosity levels:** Default (~100 tokens), `--verbose` (~200 tokens), `--minimal` (~50 tokens, y/n only).

### Handling Checkpoint Responses

| Option | User Signals | Action |
|--------|-------------|--------|
| 1. Approve | "yes", "1", "y", "looks good", "continue" | Proceed to next stage with 50-char handoff context |
| 2. Changes | "no", "2", "change X", contains feedback | Re-invoke agent with user feedback as constraint. Max 3 iterations before suggesting restart. |
| 3. Skip | "skip", "3", "go to next" | Warn what they miss, then proceed to next stage |
| 4. Go Back | "back", "4", "go back" | Save current as draft, re-invoke previous stage |
| 5. Details | "show", "5", "details", "WP-" | Call `work_product_get()`, display, re-present options |

---

## Agent Handoff Protocol

Between agents in a chain, pass **50-char context maximum** via `agent_handoff()`. Final agent (ta) receives ALL prior work product IDs via `sourceSpecifications` metadata.

---

## Explicit Flags (Escape Hatches)

| Flag | Effect |
|------|--------|
| `--technical` | Force technical flow (ta → me) |
| `--defect` | Force defect flow (qa → me → qa) |
| `--experience` | Force experience flow (sd → uxd → uids → ta → me) |
| `--no-checkpoints` | Run full chain without pausing for approval |
| `--verbose` | Show detailed summaries (~200 tokens) |
| `--minimal` | Show minimal summaries (~50 tokens, y/n only) |
| `--skip-sd` | Skip service design stage |
| `--skip-uxd` | Skip UX design stage |
| `--skip-uids` | Skip UI design stage |
| `--design-only` | Stop after design stages (no ta/me) |

---

## Mid-Flow Overrides

User can interrupt at any checkpoint:

| User Command | Effect |
|--------------|--------|
| "Skip to code" / "Skip the rest" | Bypass remaining design stages, go to ta → me |
| "Pause here" | Create checkpoint, exit flow (use `/pause`) |
| "Restart" | Discard current work, start fresh |
| "Go back to [stage]" | Return to previous stage for revision |

---

## Orchestration

The main session orchestrates agent chains. For each flow:

1. Detect intent (from keywords, action keywords, or text analysis)
2. Show protocol declaration with flow and first agent
3. Invoke first agent in chain
4. Present checkpoint with options 1-5 after agent completes
5. Handle user response (approve/change/skip/back/details)
6. Repeat for each agent in chain
7. Present completion summary after final agent

**Agent invocation pattern:** Show `[PROTOCOL: ... | Action: INVOKING]`, call agent with task ID/description and handoff context, wait for response, then present checkpoint or completion.

**Change request handling:** Re-invoke same agent with user feedback as `CONSTRAINT`. Track iterations; warn after 3.

**Skip warning pattern:** When user skips a stage, warn what they miss (e.g., no design tokens, visual inconsistency) and confirm before proceeding.

---

## Extension Resolution

Before invoking any agent:

1. Call `extension_get(agent_id)` to check for extensions
2. Apply: `override` replaces agent entirely, `extension` merges with base
3. If extension has `requiredSkills`, verify via `skill_get`. Apply `fallbackBehavior` if unavailable: `use_base` (silent), `use_base_with_warning`, or `fail`
4. No extension: use base agent unchanged

---

## Constitution Loading

Read `CONSTITUTION.md` from project root. If exists: inject into context, note `[Constitution: Active]`, Constitution takes precedence. If missing: continue normally, note `[Constitution: Not Found]`.

---

## Task Copilot Integration

1. Check existing initiative: `initiative_get()` + `progress_summary()`
2. Create PRD if needed: `prd_create({ title, description, content })`
3. Create tasks: `task_create({ title, prdId, assignedAgent, metadata })`
4. Link initiative: `initiative_link()` + `initiative_update()`
5. Pass task IDs when invoking agents; they store work products and return ~100 token summaries
6. Use `progress_summary()` for status checks (never load full task lists)
7. End of session: `initiative_update()` with currentFocus, nextAction, decisions, lessons

---

## Knowledge Status Check

| Knowledge Status | User Intent | Action |
|-----------------|-------------|--------|
| Configured | Any | Proceed normally |
| Not configured | Experience flow + brand/product keywords | Offer: "Run `/knowledge-copilot` to set up shared knowledge" |
| Not configured | Technical/Defect | Proceed without mention |

Never force or block on knowledge setup. Offer once per session when relevant.

---

## Continuation Detection

When agents stop without `<promise>COMPLETE</promise>` or `<promise>BLOCKED</promise>`: auto-resume if in iteration loop, otherwise prompt user. Warn at >5 continuations, block at >10 (runaway protection).

---

## Acknowledge

Respond with:
```
Protocol active. [Constitution: Active/Not Found]
Ready for your request.
```

Or with knowledge tip if applicable (see Knowledge Status Check above).
