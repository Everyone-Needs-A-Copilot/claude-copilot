# Task Copilot MCP Server

MCP server providing PRD and task management for Claude Code.

## Features

- **PRD Management**: Create and track Product Requirements Documents
- **Task Hierarchy**: Create tasks and subtasks with full dependency tracking
- **Work Products**: Store agent outputs (designs, implementations, reviews, etc.)
- **Activity Log**: Automatic tracking of all changes
- **Initiative Linking**: Lightweight connection to Memory Copilot initiatives
- **Stream Management** (v1.7+): Independent parallel work streams with file conflict detection
- **Performance Tracking** (v1.6+): Track agent success rates and completion rates by task type/complexity
- **Checkpoint System** (v1.6+): Create recovery points during long-running tasks with auto-expiry
- **Pause/Resume** (v1.8+): Explicit pause checkpoints with extended expiry (7 days) for seamless context switching
- **Validation System** (v1.6+): Validate work products for size, structure, and completeness
- **Token Efficiency** (v1.6+): Enforce character/token limits to prevent context bloat
- **Activation Modes** (v1.8+): Auto-detect execution modes (ultrawork, analyze, quick, thorough) with GSD-inspired constraints
- **Verification Enforcement** (v1.8+): Opt-in blocking of task completion without acceptance criteria and proof
- **Progress Visibility** (v1.8+): ASCII progress bars, milestone tracking, velocity trends with 7d/14d/30d windows

## Installation

```bash
npm install
npm run build
```

## Configuration

Configure in your `.mcp.json`:

```json
{
  "mcpServers": {
    "task-copilot": {
      "command": "node",
      "args": [
        "/path/to/claude-copilot/mcp-servers/task-copilot/dist/index.js"
      ],
      "env": {
        "TASK_DB_PATH": "~/.claude/tasks",
        "WORKSPACE_ID": "optional-explicit-id"
      }
    }
  }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TASK_DB_PATH` | `~/.claude/tasks` | Base storage path |
| `WORKSPACE_ID` | (auto-hash) | Explicit workspace identifier |
| `LOG_LEVEL` | `info` | Logging level (debug, info, warn, error) |

### Workspace ID

By default, each project gets a unique database based on its path hash. Set `WORKSPACE_ID` explicitly to:
- Preserve data when renaming/moving projects
- Share task database across multiple projects
- Use a human-readable identifier

## Database Schema

### Tables

- **initiatives**: Lightweight initiative tracking
- **prds**: Product Requirements Documents
- **tasks**: Tasks and subtasks with status tracking
- **work_products**: Agent outputs and deliverables
- **activity_log**: Audit trail of all changes

### Database Path

`{TASK_DB_PATH}/{workspace_id}/tasks.db`

## Available Tools

### PRD Tools

#### prd_create
Create a new PRD with auto-detection of type and scope lock behavior.

**Input:**
- `title` (string, required): PRD title
- `description` (string): PRD description
- `content` (string, required): Full PRD content
- `metadata` (object): Optional metadata (priority, complexity, tags, scopeLocked)

**Auto-Detection (v1.8+):**
The PRD type is automatically detected from title/description keywords:
- **FEATURE**: "add", "implement", "create", "build" → `scopeLocked: true`
- **EXPERIENCE**: "UI", "UX", "design", "interface", "modal" → `scopeLocked: true`
- **DEFECT**: "fix", "bug", "error", "broken" → `scopeLocked: false`
- **QUESTION**: "how", "what", "why", "explain" → `scopeLocked: false`
- **TECHNICAL**: Default for other cases → `scopeLocked: false`

The detected type is stored in `metadata.prdType` and `metadata.scopeLocked` is set to the default for that type unless explicitly overridden.

**Override Default:**
```typescript
// Force scope to be unlocked even for FEATURE
prd_create({
  title: "Add dark mode support",
  content: "...",
  metadata: { scopeLocked: false }  // Explicit override
})
```

**Output:**
```json
{
  "id": "PRD-xxx",
  "initiativeId": "INIT-xxx",
  "createdAt": "2025-12-29T...",
  "summary": "First 200 chars..."
}
```

#### prd_get
Get PRD by ID.

**Input:**
- `id` (string, required): PRD ID
- `includeContent` (boolean): Include full content (default: false)

**Output:**
```json
{
  "id": "PRD-xxx",
  "initiativeId": "INIT-xxx",
  "title": "...",
  "description": "...",
  "content": "...",
  "metadata": {},
  "taskCount": 10,
  "completedTasks": 5,
  "createdAt": "...",
  "updatedAt": "..."
}
```

#### prd_list
List PRDs for initiative.

**Input:**
- `initiativeId` (string): Filter by initiative ID
- `status` (string): Filter by status (active, archived, cancelled)

**Output:**
```json
[
  {
    "id": "PRD-xxx",
    "title": "...",
    "description": "...",
    "taskCount": 10,
    "completedTasks": 5,
    "progress": "5/10 (50%)"
  }
]
```

### Task Tools

#### task_create
Create task or subtask.

**Input:**
- `title` (string, required): Task title
- `description` (string): Task description
- `prdId` (string): Parent PRD ID (optional)
- `parentId` (string): Parent task ID for subtasks (optional)
- `assignedAgent` (string): Assigned agent name
- `metadata` (object): Optional metadata (complexity, priority, dependencies, acceptanceCriteria, phase, streamId, streamName, streamPhase, files, streamDependencies)

**Output:**
```json
{
  "id": "TASK-xxx",
  "prdId": "PRD-xxx",
  "parentId": null,
  "status": "pending",
  "createdAt": "2025-12-29T..."
}
```

#### task_update
Update task.

**Input:**
- `id` (string, required): Task ID
- `status` (string): New status (pending, in_progress, blocked, completed, cancelled)
- `assignedAgent` (string): New assigned agent
- `notes` (string): Task notes
- `blockedReason` (string): Reason if blocked
- `metadata` (object): Metadata updates (merged)

**Output:**
```json
{
  "id": "TASK-xxx",
  "status": "in_progress",
  "updatedAt": "2025-12-29T..."
}
```

#### task_get
Get task details.

**Input:**
- `id` (string, required): Task ID
- `includeSubtasks` (boolean): Include subtasks (default: false)
- `includeWorkProducts` (boolean): Include work products (default: false)

**Output:**
```json
{
  "id": "TASK-xxx",
  "prdId": "PRD-xxx",
  "parentId": null,
  "title": "...",
  "description": "...",
  "assignedAgent": "me",
  "status": "in_progress",
  "blockedReason": null,
  "notes": "...",
  "metadata": {},
  "createdAt": "...",
  "updatedAt": "...",
  "subtasks": [...],
  "workProducts": [...]
}
```

#### task_list
List tasks with filters.

**Input:**
- `prdId` (string): Filter by PRD ID
- `parentId` (string): Filter by parent task ID
- `status` (string): Filter by status
- `assignedAgent` (string): Filter by assigned agent

**Output:**
```json
[
  {
    "id": "TASK-xxx",
    "title": "...",
    "status": "in_progress",
    "assignedAgent": "me",
    "subtaskCount": 3,
    "completedSubtasks": 1,
    "hasWorkProducts": true
  }
]
```

### Work Product Tools

#### work_product_store
Store agent output.

**Input:**
- `taskId` (string, required): Task ID
- `type` (string, required): Work product type (technical_design, implementation, test_plan, security_review, documentation, architecture, other)
- `title` (string, required): Work product title
- `content` (string, required): Full content
- `metadata` (object): Optional metadata

**Output:**
```json
{
  "id": "WP-xxx",
  "taskId": "TASK-xxx",
  "summary": "First 300 chars...",
  "wordCount": 1500,
  "createdAt": "2025-12-29T..."
}
```

#### work_product_get
Get full work product.

**Input:**
- `id` (string, required): Work product ID

**Output:**
```json
{
  "id": "WP-xxx",
  "taskId": "TASK-xxx",
  "type": "technical_design",
  "title": "...",
  "content": "...",
  "metadata": {},
  "createdAt": "..."
}
```

#### work_product_list
List work products for task.

**Input:**
- `taskId` (string, required): Task ID

**Output:**
```json
[
  {
    "id": "WP-xxx",
    "type": "technical_design",
    "title": "...",
    "summary": "First 300 chars...",
    "wordCount": 1500,
    "createdAt": "..."
  }
]
```

### Initiative Tools

#### initiative_link
Link an initiative from Memory Copilot to Task Copilot.

**Input:**
- `initiativeId` (string, required): Initiative ID from Memory Copilot
- `title` (string, required): Initiative title
- `description` (string): Initiative description

**Output:**
```json
{
  "initiativeId": "INIT-xxx",
  "workspaceCreated": true,
  "dbPath": "~/.claude/tasks/workspace/tasks.db"
}
```

#### initiative_archive
Archive all task data for an initiative to JSON.

**Input:**
- `initiativeId` (string): Initiative ID (default: current)
- `archivePath` (string): Custom archive path (default: ~/.claude/archives/{id}_{timestamp}.json)

**Output:**
```json
{
  "initiativeId": "INIT-xxx",
  "archivePath": "~/.claude/archives/INIT-xxx_20251229.json",
  "prdCount": 3,
  "taskCount": 15,
  "workProductCount": 8,
  "archivedAt": "2025-12-29T..."
}
```

#### initiative_wipe
Delete all task data for an initiative (fresh start).

**Input:**
- `initiativeId` (string): Initiative ID (default: current)
- `confirm` (boolean, required): Must be true to proceed

**Output:**
```json
{
  "initiativeId": "INIT-xxx",
  "deletedPrds": 3,
  "deletedTasks": 15,
  "deletedWorkProducts": 8,
  "deletedActivityLogs": 42
}
```

#### progress_summary
Get high-level progress overview (optimized for minimal context usage).

**Input:**
- `initiativeId` (string): Initiative ID (default: current)

**Output:**
```json
{
  "initiativeId": "INIT-xxx",
  "title": "Framework Improvements",
  "prds": { "total": 3, "active": 2, "completed": 1 },
  "tasks": {
    "total": 15,
    "pending": 5,
    "inProgress": 3,
    "completed": 6,
    "blocked": 1
  },
  "workProducts": {
    "total": 8,
    "byType": {
      "technical_design": 3,
      "implementation": 4,
      "test_plan": 1
    }
  },
  "recentActivity": [
    { "timestamp": "...", "type": "task_updated", "summary": "..." }
  ]
}
```

### Stream Management Tools

Independent work streams enable parallel development by multiple agents/sessions without file conflicts. Streams track which files each task modifies and validate dependencies.

#### stream_list
List all independent work streams in an initiative.

**Input:**
- `initiativeId` (string): Initiative ID (default: current)
- `prdId` (string): Filter by PRD ID

**Output:**
```json
{
  "streams": [
    {
      "streamId": "Stream-A",
      "streamName": "foundation",
      "streamPhase": "foundation",
      "totalTasks": 4,
      "completedTasks": 4,
      "inProgressTasks": 0,
      "blockedTasks": 0,
      "pendingTasks": 0,
      "files": ["src/types.ts", "src/tools/stream.ts"],
      "dependencies": []
    },
    {
      "streamId": "Stream-B",
      "streamName": "command-updates",
      "streamPhase": "parallel",
      "totalTasks": 2,
      "completedTasks": 0,
      "inProgressTasks": 1,
      "blockedTasks": 0,
      "pendingTasks": 1,
      "files": [".claude/commands/protocol.md"],
      "dependencies": ["Stream-A"]
    }
  ]
}
```

#### stream_get
Get detailed information for a specific stream.

**Input:**
- `streamId` (string, required): Stream ID (e.g., "Stream-B")
- `initiativeId` (string): Initiative ID (default: current)

**Output:**
```json
{
  "streamId": "Stream-B",
  "streamName": "command-updates",
  "streamPhase": "parallel",
  "tasks": [
    {
      "id": "TASK-xxx",
      "title": "Update /protocol command",
      "status": "in_progress",
      "assignedAgent": "me"
    }
  ],
  "dependencies": ["Stream-A"],
  "status": "in_progress"
}
```

#### stream_conflict_check
Check if files are already being worked on by other streams to prevent conflicts.

**Input:**
- `files` (string[], required): File paths to check
- `excludeStreamId` (string): Exclude tasks from this stream
- `initiativeId` (string): Initiative ID (default: current)

**Output:**
```json
{
  "hasConflict": true,
  "conflicts": [
    {
      "file": "src/types.ts",
      "streamId": "Stream-A",
      "streamName": "foundation",
      "taskId": "TASK-123",
      "taskTitle": "Add stream metadata types",
      "taskStatus": "in_progress"
    }
  ]
}
```

**Stream Metadata Schema:**

Tasks can include stream metadata for parallel work coordination:

```typescript
metadata: {
  streamId: "Stream-B",              // Auto-generated ID
  streamName: "command-updates",     // Human-readable name
  streamPhase: "parallel",           // foundation | parallel | integration
  files: [                           // Files this task will modify
    ".claude/commands/protocol.md",
    ".claude/commands/continue.md"
  ],
  streamDependencies: ["Stream-A"]   // Must complete before this stream
}
```

**Stream Phases:**

| Phase | When | Dependencies |
|-------|------|--------------|
| `foundation` | First - shared infrastructure | None |
| `parallel` | Independent work streams | Foundation complete |
| `integration` | Combine parallel work | All parallel streams complete |

**Use Cases:**
- Multiple agents working simultaneously in separate Claude Code sessions
- Prevent file conflicts by tracking which files each stream modifies
- Enforce dependency order (foundation → parallel → integration)
- Validate circular dependencies at task creation time

### Activation Modes

Activation modes are auto-detected from task titles/descriptions using keyword matching. They help scope tasks appropriately and enforce GSD-inspired constraints for focused, atomic work.

**Available Modes:**

| Mode | Keywords | Constraints | Use When |
|------|----------|-------------|----------|
| `ultrawork` | ultrawork, atomic, focused | Max 3 subtasks (warns if exceeded) | Atomic, focused work with clear scope |
| `analyze` | analyze, analysis, analyse, investigate, research | None | Investigation or research tasks |
| `quick` | quick, fast, rapid, simple | None | Fast, simple tasks |
| `thorough` | thorough, comprehensive, detailed, in-depth, deep | None | Deep, comprehensive work (no limits) |

**Auto-Detection:**

```javascript
// Keywords in title or description
"Quick fix for login bug"           → mode: 'quick'
"Analyze authentication flow"       → mode: 'analyze'
"Comprehensive security audit"      → mode: 'thorough'
"Use ultrawork for this task"       → mode: 'ultrawork'
"Regular task"                       → mode: null (no keywords)
```

**Explicit Override:**

```javascript
await task_create({
  title: "Quick task",
  metadata: {
    activationMode: 'ultrawork'  // Explicit mode overrides auto-detection
  }
});
```

**Ultrawork Constraint:**

When a task is in `ultrawork` mode, the system warns if it has more than 3 direct subtasks:

```javascript
// Creating 4th subtask triggers warning
const result = await task_create({
  title: "Subtask 4",
  parentId: ultraworkTaskId
});

// result.activationModeWarning:
// ⚠️  ULTRAWORK MODE CONSTRAINT VIOLATED
//
// Task: "Implement authentication"
// Subtasks: 4 (limit: 3)
//
// Ultrawork mode enforces atomic, focused work with max 3 subtasks.
//
// Recommendations:
// 1. Break this task into smaller ultrawork tasks (preferred)
// 2. Change activationMode to "thorough" if complexity justified
// 3. Remove 1 subtask(s) to fit within limit
```

**Why This Matters:**

Tasks with >3 subtasks often indicate scope creep. The ultrawork constraint encourages:
- Smaller, focused tasks
- Faster iteration cycles
- Better focus and clarity
- Higher completion rates

**Changing Modes:**

```javascript
await task_update({
  id: taskId,
  metadata: {
    activationMode: 'thorough'  // Change from ultrawork to allow more subtasks
  }
});
```

### Verification Enforcement

Verification enforcement prevents tasks from being completed without proper success criteria and proof. This is an opt-in feature inspired by GSD methodology.

**Enable Verification:**

```javascript
await task_create({
  title: "Implement authentication endpoint",
  metadata: {
    verificationRequired: true,
    acceptanceCriteria: [
      "Endpoint returns 200 for valid credentials",
      "Endpoint returns 401 for invalid credentials",
      "JWT token is included in response"
    ]
  }
});
```

**Requirements for Completion:**

When `metadata.verificationRequired: true`, the task cannot be completed without:

1. **Acceptance Criteria**: Non-empty array in `metadata.acceptanceCriteria`
2. **Proof** (one of):
   - Work product stored via `work_product_store`
   - Task notes with substantive content (≥50 characters)
   - Blocked reason (if task cannot be completed)

**Validation Errors:**

```javascript
// Attempting to complete without proof
await task_update({
  id: taskId,
  status: 'completed'  // ❌ Rejected
});

// Error returned:
// "Verification failed - task cannot be completed:
//
// [ACCEPTANCE_CRITERIA] Task missing acceptance criteria
//   → Add acceptanceCriteria to task metadata before marking as completed.
//      Example: metadata.acceptanceCriteria = ["Test passes", "Code reviewed"]
//
// [PROOF] Task completion requires proof/evidence
//   → Provide evidence via: (1) work_product_store with implementation/test results,
//      (2) task notes with test output, screenshot paths, or acceptance criteria
//      checklist (min 50 chars), or (3) blocked_reason if task cannot be completed"
```

**Valid Completion:**

```javascript
// Option 1: Store work product
await work_product_store({
  taskId: taskId,
  type: 'implementation',
  title: 'Authentication Endpoint',
  content: '// implementation code...'
});

await task_update({
  id: taskId,
  status: 'completed'  // ✅ Allowed
});

// Option 2: Add detailed notes
await task_update({
  id: taskId,
  status: 'completed',
  notes: `All acceptance criteria verified:
    ✓ Endpoint returns 200 for valid credentials
    ✓ Endpoint returns 401 for invalid credentials
    ✓ JWT token is included in response
    Test output: test/auth.test.ts passed`  // ✅ Allowed (>50 chars)
});

// Option 3: Document blocker
await task_update({
  id: taskId,
  status: 'blocked',
  blockedReason: 'Waiting for external API credentials'  // ✅ Allowed
});
```

**Disabling Verification:**

```javascript
await task_update({
  id: taskId,
  metadata: {
    verificationRequired: false  // Remove enforcement
  }
});
```

### Progress Visibility

Task Copilot provides rich progress tracking with ASCII progress bars, milestone tracking, and velocity trends.

**Progress Summary with Bars:**

```javascript
const summary = await progress_summary({ initiativeId: 'INIT-xxx' });

// Returns:
{
  "initiativeId": "INIT-xxx",
  "title": "Framework Improvements",
  "progressBar": "[████████████░░░░░░░░] 60% (12/20)",
  "prds": { "total": 3, "active": 2, "completed": 1 },
  "tasks": {
    "total": 20,
    "pending": 5,
    "inProgress": 3,
    "completed": 12,
    "blocked": 0
  },
  "milestones": [
    {
      "id": "milestone-1",
      "name": "Core Infrastructure",
      "totalTasks": 8,
      "completedTasks": 8,
      "percentComplete": 100
    }
  ],
  "velocity": [
    { "period": "7d", "completed": 5, "trend": "↗" },
    { "period": "14d", "completed": 9, "trend": "→" },
    { "period": "30d", "completed": 12, "trend": "↘" }
  ]
}
```

**Milestone Tracking in PRDs:**

```javascript
await prd_create({
  title: "User Authentication",
  content: "PRD content...",
  metadata: {
    milestones: [
      {
        id: "auth-phase-1",
        name: "Basic Auth",
        description: "Email/password authentication",
        taskIds: ["TASK-001", "TASK-002", "TASK-003"]
      },
      {
        id: "auth-phase-2",
        name: "OAuth Integration",
        description: "Google and GitHub OAuth",
        taskIds: ["TASK-004", "TASK-005"]
      }
    ]
  }
});
```

**Velocity Trends:**

Velocity is automatically calculated over three time windows:
- **7d**: Last 7 days of completed tasks
- **14d**: Last 14 days of completed tasks
- **30d**: Last 30 days of completed tasks

Trend indicators:
- `↗` Improving: +10% or more vs previous period
- `→` Stable: Within ±10% of previous period
- `↘` Declining: -10% or more vs previous period

**ASCII Progress Bar Rendering:**

```javascript
import { renderProgressBar } from './utils/progress-bar';

// Single progress bar
const bar = renderProgressBar(8, 20);
// "[████████░░░░░░░░░░░░] 40% (8/20)"

// Multiple aligned bars
const bars = renderMultiProgressBars([
  { label: 'Frontend', completed: 5, total: 10 },
  { label: 'Backend', completed: 8, total: 10 },
  { label: 'Tests', completed: 12, total: 15 }
]);
// "Frontend: [██████████░░░░░░░░░░] 50% (5/10)
//  Backend:  [████████████████░░░░] 80% (8/10)
//  Tests:    [████████████████░░░░] 80% (12/15)"
```

### Performance Tracking Tools

#### agent_performance_get
Get agent performance metrics including success rates and completion rates by task type and complexity.

**Input:**
- `agentId` (string): Filter by agent ID (me, ta, qa, sec, doc, do, sd, uxd, uids, uid, cw)
- `workProductType` (string): Filter by work product type
- `complexity` (string): Filter by complexity (low, medium, high, very_high)
- `sinceDays` (number): Only include last N days (default: all)

**Output:**
```json
{
  "agents": [
    {
      "agentId": "me",
      "metrics": {
        "total": 25,
        "success": 20,
        "failure": 2,
        "blocked": 1,
        "reassigned": 2,
        "successRate": 0.8,
        "completionRate": 0.87
      },
      "byType": {
        "implementation": { "total": 15, "successRate": 0.87 },
        "technical_design": { "total": 10, "successRate": 0.7 }
      },
      "byComplexity": {
        "medium": { "total": 12, "successRate": 0.92 },
        "high": { "total": 13, "successRate": 0.69 }
      },
      "recentTrend": "improving"
    }
  ],
  "summary": {
    "totalRecords": 150,
    "periodStart": "2025-11-01T...",
    "periodEnd": "2025-12-30T..."
  }
}
```

**Use Cases:**
- Identify which agents excel at specific task types
- Track improvement or regression over time
- Make informed decisions about task assignment
- Detect patterns in blocked or failed tasks

### Checkpoint System Tools

Checkpoints enable mid-task recovery by creating snapshots of task state, execution progress, and draft work.

#### checkpoint_create
Create a checkpoint for mid-task recovery. Use before risky operations or after completing significant steps.

**Input:**
- `taskId` (string, required): Task ID to checkpoint
- `trigger` (string): Checkpoint trigger type (auto_status, auto_subtask, manual, error) - default: manual
- `executionPhase` (string): Current phase (e.g., "analysis", "implementation")
- `executionStep` (number): Step number within phase
- `agentContext` (object): Agent-specific state to preserve
- `draftContent` (string): Partial work in progress (max 50KB, auto-truncated)
- `draftType` (string): Type of draft content
- `expiresIn` (number): Minutes until checkpoint expires (default: 1440 = 24h for auto, 10080 = 7d for manual)

**Output:**
```json
{
  "id": "CP-xxx",
  "taskId": "TASK-xxx",
  "sequence": 3,
  "trigger": "manual",
  "createdAt": "2025-12-30T...",
  "expiresAt": "2026-01-06T..."
}
```

**Auto-Cleanup:**
- Max 5 checkpoints per task (oldest pruned automatically)
- Expired checkpoints cleaned on server startup
- Manual checkpoints live 7 days, auto checkpoints 24 hours

**Pause/Resume Integration:**

Manual checkpoints with specific metadata are used by `/pause` and `/continue` commands:

```javascript
// Created by /pause command
await checkpoint_create({
  taskId: task.id,
  trigger: 'manual',
  executionPhase: 'paused',
  agentContext: {
    pauseReason: 'Switching to urgent bug',
    pausedBy: 'user',
    pausedAt: new Date().toISOString()
  },
  expiresIn: 10080  // Extended 7-day expiry for manual pauses
});
```

The `/continue` command checks for pause checkpoints BEFORE loading standard initiative context, allowing seamless resume of paused work even after switching initiatives.

#### checkpoint_resume
Resume task from last checkpoint. Returns state and context for continuing work.

**Input:**
- `taskId` (string, required): Task ID to resume
- `checkpointId` (string): Specific checkpoint ID (default: latest non-expired)

**Output:**
```json
{
  "taskId": "TASK-xxx",
  "taskTitle": "Implement user authentication",
  "checkpointId": "CP-xxx",
  "checkpointCreatedAt": "2025-12-30T...",
  "restoredStatus": "in_progress",
  "restoredPhase": "implementation",
  "restoredStep": 3,
  "agentContext": { "filesModified": ["auth.ts", "login.tsx"] },
  "hasDraft": true,
  "draftType": "implementation",
  "draftPreview": "# Authentication Implementation\n\nCompleted:\n- User model\n- Login endpoint...",
  "subtaskSummary": {
    "total": 5,
    "completed": 2,
    "pending": 2,
    "blocked": 1
  },
  "resumeInstructions": "Resuming task: \"Implement user authentication\"\n..."
}
```

#### checkpoint_get
Get a specific checkpoint by ID with full details.

**Input:**
- `id` (string, required): Checkpoint ID

**Output:**
Full checkpoint details including task metadata, execution state, draft content, and subtask states.

#### checkpoint_list
List available checkpoints for a task.

**Input:**
- `taskId` (string, required): Task ID
- `limit` (number): Max results (default: 5)

**Output:**
```json
{
  "taskId": "TASK-xxx",
  "checkpoints": [
    {
      "id": "CP-xxx",
      "sequence": 3,
      "trigger": "manual",
      "phase": "implementation",
      "step": 3,
      "hasDraft": true,
      "createdAt": "2025-12-30T...",
      "expiresAt": "2026-01-06T..."
    }
  ]
}
```

#### checkpoint_cleanup
Clean up old or expired checkpoints.

**Input:**
- `taskId` (string): Clean specific task (omit for all tasks)
- `olderThan` (number): Remove checkpoints older than N minutes
- `keepLatest` (number): Keep N most recent per task (default: 3)

**Output:**
```json
{
  "deletedCount": 12,
  "remainingCount": 8
}
```

### Validation System Tools

The validation system checks work products before storage to prevent low-quality outputs from propagating.

#### validation_config_get
Get current validation configuration.

**Output:**
```json
{
  "version": "1.0",
  "defaultMode": "warn",
  "globalRulesCount": 2,
  "typeRules": {
    "architecture": 2,
    "technical_design": 2,
    "implementation": 2,
    "test_plan": 2,
    "security_review": 2,
    "documentation": 2,
    "other": 1
  }
}
```

#### validation_rules_list
List validation rules for a work product type.

**Input:**
- `type` (string): Work product type (omit for global rules)

**Output:**
```json
{
  "type": "implementation",
  "rules": [
    {
      "id": "impl-code-blocks",
      "name": "Implementation Has Code",
      "description": "Implementation should include code",
      "type": "completeness",
      "severity": "warn",
      "enabled": true
    },
    {
      "id": "impl-size",
      "name": "Implementation Size",
      "description": "Implementation notes should be concise",
      "type": "size",
      "severity": "warn",
      "enabled": true
    }
  ]
}
```

**Validation Rule Types:**

| Rule Type | Checks |
|-----------|--------|
| `size` | Character/token limits (min/max) |
| `structure` | Required sections, required/forbidden patterns |
| `completeness` | Minimum sections, code blocks, tables, conclusion |

**Default Limits:**

| Work Product Type | Max Characters | Max Tokens (est) | Special Requirements |
|-------------------|----------------|------------------|---------------------|
| Global | 50,000 | ~12,500 | Has heading |
| Architecture | 30,000 | ~7,500 | Overview, Components sections |
| Technical Design | 25,000 | ~6,250 | Min 3 sections |
| Implementation | 20,000 | ~5,000 | Min 1 code block |
| Test Plan | - | - | Min 1 table, Scope/Test sections |
| Security Review | - | - | Finding/Summary sections, min 1 table |
| Documentation | 30,000 | ~7,500 | Min 1 code block |

**Validation Modes:**
- `warn`: Flag issues but allow storage (default)
- `reject`: Prevent storage if validation fails
- `skip`: Disable validation entirely

### Utility Tools

#### health_check
Get server health and statistics.

**Output:**
```json
{
  "status": "healthy",
  "workspaceId": "abc123",
  "prdCount": 5,
  "taskCount": 42,
  "completedTasks": 20,
  "workProductCount": 15
}
```

## Usage Example

```javascript
// Create a PRD
const prd = await prdCreate({
  title: "User Authentication Feature",
  description: "Add OAuth2 authentication",
  content: "# PRD: User Authentication...",
  metadata: {
    priority: "P0",
    complexity: "High",
    tags: ["auth", "security"]
  }
});

// Create tasks
const task1 = await taskCreate({
  title: "Design authentication flow",
  prdId: prd.id,
  assignedAgent: "ta",
  metadata: {
    phase: "Phase 1",
    complexity: "Medium"
  }
});

// Update task status
await taskUpdate({
  id: task1.id,
  status: "in_progress",
  notes: "Working on OAuth2 provider integration"
});

// Store work product
await workProductStore({
  taskId: task1.id,
  type: "technical_design",
  title: "OAuth2 Authentication Design",
  content: "# Technical Design\n\n..."
});

// List tasks for PRD
const tasks = await taskList({
  prdId: prd.id,
  status: "in_progress"
});
```

## Token Efficiency Enforcement (v1.6+)

Task Copilot enforces token efficiency through its validation system to prevent context bloat:

### How It Works

1. **Pre-Storage Validation**: All work products are validated before storage using `work_product_store`
2. **Size Limits**: Character and token count limits prevent oversized outputs
3. **Structure Checks**: Required sections ensure completeness without verbosity
4. **Quality Gates**: Type-specific rules ensure outputs meet minimum standards

### Benefits

- **96% Context Reduction**: Agents store detailed work in Task Copilot, returning only summaries
- **Automatic Enforcement**: No manual checking needed - validation runs automatically
- **Actionable Feedback**: When validation fails, agents receive specific suggestions
- **Configurable**: Adjust limits and rules via validation config

### Example Workflow

```javascript
// Agent creates detailed work product
const content = generateImplementation(); // 15,000 characters

// Validation runs automatically on storage
const result = await workProductStore({
  taskId: 'TASK-xxx',
  type: 'implementation',
  title: 'User Authentication',
  content: content
});

// If oversized, validation warns but allows (in 'warn' mode)
// Agent receives feedback and can optionally split into smaller products
```

### Main Session vs Agent Output

| Session Type | Expected Tokens | Enforced By |
|--------------|----------------|-------------|
| Main Session | ~500 per task | Protocol guardrails (CLAUDE.md) |
| Agent Work Products | ~5,000-12,500 | Validation system (automatic) |
| Full Initiative | ~2,000 main + unlimited stored | Task Copilot storage |

## Integration with Memory Copilot

Task Copilot maintains lightweight initiative records but does not duplicate Memory Copilot's functionality. Use both together:

- **Memory Copilot**: Session memory, decisions, lessons, context
- **Task Copilot**: PRDs, task tracking, work products

## Development

```bash
# Install dependencies
npm install

# Build
npm run build

# Development mode (watch)
npm run dev

# Start server
npm start
```

### Testing

```bash
# Run all tests
npm test

# Run specific test suites
npm run test:full              # Full integration tests
npm run test:integration       # Iteration system tests
npm run test:progress          # Progress visibility tests
npm run test:pause-resume      # Pause/resume checkpoint tests
npm run test:activation-mode   # Activation mode validation tests
```

## License

MIT
