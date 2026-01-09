# Auto-Commit on Task Completion

## Overview

The auto-commit feature signals to calling agents when a task completion should trigger a git commit. When enabled, `task_update` returns a flag and suggested commit message, allowing the agent to create a checkpoint commit for the completed task.

## How It Works

When `task_update` marks a task as `completed`:

1. **Check if enabled**: Verify `metadata.autoCommitOnComplete === true`
2. **Check transition**: Only on transition TO completed (not when already completed)
3. **Return flag**: Set `autoCommitRequested: true` in response
4. **Provide message**: Include `suggestedCommitMessage` with task ID and title
5. **Agent handles commit**: Calling agent performs git operations

## Configuration

### Task Metadata Fields

```typescript
interface TaskMetadata {
  // Request auto-commit when task transitions to completed (default: false, opt-in)
  autoCommitOnComplete?: boolean;

  // Files to stage and commit (optional, for agent reference)
  filesModified?: string[];
}
```

### Default Behavior

- `autoCommitOnComplete` defaults to `false` (opt-in feature)
- Only triggers on transition TO completed status (not when already completed)
- Returns flag in response, does not execute git commands
- Agent is responsible for performing git commit

## Usage Examples

### Enable Auto-Commit (Opt-in)

```typescript
const result = await task_update({
  id: 'TASK-123',
  status: 'completed',
  metadata: {
    autoCommitOnComplete: true,
    filesModified: [
      'src/tools/task.ts',
      'src/types.ts'
    ]
  }
});

// Result includes:
// {
//   id: 'TASK-123',
//   status: 'completed',
//   updatedAt: '2025-01-08T10:30:00.000Z',
//   autoCommitRequested: true,
//   suggestedCommitMessage: 'feat(TASK-123): Implement auto-commit feature'
// }

// Agent then performs git commit:
if (result.autoCommitRequested) {
  await exec(`git add ${metadata.filesModified.join(' ')}`);
  await exec(`git commit -m "${result.suggestedCommitMessage}"`);
}
```

### Disable Auto-Commit (Default)

```typescript
await task_update({
  id: 'TASK-456',
  status: 'completed',
  metadata: {
    // autoCommitOnComplete: false (default)
    filesModified: ['README.md']
  }
});

// Result does NOT include autoCommitRequested flag
// {
//   id: 'TASK-456',
//   status: 'completed',
//   updatedAt: '2025-01-08T10:30:00.000Z'
// }
```

### Already Completed Task

```typescript
await task_update({
  id: 'TASK-789',
  status: 'completed', // Already completed
  metadata: {
    autoCommitOnComplete: true
  }
});

// Result does NOT include autoCommitRequested (no transition)
```

## Commit Message Format

### Suggested Commit Message

The `suggestedCommitMessage` field returns:

```
feat(TASK-{id}): {task title}
```

**Example:**
```
feat(TASK-419ae33f-a31b-4ef9-832f-b813bee8035b): Implement auto-commit on task completion
```

### Agent Customization

Agents can customize the commit message and body:

```typescript
// Basic usage (use suggested message as-is)
await exec(`git commit -m "${result.suggestedCommitMessage}"`);

// Custom body with work products
const workProducts = await work_product_list({ taskId });
const body = `
Task ID: ${taskId}
Work Products: ${workProducts.map(wp => wp.id).join(', ')}
Files Modified: ${metadata.filesModified.length} file(s)
`;
await exec(`git commit -m "${result.suggestedCommitMessage}" -m "${body}"`);
```

## Edge Cases & Behavior

### Already Completed Task

**Scenario:** Updating a task that's already in `completed` status

**Behavior:**
- No `autoCommitRequested` flag returned
- Agent does not perform commit
- Prevents duplicate commits for same task

### Missing autoCommitOnComplete

**Scenario:** Task metadata does not include `autoCommitOnComplete` field

**Behavior:**
- Defaults to `false` (opt-in feature)
- No `autoCommitRequested` flag returned
- Agent does not perform commit

### Agent Responsibility

**Important:** The MCP server only returns a flag. The calling agent must:
1. Check if `autoCommitRequested === true` in response
2. Stage files from `metadata.filesModified` (if provided)
3. Execute git commit with `suggestedCommitMessage`
4. Handle all git errors gracefully
5. Update task notes with commit SHA (optional)

## Integration with Task Copilot

### Task Update Flow

```
task_update(status: 'completed')
  ↓
Check verification requirements
  ↓
Check quality gates
  ↓
Record performance
  ↓
Create auto-checkpoint
  ↓
Check auto-commit request
  ↓
Return response with autoCommitRequested flag
  ↓
Agent performs git commit (if requested)
```

### Response Structure

When auto-commit is requested, `task_update` returns:

```typescript
{
  id: string;
  status: 'completed';
  updatedAt: string;
  autoCommitRequested: true;
  suggestedCommitMessage: string;
}
```

When auto-commit is NOT requested:

```typescript
{
  id: string;
  status: 'completed';
  updatedAt: string;
  // No autoCommitRequested field
}
```

## Best Practices

### When to Use

✅ **Good use cases:**
- Feature implementations with clear file changes
- Bug fixes modifying specific files
- Refactoring with known scope
- Tasks with automated testing (can verify before commit)

❌ **Not recommended:**
- Exploratory work (scope unclear)
- Multi-stage tasks (commit per stage instead)
- Tasks with no file changes (analysis, planning)
- Tasks requiring manual commit message customization

### Enabling Auto-Commit

**Recommended approach:**
```typescript
// Set autoCommitOnComplete when creating task
await task_create({
  title: 'Implement user authentication',
  metadata: {
    autoCommitOnComplete: true,
    filesModified: [
      'src/auth/login.ts',
      'src/auth/login.test.ts'
    ]
  }
});

// On completion, handle auto-commit request
const result = await task_update({
  id: taskId,
  status: 'completed'
});

if (result.autoCommitRequested) {
  // Stage files and commit
  const files = metadata.filesModified || [];
  await exec(`git add ${files.join(' ')}`);
  await exec(`git commit -m "${result.suggestedCommitMessage}"`);
}
```

### When to Disable

Don't set `autoCommitOnComplete: true` when:
- You want to manually craft the commit message
- Multiple tasks contribute to one logical commit
- Working in a shared branch (need to coordinate commits)
- Task is part of larger PR scope requiring custom commit history

## Implementation Details

### Task Update Integration

Located: `src/tools/task.ts`

**In `taskUpdate()` function:**

**Flow:**
1. Check if status is transitioning TO `completed` (not already completed)
2. Parse updated task metadata
3. Check if `metadata.autoCommitOnComplete === true`
4. If yes, set response flags:
   - `autoCommitRequested: true`
   - `suggestedCommitMessage: "feat(TASK-xxx): {title}"`
5. Return response to calling agent

**Code snippet:**
```typescript
// Check if auto-commit is requested on completion
let autoCommitRequested = false;
let suggestedCommitMessage: string | undefined;

if (input.status === 'completed' && task.status !== 'completed') {
  // Task is transitioning TO completed (not already completed)
  const updatedMetadata = JSON.parse(updates.metadata || task.metadata) as TaskMetadata;

  // Check if autoCommitOnComplete is enabled
  if (updatedMetadata.autoCommitOnComplete === true) {
    autoCommitRequested = true;
    suggestedCommitMessage = `feat(${input.id}): ${task.title}`;
  }
}

return {
  id: input.id,
  status: (input.status || task.status) as TaskStatus,
  updatedAt: now,
  ...(autoCommitRequested && {
    autoCommitRequested,
    suggestedCommitMessage
  })
};
```

### Agent Implementation

Agents should implement the git commit logic:

```typescript
// After task_update call
if (result.autoCommitRequested) {
  try {
    // Stage files from metadata
    const files = taskMetadata.filesModified || [];
    if (files.length > 0) {
      await exec(`git add ${files.join(' ')}`);
    }

    // Create commit with suggested message
    await exec(`git commit -m "${result.suggestedCommitMessage}"`);

    // Optionally update task notes with commit SHA
    const { stdout } = await exec('git rev-parse HEAD');
    const commitSha = stdout.trim().substring(0, 7);
    await task_update({
      id: taskId,
      notes: `${existingNotes}\n\nCommitted: ${commitSha}`
    });
  } catch (error) {
    // Handle git errors gracefully
    console.warn('Auto-commit failed:', error);
  }
}
```

## Testing

### Unit Tests

Test the flag return behavior in `task.ts`:

**Test cases:**
- Task transitioning to completed with `autoCommitOnComplete: true` → Returns flag
- Task already completed → Does NOT return flag
- Task with `autoCommitOnComplete: false` → Does NOT return flag
- Task with missing `autoCommitOnComplete` → Does NOT return flag
- Suggested message format matches `feat(TASK-xxx): {title}`

### Integration Testing

**Manual test procedure:**

1. Create task with auto-commit enabled:
   ```typescript
   const task = await task_create({
     title: 'Test auto-commit flag',
     metadata: {
       autoCommitOnComplete: true,
       filesModified: ['test.txt']
     }
   });
   ```

2. Create test file:
   ```bash
   echo "test content" > test.txt
   ```

3. Complete task and check response:
   ```typescript
   const result = await task_update({
     id: task.id,
     status: 'completed'
   });

   console.log(result);
   // Should include:
   // {
   //   autoCommitRequested: true,
   //   suggestedCommitMessage: "feat(TASK-xxx): Test auto-commit flag"
   // }
   ```

4. Agent performs commit:
   ```bash
   git add test.txt
   git commit -m "feat(TASK-xxx): Test auto-commit flag"
   ```

5. Verify commit:
   ```bash
   git log -1 --pretty=format:"%s"
   # Expected: feat(TASK-xxx): Test auto-commit flag
   ```

## Future Enhancements

### Potential Improvements

1. **Automatic file detection**: Track files modified during task execution (via git diff)
2. **Commit templates**: Customize commit format per project/agent
3. **Branch integration**: Auto-create branch per task/stream
4. **PR automation**: Auto-create PR when task completed
5. **Rollback support**: Revert task commit if task reopened
6. **Multi-commit support**: Multiple commits per task for large changes
7. **Commit body templates**: Standardized body format with work products, tests, etc.

### Configuration Options (Future)

Could add to task metadata:

```typescript
interface TaskMetadata {
  autoCommitOnComplete?: boolean;
  autoCommitConfig?: {
    commitType: 'feat' | 'fix' | 'refactor' | 'docs' | 'test';
    includeWorkProducts: boolean;
    includeTestStatus: boolean;
    customBody?: string;
  };
}
```

## Troubleshooting

### Flag not returned when expected

**Cause:** Task metadata missing `autoCommitOnComplete: true`

**Solution:**
```typescript
await task_update({
  id: taskId,
  status: 'completed',
  metadata: {
    autoCommitOnComplete: true  // Must be explicitly set
  }
});
```

### Flag returned but agent doesn't commit

**Cause:** Agent not checking `autoCommitRequested` in response

**Solution:** Implement git commit logic in agent:
```typescript
const result = await task_update({ id, status: 'completed' });
if (result.autoCommitRequested) {
  // Add git commit logic here
}
```

### Task already completed, no flag returned

**Cause:** Task status was already `completed`, no transition occurred

**Solution:** This is expected behavior. Auto-commit only triggers on status transition TO completed, preventing duplicate commits.

### Agent git commit fails

**Cause:** Git errors (not staged, conflicts, etc.)

**Solution:** Agent should handle git errors gracefully:
```typescript
try {
  await exec(`git commit -m "${message}"`);
} catch (error) {
  console.warn('Auto-commit failed:', error);
  // Optionally update task notes with error
}
```

## Related Features

- **Quality Gates**: Auto-commit happens after quality gates pass
- **Verification Rules**: Auto-commit happens after verification passes
- **Checkpoints**: Auto-checkpoint created after auto-commit
- **Performance Tracking**: Commit success tracked in agent performance
- **Stream Isolation**: Each stream can have independent commits

## References

- Git Conventional Commits: https://www.conventionalcommits.org/
- Task Copilot Architecture: `../README.md`
- Quality Gates: `./QUALITY_GATES.md`
- Verification Rules: `./VERIFICATION.md`
