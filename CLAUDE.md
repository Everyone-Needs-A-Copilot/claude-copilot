# CLAUDE.md

This file provides guidance to Claude Code when working with the Claude Copilot framework.

---

## Main Session Guardrails

**These rules prevent context bloat — the framework's core purpose.**

| Rule | What To Do Instead | Enforcement |
|------|-------------------|-------------|
| Never write implementation code | Delegate to `@agent-me` | Hook: force-delegate |
| Never create detailed plans | Delegate to `@agent-ta` | Hook: force-delegate |
| Never use `Explore`, `Plan`, or `general-purpose` agents | Use framework agents (they integrate with Task Copilot) | Advisory |
| Avoid reading >8 files directly | Delegate to framework agent | Hook: force-delegate (triggers at 5 consecutive same-tool calls) |
| Keep responses short | Store details via `tc wp store` | Advisory |

**Mechanical enforcement:** The force-delegate rule, QA-gate rule, session-cap advisory, and safety primitives are enforced by hooks in `.claude/hooks/` — not just policy. Attempting >5 consecutive Bash/Read/Edit calls will be blocked automatically. After `@agent-me` completes, all main-session tools are gated until `@agent-qa` provides a pass verdict. **Safety primitives:** `/careful` (destructive-command block/warn via `security-rules.json`) and `/freeze` (edit-boundary lock via `.claude/hooks/state/.freeze`) — escape hatches: `COPILOT_CAREFUL=off`, `COPILOT_FREEZE=off`, `COPILOT_SAFETY=off`. See `.claude/hooks/README.md` for escape hatches and debug tools.

**Framework agents:** ta, me, qa, do, doc, sd · design chain sd→uxd→uids→uid→ta→me · branches ind/cco/cw · sec (13 framework agents; kc is setup-only; `design` retired; cs/cpa cut 2026-07-14, DEC-8/TASK-100 — 0 measured invocations). Roster is the authoritative list in `.claude/agents/manifest.json`.

---

## Overview

**Claude Copilot** solves five challenges:

| Challenge | Solution | Component |
|-----------|----------|-----------|
| Lost memory, wasted tokens | Persistent memory + FTS5 keyword search | **Memory Copilot** |
| Generic AI lacks expertise | Specialized agents for complex tasks | **Agents** |
| Manual skill management | Auto-fire from trigger-rich `description`; `cc skill search` as fallback | **Skills** |
| Context bloat from agents | Ephemeral task/work product storage | **Task Copilot** |
| Inconsistent processes | Battle-tested workflows | **Protocol** |

### Feature Comparison

| Feature | Invocation | Persistence | Best For |
|---------|------------|-------------|----------|
| **Memory** | Auto | Cross-session | Context preservation, decisions, lessons |
| **Agents** | Protocol | Session | Expert tasks, complex work |
| **Skills** | Auto-fire (description match) | On-demand | Reusable patterns, code-bearing scripts |
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
| Build a feature | `/protocol add dark mode UI` | Experience flow: sd → uxd → uids → uid → ta → me → qa |
| Refactor code | `/protocol refactor auth module` | Technical flow: ta → me → qa |
| Deploy / infra work | `/protocol deploy to staging` | Infra flow: do → me → qa |
| Improve something | `/protocol improve dashboard` | Clarification flow (asks intent) |
| Skip design stages | `/protocol --skip-sd add feature` | Jumps to specified stage |
| Resume yesterday's work | `/continue` | Memory loads automatically |
| Run parallel work streams | `/orchestrate generate` then `/orchestrate start` | Create PRD + tasks → set up worktrees |
| Search past decisions | `cc memory search "<query>"` | Full-text keyword search across sessions |
| Load local skill | `@include .claude/skills/NAME/SKILL.md` | Direct file include |

---

## The Five Pillars

### 1. Memory Copilot

Persistent memory across sessions with full-text (FTS5 keyword) search.

**Storage:** `.claude/memory/entries/<uuid>.md` (committed, travels with repo)
**Commands:** `cc memory store`, `cc memory search`, `cc memory get`, `cc memory list`, `cc memory check`, `cc eval`
**Index:** `cc memory index --rebuild` (local SQLite cache, gitignored)
**Drift detection:** `cc memory check` — token-free deterministic checkers for path-existence, command-resolve, version-conflict, staleness; 0–100 score; exits 1 on any `fail`-severity finding
**Regression eval:** `cc eval run [--agent <name>]` — golden cases in `.claude/evals/<agent>/*.yaml`; scores persist to `cc memory`; CI gate on VERSION.json bumps

**Location:** `tools/cc/`

### 2. Agents

13 framework agents + kc (setup-only, not in the build chain). Every framework agent embeds named industry methodology — IDEO (sd), Dieter Rams/Jony Ive (ind), Nielsen/JTBD (uxd), Rams Principles/Atomic Design (uids), Atomic Design/CDD (uid), Litmus Test (cco), MailChimp Voice & Tone (cw), STRIDE+DREAD (sec), ADR/Fitness Functions (ta), Kent Beck (me), Diátaxis (doc), 12-Factor/SRE (do), Meszaros (qa). Authoritative roster: `.claude/agents/manifest.json`.

**Design chain:** sd → uxd → uids → uid → ta → me (ind and cco/cw are optional branches)
**Security:** @agent-sec routes to me/ta/do; @includes stride-dread skill

**Location:** `.claude/agents/`

### 3. Skills

Skills auto-fire based on their trigger-rich `description` field — native Claude Code surfaces every skill's `name` + `description` at session start and fires the skill when a prompt matches. For prose-only skills, auto-firing handles discovery. For code-bearing skills, auto-firing handles discovery but the agent must still invoke the L3 script via Bash. No MCP server required.

**Primary discovery:** Auto-fire from `description` match (no agent action needed)

**Fallback discovery:** `cc skill search "<topic>"` — case-insensitive substring match over name, description, and tags. Use this fallback when a needed skill did not auto-surface (e.g., in a subagent context).

**Load:** `@include .claude/skills/NAME/SKILL.md` (explicit fallback path)

**Inspect:** `cc skill get <name>`, `cc skill list`

**Location:** `tools/cc/`

### 4. Task Copilot

Ephemeral PRD, task, and work product storage. Reduces context for externalized work products by ~94% vs inlining outputs above the 8KB threshold (not end-to-end session savings — see [derivation](docs/70-reference/04-framework-modernization-analysis.md)). Uses the `tc` CLI tool (installed at `tools/tc/`). Agents call `tc` commands via Bash.

**Core Commands:** `tc prd create`, `tc task create [--max-budget-usd <float>]`, `tc task update`, `tc task get`, `tc wp store`, `tc wp get`, `tc wp render <id> --html`, `tc progress`

**Stream Commands:** `tc stream list`, `tc stream get`

**Collaboration:** `tc handoff`, `tc log --task <id>`

**Dispatch:** `tc worker run <task_id>` (budget cap flag stored in metadata; enforcement is roadmap P1)

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
| Any | `me` | Code implementation |
| Any | `qa` | Testing needed |
| Any | `doc` | Documentation needed |
| Any | `sec` | Security review, threat modeling, vulnerability analysis |
| `sd` | `ind` | Object-level essentialism review needed (optional, upstream) |
| `sd` | `uxd` | Interaction/task flow design needed |
| `ind` | `uxd` | Element verdict ready, interaction must be designed within it |
| `uxd` | `uids` | Task flows ready for visual design |
| `uids` | `uid` | Design tokens and specs ready for component implementation |
| `uid` | `ta` | Components complete, ready for task planning |
| `sd` | `cco` | Creative direction or brand strategy needed |
| `cco` | `cw` | Copy execution, messaging, microcopy |

---

## Specification Workflow

Domain agents (sd, ind, uxd, uids, cco, cw) **MUST NOT create tasks directly**. They create specification work products (`type: 'specification'`) and route to @agent-ta. TA discovers all specifications via `tc wp list`, reviews them, and creates tasks with `metadata.sourceSpecifications` linking back to each spec.

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

- **Env Hydration:** Run `eval "$(cc env)"` at start to hydrate `CC_SHARED_DOCS`, `CC_KNOWLEDGE_REPO`, and other machine-level paths
- **Skill Discovery:** Skills auto-fire from their trigger-rich `description` field — no explicit search step needed in normal operation. If a needed skill did not auto-surface, use `cc skill search "<topic>"` (case-insensitive substring match over name, description, tags) as a fallback, then `@include` the returned path. No `evaluate` step needed — skills are model-readable markdown, not code.
- **Live Docs — Verify upstream APIs before coding:** Before implementing or planning against a third-party library/framework API where correctness depends on the *installed* version, run `cc docs get <pkg>` (also `cc docs resolve <pkg>` for the active version and `cc docs search <pkg> "<query>"`) instead of trusting training-data memory of that API. It returns docs for the version actually installed in the project, is local-first so it works offline/headless, and only falls back to a self-owned network fetch when the optional `httpx` extra is present.
- **Memory — Recall at start:** Run `cc memory search "<task topic>"` to recall prior decisions, lessons, and context relevant to the current task.
- **Memory — Store at end:** After completing meaningful work, run `cc memory store --type <decision|context|lesson|reference> "<content>"` to persist decisions and lessons for future sessions. Do NOT call it "semantic" — it is FTS5 keyword search.
- **Memory commands:** `cc memory store`, `cc memory search`, `cc memory get`, `cc memory list`, `cc memory export` (not MCP `memory_store`/`memory_search`)
- **Task Copilot Pattern:** `tc task get` → do work → `tc wp store` → `tc task update --status completed`
- **Code-Execution Path (PREFER for >=3 related ops):** When performing 3+ related tc or cc operations (create PRD + tasks, wire deps, store multiple WPs, batch memory stores), use a SINGLE `python3` Bash block importing `tc.api` or `cc.api` instead of multiple CLI calls. Each CLI round-trip echoes a full JSON payload back into context; a python3 block returns only what you `print()`.
  - tc-only block: `from tc.api import create_prd, create_task, add_dependency, transaction`
  - cc-only block: `from cc.api import memory_store, memory_search, memory_list`
  - CRITICAL: tc and cc are in separate environments — keep each block to ONE tool.
  - Keep CLI for single one-shot ops (`tc task get 40 --json`; one `tc wp store`; one `cc memory search`).
  - Token win example: PRD + 18 tasks + 17 deps = 36 CLI calls (~9-20K tokens echoed) vs one python3 block (~25 tokens returned).
  - See `tools/tc/README.md` and `tools/cc/README.md` for the full usage pattern.
- **Iteration Loop:** Self-manage iterations (max from frontmatter). Pass → complete. Blocked → emit `<promise>BLOCKED</promise>`. Confused → emit `<promise>CONFUSED</promise>` (see Confused Loop-State). Else → iterate.
- **Confused Loop-State:** When mid-task you hit a genuine decision fork that only the user can resolve, emit `<promise>CONFUSED</promise>` and record loop-state in a fenced block immediately after the promise tag:
  ```
  QUESTION: <one clear question — what decision must be made>
  OPTIONS:
  - A: <option description>
  - B: <option description>
  CONTEXT: <why the choice matters — consequences of each option>
  ```
  Do NOT guess. Suspend iteration and wait for the user's answer, then resume from where you stopped. **Distinct from `<promise>BLOCKED</promise>`** (technical blocker or unmet external dependency): CONFUSED is for decision forks where user judgment defines the correct path, not for missing prerequisites.
- **Return Format:** Return ONLY ~100 tokens to main session. Store all details via `tc wp store`.
- **Context Compaction:** If response exceeds ~14K tokens, store as work product and return summary only.
- **Knowledge:** Run `cc memory search "<voice/brand query>"` for user-facing features. Never block work for missing knowledge.
- **Specification Workflow:** Domain agents (sd, ind, uxd, uids, cco, cw) store as `type: 'specification'`, route to @agent-ta.
- **Multi-Agent Handoff:** Intermediate agents: `tc handoff` then route to next agent. Final agent: `tc log --task <id>`, return consolidated summary.
- **Testing Gate (MANDATORY):** @agent-me is NEVER final. After implementation, @agent-qa MUST run tests and include an `ARTIFACT: <type>|<detail>` marker in its verdict (`test-run`, `file-check`, `diff-check`, or `adversarial-run`). A bare `VERDICT: APPROVED` with no ARTIFACT line will NOT unblock the gate. `adversarial-run` satisfies the artifact requirement on its own but is never a new mandatory requirement (it is availability-gated — see `.claude/hooks/bin/adversarial-pass.sh`). No implementation ships without QA. See `.claude/hooks/README.md` for the full verdict format.
- **Protocol Integration:** Output stage-complete summary with Task/WP IDs, key decisions, handoff context (200-char max).

---

## Installation

**Quick Setup:**
1. Machine setup (once): `cd ~/.claude/copilot && claude` then run `/setup`
2. Project setup (per project): Run `/setup-project`
3. Update projects: Run `/update-project` in each project
4. Knowledge (optional): Run `/knowledge-copilot`

**cc CLI** — unified tool for memory and skill management:
- Install: `bash tools/cc/install.sh`
- Machine config: `cc config set paths.shared_docs /path/to/docs`
- Env hydration: `eval "$(cc env)"` in agent preamble
- Full docs: `cc --help`

**Known References** — stable paths and values injected automatically into every session:
- Register: `cc config set refs.<name> <value>` (e.g. `cc config set refs.cli_copilot /path/to/cli`)
- Or: `cc memory store --type reference "<content>"` for free-text entries
- The `UserPromptSubmit` hook surfaces these on the first prompt of each session so the main session and protocol always have them without re-supplying paths.

**Model pinning (recommended for Copilot-style projects):** Use `.claude/claude-launcher` instead of `claude` directly. It reads `.claude/.model` (default: `claude-sonnet-4-6[1m]`) and passes `--model` automatically. Override with `CLAUDE_MODEL` env var. See [SETUP.md](SETUP.md) for details.

---

## Project-Owned Agents

To override a framework agent at the project level, add `owner: project` to its frontmatter. Sync (`/update-project`, `/setup-project`) will never overwrite or remove it. Files without that marker are framework-owned and refresh normally.

```yaml
---
name: cco
owner: project   # ← sync will never touch this file
...
---
```

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

Call `cc memory store --type initiative "<content>"` with session context. Include:

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

### Version Source of Truth

**`VERSION.json` is the single canonical source for the framework version.**

- `VERSION.json` → `framework` field is the authoritative framework version
- `package.json` → `version` MUST match `VERSION.json.framework` (it is a mirror only)
- Component versions (`cc`, `tc`, `agents`, `commands`, `skills`) are independent semver tracked inside `VERSION.json.components`
- Do NOT update `package.json` independently — update `VERSION.json` first, then sync `package.json` to match

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
