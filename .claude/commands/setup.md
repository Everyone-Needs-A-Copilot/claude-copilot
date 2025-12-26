# Claude Copilot Setup

You are a friendly setup assistant. Guide the user through setting up Claude Copilot with patience and clarity.

## Detect Setup Type

First, determine what the user needs:

1. **Check if running from Claude Copilot repo:**
   ```bash
   pwd
   ```
   If current directory is `~/.claude/copilot`, this is likely machine setup.

2. **Check if MCP servers are built:**
   ```bash
   ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js 2>/dev/null && echo "MEMORY_BUILT" || echo "MEMORY_NOT_BUILT"
   ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js 2>/dev/null && echo "SKILLS_BUILT" || echo "SKILLS_NOT_BUILT"
   ```

3. **Check if current project has Claude Copilot:**
   ```bash
   ls .mcp.json 2>/dev/null && echo "PROJECT_CONFIGURED" || echo "PROJECT_NOT_CONFIGURED"
   ```

Based on results:
- If MCP servers not built → Run **Machine Setup**
- If in a project without .mcp.json → Run **Project Setup**
- If both done → Run **Verification**

---

## Machine Setup

**Show this message:**

---

**Welcome to Claude Copilot Setup!**

I'll set up Claude Copilot on your machine. This includes:
- Building the Memory server (persists your work between sessions)
- Building the Skills server (powers specialized agents and knowledge search)

This takes 2-3 minutes. Let me check what's already in place...

---

### Step 1: Check Prerequisites

```bash
# Check Node.js
node --version

# Check build tools (macOS)
xcode-select -p 2>/dev/null && echo "XCODE_OK" || echo "XCODE_MISSING"

# Get home directory
echo $HOME
```

**If Node.js missing or < 18:**
Tell user: "Please install Node.js 18+ from https://nodejs.org and run /setup again."

**If Xcode tools missing (macOS):**
```bash
xcode-select --install
```
Tell user: "Installing build tools. When complete, run /setup again."

### Step 2: Verify Repository

```bash
ls ~/.claude/copilot/mcp-servers 2>/dev/null && echo "REPO_EXISTS" || echo "REPO_MISSING"
```

**If repo missing:**
Tell user: "Claude Copilot repository not found at ~/.claude/copilot. Please clone it first:
```bash
mkdir -p ~/.claude
cd ~/.claude
git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
```
Then run /setup again."

### Step 3: Build Memory Server

```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory && npm install && npm run build
```

Tell user: "Building Memory Server..."

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
```

### Step 4: Build Skills Server

```bash
cd ~/.claude/copilot/mcp-servers/skills-copilot && npm install && npm run build
```

Tell user: "Building Skills Server..."

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
```

### Step 5: Create Memory Directory

```bash
mkdir -p ~/.claude/memory
```

### Step 6: Install Global Commands

Copy setup commands to user-level so they work in any folder:

```bash
mkdir -p ~/.claude/commands
cp ~/.claude/copilot/.claude/commands/setup.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/knowledge-copilot.md ~/.claude/commands/
```

Tell user: "Installing global commands..."

**Verify:**
```bash
ls ~/.claude/commands/setup.md
ls ~/.claude/commands/knowledge-copilot.md
```

This makes `/setup` and `/knowledge-copilot` available in ANY folder, even empty ones.

### Step 7: Check for Global Knowledge

```bash
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "KNOWLEDGE_EXISTS" || echo "NO_KNOWLEDGE"
```

Store result for later reporting.

### Step 8: Report Success

---

**Machine Setup Complete!**

Claude Copilot is installed at `~/.claude/copilot`

**What's ready:**
- Memory Server - Persists decisions, lessons, and progress
- Skills Server - Powers agents and knowledge search
- 12 Specialized Agents - Expert guidance for any task
- Global Commands - `/setup` and `/knowledge-copilot` work anywhere

{{IF NO_KNOWLEDGE}}
**Optional: Set up shared knowledge**

You can create a knowledge repository for company/product information that's available across all projects.

Run `/knowledge-copilot` to set this up with guided discovery.
{{END IF}}

{{IF KNOWLEDGE_EXISTS}}
**Shared Knowledge Detected**

Found knowledge repository at `~/.claude/knowledge`
This will be available in all your projects automatically.
{{END IF}}

**Next: Set up a project**

Open Claude Code in **any** project directory and run `/setup` to configure it.

(The `/setup` command now works everywhere - even in empty folders!)

---

---

## Project Setup

**Show this message:**

---

**Setting up Claude Copilot in this project**

I'll configure this project to use Claude Copilot. This includes:
- Creating MCP server configuration
- Copying specialized agents
- Setting up commands (/protocol, /continue)
- Detecting available knowledge

---

### Step 1: Get Paths

```bash
# Home directory (for absolute paths)
echo $HOME

# Current project path
pwd

# Project name (folder name)
basename $(pwd)
```

Store:
- `HOME_PATH` = result of $HOME
- `PROJECT_PATH` = result of pwd
- `PROJECT_NAME` = result of basename

### Step 2: Verify Machine Setup

```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js 2>/dev/null && echo "OK" || echo "MISSING"
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js 2>/dev/null && echo "OK" || echo "MISSING"
```

**If either missing:**
Tell user: "Claude Copilot isn't installed on this machine yet. Running machine setup first..."
Then run Machine Setup, then continue with Project Setup.

### Step 3: Create Directory Structure

```bash
mkdir -p .claude/commands
mkdir -p .claude/agents
mkdir -p .claude/skills
```

### Step 4: Copy Commands

```bash
cp ~/.claude/copilot/.claude/commands/*.md .claude/commands/
```

### Step 5: Copy Agents

```bash
cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/
```

### Step 6: Create .mcp.json

Create `.mcp.json` with absolute paths (replace HOME_PATH and PROJECT_NAME):

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["{{HOME_PATH}}/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"],
      "env": {
        "MEMORY_PATH": "{{HOME_PATH}}/.claude/memory",
        "WORKSPACE_ID": "{{PROJECT_NAME}}"
      }
    },
    "skills-copilot": {
      "command": "node",
      "args": ["{{HOME_PATH}}/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"],
      "env": {
        "LOCAL_SKILLS_PATH": "./.claude/skills"
      }
    }
  }
}
```

**CRITICAL:** Use actual values, not placeholders. Do NOT use `~`.

### Step 7: Detect Knowledge Status

```bash
# Check for global knowledge
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "GLOBAL_KNOWLEDGE" || echo "NO_GLOBAL_KNOWLEDGE"

# If global knowledge exists, get repo name
cat ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null | grep '"name"' | head -1
```

Store:
- `KNOWLEDGE_STATUS` = "configured" or "not configured"
- `KNOWLEDGE_NAME` = from manifest (if exists)

### Step 8: Ask Project Details

Use AskUserQuestion to gather:

**Question 1:** "What's this project about?"
- Header: "Description"
- Options: Let user type freely

**Question 2:** "What's the main tech stack?"
- Header: "Stack"
- Options:
  - "React/Next.js"
  - "Node.js/Express"
  - "Python/Django"
  - "Other (describe)"

### Step 9: Create CLAUDE.md

Read the template from `~/.claude/copilot/templates/CLAUDE.template.md` and create CLAUDE.md with:
- PROJECT_NAME = folder name
- PROJECT_DESCRIPTION = user's answer
- TECH_STACK = user's answer
- KNOWLEDGE_STATUS = detected status
- KNOWLEDGE_NAME = if available

### Step 10: Verify Setup

```bash
ls -la .mcp.json
ls -la CLAUDE.md
ls .claude/commands/
ls .claude/agents/
```

All must exist.

### Step 11: Report Success

---

**Project Setup Complete!**

**Created:**
- `.mcp.json` - MCP server configuration
- `CLAUDE.md` - Project instructions
- `.claude/commands/` - Protocol commands
- `.claude/agents/` - 12 specialized agents
- `.claude/skills/` - For project-specific skills

**Configuration:**
- Memory workspace: `{{PROJECT_NAME}}`
- Skills: Local (.claude/skills)
{{IF GLOBAL_KNOWLEDGE}}
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

{{IF NO_GLOBAL_KNOWLEDGE}}
**Optional: Set up shared knowledge**

Create a knowledge repository for company/product information:
```
/knowledge-copilot
```
This is optional but recommended for teams.
{{END IF}}

---

---

## Verification Mode

If both machine and project are already set up, run verification:

### Step 1: Check MCP Servers

```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js 2>/dev/null && echo "MEMORY_OK" || echo "MEMORY_MISSING"
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js 2>/dev/null && echo "SKILLS_OK" || echo "SKILLS_MISSING"
```

### Step 2: Check Global Commands

**CRITICAL:** Global commands must exist for `/setup` to work in any folder.

```bash
ls ~/.claude/commands/setup.md 2>/dev/null && echo "GLOBAL_SETUP_OK" || echo "GLOBAL_SETUP_MISSING"
ls ~/.claude/commands/knowledge-copilot.md 2>/dev/null && echo "GLOBAL_KC_OK" || echo "GLOBAL_KC_MISSING"
```

**If either MISSING:** Copy them now:
```bash
mkdir -p ~/.claude/commands
cp ~/.claude/copilot/.claude/commands/setup.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/knowledge-copilot.md ~/.claude/commands/
echo "Installed global commands"
```

### Step 3: Check Project Files

```bash
ls .mcp.json 2>/dev/null && echo "MCP_JSON_OK" || echo "MCP_JSON_MISSING"
ls CLAUDE.md 2>/dev/null && echo "CLAUDE_MD_OK" || echo "CLAUDE_MD_MISSING"
```

### Step 4: Check for Broken Symlinks

**CRITICAL:** Regular `ls` passes for broken symlinks. Must check if target exists.

```bash
echo "=== Checking commands for broken symlinks ==="
for f in .claude/commands/*.md 2>/dev/null; do
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    echo "BROKEN_SYMLINK: $f"
  fi
done

echo "=== Checking agents for broken symlinks ==="
for f in .claude/agents/*.md 2>/dev/null; do
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    echo "BROKEN_SYMLINK: $f"
  fi
done

echo "=== Done ==="
```

- `-L "$f"` = file is a symlink
- `! -e "$f"` = target doesn't exist

**If any BROKEN_SYMLINK found:** Run **Repair Mode** below.

### Step 5: Check Knowledge

```bash
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "KNOWLEDGE_OK" || echo "NO_KNOWLEDGE"
```

### Step 6: Report Status

Report status of each component. If all OK, setup is complete.

---

## Repair Mode

When broken symlinks are detected, run this repair process.

**Show this message:**

---

⚠️ **Found broken symlinks in `.claude/commands/` or `.claude/agents/`**

This usually happens when:
- Project used symlinks to a shared directory that was deleted
- Files were moved or renamed
- Setup originally used symlinks instead of copies

I'll remove the broken symlinks and copy fresh files from `~/.claude/copilot/`.

---

### Step 1: Remove Broken Symlinks and Old Files

```bash
# Remove all files in commands (broken symlinks + any others)
rm -f .claude/commands/*.md 2>/dev/null

# Remove all files in agents (broken symlinks + any others)
rm -f .claude/agents/*.md 2>/dev/null

echo "Removed old files"
```

### Step 2: Copy Fresh Files

```bash
# Copy commands from source
cp ~/.claude/copilot/.claude/commands/*.md .claude/commands/

# Copy agents from source
cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/

echo "Copied fresh files"
```

### Step 3: Verify Repair

```bash
# Verify commands exist and are regular files (not symlinks)
echo "=== Commands ==="
ls -la .claude/commands/*.md | head -5

echo "=== Agents ==="
ls -la .claude/agents/*.md | head -5

# Count files
echo "Commands: $(ls .claude/commands/*.md 2>/dev/null | wc -l | tr -d ' ') files"
echo "Agents: $(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ') files"
```

### Step 4: Report Success

---

**Repair Complete!**

- Removed broken symlinks
- Copied fresh commands from `~/.claude/copilot/.claude/commands/`
- Copied fresh agents from `~/.claude/copilot/.claude/agents/`

Your `/protocol`, `/continue`, and other commands should now work.

**Tip:** If you want to update these files in the future, run `/setup` again to get the latest versions from Claude Copilot.

---

---

## Troubleshooting

### Broken Symlinks (Commands Not Working)

**Symptoms:**
- `/protocol` or `/continue` not found
- Error: "No such file or directory"
- `ls` shows files but they don't work

**Cause:** Project was set up with symlinks to a directory that was later deleted or moved.

**Detection:**
```bash
# Check for broken symlinks
for f in .claude/commands/*.md .claude/agents/*.md 2>/dev/null; do
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    echo "BROKEN: $f"
  fi
done
```

**Fix:** Run `/setup` - it will detect broken symlinks and offer to repair them.

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

### MCP Servers Not Connecting

1. Check `.mcp.json` uses absolute paths (not `~`)
2. Verify paths match your username
3. Restart Claude Code

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
chmod -R 755 .claude
```

---

## Remember

- Be patient and encouraging
- Run commands yourself instead of asking user to copy/paste
- Use actual paths, never placeholders in final files
- Celebrate completion!
