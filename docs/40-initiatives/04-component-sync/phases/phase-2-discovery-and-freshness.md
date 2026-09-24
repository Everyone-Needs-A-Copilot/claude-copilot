# Phase 2 — Read-Side Machine-Wide Verbs: Discovery + Freshness

> Status: Planned
> Complexity: Medium
> Depends on: Phase 1 (frozen schema)
> Gates: Phase 3 (materialize consumes discovery + freshness)

## Goal

Build the two read-only machine-wide `cc` verbs that enumerate projects and
compute what is outdated, both emitting the frozen `--json`. No writes.

## Deliverables

- `cc projects discover --json` — locates every lock-manifested project on the
  machine and returns each project's path, manifest path, and embedded
  components. Output shape per the initiative README.
- `cc freshness --all --json` — for every discovered project and for the
  global-once components, compares recorded `version` against the latest
  published release tag and classifies `current` | `outdated`. Includes the
  `dirty` flag per project and the `summary` roll-up counts.
- Global-once components reported once at machine scope, never per project.

## Acceptance criteria

- Discovery finds all manifested fixture projects and no non-manifested ones.
- Freshness classification is correct for both scopes against a fixture release
  feed; `summary` counts equal the per-project classifications.
- `dirty` reflects the real working-tree state (used later by materialize to
  decide holds).
- Both verbs are pure reads: running them changes zero files (fitness function:
  repo state identical before/after).

## Test requirements

Unit and integration tests required: discovery over a fixture machine tree,
freshness against a fixture release feed (both scopes), dirty-flag detection,
and a read-only-invariant assertion.
