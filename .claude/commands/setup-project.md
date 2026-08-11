# Setup Project

Initialize a new project with Claude Copilot. This command only works on projects that haven't been set up yet.

## Step 1: Verify This Is a New Project

```bash
if [ -d .claude ] && { ls .claude/commands/*.md >/dev/null 2>&1 || ls .claude/agents/*.md >/dev/null 2>&1; }; then
  echo "PROJECT_EXISTS"
else
  echo "NEW_PROJECT"
fi
```

**If PROJECT_EXISTS:**

Stop and tell the user:

---

**This project is already configured.**

A `.claude/` directory with framework files was found — this project has already been set up with Claude Copilot.

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
# Resolve cc: prefer PATH, but also check ~/.local/bin directly.
# Guard against /usr/bin/cc (macOS C compiler) by verifying the banner.
_cc_bin=""
_cc_candidate="$(command -v cc 2>/dev/null)"
if [ -n "$_cc_candidate" ] && "$_cc_candidate" --version 2>/dev/null | grep -q "^cc version"; then
  _cc_bin="$_cc_candidate"
elif [ -x "$HOME/.local/bin/cc" ] && "$HOME/.local/bin/cc" --version 2>/dev/null | grep -q "^cc version"; then
  _cc_bin="$HOME/.local/bin/cc"
  export PATH="$HOME/.local/bin:$PATH"
fi
[ -n "$_cc_bin" ] && echo "CC_OK" || echo "CC_MISSING"

# Resolve tc: pip installs into the active Python's bin (e.g. /opt/homebrew/bin),
# which is already on PATH. No fallback path needed.
command -v tc >/dev/null 2>&1 && echo "TC_OK" || echo "TC_MISSING"
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

**Note:** If `cc` was just installed, your shell may not have picked up `~/.local/bin` yet. Try opening a new terminal first, then re-run `/setup-project`.

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
mkdir -p .claude/hooks
```

---

## Step 5: Copy Project Commands

Copy every project-level command (VERSION.json's `components.commands.projectCommands`: protocol, continue, pause, map, memory, extensions, orchestrate). A fresh project gets the full command set immediately — it does not have to wait for `/update-project` to close the gap.

```bash
cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/pause.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/map.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/memory.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/extensions.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/orchestrate.md .claude/commands/
```

**Verify:**
```bash
ls .claude/commands/
```

Should show all 7 project commands: `continue.md`, `extensions.md`, `map.md`, `memory.md`, `orchestrate.md`, `pause.md`, `protocol.md`

---

## Step 6: Copy Agents

Copy only framework-owned agents (from the roster manifest in VERSION.json). This preserves any project-specific agents that may already exist.

```bash
# Read framework agent roster from VERSION.json. One agent id PER LINE --
# never space-joined -- so the loop below reads it with `while read`
# instead of relying on word-splitting an unquoted scalar. bash splits an
# unquoted `$ROSTER` on IFS whitespace by default; zsh does NOT, so
# `for agent in $ROSTER` silently ran ONCE with the entire roster as a
# single value under zsh (this machine's login shell) -- every agent copy
# below was a silent no-op, while the step still reported success with
# its own freshly-computed counts. Verified live under both shells.
COPILOT_PATH=~/.claude/copilot
ROSTER=$(python3 -c "
import json, sys
with open('$COPILOT_PATH/VERSION.json') as f:
    v = json.load(f)
agents = list(v['components']['agents']['frameworkAgents'])
agents.append('kc')  # setup-only agent; VERSION.json's frameworkAgents deliberately excludes it
print('\n'.join(agents))
" 2>/dev/null || printf '%s\n' cco cpa cs cw do doc ind kc me qa sd sec ta uid uids uxd)

# `while read` off a herestring (not a pipe) runs in THIS shell, not a
# subshell, and is correct under both bash and zsh regardless of
# word-splitting settings, since it never relies on unquoted splitting.
while IFS= read -r agent; do
  [ -z "$agent" ] && continue
  if [ -f "$COPILOT_PATH/.claude/agents/${agent}.md" ]; then
    existing=".claude/agents/${agent}.md"
    if [ -f "$existing" ] && grep -q '^owner: project' "$existing" 2>/dev/null; then
      echo "preserved project-owned agent: ${agent}"
    else
      cp "$COPILOT_PATH/.claude/agents/${agent}.md" .claude/agents/
    fi
  fi
done <<< "$ROSTER"
```

**Verify:**
```bash
ls .claude/agents/ | wc -l
```

Should show one file per `$ROSTER` entry — the full specialist roster (every framework agent plus kc).

---

## Step 6B: Install Enforcement Hook

Vendor the framework's enforcement hook shim into the project and register it in `.claude/settings.json`. This is the ONLY hook file ever copied into a project — it carries no rule content of its own and delegates every rule to the global framework install (see the shim's own header comment for its resolution order and fail-open/fail-closed policy). Registration is a non-destructive structural merge via `cc settings-hook add`: it never touches hooks a human already added, and running it again later (e.g. via `/update-project`) is a no-op if nothing changed.

```bash
mkdir -p .claude/hooks
cp ~/.claude/copilot/.claude/hooks/copilot-hook.sh .claude/hooks/copilot-hook.sh
chmod +x .claude/hooks/copilot-hook.sh

cc settings-hook add
```

**Verify:**
```bash
ls -la .claude/hooks/copilot-hook.sh
```

Should be present and executable.

---

## Step 6C: Generate Project Lock (claude component)

Generate `copilot.lock.json`'s `claude` component entry from what is genuinely on disk in THIS project -- real per-path sha256 checksums computed here, never a value copied from the framework source or another project's lock (RC-4: `projects.generate_component_lock_entry()`). A candidate path whose own frontmatter declares `owner: project` is never recorded as framework-owned -- that exclusion lives inside the generator itself, so a hand-authored agent stays out of the lock's `files[]` automatically. This step reads back any existing `copilot.lock.json` first (e.g. the `mutations[]` ledger `cc settings-hook add` just wrote in Step 6B, and any `codex` component entry) and only replaces the `claude` entry -- everything else in the file is preserved untouched.

This step is self-contained (recomputes the agent roster from `VERSION.json` itself rather than reusing Step 6's `$ROSTER`): each fenced command block in this file may run as its own shell invocation, so nothing here depends on shell state set by an earlier step.

```bash
COPILOT_PATH=~/.claude/copilot
python3 -c "
import json
from pathlib import Path
from cc.core.ecosystem.projects import (
    generate_component_lock_entry,
    read_project_lock,
    write_project_lock,
    PROJECT_LOCK_FILENAME,
)

copilot_path = Path('$COPILOT_PATH').expanduser()
with open(copilot_path / 'VERSION.json') as f:
    v = json.load(f)
roster = list(v['components']['agents']['frameworkAgents'])
roster.append('kc')  # setup-only agent; VERSION.json's frameworkAgents deliberately excludes it
version = v.get('framework', 'unknown')
release_tag = ('v' + version) if version != 'unknown' else 'unknown'

candidate_paths = [
    '.claude/commands/protocol.md', '.claude/commands/continue.md',
    '.claude/commands/pause.md', '.claude/commands/map.md',
    '.claude/commands/memory.md', '.claude/commands/extensions.md',
    '.claude/commands/orchestrate.md',
    '.claude/fitness-check.sh', '.claude/hooks/copilot-hook.sh',
] + [f'.claude/agents/{agent}.md' for agent in roster]

root = Path('.').resolve()
entry = generate_component_lock_entry(
    root, 'claude',
    version=version, release_tag=release_tag, ownership_mode='full',
    candidate_paths=candidate_paths,
)

lock_path = root / PROJECT_LOCK_FILENAME
manifest = read_project_lock(lock_path)
if not isinstance(manifest, dict):
    manifest = {}
manifest.setdefault('schema_version', '1.0')
existing = manifest.get('components')
components = (
    [c for c in existing if isinstance(c, dict) and c.get('component') != 'claude']
    if isinstance(existing, list) else []
)
components.append(entry)
components.sort(key=lambda c: str(c.get('component', '')))
manifest['components'] = components
write_project_lock(lock_path, manifest)
print(f'copilot.lock.json: claude component generated ({len(entry[\"files\"])} files, version {version})')
" 2>&1 || echo "WARN: could not generate copilot.lock.json's claude component (is the cc package importable from python3?). The project is still usable; re-run /setup-project or /update-project later to retry."
```

**Verify:**
```bash
python3 -c "
import json
d = json.load(open('copilot.lock.json'))
c = [x for x in d.get('components', []) if x.get('component') == 'claude']
print('claude component present:', bool(c))
print('files recorded:', len(c[0]['files']) if c else 0)
" 2>/dev/null || echo "copilot.lock.json missing or unreadable"
```

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
- OUTPUT_VERBOSITY = `cc config get output.verbosity --raw` (falls back to `concise` if unset)
- OUTPUT_AUDIENCE = `cc config get output.audience --raw` (falls back to `plain` if unset)

---

## Step 11: Verify Setup

```bash
ls -la .mcp.json
ls -la CLAUDE.md
ls .claude/commands/
ls .claude/agents/ | head -5
ls -la .claude/hooks/copilot-hook.sh

AGENT_COUNT=$(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ')
COMMAND_COUNT=$(ls .claude/commands/*.md 2>/dev/null | wc -l | tr -d ' ')
echo "AGENT_COUNT=$AGENT_COUNT"
echo "COMMAND_COUNT=$COMMAND_COUNT"
```

All must exist.

Store:
- `AGENT_COUNT` = measured count of `.claude/agents/*.md` (used in the Step 12 report — never hardcoded)
- `COMMAND_COUNT` = measured count of `.claude/commands/*.md` (used in the Step 12 report — never hardcoded)

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
- `.claude/commands/` - {{COMMAND_COUNT}} project commands (protocol, continue, pause, map, memory, extensions, orchestrate)
- `.claude/agents/` - {{AGENT_COUNT}} agent files: framework agents + kc (setup-only, full specialist roster)
- `.claude/hooks/copilot-hook.sh` - Enforcement hook shim, registered in `.claude/settings.json`
- `.claude/skills/` - For project-specific skills
- `.claude/memory/entries/` - Project memory (committed to git)
- `.claude/cc/config.json` - cc CLI project config
- `copilot.lock.json` - Per-project component lock, generated from what's actually installed (not a copied template)

**Configuration:**
- Memory: `.claude/memory/entries/` (committed files)
- Skills: Local (`.claude/skills/`)
- Output: verbosity `{{OUTPUT_VERBOSITY}}`, audience `{{OUTPUT_AUDIENCE}}` (machine default — override here with `cc config set output.verbosity <level> --project`)
{{IF GLOBAL_KNOWLEDGE_EXISTS}}
- Knowledge: `{{KNOWLEDGE_NAME}}` (global)
{{ELSE}}
- Knowledge: Not configured
{{END IF}}

**Codex Copilot (separate, optional step):**
This command sets up Claude Code only — it never touches `plugins/codex-copilot/`. If this project also uses Codex, install the Codex half separately by running `codex-copilot`'s own installer (`scripts/setup-project.sh` in the `codex-copilot` repo). This project is not Codex-enabled until that step is run.

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
