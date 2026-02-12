# Continue Previous Work

Resume a conversation by loading context from Memory Copilot and Task Copilot.

**Usage:** `/continue` (interactive) | `/continue Stream-B` (resume specific stream)

## Step 0: Check for Pause Checkpoints (Priority Check)

**BEFORE loading standard initiative context**, check for recent pause checkpoints:

1. Call `initiative_get({ mode: "lean" })` — if no initiative, skip
2. Call `task_list({ status: 'in_progress' })` — get all active tasks
3. For each task, call `checkpoint_list({ taskId, limit: 5 })` then `checkpoint_get({ id })`
4. Filter checkpoints where `trigger === 'manual'`, `executionPhase === 'paused'`, `agentContext?.pausedBy === 'user'`
5. Sort by most recent `pausedAt`

**If pause checkpoints found**, present options:

```
## Paused Work Detected
Found N paused task(s):
1. [Task Title] — Paused: [time ago] | Reason: [reason] | Draft: Yes/No
Options: [1-N] Resume task | [c] Standard resume | [s] Show all streams
```

**If none found**, proceed to standard resume flow.

### Stream Argument Handling

**When stream argument provided** (e.g., `/continue Stream-B`):

1. `stream_get({ streamId: "Stream-B" })` — load stream details
2. **Setup worktree** if parallel stream without `worktreePath` in metadata:
   - Create worktree at `.claude/worktrees/{streamId}`, branch `stream-{streamId}`
   - Update all stream tasks with `worktreePath` and `branchName` metadata
   - Foundation/integration streams use main worktree (no isolation)
3. Load stream context (~200 tokens): name, phase, task counts, dependencies, worktree info, next task
4. Begin work immediately — invoke appropriate agent with next pending/blocked task

**When no argument provided:**

1. `stream_list()` — check for streams (excludes archived; use `includeArchived: true` + `stream_unarchive` if needed)
2. If streams exist, present selection list (parallel streams show worktree path/branch)
3. If no streams, proceed with standard resume flow
4. After selection, load stream context and begin work

## Step 1: Load Context (Slim)

Load minimal context to preserve token budget:

| Source | Call | Returns |
|--------|------|---------|
| Memory Copilot | `initiative_get({ mode: "lean" })` | currentFocus, nextAction, status (~150 tokens) |
| Task Copilot | `progress_summary()` | PRD counts, task status, recent activity |
| Project | Read `CONSTITUTION.md` from root | Constitution context (graceful fallback if missing) |

If no initiative exists, ask user what they're working on and call `initiative_start`.

**Important:** Do NOT load full task lists. Use `progress_summary` for compact status.

## Step 2: Activate Protocol

**The Agent-First Protocol is now active.**

Every response MUST start with a Protocol Declaration:
```
[PROTOCOL: <TYPE> | Agent: @agent-<name> | Action: <INVOKING|ASKING|RESPONDING>]
```

**You MUST** invoke agents BEFORE responding with analysis or plans.

**You MUST NOT** skip protocol declaration, promise agents without invoking, read files yourself, write plans before agent investigation, or load full task lists.

| Type | Indicators | Agent |
|------|------------|-------|
| DEFECT | bug, broken, error, not working | @agent-qa |
| EXPERIENCE | UI, UX, feature, modal, form | @agent-sd + @agent-uxd |
| TECHNICAL | architecture, refactor, API, backend | @agent-ta |
| QUESTION | how does, where is, explain | none |

## Step 3: Present Status (Compact)

~300 tokens max:

```
## Resuming: [Initiative Name]
**Status:** [IN PROGRESS / BLOCKED / READY FOR REVIEW]
**Progress:** [X/Y tasks complete] | [Z work products]
**Current Focus:** [From initiative.currentFocus]
**Next Action:** [From initiative.nextAction]
**Active Stream:** [stream name, phase, worktree path, branch, task progress]
**Recent Decisions:** [Key decisions from Memory Copilot]
**Recent Activity:** [From Task Copilot progress_summary]
```

Do NOT list all tasks. If resuming a parallel stream, include worktree path and branch.

## Step 4: Ask

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

### Progress Updates

| Purpose | Tool |
|---------|------|
| Update task status | `task_update({ id, status, notes })` |
| Check progress | `progress_summary()` |
| Store decisions | `memory_store({ type: "decision", content })` |
| Store learnings | `memory_store({ type: "lesson", content })` |

## Worktree Management

Git worktrees provide isolation for parallel streams, eliminating file conflicts.

### Phase to Location Mapping

| Stream Phase | Worktree Location | Notes |
|--------------|------------------|-------|
| Foundation | Main worktree (project root) | Shared infrastructure, other streams depend on it |
| Parallel | `.claude/worktrees/{streamId}` | Fully isolated, auto-created on `/continue` |
| Integration | Main worktree (project root) | Merges all parallel streams together |

### Common Commands

| Task | Command |
|------|---------|
| Resume parallel stream | `/continue Stream-B` (auto-creates worktree) |
| Switch streams | `/continue Stream-C` (auto-switches context) |
| Return to main | `/continue` (main worktree) |
| List worktrees | `git worktree list` |
| Merge completed stream | `git checkout main && git merge stream-b --no-ff` |
| Remove worktree | `git worktree remove .claude/worktrees/Stream-B` |
| Delete branch after merge | `git branch -d stream-b` |
| Clean stale refs | `git worktree prune` |
| Force remove dirty worktree | `git worktree remove --force .claude/worktrees/Stream-B` |

### Conflict Resolution

- Parallel streams are fully isolated — no conflicts during development
- Conflicts only arise at merge time if same file modified in multiple branches
- Foundation work is always in main worktree; parallel streams branch from it
- Use `stream_conflict_check` to detect shared-file risks

### Troubleshooting

| Problem | Solution |
|---------|----------|
| "already exists" error | `git worktree prune` then retry |
| Uncommitted changes blocking removal | `git worktree remove --force .claude/worktrees/Stream-B` |
| Switching streams with uncommitted work | Commit (`git commit -m "WIP"`) or stash (`git stash push -m "checkpoint"`) first |

### Best Practices

1. Commit frequently in stream worktrees
2. Keep streams focused — avoid modifying shared files across streams
3. Merge foundation first before parallel streams
4. Test in main worktree after merging
5. Remove worktrees promptly after successful merge

## End of Session

Update Memory Copilot with slim context only:

```
initiative_update({
  currentFocus: "Brief description",       // 100 chars max
  nextAction: "Specific next step: TASK-xxx", // 100 chars max
  decisions: [{ decision, rationale }],    // Strategic only
  lessons: [{ lesson, context }],          // Key learnings only
  keyFiles: ["important/files/touched.ts"]
})
```

**Do NOT store in Memory Copilot:** `completed`, `inProgress`, `blocked` (live in Task Copilot), or `resumeInstructions` (replaced by `currentFocus` + `nextAction`).

### If Initiative is Bloated

Call `initiative_slim({ archiveDetails: true })` to migrate. Archive saves to `~/.claude/memory/archives/`. Continue with slim initiative.
