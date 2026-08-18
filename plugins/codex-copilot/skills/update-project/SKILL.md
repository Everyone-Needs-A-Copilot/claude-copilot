---
name: update-project
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /update-project: refresh a project-local Codex Copilot setup from the shared framework."
---

# Update Project

Refresh project-local Codex Copilot wiring in place.

## Workflow

1. Run `scripts/update-project.sh --project <path>`. Unless `--framework-root` is given explicitly, it syncs from the pinned mirror (`~/.copilot/mirrors/codex-foundation` by default) rather than wherever the framework repo happens to be checked out, so a project is never synced ahead of any released version. It updates an EXISTING install; if the project has never been set up, it exits and points at `$setup-project` / `scripts/setup-project.sh` instead.
2. The 62 framework-owned files (61 under `plugins/codex-copilot/` plus `scripts/copilot-gate.sh`) are compared by content (sha256), not by declared version, so it also repairs drift that doesn't match any released version.
3. A file marked `ownership: project` -- via `owner: project` YAML frontmatter in the file itself, or a `copilot.lock.json` entry -- is never touched. Confirm the report's "Preserved" section lists exactly the paths a human intentionally customized.
4. `AGENTS.md`, `SOUL.md`, `docs/40-initiatives/`, `.agents/plugins/marketplace.json` are never touched by the updater; `.codex-copilot.json` only has its framework-tracking fields merged (`projectName`/`pluginPath` preserved).
5. Idempotent: run it twice to confirm the second run reports "no changes needed." Use `--dry-run` to preview without writing.
6. Validate with `cc skill list`, `cc docs sources`, `cc memory check --json`, and `tc progress --json` when available.
7. If optional packs are needed, activate them with `scripts/activate-pack.py` instead of copying pack files manually.

## Output

- files updated / added / unchanged / preserved / retired (from the script's report)
- skill symlink and `.codex-copilot.json` status
- `copilot.lock.json` write confirmation
- idempotence check (second run == no changes needed)
