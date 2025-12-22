# Claude Copilot Setup Guide

This guide is designed for Claude Code to read and execute. It enables setup with a single prompt.

---

## Quick Reference

| Setup Type | Prompt | What It Does |
|------------|--------|--------------|
| Machine Setup | "Read @~/.claude/copilot/SETUP.md and set up Claude Copilot on this machine." | One-time installation |
| Project Setup | "Read @~/.claude/copilot/SETUP.md and set up Claude Copilot in this project." | Per-project configuration |
| Project Setup (path) | "Read @~/.claude/copilot/SETUP.md and set up Claude Copilot in /path/to/project" | Configure specific project |

---

## Machine Setup (One-Time)

**Trigger:** User asks to "set up Claude Copilot on this machine" or similar.

### Prerequisites Check

Before proceeding, verify:

```bash
# Check Node.js version (must be 18+)
node --version

# Check for build tools (macOS)
xcode-select -p
```

**If Node.js is missing or < 18:**
- Direct user to install from https://nodejs.org (LTS version)

**If build tools are missing (macOS):**
```bash
xcode-select --install
```

### Step 1: Determine Installation Location

The standard location is `~/.claude/copilot`. Detect the user's home directory:

```bash
echo $HOME
```

Use this path (e.g., `/Users/username`) for all configurations.

### Step 2: Clone Repository

```bash
mkdir -p ~/.claude
cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
```

**If already cloned**, pull latest:
```bash
cd ~/.claude/copilot && git pull
```

### Step 3: Build Memory Copilot

```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm install
npm run build
```

**Verify build succeeded:**
```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
```

### Step 4: Build Skills Copilot

```bash
cd ~/.claude/copilot/mcp-servers/skills-copilot
npm install
npm run build
```

**Verify build succeeded:**
```bash
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
```

### Step 5: Verify Installation

Both files must exist:
- `~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js`
- `~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js`

### Step 6: Report to User

Tell the user:

```
Claude Copilot has been installed on this machine.

Installation location: ~/.claude/copilot

To use it in a project, open Claude Code in your project directory and say:
"Read @~/.claude/copilot/README.md and set up Claude Copilot in this project"

Or provide a specific path:
"Read @~/.claude/copilot/README.md and set up Claude Copilot in /path/to/project"
```

---

## Project Setup (Per-Project)

**Trigger:** User asks to "set up Claude Copilot in [path]" or "in this project".

### Step 1: Determine Paths

1. **Home directory:** Run `echo $HOME` to get the full path (e.g., `/Users/username`)
2. **Project path:** Use the path provided by the user, or current working directory
3. **Copilot source:** `$HOME/.claude/copilot`

### Step 2: Verify Machine Setup

Check that Claude Copilot is installed on the machine:

```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
```

**If not installed:** Run Machine Setup first (see above).

### Step 3: Create Directory Structure

```bash
mkdir -p /path/to/project/.claude/commands
mkdir -p /path/to/project/.claude/agents
mkdir -p /path/to/project/.claude/skills
```

### Step 4: Copy Commands

```bash
cp ~/.claude/copilot/.claude/commands/*.md /path/to/project/.claude/commands/
```

### Step 5: Copy Agents

```bash
cp ~/.claude/copilot/.claude/agents/*.md /path/to/project/.claude/agents/
```

### Step 6: Create .mcp.json

Create `/path/to/project/.mcp.json` with the user's actual home directory path:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["<HOME_PATH>/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "MEMORY_PATH": "<HOME_PATH>/.claude/memory",
        "WORKSPACE_ID": "<PROJECT_NAME>"
      }
    },
    "skills-copilot": {
      "command": "node",
      "args": ["<HOME_PATH>/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "LOCAL_SKILLS_PATH": "./.claude/skills"
      }
    }
  }
}
```

**Replace:**
- `<HOME_PATH>` with the actual home directory (e.g., `/Users/username`)
- `<PROJECT_NAME>` with the project folder name (e.g., `my-app`)

**IMPORTANT:** Do NOT use `~` - it does not expand in MCP configurations.

### Step 7: Create CLAUDE.md

Create `/path/to/project/CLAUDE.md` from the template at `~/.claude/copilot/templates/CLAUDE.template.md`.

Update the placeholders:
- `[PROJECT_NAME]` - The project name
- `[PROJECT_DESCRIPTION]` - Brief description (ask user if unknown)
- `[TECH_STACK]` - Technologies used (ask user if unknown)

### Step 8: Verify Setup

All these files/directories must exist:

```
/path/to/project/
├── .mcp.json
├── CLAUDE.md
└── .claude/
    ├── commands/
    │   ├── protocol.md
    │   └── continue.md
    ├── agents/
    │   ├── me.md
    │   ├── ta.md
    │   ├── qa.md
    │   ├── sec.md
    │   ├── doc.md
    │   ├── do.md
    │   ├── sd.md
    │   ├── uxd.md
    │   ├── uids.md
    │   ├── uid.md
    │   └── cw.md
    └── skills/
        (empty, for project-specific skills)
```

### Step 9: Report to User

Tell the user:

```
Claude Copilot has been set up in your project.

Files created:
- .mcp.json (MCP server configuration)
- CLAUDE.md (Project instructions for Claude)
- .claude/commands/ (Protocol commands)
- .claude/agents/ (Specialized agents)
- .claude/skills/ (For project-specific skills)

Next steps:
1. Restart Claude Code to load the MCP servers
2. Run /protocol to start fresh work
3. Run /continue to resume previous work

Verify setup by running /mcp - you should see:
● copilot-memory
● skills-copilot
```

---

## Troubleshooting

### Build Fails with Native Module Errors

```bash
# macOS
xcode-select --install

# Linux
sudo apt-get install build-essential python3

# Then rebuild
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm rebuild better-sqlite3
npm run build
```

### MCP Servers Not Connecting

1. Check `.mcp.json` uses absolute paths (not `~`)
2. Verify dist/index.js files exist
3. Restart Claude Code

### Commands Not Available

Verify `.claude/commands/` directory contains:
- `protocol.md`
- `continue.md`

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
chmod -R 755 /path/to/project/.claude
```

---

## What Gets Installed

### Machine Level (~/.claude/copilot/)

| Component | Purpose |
|-----------|---------|
| `mcp-servers/copilot-memory/` | Persistent memory across sessions |
| `mcp-servers/skills-copilot/` | On-demand skill loading |
| `.claude/agents/` | 11 specialized agent definitions |
| `.claude/commands/` | Protocol commands |
| `templates/` | Project setup templates |

### Project Level

| File/Directory | Purpose |
|----------------|---------|
| `.mcp.json` | MCP server configuration |
| `CLAUDE.md` | Project-specific instructions |
| `.claude/commands/` | Slash commands (/protocol, /continue) |
| `.claude/agents/` | Agent definitions |
| `.claude/skills/` | Project-specific skills |

---

## Environment Variables Reference

### Memory Copilot

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `MEMORY_PATH` | No | `~/.claude/memory` | Where databases are stored |
| `WORKSPACE_ID` | No | Auto-hash of path | Unique project identifier |

### Skills Copilot

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `LOCAL_SKILLS_PATH` | No | `./.claude/skills` | Project skills location |
| `SKILLSMP_API_KEY` | No | - | Access to 25K+ public skills |
| `POSTGRES_URL` | No | - | Team-shared private skills |
| `KNOWLEDGE_REPO_PATH` | No | - | Project-specific knowledge repository |
| `GLOBAL_KNOWLEDGE_PATH` | No | `~/.claude/knowledge` | Machine-wide knowledge repository |

---

## Knowledge Repository (Shared Knowledge)

Claude Copilot supports **two-tier knowledge resolution** for company/product information:

```
Query: "Tell me about my company"
         ↓
  1. Check project-level knowledge (KNOWLEDGE_REPO_PATH)
         ↓
  2. Check machine-level knowledge (~/.claude/knowledge)
         ↓
  3. Return matching knowledge files
```

### Setting Up Machine-Wide Shared Knowledge

Create a symlink or directory at `~/.claude/knowledge`:

```bash
# Option 1: Symlink to existing docs
ln -s /path/to/your/shared-docs ~/.claude/knowledge

# Option 2: Create new directory
mkdir -p ~/.claude/knowledge
```

**Required:** Create a `knowledge-manifest.json` in the knowledge repo:

```json
{
  "version": "1.0",
  "name": "my-company",
  "description": "Company knowledge repository"
}
```

### Knowledge Tools Available

Once configured, these tools are automatically available in every project:

| Tool | Purpose |
|------|---------|
| `knowledge_search` | Search knowledge files by query (project → global) |
| `knowledge_get` | Get specific knowledge file by path |

### Example Queries

```
"Tell me about my company"     → Searches for company info
"What is our brand voice?"     → Searches brand/voice docs
"Show me our products"         → Searches product docs
```

### Knowledge Directory Structure

Organize your knowledge repo for best search results:

```
~/.claude/knowledge/
├── knowledge-manifest.json    # Required
├── 01-company/
│   ├── 00-overview.md
│   ├── 01-brand/
│   └── 02-voice/
├── 02-products/
│   └── ...
└── 03-operations/
    └── ...
```

**Key benefit:** Set up knowledge once at `~/.claude/knowledge` and it's automatically available in every project—no per-project configuration needed
