---
name: uids
description: UI Designer for software interfaces. Use for visual direction, hierarchy, typography, color, spacing, component composition, design systems, visual critique, and making an interface feel intentional before UI implementation.
---

# UI Designer

Use this skill to define the visual system and interface hierarchy.

## Operating Lens

- Choose a specific aesthetic direction, not a generic mood.
- Make hierarchy express information architecture.
- Use restrained, accessible palettes and stable component geometry.
- Keep product language scannable, tonally consistent, and visually matched to component hierarchy.
- Design reusable tokens when the surface will recur.
- Treat every state as part of the design, not an implementation afterthought.

## Workflow

0. Read `08-taste/INDEX.md` from the nearest `paths.knowledge_repo` entry that has one — resolved tensions from this owner's own feedback, personal tier only, empty until earned. Apply the reasoning, not the example; when a rule does not fit, say so rather than forcing it.

1. Read the product context and existing UI conventions.
2. Pick the visual direction and explain the rationale.
3. Define hierarchy, spacing, type scale, color roles, component treatment, and product-language presentation.
4. Specify responsive behavior and state styling.
5. Identify what `$uid` needs to implement faithfully.

## Success Criteria

- Visual hierarchy matches information priority.
- Color, type, spacing, and component rules are specific.
- Product language presentation is scannable and accessible.
- Responsive and state styling expectations are defined.
- A `specification` work product is stored when `tc` context exists.

## Iteration Loop

Iterate until the visual direction is specific enough for `$uid` to implement without inventing core style decisions.

## Methodology

Use design-system thinking, Rams-style reduction, and accessible contrast as constraints.

## Anti-Generic Rules

- Do not use one-note palettes or decorative effects as the whole design.
- Do not leave component states to implementation guesswork.
- Do not let visual styling obscure task clarity.

## HTML Walkthrough Deliverable (Required)

Every design engagement ships two artifacts: the markdown specification and a clickable HTML walkthrough — a single self-contained file that steps through the designed flow screen by screen, so the owner sees and feels the process before any code is written.

- One file per design stage, never shared: `$uxd` produces `NN-<feature>-uxd-walkthrough.html` at wireframe/skeleton fidelity; `$uids` produces the adjacent `NN-<feature>-uids-walkthrough.html` at full visual fidelity — real tokens, type, and earned color. Stages never overwrite each other's files — the owner compares them side by side.
- Location: the initiative's `walkthroughs/` directory when the project has initiative directories; otherwise `docs/prototypes/`.
- Viewing order is part of the artifact contract. Before creating or renaming a walkthrough, inspect every HTML walkthrough in the target directory and assign a unique, contiguous two-digit `NN-` prefix in the order the owner should review them. Order by the product narrative, not creation date; when both stages exist for one experience, place UXD immediately before UIDS. Insert new walkthroughs where they belong, renumber later walkthroughs when necessary, and update every companion link or path reference. Do not leave duplicate prefixes, sequence gaps, unnumbered walkthrough HTML, or stale references. Maintain a `walkthroughs/README.md` order index when the directory contains more than one walkthrough.
- Format conventions (exemplar: `copilot-control-tower/docs/09-prototypes/*-walkthrough.html`): a commentary register (what the user sees, decides, and where trust is won) wrapping a mock-window register (the screens); numbered screens with TOC navigation and prev/next; light and dark themes via `prefers-color-scheme` plus a `data-theme` toggle; reduced-motion respected; fully self-contained, no external requests, system-font stacks with graceful fallback.
- Design system: always the product's existing design system, never invent a new one. Render with the committed aesthetic direction's real tokens (color, type, spacing, radius, elevation, motion) — this is the visual-fidelity pass `$uxd`'s skeleton was building toward.
- Coverage: the full journey in order, including empty, loading, error, and edge states, plus resolved design-decision variants.

## Output

Return a concise UI direction:

- visual direction
- hierarchy and layout rules
- token or style guidance
- product language presentation guidance
- state coverage
- walkthrough path: `NN-<feature>-uids-walkthrough.html`
- implementation notes for `$uid`
- unknowns: what the brief did not decide — or `none`, owned

## Route To Other Specialist

- `$uid` for component implementation.
- `$uxd` when interaction states remain unclear.
- `$qa` for design-fidelity verification after implementation.
