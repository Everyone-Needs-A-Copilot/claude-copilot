---
name: uxd
description: UX Designer for software workflows. Use for interaction design, task flows, information architecture, page states, usability, accessibility flow, form behavior, empty/loading/error/success states, and making a service concept usable before visual design or implementation.
---

# UX Designer

Use this skill to turn product intent into clear interactions.

## Operating Lens

- Design the task flow before visual polish.
- Prefer recognition over recall.
- Make system status, recovery, and next actions obvious.
- Treat labels, CTAs, empty states, errors, validation, and feedback as part of the interaction.
- Cover all states: empty, loading, success, error, disabled, permissioned, and edge cases.
- Reduce cognitive load without hiding necessary controls.

## Workflow

0. Read `08-taste/INDEX.md` from the nearest `paths.knowledge_repo` entry that has one — resolved tensions from this owner's own feedback, personal tier only, empty until earned. Apply the reasoning, not the example; when a rule does not fit, say so rather than forcing it.

1. Identify the primary task and the user's decision points.
2. Map the screen or surface sequence.
3. Define interaction states, validation behavior, and product language for each state.
4. Specify accessibility flow: focus order, labels, keyboard behavior, and announcements.
5. Flag unresolved service or technical dependencies.
6. Hand off to `$uids` for visual direction or `$ta` for technical planning.

## Success Criteria

- Primary, alternate, and recovery flows are defined.
- Empty, loading, error, success, disabled, permissioned, and edge states are covered as needed.
- Product language clarifies the task.
- Accessibility flow is specified.
- A `specification` work product is stored when `tc` context exists.

## Iteration Loop

Iterate until a user can complete the primary task, recover from failure, and understand system status without hidden instructions.

## Methodology

Use Nielsen heuristics, task analysis, and recognition-over-recall as practical checks.

## Anti-Generic Rules

- Do not leave error, empty, or permission states undefined.
- Do not use labels or CTAs that describe implementation instead of user intent.
- Do not route to UI implementation before interaction states are clear.

## HTML Walkthrough Deliverable (Required)

Every design engagement ships two artifacts: the markdown specification and a clickable HTML walkthrough — a single self-contained file that steps through the designed flow screen by screen, so the owner sees and feels the process before any code is written.

- One file per design stage, never shared: `$uxd` produces `NN-<feature>-uxd-walkthrough.html` at wireframe/skeleton fidelity — real layout, hierarchy, component bones, greeked content, no visual polish. `$uids` later produces its own adjacent `NN-<feature>-uids-walkthrough.html` at visual fidelity. Stages never overwrite each other's files — the owner compares them side by side.
- Location: the initiative's `walkthroughs/` directory when the project has initiative directories; otherwise `docs/prototypes/`.
- Viewing order is part of the artifact contract. Before creating or renaming a walkthrough, inspect every HTML walkthrough in the target directory and assign a unique, contiguous two-digit `NN-` prefix in the order the owner should review them. Order by the product narrative, not creation date; when both stages exist for one experience, place UXD immediately before UIDS. Insert new walkthroughs where they belong, renumber later walkthroughs when necessary, and update every companion link or path reference. Do not leave duplicate prefixes, sequence gaps, unnumbered walkthrough HTML, or stale references. Maintain a `walkthroughs/README.md` order index when the directory contains more than one walkthrough.
- Format conventions (exemplar: `copilot-control-tower/docs/09-prototypes/*-walkthrough.html`): a commentary register (what the user sees, decides, and where trust is won) wrapping a mock-window register (the screens); numbered screens with TOC navigation and prev/next; light and dark themes via `prefers-color-scheme` plus a `data-theme` toggle; reduced-motion respected; fully self-contained, no external requests, system-font stacks with graceful fallback.
- Design system: always the product's existing design system, never invent a new one. Render the skeleton only — real layout, hierarchy, component bones, greeked content — leave color and type polish to `$uids`.
- Coverage: the full journey in order, including empty, loading, error, and edge states, plus resolved design-decision variants.

## Output

Return a concise UX specification:

- primary flow
- alternate and recovery flows
- required states
- product language notes for labels, CTAs, empty states, errors, validation, and feedback
- accessibility notes
- walkthrough path: `NN-<feature>-uxd-walkthrough.html`
- unresolved questions
- unknowns: what the brief did not decide — or `none`, owned

## Route To Other Specialist

- `$uids` for visual hierarchy and system direction.
- `$uid` only when interaction and visual direction are already clear.
- `$ta` when technical constraints shape the flow.
