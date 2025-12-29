# Claude Copilot Machine Setup

You are a friendly setup assistant. This command sets up Claude Copilot on the user's machine. It should only be run from the Claude Copilot repository (`~/.claude/copilot`).

## Step 1: Verify Running From Correct Location

```bash
pwd
```

**If NOT in `~/.claude/copilot` or similar:**

Tell user:

---

**This command is for machine setup only.**

It should be run from the Claude Copilot repository at `~/.claude/copilot`.

**For project operations, use:**
- `/setup-project` - Initialize a new project
- `/update-project` - Update an existing project

---

Then STOP.

---

## Step 2: Welcome Message

---

**Welcome to Claude Copilot Machine Setup!**

I'll set up Claude Copilot on your machine. This includes:
- Building the Memory server (persists your work between sessions)
- Building the Skills server (powers specialized agents and knowledge search)
- Building the Task server (manages PRDs, tasks, and work products)
- Installing global commands (`/setup-project`, `/update-project`, `/knowledge-copilot`)

Let me check what's already in place...

---

## Step 3: Check Prerequisites

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

## Step 4: Build Memory Server

Tell user: "Building Memory Server..."

```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
```

---

## Step 5: Build Skills Server

Tell user: "Building Skills Server..."

```bash
cd ~/.claude/copilot/mcp-servers/skills-copilot && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
```

---

## Step 6: Build Task Server

Tell user: "Building Task Server..."

```bash
cd ~/.claude/copilot/mcp-servers/task-copilot && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/task-copilot/dist/index.js
```

---

## Step 7: Create Data Directories

```bash
mkdir -p ~/.claude/memory
mkdir -p ~/.claude/tasks
```

---

## Step 8: Install Global Commands

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
```

Tell user: "Installing global commands..."

**Verify:**
```bash
ls ~/.claude/commands/
```

Should show: `setup-project.md`, `update-project.md`, `update-copilot.md`, `knowledge-copilot.md`

---

## Step 9: Check for Global Knowledge

```bash
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "KNOWLEDGE_EXISTS" || echo "NO_KNOWLEDGE"
```

Store result for reporting.

---

## Step 10: Report Success

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
/setup-project
```

---

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
- Celebrate completion!
