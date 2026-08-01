---
name: update-project
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /update-project: refresh a project-local Codex Copilot setup from the shared framework."
---

# Update Project

Refresh project-local Codex Copilot wiring.

## Workflow

1. Verify `AGENTS.md`, `.agents/plugins/marketplace.json`, `.claude/cc/config.json`, `.claude/memory/entries/`, and `plugins/codex-copilot`.
2. Compare the embedded project plugin files and ownership lock with the shared framework plugin source.
3. Re-run `scripts/setup-project.sh` only after reviewing whether it would replace existing files.
4. Do not use destructive replacement without explicit current user approval for the exact paths.
5. Validate with `cc skill list`, `cc docs sources`, `cc memory check --json`, and `tc progress --json` when available.
6. If optional packs are needed, activate them with `scripts/activate-pack.py` instead of copying pack files manually.

## Output

- current setup status
- drift list
- safe update commands
- approval needs for any replacement
