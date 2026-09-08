# Complete states and responsive behavior

Exercise realistic minimum, typical and maximum data, including zero records,
long labels, unbroken strings, missing images and partially available results.
Preserve meaningful distinctions between empty, loading, error, disabled and
permission-limited states. Check persistence and recovery after refresh; a mocked
callback is insufficient evidence that the underlying change was saved.

Adapt the task structurally across supported viewports: navigation, columns,
tables, dialogs and controls may need different arrangements. Text must remain
readable and reachable under scaling; do not fix overflow by hiding important
content. Verify keyboard navigation, focus visibility, labels, announcements,
touch use and hover-independent affordances where they apply.

Check platform and language requirements explicitly. Test right-to-left layout,
translated strings, locale formatting and pluralization for the actual supported
locales. Do not call a single English screenshot an internationalization check.
Preserve native form behavior and use the established component library where it
already solves semantics, focus and interaction correctly.

Batch related viewport/state inspections, fix the observed defects, then rerun
the affected checks. A bounded polish budget must surface remaining requirements;
it cannot turn a known failure into approval. Record which devices, data, themes
and states were actually tested and route uncovered requirements to QA.
