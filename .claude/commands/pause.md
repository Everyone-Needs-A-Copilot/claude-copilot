# Pause Current Work

Create a named checkpoint of current work to enable easy resumption later.

## Command Argument Handling

This command supports an optional pause reason/name:

**Usage:**
- `/pause` - Pause with auto-generated name
- `/pause "switching to urgent bug"` - Pause with custom reason
- `/pause working on feature X, need to context switch` - Pause with description

## What This Does

This command creates explicit pause checkpoints for all in-progress tasks, making it easy to resume exactly where you left off even after working on other initiatives.

**Key differences from regular checkpoints:**
- **Explicit intent**: User-initiated pause vs automatic checkpoints
- **Extended expiry**: Manual checkpoints last longer than auto-checkpoints
- **Named/contextualized**: Optional reason helps recall context when resuming
- **Resume priority**: `/continue` checks pause checkpoints first

## Step 1: Get Current Initiative Context

```typescript
// Get current initiative to find active tasks
const initiative = await initiative_get({ mode: "lean" });

if (!initiative) {
  return "No active initiative found. Start work with /protocol first.";
}
```

## Step 2: Find In-Progress Tasks

```typescript
// Get all in-progress tasks across all PRDs in the initiative
const allTasks = await task_list({ status: 'in_progress' });

if (allTasks.length === 0) {
  return "No in-progress tasks to pause.";
}
```

## Step 3: Create Pause Checkpoints

For each in-progress task:

```typescript
const pauseReason = commandArg || `Paused at ${new Date().toLocaleString()}`;

for (const task of allTasks) {
  await checkpoint_create({
    taskId: task.id,
    trigger: 'manual',
    executionPhase: 'paused',
    executionStep: 0,
    agentContext: {
      pauseReason: pauseReason,
      pausedBy: 'user',
      pausedAt: new Date().toISOString(),
      initiativeId: initiative.id,
      initiativeTitle: initiative.title
    },
    expiresIn: 10080 // Extended expiry for manual checkpoints
  });
}
```

**Important:** The `expiresIn` parameter sets extended checkpoint expiry for manual pauses.

## Step 4: Update Initiative Context

```typescript
// Store pause context in Memory Copilot
await initiative_update({
  currentFocus: `Paused: ${pauseReason}`,
  nextAction: `Resume with /continue to restore paused tasks`,
  decisions: [{
    decision: `Paused work on ${allTasks.length} task(s)`,
    rationale: pauseReason
  }]
});
```

## Step 5: Return Confirmation

```typescript
return `
## Work Paused

**Reason:** ${pauseReason}

**Checkpoints Created:** ${allTasks.length} task(s)
${allTasks.map(t => `  - ${t.title} (${t.id})`).join('\n')}

**Expiry:** Extended (manual checkpoint)
**Resume:** Use \`/continue\` to resume from these checkpoints

All task states have been preserved. You can safely work on other initiatives.
`;
```

## Implementation Notes

### Pause Checkpoint Characteristics

Pause checkpoints are identified by:
- `trigger: 'manual'`
- `executionPhase: 'paused'`
- `agentContext.pausedBy: 'user'`
- `expiresIn: 10080` (extended expiry)

This allows `/continue` to detect and prioritize pause checkpoints.

### Multi-Task Pause Support

The command creates checkpoints for ALL in-progress tasks, not just one. This ensures:
- Complete state preservation across parallel streams
- No lost work when context switching
- Easy resume of entire work context

### Edge Cases

**No in-progress tasks:**
- Return friendly message: "No in-progress tasks to pause."
- Do NOT error - this is a valid state

**Task already has checkpoint:**
- Create new checkpoint (older ones auto-pruned per MAX_CHECKPOINTS_PER_TASK)
- Sequence number increments automatically

**Initiative switching:**
- Pause checkpoints survive initiative changes (extended expiry)
- `/continue` can find pause checkpoints from previous initiative
- User must explicitly link back to old initiative to access old pause checkpoints

## Example Output

**Successful pause:**
```
## Work Paused

**Reason:** Switching to urgent production bug

**Checkpoints Created:** 2 task(s)
  - Implement user authentication endpoint (TASK-abc123)
  - Add password reset flow (TASK-def456)

**Expiry:** Extended (manual checkpoint)
**Resume:** Use `/continue` to resume from these checkpoints

All task states have been preserved. You can safely work on other initiatives.
```

**No tasks to pause:**
```
No in-progress tasks to pause.

Tip: Use /protocol to start new work, or /continue to resume existing tasks.
```

## Integration with /continue

The `/continue` command checks for pause checkpoints BEFORE loading standard initiative context:

```typescript
// /continue enhancement (implemented separately)
const pauseCheckpoints = await findPauseCheckpoints();

if (pauseCheckpoints.length > 0) {
  // Show pause checkpoint resume options
  // User can choose to resume from pause or continue with standard flow
}
```

See `continue.md` for pause checkpoint detection logic.
