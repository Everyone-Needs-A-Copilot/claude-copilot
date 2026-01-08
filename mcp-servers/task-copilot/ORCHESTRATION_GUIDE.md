# Claude Code Orchestration System Guide

**Version:** 1.0
**Date:** 2026-01-08
**Component:** Task Copilot v1.8.0+

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Components](#components)
5. [Three-Phase Execution Model](#three-phase-execution-model)
6. [Usage Guide](#usage-guide)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Topics](#advanced-topics)
9. [API Reference](#api-reference)

---

## Overview

The Claude Code Orchestration System enables **parallel development** across multiple independent work streams using separate Claude Code sessions. This dramatically reduces initiative completion time by allowing agents to work on different features simultaneously.

### Key Benefits

| Benefit | Description | Impact |
|---------|-------------|--------|
| **Parallel Execution** | Run multiple Claude sessions simultaneously | 3-5x faster initiative completion |
| **Zero File Conflicts** | Git worktrees provide complete isolation | No merge conflicts during development |
| **Real-time Monitoring** | Live progress tracking across all streams | Instant visibility into bottlenecks |
| **Dependency Management** | Automatic enforcement of execution order | Prevents premature parallel work |
| **Context Preservation** | Each stream maintains independent context | No cross-stream interference |

### When to Use Orchestration

**Use orchestration when:**
- ✓ Initiative has 5+ tasks across multiple files
- ✓ Tasks can be grouped into independent streams
- ✓ Parallel work would save significant time
- ✓ Foundation work must complete before parallel work

**Don't use orchestration when:**
- ✗ Initiative has <3 tasks
- ✗ All work is sequential (no parallelization possible)
- ✗ Single file being modified
- ✗ Quick bugfix or hotfix

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Orchestration System                    │
└─────────────────────────────────────────────────────────────┘

┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Task Copilot    │    │  /orchestration  │    │  watch-status.py │
│  HTTP API        │◄───│  Command         │◄───│  Monitor         │
│  (Port 9090)     │    │                  │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
        │                        │                        │
        │                        ▼                        │
        │              orchestration-config.json          │
        │              start-streams.py                   │
        │              README.md                          │
        │                        │                        │
        └────────────────────────┴────────────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌─────────┐  ┌─────────┐  ┌─────────┐
              │Claude #1│  │Claude #2│  │Claude #3│
              │Stream-A │  │Stream-B │  │Stream-C │
              └─────────┘  └─────────┘  └─────────┘
                  │            │            │
                  ▼            ▼            ▼
              Main         Worktree     Worktree
              Worktree     .claude/     .claude/
              (project     worktrees/   worktrees/
               root)       Stream-B     Stream-C
```

### Component Responsibilities

| Component | Purpose | Technology |
|-----------|---------|------------|
| **Task Copilot HTTP API** | Exposes stream/task data to external tools | Fastify (Node.js) |
| **/orchestration command** | Generates orchestration scripts | Claude command (Markdown) |
| **watch-status.py** | Real-time progress monitoring | Python 3.8+ |
| **start-streams.py** | Stream execution orchestrator | Python 3.8+ |
| **Git Worktrees** | Parallel workspace isolation | Git 2.5+ |
| **Stream Tools** | Stream metadata and dependencies | Task Copilot MCP |

### Data Flow

```
1. User defines streams in PRD (Stream-A, Stream-B, Stream-C)
                  ↓
2. /orchestration command queries Task Copilot via MCP
                  ↓
3. Generates orchestration-config.json + scripts
                  ↓
4. User starts monitor: python3 watch-status.py
                  ↓
5. Monitor polls HTTP API at /api/streams
                  ↓
6. User runs /continue Stream-A in Claude session
                  ↓
7. Agent completes tasks, updates progress
                  ↓
8. Monitor displays updated progress bars
                  ↓
9. When Stream-A complete, Stream-B can start
                  ↓
10. Parallel streams run in separate worktrees
                  ↓
11. Monitor shows all streams simultaneously
                  ↓
12. Integration stream runs after all parallel complete
```

---

## Quick Start

### Prerequisites

**Install dependencies:**
```bash
# Python 3.8+ required
python3 --version

# Install requests library
pip install requests

# Verify Git worktree support
git worktree --version
```

**Configure Task Copilot HTTP API:**
```json
// .mcp.json
{
  "mcpServers": {
    "task-copilot": {
      "env": {
        "HTTP_API_PORT": "9090",
        "HTTP_API_HOST": "127.0.0.1"
      }
    }
  }
}
```

### 5-Minute Tutorial

**Step 1: Define streams in your PRD**
```
Foundation Phase:
- Stream-A: Core type system, database schema (4 tasks)

Parallel Phase:
- Stream-B: Command updates (2 tasks, depends on Stream-A)
- Stream-C: Agent updates (3 tasks, depends on Stream-A)

Integration Phase:
- Stream-Z: Documentation and testing (5 tasks, depends on Stream-B, Stream-C)
```

**Step 2: Generate orchestration scripts**
```bash
# In Claude Code session
/orchestration generate
```

**Step 3: Start real-time monitor**
```bash
# In separate terminal
cd .claude/orchestration
python3 watch-status.py
```

**Step 4: Execute streams in order**
```bash
# Terminal 1: Foundation stream (must complete first)
claude
/continue Stream-A

# Terminal 2: Parallel stream #1 (after foundation done)
claude
/continue Stream-B

# Terminal 3: Parallel stream #2 (after foundation done)
claude
/continue Stream-C

# Terminal 4: Integration stream (after all parallel done)
claude
/continue Stream-Z
```

**Step 5: Monitor progress**
Watch the monitor terminal for real-time updates:
```
╔══════════════════════════════════════════════════════════════════╗
║  ORCHESTRATION STATUS               [Refresh: 5s]                ║
╠══════════════════════════════════════════════════════════════════╣
║  Overall: ████████████░░░░░░░░ 60.0% (9/15 tasks)                ║
╠══════════════════════════════════════════════════════════════════╣
║  Stream-A (foundation)  ████████████████████ 100.0% ✓ COMPLETE   ║
║  Stream-B (parallel)    ██████████░░░░░░░░░░ 50.0% (1/2 tasks)   ║
║    └─ @agent-me: Implementing command handler                    ║
║  Stream-C (parallel)    ██████░░░░░░░░░░░░░░ 33.3% (1/3 tasks)   ║
║    └─ @agent-me: Updating agent templates                        ║
║  Stream-Z (integration) ░░░░░░░░░░░░░░░░░░░░  0.0% (0/5 tasks)   ║
║    ⚠ Waiting on: Stream-B, Stream-C                              ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Components

### 1. Task Copilot HTTP API

**Purpose:** Exposes Task Copilot data to external tools via REST API.

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/streams` | GET | List all streams with progress |
| `/api/streams/:streamId` | GET | Get specific stream details |
| `/api/tasks` | GET | Query tasks with filters |
| `/api/activity` | GET | Get current agent activity |

**Example Request:**
```bash
curl http://127.0.0.1:9090/api/streams/Stream-A | jq
```

**Example Response:**
```json
{
  "streamId": "Stream-A",
  "streamName": "foundation",
  "streamPhase": "foundation",
  "totalTasks": 4,
  "completedTasks": 3,
  "inProgressTasks": 1,
  "blockedTasks": 0,
  "pendingTasks": 0,
  "progressPercentage": 75.0,
  "status": "in_progress",
  "dependencies": [],
  "worktreePath": null,
  "branchName": "main",
  "tasks": [
    {
      "id": "TASK-001",
      "title": "Implement type system",
      "status": "completed",
      "assignedAgent": "me"
    }
  ]
}
```

**Configuration:**
```bash
# Environment variables
export HTTP_API_HOST="127.0.0.1"
export HTTP_API_PORT="9090"
```

**Security:**
- Binds to localhost only (not exposed to network)
- No authentication required (local-only access)
- CORS not enabled (same-origin only)

---

### 2. /orchestration Command

**Purpose:** Generates orchestration scripts and configuration.

**Actions:**

| Action | Command | Description |
|--------|---------|-------------|
| Generate | `/orchestration` or `/orchestration generate` | Create all scripts |
| Config | `/orchestration config` | Show current config |
| Status | `/orchestration status` | Display stream progress |

**What it generates:**

```
.claude/orchestration/
├── orchestration-config.json   # Stream configuration
├── start-streams.py            # Orchestration script (700+ lines)
└── README.md                   # Usage documentation
```

**orchestration-config.json structure:**
```json
{
  "version": "1.0",
  "generatedAt": "2026-01-08T12:00:00Z",
  "initiative": {
    "id": "init-123",
    "name": "Parallel Orchestration"
  },
  "apiBaseUrl": "http://127.0.0.1:9090",
  "pollInterval": 30,
  "maxParallelStreams": 5,
  "streams": [
    {
      "streamId": "Stream-A",
      "streamName": "foundation",
      "streamPhase": "foundation",
      "totalTasks": 4,
      "completedTasks": 0,
      "dependencies": [],
      "projectRoot": "/path/to/project",
      "worktreePath": null
    }
  ],
  "executionPlan": {
    "foundation": ["Stream-A"],
    "parallel": ["Stream-B", "Stream-C"],
    "integration": ["Stream-Z"]
  }
}
```

**Validation rules:**
- ✓ At least one foundation stream required
- ✓ Maximum 5 parallel streams (practical limit)
- ✓ No circular dependencies
- ✓ All dependencies must reference existing streams

---

### 3. watch-status.py Monitor

**Purpose:** Real-time terminal display of orchestration progress.

**Features:**
- Live terminal updates (default 5s refresh)
- Unicode progress bars (█ filled, ░ empty)
- ANSI color coding (green=complete, yellow=active, red=blocked)
- Agent activity tracking per stream
- Alerts section for blocked streams
- Graceful keyboard interrupt handling

**Usage:**
```bash
# Default settings
python3 watch-status.py

# Custom refresh interval
python3 watch-status.py --refresh 10

# Disable colors (for non-ANSI terminals)
python3 watch-status.py --no-color

# Custom API endpoint
python3 watch-status.py --api http://localhost:9090
```

**Display Format:**
```
╔══════════════════════════════════════════════════════════════════╗
║  ORCHESTRATION STATUS               [Refresh: 5s]                ║
╠══════════════════════════════════════════════════════════════════╣
║  Overall: ████████████░░░░░░░░ 60.0% (9/15 tasks)                ║
╠══════════════════════════════════════════════════════════════════╣
║  Stream-A (foundation)  ████████████████████ 100.0% ✓ COMPLETE   ║
║  Stream-B (parallel)    ██████████░░░░░░░░░░ 50.0% (1/2 tasks)   ║
║    └─ @agent-me: Implementing feature X                          ║
║  Stream-C (parallel)    ░░░░░░░░░░░░░░░░░░░░  0.0% (0/3 tasks)   ║
╠══════════════════════════════════════════════════════════════════╣
║  ALERTS                                                          ║
║  ⚠ Stream-C: Waiting on dependencies                             ║
╚══════════════════════════════════════════════════════════════════╝

Press Ctrl+C to exit
```

**Exit:**
Press `Ctrl+C` to stop monitoring. Claude sessions continue running in background.

---

### 4. start-streams.py Script

**Purpose:** Automated stream execution orchestrator (optional, user-customizable).

**Note:** This is a **template** for customization. Default implementation requires manual session launching.

**CLI Arguments:**

| Argument | Description | Example |
|----------|-------------|---------|
| (none) | Run full orchestration | `python3 start-streams.py` |
| `--dry-run` | Preview execution plan | `python3 start-streams.py --dry-run` |
| `--stream <id>` | Start specific stream | `python3 start-streams.py --stream Stream-B` |
| `--status` | Show current status | `python3 start-streams.py --status` |

**Example output:**
```
Orchestration Manager v1.0

Loading configuration...
✓ Configuration loaded: 3 streams

Checking API health...
✓ Task Copilot API is healthy

Phase 1: Foundation
────────────────────────────────────────────────────────
Starting Stream-A (foundation)...
⚠ Manual action required:
  1. Open new terminal
  2. Run: cd /path/to/project
  3. Run: claude
  4. Run: /continue Stream-A
  5. Complete all tasks in Stream-A

Press Enter when Stream-A is complete...
```

**Customization points:**
```python
# Line ~200: Customize session launching
def _start_stream_session(self, stream_id: str, work_dir: str):
    """
    CUSTOMIZE THIS METHOD for your environment.

    Options:
    - iTerm2 automation
    - tmux session management
    - screen sessions
    - Manual instructions (default)
    """
    print(f"⚠ Manual action required:")
    print(f"  1. Open new terminal")
    print(f"  2. Run: cd {work_dir}")
    print(f"  3. Run: claude")
    print(f"  4. Run: /continue {stream_id}")
```

**Three-phase execution:**
1. **Foundation:** Manual start → wait for completion → proceed
2. **Parallel:** Start all at once (max 5) → poll until all complete
3. **Integration:** Start after all parallel done → wait for completion

---

### 5. Git Worktrees

**Purpose:** Provide complete file isolation for parallel streams.

**Created automatically by `/continue` command when starting parallel streams.**

**Structure:**
```
my-project/                      # Main worktree (foundation + integration)
├── src/
├── .git/
└── .claude/
    └── worktrees/
        ├── Stream-B/            # Parallel stream worktree
        │   ├── src/             # Independent file tree
        │   └── .git/            # Linked to main .git
        └── Stream-C/            # Parallel stream worktree
            ├── src/
            └── .git/
```

**Benefits:**
- ✓ Zero file conflicts during development
- ✓ Independent git state per stream
- ✓ True parallel execution
- ✓ Easy merge after completion

**Managed by:**
- `/continue Stream-X` creates worktree if needed
- Worktree path stored in task metadata
- Orchestration scripts validate worktree exists

**Cleanup after merge:**
```bash
# After merging Stream-B into main
git worktree remove .claude/worktrees/Stream-B
```

---

## Three-Phase Execution Model

### Phase 1: Foundation

**Purpose:** Shared infrastructure that parallel work depends on.

**Characteristics:**
- ✓ Runs in main worktree
- ✓ No dependencies on other streams
- ✓ **Must complete before parallel work starts**
- ✓ Typically 1-2 streams
- ✓ Examples: Type systems, database schemas, core APIs

**Execution:**
```bash
# Must be completed sequentially before parallel work
claude
/continue Stream-A
# Complete all tasks in Stream-A
```

**Progress tracking:**
```
Stream-A (foundation)  ████████████████████ 100.0% ✓ COMPLETE
```

---

### Phase 2: Parallel

**Purpose:** Independent features that can run simultaneously.

**Characteristics:**
- ✓ Runs in dedicated worktrees (`.claude/worktrees/Stream-X`)
- ✓ Depends on foundation streams
- ✓ **Can run simultaneously (max 5 streams)**
- ✓ Complete file isolation via Git worktrees
- ✓ Examples: UI components, API endpoints, agent updates

**Execution:**
```bash
# Terminal 1
claude
/continue Stream-B

# Terminal 2 (simultaneously)
claude
/continue Stream-C

# Terminal 3 (simultaneously)
claude
/continue Stream-D
```

**Progress tracking:**
```
Stream-B (parallel)    ██████████░░░░░░░░░░ 50.0% (1/2 tasks)
  └─ @agent-me: Implementing command handler
Stream-C (parallel)    ██████░░░░░░░░░░░░░░ 33.3% (1/3 tasks)
  └─ @agent-qa: Testing agent validation
Stream-D (parallel)    ████████░░░░░░░░░░░░ 40.0% (2/5 tasks)
  └─ @agent-doc: Writing API documentation
```

**Dependency checking:**
Before starting parallel streams, verify foundation complete:
```bash
python3 start-streams.py --dry-run
# Shows: "✓ Foundation complete, parallel streams can start"
```

---

### Phase 3: Integration

**Purpose:** Combine work from parallel streams, final testing.

**Characteristics:**
- ✓ Runs in main worktree
- ✓ Depends on **all parallel streams**
- ✓ **Runs after all parallel complete**
- ✓ Typically 1 stream
- ✓ Examples: E2E testing, documentation, final integration

**Execution:**
```bash
# Only after all parallel streams complete
claude
/continue Stream-Z
# Complete integration tasks
```

**Progress tracking:**
```
Stream-Z (integration) ░░░░░░░░░░░░░░░░░░░░  0.0% (0/5 tasks)
  ⚠ Waiting on: Stream-B, Stream-C, Stream-D
```

**Dependency enforcement:**
Integration streams show waiting status until all dependencies complete:
```
Stream-Z (integration) ████░░░░░░░░░░░░░░░░ 20.0% (1/5 tasks)
  └─ @agent-qa: Running integration tests
```

---

### Execution Flow Diagram

```
START INITIATIVE
       │
       ▼
┌─────────────┐
│ Foundation  │  Stream-A: Core infrastructure (4 tasks)
│   Phase     │  ─────────────────────────────────────
│             │  Runs in: Main worktree
└─────────────┘  Must complete before parallel work
       │
       │ (Wait for 100% completion)
       │
       ▼
┌─────────────┐
│  Parallel   │  Stream-B: Feature A (2 tasks) ┐
│   Phase     │  Stream-C: Feature B (3 tasks) ├─ Max 5 concurrent
│             │  Stream-D: Feature C (5 tasks) ┘
└─────────────┘  ─────────────────────────────
       │         Runs in: Dedicated worktrees
       │         Dependencies: Stream-A
       │
       │ (Wait for all parallel streams 100%)
       │
       ▼
┌─────────────┐
│Integration  │  Stream-Z: Testing + Docs (5 tasks)
│   Phase     │  ─────────────────────────────────────
│             │  Runs in: Main worktree
└─────────────┘  Dependencies: Stream-B, Stream-C, Stream-D
       │
       ▼
  INITIATIVE COMPLETE
```

---

## Usage Guide

### Step-by-Step Workflow

#### 1. Plan Your Initiative

**Define streams in PRD:**
```markdown
# Initiative: Add Dark Mode Support

## Foundation Phase
### Stream-A: Core Theme System
- TASK-001: Create theme type definitions
- TASK-002: Implement theme provider
- TASK-003: Add theme storage service
- TASK-004: Create theme switching API

## Parallel Phase
### Stream-B: UI Component Updates
- TASK-005: Update Button component
- TASK-006: Update Input component
- TASK-007: Update Card component

### Stream-C: Page Theme Integration
- TASK-008: Update Dashboard page
- TASK-009: Update Settings page
- TASK-010: Update Profile page

## Integration Phase
### Stream-Z: Testing and Documentation
- TASK-011: E2E theme switching tests
- TASK-012: Visual regression tests
- TASK-013: Update component documentation
- TASK-014: Update user guide
- TASK-015: Performance testing
```

#### 2. Generate Orchestration Scripts

```bash
# In Claude Code session
/orchestration generate
```

**Output:**
```
✓ Generated orchestration configuration

Files created:
  .claude/orchestration/orchestration-config.json
  .claude/orchestration/start-streams.py
  .claude/orchestration/README.md

Next steps:
1. Review configuration: /orchestration config
2. Start monitoring: python3 .claude/orchestration/watch-status.py
3. Execute streams:
   - Foundation: /continue Stream-A
   - After foundation: /continue Stream-B, /continue Stream-C
   - After parallel: /continue Stream-Z
```

#### 3. Start Real-Time Monitor

```bash
# In separate terminal
cd .claude/orchestration
python3 watch-status.py
```

**Monitor will display:**
```
╔══════════════════════════════════════════════════════════════════╗
║  ORCHESTRATION STATUS               [Refresh: 5s]                ║
╠══════════════════════════════════════════════════════════════════╣
║  Overall: ░░░░░░░░░░░░░░░░░░░░  0.0% (0/15 tasks)                ║
╠══════════════════════════════════════════════════════════════════╣
║  Stream-A (foundation)  ░░░░░░░░░░░░░░░░░░░░  0.0% (0/4 tasks)   ║
║  Stream-B (parallel)    ░░░░░░░░░░░░░░░░░░░░  0.0% (0/3 tasks)   ║
║  Stream-C (parallel)    ░░░░░░░░░░░░░░░░░░░░  0.0% (0/3 tasks)   ║
║  Stream-Z (integration) ░░░░░░░░░░░░░░░░░░░░  0.0% (0/5 tasks)   ║
╚══════════════════════════════════════════════════════════════════╝
```

#### 4. Execute Foundation Stream

```bash
# Terminal 1: Foundation
claude
/continue Stream-A
```

**Claude loads context:**
```
Resuming Stream-A: Core Theme System
Current focus: Implement theme provider
Next task: TASK-002

Loading files:
  - src/types/theme.ts
  - src/services/theme-provider.ts

Dependencies: None (foundation stream)
```

**Work through tasks:**
- TASK-001: Create theme type definitions ✓
- TASK-002: Implement theme provider ✓
- TASK-003: Add theme storage service ✓
- TASK-004: Create theme switching API ✓

**Monitor updates in real-time:**
```
Stream-A (foundation)  █████░░░░░░░░░░░░░░░ 25.0% (1/4 tasks)
  └─ @agent-me: Implementing theme provider

Stream-A (foundation)  ██████████░░░░░░░░░░ 50.0% (2/4 tasks)
  └─ @agent-me: Adding theme storage service

Stream-A (foundation)  ███████████████░░░░░ 75.0% (3/4 tasks)
  └─ @agent-me: Creating theme switching API

Stream-A (foundation)  ████████████████████ 100.0% ✓ COMPLETE
```

#### 5. Start Parallel Streams

**After foundation completes, start parallel work:**

```bash
# Terminal 2: Parallel Stream B
claude
/continue Stream-B

# Terminal 3: Parallel Stream C
claude
/continue Stream-C
```

**Claude creates worktrees automatically:**
```
Creating worktree for Stream-B...
✓ Worktree created: .claude/worktrees/Stream-B
✓ Branch created: stream-b

Resuming Stream-B: UI Component Updates
Current focus: Update Button component
Next task: TASK-005
```

**Work on both streams simultaneously:**
```
Stream-A (foundation)  ████████████████████ 100.0% ✓ COMPLETE
Stream-B (parallel)    ██████████░░░░░░░░░░ 50.0% (1/2 tasks)
  └─ @agent-me: Updating Input component
Stream-C (parallel)    ██████░░░░░░░░░░░░░░ 33.3% (1/3 tasks)
  └─ @agent-me: Updating Dashboard page
```

#### 6. Start Integration Stream

**After all parallel streams complete:**

```bash
# Terminal 4: Integration
claude
/continue Stream-Z
```

**Claude loads integration context:**
```
Resuming Stream-Z: Testing and Documentation
Current focus: E2E theme switching tests
Next task: TASK-011

Parallel streams completed:
  ✓ Stream-B: UI Component Updates
  ✓ Stream-C: Page Theme Integration

Ready for integration work.
```

**Complete integration tasks:**
```
Stream-Z (integration) ████████████████████ 100.0% ✓ COMPLETE
  └─ @agent-qa: Performance testing complete

Overall: ████████████████████ 100.0% (15/15 tasks) ✓ COMPLETE
```

#### 7. Merge and Clean Up

**After all streams complete:**

```bash
# Switch to main branch
git checkout main

# Merge parallel streams
git merge stream-b
git merge stream-c

# Remove worktrees
git worktree remove .claude/worktrees/Stream-B
git worktree remove .claude/worktrees/Stream-C

# Push changes
git push origin main

# Archive completed streams
claude
/protocol
> Call stream_archive({ streamId: "Stream-A" })
> Call stream_archive({ streamId: "Stream-B" })
> Call stream_archive({ streamId: "Stream-C" })
> Call stream_archive({ streamId: "Stream-Z" })
```

---

### Best Practices

#### Stream Design

**✓ DO:**
- Group related tasks into streams
- Keep streams focused on specific areas
- Limit parallel streams to 3-5 for manageability
- Define clear dependencies
- Use descriptive stream names

**✗ DON'T:**
- Mix unrelated tasks in same stream
- Create more than 5 parallel streams
- Create circular dependencies
- Use generic names like "Stream-1"

#### Dependency Management

**Foundation streams should:**
- ✓ Create shared types and interfaces
- ✓ Set up database schemas
- ✓ Implement core APIs
- ✓ Establish architectural patterns

**Parallel streams should:**
- ✓ Be completely independent
- ✓ Work on different files
- ✓ Depend only on foundation
- ✓ Focus on specific features

**Integration streams should:**
- ✓ Run comprehensive tests
- ✓ Update documentation
- ✓ Perform final validation
- ✓ Merge parallel work

#### Task Assignment

**Assign to agents strategically:**
```
Foundation:
- @agent-ta: Architecture decisions
- @agent-me: Core implementation

Parallel:
- @agent-uid: UI components
- @agent-me: API endpoints
- @agent-qa: Test suites

Integration:
- @agent-qa: E2E testing
- @agent-doc: Documentation
```

---

## Troubleshooting

### API Connection Issues

#### Symptom: "Cannot connect to Task Copilot API"

**Possible causes:**
1. HTTP API not enabled
2. Wrong port configured
3. MCP server not running

**Solution:**
```bash
# 1. Check .mcp.json configuration
cat .mcp.json | grep HTTP_API_PORT
# Should show: "HTTP_API_PORT": "9090"

# 2. Verify server is running
curl http://127.0.0.1:9090/health
# Should return: {"status":"ok","timestamp":"..."}

# 3. Check server logs
# Look for: "HTTP server listening on 127.0.0.1:9090"

# 4. Restart MCP server if needed
# Stop Claude Code
# Start Claude Code
# Verify HTTP API started
```

---

### Stream Dependency Errors

#### Symptom: "Stream cannot start - dependencies incomplete"

**Possible causes:**
1. Foundation stream not 100% complete
2. Parallel stream dependencies not met
3. Tasks still in progress

**Solution:**
```bash
# 1. Check stream progress
/orchestration status

# 2. Verify foundation complete
# Foundation streams must show 100% before parallel can start

# 3. Check dependency status
python3 watch-status.py
# Look for "⚠ Waiting on: Stream-X"

# 4. Complete blocking tasks
/continue Stream-A
# Finish all tasks in Stream-A

# 5. Retry starting parallel stream
/continue Stream-B
```

---

### Worktree Errors

#### Symptom: "Worktree already exists" or "Worktree not found"

**Possible causes:**
1. Previous worktree not cleaned up
2. Manual worktree deletion
3. Git state corruption

**Solution:**
```bash
# 1. List existing worktrees
git worktree list

# 2. Remove orphaned worktree
git worktree remove .claude/worktrees/Stream-B --force

# 3. Recreate worktree via /continue
claude
/continue Stream-B
# Will auto-create worktree

# 4. If still fails, prune and retry
git worktree prune
/continue Stream-B
```

---

### Progress Not Updating

#### Symptom: Monitor shows stale progress

**Possible causes:**
1. Task status not updated
2. API caching issue
3. Database lock

**Solution:**
```bash
# 1. Verify task was marked complete
# In Claude session where you completed task
task_update({
  id: "TASK-001",
  status: "completed",
  notes: "Feature implemented"
})

# 2. Force refresh API
curl http://127.0.0.1:9090/api/streams/Stream-A | jq

# 3. Restart monitor
# Press Ctrl+C
python3 watch-status.py

# 4. Check database
# Verify task status in ~/.claude/tasks/task-copilot.db
```

---

### Python Import Errors

#### Symptom: "ModuleNotFoundError: No module named 'requests'"

**Solution:**
```bash
# Install requests library
pip install requests

# Or with Python 3 explicitly
pip3 install requests

# Verify installation
python3 -c "import requests; print(requests.__version__)"
```

---

### Circular Dependency Detected

#### Symptom: "Circular dependency: Stream-A -> Stream-B -> Stream-A"

**Cause:** Stream dependencies form a cycle

**Solution:**
```bash
# 1. Review stream dependencies
/orchestration status

# 2. Identify the cycle
# Example: A depends on B, B depends on C, C depends on A

# 3. Break the cycle by redefining dependencies
# Option A: Make one stream not depend on others (foundation)
# Option B: Merge circular streams into single stream
# Option C: Reorder dependencies to form DAG

# 4. Update PRD with correct dependencies

# 5. Regenerate orchestration
/orchestration generate
```

---

### Max Parallel Limit Exceeded

#### Symptom: "Cannot create more than 5 parallel streams"

**Cause:** Too many parallel streams defined

**Solution:**
```bash
# Option 1: Reduce parallel streams
# Merge related streams together
# Example: Combine Stream-B and Stream-C into single stream

# Option 2: Split into batches
# Run 5 streams first, then run remaining after complete

# Option 3: Convert some to integration phase
# Move less critical streams to integration phase

# 4. Update PRD

# 5. Regenerate orchestration
/orchestration generate
```

---

## Advanced Topics

### Custom Session Management

**Default implementation requires manual session launching. Here's how to automate with iTerm2:**

```python
# In start-streams.py, around line 200
def _start_stream_session(self, stream_id: str, work_dir: str):
    """Launch Claude session in new iTerm2 window."""

    # AppleScript for iTerm2
    script = f'''
    tell application "iTerm"
        create window with default profile
        tell current session of current window
            write text "cd {work_dir}"
            write text "claude"
            delay 2
            write text "/continue {stream_id}"
        end tell
    end tell
    '''

    subprocess.run(['osascript', '-e', script])
    print(f"✓ Launched {stream_id} in new iTerm2 window")
```

**For tmux:**
```python
def _start_stream_session(self, stream_id: str, work_dir: str):
    """Launch Claude session in new tmux window."""

    session_name = f"orchestration-{self.initiative_id[:8]}"

    # Create session if doesn't exist
    subprocess.run([
        'tmux', 'new-session',
        '-d', '-s', session_name
    ])

    # Create new window for stream
    subprocess.run([
        'tmux', 'new-window',
        '-t', session_name,
        '-n', stream_id
    ])

    # Send commands
    subprocess.run([
        'tmux', 'send-keys',
        '-t', f"{session_name}:{stream_id}",
        f"cd {work_dir}", 'C-m'
    ])

    subprocess.run([
        'tmux', 'send-keys',
        '-t', f"{session_name}:{stream_id}",
        "claude", 'C-m'
    ])

    time.sleep(2)

    subprocess.run([
        'tmux', 'send-keys',
        '-t', f"{session_name}:{stream_id}",
        f"/continue {stream_id}", 'C-m'
    ])

    print(f"✓ Launched {stream_id} in tmux window")
```

---

### Webhook Notifications

**Add Slack/Discord notifications when streams complete:**

```python
# In start-streams.py, add notification method
import requests

def _send_webhook_notification(self, message: str, webhook_url: str):
    """Send notification to webhook."""
    try:
        payload = {"text": message}
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠ Webhook notification failed: {e}")

# Call after stream completes
def _monitor_stream(self, stream_id: str, phase: str):
    # ... existing polling logic ...

    if stream_status['progressPercentage'] >= 100:
        message = f"✓ {stream_id} complete! ({phase} phase)"
        webhook_url = os.getenv('ORCHESTRATION_WEBHOOK_URL')
        if webhook_url:
            self._send_webhook_notification(message, webhook_url)
```

**Configure webhook:**
```bash
export ORCHESTRATION_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

---

### Progress Persistence

**Save orchestration state between runs:**

```python
# Add to start-streams.py
import json
from pathlib import Path

class OrchestrationManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.state_file = Path(config_path).parent / "orchestration-state.json"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load saved state if exists."""
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {
            "startedAt": None,
            "completedStreams": [],
            "failedStreams": [],
            "lastUpdate": None
        }

    def _save_state(self):
        """Save current state to disk."""
        self.state["lastUpdate"] = datetime.now().isoformat()
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def _mark_stream_complete(self, stream_id: str):
        """Record stream completion."""
        if stream_id not in self.state["completedStreams"]:
            self.state["completedStreams"].append(stream_id)
            self._save_state()
            print(f"✓ {stream_id} recorded as complete")
```

---

### CI/CD Integration

**Run orchestration in CI pipeline:**

```yaml
# .github/workflows/orchestration.yml
name: Parallel Development

on:
  workflow_dispatch:
    inputs:
      initiative_id:
        description: 'Initiative ID'
        required: true

jobs:
  foundation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Task Copilot
        run: |
          npm install
          npm run build

      - name: Run Foundation Stream
        run: |
          claude /continue Stream-A
          # Poll until complete

  parallel:
    needs: foundation
    runs-on: ubuntu-latest
    strategy:
      matrix:
        stream: [Stream-B, Stream-C]
    steps:
      - uses: actions/checkout@v3

      - name: Run Parallel Stream
        run: |
          claude /continue ${{ matrix.stream }}

  integration:
    needs: parallel
    runs-on: ubuntu-latest
    steps:
      - name: Run Integration Stream
        run: |
          claude /continue Stream-Z
```

---

## API Reference

### REST Endpoints

#### GET /health

**Purpose:** Health check

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-01-08T12:00:00.000Z"
}
```

---

#### GET /api/streams

**Purpose:** List all streams

**Query Parameters:**
- `initiativeId` (optional) - Filter by initiative
- `includeArchived` (optional) - Include archived streams (default: false)

**Response:**
```json
{
  "streams": [
    {
      "streamId": "Stream-A",
      "streamName": "foundation",
      "streamPhase": "foundation",
      "totalTasks": 4,
      "completedTasks": 3,
      "inProgressTasks": 1,
      "blockedTasks": 0,
      "pendingTasks": 0,
      "progressPercentage": 75.0,
      "status": "in_progress",
      "dependencies": [],
      "worktreePath": null,
      "branchName": "main",
      "files": ["src/theme.ts", "src/provider.ts"]
    }
  ],
  "totalStreams": 1
}
```

---

#### GET /api/streams/:streamId

**Purpose:** Get specific stream details

**Path Parameters:**
- `streamId` - Stream identifier (e.g., "Stream-A")

**Query Parameters:**
- `includeArchived` (optional) - Include if archived (default: false)

**Response:**
```json
{
  "streamId": "Stream-A",
  "streamName": "foundation",
  "streamPhase": "foundation",
  "totalTasks": 4,
  "completedTasks": 3,
  "inProgressTasks": 1,
  "progressPercentage": 75.0,
  "status": "in_progress",
  "dependencies": [],
  "worktreePath": null,
  "branchName": "main",
  "tasks": [
    {
      "id": "TASK-001",
      "title": "Create theme types",
      "status": "completed",
      "assignedAgent": "me",
      "createdAt": "2026-01-08T10:00:00.000Z",
      "updatedAt": "2026-01-08T10:30:00.000Z"
    }
  ]
}
```

**Error Response (404):**
```json
{
  "error": "Stream not found",
  "streamId": "Stream-X"
}
```

---

#### GET /api/tasks

**Purpose:** Query tasks with filters

**Query Parameters:**
- `status` (optional) - Filter by status (pending, in_progress, blocked, completed, cancelled)
- `streamId` (optional) - Filter by stream
- `assignedAgent` (optional) - Filter by agent
- `prdId` (optional) - Filter by PRD
- `limit` (optional) - Max results

**Response:**
```json
{
  "tasks": [
    {
      "id": "TASK-001",
      "prdId": "PRD-001",
      "title": "Create theme types",
      "description": "Define TypeScript interfaces",
      "assignedAgent": "me",
      "status": "completed",
      "notes": "Completed successfully",
      "metadata": {
        "streamId": "Stream-A",
        "complexity": "Medium",
        "files": ["src/types/theme.ts"]
      },
      "createdAt": "2026-01-08T10:00:00.000Z",
      "updatedAt": "2026-01-08T10:30:00.000Z"
    }
  ],
  "totalTasks": 1
}
```

---

#### GET /api/activity

**Purpose:** Get current agent activity

**Query Parameters:**
- `streamId` (optional) - Filter by stream
- `active` (optional) - Filter active only (default: true)

**Response:**
```json
{
  "activities": [
    {
      "activityId": "ACT-001",
      "taskId": "TASK-002",
      "taskTitle": "Implement theme provider",
      "agentId": "me",
      "streamId": "Stream-A",
      "streamName": "foundation",
      "phase": "implementation",
      "startedAt": "2026-01-08T11:00:00.000Z",
      "lastHeartbeat": "2026-01-08T11:05:00.000Z",
      "isActive": true,
      "notes": "Implementing theme context provider"
    }
  ],
  "totalActive": 1,
  "totalIdle": 0
}
```

---

### MCP Tools

#### stream_list()

**Purpose:** List all streams (used by /orchestration command)

**Parameters:**
```typescript
{
  initiativeId?: string;      // Optional filter
  includeArchived?: boolean;  // Default: false
}
```

**Returns:**
```typescript
{
  streams: Array<{
    streamId: string;
    streamName: string;
    streamPhase: 'foundation' | 'parallel' | 'integration';
    totalTasks: number;
    completedTasks: number;
    inProgressTasks: number;
    blockedTasks: number;
    pendingTasks: number;
    progressPercentage: number;
    dependencies: string[];
    files: string[];
    worktreePath: string | null;
    branchName: string;
  }>;
}
```

---

#### stream_get()

**Purpose:** Get specific stream details

**Parameters:**
```typescript
{
  streamId: string;           // Required
  includeArchived?: boolean;  // Default: false
}
```

**Returns:**
```typescript
{
  streamId: string;
  streamName: string;
  streamPhase: string;
  tasks: Array<Task>;
  dependencies: string[];
  status: string;
  progressPercentage: number;
  worktreePath: string | null;
  branchName: string;
  archived: boolean;
}
```

---

#### stream_conflict_check()

**Purpose:** Check for file conflicts with other streams

**Parameters:**
```typescript
{
  streamId: string;      // Stream to check
  files: string[];       // Files to check for conflicts
}
```

**Returns:**
```typescript
{
  hasConflicts: boolean;
  conflictingStreams: Array<{
    streamId: string;
    streamName: string;
    conflictingFiles: string[];
  }>;
}
```

---

## Appendix

### File Reference

| File | Size | Purpose |
|------|------|---------|
| `.claude/orchestration/orchestration-config.json` | ~2 KB | Stream configuration |
| `.claude/orchestration/start-streams.py` | ~20 KB | Orchestration script |
| `.claude/orchestration/README.md` | ~8 KB | Usage documentation |
| `.claude/orchestration/watch-status.py` | ~15 KB | Real-time monitor |
| `.claude/worktrees/Stream-X/` | Varies | Parallel stream worktree |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTP_API_HOST` | `127.0.0.1` | API bind address |
| `HTTP_API_PORT` | `9090` | API port |
| `TASK_DB_PATH` | `~/.claude/tasks` | Task database path |
| `WORKSPACE_ID` | (auto) | Workspace identifier |

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-08 | Initial orchestration system release |

---

**Document Version:** 1.0
**Last Updated:** 2026-01-08
**Author:** @agent-qa
**Component:** Task Copilot v1.8.0+
