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

1. Invoke **@agent-ta** to design architecture and return structured JSON:

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

2. Parse JSON, validate (no cycles, at least one task with `dependencies: []`)
3. `tc prd create --title "..." --description "..." --json` then `tc task create --title "..." --prd <id> --json` for each task
4. Display plan summary and ask user to approve

---

## `start`

Validates streams, creates an isolated git worktree per ready stream, and prints
launch instructions. Claude Code's native `Task` tool runs the agents —
`/orchestrate` does not spawn background workers.

1. `tc stream list --json` -- stop if no streams (tell user to run `generate` first)
2. Preflight: confirm `tc` is on PATH, you're inside a git repo, and the working tree is clean
3. Check for file overlaps between parallel streams (compare each stream's `files` metadata) -- stop if two parallel streams touch the same file
4. For each stream whose dependencies are all satisfied, create an isolated worktree:
   ```bash
   git worktree add .worktrees/<stream-id> -b stream/<stream-id>
   ```
5. Print launch instructions: dispatch one native `Task` agent per ready stream. Each agent works in its `.worktrees/<stream-id>` directory on that stream's tasks:
   ```bash
   tc task list --stream <stream-id> --json   # the agent's work list
   ```
6. As streams finish, run `/orchestrate merge` to integrate them.

> **Note:** Agent execution is handled by the native `Task` tool, not a background
> worker pool. Dependency ordering is your call — only start a stream once the
> streams it depends on have merged.

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

Merges completed stream worktrees back into the main branch using plain git.

1. `tc stream list --json` to find completed streams
2. For each completed stream, merge its branch:
   ```bash
   git merge stream/<stream-id> --no-ff -m "Merge <stream-id>: <description>"
   ```
3. If the merge reports conflicts: list the conflicting files and stop for manual resolution (do not auto-resolve)
4. If clean: remove the worktree and branch:
   ```bash
   git worktree remove .worktrees/<stream-id>
   git branch -d stream/<stream-id>
   ```

| Outcome | Action |
|---------|--------|
| Clean merge | Remove worktree + branch, report success |
| Conflicts | Report conflicting files, leave for manual `git` resolution |
| Not complete | Skip stream, note in output |

---

## Tool Reference

| Tool / Command | Used In | Purpose |
|------|---------|---------|
| `tc prd create` | generate | Create PRD |
| `tc task create` | generate | Create stream tasks |
| `tc task list --stream <id>` | start | The work list for each stream's agent |
| `tc stream list` | start, status, merge | List streams |
| `tc progress` | status | Overall progress |
| `git worktree add` | start | Create isolated worktree per stream |
| `git merge --no-ff` | merge | Merge a stream branch to main |
| `git worktree remove` / `git branch -d` | merge | Clean up after a successful merge |
