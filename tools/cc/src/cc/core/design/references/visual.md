# Typography, hierarchy, composition and color

Start from surface intent and the established design system. Make information
priority visible through grouping, position, type roles and contrast before adding
decoration. Use spacing to explain relationships; measure actual computed values,
not just CSS declarations. Density is a task decision: a frequently scanned data
table and a first-visit narrative need different compositions.

Choose typography for legibility, language coverage, platform expectations and
the product's identity. A conventional font is valid when intentional. Establish
distinguishable heading, body, label and numeric roles; inspect actual strings,
wrapping, text scaling and fallback fonts. Use tabular figures where alignment
helps comparison. Avoid fixed heuristics that impose editorial line lengths or
display scales on compact controls and tables.

Give color semantic roles and verify rendered foreground/background contrast
against the applicable accessibility requirement, including hover, focus, disabled,
error and selected states. Test gradients, images and translucent layers at their
actual worst-case backgrounds. Do not rely on color alone to convey status.

Inspect all relevant viewport and content states together. Verify containers do
not clip focus rings, menus or translated labels; keep useful content discoverable
without accidental overflow. Cards, shadows, gradients and rounded shapes need a
purpose, not a universal ban. Every material change should have a named effect on
the task or approved expression and an observable fidelity check.
