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
- `.claude/commands/protocol.md` and `continue.md`
- `.claude/agents/*.md` (all 12 agents)

This will ONLY update if needed:
- `.mcp.json` (only to add new MCP servers, preserving all existing configuration)

This will NOT touch:
- `CLAUDE.md` (your project instructions)
- `.claude/skills/` (your project skills)
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

echo "Commands updated (8 project commands)"
```

---

## Step 8: Update Agents

Remove old agent files and copy fresh ones:

```bash
# Remove all old agents
rm -f .claude/agents/*.md 2>/dev/null

# Copy fresh from source
cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/

echo "Agents updated"
```

---

## Step 9: Verify Update

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

## Step 10: Report Success

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
- `.claude/commands/` (8 project commands: protocol, continue, pause, map, memory, extensions, orchestrate)
- `.claude/agents/` (12 agents)

**MCP Configuration:**
{{IF_SERVERS_ADDED}}
- `.mcp.json` updated: Added {{SERVER_NAMES}}
{{ELSE}}
- `.mcp.json` unchanged (all servers already configured)
{{END_IF}}

**Unchanged:**
- `CLAUDE.md`
- `.claude/skills/`
- Existing MCP server configurations

**Claude Copilot Version:** $COPILOT_VERSION

**What's New:**
$SUMMARY

**Full details:** `~/.claude/copilot/CHANGELOG.md`

Your project now has the latest Claude Copilot commands and agents.

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
