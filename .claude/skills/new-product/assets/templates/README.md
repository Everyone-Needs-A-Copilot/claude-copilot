# Product Design Creation — Template Package

This package guides product designers through facilitated conversations to create complete design documentation for a product, ending with a working prototype or design specification.

## What This Package Contains

17 standard outputs across 6 phases — 16 facilitated design documents (copied into `docs/`) plus `SOUL.md`, a root-level decision instrument drafted after Phase 2 and ratified after Phase 5. Every facilitated document contains an embedded facilitation guide as HTML comments — these guides tell Claude how to conduct the conversation, what questions to ask, and how to synthesize the output.

## How It Is Organized

| Phase | Folder | Purpose |
|-------|--------|---------|
| 1 — Discovery | `00-overview/` | Vision, scope, success metrics |
| 2 — Research & Service Design | `01-research/` + `02-service-design/` | Interviews, journeys, JTBD, moments |
| After Phase 2 — Soul DRAFT | Project root (`SOUL.md`) | Distil the product's soul: IS/IS-NOT, design principles, anti-patterns, Feature Filter (DRAFT v0.1) |
| 3 — Requirements | `03-requirements/` | User stories, use cases, acceptance criteria |
| 4 — Experience Design | `04-experience-design/` | UX, UI, copy and voice |
| 5 — Design Challenge | `05-design-challenge/` | Critical views brief |
| After Phase 5 — Soul RATIFY | Project root (`SOUL.md`) | Lock case law, founding decisions, principle priority order (RATIFIED v1.0) |
| 6 — Prototype | `06-prototype/` | Figma, design spec, Storybook, or Next.js |

## How to Use It

1. Start with `TODO-DESIGN-PACKAGE.md` — it is your progress tracker and resume point.
2. Find the first document marked `NOT STARTED` — that is where you pick up.
3. Open the document and tell your assistant: "Let's work on [filename]."
4. The assistant reads the facilitation guide (the HTML comment at the top of each file) and conducts a conversation with you to fill in the document.
5. When the document is complete, the assistant updates `TODO-DESIGN-PACKAGE.md` to mark it `DONE`.
6. Continue to the next document.

## Facilitation Guides

Every document begins with an HTML comment block marked `FACILITATION GUIDE`. These comments are invisible in rendered Markdown but are read by the assistant as instructions. They define:

- The prerequisite documents
- The conversation flow (what to cover in what order)
- The specific questions to ask
- How to synthesize the output

Do not delete the facilitation guides. They are the core value of this package.

## Phase 6: Prototype

After Phase 5 is complete, you choose one prototype output format. See `06-prototype/README.md` for guidance on which format fits your situation. You are not required to complete all four prototype formats — choose one and go deep.
