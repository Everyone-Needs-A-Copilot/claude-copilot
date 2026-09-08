# Design judgment before automated findings

Resolve one stable target and its product/design authority. Inspect the rendered
surface when available, including actual task flow and important states. If only
source or old captures are available, state that limitation and verify their
identity; do not claim a live inspection.

Assess task clarity, hierarchy, discoverability, cognitive load, content truth,
visual fit, consistency, state completeness and accessibility. Record strengths
and specific issues before reading detector output. Explain why each issue matters
to this surface's job. Avoid a synthetic overall score that suggests objective
quality or hides a failed required behavior.

Use existing CSE specialist routing and delegation authorization. With one context,
record a sequential review; do not label it independent. With authorized isolated
reviewers, preserve evidence of separate inputs before synthesis. A reviewer who
has already seen the scan must say so rather than claim an unanchored judgment.

Record assessment JSON with `judgment`, `reviewed_by`, `method` (`sequential` or
`independent`), `detector_seen` (boolean), and `issues` (explicit array of `id`,
`severity`: `blocking|minor|question`, and `observation`); independent review also
requires `independence_evidence`. Then use `cc design review --contract ...
--assessment ... --output ... --json` and `cc design audit --review ... --output
... --json`. These receipts bind task scope and source bytes; they record reviewer
attestations rather than authenticating the reviewer or proving model compliance.
