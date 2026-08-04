---
name: continue
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /continue: resume paused or previous work from tc tasks, work products, memory, and stream context."
---

# Continue

Resume previous Codex Copilot work.

## Workflow

1. Run `tc progress --json` and `tc task list --status paused --json` when available.
2. Search memory with `cc memory search "paused continue current focus"` when `cc` is configured.
3. Identify the most relevant paused or in-progress task.
4. Retrieve recent activity with `tc log --task <id> --json` when available.
5. Summarize current state, next action, and any missing context.
6. Continue through `$protocol` if the resumed work needs routing.

## Output

- active task or stream
- last known state
- next action
- blocker list if any
