---
name: setup
description: Universal Codex Copilot setup router. Use when you need to decide whether to run machine/framework setup, project setup, update, or verification.
---

# Setup

Route setup requests to the right Codex Copilot workflow.

## Workflow

1. If running in the framework repo, use `$setup-copilot` to verify shared tooling.
2. If running in a target project without Codex Copilot wiring, use `$setup-project`.
3. If wiring exists but may be stale, use `$update-project`.
4. Verify `cc`, `tc`, plugin metadata, skill links, and memory/config directories.
5. Never replace existing project files without explicit current approval.

## Output

- detected context
- selected setup path
- missing tools or files
- verification commands
