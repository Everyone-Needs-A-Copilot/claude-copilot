# CLAUDE.md

This file provides guidance to Claude Code when working with the Claude Copilot framework.

---

## CRITICAL: Main Session Guardrails

**These rules exist to prevent context bloat. Violating them wastes tokens and defeats the framework's purpose.**

### What You MUST NEVER Do

| Action | Why It's Wrong | What To Do Instead |
|--------|---------------|-------------------|
| Write implementation code | Code belongs in work products | Delegate to `@agent-me` |
| Create detailed plans | Plans belong in Task Copilot | Delegate to `@agent-ta` |
| Use `Explore` agent | Returns full content to context | Use `@agent-ta` or `@agent-me` |
| Use `Plan` agent | Returns full plans to context | Use `@agent-ta` with PRD |
| Use `general-purpose` agent | No Task Copilot integration | Use specific framework agent |

### What You Should AVOID

| Action | Why It's Suboptimal | What To Do Instead |
|--------|-------------------|-------------------|
| Read more than 8 files | Prefer delegation for large exploration | Delegate to framework agent |
| Return detailed analysis | Fills context with text | Store as work product |

### Self-Check Before Every Response

Ask yourself:

1. **Am I about to read many files (>8)?** → CONSIDER delegating to agent.
2. **Am I about to write code?** → STOP. Delegate to `@agent-me`.
3. **Am I about to create a plan?** → STOP. Delegate to `@agent-ta`.
4. **Am I using a generic agent?** → STOP. Switch to framework agent.
5. **Is my response going to be long?** → CONSIDER storing details in Task Copilot.

### Framework Agents vs Generic Agents

**ONLY use framework agents** - they integrate with Task Copilot:

| Framework Agent | Domain | Stores Work Products |
|-----------------|--------|---------------------|
| `@agent-ta` | Architecture, planning | ✅ Yes |
| `@agent-me` | Code implementation | ✅ Yes |
| `@agent-qa` | Testing | ✅ Yes |
| `@agent-sec` | Security | ✅ Yes |
| `@agent-doc` | Documentation | ✅ Yes |
| `@agent-do` | DevOps | ✅ Yes |
| `@agent-sd` | Service design | ✅ Yes |
| `@agent-uxd` | UX design | ✅ Yes |
| `@agent-uids` | UI design | ✅ Yes |
| `@agent-uid` | UI implementation | ✅ Yes |
| `@agent-cw` | Content | ✅ Yes |

**NEVER use generic agents** - they bypass Task Copilot:

| Generic Agent | Problem |
|---------------|---------|
| `Explore` | Returns full file contents to main context |
| `Plan` | Returns full plans to main context |
| `general-purpose` | No Task Copilot, returns everything to context |

### Expected Token Usage Per Task

| Task Type | With Framework | Without Framework |
|-----------|---------------|-------------------|
| Research + Plan | ~2,000 tokens (summary only) | ~80,000+ tokens (full content) |
| Implementation | ~2,000 tokens (summary only) | ~40,000+ tokens (full code) |
| Full initiative | ~8,000 tokens | ~200,000+ tokens |

**If you're hitting compact frequently, consider delegating more to framework agents.**

---

## Overview

**Claude Copilot** is a complete AI-enabled development framework solving five challenges:

| Challenge | Solution | Component |
|-----------|----------|-----------|
| Lost memory, wasted tokens | Persistent memory + semantic search | **Memory Copilot** |
| Generic AI lacks expertise | Specialized agents for complex tasks | **Agents** |
| Manual skill management | Native @include + optional MCP | **Skills** |
| Context bloat from agents | Ephemeral task/work product storage | **Task Copilot** |
| Inconsistent processes | Battle-tested workflows | **Protocol** |

---

## Quick Decision Guide

*Note: For comprehensive details see CLAUDE_REFERENCE.md or [docs/10-architecture/03-decision-guide.md](docs/10-architecture/03-decision-guide.md).*

### Command Selection Matrix

| Command | When to Use | Scope | Run From |
|---------|-------------|-------|----------|
| `/setup` | First time on machine | Machine | `~/.claude/copilot` |
| `/setup-project` | New project initialization | Project | Any project root |
| `/update-project` | Sync project with latest framework | Project | Project root |
| `/update-copilot` | Update framework itself | Machine | `~/.claude/copilot` |
| `/knowledge-copilot` | Create shared knowledge repo | Machine/Team | Any directory |
| `/setup-knowledge-sync` | Install automatic knowledge updates | Project | Project root |
| `/protocol [task]` | Start fresh work session | Session | Project root |
| `/continue [stream]` | Resume previous work | Session | Project root |
| `/pause [reason]` | Context switch, save state | Session | Project root |
| `/map` | Analyze codebase structure | Project | Project root |
| `/memory` | View memory state and recent activity | Session | Project root |
| `/orchestrate` | Set up parallel stream orchestration | Project | Project root |

### Use Case Mapping

| I want to... | Start with | What Happens |
|--------------|------------|--------------|
| Fix a bug | `/protocol fix the login bug` | Defect flow: qa → me → qa |
| Build a feature | `/protocol add dark mode UI` | Experience flow: sd → uxd → uids → ta → me |
| Refactor code | `/protocol refactor auth module` | Technical flow: ta → me |
| Improve something | `/protocol improve dashboard` | Clarification flow (asks intent) |
| Skip design stages | `/protocol --skip-sd add feature` | Jumps to specified stage |
| Resume yesterday's work | `/continue` | Memory loads automatically |
| Resume specific stream | `/continue Stream-B` | Loads stream context directly |
| Context switch mid-task | `/pause switching to X` | Creates checkpoint, switch safely |
| Understand new codebase | `/map` | Generates PROJECT_MAP.md |
| View memory state | `/memory` | See current initiative & recent activity |
| Run parallel work streams | `/orchestrate generate` then `/orchestrate start` | Create PRD + tasks → spawn workers |
| Monitor orchestration | `/orchestrate status` or `./watch-status` | Live progress dashboard |
| Set up team standards | `/knowledge-copilot` | Create extension repository |
| Auto-update product knowledge | `/setup-knowledge-sync` | Updates on git release tags |
| Initialize new project | `/setup-project` | Framework installs |
| Update all projects | `/update-project` (each project) | Syncs latest changes |
| Search past decisions | Use `memory_search` tool | Semantic search across sessions |
| Load local skill | `@include .claude/skills/NAME/SKILL.md` | Direct file include |
| Search marketplace skills | Use `skill_search` tool (requires MCP) | SkillsMP access |

---

## The Five Pillars

### 1. Memory Copilot

Persistent memory across sessions with semantic search.

**Essential Tools:** `initiative_get`, `initiative_start`, `initiative_update`, `initiative_complete`, `memory_store`, `memory_search`

**Location:** `mcp-servers/copilot-memory/`

### 2. Agents

13 specialized agents using lean agent model (~60-100 lines each).

**Agents:** me, ta, qa, sec, doc, do, sd, uxd, uids, uid, cw, cco, kc

**Location:** `.claude/agents/`

### 3. Skills

Load via native @include (recommended) or Skills Copilot MCP server (optional).

**Native:** `@include .claude/skills/NAME/SKILL.md`

**MCP Tools:** `skill_get`, `skill_search`, `skill_list`, `skill_evaluate`, `knowledge_search`, `knowledge_get`

**Location:** `mcp-servers/skills-copilot/`

### 4. Task Copilot

Ephemeral PRD, task, and work product storage. Reduces context bloat by ~94%.

**Core Tools:** `prd_create`, `prd_get`, `task_create`, `task_update`, `task_get`, `work_product_store`, `work_product_get`, `progress_summary`, `initiative_link`

**Stream Tools:** `stream_list`, `stream_get`, `stream_conflict_check`, `stream_unarchive`, `stream_archive_all`

**Other Tools:** `agent_handoff`, `agent_chain_get`, `checkpoint_create`, `checkpoint_resume`, `validation_config_get`

**Location:** `mcp-servers/task-copilot/`

### 5. Protocol

Battle-tested workflow commands.

**Commands:** `/setup`, `/setup-project`, `/update-project`, `/update-copilot`, `/knowledge-copilot`, `/protocol [task]`, `/continue [stream]`, `/pause [reason]`, `/map`, `/memory`, `/orchestrate`

**Location:** `.claude/commands/`


---

## Agent Routing

Agents route to each other based on expertise:

| From | Routes To | When |
|------|-----------|------|
| Any | `ta` | Architecture decisions |
| Any | `sec` | Security concerns |
| `sd` | `uxd` | Interaction design needed |
| `uxd` | `uids` | Visual design needed |
| `uids` | `uid` | Implementation needed |
| Any | `me` | Code implementation |
| Any | `qa` | Testing needed |
| Any | `doc` | Documentation needed |

---

## Specification Workflow

Domain agents (sd, uxd, uids, cw, cco) **MUST NOT create tasks directly**. Instead, they create specifications that @agent-ta reviews and decomposes into tasks.

### Why Specifications?

| Problem | Solution |
|---------|----------|
| Domain expertise ≠ technical decomposition | Domain agents focus on their specialty |
| @agent-ta needs full context | Specifications provide complete requirements |
| Prevents misalignment | TA sees all domain requirements before task creation |

### Workflow

```
1. Domain agent completes work (journey map, wireframes, design tokens, copy, creative direction)
2. Store as specification work product (type: 'specification')
3. Route to @agent-ta
4. TA discovers specifications for PRD
5. TA reviews all domain specifications
6. TA creates tasks with specification traceability
```

### Specification Structure

All specifications include:

| Section | Purpose |
|---------|---------|
| PRD Reference | Link back to source PRD |
| Overview | High-level description |
| Domain Content | Journey maps, wireframes, tokens, copy, creative direction |
| Implementation Implications | Technical requirements from domain perspective |
| Acceptance Criteria | How to verify domain requirements met |
| Open Questions | Technical feasibility questions for TA |

### Task Creation with Traceability

When TA creates tasks from specifications, metadata includes:

```typescript
metadata: {
  sourceSpecifications: ['WP-xxx', 'WP-yyy', 'WP-zzz'],
  // Links back to all domain specifications
}
```

Task descriptions consolidate requirements from all specifications, ensuring implementation aligns with all domain input.

### Example Flow

```
1. User creates PRD-001: "Build user dashboard"
2. @agent-sd creates WP-001: Service Design Specification (journey stages)
3. @agent-uxd creates WP-002: UX Design Specification (interactions, states)
4. @agent-uids creates WP-003: UI Design Specification (design tokens, components)
5. @agent-cw creates WP-004: Copy Specification (headlines, errors, empty states)
6. @agent-ta discovers WP-001 through WP-004
7. @agent-ta creates tasks with consolidated requirements and sourceSpecifications metadata
```

---

## Installation

**Quick Setup:**
1. Machine setup (once): `cd ~/.claude/copilot && claude` then run `/setup`
2. Project setup (per project): Run `/setup-project`
3. Update projects: Run `/update-project` in each project
4. Knowledge (optional): Run `/knowledge-copilot`

See [SETUP.md](SETUP.md) for details.

---

## Extension System

Extensions allow company-specific methodologies to override or enhance base agents via knowledge repositories.

**Resolution order:** Project (`$KNOWLEDGE_REPO_PATH`) → Global (`~/.claude/knowledge`) → Base framework

**Extension types:** `override` (replace agent), `extension` (add to sections), `skills` (inject skills)

See [extension-spec.md](docs/40-extensions/00-extension-spec.md) and CLAUDE_REFERENCE.md for full details.

---

## File Locations

| Content | Location |
|---------|----------|
| Agents | `.claude/agents/` |
| Commands | `.claude/commands/` |
| MCP Servers | `mcp-servers/` |
| Knowledge sync scripts | `scripts/knowledge-sync/` |
| Git hooks | `templates/hooks/` |
| Decision matrices | `docs/10-architecture/03-decision-guide.md` |
| Operations docs | `docs/30-operations/` |
| Feature docs | `docs/50-features/` |
| Templates | `templates/` |
| Integration tests | `tests/integration/` |
| Extension spec | `docs/40-extensions/00-extension-spec.md` |
| Orchestration workflow | `docs/50-features/02-orchestration-workflow.md` |
| Knowledge sync protocol | `docs/50-features/03-knowledge-sync.md` |
| Worktree isolation | `docs/50-features/05-worktree-isolation.md` |
| Opus 4.6 capabilities | `docs/50-features/06-opus-46-capabilities.md` |

---

## Session Management

### Starting Fresh Work

Use `/protocol` to activate the Agent-First Protocol.

### Resuming Previous Work

Use `/continue` to load context from Memory Copilot.

### End of Session

Call `initiative_update` with:

| Field | Content |
|-------|---------|
| `completed` | Tasks finished |
| `inProgress` | Current state |
| `resumeInstructions` | Next steps |
| `lessons` | Insights gained |
| `decisions` | Choices made |
| `keyFiles` | Important files touched |

---

## Development Guidelines

### No Time Estimates Policy

**ALL outputs from agents and direct responses MUST NEVER include:**

- Time-based estimates (hours, days, weeks, months, quarters, sprints)
- Completion dates or deadlines
- Duration predictions or timelines
- Phase durations (e.g., "Phase 1 (Weeks 1-2)")

**Acceptable alternatives:**

| Instead of | Use |
|------------|-----|
| "Phase 1 (weeks 1-2)" | "Phase 1: Foundation" |
| "Estimated: 3 days" | "Complexity: Medium" |
| "Sprint 1-3" | "Priority: P0, P1, P2" |
| "Will take 2 hours" | "Task: [description]" |
| "Response time: < 1 hour" | "Severity: Critical (immediate response)" |
| "Q1 delivery" | "After Phase 2 completes" |

**Sequencing without time:**
- Use dependency chains: "After X completes" not "Week 2"
- Use phases: "Phase 1 → Phase 2" not "Weeks 1-3"
- Use priority: "P0 (critical), P1 (high), P2 (medium)" not "This week"
- Use complexity: "Low / Medium / High / Very High" not "X days"

**Why:** Time estimates are consistently inaccurate, create false expectations, and shift focus from quality to arbitrary deadlines. With parallel agents, traditional time-based planning is meaningless.

---

### When Modifying Agents

- Keep base agents generic (no company-specific content)
- Use industry-standard methodologies
- Include routing to other agents
- Document decision authority

### Required Agent Sections

Every agent must include:

1. **Frontmatter** - name, description, tools, model (YAML block between `---` markers)
2. **Opening description** - Role and mission (paragraph after frontmatter)
3. **Core Behaviors** - Always do / Never do lists
4. **Output format** - Example output or deliverable templates
5. **Route To Other Agent** - When to hand off to specialists
6. **Task Copilot Integration** - How to store work products

---

## Operations Documentation

Standards and guides in `docs/30-operations/`:

| Document | Purpose |
|----------|---------|
| `01-working-protocol.md` | Agent-First Protocol details |
| `02-documentation-guide.md` | Doc standards, token budgets |

---

## Extended Reference

For detailed information on the following topics, see CLAUDE_REFERENCE.md:

- **Full Quick Decision Guide**: Protocol flow system, agent selection matrix, extension types, memory vs skills vs extensions comparison
- **The Five Pillars (Detailed)**: Complete tool descriptions, configuration tables, work product types, key features
- **OMC Features**: Ecomode, magic keywords, progress HUD, skill extraction, zero-config install
- **Extension System (Full)**: Two-tier resolution, setup instructions, extension tools
- **Session Boundary Protocol**: Preflight checks, decision matrix, agent-specific guidance, example usage
- **Lifecycle Hooks**: Hook types, security rules, API examples
- **Skill Evaluation**: Evaluation methods, confidence levels, usage examples
- **Correction Detection**: Detection patterns, tools, /reflect command

**To include the extended reference:**
```markdown
@include CLAUDE_REFERENCE.md
```
