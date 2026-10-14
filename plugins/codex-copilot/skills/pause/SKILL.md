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
4. If retrieval needs it, update a scoped memory pointer to that task record; do not duplicate the pause narrative in memory.
5. Return a compact resume instruction.

## Safety

Do not modify files, branches, worktrees, or task data destructively.

## Work Lifecycle

Apply the [shared work lifecycle](../optimize/references/work-lifecycle.md) once
per task, including direct invocation of this skill: start/resume, maintain,
pause/handoff, finish and later reuse. Keep the checkpoint proportional in the
existing record; a small answer does not need a new task or document.
