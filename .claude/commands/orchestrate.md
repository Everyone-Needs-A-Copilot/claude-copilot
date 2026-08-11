---
name: orchestrate
description: Set up parallel stream scaffolding for native Task agent execution
alwaysAllow: true
---

# Orchestrate Command

Scaffolding layer for parallel streams. Agent dispatch is handled by the
harness, not by this command.

```
/orchestrate generate  # Create PRD + stream tasks via @agent-ta
/orchestrate start     # Validate streams, check conflicts, create worktrees, print dispatch cmds
/orchestrate status    # Show stream progress + live sessions
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
3. Persist real rows for `start`: `tc prd create --title "..." --description "..." --json` (capture `<prd-id>`); per unique `streamId`, `tc stream create --name "<streamName>" --prd <prd-id> --json` (capture the numeric `id`); then per task, `tc task create --title "..." --prd <prd-id> --stream <numeric-id> --description "..." --metadata '<json>' --json`. Skipping `--stream`/`--metadata` leaves `tc stream conflicts` and `tc task list --stream <id>` empty.
4. Display plan summary and ask user to approve

---

## `start`

Validates streams, checks for real file conflicts, creates an isolated git
worktree per ready stream, and prints exact dispatch commands (`claude --bg`
or `tc worker`).

1. `tc stream list --json` -- stop if no streams (tell user to run `generate` first)
2. Preflight: confirm `tc` is on PATH, you're inside a git repo, and the working tree is clean
3. `tc stream conflicts --json` (hard precondition) -- non-zero exit means a file is claimed by multiple streams. Report the conflicts; stop before creating worktrees.
4. For each stream whose dependencies are all satisfied, create an isolated worktree:
   ```bash
   git worktree add .worktrees/<stream-id> -b stream/<stream-id>
   ```
5. Print one dispatch command per ready stream; each agent works in `.worktrees/<stream-id>` on that stream's tasks (`tc task list --stream <stream-id> --json`):

   **Native background agent (default):**
   ```bash
   claude --bg --add-dir .worktrees/<stream-id> --agent me "Work on stream <stream-id>. Run: tc task list --stream <stream-id> --json"
   ```

   **Budget-capped dispatch (optional):** when a per-run spending cap is needed, use `tc worker` instead:
   ```bash
   tc worker <task-id> --max-budget-usd 3.00
   ```
6. As streams finish, run `/orchestrate merge` to integrate them. Dependency ordering is your call — only start a stream once its dependencies have merged.

---

## `status`

1. `tc progress --json` -- overall completion
2. `tc stream list --json` -- per-stream status
3. `claude agents --json` -- live sessions from `claude --bg` (`--all` for finished)
4. Print compact table:

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
| `tc stream create` | generate | Create a stream; returns numeric id |
| `tc task create --stream --metadata` | generate | Create a task with `--stream` id + metadata |
| `tc task list --stream <id>` | start | Per-stream work list |
| `tc stream list` | start, status, merge | List streams |
| `tc stream conflicts` | start | File-overlap check |
| `tc worker --max-budget-usd` | start | Budget-capped dispatch |
| `claude --bg` | start | Background agent dispatch |
| `claude agents --json` | status | List sessions |
| `tc progress` | status | Overall progress |
| `git worktree add` | start | Create worktree per stream |
| `git merge --no-ff` | merge | Merge a stream branch to main |
| `git worktree remove` / `git branch -d` | merge | Clean up after merge |
