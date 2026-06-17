# Memory Dashboard

Display current memory state for transparency and debugging.

## Step 1: Retrieve Memory Data

Run these CLI commands to gather memory state:

1. **Get recent decisions:**
   ```bash
   cc memory list --type decision
   ```

2. **Get recent memories:**
   ```bash
   cc memory list
   ```

3. **Get recent context entries:**
   ```bash
   cc memory list --type context
   ```

4. **Get session quota / rate-limit state:**
   ```bash
   cc usage --json
   ```
   Note: `cc usage` reads the cache written by a prior probe, or falls back to
   transcript reconstruction if no cache exists. Use `cc usage --refresh` to
   force a fresh probe.

5. **If Task Copilot is linked, get progress:**
   ```bash
   tc progress --json
   ```

6. **Get protocol violations (if Task Copilot is linked):**
   ```bash
   tc log --json
   ```

## Step 2: Display Dashboard

Format the output as a clean, scannable dashboard:

```
## Memory Dashboard

### Session Quota
Source: probe | fallback | stale (cached)
unified-5h window: [status] [utilization%] used  resets [HH:MM UTC]
unified-7d window: [status] [utilization%] used  resets [HH:MM UTC]
[If fallback: "unified-5h messages: N  unified-7d messages: N  (offline estimate, not token count)"]
[If probe error: show error message]
Run `cc usage --refresh` to force a new probe.

### Recent Decisions
[List last 3-5 decisions, or "None recorded"]

### Recent Lessons
[List last 3-5 lessons, or "None recorded"]

### Recent Memories (Last 10)
Type       | Content Preview                    | Created
---------- | ---------------------------------- | ----------
decision   | [First 50 chars...]                | 2025-01-15
lesson     | [First 50 chars...]                | 2025-01-14

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

### No Memories

If `cc memory list` returns empty:
```
### Recent Memories
No memories stored yet.
Use `cc memory store --type decision "..."` to start recording.
```

## Display Notes

- Keep output compact and scannable
- Truncate long content previews to 50 characters
- Show timestamps in YYYY-MM-DD format
- Group decisions and lessons separately from other memory types
- Highlight if Task Copilot is linked
- Valid entry types: `decision` | `context` | `lesson` | `reference` | `person`
- For protocol violations, show summary counts by severity
- Only show violations section if Task Copilot is linked
- Highlight critical and high-severity violations

## Example Output

```
## Memory Dashboard

### Session Quota
Source: probe, updated 42s ago
unified-5h window: allowed  7.0% used  resets 17:30 UTC
unified-7d window: allowed 13.0% used  resets 03:00 UTC
Run `cc usage --refresh` to force a new probe.

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
