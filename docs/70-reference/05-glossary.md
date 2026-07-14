---
title: "Glossary"
status: Current
date: 2026-06-05
diátaxis-mode: Reference
---

# Glossary

**Diátaxis mode:** Reference. Concise definitions of acronyms, methods, and framework-specific terms used throughout Claude Copilot documentation. Each heading is a stable anchor for cross-document linking.

---

## Acronyms and Methods

### ADR

**Architecture Decision Record.** A short document that captures a significant architectural decision: the context, the options considered, the choice made, and the consequences. The `ta` agent authors ADRs using the standard format. See [ADR template docs](../10-architecture/00-overview.md).

### BM25

**Best Match 25.** The probabilistic ranking function that SQLite FTS5 uses to score keyword search results by relevance. Higher-scoring matches appear first. BM25 is not semantic (it does not understand meaning); it ranks by term frequency and inverse document frequency. `cc memory search` and `tc wp search` both use BM25 ranking.

### Diátaxis

A documentation framework by Daniele Procida that classifies every page into exactly one mode: **Tutorial** (learning-oriented), **How-to** (task-oriented), **Reference** (information-oriented), or **Explanation** (understanding-oriented). The `doc` agent applies Diátaxis when creating or reviewing documentation. See [Diátaxis official site](https://diataxis.fr/).

### DREAD

A threat-scoring model used alongside STRIDE. Each threat is rated on five dimensions — **D**amage, **R**eproducibility, **E**xploitability, **A**ffected users, **D**iscoverability — to produce a numeric risk score. The `sec` agent uses DREAD scoring to prioritize mitigations.

### FTS5

**Full-Text Search version 5.** The full-text search extension built into SQLite. `cc memory search` and `tc wp search` use FTS5 for keyword matching across stored entries. FTS5 is keyword-based, not semantic — it matches terms, not meaning. Results are ranked by [BM25](#bm25). The framework migrated away from claiming "semantic search" after PRD-2 verification.

### JTBD

**Jobs To Be Done.** A user-research framework that frames customer needs as "jobs" they are trying to accomplish, rather than as features or demographics. The `uxd` agent applies JTBD thinking when designing interaction flows.

### MCP

**Model Context Protocol.** An open protocol for connecting AI models to external tools and data sources. Claude Copilot originally used MCP servers for memory and skills. The framework migrated off MCP to the `cc` and `tc` CLIs, which do not require a running server. MCP references in older documentation are historical; current setup uses `cc version && tc version` to verify the CLIs.

### PRD

**Product Requirements Document.** A structured document defining the goals, scope, and tasks for a piece of work. The `tc prd create` command creates PRDs; the `ta` agent authors them as part of planning. PRDs live in the Task Copilot store and are referenced by tasks.

### SRE

**Site Reliability Engineering.** A discipline (originating at Google) that applies software engineering practices to operations: service-level objectives, error budgets, incident management, and infrastructure as code. The `do` agent applies SRE practices when designing CI/CD pipelines and infrastructure.

### STRIDE

A threat-modeling framework that categorizes security threats into six types: **S**poofing, **T**ampering, **R**epudiation, **I**nformation disclosure, **D**enial of service, **E**levation of privilege. The `sec` agent runs STRIDE analysis on authentication, authorization, and data-handling designs.

### 12-Factor

The **Twelve-Factor App** methodology, a set of principles for building software-as-a-service applications. Key factors include: strict config-from-environment, stateless processes, and explicit dependency declaration. The `do` agent references 12-Factor when reviewing deployment and infrastructure design.

---

## Framework Terms

### Auto-Firing Skill

A skill that Claude Code activates automatically based on its `description` field, without an explicit `@include`. When Claude Code reads a task description that matches a skill's trigger words, the skill surfaces into context. Manual `cc skill search` + `@include` is the fallback when auto-fire does not trigger.

### Known References Registry

A machine-level registry of named paths and values, configured via `cc config set refs.<name> <value>`. The `UserPromptSubmit` hook surfaces these into the first prompt of every session, making stable paths (e.g., a shared docs directory, a CLI path) available to all agents without re-supplying them. Distinct from `cc memory`: the registry holds stable config values; memory holds decisions and context.

### L1 / L2 / L3

The three tiers of the Anthropic SKILL.md skill architecture:

| Tier | Name | What It Contains | Runs How |
|------|------|-----------------|----------|
| **L1** | Metadata | `when_to_use`, `model`, `effort` hints | Auto-surfaced by Claude Code |
| **L2** | Prose | Human-readable guidance, checklists, examples | Read by the model into context |
| **L3** | Executable | Python/shell scripts with `!cmd` invocations | Run via Bash; output injected into context; source never enters context |

After PRD-2, 16 framework skills were upgraded from flat markdown to full L1/L2/L3; 13 legitimately-prose skills remain markdown-only.

### WP (Work Product)

A typed artifact stored in Task Copilot via `tc wp store`. Work products hold agent outputs — specifications, test reports, implementation notes, documentation — outside the main session context. Agents return a ~100-token summary to the main session and store all detail as a WP, reducing context bloat. Retrieve with `tc wp get <id>`. Types include `specification`, `documentation`, `test-report`, `implementation`, and `analysis`.

---

## The 16 Agent Codes (incl. kc)

| Code | Full Name | Role |
|------|-----------|------|
| `ta` | Technical Architect | System architecture, ADRs, PRD-to-task planning |
| `me` | Implementation Engineer | Feature implementation, bug fixes, refactoring (Kent Beck methodology) |
| `qa` | QA Engineer | Test strategy, coverage, bug verification (Meszaros methodology) |
| `do` | DevOps Engineer | CI/CD, deployment automation, infrastructure as code (12-Factor / SRE) |
| `doc` | Documentation Specialist | Technical docs, API docs, guides (Diátaxis framework) |
| `sd` | Service Designer | Customer journey mapping, touchpoint analysis, end-to-end experience strategy (IDEO methodology) |
| `uxd` | UX Designer | Interaction design, wireframing, task flows, information architecture (Nielsen / JTBD) |
| `uids` | UI Design System | Visual design tokens, color systems, typography, design system consistency (Rams Principles / Atomic Design) |
| `uid` | UI Developer | UI component implementation, CSS/Tailwind, responsive layouts, accessibility (Atomic Design / CDD) |
| `sec` | Security Engineer | Security review, vulnerability analysis, threat modeling (STRIDE + DREAD) |
| `ind` | Industrial Designer | Object-level essentialism, reduction, honesty of form; upstream of visual and interaction design (Dieter Rams / Jony Ive) |
| `cco` | Creative Director | Strategic creative direction, brand strategy, campaign concepts (Litmus Test methodology) |
| `cw` | Copywriter | UX copy, microcopy, error messages, user-facing content (Mailchimp Voice & Tone) |
| `kc` | Knowledge Copilot | Setup utility for shared knowledge repository; invoked via `/knowledge-copilot` (not a build-chain agent) |
