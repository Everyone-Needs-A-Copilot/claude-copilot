# Orchestration Troubleshooting Guide

Diagnosing and fixing common issues with the native `/orchestrate` model: `tc` CLI, `git worktree`, and Claude Code `Task` agents.

---

## Pre-Orchestration Checklist

Run these checks before starting orchestration to catch problems early.

### Required Tools

- [ ] **Claude CLI in PATH**
  ```bash
  which claude
  # Must return a path, e.g. /opt/homebrew/bin/claude
  ```

- [ ] **Git version >= 2.5** (for worktree support)
  ```bash
  git --version
  ```

- [ ] **`cc` and `tc` CLIs installed**
  ```bash
  cc --version
  tc version
  ```

- [ ] **Framework up to date**
  ```bash
  cd ~/.claude/copilot && git log --oneline -1
  ```

- [ ] **Project up to date**
  ```bash
  /update-project
  ```

### Git State

- [ ] **Working directory clean** (or changes stashed)
  ```bash
  git status
  # Should show: "nothing to commit, working tree clean"
  ```

- [ ] **On intended branch** (not main if streaming feature work)
  ```bash
  git branch --show-current
  ```

---

## Common Issues

### Issue 1: "No streams found" on `/orchestrate start`

#### Symptom
`/orchestrate start` reports no streams exist.

#### Cause
`/orchestrate generate` was not run, or `@agent-ta` returned markdown instead of calling `tc task create` / `tc prd create`.

#### Solution
```bash
# Verify streams exist
tc stream list --json

# If empty, re-run generate
/orchestrate generate

# Confirm tasks were actually created (not just described in markdown)
tc stream list --json
tc task list --json
```

---

### Issue 2: File Overlap Detected Between Streams

#### Symptom
`/orchestrate start` stops with a file overlap error.

#### Cause
Two or more streams declare the same file in their `files` metadata. The conflict check prevents this before worktrees are created.

#### Solution
Restructure the stream plan so each file belongs to exactly one stream. Options:
- Move the shared file to a foundation stream that upstream streams depend on.
- Merge the two conflicting streams into one.

Then re-run `/orchestrate generate` to recreate tasks with the corrected metadata.

---

### Issue 3: Circular Dependency Detected

#### Symptom
`/orchestrate generate` or `start` reports a dependency cycle.

#### Cause
Stream A depends on Stream B, and Stream B depends on Stream A (directly or transitively).

#### Diagnosis
```bash
tc stream list --json
# Inspect streamDependencies for each stream
```

#### Solution
Identify the true starting point and set its `dependencies` to `[]`. Then update the task metadata:
```bash
tc task list --stream Stream-A --json
tc task update <task-id> --status pending --json
# Set metadata.streamDependencies to [] for the foundation stream's tasks
```

---

### Issue 4: Stale or Broken Git Worktree

#### Symptom
`git worktree add` fails saying the path already exists, or a worktree directory exists but `git worktree list` does not show it.

#### Diagnosis
```bash
git worktree list
# List all registered worktrees

ls -la .worktrees/
# Check what directories exist on disk
```

#### Solution

**Prune stale references first:**
```bash
git worktree prune
git worktree list
```

**Remove a specific broken worktree:**
```bash
git worktree remove --force .worktrees/<stream-id>
```

**If the directory still exists after removal:**
```bash
rm -rf .worktrees/<stream-id>
git worktree prune
```

**Recreate cleanly:**
```bash
git worktree add .worktrees/<stream-id> -b stream/<stream-id>
```

---

### Issue 5: Merge Conflicts on `/orchestrate merge`

#### Symptom
`/orchestrate merge` reports conflicts on one or more stream branches.

#### Diagnosis
```bash
# After a failed merge attempt, check which files conflict
git status
git diff --name-only --diff-filter=U
```

#### Solution

**Resolve manually:**
```bash
# Open conflicting files, edit to resolve
git add <resolved-files>
git commit -m "Merge stream/<stream-id>: resolve conflicts"
```

**Then clean up the worktree:**
```bash
git worktree remove .worktrees/<stream-id>
git branch -d stream/<stream-id>
```

**Prevention:** Run `/orchestrate merge` promptly after each stream completes. Long-lived worktrees diverge from main and accumulate conflicts.

---

### Issue 6: Stream Dependency Not Progressing (Waiting Forever)

#### Symptom
A downstream stream never starts — its dependency stream appears stuck at incomplete.

#### Diagnosis
```bash
# Check stream and task statuses
tc stream list --json
tc task list --stream Stream-A --json
tc progress --json
```

**Look for:** tasks in `in_progress` state that are not advancing, or tasks that completed without being marked `completed`.

#### Solution

**If tasks finished but were not marked complete:**
```bash
# Manually mark tasks completed
tc task update <task-id> --status completed --json
```

**If dependency ordering is wrong:**
```bash
# Verify which streams are ready
tc stream list --json
# A stream is ready when all streams in its dependencies[] are 100% complete
```

---

### Issue 7: `tc` CLI Returns Errors or Inconsistent Data

#### Symptom
`tc task list` or `tc stream list` returns errors, empty results, or data from a different workspace.

#### Diagnosis
```bash
tc progress --json
# Check workspace identifier in output

tc task list --json
# Verify tasks exist and are scoped to this project
```

#### Solution

**If scoped to wrong workspace:** The `tc` CLI scopes data by project directory. Verify you are in the correct project root before running orchestrate commands.

**If database is corrupted:**
```bash
# Backup first
cp ~/.claude/tasks/$(basename $(pwd)).db ~/.claude/tasks/$(basename $(pwd)).db.backup

# Delete and re-generate
rm ~/.claude/tasks/$(basename $(pwd)).db
/orchestrate generate
```

---

## Recovery Procedures

### Clean Up Failed Worktrees

When orchestration failed mid-setup and worktrees are in a bad state:

```bash
# Prune all stale worktree references
git worktree prune

# Force-remove any remaining worktrees
git worktree list | grep '.worktrees/' | awk '{print $1}' | \
  xargs -I {} git worktree remove {} --force 2>/dev/null || true

# Remove orphaned directories
rm -rf .worktrees/

# Delete stream branches (optional — for a clean restart)
git branch | grep 'stream/' | xargs -I {} git branch -D {} 2>/dev/null || true

# Verify clean state
git worktree list
```

### Reset Stream Task Statuses

When you need to restart orchestration without re-running `generate`:

```bash
# List all tasks
tc task list --json

# Reset each in-progress or stuck task to pending
tc task update <task-id> --status pending --json
```

### Full Restart from Scratch

```bash
# 1. Clean up worktrees (see above)

# 2. Reset task statuses to pending
tc task list --json
# Run: tc task update <id> --status pending --json  for each task

# 3. Start fresh
/orchestrate start
```

---

## Diagnostic Commands

```bash
# Stream and task status
tc stream list --json
tc task list --json
tc progress --json

# Git worktree state
git worktree list
git worktree prune --dry-run

# Preflight: verify required tools
which claude && echo "claude OK" || echo "claude NOT FOUND"
which tc && echo "tc OK" || echo "tc NOT FOUND"
which cc && echo "cc OK" || echo "cc NOT FOUND"
git --version
```

---

## See Also

- **Workflow Guide:** [01-orchestration-workflow.md](./01-orchestration-workflow.md)
- **Worktree Isolation:** [05-worktree-isolation.md](./05-worktree-isolation.md)

---

*Updated: June 2026 — Rewritten for native Task model; Python orchestrator retired*
