# Memory Dashboard

Display current memory state from Memory Copilot for transparency and debugging.

## Step 1: Retrieve Memory Data

Call these tools to gather memory state:

1. **Get current initiative:**
   ```
   initiative_get()
   ```

2. **Get recent memories:**
   ```
   memory_list({ limit: 10 })
   ```

3. **Get agent improvement suggestions:**
   ```
   memory_list({ type: 'agent_improvement', limit: 20 })
   ```

4. **If Task Copilot is linked, get progress:**
   ```
   progress_summary()
   ```

## Step 2: Display Dashboard

Format the output as a clean, scannable dashboard:

```
## Memory Dashboard

**Initiative:** [name]
**Status:** [status - IN PROGRESS / COMPLETED / BLOCKED]

**Focus:** [currentFocus]
**Next:** [nextAction]

### Recent Decisions
[List last 3-5 decisions, or "None recorded"]

### Recent Lessons
[List last 3-5 lessons, or "None recorded"]

### Key Files
[List keyFiles, or "None tracked"]

### Recent Memories (Last 10)
[Table format:]
Type       | Content Preview                    | Created
---------- | ---------------------------------- | ----------
decision   | [First 50 chars...]                | 2025-01-15
lesson     | [First 50 chars...]                | 2025-01-14

### Agent Improvements
[If agent improvements exist, show summary:]
**Pending:** [count] | **Approved:** [count] | **Rejected:** [count]

[Table format for pending suggestions:]
Agent | Section           | Rationale                           | Created
----- | ----------------- | ----------------------------------- | ----------
me    | Core Behaviors    | [First 40 chars...]                 | 2025-01-15
ta    | Output format     | [First 40 chars...]                 | 2025-01-14

[If no improvements: "No agent improvements recorded"]

**Storage:** ~/.claude/memory/[workspace-id]/memory.db
**Workspace ID:** [workspace-id or "auto-generated hash"]

### Task Progress (if Task Copilot linked)
[Show output from progress_summary(), or skip section if not linked]
PRDs: [count] | Tasks: [pending/in_progress/completed] | Work Products: [count]
```

## Step 3: Handle Edge Cases

### No Active Initiative

If `initiative_get` returns null or no initiative exists:
```
## Memory Dashboard

**Status:** No active initiative

Use `/protocol` to start fresh work or `/continue` to resume.

**Storage:** ~/.claude/memory/[workspace-id]/memory.db
```

### No Memories

If `memory_list` returns empty:
```
### Recent Memories
No memories stored yet.
```

### No Agent Improvements

If `memory_list({ type: 'agent_improvement' })` returns empty:
```
### Agent Improvements
No agent improvements recorded
```

### Bloated Initiative Warning

If the initiative contains legacy fields (`completed`, `inProgress`, `blocked`, `resumeInstructions`):

```
**WARNING:** This initiative uses legacy format with bloated task lists.
Consider running `initiative_slim({ archiveDetails: true })` to reduce context usage by ~75%.
```

## Display Notes

- Keep output compact and scannable
- Truncate long content previews to 50 characters
- Show timestamps in YYYY-MM-DD format
- Group decisions and lessons separately from other memory types
- Highlight if Task Copilot is linked (`taskCopilotLinked: true`)
- Show `activePrdIds` if linked to Task Copilot
- For agent improvements, parse metadata to extract AgentImprovementMetadata fields
- Show status counts (pending/approved/rejected) from metadata.status field
- Truncate rationale to 40 characters for table display

## Example Output

```
## Memory Dashboard

**Initiative:** Framework Improvements v2.0
**Status:** IN PROGRESS
**Task Copilot:** Linked (PRDs: PRD-001, PRD-002)

**Focus:** 4 remaining tasks for v2.0 release
**Next:** Complete CMD-1 memory command

### Recent Decisions
- Migrate to slim initiative format for 75% context reduction
- Use Task Copilot for all task tracking, Memory Copilot for strategic decisions only
- No time estimates policy enforced across all outputs

### Recent Lessons
- Bloated initiatives waste tokens and slow down /continue
- Separating task management from strategic memory improves clarity

### Key Files
- .claude/commands/continue.md
- mcp-servers/copilot-memory/src/index.ts
- docs/operations/working-protocol.md

### Recent Memories (Last 10)
Type       | Content Preview                                    | Created
---------- | -------------------------------------------------- | ----------
decision   | Migrate to slim initiative format for 75% cont... | 2025-01-15
lesson     | Bloated initiatives waste tokens and slow down... | 2025-01-15
decision   | Use Task Copilot for all task tracking, Memory... | 2025-01-14
context    | Framework v2.0 focuses on memory optimization      | 2025-01-14

### Agent Improvements
**Pending:** 2 | **Approved:** 1 | **Rejected:** 0

Agent | Section           | Rationale                           | Created
----- | ----------------- | ----------------------------------- | ----------
me    | Core Behaviors    | Add checkpoint validation before r... | 2025-01-15
qa    | Output format     | Include regression test considerati... | 2025-01-14

**Storage:** ~/.claude/memory/abc123def456/memory.db
**Workspace ID:** abc123def456 (auto-generated)
```

## Additional Information

If the user asks "where is my data stored?", explain:

- Memory database location: `~/.claude/memory/<workspace-id>/memory.db`
- Archives location: `~/.claude/memory/archives/`
- Workspace ID is auto-generated hash of project path (unless explicitly set)
- To preserve memories when moving/renaming projects, set `WORKSPACE_ID` in `.mcp.json`
- See Memory Copilot README for details on workspace management

## End

Present the dashboard and ask: "Would you like to see more details about any specific memory or initiative field?"
