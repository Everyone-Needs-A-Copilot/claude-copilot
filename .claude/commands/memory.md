# Memory Dashboard

Display current memory state for transparency and debugging.

## Step 1: Retrieve Memory Data

Run these CLI commands to gather memory state:

1. **Get recent initiative entries:**
   ```bash
   cc memory list --type initiative --limit 3
   ```

2. **Get recent memories:**
   ```bash
   cc memory list --limit 10
   ```

3. **Get agent improvement suggestions:**
   ```bash
   cc memory list --type agent_improvement
   ```

4. **If Task Copilot is linked, get progress:**
   ```bash
   tc progress --json
   ```

5. **Get protocol violations (if Task Copilot is linked):**
   ```bash
   tc log --json
   ```

## Step 2: Display Dashboard

Format the output as a clean, scannable dashboard:

```
## Memory Dashboard

**Initiative:** [name from most recent initiative entry, or "None"]
**Status:** [status - IN PROGRESS / COMPLETED / BLOCKED]

**Focus:** [currentFocus]
**Next:** [nextAction]

### Recent Decisions
[List last 3-5 decisions, or "None recorded"]

### Recent Lessons
[List last 3-5 lessons, or "None recorded"]

### Recent Memories (Last 10)
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

**Storage:** ~/.claude/memory/ (machine) | .claude/memory/entries/ (project)

### Task Progress (if Task Copilot linked)
[Show output from `tc progress --json`, or skip section if not linked]
PRDs: [count] | Tasks: [pending/in_progress/completed] | Work Products: [count]

### Protocol Violations (if Task Copilot linked)
[If protocol violations exist, show summary:]
**Total:** [count] | **Critical:** [count] | **High:** [count] | **Medium:** [count] | **Low:** [count]

[Table format for recent violations:]
Type                     | Severity | Description                     | When
------------------------ | -------- | ------------------------------- | ----------
files_read_exceeded      | high     | Read 5 files (limit: 3)         | 2025-01-12
generic_agent_used       | critical | Used "Explore" agent            | 2025-01-12

[If no violations: "No protocol violations recorded"]
```

## Step 3: Handle Edge Cases

### No Active Initiative

If `cc memory list --type initiative` returns no entries:
```
## Memory Dashboard

**Status:** No active initiative

Use `/protocol` to start fresh work or `/continue` to resume.

**Storage:** ~/.claude/memory/ (machine) | .claude/memory/entries/ (project)
```

### No Memories

If `cc memory list` returns empty:
```
### Recent Memories
No memories stored yet.
```

### No Agent Improvements

If `cc memory list --type agent_improvement` returns empty:
```
### Agent Improvements
No agent improvements recorded
```

## Display Notes

- Keep output compact and scannable
- Truncate long content previews to 50 characters
- Show timestamps in YYYY-MM-DD format
- Group decisions and lessons separately from other memory types
- Highlight if Task Copilot is linked
- For agent improvements, parse metadata to extract AgentImprovementMetadata fields
- Show status counts (pending/approved/rejected) from metadata.status field
- Truncate rationale to 40 characters for table display
- For protocol violations, show summary counts by severity
- Only show violations section if Task Copilot is linked
- Highlight critical and high-severity violations

## Example Output

```
## Memory Dashboard

**Initiative:** Framework Improvements v2.0
**Status:** IN PROGRESS

**Focus:** 4 remaining tasks for v2.0 release
**Next:** Complete CMD-1 memory command

### Recent Decisions
- Migrate to cc CLI for memory and skills management
- Use Task Copilot for all task tracking, cc memory for strategic decisions only
- No time estimates policy enforced across all outputs

### Recent Lessons
- File-per-entry memory travels with the repo across machines
- Separating task management from strategic memory improves clarity

### Recent Memories (Last 10)
Type       | Content Preview                                    | Created
---------- | -------------------------------------------------- | ----------
decision   | Migrate to cc CLI for memory management...         | 2025-01-15
lesson     | File-per-entry memory travels with the repo...     | 2025-01-15
decision   | Use Task Copilot for all task tracking...          | 2025-01-14
context    | Framework v5.0 focuses on CLI-based tooling        | 2025-01-14
```

## Additional Information

If the user asks "where is my data stored?", explain:

- Machine memory: `~/.claude/memory/` (set via `cc config get paths.memory`)
- Project memory: `.claude/memory/entries/` (committed to git, travels with repo)
- Use `cc memory list` to see all entries
- Use `cc config list` to see the full configuration

## End

Present the dashboard and ask: "Would you like to see more details about any specific memory entry?"
