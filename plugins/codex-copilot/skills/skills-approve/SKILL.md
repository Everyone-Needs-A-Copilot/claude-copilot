---
name: skills-approve
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /skills-approve: review available skills and decide which reusable skills should be trusted or used for a task."
---

# Skills Approve

Review available skills before use.

## Workflow

1. Run `cc skill list --scope all` when `cc` is available.
2. Inspect candidate skills with `cc skill get <name>`.
3. Prefer repo-local Codex skills for Codex workflows.
4. Recommend skills to use and any safety constraints.

## Output

- candidate skills
- approval recommendation
- constraints or warnings
