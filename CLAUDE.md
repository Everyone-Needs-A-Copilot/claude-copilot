# CLAUDE.md

This file provides guidance to Claude Code when working with the Claude Copilot framework.

## Overview

**Claude Copilot** is a complete AI-enabled development framework solving five challenges:

| Challenge | Solution | Component |
|-----------|----------|-----------|
| Lost memory, wasted tokens | Persistent memory + semantic search | **Memory Copilot** |
| Generic AI lacks expertise | Specialized agents for complex tasks | **Agents** |
| Manual skill management | On-demand skill loading | **Skills Copilot** |
| Context bloat from agents | Ephemeral task/work product storage | **Task Copilot** |
| Inconsistent processes | Battle-tested workflows | **Protocol** |

---

## Quick Decision Guide

### Feature Comparison

| Feature | Invocation | Persistence | Best For |
|---------|------------|-------------|----------|
| **Memory** | Auto | Cross-session | Context preservation, decisions, lessons |
| **Agents** | Protocol | Session | Expert tasks, complex work |
| **Skills** | Auto | On-demand | Reusable patterns, workflows |
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
| `/protocol` | Start fresh work session | Session | Project root |
| `/continue` | Resume previous work | Session | Project root |
| `/memory` | View memory state and recent activity | Session | Project root |

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
| Fix a bug | `/protocol` select DEFECT | Follow Agent-First Protocol |
| Build a feature | `/protocol` select EXPERIENCE/FEATURE | Agent routes automatically |
| Resume yesterday's work | `/continue` | Memory loads automatically |
| View memory state | `/memory` | See current initiative & recent activity |
| Set up team standards | `/knowledge-copilot` | Create extension repository |
| Initialize new project | `/setup-project` | Framework installs |
| Update all projects | `/update-project` (each project) | Syncs latest changes |
| Search past decisions | Use `memory_search` tool | Semantic search across sessions |
| Load reusable pattern | Skills load automatically | Or use `skill_get` manually |

### Extension Type Guide

| Goal | Extension Type | File Pattern | Behavior |
|------|----------------|--------------|----------|
| Replace agent entirely | `override` | `agent-name.override.md` | Full replacement |
| Add to agent sections | `extension` | `agent-name.extension.md` | Section-level merge |
| Inject skills only | `skills` | `agent-name.skills.json` | Skill injection |
| Company methodology | `override` | Multiple agents | Custom processes |
| Add checklists/templates | `extension` | Specific sections | Enhance existing |

### Memory vs Skills vs Extensions

| When to Use | Memory | Skills | Extensions |
|-------------|--------|--------|------------|
| Project context | ✓ Store in memory | | |
| Team decisions | ✓ Store in memory | | |
| Reusable workflows | | ✓ Create skill | |
| Company standards | | | ✓ Create extension |
| Past lessons | ✓ Store in memory | | |
| Custom methodologies | | | ✓ Create extension |
| Tool integrations | | ✓ Create skill | |
| Cross-project patterns | | ✓ Global skills | ✓ Global extensions |

---

## The Five Pillars

### 1. Memory Copilot

MCP server providing persistent memory across sessions.

**Location:** `mcp-servers/copilot-memory/`

| Tool | Purpose |
|------|---------|
| `initiative_get` | Retrieve current initiative |
| `initiative_start` | Begin new initiative |
| `initiative_update` | Update progress, decisions, lessons |
| `initiative_complete` | Archive completed initiative |
| `memory_store` | Store decisions, lessons, context |
| `memory_search` | Semantic search across memories |

**Configuration:**

| Env Variable | Default | Purpose |
|--------------|---------|---------|
| `MEMORY_PATH` | `~/.claude/memory` | Base storage path |
| `WORKSPACE_ID` | (auto-hash) | Explicit workspace identifier |

**Important:** By default, each project gets a unique database based on its path hash. Set `WORKSPACE_ID` explicitly to preserve memories when renaming/moving projects. See `mcp-servers/copilot-memory/README.md` for details.

### 2. Agents

12 specialized agents for complex development tasks.

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
| `kc` | Knowledge Copilot | Shared knowledge setup |

### 3. Skills Copilot

MCP server for on-demand skill loading and knowledge search.

**Location:** `mcp-servers/skills-copilot/`

**Skill Tools:**

| Tool | Purpose |
|------|---------|
| `skill_get` | Load specific skill by name |
| `skill_search` | Search skills across sources |
| `skill_list` | List available skills |
| `skill_save` | Save skill to private DB |

**Knowledge Tools:**

| Tool | Purpose |
|------|---------|
| `knowledge_search` | Search knowledge files (project → global) |
| `knowledge_get` | Get specific knowledge file by path |

Knowledge is searched in two-tier resolution: project-level first (`KNOWLEDGE_REPO_PATH`), then machine-level (`~/.claude/knowledge`).

### 4. Task Copilot

MCP server for ephemeral PRD, task, and work product storage.

**Location:** `mcp-servers/task-copilot/`

**Purpose:** Agents store detailed work products here instead of returning them to the main session, reducing context bloat by ~96%.

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
| `other` | @agent-sd, @agent-uxd, @agent-uids, @agent-uid, @agent-cw |

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
| `/protocol` | Project | Start fresh work with Agent-First Protocol |
| `/continue` | Project | Resume previous work via Memory Copilot |
| `/memory` | Project | View current memory state and recent activity |

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

See [EXTENSION-SPEC.md](docs/EXTENSION-SPEC.md) for full documentation on:
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
| Decision matrices | `docs/DECISION-GUIDE.md` |
| Operations docs | `docs/operations/` |
| Templates | `templates/` |
| Extension spec | `docs/EXTENSION-SPEC.md` |

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

1. **Frontmatter** - name, description, tools, model
2. **Identity** - Role, Mission, Success criteria
3. **Core Behaviors** - Always do / Never do
4. **Output Formats** - Templates for deliverables
5. **Quality Gates** - Checklists
6. **Route To Other Agent** - When to hand off
7. **Decision Authority** - Autonomous vs escalate
8. **Task Copilot Integration** - How to store work products

---

## Operations Documentation

Standards and guides in `docs/operations/`:

| Document | Purpose |
|----------|---------|
| `working-protocol.md` | Agent-First Protocol details |
| `documentation-guide.md` | Doc standards, token budgets |
