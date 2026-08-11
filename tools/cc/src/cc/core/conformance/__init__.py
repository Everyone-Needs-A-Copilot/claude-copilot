"""The `cc conformance` harness core — the ecosystem conformance test suite
described by the conformance harness design spec (six layers, one shared
result model).

Modules:
  types.py      the result model (Verdict, Severity, Scope, Evidence,
                 CheckResult) -- pure data, no I/O.
  registry.py    check registration and discovery: id -> {layer, severity,
                 applies_to_classes, mode, summary, remediation}, with
                 collision detection at registration time.
  report.py      human output and `--json` output; the no-averaging and
                 no-bare-"ready" refusals; exit-code computation; baseline
                 comparison.
  fsguard.py     the read-only tripwire that makes it safe to run checks
                 against the real machine: pre/post SHA-256 fingerprinting,
                 a git read-only plumbing allowlist, and a
                 write-refusing filesystem adapter.
  cache.py       per-repo verdict caching for the fast-mode sweep, keyed on
                 a (git HEAD, dirty bit, dimension-path mtimes) fingerprint.

Layers 1-6 (tier.py, stack.py, sweep.py+dimensions/, lock.py, roundtrip.py,
root_causes.py) and the CLI surface (commands/conformance.py) build on top
of these five modules; none of those siblings' files live in this package's
top-level __init__.py -- import from the specific submodule instead (this
mirrors `cc.core.ecosystem`'s own __init__.py, which is a docstring only).
"""
