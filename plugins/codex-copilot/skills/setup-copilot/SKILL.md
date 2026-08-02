---
name: setup-copilot
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /setup-copilot or /setup: install or verify shared Copilot tooling for Codex-native projects."
---

# Setup Copilot

Verify shared Copilot tooling.

## Workflow

1. Verify Python, `cc`, and `tc`.
2. Confirm `cc` resolves to the Copilot CLI, not the system C compiler.
3. Confirm `cc docs sources` works for Live Docs capability.
4. Confirm `tc` supports required commands.
5. Run `scripts/check-versions.sh` from the framework root.
6. Confirm the Codex plugin manifest and marketplace entry exist.
7. Provide install or repair commands without deleting existing resources.

## Output

- setup status
- missing tools
- safe install commands
- verification commands
