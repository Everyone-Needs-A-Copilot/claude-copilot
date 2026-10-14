---
name: config
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /config: inspect or explain cc configuration, known references, paths, and environment hydration."
---

# Config

Inspect Copilot configuration.

## Workflow

1. Prefer `$HOME/.local/bin/cc`.
2. Run `cc config list --scope effective`.
3. Run `cc env --json` when machine-readable output is useful.
4. Explain project, machine, and sentinel values.
5. Recommend `cc config set` commands for missing values.
6. Treat `paths.knowledge_repo` as string-or-ordered-list configuration. Use
   `cc config add` and `cc config remove` for idempotent list updates.

## Output

- effective config summary
- missing or stale values
- recommended commands

## Work Lifecycle

Apply the [shared work lifecycle](../optimize/references/work-lifecycle.md) once
per task, including direct invocation of this skill: start/resume, maintain,
pause/handoff, finish and later reuse. Keep the checkpoint proportional in the
existing record; a small answer does not need a new task or document.
