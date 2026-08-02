# Continue Previous Work

Resume a conversation by loading context from Memory Copilot and Task Copilot.

## Command Argument Handling

This command supports an optional stream name argument for resuming work on specific parallel streams:

**Usage:**
- `/continue` - Interactive mode (check pause checkpoints, then resume main initiative or select from streams)
- `/continue Stream-B` - Resume work on specific stream directly

## Step 0: Check for Paused Tasks (Priority Check)

**BEFORE loading standard context**, check for paused tasks:

```bash
tc task list --status paused --json
```

**If paused tasks found**, present resume options:

```
## Paused Work Detected

Found N paused task(s) from recent session:

1. <task title>
   Paused reason: <from task metadata.pauseReason if set>

2. <task title>
   ...

Options:
[1-N] Resume specific paused task
[c] Continue with standard resume (ignore paused work)
[s] Show all streams

Select option:
```

**User selections:**
- Number (1-N): Set the chosen task back to in_progress and begin work:
  ```bash
  tc task update <id> --status in_progress --json
  ```
- `c`: Proceed to standard resume flow (Step 1 below)
- `s`: Proceed to stream selection flow (Step 1 below, then stream list)

**If no paused tasks found**, proceed to standard resume flow.

**Auto-Detection Logic:**
When a stream argument is provided:

1. **Query stream details**:
   ```bash
   tc stream get Stream-B --json
   ```

2. **Setup git worktree isolation** (if parallel stream and worktree not already created):
   - Check if stream has `worktreePath` in metadata
   - If not and streamPhase is 'parallel':
     - Create worktree: `.claude/worktrees/{streamId}`
     - Create branch: `stream-{streamId}` (lowercase)
     - Update all stream tasks with worktree metadata:
       ```bash
       tc task update <id> --metadata '{"worktreePath": ".claude/worktrees/Stream-B", "branchName": "stream-b"}' --json
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

1. **Check for streams** in current project:
   ```bash
   tc stream list
   ```

   **Note:** `tc stream list` shows all current streams. There is no archived-stream concept in the current CLI; streams that are no longer relevant simply have no pending tasks.

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
   ```bash
   cc memory search "current focus"
   cc memory list --type context
   ```

   Recall recent context, decisions, and lessons. For a broad sweep, `cc memory list --type context` surfaces all current-focus entries.

2. **From Task Copilot** (work progress):
   ```bash
   tc progress
   ```
   Shows PRD counts, task status by stream, and totals.

3. **From Project Constitution** (if exists):
   - Try to read `CONSTITUTION.md` from project root
   - If exists: Inject into context, note `[Constitution: Active]`
   - If missing: Continue without it (graceful fallback), note `[Constitution: Not Found]`

4. If no context exists, ask user what they're working on and store the focus:
   ```bash
   cc memory store --type context "Focus: <what user described>"
   ```

**Important:** Do NOT load full task lists. Use `tc progress` for compact status.

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
| EXPERIENCE | UI, UX, feature, modal, form | @agent-sd → @agent-uxd → @agent-uids → @agent-uid |
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
- [From `tc progress` output]
```

**Do NOT list all completed/in-progress tasks.** That data lives in Task Copilot.

**Worktree Info:** If resuming a parallel stream, include the worktree path and branch name from `tc stream get` output.

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
- `tc task update <id> --status <status> --json` - Update task status
- `tc progress` - Check overall progress

Use Memory Copilot for permanent knowledge:
- `cc memory store --type decision "<content>"` - Strategic decisions
- `cc memory store --type lesson "<content>"` - Key learnings

## Worktree Management

Git worktrees provide complete isolation for parallel streams, eliminating file conflicts and enabling true concurrent development.

### Quick Reference: Common Worktree Commands

| Task | Command |
|------|---------|
| Resume parallel stream | `/continue Stream-B` (creates worktree if needed) |
| List all worktrees | `git worktree list` |
| Check stream completion | `tc stream get Stream-B --json` |
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

1. **Detects if worktree exists** via `tc stream get` (checks `worktreePath` and `branchName` fields in metadata)
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

```bash
# Verify completion
tc stream get Stream-B --json

# Then merge
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

```bash
# Store current focus and next action (100 chars max each)
cc memory store --type context "Focus: <brief description of current focus>. Next: TASK-xxx — <specific next step>"

# Store strategic decisions (one entry per decision)
cc memory store --type decision "<decision>: <rationale>"

# Store key learnings (one entry per lesson)
cc memory store --type lesson "<lesson> [context: <where it applies>]"
```

**Do NOT store in Memory Copilot:**
- `completed` - Lives in Task Copilot (task status = completed)
- `inProgress` - Lives in Task Copilot (task status = in_progress)
- `blocked` - Lives in Task Copilot (task status = blocked)
- `resumeInstructions` - Replaced by a context entry with current focus and next action

### Memory is Self-Trimming

Memory entries are stored as individual files (one per entry). There is no "bloated initiative" to slim — each `cc memory store` call creates a discrete file. Old or superseded context entries can be removed with `cc memory delete <uuid>` if needed. The next session's `cc memory search` naturally surfaces the most relevant recent entries.
