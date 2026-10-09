# Agent Instructions

## Project Overview

- Project: `claude-copilot`
- Description: Public Claude Code instruction framework with specialist agents, lifecycle hooks, and the shared cc/tc command-line tools.
- Stack: Markdown agents/skills/commands; shell hooks; Python cc/tc tooling; Node utility scripts

## Project-Specific Rules

- This repository owns the public Claude Copilot framework and the shared `cc` / `tc` tools. Keep base agents generic and company-specific behavior in extension tiers.
- `VERSION.json.framework` is the framework version authority; `package.json.version` mirrors it. Component versions in `VERSION.json.components` are independent; never update the package version alone.
- When editing Claude agents, preserve their frontmatter (name, description, tools, model), role/mission, Core Behaviors, output format, Route To Other Agent, and Task Copilot Integration. Use industry-standard methods and document decision authority.
- Claude runtime guardrails, hook schemas, `@agent-*` routing, and slash commands describe the product maintained here; they are not Codex runtime features. Apply Codex specialist playbooks locally unless the user requests delegation.
- Read the relevant development guidance in `CLAUDE.md` when maintaining framework assets, and the corresponding `tools/cc/` or `tools/tc/` documentation when changing those tools. Do not import Claude session/delegation instructions into Codex.
- Before publishing/notarization, read `docs/30-operations/20-notarization-credentials.md`.
- Keep shared project requirements consistent between CLAUDE.md and AGENTS.md; preserve their scope and keep tool-specific instructions in the appropriate entrypoint.

## Project Commands

- For framework setup and verification, read `README.md` and `CONTRIBUTING.md`; for Python tool dependencies and focused tests, use the corresponding `tools/cc/` or `tools/tc/` project configuration. From the root, `bash scripts/check-versions.sh` checks version consistency. No application dev server applies.

## Instruction Scope

- Check applicable nested `AGENTS.md` / `AGENTS.override.md` before working in a subtree. Preserve scoped rules; references and Claude `paths:` frontmatter are not automatic Codex imports.
- Keep shared project requirements consistent with `CLAUDE.md` when present; preserve scope and keep tool-specific routing separate. Do not import either whole entrypoint into the other.

## Codex Copilot

- Use relevant skills exposed in this session. `$protocol` and specialist names are shorthand, not shell commands or requests to spawn agents. Read only task-relevant skills/references.
- Start with `$protocol` unless the specialist is obvious; use `$launcher` when routing is unclear. Apply playbooks locally; if unavailable in the session, inspect `plugins/codex-copilot/skills/<name>/SKILL.md`. Report missing capabilities.

## Output Contract

- Lead with the answer, decision, result, or blocker. Default to 6 sentences or 5 bullets; expand when completeness requires it. Preserve findings, uncertainty, citations, QA evidence, safety warnings, Task/WP identifiers, and blockers.
- For real decisions, give 2–3 concrete outcome options and a short question. Do not manufacture decisions or ask again for authorized work.
- Keep progress brief and material. Report outcome, changed scope, verification, and limitations at completion; store detail in `tc` work products.

## `cc` CLI

- Use `cc` for memory, skills, Live Docs, and configuration; `tc` for tasks/work products. The retired Copilot MCP servers and their `initiative_*`, `memory_*`, and `skill_*` tools do not exist.
- Prefer `$HOME/.local/bin/cc`; verify bare `cc` is not the C compiler. Source: Claude Copilot `tools/cc/`. Config: `.claude/cc/config.json`; memory: `.claude/memory/entries/`.
- When configuration is needed, run `eval "$($HOME/.local/bin/cc env)"`; use returned values instead of machine-specific paths.

## Live Docs

- Before planning or implementing against an installed third-party package API, run `$HOME/.local/bin/cc docs get <package> --topic <area> --json`.
- If `cc docs` is unavailable, state the limitation and verify against local package files or official documentation before coding.

## Knowledge and Optional Context

- For brand, voice, product, or methodology knowledge, hydrate `cc env`; follow project consumption-contract pointers through comma-separated `CC_KNOWLEDGE_REPOS`, nearest tier first, reading the first matching sub-path. Never use singular `CC_KNOWLEDGE_REPO` for sub-path lookup. Report missing sources; never invent company facts.
- Before `cc skill select`, read `plugins/codex-copilot/skills/specialist-agents/references/shared-behaviors.md`, section `Optional Context`. Follow its load-once, receipt, and fallback rules; mandatory instructions are never relevance-filtered.

## Task Management

- Track substantial work in `tc` PRDs/tasks and store detailed work products there; create missing records. Use `cc memory` for durable decisions and lessons.
- Prefer `tc`, then `./.venv-tc/bin/tc`; use `--json` where supported. Read `plugins/codex-copilot/skills/task-copilot/SKILL.md` when managing tasks.
- Batch three or more related operations using `tc.api`, or separately `cc.api`, with a verified interpreter. Never mix these APIs in one process.
- Formal initiatives belong in `docs/40-initiatives/NN-slug/`, indexed in `docs/40-initiatives/README.md`, with `README.md`, `phases/`, `decisions/`, and `retrospectives/`. Markdown holds durable rationale/evidence; `tc` owns live state. Never create `docs/initiatives/`.

### QA Gate Convention

- For verification-required implementation, set `metadata.requiresQa=true` and register observable criteria and source scope with `tc task contract <id> --file <path>` (`schemaVersion: 2`) before implementing.
- `$me` stores implementation evidence; `$qa` verifies it. Read their installed evidence contracts for those tasks.
- Capture `tc task evidence-identity <id>` before and after checks, preserve the exact `IDENTITY:` line, and rerun affected checks if the tested content changes.
- Store a task-bound `test` work product with matching `CRITERION:` / `EXPECTED:`, actual observations, inspectable `ARTIFACT:` evidence, untested scope, and one `VERDICT:`. Missing required behavior, bare markers, or stale evidence cannot support approval.
- Before completion, run `tc task check-qa <id> --json` and the setup-installed `scripts/copilot-gate.sh --task <id>`. Never remove `requiresQa` to bypass QA; installed hooks alone prove neither enforcement nor approval.

## Framework Rules

- Experience work starts with `$sd` / `$uxd`; visual direction uses `$uids` before `$uid`. Architecture and non-trivial technical work use `$ta`; `$me` implements and `$qa` verifies.
- Bugs follow `$qa -> $me -> $qa`; security-sensitive work includes `$sec`; infrastructure changes needing implementation follow `$do -> $me -> $qa`.
- Keep changes focused, preserve user work, omit time estimates, and respect the user's authorization and review boundaries.
- Use `spawn_agent` only when the user explicitly requests delegation, subagents, or parallel agent work.

### Delegating to Subagents

- Do not end a subagent prompt with an enumerated reporting checklist.
- The standing return contract is at most three sentences: outcome, root cause if known, and anything anomalous or requiring a decision. Put full evidence in a file and return its path.
- Surface every safety-relevant anomaly in those three sentences; never bury it only in the evidence file.
- Request more depth only when the decision genuinely depends on it.

## Debugging Discipline

When an explanation conflicts with a measurement, follow the measurement and narrow the investigation.

1. Confirm a mechanism exists in the relevant environment, plan, or account before naming it as the cause.
2. State what every diagnostic exercised, including the selected key, config, binary, branch, interpreter, and working directory when relevant.
3. Count failures through one shared dependency as one observation unless that dependency is varied.
4. After two hypotheses are falsified, stop hypothesizing. Read the code that enforces the behavior and cite `file:line`.

## Decision Instruments

- Read `SOUL.md` before substantial product-facing work to decide whether the direction belongs here; report missing or unfilled purpose rather than inventing it.
- Read `docs/01-architecture/12-architecture-guiding-principles.md` for durable architecture, migration, data, security, performance, or AI pipeline decisions. Report a missing reference and use verified project authority.
- When either instrument changes the route, state that before continuing.
