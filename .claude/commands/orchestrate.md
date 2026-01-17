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

**Purpose:** Create specifications, PRD, and tasks with proper stream metadata for orchestration.

**This command MUST be run before `/orchestrate start`.**

**Two Modes:**
- **Experience-First (default):** Domain agents create specifications → TA creates tasks from specs
- **Technical-Only (`--technical`):** TA creates tasks directly (for refactoring, optimization, etc.)

**Workflow (Experience-First - Default):**

```
1. @agent-sd → Service Design Specification (WP-xxx)
2. @agent-uxd → UX Design Specification (WP-yyy)
3. @agent-uids → UI Design Specification (WP-zzz)
4. @agent-ta → PRD + Tasks with sourceSpecifications traceability
```

**Workflow (Technical-Only):**

```
1. @agent-ta → PRD + Tasks directly (no specifications)
```

**Usage:**
```
User: /orchestrate generate
Assistant: What feature or initiative should I plan for orchestration?

User: Implement user voice profiles
Assistant: [Detects: Experience-first flow - user-facing feature]

           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           Stage 1/4: Service Design (@agent-sd)
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           [Invokes @agent-sd to create service design specification]

           Specification Created: WP-001
           Service: User Voice Profiles
           Journey: Discovery → Setup → Usage → Management
           Pain Points: Profile creation friction, unclear value

           Proceed to UX Design? [y/n/skip]

User: y
Assistant: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           Stage 2/4: UX Design (@agent-uxd)
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           [Invokes @agent-uxd to create UX specification]

           Specification Created: WP-002
           Interactions: 8 states designed
           Key Flows: First-time setup (3 steps), Quick record
           Accessibility: WCAG 2.1 AA, keyboard navigation

           Proceed to Visual Design? [y/n/skip]

User: y
Assistant: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           Stage 3/4: UI Design (@agent-uids)
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           [Invokes @agent-uids to create visual design specification]

           Specification Created: WP-003
           Design Tokens: 12 color, 6 spacing, 4 typography
           Components: VoiceProfileCard, RecordButton, WaveformVisualizer

           Proceed to Technical Architecture? [y/n]

User: y
Assistant: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           Stage 4/4: Technical Architecture (@agent-ta)
           ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
           [Invokes @agent-ta with specification IDs]

           PRD Created: PRD-abc123
           Tasks Created: 12 tasks across 4 streams
           Source Specifications: WP-001, WP-002, WP-003

           Stream Structure:
             Stream-A (Foundation): 3 tasks - DB migrations, types
             Stream-B (Backend API): 4 tasks - depends on Stream-A
             Stream-C (Frontend UI): 3 tasks - depends on Stream-A
             Stream-Z (Integration): 2 tasks - depends on Stream-B, Stream-C

           Next: Run `/orchestrate start` to begin parallel execution
```

**Technical-Only Usage:**
```
User: /orchestrate generate --technical
Assistant: What technical work should I plan for orchestration?

User: Refactor authentication to use JWT
Assistant: [Invokes @agent-ta directly - no specification stages]

           PRD Created: PRD-def456
           Tasks Created: 8 tasks across 3 streams
           ...
```

**Implementation:**

When user runs `/orchestrate generate [--technical] [description]`:

1. **Parse arguments:**
   - Check for `--technical` flag
   - Extract feature description if provided

2. **Prompt for feature name** if not provided as argument

3. **Link to Memory Copilot initiative (REQUIRED FIRST):**
   - Call `initiative_link({ initiativeId, title, description })` to:
     - Establish current initiative in Task Copilot
     - Auto-archive old streams from previous initiatives (clean slate)
     - Prevent stream pollution from prior work
   - If initiative not found, return error asking user to start initiative in Memory Copilot first

4. **Detect workflow mode:**
   - If `--technical` flag: Use Technical-Only workflow (skip to step 8)
   - If feature contains technical keywords (refactor, optimize, migrate, performance):
     Ask user to confirm: "This sounds technical. Use technical-only flow? [y/n]"
   - Default: Use Experience-First workflow

**Experience-First Workflow (Steps 5-7):**

5. **Stage 1: Service Design (@agent-sd)**

   Invoke @agent-sd with this prompt:
   ```
   Create a Service Design Specification for orchestration planning.

   Feature: {feature_description}

   REQUIREMENTS:
   1. Map the complete user journey for this feature
   2. Identify all touchpoints (frontstage and backstage)
   3. Document pain points and opportunities
   4. Store specification using work_product_store():
      {
        taskId: "planning-task",
        type: "specification",
        title: "Service Design Specification: {feature}",
        content: "<full service blueprint>"
      }
   5. Return summary (~100 tokens) with WP-xxx ID
   ```

   After @agent-sd returns:
   - Extract WP-xxx ID from response
   - Display checkpoint summary
   - Ask: "Proceed to UX Design? [y/n/skip]"
   - If "skip": Jump to step 8 (TA) with collected specs
   - If "n": Allow user to provide feedback, re-invoke @agent-sd

6. **Stage 2: UX Design (@agent-uxd)**

   Invoke @agent-uxd with this prompt:
   ```
   Create a UX Design Specification based on the service design.

   Feature: {feature_description}
   Service Design Spec: {WP-xxx from step 5}

   REQUIREMENTS:
   1. Read the service design specification for context
   2. Design all interaction states (default, hover, focus, error, loading, empty)
   3. Define task flows with all paths (primary, alternative, error recovery)
   4. Specify accessibility requirements (WCAG 2.1 AA)
   5. Store specification using work_product_store():
      {
        taskId: "planning-task",
        type: "specification",
        title: "UX Design Specification: {feature}",
        content: "<full interaction design>"
      }
   6. Return summary (~100 tokens) with WP-xxx ID
   ```

   After @agent-uxd returns:
   - Extract WP-xxx ID from response
   - Display checkpoint summary
   - Ask: "Proceed to Visual Design? [y/n/skip]"
   - If "skip": Jump to step 8 (TA) with collected specs
   - If "n": Allow user to provide feedback, re-invoke @agent-uxd

7. **Stage 3: UI Design (@agent-uids)**

   Invoke @agent-uids with this prompt:
   ```
   Create a UI Design Specification based on the UX design.

   Feature: {feature_description}
   Service Design Spec: {WP-xxx from step 5}
   UX Design Spec: {WP-yyy from step 6}

   REQUIREMENTS:
   1. Read prior specifications for context
   2. Define design tokens (colors, spacing, typography)
   3. Specify component designs with all visual states
   4. Include micro-interactions and transitions
   5. Store specification using work_product_store():
      {
        taskId: "planning-task",
        type: "specification",
        title: "UI Design Specification: {feature}",
        content: "<full visual design>"
      }
   6. Return summary (~100 tokens) with WP-xxx ID
   ```

   After @agent-uids returns:
   - Extract WP-xxx ID from response
   - Display checkpoint summary
   - Ask: "Proceed to Technical Architecture? [y/n]"
   - If "n": Allow user to provide feedback, re-invoke @agent-uids

8. **Stage 4: Technical Architecture (@agent-ta)**

   Invoke @agent-ta with this prompt:
   ```
   Create a PRD and task breakdown for parallel orchestration.

   Feature: {feature_description}

   SOURCE SPECIFICATIONS (READ THESE FIRST):
   {list of WP-xxx IDs from steps 5-7, or "None - technical-only flow"}

   MANDATORY REQUIREMENTS:
   1. If specifications provided:
      - Call work_product_get() for each specification ID
      - Read and understand all domain requirements
      - Consolidate requirements into implementation tasks
   2. Call prd_create() to create PRD in Task Copilot
   3. Design stream structure:
      - Foundation streams (shared dependencies, no deps)
      - Parallel streams (independent work, depend on foundation)
      - Integration streams (combines parallel work)
   4. For EACH task, call task_create() with metadata:
      {
        "prdId": "PRD-xxx",
        "title": "Task title",
        "description": "Task description with requirements from specs",
        "assignedAgent": "me|qa|doc|etc",
        "metadata": {
          "streamId": "Stream-X",
          "streamName": "Human Readable Name",
          "streamPhase": "foundation|parallel|integration",
          "files": ["list", "of", "files", "this", "stream", "modifies"],
          "dependencies": ["Stream-A", "Stream-B"],
          "sourceSpecifications": ["WP-xxx", "WP-yyy", "WP-zzz"]
        }
      }
   5. After creating all tasks, validate:
      - Every task has streamId
      - At least one stream has empty dependencies
      - No circular dependencies
      - Tasks reference source specifications (if provided)
   6. Display dependency structure visualization
   7. Return "Ready for /orchestrate start"
   ```

9. **VERIFY Task Copilot State (MANDATORY - DO NOT SKIP):**

   After @agent-ta returns, you MUST verify that tools were actually called:

   a. **Check PRDs exist:**
      ```
      Call: prd_list({})
      Expected: At least 1 PRD returned
      ```

   b. **Check streams exist:**
      ```
      Call: stream_list({})
      Expected: At least 1 stream returned
      ```

   c. **If EITHER check returns empty:**

      Display error and STOP:
      ```
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ❌ ERROR: Verification Failed
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

      @agent-ta did not properly use Task Copilot tools.

      Verification Results:
        • PRDs found: {count}
        • Streams found: {count}

      The agent may have:
        • Output a planning document instead of calling tools
        • Skipped prd_create() or task_create() calls
        • Failed to include metadata.streamId in tasks
        • Created content but not stored it in Task Copilot

      Would you like to retry with explicit tool enforcement? [y/n]
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ```

      **If user says yes, re-invoke @agent-ta with STRONGER prompt:**
      ```
      CRITICAL: Previous attempt did not use Task Copilot tools.

      You MUST call these tools - do NOT output markdown documents:

      1. prd_create({ title, description, acceptanceCriteria, ... })
         → Returns PRD-xxx ID - USE THIS ID for all tasks

      2. task_create({ prdId: "PRD-xxx", title, description, metadata: {...} })
         → Call multiple times, once per task
         → MUST include metadata.streamId in EVERY task
         → MUST include metadata.dependencies array

      3. After all tool calls, verify:
         → Call prd_list({}) and confirm PRD exists
         → Call stream_list({}) and confirm streams exist
         → If either is empty, you did NOT call the tools

      Feature: {feature_description}

      {rest of original prompt}
      ```

      **If user says no, exit and report failure.**

   d. **If verification PASSES (both have results):**
      - Continue to display success message with stream structure
      - Proceed to step 5 below

5. **Create Orchestrator Files:**

   After verification passes, set up the orchestrator infrastructure:

   a. **Create directory:**
      ```bash
      mkdir -p .claude/orchestrator
      ```

   b. **Copy template files from framework:**
      - `task_copilot_client.py` - Task Copilot data abstraction layer
      - `check_streams_data.py` - Stream data fetcher for bash scripts
      - `check-streams` - Live status dashboard (with dynamic workspace detection)
      - `watch-status` - Wrapper for live status updates
      - `orchestrate.py` - Main orchestration script with dynamic dependencies
      - `ORCHESTRATION_GUIDE.md` - Full documentation

   c. **Replace workspace placeholder:**
      - In `check-streams` file, replace `WORKSPACE_ID="insights-copilot"` with dynamic detection

   d. **Make scripts executable:**
      ```bash
      chmod +x .claude/orchestrator/check-streams
      chmod +x .claude/orchestrator/watch-status
      ```

   e. **Create symlink at project root:**
      ```bash
      ln -sf .claude/orchestrator/watch-status watch-status
      ```

   f. **Display creation confirmation:**
      ```
      ✓ Orchestrator files created in .claude/orchestrator/
      ✓ Symlink created: ./watch-status
      ```

6. **Display success message** with:
   - PRD ID created
   - Number of streams and tasks
   - Dependency structure visualization
   - Next step: "Run `/orchestrate start` to begin execution"

---

### `/orchestrate start`

**Single command that handles everything:**

**File Verification (ALWAYS runs first):**

Before any validation or execution, verify orchestrator files exist:

1. **Check required files exist:**
   - `.claude/orchestrator/orchestrate.py`
   - `.claude/orchestrator/task_copilot_client.py`
   - `.claude/orchestrator/check_streams_data.py`
   - `.claude/orchestrator/check-streams`
   - `.claude/orchestrator/watch-status`

2. **If any files are missing:**
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ❌ ERROR: Orchestrator Files Not Found
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Missing required orchestrator files.

   Run `/orchestrate generate` first to:
     1. Create PRD and tasks in Task Copilot
     2. Set up orchestrator infrastructure
     3. Create worker scripts and symlinks

   Then run `/orchestrate start` to spawn workers.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```

   **STOP - Do NOT create files, do NOT proceed to validation.**

**Pre-flight Validation (runs after file verification):**

After verifying files exist, validate Task Copilot has proper stream data:

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

**Stale PID Cleanup (automatic on startup):**

Before any workers are spawned, the orchestrator automatically cleans up orphaned PID files:

1. **Scan PID directory** - Find all existing `.pid` files in `.claude/orchestrator/pids/`
2. **Check process status** - For each PID file:
   - Read the PID value
   - Run `ps -p <PID>` to check if process is actually running
   - If process not found or is zombie: Remove the stale PID file
   - If process is running: Preserve the PID file
3. **Log cleanup** - Display count of cleaned up stale PID files for visibility

This ensures a clean slate when starting new orchestration, preventing false "already running" errors from crashed workers.

---

**Execution (after verification passes):**

After file and stream validation passes, start the orchestration system:
```bash
python .claude/orchestrator/orchestrate.py start
```

**On startup, orchestrator will:**
1. Clean up stale PID files (logged if any found)
2. Validate stream metadata and dependencies
3. Spawn workers according to dependency order

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

1. **Validate environment** (optional but recommended):
   ```bash
   cd ~/.claude/copilot/templates/orchestration
   python validate-setup.py --verbose
   ```
   This checks Python version, Claude CLI, Git, MCP configuration, and more.

2. **Run `/orchestrate generate` first**: This creates PRD and tasks with proper stream metadata:
   ```json
   {
     "metadata": {
       "streamId": "Stream-A",
       "streamName": "Foundation Work",
       "dependencies": []
     }
   }
   ```

3. **Python 3.8+** installed

4. **Git worktrees** (optional): For parallel streams working on different branches

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
│       ├── logs/                    # Worker logs (per-initiative: Stream-A_abc12345.log)
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

### Environment issues
- **Run validation first:**
  ```bash
  python validate-setup.py --verbose --fix
  ```
  This checks Python, Claude CLI, Git, MCP config, and attempts fixes.

### "No streams found in Task Copilot database"
- **Most common cause:** You ran `/orchestrate start` before `/orchestrate generate`
- **Solution:** Run `/orchestrate generate` first to create PRD and tasks with stream metadata
- Also check: Tasks are not archived (`archived = 0`)

### "Worker already running" (false positive)
- **Cause:** Stale PID file from crashed worker
- **Solution:** This is now automatically fixed on startup - stale PID files are cleaned up before spawning workers
- **Manual fix:** If needed, run: `rm .claude/orchestrator/pids/*.pid` then retry `/orchestrate start`

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
- **Automatic PID cleanup**: Stale PID files from crashed workers are automatically removed on startup, preventing false "already running" errors

---

## Implementation

When user runs `/orchestrate [command]`:

1. **Validate command** - Must be `generate`, `start`, `status`, or `stop`

2. **For `generate`:**
   - **Parse arguments** for `--technical` flag and feature description
   - **Prompt for feature** if not provided as argument
   - **Link initiative** via `initiative_link()` (see detailed steps in `/orchestrate generate` section above)
   - **Detect workflow mode:**
     - If `--technical` flag: Skip to @agent-ta invocation
     - If technical keywords detected: Ask user to confirm technical-only flow
     - Default: Use Experience-First workflow
   - **Experience-First Flow (if not --technical):**
     - **Stage 1:** Invoke @agent-sd → Service Design Specification (WP-xxx)
       - Display checkpoint, ask "Proceed to UX Design? [y/n/skip]"
     - **Stage 2:** Invoke @agent-uxd → UX Design Specification (WP-yyy)
       - Display checkpoint, ask "Proceed to Visual Design? [y/n/skip]"
     - **Stage 3:** Invoke @agent-uids → UI Design Specification (WP-zzz)
       - Display checkpoint, ask "Proceed to Technical Architecture? [y/n]"
     - Collect specification IDs for @agent-ta
   - **Stage 4:** Invoke @agent-ta with:
     - Feature description
     - Source specification IDs (from Experience-First stages, or "None" if --technical)
     - Orchestration generation prompt (see `/orchestrate generate` section above)
   - **Wait for @agent-ta** to create PRD and tasks in Task Copilot
   - **VERIFY creation (MANDATORY):**
     - Call `prd_list({})` to verify PRDs exist
     - Call `stream_list({})` to verify streams exist
     - **If either is empty:** Display error, offer retry with stronger prompt
     - **If both have results:** Proceed to create files
   - **CREATE Orchestrator Files (AFTER verification passes):**
     - Create `.claude/orchestrator/` directory
     - Copy template files from `~/.claude/copilot/templates/orchestration/`:
       - `orchestrate.py` - Main orchestration script
       - `task_copilot_client.py` - Task Copilot data abstraction
       - `check_streams_data.py` - Stream data fetcher
       - `check-streams` - Status dashboard script
       - `watch-status` - Live monitoring wrapper
       - `ORCHESTRATION_GUIDE.md` - Documentation
     - Make scripts executable: `chmod +x check-streams watch-status`
     - Create project root symlink: `ln -sf .claude/orchestrator/watch-status watch-status`
   - **Display results:**
     - Specifications created (if Experience-First)
     - PRD ID created
     - Number of streams and tasks
     - Source specifications linked to tasks
     - Dependency structure visualization
     - Files created confirmation
     - Next step: "Run `/orchestrate start` to begin execution"

3. **For `start`:**
   - **File Verification (REQUIRED - runs first):**
     - Check if all required files exist:
       - `.claude/orchestrator/orchestrate.py`
       - `.claude/orchestrator/task_copilot_client.py`
       - `.claude/orchestrator/check_streams_data.py`
       - `.claude/orchestrator/check-streams`
       - `.claude/orchestrator/watch-status`
     - **If any files missing:** Display error box directing user to run `/orchestrate generate` first
     - **CRITICAL: Do NOT create files - only verify they exist**
     - **If missing, STOP and direct user to `/orchestrate generate`**
   - **Stale PID Cleanup (automatic - runs after file verification):**
     - Orchestrator automatically cleans up orphaned PID files on startup
     - For each `.pid` file in `.claude/orchestrator/pids/`:
       - Check if process is actually running via `ps -p <PID>`
       - Remove PID file if process is dead or zombie
       - Preserve PID file if process is alive
     - Log count of cleaned up files for visibility
     - This prevents false "already running" errors from crashed workers
   - **Pre-flight Validation (runs after cleanup):**
     - Query Task Copilot for tasks with `metadata.streamId`
     - **If no streams found:** ERROR - direct user to run `/orchestrate generate` first
     - Verify at least one foundation stream exists (empty dependencies)
     - Verify no circular dependencies in graph
   - **Execution Phase (only if all verification passes):**
     - Display dependency structure before starting
     - Run `python .claude/orchestrator/orchestrate.py start`
     - Show output in real-time

4. **For `status` and `stop`:**
   - Run `python .claude/orchestrator/orchestrate.py [command]`
   - Show output in real-time
