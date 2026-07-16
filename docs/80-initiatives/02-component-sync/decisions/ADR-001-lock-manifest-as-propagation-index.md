# ADR-001: Adopt Embedded Assets + Lock Manifest As The Machine-Wide Propagation Index

> Status: Accepted (owner, 2026-07-16)

## Context

The owner's top pain point is that updating a framework component means manually
re-running `/update-project` in every project, one at a time. There is no
machine-level index of *which project embeds which component at which version*,
so nothing can enumerate the affected projects or compute what is outdated.

codex-copilot initiative 02 (repository-portable-copilot), ADR-001, already
introduces exactly the artifact needed: **version-pinned framework assets
embedded as tracked repository files, plus a lock manifest recording source
versions, checksums, and ownership.** It introduced that manifest for
*portability* (survive a fresh clone). This decision reuses it for a second
purpose: as the **machine-readable index that makes machine-wide propagation
computable.**

The alternative substrate — symlinks into a shared framework checkout, which
codex 02 removes — gave automatic propagation for free but is fragile across
clone topologies and platforms and hides the version a project is actually
running.

## Decision

Component Sync **adopts codex ADR-001's embedded-assets + lock manifest as-is**
and treats it as the authoritative index for machine-wide operations. The
manifest is the contract every new `cc` verb reads:

- **project discovery** finds projects by locating their lock manifests;
- **freshness** compares each manifest's recorded component `version` against
  the latest published release tag;
- **materialize** uses each file's `ownership` (`framework` | `project`) to
  decide what it may write.

Per-file **ownership** is the load-bearing field: it is what lets propagation
update framework files while structurally guaranteeing project overrides are
never touched. Recorded **checksums** let drift be detected without trusting
timestamps. The recorded **releaseTag** is what makes every version change
reviewable (see ADR-002).

## Consequences

- Machine-wide propagation becomes a pure function of tracked manifests — no
  guessing, no scanning heuristics.
- The manifest schema becomes a frozen, versioned contract (`schemaVersion`)
  that both `cc` and Control Tower depend on; Phase 1 must freeze it before the
  verbs are built.
- Projects grow by the size of embedded assets + manifest (accepted in codex 02).
- Symlink auto-update is gone (codex 02); automatic propagation is re-provided
  at the machine level by this initiative instead — the manifest is the bridge.
- Ownership must be assigned correctly at embed time; a file mis-marked
  `framework` would be eligible for overwrite. Phase 1 owns that contract and
  its fitness check.

## Alternatives Rejected

- **Keep symlinks for auto-propagation:** rejected — codex 02 already removed
  them for portability; re-introducing them re-opens clone-topology fragility
  and hides the running version. Propagation is restored differently (this ADR).
- **A separate propagation index distinct from the portability manifest:**
  rejected — two indexes would drift. One manifest, two consumers.
- **Compute freshness from git history / file mtimes instead of a recorded
  version:** rejected — non-portable, non-deterministic, and unreadable by a
  render-only Control Tower.
- **Store the index centrally (per-machine registry file) instead of per
  project:** rejected — it would desync from the projects it describes and would
  not survive a clone; the per-project tracked manifest is self-describing.
