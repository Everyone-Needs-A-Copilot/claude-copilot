# Documentation Strategy Guide

Framework for consistent documentation optimized for both humans and LLMs.

## Core Principle

Documentation should make projects accessible to human contributors and LLM agents that need to understand, integrate with, or extend systems.

---

## Two-Tier Documentation Model

| Tier | Location | Audience | Token Budget |
|------|----------|----------|--------------|
| **Product Docs** | `docs/` in each repo | Developers, operators | Unlimited |
| **Shared Pack** | `docs/shared/02-products/<product>/` | LLMs, integrators | <4,000 total |

**Product docs:** Full implementation detail, runbooks, schemas, testing procedures.

**Shared packs:** Concise LLM-facing summaries with cross-links to detailed docs.

### Token Budgets by Page Type

| Page Type | Max Tokens | Notes |
|-----------|------------|-------|
| Overview | 700 | Purpose, capabilities |
| Architecture | 850 | + diagram reference |
| Deployment/Operations | 560 | Environments, monitoring |
| API | 700 | Endpoints, auth, payloads |
| Security | 420 | Auth methods, data handling |
| Integrations | 700 | Connections, webhooks |

**Efficiency tips:** Tables over prose (30-50% savings), bullets over paragraphs, omit articles in tables, use abbreviations (env, config, auth).

---

## Directory Structure

### Standard Project Structure

```
project-root/
├── README.md                    # Overview and quick start
├── docs/                        # Main documentation
│   ├── getting-started.md
│   ├── architecture.md
│   ├── api/
│   ├── guides/
│   └── troubleshooting/
└── examples/
```

### Shared Docs Structure

```
docs/shared/
├── 01-company/                 # Brand, services, GTM
├── 02-products/                # Product packs
│   ├── 00-ecosystem-overview.md
│   └── XX-product-name/        # Per-product folder
├── 03-ai-enabling/             # Profiles, operations
└── 99-docs-maintenance/        # Utilities
```

**Numbering rules:**
- `00` reserved for overviews only
- Content starts at `01`
- Files in shared packs: sparse numbering (`10-`, `20-`) for insertions

### Shared Pack Filenames

| File | Purpose |
|------|---------|
| `00-overview.md` | Summary, capabilities, status |
| `10-architecture.md` | Components, data flow |
| `20-deployment.md` | Environments, infrastructure |
| `30-operations.md` | Monitoring, runbook links |
| `40-integrations.md` | Connections, webhooks |
| `50-api.md` | Endpoints, auth, payloads |
| `60-security.md` | Auth, compliance |
| `70-decisions.md` | ADRs, priorities, gaps |
| `80-integration-prompt.md` | LLM integration prompt |

---

## LLM-Ready Documentation

### Required Header Block

```markdown
---
product: [Product Name]
status: [Active | Beta | Deprecated | Planning]
last_updated: YYYY-MM-DD
source_of_truth: [path to detailed doc]
owner: [team]
token_estimate: [number]
---
```

### Required Sections per Pack

1. **Purpose** - Problem solved, audience
2. **System Context** - Ecosystem position, components
3. **Data Model** - Key entities (table format)
4. **Key Flows** - Primary journeys (<5 steps each)
5. **Integrations** - Inbound/outbound connections
6. **Auth Methods** - Headers, tokens, signing
7. **Environment Matrix** - Domains per environment
8. **Security Posture** - Data handling, compliance
9. **Decisions/Gaps** - Priorities, limitations

### Cross-Link Format

```markdown
> **Full details:** [Page Title](relative/path/to/doc.md)
```

Place at section end, not inline. One per section maximum.

---

## Content Location Decision

| Content Type | Location | Rationale |
|--------------|----------|-----------|
| Step-by-step runbooks (>5 steps) | `docs/` only | Changes with code |
| Code examples, configs | `docs/` only | Must match implementation |
| Architecture diagrams | Both | Shared links to detailed |
| Environment matrix | Both | Shared=table, docs=rationale |
| API endpoint list | Both | Shared=summary, docs=specs |
| Error code reference | `docs/` only | Too detailed for summaries |
| Security posture | `docs/shared/` | LLMs need auth context fast |
| Security implementation | `docs/` only | Audit trail, compliance |
| Troubleshooting | `docs/` only | Requires full context |
| Data model (key entities) | Both | Shared=snapshot, docs=schema |

---

## Cross-Product Integration

### Integration Matrix Template

```markdown
| Direction | Partner | Method | Data Exchanged |
|-----------|---------|--------|----------------|
| Inbound | Product A | Webhook | Assessment results |
| Outbound | Product B | API | Synthesized insights |
```

### Shared Entity Template

```markdown
### EntityName
Used by: Product A, Product B

| Field | Type | Description |
|-------|------|-------------|
| id | uuid | Unique identifier |
| name | string | Display name |
```

### Integration Prompt Template (`80-integration-prompt.md`)

```markdown
# Integration: [Product Name]

## To send data TO [Product]:
1. Auth: [method]
2. POST to `[endpoint]`
3. Payload: `{ "field": "value" }`

## To receive data FROM [Product]:
1. Register webhook at [endpoint]
2. Validate signature (HMAC-SHA256)
3. Handle events: [list]

## Gotchas:
- [Known issue or constraint]
```

---

## Shared Pack Page Template

```markdown
---
product: [Product Name]
status: Active
last_updated: YYYY-MM-DD
source_of_truth: [path]
owner: [team]
token_estimate: [number]
---

# [Topic]: [Product Name]

## Summary
[2-3 sentences maximum]

## [Content Section]

| Column 1 | Column 2 |
|----------|----------|
| data | data |

## Key Points
- Point 1
- Point 2

> **Full details:** [Doc Title](path/to/doc.md)
```

---

## Duplication Control

**Prevention:** Run `99-docs-maintenance/check-shared-redundancy.sh` after changes.

**Handling redundant docs:**
```markdown
# [Title] - MOVED
**New location:** [Link](path/to/canonical.md)
**Archived:** YYYY-MM-DD
```

Then move to `_archive/` preserving directory structure.

---

## Writing Guidelines

| Principle | Do | Don't |
|-----------|-----|-------|
| Clarity | Use everyday language | Use jargon without explanation |
| Voice | Active, direct ("Click Save") | Passive ("The button should be clicked") |
| Steps | Number each, one action per step | Multiple actions per step |
| Tone | Conversational ("you'll") | Formal ("users must") |
| Structure | Scannable headings, bullets | Long prose paragraphs |
| Terms | Consistent terminology | Different words for same concept |

---

## Checklists

### New/Updated Feature

- [ ] Update detailed doc in `docs/`
- [ ] Update shared summary with cross-link
- [ ] Update `last_updated` in header
- [ ] Run redundancy check
- [ ] Verify cross-links resolve
- [ ] Update `40-integrations.md` if needed

### New Product Pack

- [ ] Create `docs/shared/02-products/XX-name/`
- [ ] Create `00-overview.md` with header block
- [ ] Add minimum: overview, architecture, API, integrations
- [ ] Add to `00-ecosystem-overview.md`
- [ ] Create `80-integration-prompt.md`
- [ ] Verify total <4,000 tokens

### Documentation Consolidation

- [ ] Run redundancy check script
- [ ] Classify duplicates (detail vs summary)
- [ ] Merge overlapping detail pages
- [ ] Replace shared duplicates with summaries + links
- [ ] Create redirect stubs for moved content
- [ ] Archive redundant files (never delete)

---

## Quick Reference

### Token Estimation

| Content Type | Tokens per 100 words |
|--------------|---------------------|
| Prose | ~140 |
| Tables | ~105 |
| Code blocks | ~125 |
| Bullets | ~115 |

### File Location Quick Test

| Question | Yes → | No → |
|----------|-------|------|
| >5 procedural steps? | `docs/` | Either |
| Contains code examples? | `docs/` | Either |
| Summary for quick context? | `docs/shared/` | `docs/` |
| LLMs need for integration? | Both | `docs/` |
| Security implementation? | `docs/` | `docs/shared/` for posture |
