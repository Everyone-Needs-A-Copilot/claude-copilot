# Visual iteration and recovery

Keep scope and product truth fixed while exploring a design choice. Use a named
baseline and candidate with the same target, state, theme, viewport and realistic
data. Preserve an explicit source/runtime identity for each capture. Functional,
keyboard and persistence checks accompany visual inspection; a preferred image
does not establish working behavior.

`cc design compare manifest.json --output comparison.html --json` packages two
actual local PNG captures into an offline side-by-side reviewer. The manifest
names `surface`, `state`, `theme` and `viewport: [width,height]`; `baseline` and
`candidate` each contain `path`, `sha256`, `identity`, and the same `state`, `theme`
and `viewport`. Capture pixel dimensions must match. The output includes no
external requests and computes no quality score. Record actual reviewer decisions
and corrective work separately from image similarity.

Optional Impeccable live mode stays an external development tool. Use it only for
an explicitly chosen local checkout and target: first inspect the pinned engine's
current live workflow, current dev server, supported framework and mutation scope.
Save source hashes and a recoverable baseline before wrapping or accepting variants;
reuse the real server when suitable and record the stop method for any temporary
process. Do not inject into production, weaken CSP/browser security, publish
captures or start a model provider implicitly. CSE supplies no background server.

Accept only the selected variant's intended changes; inspect the diff, remove
tool-created preview scaffolding using the tool's supported cleanup, and verify
the real app and saved state afterward. Stop temporary processes and preserve
unrelated edits. If live tooling is unavailable or incompatible, the capture and
comparison workflow remains available through existing browser tools. Bound
iterations, report unresolved criteria and hand the actual evidence to QA.
