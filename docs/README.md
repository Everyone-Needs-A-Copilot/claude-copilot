# Claude Copilot Documentation Index

This file maps the full `docs/` taxonomy. Use it as a starting point before reading any section.

---

## Root

| File | Description |
|------|-------------|
| `docs/00-overview.md` | Framework overview — the five pillars, component map, and design philosophy |

---

## 01 — Getting Started

Tutorial-mode pages for new users.

| File | Description |
|------|-------------|
| `01-getting-started/01-user-journey.md` | Step-by-step first session: install, first `/protocol`, first agent handoff |
| `01-getting-started/02-learning-roadmap.md` | Learning path from zero to advanced framework use |

---

## 10 — Architecture

Explanation-mode pages on how and why the framework is structured.

| File | Description |
|------|-------------|
| `10-architecture/00-overview.md` | Architecture overview and component relationships |
| `10-architecture/01-agents.md` | Agent roster, capabilities, and inter-agent routing rules |
| `10-architecture/02-philosophy.md` | Design principles: context economy, ephemerality, battle-tested workflows |
| `10-architecture/03-decision-guide.md` | When to use which agent, command, or tool |
| `10-architecture/04-framework-restructure-2026-04.md` | ADR: April 2026 restructure — MCP → CLI migration rationale |

---

## 20 — Configuration

Reference-mode pages for settings and customisation.

| File | Description |
|------|-------------|
| `20-configuration/01-configuration.md` | Environment variables, `.claude/` directory layout, `cc config` |
| `20-configuration/02-customization.md` | Per-project overrides, `.claude/quality-gates.json`, agent model pinning |
| `20-configuration/03-references-registry.md` | Shared-docs and knowledge-repo path registry reference |

---

## 30 — Operations

How-to pages for day-to-day and advanced operational use.

| File | Description |
|------|-------------|
| `30-operations/01-working-protocol.md` | Session lifecycle: `/protocol`, `/continue`, `/pause` workflows |
| `30-operations/02-documentation-guide.md` | How to author and maintain Copilot documentation (Diátaxis) |
| `30-operations/03-agent-guide.md` | How to author, modify, and extend agents |
| `30-operations/04-token-efficiency-playbook.md` | Patterns for keeping main-session token budgets lean |
| `30-operations/05-deploy-and-verify.md` | Deployment and infrastructure agent workflows |
| `30-operations/06-skills-authoring-guide.md` | How to write and publish a `cc skill` — metadata, triggers, SKILL.md format |

---

## 40 — Extensions

Reference + explanation pages for the extension and knowledge-repository system.

| File | Description |
|------|-------------|
| `40-extensions/00-extension-spec.md` | Extension specification: override, extension, and skills extension types |
| `40-extensions/01-shared-docs-integration.md` | How shared-docs and knowledge repositories integrate with agents |

---

## 50 — Features

Feature reference and explanation pages. One page per major system feature.

| File | Description |
|------|-------------|
| `50-features/00-enhancement-features.md` | 12 enhancement features: quality gates, activation mode, continuation enforcement, auto-compaction, and more |
| `50-features/01-orchestration-workflow.md` | Parallel stream execution with `/orchestrate` — generate, start, status, merge |
| `50-features/02-orchestration-troubleshooting.md` | Diagnosing and fixing orchestration issues: PATH, worktrees, zombies, stream dependencies |
| `50-features/03-knowledge-sync.md` | Automated knowledge updates on git release tags via post-tag hook |
| `50-features/04-goal-driven-agents.md` | Goal-driven iteration loop: verify outcomes, not just execute steps |
| `50-features/05-worktree-isolation.md` | Git worktree lifecycle per task: create, merge, conflict resolution, cleanup |
| `50-features/06-opus-46-capabilities.md` | Opus 4.6 capabilities: 1M context, effort parameter, ecomode refactor |
| `50-features/07-correction-detection.md` | Auto-capturing user corrections and routing them to skills, agents, or memory |
| `50-features/08-ecomode.md` | Smart model routing: complexity scoring + effort-level keywords |
| `50-features/09-magic-keywords.md` | `/protocol` modifier and action keyword reference (`eco:`, `fast:`, `max:`, `fix:`, `add:`, etc.) |
| `50-features/10-progress-hud.md` | Terminal statusline and progress bar components for real-time task visibility |
| `50-features/11-zero-config-installation.md` | NPM-package and source-based installation, platform setup, MCP server builds |
| `50-features/12-code-execution-path.md` | How to compose multi-step `tc.api` / `cc.api` operations in one python3 block for ~99% intermediate-output savings |
| `50-features/13-memory-fts5.md` | Memory Copilot is FTS5/BM25 keyword search, not semantic; entry types, storage layout, pluggable backend seam |
| `50-features/14-plugin-install.md` | Installing Claude Copilot as a native Claude Code plugin; ceiling/floor model; how `cc` runtime assembly composes with plugin-provided base agents |
| `50-features/15-live-docs.md` | Live Docs (`cc docs`): version-exact package documentation for agents; local-first source order, optional fetch extra, Context7 deferred |

---

## 60 — QA

Testing and validation pages.

| File | Description |
|------|-------------|
| `60-qa/00-testing.md` | Framework testing strategy and test matrix |
| `60-qa/01-framework-validation-strategy.md` | Validation approach for agent behaviour and protocol conformance |
| `60-qa/02-time-estimate-test-plan.md` | Test plan for time-estimate-free language enforcement |
| `60-qa/03-time-free-language-guide.md` | Guide for writing outputs without duration estimates |

---

## 70 — Reference

Reference-mode pages for quick lookup.

| File | Description |
|------|-------------|
| `70-reference/00-quick-reference.md` | Command and agent cheat sheet |
| `70-reference/01-usage-guide.md` | Full usage guide: commands, agents, skills, memory |
| `70-reference/02-upgrade-guide.md` | Upgrade notes between framework versions |
| `70-reference/03-competitive-landscape.md` | How Claude Copilot compares to other agent frameworks |
| `70-reference/04-framework-modernization-analysis.md` | Analysis of the MCP → CLI migration and framework modernization |
| `70-reference/05-glossary.md` | Definitions for framework terms: Memory Copilot, Task Copilot, extensions, work products, agent codes |

---

## Schemas

JSON schemas for knowledge repository manifest and example files.

| File | Description |
|------|-------------|
| `schemas/knowledge-manifest-schema.json` | JSON Schema for `~/.claude/knowledge/knowledge-manifest.json` |
| `schemas/knowledge-manifest.example.json` | Annotated example knowledge manifest |

---

## Navigation Tips

- **New user?** Start at `01-getting-started/01-user-journey.md`.
- **Understanding the framework?** Read `10-architecture/00-overview.md` then `10-architecture/02-philosophy.md`.
- **Configuring for a project?** See `20-configuration/01-configuration.md`.
- **Writing your first agent?** See `30-operations/03-agent-guide.md`.
- **Token budget blowing up?** See `30-operations/04-token-efficiency-playbook.md` and `50-features/12-code-execution-path.md`.
- **Memory not returning expected results?** See `50-features/13-memory-fts5.md`.
- **Orchestration broken?** See `50-features/02-orchestration-troubleshooting.md`.
