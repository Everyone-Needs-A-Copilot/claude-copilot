# Agent Instructions

## Project Overview

- Project: `claude-copilot`
- Description: Project using Copilot Control Tower
- Stack: Unknown

## Codex Copilot

This project uses the shared `codex-copilot` framework through the project-local plugin link:

- `./plugins/codex-copilot`

Use these native specialist skills when appropriate:

- `$protocol`
- `$launcher`
- `$sd`
- `$uxd`
- `$uids`
- `$uid`
- `$ta`
- `$me`
- `$qa`
- `$ind`
- `$sec`
- `$doc`
- `$do`

## Memory And Skills Copilot

Use the new `cc` CLI for persistent memory, skill discovery, and Copilot config. It replaces the old Skills Copilot and Memory Copilot MCP servers.

- Preferred command: `$HOME/.local/bin/cc`
- Fallback if needed: `cc`, after confirming it resolves to the Claude Copilot CLI and not the system C compiler
- Source: Claude Copilot `tools/cc/`
- Project config: `.claude/cc/config.json`
- Project memory: `.claude/memory/entries/`
- Project skills bridge: `.claude/skills/codex-copilot` -> `plugins/codex-copilot/skills`

When a task needs Copilot config values, run:

```bash
eval "$($HOME/.local/bin/cc env)"
```

Use `cc memory ...` for durable project/global memory and `cc skill ...` to list, search, inspect, and retrieve reusable skills.

### Apple Notarization Credential Doctrine

- The publisher Mac's `ct-notary` profile is a standing credential. The release
  environment stores its profile name, not the Apple password.
- Without an explicit `--keychain`, Apple `notarytool` stores the profile in the
  macOS Data Protection Keychain. Do not use `security find-generic-password`
  against `login.keychain-db` as an existence test.
- Probe with
  `xcrun notarytool history --keychain-profile ct-notary --output-format json`.
  Retry transient `No Keychain password item found` failures. If a later probe
  succeeds, continue the release and do not ask the owner to recreate the
  credential.
- Release scripts must preflight before expensive builds and retry only local
  Keychain-lookup failures at notarization boundaries. Never bypass signing,
  notarization, source verification, or artifact verification.

## Live Docs

Before planning or implementing against an installed third-party package API, use Live Docs through `cc`:

```bash
$HOME/.local/bin/cc docs get <package> --topic <area> --json
```

If `cc docs` is unavailable, say so and verify against local package files or official docs before coding.

## Task Management

Use `tc` for task tracking and work-product storage in this repository.

- Preferred command: `tc`
- Fallback if unavailable: `./.venv-tc/bin/tc`
- Use `--json` on commands that support it.

### Core Pattern

1. `tc task get <taskId> --json`
2. do the work
3. `tc wp store --task <taskId> --type <type> --title "..." --content "..." --json`
4. `tc task update <id> --status completed --json`

For three or more related `tc` operations, prefer one `python3` block using `tc.api`. For three or more related `cc` memory/skill operations, use a separate `cc.api` block. Keep `tc` and `cc` API blocks separate.

### Initiative Documentation

Formal multi-phase initiatives live in `docs/40-initiatives/NN-slug/`.

- each initiative includes `README.md`, `phases/`, `decisions/`, and `retrospectives/`
- initiative Markdown stores durable goals, phase design, decisions, validation evidence, and outcomes
- `tc` remains authoritative for live tasks, dependencies, assignments, work products, and QA status
- link initiative documents to their `tc` PRD/tasks instead of maintaining a second task board
- add every initiative to `docs/40-initiatives/README.md`
- never create `docs/initiatives/`

### QA Gate Convention

Codex Copilot cannot rely on Claude runtime lifecycle hooks such as SessionStart,
PreToolUse, or SubagentStop, so implementation work uses explicit `tc` state.
This does not change the design-led product creation protocol.

- implementation tasks that need verification should carry `metadata.requiresQa=true`
- `$me` stores an implementation work product and routes to `$qa`
- `$qa` stores a `test` work product with an `ARTIFACT:` marker and a `VERDICT: APPROVED`, `VERDICT: APPROVED-WITH-MINOR-FIXES`, or `VERDICT: REJECTED` token
- `scripts/copilot-gate.sh` can inspect QA-required tasks before closure; setup installs a project-local framework-owned copy

Passing QA verdicts must be evidence-bound. Valid artifact markers include
`test-run`, `file-check`, `diff-check`, `screenshot-check`, `a11y-check`, and
`design-fidelity-check`.

## Framework Rules

- Start new work with `$protocol` unless the correct specialist path is already obvious.
- Use `$launcher` when the correct specialist flow is unclear.
- Read `SOUL.md` before substantial product-facing work and use it to decide whether the direction should be built, reshaped, deferred, or rejected.
- Read `docs/01-architecture/12-architecture-guiding-principles.md` before durable architecture, migration, data, security, performance, AI pipeline, or productized implementation work.
- Use `$ta` before implementation for architecture, refactors, or non-trivial features.
- Use `$me` for implementation once the work is framed.
- Use `$qa` to verify implementation work.
- Use `$do -> $me -> $qa` for infrastructure, CI, deployment, and environment changes that require implementation.
- Use `spawn_agent` only when the user explicitly asks for delegation or parallel subagents.
- Keep plans free of time estimates.

## Decision Instruments

- `SOUL.md` is the product taste and purpose lens. It answers whether a product-facing direction belongs here.
- `docs/01-architecture/12-architecture-guiding-principles.md` is the technical lens. It answers how accepted direction should be built.
- When either file changes the route, state that explicitly before continuing.

## Project-Specific Rules

Add project-specific rules here.
