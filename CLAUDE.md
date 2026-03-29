# CLAUDE.md

This file provides guidance to Claude Code when working with the Claude Copilot framework.

---

## Main Session Guardrails

**These rules prevent context bloat — the framework's core purpose.**

| Rule | What To Do Instead |
|------|-------------------|
| Never write implementation code | Delegate to `@agent-me` |
| Never create detailed plans | Delegate to `@agent-ta` |
| Never use `Explore`, `Plan`, or `general-purpose` agents | Use framework agents (they integrate with Task Copilot) |
| Avoid reading >8 files directly | Delegate to framework agent |
| Keep responses short | Store details via `tc wp store` |

**Framework agents:** ta, me, qa, sec, doc, do, sd, uxd, uids, uid, cw, cco, kc, cs

---

## Overview

**Claude Copilot** solves five challenges:

| Challenge | Solution | Component |
|-----------|----------|-----------|
| Lost memory, wasted tokens | Persistent memory + semantic search | **Memory Copilot** |
| Generic AI lacks expertise | Specialized agents for complex tasks | **Agents** |
| Manual skill management | Native @include + optional MCP | **Skills** |
| Context bloat from agents | Ephemeral task/work product storage | **Task Copilot** |
| Inconsistent processes | Battle-tested workflows | **Protocol** |

### Feature Comparison

| Feature | Invocation | Persistence | Best For |
|---------|------------|-------------|----------|
| **Memory** | Auto | Cross-session | Context preservation, decisions, lessons |
| **Agents** | Protocol | Session | Expert tasks, complex work |
| **Skills** | @include or MCP | On-demand | Reusable patterns, marketplace |
| **Tasks** | CLI (`tc`) | Per-initiative | PRDs, task tracking, work products |
| **Commands** | Manual | Session | Quick shortcuts, workflows |
| **Extensions** | Auto | Permanent | Team standards, custom methodologies |

---

## Quick Decision Guide

### Command Selection Matrix

| Command | When to Use | Scope |
|---------|-------------|-------|
| `/setup` | First time on machine | Machine |
| `/setup-project` | New project initialization | Project |
| `/update-project` | Sync project with latest framework | Project |
| `/update-copilot` | Update framework itself | Machine |
| `/knowledge-copilot` | Create shared knowledge repo | Machine/Team |
| `/protocol [task]` | Start fresh work session | Session |
| `/continue [stream]` | Resume previous work | Session |
| `/pause [reason]` | Context switch, save state | Session |
| `/map` | Analyze codebase structure | Project |
| `/memory` | View memory state and recent activity | Session |
| `/orchestrate` | Set up parallel stream orchestration | Project |

### Use Case Mapping

| I want to... | Start with | What Happens |
|--------------|------------|--------------|
| Fix a bug | `/protocol fix the login bug` | Defect flow: qa → me → qa |
| Build a feature | `/protocol add dark mode UI` | Experience flow: sd → uxd → uids → ta → me → qa |
| Refactor code | `/protocol refactor auth module` | Technical flow: ta → me → qa |
| Improve something | `/protocol improve dashboard` | Clarification flow (asks intent) |
| Skip design stages | `/protocol --skip-sd add feature` | Jumps to specified stage |
| Resume yesterday's work | `/continue` | Memory loads automatically |
| Run parallel work streams | `/orchestrate generate` then `/orchestrate start` | Create PRD + tasks → set up worktrees |
| Search past decisions | Use `memory_search` tool | Semantic search across sessions |
| Load local skill | `@include .claude/skills/NAME/SKILL.md` | Direct file include |

---

## The Five Pillars

### 1. Memory Copilot

Persistent memory across sessions with semantic search.

**Essential Tools:** `initiative_get`, `initiative_start`, `initiative_update`, `initiative_complete`, `memory_store`, `memory_search`

**Location:** `mcp-servers/copilot-memory/`

### 2. Agents

14 specialized agents. Every agent embeds named industry methodology — IDEO (sd), Nielsen (uxd), Rams (uids), ADR/Fitness Functions (ta), Kent Beck (me), STRIDE/DREAD (sec), Diátaxis (doc), 12-Factor/SRE (do), Atomic Design (uid), Meszaros (qa), MailChimp Voice & Tone (cw), Litmus Test (cco).

**Location:** `.claude/agents/`

### 3. Skills

Load via native @include (recommended) or Skills Copilot MCP server (optional).

**Native:** `@include .claude/skills/NAME/SKILL.md`

**MCP Tools:** `skill_get`, `skill_search`, `skill_list`, `skill_evaluate`, `knowledge_search`, `knowledge_get`

**Location:** `mcp-servers/skills-copilot/`

### 4. Task Copilot

Ephemeral PRD, task, and work product storage. Reduces context bloat by ~94%. Uses the `tc` CLI tool (installed at `tools/tc/`). Agents call `tc` commands via Bash.

**Core Commands:** `tc prd create`, `tc task create`, `tc task update`, `tc task get`, `tc wp store`, `tc wp get`, `tc progress`

**Stream Commands:** `tc stream list`, `tc stream get`

**Collaboration:** `tc handoff`, `tc log --task <id>`

**Location:** `tools/tc/`

### 5. Protocol

Battle-tested workflow commands.

**Commands:** `/setup`, `/setup-project`, `/update-project`, `/update-copilot`, `/knowledge-copilot`, `/protocol`, `/continue`, `/pause`, `/map`, `/memory`, `/orchestrate`

**Location:** `.claude/commands/`

---

## Agent Routing

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

Domain agents (sd, uxd, uids, cw, cco) **MUST NOT create tasks directly**. They create specification work products (`type: 'specification'`) and route to @agent-ta. TA discovers all specifications via `tc wp list`, reviews them, and creates tasks with `metadata.sourceSpecifications` linking back to each spec.

---

## Session Boundary Protocol

Agents verify their task exists and check environment health before starting work:

1. `tc task get <taskId> --json` — verify task exists and is assignable
2. `git status --short` — check working directory state
3. If dirty with unrelated changes → warn user, suggest commit/stash
4. If environment issues (missing deps, config) → fix before proceeding
5. If blocked dependencies → wait for prerequisites

---

## Agent Shared Behaviors

All agents inherit these. Individual agent files should NOT repeat them.

- **Skill Loading:** Call `skill_evaluate({ files, text, threshold: 0.5 })` at start
- **Task Copilot Pattern:** `tc task get` → do work → `tc wp store` → `tc task update --status completed`
- **Iteration Loop:** Self-manage iterations (max from frontmatter). Pass → complete. Blocked → emit `<promise>BLOCKED</promise>`. Else → iterate.
- **Return Format:** Return ONLY ~100 tokens to main session. Store all details via `tc wp store`.
- **Context Compaction:** If response exceeds ~14K tokens, store as work product and return summary only.
- **Knowledge:** Check `knowledge_search()` for voice/brand context when working on user-facing features. Never block work for missing knowledge.
- **Specification Workflow:** Domain agents (sd, uxd, uids, cw, cco) store as `type: 'specification'`, route to @agent-ta.
- **Multi-Agent Handoff:** Intermediate agents: `tc handoff` then route to next agent. Final agent: `tc log --task <id>`, return consolidated summary.
- **Testing Gate (MANDATORY):** @agent-me is NEVER final. After implementation, @agent-qa MUST run tests. No implementation ships without QA.
- **Protocol Integration:** Output stage-complete summary with Task/WP IDs, key decisions, handoff context (200-char max).

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

See [extension-spec.md](docs/40-extensions/00-extension-spec.md) for full details.

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

**ALL outputs MUST NEVER include** time-based estimates, completion dates, duration predictions, or phase durations.

**Acceptable alternatives:**

| Instead of | Use |
|------------|-----|
| "Phase 1 (weeks 1-2)" | "Phase 1: Foundation" |
| "Estimated: 3 days" | "Complexity: Medium" |
| "Sprint 1-3" | "Priority: P0, P1, P2" |
| "Q1 delivery" | "After Phase 2 completes" |

Use dependency chains, phases, priority levels, and complexity ratings instead.

### When Modifying Agents

- Keep base agents generic (no company-specific content)
- Use industry-standard methodologies
- Include routing to other agents
- Document decision authority

### Required Agent Sections

1. **Frontmatter** — name, description, tools, model
2. **Opening description** — Role and mission
3. **Core Behaviors** — Always do / Never do
4. **Output format** — Deliverable templates
5. **Route To Other Agent** — Handoff rules
6. **Task Copilot Integration** — Work product storage
