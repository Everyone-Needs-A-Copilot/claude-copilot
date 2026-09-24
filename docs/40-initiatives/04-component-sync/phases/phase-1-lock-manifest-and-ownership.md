# Phase 1 — Freeze The Lock-Manifest Schema + Ownership Model

> Status: Planned
> Complexity: Medium
> Gates: Phases 2 and 3 (both read this schema)

## Goal

Freeze the versioned lock-manifest schema and the per-file ownership model that
every machine-wide verb depends on. This is the WS-A-style schema freeze: no
verb is built against an unfrozen shape.

## Deliverables

- A versioned (`schemaVersion`) lock-manifest schema (JSON Schema) covering:
  `component`, `scope` (`global` | `per-project`), `version`, `releaseTag`,
  `source`, and a `files[]` list with `path`, `ownership` (`framework` |
  `project`), and `checksum`.
- The **ownership assignment contract**: how, at embed time, each shipped file
  is marked `framework` vs `project`, and the rule that project overrides are
  additive (never mutate a framework entry to `project`).
- The **global-once vs per-project** classification list (per AS-7: Claude
  Copilot + Codex Copilot harness = per-project; Knowledge Copilot + CLI
  Copilot = global-once), recorded as data, not code.
- Alignment note reconciling this schema with codex 02's manifest so there is
  **one** manifest, two consumers (portability + propagation).

## Acceptance criteria

- Schema validates the example manifest in the initiative README.
- A fitness function asserts: every file path appears exactly once with exactly
  one ownership value; no `global` component appears in a per-project `files[]`.
- Round-trip: a manifest written by embed tooling validates and re-parses to an
  identical object.

## Test requirements

Unit and integration tests required: schema validation (valid + malformed
fixtures), ownership-uniqueness fitness function, and a codex-manifest
compatibility fixture.
