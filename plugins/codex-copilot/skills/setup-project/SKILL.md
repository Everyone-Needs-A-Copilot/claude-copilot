---
name: setup-project
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /setup-project: wire a target repository to the shared Codex Copilot framework."
---

# Setup Project

Wire a project to Codex Copilot.

## Workflow

1. Use `scripts/setup-project.sh --project <path>` from the framework repo. Safe to re-run: if the project already has a codex-copilot install, this delegates to `scripts/update-project.sh` to repair the plugin/skill/QA-gate paths in place instead of refusing.
2. Treat `--force` as compatibility-only; it changes nothing (there is no longer a refusal to bypass).
3. Verify generated `AGENTS.md`, `.agents/plugins/marketplace.json`, `.claude/cc/config.json`, memory dirs, plugin links, `docs/40-initiatives/`, and the `scripts/copilot-gate.sh` link.
4. Confirm existing `AGENTS.md`, initiative documentation, and any file marked `owner: project` were preserved rather than replaced.
5. Run `cc skill list`, `cc docs sources`, `cc memory check --json`, `tc progress --json`, and `scripts/copilot-gate.sh` from the target project when available.
6. If wiring already exists and you only want a refresh (no first-install scaffolding), use `$update-project` / `scripts/update-project.sh` directly.

## Output

- generated files
- plugin and skill link targets
- verification results
