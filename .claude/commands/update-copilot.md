# Update Claude Copilot

Update Claude Copilot to the latest version. This pulls the latest code and rebuilds the MCP servers.

## Step 1: Check Current Version

```bash
cd ~/.claude/copilot && git log --oneline -1
git describe --tags --abbrev=0 2>/dev/null || echo "No tags"
```

Store the current version for comparison.

---

## Step 2: Pull Latest Updates

Tell user: "Pulling latest Claude Copilot updates..."

```bash
cd ~/.claude/copilot && git pull origin main
```

**If pull fails:**

Tell user:

---

**Pull failed**

There may be local changes or network issues. Try:

```bash
cd ~/.claude/copilot
git status
git stash  # if you have local changes
git pull origin main
git stash pop  # restore local changes
```

---

Then STOP.

---

## Step 3: Check New Version

```bash
cd ~/.claude/copilot && git log --oneline -1
git describe --tags --abbrev=0 2>/dev/null || echo "No tags"
```

Compare with previous version. If same, tell user "Already up to date" and skip to Step 7.

---

## Step 4: Rebuild Memory Server

Tell user: "Rebuilding Memory Server..."

```bash
cd ~/.claude/copilot/mcp-servers/copilot-memory && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js
```

---

## Step 5: Rebuild Skills Server

Tell user: "Rebuilding Skills Server..."

```bash
cd ~/.claude/copilot/mcp-servers/skills-copilot && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js
```

---

## Step 6: Rebuild Task Server

Tell user: "Rebuilding Task Server..."

```bash
cd ~/.claude/copilot/mcp-servers/task-copilot && npm install && npm run build
```

**Verify:**
```bash
ls ~/.claude/copilot/mcp-servers/task-copilot/dist/index.js
```

---

## Step 7: Create Tasks Directory (if needed)

```bash
mkdir -p ~/.claude/tasks
```

---

## Step 8: Update Global Commands

Tell user: "Updating global commands..."

```bash
# Update user-level commands
cp ~/.claude/copilot/.claude/commands/setup-project.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/update-project.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/update-copilot.md ~/.claude/commands/
cp ~/.claude/copilot/.claude/commands/knowledge-copilot.md ~/.claude/commands/
```

**Verify:**
```bash
ls -la ~/.claude/commands/
```

---

## Step 9: Show Changelog

```bash
cd ~/.claude/copilot && git log --oneline HEAD~5..HEAD 2>/dev/null || git log --oneline -5
```

---

## Step 10: Report Success

---

**Claude Copilot Updated!**

**Previous version:** `{{OLD_VERSION}}`
**Current version:** `{{NEW_VERSION}}`

**What was updated:**
- MCP servers rebuilt (copilot-memory, skills-copilot, task-copilot)
- Global commands refreshed

**Recent changes:**
{{CHANGELOG}}

**Next steps:**

To update your projects with the latest agents and commands:
```
cd your-project
/update-project
```

**Note:** Restart Claude Code to load the updated MCP servers.

---

---

## Troubleshooting

### Build Fails

**Native module errors:**
```bash
xcode-select --install  # macOS
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm rebuild better-sqlite3
npm run build
```

### Permission Errors

```bash
chmod -R 755 ~/.claude/copilot
```

### Want to Rollback

```bash
cd ~/.claude/copilot
git log --oneline -10  # find the commit to rollback to
git checkout <commit-hash>
```

Then run `/update-copilot` again to rebuild.
