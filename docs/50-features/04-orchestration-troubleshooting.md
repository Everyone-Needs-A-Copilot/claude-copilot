# Orchestration Troubleshooting Guide

This guide helps diagnose and fix common orchestration issues quickly. Based on real incidents and production debugging sessions.

---

## Quick Diagnostics

Run these one-liners to check common issues:

```bash
# 1. Check Claude CLI is in PATH
which claude || echo "❌ NOT FOUND"

# 2. Check git worktrees
git worktree list

# 3. Check MCP servers configured
cat .mcp.json | grep -A 5 task-copilot

# 4. Check orchestrator files exist
ls -la .claude/orchestrator/

# 5. Check worker logs
tail -f .claude/orchestrator/logs/Stream-*.log

# 6. Check PID files
ls -la .claude/orchestrator/pids/

# 7. Check stream status
python .claude/orchestrator/check_streams_data.py

# 8. Check for zombie processes
ps aux | grep claude | grep -v grep
```

---

## Pre-Orchestration Checklist

**Run BEFORE starting orchestration to prevent issues:**

### Required Environment

- [ ] **Claude CLI in PATH**
  ```bash
  which claude
  # Must return: /opt/homebrew/bin/claude (or similar)
  ```

- [ ] **Git version >= 2.5** (for worktree support)
  ```bash
  git --version
  # Must be: 2.5.0 or higher
  ```

- [ ] **MCP servers configured**
  ```bash
  cat .mcp.json | grep -E "(task-copilot|copilot-memory)"
  # Both servers must be present
  ```

- [ ] **MCP servers built**
  ```bash
  cd ~/.claude/copilot/mcp-servers/task-copilot
  npm run build

  cd ~/.claude/copilot/mcp-servers/copilot-memory
  npm run build
  ```

- [ ] **Claude Copilot framework updated**
  ```bash
  cd ~/.claude/copilot
  git pull
  ```

- [ ] **Project updated to latest templates**
  ```bash
  # In your project
  /update-project
  ```

### Git State

- [ ] **Working directory clean** (or changes stashed)
  ```bash
  git status
  # Should show: "nothing to commit, working tree clean"
  ```

- [ ] **On a feature branch** (not main)
  ```bash
  git branch --show-current
  # Should NOT be: main or master
  ```

### Validation Script

**Recommended:** Run the validation script before orchestration:

```bash
# Create validation script
cat > validate-setup.py << 'EOF'
#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

def check(name, command, expected=None):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if expected and expected not in result.stdout:
            print(f"❌ {name}: Failed")
            return False
        print(f"✅ {name}")
        return True
    except Exception as e:
        print(f"❌ {name}: {e}")
        return False

checks = [
    ("Claude CLI", "which claude", "/claude"),
    ("Git version", "git --version", "git version"),
    ("Task Copilot MCP", "cat .mcp.json | grep task-copilot", "task-copilot"),
    ("Memory Copilot MCP", "cat .mcp.json | grep copilot-memory", "copilot-memory"),
    ("Orchestrator directory", "ls .claude/orchestrator", "orchestrate.py"),
]

print("Running pre-orchestration checks...\n")
results = [check(name, cmd, exp) for name, cmd, exp in checks]

if all(results):
    print("\n✅ All checks passed. Ready for orchestration.")
    sys.exit(0)
else:
    print("\n❌ Some checks failed. Fix issues before orchestrating.")
    sys.exit(1)
EOF

chmod +x validate-setup.py
python validate-setup.py
```

---

## Common Issues

### Issue 1: Workers Start But Produce No Output

#### Symptoms
- `./watch-status` shows workers running
- Log files exist but contain minimal content:
  ```
  Starting claude...
  ```
  ...and nothing else

#### Root Cause
Claude CLI not found in worker's PATH. Non-login shells (spawned by `#!/bin/bash`) don't include `/opt/homebrew/bin` on macOS by default.

#### Diagnosis
Check worker log for Claude path:
```bash
tail .claude/orchestrator/logs/Stream-A_*.log
```

Look for:
```
Claude path: NOT FOUND
```

Or absence of "Claude path:" line entirely (indicates old worker-wrapper.sh).

#### Solution

**1. Update worker-wrapper.sh template:**
```bash
# Check if PATH export exists
head -20 ~/.claude/copilot/templates/orchestration/worker-wrapper.sh | grep PATH

# If missing, update Claude Copilot
cd ~/.claude/copilot
git pull

# Verify fix is present (should see line 14-15):
# export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
```

**2. Update project symlinks:**
```bash
# In your project
/update-project
```

**3. Restart workers:**
```bash
# Kill existing workers
pkill -f "worker-wrapper.sh"

# Restart orchestration
/orchestrate start
```

#### Prevention
- Always run `/update-project` after updating Claude Copilot
- Check `validate-setup.py` script before orchestrating
- Verify worker-wrapper.sh has PATH export

---

### Issue 2: Worktrees Created But Empty

#### Symptoms
- Worktree directories exist in `.claude/worktrees/`
- Directory has only 6-10 files instead of full project (68+ items)
- Workers fail with "file not found" errors
- `git worktree list` doesn't show worktrees

#### Root Cause
`orchestrate.py` uses `mkdir` instead of `git worktree add`, creating empty directories instead of git worktrees.

#### Diagnosis
```bash
# Check worktree count
git worktree list
# Should show: main branch + all Stream-* worktrees

# Check directory contents
ls -la .claude/worktrees/Stream-A/ | wc -l
# Should be: 68+ items (same as project root)
```

#### Solution

**Option 1: Manual worktree creation (immediate fix):**
```bash
# From project root
for stream in Stream-A Stream-B Stream-C Stream-D Stream-E; do
    # Create branch if doesn't exist
    git branch "$stream" 2>/dev/null || true

    # Create git worktree
    git worktree add ".claude/worktrees/$stream" "$stream"
done

# Verify
git worktree list
```

**Option 2: Fix orchestrate.py (permanent fix):**

Edit `~/.claude/copilot/templates/orchestration/orchestrate.py` at lines 620-623:

**Before (broken):**
```python
if not work_dir.exists():
    log(f"Creating worktree for {stream_id}...")
    work_dir.mkdir(parents=True, exist_ok=True)  # ❌ Creates empty directory
```

**After (fixed):**
```python
if not work_dir.exists():
    log(f"Creating git worktree for {stream_id}...")
    branch_name = stream_id

    # Create branch if doesn't exist
    subprocess.run(
        ["git", "branch", branch_name],
        cwd=PROJECT_ROOT,
        capture_output=True
    )

    # Create git worktree
    result = subprocess.run(
        ["git", "worktree", "add", str(work_dir), branch_name],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        error(f"Failed to create worktree: {result.stderr}")
        return False
```

#### Prevention
- Always verify worktrees with `git worktree list` before starting
- Run manual worktree creation as part of pre-flight checklist
- Monitor for "file not found" errors in worker logs

---

### Issue 3: "Command not found: claude"

#### Symptoms
- Workers fail immediately
- Logs show: `line 105: claude: command not found`
- Exit code: 127

#### Root Cause
Same as Issue 1 - PATH doesn't include Claude CLI location.

#### Diagnosis
```bash
# In interactive shell
which claude
# Returns: /opt/homebrew/bin/claude

# In non-login shell (like worker)
/bin/bash -c "which claude"
# Returns: (nothing) ← PROBLEM
```

#### Solution
Follow steps in **Issue 1: Workers Start But Produce No Output**.

#### Prevention
Add to your shell profile to ensure PATH is consistent:
```bash
# In ~/.zshrc or ~/.bashrc
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
```

---

### Issue 4: Permission Denied Errors

#### Symptoms
- Workers fail with: `Permission denied: .claude/orchestrator/orchestrate.py`
- Or: `Permission denied: worker-wrapper.sh`

#### Root Cause
Scripts not marked executable after template copy.

#### Diagnosis
```bash
ls -la .claude/orchestrator/ | grep -E "(orchestrate|worker-wrapper)"
# Should show: -rwxr-xr-x (executable)
# Not: -rw-r--r-- (not executable)
```

#### Solution
```bash
# Make scripts executable
chmod +x .claude/orchestrator/orchestrate.py
chmod +x .claude/orchestrator/worker-wrapper.sh
chmod +x .claude/orchestrator/check-streams
chmod +x .claude/orchestrator/monitor-workers.py
chmod +x .claude/orchestrator/start-ready-streams.py

# Make root-level symlinks executable
chmod +x watch-status
```

#### Prevention
`/update-project` command should handle this automatically. If not:
```bash
# One-time fix for all orchestrator scripts
find .claude/orchestrator -type f -name "*.py" -exec chmod +x {} \;
find .claude/orchestrator -type f -name "*.sh" -exec chmod +x {} \;
find .claude/orchestrator -type f -name "check-*" -exec chmod +x {} \;
find .claude/orchestrator -type f -name "watch-*" -exec chmod +x {} \;
```

---

### Issue 5: Task Copilot Connection Failed

#### Symptoms
- Workers start but fail immediately
- Logs show: `Error: Cannot connect to Task Copilot MCP server`
- Or: `ECONNREFUSED`

#### Root Cause
- Task Copilot MCP server not running
- Server not built after update
- Invalid `.mcp.json` configuration

#### Diagnosis
```bash
# 1. Check MCP configuration
cat .mcp.json | jq '.mcpServers["task-copilot"]'

# 2. Check if server is built
ls ~/.claude/copilot/mcp-servers/task-copilot/build/
# Should show: index.js and other files

# 3. Test server manually
cd ~/.claude/copilot/mcp-servers/task-copilot
npm run dev
# Should start without errors
```

#### Solution

**1. Rebuild MCP servers:**
```bash
cd ~/.claude/copilot/mcp-servers/task-copilot
npm install
npm run build

cd ~/.claude/copilot/mcp-servers/copilot-memory
npm install
npm run build
```

**2. Verify `.mcp.json` configuration:**
```json
{
  "mcpServers": {
    "task-copilot": {
      "command": "node",
      "args": [
        "/absolute/path/to/.claude/copilot/mcp-servers/task-copilot/build/index.js"
      ],
      "env": {
        "TASK_DB_PATH": "/absolute/path/to/.claude/tasks",
        "WORKSPACE_ID": "your-project"
      }
    },
    "copilot-memory": {
      "command": "node",
      "args": [
        "/absolute/path/to/.claude/copilot/mcp-servers/copilot-memory/build/index.js"
      ],
      "env": {
        "MEMORY_PATH": "/absolute/path/to/.claude/memory",
        "WORKSPACE_ID": "your-project"
      }
    }
  }
}
```

**3. Restart Claude:**
```bash
# Close and reopen Claude Code
# Or restart via command palette
```

#### Prevention
- Run `npm run build` after every `git pull` in Claude Copilot
- Use absolute paths in `.mcp.json` (avoid `~` tilde)
- Verify MCP servers in Claude status bar before orchestrating

---

### Issue 6: Streams Not Showing in watch-status

#### Symptoms
- `/orchestrate generate` succeeds
- `tc stream list --json` shows streams
- But `./watch-status` shows: "No streams found" or empty dashboard

#### Root Cause
- Initiative scoping mismatch
- Streams from different initiative (auto-archived)
- Task Copilot database corruption

#### Diagnosis
```bash
# 1. Check streams exist
tc stream list --json

# 2. Check database exists
ls -lh ~/.claude/tasks/$(basename $(pwd)).db

# 3. Check for archived streams
python .claude/orchestrator/check_streams_data.py | grep -i archived
```

#### Solution

**If streams from different initiative:**
```bash
# Re-link to current initiative via Memory Copilot
# Use initiative_link() MCP tool to reconnect

# Then verify streams are visible
tc stream list --json
```

**If database corrupted:**
```bash
# Backup database
cp ~/.claude/tasks/$(basename $(pwd)).db ~/.claude/tasks/$(basename $(pwd)).db.backup

# Delete and regenerate
rm ~/.claude/tasks/$(basename $(pwd)).db
/orchestrate generate  # Recreate PRD and tasks
```

#### Prevention
- Always use `/orchestrate generate` to start new initiatives
- Don't manually switch initiatives mid-orchestration
- Use `initiative_link()` (Memory Copilot MCP) to properly scope initiatives

---

### Issue 7: Symlink Path Resolution Errors

#### Symptoms
- `./watch-status` shows wrong project name
- Or: `check-streams` can't find files
- Or: Scripts work from `.claude/orchestrator/` but not from project root

#### Root Cause
Multiple levels of symlinks cause path resolution to point to template directory instead of project root.

#### Diagnosis
```bash
# Check symlink structure
ls -la watch-status
# Should show: watch-status -> .claude/orchestrator/watch-status

ls -la .claude/orchestrator/watch-status
# Should show: watch-status -> ~/.claude/copilot/templates/orchestration/watch-status

# Check what PROJECT_ROOT resolves to
bash -x ./watch-status 2>&1 | grep PROJECT_ROOT
# Should show your project path, NOT ~/.claude/copilot/templates
```

#### Solution

**Update to latest templates with symlink fix:**
```bash
# Update Claude Copilot
cd ~/.claude/copilot
git pull

# Update project
cd /your/project
/update-project
```

**Verify fix is present** in `~/.claude/copilot/templates/orchestration/watch-status` (lines 26-51):
```bash
# Should see logic like:
# Handle multiple symlink scenarios
if [ -L "$INVOCATION_PATH" ]; then
    FIRST_TARGET="$(readlink "$INVOCATION_PATH")"
    if [[ "$FIRST_TARGET" == *".claude/orchestrator"* ]]; then
        # Called from project root via symlink
        PROJECT_ROOT="$INVOCATION_DIR"
```

#### Prevention
- Always use `./watch-status` from project root (not `.claude/orchestrator/watch-status`)
- Update projects after framework updates
- Test scripts from both locations to verify symlink resolution

---

### Issue 8: Workers Never Start (Blocked Forever)

#### Symptoms
- `/orchestrate start` runs without error
- `./watch-status` shows all streams with status: `---` (not started)
- No workers spawn
- No progress for extended period

#### Root Cause
- All streams have dependencies that aren't satisfied
- Circular dependency in stream graph
- No foundation streams (streams with empty dependencies)

#### Diagnosis
```bash
# Check stream dependencies
python .claude/orchestrator/check_streams_data.py | grep -A 5 "Dependencies"

# Check for circular dependencies
tc stream list --json
# Review streamDependencies in each stream's metadata
```

**Look for:**
- Stream-A depends on Stream-B
- Stream-B depends on Stream-A
- No stream with `dependencies: []`

#### Solution

**If circular dependency:**
```bash
# Identify cycle and break it by making one stream foundation
# List tasks for the stream
tc task list --stream Stream-A --json

# Update each task to remove dependencies
tc task update <task-id> --status pending --json
# Set metadata.dependencies to [] for each task in the stream
```

**If no foundation streams:**
```bash
# Identify the true starting point and remove its dependencies
# Usually this is "database setup" or "configuration" stream
tc task list --stream Stream-A --json

# Update foundation tasks to have no dependencies
tc task update <task-id> --status pending --json
# Set metadata.dependencies to []

# Restart orchestration
/orchestrate start
```

#### Prevention
- During `/orchestrate generate`, verify at least one foundation stream
- Review dependency graph before starting:
  ```
  Depth 0 (Foundation):
    • Stream-A - 3 tasks  ← Must have at least one foundation
  ```
- Use dependency validation in @agent-ta planning phase

---

### Issue 9: Worker Keeps Restarting Infinitely

#### Symptoms
- `./watch-status` shows worker alternating between `RUN` and `---`
- Monitor log shows repeated restart attempts
- Eventually hits max restart limit

#### Root Cause
- Worker completes but doesn't mark tasks as complete
- Worker crashes consistently (environment issue)
- Task blocked on external dependency

#### Diagnosis
```bash
# Check monitor log for restart pattern
tail -50 .claude/orchestrator/logs/monitor.log
# Look for: "Restarting dead worker: Stream-A (attempt 1 of 2)"

# Check worker log for errors
tail -100 .claude/orchestrator/logs/Stream-A_*.log
# Look for: exceptions, exit codes, task verification failures

# Check task status
tc task list --stream Stream-A --json
```

#### Solution

**If worker completes but tasks show incomplete:**
```bash
# Worker isn't calling tc task update properly
# Check worker prompt includes mandatory protocol
tail .claude/orchestrator/logs/Stream-A_*.log | grep -A 10 "MANDATORY PROTOCOL"

# Manually complete tasks if worker finished work
tc task list --stream Stream-A --json
# For each in-progress task:
tc task update <task-id> --status completed --json
```

**If environment issue (missing package, permissions):**
```bash
# Check worker log for error
tail -100 .claude/orchestrator/logs/Stream-A_*.log | grep -i error

# Fix environment issue (example: missing package)
cd .claude/worktrees/Stream-A
npm install  # or pip install, etc.

# Restart worker manually
python .claude/orchestrator/orchestrate.py start Stream-A
```

**If hitting max restarts:**
```bash
# Increase restart limit temporarily
# Edit monitor-workers.py or watch-status
./watch-status  # Uses --max-restarts 2 by default

# Or run monitor manually with higher limit
python .claude/orchestrator/monitor-workers.py --auto-restart --max-restarts 5
```

#### Prevention
- Verify worker prompt includes task update protocol
- Test environment in worktree before orchestrating
- Monitor first few runs for consistent failures

---

### Issue 10: Zombie Processes Blocking Workers

#### Symptoms
- Worker shows as "already running" but no visible process
- `ps aux | grep Stream-A` shows `<defunct>` or zombie
- PID file exists but process doesn't respond

#### Root Cause
Worker terminated abnormally (killed, segfault, OOM) leaving zombie process.

#### Diagnosis
```bash
# Check for zombies
ps aux | grep claude | grep defunct

# Check PID file
cat .claude/orchestrator/pids/Stream-A.pid
# Note PID number

# Check if process exists
ps -p <PID>
# If shows "<defunct>" → zombie
```

#### Solution

**Automatic (should happen automatically):**
- Zombie detection runs on every `_is_running()` check
- Stale PID cleanup runs on orchestrator startup
- Monitor should detect and restart

**Manual cleanup if needed:**
```bash
# Kill zombie (parent needs to reap it)
pkill -9 -f worker-wrapper.sh

# Clean up PID files
rm .claude/orchestrator/pids/*.pid

# Restart orchestration
/orchestrate start
```

#### Prevention
- Ensure `worker-wrapper.sh` has EXIT trap (should be in template)
- Monitor system resources (prevent OOM kills)
- Use `./watch-status` with auto-restart enabled

---

## Diagnostic Commands

### Stream Status
```bash
# Comprehensive stream data
python .claude/orchestrator/check_streams_data.py

# Just stream list
tc stream list --json

# Stream with full details
tc stream get Stream-A --json
```

### Worker Status
```bash
# Check running workers
ps aux | grep worker-wrapper.sh | grep -v grep

# Check worker PIDs
ls -la .claude/orchestrator/pids/

# Check specific worker
if [ -f .claude/orchestrator/pids/Stream-A.pid ]; then
    pid=$(cat .claude/orchestrator/pids/Stream-A.pid)
    ps -p $pid
fi
```

### Log Analysis
```bash
# Latest log entries across all streams
tail -n 20 .claude/orchestrator/logs/Stream-*.log

# Follow all logs in real-time
tail -f .claude/orchestrator/logs/*.log

# Search for errors
grep -i error .claude/orchestrator/logs/*.log

# Search for Claude path issues
grep "Claude path:" .claude/orchestrator/logs/*.log

# Check exit codes
grep "exited with code" .claude/orchestrator/logs/*.log
```

### Git Worktree Status
```bash
# List all worktrees
git worktree list

# Check worktree file count
for dir in .claude/worktrees/Stream-*; do
    echo "$dir: $(find "$dir" -maxdepth 1 | wc -l) items"
done

# Compare worktree to main
diff -r .claude/worktrees/Stream-A/ . --exclude=.git --exclude=.claude | head -20
```

### Task Copilot Status
```bash
# Check database exists
ls -lh ~/.claude/tasks/$(basename $(pwd)).db

# Query task counts and progress
tc progress --json

# List all tasks
tc task list --json
```

---

## Recovery Procedures

### 1. Clean Up Failed Worktrees

**When:** Orchestration failed mid-setup, worktrees are in bad state.

```bash
# Remove all worktrees
git worktree list | grep -v "main" | awk '{print $1}' | xargs -I {} git worktree remove {} --force

# Prune stale references
git worktree prune

# Delete worktree directories
rm -rf .claude/worktrees/*

# Delete stream branches (optional - if you want fresh start)
git branch | grep "Stream-" | xargs -I {} git branch -D {}

# Recreate worktrees
for stream in Stream-A Stream-B Stream-C Stream-D Stream-E; do
    git branch "$stream" 2>/dev/null || true
    git worktree add ".claude/worktrees/$stream" "$stream"
done

# Verify
git worktree list
```

### 2. Reset Orchestration State

**When:** Orchestration is in inconsistent state, need to start fresh.

```bash
# Stop all workers
pkill -f worker-wrapper.sh

# Clean up PID files
rm -f .claude/orchestrator/pids/*.pid

# Archive old logs
mkdir -p .claude/orchestrator/logs/archive
mv .claude/orchestrator/logs/*.log .claude/orchestrator/logs/archive/ 2>/dev/null || true

# Clean up worktrees (see procedure above)

# Reset task statuses to pending
tc task list --json
# For each in_progress or completed task:
tc task update <task-id> --status pending --json

# Start fresh
/orchestrate start
```

### 3. Kill Orphaned Worker Processes

**When:** Workers running but not managed by orchestrator.

```bash
# Find worker processes
ps aux | grep -E "(worker-wrapper|claude.*Stream-)" | grep -v grep

# Kill all worker-related processes
pkill -f worker-wrapper.sh
pkill -f "claude.*Stream-"

# Wait for processes to die
sleep 2

# Force kill if still alive
pkill -9 -f worker-wrapper.sh
pkill -9 -f "claude.*Stream-"

# Clean up PID files
rm -f .claude/orchestrator/pids/*.pid

# Verify clean
ps aux | grep -E "(worker-wrapper|claude.*Stream-)" | grep -v grep
# Should return nothing
```

### 4. Restart from Scratch

**When:** Everything is broken, need complete reset.

```bash
#!/bin/bash
# save as: reset-orchestration.sh

set -e

echo "🧹 Cleaning up orchestration state..."

# 1. Stop all workers
echo "  Stopping workers..."
pkill -f worker-wrapper.sh 2>/dev/null || true
sleep 2
pkill -9 -f worker-wrapper.sh 2>/dev/null || true

# 2. Clean up PID files
echo "  Removing PID files..."
rm -f .claude/orchestrator/pids/*.pid

# 3. Archive logs
echo "  Archiving logs..."
mkdir -p .claude/orchestrator/logs/archive
mv .claude/orchestrator/logs/*.log .claude/orchestrator/logs/archive/ 2>/dev/null || true

# 4. Clean up worktrees
echo "  Removing worktrees..."
git worktree list | grep -v "main" | awk '{print $1}' | xargs -I {} git worktree remove {} --force 2>/dev/null || true
git worktree prune
rm -rf .claude/worktrees/*

# 5. Delete stream branches
echo "  Deleting stream branches..."
git branch | grep "Stream-" | xargs -I {} git branch -D {} 2>/dev/null || true

# 6. Archive initiative in Task Copilot
echo "  Archiving Task Copilot streams..."
# Archive handled by initiative_link in generate phase
tc stream list --json 2>/dev/null || true

echo "✅ Cleanup complete. Run '/orchestrate generate' to start fresh."
```

Run with:
```bash
chmod +x reset-orchestration.sh
./reset-orchestration.sh
```

### 5. Fix Corrupted Task Copilot Database

**When:** Task Copilot returning errors or inconsistent data.

```bash
# Backup database
cp ~/.claude/tasks/$(basename $(pwd)).db ~/.claude/tasks/$(basename $(pwd)).db.backup

# Option 1: Vacuum and reindex
python -c "
import sqlite3
from pathlib import Path

db_path = Path.home() / '.claude' / 'tasks' / '$(basename $(pwd)).db'
conn = sqlite3.connect(str(db_path))
conn.execute('VACUUM')
conn.execute('REINDEX')
conn.close()
print('Database vacuumed and reindexed')
"

# Option 2: Delete and regenerate (DESTRUCTIVE)
rm ~/.claude/tasks/$(basename $(pwd)).db
echo "Database deleted. Run '/orchestrate generate' to recreate."

# Verify
tc stream list --json
```

### 6. Recover from Max Restarts Exceeded

**When:** Worker hit max restart limit, needs manual intervention.

```bash
# 1. Identify the failing stream
grep "max restart limit" .claude/orchestrator/logs/monitor.log
# Example: Stream-A hit max restart limit

# 2. Investigate root cause
tail -100 .claude/orchestrator/logs/Stream-A_*.log

# 3. Fix the underlying issue (examples):
#    - Install missing dependency in worktree
#    - Fix environment variable
#    - Correct task definition

# 4. Reset restart counter
python -c "
# Restart counter is in-memory, so just restart orchestrator
print('Restart counter will reset on next orchestrate.py start')
"

# 5. Manually restart the worker
python .claude/orchestrator/orchestrate.py start Stream-A

# 6. Monitor for success
tail -f .claude/orchestrator/logs/Stream-A_*.log
```

---

## Prevention Best Practices

### 1. Always Validate Before Orchestrating

Create and run validation script before every orchestration:
```bash
python validate-setup.py
```

### 2. Use watch-status with Auto-Restart

```bash
# Default mode includes auto-restart
./watch-status

# Monitors workers and auto-restarts failures
```

### 3. Monitor Logs During First Run

For the first orchestration run in a project:
```bash
# Terminal 1: Status dashboard
./watch-status

# Terminal 2: Live logs
tail -f .claude/orchestrator/logs/*.log
```

Watch for:
- "Claude path: NOT FOUND" → PATH issue
- "File not found" → Worktree issue
- Repeated restarts → Task or environment issue

### 4. Update Framework and Projects Regularly

```bash
# Weekly or after major releases
cd ~/.claude/copilot
git pull

# Then update each project
cd /your/project
/update-project
```

### 5. Keep Worktrees in Sync

```bash
# Before orchestrating, verify worktrees
git worktree list
# Should show all expected streams

# Recreate if missing
for stream in Stream-A Stream-B Stream-C Stream-D Stream-E; do
    git worktree add ".claude/worktrees/$stream" "$stream" 2>/dev/null || true
done
```

### 6. Test MCP Servers Before Orchestrating

```bash
# Test Task Copilot
cd ~/.claude/copilot/mcp-servers/task-copilot
npm run dev
# Should start without errors, Ctrl-C to stop

# Test Memory Copilot
cd ~/.claude/copilot/mcp-servers/copilot-memory
npm run dev
# Should start without errors, Ctrl-C to stop
```

### 7. Use Initiative Scoping Properly

```bash
# Always start with /orchestrate generate
/orchestrate generate  # Creates initiative link, PRD, tasks

# Don't manually call tc task create outside of generate phase
# Don't switch initiatives mid-orchestration
```

---

## When to Escalate

Contact framework maintainers if:

1. **Issues persist after following all procedures**
   - Provide: full logs, database state, system info

2. **Database corruption is recurring**
   - Provide: backup database, steps to reproduce

3. **Worker-wrapper.sh changes don't fix PATH issues**
   - Provide: `echo $PATH` output from login and non-login shells

4. **Zombie process detection isn't working**
   - Provide: `ps aux` output, PID file contents, OS version

5. **Circular dependency detection fails**
   - Provide: stream dependency graph, task metadata

**Information to include:**
```bash
# System info
uname -a
git --version
which claude
echo $PATH

# Framework version
cd ~/.claude/copilot && git log -1 --oneline

# Project state
git worktree list
ls -la .claude/orchestrator/
cat .mcp.json

# Database state
python .claude/orchestrator/check_streams_data.py

# Recent logs
tail -100 .claude/orchestrator/logs/*.log
```

---

## See Also

- **Workflow Guide:** [02-orchestration-workflow.md](./02-orchestration-workflow.md)
- **Full Feature Guide:** [02-orchestration-workflow.md](./02-orchestration-workflow.md)
- **Task Copilot README:** [mcp-servers/task-copilot/README.md](../../mcp-servers/task-copilot/README.md)

---

*Updated: January 2026 - Based on production incidents and debugging sessions*
