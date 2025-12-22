# CLAUDE.md

This file provides guidance to Claude Code when working with the Claude Copilot framework.

## Overview

**Claude Copilot** is a complete AI-enabled development framework solving four challenges:

| Challenge | Solution | Component |
|-----------|----------|-----------|
| Lost memory, wasted tokens | Persistent memory + semantic search | **Memory Copilot** |
| Generic AI lacks expertise | Specialized agents for complex tasks | **Agents** |
| Manual skill management | On-demand skill loading | **Skills Copilot** |
| Inconsistent processes | Battle-tested workflows | **Protocol** |

---

## The Four Pillars

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

11 specialized agents for complex development tasks.

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

### 4. Protocol

Commands enforcing battle-tested workflows.

**Location:** `.claude/commands/`

| Command | Purpose |
|---------|---------|
| `/protocol` | Start fresh work with Agent-First Protocol |
| `/continue` | Resume previous work via Memory Copilot |

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

### One-Prompt Setup

After cloning, use these prompts to let Claude Code handle installation:

**Machine Setup (once per machine):**
```
Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine.
```

**Project Setup (each project):**
```
Read @~/.claude/copilot/SETUP.md and set up Claude Copilot in this project.
```

See [SETUP.md](SETUP.md) for detailed step-by-step instructions.

### What Gets Created Per Project

```
your-project/
├── .mcp.json              # MCP server configuration
├── CLAUDE.md              # Project instructions
└── .claude/
    ├── commands/          # /protocol, /continue
    ├── agents/            # 11 specialized agents
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

---

## Operations Documentation

Standards and guides in `docs/operations/`:

| Document | Purpose |
|----------|---------|
| `working-protocol.md` | Agent-First Protocol details |
| `documentation-guide.md` | Doc standards, token budgets |
