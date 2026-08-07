# Phase 3 — Write-Side: Per-Project + Fan-Out Materialize

> Status: Planned
> Complexity: High
> Depends on: Phase 1 (schema), Phase 2 (discovery + freshness)

## Goal

Build the write verbs that actually propagate a release: per-project materialize
(framework-owned files only, hold on dirty, rollback on failure) and the fan-out
roll-up Control Tower renders.

## Deliverables

- `cc materialize --project <path> --component <name> --json` — updates only
  `ownership: framework` files to the target published release; holds (changes
  zero files, `result: held`, `heldReason: "dirty-working-tree"`) when dirty WIP
  touches a framework path; rolls back on failed apply (`result: rolled-back`).
- `cc materialize --fanout --json` — applies a component release across all
  embedding projects (per-project components fan out; global-once apply once),
  returning the aggregate + per-project roll-up per the README shape, with
  `triggeredBy` provenance.
- Enforcement of every never-destroy rule: framework-owned only, project-owned
  read-only, pull-only/downward (no push), reversible/rollback-guarded.

## Acceptance criteria (fitness functions)

- **Ownership containment:** post-run checksum of every `ownership: project`
  file equals pre-run — bit-for-bit. Any deviation fails the build.
- **Hold correctness:** a project with dirty WIP touching a framework path
  returns `held` and changes zero files.
- **Rollback:** an injected apply failure yields `rolled-back` with the prior
  version restored.
- **No upward path:** materialize performs no push / no write to any shared
  remote (fitness function: no network write, no shared-remote ref update).
- **Render parity:** the fan-out JSON validates against the frozen schema and
  populates every Arc 4 screen (the "across N projects to vX" line, the global
  once-line, the per-project held entries) with no render-side computation.

## Test requirements

Unit/integration tests AND a Control Tower render fixture required: per-project
apply/hold/rollback cases, fan-out roll-up across mixed scopes, the four fitness
functions above, and a golden `--json` fixture asserted against the Arc 4
screens.
