# Dynamic Orchestration System Guide

This document explains how the dynamic orchestration system works, what changes were made, and how to properly set up streams and dependencies for parallel execution.

## Overview

The orchestration system spawns multiple headless Claude Code sessions to work on different streams in parallel. It uses **Task Copilot as the single source of truth** for all stream and dependency information.

**Key Principle:** The orchestrator never needs to be modified. All configuration is done through Task Copilot task metadata.

---

## Pre-flight Validation

Before starting orchestration, validate your environment is ready:

```bash
python validate-setup.py              # Run all checks
python validate-setup.py --verbose    # Show detailed information
python validate-setup.py --fix        # Attempt automatic fixes
```

**What it checks:**
- Python version >= 3.8
- Claude CLI installed and in PATH
- Git version >= 2.5 with worktree support
- Current directory is a git repository
- Write permissions in project root
- .mcp.json exists with task-copilot configured
- MCP servers built (node_modules present)
- Orchestration templates available

**Exit codes:**
- 0 = All checks passed, ready for orchestration
- 1 = One or more checks failed

Run this before `/orchestrate generate` to catch environment issues early.

---

## How Dependencies Work

### The Dependency Contract

Every task in Task Copilot that belongs to a stream must have this metadata structure:

```json
{
  "streamId": "Stream-X",
  "streamName": "Human Readable Name",
  "dependencies": ["Stream-A", "Stream-B"]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `streamId` | Yes | Unique identifier for the stream (e.g., "Stream-A", "Stream-B") |
| `streamName` | No | Human-readable name (defaults to streamId if not provided) |
| `dependencies` | Yes | Array of streamIds that must complete before this stream can start. Use `[]` for no dependencies. |

### Dependency Resolution Algorithm

The orchestrator follows this logic:

1. **Query all streams** from Task Copilot by finding unique `metadata.streamId` values
2. **Build dependency graph** by collecting all `metadata.dependencies` arrays
3. **Calculate dependency depth** for each stream:
   - Depth 0: No dependencies (starts immediately)
   - Depth 1: Depends only on depth-0 streams
   - Depth N: Depends on at least one depth-(N-1) stream
4. **A stream is READY when:**
   - All streams in its `dependencies` array have 100% of their tasks completed
   - It's not already running
   - It's not already complete
5. **Continuous polling** every 30 seconds to spawn newly-ready streams

### Example: Stream A → B, C, D → Z

To ensure Stream-A completes before B, C, D start, and Stream-Z waits for all others:

```
Stream-A (foundation)     → dependencies: []
Stream-B (parallel work)  → dependencies: ["Stream-A"]
Stream-C (parallel work)  → dependencies: ["Stream-A"]
Stream-D (parallel work)  → dependencies: ["Stream-A"]
Stream-Z (final)          → dependencies: ["Stream-B", "Stream-C", "Stream-D"]
```

**Execution flow:**
1. Orchestrator starts → Stream-A is ready (no deps) → spawns worker
2. Stream-A completes (all tasks marked completed)
3. Next poll → B, C, D are ready → spawns 3 workers in parallel
4. B, C, D complete
5. Next poll → Z is ready → spawns worker
6. Z completes → orchestration done

---

## Key Features

### Dynamic Stream Discovery

The orchestrator automatically discovers all streams from Task Copilot:

```python
cursor.execute("""
    SELECT DISTINCT
        json_extract(metadata, '$.streamId') as stream_id,
        json_extract(metadata, '$.streamName') as stream_name,
        json_extract(metadata, '$.dependencies') as dependencies
    FROM tasks
    WHERE json_extract(metadata, '$.streamId') IS NOT NULL
      AND archived = 0
    ORDER BY stream_id
""")
```

**What it does:**
- Finds all unique streamIds from task metadata
- Extracts streamName for display
- Parses dependencies JSON array
- No hardcoded stream definitions

### Dependency Graph Construction

The orchestrator builds a dependency graph dynamically:

```python
def _build_dependency_graph(self) -> Dict[str, Set[str]]:
    dependency_graph: Dict[str, Set[str]] = defaultdict(set)

    for stream_id, stream in self.streams.items():
        dependencies = stream.get("dependencies", [])

        for dep in dependencies:
            if dep in self.streams:
                dependency_graph[stream_id].add(dep)

    return dependency_graph
```

**What it does:**
- Builds a mapping: `stream_id → set of streams it depends on`
- Handles both direct streamId references and task title formats

### Dependency Depth Calculation

The orchestrator calculates execution order without hardcoded phases:

```python
def _calculate_dependency_depth(self) -> Dict[str, int]:
    depths: Dict[str, int] = {}
    remaining = set(self.streams.keys())

    while remaining:
        ready = set()
        for stream_id in remaining:
            deps = self.stream_dependencies.get(stream_id, set())
            if all(dep in depths for dep in deps):
                ready.add(stream_id)

        for stream_id in ready:
            deps = self.stream_dependencies.get(stream_id, set())
            if deps:
                depths[stream_id] = max(depths[dep] for dep in deps) + 1
            else:
                depths[stream_id] = 0
            remaining.remove(stream_id)

    return depths
```

**What it does:**
- Calculates execution order without hardcoded phases
- Detects circular dependencies (warns if found)
- Groups streams by their dependency depth for status display

### Dynamic Readiness Check

The orchestrator checks actual stream completion:

```python
def _are_dependencies_complete(self, stream_id: str) -> bool:
    dependencies = self.stream_dependencies.get(stream_id, set())

    if not dependencies:
        return True  # No dependencies, always ready

    for dep_stream_id in dependencies:
        status = self._get_stream_status(dep_stream_id)
        if not status or not status["is_complete"]:
            return False

    return True
```

**What it does:**
- Queries Task Copilot for each dependency stream's completion status
- A stream is complete when `completed_tasks >= total_tasks`
- Returns True only when ALL dependencies are complete

### Continuous Polling Execution

The orchestrator uses continuous polling instead of phases:

```python
def start_all(self):
    while True:
        ready_streams = self._get_ready_streams()

        for stream_id in ready_streams:
            self.spawn_worker(stream_id)

        if all_complete:
            break

        time.sleep(POLL_INTERVAL)  # 30 seconds
```

**What it does:**
- No sequential phase execution
- Continuously finds ready streams and spawns workers
- Detects when stuck (nothing ready, nothing running)
- Exits when all streams complete

---

## Task Copilot Integration

### Metadata Format

Every task must include `streamId` and `dependencies` in metadata:

```python
task_create({
    "title": "Stream-B: Task Name",
    "prdId": "PRD-xxx",
    "description": "...",
    "assignedAgent": "me",
    "metadata": {
        "streamId": "Stream-B",           # Required
        "streamName": "Extraction Pipeline",  # Optional
        "dependencies": ["Stream-A"],     # Required (use [] for none)
        "complexity": "medium"            # Optional
    }
})
```

### How to Update Existing Tasks

Use `task_update` to set proper metadata:

```python
task_update({
    "id": "TASK-xxx",
    "metadata": {
        "streamId": "Stream-A",
        "streamName": "Database Foundation",
        "dependencies": []
    }
})
```

### Dependency Patterns

#### Pattern 1: Foundation Stream (No Dependencies)
```json
{"streamId": "Stream-A", "dependencies": []}
```
Starts immediately when orchestration begins.

#### Pattern 2: Single Dependency
```json
{"streamId": "Stream-B", "dependencies": ["Stream-A"]}
```
Waits for Stream-A to complete (100% tasks done).

#### Pattern 3: Multiple Dependencies (AND logic)
```json
{"streamId": "Stream-E", "dependencies": ["Stream-B", "Stream-C"]}
```
Waits for BOTH Stream-B AND Stream-C to complete.

#### Pattern 4: Final Stream (Depends on Many)
```json
{"streamId": "Stream-Final", "dependencies": ["Stream-B", "Stream-C", "Stream-D", "Stream-E"]}
```
Waits for all listed streams to complete.

---

## Creating New Streams for Future PRDs

### Step 1: Plan Your Streams

Identify logical groupings of work that can be parallelized:

```
Stream-A: Foundation (models, migrations)  → no deps
Stream-B: Service Layer                    → depends on A
Stream-C: API Layer                        → depends on A
Stream-D: Frontend                         → depends on C
Stream-E: Testing                          → depends on B, C, D
```

### Step 2: Create PRD

```python
prd_create({
    "title": "Feature Name",
    "description": "...",
    "content": "...",
    "metadata": {"tags": ["parallel-streams"]}
})
```

### Step 3: Create Tasks with Stream Metadata

```python
# Foundation tasks (no dependencies)
task_create({
    "title": "Stream-A: Create database models",
    "prdId": "PRD-xxx",
    "metadata": {
        "streamId": "Stream-A",
        "streamName": "Foundation",
        "dependencies": []
    }
})

# Dependent tasks
task_create({
    "title": "Stream-B: Implement service",
    "prdId": "PRD-xxx",
    "metadata": {
        "streamId": "Stream-B",
        "streamName": "Service Layer",
        "dependencies": ["Stream-A"]
    }
})
```

### Step 4: Run Orchestration

```bash
python .claude/orchestrator/orchestrate.py start
```

The orchestrator will:
1. Discover all streams from Task Copilot
2. Build dependency graph
3. Start Stream-A immediately
4. Start B, C when A completes
5. Continue until all complete

---

## Status Dashboard (watch-status)

### Architecture

The watch-status dashboard provides real-time monitoring of orchestration progress using a clean Python abstraction layer:

```
task_copilot_client.py  →  check_streams_data.py  →  check-streams (bash)
    (typed API)              (data fetcher)           (live dashboard)
```

#### Components

| Component | Purpose | Location |
|-----------|---------|----------|
| `task_copilot_client.py` | Clean API abstraction with typed dataclasses | `.claude/orchestrator/` |
| `check_streams_data.py` | Python script that outputs JSON data | `.claude/orchestrator/` |
| `check-streams` | Bash script that displays live dashboard | `.claude/orchestrator/` |

#### Data Models

The Task Copilot client uses strongly-typed dataclasses:

```python
@dataclass
class StreamInfo:
    stream_id: str
    stream_name: str
    dependencies: List[str]

@dataclass
class StreamProgress:
    stream_id: str
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
    completion_percentage: float

@dataclass
class ProgressSummary:
    streams: List[StreamProgress]
    overall_completion: float
    total_tasks: int
    completed_tasks: int
    in_progress_tasks: int
    pending_tasks: int
```

### Compact Dashboard Layout

The dashboard displays all streams in a compact single-line format:

```
PROJECT-NAME                                          91% ✓82 ⚙1 ○7
═══════════════════════════════════════════════════════════════════════════
Stream-A [===============] 100%  ✓30        RUN  PID:52471  Database Founda
Stream-F [=========------]  66%   ✓4  ⚙1 ○1 RUN  PID:82094  Outline/Draft I
Stream-H [---------------]   0%   ✓0     ○6 ---            QA Testing
═══════════════════════════════════════════════════════════════════════════
```

#### Status Symbols

| Symbol | Meaning | When Displayed |
|--------|---------|----------------|
| `✓` | Completed tasks | Always (shows count) |
| `⚙` | In-progress tasks | When `in_progress_tasks > 0` |
| `○` | Pending tasks | When `pending_tasks > 0` |

#### Status Codes

| Code | State | Description |
|------|-------|-------------|
| `RUN` | Running | Worker is actively processing tasks |
| `FIN` | Finished | All tasks completed |
| `DONE` | Done (alias) | Alternative completion state |
| `---` | Not started | No worker spawned yet |

### Dashboard Usage

#### Watch Mode (Live Updates)
```bash
./watch-status          # Default: 15 second interval
./watch-status 5        # Custom: 5 second interval
```

Automatically refreshes with clear screen.

#### One-Time Status Check
```bash
./.claude/orchestrator/check-streams
```

Returns single snapshot.

---

## Troubleshooting

### "No streams found in Task Copilot database"
- Ensure tasks have `metadata.streamId` set
- Check that tasks are not archived (`archived = 0`)

### "Circular dependency detected"
- Review your dependency graph for cycles
- A → B → C → A is invalid
- Fix by removing one dependency or restructuring

### "Orchestration stuck"
- Check blocked streams in status output
- Verify dependency streams are progressing
- Look for failed workers in logs

### Stream not starting when expected
- Verify all dependencies are truly complete (100% tasks)
- Check that dependency streamIds match exactly (case-sensitive)
- Run `python orchestrate.py status` to see blocking dependencies

---

## Best Practices

1. **Use consistent streamId naming**: `Stream-A`, `Stream-B`, etc.
2. **Keep dependency chains shallow**: Deep chains reduce parallelism
3. **Group related tasks**: All tasks in a stream should be cohesive
4. **Test with status command**: Verify dependency structure before running
5. **Monitor logs**: `python orchestrate.py logs Stream-A`
6. **Use watch-status during execution**: Run `./watch-status` in a split terminal for live progress monitoring

### Stream ID Naming Best Practices

**Use PRD-specific prefixes** to avoid conflicts between PRDs:

```
# Good - unique and identifiable
streamId: "KnowledgeFragments-A"
streamId: "PipelineAudit-A"
streamId: "Audit-Foundation"

# Bad - generic and prone to conflicts
streamId: "Stream-A"
streamId: "Stream-B"
```

**Why this matters:**
- Multiple PRDs may run in the same workspace
- Generic IDs like "Stream-A" can conflict across PRDs
- PRD-specific prefixes make streams immediately identifiable
- Dashboard displays become more meaningful

**Recommended pattern:**
```json
{
  "streamId": "PRDPrefix-Phase",
  "streamName": "Human Readable Name",
  "prdId": "PRD-xxx",
  "dependencies": []
}
```

**Example for a PRD about audit pipeline:**
```json
{
  "streamId": "Audit-A",
  "streamName": "Audit Foundation",
  "prdId": "PRD-123",
  "dependencies": []
}
```

This creates clear separation between PRDs and makes orchestration status more readable

---

## Worker Chaining (Automatic Stream Starting)

### Overview

The `start-ready-streams.py` script enables automatic worker chaining - when a worker completes its tasks, it can trigger the start of dependent streams without waiting for the orchestrator's next polling cycle.

This reduces latency between stream completions and dependent stream starts from up to 30 seconds (polling interval) down to near-instant.

### How It Works

```
Worker A completes → Calls start-ready-streams.py --completed-stream Stream-A
                  → Finds streams that depend on Stream-A
                  → Checks if all dependencies are satisfied
                  → Spawns workers for ready streams immediately
```

### Usage

#### Manual Invocation

Check and start any ready streams:
```bash
python .claude/orchestrator/start-ready-streams.py
```

Check streams that depend on a specific completed stream:
```bash
python .claude/orchestrator/start-ready-streams.py --completed-stream Stream-A
```

#### Automatic Invocation (Recommended)

Workers can call this script at the end of their execution to trigger dependent streams:

```python
# At end of worker prompt or in worker's final steps
import subprocess
subprocess.run([
    "python3",
    ".claude/orchestrator/start-ready-streams.py",
    "--completed-stream", "Stream-A"
])
```

### Benefits

| Benefit | Impact |
|---------|--------|
| **Reduced Latency** | Dependent streams start immediately instead of waiting for next poll |
| **Faster Overall Execution** | Especially beneficial for deep dependency chains |
| **Better Resource Usage** | Workers start as soon as they're ready, maximizing parallelism |
| **Orchestrator Still Works** | The polling orchestrator continues as backup/fallback |

### Architecture

```
orchestrate.py (main loop)
    ↓ spawns
worker-wrapper.sh
    ↓ runs
Claude worker for Stream-A
    ↓ completes tasks
    ↓ (optional) calls
start-ready-streams.py --completed-stream Stream-A
    ↓ checks
Task Copilot database
    ↓ finds Stream-B and Stream-C are ready
    ↓ spawns (via orchestrate.py start)
New workers for Stream-B and Stream-C
```

### Decision Logic

The script follows this logic for each stream:

1. **Skip if stream is complete** - Check `progress.is_complete`
2. **Skip if already running** - Check PID file existence
3. **Filter by --completed-stream** - Only consider streams that depend on the specified stream
4. **Check all dependencies complete** - Verify all dependency streams have 100% completion
5. **Start ready streams** - Call `orchestrate.py start <stream-id>` for each ready stream

### Example Flow

Given dependency chain: `Stream-A → [Stream-B, Stream-C] → Stream-D`

**Without worker chaining:**
```
T=0:00  Stream-A completes
T=0:30  Orchestrator polls, starts B and C
T=2:00  Stream-B completes
T=2:10  Stream-C completes
T=2:30  Orchestrator polls, starts D
Total delay from dependencies: 60 seconds
```

**With worker chaining:**
```
T=0:00  Stream-A completes, immediately triggers B and C
T=2:00  Stream-B completes, checks D (not ready yet)
T=2:10  Stream-C completes, immediately triggers D
Total delay from dependencies: 0 seconds
```

### Integration with worker-wrapper.sh

The worker-wrapper.sh handles PID management and logging. When combined with worker chaining:

1. Worker-wrapper spawns Claude session
2. Claude completes all tasks in stream
3. (Optional) Claude calls start-ready-streams.py before exit
4. Worker-wrapper cleans up PID file
5. Start-ready-streams spawns new workers (which use worker-wrapper)

### Best Practices

1. **Use --completed-stream flag** when calling from workers for efficiency
2. **Call after verifying tasks complete** to avoid false triggers
3. **Handle errors gracefully** - orchestrator polling provides fallback
4. **Don't rely solely on chaining** - orchestrator still needed for restart scenarios

---

## File Locations

| File | Purpose |
|------|---------|
| `.claude/orchestrator/orchestrate.py` | Main orchestrator script |
| `.claude/orchestrator/start-ready-streams.py` | Worker chaining script (automatic stream starting) |
| `.claude/orchestrator/worker-wrapper.sh` | Worker wrapper for PID management and log archiving |
| `.claude/orchestrator/task_copilot_client.py` | Task Copilot data abstraction |
| `.claude/orchestrator/check_streams_data.py` | Stream data fetcher |
| `.claude/orchestrator/check-streams` | Status dashboard script |
| `.claude/orchestrator/watch-status` | Live monitoring wrapper |
| `.claude/orchestrator/logs/` | Worker log files |
| `.claude/orchestrator/pids/` | Worker PID files |
| `~/.claude/tasks/{workspace}/tasks.db` | Task Copilot SQLite database |

---

## Summary

The dynamic orchestration system requires:

1. **Tasks with proper metadata:**
   - `streamId`: Unique stream identifier
   - `dependencies`: Array of streamIds (or empty array)

2. **No orchestrator changes needed:**
   - All configuration via Task Copilot
   - Dependency graph built dynamically
   - Execution order calculated automatically

3. **Execution guarantees:**
   - A stream starts ONLY when all its dependencies are 100% complete
   - Multiple independent streams run in parallel
   - Final streams wait for all predecessors

This system ensures proper execution order while maximizing parallelism.
