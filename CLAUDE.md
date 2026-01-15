# CLAUDE.md

This file provides guidance to Claude Code when working with the Claude Copilot framework.

---

## CRITICAL: Main Session Guardrails

**These rules exist to prevent context bloat. Violating them wastes tokens and defeats the framework's purpose.**

### What You (Main Session) Must NEVER Do

| Action | Why It's Wrong | What To Do Instead |
|--------|---------------|-------------------|
| Read more than 3 files | Bloats context with code | Delegate to framework agent |
| Write implementation code | Code belongs in work products | Delegate to `@agent-me` |
| Create detailed plans | Plans belong in Task Copilot | Delegate to `@agent-ta` |
| Use `Explore` agent | Returns full content to context | Use `@agent-ta` or `@agent-me` |
| Use `Plan` agent | Returns full plans to context | Use `@agent-ta` with PRD |
| Use `general-purpose` agent | No Task Copilot integration | Use specific framework agent |
| Return detailed analysis | Fills context with text | Store as work product |

### Self-Check Before Every Response

Ask yourself:

1. **Am I about to read multiple files?** → STOP. Delegate to agent.
2. **Am I about to write code?** → STOP. Delegate to `@agent-me`.
3. **Am I about to create a plan?** → STOP. Delegate to `@agent-ta`.
4. **Am I using a generic agent?** → STOP. Switch to framework agent.
5. **Is my response going to be long?** → STOP. Store details in Task Copilot.

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
| Research + Plan | ~500 tokens (summary only) | ~20,000+ tokens (full content) |
| Implementation | ~500 tokens (summary only) | ~10,000+ tokens (full code) |
| Full initiative | ~2,000 tokens | ~50,000+ tokens (compact needed) |

**If you're approaching compact, you violated these rules.**

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

*Note: For comprehensive decision matrices and flowcharts, see [docs/10-architecture/03-decision-guide.md](docs/10-architecture/03-decision-guide.md). The tables below provide quick reference for common scenarios.*

### Feature Comparison

| Feature | Invocation | Persistence | Best For |
|---------|------------|-------------|----------|
| **Memory** | Auto | Cross-session | Context preservation, decisions, lessons |
| **Agents** | Protocol | Session | Expert tasks, complex work |
| **Skills (Native)** | Manual (@include) | Session | Local reusable patterns, workflows |
| **Skills (MCP)** | Auto/Manual | On-demand | Marketplace access, cross-source search |
| **Tasks** | Auto | Per-initiative | PRDs, task tracking, work products |
| **Commands** | Manual | Session | Quick shortcuts, workflows |
| **Extensions** | Auto | Permanent | Team standards, custom methodologies |

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

**Command Arguments (optional):**
- `/protocol <task>` - Auto-detect task type and route to agent (e.g., `/protocol fix the login bug`)
- `/continue <stream>` - Resume specific parallel stream (e.g., `/continue Stream-B`)
- `/pause <reason>` - Create named checkpoint (e.g., `/pause switching to urgent bug`)
- `/orchestrate <subcommand>` - Manage parallel orchestration (e.g., `/orchestrate start`, `/orchestrate status`)

### Agent Selection Matrix

| Scenario | Start With | Then Route To | Why |
|----------|------------|---------------|-----|
| Bug reported | `/protocol` (DEFECT) | `@agent-qa` | Reproduce, diagnose, test fix |
| New feature | `/protocol` (EXPERIENCE) | `@agent-sd` → `@agent-uxd` | Journey design → interaction |
| Architecture question | `/protocol` (ARCHITECTURE) | `@agent-ta` | System design expertise |
| Code implementation | `/protocol` (FEATURE) | `@agent-me` | Write production code |
| Security concern | Any agent | `@agent-sec` | Vulnerability analysis |
| API documentation | Any agent | `@agent-doc` | Technical writing |
| CI/CD pipeline | `/protocol` (DEVOPS) | `@agent-do` | Infrastructure automation |
| UI component | `@agent-uids` | `@agent-uid` | Visual design → implementation |

### Use Case Mapping

| I want to... | Start with | Next Step |
|--------------|------------|-----------|
| Fix a bug | `/protocol fix the login bug` | Auto-routes to @agent-qa |
| Build a feature | `/protocol add dark mode UI` | Auto-routes to @agent-sd |
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

### Extension Type Guide

| Goal | Extension Type | File Pattern | Behavior |
|------|----------------|--------------|----------|
| Replace agent entirely | `override` | `agent-name.override.md` | Full replacement |
| Add to agent sections | `extension` | `agent-name.extension.md` | Section-level merge |
| Inject skills only | `skills` | `agent-name.skills.json` | Skill injection |
| Company methodology | `override` | Multiple agents | Custom processes |
| Add checklists/templates | `extension` | Specific sections | Enhance existing |

### Memory vs Skills vs Extensions

| When to Use | Memory | Skills (Native) | Skills (MCP) | Extensions |
|-------------|--------|-----------------|--------------|------------|
| Project context | ✓ | | | |
| Team decisions | ✓ | | | |
| Reusable workflows | | ✓ (@include) | ✓ (skill_get) | |
| Company standards | | | | ✓ |
| Past lessons | ✓ | | | |
| Custom methodologies | | | | ✓ |
| Tool integrations | | ✓ (@include) | ✓ (skill_get) | |
| Local patterns | | ✓ (@include) | | |
| Marketplace skills | | | ✓ (SkillsMP) | |
| Cross-project patterns | | ✓ (~/skills) | ✓ (Private DB) | ✓ |

---

## The Five Pillars

### 1. Memory Copilot

MCP server providing persistent memory across sessions.

**Location:** `mcp-servers/copilot-memory/`

| Tool | Purpose |
|------|---------|
| `initiative_get` | Retrieve current initiative (supports `mode: "lean"` for ~150 tokens or `mode: "full"` for ~370 tokens) |
| `initiative_start` | Begin new initiative |
| `initiative_update` | Update progress, decisions, lessons |
| `initiative_complete` | Archive completed initiative |
| `memory_store` | Store decisions, lessons, context |
| `memory_search` | Semantic search across memories |

**Two-Tier Resume System:**
- **Lean mode** (default): Returns ~150 tokens - status, currentFocus, nextAction only
- **Full mode**: Returns ~370 tokens - includes decisions, lessons, keyFiles

**Configuration:**

| Env Variable | Default | Purpose |
|--------------|---------|---------|
| `MEMORY_PATH` | `~/.claude/memory` | Base storage path |
| `WORKSPACE_ID` | (auto-hash) | Explicit workspace identifier |

**Important:** By default, each project gets a unique database based on its path hash. Set `WORKSPACE_ID` explicitly to preserve memories when renaming/moving projects. See `mcp-servers/copilot-memory/README.md` for details.

### 2. Agents

13 specialized agents for complex development tasks using the **lean agent model**.

**Location:** `.claude/agents/`

| Agent | Name | Domain |
|-------|------|--------|
| `me` | Engineer | Code implementation |
| `ta` | Tech Architect | System design |
| `qa` | QA Engineer | Testing |
| `sec` | Security | Security review |
| `doc` | Documentation | Technical writing |
| `do` | DevOps | CI/CD, infrastructure |
| `sd` | Service Designer | Experience strategy |
| `uxd` | UX Designer | Interaction design |
| `uids` | UI Designer | Visual design |
| `uid` | UI Developer | UI implementation |
| `cw` | Copywriter | Content/copy |
| `cco` | Creative Chief Officer | Creative direction |
| `kc` | Knowledge Copilot | Shared knowledge setup |

**Lean Agent Model:**

Agents are ~60-100 lines and auto-load domain skills using `skill_evaluate`:

```typescript
// Agents auto-detect relevant skills
const skills = await skill_evaluate({
  files: ['src/auth/login.ts'],     // Files being worked on
  text: task.description,            // Task context
  threshold: 0.5                     // Minimum confidence
});
// Then load matching skills via @include
```

**Required Agent Tools:**

| Tool | Purpose |
|------|---------|
| `preflight_check` | Verify environment before work |
| `skill_evaluate` | Auto-detect and load skills |
| `task_get`, `task_update` | Task management |
| `work_product_store` | Store output (not in response) |

### 3. Skills (Native & MCP)

Skills can be loaded via **native @include directive** or **Skills Copilot MCP server**.

#### Native @include (Recommended for Local Skills)

Load local skills directly without MCP overhead:

```markdown
## Context
When working with Laravel:
@include ~/.claude/skills/laravel/SKILL.md

When writing tests:
@include .claude/skills/testing/SKILL.md
```

**Benefits:**
- Zero MCP overhead (~500 tokens saved per skill)
- Instant loading, no network/database
- Simpler setup (no MCP configuration)
- Full control over skill content

**Use for:**
- Project-specific skills (`.claude/skills/`)
- User-level skills (`~/.claude/skills/`)
- Simple, direct loading

#### Auto-Detection with skill_evaluate

Agents use `skill_evaluate` to automatically detect relevant skills based on file patterns and keywords:

```typescript
const skills = await skill_evaluate({
  files: ['src/Button.test.tsx'],     // Match against trigger_files
  text: 'Help with React testing',    // Match against trigger_keywords
  threshold: 0.5                      // Minimum confidence (0-1)
});
// Returns ranked list: { skillName, confidence, path }
```

See [Skill Evaluation Quick Reference](#skill-evaluation-quick-reference) for details.

#### Skills Copilot MCP (OPTIONAL)

MCP server for advanced skill management and marketplace access.

**Location:** `mcp-servers/skills-copilot/`

**Skill Tools:**

| Tool | Purpose |
|------|---------|
| `skill_get` | Load specific skill by name |
| `skill_search` | Search skills across sources |
| `skill_list` | List available skills |
| `skill_save` | Save skill to private DB |
| `skill_evaluate` | Auto-detect skills from context |

**Knowledge Tools:**

| Tool | Purpose |
|------|---------|
| `knowledge_search` | Search knowledge files (project → global) |
| `knowledge_get` | Get specific knowledge file by path |

**Use when you need:**
- SkillsMP marketplace access (25K+ public skills)
- Private skill storage in Postgres database
- Cross-source skill search (DB + marketplace + local)
- Usage analytics and caching
- Knowledge repository extensions

Knowledge is searched in two-tier resolution: project-level first (`KNOWLEDGE_REPO_PATH`), then machine-level (`~/.claude/knowledge`).

### 4. Task Copilot

MCP server for ephemeral PRD, task, and work product storage.

**Location:** `mcp-servers/task-copilot/`

**Purpose:** Agents store detailed work products here instead of returning them to the main session, reducing context bloat by ~94% on average (up to 96% for single-agent tasks, 85%+ for session resume, 92%+ for multi-agent collaboration).

**Core Tools:**

| Tool | Purpose |
|------|---------|
| `prd_create` | Create product requirements document |
| `prd_get` | Retrieve PRD details |
| `prd_list` | List PRDs for initiative |
| `task_create` | Create task or subtask |
| `task_update` | Update task status and notes |
| `task_get` | Retrieve task details |
| `task_list` | List tasks with filters |
| `work_product_store` | Store agent output |
| `work_product_get` | Retrieve full work product |
| `work_product_list` | List work products for task |
| `progress_summary` | Get compact progress overview (~200 tokens) |
| `initiative_link` | Link Memory Copilot initiative to Task Copilot |

**Stream Management:**

| Tool | Purpose |
|------|---------|
| `stream_list` | List all independent work streams in initiative (use `includeArchived: true` to show archived) |
| `stream_get` | Get detailed info for specific stream (~200 tokens) |
| `stream_conflict_check` | Check if files conflict with other streams |
| `stream_unarchive` | Recover an archived stream to make it active again |
| `stream_archive_all` | One-time cleanup to archive all legacy streams (requires `confirm: true`) |

**Stream Archival:**

Streams are automatically archived when switching initiatives via `initiative_link()`. This prevents stream pollution when using `/continue` across different initiatives.

| Scenario | Behavior |
|----------|----------|
| Switch to new initiative | Old streams auto-archived |
| Re-link same initiative | No archival (streams preserved) |
| `/continue Stream-A` | Only shows current initiative's streams |
| `/orchestrate generate` | Calls `initiative_link()` → archives old streams before creating new ones |
| `/orchestrate start` | Only spawns workers for current initiative's streams |
| `watch-status` | Only displays streams from active initiative |
| Need old stream back | Use `stream_unarchive({ streamId: "Stream-A" })` |

**After Updating from Pre-1.7.1:** Run `stream_archive_all({ confirm: true })` once to clean up legacy streams from before the auto-archive feature.

**Agent Collaboration (Hierarchical Handoffs):**

| Tool | Purpose |
|------|---------|
| `agent_handoff` | Record handoff between agents (50-char context, intermediate agents only) |
| `agent_chain_get` | Retrieve full collaboration chain (final agent uses to consolidate) |

**Performance Tracking:**

| Tool | Purpose |
|------|---------|
| `agent_performance_get` | Get agent success rates, completion rates by task type, complexity |

**Checkpoint System:**

| Tool | Purpose |
|------|---------|
| `checkpoint_create` | (Optional) Manually create checkpoint outside iteration loops |
| `checkpoint_resume` | Resume task from last checkpoint with full state |
| `checkpoint_get` | Get specific checkpoint details |
| `checkpoint_list` | List available checkpoints for task |
| `checkpoint_cleanup` | Clean up old or expired checkpoints |

**Note:** Checkpoints are automatically created during iteration loops. Manual `checkpoint_create()` calls are only needed for recovery points outside TDD/iteration workflows.

**Validation System:**

| Tool | Purpose |
|------|---------|
| `validation_config_get` | Get current validation configuration and rules |
| `validation_rules_list` | List validation rules for work product types |

**Configuration:**

| Env Variable | Default | Purpose |
|--------------|---------|---------|
| `TASK_DB_PATH` | `~/.claude/tasks` | Database storage path |
| `WORKSPACE_ID` | (auto) | Links to Memory Copilot workspace |

**Work Product Types:**

| Type | Agent |
|------|-------|
| `architecture` | @agent-ta |
| `technical_design` | @agent-ta, @agent-do |
| `implementation` | @agent-me |
| `test_plan` | @agent-qa |
| `security_review` | @agent-sec |
| `documentation` | @agent-doc |
| `specification` | @agent-sd, @agent-uxd, @agent-uids, @agent-cw, @agent-cco |
| `other` | @agent-uid, misc. agents |

**Key Features:**

- **Hierarchical Handoffs**: Multi-agent chains pass 50-char context between agents; only final agent returns to main (~100 tokens vs ~900)
- **Performance Tracking**: Automatically tracks agent success rates, completion rates by task type and complexity
- **Checkpoint System**: Create recovery points during long-running tasks; auto-expires (extended for manual pauses)
- **Validation System**: Validates work products for size limits, required structure, completeness before storage
- **Token Efficiency**: Validation enforces character/token limits to prevent context bloat (warn/reject modes)
- **Independent Streams**: Parallel work streams with file conflict detection and dependency management (foundation → parallel → integration)
- **Verification Enforcement**: Opt-in blocking of task completion without acceptance criteria and proof (set `metadata.verificationRequired: true`)
- **Activation Modes**: Auto-detected from keywords (ultrawork, analyze, quick, thorough); ultrawork warns when >3 subtasks
- **Progress Visibility**: ASCII progress bars, milestone tracking in PRDs, velocity trends (7d/14d/30d with ↗↘→ indicators)
- **Specification Workflow**: Domain agents (sd, uxd, uids, cw, cco) create specifications → @agent-ta reviews and creates tasks with traceability

### 5. Protocol

Commands enforcing battle-tested workflows.

**Location:** `.claude/commands/`

| Command | Level | Purpose |
|---------|-------|---------|
| `/setup` | Machine | One-time machine setup (run from `~/.claude/copilot`) |
| `/setup-project` | User | Initialize a new project |
| `/update-project` | User | Update existing project with latest Claude Copilot |
| `/update-copilot` | User | Update Claude Copilot itself (pull + rebuild) |
| `/knowledge-copilot` | User | Build or link shared knowledge repository |
| `/protocol [task]` | Project | Start fresh work with Agent-First Protocol |
| `/continue [stream]` | Project | Resume previous work (checks pause checkpoints first, then Memory Copilot) |
| `/pause [reason]` | Project | Create named checkpoint with extended expiry for context switching |
| `/map` | Project | Generate PROJECT_MAP.md with codebase analysis |
| `/memory` | Project | View current memory state and recent activity |
| `/orchestrate` | Project | Set up and manage parallel stream orchestration |

**Quick Start Examples:**
```
/protocol fix login authentication bug        → Auto-routes to @agent-qa
/protocol add dark mode to dashboard          → Auto-routes to @agent-sd
/continue Stream-B                            → Resume parallel stream work
/pause switching to urgent bug                → Create checkpoint with reason
/map                                          → Generate project structure map
/orchestrate start                            → Start parallel workers for all streams
/orchestrate status                           → Check progress of all streams
```

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

### Setup Flow

**1. Machine Setup (once per machine):**
```bash
cd ~/.claude/copilot
claude
```
Then run `/setup`

**2. Project Setup (each project):**
Open Claude Code in your project and run `/setup-project`

**3. Update Projects (after updating Claude Copilot):**
Run `/update-project` in each project

**4. Knowledge Setup (optional):**
Run `/knowledge-copilot` to create a shared knowledge repository

See [SETUP.md](SETUP.md) for manual setup instructions.

### What Gets Created Per Project

```
your-project/
├── .mcp.json              # MCP server configuration
├── CLAUDE.md              # Project instructions
└── .claude/
    ├── commands/          # /protocol, /continue
    ├── agents/            # 12 specialized agents
    └── skills/            # Project-specific skills
```

---

## Extension System

This framework supports extensions via knowledge repositories. Extensions allow company-specific methodologies to override or enhance base agents.

### Two-Tier Resolution

Extensions are resolved in priority order:

| Tier | Path | Configuration |
|------|------|---------------|
| 1. Project | `$KNOWLEDGE_REPO_PATH` | Set in `.mcp.json` (optional) |
| 2. Global | `~/.claude/knowledge` | Auto-detected (no config needed) |
| 3. Base | Framework agents | Always available |

**Key benefit:** Set up your company knowledge once in `~/.claude/knowledge` and it's automatically available in every project.

### Extension Types

| Type | Behavior |
|------|----------|
| `override` | Replaces base agent entirely |
| `extension` | Adds to base agent (section-level merge) |
| `skills` | Injects additional skills into agent |

### Setting Up Global Knowledge Repository

Create a knowledge repository at `~/.claude/knowledge/`:

```
~/.claude/knowledge/
├── knowledge-manifest.json    # Required
└── .claude/
    └── extensions/
        ├── sd.override.md     # Your agent extensions
        └── uxd.extension.md
```

**Minimal manifest:**
```json
{
  "version": "1.0",
  "name": "my-company",
  "description": "Company-specific agent extensions"
}
```

No `.mcp.json` changes needed - global repository is auto-detected.

### Project-Specific Overrides (Optional)

Only needed when a project requires different extensions than global:

```json
{
  "mcpServers": {
    "skills-copilot": {
      "env": {
        "KNOWLEDGE_REPO_PATH": "/path/to/project-specific/knowledge"
      }
    }
  }
}
```

### Extension Tools

| Tool | Purpose |
|------|---------|
| `extension_get` | Get extension for specific agent |
| `extension_list` | List all extensions (shows source: global/project) |
| `manifest_status` | Check both global and project repo status |

### Documentation

See [extension-spec.md](docs/40-extensions/00-extension-spec.md) for full documentation on:
- Creating knowledge repositories
- Extension file formats
- Fallback behaviors
- Required skills validation

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

## Session Boundary Protocol

The Session Boundary Protocol ensures agents start work in a healthy environment by running preflight checks before substantive work.

### Overview

Agents should call `preflight_check()` before beginning implementation, planning, or testing to surface environment issues early and prevent wasted work.

### When to Use

| Agent | When to Check | Why |
|-------|---------------|-----|
| `@agent-me` | Before implementation | Verify environment, git state, dependencies satisfied |
| `@agent-ta` | Before planning/PRD creation | Understand current context, check for blockers |
| `@agent-qa` | Before running tests | Ensure test environment configured, no false failures |

### Preflight Check Tool

**Tool:** `preflight_check({ taskId: "TASK-xxx" })`

**Returns health report with:**

| Field | Description |
|-------|-------------|
| `healthy` | Overall health status (boolean) |
| `git.clean` | Whether working directory is clean |
| `progress.blockedTasks` | Number of blocked tasks |
| `environment` | Environment issues detected |
| `recommendations` | Suggested actions if unhealthy |

### Decision Matrix

| Condition | Action |
|-----------|--------|
| `healthy: true` | Proceed with work |
| `git.clean: false` (unrelated changes) | Warn user, suggest commit/stash |
| `git.clean: false` (related changes) | Proceed, note in context |
| `blockedTasks > 3` | Suggest unblocking before new work |
| `environment` issues | Fix critical issues before proceeding |

### Agent-Specific Guidance

**@agent-me:**
- Must verify environment before implementation
- Git dirty with unrelated changes: warn but can continue if acknowledged
- Environment issues: STOP and fix (missing deps, config errors)
- Blocked dependencies: wait for prerequisites

**@agent-ta:**
- Check before creating PRDs/tasks
- Git dirty: note current work, ensure new plan doesn't conflict
- Many blocked tasks: identify patterns, address in plan
- Use `stream_conflict_check()` for parallel work planning

**@agent-qa:**
- Check before running tests
- Environment issues: fix before test execution to prevent false failures
- Git dirty with failing tests: determine if failures from current changes
- Missing test dependencies: install before proceeding

### Benefits

- **Early issue detection**: Surface problems before wasted work
- **Context awareness**: Understand current state before planning
- **Better decisions**: Know git state, blockers, environment status
- **Prevent false failures**: Ensure healthy environment for tests
- **Stream coordination**: Avoid file conflicts in parallel work

### Example Usage

```typescript
// @agent-me starting implementation
const health = await preflight_check({ taskId: "TASK-123" });

if (!health.healthy) {
  // Review recommendations
  if (health.git.clean === false) {
    console.log("Warning: Uncommitted changes detected");
    console.log("Recommendation:", health.recommendations);
    // Proceed if changes are related to current task
  }

  if (health.environment.length > 0) {
    console.log("Environment issues:", health.environment);
    // STOP and fix critical issues
    return;
  }
}

// Proceed with implementation
```

---

## Lifecycle Hooks Quick Reference

Lifecycle hooks intercept execution at critical phases for security, transformation, and monitoring.

### Hook Types

| Hook | Fires | Primary Use |
|------|-------|-------------|
| `PreToolUse` | Before tool executes | Security validation, preprocessing |
| `PostToolUse` | After tool completes | Logging, result transformation |
| `UserPromptSubmit` | Before prompt processing | Context injection, skill detection |

### PreToolUse Security Rules (Built-in)

| Rule | Action | Detects |
|------|--------|---------|
| `secret-detection` | Block | AWS keys, GitHub tokens, JWTs, private keys |
| `destructive-command` | Block | `rm -rf /`, `DROP DATABASE`, etc. |
| `sensitive-file-protection` | Block | `.env`, credentials, SSH keys |
| `credential-url` | Block | URLs with embedded passwords |

### Hook API Examples

```typescript
// Test if a tool call would be blocked
import { testSecurityRules } from 'task-copilot/hooks';
const result = await testSecurityRules('Write', { file_path: '.env', content: '...' });
if (!result.allowed) console.log('Would be blocked:', result.violations);

// Register custom rule
import { registerSecurityRule, SecurityAction } from 'task-copilot/hooks';
registerSecurityRule({
  id: 'my-rule', name: 'Custom', description: '...', enabled: true, priority: 75,
  evaluate: (ctx) => ctx.toolInput.content?.includes('UNSAFE')
    ? { action: SecurityAction.BLOCK, ruleName: 'my-rule', reason: 'Unsafe', severity: 'high' }
    : null
});
```

**Full documentation:** [docs/50-features/lifecycle-hooks.md](docs/50-features/lifecycle-hooks.md)

---

## Skill Evaluation Quick Reference

Automatically detect relevant skills from file patterns and text keywords.

### Evaluation Methods

| Method | Analyzes | Weight |
|--------|----------|--------|
| Pattern matching | File paths (glob patterns) | 0.5 |
| Keyword detection | Text content (TF-IDF) | 0.5 |

### skill_evaluate Tool

```typescript
// Evaluate context for relevant skills
const result = await skill_evaluate({
  files: ['src/Button.test.tsx'],     // File patterns to match
  text: 'Help with React testing',    // Keywords to detect
  recentActivity: ['testing'],        // Boost matching skills
  threshold: 0.3,                     // Min confidence (0-1)
  limit: 5                            // Max results
});

// Returns ranked skills:
// { skillName: 'react-testing', confidence: 0.78, level: 'high', reason: '...' }
```

### Confidence Levels

| Level | Threshold | Meaning |
|-------|-----------|---------|
| High | >= 0.7 | Strong match, likely relevant |
| Medium | >= 0.4 | Moderate match, possibly relevant |
| Low | < 0.4 | Weak match |

**Full documentation:** [docs/50-features/skill-evaluation.md](docs/50-features/skill-evaluation.md)

---

## Correction Detection Quick Reference

Auto-capture user corrections for continuous agent/skill improvement.

### Detection Patterns

| Pattern Type | Example | Weight |
|--------------|---------|--------|
| Explicit | "Correction: use X" | 0.95 |
| Negation | "No, that's wrong" | 0.90 |
| Replacement | "Use X instead of Y" | 0.90 |
| Preference | "I prefer X over Y" | 0.75 |

### Correction Tools

| Tool | Purpose |
|------|---------|
| `correction_detect` | Detect patterns in user message |
| `correction_list` | List pending/approved corrections |
| `correction_update` | Approve or reject a correction |
| `correction_route` | Get routing info (skill/agent/memory) |

### /reflect Command

Review and manage pending corrections:

```bash
/reflect                    # Review all pending
/reflect --agent me         # Filter by agent
/reflect --status approved  # Filter by status
```

### Example Detection

```typescript
import { detectCorrections } from 'copilot-memory/tools/correction-tools';

const result = detectCorrections({
  userMessage: 'Actually, use async/await instead of callbacks',
  previousAgentOutput: '...',
  agentId: 'me',
  threshold: 0.5
}, 'project-id');

// result.detected: true
// result.maxConfidence: 0.85
// result.suggestedAction: 'auto_capture'
```

**Full documentation:** [docs/50-features/correction-detection.md](docs/50-features/correction-detection.md)
