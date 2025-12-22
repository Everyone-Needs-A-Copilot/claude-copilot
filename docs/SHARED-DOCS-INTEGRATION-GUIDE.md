# Shared-Docs Integration Guide for Claude Copilot

**Purpose:** Define how shared-docs should be structured to optimize ingestion by Claude Code and Claude Copilot agents.

**Audience:** Documentation curators, developers maintaining shared-docs, Claude Code when consuming documentation.

---

## Overview

Claude Copilot consumes documentation through multiple touchpoints:

| Touchpoint | Trigger | Content Consumed |
|------------|---------|------------------|
| Session Start | Developer opens Claude Code | `CLAUDE.md` in project root |
| Agent Invocation | `@agent-sd`, `@agent-ta`, etc. | Agent profile from `.claude/agents/` |
| Skill Request | Developer/Claude requests skill | Skill from skills-hub MCP |
| Protocol Activation | `/protocol` or `/continue` | Working Protocol from operations docs |
| Voice Reference | Writing company content | Brand voice docs |
| Cross-Product Integration | Building connected features | Product docs via cross-links |

**Key Insight:** The problem isn't content quality—it's the **absence of navigation layers** that would help Claude Code find relevant context efficiently.

---

## Directory Structure

### Root Structure (Locked)

```
shared-docs/
├── 00-best-practices/     # Templates for developer rules, handoffs
├── 01-company/            # Identity, brand, voice, services, methodologies
├── 02-products/           # Product ecosystem and per-product packs
├── 03-ai-enabling/        # Skills, profiles, operations (proprietary)
├── _archive/              # Archived content (excluded from ingestion)
├── .claude/               # Claude Code configuration
├── CLAUDE.md              # Claude Code guidance
├── README.md              # Repository overview
└── STRUCTURE.md           # Structure enforcement
```

**Rule:** Root structure is FINAL. Do not create, rename, or remove root-level directories.

### Numbering Conventions

| Context | Pattern | Example |
|---------|---------|---------|
| Directories | Sequential `01-`, `02-`, `03-` | `01-company/`, `02-products/` |
| Files within packs | Sparse `10-`, `20-`, `30-` | `10-architecture.md`, `20-deployment.md` |
| Reserved | `00-` for entry points | `00-overview.md`, `00-index.md` |

**Sparse numbering** (10, 20, 30) allows inserting files without renumbering (15, 25 can be added).

---

## Navigation Layers

### Three-Tier Navigation System

```
Tier 1: Global Index (00-INDEX.md)
    └── Tier 2: Section Overviews (00-overview.md per directory)
        └── Tier 3: Individual Documents
```

### 00-INDEX.md (Create at shared-docs root)

Topic-based navigation for Claude Code to quickly locate relevant content:

```markdown
# Shared-Docs Navigation Index

## By Topic

### Security
| Document | Location | Tokens | For Agent |
|----------|----------|--------|-----------|
| Security Guidelines | 03-ai-enabling/03-operations/02-security-guidelines.md | ~800 | All |

### Company Voice
| Document | Location | Tokens | For Agent |
|----------|----------|--------|-----------|
| Identity | 01-company/02-voice/01-identity.md | ~600 | @cw, @sd |

### Methodologies
| Document | Location | Tokens | For Agent |
|----------|----------|--------|-----------|
| Forces Framework | 01-company/06-methodologies/10-forces-framework.md | ~1,500 | @sd |
```

### 00-overview.md vs 00-index.md

| File | Purpose | Use When |
|------|---------|----------|
| `00-overview.md` | Describes WHAT a section contains (context) | Products, concepts, domains |
| `00-index.md` | Lists WHAT EXISTS in section (navigation) | Collections (methodologies, patterns) |

---

## Token Budget Guidelines

### By Document Type

| Document Type | Max Tokens | Max Words | Rationale |
|---------------|------------|-----------|-----------|
| Skill (SKILL.md) | 2,000 | 1,400 | Proven effective |
| Product overview | 800 | 560 | Quick context |
| Product architecture | 1,200 | 840 | + 1 diagram reference |
| Product API summary | 1,000 | 700 | Endpoint list + auth |
| Product integration | 800 | 560 | Connection + webhooks |
| Operational guide | 4,000 | 2,800 | Detailed procedures allowed |
| Agentic profile | 2,000 | 1,400 | Current standard |
| Strategic profile | 800 | 560 | Current standard |
| Voice layer (total) | 4,500 | 3,150 | All voice files combined |

### Aggregates

| Aggregate | Max Tokens | Components |
|-----------|------------|------------|
| Product pack (total) | 4,000 | overview + architecture + API + integrations |
| Agent context load | 3,600 | Required docs for single agent |

### Efficiency Patterns

| Pattern | Token Savings |
|---------|---------------|
| Tables over prose | 30-50% |
| Bullet points over paragraphs | 20-30% |
| Omit articles in table cells | 5-10% |
| Use abbreviations (env, config, auth) | 5-10% |

### File Splitting Triggers

- Single file exceeds token budget → split by logical section
- Operational guides > 4,000 tokens → create overview + detailed sections
- Product packs > 4,000 tokens total → review for duplication

---

## Frontmatter Schema

### Three-Tier Metadata System

#### Tier 1: Skills (SKILL.md files)

```yaml
---
skill_name: forces-analysis
skill_category: analysis
description: One-line description for skill search
allowed_tools: [Read, Write, Edit]
token_estimate: 1850
version: 1.2
last_updated: 2025-01-15
owner: Service Design Team
status: active
tags: [forces, organizational-design, leadership]
methodology: 01-company/06-methodologies/10-forces-framework.md
related_skills: [moments-mapping, colab-facilitation]
---
```

#### Tier 2: Product Documentation

```yaml
---
product: Insights Copilot
status: active
last_updated: 2025-01-15
source_of_truth: ../../insights-copilot/docs/04-architecture/system-design.md
owner: Platform Team
token_estimate: 650
doc_type: architecture
ingestion_priority: high
dependencies: [forces-assessment, research-copilot]
summary: Intelligence synthesis platform for pattern detection
key_entities: [Force, Intelligence, Pattern, Stream]
integration_endpoints: [POST /api/forces, GET /api/patterns]
---
```

#### Tier 3: Operational Documentation

```yaml
---
title: Documentation Strategy Guide
doc_type: guide
category: operations
last_updated: 2025-01-15
version: 2.1
status: active
primary_audience: [developers, agents, documentation-curators]
required_reading: false
token_estimate: 2500
replaces: _archive/old-doc-guide.md
related: [05-documentation-guide.md]
---
```

---

## Agent Dependency Mapping

### Create: `03-ai-enabling/02-profiles/AGENT-DEPENDENCIES.md`

Maps which documents each agent requires:

```markdown
# Agent Context Dependencies

## Service Designer (@sd)

### Required Context (always load)
| Document | Reason | Tokens |
|----------|--------|--------|
| 01-company/02-voice/01-identity.md | Company voice | ~600 |
| 01-company/06-methodologies/10-forces-framework.md | Core methodology | ~1,500 |
| 01-company/06-methodologies/20-moments-framework.md | Core methodology | ~1,500 |

**Total minimum**: ~3,600 tokens

### Optional Context (load on demand)
| Document | When Needed | Tokens |
|----------|-------------|--------|
| 01-company/05-patterns/20-tension-patterns.md | Forces analysis | ~1,000 |

## Copywriter (@cw)

### Required Context
| Document | Reason | Tokens |
|----------|--------|--------|
| 01-company/02-voice/* | All voice files | ~4,500 total |

## Tech Architect (@ta)

### Required Context
| Document | Reason | Tokens |
|----------|--------|--------|
| 03-ai-enabling/03-operations/01-development-standards.md | Code standards | ~1,200 |
| Product architecture docs | Integration context | ~1,200 |
```

---

## Cross-Referencing Strategy

### Current Pattern

```markdown
> **Full details:** [Page Title](relative/path/to/detailed/doc.md)
```

### Enhanced Pattern: Typed Cross-References

```markdown
## Cross-References

**Source of Truth:**
→ [Architecture Deep Dive](../../product-repo/docs/04-architecture/system-design.md)

**Prerequisites:**
→ [Getting Started](./00-overview.md)
→ [Authentication Setup](./60-security.md#authentication)

**Related Concepts:**
→ [Shared Glossary: Force](../03-operations/12-shared-glossary.md#force)

**Implementation:**
→ [Task Breakdown](./80-integration-prompt.md)
```

### Link Registry Pattern (Per Product Directory)

Create `00-links.md` per product pack:

```yaml
---
# Link Registry: 02-products/06-insights-copilot
---

## Source of Truth Links
- architecture: ../../insights-copilot/docs/04-architecture/
- api: ../../insights-copilot/docs/05-api/

## Internal Links
- ecosystem: ../00-ecosystem-overview.md
- shared-glossary: ../../03-ai-enabling/03-operations/12-shared-glossary.md

## External Links
- production: https://insights.ineedacopilot.com
- repo: https://github.com/org/insights-copilot
```

---

## Product Pack Structure

### Standard Product Pack Template

```
02-products/06-insights-copilot/
├── 00-overview.md          # Entry point (800 tokens max)
├── 10-architecture.md      # System context (1,200 tokens max)
├── 20-deployment.md        # Environments (400 tokens max)
├── 30-operations.md        # Monitoring (400 tokens max)
├── 40-integrations.md      # How to connect (650 tokens max)
├── 50-api.md               # Endpoints (700 tokens max)
├── 60-security.md          # Auth/data (400 tokens max)
├── 70-decisions.md         # ADRs/gaps (400 tokens max)
└── 80-integration-prompt.md # LLM integration guide (600 tokens max)
```

**Total target:** < 4,000 tokens per product pack

### Each File Must Include

1. Frontmatter (product metadata)
2. Summary (2-3 sentences max)
3. Core content (tables preferred)
4. Cross-reference to detailed docs in product repo

---

## Content Optimization for AI

### Structural Patterns

| Pattern | Benefit |
|---------|---------|
| Tables for environment variables | Scannable, consistent |
| Tables for API endpoints | Easy extraction |
| Consistent field names matching code | Reduces confusion |
| Auth header examples with placeholders | Copy-paste ready |
| Inline defaults/thresholds | No hunting for values |

### Semantic Markers (Optional)

```markdown
<!-- AI_CONTEXT: Authentication required for all endpoints -->
| Method | Path | Auth | Purpose |
|--------|------|------|---------|

<!-- AI_CONSTRAINT: Rate limit 100 req/min per token -->
```

### Payload Examples with Type Annotations

```json5
{
  "event": "assessment.completed",        // string, required
  "assessment_id": "uuid",                 // UUID v4, required
  "forces": [                              // array, 1-20 items
    {
      "name": "string",                    // max 255 chars
      "intensity": 5                       // int, 1-10
    }
  ],
  "timestamp": "2025-01-15T10:30:00Z"     // ISO-8601, UTC
}
```

---

## Context Loading Strategy

### On Session Start

1. Load Tier 1: `00-INDEX.md` (~400 tokens)
2. If agent invoked, load agent manifest (~200 tokens)
3. Defer Tier 2 until needed

### When Agent Invoked

1. Load required context from `AGENT-DEPENDENCIES.md`
2. Surface optional context (don't auto-load)
3. Load dependencies on demand

### When User Asks Specific Question

1. Use `00-INDEX.md` to find topic docs
2. Load doc + stated dependencies
3. Suggest related docs

### Token Budget by Scenario

| Scenario | Target Budget |
|----------|---------------|
| Orientation only | < 500 tokens |
| Single agent task | < 4,000 tokens |
| Cross-product integration | < 6,000 tokens |
| Full context (rare) | < 10,000 tokens |

---

## Files to Create

### Priority 1: Navigation (Immediate)

| File | Location | Purpose |
|------|----------|---------|
| `00-INDEX.md` | `shared-docs/` root | Topic-based navigation |
| `AGENT-DEPENDENCIES.md` | `03-ai-enabling/02-profiles/` | Agent context requirements |
| `QUICK-START.md` | `shared-docs/` root | Task-based quick start |

### Priority 2: Catalogs (This Week)

| File | Location | Purpose |
|------|----------|---------|
| `00-skills-catalog.md` | `03-ai-enabling/01-skills/` | Searchable skill index |
| `00-profiles-catalog.md` | `03-ai-enabling/02-profiles/` | Agent/profile catalog |

### Priority 3: Per-Directory (Ongoing)

| File | Location | Purpose |
|------|----------|---------|
| `00-overview.md` | Each product directory | Product entry point |
| `00-links.md` | Each product directory | Link registry |

---

## Validation Skills

Claude Copilot provides three validation skills for maintaining shared-docs quality. These are invoked by Claude during sessions rather than run as external scripts.

### Available Skills

| Skill | Purpose | Location |
|-------|---------|----------|
| `token-budget-check` | Verify files comply with token budgets | `templates/skills/token-budget-check/` |
| `link-validation` | Find and fix broken markdown links | `templates/skills/link-validation/` |
| `frontmatter-validation` | Validate/fix YAML frontmatter metadata | `templates/skills/frontmatter-validation/` |

### Usage

Ask Claude to invoke a skill:

```
Check the token budgets for all files in docs/
```

```
Validate links in the shared-docs directory
```

```
Check frontmatter in 02-products/ and fix any issues
```

Claude will load the skill via `skill_get` and execute the validation, providing a report and optionally fixing issues.

### Skill Capabilities

| Skill | Reports | Auto-Fixes |
|-------|---------|------------|
| `token-budget-check` | Token counts, budget violations, optimization suggestions | Restructures prose to tables |
| `link-validation` | Broken links, missing anchors, path issues | Updates incorrect paths |
| `frontmatter-validation` | Missing fields, invalid values, stale data | Adds missing fields, updates dates |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Files to read for orientation | 3-5 | 1 (`00-INDEX.md`) |
| Tokens to understand agent needs | ~1,500 | ~400 |
| Time to find topic-specific docs | 2-5 minutes | 30 seconds |
| Dependency discovery | Manual | Automatic (frontmatter) |
| Product packs with complete metadata | ~30% | 100% |
| Directories with index files | ~60% | 100% |

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | Do This Instead |
|--------------|--------------|-----------------|
| Prose over tables | Wastes tokens | Use tables for structured data |
| Duplicate content across files | Version drift, maintenance burden | Cross-link to single source |
| No token estimates | Can't budget context | Add `token_estimate` to frontmatter |
| Missing entry point | Claude must explore | Add `00-overview.md` |
| Inline links everywhere | Hard to maintain | Use link registry pattern |
| Agent loads all context | Token waste | Use agent dependency manifest |

---

## Implementation Roadmap

### Phase 1: Navigation (Week 1)
- [ ] Create `00-INDEX.md` at shared-docs root
- [ ] Create `AGENT-DEPENDENCIES.md`
- [ ] Add token estimates to all frontmatter

### Phase 2: Catalogs (Week 2)
- [ ] Generate skills catalog
- [ ] Generate profiles catalog
- [ ] Consolidate voice layer files (optional)

### Phase 3: Product Packs (Week 3-4)
- [ ] Add `00-overview.md` to each product directory
- [ ] Add frontmatter to all product docs
- [ ] Create link registries per product

### Phase 4: Automation (Month 2)
- [ ] Token budget CI check
- [ ] Link validation in pre-commit
- [ ] Automated index generation

---

## References

- Extension Specification: [EXTENSION-SPEC.md](./EXTENSION-SPEC.md)
- Documentation Guide: [documentation-guide.md](./operations/documentation-guide.md)
- Working Protocol: [working-protocol.md](./operations/working-protocol.md)
