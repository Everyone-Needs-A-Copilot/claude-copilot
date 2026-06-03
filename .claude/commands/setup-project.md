# Setup Project

Initialize a new project with Claude Copilot. This command only works on projects that haven't been set up yet.

## Step 1: Verify This Is a New Project

```bash
ls .mcp.json 2>/dev/null && echo "PROJECT_EXISTS" || echo "NEW_PROJECT"
```

**If PROJECT_EXISTS:**

Stop and tell the user:

---

**This project is already configured.**

Found `.mcp.json` - this project has already been set up with Claude Copilot.

To update this project with the latest Claude Copilot files, use:

```
/update-project
```

---

Then STOP. Do not continue.

**If NEW_PROJECT:** Continue to Step 1B.

---

## Step 1B: Check for Minimal Setup

Look at the user's message for keywords: "minimal", "quick start", "memory only", "simple", "fast"

**If found:** Set `SETUP_MODE` = "MINIMAL" and continue to Step 2.
**If not found:** Set `SETUP_MODE` = "FULL" and continue to Step 2.

---

## Step 2: Verify Machine Setup

```bash
which cc >/dev/null 2>&1 && echo "CC_OK" || echo "CC_MISSING"
which tc >/dev/null 2>&1 && echo "TC_OK" || echo "TC_MISSING"
```

**If any MISSING:**

Tell user:

---

**Claude Copilot CLIs not found.**

Please complete machine setup first:

1. Clone the repository:
   ```bash
   mkdir -p ~/.claude
   cd ~/.claude
   git clone https://github.com/Everyone-Needs-A-Copilot/claude-copilot.git copilot
   ```

2. Open Claude Code in `~/.claude/copilot` and run `/setup`

Then return here and run `/setup-project` again.

---

Then STOP.

**If SETUP_MODE = "MINIMAL":** Skip to [Minimal Setup Flow](#minimal-setup-flow).

---

## Step 3: Get Project Info

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

## Step 4: Create Directory Structure

```bash
mkdir -p .claude/commands
mkdir -p .claude/agents
mkdir -p .claude/skills
```

---

## Step 5: Copy Project Commands

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

## Step 6: Copy Agents

Copy only framework-owned agents (from the roster manifest in VERSION.json). This preserves any project-specific agents that may already exist.

```bash
# Read framework agent roster from VERSION.json
COPILOT_PATH=~/.claude/copilot
ROSTER=$(python3 -c "
import json, sys
with open('$COPILOT_PATH/VERSION.json') as f:
    v = json.load(f)
agents = v['components']['agents']['frameworkAgents']
print(' '.join(agents))
" 2>/dev/null || echo "cco cpa cs cw do doc ind kc me qa sd sec ta uid uids uxd")

for agent in $ROSTER; do
  if [ -f "$COPILOT_PATH/.claude/agents/${agent}.md" ]; then
    cp "$COPILOT_PATH/.claude/agents/${agent}.md" .claude/agents/
  fi
done
```

**Verify:**
```bash
ls .claude/agents/ | wc -l
```

Should show 16 framework agents.

---

## Step 7: Create .mcp.json

Claude Copilot no longer ships MCP servers. The `.mcp.json` file is still created as a marker that this project is set up, and to allow adding third-party MCP servers later.

```bash
printf '{"mcpServers":{}}\n' > .mcp.json
```

**Validate JSON:**
```bash
python3 -c "import json,sys; json.load(open('.mcp.json')); print('JSON valid')"
```

---

## Step 7B: Initialize cc Project Config

Tell user: "Initializing cc project config..."

```bash
cc config init --project
```

This creates `.claude/cc/config.json` with `@machine` sentinel defaults so project config can reference machine-level paths without duplicating them.

**Add memory files to .gitignore:**

```bash
# Add SQLite index (gitignored — local cache only)
if ! grep -q '\.claude/memory/memory\.db' .gitignore 2>/dev/null; then
  printf '\n# cc memory index (local SQLite cache)\n.claude/memory/memory.db\n.claude/memory/memory.db-*\n' >> .gitignore
fi
```

**Track the entries directory:**

```bash
mkdir -p .claude/memory/entries
touch .claude/memory/entries/.gitkeep
```

---

## Step 8: Detect Knowledge

### 8.1: Check Global Knowledge

```bash
ls ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null && echo "GLOBAL_KNOWLEDGE_EXISTS" || echo "NO_GLOBAL_KNOWLEDGE"
cat ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null | grep '"name"' | head -1
```

Store:
- `GLOBAL_KNOWLEDGE_EXISTS` = true/false
- `KNOWLEDGE_NAME` = from manifest (if exists)

### 8.2: Check Project Expectation

Look for signals that this project expects knowledge:

```bash
# Check if CLAUDE.md references knowledge tools
grep -q "knowledge_search\|knowledge_get" CLAUDE.md 2>/dev/null && echo "PROJECT_EXPECTS_KNOWLEDGE" || echo "NO_EXPECTATION"

# Check for team repo URL in existing manifest (if any)
cat ~/.claude/knowledge/knowledge-manifest.json 2>/dev/null | grep '"repository"' -A2 | grep '"url"'
```

Store:
- `PROJECT_EXPECTS_KNOWLEDGE` = true/false
- `TEAM_REPO_URL` = if found in manifest

### 8.3: Decision Matrix

| Global | Expects | Action |
|--------|---------|--------|
| Yes | Any | Status: configured |
| No | Yes | Offer knowledge setup (see below) |
| No | No | Status: not configured |

**If NO_GLOBAL_KNOWLEDGE but PROJECT_EXPECTS_KNOWLEDGE:**

Use AskUserQuestion to offer knowledge setup:

**Question:** "This project references team knowledge, but none is configured on this machine. Would you like to set it up?"
**Header:** "Knowledge"
**Options:**
1. **"Yes, set up knowledge now"** - Will run /knowledge-copilot after setup
2. **"Skip for now"** - Continue without knowledge (can run /knowledge-copilot later)

Store user's choice in `SETUP_KNOWLEDGE_NOW`.

---

## Step 9: Ask Project Details

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

## Step 10: Create CLAUDE.md

Read the template from `~/.claude/copilot/templates/CLAUDE.template.md` and create CLAUDE.md with:
- PROJECT_NAME = folder name
- PROJECT_DESCRIPTION = user's answer
- TECH_STACK = user's answer
- KNOWLEDGE_STATUS = detected status
- KNOWLEDGE_NAME = if available

---

## Step 11: Verify Setup

```bash
ls -la .mcp.json
ls -la CLAUDE.md
ls .claude/commands/
ls .claude/agents/ | head -5
```

All must exist.

---

## Step 11B: Run Fitness Check

Run the fitness check to verify the agent roster is healthy:

```bash
# Copy fitness-check.sh from copilot source
cp ~/.claude/copilot/.claude/fitness-check.sh .claude/fitness-check.sh
chmod +x .claude/fitness-check.sh

bash .claude/fitness-check.sh \
  --agents-dir .claude/agents \
  --commands-dir .claude/commands \
  --copilot-path ~/.claude/copilot
FITNESS_RESULT=$?
```

If `FITNESS_RESULT` is non-zero (check failed), print the failures and tell the user:

---

**Fitness check reported issues.** Review the failures above. The project was created but the agent roster has problems. Run `/update-project` after resolving them.

---

---

## Step 12: Report Success

---

**Project Setup Complete!**

**Created:**
- `.mcp.json` - Project marker (empty MCP config; add third-party servers here as needed)
- `CLAUDE.md` - Project instructions
- `.claude/commands/` - Protocol commands (/protocol, /continue)
- `.claude/agents/` - 16 framework agents (full specialist roster)
- `.claude/skills/` - For project-specific skills
- `.claude/memory/entries/` - Project memory (committed to git)
- `.claude/cc/config.json` - cc CLI project config

**Configuration:**
- Memory: `.claude/memory/entries/` (committed files)
- Skills: Local (`.claude/skills/`)
{{IF GLOBAL_KNOWLEDGE_EXISTS}}
- Knowledge: `{{KNOWLEDGE_NAME}}` (global)
{{ELSE}}
- Knowledge: Not configured
{{END IF}}

**Next steps:**

1. Run `/protocol` to start working
2. Use `cc memory search "<query>"` to search past decisions

**Using Skills:**
- Local skills: `@include .claude/skills/NAME/SKILL.md` in your prompts
- Search skills: `cc skill search "<query>"`

{{IF NO_GLOBAL_KNOWLEDGE AND NOT SETUP_KNOWLEDGE_NOW}}
**Optional: Set up shared knowledge**

Create a knowledge repository for company/product information:
```
/knowledge-copilot
```
{{END IF}}

---

{{IF SETUP_KNOWLEDGE_NOW}}
## Step 13: Set Up Knowledge

Since you chose to set up knowledge now, running `/knowledge-copilot`:

**Note:** This will guide you through connecting to your team's knowledge repository.

---
{{END IF}}

---

## Minimal Setup Flow

This flow is triggered when `SETUP_MODE` = "MINIMAL". It installs only the `continue` command for the fastest path to getting started.

Report:
```
Mode: Minimal Setup

What you'll get:
- /continue command - Resume previous work
- cc memory - Persistent session memory via CLI

What you WON'T get:
- Agents - No specialized expertise
- /protocol command - No Agent-First workflow

You can upgrade to the full framework anytime by running /setup-project again (without "minimal").
```

### Minimal Step 1: Get Project Info

```bash
pwd
basename $(pwd)
```

Store:
- `PROJECT_PATH` = result of pwd
- `PROJECT_NAME` = result of basename

### Minimal Step 2: Create Directory and Copy Continue Command

```bash
mkdir -p .claude/commands
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
```

**Verify:**
```bash
ls .claude/commands/
```

Should show: `continue.md`

### Minimal Step 3: Create .mcp.json

```bash
printf '{"mcpServers":{}}\n' > .mcp.json
```

### Minimal Step 4: Initialize cc Project Config and Memory

```bash
cc config init --project
mkdir -p .claude/memory/entries
touch .claude/memory/entries/.gitkeep
printf 'memory.db\nmemory.db-*\n' > .claude/memory/.gitignore
```

### Minimal Step 5: Create Minimal CLAUDE.md

Create a minimal CLAUDE.md:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

**Name:** {{PROJECT_NAME}}

---

## Claude Copilot (Minimal Setup)

This project uses the minimal Claude Copilot configuration.

### What You Have

| Feature | Status |
|---------|--------|
| **cc memory** | Enabled — persistent cross-session memory as committed files |
| **`/continue` command** | Enabled — resume previous work |
| **Agents** | Not installed |
| **`/protocol`** | Not installed |

### Commands

| Command | Purpose |
|---------|---------|
| `/continue` | Resume previous work |

### Memory CLI

| Command | Purpose |
|---------|---------|
| `cc memory store "<note>"` | Store decisions, lessons, context |
| `cc memory search "<query>"` | Semantic search across memories |
| `cc memory list` | List recent entries |

---

## Upgrading to Full Framework

When you're ready for agents and the full protocol:

1. Run `/setup-project` again (without "minimal")
2. This will add all agents and commands
3. Your memory will be preserved
```

Replace `{{PROJECT_NAME}}` with the actual project name. Write to `CLAUDE.md`.

### Minimal Step 6: Verify and Report

```bash
ls -la .mcp.json
ls -la CLAUDE.md
ls .claude/commands/
```

Report:

---

**Minimal Setup Complete!**

**Created:**
- `.mcp.json` - Project marker
- `CLAUDE.md` - Project instructions (minimal)
- `.claude/commands/continue.md` - Resume command
- `.claude/memory/entries/` - Memory storage
- `.claude/cc/config.json` - cc project config

**Next steps:**

1. Run `/continue` to resume previous work
2. Use `cc memory store "<note>"` to persist decisions

**To upgrade to full framework later:**
Run `/setup-project` again (without saying "minimal").

---

Then STOP.

---

## Remember

- Be patient and encouraging
- Run commands yourself instead of asking user to copy/paste
- Use actual paths, never placeholders in final files
