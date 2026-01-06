# Continue Previous Work

Resume a conversation by loading context from Memory Copilot and Task Copilot.

## Command Argument Handling

This command supports an optional stream name argument for resuming work on specific parallel streams:

**Usage:**
- `/continue` - Interactive mode (check pause checkpoints, then resume main initiative or select from streams)
- `/continue Stream-B` - Resume work on specific stream directly

## Step 0: Check for Pause Checkpoints (Priority Check)

**BEFORE loading standard initiative context**, check for recent pause checkpoints:

```typescript
// Find all non-expired checkpoints with pause characteristics
const pauseCheckpoints = await findPauseCheckpoints();

function findPauseCheckpoints() {
  // Get current initiative (lean mode)
  const initiative = await initiative_get({ mode: "lean" });
  if (!initiative) return [];

  // Get all in-progress tasks
  const tasks = await task_list({ status: 'in_progress' });

  // For each task, check for pause checkpoints
  const checkpoints = [];
  for (const task of tasks) {
    const taskCheckpoints = await checkpoint_list({ taskId: task.id, limit: 5 });

    // Find checkpoints with pause characteristics
    for (const cp of taskCheckpoints.checkpoints) {
      const fullCheckpoint = await checkpoint_get({ id: cp.id });

      if (fullCheckpoint &&
          fullCheckpoint.trigger === 'manual' &&
          fullCheckpoint.executionPhase === 'paused' &&
          fullCheckpoint.agentContext?.pausedBy === 'user') {
        checkpoints.push({
          checkpointId: cp.id,
          taskId: task.id,
          taskTitle: task.title,
          pauseReason: fullCheckpoint.agentContext.pauseReason,
          pausedAt: fullCheckpoint.agentContext.pausedAt,
          hasDraft: cp.hasDraft,
          expiresAt: cp.expiresAt
        });
      }
    }
  }

  // Sort by most recent pause
  return checkpoints.sort((a, b) =>
    new Date(b.pausedAt).getTime() - new Date(a.pausedAt).getTime()
  );
}
```

**If pause checkpoints found**, present resume options:

```
## Paused Work Detected

Found ${pauseCheckpoints.length} paused task(s) from recent session:

${pauseCheckpoints.map((cp, idx) => `
${idx + 1}. ${cp.taskTitle}
   Paused: ${formatTimeAgo(cp.pausedAt)}
   Reason: ${cp.pauseReason}
   Has draft: ${cp.hasDraft ? 'Yes' : 'No'}
   Expires: ${formatTimeAgo(cp.expiresAt)}
`).join('\n')}

Options:
[1-${pauseCheckpoints.length}] Resume specific paused task
[c] Continue with standard initiative resume (ignore paused work)
[s] Show all streams (include paused tasks)

Select option:
```

**User selections:**
- Number (1-N): Call `checkpoint_resume({ taskId, checkpointId })` and begin work
- `c`: Proceed to standard resume flow (Step 1 below)
- `s`: Proceed to stream selection flow (Step 1 below, then stream list)

**If no pause checkpoints found**, proceed to standard resume flow.

**Auto-Detection Logic:**
When a stream argument is provided:

1. **Query stream details**:
   ```
   stream_get({ streamId: "Stream-B" })
   ```

2. **Setup git worktree isolation** (if parallel stream and worktree not already created):
   - Check if stream has `worktreePath` in metadata
   - If not and streamPhase is 'parallel':
     - Create worktree: `.claude/worktrees/{streamId}`
     - Create branch: `stream-{streamId}` (lowercase)
     - Update all stream tasks with worktree metadata:
       ```
       task_update({
         id: taskId,
         metadata: {
           ...existingMetadata,
           worktreePath: ".claude/worktrees/Stream-B",
           branchName: "stream-b"
         }
       })
       ```
   - Foundation and integration streams work in main worktree (no isolation needed)

   **Important:** The WorktreeManager automatically handles:
   - Creating worktree directories under `.claude/worktrees/`
   - Branching from current branch (usually main)
   - Returning existing worktree info if already created
   - All worktrees are gitignored by default

3. **Load stream context** (~200 tokens):
   - Stream name and phase
   - Total/completed/in-progress/blocked tasks
   - Files touched by stream
   - Stream dependencies
   - **Git worktree info** (if parallel stream):
     - Worktree path: `.claude/worktrees/{streamId}`
     - Branch name: `stream-{streamId}`
     - Status: Active/Not Created
   - Next incomplete task

4. **Begin work immediately**:
   - Identify next pending/blocked task
   - Invoke appropriate agent with task ID
   - **Agent works in the worktree directory** (path resolution automatic):
     - For parallel streams: All file paths are relative to `.claude/worktrees/{streamId}`
     - For foundation/integration: File paths are relative to project root
     - No manual directory switching required
   - Skip interactive selection

**When no argument provided:**

1. **Check for streams** in current initiative:
   ```
   stream_list()
   ```

   **Note:** By default, `stream_list()` excludes archived streams. Archived streams are tasks from previous initiatives that were automatically archived when switching initiatives. If you need to resume an archived stream, use:
   ```
   stream_list({ includeArchived: true })
   stream_unarchive({ streamId: "Stream-X" })
   ```

2. **If streams exist**, present formatted list:
   ```
   Available streams:

   1. Stream-A (foundation) - 4/4 tasks complete ✓
   2. Stream-B (command-updates, parallel) - 1/2 tasks complete
      Worktree: .claude/worktrees/Stream-B | Branch: stream-b
   3. Stream-C (agent-updates, parallel) - 0/3 tasks pending
      Worktree: .claude/worktrees/Stream-C | Branch: stream-c

   Select stream [1-3] or press Enter to resume main initiative:
   ```

   **Note:** Only parallel streams show worktree information. Foundation and integration streams work in the main worktree.

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

**Active Stream:** [If resuming specific stream]
- Stream: Stream-B (command-updates, parallel)
- Worktree: .claude/worktrees/Stream-B
- Branch: stream-b
- Tasks: 1/2 complete

**Recent Decisions:**
- [Key decisions from Memory Copilot]

**Recent Activity:**
- [From Task Copilot progress_summary]
```

**Do NOT list all completed/in-progress tasks.** That data lives in Task Copilot.

**Worktree Info:** If resuming a parallel stream, include the worktree path and branch name from `stream_get` output.

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

## Worktree Management

Git worktrees provide complete isolation for parallel streams, eliminating file conflicts and enabling true concurrent development.

### Quick Reference: Common Worktree Commands

| Task | Command |
|------|---------|
| Resume parallel stream | `/continue Stream-B` (creates worktree if needed) |
| List all worktrees | `git worktree list` |
| Check stream completion | `stream_get({ streamId: "Stream-B" })` |
| Merge completed stream | `git checkout main && git merge stream-b --no-ff` |
| Remove worktree | `git worktree remove .claude/worktrees/Stream-B` |
| Clean up stale worktrees | `git worktree prune` |
| Force remove dirty worktree | `git worktree remove --force .claude/worktrees/Stream-B` |

### Understanding Worktree Phases

| Stream Phase | Worktree Location | Purpose |
|--------------|------------------|---------|
| **Foundation** | Main worktree (project root) | Shared infrastructure that other streams depend on |
| **Parallel** | `.claude/worktrees/{streamId}` | Independent feature work, fully isolated |
| **Integration** | Main worktree (project root) | Merges all parallel streams together |

### When Resuming a Parallel Stream

The `/continue` command automatically:

1. **Detects if worktree exists** via `stream_get` (checks `worktreePath` and `branchName` fields)
2. **Creates worktree if needed**:
   - Path: `.claude/worktrees/{streamId}`
   - Branch: `stream-{streamId}` (lowercase)
   - Branched from: Current branch (usually `main`)
3. **Updates all stream tasks** with worktree metadata
4. **Agents work in the worktree directory** automatically

**You do NOT need to manually switch directories.** All file operations are automatically scoped to the worktree path.

### Switching Between Streams

To work on different streams in the same session:

```
/continue Stream-B  → Switch to Stream-B worktree
/continue Stream-C  → Switch to Stream-C worktree
/continue          → Return to main initiative (main worktree)
```

Each invocation loads the correct worktree context automatically.

### When Stream is Completed

When all tasks in a parallel stream are completed, you have two options:

#### Option 1: Merge via Command (Recommended)

The WorktreeManager provides a merge helper:

```
Use stream_get to verify completion:
  stream_get({ streamId: "Stream-B" })

Then merge:
  git checkout main
  git merge stream-b --no-ff -m "Merge Stream-B: <description>"
```

#### Option 2: Manual Merge

```bash
# Switch to main branch
git checkout main

# Merge stream branch with no-fast-forward
git merge stream-b --no-ff -m "Merge Stream-B: feature description"

# Verify merge
git log --oneline --graph -10
```

### Cleanup After Merge

**Important:** Only clean up worktrees AFTER successfully merging and verifying the merge.

1. **Remove the worktree**:
   ```bash
   git worktree remove .claude/worktrees/Stream-B
   ```

2. **Optional: Delete the branch** (if no longer needed):
   ```bash
   git branch -d stream-b
   ```

3. **Prune stale worktree references** (cleanup metadata):
   ```bash
   git worktree prune
   ```

**Safety Note:** Worktree cleanup is intentionally manual to prevent accidental loss of uncommitted work. Always verify your work is committed and merged before removing worktrees.

### Listing All Worktrees

To see all active worktrees:

```bash
git worktree list
```

Output example:
```
/project/root              abc1234 [main]
/project/root/.claude/worktrees/Stream-B  def5678 [stream-b]
/project/root/.claude/worktrees/Stream-C  ghi9012 [stream-c]
```

### Conflict Resolution

When using worktrees:

- **Parallel streams are fully isolated** - `stream_conflict_check` returns empty for different parallel streams
- **File conflicts only occur** if:
  - Multiple streams share the main worktree (foundation/integration)
  - Same file is modified in multiple parallel branches (detected at merge time, not during development)
- **Foundation stream work** is always in main worktree (other streams branch from it)
- **Integration stream** works in main worktree, merges all parallel branches

### Troubleshooting Worktrees

#### Worktree Already Exists Error

If you see "fatal: '.claude/worktrees/Stream-B' already exists":

```bash
# List worktrees to verify
git worktree list

# If stale, prune first
git worktree prune

# Then retry /continue Stream-B
```

#### Uncommitted Changes in Worktree

If you need to remove a worktree with uncommitted changes:

```bash
# Force removal (USE WITH CAUTION)
git worktree remove --force .claude/worktrees/Stream-B
```

#### Switching Streams with Uncommitted Work

Always commit or stash before switching streams:

```bash
# In worktree directory
git add .
git commit -m "WIP: checkpoint before switching"

# Or stash
git stash push -m "Stream-B checkpoint"
```

### Best Practices

1. **Commit frequently** in your stream worktree
2. **Keep streams focused** - avoid modifying shared files across streams
3. **Merge foundation first** - ensure parallel streams branch from latest foundation
4. **Test after merge** - run tests in main worktree after merging streams
5. **Clean up promptly** - remove worktrees after successful merge to avoid confusion

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
