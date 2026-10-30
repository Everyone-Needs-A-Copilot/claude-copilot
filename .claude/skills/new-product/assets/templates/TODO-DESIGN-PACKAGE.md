# {{PRODUCT_NAME}} — Design Package Status

> **Purpose:** Pick this up in a new conversation to finish the design package.
> **How to use:** Tell your assistant "Check TODO-DESIGN-PACKAGE.md for where I left off"
> **Note:** Find the first "NOT STARTED" document — that's where you pick up.
> **Created with:** new-product skill v{{SKILL_VERSION}}

---

## Status Summary

| Status | Count |
|--------|-------|
| NOT STARTED | 18 |
| IN PROGRESS | 0 |
| DONE | 0 |

---

## Phase 1: Discovery

### Design Foundation Checkpoint requirement: Vision + scope + success metrics exist

| # | Document | Status | Notes |
|---|----------|--------|-------|
| 1 | `00-overview/00-vision.md` | NOT STARTED | Facilitation guide ready. Covers: problem, users, vision, forces, JTBD, AI philosophy, capabilities, ecosystem context, warning signs |
| 2 | `00-overview/10-scope-and-non-goals.md` | NOT STARTED | Facilitation guide ready. Covers: scope, non-goals, anti-features, constraints, integration boundaries |
| 3 | `00-overview/20-success-metrics.md` | NOT STARTED | Facilitation guide ready. Covers: user outcomes, business outcomes, leading/failure indicators, ecosystem health |

---

## Phase 2: Research & Service Design

### Design Foundation Checkpoint requirement: At least 1 completed interview + journeys/JTBD/moments exist

| # | Document | Status | Notes |
|---|----------|--------|-------|
| 4 | `01-research/10-interviews/01-interview-self.md` | NOT STARTED | Self-interview (product owner interviews themselves as primary user) |
| 5 | `02-service-design/30-jtbd.md` | NOT STARTED | Jobs to be done across all personas |
| 6 | `02-service-design/20-journey-maps.md` | NOT STARTED | Primary stakeholder and trigger, progress statements, moments, struggling moments with stress 1-10 and forces, moments that matter (3 or 5), emotional arc |
| 7 | `02-service-design/40-moments-that-matter.md` | NOT STARTED | The 3 or 5 highest-stress struggling moments with evidence, forces, why they matter, success/failure criteria |
| 8 | `02-service-design/10-service-blueprint.md` | NOT STARTED | Optional for simple products — frontstage, backstage, support processes |

---

--- CHECKPOINT: Design Foundation ---

Before continuing to Phase 3, confirm:

- [ ] Vision + scope + success metrics complete (#1-3)
- [ ] At least 1 completed interview (#4)
- [ ] Journeys, JTBD, and Moments That Matter complete (#5-7)

---

## SOUL.md — DRAFT

Draft the soul file immediately after the Design Foundation Checkpoint passes, before Phase 3 begins.

| # | Document | Status | Notes |
|---|----------|--------|-------|
| — | `SOUL.md` (project root — not in docs/) | NOT STARTED | DRAFT v0.1: walk-away test in the user's words, soul statement, IS/IS-NOT table, design principles with rejection tests, named anti-patterns, Feature Filter gates. See the new-product skill's `references/soul-file.md` |

---

## Phase 3: Requirements

| # | Document | Status | Notes |
|---|----------|--------|-------|
| 9 | `03-requirements/10-user-stories.md` | NOT STARTED | User stories grouped by persona, prioritized |
| 10 | `03-requirements/20-use-cases-and-scenarios.md` | NOT STARTED | E2E scenarios, edge cases, critical view scenarios |
| 11 | `03-requirements/30-acceptance-criteria.md` | NOT STARTED | Given/When/Then, performance, quality criteria |

---

## Phase 4: Experience Design

| # | Document | Status | Notes |
|---|----------|--------|-------|
| 12 | `04-experience-design/50-ux-design.md` | NOT STARTED | IA, task flows, interaction patterns, responsive, accessibility |
| 13 | `04-experience-design/60-ui-design.md` | NOT STARTED | Visual direction, design tokens, component patterns |
| 14 | `04-experience-design/70-copy-voice.md` | NOT STARTED | Voice character, speech patterns, key UI copy, banned language |

---

## Phase 5: Design Challenge

| # | Document | Status | Notes |
|---|----------|--------|-------|
| 15 | `05-design-challenge/00-brief.md` | NOT STARTED | Critical views, creative direction, concepts per view, evaluation criteria |

---

## SOUL.md — RATIFY

Ratify the soul file after the design challenge brief (#15) is approved, before the Design Complete Checkpoint.

| # | Document | Status | Notes |
|---|----------|--------|-------|
| — | `SOUL.md` (project root — ratify pass) | NOT STARTED | RATIFIED v1.0: re-ask the walk-away test (no answer, no ratification), populate case-law table with real in/out verdicts from Phases 3–5, settle founding decisions with dates, confirm principle priority order. See the new-product skill's `references/soul-file.md` |

---

--- CHECKPOINT: Design Complete ---

Before continuing to Phase 6, confirm:

- [ ] All requirements documents complete (#9-11)
- [ ] UX, UI, and copy documents complete (#12-14)
- [ ] Design challenge brief written and approved (#15)
- [ ] Critical views list confirmed

---

## Phase 6: Prototype

Choose ONE output format. See `06-prototype/README.md` for guidance.

| # | Document | Status | Notes |
|---|----------|--------|-------|
| 16 | `06-prototype/[chosen-output].md` | NOT STARTED | User chooses format: Figma, Design Spec, Storybook, or Next.js |

**Chosen format:** _Not yet decided_

---

## Reference

| File | Purpose |
|------|---------|
| `01-research/10-interviews/00-interview-template.md` | Generic interview template — copy and rename for additional interviews |
| `06-prototype/README.md` | Guidance on choosing the right prototype format |
