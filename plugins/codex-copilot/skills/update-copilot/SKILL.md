---
name: update-copilot
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /update-copilot: update the shared Codex Copilot framework and verify plugin, cc, and tc alignment."
---

# Update Copilot

Update and verify the shared framework.

## Workflow

1. Check git status and preserve user changes.
2. Fetch from GitHub and inspect incoming changes before merging or rebasing.
3. Never delete, reset, clean, or force-push without explicit current approval.
4. Verify plugin metadata, agent catalog schema, skills, `cc`, `tc`, pack manifests, and artifact-bound QA gate contracts.
5. Run `scripts/check-versions.sh` and `scripts/smoke-test.sh`.
6. Run the parity tests.

## Output

- git sync status
- version status
- verification results
- approval needs for destructive operations
