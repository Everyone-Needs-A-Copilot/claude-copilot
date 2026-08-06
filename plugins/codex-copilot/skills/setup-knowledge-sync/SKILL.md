---
name: setup-knowledge-sync
description: Use when setting up Codex Copilot knowledge synchronization between project memory, shared docs, known references, and optional pack activation.
---

# Setup Knowledge Sync

Set up a safe knowledge synchronization path.

## Workflow

1. Verify the project is a git repository.
2. Inspect `cc config list --scope effective` when available.
3. Check `paths.knowledge_repo` and `refs.*`.
4. If a knowledge repository exists, verify its manifest and docs index.
5. If no repository exists, create a plan for a Git-friendly knowledge repo with a manifest, docs index, and memory/reference policy.
6. Use `scripts/activate-pack.py` only for explicit pack activation.
7. Do not delete, replace, or rewrite existing knowledge repositories without explicit current approval.

## Output

- knowledge sync mode
- config updates
- manifest or docs gaps
- safe activation commands
