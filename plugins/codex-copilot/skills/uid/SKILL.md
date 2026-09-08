---
name: uid
description: UI Developer for software interfaces. Use when implementing components, layouts, responsive behavior, styling, accessibility attributes, visual states, and translating UX/UI design direction into working frontend code.
---

# UI Developer

Use this skill to implement polished, accessible UI.

## Operating Lens

- Follow the repo's component, styling, and state-management patterns.
- Preserve the UX/UI design direction, including hierarchy, spacing, product language presentation, and state intent.
- Implement complete states, not just the happy path.
- Preserve stable dimensions for controls, grids, boards, tiles, and toolbars.
- Verify responsive behavior and accessibility.
- Keep UI changes scoped to the requested surface.

## Workflow

0. Read `08-taste/INDEX.md` from the nearest `paths.knowledge_repo` entry that has one — resolved tensions from this owner's own feedback, personal tier only, empty until earned. Apply the reasoning, not the example; when a rule does not fit, say so rather than forcing it.

1. Read the existing UI patterns and the relevant design direction.
2. Identify component boundaries and data/state inputs.
3. Implement layout, styling, states, and accessibility behavior.
4. Run the relevant checks and, for visual work, inspect the rendered result against the design direction.
5. Hand off to `$qa` for verification.

## Success Criteria

- Components preserve UX/UI direction.
- All relevant states are implemented.
- Responsive and accessibility behavior are verified.
- Layout geometry is stable across dynamic content.
- Implementation details are stored as a `code` work product when `tc` context exists.

## Iteration Loop

Implement, render or inspect the result, compare against design intent, fix mismatches, and hand off to `$qa`.

## Methodology

Use component-driven development and accessibility-first UI implementation.

## Anti-Generic Rules

- Do not implement only the happy path state.
- Do not introduce new styling conventions without a reason.
- Do not close UI work without responsive and accessibility checks.

## Output

Return:

- files changed
- states implemented
- design direction preserved or intentionally changed
- verification run
- remaining visual or accessibility risks

## Route To Other Specialist

- `$qa` for visual, interaction, accessibility, and regression verification.
- `$uids` when visual direction is insufficient.
- `$uxd` when interaction behavior is unresolved.

<!-- cse-design-quality:start -->
## Design Quality Contract

Use `adapt`, `harden`, `optimize`, `extract` and `polish`: implement the contracted states and real content, reuse existing tokens/components, inspect rendered desktop/narrow layouts and actual focus/error/reduced-motion behavior. Preserve a baseline, then provide source identities, screenshots and behavioral checks to QA; a static scan cannot certify rendered accessibility.

For material product-facing work, use `cc design template` to draft a task-bound surface contract, then `cc design context --contract <file> --action <action> --json` to load explicit product/design authority and one focused guide. Inspect omitted authority before editing. Surface modes (`persuade`, `operate`, `read`, `experience`) describe the user's job; they do not prescribe a style. Existing product facts, design systems, accessibility requirements and owner decisions govern the result.

After implementation, record design judgment with `cc design review` before `cc design audit --review ...`; then use `cc design report` to check criterion coverage, artifact hashes and freshness. A sequential critique is labeled sequential; claim independence only with evidence. Changed source, linked stylesheets or authority requires a fresh review and affected checks. Detector findings are contextual candidates, and report readiness never grants QA approval. Keep task execution and the final evidence-bound verdict in `tc`.

Load `cc design guide` for the full action catalog; retrieve focused guidance as needed instead of loading every playbook. `cc design compare` packages actual comparable captures for review; `cc design guide live` defines optional visual iteration ownership and cleanup. Native feedback is opt-in per project/runtime through `cc design feedback-config`; it neither installs a detector implicitly nor replaces explicit QA. See `cc design guide audit` for verification JSON and fallback rules.
<!-- cse-design-quality:end -->
