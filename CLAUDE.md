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

MCP server for on-demand skill loading.

**Location:** `mcp-servers/skills-copilot/`

| Tool | Purpose |
|------|---------|
| `skill_get` | Load specific skill by name |
| `skill_search` | Search skills across sources |
| `skill_list` | List available skills |
| `skill_save` | Save skill to private DB |

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

### One-Time Setup (Per Machine)

```bash
# Clone to global location
mkdir -p ~/.claude
cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot

# Build MCP servers
cd copilot/mcp-servers/copilot-memory && npm install && npm run build
cd ../skills-copilot && npm install && npm run build
```

### Per-Project Setup

```bash
# Copy MCP config template
cp ~/.claude/copilot/templates/mcp.json ./.mcp.json

# Create CLAUDE.md from template
cp ~/.claude/copilot/templates/CLAUDE.template.md ./CLAUDE.md
# Edit CLAUDE.md with project-specific details
```

---

## Extension System

This framework supports extensions via knowledge repositories. Extensions allow company-specific methodologies to override or enhance base agents.

### Extension Types

| Type | Behavior |
|------|----------|
| `override` | Replaces base agent entirely |
| `extension` | Adds to base agent (section-level merge) |
| `skills` | Injects additional skills into agent |

### Configuring a Knowledge Repository

1. **Set `KNOWLEDGE_REPO_PATH`** in your MCP config (`.mcp.json`):

```json
{
  "mcpServers": {
    "skills-copilot": {
      "env": {
        "KNOWLEDGE_REPO_PATH": "/path/to/your/knowledge-repo"
      }
    }
  }
}
```

2. **Knowledge repo must contain** `knowledge-manifest.json` declaring extensions
3. **Restart Claude Code** to pick up changes

### Extension Tools

| Tool | Purpose |
|------|---------|
| `extension_get` | Get extension for specific agent |
| `extension_list` | List all available extensions |
| `manifest_status` | Check knowledge repo configuration |

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
| `development-standards.md` | Code quality, testing, Git workflow |
| `security-guidelines.md` | OWASP, secrets, authentication |
| `documentation-guide.md` | Doc standards, token budgets |
| `working-protocol.md` | Agent-First Protocol details |
