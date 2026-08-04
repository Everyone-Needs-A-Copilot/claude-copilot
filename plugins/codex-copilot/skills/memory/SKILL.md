---
name: memory
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /memory: inspect recent cc memory entries, known references, and task progress."
---

# Memory

Show memory and task state for transparency.

## Workflow

1. Run `cc memory list --limit 10` when `cc` is configured.
2. Run `cc config list --scope effective` to show relevant paths and `refs.*`.
3. Run `cc memory check --json` to detect broken paths, unresolved commands, version conflicts, and stale entries.
4. Run `cc usage --json --no-probe` only when the user asks about Claude Copilot quota or session usage.
5. Run `tc progress --json` when `tc` is initialized.
6. Present a compact dashboard.

When the user requests a portable snapshot, use `cc memory export` with an
explicit output path or JSON output. Export is user-requested; it is not an
automatic memory-to-knowledge sync.

## Output

- recent decisions
- recent context or lessons
- known references
- memory drift score and flagged entries
- task progress
