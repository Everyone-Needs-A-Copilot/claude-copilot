---
name: orchestrate
description: Set up parallel stream scaffolding for native Task agent execution
alwaysAllow: true
---

# Orchestrate Command

Scaffolding layer for parallel streams. Claude Code's native `Task` tool handles actual agent execution.

```
/orchestrate generate  # Create PRD + stream tasks via @agent-ta
/orchestrate start     # Validate streams, create worktrees, print launch instructions
/orchestrate status    # Show stream progress
/orchestrate merge     # Merge completed worktrees back to main branch
```

---

## `generate` (default if no subcommand)

Creates PRD and tasks with stream metadata. Prompt user for feature description if not provided.

1. `initiative_get({ mode: "lean" })` -- stop if no active initiative
2. `initiative_link({ initiativeId, title, description })` to connect task tracking
3. Invoke **@agent-ta** to design architecture and return structured JSON:

```json
{
  "prd": { "title": "...", "description": "...", "content": "# PRD..." },
  "tasks": [{
    "title": "...", "description": "...",
    "metadata": {
      "streamId": "Stream-A", "streamName": "Foundation",
      "files": ["src/auth.ts"], "dependencies": []
    }
  }]
}
```

4. Parse JSON, validate (no cycles, at least one task with `dependencies: []`)
5. `tc prd create --title "..." --description "..." --json` then `tc task create --title "..." --prd <id> --json` for each task
6. Display plan summary and ask user to approve

---

## `start`

Sets up git isolation and prints launch instructions. Does NOT launch agents.

1. `tc stream list --json` -- stop if no streams (tell user to run `generate` first)
2. Check for file overlaps between streams using `git diff` across worktrees -- stop if conflicts detected
3. For each stream task: `worktree_create({ taskId })` to create git worktree
4. Print:

```
Scaffolding ready. Each stream has an isolated worktree.

To launch, the MAIN SESSION should run Task agents:
  - For each stream task, use Task tool with run_in_background: true
  - Pass the task description, worktree path, and stream context
  - Agents work in parallel in isolated worktrees

I'll launch the stream agents now.
```

The **main session** (not this command) then launches `Task` agents with `run_in_background: true` for each stream.

---

## `status`

1. `tc progress --json` -- overall completion
2. `tc stream list --json` -- per-stream status
3. Print compact table:

```
Stream     | Status      | Progress
-----------|-------------|----------
Stream-A   | completed   | 100%
Stream-B   | in_progress | 60%
Stream-C   | pending     | 0%
```

---

## `merge`

Merges completed stream worktrees back to the main branch.

1. `tc stream list --json` to find completed streams
2. For each completed stream: `worktree_merge({ taskId })`
3. If conflicts: `worktree_conflict_status({ taskId })` and report files
4. If clean: `worktree_cleanup({ taskId })` and report success

| Outcome | Action |
|---------|--------|
| Clean merge | Cleanup worktree, report success |
| Conflicts | Report conflicting files, suggest `worktree_conflict_resolve()` |
| Not complete | Skip stream, note in output |

---

## Tool Reference

| Tool / Command | Used In | Purpose |
|------|---------|---------|
| `initiative_get` | generate | Check active initiative (Memory Copilot MCP) |
| `initiative_link` | generate | Link to task tracking (Memory Copilot MCP) |
| `tc prd create` | generate | Create PRD |
| `tc task create` | generate | Create stream tasks |
| `tc stream list` | start, status, merge | List streams |
| `git diff` across worktrees | start | Validate no file overlaps |
| `worktree_create` | start | Git isolation per stream |
| `worktree_merge` | merge | Merge branch to main |
| `worktree_conflict_status` | merge | Check merge conflicts |
| `worktree_conflict_resolve` | merge | Resolve conflicts |
| `worktree_cleanup` | merge | Remove merged worktree |
| `tc progress` | status | Overall progress |
