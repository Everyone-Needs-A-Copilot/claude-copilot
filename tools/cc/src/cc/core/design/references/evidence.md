# Review, audit and QA evidence

Define observable acceptance criteria before editing and preserve available
baseline evidence. The contract names the task, surface, states, authoritative
sources, target files and required checks. After implementation, record current
design judgment before the optional detector run. A changed source or authority
requires a fresh review and affected checks, not a copied old approval.

The pinned detector runs a raw static scan with project and inline suppressions
disabled. Its results are candidate findings, not an accessibility certification
or a release verdict. Keep the raw output, tested source identities, exact tool
hash and run status. Confirm each finding in context; preserve legitimate design
choices and use explicit evidence for false-positive or accepted-exception
dispositions. Fixing code requires another scan of the new source.

Verification JSON records `reviewed_by`, `baseline` (or unavailable reason), and
one record per criterion in `criteria`: `id`, `observed`, boolean `passed`, named
boolean `checks`, and local `artifacts` containing `path` and `sha256`. `issues`
maps initial issue IDs to `status` (`verified` or `accepted-minor`) and `reason`;
only minor issues may use the latter. `findings` maps detector IDs to `status`
(`false-positive` or `accepted-exception`) and `reason`; exceptions also name
their `authority`. Unresolved real findings remain gaps.

Use `cc design report --review ... --audit ... --verification ... --output ...
--json` to check coverage and freshness. If an optional scan is unavailable,
explicit manual fallback evidence must be recorded; never call the scan clean.
QA then verifies behavioral truth, artifact relevance and remaining gaps and
stores its own task-bound `test` WP with ARTIFACT and VERDICT. Report readiness
does not grant approval and never updates a task to completed.
