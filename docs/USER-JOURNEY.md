# Claude Copilot User Journey

This guide walks through the complete journey from first discovering Claude Copilot to being productive with a full team of AI specialists.

---

## Quick Start Decision Matrix

| I am... | Start Here | Required Steps | Time |
|---------|------------|----------------|------|
| **First-time user (solo)** | Phase 1 → Phase 4 | Clone → Machine Setup → Project Setup → Work | 15-30 min |
| **First-time user (team member)** | Phase 1 → Phase 6 | Clone → Machine Setup → Clone Team Knowledge → Link → Project Setup | 20-40 min |
| **Have Copilot, new project** | Phase 3 | `/setup-project` in project | 2-5 min |
| **Resuming work** | `/continue` | Just load and continue | Instant |
| **Setting up team knowledge** | Phase 5 | `/knowledge-copilot` | 30-60 min |
| **Team lead (first time)** | Phase 1 → Phase 5 | Full setup + knowledge creation | 60-90 min |

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Clone          │  One-time: Get the framework               │
├─────────────────────────────────────────────────────────────────┤
│  2. Machine Setup  │  One-time: Build servers, install commands │
├─────────────────────────────────────────────────────────────────┤
│  3. Project Setup  │  Per-project: Configure and copy files     │
├─────────────────────────────────────────────────────────────────┤
│  4. Start Working  │  /protocol or /continue                    │
├─────────────────────────────────────────────────────────────────┤
│  5. Knowledge      │  Optional: Build shared company knowledge  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Discovery & Installation

You've discovered Claude Copilot and want to try it.

### Step 1: Clone the Repository

```bash
mkdir -p ~/.claude
cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
```

**What you now have:**

```
~/.claude/copilot/
├── mcp-servers/            ← Not built yet
│   ├── copilot-memory/     ← Persistence layer
│   ├── skills-copilot/     ← Knowledge layer
│   └── task-copilot/       ← Task management layer
├── .claude/
│   ├── agents/             ← 12 agent definitions (markdown)
│   └── commands/           ← Slash commands (markdown)
├── templates/              ← Project templates
├── SETUP.md                ← Setup instructions
└── README.md               ← Documentation
```

---

## Phase 2: Machine Setup

This is done once per machine. It builds the MCP servers and installs global commands.

### Step 2: Open Claude Code in the Copilot Directory

```bash
cd ~/.claude/copilot
claude
```

### Step 3: Run Machine Setup

Since Claude Copilot isn't configured yet, you need to reference the setup file directly or use the `/setup` command (which only works in `~/.claude/copilot`):

```
Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine
```

Or simply:
```
/setup
```

**What happens:**

1. **Prerequisites check** - Verifies Node.js 18+ and build tools
2. **Build Memory Server** - `npm install && npm run build`
3. **Build Skills Server** - `npm install && npm run build`
4. **Build Task Server** - `npm install && npm run build`
5. **Create directories** - `~/.claude/memory/` and `~/.claude/tasks/` for databases
6. **Install global commands** - Copies `/setup-project`, `/update-project`, `/update-copilot`, and `/knowledge-copilot` to `~/.claude/commands/`
7. **Check for knowledge** - Detects existing knowledge repository

**What you now have:**

```
~/.claude/
├── copilot/
│   └── mcp-servers/
│       ├── copilot-memory/dist/   ← Built!
│       ├── skills-copilot/dist/   ← Built!
│       └── task-copilot/dist/     ← Built!
├── commands/                       ← NEW
│   ├── setup-project.md            ← Works in any folder
│   ├── update-project.md           ← Works in any folder
│   ├── update-copilot.md           ← Works in any folder
│   └── knowledge-copilot.md        ← Works in any folder
├── memory/                         ← NEW - Memory database storage
└── tasks/                          ← NEW - Task database storage
```

**You'll see:**

```
Machine Setup Complete!

What's ready:
- Memory Server - Persists decisions, lessons, and progress
- Skills Server - Powers agents and knowledge search
- Task Server - Manages PRDs, tasks, and work products
- 12 Specialized Agents - Expert guidance for any task
- Global Commands - /setup-project, /update-project, /update-copilot, and /knowledge-copilot work anywhere

Next: Set up a project
Open Claude Code in any project directory and run /setup-project
```

---

## Phase 3: Project Setup

This is done for each project you want to use with Claude Copilot.

### Step 4: Open Claude Code in Your Project

```bash
cd ~/my-project    # Can be empty or existing code
claude
```

### Step 5: Run Project Setup

```
/setup-project
```

This works because `/setup-project` was installed globally in Phase 2.

**What happens:**

1. **Detect setup type** - Recognizes this is project setup (not machine)
2. **Verify machine setup** - Confirms MCP servers are built
3. **Create directories** - `.claude/commands/`, `.claude/agents/`, `.claude/skills/`
4. **Copy files** - All agents and commands
5. **Create .mcp.json** - MCP server configuration with correct paths
6. **Detect knowledge** - Checks for global knowledge repository
7. **Ask about project** - Description and tech stack
8. **Create CLAUDE.md** - Project instructions from template

**What you now have:**

```
~/my-project/
├── .mcp.json              ← MCP server configuration
├── CLAUDE.md              ← Project instructions for Claude
└── .claude/
    ├── commands/          ← /protocol, /continue, etc.
    ├── agents/            ← 12 specialist agents
    └── skills/            ← For project-specific skills
```

**You'll see:**

```
Project Setup Complete!

Created:
- .mcp.json - MCP server configuration
- CLAUDE.md - Project instructions
- .claude/commands/ - Protocol commands
- .claude/agents/ - 12 specialized agents
- .claude/skills/ - For project-specific skills

Next steps:
1. Restart Claude Code to load the MCP servers
2. Run /mcp to verify servers are connected
3. Run /protocol to start working
```

---

## Phase 4: Start Working

### Step 6: Restart Claude Code

```bash
claude
```

This loads the MCP servers configured in `.mcp.json`.

### Step 7: Verify Setup

```
/mcp
```

You should see:

```
● copilot-memory
● skills-copilot
● task-copilot
```

### Step 8: Start Working

**For new work:**

```
/protocol
```

This activates the Agent-First Protocol:
- Every request is classified (bug fix, feature, architecture, etc.)
- Routed to the appropriate specialist agent
- Agent investigates before responding
- You approve before execution

**To resume previous work:**

```
/continue
```

This loads from Memory Copilot:
- Current initiative and status
- What you've completed
- Decisions made and why
- Exactly where to pick up

---

## Phase 5: Knowledge Setup (Optional)

Shared knowledge lets you document company information once and access it in every project.

### Step 9: Create Knowledge Repository

```
/knowledge-copilot
```

**You'll be asked:**

1. **Mode** - Create new or link existing?
2. **Location** - Where to create (recommend `~/company-knowledge`)
3. **Company name** - Used for folder and manifest

**What happens:**

1. Creates Git repository at chosen location
2. Creates directory structure:
   ```
   ~/company-knowledge/
   ├── knowledge-manifest.json
   ├── 01-company/
   ├── 02-voice/
   ├── 03-products/
   ├── 04-standards/
   └── README.md
   ```
3. Creates symlink: `~/.claude/knowledge → ~/company-knowledge`

### Step 10: Guided Discovery

Knowledge Copilot guides you through documenting:

| Phase | What You Define |
|-------|-----------------|
| **Foundation** | Company origin, values, mission |
| **Voice** | Communication style, terminology |
| **Products/Services** | What you offer, for whom |
| **Standards** | Development, design, operations |
| **Agent Extensions** | Custom agent behaviors (optional) |

### Step 11: Push to GitHub

```
/knowledge-copilot
```

Choose to push to GitHub for team sharing:

1. Create private repo on GitHub
2. Add remote and push
3. Team members can clone and link

---

## Phase 6: Team Member Onboarding

When a new team member joins:

### Their Setup

```bash
# 1. Clone Claude Copilot
mkdir -p ~/.claude && cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot

# 2. Machine setup
cd ~/.claude/copilot && claude
> Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine

# 3. Clone team knowledge
git clone git@github.com:your-org/company-knowledge.git ~/company-knowledge

# 4. Link knowledge
claude
> /knowledge-copilot
> Choose "Link existing repository"
> Enter: ~/company-knowledge

# 5. Set up project
cd ~/work-project && claude
> /setup-project
```

**Result:** Team member has identical setup—same agents, same knowledge, same experience.

---

## Visual Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                     FIRST TIME USER                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. git clone ... ~/.claude/copilot                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. cd ~/.claude/copilot && claude                              │
│     "Read @~/.claude/copilot/SETUP.md and set up..." OR /setup │
│                                                                  │
│     ✓ Builds MCP servers                                        │
│     ✓ Installs /setup-project and other global commands        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. cd ~/any-project && claude                                  │
│     /setup-project                                               │
│                                                                  │
│     ✓ Creates .mcp.json                                         │
│     ✓ Copies agents & commands                                  │
│     ✓ Creates CLAUDE.md                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. Restart claude                                              │
│     /protocol  ← Start working!                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (optional)
┌─────────────────────────────────────────────────────────────────┐
│  5. /knowledge-copilot                                          │
│                                                                  │
│     ✓ Creates ~/company-knowledge/                              │
│     ✓ Guides discovery                                          │
│     ✓ Helps push to GitHub                                      │
│     ✓ Links to ~/.claude/knowledge                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## What's Installed Where

| Location | What | Purpose |
|----------|------|---------|
| `~/.claude/copilot/` | Framework | Source of truth for agents, commands, servers |
| `~/.claude/commands/` | Global commands | `/setup-project`, `/update-project`, `/update-copilot`, and `/knowledge-copilot` work anywhere |
| `~/.claude/memory/` | Memory databases | SQLite databases for decisions, lessons, initiatives |
| `~/.claude/tasks/` | Task databases | SQLite databases for PRDs, tasks, work products |
| `~/.claude/knowledge/` | Symlink | Points to your knowledge repository |
| `~/[company]-knowledge/` | Knowledge repo | Git-managed, shareable via GitHub |
| `[project]/.mcp.json` | Config | MCP server configuration for this project |
| `[project]/CLAUDE.md` | Instructions | Project-specific guidance for Claude |
| `[project]/.claude/` | Local copies | Agents, commands, skills for this project |

---

## Troubleshooting

### /setup-project not found in empty folder

Machine setup hasn't been run. Go to `~/.claude/copilot` and run:
```
Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine
```

Or simply:
```
/setup
```

Note: `/setup` only works when run from `~/.claude/copilot`. For projects, use `/setup-project`.

### MCP servers not connecting

1. Check `.mcp.json` uses absolute paths (not `~`)
2. Verify all servers are built: `ls ~/.claude/copilot/mcp-servers/*/dist/index.js`
   - Should show: `copilot-memory`, `skills-copilot`, `task-copilot`
3. Restart Claude Code

### Knowledge not found

1. Check symlink exists: `ls -la ~/.claude/knowledge`
2. Verify manifest: `cat ~/.claude/knowledge/knowledge-manifest.json`
3. Re-run `/knowledge-copilot` to link

---

## Next Steps

- [Meet Your Team](AGENTS.md) - Learn about all 12 specialist agents
- [Configuration Guide](CONFIGURATION.md) - Detailed setup options
- [Customization](CUSTOMIZATION.md) - Extend and personalize
- [Philosophy](PHILOSOPHY.md) - Why we built it this way
