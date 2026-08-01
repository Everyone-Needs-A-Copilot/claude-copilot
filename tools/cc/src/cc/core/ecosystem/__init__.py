"""Pure ecosystem resolver — WS-A `resolve --explain --json` slice.

See:
  - copilot-control-tower/docs/reference/four-tier-topology.md §3-5 (manifest
    shape, rank rules, N-tier resolver walk)
  - copilot-control-tower/docs/reference/ecosystem-architecture.md §3.1
    (dimension override/accumulate semantics), §7.4 (override-stale)
  - copilot-control-tower/docs/01-architecture/schemas/resolve.schema.json

Modules:
  manifest.py    load + validate the layer manifest (I/O for loading; pure
                 validation)
  dimensions.py  the override/accumulate semantics table, as data
  resolver.py    the PURE fold (no I/O, no filesystem, no network)
  lockfile.py    READ-ONLY reader for the per-item SHA pins
  discovery.py   best-effort local-only scan that builds the `contributions`
                 input the pure resolver folds over (NOT the materialize
                 engine — that is a later, engine-blocked slice)
"""
