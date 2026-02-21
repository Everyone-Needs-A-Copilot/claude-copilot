# Worktree Isolation

**Status:** Implemented
**Version:** 1.0.0

---

## Overview

Worktree isolation enables tasks to run in dedicated git worktrees, providing complete filesystem isolation for parallel work. This eliminates file conflicts when multiple agents or streams are working simultaneously.

## Key Features

| Feature | Description |
|---------|-------------|
| **Automatic Lifecycle** | Worktrees are automatically created, merged, and cleaned up based on task status transitions |
| **Conflict Detection** | Merge conflicts are automatically detected and block task completion |
| **Manual Override** | Full set of tools for manual worktree management |
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
| **in_progress → completed** | Merge worktree branch into current branch, cleanup worktree | Metadata cleaned up |
| **Merge conflict** | Task blocked, conflict files recorded | `mergeConflicts[]`, `mergeConflictTimestamp` |

---

## Manual Worktree Management

### Create Worktree

Create a worktree for an existing task:

```typescript
await worktree_create({
  taskId: "TASK-xxx",
  baseBranch: "develop"  // Optional
});
```

**Returns:**
```json
{
  "taskId": "TASK-xxx",
  "worktreePath": "/project/.worktrees/TASK-xxx",
  "branchName": "task/task-xxx",
  "message": "Worktree created successfully"
}
```

### List Worktrees

View all active task worktrees:

```typescript
await worktree_list({});
```

**Returns:**
```json
{
  "worktrees": [
    {
      "taskId": "TASK-abc123",
      "taskTitle": "Implement feature X",
      "taskStatus": "in_progress",
      "worktreePath": "/project/.worktrees/TASK-abc123",
      "branchName": "task/task-abc123"
    }
  ],
  "totalCount": 1
}
```

### Merge Worktree

Manually merge a worktree branch:

```typescript
await worktree_merge({
  taskId: "TASK-xxx",
  targetBranch: "main"  // Optional, defaults to current
});
```

**Success Response:**
```json
{
  "taskId": "TASK-xxx",
  "merged": true,
  "message": "Merged TASK-xxx into main: ..."
}
```

**Conflict Response:**
```json
{
  "taskId": "TASK-xxx",
  "merged": false,
  "conflicts": ["src/auth.ts", "src/config.ts"],
  "message": "Merge conflicts detected: src/auth.ts, src/config.ts"
}
```

When conflicts occur:
- Task status → `blocked`
- `blockedReason` → "Merge conflicts detected: {files}"
- Metadata updated with `mergeConflicts` and `mergeConflictTimestamp`

### Cleanup Worktree

Remove worktree and delete branch:

```typescript
await worktree_cleanup({
  taskId: "TASK-xxx",
  force: false  // Optional, force removal even if dirty
});
```

**Returns:**
```json
{
  "taskId": "TASK-xxx",
  "worktreeRemoved": true,
  "branchDeleted": true,
  "message": "Worktree cleaned up successfully"
}
```

---

## Conflict Resolution

### Check Conflict Status

Get detailed conflict analysis:

```typescript
await worktree_conflict_status({
  taskId: "TASK-xxx"
});
```

**Returns:**
```json
{
  "taskId": "TASK-xxx",
  "hasConflicts": true,
  "conflicts": [
    {
      "file": "src/auth.ts",
      "type": "content",
      "hasConflictMarkers": true,
      "suggestedStrategy": "manual"
    },
    {
      "file": "src/config.ts",
      "type": "modify-delete",
      "hasConflictMarkers": false,
      "suggestedStrategy": "manual"
    }
  ],
  "summary": "2 content conflict(s)",
  "suggestedAction": "All conflicts require manual resolution. Edit files to remove conflict markers, then use worktree_conflict_resolve"
}
```

### Conflict Types

| Type | Description | Resolution Strategy |
|------|-------------|---------------------|
| `content` | Both sides modified same lines | Manual merge required |
| `add-add` | Same file added by both sides | Manual decision needed |
| `modify-delete` | One side deleted, other modified | Manual decision needed |
| `delete` | Both sides deleted (rare) | Manual decision needed |
| `rename` | File renamed differently | Manual merge required |

### Resolve Conflicts

After manually resolving conflicts (removing `<<<<<<<`, `=======`, `>>>>>>>` markers):

```typescript
await worktree_conflict_resolve({
  taskId: "TASK-xxx",
  strategy: "manual",  // or "ours" / "theirs" for automatic resolution
  targetBranch: "main"  // Optional
});
```

**Strategy Options:**

| Strategy | Behavior |
|----------|----------|
| `manual` | Verify conflicts are manually resolved, stage all files, complete merge |
| `ours` | Keep our changes (task branch), discard theirs (target branch) |
| `theirs` | Keep their changes (target branch), discard ours (task branch) |

**Success Response:**
```json
{
  "success": true,
  "completed": true,
  "resolvedFiles": ["src/auth.ts", "src/config.ts"],
  "message": "Merge successful. Resolved 2 file(s). Task completed and worktree cleaned up."
}
```

When successful:
- Task status → `completed`
- Worktree cleaned up automatically
- Conflict metadata removed

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

Before allowing conflict resolution to complete, the system verifies:

| Check | Purpose |
|-------|---------|
| No conflict markers | Files must not contain `<<<<<<<`, `=======`, `>>>>>>>` |
| All files staged | Resolved files must be added with `git add` |
| No remaining conflicts | `git diff --name-only --diff-filter=U` returns empty |
| Merge can complete | `git merge` completes successfully |

---

## Best Practices

### When to Use Worktrees

| Scenario | Use Worktree? |
|----------|--------------|
| Parallel stream work | ✅ Yes - prevents conflicts |
| High-complexity refactoring | ✅ Yes - isolates risky changes |
| Simple documentation updates | ❌ No - unnecessary overhead |
| Sequential task work | ❌ No - no conflict risk |

### Cleanup

Worktrees are automatically cleaned up on task completion. For manual cleanup:

1. **Before completion:** Use `worktree_cleanup` if you want to abandon changes
2. **Stale worktrees:** Use `worktree_list` to find orphaned worktrees, then cleanup

### Error Handling

If worktree operations fail:
- Task creation/update still succeeds (worktree is optional)
- Error logged to task notes
- Manual worktree tools can be used to recover

---

## CLI Reference

### All Worktree Tools

| Tool | Purpose | Required Args | Optional Args |
|------|---------|---------------|---------------|
| `worktree_create` | Create worktree for task | `taskId` | `baseBranch` |
| `worktree_list` | List all task worktrees | None | None |
| `worktree_merge` | Merge worktree branch | `taskId` | `targetBranch` |
| `worktree_cleanup` | Remove worktree & branch | `taskId` | `force` |
| `worktree_conflict_status` | Check conflict status | `taskId` | None |
| `worktree_conflict_resolve` | Resolve conflicts | `taskId` | `strategy`, `targetBranch` |

---

## Examples

### Complete Workflow

```bash
# 1. Create task with automatic worktree
tc task create --title "Refactor authentication" --prd <id> --json
# Set metadata: { requiresWorktree: true, complexity: "High" }

# 2. Start work (worktree created automatically)
tc task update <task-id> --status in_progress --json

# 3. Do work in .worktrees/TASK-xxx directory
# ...

# 4. Complete task (automatic merge & cleanup)
tc task update <task-id> --status completed --json

# If merge conflicts:
# 5. Check conflict details
worktree_conflict_status({ taskId: "<task-id>" })

# 6. Manually resolve conflicts in files
# ...

# 7. Resolve and complete
worktree_conflict_resolve({ taskId: "<task-id>", strategy: "manual" })
```

### Manual Worktree Management

```typescript
// Create worktree for existing task
await worktree_create({
  taskId: "TASK-existing",
  baseBranch: "feature/new-api"
});

// List all worktrees
const list = await worktree_list({});
console.log(list.worktrees);

// Manually merge when ready
const mergeResult = await worktree_merge({
  taskId: "TASK-existing",
  targetBranch: "develop"
});

if (mergeResult.merged) {
  // Success - cleanup
  await worktree_cleanup({ taskId: "TASK-existing" });
} else {
  // Handle conflicts
  console.log("Conflicts:", mergeResult.conflicts);
}
```

---

## Troubleshooting

### Worktree Already Exists

**Error:** "Worktree already exists for this task"

**Solution:** Use `worktree_list` to verify, then `worktree_cleanup` to remove if stale.

### Merge Conflicts

**Error:** Task blocked with merge conflicts

**Solution:**
1. Use `worktree_conflict_status` to see conflict details
2. Navigate to worktree path
3. Resolve conflicts manually (remove markers)
4. Use `worktree_conflict_resolve` with `strategy: "manual"`

### Stale Worktrees

**Error:** Git complains about existing worktree paths

**Solution:**
```bash
# List all worktrees
git worktree list

# Remove stale worktree manually
git worktree remove --force /path/to/worktree

# Or use Task Copilot
await worktree_cleanup({ taskId: "TASK-xxx", force: true });
```

### Cannot Delete Branch

**Error:** Branch deletion fails during cleanup

**Solution:**
- Branch may have unmerged changes
- Use `force: true` in `worktree_cleanup` to force deletion
- Or manually: `git branch -D task/task-xxx`

---

## Migration Guide

### From Manual Worktree Management

If you were managing worktrees manually:

1. **Update task metadata** to include `requiresWorktree: true`
2. **Use `tc task update`** status transitions instead of manual git commands
3. **Conflict resolution** now handled via `worktree_conflict_resolve`

### From No Worktrees

To start using worktrees:

1. **Update task templates** to include `requiresWorktree: true` for parallel work
2. **No code changes** required - lifecycle is automatic
3. **Existing tasks** can opt-in using `worktree_create`

---

## See Also

- [Stream System](./01-streams.md) - Parallel work streams that benefit from worktree isolation
- [Task Lifecycle](../20-architecture/02-task-lifecycle.md) - Complete task status transition flow
- [Quality Gates](./04-quality-gates.md) - Pre-merge validation
