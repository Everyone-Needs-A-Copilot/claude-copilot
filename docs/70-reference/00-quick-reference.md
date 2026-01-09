# Claude Copilot - Quick Reference Card

## Installation Quick Commands

### Machine Setup (Once Per Machine)
```bash
# Clone to ~/.claude/copilot
mkdir -p ~/.claude && cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot

# Open and run setup
cd ~/.claude/copilot && claude
# Then say: Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine
```

### Project Setup (Each Project)
```bash
# Open project in Claude Code
cd ~/your-project && claude

# Initialize project
/setup-project
```

### Update Commands
```bash
# Update Claude Copilot itself
cd ~/.claude/copilot && claude
/update-copilot

# Update project with latest
cd ~/your-project && claude
/update-project
```

### Knowledge Repository (Optional)
```bash
# Create shared knowledge repository
/knowledge-copilot
```

### Individual Components

#### Memory Copilot
```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm install
npm run build
```

#### Skills Copilot
```bash
cd ~/.claude/copilot/mcp-servers/skills-copilot
npm install
npm run build
```

#### Agents
```bash
# Copy all agents to project
cp ~/.claude/copilot/templates/agents/*.md ~/your-project/.claude/agents/

# Copy specific agent
cp ~/.claude/copilot/templates/agents/ta.md ~/your-project/.claude/agents/
```

#### Commands
```bash
# Copy all commands to project
cp ~/.claude/copilot/templates/commands/*.md ~/your-project/.claude/commands/

# Copy specific command
cp ~/.claude/copilot/templates/commands/protocol.md ~/your-project/.claude/commands/
```

---

## Feature Cheat Sheet

| Feature | Invocation | Persistence | Best For |
|---------|-----------|-------------|----------|
| **Memory Copilot** | `initiative_*` tools | SQLite (~/.claude/memory) | Decisions, lessons, resuming work |
| **Agents** | `/protocol` or direct | None (stateless) | Complex tasks needing expertise |
| **Skills Copilot** | `skill_get`, `skill_search` | PostgreSQL (optional) | Loading best practices on demand |
| **Knowledge** | `knowledge_search` | Git repo | Company docs, shared standards |
| **Protocol** | `/protocol` | Via Memory Copilot | Starting fresh work |
| **Continue** | `/continue` | Via Memory Copilot | Resuming previous work |
| **Extensions** | Auto-loaded | Knowledge repo | Company-specific agent overrides |

---

## Decision Matrix: "I want to..."

| I want to... | Use this | Command/File |
|--------------|----------|--------------|
| Start fresh work | Protocol | `/protocol` |
| Resume previous work | Continue | `/continue` |
| Run parallel work streams | Orchestrate | `/orchestrate start` |
| Monitor orchestration | Orchestrate | `/orchestrate status` |
| Get architecture help | Tech Architect agent | `/protocol` → routes to `ta` |
| Implement code | Engineer agent | `/protocol` → routes to `me` |
| Review security | Security agent | `/protocol` → routes to `sec` |
| Write tests | QA agent | `/protocol` → routes to `qa` |
| Write documentation | Documentation agent | `/protocol` → routes to `doc` |
| Set up CI/CD | DevOps agent | `/protocol` → routes to `do` |
| Design UX flows | UX Designer agent | `/protocol` → routes to `uxd` |
| Design UI visuals | UI Designer agent | `/protocol` → routes to `uids` |
| Implement UI | UI Developer agent | `/protocol` → routes to `uid` |
| Write copy | Copywriter agent | `/protocol` → routes to `cw` |
| Design services | Service Designer agent | `/protocol` → routes to `sd` |
| Load a skill | Skills Copilot | `skill_get "skill-name"` |
| Search skills | Skills Copilot | `skill_search "query"` |
| Find company docs | Knowledge search | `knowledge_search "query"` |
| Store a decision | Memory Copilot | `memory_store` |
| Search past decisions | Memory Copilot | `memory_search "query"` |
| Track progress | Memory Copilot | `initiative_update` |
| Add company standards | Extensions | Create knowledge repo |
| Override base agent | Extensions | Create `.override.md` extension |
| Extend base agent | Extensions | Create `.extension.md` extension |
| Initialize new project | Setup | `/setup-project` |
| Update project files | Update | `/update-project` |
| Update Copilot itself | Update | `/update-copilot` |

---

## File Locations Reference

### Project Level (`~/your-project/`)
```
your-project/
├── .mcp.json                    # MCP server configuration
├── CLAUDE.md                    # Project instructions (auto-loaded by Claude)
└── .claude/
    ├── commands/                # /protocol, /continue
    │   ├── protocol.md
    │   └── continue.md
    ├── agents/                  # 12 specialized agents
    │   ├── ta.md               # Tech Architect
    │   ├── me.md               # Engineer
    │   ├── qa.md               # QA Engineer
    │   ├── sec.md              # Security
    │   ├── doc.md              # Documentation
    │   ├── do.md               # DevOps
    │   ├── sd.md               # Service Designer
    │   ├── uxd.md              # UX Designer
    │   ├── uids.md             # UI Designer
    │   ├── uid.md              # UI Developer
    │   ├── cw.md               # Copywriter
    │   └── kc.md               # Knowledge Copilot
    └── skills/                  # Project-specific skills (optional)
```

### User Level (`~/.claude/`)
```
~/.claude/
├── copilot/                     # Claude Copilot framework (cloned repo)
│   ├── mcp-servers/            # MCP server source code
│   │   ├── copilot-memory/     # Memory Copilot
│   │   └── skills-copilot/     # Skills Copilot
│   ├── templates/              # Source templates
│   │   ├── agents/             # Base agents
│   │   └── commands/           # Base commands
│   └── docs/                   # Documentation
├── knowledge/                   # Global knowledge repository (optional)
│   ├── knowledge-manifest.json
│   └── .claude/
│       └── extensions/         # Global agent extensions
└── memory/                      # Memory Copilot storage (auto-created)
    └── [workspace-hash]/       # Per-project database
        └── memory.db
```

### Machine Level (`~/.claude/copilot/`)
```
~/.claude/copilot/              # Framework installation
├── .claude/
│   ├── commands/               # Machine-level commands
│   │   └── setup.md           # /setup command
│   └── agents/                # (Unused - agents are in templates/)
├── mcp-servers/               # MCP servers
│   ├── copilot-memory/
│   │   ├── src/
│   │   ├── package.json
│   │   └── build/             # Built JS files
│   └── skills-copilot/
│       ├── src/
│       ├── package.json
│       └── build/             # Built JS files
└── templates/                 # Source for project setup
    ├── agents/
    ├── commands/
    └── mcp.json
```

### Memory Storage (`~/.claude/memory/`)
```
~/.claude/memory/
└── [workspace-id]/            # Unique per project (path hash)
    └── memory.db              # SQLite database
        ├── initiatives        # Current and archived initiatives
        ├── memories           # Decisions, lessons, context
        └── embeddings         # Vector search data
```

---

## The Five Pillars

### 1. Memory Copilot
**MCP server providing persistent memory across sessions**

| Tool | Purpose |
|------|---------|
| `initiative_get` | Retrieve current initiative |
| `initiative_start` | Begin new initiative |
| `initiative_update` | Update progress, decisions, lessons |
| `initiative_complete` | Archive completed initiative |
| `memory_store` | Store decisions, lessons, context |
| `memory_search` | Semantic search across memories |

**Environment:**
- `MEMORY_PATH`: Base storage path (default: `~/.claude/memory`)
- `WORKSPACE_ID`: Explicit workspace identifier (optional, defaults to path hash)

### 2. Agents
**12 specialized agents for complex development tasks**

| Agent | Name | Domain |
|-------|------|--------|
| `ta` | Tech Architect | System design, ADRs, task breakdown |
| `me` | Engineer | Code implementation, refactoring |
| `qa` | QA Engineer | Testing strategy, edge cases |
| `sec` | Security | Vulnerabilities, OWASP, threat modeling |
| `doc` | Documentation | READMEs, API docs, technical writing |
| `do` | DevOps | CI/CD, infrastructure, containers |
| `sd` | Service Designer | Experience strategy, customer journeys |
| `uxd` | UX Designer | Interaction design, wireframes |
| `uids` | UI Designer | Visual design, design systems |
| `uid` | UI Developer | UI implementation, responsive design |
| `cw` | Copywriter | Microcopy, error messages, voice |
| `kc` | Knowledge Copilot | Shared knowledge setup |

### 3. Skills Copilot
**MCP server for on-demand skill loading and knowledge search**

| Tool | Purpose |
|------|---------|
| `skill_get` | Load specific skill by name |
| `skill_search` | Search skills across sources |
| `skill_list` | List available skills |
| `skill_save` | Save skill to private DB |
| `knowledge_search` | Search knowledge files (project → global) |
| `knowledge_get` | Get specific knowledge file by path |
| `extension_get` | Get extension for specific agent |
| `extension_list` | List all extensions |
| `manifest_status` | Check knowledge repository status |

**Environment:**
- `KNOWLEDGE_REPO_PATH`: Project-specific knowledge (optional)
- `~/.claude/knowledge`: Global knowledge (auto-detected)
- `DATABASE_URL`: PostgreSQL for private skills (optional)

### 4. Task Copilot
**MCP server for ephemeral PRD, task, and work product storage**

Agents store detailed work products here instead of returning them to the main session, reducing context usage by ~96%.

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

**Environment:**
- `TASK_DB_PATH`: Database storage path (default: `~/.claude/tasks`)
- `WORKSPACE_ID`: Links to Memory Copilot workspace (auto-detected)

### 5. Protocol
**Commands enforcing battle-tested workflows**

| Command | Level | Purpose |
|---------|-------|---------|
| `/setup` | Machine | One-time machine setup (run from `~/.claude/copilot`) |
| `/setup-project` | User | Initialize a new project |
| `/update-project` | User | Update existing project with latest Claude Copilot |
| `/update-copilot` | User | Update Claude Copilot itself (pull + rebuild) |
| `/knowledge-copilot` | User | Build or link shared knowledge repository |
| `/protocol` | Project | Start fresh work with Agent-First Protocol |
| `/continue` | Project | Resume previous work via Memory Copilot |
| `/orchestrate` | Project | Set up and manage parallel stream orchestration |

---

## Common Workflows

### First Time Setup
```bash
# 1. Clone framework
mkdir -p ~/.claude && cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot

# 2. Machine setup
cd ~/.claude/copilot && claude
# Then: Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine

# 3. Project setup
cd ~/your-project && claude
/setup-project

# 4. Start working
/protocol
```

### Daily Work
```bash
# Resume previous session
/continue

# Start fresh task
/protocol

# At end of session
# Memory Copilot auto-saves via initiative_update
```

### Adding Company Standards
```bash
# Create global knowledge repository
/knowledge-copilot

# Create extension
# Edit: ~/.claude/knowledge/.claude/extensions/ta.extension.md

# All projects now use your extended agents (auto-detected)
```

### Updating
```bash
# Update Claude Copilot
cd ~/.claude/copilot && claude
/update-copilot

# Update each project
cd ~/your-project && claude
/update-project
```

---

## Quick Troubleshooting

| Issue | Solution |
|-------|----------|
| **MCP servers not found** | Check `.mcp.json` has correct paths to built servers |
| **Build fails** | Install build tools: macOS `xcode-select --install`, Linux `sudo apt-get install build-essential python3` |
| **Memory not persisting** | Check `MEMORY_PATH` env variable, verify `~/.claude/memory/` exists |
| **Skills not loading** | Run `npm run build` in `mcp-servers/skills-copilot/` |
| **Commands not working** | Verify `.claude/commands/*.md` exist, restart Claude Code |
| **Agents not routing** | Check frontmatter in agent files, verify file is in `.claude/agents/` |
| **Extensions not loading** | Verify `knowledge-manifest.json` exists, check `KNOWLEDGE_REPO_PATH` |
| **Wrong workspace** | Set `WORKSPACE_ID` explicitly in `.mcp.json` to preserve memories across renames |
| **Outdated project files** | Run `/update-project` to sync with latest templates |
| **Skill search empty** | Check DATABASE_URL for PostgreSQL, or verify public skills API |
| **Knowledge search fails** | Verify knowledge repo structure, check manifest syntax |
| **Permission errors** | Check file permissions on `~/.claude/` directories |

### Verification Commands
```bash
# Check MCP servers built
ls ~/.claude/copilot/mcp-servers/*/build/

# Check project setup
ls .claude/agents/ .claude/commands/

# Check memory database
ls ~/.claude/memory/*/memory.db

# Check knowledge repo
ls ~/.claude/knowledge/knowledge-manifest.json

# Rebuild MCP servers
cd ~/.claude/copilot/mcp-servers/copilot-memory && npm install && npm run build
cd ~/.claude/copilot/mcp-servers/skills-copilot && npm install && npm run build
```

---

## Extension System

### Extension Types
| Type | Behavior | File Pattern |
|------|----------|--------------|
| `override` | Replaces base agent entirely | `agent-name.override.md` |
| `extension` | Adds to base agent (section merge) | `agent-name.extension.md` |
| `skills` | Injects skills into agent | `agent-name.skills.md` |

### Two-Tier Resolution
| Tier | Path | Configuration |
|------|------|---------------|
| 1. Project | `$KNOWLEDGE_REPO_PATH` | Set in `.mcp.json` (optional) |
| 2. Global | `~/.claude/knowledge` | Auto-detected (no config needed) |
| 3. Base | Framework agents | Always available |

### Minimal Global Knowledge Repo
```bash
mkdir -p ~/.claude/knowledge/.claude/extensions
cd ~/.claude/knowledge

# Create manifest
cat > knowledge-manifest.json << 'EOF'
{
  "version": "1.0",
  "name": "my-company",
  "description": "Company-specific agent extensions"
}
EOF

# Create extension (example)
cat > .claude/extensions/ta.extension.md << 'EOF'
---
extension_type: extension
target_agent: ta
---

## Company Architecture Standards

[Your company's architecture guidelines...]
EOF
```

---

## Agent Routing

Agents automatically route to each other based on expertise:

| From | Routes To | When |
|------|-----------|------|
| Any | `ta` | Architecture decisions, system design |
| Any | `sec` | Security concerns, vulnerabilities |
| Any | `me` | Code implementation |
| Any | `qa` | Testing strategy, verification |
| Any | `doc` | Documentation needed |
| Any | `do` | CI/CD, infrastructure |
| `sd` | `uxd` | Interaction design needed |
| `uxd` | `uids` | Visual design needed |
| `uids` | `uid` | UI implementation needed |

---

## Memory Copilot Session Management

### Starting Work
```
# Fresh task
/protocol

# Resume previous work
/continue
```

### During Work
Memory Copilot automatically tracks:
- Decisions made
- Lessons learned
- Progress updates
- Key files touched

### Ending Work
Update initiative with:
```
initiative_update({
  completed: ["Tasks finished"],
  inProgress: "Current state",
  resumeInstructions: "Next steps for /continue",
  lessons: ["Insights gained"],
  decisions: ["Choices made"],
  keyFiles: ["file1.ts", "file2.ts"]
})
```

---

## Configuration Quick Reference

### .mcp.json (Project Level)
```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["/Users/you/.claude/copilot/mcp-servers/copilot-memory/build/index.js"],
      "env": {
        "MEMORY_PATH": "/Users/you/.claude/memory"
      }
    },
    "skills-copilot": {
      "command": "node",
      "args": ["/Users/you/.claude/copilot/mcp-servers/skills-copilot/build/index.js"],
      "env": {
        "KNOWLEDGE_REPO_PATH": "/path/to/project/knowledge"
      }
    }
  }
}
```

### Environment Variables
| Variable | Purpose | Default |
|----------|---------|---------|
| `MEMORY_PATH` | Memory storage location | `~/.claude/memory` |
| `WORKSPACE_ID` | Explicit workspace ID | Auto-hash from path |
| `KNOWLEDGE_REPO_PATH` | Project knowledge repo | None (optional) |
| `DATABASE_URL` | PostgreSQL for private skills | None (optional) |

---

## Links to Full Documentation

| Document | Purpose |
|----------|---------|
| [README.md](../README.md) | Overview and quick start |
| [SETUP.md](../SETUP.md) | Detailed setup instructions |
| [USER-JOURNEY.md](USER-JOURNEY.md) | Complete walkthrough |
| [AGENTS.md](AGENTS.md) | All agents in detail |
| [CONFIGURATION.md](CONFIGURATION.md) | Configuration reference |
| [CUSTOMIZATION.md](CUSTOMIZATION.md) | Extensions and customization |
| [EXTENSION-SPEC.md](EXTENSION-SPEC.md) | Extension file format |
| [PHILOSOPHY.md](PHILOSOPHY.md) | Why we built this |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture |

---

## Quick Tips

- **Memory survives sessions**: Use `/continue` to resume exactly where you left off
- **Agents are stateless**: They don't remember previous conversations (use Memory Copilot for that)
- **Skills load on demand**: No need to preload, Skills Copilot fetches when needed
- **Knowledge is two-tier**: Project knowledge overrides global knowledge
- **Extensions auto-merge**: Base agent + your extension = customized agent
- **No time estimates**: Framework uses phases, priorities, and complexity instead
- **Git-friendly**: All config files are plain text, commit `.claude/` and `CLAUDE.md`
- **Update regularly**: Run `/update-copilot` and `/update-project` when framework updates

---

**This Card**: Print or bookmark for quick reference!

**Quick Start**: Run `/protocol` and let Claude Copilot guide you.
