---
name: pause
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /pause: preserve current work state in tc and memory before context switching."
---

# Pause

Preserve current work so it can be resumed later.

## Workflow

1. Find in-progress work with `tc task list --status in_progress --json`.
2. Store a compact pause work product on each active task with the reason, current state, and next action.
3. Update task status to `paused` only if the local `tc` version supports that status; otherwise store the pause work product and leave the status unchanged.
4. Store memory with `cc memory store --type context "Paused work: ..."` when `cc` is configured.
5. Return a compact resume instruction.

## Safety

Do not modify files, branches, worktrees, or task data destructively.
