# Document Sequence Reference

The full design package structure. Facilitated documents (Phases 1–5) are completed in order with prerequisites. Phase 6 is a prototype output chosen by the user after the Design Complete Checkpoint passes.

---

## Sequence Overview

```
Phase 1: Discovery
  1. 00-vision.md
  2. 10-scope-and-non-goals.md
  3. 20-success-metrics.md

Phase 2: Research & Service Design
  4. 01-interview-self.md
  5. 30-jtbd.md
  6. 20-journey-maps.md
  7. 40-moments-that-matter.md
  8. 10-service-blueprint.md (optional for simple products)

  ── DESIGN FOUNDATION CHECKPOINT ──
  ░░ SOUL — DRAFT PASS  →  SOUL.md v0.1 (project root) ░░

Phase 3: Requirements
  9.  10-user-stories.md
  10. 20-use-cases-and-scenarios.md
  11. 30-acceptance-criteria.md

Phase 4: Experience Design
  12. 50-ux-design.md
  13. 60-ui-design.md
  14. 70-copy-voice.md

Phase 5: Design Challenge
  15. 00-brief.md
  ░░ SOUL — RATIFY PASS  →  SOUL.md v1.0 (project root) ░░

  ── DESIGN COMPLETE CHECKPOINT ──

Phase 6: Prototype (user chooses one)
  16a. 00-figma-design.md      OR
  16b. 10-design-spec.md       OR
  16c. 20-storybook.md         OR
  16d. 30-nextjs-prototype.md
```

---

## Document Details

### Phase 1: Discovery

| # | File | Agent | Prerequisites | What It Produces |
|---|------|-------|--------------|-----------------|
| 1 | `00-overview/00-vision.md` | SD | None | Problem statement, target users, core capabilities, forces map, JTBD (initial), magic moment, non-goals |
| 2 | `00-overview/10-scope-and-non-goals.md` | SD | #1 | In-scope features for v1, explicit non-goals with rationale, anti-features, constraints |
| 3 | `00-overview/20-success-metrics.md` | SD | #1, #2 | User outcome metrics, business outcome metrics, leading indicators, failure indicators |

**Notes:**
- Document #1 is the longest conversation — typically the most expansive Q&A session in the entire process
- Documents #2 and #3 can sometimes be combined into a single conversation if the user has clear answers
- The forces map in #1 uses the Moments Framework (Push, Pull, Anxiety, Habit)

### Phase 2: Research & Service Design

| # | File | Agent | Prerequisites | What It Produces |
|---|------|-------|--------------|-----------------|
| 4 | `01-research/10-interviews/01-interview-self.md` | SD | #1 | Participant context, current process, key quotes, pain points, risks, takeaways |
| 5 | `02-service-design/30-jtbd.md` | SD | #1, #4 | Primary job, supporting jobs, job ranking, competing solutions |
| 6 | `02-service-design/20-journey-maps.md` | SD | #1, #4, #5 | Personas, narrative journey map, struggling moments, emotional arc, touchpoints, service blueprint layers |
| 7 | `02-service-design/40-moments-that-matter.md` | SD | #6 | Critical moments with success/failure criteria, design implications, ranked by impact |
| 8 | `02-service-design/10-service-blueprint.md` | SD | #6 | Customer actions, frontstage, backstage, support processes, failure points |

**Notes:**
- Document #4 is a self-interview — the user answers as both the product creator and a prospective user
- Additional interviews can be added as `02-interview-user-01.md`, `03-interview-user-02.md`, etc.
- Documents #5 and #6 are the most design-critical — they drive everything downstream
- Document #8 is optional for simple products. Required for products with significant backstage processes (APIs, pipelines, automation)

### Design Foundation Checkpoint

**Check these before proceeding to Phase 3:**
- [ ] Vision + scope + success metrics exist (Documents #1–3)
- [ ] At least 1 completed interview artifact exists (Document #4)
- [ ] Journeys / JTBD / Moments That Matter exist (Documents #5–7)

**If anything is missing:** Surface what's missing and ask the user:
1. Create missing doc(s) now (pause downstream work)
2. Proceed without doc(s) using best judgment (list risks)

### Soul — DRAFT Pass

The soul file is created immediately after the Design Foundation Checkpoint, before Phase 3 begins.

| Output | Path | Role | Prerequisites | What It Produces |
|--------|------|------|--------------|-----------------|
| `SOUL.md` (DRAFT v0.1) | **Project root** | Industrial Designer (essentialism lens) | Documents #1–7; builds specifically on the Capabilities & Essence section (Round 7) of `00-vision.md` | Walk-away test in the user's words (asked first), draft soul statement, IS / IS-NOT table, design principles with rejection tests, named anti-patterns, Feature Filter gates ending with the Walk-away gate, first-draft quality bar and voice |

**Notes:**
- Full facilitation guide: the new-product skill's `references/soul-file.md`
- Builds directly on vision Round 7 (Capabilities & Essence) — that section is the upstream input the soul DRAFT formalises into a decision instrument
- Output path is the **project root** as `SOUL.md`, NOT inside `docs/` — it is a cross-phase decision instrument, not a phase deliverable
- All Phase 3–5 documents should be checked against the draft soul as they are written

### Phase 3: Requirements

| # | File | Agent | Prerequisites | What It Produces |
|---|------|-------|--------------|-----------------|
| 9 | `03-requirements/10-user-stories.md` | SD + UXD | #5, #6, #7 | User stories grouped by persona, prioritized P0/P1/P2, with dependencies |
| 10 | `03-requirements/20-use-cases-and-scenarios.md` | SD + UXD | #9 | E2E scenarios, edge cases, error scenarios |
| 11 | `03-requirements/30-acceptance-criteria.md` | SD + UXD | #9, #10 | Given/When/Then criteria, quality thresholds |

**Notes:**
- Document #9 is heavily informed by the JTBD and journey maps — cross-reference them
- Document #10 produces the scenarios that will be used for testing and that the design challenge will use for prototyping
- Document #11 is where testability thinking enters — every criterion must be independently verifiable

### Phase 4: Experience Design

| # | File | Agent | Prerequisites | What It Produces |
|---|------|-------|--------------|-----------------|
| 12 | `04-experience-design/50-ux-design.md` | UXD | #6, #7, #9 | Design principles, information architecture, task flows, interaction patterns, responsive strategy, accessibility |
| 13 | `04-experience-design/60-ui-design.md` | UIDS | #12 | Named visual direction, anti-direction, design tokens (colors, type, spacing), component patterns, references |
| 14 | `04-experience-design/70-copy-voice.md` | CW | #12, #13 | Voice character, speech patterns, key UI copy strings, microcopy patterns, banned language |

**Notes:**
- Document #12 is where the Service Designer's work gets translated into interaction design — every decision must trace back to a user need or struggling moment
- Document #13 should produce a named aesthetic direction — not vague adjectives
- Document #14 produces actual copy strings that the design team implements directly — specification, not suggestion

### Phase 5: Design Challenge

| # | File | Agent | Prerequisites | What It Produces |
|---|------|-------|--------------|-----------------|
| 15 | `05-design-challenge/00-brief.md` | Design Lead | ALL prior documents | Critical views list, creative direction, concepts per view, constraints, evaluation criteria |

**Notes:**
- This document synthesizes everything into an actionable brief for the prototype phase
- It must be specific enough that the design team can produce a prototype without further clarification
- The user must approve this brief before prototype work begins (Design Complete Checkpoint)

### Soul — RATIFY Pass

The soul file is ratified after Document #15 is approved and before the Design Complete Checkpoint runs.

| Output | Path | Role | Prerequisites | What It Produces |
|--------|------|------|--------------|-----------------|
| `SOUL.md` (RATIFIED v1.0) | **Project root** | Industrial Designer (essentialism lens) + Design Lead | SOUL.md DRAFT; Document #15 (design challenge brief) | Walk-away test re-asked and confirmed, populated case-law table, founding decisions settled and dated, principle priority order confirmed, soul marked RATIFIED v1.0 |

**Notes:**
- Full facilitation guide: the new-product skill's `references/soul-file.md`
- The brief (#15) surfaces the real trade-offs that populate the case-law table; the founding decisions convert open questions into settled, dated calls
- After ratification, run the Design Complete Checkpoint

### Design Complete Checkpoint

**Check before prototype work begins:**
- [ ] All design documents complete (Documents #1–15)
- [ ] Design challenge brief reviewed and approved by the user
- [ ] Creative direction is clear and agreed upon

---

### Phase 6: Prototype

The user chooses one output format based on their needs and audience. Only one is created.

| Option | File | Best For |
|--------|------|---------|
| 16a | `06-prototype/00-figma-design.md` | Visual fidelity, stakeholder reviews, design-to-dev handoff via Figma |
| 16b | `06-prototype/10-design-spec.md` | Developer handoff, implementation documentation, annotation-heavy specs |
| 16c | `06-prototype/20-storybook.md` | Component libraries, design systems, reusable UI at the component level |
| 16d | `06-prototype/30-nextjs-prototype.md` | Working prototype, real data, testable interactions, investor demos |

**Notes:**
- Help the user choose by asking: "Who needs to experience this, and what will they do with it?"
- Figma is best when a designer needs to iterate visually and hand off to developers
- Design spec is best when the output goes to a development team who needs every decision documented
- Storybook is best when the product is component-driven or part of a larger design system
- Next.js is best when the prototype needs to feel real, handle real interactions, or be tested with users
- Only one prototype format is created — if the user needs more than one, complete the primary first

---

## Document Creation Roles

| Role | Abbreviation | Phases |
|------|-------------|--------|
| Service Designer | SD | 1, 2, 3 |
| UX Designer | UXD | 3, 4 |
| UI Designer | UIDS | 4 |
| Copywriter | CW | 4 |
| Design Lead | Design Lead | 5 |
| Industrial Designer (essentialism lens) | ID | Soul DRAFT (after Phase 2) + Soul RATIFY (after Phase 5) |
| Implementation Team | — | 6 |
