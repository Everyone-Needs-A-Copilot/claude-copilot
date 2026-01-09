# Claude Copilot v2.0.0 Upgrade Guide

## Overview

This guide walks you through upgrading to Claude Copilot v2.0.0, which introduces parallel stream orchestration, WebSocket event streaming, and a paradigm shift to multi-session agent coordination.

**Estimated Time:** 15-20 minutes
**Difficulty:** Easy (backwards compatible)
**Breaking Changes:** None

---

## Table of Contents

1. [Pre-Upgrade Checklist](#pre-upgrade-checklist)
2. [Standard Upgrade (Recommended)](#standard-upgrade-recommended)
3. [Manual Upgrade](#manual-upgrade)
4. [Post-Upgrade Verification](#post-upgrade-verification)
5. [New Features Configuration](#new-features-configuration)
6. [Troubleshooting](#troubleshooting)
7. [Rollback Instructions](#rollback-instructions)

---

## Pre-Upgrade Checklist

Before upgrading, verify your current setup:

### 1. Check Current Version

```bash
cd ~/.claude/copilot
git log --oneline -1
```

**Expected output:**
- If on v1.7.0 or v1.7.1: Ready to upgrade
- If on v1.6.x or earlier: Review [CHANGELOG.md](CHANGELOG.md) for intermediate changes

### 2. Commit Uncommitted Work

```bash
# In all project directories
git status
git add .
git commit -m "WIP: Pre-upgrade checkpoint"
```

### 3. Backup Current Configuration

```bash
# Backup MCP configuration
cp ~/.mcp/config.json ~/.mcp/config.json.backup

# Or backup project-level config
cp ~/your-project/.mcp.json ~/your-project/.mcp.json.backup
```

### 4. Check Node Version

```bash
node --version
```

**Required:** Node.js 18.0.0 or higher

### 5. Check Disk Space

```bash
df -h ~/.claude
```

**Required:** At least 500 MB free space

### 6. List Active Initiatives

```bash
# In Claude Code
claude
# Then query memory
initiative_get({ mode: "lean" })
```

Note any active initiatives - you'll resume these after upgrade.

---

## Standard Upgrade (Recommended)

The standard upgrade uses the built-in `/update-copilot` and `/update-project` commands.

### Step 1: Update Framework

```bash
# Navigate to Claude Copilot installation
cd ~/.claude/copilot

# Start Claude Code
claude
```

In Claude Code:
```
/update-copilot
```

**What this does:**
- Pulls latest changes from `origin/main`
- Rebuilds all MCP servers
- Updates global `.claude/` directory
- Preserves your custom extensions

**Expected output:**
```
Updating Claude Copilot Framework

Current version: v1.7.1
Latest version: v1.8.0

Changes:
- Parallel stream orchestration
- WebSocket bridge
- Context recovery system
- v1.8 harness features

Pulling changes...
✓ Git pull complete

Rebuilding MCP servers...
✓ copilot-memory rebuilt
✓ task-copilot rebuilt
✓ skills-copilot rebuilt
✓ websocket-bridge installed

Framework updated successfully!

Next: Update your projects with /update-project
```

### Step 2: Update Projects

For **each project** using Claude Copilot:

```bash
cd ~/your-project
claude
```

In Claude Code:
```
/update-project
```

**What this does:**
- Syncs `.claude/` directory with latest framework
- Updates agents with new features
- Adds new commands (`/orchestrate`)
- Preserves project-specific customizations
- Updates `.gitignore` with orchestration directories

**Expected output:**
```
Updating Project with Claude Copilot v1.8.0

Files updated:
✓ .claude/agents/ (12 agents)
✓ .claude/commands/ (added orchestrate.md)
✓ .gitignore (added .claude/orchestrator/)

New features available:
- /orchestrate command
- Parallel stream execution
- Context recovery system

Update complete!
```

### Step 3: Restart Claude Code

Close and reopen Claude Code to reload MCP server configurations.

```bash
# Close Claude Code
# Reopen in your project
cd ~/your-project
claude
```

---

## Manual Upgrade

If `/update-copilot` is unavailable, follow these manual steps.

### Step 1: Pull Latest Code

```bash
cd ~/.claude/copilot
git pull origin main
```

**Expected output:**
```
remote: Enumerating objects: 847, done.
remote: Counting objects: 100% (847/847), done.
remote: Compressing objects: 100% (523/523), done.
remote: Total 847 (delta 324), reused 847 (delta 324)
Receiving objects: 100% (847/847), 1.23 MiB | 2.45 MiB/s, done.
Resolving deltas: 100% (324/324), done.
```

### Step 2: Rebuild MCP Servers

```bash
# Memory Copilot
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm install
npm run build

# Task Copilot
cd ../task-copilot
npm install
npm run build

# Skills Copilot
cd ../skills-copilot
npm install
npm run build

# WebSocket Bridge (NEW)
cd ../websocket-bridge
npm install
npm run build
```

### Step 3: Update Project Files

For each project:

```bash
cd ~/your-project

# Copy new command
cp ~/.claude/copilot/.claude/commands/orchestrate.md .claude/commands/

# Update agents (all 12 files)
cp -r ~/.claude/copilot/.claude/agents/ .claude/

# Update .gitignore
echo "" >> .gitignore
echo "# Claude Copilot orchestration" >> .gitignore
echo ".claude/orchestrator/" >> .gitignore
```

### Step 4: Verify Installation

```bash
# Check MCP servers built successfully
ls -la ~/.claude/copilot/mcp-servers/*/dist/

# Should see dist/ directories for:
# - copilot-memory
# - task-copilot
# - skills-copilot
# - websocket-bridge
```

---

## Post-Upgrade Verification

Verify the upgrade completed successfully.

### 1. Check Framework Version

```bash
cd ~/.claude/copilot
git log --oneline -1
```

**Expected:** Commit from January 8, 2026 or later

### 2. Verify MCP Servers

In Claude Code:
```bash
claude
# Check available tools
```

**New tools should be available:**
- `stream_list`, `stream_get`, `stream_conflict_check`
- `stream_unarchive`, `stream_archive_all`
- `preflight_check`
- `scope_change_request`, `scope_change_list`, `scope_change_review`
- `validation_config_get`, `validation_rules_list`
- `worktree_conflict_status`, `worktree_conflict_resolve`

### 3. Test New Commands

```bash
claude
```

In Claude Code:
```
/orchestrate
```

**Expected output:**
```
## No Active Initiative

Cannot generate orchestration without an active initiative.

To create an initiative:
1. Run /protocol
2. Work with @agent-ta to create a PRD with tasks
3. Ensure tasks are organized into streams
```

This confirms the `/orchestrate` command is installed.

### 4. Verify Quality Gates

Create a test quality gates config:

```bash
cat > .claude/quality-gates.json << 'EOF'
{
  "version": "1.0",
  "defaultGates": ["tests_pass"],
  "gates": {
    "tests_pass": {
      "name": "tests_pass",
      "description": "Tests must pass",
      "command": "echo 'Tests passed'",
      "expectedExitCode": 0
    }
  }
}
EOF
```

Quality gates should now run automatically on task completion.

### 5. Test HTTP API (Optional)

If you want to use orchestration or WebSocket bridge, test HTTP API:

**Add to `.mcp.json`:**
```json
{
  "mcpServers": {
    "task-copilot": {
      "command": "node",
      "args": [
        "/Users/your-username/.claude/copilot/mcp-servers/task-copilot/dist/index.js"
      ],
      "env": {
        "HTTP_API_PORT": "9090"
      }
    }
  }
}
```

**Restart Claude Code, then test:**
```bash
curl http://127.0.0.1:9090/health
```

**Expected output:**
```json
{"status":"ok","timestamp":"2026-01-08T12:34:56.789Z"}
```

---

## New Features Configuration

Configure new features introduced in v1.8.0.

### 1. Enable Orchestration

**Prerequisites:**
- tmux installed: `brew install tmux` (macOS) or `apt install tmux` (Linux)
- Python 3.8+: `python3 --version`
- requests library: `pip3 install requests`
- HTTP API enabled (see verification step above)

**Usage:**
```bash
claude
/protocol
# Create a PRD with multiple streams via @agent-ta

/orchestrate generate
# Generates scripts in .claude/orchestrator/

# Outside Claude Code:
python3 .claude/orchestrator/start-streams.py
```

### 2. Enable WebSocket Bridge (Optional)

**For real-time event streaming to UIs or dashboards:**

```bash
cd ~/.claude/copilot/mcp-servers/websocket-bridge

# Create .env file
cat > .env << EOF
JWT_SECRET=your-random-secret-key-here
WORKSPACE_ID=your-workspace-id
WS_PORT=8765
POLL_INTERVAL=100
EOF

# Start bridge
npm start
```

**Test connection:**
```javascript
const jwt = require('jsonwebtoken');
const WebSocket = require('ws');

const token = jwt.sign(
  { initiativeId: 'INIT-xxx' },
  'your-random-secret-key-here',
  { expiresIn: '24h' }
);

const ws = new WebSocket(`ws://localhost:8765?token=${token}`);
ws.on('message', (data) => {
  console.log('Event:', JSON.parse(data));
});
```

### 3. Configure Quality Gates

Create `.claude/quality-gates.json` in your project:

**Minimal (tests only):**
```json
{
  "version": "1.0",
  "defaultGates": ["tests_pass"],
  "gates": {
    "tests_pass": {
      "name": "tests_pass",
      "description": "Tests must pass",
      "command": "npm test",
      "expectedExitCode": 0
    }
  }
}
```

**Comprehensive (tests, lint, build):**
```json
{
  "version": "1.0",
  "defaultGates": ["tests_pass", "lint_clean", "build_success"],
  "gates": {
    "tests_pass": {
      "name": "tests_pass",
      "description": "All tests pass",
      "command": "npm test",
      "expectedExitCode": 0,
      "timeout": 300000
    },
    "lint_clean": {
      "name": "lint_clean",
      "description": "No linting errors",
      "command": "npm run lint",
      "expectedExitCode": 0
    },
    "build_success": {
      "name": "build_success",
      "description": "Build succeeds",
      "command": "npm run build",
      "expectedExitCode": 0,
      "timeout": 120000
    }
  }
}
```

### 4. Clean Up Legacy Streams (v1.7.1 Migration)

If upgrading from pre-v1.7.1, clean up legacy streams:

```bash
claude
```

In Claude Code:
```typescript
stream_archive_all({ confirm: true })
```

**What this does:**
- Archives all streams from previous initiatives
- Prevents stream pollution when using `/continue`
- One-time operation only needed after upgrade

### 5. Configure Context Recovery (Optional)

For orchestration with auto-recovery, edit generated config:

**.claude/orchestrator/orchestrate-config.json:**
```json
{
  "version": "1.0",
  "generatedAt": "...",
  "initiative": { ... },
  "apiEndpoint": "http://127.0.0.1:9090",
  "streams": [ ... ],
  "executionPlan": { ... },
  "contextRecovery": {
    "stallTimeoutMinutes": 10,
    "autoRecoveryEnabled": true,
    "maxRecoveryAttempts": 3
  }
}
```

---

## Troubleshooting

### Issue: `/update-copilot` command not found

**Cause:** Old version of framework
**Solution:** Use [Manual Upgrade](#manual-upgrade) instead

---

### Issue: MCP servers fail to build

**Symptom:**
```
npm ERR! Build failed
```

**Solution:**
```bash
# Clear node_modules and rebuild
cd ~/.claude/copilot/mcp-servers/task-copilot
rm -rf node_modules package-lock.json
npm install
npm run build

# Repeat for other servers
```

---

### Issue: `/orchestrate` command not available

**Cause:** Project files not updated
**Solution:**
```bash
cd ~/your-project
cp ~/.claude/copilot/.claude/commands/orchestrate.md .claude/commands/
```

Restart Claude Code.

---

### Issue: Quality gates not running

**Cause:** Invalid configuration or missing file
**Solution:**
```bash
# Validate JSON syntax
cat .claude/quality-gates.json | jq

# If error, fix JSON syntax
# Ensure gates match task metadata
```

---

### Issue: HTTP API not available

**Symptom:**
```bash
curl http://127.0.0.1:9090/health
curl: (7) Failed to connect
```

**Solution:**
```bash
# 1. Check .mcp.json has HTTP_API_PORT
cat .mcp.json | grep HTTP_API_PORT

# 2. Restart Claude Code to reload config

# 3. Check port not in use
lsof -i :9090

# 4. Try different port
# Edit .mcp.json: "HTTP_API_PORT": "9091"
```

---

### Issue: WebSocket bridge fails to start

**Symptom:**
```
Error: WORKSPACE_ID required
```

**Solution:**
```bash
# Get workspace ID
ls ~/.claude/tasks/
# Use directory name as WORKSPACE_ID

# Set in .env
echo "WORKSPACE_ID=<directory-name>" >> .env
```

---

### Issue: Orchestration script fails

**Symptom:**
```
ModuleNotFoundError: No module named 'requests'
```

**Solution:**
```bash
pip3 install requests

# Verify
python3 -c "import requests; print('OK')"
```

---

### Issue: tmux not found

**Symptom:**
```
tmux: command not found
```

**Solution:**
```bash
# macOS
brew install tmux

# Ubuntu/Debian
sudo apt install tmux

# Fedora/CentOS
sudo dnf install tmux
```

---

### Issue: Tests fail after upgrade

**Symptom:** Existing tests fail that previously passed

**Solution:**
```bash
# Clear test cache
npm run test -- --clearCache

# Rebuild
npm run build

# Run tests
npm test
```

If tests still fail, review changes in [CHANGELOG.md](CHANGELOG.md) for breaking changes (there should be none, but verify).

---

### Issue: Agent performance seems slower

**Cause:** New validation overhead
**Solution:**
- First upgrade is slower due to database migrations
- Subsequent runs are normal speed
- Disable quality gates temporarily if needed: `metadata: { qualityGates: [] }`

---

## Rollback Instructions

If you encounter critical issues, rollback to previous version.

### Step 1: Identify Previous Version

```bash
cd ~/.claude/copilot
git log --oneline -10
```

Find the commit for v1.7.1 or your previous version.

### Step 2: Rollback Framework

```bash
cd ~/.claude/copilot

# Rollback to specific commit
git reset --hard <commit-hash>

# Or rollback to specific tag
git checkout v1.7.1
```

### Step 3: Rebuild MCP Servers

```bash
cd mcp-servers/copilot-memory && npm install && npm run build
cd ../task-copilot && npm install && npm run build
cd ../skills-copilot && npm install && npm run build
```

### Step 4: Restore Project Files

```bash
cd ~/your-project

# Remove new files
rm .claude/commands/orchestrate.md
rm -rf .claude/orchestrator/

# Restore agents from backup
git checkout HEAD .claude/agents/
```

### Step 5: Restore Configuration

```bash
# Restore MCP config
cp ~/.mcp/config.json.backup ~/.mcp/config.json

# Or restore project config
cp ~/your-project/.mcp.json.backup ~/your-project/.mcp.json
```

### Step 6: Restart Claude Code

Close and reopen Claude Code.

### Step 7: Verify Rollback

```bash
cd ~/.claude/copilot
git log --oneline -1
```

Should show your previous version.

---

## Migration Notes

### Database Migrations

Task Copilot database automatically migrates to v6 schema on first run:

- **Added columns:** `archived`, `archived_at`, `archived_by_initiative_id` to tasks table
- **No data loss:** Existing tasks preserved
- **Automatic:** No manual intervention needed

### Memory Schema

Memory Copilot database remains compatible. New `agent_improvement` type is additive.

### Configuration Changes

**No breaking changes to:**
- `.mcp.json` format
- `CLAUDE.md` structure
- Agent frontmatter schema
- Tool signatures

**New optional configs:**
- `.claude/quality-gates.json` (optional)
- `.claude/orchestrator/` (generated on-demand)
- `contextRecovery` in orchestration config (optional)

---

## Getting Help

If you encounter issues not covered in this guide:

1. **Check Logs:**
   ```bash
   # MCP server logs
   tail -f ~/.claude/logs/task-copilot.log
   ```

2. **Search Issues:**
   - [GitHub Issues](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/issues)

3. **Ask Community:**
   - [GitHub Discussions](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/discussions)

4. **File Bug Report:**
   - Include version: `git log --oneline -1`
   - Include error messages
   - Include steps to reproduce

---

## Next Steps

After successful upgrade:

1. **Explore New Features:**
   - Try `/orchestrate` with a multi-stream PRD
   - Set up quality gates for your project
   - Test activation modes (`quick`, `thorough`, `analyze`)

2. **Read Documentation:**
   - [Orchestration Guide](../50-features/01-orchestration-guide.md)
   - [Enhancement Features](../50-features/00-enhancement-features.md)
   - [WebSocket Bridge](../../mcp-servers/websocket-bridge/README.md)

3. **Update Team:**
   - Share upgrade guide with team members
   - Configure shared quality gates
   - Set up orchestration for large initiatives

4. **Provide Feedback:**
   - Report bugs or issues
   - Suggest improvements
   - Share success stories

---

**Welcome to Claude Copilot v1.8.0!**

Enjoy parallel stream orchestration, real-time monitoring, and enhanced agent reliability.
