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

#### Reinstall CLIs
```bash
# cc CLI (memory + skills)
bash ~/.claude/copilot/tools/cc/install.sh

# tc CLI (Task Copilot)
pip install -e ~/.claude/copilot/tools/tc
```

#### Agents
```bash
# Copy all agents to project
cp ~/.claude/copilot/.claude/agents/*.md ~/your-project/.claude/agents/
```

#### Commands
```bash
# Copy all commands to project
cp ~/.claude/copilot/.claude/commands/protocol.md ~/your-project/.claude/commands/
cp ~/.claude/copilot/.claude/commands/continue.md ~/your-project/.claude/commands/
```

---

## Feature Cheat Sheet

| Feature | Invocation | Persistence | Best For |
|---------|-----------|-------------|----------|
| **Memory Copilot** | `cc memory` CLI | SQLite FTS5 (~/.claude/memory) | Decisions, lessons, resuming work |
| **Agents** | `/protocol` or direct | None (stateless) | Complex tasks needing expertise |
| **Skills** | Auto-fire from description; `cc skill` CLI as fallback | Local .claude/skills/ | Best practices auto-surface; explicit lookup via `cc skill search` |
| **Knowledge** | `cc memory search` / knowledge repo | Git repo | Company docs, shared standards |
| **Tasks** | `tc` CLI | SQLite (~/.claude/tasks) | PRDs, tasks, work products |
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
| Security review | Security agent | `/protocol` → routes to `sec` |
| Write tests | QA agent | `/protocol` → routes to `qa` |
| Write documentation | Documentation agent | `/protocol` → routes to `doc` |
| Set up CI/CD | DevOps agent | `/protocol` → routes to `do` |
| Design UX flows | UX Designer agent | `/protocol` → routes to `uxd` (via `sd`) |
| Design visual system | UI Design System agent | `/protocol` → routes to `uids` (via `uxd`) |
| Design services | Service Designer agent | `/protocol` → routes to `sd` |
| Load a skill | cc CLI | `cc skill get <name>` |
| Search skills | cc CLI | `cc skill search "<query>"` |
| Find company docs | knowledge repo | `cc memory search "<query>"` |
| Store a decision | cc CLI | `cc memory store --type decision "<content>"` |
| Search past decisions | cc CLI | `cc memory search "<query>"` |
| Track progress | tc CLI | `tc progress` |
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
    ├── agents/                  # 16 specialist agents
    │   ├── ta.md               # Tech Architect
    │   ├── me.md               # Engineer
    │   ├── qa.md               # QA Engineer
    │   ├── do.md               # DevOps
    │   ├── doc.md              # Documentation
    │   ├── sd.md               # Service Designer
    │   ├── uxd.md              # UX Designer
    │   ├── uids.md             # UI Design System
    │   ├── uid.md              # UI Developer
    │   ├── sec.md              # Security
    │   ├── ind.md              # Industrial Designer
    │   ├── cco.md              # Creative Director
    │   ├── cw.md               # Copywriter
    │   ├── cs.md               # Customer Success  [business advisory — invoke standalone]
    │   ├── cpa.md              # CPA / Financial   [business advisory — invoke standalone]
    │   └── kc.md               # Knowledge Copilot
    └── skills/                  # Project-specific skills (optional)
```

### User Level (`~/.claude/`)
```
~/.claude/
├── copilot/                     # Claude Copilot framework (cloned repo)
│   ├── tools/
│   │   ├── cc/                 # cc CLI source (memory + skills)
│   │   └── tc/                 # tc CLI source (Task Copilot)
│   ├── .claude/
│   │   ├── agents/             # 16 agent definitions
│   │   └── commands/           # Slash command sources
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
│   ├── agents/                # 16 agent definitions (source of truth)
│   ├── commands/              # Machine and project command sources
│   └── skills/                # Skill library
├── tools/
│   ├── cc/                    # cc CLI (memory + skills)
│   └── tc/                    # tc CLI (Task Copilot)
└── templates/                 # Source for project setup
    ├── CLAUDE.template.md
    └── skills/
```

### Memory Storage (`~/.claude/memory/`)
```
~/.claude/memory/
└── [workspace-id]/            # Unique per project (path hash)
    └── memory.db              # SQLite database
        ├── initiatives        # Current and archived initiatives
        ├── memories           # Decisions, lessons, context
        └── fts_index          # FTS5 keyword search index
```

---

## The Five Pillars

### 1. Memory Copilot
**`cc memory` CLI — persistent memory with FTS5 keyword search**

| Command | Purpose |
|---------|---------|
| `cc memory store --type decision "<content>"` | Store a decision |
| `cc memory store --type lesson "<content>"` | Store a lesson |
| `cc memory store --type context "<content>"` | Store context |
| `cc memory store --type reference "<content>"` | Store a stable reference (injected at session start) |
| `cc memory search "<query>"` | Full-text keyword (FTS5) search across memories |
| `cc memory list [--type <t>]` | List memories, filterable by type |
| `cc memory index --rebuild` | Rebuild the FTS5 search index |

**Configuration:**
- `cc config set paths.shared_docs <path>`: Shared docs path (→ `CC_SHARED_DOCS`)
- `cc config set paths.knowledge_repo <path>`: Knowledge repo path (→ `CC_KNOWLEDGE_REPO`)

### 2. Agents
**16 lean agents with auto-firing skill loading**

Agents are under 120 lines each. Skills auto-fire from their trigger-rich `description` when the model matches a prompt; agents use `cc skill search` / `cc skill get` as fallback. Shared boilerplate is extracted to the "Agent Shared Behaviors" section in CLAUDE.md.

| Agent | Name | Domain |
|-------|------|--------|
| `ta` | Tech Architect | System design, ADRs, task breakdown |
| `me` | Engineer | Code implementation, refactoring |
| `qa` | QA Engineer | Testing strategy, edge cases |
| `doc` | Documentation | READMEs, API docs, technical writing |
| `do` | DevOps | CI/CD, infrastructure, containers |
| `sd` | Service Designer | Experience strategy, customer journeys |
| `uxd` | UX Designer | Interaction flows, task design |
| `uids` | UI Design System | Visual tokens, color, typography |
| `uid` | UI Developer | Component implementation specs |
| `sec` | Security | STRIDE/DREAD threat modeling |
| `ind` | Industrial Designer | Object-level essentialism (upstream of uxd) |
| `cco` | Creative Director | Brand strategy, creative direction |
| `cw` | Copywriter | Copy execution, messaging, microcopy |
| `cs` | Customer Success | Support patterns, retention (business advisory) |
| `cpa` | CPA / Financial | Tax implications, financial modeling (business advisory) |
| `kc` | Knowledge Copilot | Shared knowledge setup |

### 3. Skills (cc CLI)
**Skills auto-fire from their `description` field; `cc skill` CLI provides explicit fallback**

| Command | Purpose |
|---------|---------|
| `cc skill get <name>` | Load specific skill by name |
| `cc skill search "<query>"` | Fallback discovery — case-insensitive substring match (not FTS5) |
| `cc skill list` | List available skills |
| `cc memory search "<query>"` | Full-text keyword search across memories |
| `cc memory store --type <t> "<content>"` | Store a memory entry |
| `cc config set refs.<name> <value>` | Register a stable reference value |

**Configuration:**
- `cc config set paths.knowledge_repo <path>`: Project knowledge path
- `~/.claude/knowledge`: Global knowledge (auto-detected)
- No PostgreSQL required for local skills

### 4. Task Copilot
**CLI tool (`tc`) for ephemeral PRD, task, and work product storage**

Agents store detailed work products here instead of returning them to the main session, reducing context usage by ~96%.

| Command | Purpose |
|------|---------|
| `tc prd create --title "..." --json` | Create product requirements document |
| `tc prd get <id> --json` | Retrieve PRD details |
| `tc task create --title "..." --prd <id> --json` | Create task or subtask |
| `tc task update <id> --status <s> --json` | Update task status and notes |
| `tc task get <id> --json` | Retrieve task details |
| `tc task list [--stream N] --json` | List tasks with filters |
| `tc wp store --task <id> --type <t> --title "..." --content "..." --json` | Store agent output |
| `tc wp get <id> --json` | Retrieve full work product |
| `tc progress --json` | Get compact progress overview (~200 tokens) |
| `tc stream list --json` | List streams with progress |
| `tc stream get <id> --json` | Get detailed stream info |
| `tc handoff --from <a> --to <b> --task <id> --context "..." --json` | Agent handoff |
| `tc log --task <id> --json` | Get agent chain log |

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
| **`cc` or `tc` not found** | Run `bash ~/.claude/copilot/tools/cc/install.sh` and `pip install -e ~/.claude/copilot/tools/tc` |
| **Memory not persisting** | Run `cc memory index --rebuild`, check `~/.claude/memory/` |
| **Skill search empty** | Run `cc skill list` — confirm local skills path is set |
| **Commands not working** | Verify `.claude/commands/*.md` exist, restart Claude Code |
| **Agents not routing** | Check frontmatter in agent files, verify file is in `.claude/agents/` |
| **Extensions not loading** | Verify `knowledge-manifest.json` exists, run `cc config get paths.knowledge_repo` |
| **Outdated project files** | Run `/update-project` to sync with latest templates |
| **Knowledge search fails** | Verify knowledge repo structure, check manifest syntax |
| **Permission errors** | Check file permissions on `~/.claude/` directories |

### Verification Commands
```bash
# Check cc and tc CLIs
cc --version
tc version

# Check project setup
ls .claude/agents/ .claude/commands/

# Check memory
cc memory list | head -5

# Search memory
cc memory search "test"

# Check skills
cc skill list | head -5

# Check knowledge repo
ls "$(cc config get paths.knowledge_repo --raw)/knowledge-manifest.json" 2>/dev/null || echo "Not configured"

# Rebuild FTS5 index
cc memory index --rebuild
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
| Any | `me` | Code implementation |
| Any | `qa` | Testing strategy, verification |
| Any | `doc` | Documentation needed |
| Any | `do` | CI/CD, infrastructure |
| `sd` | `uxd` | Interaction design needed |
| `uid` | `ta` | Component spec ready for architecture |
| Any | (skill) | Security: load `security/stride-dread` |

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

### cc CLI Configuration
```bash
# Set paths (resolved as CC_SHARED_DOCS, CC_KNOWLEDGE_REPO by agents)
cc config set paths.shared_docs /path/to/shared/docs
cc config set paths.knowledge_repo /path/to/knowledge-repo

# Register stable references (injected at session start)
cc config set refs.staging_url https://staging.example.com
cc config set refs.company_wiki https://wiki.example.com

# View all config
cc config export

# Hydrate env vars in agent preambles
eval "$(cc env)"
```

### Key Environment Variables
| Variable | Source | Purpose |
|----------|--------|---------|
| `CC_SHARED_DOCS` | `cc config get paths.shared_docs` | Path to shared documentation |
| `CC_KNOWLEDGE_REPO` | `cc config get paths.knowledge_repo` | Path to knowledge repository |
| `KNOWLEDGE_REPO_PATH` | Same as above | Backward-compatible alias |
| `TASK_DB_PATH` | Shell/env | Override tc task storage path |

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
