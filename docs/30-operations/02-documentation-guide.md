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

### Knowledge Copilot Structure

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

## Work Product Compression

### Size Targets by Type

| Work Product Type | Target Range | Hard Limit | Token Estimate |
|-------------------|--------------|------------|----------------|
| architecture | 800-1,200 words | 1,500 words | 1,120-1,680 tokens |
| technical_design | 600-1,000 words | 1,200 words | 840-1,400 tokens |
| implementation | 400-700 words | 900 words | 560-980 tokens |
| test_plan | 600-900 words | 1,100 words | 840-1,260 tokens |
| security_review | 500-800 words | 1,000 words | 700-1,120 tokens |
| documentation | Context-dependent | 2,000 words | 2,800 tokens |
| other | 400-600 words | 800 words | 560-840 tokens |

**Token conversion:** ~1.4 tokens per word for typical technical documentation.

**Hard limits:** Task Copilot validation enforces these limits. Exceeding hard limits results in rejection.

### Compression Techniques

| Technique | Token Savings | When to Use |
|-----------|---------------|-------------|
| **Tables over prose** | 25-50% | Lists, comparisons, specifications |
| **Bullets over paragraphs** | 15-30% | Action items, key points, requirements |
| **Omit articles in tables** | 10-15% | Column headers, table cells |
| **Front-loaded summary** | 0% (enables skipping) | All work products |
| **Reference over duplication** | 30-70% | Cross-referencing existing docs |
| **Abbreviations** | 5-10% | Common terms (env, config, auth, impl) |

**Table-first writing:**

```markdown
❌ Before (prose): "The authentication module supports three methods: JWT tokens for API access, OAuth2 for third-party integrations, and session cookies for web applications. JWT tokens expire after 1 hour. OAuth2 tokens expire after 30 days. Session cookies expire after 24 hours." (41 words, ~57 tokens)

✅ After (table):

| Auth Method | Use Case | Expiry |
|-------------|----------|--------|
| JWT | API access | 1 hour |
| OAuth2 | Third-party | 30 days |
| Session cookie | Web app | 24 hours |

(28 words, ~29 tokens - 49% savings)
```

**Reference over duplication:**

```markdown
❌ Before: "The user registration flow consists of: 1. User submits email/password 2. System validates email format 3. System checks email uniqueness 4. System hashes password with bcrypt 5. System creates user record 6. System sends verification email 7. User clicks verification link 8. System activates account."

✅ After: "Implements standard registration flow (see `docs/auth/registration.md`). Key validations: email format, uniqueness check. Password hashing: bcrypt (cost=10)."
```

### Attention-Optimized Structure

LLM attention degrades in middle sections. Structure work products to exploit attention curve:

**High Attention Zones (70-100% attention):**
- **Start (first 200 tokens):** Executive summary, key decisions, critical findings
- **End (last 150 tokens):** Action items, next steps, blocking issues

**Low Attention Zone (30-50% attention):**
- **Middle:** Supporting details, implementation notes, reference links

**Standard work product structure:**

```markdown
# [Title]

## Summary (HIGH ATTENTION)
- Key decision: [Most important outcome]
- Impact: [Primary effect on system]
- Next: [Critical next action]

## Decisions (HIGH ATTENTION)
| Decision | Rationale | Impact |
|----------|-----------|--------|
| Choice A | Reason | Effect |

## Implementation Details (LOW ATTENTION)
[Supporting information, references, notes]

## Files Modified (LOW ATTENTION)
- `path/to/file.ts`

## Next Steps (HIGH ATTENTION)
1. [Critical action]
2. [Blocking dependency]
```

### Heading Hierarchy for Importance

Use heading levels to signal importance to both humans and LLMs:

| Level | Purpose | Placement |
|-------|---------|-----------|
| `#` | Work product title | Once, at top |
| `##` | Critical sections | Summary, Decisions, Next Steps |
| `###` | Supporting sections | Implementation, Files, Notes |
| `####` | Minor subsections | Avoid if possible |

**LLM attention prioritizes:**
1. Higher-level headings (## > ### > ####)
2. First occurrence of each heading level
3. Sections with tables/structured data
4. Lists over prose

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
