# Worktree Isolation

**Status:** Implemented
**Version:** 1.0.0

---

## Overview

Worktree isolation enables tasks to run in dedicated git worktrees, providing complete filesystem isolation for parallel work. This eliminates file conflicts when multiple agents or streams are working simultaneously.

## Key Features

| Feature | Description |
|---------|-------------|
| **Filesystem Isolation** | Each task or stream works in its own directory with no cross-contamination |
| **Parallel Safety** | Multiple agents or streams can work simultaneously without file conflicts |
| **Branch Isolation** | Each worktree operates on its own git branch |
| **Metadata Tracking** | Worktree path and branch name stored in task metadata |

---

## Automatic Worktree Lifecycle

### Enabling Automatic Worktrees

Set `requiresWorktree: true` in task metadata during task creation:

```bash
tc task create --title "Refactor authentication module" --prd <id> --json
# Set metadata: { requiresWorktree: true, worktreeBaseBranch: "develop" }
```

### Lifecycle Stages

| Status Transition | Action | Metadata Updated |
|------------------|--------|------------------|
| **pending → in_progress** | Create worktree at `.worktrees/{TASK-xxx}` with branch `task/{task-xxx}` | `worktreePath`, `branchName`, `isolatedWorktree` |
| **in_progress → completed** | Merge worktree branch into target branch, cleanup worktree | Metadata cleaned up |
| **Merge conflict** | Task blocked, conflict files recorded | `mergeConflicts[]`, `mergeConflictTimestamp` |

---

## Git Command Reference

All worktree operations use standard `git worktree` commands. There are no MCP tools for worktree management — use git directly.

| Operation | Command |
|-----------|---------|
| Create worktree | `git worktree add .worktrees/<task-id> -b <branch>` |
| List worktrees | `git worktree list` |
| Remove worktree | `git worktree remove .worktrees/<task-id>` |
| Force remove | `git worktree remove --force .worktrees/<task-id>` |
| Prune stale refs | `git worktree prune` |
| Merge branch | `git merge <branch> --no-ff -m "Merge <task-id>: <title>"` (run from target branch) |
| Delete branch | `git branch -d <branch>` |
| Check conflicts | `git status` / `git diff --name-only --diff-filter=U` |

---

## Manual Worktree Management

### Create Worktree

Create a worktree for an existing task:

```bash
git worktree add .worktrees/TASK-xxx -b task/task-xxx
```

To branch from a specific base:

```bash
git worktree add .worktrees/TASK-xxx -b task/task-xxx develop
```

### List Worktrees

View all active worktrees:

```bash
git worktree list
```

Example output:
```
/project                           abc1234 [main]
/project/.worktrees/TASK-abc123    def5678 [task/task-abc123]
/project/.worktrees/TASK-def456    ghi9012 [task/task-def456]
```

### Merge Worktree

Merge a worktree branch back into the target branch:

```bash
# Switch to target branch first
git checkout main

# Merge with no-fast-forward to preserve history
git merge task/task-xxx --no-ff -m "Merge TASK-xxx: Refactor authentication"
```

**If conflicts occur:**
- Git reports the conflicting files
- Task status → `blocked`
- Worktree is preserved for manual resolution (see Conflict Resolution below)

### Cleanup Worktree

Remove worktree directory and delete the branch after a successful merge:

```bash
# Remove the worktree directory
git worktree remove .worktrees/TASK-xxx

# Delete the branch
git branch -d task/task-xxx
```

Force-remove a dirty worktree:

```bash
git worktree remove --force .worktrees/TASK-xxx
git branch -D task/task-xxx
```

---

## Conflict Resolution

When `git merge` encounters conflicts, the merge pauses and leaves conflict markers in the affected files. There is no automated tool for this — resolution is a manual git workflow.

### Check Conflict Status

```bash
# See overall status (shows conflicted files as "both modified" / "UU")
git status

# List only unmerged files
git diff --name-only --diff-filter=U
```

### Conflict Types

| Type | Description | Resolution |
|------|-------------|------------|
| Content conflict | Both sides modified the same lines | Edit files to remove markers, then `git add` |
| Add-add | Same file added by both sides | Keep desired version, then `git add` |
| Modify-delete | One side deleted, other modified | Decide which intent wins, then `git add` or `git rm` |
| Rename conflict | File renamed differently on each side | Resolve the rename, then `git add` |

### Manual Resolution Steps

1. Open each conflicting file and remove the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`)
2. Edit the file to reflect the correct merged result
3. Stage the resolved file:
   ```bash
   git add src/auth.ts
   ```
4. Repeat for all conflicting files
5. Complete the merge commit:
   ```bash
   git commit
   ```
6. Update task status and clean up worktree:
   ```bash
   tc task update TASK-xxx --status completed --json
   git worktree remove .worktrees/TASK-xxx
   git branch -d task/task-xxx
   ```

---

## Task Metadata

### Worktree-Related Fields

| Field | Type | Description | Set By |
|-------|------|-------------|--------|
| `requiresWorktree` | `boolean` | Enable automatic worktree creation | User (tc task create) |
| `worktreeBaseBranch` | `string` | Base branch to branch from | User (optional) |
| `isolatedWorktree` | `boolean` | Indicates task uses worktree | System (auto-set) |
| `worktreePath` | `string` | Filesystem path to worktree | System (auto-set) |
| `branchName` | `string` | Git branch name for worktree | System (auto-set) |
| `mergeConflicts` | `string[]` | List of files with conflicts | System (on conflict) |
| `mergeConflictTimestamp` | `string` | When conflict was detected | System (on conflict) |

### Example Task Metadata

**Initial (requiresWorktree set):**
```json
{
  "requiresWorktree": true,
  "worktreeBaseBranch": "develop",
  "complexity": "High"
}
```

**After worktree creation:**
```json
{
  "requiresWorktree": true,
  "worktreeBaseBranch": "develop",
  "isolatedWorktree": true,
  "worktreePath": "/project/.worktrees/TASK-abc123",
  "branchName": "task/task-abc123",
  "complexity": "High"
}
```

**On merge conflict:**
```json
{
  "requiresWorktree": true,
  "worktreeBaseBranch": "develop",
  "isolatedWorktree": true,
  "worktreePath": "/project/.worktrees/TASK-abc123",
  "branchName": "task/task-abc123",
  "mergeConflicts": ["src/auth.ts", "src/config.ts"],
  "mergeConflictTimestamp": "2024-01-15T10:30:00.000Z",
  "complexity": "High"
}
```

---

## Integration with Streams

Worktrees work seamlessly with parallel streams:

```bash
# Stream-A tasks can work in isolation
tc task create --title "Implement API endpoints" --prd <id> --json
# metadata: { streamId: "Stream-A", streamName: "api-implementation", requiresWorktree: true }

# Stream-B tasks can work simultaneously without conflicts
tc task create --title "Add UI components" --prd <id> --json
# metadata: { streamId: "Stream-B", streamName: "ui-components", requiresWorktree: true }
```

Each stream task gets its own isolated worktree, preventing file conflicts.

---

## Worktree Structure

### File System Layout

```
/project-root
├── .worktrees/                    # Worktree base directory
│   ├── TASK-abc123/              # Task-specific worktree
│   │   ├── src/                  # Isolated copy of source
│   │   ├── package.json          # Project files
│   │   └── ...
│   └── TASK-def456/              # Another task's worktree
└── ... (main repo files)
```

### Git Branch Naming

- **Pattern:** `task/{task-id-lowercase}`
- **Example:** `task/task-abc123` for `TASK-abc123`

---

## Limitations

1. **Git dependency**: Requires git to be available and the working directory to be a git repo
2. **Disk space**: Each worktree is a full checkout (uses more disk space)
3. **Manual conflicts**: Merge conflicts require manual resolution
4. **No nested worktrees**: Cannot create a worktree of a worktree

---

## Integration Notes

### Auto-Commit

Worktree isolation works seamlessly with auto-commit:

```typescript
{
  requiresWorktree: true,
  autoCommit: true,           // Still works in worktree context
  filesModified: ['src/...']  // Auto-commits within the worktree
}
```

### Checkpoints

Checkpoints preserve worktree metadata (`worktreePath` and `branchName`). On resume, the worktree state is restored.

### Conflict Resolution Validation

Before completing a conflict resolution, verify manually:

| Check | How to Verify |
|-------|---------------|
| No conflict markers | Search files for `<<<<<<<`, `=======`, `>>>>>>>` |
| All files staged | `git status` shows no untracked/modified files |
| No remaining conflicts | `git diff --name-only --diff-filter=U` returns empty |
| Merge can complete | `git commit` completes successfully |

---

## Best Practices

### When to Use Worktrees

| Scenario | Use Worktree? |
|----------|--------------|
| Parallel stream work | Yes - prevents conflicts |
| High-complexity refactoring | Yes - isolates risky changes |
| Simple documentation updates | No - unnecessary overhead |
| Sequential task work | No - no conflict risk |

### Cleanup

Worktrees are automatically cleaned up on task completion. For manual cleanup:

1. **Before completion:** Use `git worktree remove --force` to abandon changes
2. **Stale worktrees:** Use `git worktree list` to find orphaned worktrees, then `git worktree remove` + `git worktree prune`

### Error Handling

If worktree operations fail:
- Task creation/update still succeeds (worktree is optional)
- Error logged to task notes
- Manual git commands can be used to recover

---

## Complete Workflow Example

```bash
# 1. Create task with automatic worktree
tc task create --title "Refactor authentication" --prd <id> --json
# Set metadata: { requiresWorktree: true, complexity: "High" }

# 2. Start work (worktree created automatically)
tc task update <task-id> --status in_progress --json

# 3. Do work in .worktrees/TASK-xxx directory
cd .worktrees/TASK-xxx
# ... make changes ...
git add .
git commit -m "feat: refactor auth module"

# 4. Complete task (triggers automatic merge & cleanup)
cd /project-root
tc task update <task-id> --status completed --json

# If merge conflicts arise:
# 5. Check which files conflict
git status
git diff --name-only --diff-filter=U

# 6. Open each conflicting file, remove markers, save correct result
# (edit files manually)

# 7. Stage resolved files and complete the merge
git add src/auth.ts src/config.ts
git commit

# 8. Clean up worktree
git worktree remove .worktrees/TASK-xxx
git branch -d task/task-xxx
```

---

## Troubleshooting

### Worktree Already Exists

**Error:** "fatal: 'TASK-xxx' already exists"

**Solution:**
```bash
# List all worktrees to verify
git worktree list

# Remove stale worktree if needed
git worktree remove --force .worktrees/TASK-xxx
git worktree prune
```

### Merge Conflicts

**Error:** Task blocked with merge conflicts

**Solution:**
1. `git status` to see conflicting files
2. Navigate to the worktree path
3. Resolve conflicts manually (remove markers, edit to desired result)
4. `git add <resolved-files>` and `git commit`
5. Update task status and clean up

### Stale Worktrees

**Error:** Git complains about existing worktree paths

**Solution:**
```bash
# List all worktrees
git worktree list

# Prune stale references (safe - only removes stale metadata)
git worktree prune

# Remove specific stale worktree
git worktree remove --force /path/to/worktree
```

### Cannot Delete Branch

**Error:** Branch deletion fails during cleanup

**Solution:**
- Branch may have unmerged changes
- Force-delete with `git branch -D task/task-xxx` if changes are already merged or abandoned

---

## Migration Guide

### From No Worktrees

To start using worktrees:

1. **Update task templates** to include `requiresWorktree: true` for parallel work
2. **No code changes** required - lifecycle is automatic
3. **Existing tasks** can opt-in by setting `isolatedWorktree: true` in metadata and creating the worktree manually with `git worktree add`

---

## See Also

- [Orchestration Workflow](./01-orchestration-workflow.md) - Parallel work streams that benefit from worktree isolation
- [Enhancement Features](./00-enhancement-features.md) - Quality gates and other agent reliability features
