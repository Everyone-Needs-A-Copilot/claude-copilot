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
- Installing the `tc` CLI (manages PRDs, tasks, and work products)
- Installing the `cc` CLI (unified memory and skills manager)
- Installing global commands (`/setup-project`, `/update-project`, `/knowledge-copilot`)

Let me check what's already in place...

---

## Step 3: Check Prerequisites

```bash
# Check Python 3
python3 --version

# Get home directory
echo $HOME
```

**If Python 3 missing:**
Tell user: "Please install Python 3.9+ and run this setup again."
Then STOP.

---

## Step 4: Install tc CLI

Tell user: "Installing tc CLI (Task Copilot)..."

```bash
pip install -e ~/.claude/copilot/tools/tc
```

**Verify:**
```bash
tc version
```

---

## Step 5: Create Data Directories

```bash
mkdir -p ~/.claude/tasks
```

---

## Step 6: Install Global Commands

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

Should show: `setup-copilot.md`, `setup-project.md`, `update-project.md`, `update-copilot.md`, `knowledge-copilot.md`

---

## Step 7: Install cc CLI

Tell user: "Installing cc CLI (memory and skills manager)..."

```bash
bash ~/.claude/copilot/tools/cc/install.sh
```

**Verify:**
```bash
cc --version
```

### Step 7B: Initialize Machine Config

```bash
cc config init --machine
```

Create required directories:

```bash
mkdir -p ~/.claude/cache/models ~/.claude/skills
printf 'config.json\n' > ~/.claude/cc/.gitignore
```

### Step 7C: Configure Machine-Level Paths

Use AskUserQuestion to gather optional paths:

**Question 1:** "Path to your shared-docs repository (optional, press Enter to skip)"
- Header: "Shared Docs Path"
- Let user type freely or press Enter

**Question 2:** "Path to your knowledge repository (optional, press Enter to skip)"
- Header: "Knowledge Repo Path"
- Let user type freely or press Enter

For each non-empty path provided, run:
```bash
cc config set shared_docs <path>   # if provided
cc config set knowledge_repo <path>  # if provided
```

Then verify:
```bash
cc config doctor
```

---

## Step 8: Check for Global Knowledge

```bash
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "KNOWLEDGE_EXISTS" || echo "NO_KNOWLEDGE"
```

Store result for reporting.

---

## Step 9: Report Success

---

**Machine Setup Complete!**

Claude Copilot is installed at `~/.claude/copilot`

**What's ready:**
- tc CLI - Manages PRDs, tasks, and work products
- cc CLI - Unified memory and skills manager (replaces MCP servers)
- 16 Specialist Agents - Expert guidance for any task

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
/setup-project
```

---

## Troubleshooting

### cc Install Fails

```bash
# Retry manually
bash ~/.claude/copilot/tools/cc/install.sh

# Verify PATH includes ~/.local/bin
echo $PATH
# Add if missing: export PATH="$HOME/.local/bin:$PATH"
```

### tc Install Fails

```bash
pip3 install -e ~/.claude/copilot/tools/tc
tc version
```

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
```

---

## Remember

- Be patient and encouraging
- Run commands yourself instead of asking user to copy/paste
- Celebrate completion!
