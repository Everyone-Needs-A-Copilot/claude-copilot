# Headless Parallel Orchestration Guide

## Overview

### What is Headless Orchestration?

Headless orchestration spawns multiple autonomous Claude Code workers that run in parallel across independent work streams. Unlike traditional orchestration that requires manual terminal management, headless orchestration:

- **Spawns workers automatically** using `claude --print --dangerously-skip-permissions`
- **Runs without user interaction** - workers are fully autonomous
- **Queries Task Copilot at runtime** - no static configuration files
- **Manages process lifecycle** - auto-restart on failure, PID tracking, log capture
- **Enforces phase dependencies** - foundation → parallel → integration

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ orchestrate.py                                               │
│ ├─ Query Task Copilot SQLite for streams                    │
│ ├─ Spawn headless workers (foundation first)                │
│ ├─ Track PIDs and logs                                      │
│ ├─ Monitor completion via SQLite                            │
│ └─ Auto-restart failed workers                              │
└─────────────────────────────────────────────────────────────┘
           │                │                │
           ▼                ▼                ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ Stream-A │     │ Stream-B │     │ Stream-C │
    │ (worker) │     │ (worker) │     │ (worker) │
    │ PID file │     │ PID file │     │ PID file │
    │ Log file │     │ Log file │     │ Log file │
    └──────────┘     └──────────┘     └──────────┘
           │                │                │
           └────────────────┴────────────────┘
                          │
                 ┌────────┴────────┐
                 │  Task Copilot   │
                 │  SQLite DB      │
                 │  (Shared State) │
                 └─────────────────┘
```

**Key difference from manual orchestration:** The orchestrator spawns and manages headless Claude Code processes directly. No tmux, no manual terminal management, no user intervention required.

---

## Prerequisites

### 1. Python 3.8+

The orchestrator is a Python script:

```bash
python3 --version  # Should be 3.8 or higher
```

### 2. Task Copilot Initialized

Tasks must be organized into streams with metadata:

- `streamId` - Unique identifier (e.g., "Stream-A")
- `streamName` - Human-readable name (e.g., "foundation")
- `streamPhase` - Execution phase: `"foundation"`, `"parallel"`, or `"integration"` (defaults to `"parallel"` if not specified)

Work with `@agent-ta` to create a PRD with organized streams.

### 3. Claude Code CLI

The `claude` command must be available in PATH:

```bash
which claude  # Should show path to Claude Code binary
```

---

## Quick Start

### Step 1: Create Streams

Start with `/protocol` and work with `@agent-ta`:

```
User: /protocol
User: Create a PRD with these streams:
      - Foundation: Core types (4 tasks)
      - Parallel A: API implementation (5 tasks)
      - Parallel B: UI components (4 tasks)
      - Integration: Tests and docs (3 tasks)
```

The Tech Architect will create a PRD with tasks organized into streams.

### Step 2: Start Orchestration

```
User: /orchestrate start
```

On first run, this automatically:
- Creates `.claude/orchestrator/` directory
- Copies orchestration templates (orchestrate.py, check-streams, watch-status, etc.)
- Creates `./watch-status` symlink at project root
- Makes scripts executable

Then it starts the orchestration:

```bash
cd /path/to/your/project
python .claude/orchestrator/orchestrate.py start
```

**The orchestrator will:**

1. Query Task Copilot for streams
2. Spawn foundation workers first
3. Wait for foundation to complete
4. Spawn parallel workers
5. Wait for parallel to complete
6. Spawn integration workers
7. Auto-restart any failed workers

### Step 3: Monitor Progress

In a separate terminal, run the live monitor:

```bash
./.claude/orchestrator/watch-status
```

**Output:**

```
╔═══════════════════════════════════════════════════════════════════════╗
║              YOUR-PROJECT - STREAM STATUS                             ║
╚═══════════════════════════════════════════════════════════════════════╝

📊 Overall Progress
───────────────────────────────────────────────────────────────────────
  [████████████████████████░░░░░░░░░░░░░░░░] 62%
  ✓ 32 completed  │  ⚡ 4 in progress  │  ◯ 15 pending  │  Total: 51

🖥  Stream Details
───────────────────────────────────────────────────────────────────────
  Workers: 3 running

  ✓ Stream-A
    [███████████████] 7/7 (100%)
    ✓7
    Status: Completed

  ◐ Stream-B
    [██████████░░░░░] 7/10 (70%)
    ✓7  ⚡1  ○2
    Status: Working (PID: 12345)

  ● Stream-C
    [████████░░░░░░░] 2/5 (40%)
    ✓2  ⚡1  ○2
    Status: Running (PID: 12346)

⌨  Quick Actions
───────────────────────────────────────────────────────────────────────
  python orchestrate.py status        Full worker status
  python orchestrate.py logs Stream-A Tail worker logs
  python orchestrate.py stop          Stop all workers

Data: Task Copilot │ 3 workers │ 16:42:11
```

---

## Commands

### orchestrate.py start

Start all streams, respecting phase dependencies:

```bash
# Start all streams
python orchestrate.py start

# Start specific stream
python orchestrate.py start Stream-B
```

**Behavior:**

- Foundation streams start first, run sequentially
- Parallel streams start after foundation completes, run concurrently
- Integration streams start after parallel completes
- Workers auto-restart on failure (max 10 attempts)
- Process runs in foreground, Ctrl+C to stop

### orchestrate.py status

Check status of all workers:

```bash
python orchestrate.py status
```

**Output:**

```
╔═══════════════════════════════════════════════════════════════════════╗
║              YOUR-PROJECT - WORKER STATUS                             ║
╚═══════════════════════════════════════════════════════════════════════╝

  FOUNDATION
    ✓ Stream-A │ foundation
      [███████████████] 7/7 │ Complete

  PARALLEL
    ● Stream-B │ api-implementation
      [██████████░░░░░] 7/10 │ Running (PID: 12345)

    ● Stream-C │ ui-components
      [████████░░░░░░░] 2/5 │ Running (PID: 12346)
```

### orchestrate.py stop

Stop all running workers:

```bash
# Stop all workers
python orchestrate.py stop

# Stop specific worker
python orchestrate.py stop Stream-B
```

### orchestrate.py logs

Tail logs for a stream:

```bash
python orchestrate.py logs Stream-B
```

Press Ctrl+C to stop tailing.

### check-streams

One-time status check (no refresh loop):

```bash
./.claude/orchestrator/check-streams
```

### watch-status

Live monitoring with auto-refresh:

```bash
# Default 15-second refresh
./.claude/orchestrator/watch-status

# Custom interval (5 seconds)
./.claude/orchestrator/watch-status 5
```

Press Ctrl+C to stop monitoring.

---

## How It Works

### Runtime Stream Query

Unlike static configuration, the orchestrator queries Task Copilot at runtime:

```python
# Query streams from SQLite
cursor.execute("""
    SELECT DISTINCT
        json_extract(metadata, '$.streamId') as stream_id,
        json_extract(metadata, '$.streamName') as stream_name,
        json_extract(metadata, '$.streamPhase') as stream_phase
    FROM tasks
    WHERE json_extract(metadata, '$.streamId') IS NOT NULL
      AND archived = 0
    ORDER BY stream_phase, stream_id
""")
```

**Benefits:**

- No `streams.json` to maintain
- Always reflects current Task Copilot state
- Stream changes automatically picked up
- Single source of truth (Task Copilot database)

### Headless Worker Spawning

The critical command that makes workers autonomous:

```python
proc = subprocess.Popen(
    ["claude", "--print", "--dangerously-skip-permissions", "-p", prompt],
    cwd=work_dir,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    start_new_session=True  # Detach from parent
)
```

**Flags:**

- `--print` - Output to stdout (captured to log file)
- `--dangerously-skip-permissions` - No interactive prompts
- `-p "prompt"` - Initial prompt for the worker
- `start_new_session=True` - Detach process (continues after parent exits)

### Process Lifecycle Management

**PID Tracking:**

```
.claude/orchestrator/pids/
├── Stream-A.pid
├── Stream-B.pid
└── Stream-C.pid
```

Each file contains the process ID. Used to check if worker is running:

```python
def _is_running(self, stream_id: str) -> bool:
    pid = int(pid_file.read_text().strip())
    os.kill(pid, 0)  # Signal 0 checks existence without killing
    return True
```

**Log Capture:**

```
.claude/orchestrator/logs/
├── Stream-A.log
├── Stream-B.log
└── Stream-C.log
```

All worker output (stdout/stderr) captured to log files.

**Auto-Restart:**

```python
# Check for dead workers
if not self._is_running(stream_id):
    if restart_counts[stream_id] < max_restarts:
        log(f"Restarting worker for {stream_id}")
        self.spawn_worker(stream_id, wait_for_deps=False)
        restart_counts[stream_id] += 1
```

Workers automatically restart up to 10 times on failure.

### Phase Management

**Foundation Phase:**

```python
# Start foundation streams first
for stream in foundation:
    self.spawn_worker(stream["id"], wait_for_deps=False)

# Wait for foundation to complete
self._wait_for_streams([s["id"] for s in foundation])
```

Foundation must complete 100% before parallel starts.

**Parallel Phase:**

```python
# Start all parallel streams at once
for stream in parallel:
    self.spawn_worker(stream["id"])

# Monitor all streams
self._wait_for_streams([s["id"] for s in parallel])
```

Parallel streams run concurrently.

**Integration Phase:**

```python
# Start after parallel complete
for stream in integration:
    self.spawn_worker(stream["id"])
```

Integration runs last, merges parallel work.

### Worker Prompt

Each worker receives a prompt with mandatory task update protocol:

```
You are a worker agent in the Claude Copilot orchestration system.

## Your Assignment
- Stream: Stream-B
- Stream Name: api-implementation
- Dependencies: Stream-A

## MANDATORY PROTOCOL

### Step 1: Query Your Tasks
Call task_list with streamId filter.

### Step 2: For EACH Task
- Before work: task_update(id="TASK-xxx", status="in_progress")
- After work: task_update(id="TASK-xxx", status="completed", notes="...")

### Step 3: Verify Before Exiting
Re-query task_list and verify ALL tasks show "completed".

### Step 4: Output Summary
Only after verification, output completion summary.

## Anti-Patterns (NEVER DO THESE)
- Claiming "complete" without calling task_update for each
- Skipping verification step
```

The worker queries Task Copilot and works autonomously with mandatory task updates.

---

## Workspace and Database Paths

### Workspace ID

Task Copilot uses the project folder name as the workspace ID:

```python
from pathlib import Path
workspace_id = Path(project_path).name  # e.g., "my-project"
```

The orchestrator uses the **same convention** to find the database.

### Database Path

```
~/.claude/tasks/{workspace_id}/tasks.db
```

Example:

```
~/.claude/tasks/my-project/tasks.db
```

**If database not found:**

```
[ERROR] Task Copilot database not found: ~/.claude/tasks/xxx/tasks.db
```

**Solution:** Run `/protocol` to initialize Task Copilot for this project.

---

## Troubleshooting

### No Streams Found

**Symptom:**

```
[ERROR] No streams found in Task Copilot database
```

**Cause:** Tasks don't have stream metadata.

**Solution:**

1. Work with `@agent-ta` to organize tasks into streams
2. Ensure task metadata includes:
   - `streamId` (e.g., "Stream-A")
   - `streamName` (e.g., "foundation")
   - `streamPhase` ("foundation", "parallel", or "integration")
3. Re-run orchestration: `/orchestrate start` (will auto-create files)

### Worker Not Starting

**Symptom:** Worker PID file created but process not running.

**Diagnosis:**

```bash
# Check log for errors
tail -50 .claude/orchestrator/logs/Stream-B.log
```

**Common causes:**

| Issue | Solution |
|-------|----------|
| `claude: command not found` | Add Claude Code to PATH |
| Permission denied | Run with proper permissions |
| Worktree doesn't exist | Orchestrator auto-creates, check file permissions |
| Port conflict (if HTTP API used) | Change port in Task Copilot config |

### Worker Keeps Restarting

**Symptom:** Worker restarts repeatedly, never completes.

**Diagnosis:**

```bash
# Check restart count in logs
grep "Restarting worker" .claude/orchestrator/logs/Stream-B.log
```

**Common causes:**

| Issue | Solution |
|-------|----------|
| Task blocked | Check task `blockedReason`, resolve blocker |
| Missing dependencies | Ensure foundation streams complete first |
| Code errors | Review logs, fix code issues |
| Context exhaustion | Worker may need human input |

### Database Permission Denied

**Symptom:**

```
SQLite query failed: database is locked
```

**Cause:** Another process has database open.

**Solution:**

1. Check for other Claude Code sessions
2. Close all sessions accessing this workspace
3. Wait 30 seconds for locks to release
4. Retry orchestration

### Process Orphaned

**Symptom:** PID file exists but process is zombie/defunct.

**Solution:**

```bash
# Clean up PID files
rm .claude/orchestrator/pids/*.pid

# Kill orphaned processes
ps aux | grep "claude --print" | grep -v grep | awk '{print $2}' | xargs kill

# Restart orchestration
python .claude/orchestrator/orchestrate.py start
```

---

## Best Practices

### 1. Test Foundation Thoroughly

Foundation affects all downstream streams. Before starting parallel work:

```bash
# Run all tests
npm test

# Verify build
npm run build

# Run lint
npm run lint

# Commit foundation
git add .
git commit -m "feat: Foundation complete for orchestration"
```

### 2. Keep Parallel Streams < 5

**Practical limits:**

| # Streams | Complexity | Recommendation |
|-----------|------------|----------------|
| 1-2 | Low | Manual coordination easier |
| 3-4 | Medium | Sweet spot for orchestration |
| 5 | High | Maximum recommended |
| 6+ | Very High | Split into multiple phases |

**Why?**

- Resource usage (memory/CPU per worker)
- Merge conflict probability increases
- Harder to monitor many streams

### 3. Monitor Regularly

Don't start orchestration and walk away:

```bash
# Terminal 1: Run orchestrator
python orchestrate.py start

# Terminal 2: Monitor live
./watch-status

# Terminal 3: Check logs
tail -f .claude/orchestrator/logs/Stream-B.log
```

### 4. Handle Blockers Quickly

If a worker gets blocked:

1. Check status: `python orchestrate.py status`
2. Review logs: `python orchestrate.py logs Stream-B`
3. Identify blocker (missing info, dependency, conflict)
4. Resolve issue (worker should auto-resume)

### 5. Clean Up After Completion

```bash
# Stop all workers
python orchestrate.py stop

# Remove PID files
rm .claude/orchestrator/pids/*.pid

# Archive logs (optional)
mkdir -p .archive/orchestration/$(date +%Y%m%d)
mv .claude/orchestrator/logs/* .archive/orchestration/$(date +%Y%m%d)/

# Remove worktrees (if used)
git worktree list
git worktree remove .claude/worktrees/Stream-B
git worktree remove .claude/worktrees/Stream-C
git worktree prune
```

---

## Comparison to Manual Orchestration

### Manual (tmux-based)

**Pros:**

- Full visibility into each worker
- Easy to intervene and provide input
- Familiar terminal-based workflow

**Cons:**

- Requires tmux knowledge
- Manual session management
- Complex setup with many streams
- Requires user to be logged in

### Headless (Automated)

**Pros:**

- Fully autonomous, no user intervention
- No tmux required
- Runs in background, can detach
- Auto-restart on failure
- Simple process management via PIDs

**Cons:**

- Less visibility (must check logs)
- Harder to provide input mid-execution
- If worker gets stuck, needs manual investigation

**When to use headless:**

- ✅ Well-defined tasks with clear acceptance criteria
- ✅ Minimal expected blockers
- ✅ Long-running work that doesn't need monitoring
- ✅ CI/CD integration (future)
- ✅ Running overnight/unattended

**When to use manual:**

- ✅ Exploratory work requiring human judgment
- ✅ Tasks likely to need user input
- ✅ Learning/debugging orchestration
- ✅ Need real-time visibility into worker actions

---

## Advanced Usage

### Custom Polling Interval

Edit `orchestrate.py`:

```python
POLL_INTERVAL = 30  # seconds (default)

# Change to:
POLL_INTERVAL = 10  # Check more frequently
POLL_INTERVAL = 60  # Check less frequently (reduce resource usage)
```

### Custom Max Restarts

Edit `orchestrate.py`:

```python
max_restarts = 10  # Default

# Change to:
max_restarts = 3   # Fail faster
max_restarts = 20  # More resilient to transient failures
```

### Running in Background

```bash
# Start in background
nohup python orchestrate.py start > orchestrator.out 2>&1 &

# Check progress
./watch-status

# Stop (find PID of orchestrator itself)
ps aux | grep "orchestrate.py start" | grep -v grep | awk '{print $2}' | xargs kill
```

### Filtering Streams

Start only specific phases:

```bash
# Only foundation
python orchestrate.py start $(grep "foundation" .claude/tasks.db | cut -d'|' -f1)

# Only parallel
python orchestrate.py start Stream-B Stream-C
```

---

## Integration with Task Copilot

### Stream Metadata Requirements

For orchestration to work, tasks must have:

```json
{
  "metadata": {
    "streamId": "Stream-B",
    "streamName": "api-implementation",
    "streamPhase": "parallel"
  }
}
```

**Set by @agent-ta when creating PRD.**

### Querying Streams

The orchestrator queries:

```sql
SELECT DISTINCT
    json_extract(metadata, '$.streamId') as stream_id,
    json_extract(metadata, '$.streamName') as stream_name,
    json_extract(metadata, '$.streamPhase') as stream_phase
FROM tasks
WHERE json_extract(metadata, '$.streamId') IS NOT NULL
  AND archived = 0
ORDER BY stream_phase, stream_id
```

**Archived streams are excluded** - only active streams are orchestrated.

### Task Progress

Completion detected by querying:

```sql
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
FROM tasks
WHERE json_extract(metadata, '$.streamId') = 'Stream-B'
  AND archived = 0
```

**Stream complete when:** `completed >= total`

---

## See Also

### Related Documentation

- **Stream Management**: `docs/TASK-WORKTREE-ISOLATION.md`
- **Task Copilot**: `mcp-servers/task-copilot/README.md`
- **Parallel Orchestration Reference**: `docs/PARALLEL_ORCHESTRATION.md` (Solution Copilot)

### Commands

- `/protocol` - Start fresh work with Agent-First Protocol
- `/continue [stream]` - Resume work on specific stream
- `/orchestrate start` - Set up and run parallel orchestration
- `/orchestrate status` - Check stream progress

### MCP Tools

- `stream_list()` - List all streams with progress
- `stream_get(streamId)` - Get detailed stream information
- `task_list({ streamId })` - List tasks in a stream
- `progress_summary()` - Get compact progress overview

---

## Appendix

### Worker Prompt Template

```
You are a worker agent in the Claude Copilot orchestration system.

## Your Assignment
- Stream: {stream.id}
- Stream Name: {stream.name}
- Dependencies: {deps_str}

## MANDATORY PROTOCOL - YOU MUST FOLLOW THIS EXACTLY

### Step 1: Query Your Tasks
Call task_list with streamId filter to get your assigned tasks.

### Step 2: For EACH Task (in order)

**Before starting work:**
task_update(id="TASK-xxx", status="in_progress")

**After completing work:**
task_update(id="TASK-xxx", status="completed", notes="Brief description")

**CRITICAL:** You MUST call task_update after EACH task. Do not batch updates.

### Step 3: Verify Before Exiting

**Before outputting any completion summary:**
1. Call task_list again
2. Check that ALL tasks have status: "completed"
3. If ANY task is still pending or in_progress, go back and complete it

### Step 4: Output Summary
Only after ALL tasks are verified complete, output:
- List of completed tasks with brief notes
- Any commits made
- Any issues encountered

## Anti-Patterns (NEVER DO THESE)
- Outputting "All tasks complete" without calling task_update for each
- Skipping verification step before exit
- Claiming success when Task Copilot shows pending tasks

Begin by querying your task list with task_list.
```

### Example Workflow

```bash
# 1. Create PRD with streams
claude
> /protocol
> Create a PRD with organized streams

# 2. Start orchestration (auto-creates files on first run)
> /orchestrate start

# 3. Monitor in separate terminal
./watch-status

# 4. Check logs if needed
tail -f .claude/orchestrator/logs/Stream-B.log

# 5. Wait for completion
# Workers run autonomously until all tasks complete

# 6. Clean up
python .claude/orchestrator/orchestrate.py stop
```

### File Structure

```
.claude/orchestrator/
├── orchestrate.py          # Main orchestrator
├── check-streams           # Status dashboard
├── watch-status            # Live monitoring
├── pids/                   # Process tracking
│   ├── Stream-A.pid
│   ├── Stream-B.pid
│   └── Stream-C.pid
└── logs/                   # Worker output
    ├── Stream-A.log
    ├── Stream-B.log
    └── Stream-C.log
```

---

*Updated: January 2026*
*Based on headless orchestration implementation*
