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

3. **Detect workflow mode:**
   - If `--technical` flag: Use Technical-Only workflow (skip to step 6)
   - If feature contains technical keywords (refactor, optimize, migrate, performance):
     Ask user to confirm: "This sounds technical. Use technical-only flow? [y/n]"
   - Default: Use Experience-First workflow

**Experience-First Workflow (Steps 4-6):**

4. **Stage 1: Service Design (@agent-sd)**

   Invoke @agent-sd with this prompt:
   ```
   Create a Service Design Specification for orchestration planning.

   Feature: {feature_description}

   ╔══════════════════════════════════════════════════════════════════╗
   ║  CRITICAL: TOOL RESTRICTIONS                                     ║
   ╠══════════════════════════════════════════════════════════════════╣
   ║  You are a SPECIFICATION AUTHOR, not a task creator.             ║
   ║                                                                  ║
   ║  ✓ ALLOWED: tc wp store - Store your specification               ║
   ║  ✓ ALLOWED: tc wp get - Read prior specifications                ║
   ║  ✓ ALLOWED: knowledge_search() - Research company context        ║
   ║                                                                  ║
   ║  ✗ FORBIDDEN: tc prd create - Only @agent-ta creates PRDs        ║
   ║  ✗ FORBIDDEN: tc task create - Only @agent-ta creates tasks      ║
   ║  ✗ FORBIDDEN: tc task update - You do not manage tasks           ║
   ║                                                                  ║
   ║  If you call forbidden tools, the orchestration will fail.       ║
   ╚══════════════════════════════════════════════════════════════════╝

   REQUIREMENTS:
   1. Map the complete user journey for this feature
   2. Identify all touchpoints (frontstage and backstage)
   3. Document pain points and opportunities
   4. Identify key moments that matter to the user
   5. Store specification as a work product (title: "Service Design Specification: {feature}",
      type: "other") and return the work product ID (WP-xxx)
   6. Return ONLY:
      - Work product ID (WP-xxx)
      - Summary (~100 tokens): key journey stages, main pain points, opportunities
      - DO NOT return task lists, implementation plans, or technical details
   ```

   After @agent-sd returns:
   - **Verify work product was stored:**
     ```bash
     tc wp get {WP-xxx from response}
     ```
     If not found, agent did not store the work product. Re-invoke with reminder.
   - Extract WP-xxx ID from response
   - Display checkpoint summary
   - Ask: "Proceed to UX Design? [y/n/skip]"
   - If "skip": Jump to step 6 (TA) with collected specs
   - If "n": Allow user to provide feedback, re-invoke @agent-sd

5. **Stage 2: UX Design (@agent-uxd)**

   Invoke @agent-uxd with this prompt:
   ```
   Create a UX Design Specification based on the service design.

   Feature: {feature_description}
   Service Design Spec: {WP-xxx from step 4}

   ╔══════════════════════════════════════════════════════════════════╗
   ║  CRITICAL: TOOL RESTRICTIONS                                     ║
   ╠══════════════════════════════════════════════════════════════════╣
   ║  You are a SPECIFICATION AUTHOR, not a task creator.             ║
   ║                                                                  ║
   ║  ✓ ALLOWED: tc wp store - Store your specification               ║
   ║  ✓ ALLOWED: tc wp get - Read prior specifications                ║
   ║  ✓ ALLOWED: knowledge_search() - Research company context        ║
   ║                                                                  ║
   ║  ✗ FORBIDDEN: tc prd create - Only @agent-ta creates PRDs        ║
   ║  ✗ FORBIDDEN: tc task create - Only @agent-ta creates tasks      ║
   ║  ✗ FORBIDDEN: tc task update - You do not manage tasks           ║
   ║                                                                  ║
   ║  If you call forbidden tools, the orchestration will fail.       ║
   ╚══════════════════════════════════════════════════════════════════╝

   REQUIREMENTS:
   1. Run `tc wp get {WP-xxx}` to read service design spec
   2. Design all interaction states (default, hover, focus, error, loading, empty)
   3. Define task flows with all paths (primary, alternative, error recovery)
   4. Specify accessibility requirements (WCAG 2.1 AA)
   5. Document information architecture and navigation
   6. Store specification as a work product (title: "UX Design Specification: {feature}",
      type: "other") and return the work product ID (WP-yyy)
   7. Return ONLY:
      - Work product ID (WP-yyy)
      - Summary (~100 tokens): key flows, interaction patterns, accessibility notes
      - DO NOT return task lists, implementation plans, or code
   ```

   After @agent-uxd returns:
   - **Verify work product was stored:**
     ```bash
     tc wp get {WP-yyy from response}
     ```
     If not found, agent did not store the work product. Re-invoke with reminder.
   - Extract WP-yyy ID from response
   - Display checkpoint summary
   - Ask: "Proceed to Visual Design? [y/n/skip]"
   - If "skip": Jump to step 6 (TA) with collected specs
   - If "n": Allow user to provide feedback, re-invoke @agent-uxd

6. **Stage 3: UI Design (@agent-uids)**

   Invoke @agent-uids with this prompt:
   ```
   Create a UI Design Specification based on the UX design.

   Feature: {feature_description}
   Service Design Spec: {WP-xxx from step 4}
   UX Design Spec: {WP-yyy from step 5}

   ╔══════════════════════════════════════════════════════════════════╗
   ║  CRITICAL: TOOL RESTRICTIONS                                     ║
   ╠══════════════════════════════════════════════════════════════════╣
   ║  You are a SPECIFICATION AUTHOR, not a task creator.             ║
   ║                                                                  ║
   ║  ✓ ALLOWED: tc wp store - Store your specification               ║
   ║  ✓ ALLOWED: tc wp get - Read prior specifications                ║
   ║  ✓ ALLOWED: knowledge_search() - Research company context        ║
   ║                                                                  ║
   ║  ✗ FORBIDDEN: tc prd create - Only @agent-ta creates PRDs        ║
   ║  ✗ FORBIDDEN: tc task create - Only @agent-ta creates tasks      ║
   ║  ✗ FORBIDDEN: tc task update - You do not manage tasks           ║
   ║                                                                  ║
   ║  If you call forbidden tools, the orchestration will fail.       ║
   ╚══════════════════════════════════════════════════════════════════╝

   REQUIREMENTS:
   1. Run `tc wp get <id>` for each prior spec to understand context
   2. Define design tokens (colors, spacing, typography, shadows)
   3. Specify component designs with all visual states
   4. Include micro-interactions and transitions
   5. Document responsive breakpoints and behavior
   6. Store specification as a work product (title: "UI Design Specification: {feature}",
      type: "other") and return the work product ID (WP-zzz)
   7. Return ONLY:
      - Work product ID (WP-zzz)
      - Summary (~100 tokens): design tokens, key components, visual patterns
      - DO NOT return task lists, implementation plans, or code
   ```

   After @agent-uids returns:
   - **Verify work product was stored:**
     ```bash
     tc wp get {WP-zzz from response}
     ```
     If not found, agent did not store the work product. Re-invoke with reminder.
   - Extract WP-zzz ID from response
   - Display checkpoint summary
   - Ask: "Proceed to Technical Architecture? [y/n]"
   - If "n": Allow user to provide feedback, re-invoke @agent-uids

7. **Stage 4: Technical Architecture (@agent-ta) - DESIGN ONLY**

   **IMPORTANT:** Subagents cannot call CLI tools directly in the main session. @agent-ta
   designs the structure, then the main session creates the PRD and tasks via `tc` CLI.

   Invoke @agent-ta with this prompt:
   ```
   Design a PRD and task breakdown for parallel orchestration.

   Feature: {feature_description}

   SOURCE SPECIFICATIONS (READ THESE FIRST):
   {list of WP-xxx IDs from steps 4-6, or "None - technical-only flow"}

   ╔══════════════════════════════════════════════════════════════════╗
   ║  CRITICAL: RETURN STRUCTURED JSON                                ║
   ╠══════════════════════════════════════════════════════════════════╣
   ║  Return a JSON structure that the main session will use to       ║
   ║  create the PRD and tasks via `tc prd create` / `tc task create`.║
   ║                                                                  ║
   ║  Your response MUST include a JSON code block with the exact     ║
   ║  structure shown below. The main session will parse this JSON    ║
   ║  and run the tc CLI commands on your behalf.                     ║
   ╚══════════════════════════════════════════════════════════════════╝

   WORKFLOW:

   STEP 1: Read all source specifications (if provided)
   - For each WP-xxx ID provided, run `tc wp get <id>` to read the specification
   - Extract requirements, user journeys, interaction patterns, visual specs
   - These specs define WHAT to build - you define HOW to build it

   STEP 2: Design stream structure
   - Foundation streams: Shared dependencies, migrations, types (dependencies: [])
   - Parallel streams: Independent work that can run simultaneously
   - Integration streams: Final assembly, depends on parallel streams
   - At least ONE stream MUST have dependencies: [] (foundation)

   STEP 3: Return structured JSON

   Your response MUST include this EXACT JSON structure in a code block:

   ```json
   {
     "prd": {
       "title": "{feature} - Stream Tasks",
       "description": "Orchestration tasks for {feature}",
       "content": "# PRD: {feature}\n\n## Overview\n...\n\n## Requirements\n...\n\n## Success Criteria\n..."
     },
     "tasks": [
       {
         "title": "Task title here",
         "description": "Full task description with acceptance criteria",
         "metadata": {
           "streamId": "Stream-A",
           "streamName": "Foundation",
           "streamPhase": "foundation",
           "phase": "backend",
           "assignedAgent": "me",
           "files": ["path/to/file1.ts"],
           "dependencies": [],
           "sourceSpecifications": ["WP-xxx"]
         }
       },
       {
         "title": "Another task",
         "description": "Description...",
         "metadata": {
           "streamId": "Stream-B",
           "streamName": "Implementation",
           "streamPhase": "parallel",
           "phase": "frontend",
           "assignedAgent": "uid",
           "files": ["path/to/file2.ts"],
           "dependencies": ["Stream-A"],
           "sourceSpecifications": ["WP-xxx", "WP-yyy"]
         }
       }
     ]
   }
   ```

   REQUIREMENTS FOR THE JSON:
   - prd.title: Clear title for the PRD
   - prd.description: One-line description
   - prd.content: Full PRD content in markdown
   - tasks: Array of task objects
   - Each task MUST have:
     - title: Clear task title
     - description: Full description with acceptance criteria
     - metadata.streamId: REQUIRED (e.g., "Stream-A", "Stream-B")
     - metadata.streamName: Human readable name
     - metadata.streamPhase: "foundation", "parallel", or "integration"
     - metadata.phase: REQUIRED — "backend", "frontend", "quality", "docs", "devops", or "integration"
     - metadata.assignedAgent: REQUIRED — "me", "uid", "ta", "qa", "sec", "doc", or "do"
     - metadata.files: Array of files this task will modify
     - metadata.dependencies: Array of streamIds this depends on ([] for foundation)
     - metadata.sourceSpecifications: Array of WP-xxx IDs (can be empty)

   AGENT ASSIGNMENT TABLE (implementation agents only):
   | Task Type | Agent | Phase |
   |-----------|-------|-------|
   | Backend APIs, services, data models | me | backend |
   | Frontend pages, UI integration, hooks | uid | frontend |
   | Architecture, schemas, contracts | ta | backend |
   | Test suites, edge cases | qa | quality |
   | Security review, auth flows | sec | quality |
   | Technical docs | doc | docs |
   | CI/CD, deployment | do | devops |

   TASK GRANULARITY — FILE INDEPENDENCE RULE:
   - ONE independent file/feature per task
   - Tasks in the same phase + same stream MUST modify different files
   - If two tasks need to touch the same file, put them in different phases or merge into one task
   - Backend: one endpoint/service/model per task
   - Frontend: one page/component per task
   - Count of tasks in a phase = count of independent units (no artificial merging)
   - No single task should list more than 4 files (split if larger)

   VALIDATION RULES:
   - At least one task must have dependencies: []
   - No circular dependencies
   - All dependency references must exist as streamIds in other tasks
   - Every task MUST have metadata.phase (reject if missing)
   - Every task MUST have metadata.assignedAgent (reject if missing)
   - assignedAgent MUST be one of: me, uid, ta, qa, sec, doc, do
   - No two tasks in the same stream+phase should share files

   After the JSON block, provide a brief summary:
   - Number of streams
   - Number of tasks per stream (grouped by phase)
   - Dependency structure
   ```

8. **PARSE @agent-ta Response and CREATE via tc CLI (MAIN SESSION):**

   After @agent-ta returns, the MAIN SESSION (not a subagent) must:

   a. **Extract JSON from response:**
      - Find the JSON code block in @agent-ta's response
      - Parse it to get `prd` and `tasks` objects
      - If JSON is malformed or missing, display error and ask to retry

   b. **Validate the JSON structure:**
      - Verify `prd` has title, description, content
      - Verify `tasks` is a non-empty array
      - Verify each task has required metadata fields (streamId, streamName, streamPhase, phase, assignedAgent, files, dependencies)
      - Verify `metadata.phase` exists and is one of: backend, frontend, quality, docs, devops, integration
      - Verify `metadata.assignedAgent` exists and is one of: me, uid, ta, qa, sec, doc, do
      - Verify at least one task has `dependencies: []`
      - Verify no single task lists more than 4 files
      - Verify no two tasks in the same stream+phase share files
      - Check for circular dependencies

      **If validation fails:**
      ```
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ❌ INVALID JSON STRUCTURE
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

      @agent-ta's response had invalid or missing JSON.

      Error: {specific validation error}

      Options:
      1. Retry @agent-ta with feedback
      2. Abort

      [1/2]?
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ```

   c. **Create PRD via tc CLI:**
      ```bash
      tc prd create --title "{prd.title}" --description "{prd.description}" --content "{prd.content}" --json
      ```
      Store result as: PRD_ID = {id from JSON output}

   d. **Create each task via tc CLI:**
      For each task in tasks array:
      ```bash
      tc task create \
        --title "{task.title}" \
        --prd {PRD_ID} \
        --description "{task.description}" \
        --agent "{task.metadata.assignedAgent}" \
        --metadata '{task.metadata as JSON string}' \
        --json
      ```
      **NOTE:** The `--agent` field controls which specialist is assigned.
      The `metadata.phase` field controls execution ordering within the stream.

      Count successful creates as: TASK_COUNT

   e. **Display creation progress:**
      ```
      Creating PRD... ✓ PRD-xxx
      Creating tasks...
        ✓ Task 1: {title} (Stream-A)
        ✓ Task 2: {title} (Stream-B)
        ✓ Task 3: {title} (Stream-Z)
      Created {TASK_COUNT} tasks across {STREAM_COUNT} streams.
      ```

9. **VERIFY Task Copilot State (MANDATORY - BLOCKING):**

   This step verifies that all data was created correctly.

   a. **Check streams exist:**
      ```bash
      tc stream list --json
      ```
      Store result as: STREAM_COUNT = {number of streams returned}

   b. **Check tasks are linked to PRD:**
      ```bash
      tc task list --prd {PRD_ID} --json
      ```
      Store result as: TASK_COUNT = {number of tasks returned}

   c. **Evaluate verification results:**

      **BOTH must pass:**
      - STREAM_COUNT >= 1
      - TASK_COUNT >= 1

      **If ANY check fails (count is 0):**

      ```
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ❌ VERIFICATION FAILED
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

      Data creation failed despite tc CLI calls succeeding.

      Verification Results:
        • Streams found:        {STREAM_COUNT} {✓ or ✗}
        • Tasks linked to PRD:  {TASK_COUNT}  {✓ or ✗}

      Check Task Copilot database: ~/.claude/tasks/{workspace}/tasks.db

      Aborting /orchestrate generate.
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ```
      **STOP.**

   d. **Only if ALL verifications pass:**
      Display success and proceed to step 10 (file creation):
      ```
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ✓ VERIFICATION PASSED
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

      PRD: {PRD_ID}
      Streams: {STREAM_COUNT}
      Tasks: {TASK_COUNT}

      Proceeding to create orchestrator files...
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ```

10. **Create Orchestrator Files:**

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

12. **Display success message** with:
   - PRD ID created
   - Number of streams and tasks
   - Dependency structure visualization
   - Next step: "Run `/orchestrate start` to begin execution"

---

### `/orchestrate start`

**Purpose:** Validate orchestration data exists, then spawn workers.
**This command does NOT create or fix data - it only validates and runs.**

**Workflow:**

1. **File Verification (BLOCKING):**

   Check required orchestrator files exist:
   - `.claude/orchestrator/orchestrate.py`
   - `.claude/orchestrator/task_copilot_client.py`
   - `.claude/orchestrator/check_streams_data.py`
   - `.claude/orchestrator/check-streams`
   - `.claude/orchestrator/watch-status`

   **If ANY file is missing:**
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ❌ ORCHESTRATOR FILES NOT FOUND
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Missing: {list of missing files}

   Run `/orchestrate generate` first to:
     1. Create PRD and tasks in Task Copilot
     2. Generate orchestrator files

   /orchestrate start does NOT create files.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
   **STOP - Do NOT create files. Do NOT proceed.**

2. **Stream Verification (BLOCKING):**

   ```bash
   tc stream list --json
   ```

   **If no streams found:**
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ❌ NO STREAMS FOUND
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   No streams found in Task Copilot.

   This means either:
     • /orchestrate generate was not run
     • @agent-ta did not create tasks with metadata.streamId

   Run `/orchestrate generate` to create streams.

   /orchestrate start does NOT create streams.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
   **STOP - Do NOT attempt to create streams. Do NOT proceed.**

3. **Foundation Stream Verification (BLOCKING):**

   Check that at least one stream has `dependencies: []`:
   ```
   foundation_streams = [s for s in streams if s.dependencies == []]
   ```

   **If no foundation stream:**
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ❌ NO FOUNDATION STREAM
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   All streams have dependencies. At least one stream must have
   dependencies: [] to serve as the starting point.

   Found streams:
   {for each stream: "  {stream_id}: depends on {dependencies}"}

   This is a task configuration error. Re-run `/orchestrate generate`
   and ensure @agent-ta creates at least one foundation stream.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
   **STOP.**

4. **Circular Dependency Check (BLOCKING):**

   Build dependency graph and check for cycles.

   **If circular dependency detected:**
   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ❌ CIRCULAR DEPENDENCY DETECTED
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Cycle found: {Stream-A → Stream-B → Stream-C → Stream-A}

   Circular dependencies make orchestration impossible.
   Re-run `/orchestrate generate` with corrected dependencies.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
   **STOP.**

5. **Stale PID Cleanup (automatic):**

   Before spawning workers, clean up orphaned PID files:
   - Scan `.claude/orchestrator/pids/` for `.pid` files
   - For each PID, check if process is actually running via `ps -p <PID>`
   - Remove stale PID files for dead/zombie processes
   - Log count of cleaned up files

6. **All Validations Passed - Display and Confirm:**

   ```
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ✓ READY TO START ORCHESTRATION
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   Streams: {stream_count}
   Tasks: {task_count}

   Execution Order:
     Depth 0 (start immediately):
       • {stream_id} ({task_count} tasks)
     Depth 1 (after depth 0 completes):
       • {stream_id} ({task_count} tasks) - depends on [...]
     ...

   Start orchestration? [y/n]
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```

7. **On User Confirmation:**

   ```bash
   python .claude/orchestrator/orchestrate.py start
   ```

   Display:
   ```
   ✓ Orchestration started

   Monitor progress:
     ./watch-status          # Live updates every 15s
     ./watch-status 5        # Live updates every 5s

   Stop workers:
     /orchestrate stop
   ```

**Commands:**
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
- Run `/orchestrate generate` to recreate orchestrator files and symlinks
- Check file permissions (scripts should be executable): `chmod +x .claude/orchestrator/*`
- `/orchestrate start` does NOT auto-fix - it will fail and direct you to run generate

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
     - Prompt requesting STRUCTURED JSON output
   - **Wait for @agent-ta** to return JSON structure for PRD and tasks
   - **PARSE JSON and CREATE via tc CLI (MAIN SESSION):**
     - Extract JSON code block from @agent-ta's response
     - Validate JSON structure (prd object, tasks array, required metadata)
     - **If JSON invalid:** Display error, offer retry
     - **If JSON valid:** Main session runs tc CLI commands:
       - `tc prd create --title "..." --description "..." --content "..." --json` → get PRD_ID
       - For each task: `tc task create --title "..." --prd {PRD_ID} --agent "..." --metadata '...' --json`
     - Display creation progress
   - **VERIFY creation (MANDATORY - BLOCKING):**
     - `tc stream list --json` to verify streams exist
     - `tc task list --prd {PRD_ID} --json` to verify tasks are linked
     - **BOTH checks must pass** (count >= 1 for each)
     - **If ANY check fails:** Display error
     - **If all checks pass:** Proceed to create files
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
   - **File Verification (BLOCKING):**
     - Check if all required files exist:
       - `.claude/orchestrator/orchestrate.py`
       - `.claude/orchestrator/task_copilot_client.py`
       - `.claude/orchestrator/check_streams_data.py`
       - `.claude/orchestrator/check-streams`
       - `.claude/orchestrator/watch-status`
     - **If any files missing:** Display error, STOP - do NOT create files
   - **Stream Verification (BLOCKING):**
     - Run `tc stream list --json`
     - **If no streams found:** Display error, STOP - do NOT create streams
   - **Foundation Stream Verification (BLOCKING):**
     - Check at least one stream has `dependencies: []`
     - **If no foundation stream:** Display error, STOP
   - **Circular Dependency Check (BLOCKING):**
     - Build dependency graph and check for cycles
     - **If cycle detected:** Display error, STOP
   - **Stale PID Cleanup (automatic):**
     - Clean up orphaned PID files before spawning
   - **Execution Phase (only if ALL verifications pass):**
     - Display confirmation with execution order
     - Ask user to confirm: "Start orchestration? [y/n]"
     - Run `python .claude/orchestrator/orchestrate.py start`
     - Show output in real-time

4. **For `status` and `stop`:**
   - Run `python .claude/orchestrator/orchestrate.py [command]`
   - Show output in real-time
