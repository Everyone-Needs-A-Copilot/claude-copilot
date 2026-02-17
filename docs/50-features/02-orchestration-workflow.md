# Orchestration Workflow

Parallel stream execution using Claude Code's native `Task` tool. The `/orchestrate` command is a thin scaffolding layer -- it creates worktrees and validates streams, but does not launch agents.

---

## How It Works

```
/orchestrate generate   -->  PRD + stream tasks created via @agent-ta
/orchestrate start      -->  Worktrees created, conflict check, launch instructions printed
  Main session          -->  Launches Task agents (run_in_background: true) per stream
/orchestrate status     -->  Compact progress table
/orchestrate merge      -->  Merge completed worktrees back to main
```

Agents run in parallel inside isolated git worktrees. Task Copilot tracks progress. No external Python scripts or HTTP APIs required.

---

## Subcommands

### `generate`

Creates PRD and tasks with stream metadata. Default if no subcommand given.

| Step | Action |
|------|--------|
| 1 | `initiative_get({ mode: "lean" })` -- stop if no active initiative |
| 2 | `initiative_link()` to connect Task Copilot (archives old streams) |
| 3 | Invoke **@agent-ta** to design architecture and return structured JSON |
| 4 | Validate: no cycles, at least one foundation stream (`dependencies: []`) |
| 5 | `prd_create()` then `task_create()` for each task |
| 6 | Display plan summary, ask user to approve |

**Required task metadata:**

```json
{
  "streamId": "Stream-A",
  "streamName": "Foundation",
  "files": ["src/auth.ts"],
  "streamDependencies": [],
  "streamPaths": ["src/auth/**"],
  "streamTokenBudget": 2500
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `streamId` | Yes | Unique identifier (e.g., "Stream-A") |
| `streamName` | No | Human-readable label (defaults to streamId) |
| `files` | Yes | Files this stream touches (for conflict detection) |
| `streamDependencies` | Yes | Array of streamIds that must complete first (`[]` for foundation) |
| `streamPaths` | No | Optional path patterns (globs or directory prefixes) owned by the stream |
| `streamTokenBudget` | No | Optional per-stream token budget (estimated tokens) |

### `start`

Sets up git isolation. Does NOT launch agents.

| Step | Action |
|------|--------|
| 1 | `stream_list()` -- stop if no streams |
| 2 | `stream_conflict_check()` -- stop if file overlaps between streams |
| 3 | `worktree_create({ taskId })` for each stream task |
| 4 | Print launch instructions for the main session |

After this command completes, the **main session** launches `Task` agents with `run_in_background: true` for each stream. Each agent receives its stream context, worktree path, and task list.

### `status`

Shows compact progress.

```
Stream     | Status      | Progress
-----------|-------------|----------
Stream-A   | completed   | 100%
Stream-B   | in_progress | 60%
Stream-C   | pending     | 0%
```

Uses `progress_summary()` and `stream_list()`.

### `merge`

Merges completed stream worktrees back to main.

| Outcome | Action |
|---------|--------|
| Clean merge | `worktree_merge()`, then `worktree_cleanup()` |
| Conflicts | Report files, suggest `worktree_conflict_resolve()` |
| Not complete | Skip stream, note in output |

---

## Stream Dependency Model

Execution order is determined entirely by the dependency graph in task metadata. No hardcoded phases.

| Pattern | Metadata | Behavior |
|---------|----------|----------|
| Foundation | `"dependencies": []` | Starts immediately |
| Single dependency | `"dependencies": ["Stream-A"]` | Waits for Stream-A to reach 100% |
| Multiple dependencies | `"dependencies": ["Stream-A", "Stream-B"]` | Waits for both (AND logic) |

**Typical structure:**

```
Depth 0 (Foundation):  Stream-A  [no dependencies]
Depth 1 (Parallel):    Stream-B  [depends on A]
                       Stream-C  [depends on A]
Depth 2 (Integration): Stream-Z  [depends on B, C]
```

---

## Stream Conflict Detection

Before creating worktrees, `stream_conflict_check()` compares the `files` arrays across streams. If two streams declare overlapping files, orchestration stops.

**Resolution:** restructure streams so each file belongs to exactly one stream, or merge overlapping streams.

---

## Worktree Isolation

Each stream gets a dedicated git worktree for complete filesystem isolation.

| Aspect | Detail |
|--------|--------|
| Location | `.worktrees/{TASK-xxx}` per task |
| Branch naming | `task/{task-id-lowercase}` |
| Creation | `worktree_create({ taskId })` during `start` |
| Merge | `worktree_merge({ taskId })` during `merge` |
| Cleanup | `worktree_cleanup({ taskId })` after successful merge |
| Conflict resolution | `worktree_conflict_status()` then `worktree_conflict_resolve()` |

For full worktree details, see [05-worktree-isolation.md](./05-worktree-isolation.md).

---

## Initiative Scoping

Streams are scoped to the active initiative.

| Action | Effect |
|--------|--------|
| `initiative_link()` with new initiative | Archives streams from previous initiative |
| `stream_list()` | Returns only current initiative streams |
| Switching back | Use `stream_unarchive({ streamId })` then re-link old initiative |

---

## Monitoring

### From Claude Code

Run `/orchestrate status` for a quick snapshot.

### Live Dashboard (Legacy)

The `./watch-status` script (from `templates/orchestration/`) provides a live terminal dashboard if the legacy infrastructure is installed:

```
Stream-A [===============] 100%  DONE  2h31m  Foundation
Stream-B [==========-----]  70%  RUN   1h45m  API Layer
Stream-C [========-------]  40%  RUN     52m  UI Components
Stream-Z [---------------]   0%  ---    ---   Integration
```

---

## Best Practices

| Practice | Rationale |
|----------|-----------|
| Keep parallel streams at 3-5 | More streams increase merge complexity and resource usage |
| Ensure files do not overlap | Prevents merge conflicts; enforced by `stream_conflict_check()` |
| Complete foundation before parallel | Downstream streams depend on shared infrastructure |
| Verify after `generate` | Call `stream_list()` to confirm tasks were created (not just markdown) |
| Run `merge` promptly | Long-lived worktrees diverge from main, increasing conflict risk |

---

## Troubleshooting

| Symptom | Cause | Solution |
|---------|-------|----------|
| "No streams found" on `start` | `generate` not run, or @agent-ta output markdown instead of calling tools | Run `/orchestrate generate`; verify with `stream_list()` |
| File overlap detected | Two streams declare the same file in `files` metadata | Restructure streams or merge overlapping ones |
| Circular dependency detected | Streams depend on each other in a cycle | Break cycle by making one stream foundation (`dependencies: []`) |
| Worktree already exists | Previous run not cleaned up | `worktree_cleanup({ taskId, force: true })` or `git worktree remove --force` |
| Merge conflicts on `merge` | Parallel changes touched same lines | Use `worktree_conflict_status()` to inspect, resolve manually, then `worktree_conflict_resolve()` |
| Streams missing after initiative switch | `initiative_link()` auto-archives old streams | `stream_unarchive({ streamId })` then re-link old initiative |
| Database locked | Another process has SQLite open | Close other Claude sessions, wait 30s, retry |
| Task agent not starting | Main session did not launch Task tool | Main session must call `Task` with `run_in_background: true` per stream |

---

## Tool Reference

| Tool | Used In | Purpose |
|------|---------|---------|
| `initiative_get` | generate | Check active initiative |
| `initiative_link` | generate | Connect Task Copilot, archive old streams |
| `prd_create` | generate | Create PRD |
| `task_create` | generate | Create stream tasks with metadata |
| `stream_list` | start, status, merge | List streams with progress |
| `stream_conflict_check` | start | Validate no file overlaps |
| `worktree_create` | start | Create git worktree per stream |
| `worktree_merge` | merge | Merge branch to main |
| `worktree_conflict_status` | merge | Inspect merge conflicts |
| `worktree_conflict_resolve` | merge | Complete conflict resolution |
| `worktree_cleanup` | merge | Remove worktree and branch |
| `progress_summary` | status | Overall completion percentage |

---

## See Also

- **Command source:** [`.claude/commands/orchestrate.md`](../../.claude/commands/orchestrate.md)
- **Worktree isolation:** [`docs/50-features/05-worktree-isolation.md`](./05-worktree-isolation.md)
- **Task Copilot:** [`mcp-servers/task-copilot/README.md`](../../mcp-servers/task-copilot/README.md)

---

*Updated: February 2026 -- `/orchestrate` rewritten as thin scaffolding layer; Claude Code's native `Task` tool handles parallel agent execution*
