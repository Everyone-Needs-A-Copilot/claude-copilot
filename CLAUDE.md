# CLAUDE.md

Claude Copilot guidance.

---

## Main Session Guardrails

**Prevent context bloat.**

| Rule | What To Do Instead | Enforcement |
|------|-------------------|-------------|
| Never write implementation code | Delegate to `@agent-me` | Hook: force-delegate |
| Never create detailed plans | Delegate to `@agent-ta` | Hook: force-delegate |
| Never use `Explore`, `Plan`, or `general-purpose` agents | Use framework agents (they integrate with Task Copilot) | Advisory |
| Avoid reading >8 files directly | Delegate to framework agent | Hook: force-delegate (output + file budget) |
| Keep responses short | Store details via `tc wp store` | Advisory |

**Hook enforcement:** `.claude/hooks/` enforces force-delegate output/file budgets, QA gates, session-cap advisory and safety primitives. Main-session tools block until delegation or `/compact` when budgets are reached; after @agent-me, @agent-qa must pass. `/careful` checks destructive commands against `security-rules.json`; `/freeze` locks edit boundaries in `.claude/hooks/state/.freeze`. Escape hatches/debugging: `.claude/hooks/README.md`.

**Framework agents:** ta, me, qa, do, doc, sd · design chain sd→uxd→uids→uid→ta→me · branches ind/cco/cw · sec · business cs/cpa (15 framework agents; kc is setup-only; `design` retired). Roster is the authoritative list in `.claude/agents/manifest.json`.

---

## Output Contract

Follow `.claude/agents/_shared/output-contract.md`, embedded verbatim in agents/protocol and inherited here by other commands. Handoffs and stored records retain precise QA markers and Task/WP IDs; vocabulary/length limits do not apply to them.

**Configurable at setup** (`/setup` machine-wide, overridable per project with `--project`):
- `cc config set output.verbosity <concise|standard|detailed>` — default `concise` if unset.
- `cc config set output.audience <plain|technical>` — default `plain` if unset.

`eval "$(cc env)"` exports `$CC_OUTPUT_VERBOSITY` / `$CC_OUTPUT_AUDIENCE`.

---

## Overview

**Claude Copilot** addresses:

| Challenge | Solution | Component |
|-----------|----------|-----------|
| Lost memory, wasted tokens | Persistent memory + FTS5 keyword search | **Memory Copilot** |
| Generic AI lacks expertise | Specialized agents for complex tasks | **Agents** |
| Manual skill management | Auto-fire from trigger-rich `description`; `cc skill search` as fallback | **Skills** |
| Context bloat from agents | Ephemeral task/work product storage | **Task Copilot** |
| Inconsistent processes | Battle-tested workflows | **Protocol** |

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
| `/orchestrate` | Deprecated protocol redirect | Project |

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
| Run parallel work streams | `/protocol` | Approve → dispatch → converge, verify and clean up |
| Search past decisions | `cc memory search "<query>"` | Full-text keyword search across sessions |
| Load a skill | `cc skill get NAME` | Resolves project → machine → knowledge |

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

15 framework agents + kc (setup-only, not in the build chain). Every framework agent embeds named industry methodology — IDEO (sd), Dieter Rams/Jony Ive (ind), Nielsen/JTBD (uxd), Rams Principles/Atomic Design (uids), Atomic Design/CDD (uid), Litmus Test (cco), MailChimp Voice & Tone (cw), STRIDE+DREAD (sec), Socratic Sales (cs), S-Corp Tax Advisory (cpa), ADR/Fitness Functions (ta), Kent Beck (me), Diátaxis (doc), 12-Factor/SRE (do), Meszaros (qa). Authoritative roster: `.claude/agents/manifest.json`.

**Design chain:** sd → uxd → uids → uid → ta → me (ind and cco/cw are optional branches)
**Security:** @agent-sec routes to me/ta/do; loads the stride-dread skill
**Business advisory (optional, outside the build chain):** cs (sales) and cpa (finance/tax) are standalone agents for founder/agency business needs — they do not route into the software build chain; invoke them directly

**Location:** `.claude/agents/`

### 3. Skills

Claude Code loads each skill's `name` + trigger-rich `description` at session start
and auto-fires on prompt matches. This discovers prose/code skills; code-bearing
skills still require invoking the L3 script via Bash. No MCP server required.

**Primary discovery:** Automatic `description` match.

**Fallback:** If needed skills did not surface (including in subagents), use
`cc skill search "<topic>"`: case-insensitive substring over name/description/tags.

**Load / inspect:** `cc skill get NAME` (by name, not a repo path), `cc skill list`

For additional optional context, `cc skill select "<topic>" --required <skill>
--max-chars 12000 --json` returns source/selection receipts and an explicit character
budget. Keep the receipt once in the task work product and avoid repeated loads;
repository/system constraints always apply outside relevance selection. Character
counts are not tokens, and a receipt records selection, never proof of consumption.
Full contract, embedded byte-for-byte in `.claude/agents/{ta,me,qa}.md`, `.claude/commands/protocol.md`,
`templates/CLAUDE.template.md`, and the Codex shared-behaviors reference:
`.claude/agents/_shared/optional-context.md`. Four visible fallbacks apply, one
named at a time: `cc` unavailable or non-zero exit (proceed on repository
instructions and prior memory only); a `--required` skill not found, exit 2
(state the missing name, never substitute a similar skill, and proceed without it
or emit `<promise>BLOCKED</promise>` if the task cannot continue); no optional
skill matched, `selected: []` (proceed on repository instructions; do not widen
the query to manufacture a match); no knowledge repos configured,
`CC_KNOWLEDGE_REPOS` empty (optional context limited to project and machine
skills; never block). `cc doctor --runtime-details --json` distinguishes project
installation from unobserved runtime trust/dispatch; direct hook probes are explicit
via `--exercise-runtime` and do not prove lifecycle enforcement.

**Location:** `tools/cc/`

### 4. Task Copilot

Ephemeral PRD, task, and work product storage. Reduces context for externalized work products by ~94% vs inlining outputs above the 8KB threshold (not end-to-end session savings — see [derivation](docs/70-reference/04-framework-modernization-analysis.md)). Uses the `tc` CLI tool (installed at `tools/tc/`). Agents call `tc` commands via Bash.

**Core Commands:** `tc prd create`, `tc task create [--max-budget-usd <float>]`, `tc task update`, `tc task get`, `tc wp store`, `tc wp get`, `tc wp render <id> --html`, `tc progress`, `tc task stale|park|unpark|cancel`, `tc archive`, `tc history`

**Stream Commands:** `tc stream list`, `tc stream get`

**Collaboration:** `tc handoff`, `tc log --task <id>`

**Dispatch:** `tc worker run <task_id>` (budget cap flag stored in metadata; enforcement is roadmap P1)

**Location:** `tools/tc/`

### 5. Protocol

Battle-tested workflow commands.

**Commands:** `/setup`, `/setup-project`, `/update-project`, `/update-copilot`, `/knowledge-copilot`, `/protocol`, `/continue`, `/pause`, `/map`, `/memory`, `/orchestrate`

**Location:** `.claude/commands/`

---

## Protocol-native parallel execution

After scoped approval, refill useful independent work within native/resource capacity. Protocol conditionally discovers canonical organization policy with `cc skill list --scope machine --json` and loads the listed `parallel-execution` name once; both Copilots share it. `/orchestrate` redirects there.

If absent, report fallback: `tc cycle --help` governs exclusive writes, actual cwd/branch, native dispatch, one integrator, current independent QA and authorized safe retirement. Read-only research needs no worktree; report missing cycle capability honestly.

**Blast-Radius QA:** replaces prior QA-depth rules. Test affected behavior; both Copilots read `cc skill get blast-radius-qa --scope machine --json`.

## Agent Routing

Fan-out follows the validated ready set and actual runtime/resource capacity; no arbitrary framework cap. Finish each worker promptly, converge through one owner, and partition independent QA with cross-stream coverage. (2026-11-04)

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
| `cs` | `cpa` | Tax implications, financial modeling needed |

---

## Specification Workflow

**Done block (2026-10-29).** Before substantial work, in or out of `/protocol`, post five short lines (Done means / Proven by / Not in scope / Assumptions / First example) and wait for one word from the owner; the confirmed block becomes the task contract (`tc task contract <id> --from-done-block <file>`).

**Make this a rule (2026-10-29).** When the owner says "make this a rule", propose the destination (global CLAUDE.md, framework file, project CLAUDE.md or memory), rewrite the current rule rather than append an exception, and report where it went; the command is `cc rule add`.

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

Start/resume/new PRD/initiative/finish/merge/pause/handoff: apply `.claude/agents/_shared/work-lifecycle.md`; proactively inspect worktrees; automatically retire eligible recorded merged worktrees during cleanup; get exact approval for other deletion.

## Agent Shared Behaviors

All agents inherit these; agent files must not repeat them.

- **Env Hydration:** Run `eval "$(cc env)"` at start to hydrate `CC_SHARED_DOCS`, `CC_KNOWLEDGE_REPO`, and other machine-level paths
- **Skill Discovery:** Auto-fire from `description`; if needed skills did not surface, `cc skill search "<topic>"`, then `@include` the returned path.
- **Live Docs:** Before planning/coding against version-sensitive third-party APIs, use `cc docs get <pkg>`, not API memory. `cc docs resolve <pkg>` identifies the installed version; `cc docs search <pkg> "<query>"` searches it.
- **Memory — Recall at start:** Run `cc memory search "<task topic>"` to recall prior decisions, lessons, and context relevant to the current task.
- **Memory — Selective pointers:** Keep decisions/lessons in canonical task records and narratives; add `cc memory` locators only for useful retrieval, never duplicate session prose.
- **Memory commands:** `cc memory store`, `cc memory search`, `cc memory get`, `cc memory list`, `cc memory export` (not MCP `memory_store`/`memory_search`)
- **Task Copilot Pattern:** `tc task get` → do work → `tc wp store` → `tc task update --status completed`
- **Code-Execution Path:** Batch ≥3 related operations through one `python3` block using `tc.api` or `cc.api`; never mix tools. Print only needed summaries; CLI for single operations. See `tools/tc/README.md` and `tools/cc/README.md`.
- **Iteration Loop:** Self-manage iterations (max from frontmatter). Pass → complete. Blocked → emit `<promise>BLOCKED</promise>`. Confused → emit `<promise>CONFUSED</promise>`. Else → iterate.
- **Confused Loop-State:** When mid-task you hit a genuine decision fork that only the user can resolve, emit `<promise>CONFUSED</promise>` and record loop-state in a fenced block immediately after the promise tag:
  ```
  QUESTION: <one clear question — what decision must be made>
  RECOMMENDATION: <what you would do, and why>
  CONTEXT: <why the choice matters — consequences of each path>
  ```
  Take reversible choices within current authorization and report them; otherwise recommend and ask once, then await the answer. Options are for irreversible, outward or budget-affecting choices. CONFUSED needs owner judgment; BLOCKED means a technical blocker or unmet prerequisite. (2026-10-29)
- **Return Format:** Return ONLY ~100 tokens to main session. Store all details via `tc wp store`.
- **Context Compaction:** If response exceeds ~14K tokens, store as work product and return summary only.
- **Knowledge:** Run `cc memory search "<voice/brand query>"` for user-facing features. Never block work for missing knowledge.
- **Specification Workflow:** Domain agents (sd, ind, uxd, uids, cco, cw) store as `type: 'specification'`, route to @agent-ta.
- **Multi-Agent Handoff:** Intermediate agents: `tc handoff` then route to next agent. Final agent: `tc log --task <id>`, return consolidated summary.
- **Testing Gate (MANDATORY):** @agent-me is NEVER final. After implementation, @agent-qa MUST run tests and include an `ARTIFACT: <type>|<detail>` marker in its verdict (`test-run`, `file-check`, `diff-check`, or `adversarial-run`). A bare `VERDICT: APPROVED` with no ARTIFACT line will NOT unblock the gate. `adversarial-run` satisfies the artifact requirement alone but is availability-gated (`.claude/hooks/bin/adversarial-pass.sh`). No implementation ships without QA; verdict format in `.claude/hooks/README.md`.
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

Apply the work-lifecycle pause/handoff or finish checkpoint in the existing task. Preserve original approvals, failed criteria, cumulative execution history and the next owner/action; memory is an optional locator, not another session summary.

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

- `VERSION.json.framework` is canonical; `package.json.version` is its mirror. Update VERSION first, then sync the package; never update the package independently.
- `VERSION.json.components` tracks independent semver for `cc`, `tc`, `agents`, `commands`, and `skills`.

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

## Project Rules

- Before publishing/notarization, read `docs/30-operations/20-notarization-credentials.md`.
- Keep shared rules consistent across CLAUDE.md and AGENTS.md; preserve scope and place tool-specific rules in their own entrypoint.
