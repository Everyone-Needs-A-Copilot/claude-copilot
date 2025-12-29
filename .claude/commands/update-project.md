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

## Step 3: Check for Broken Symlinks

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

## Step 4: Show Current State

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

## Step 5: Confirm Update

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

## Step 6: Update Commands

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

## Step 7: Update Agents

Remove old agent files and copy fresh ones:

```bash
# Remove all old agents
rm -f .claude/agents/*.md 2>/dev/null

# Copy fresh from source
cp ~/.claude/copilot/.claude/agents/*.md .claude/agents/

echo "Agents updated"
```

---

## Step 8: Verify Update

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

## Step 9: Report Success

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
