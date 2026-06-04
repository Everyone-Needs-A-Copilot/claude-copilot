# Update Project

Update an existing Claude Copilot project with the latest files. This command only works on projects that have already been set up.

## Step 1: Verify This Is an Existing Project

```bash
ls .mcp.json 2>/dev/null && echo "PROJECT_EXISTS" || echo "NEW_PROJECT"
```

**If NEW_PROJECT:**

Stop and tell the user:

---

**This project hasn't been set up yet.**

No `.mcp.json` found - this project needs initial setup first.

To set up this project with Claude Copilot, use:

```
/setup-project
```

---

Then STOP. Do not continue.

**If PROJECT_EXISTS:** Continue to Step 2.

---

## Step 2: Verify Machine Setup

```bash
which cc >/dev/null 2>&1 && echo "CC_CLI_OK" || echo "CC_CLI_MISSING"
which tc >/dev/null 2>&1 && echo "TC_CLI_OK" || echo "TC_CLI_MISSING"
```

**If any MISSING:**

Tell user:

---

**Claude Copilot CLIs not found.**

One or more required CLIs (`cc`, `tc`) are missing.

Please run machine setup first:
```bash
cd ~/.claude/copilot
/setup
```

Or install manually:
```bash
bash ~/.claude/copilot/tools/cc/install.sh
pip install -e ~/.claude/copilot/tools/tc
```

---

Then STOP.

---

## Step 3: Check and Update MCP Server Configuration

**Read both configurations:**

```bash
cat .mcp.json
cat ~/.claude/copilot/templates/mcp.json
```

**Identify missing servers:**

Compare the `mcpServers` keys in project's `.mcp.json` with the template.

For each server in the template that is NOT in the project's `.mcp.json`:
1. Note the server name
2. Prepare to add it with variable expansion:
   - `$HOME` → actual home directory path
   - `$PROJECT_PATH` → result of `pwd`
   - `$PROJECT_NAME` → result of `basename $(pwd)`
   - `$COPILOT_PATH` → `$HOME/.claude/copilot`

**If missing servers found:**

Tell the user:

---

**New MCP servers available**

The following servers will be added to your `.mcp.json`:

{{LIST_MISSING_SERVERS}}

This will preserve all existing server configurations and only add new ones.

---

Use AskUserQuestion:

**Question:** "Add these new servers to .mcp.json?"
- Header: "MCP Configuration Update"
- Options:
  - "Yes, add new servers"
  - "No, skip this step"

**If user says "Yes, add new servers":**

1. Read the existing `.mcp.json` as JSON
2. For each missing server from template:
   - Expand all variables (`$HOME`, `$PROJECT_PATH`, `$PROJECT_NAME`, `$COPILOT_PATH`)
   - Add the server entry to `mcpServers` object
3. Write the merged JSON back to `.mcp.json` with proper formatting (2-space indent)
4. Validate the JSON is well-formed
5. Report success: "Added {{SERVER_NAMES}} to .mcp.json"

**If user says "No, skip this step":**

Continue to Step 4 without modifying `.mcp.json`.

**If no missing servers:**

Report: "All MCP servers already configured, no updates needed."

Continue to Step 4.

---

## Step 4: Check for Broken Symlinks

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

## Step 5: Show Current State

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

## Step 6: Confirm Update

Tell the user:

---

**Ready to update project**

This will refresh:
- `.claude/commands/` (7 project commands)
- `.claude/agents/` (16 framework agents — roster-aware: preserves project-specific agents, removes retired agents)
- `.claude/orchestrator/` (if present - Python scripts and shell utilities)

This will ONLY update if needed:
- `.mcp.json` (only to add new MCP servers, preserving all existing configuration)

This will NOT touch:
- `CLAUDE.md` (your project instructions)
- `.claude/skills/` (your project skills)
- Project-specific agent files (only framework-owned agents from VERSION.json roster are updated)
- Existing MCP server configurations in `.mcp.json`

---

Use AskUserQuestion:

**Question:** "Proceed with update?"
- Header: "Confirm"
- Options:
  - "Yes, update now"
  - "No, cancel"

**If cancelled:** Stop and tell user "Update cancelled."

---

## Step 7: Update Commands

Remove old command files and copy fresh ones:

```bash
# Remove old project commands
rm -f .claude/commands/protocol.md 2>/dev/null
rm -f .claude/commands/continue.md 2>/dev/null
rm -f .claude/commands/pause.md 2>/dev/null
rm -f .claude/commands/map.md 2>/dev/null
rm -f .claude/commands/memory.md 2>/dev/null
rm -f .claude/commands/extensions.md 2>/dev/null
rm -f .claude/commands/orchestrate.md 2>/dev/null

# Copy fresh from source (all project-level commands)
cp ~/.claude/copilot/.claude/commands/protocol.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/continue.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/pause.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/map.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/memory.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/extensions.md .claude/commands/
cp ~/.claude/copilot/.claude/commands/orchestrate.md .claude/commands/

echo "Commands updated (7 project commands)"
```

---

## Step 8: Update Agents (Roster-Aware Sync)

Refresh only framework-owned agents; preserve any project-specific agents.

**Project-owned agent override:** If an existing agent file contains `owner: project` in its frontmatter, sync will never overwrite or remove it — even if its name appears in the framework roster. To override a framework agent at the project level, add `owner: project` to its frontmatter.

```bash
COPILOT_PATH=~/.claude/copilot

# Read framework agent roster from VERSION.json
ROSTER=$(python3 -c "
import json, sys
with open('$COPILOT_PATH/VERSION.json') as f:
    v = json.load(f)
agents = v['components']['agents']['frameworkAgents']
print(' '.join(agents))
" 2>/dev/null || echo "cco cpa cs cw do doc ind kc me qa sd sec ta uid uids uxd")

# Also read retired agents list to remove any stale copies
RETIRED=$(python3 -c "
import json, sys
with open('$COPILOT_PATH/VERSION.json') as f:
    v = json.load(f)
retired = v['components']['agents'].get('retired', [])
print(' '.join(retired))
" 2>/dev/null || echo "design")

# Remove retired agents from project (they should not remain)
# Exception: never remove an agent marked owner: project
for agent in $RETIRED; do
  if [ -f ".claude/agents/${agent}.md" ]; then
    if grep -q '^owner: project' ".claude/agents/${agent}.md" 2>/dev/null; then
      echo "preserved project-owned agent: ${agent} (skipping retired-agent removal)"
    else
      rm -f ".claude/agents/${agent}.md"
      echo "Removed retired agent: ${agent}.md"
    fi
  fi
done

# Refresh framework-owned agents only (preserve project-specific agents)
# Convention: if an existing agent file has frontmatter "owner: project", skip it
UPDATED=0
PROJECT_OWNED_SKIPPED=""
for agent in $ROSTER; do
  if [ -f "$COPILOT_PATH/.claude/agents/${agent}.md" ]; then
    existing=".claude/agents/${agent}.md"
    if [ -f "$existing" ] && grep -q '^owner: project' "$existing" 2>/dev/null; then
      echo "preserved project-owned agent: ${agent}"
      PROJECT_OWNED_SKIPPED="$PROJECT_OWNED_SKIPPED $agent"
    else
      cp "$COPILOT_PATH/.claude/agents/${agent}.md" ".claude/agents/"
      UPDATED=$((UPDATED + 1))
    fi
  fi
done

# Report any project-specific agents that were preserved
echo "Framework agents refreshed: $UPDATED"
[ -n "$PROJECT_OWNED_SKIPPED" ] && echo "Project-owned agents preserved (owner: project):$PROJECT_OWNED_SKIPPED"
PRESERVED=$(ls .claude/agents/*.md 2>/dev/null | while read f; do
  name=$(basename "$f" .md)
  is_framework=0
  for a in $ROSTER; do [ "$a" = "$name" ] && is_framework=1 && break; done
  [ $is_framework -eq 0 ] && echo "$name"
done | tr '\n' ' ')
[ -n "$PRESERVED" ] && echo "Project-specific agents preserved: $PRESERVED"

echo "Agents updated (roster-aware)"
```

---

## Step 9: Update Orchestrator Files (if present)

**Only update if orchestrator directory exists** (project has used `/orchestrate` before):

```bash
if [ -d ".claude/orchestrator" ]; then
  echo "=== Updating Orchestrator Files ==="

  # Copy Python scripts (preserve symlinks or update files)
  cp ~/.claude/copilot/templates/orchestration/task_copilot_client.py .claude/orchestrator/
  cp ~/.claude/copilot/templates/orchestration/check_streams_data.py .claude/orchestrator/
  cp ~/.claude/copilot/templates/orchestration/orchestrate.py .claude/orchestrator/
  cp ~/.claude/copilot/templates/orchestration/monitor-workers.py .claude/orchestrator/

  # Copy shell scripts
  cp ~/.claude/copilot/templates/orchestration/check-streams .claude/orchestrator/
  cp ~/.claude/copilot/templates/orchestration/watch-status .claude/orchestrator/

  # Ensure scripts are executable
  chmod +x .claude/orchestrator/check-streams
  chmod +x .claude/orchestrator/watch-status
  chmod +x .claude/orchestrator/orchestrate.py

  echo "Orchestrator files updated"
  ORCHESTRATOR_UPDATED=true
else
  echo "No orchestrator directory found (skipping)"
  ORCHESTRATOR_UPDATED=false
fi
```

---

## Step 10: Update cc CLI and Project Config

### 10A: Check cc Is Installed

```bash
which cc >/dev/null 2>&1 && echo "CC_OK" || echo "CC_MISSING"
```

**If CC_MISSING:**

Tell user: "Installing cc CLI..."

```bash
bash ~/.claude/copilot/tools/cc/install.sh
```

After install, verify:

```bash
which cc >/dev/null 2>&1 && echo "CC_INSTALLED" || echo "CC_INSTALL_FAILED"
```

If CC_INSTALL_FAILED, tell user:

---

**cc install failed.**

Try installing manually:
```bash
bash ~/.claude/copilot/tools/cc/install.sh
```

---

Then continue (do not stop — remaining steps may still work).

### 10B: Check cc Project Config

```bash
ls .claude/cc/config.json 2>/dev/null && echo "CC_CONFIG_OK" || echo "CC_CONFIG_MISSING"
```

**If CC_CONFIG_MISSING:**

Tell user: "Initializing cc project config..."

```bash
cc config init --project
```

### 10C: Ensure Memory Directory and .gitignore

```bash
# Ensure entries directory exists with a tracking file
if [ ! -d ".claude/memory/entries" ]; then
  mkdir -p .claude/memory/entries
  touch .claude/memory/entries/.gitkeep
  echo "Created .claude/memory/entries/"
fi

# Ensure .claude/memory/.gitignore exists with correct entries
if [ ! -f ".claude/memory/.gitignore" ]; then
  printf 'memory.db\nmemory.db-*\n' > .claude/memory/.gitignore
  echo "Created .claude/memory/.gitignore"
fi
```

### 10D: Run cc config doctor

```bash
cc config doctor 2>&1
```

If `cc config doctor` reports any issues (non-zero exit or lines containing "WARN" or "ERROR"), print the output and tell user:

---

**cc config doctor reported issues. Please review and resolve the items above before continuing.**

---

---

## Step 11: Verify Update

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

echo ""
echo "=== Component Versions ==="
if [ -f ~/.claude/copilot/VERSION.json ]; then
  node -p "
    const v = require('$HOME/.claude/copilot/VERSION.json');
    console.log('Framework: v' + v.framework);
    console.log('Agents: v' + v.components.agents.version);
    console.log('Commands: v' + v.components.commands.version);
    console.log('Skills: v' + v.components.skills.version);
    console.log('cc: v' + v.components.cc.version);
    console.log('tc: v' + v.components.tc.version);
  "
fi
```

---

## Step 11B: Run Fitness Check

After updating agents, run the fitness check to verify the roster is healthy:

```bash
if [ -f .claude/fitness-check.sh ]; then
  bash .claude/fitness-check.sh \
    --agents-dir .claude/agents \
    --commands-dir .claude/commands \
    --copilot-path ~/.claude/copilot
  FITNESS_RESULT=$?
else
  # fitness-check.sh not yet copied — copy it first
  cp ~/.claude/copilot/.claude/fitness-check.sh .claude/fitness-check.sh
  chmod +x .claude/fitness-check.sh
  bash .claude/fitness-check.sh \
    --agents-dir .claude/agents \
    --commands-dir .claude/commands \
    --copilot-path ~/.claude/copilot
  FITNESS_RESULT=$?
fi
```

If `FITNESS_RESULT` is non-zero (check failed), print the failures and tell the user:

---

**Fitness check reported issues.** Review the failures above. Common fixes:
- Missing agent: `cp ~/.claude/copilot/.claude/agents/<name>.md .claude/agents/`
- Orphan route: Edit the agent file's Route To table to point to a valid agent
- Retired agent still present: `rm .claude/agents/design.md` (or other retired agent)

The project is updated but the fitness check should be resolved before using protocol chains.

---

Store `FITNESS_RESULT` to include in Step 12 report.

---

## Step 12: Report Success

```bash
# Get Claude Copilot version
if [ -f ~/.claude/copilot/package.json ]; then
  COPILOT_VERSION=$(node -p "require('$HOME/.claude/copilot/package.json').version" 2>/dev/null || echo "unknown")
else
  COPILOT_VERSION="unknown"
fi

# Read version summary if available
if [ -f ~/.claude/copilot/CHANGELOG-SUMMARY.json ] && [ "$COPILOT_VERSION" != "unknown" ]; then
  # Extract summary for the version using node
  SUMMARY=$(node -p "
    try {
      const data = require('$HOME/.claude/copilot/CHANGELOG-SUMMARY.json');
      const version = data.versions['$COPILOT_VERSION'];
      if (version) {
        version.summary || 'See CHANGELOG.md for details';
      } else {
        'Version details not found in summary';
      }
    } catch (e) {
      'See CHANGELOG.md for details';
    }
  " 2>/dev/null || echo "See CHANGELOG.md for details")
else
  # Fallback to git log
  SUMMARY=$(cd ~/.claude/copilot && git log --oneline -1 2>/dev/null || echo "Latest version")
fi
```

Tell user:

---

**Project Updated!**

**Refreshed:**
- `.claude/commands/` (7 project commands: protocol, continue, pause, map, memory, extensions, orchestrate)
- `.claude/agents/` (16 framework agents, roster-aware sync)
{{IF_ORCHESTRATOR_UPDATED}}
- `.claude/orchestrator/` (Python scripts and shell utilities)
{{END_IF}}

**MCP Configuration:**
{{IF_SERVERS_ADDED}}
- `.mcp.json` updated: Added {{SERVER_NAMES}}
{{ELSE}}
- `.mcp.json` unchanged (all servers already configured)
{{END_IF}}

**cc CLI:**
- cc installed and project config verified
- Memory directory and `.gitignore` ensured
- `cc config doctor` passed (or issues printed above)

**Unchanged:**
- `CLAUDE.md`
- `.claude/skills/`
- Existing MCP server configurations
{{IF_NO_ORCHESTRATOR}}
- `.claude/orchestrator/` not present (run `/orchestrate setup` to initialize)
{{END_IF}}

**Claude Copilot Version:** $COPILOT_VERSION

**What's New:**
$SUMMARY

**Full details:** `~/.claude/copilot/CHANGELOG.md`

Your project now has the latest Claude Copilot commands and agents.

**Next step:** Run `cc memory index --rebuild` to refresh your local search index with any new memory entries.

---

## Troubleshooting

### Permissions Error

```bash
chmod -R 755 .claude
```

### Commands Still Not Working

Restart Claude Code to reload the files.

### Want to Reset Everything

If you need a complete reset (including .mcp.json and CLAUDE.md):
1. Remove the existing setup: `rm -rf .claude .mcp.json CLAUDE.md`
2. Run `/setup-project` for fresh initialization
