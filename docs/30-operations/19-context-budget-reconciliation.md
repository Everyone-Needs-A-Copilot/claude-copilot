# Context-budget reconciliation

The September 2026 CI repair keeps the original hard limits: **204,014 bytes of
agent source** and **26,268 bytes of always-loaded context**. It does not claim
that these byte estimates measure model quality or exact tokens.

## Reduction before measurement refresh

Later evidence, design and verification capabilities outgrew the August
`v5.13.5` snapshot. Compressing repeated explanations and command examples reduced
the agent corpus from **234,759 to 203,916 bytes** and always-loaded context from
**27,699 to 26,212 bytes**, measured against the old baseline before creating a new
one. Both old absolute ceilings therefore pass independently of rebaselining.

The existing per-file growth checks still flag engineering, QA, architecture and
protocol. Their distinct new responsibilities do not fit the August allocation
after the bounded, obligation-preserving compression pass. The checker already
identifies stale per-file references separately from content bloat and supports a
new versioned snapshot (`fitness-check.sh`, FF9 staleness diagnostic).

`context-budget-baseline-v5.15.1.json` records the resulting allocation explicitly.
This **changes per-file reference sizes**; it does not pretend the August per-file
limits passed. All growth/shrink ratios, absolute ceilings, conversion assumptions
and the override ledger remain unchanged. Historical baselines remain immutable.
New work is measured against this snapshot and must still fit the original hard
limits. A future snapshot alone cannot erase an absolute-budget breach.

## Preserved contracts

- Every agent keeps its role, frontmatter, iteration settings, routing and output
  fields. Shared Output Contract and Runtime Precedence remain fully embedded and
  byte-identical across the existing roster, with their original anchors.
- Optional Context remains embedded in all six existing consumers, including the
  project template and vendored Codex shared-behaviors reference. Required context,
  selection receipts, duplicate aliases and visible fallbacks remain enforced by
  the same instructions and checks.
- Engineering/QA retain the full verification policy, negative controls, fixed
  finish line, source-bound task authority, and design/evidence obligations.
- No mandatory content is hidden in a new helper. Named-file installations do not
  ship `_shared` sources, so the full contracts remain in their installed files.
- No test, golden assertion, hook, CLI implementation, budget checker or override
  is changed to obtain a pass. Only instruction wording and measured allocations
  change. This is not a package/API version change or a machine-wide rollout.

## Verification boundary

TASK77 in PRD9 records the plan, before/after identities, obligation review and
bounded source/installation checks. TASK73 covers the smoke repair; TASK76 retains
the exact PR/main CI and live merge-rule acceptance. Source approval is separate
from publication, whose finish line remains
[the CI delivery contract](18-ci-acceptance-and-merge-gates.md).

A fitness check against the existing publisher Mac also reports older,
unknown-origin deployed agent content. That finding is retained, not relabeled as
source success. This repair verifies a real disposable installation and hosted
CI; it does not overwrite that machine's agents or claim they were updated.
