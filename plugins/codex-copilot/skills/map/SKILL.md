---
name: map
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /map: produce or refresh a concise codebase map for agent navigation."
---

# Map

Create a compact project map for faster specialist navigation.

## Workflow

1. Detect stack from package and config files.
2. Summarize top-level directories and key entry points.
3. Identify docs, tests, build scripts, and configuration files.
4. Store the result as a `documentation` work product when `tc` context exists.
5. If writing `PROJECT_MAP.md`, do it only when explicitly requested.

## Output

- tech stack summary
- key directories
- important files
- recommended first reads

## Work Lifecycle

Apply the [shared work lifecycle](../optimize/references/work-lifecycle.md) once
per task, including direct invocation of this skill: start/resume, maintain,
pause/handoff, finish and later reuse. Keep the checkpoint proportional in the
existing record; a small answer does not need a new task or document.
