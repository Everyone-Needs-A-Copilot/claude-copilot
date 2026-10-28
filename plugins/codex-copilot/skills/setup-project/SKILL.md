---
name: setup-project
description: "Use when you need the Codex Copilot equivalent of Claude Copilot /setup-project: wire a target repository to the shared Codex Copilot framework."
---

# Setup Project

Wire a project to Codex Copilot.

## Workflow

1. Before running setup, record whether project wiring or a project-authored description already exists. Use `scripts/setup-project.sh --project <path>` from the framework repo. Safe to re-run: if the project already has a codex-copilot install, this delegates to `scripts/update-project.sh` to repair the plugin/skill/QA-gate paths in place instead of refusing.
2. Treat `--force` as compatibility-only; it changes nothing (there is no longer a refusal to bypass).
3. Verify generated `AGENTS.md`, `.agents/plugins/marketplace.json`, `.claude/cc/config.json`, memory dirs, plugin links, `docs/40-initiatives/`, and the `scripts/copilot-gate.sh` link.
4. Confirm existing `AGENTS.md`, initiative documentation, and any file marked `owner: project` were preserved rather than replaced.
5. Run `cc skill list`, `cc docs sources`, `cc memory check --json`, `tc progress --json`, and `scripts/copilot-gate.sh` from the target project when available.
6. A project with no organization (no layer manifest and no inherited organization config) is a solo setup: organization sign-in and signed layer pins are optional, and the project is still fully wired. Signed layer resolution starts once an organization is configured; a broken organization setup still blocks. The project must sit inside an approved `projects.roots` folder (`cc config add projects.roots "<absolute folder>"`; prefer the project folder or its parent, never `$HOME`).
7. If wiring already exists and you only want a refresh (no first-install scaffolding), use `$update-project` / `scripts/update-project.sh` directly.

## Optional first-setup identity

Only after a new installation and successful verification, ask for an optional project description, main tech stack and teammate notes. Offer free text and a skip for each question. Skip this step for updates, existing wiring, failed or held setup, or an existing project-authored description in AGENTS.md or CLAUDE.md.

Write only supplied answers under a project-authored `## Project` section in AGENTS.md and, when present, CLAUDE.md. Preserve existing content and framework markers; omit skipped fields and write nothing if every question is skipped. Do not duplicate machine-level settings. Re-run verification; if it fails, undo only the new section and report the result.

## Output

- generated files
- plugin and skill link targets
- verification results

## Work Lifecycle

Apply the [shared work lifecycle](../cleanup/references/work-lifecycle.md) once
per task, including direct invocation of this skill: start/resume, maintain,
pause/handoff, finish and later reuse. Keep the checkpoint proportional in the
existing record; a small answer does not need a new task or document.

Existing project instructions are preserved by setup/update. Review their lifecycle
coverage and propose the minimal template pointer addition if missing, preserving
owner rules. Plugin refresh makes `$cleanup` available but does not silently edit
project-owned AGENTS.md or add lifecycle instructions to standalone optional packs.
