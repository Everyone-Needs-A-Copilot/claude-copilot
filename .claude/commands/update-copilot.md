# Update Claude Copilot

Update Claude Copilot to the latest version. This pulls the latest code and rebuilds the MCP servers.

## Step 1: Check Current Version

```bash
cd ~/.claude/copilot

# Get current version from package.json if it exists
if [ -f package.json ]; then
  OLD_VERSION=$(node -p "require('./package.json').version" 2>/dev/null || echo "unknown")
else
  OLD_VERSION="unknown"
fi

echo "Current version: $OLD_VERSION"

# Also show git log for reference
git log --oneline -1
```

Store the OLD_VERSION for comparison.

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
cd ~/.claude/copilot

# Get new version from package.json
if [ -f package.json ]; then
  NEW_VERSION=$(node -p "require('./package.json').version" 2>/dev/null || echo "unknown")
else
  NEW_VERSION="unknown"
fi

echo "New version: $NEW_VERSION"

# Also show git log for reference
git log --oneline -1
```

Compare with OLD_VERSION. If same, tell user "Already up to date" and skip to Step 7.

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

## Step 6: Reinstall tc CLI

Tell user: "Reinstalling tc CLI (Task Copilot)..."

```bash
pip install -e ~/.claude/copilot/tools/tc
```

**Verify:**
```bash
tc version
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

## Step 9: Generate Summary (if new version)

If NEW_VERSION is different from OLD_VERSION:

```bash
cd ~/.claude/copilot

# Generate summary from CHANGELOG.md
npm run generate-summary 2>/dev/null || echo "Warning: Could not generate summary"
```

---

## Step 10: Run Version Check

Tell user: "Verifying all components..."

```bash
cd ~/.claude/copilot && ./scripts/check-versions.sh
```

This validates:
- All MCP servers are built and version-matched
- Agents have required sections
- Global paths are configured

**If errors:** Address them before continuing.

---

## Step 11: Report Success

```bash
cd ~/.claude/copilot

# Read version summary if available
if [ -f CHANGELOG-SUMMARY.json ] && [ "$NEW_VERSION" != "unknown" ]; then
  # Extract summary for the new version using node
  SUMMARY=$(node -p "
    try {
      const data = require('./CHANGELOG-SUMMARY.json');
      const version = data.versions['$NEW_VERSION'];
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
  SUMMARY=$(git log --oneline HEAD~3..HEAD 2>/dev/null | head -3 | sed 's/^[a-f0-9]* /- /' || echo "Recent updates applied")
fi
```

Tell user:

---

**Claude Copilot Updated!**

**Version:** $OLD_VERSION → $NEW_VERSION

**What's New:**
$SUMMARY

**What was updated:**
- MCP servers rebuilt (copilot-memory, skills-copilot)
- tc CLI reinstalled
- Global commands refreshed

**Next steps:**

To update your projects with the latest agents and commands:
```
cd your-project
/update-project
```

**Full details:** `~/.claude/copilot/CHANGELOG.md`

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
