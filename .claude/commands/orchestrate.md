---
name: orchestrate
description: Set up and manage parallel stream orchestration for Task Copilot
alwaysAllow: true
---

# Orchestrate Command

This command helps set up and run the orchestration system for parallel Claude Code workers.

## Usage

```
/orchestrate generate  # Create PRD and tasks with stream metadata (REQUIRED FIRST)
/orchestrate start     # Set up (if needed) and start orchestration
/orchestrate status    # Check status of all streams
/orchestrate stop      # Stop all running workers
```

## What This Does

### `/orchestrate generate` (REQUIRED FIRST)

**Purpose:** Create PRD and tasks with proper stream metadata for orchestration.

**This command MUST be run before `/orchestrate start`.**

**Workflow:**

1. **Invoke @agent-ta** with the feature/initiative description
2. **@agent-ta creates:**
   - PRD using `prd_create()` in Task Copilot
   - Tasks using `task_create()` with required stream metadata:
     ```json
     {
       "metadata": {
         "streamId": "Stream-A",
         "streamName": "Foundation Work",
         "streamPhase": "foundation|parallel|integration",
         "files": ["list", "of", "files"],
         "dependencies": ["Stream-X", "Stream-Y"]
       }
     }
     ```
3. **Validate stream metadata:**
   - All tasks have `streamId`
   - All tasks have `dependencies` (empty `[]` for foundation)
   - At least one foundation stream exists (no dependencies)
   - No circular dependencies
4. **Display dependency structure:**
   ```
   Stream Dependency Structure:

     Depth 0 (Independent):
       • Stream-A (Foundation)

     Depth 1:
       • Stream-B (Auth API) → depends on: Stream-A
       • Stream-C (User API) → depends on: Stream-A

     Depth 2:
       • Stream-Z (Integration) → depends on: Stream-B, Stream-C
   ```
5. **Return next step:** "Run `/orchestrate start` to begin execution"

**Usage:**
```
User: /orchestrate generate
Assistant: I'll invoke @agent-ta to create PRDs and tasks with stream metadata.
           What feature or initiative should I plan for orchestration?

User: Implement user authentication with OAuth
Assistant: [Invokes @agent-ta to create PRD and tasks]

           PRD Created: PRD-abc123
           Tasks Created: 12 tasks across 4 streams

           Stream Structure:
             Stream-A (Foundation): 3 tasks - DB migrations, types
             Stream-B (OAuth Provider): 4 tasks - depends on Stream-A
             Stream-C (Session Management): 3 tasks - depends on Stream-A
             Stream-Z (Integration): 2 tasks - depends on Stream-B, Stream-C

           Next: Run `/orchestrate start` to begin parallel execution
```

**Implementation:**

When user runs `/orchestrate generate`:

1. **Prompt for feature name** if not provided as argument
2. **Call initiative_link()** to establish current initiative and trigger archival of old streams:
   ```typescript
   // Link current Memory Copilot initiative to Task Copilot
   const initiative = await initiative_get();  // From Memory Copilot
   if (!initiative?.id) {
     console.error("ERROR: No active initiative found.");
     console.error("Run '/protocol' first to start a new initiative.");
     return;
   }
   await initiative_link({
     initiativeId: initiative.id,
     title: initiative.name
   });
   // This archives any streams from previous initiatives
   ```
3. **Invoke @agent-ta** with this prompt:
   ```
   Create a PRD and task breakdown for parallel orchestration.

   Feature: {feature_description}

   MANDATORY REQUIREMENTS:
   1. Call prd_create() to create PRD in Task Copilot
   2. Design stream structure:
      - Foundation streams (shared dependencies, no deps)
      - Parallel streams (independent work, depend on foundation)
      - Integration streams (combines parallel work)
   3. For EACH task, call task_create() with metadata:
      {
        "prdId": "PRD-xxx",
        "title": "Task title",
        "description": "Task description",
        "assignedAgent": "me|qa|doc|etc",
        "metadata": {
          "streamId": "Stream-X",
          "streamName": "Human Readable Name",
          "files": ["list", "of", "files", "this", "stream", "modifies"],
          "dependencies": ["Stream-A", "Stream-B"]  // empty [] for foundation
        }
      }
   4. After creating all tasks, validate:
      - Every task has streamId
      - At least one stream has empty dependencies
      - No circular dependencies
   5. Display dependency structure visualization
   6. Return "Ready for /orchestrate start"
   ```
4. **POST-INVOCATION VERIFICATION (CRITICAL)**
   After @agent-ta returns, ALWAYS verify PRDs and streams were actually created:
   ```typescript
   // Verify PRD creation
   const prds = await prd_list({ initiativeId: initiative.id });
   const prdCount = prds?.length || 0;

   // Verify stream creation
   const streams = await stream_list({ initiativeId: initiative.id });
   const streamCount = streams?.length || 0;

   if (prdCount === 0 || streamCount === 0) {
     // VERIFICATION FAILED - @agent-ta did not use Task Copilot tools
     console.error("ERROR: Verification Failed");
     console.error("");
     console.error("@agent-ta did not properly create PRD/tasks in Task Copilot:");
     console.error(`  - PRDs created: ${prdCount} (expected: >= 1)`);
     console.error(`  - Streams created: ${streamCount} (expected: >= 1)`);
     console.error("");
     console.error("The agent may have output a plan but failed to call:");
     console.error("  - prd_create() to create the PRD");
     console.error("  - task_create() to create tasks with streamId metadata");
     console.error("");

     // Offer retry with stronger enforcement
     const retry = await askUser("Would you like to retry with stronger enforcement?");
     if (retry) {
       // Re-invoke with EXPLICIT tool enforcement
       // (See retry prompt below)
     }
     return;
   }
   ```

5. **IF VERIFICATION FAILS - Retry with stronger enforcement prompt:**
   ```
   CRITICAL FAILURE RECOVERY - You MUST use Task Copilot tools.

   Your previous response did NOT create PRDs or tasks in Task Copilot.

   ## MANDATORY TOOL CALLS

   You MUST call these tools in this exact order:

   1. FIRST: Call prd_create() to create the PRD
      prd_create({
        title: "Feature Title",
        content: "PRD content...",
        description: "Brief description"
      })

   2. THEN: For EACH task, call task_create() with stream metadata
      task_create({
        prdId: "PRD-xxx",  // From step 1
        title: "Task title",
        description: "Task description",
        assignedAgent: "me",
        metadata: {
          streamId: "Stream-A",
          streamName: "Stream Name",
          dependencies: []  // Empty for foundation, or ["Stream-A"] for dependent
        }
      })

   ## VERIFICATION

   After creating all tasks, call:
   - prd_list() - should show your PRD
   - stream_list() - should show your streams

   ## FAILURE IS NOT AN OPTION

   DO NOT output a markdown plan.
   DO NOT skip the tool calls.
   DO NOT claim completion without tool calls.

   The orchestration system REQUIRES PRDs and tasks in Task Copilot.

   Feature: {feature_description}
   ```

6. **Validate @agent-ta created proper metadata** - if validation fails, report errors
7. **Display success message** with stream structure and next steps

---

### `/orchestrate start`

**Single command that handles everything:**

**Pre-flight Validation (ALWAYS runs first):**

Before setting up or starting orchestration, validate Task Copilot has proper stream data:

1. **Check streams exist** - Query Task Copilot for tasks with `metadata.streamId`
2. **Check foundation exists** - At least one stream must have `dependencies: []`
3. **Check no circular deps** - Dependency graph must be acyclic

**If validation fails:**
```
ERROR: No streams found in Task Copilot

Tasks must include stream metadata for orchestration:
  {
    "metadata": {
      "streamId": "Stream-A",
      "streamName": "Description",
      "dependencies": []
    }
  }

Run `/orchestrate generate` first to create PRD and tasks with stream metadata.
```

---

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

1. **Run `/orchestrate generate` first**: This creates PRD and tasks with proper stream metadata:
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

## Workflow

The correct workflow for orchestration is:

```
1. /orchestrate generate    ← Creates PRD + tasks with stream metadata
2. /orchestrate start       ← Spawns parallel workers
3. ./watch-status           ← Monitor progress
4. /orchestrate stop        ← (if needed) Stop workers
```

**Do NOT run `/orchestrate start` without first running `/orchestrate generate`.**

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
- **Most common cause:** You ran `/orchestrate start` before `/orchestrate generate`
- **Solution:** Run `/orchestrate generate` first to create PRD and tasks with stream metadata
- Also check: Tasks are not archived (`archived = 0`)

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

1. **Validate command** - Must be `generate`, `start`, `status`, or `stop`

2. **For `generate`:**
   - **Prompt for feature** if not provided as argument
   - **FIRST: Call initiative_link()** to establish current initiative:
     - Get current initiative from Memory Copilot via `initiative_get()`
     - If no initiative: ERROR - "Run /protocol first to start an initiative"
     - Call `initiative_link()` with initiativeId and title
     - This automatically archives streams from previous initiatives
   - **Invoke @agent-ta** with orchestration generation prompt (see `/orchestrate generate` section above)
   - **Wait for @agent-ta** to create PRD and tasks in Task Copilot
   - **POST-INVOCATION VERIFICATION (CRITICAL):**
     - Call `prd_list({ initiativeId: initiative.id })` to get PRD count
     - Call `stream_list({ initiativeId: initiative.id })` to get stream count
     - If PRD count == 0 OR stream count == 0:
       - Display ERROR: "@agent-ta did not properly create PRD/tasks"
       - Show: "PRDs created: X (expected >= 1)"
       - Show: "Streams created: Y (expected >= 1)"
       - Explain: "Agent may have output plan but failed to call prd_create()/task_create()"
       - **Offer retry with stronger enforcement prompt**
       - If user accepts retry: Re-invoke @agent-ta with failure recovery prompt
   - **Validate creation:**
     - Query Task Copilot for tasks with `metadata.streamId`
     - Verify at least one stream has `dependencies: []`
     - Verify no circular dependencies
   - **Display results:**
     - PRD ID created
     - Number of streams and tasks
     - Dependency structure visualization
     - Next step: "Run `/orchestrate start` to begin execution"

3. **For `start`:**
   - **Pre-flight Validation (REQUIRED):**
     - Query Task Copilot for tasks with `metadata.streamId`
     - **If no streams found:** ERROR - direct user to run `/orchestrate generate` first
     - Verify at least one foundation stream exists (empty dependencies)
     - Verify no circular dependencies in graph
   - **Setup Phase:**
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
     - Display dependency structure before starting
     - Run `python .claude/orchestrator/orchestrate.py start`
     - Show output in real-time

4. **For `status` and `stop`:**
   - Run `python .claude/orchestrator/orchestrate.py [command]`
   - Show output in real-time
