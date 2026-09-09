# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

**Name:** {{PROJECT_NAME}}
**Description:** {{PROJECT_DESCRIPTION}}
**Stack:** {{TECH_STACK}}

---

## Claude Copilot

This project uses [Claude Copilot](https://github.com/Everyone-Needs-A-Copilot/claude-copilot).

**Full documentation:** `~/.claude/copilot/README.md`

### Commands

| Command | Purpose |
|---------|---------|
| `/protocol` | Start fresh work with Agent-First Protocol |
| `/continue` | Resume previous work via Memory Copilot |
| `/setup-project` | Initialize Claude Copilot in a new project |
| `/knowledge-copilot` | Build or link shared knowledge repository |

### Capabilities

| Capability | Tools | Purpose |
|------------|-------|---------|
| **Memory** | `cc memory` | Persist decisions, lessons, progress across sessions |
| **Agents** | 15 framework agents + kc (setup-only) via `/protocol` | Expert guidance routed by task type |
| **Knowledge** | `knowledge_search`, `knowledge_get` | Search company/product documentation |
| **Skills** | `cc skill search`, `cc skill get`, `cc skill select` | Load expertise on demand; `select` returns a bounded, receipted set — see Optional Context below |

### Agents

| Agent | Domain |
|-------|--------|
| `ta` | Tech Architect - system design, task breakdown |
| `me` | Engineer - code implementation |
| `qa` | QA - testing, edge cases |
| `sec` | Security - vulnerabilities, OWASP |
| `doc` | Documentation - technical writing |
| `do` | DevOps - CI/CD, infrastructure |
| `sd` | Service Designer - customer journeys |
| `uxd` | UX Designer - interaction design |
| `uids` | UI Designer - visual design |
| `uid` | UI Developer - component implementation |
| `cw` | Copywriter - microcopy, voice |
| `cco` | Creative Director - brand strategy, art direction, creative concepts |
| `ind` | Industrial Designer - essentialism, reduction, product-as-object |
| `cs` | Sales Advisor - sales strategy, pipeline, deal architecture |
| `kc` | Knowledge Copilot - shared knowledge setup |
| `cpa` | CPA Copilot - tax strategy, financial modeling, hiring economics |

### Configuration

| Component | Status |
|-----------|--------|
| Memory | Workspace: `{{WORKSPACE_ID}}` |
| Knowledge | {{KNOWLEDGE_STATUS}} |
| Skills | Local: `.claude/skills/` {{EXTERNAL_SKILLS_STATUS}} |
| Output | Verbosity `{{OUTPUT_VERBOSITY}}`, audience `{{OUTPUT_AUDIENCE}}` — see `.claude/agents/_shared/output-contract.md`; change with `cc config set output.verbosity <concise\|standard\|detailed> --project` |

---

## Optional Context

Mandatory repository/project/system instructions always apply; never filter or load them here.

Load needed additional knowledge once; use `selected[].content` or do not load it:

    cc skill select "<task topic>" --required <skill> --max-chars 12000 --json

Record one receipt per task, not per load:

    tc wp store --task <id> --type context --title "Context selection receipt" --file receipt.json

Keep `query`, `max_chars`, `loaded_characters`, `mandatory_over_budget`; each
`selected`/`excluded` entry's `name`, `source`, `source_revision`, `selection_reason`
or `reason`, not content. Before reselection read the receipt; skip held revisions.
Reload only changes; record both revisions and announce the change.

Retain required skills in full if `mandatory_over_budget: true`; report `max_chars`
and overage `loaded_characters - max_chars`. Characters are not tokens; receipts
prove selection, not reading/obedience.

Keep every required name in `selected[]`; identical aliases have `duplicate_of`,
empty `content`, zero charged characters/bytes: use the selected entry named by
`duplicate_of`. Optional
duplicates stay `excluded[]` as `duplicate-content`.

**Visible fallbacks:** name the applicable one, then continue:

- `cc` absent/nonzero: report failure/stderr; use repository instructions and prior memory only.
- Exit 2, `Required skill not found: <name>`: name it, never substitute; proceed without it or emit `<promise>BLOCKED</promise>` if indispensable.
- `selected: []`: report no match for the query; use repository instructions, never widen the query to force a match.
- `CC_KNOWLEDGE_REPOS` empty: "Knowledge tier
  unconfigured; optional context limited to project and machine skills." Never block.

---

## Session Management

**Start:** `/protocol` - Activates Agent-First Protocol

**Resume:** `/continue` - Loads from Memory Copilot

**End:** Run `cc memory store` to persist key decisions and lessons from the session

---

## Knowledge Copilot

Knowledge Copilot is the single source of truth for brand, voice, offerings, and processes. Consult it first — never invent or duplicate this knowledge.

```bash
eval "$(cc env)"   # hydrates CC_KNOWLEDGE_REPO
```

| Domain | Path under `$CC_KNOWLEDGE_REPO` |
|--------|----------------------------------|
| Voice & tone | `01-company/02-voice/` |
| Brand & visual | `01-company/01-brand/` |
| Services & offerings | `01-company/03-services/` |
| Methodologies | `01-company/06-methodologies/` |
| Products | `02-products/` |

Full contract: `$CC_KNOWLEDGE_REPO/docs/00-knowledge-copilot/02-consumption-contract.md`

---

## Project-Specific Rules

### No Time Estimates
All plans, roadmaps, and task breakdowns MUST omit time estimates. Use phases, priorities, complexity ratings, and dependencies instead of dates or durations. See `~/.claude/copilot/CLAUDE.md` for full policy.

{{PROJECT_RULES}}

<!-- cse-evidence-v2:start -->
## Task Acceptance and Tested Identity

Current QA-required work uses tc 2 evidence binding. Before implementation,
register a JSON acceptance contract with `tc task contract <id> --file <path>`:
`schemaVersion: 2`, `criteria: [{id, expected}]`, and explicit project-relative
`sources` files/directories covering implementation, dependencies and relevant
configuration. Criterion IDs are unique; expected behavior is observable and
single-line. Keep generated review outputs outside source scopes.

Before running verification, capture `tc task evidence-identity <id>` and retain
its exact `IDENTITY:` line in the task work product. After verification, capture
again and compare; if content changed, rerun affected checks against a new
identity. Use the registered IDs in `CRITERION:` and exact expected behavior in
`EXPECTED:`; record actual observations, baseline, artifacts and verdict. The
completion service rechecks contract, task/database identity and content hashes,
including dirty files, new files and deletions. It also enforces unfinished task
dependencies. Do not downgrade requiresQa or replace source evidence with prose.

A v1 packet for pending work must be migrated with a registered contract and
fresh verification. Historical completed records remain readable and explicitly
historical; they are not current strict QA evidence. cc design review/report
checks the named database's acceptance contract and source coverage; detector or
report readiness still never grants task approval. CLI/API and native adapters
share the same tc authority. Missing current capabilities require a verified tc
installation; legacy artifact inspection is not a current completion proof.
<!-- cse-evidence-v2:end -->
