# Auto-Checkpoint Hooks (Legacy)

> **Note:** Checkpoint and iteration MCP tools (`checkpoint_create`, `checkpoint_resume`, `iteration_start`, `iteration_validate`, `iteration_next`, `iteration_complete`) have been removed. Agents now self-manage their iteration loops, and checkpoint/recovery functionality is handled via git commits and Memory Copilot. This document is retained for historical reference.

## Overview

The auto-checkpoint system previously created recovery points during iteration loops automatically. With the migration to the `tc` CLI, checkpoint and iteration tools have been removed. Agents self-manage their iteration loops using standard tooling (run tests, check results, iterate).

## What Changed

| Old MCP Tool | Status |
|---|---|
| `checkpoint_create(...)` | Removed |
| `checkpoint_resume(...)` | Removed |
| `iteration_start(...)` | Removed (agents self-manage) |
| `iteration_validate(...)` | Removed (agents self-manage) |
| `iteration_next(...)` | Removed (agents self-manage) |
| `iteration_complete(...)` | Removed (agents self-manage) |

## Current Approach

Recovery and checkpointing are now handled through:

- **Git commits** -- Auto-commit on task completion creates recovery points
- **Memory Copilot** -- `initiative_update` saves session state for `/continue`
- **Task Copilot CLI** -- `tc task get <id> --json` retrieves task state
- **Work products** -- `tc wp store --task <id> --type <t> --title "..." --content "..." --json` persists deliverables

## Agent Iteration Pattern (Current)

Agents manage their own iteration loops without dedicated MCP tools:

```markdown
FOR EACH attempt (up to max retries):
  # Do work
  - Read files
  - Make changes
  - Run tests via Bash

  # Check results
  IF tests pass AND lint clean:
    Store work product: tc wp store --task <id> ...
    Update task: tc task update <id> --status completed --json
    BREAK
  ELSE:
    Analyze failures, refine approach, try again
```

## Blocked Stream Compaction

When an agent encounters a blocker, it should:
1. Store findings as a work product: `tc wp store --task <id> --type other --title "Blocked: ..." --content "..." --json`
2. Update task status: `tc task update <id> --status blocked --json`

## Related Documentation

- [Working Protocol](../30-operations/01-working-protocol.md) - Agent-First Protocol
- [Agent Guide](../30-operations/03-agent-guide.md) - Agent configuration
