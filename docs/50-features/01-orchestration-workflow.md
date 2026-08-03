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

Agents run in parallel inside isolated git worktrees. The `tc` CLI tracks progress. No external Python scripts or HTTP APIs required.

---

## Subcommands

### `generate`

Creates PRD and tasks with stream metadata. Default if no subcommand given.

| Step | Action |
|------|--------|
| 1 | Invoke **@agent-ta** to design architecture and return structured JSON |
| 2 | Validate: no cycles, at least one foundation stream (`dependencies: []`) |
| 3 | `tc prd create --title "..." --json` then `tc task create --title "..." --prd <id> --json` for each task |
| 4 | Display plan summary, ask user to approve |

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
| 1 | `tc stream list --json` -- stop if no streams |
| 2 | Check for file overlaps between streams using `git diff` -- stop if conflicts |
| 3 | `git worktree add .worktrees/<stream-id> -b stream/<stream-id>` for each ready stream |
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

Uses `tc progress --json` and `tc stream list --json`.

### `merge`

Merges completed stream worktrees back to main.

| Outcome | Action |
|---------|--------|
| Clean merge | `git merge --no-ff stream/<stream-id>`, then `git worktree remove` + `git branch -d` |
| Conflicts | Report conflicting files; resolve manually, then commit and clean up |
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

Before creating worktrees, the orchestration compares the `files` arrays across streams (using `git diff`). If two streams declare overlapping files, orchestration stops.

**Resolution:** restructure streams so each file belongs to exactly one stream, or merge overlapping streams.

---

## Worktree Isolation

Each stream gets a dedicated git worktree for complete filesystem isolation.

| Aspect | Detail |
|--------|--------|
| Location | `.worktrees/<stream-id>` per stream |
| Branch naming | `stream/<stream-id>` |
| Creation | `git worktree add .worktrees/<stream-id> -b stream/<stream-id>` during `start` |
| Merge | `git merge --no-ff stream/<stream-id>` during `merge` |
| Cleanup | `git worktree remove .worktrees/<stream-id>` + `git branch -d stream/<stream-id>` after merge |
| Conflict resolution | Resolve manually in working tree, then `git add` + `git commit` |

For full worktree details, see [05-worktree-isolation.md](./05-worktree-isolation.md).

---

## Monitoring

### From Claude Code

Run `/orchestrate status` for a quick snapshot.

---

## Best Practices

| Practice | Rationale |
|----------|-----------|
| Keep parallel streams at 3-5 | More streams increase merge complexity and resource usage |
| Ensure files do not overlap | Prevents merge conflicts; enforced by file overlap checks during `start` |
| Complete foundation before parallel | Downstream streams depend on shared infrastructure |
| Verify after `generate` | Call `tc stream list --json` to confirm tasks were created (not just markdown) |
| Run `merge` promptly | Long-lived worktrees diverge from main, increasing conflict risk |

---

## Troubleshooting

| Symptom | Cause | Solution |
|---------|-------|----------|
| "No streams found" on `start` | `generate` not run, or @agent-ta output markdown instead of calling tools | Run `/orchestrate generate`; verify with `tc stream list --json` |
| File overlap detected | Two streams declare the same file in `files` metadata | Restructure streams or merge overlapping ones |
| Circular dependency detected | Streams depend on each other in a cycle | Break cycle by making one stream foundation (`dependencies: []`) |
| Worktree already exists | Previous run not cleaned up | `git worktree prune` then `git worktree remove --force .worktrees/<stream-id>` |
| Merge conflicts on `merge` | Parallel changes touched same lines | Resolve manually in worktree, `git add` + `git commit`, then remove worktree |
| Streams missing after workspace switch | Tasks scoped to a different workspace | Verify `tc stream list --json` returns expected streams |
| Database locked | Another process has SQLite open | Close other Claude sessions, wait 30s, retry |
| Task agent not starting | Main session did not launch Task tool | Main session must call `Task` with `run_in_background: true` per stream |

---

## Tool Reference

| Tool / Command | Used In | Purpose |
|------|---------|---------|
| `tc prd create` | generate | Create PRD |
| `tc task create` | generate | Create stream tasks with metadata |
| `tc stream list` | start, status, merge | List streams with progress |
| `git diff` | start | Validate no file overlaps between streams |
| `git worktree add` | start | Create git worktree per stream |
| `git merge --no-ff` | merge | Merge stream branch to main |
| `git worktree remove` | merge | Remove worktree after merge |
| `git branch -d` | merge | Delete merged stream branch |
| `git worktree prune` | troubleshooting | Clean up stale worktree references |
| `tc progress` | status | Overall completion percentage |

---

## See Also

- **Command source:** [`.claude/commands/orchestrate.md`](../../.claude/commands/orchestrate.md)
- **Worktree isolation:** [`docs/50-features/05-worktree-isolation.md`](./05-worktree-isolation.md)
- **Task Management:** `tc` CLI tool

---

*Updated: February 2026 -- `/orchestrate` rewritten as thin scaffolding layer; Claude Code's native `Task` tool handles parallel agent execution*
