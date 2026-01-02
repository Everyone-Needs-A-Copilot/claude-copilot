# Continue Previous Work

Resume a conversation by loading context from Memory Copilot and Task Copilot.

## Command Argument Handling

This command supports an optional stream name argument for resuming work on specific parallel streams:

**Usage:**
- `/continue` - Interactive mode (resume main initiative or select from streams)
- `/continue Stream-B` - Resume work on specific stream directly

**Auto-Detection Logic:**
When a stream argument is provided:

1. **Query stream details**:
   ```
   stream_get({ streamId: "Stream-B" })
   ```

2. **Load stream context** (~200 tokens):
   - Stream name and phase
   - Total/completed/in-progress/blocked tasks
   - Files touched by stream
   - Stream dependencies
   - Next incomplete task

3. **Begin work immediately**:
   - Identify next pending/blocked task
   - Invoke appropriate agent with task ID
   - Skip interactive selection

**When no argument provided:**

1. **Check for streams** in current initiative:
   ```
   stream_list()
   ```

2. **If streams exist**, present formatted list:
   ```
   Available streams:

   1. Stream-A (foundation) - 4/4 tasks complete ✓
   2. Stream-B (command-updates) - 1/2 tasks complete
   3. Stream-C (agent-updates) - 0/3 tasks pending

   Select stream [1-3] or press Enter to resume main initiative:
   ```

3. **If no streams**, proceed with standard resume flow

4. **After selection**:
   - Load selected stream context
   - Identify next task
   - Begin work

**When no streams or user selects main**:
- Follow standard resume protocol (load initiative, show status, ask what to work on)

## Step 1: Load Context (Slim)

Load minimal context to preserve token budget:

1. **From Memory Copilot** (permanent knowledge):
   ```
   initiative_get({ mode: "lean" }) → currentFocus, nextAction, status (~150 tokens)
   ```

   **Note:** Use lean mode (default) for session resume. Only use `mode: "full"` if you specifically need to review all decisions, lessons, or keyFiles.

2. **From Task Copilot** (work progress):
   ```
   progress_summary() → PRD counts, task status, recent activity
   ```

3. **From Project Constitution** (if exists):
   - Try to read `CONSTITUTION.md` from project root
   - If exists: Inject into context, note `[Constitution: Active]`
   - If missing: Continue without it (graceful fallback), note `[Constitution: Not Found]`

4. If no initiative exists, ask user what they're working on and call `initiative_start`

**Important:** Do NOT load full task lists. Use `progress_summary` for compact status.

## Step 2: Activate Protocol

**The Agent-First Protocol is now active.**

### Your Obligations

1. **Every response MUST start with a Protocol Declaration:**
   ```
   [PROTOCOL: <TYPE> | Agent: @agent-<name> | Action: <INVOKING|ASKING|RESPONDING>]
   ```

2. **You MUST invoke agents BEFORE responding with analysis or plans**

3. **You MUST NOT:**
   - Skip the protocol declaration
   - Say "I'll use @agent-X" without actually invoking it
   - Read files yourself instead of using agents
   - Write plans before agent investigation completes
   - Load full task lists into context

### Request Type to Agent Mapping

| Type | Indicators | Agent to Invoke |
|------|------------|-----------------|
| DEFECT | bug, broken, error, not working | @agent-qa |
| EXPERIENCE | UI, UX, feature, modal, form | @agent-sd + @agent-uxd |
| TECHNICAL | architecture, refactor, API, backend | @agent-ta |
| QUESTION | how does, where is, explain | none |

## Step 3: Present Status (Compact)

Present a compact summary (~300 tokens max):

```
## Resuming: [Initiative Name]

**Status:** [IN PROGRESS / BLOCKED / READY FOR REVIEW]

**Progress:** [X/Y tasks complete] | [Z work products]

**Current Focus:** [From initiative.currentFocus]

**Next Action:** [From initiative.nextAction]

**Recent Decisions:**
- [Key decisions from Memory Copilot]

**Recent Activity:**
- [From Task Copilot progress_summary]
```

**Do NOT list all completed/in-progress tasks.** That data lives in Task Copilot.

## Step 4: Ask

End with:
```
Protocol active. [Constitution: Active/Not Found]
What would you like to work on?
```

## During Session

### Routing to Agents

Pass task IDs when invoking agents:
```
[PROTOCOL: TECHNICAL | Agent: @agent-ta | Action: INVOKING]

Please complete TASK-xxx: <brief description>
```

Agents will store work products in Task Copilot and return minimal summaries.

### Progress Updates

Use Task Copilot for task management:
- `task_update({ id, status, notes })` - Update task status
- `progress_summary()` - Check overall progress

Use Memory Copilot for permanent knowledge:
- `memory_store({ type: "decision", content })` - Strategic decisions
- `memory_store({ type: "lesson", content })` - Key learnings

## End of Session

Update Memory Copilot with **slim context only**:

```
initiative_update({
  currentFocus: "Brief description of current focus",  // 100 chars max
  nextAction: "Specific next step: TASK-xxx",          // 100 chars max
  decisions: [{ decision, rationale }],                // Strategic only
  lessons: [{ lesson, context }],                      // Key learnings only
  keyFiles: ["important/files/touched.ts"]
})
```

**Do NOT store in Memory Copilot:**
- `completed` - Lives in Task Copilot (task status = completed)
- `inProgress` - Lives in Task Copilot (task status = in_progress)
- `blocked` - Lives in Task Copilot (task status = blocked)
- `resumeInstructions` - Replaced by `currentFocus` + `nextAction`

### If Initiative is Bloated

If `initiative_get` returns a bloated initiative (many tasks inline):

1. Call `initiative_slim({ archiveDetails: true })` to migrate
2. Archive is saved to `~/.claude/memory/archives/`
3. Continue with slim initiative

This ensures the next session loads quickly with minimal context usage.
