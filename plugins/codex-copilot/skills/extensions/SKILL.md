---
name: extensions
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /extensions: inspect knowledge repositories, extension status, active skills, and project/global/base resolution."
---

# Extensions

Inspect knowledge and extension status.

## Workflow

1. Check `cc config get paths.knowledge_repo`.
2. Inspect project and global knowledge manifests if configured.
3. Run `cc skill list --scope all` when available.
4. Inspect pack manifests under `packs/*/pack.json`.
5. Explain resolution order: project -> global -> base, plus project-activated packs.
6. Recommend setup or repair steps without deleting or replacing existing knowledge.
7. Use `scripts/activate-pack.py` for explicit pack activation.

## Output

- knowledge repository status
- active skills summary
- extension resolution notes
- safe next steps
