---
name: orchestrate
description: Set up and manage parallel stream orchestration for Task Copilot
alwaysAllow: true
---

# Orchestrate Command

This command helps set up and run the orchestration system for parallel Claude Code workers.

## Usage

```
/orchestrate start     # Set up (if needed) and start orchestration
/orchestrate status    # Check status of all streams
/orchestrate stop      # Stop all running workers
```

## What This Does

### `/orchestrate start`

**Single command that handles everything:**

**First Run (nothing exists):**
1. Creates `.claude/orchestrator/` directory in project root
2. Copies template files from framework:
   - `task_copilot_client.py` - Task Copilot data abstraction layer
   - `check_streams_data.py` - Stream data fetcher for bash scripts
   - `check-streams` - Live status dashboard (with dynamic workspace detection)
   - `watch-status` - Wrapper for live status updates
   - `orchestrate.py` - Main orchestration script with dynamic dependencies
3. Creates symlink: `./watch-status` → `.claude/orchestrator/watch-status`
4. Makes scripts executable (`chmod +x`)
5. Then starts orchestration

**Subsequent Runs (files exist):**
1. Validates all required files are present and correct:
   - `orchestrate.py`
   - `task_copilot_client.py`
   - `check_streams_data.py`
   - `check-streams`
   - `watch-status`
2. Fixes any missing files (copies from templates)
3. Fixes symlink if broken
4. Then starts orchestration

**Runs the orchestration system:**
```bash
python .claude/orchestrator/orchestrate.py start
```

Options:
- `start` - Start all streams (respects dependencies)
- `start Stream-A` - Start specific stream only
- `status` - Display status of all streams
- `stop` - Stop all running workers
- `logs Stream-A` - Tail logs for specific stream

### Dynamic Workspace Detection

The generated `check-streams` script automatically detects the workspace ID from the project directory name. No manual configuration needed.

**Example:**
- Project: `/Users/you/projects/my-app`
- Workspace ID: `my-app` (auto-detected)
- Task DB: `~/.claude/tasks/my-app/tasks.db`

## Prerequisites

Before using orchestration:

1. **Task Copilot with stream metadata**: All tasks must include:
   ```json
   {
     "metadata": {
       "streamId": "Stream-A",
       "streamName": "Foundation Work",
       "dependencies": []
     }
   }
   ```

2. **Python 3.7+** installed

3. **Git worktrees** (optional): For parallel streams working on different branches

## File Structure

After running `/orchestrate start` (first time):

```
your-project/
├── .claude/
│   └── orchestrator/
│       ├── orchestrate.py           # Main orchestrator
│       ├── task_copilot_client.py   # Data abstraction layer
│       ├── check_streams_data.py    # Stream data fetcher
│       ├── check-streams            # Status dashboard
│       ├── watch-status             # Live monitoring wrapper
│       ├── logs/                    # Worker logs (created at runtime)
│       └── pids/                    # Worker PIDs (created at runtime)
└── watch-status                     # Symlink to orchestrator/watch-status
```

## Live Status Monitoring

After starting orchestration, monitor progress:

```bash
./watch-status          # Live updates every 15s
./watch-status 5        # Live updates every 5s
```

Dashboard shows:
- Overall progress across all streams
- Per-stream progress bars
- Task counts (completed, in-progress, pending)
- Worker status (running, stopped, finished)
- Process IDs for active workers

## How Dependencies Work

The orchestration system uses Task Copilot as the single source of truth:

1. **Query streams** - Finds all unique `metadata.streamId` values
2. **Build dependency graph** - Uses `metadata.dependencies` arrays
3. **Calculate execution order** - Streams with no dependencies start first
4. **Continuous polling** - Every 30s, spawns newly-ready streams
5. **A stream is ready when:**
   - All streams in its `dependencies` array are 100% complete
   - It's not already running
   - It's not already complete

**Example dependency chain:**
```
Stream-A (foundation)     → dependencies: []
Stream-B (parallel work)  → dependencies: ["Stream-A"]
Stream-C (parallel work)  → dependencies: ["Stream-A"]
Stream-Z (final)          → dependencies: ["Stream-B", "Stream-C"]
```

Execution:
1. Stream-A starts immediately (no deps)
2. When A completes → B and C start in parallel
3. When B and C complete → Z starts
4. When Z completes → orchestration done

## Troubleshooting

### "No streams found in Task Copilot database"
- Ensure tasks have `metadata.streamId` set
- Check tasks are not archived (`archived = 0`)

### "Circular dependency detected"
- Review dependency graph for cycles (A → B → C → A is invalid)
- Restructure to break the cycle

### "Orchestration stuck"
- Run `python .claude/orchestrator/orchestrate.py status`
- Check which streams are blocked and why
- Verify dependency streams are progressing
- Check logs: `python .claude/orchestrator/orchestrate.py logs Stream-A`

### Symlink issues
- Run `/orchestrate start` - it will auto-fix broken symlinks
- Check file permissions (scripts should be executable)

## Documentation

For full orchestration system documentation, see:
- `.claude/orchestrator/ORCHESTRATION_GUIDE.md` (created after first run)

## Notes

- **No hardcoded phases**: All execution order determined by dependencies
- **No orchestrator modifications needed**: Configure via Task Copilot metadata
- **Automatic parallelism**: Independent streams run simultaneously
- **Clean shutdown**: Ctrl-C stops orchestrator, workers continue (use `stop` command to kill workers)

---

## Implementation

When user runs `/orchestrate [command]`:

1. **Validate command** - Must be `start`, `status`, or `stop`

2. **For `start`:**
   - **Setup/Validation Phase:**
     - Detect project root (current working directory)
     - Check if `.claude/orchestrator/` directory exists
     - Check if all required files exist:
       - `orchestrate.py`
       - `task_copilot_client.py`
       - `check_streams_data.py`
       - `check-streams`
       - `watch-status`
     - Check if symlink `./watch-status` exists at project root
     - **If directory missing:** Create `.claude/orchestrator/`
     - **If any files missing or broken:**
       - Copy all template files from `{framework_root}/templates/orchestration/`
       - Replace `WORKSPACE_ID="insights-copilot"` with dynamic detection in `check-streams`
       - Make scripts executable (`chmod +x`)
       - Copy ORCHESTRATION_GUIDE.md
     - **If symlink missing or broken:**
       - Create symlink: `watch-status` → `.claude/orchestrator/watch-status`
   - **Execution Phase:**
     - Run `python .claude/orchestrator/orchestrate.py start`
     - Show output in real-time

3. **For `status` and `stop`:**
   - Run `python .claude/orchestrator/orchestrate.py [command]`
   - Show output in real-time
