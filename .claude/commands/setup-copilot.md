---
name: setup-copilot
description: Universal Claude Copilot setup. Auto-detects context and runs appropriate setup.
---

# Universal Setup Command

This command auto-detects your context and runs the appropriate setup. No need to know which command to run - this figures it out for you.

## Step 1: Detect Context

Determine which mode to run:

```bash
# Get current directory
pwd

# Check if .mcp.json exists
ls .mcp.json 2>/dev/null && echo "MCP_EXISTS" || echo "NO_MCP"

# Get home directory for comparison
echo $HOME
```

Store:
- `CURRENT_DIR` = result of pwd
- `HOME_PATH` = result of $HOME
- `MCP_STATUS` = "MCP_EXISTS" or "NO_MCP"

**Check for minimal setup request:**

Look at the user's message for keywords:
- "minimal"
- "quick start"
- "memory only"
- "simple"
- "fast"

If found, set `SETUP_MODE` = "MINIMAL"

**Determine mode:**

1. **If CURRENT_DIR ends with `/.claude/copilot`:**
   → **Machine Setup Mode**

2. **Else if MCP_STATUS = "MCP_EXISTS":**
   → **Update Mode**

3. **Else if SETUP_MODE = "MINIMAL":**
   → **Minimal Setup Mode**

4. **Else:**
   → **Project Setup Mode**

---

## Step 2: Report Detected Mode

### Machine Setup Mode

Report:
```
Detected: Claude Copilot directory (~/.claude/copilot)
Mode: Machine Setup

This will:
- Build Memory Copilot MCP server
- Build Skills Copilot MCP server
- Build Task Copilot MCP server
- Install global commands
- Create data directories (memory, tasks)
```

Then proceed to Step 3A.

---

### Update Mode

Report:
```
Detected: Existing project configuration (.mcp.json found)
Mode: Update

This will:
- Update commands to latest versions
- Update agents to latest versions
- Preserve your customizations
- Keep .mcp.json unchanged
```

Then proceed to Step 3B.

---

### Minimal Setup Mode

Report:
```
Detected: New project (no .mcp.json)
Mode: Minimal Setup (Memory Only)

This is the fastest path to get started - just 5 steps!

What you'll get:
✓ Memory Copilot - Session persistence and context
✓ /continue command - Resume previous work
✓ Automatic progress tracking

What you WON'T get:
✗ Agents - No specialized expertise
✗ Skills Copilot - No on-demand skills
✗ /protocol command - No Agent-First workflow

You can upgrade to the full framework anytime.
See docs/QUICK-START.md for details.
```

Then proceed to Step 3C-Minimal.

---

### Project Setup Mode

Report:
```
Detected: New project (no .mcp.json)
Mode: Project Setup (Full Framework)

This will:
- Create .claude/ directory structure
- Copy agents and commands
- Create .mcp.json with expanded template variables
- Create CLAUDE.md
```

Then proceed to Step 3C.

---

## Step 3A: Execute Machine Setup

Follow the complete flow from `/setup` command:

### 3A.1: Welcome Message

---

**Welcome to Claude Copilot Machine Setup!**

I'll set up Claude Copilot on your machine. This includes:
- Building the Memory server (persists your work between sessions)
- Building the Skills server (powers specialized agents and knowledge search)
- Building the Task server (manages PRDs, tasks, and work products)
- Installing global commands (`/setup-project`, `/update-project`, `/knowledge-copilot`)

Let me check what's already in place...

---

### 3A.2: Check Prerequisites

```bash
# Check Node.js
node --version

# Check build tools (macOS)
xcode-select -p 2>/dev/null && echo "XCODE_OK" || echo "XCODE_MISSING"

# Get home directory
echo $HOME
```

**If Node.js missing or < 18:**
Tell user: "Please install Node.js 18+ from https://nodejs.org and run this setup again."
Then STOP.

**If Xcode tools missing (macOS):**
```bash
xcode-select --install
```
Tell user: "Installing build tools. When complete, run this setup again."
Then STOP.

---

### 3A.3: Build Memory Server

Tell user: "Building Memory Server..."

```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
```

---

### 3A.4: Build Skills Server

Tell user: "Building Skills Server..."

```bash
cd ~/.claude/copilot/mcp-servers/skills-copilot && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
```

---

### 3A.5: Build Task Server

Tell user: "Building Task Server..."

```bash
cd ~/.claude/copilot/mcp-servers/task-copilot && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/task-copilot/dist/index.js
```

---

### 3A.6: Create Data Directories

```bash
mkdir -p ~/.claude/memory
mkdir -p ~/.claude/tasks
```

---

### 3A.7: Install Global Commands

Install commands that work in any folder:

```bash
mkdir -p ~/.claude/commands

# Project management commands
cp ~/.claude/copilot/.claude/commands/setup-project.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/update-project.md ~/.claude/commands/

# Maintenance command
cp ~/.claude/copilot/.claude/commands/update-copilot.md ~/.claude/commands/

# Knowledge setup command
cp ~/.claude/copilot/.claude/commands/knowledge-copilot.md ~/.claude/commands/

# Universal setup command
cp ~/.claude/copilot/.claude/commands/setup-copilot.md ~/.claude/commands/
```

Tell user: "Installing global commands..."

**Verify:**
```bash
ls ~/.claude/commands/
```

Should show: `setup-project.md`, `update-project.md`, `update-copilot.md`, `knowledge-copilot.md`, `setup-copilot.md`

---

### 3A.8: Check for Global Knowledge

```bash
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "KNOWLEDGE_EXISTS" || echo "NO_KNOWLEDGE"
```

Store result for reporting.

---

### 3A.9: Report Success

---

**Machine Setup Complete!**

Claude Copilot is installed at `~/.claude/copilot`

**What's ready:**
- Memory Server - Persists decisions, lessons, and progress
- Skills Server - Powers agents and knowledge search
- Task Server - Manages PRDs, tasks, and work products
- 12 Specialized Agents - Expert guidance for any task

**Global commands installed:**
| Command | Purpose |
|---------|---------|
| `/setup-copilot` | Universal setup (auto-detects context) |
| `/setup-project` | Initialize a new project |
| `/update-project` | Update an existing project |
| `/update-copilot` | Update Claude Copilot itself |
| `/knowledge-copilot` | Set up shared knowledge |

{{IF NO_KNOWLEDGE}}
**Optional: Set up shared knowledge**

You can create a knowledge repository for company/product information that's available across all projects.

Run `/knowledge-copilot` to set this up.
{{END IF}}

{{IF KNOWLEDGE_EXISTS}}
**Shared Knowledge Detected**

Found knowledge repository at `~/.claude/knowledge`
This will be available in all your projects automatically.
{{END IF}}

**Next: Set up a project**

Open Claude Code in any project directory and run:
```
/setup-copilot
```

---

Then STOP.

---

## Step 3B: Execute Update Mode

Follow the complete flow from `/update-project` command:

### 3B.1: Verify Machine Setup

```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js 2>/dev/null && echo "MEMORY_OK" || echo "MEMORY_MISSING"
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js 2>/dev/null && echo "SKILLS_OK" || echo "SKILLS_MISSING"
ls ~/.claude/copilot/mcp-servers/task-copilot/dist/index.js 2>/dev/null && echo "TASK_OK" || echo "TASK_MISSING"
```

**If any MISSING:**

Tell user:

---

**Claude Copilot installation not found.**

The MCP servers at `~/.claude/copilot/` are missing or not built.

Please verify your Claude Copilot installation:
```bash
cd ~/.claude/copilot
git pull
```

Then rebuild the MCP servers following the instructions in `SETUP.md`.

---

Then STOP.

---

### 3B.2: Check for Broken Symlinks

**CRITICAL:** Regular `ls` passes for broken symlinks. Must check if target exists.

```bash
echo "=== Checking commands for broken symlinks ==="
BROKEN_FOUND=0
for f in .claude/commands/*.md 2>/dev/null; do
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    echo "BROKEN_SYMLINK: $f"
    BROKEN_FOUND=1
  fi
done

echo "=== Checking agents for broken symlinks ==="
for f in .claude/agents/*.md 2>/dev/null; do
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    echo "BROKEN_SYMLINK: $f"
    BROKEN_FOUND=1
  fi
done

if [ $BROKEN_FOUND -eq 0 ]; then
  echo "No broken symlinks found"
fi
```

Note any broken symlinks found - they will be fixed in the update.

---

### 3B.3: Show Current State

```bash
echo "=== Current Commands ==="
ls -la .claude/commands/*.md 2>/dev/null | head -5

echo "=== Current Agents ==="
ls .claude/agents/*.md 2>/dev/null | wc -l
echo "agent files"

echo "=== Claude Copilot Version ==="
cd ~/.claude/copilot && git log --oneline -1
```

---

### 3B.4: Confirm Update

Tell the user:

---

**Ready to update project**

This will refresh:
- `.claude/commands/protocol.md` and `continue.md`
- `.claude/agents/*.md` (all 12 agents)

This will NOT touch:
- `.mcp.json` (your MCP configuration)
- `CLAUDE.md` (your project instructions)
- `.claude/skills/` (your project skills)

---

Use AskUserQuestion:

**Question:** "Proceed with update?"
- Header: "Confirm"
- Options:
  - "Yes, update now"
  - "No, cancel"

**If cancelled:** Stop and tell user "Update cancelled."

---

### 3B.5: Update Commands

Remove old command files and copy fresh ones:

```bash
# Remove old project commands (only protocol and continue)
rm -f .claude/commands/protocol.md 2>/dev/null
rm -f .claude/commands/continue.md 2>/dev/null

# Copy fresh from source
cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/

echo "Commands updated"
```

---

### 3B.6: Update Agents

Remove old agent files and copy fresh ones:

```bash
# Remove all old agents
rm -f .claude/agents/*.md 2>/dev/null

# Copy fresh from source
cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/

echo "Agents updated"
```

---

### 3B.7: Verify Update

```bash
echo "=== Updated Commands ==="
ls -la .claude/commands/*.md

echo "=== Updated Agents ==="
ls .claude/agents/*.md | wc -l
echo "agent files"

echo "=== Verification ==="
# Check commands are regular files (not symlinks)
for f in .claude/commands/*.md; do
  if [ -L "$f" ]; then
    echo "WARNING: $f is still a symlink"
  else
    echo "OK: $f"
  fi
done
```

---

### 3B.8: Report Success

---

**Project Updated!**

**Refreshed:**
- `.claude/commands/protocol.md`
- `.claude/commands/continue.md`
- `.claude/agents/` (12 agents)

**Unchanged:**
- `.mcp.json`
- `CLAUDE.md`
- `.claude/skills/`

**Claude Copilot version:**
`{{VERSION_FROM_GIT_LOG}}`

Your project now has the latest Claude Copilot commands and agents.

---

Then STOP.

---

## Step 3C-Minimal: Execute Minimal Setup (Memory Only)

This is the streamlined setup for Memory Copilot only.

### 3C-Minimal.1: Verify Machine Setup

```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js 2>/dev/null && echo "MEMORY_OK" || echo "MEMORY_MISSING"
```

**If MEMORY_MISSING:**

Tell user:

---

**Memory Copilot is not built yet.**

First, build the Memory Copilot server:

```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm install
npm run build
```

Then run this setup again.

For detailed instructions, see: `docs/QUICK-START.md`

---

Then STOP.

---

### 3C-Minimal.2: Get Project Info

```bash
echo $HOME
pwd
basename $(pwd)
```

Store:
- `HOME_PATH` = result of $HOME
- `PROJECT_PATH` = result of pwd
- `PROJECT_NAME` = result of basename

---

### 3C-Minimal.3: Create Directory Structure

Create only the commands directory (no agents, no skills):

```bash
mkdir -p .claude/commands
```

---

### 3C-Minimal.4: Copy Continue Command

Copy only the continue command:

```bash
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
```

**Verify:**
```bash
ls .claude/commands/
```

Should show: `continue.md`

---

### 3C-Minimal.5: Create .mcp.json with Minimal Template

Read the minimal template and expand variables:

```bash
cat ~/.claude/copilot/templates/minimal-mcp.json
```

**Expand these variables:**

| Variable | Value | Example |
|----------|-------|---------|
| `$HOME` | User's home directory | `/Users/pabs` |
| `$PROJECT_PATH` | Current working directory | `/Users/pabs/Sites/my-app` |
| `$PROJECT_NAME` | Directory basename | `my-app` |
| `$COPILOT_PATH` | Claude Copilot location | `$HOME/.claude/copilot` |

**Process:**

1. Read template from `~/.claude/copilot/templates/minimal-mcp.json`
2. Replace all variables:
   - `$HOME` → actual home path (NO tilde)
   - `$PROJECT_PATH` → result of `pwd`
   - `$PROJECT_NAME` → result of `basename $(pwd)`
   - `$COPILOT_PATH` → `$HOME/.claude/copilot` (expanded)
3. Validate expansion
4. Write to `.mcp.json`

**CRITICAL:**
- All paths must be absolute (no `~` or `$HOME` in final output)
- No unexpanded variables (`$xxx`) in final file
- Verify JSON is valid

**Validation After Expansion:**

```bash
# Check for unexpanded variables
grep -E '\$[A-Z_]+' .mcp.json && echo "ERROR: Unexpanded variables found" || echo "Variables OK"

# Verify memory server exists
ls -l "$HOME/.claude/copilot/mcp-servers/copilot-memory/dist/index.js" && echo "Memory server OK" || echo "Memory server MISSING"

# Validate JSON
node -e "JSON.parse(require('fs').readFileSync('.mcp.json', 'utf8'))" && echo "JSON valid" || echo "JSON INVALID"
```

---

### 3C-Minimal.6: Create Minimal CLAUDE.md

Create a minimal CLAUDE.md with only memory configuration:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

**Name:** {{PROJECT_NAME}}

---

## Claude Copilot (Minimal Setup)

This project uses Memory Copilot only - the minimal Claude Copilot configuration.

**Full documentation:** `~/.claude/copilot/docs/QUICK-START.md`

### What You Have

| Feature | Status |
|---------|--------|
| **Memory Copilot** | Enabled - Persistent session memory |
| **`/continue` command** | Enabled - Resume previous work |
| **Agents** | Not installed |
| **Skills** | Not installed |
| **`/protocol`** | Not installed |

### Commands

| Command | Purpose |
|---------|---------|
| `/continue` | Resume previous work via Memory Copilot |

### Memory Tools

| Tool | Purpose |
|------|---------|
| `initiative_start` | Begin new initiative |
| `initiative_get` | Retrieve current initiative |
| `initiative_update` | Update progress, decisions, lessons |
| `initiative_complete` | Archive completed initiative |
| `memory_store` | Store decisions, lessons, context |
| `memory_search` | Semantic search across memories |

### Configuration

- Memory workspace: `{{PROJECT_NAME}}`
- Memory path: `~/.claude/memory/`

---

## Upgrading to Full Framework

When you're ready for agents, skills, and the full protocol:

1. Run `/setup-copilot` again (without "minimal")
2. This will add all agents, skills, and commands
3. Your memory will be preserved

See `~/.claude/copilot/SETUP.md` for full setup.

---

## Session Management

**Resume work:** `/continue` - Loads from Memory Copilot

**End session:** Just close Claude Code - progress auto-saves

**Explicit update:**
```
initiative_update({
  completed: ["Tasks finished"],
  inProgress: "Current state",
  resumeInstructions: "Next steps",
  lessons: ["Insights gained"],
  decisions: ["Choices made"],
  keyFiles: ["file1.ts"]
})
```

---
```

Replace `{{PROJECT_NAME}}` with the actual project name.

Write to `CLAUDE.md`.

---

### 3C-Minimal.7: Verify Setup

```bash
ls -la .mcp.json
ls -la CLAUDE.md
ls .claude/commands/
```

All must exist.

---

### 3C-Minimal.8: Report Success

---

**Minimal Setup Complete! (Memory Only)**

**Created:**
- `.mcp.json` - Memory Copilot configuration
- `CLAUDE.md` - Project instructions (minimal)
- `.claude/commands/continue.md` - Resume command

**Configuration:**
- Memory workspace: `{{PROJECT_NAME}}`
- Memory path: `~/.claude/memory/`

**What you have:**
✓ Persistent memory across sessions
✓ `/continue` command to resume work
✓ Decision and lesson tracking

**What you DON'T have:**
✗ 12 specialized agents
✗ Skills Copilot
✗ `/protocol` command
✗ Knowledge repository integration

**Next steps:**

1. **Restart Claude Code** to load Memory Copilot
2. Run `/mcp` to verify connection:
   ```
   ● copilot-memory
   ```
3. Test with `/continue` or start using memory tools directly

**To upgrade to full framework:**

Run `/setup-copilot` again (without saying "minimal") to add:
- All 12 agents
- Skills Copilot
- Task Copilot
- `/protocol` command
- Full documentation

**Documentation:**
- Quick start guide: `~/.claude/copilot/docs/QUICK-START.md`
- Full setup: `~/.claude/copilot/SETUP.md`

---

Then STOP.

---

## Step 3C: Execute Project Setup

Follow the complete flow from `/setup-project` command:

### 3C.1: Verify Machine Setup

```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js 2>/dev/null && echo "MEMORY_OK" || echo "MEMORY_MISSING"
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js 2>/dev/null && echo "SKILLS_OK" || echo "SKILLS_MISSING"
ls ~/.claude/copilot/mcp-servers/task-copilot/dist/index.js 2>/dev/null && echo "TASK_OK" || echo "TASK_MISSING"
```

**If any MISSING:**

Tell user:

---

**Claude Copilot is not installed on this machine.**

Please complete machine setup first:

1. Clone the repository:
   ```bash
   mkdir -p ~/.claude
   cd ~/.claude
   git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
   ```

2. Open Claude Code in `~/.claude/copilot` and run `/setup-copilot`

Then return here and run `/setup-copilot` again.

---

Then STOP.

---

### 3C.2: Get Project Info

```bash
echo $HOME
pwd
basename $(pwd)
```

Store:
- `HOME_PATH` = result of $HOME
- `PROJECT_PATH` = result of pwd
- `PROJECT_NAME` = result of basename

---

### 3C.3: Create Directory Structure

```bash
mkdir -p .claude/commands
mkdir -p .claude/agents
mkdir -p .claude/skills
```

---

### 3C.4: Copy Project Commands

Only copy commands that belong at project level (protocol and continue):

```bash
cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
```

**Verify:**
```bash
ls .claude/commands/
```

Should show: `continue.md` and `protocol.md`

---

### 3C.5: Copy Agents

```bash
cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/
```

**Verify:**
```bash
ls .claude/agents/ | wc -l
```

Should show 12+ files.

---

### 3C.6: Create .mcp.json with Template Variable Expansion

Read the template and expand variables automatically:

```bash
cat ~/.claude/copilot/templates/mcp.json
```

**Expand these variables:**

| Variable | Value | Example |
|----------|-------|---------|
| `$HOME` | User's home directory | `/Users/pabs` |
| `$PROJECT_PATH` | Current working directory | `/Users/pabs/Sites/my-app` |
| `$PROJECT_NAME` | Directory basename | `my-app` |
| `$COPILOT_PATH` | Claude Copilot location | `$HOME/.claude/copilot` |

**Process:**

1. Read template from `~/.claude/copilot/templates/mcp.json`
2. Replace all variables:
   - `$HOME` → actual home path (NO tilde)
   - `$PROJECT_PATH` → result of `pwd`
   - `$PROJECT_NAME` → result of `basename $(pwd)`
   - `$COPILOT_PATH` → `$HOME/.claude/copilot` (expanded)
3. Validate expansion (see validation below)
4. Write to `.mcp.json`

**CRITICAL:**
- All paths must be absolute (no `~` or `$HOME` in final output)
- No unexpanded variables (`$xxx`) in final file
- Verify JSON is valid

**Validation After Expansion:**

```bash
# Check for unexpanded variables
grep -E '\$[A-Z_]+' .mcp.json && echo "ERROR: Unexpanded variables found" || echo "Variables OK"

# Verify critical paths exist
ls -l "$HOME/.claude/copilot/mcp-servers/copilot-memory/dist/index.js" && echo "Memory server OK" || echo "Memory server MISSING"
ls -l "$HOME/.claude/copilot/mcp-servers/skills-copilot/dist/index.js" && echo "Skills server OK" || echo "Skills server MISSING"
ls -l "$HOME/.claude/copilot/mcp-servers/task-copilot/dist/index.js" && echo "Task server OK" || echo "Task server MISSING"

# Validate JSON
node -e "JSON.parse(require('fs').readFileSync('.mcp.json', 'utf8'))" && echo "JSON valid" || echo "JSON INVALID"
```

**If validation fails:**

Report clear error with fix instructions:

```
ERROR: Template expansion failed

Variable: $COPILOT_PATH
Expected: ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
Found: File does not exist

Fix: Run /setup-copilot from ~/.claude/copilot first to build MCP servers
```

---

### 3C.7: Detect Knowledge

```bash
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "KNOWLEDGE_EXISTS" || echo "NO_KNOWLEDGE"
cat ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null | grep '"name"' | head -1
```

Store:
- `KNOWLEDGE_STATUS` = "configured" or "not configured"
- `KNOWLEDGE_NAME` = from manifest (if exists)

---

### 3C.8: Ask Project Details

Use AskUserQuestion to gather:

**Question 1:** "What's this project about?"
- Header: "Description"
- Let user type freely

**Question 2:** "What's the main tech stack?"
- Header: "Stack"
- Options:
  - "React/Next.js"
  - "Node.js/Express"
  - "Python/Django"
  - "Other (describe)"

---

### 3C.9: Create CLAUDE.md

Read the template from `~/.claude/copilot/templates/CLAUDE.template.md` and create CLAUDE.md with:
- PROJECT_NAME = folder name
- PROJECT_DESCRIPTION = user's answer
- TECH_STACK = user's answer
- KNOWLEDGE_STATUS = detected status
- KNOWLEDGE_NAME = if available

---

### 3C.10: Verify Setup

```bash
ls -la .mcp.json
ls -la CLAUDE.md
ls .claude/commands/
ls .claude/agents/ | head -5
```

All must exist.

---

### 3C.11: Report Success

---

**Project Setup Complete!**

**Created:**
- `.mcp.json` - MCP server configuration
- `CLAUDE.md` - Project instructions
- `.claude/commands/` - Protocol commands (/protocol, /continue)
- `.claude/agents/` - 12 specialized agents
- `.claude/skills/` - For project-specific skills

**Configuration:**
- Memory workspace: `{{PROJECT_NAME}}`
- Skills: Local (.claude/skills)
{{IF KNOWLEDGE_EXISTS}}
- Knowledge: `{{KNOWLEDGE_NAME}}` (global)
{{ELSE}}
- Knowledge: Not configured
{{END IF}}

**Next steps:**

1. **Restart Claude Code** to load the MCP servers
2. Run `/mcp` to verify servers are connected:
   ```
   ● copilot-memory
   ● skills-copilot
   ```
3. Run `/protocol` to start working

{{IF NO_KNOWLEDGE}}
**Optional: Set up shared knowledge**

Create a knowledge repository for company/product information:
```
/knowledge-copilot
```
{{END IF}}

---

Then STOP.

---

## Troubleshooting

### Build Fails

**"gyp ERR!" or native module errors:**
```bash
# macOS
xcode-select --install

# Then rebuild
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm rebuild better-sqlite3
npm run build
```

**"npm: command not found":**
- Install Node.js from https://nodejs.org

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
```

---

## Remember

- Be patient and encouraging
- Run commands yourself instead of asking user to copy/paste
- Use actual paths, never placeholders in final files
- Celebrate completion!
