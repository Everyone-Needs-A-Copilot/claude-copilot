# Orchestration System - Quick Reference

## Overview

The `/orchestrate` command sets up and manages parallel stream execution with dynamic dependency resolution. All configuration comes from Task Copilot metadata - no hardcoded phases or execution order.

**Key principle:** The orchestrator never needs modification. All configuration is done through Task Copilot task metadata.

## Quick Start

```bash
# 1. Create PRD with streams (work with @agent-ta)
/protocol
> Create a PRD with these streams:
>   Stream-A (foundation) - no dependencies
>   Stream-B (parallel) - depends on Stream-A
>   Stream-C (parallel) - depends on Stream-A
>   Stream-Z (integration) - depends on Stream-B, Stream-C

# 2. Start orchestration (auto-creates files on first run)
/orchestrate start

# 3. Monitor in separate terminal
./watch-status
```

## Command Reference

**Location:** `.claude/commands/orchestrate.md`

| Command | Purpose |
|---------|---------|
| `/orchestrate start` | Set up (if needed) and start all streams |
| `/orchestrate start Stream-B` | Start specific stream only |
| `/orchestrate status` | Display status of all workers |
| `/orchestrate stop` | Stop all running workers |

**First run automatically:**
- Creates `.claude/orchestrator/` directory
- Copies all template files
- Creates `./watch-status` symlink
- Makes scripts executable
- Starts orchestration

## Generated Files

After running `/orchestrate start`, these files are created in your project:

### Main Scripts (`.claude/orchestrator/`)

| File | Lines | Purpose |
|------|-------|---------|
| `orchestrate.py` | 647 | Main orchestrator - spawns workers, manages lifecycle, resolves dependencies |
| `task_copilot_client.py` | 360 | Clean abstraction for Task Copilot SQLite with typed dataclasses |
| `check_streams_data.py` | 50 | Data fetcher outputting parseable format for bash scripts |
| `check-streams` | 269 | Status dashboard with compact single-line stream display |
| `watch-status` | 26 | Live monitoring wrapper with configurable refresh interval |
| `ORCHESTRATION_GUIDE.md` | 920+ | Complete documentation (copy of main guide) |

### Runtime Directories

| Directory | Contents |
|-----------|----------|
| `.claude/orchestrator/logs/` | Worker output logs (e.g., `Stream-A.log`) |
| `.claude/orchestrator/pids/` | Worker process IDs (e.g., `Stream-A.pid`) |

### Project Root

| File | Type | Purpose |
|------|------|---------|
| `./watch-status` | Symlink | Points to `.claude/orchestrator/watch-status` for quick access |

## How Dependencies Work

### The Dependency Contract

Every task must include this metadata:

```json
{
  "streamId": "Stream-B",
  "streamName": "API Implementation",
  "dependencies": ["Stream-A"]
}
```

### Dynamic Resolution Algorithm

1. **Query all streams** from Task Copilot (finds unique `streamId` values)
2. **Build dependency graph** from `dependencies` arrays
3. **Calculate dependency depth** for each stream
4. **Continuous polling** (every 30s) finds ready streams
5. **A stream is ready when:**
   - All dependencies are 100% complete (all tasks done)
   - Stream is not already running
   - Stream is not already complete

### Example Dependency Chain

```
Stream-A (foundation)     → dependencies: []
Stream-B (parallel work)  → dependencies: ["Stream-A"]
Stream-C (parallel work)  → dependencies: ["Stream-A"]
Stream-Z (final)          → dependencies: ["Stream-B", "Stream-C"]
```

**Execution:**
1. Stream-A starts immediately (no deps)
2. When A completes → B and C start in parallel
3. When B and C complete → Z starts
4. When Z completes → orchestration done

**No hardcoded phases.** Execution order emerges from dependency graph.

## Usage Examples

### Starting Orchestration

```bash
# Start all streams (auto-creates files on first run)
/orchestrate start

# Start specific stream only
/orchestrate start Stream-B

# Monitor progress in separate terminal
./watch-status

# Check detailed status
python .claude/orchestrator/orchestrate.py status

# View worker logs
python .claude/orchestrator/orchestrate.py logs Stream-A

# Stop all workers
/orchestrate stop
```

## Task Metadata Format

### Required Fields

```json
{
  "metadata": {
    "streamId": "Stream-B",           // Required - unique identifier
    "dependencies": ["Stream-A"]       // Required - array (use [] for none)
  }
}
```

### Optional Fields

```json
{
  "metadata": {
    "streamId": "Stream-B",
    "streamName": "API Implementation",  // Optional - defaults to streamId
    "dependencies": ["Stream-A"]
  }
}
```

### Dependency Patterns

| Pattern | Metadata | Behavior |
|---------|----------|----------|
| **No dependencies** | `"dependencies": []` | Starts immediately |
| **Single dependency** | `"dependencies": ["Stream-A"]` | Waits for Stream-A to complete |
| **Multiple dependencies** | `"dependencies": ["Stream-A", "Stream-B"]` | Waits for BOTH (AND logic) |
| **Sequential chain** | A→[], B→[A], C→[B] | A, then B, then C |
| **Parallel + merge** | A→[], B→[A], C→[A], Z→[B,C] | A, then B+C parallel, then Z |

## File Structure After Generation

```
your-project/
├── .claude/
│   └── orchestrator/
│       ├── orchestrate.py           # Main orchestrator (647 lines)
│       ├── task_copilot_client.py   # Data abstraction (360 lines)
│       ├── check_streams_data.py    # Data fetcher (50 lines)
│       ├── check-streams            # Status dashboard (269 lines)
│       ├── watch-status             # Live wrapper (26 lines)
│       ├── ORCHESTRATION_GUIDE.md   # Documentation (589 lines)
│       ├── logs/                    # Worker logs (created at runtime)
│       └── pids/                    # Worker PIDs (created at runtime)
└── watch-status                     # Symlink to orchestrator/watch-status
```

## Key Features

### 1. Dynamic Workspace Detection

Workspace ID is automatically detected from project directory name:

```python
# orchestrate.py
PROJECT_ROOT = SCRIPT_DIR.parent.parent
WORKSPACE_ID = PROJECT_ROOT.name
```

```bash
# check-streams
WORKSPACE_ID=$(basename "$PROJECT_ROOT")
```

**Benefit:** Works for any project without manual configuration.

### 2. Runtime Query System

No static configuration files. All data comes from Task Copilot:

```python
# Query streams
stream_infos = tc_client.stream_list()

# Check progress
progress = tc_client.stream_get(stream_id)

# Get overall status
summary = tc_client.progress_summary()
```

**Benefit:** Single source of truth, always up-to-date.

### 3. Headless Workers

Spawns autonomous Claude Code sessions:

```python
proc = subprocess.Popen(
    ["claude", "--print", "--dangerously-skip-permissions", "-p", prompt],
    cwd=work_dir,
    stdout=log_file,
    stderr=subprocess.STDOUT,
    start_new_session=True
)
```

**Benefit:** Fully autonomous, runs without user interaction.

### 4. Auto-Restart on Failure

Workers automatically restart up to 10 times on failure.

**Benefit:** Resilient to transient errors.

## Troubleshooting

### "No streams found in Task Copilot database"
- Ensure tasks have `metadata.streamId` and `metadata.dependencies` set
- Check tasks are not archived (`archived = 0`)
- Work with `@agent-ta` to organize tasks into streams

### "Circular dependency detected"
- Review dependency graph for cycles (A → B → C → A is invalid)
- Restructure to break the cycle

### Worker not starting
- Check logs: `python .claude/orchestrator/orchestrate.py logs Stream-A`
- Verify `claude` command is in PATH: `which claude`
- Check Task Copilot database exists: `~/.claude/tasks/{workspace}/tasks.db`

### Orchestration stuck
- Run status: `python .claude/orchestrator/orchestrate.py status`
- Check which streams are blocked and why
- Verify dependency streams are progressing

## Documentation

For complete documentation, see:
- **Full guide:** `docs/50-features/01-orchestration-guide.md` (920+ lines)
- **Command reference:** `.claude/commands/orchestrate.md`
- **Task Copilot:** `mcp-servers/task-copilot/README.md`
- **Template guide:** Generated in `.claude/orchestrator/ORCHESTRATION_GUIDE.md`

---

**Key Principle:** The orchestrator never needs modification. All configuration is done through Task Copilot task metadata.
