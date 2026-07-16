---
initiative: 02-component-sync
title: Component Sync — Update Once, Every Project Follows
status: planned
status_note: Approved for build (owner, 2026-07-16). Scope = the cc CLI machine-wide verbs + the tracked lock manifest; Control Tower rendering is downstream. Reconciles codex 02 (portability, removes symlinks) with claude 01 (Control Tower, guided sync) by restoring automatic propagation at the machine level.
owner: Pablo Alejo
created: 2026-07-16
execution_context:
  prd: null
  tasks: null
superseded_by: null
---

# Component Sync — Update Once, Every Project Follows

> Mode: Initiative
> Status: Planned — Approved for build (owner, 2026-07-16)
> Execution context: PRD-TBD / TASK-TBD (this initiative defines the CLI contract the PRD will schedule)

## Goal

Make "update a framework component once, and every project on the machine that
embeds it follows" a machine-level guarantee, not a manual chore. When a
component release is published (tagged), each machine notices on its normal
cadence sync and **auto-applies the framework-owned parts of that update to
every project that embeds the component** — holding, never touching, any
project whose personal working tree is in the way — and reports the result in
the past tense.

This is the owner's top pain point today. The current mechanics are a manual
fan-out: `/update-copilot` updates the machine's framework checkout, and then a
human must run `/update-project` **in each project, one at a time**. Nothing
enumerates the affected projects, nothing tells you which projects are running
an outdated component, and nothing propagates a release across the machine
without per-project human effort. This initiative closes that gap.

## Scope

- A **tracked lock manifest** in every project that records which framework
  components it embeds, at which versions, with **per-file ownership**
  (framework-owned vs project-owned). This adopts codex initiative
  02's ADR-001 embedded-assets + lock manifest as the machine-readable index
  that makes machine-wide propagation computable.
- New **machine-wide `cc` verbs**, all emitting `--json` for Control Tower to
  render (parse-never-compute; the app holds no sync logic — see
  copilot-control-tower CLAUDE.md invariant #1):
  - **project discovery** — find every lock-manifested project on the machine.
  - **freshness across all projects** — which projects (and which global
    components) are running an outdated version.
  - **per-project materialize** — update **framework-owned files only** in one
    project, **holding** any project with dirty personal changes in the way.
  - a **fan-out** roll-up that applies a component release across all embedding
    projects and returns aggregate + per-project results.
- The **global-once vs per-project distinction**: global components (Knowledge
  Copilot, CLI Copilot) update **once per machine**; per-project components
  (Claude Copilot, Codex Copilot harness layers) **fan out** across projects.
- The **trigger/cadence flow**: publish a release tag upstream → machines notice
  on cadence sync (Control Tower supervises the timer) → auto-apply
  framework-owned updates → report past-tense.

## Non-Goals

- **No upward sync.** Personal content never flows up. Materialize only ever
  *pulls* framework-owned content down into a project. Publishing to a broader
  tier stays a separate, human-invoked, distinctly-credentialed action
  (control-tower CLAUDE.md invariant #6; codex 02 non-goal).
- **No touching project-owned files.** Files the manifest marks `project` are
  never written, stashed, merged, or discarded — only checksum-compared for
  drift *reporting*.
- **No silent version changes.** A component is only ever moved to a version
  that exists as a **reviewable, published release tag upstream** — see the
  reconciliation below. Mutating a project to an unpublished/untagged version
  (local silent drift) is forbidden.
- **No resolution/merge/sync logic in Control Tower.** The app renders the JSON;
  `cc` computes (control-tower invariant #1). Even a conflict chooser would be
  CLI-computed.
- **No vendoring or updating of the host apps** (Claude Code, Codex) — those
  stay machine-owned prerequisites (codex 02 non-goal).

### The reconciliation: "reviewable version change" vs "local silent drift"

codex ADR-001 lists as a non-goal *"silently updating framework-owned files
without a reviewable version change."* This initiative auto-applies updates —
which must be shown **not** to violate that non-goal. The distinction:

| | Reviewable version change published upstream (**this initiative auto-applies**) | Local silent drift (**forbidden by both**) |
| --- | --- | --- |
| Origin | A tagged, published component **release** the lock manifest points at | An unpublished, untagged, in-place edit |
| Inspectable? | Yes — the diff is a normal, revertable change in the project; the release tag + checksums are recorded in the manifest | No — the change corresponds to no release anyone can review |
| Reported? | Yes — past-tense, with version, per-project, "See projects" detail | No |
| Reversible? | Yes — git-native; the applied bump is revertable and rollback-recoverable | n/a |

Auto-apply is therefore **not** silent: it (a) only advances to a version that
was *already made reviewable by being published as a release tag*, (b) lands as
an inspectable, revertable diff in the project, and (c) is reported in the
past tense with drill-in detail. What both initiatives forbid is moving a
project's framework files to a state that was never published — that path does
not exist here.

## Target Outcomes

- Given a published component release, **every embedding project on the machine
  is brought current without per-project human action**, except projects held
  for dirty WIP.
- `cc` can **enumerate** every lock-manifested project and report, over `--json`,
  exactly which are outdated and by how much — with **no** guessing, and with a
  clean global-once vs per-project split.
- A materialize run **provably** changes only framework-owned files; a
  project-owned override is byte-for-byte preserved across the update.
- A project with unsaved personal work **in the way of** a framework-owned file
  is **held** (state: waiting on your unsaved changes), never stashed or
  overwritten, and the hold reads as a fact, not a failure.
- Control Tower can render the Arc 4 surface —
  *"Updated Claude Copilot across 12 of your projects to v5.9.0"*, the
  See-projects drill-in, and the per-project held state — **purely from the
  `--json`**, computing nothing.

## The JSON surface (sketch)

The verbs below are the WS-A-style contract this initiative freezes. Field
names are illustrative; the schema is versioned (`schemaVersion`) so Control
Tower renders against a frozen shape.

### Lock manifest (per project, tracked)

```json
{
  "schemaVersion": "1.0.0",
  "components": [
    {
      "component": "claude-copilot",
      "scope": "per-project",
      "version": "5.9.0",
      "releaseTag": "claude-copilot@5.9.0",
      "source": "github:everyone-needs-a-copilot/claude-copilot",
      "files": [
        { "path": ".claude/commands/continue.md", "ownership": "framework", "checksum": "sha256:…" },
        { "path": ".claude/agents/custom-me.md",  "ownership": "project" }
      ]
    }
  ]
}
```

### `cc projects discover --json`

```json
{
  "schemaVersion": "1.0.0",
  "verb": "projects.discover",
  "generatedAt": "2026-07-16T14:02:11Z",
  "projects": [
    {
      "path": "/Volumes/Dev/Sites/acme-website",
      "manifestPath": ".copilot/lock.json",
      "components": [
        { "component": "claude-copilot", "scope": "per-project", "version": "5.8.1" },
        { "component": "codex-copilot",  "scope": "per-project", "version": "5.8.1" }
      ]
    }
  ]
}
```

### `cc freshness --all --json`

```json
{
  "schemaVersion": "1.0.0",
  "verb": "freshness.all",
  "generatedAt": "2026-07-16T14:02:11Z",
  "globalComponents": [
    { "component": "knowledge-copilot", "scope": "global", "installed": "3.2.0", "latest": "3.3.0", "state": "outdated" },
    { "component": "cli-copilot",       "scope": "global", "installed": "1.5.0", "latest": "1.5.0", "state": "current" }
  ],
  "projects": [
    {
      "path": "/Volumes/Dev/Sites/acme-website",
      "dirty": false,
      "components": [
        { "component": "claude-copilot", "installed": "5.8.1", "latest": "5.9.0", "state": "outdated" }
      ]
    }
  ],
  "summary": { "projectsTotal": 16, "projectsOutdated": 12, "projectsCurrent": 4 }
}
```

### `cc materialize --project <path> --component <name> --json` (one project)

```json
{
  "schemaVersion": "1.0.0",
  "verb": "materialize.project",
  "project": "/Volumes/Dev/Sites/acme-website",
  "component": "claude-copilot",
  "fromVersion": "5.8.1",
  "toVersion": "5.9.0",
  "releaseTag": "claude-copilot@5.9.0",
  "result": "applied",
  "heldReason": null,
  "filesChanged":  [ { "path": ".claude/commands/continue.md", "ownership": "framework", "action": "updated" } ],
  "filesSkipped":  [ { "path": ".claude/agents/custom-me.md",  "ownership": "project",   "action": "preserved" } ],
  "rollback": { "available": true, "restoredVersion": null }
}
```

`result` ∈ `applied | held | up-to-date | failed | rolled-back`.
When `held`, `heldReason` is `"dirty-working-tree"` and `filesChanged` is empty.

### `cc materialize --fanout --json` (the roll-up Control Tower renders)

```json
{
  "schemaVersion": "1.0.0",
  "verb": "materialize.fanout",
  "generatedAt": "2026-07-16T14:02:11Z",
  "triggeredBy": "cadence-sync",
  "components": [
    {
      "component": "claude-copilot",
      "scope": "per-project",
      "toVersion": "5.9.0",
      "releaseTag": "claude-copilot@5.9.0",
      "applied": 12, "held": 1, "upToDate": 3, "failed": 0,
      "projects": [ /* array of materialize.project results, as above */ ]
    },
    {
      "component": "knowledge-copilot",
      "scope": "global",
      "toVersion": "3.3.0",
      "releaseTag": "knowledge-copilot@3.3.0",
      "applied": 1, "held": 0, "upToDate": 0, "failed": 0
    }
  ]
}
```

`triggeredBy` ∈ `cadence-sync | manual | release-tag`. The fan-out roll-up maps
1:1 onto Arc 4: the per-component `applied` count is the *"across 12 of your
projects to v5.9.0"* line; `scope: global` renders as the one-time,
whole-organization line; the `held` per-project entries render as *"Waiting on
your unsaved changes."*

## The never-destroy rules

Materialize inherits the ecosystem's never-destroy posture (control-tower
CLAUDE.md invariants #3, #5, #6). Concretely:

1. **Framework-owned only.** Materialize writes a file **iff** the manifest
   marks its ownership `framework`. Project-owned files are out of bounds.
2. **Project-owned files are read-only to sync.** They are checksum-compared to
   report drift; they are never written, merged, stashed, or discarded.
3. **Dirty WIP in the way ⇒ hold the whole component update for that project.**
   Never stash, never `--force`, never "discard." Report `held` /
   *waiting on your unsaved changes* — a fact, not a warning. Only the user can
   action their own unsaved work; the app never offers "discard."
4. **Every applied update is reversible.** The bump lands as a git-native,
   revertable change; a rollback snapshot restores the prior framework-owned
   content if apply fails (`result: rolled-back`, keep the version that worked).
5. **Pull-only, downward.** Materialize never pushes and never writes to a
   shared remote. No upward sync path exists in this verb set.
6. **Global-once components** update at the single machine install location,
   never forked per-project.

## Routing (why auto-apply, why hold)

Per the actor-competence × reversibility routing rule (control-tower invariant
#5): a framework-owned bump to a **published** release tag is reversible and
**the user cannot meaningfully judge it** → **auto-act**, report past-tense.
Dirty personal WIP in the way is **the one thing only the user can action** →
**hold and report**, never ask-to-discard, never auto-resolve.

## Phase Index

| Phase | Goal | Status | Document |
| --- | --- | --- | --- |
| Phase 1 | Freeze the lock-manifest schema + ownership model (adopt codex ADR-001 as the machine-readable index) | Planned | [`phases/phase-1-lock-manifest-and-ownership.md`](./phases/phase-1-lock-manifest-and-ownership.md) |
| Phase 2 | Build the read-side machine-wide verbs: `projects discover` + `freshness --all` (`--json`) | Planned | [`phases/phase-2-discovery-and-freshness.md`](./phases/phase-2-discovery-and-freshness.md) |
| Phase 3 | Build the write-side: per-project + fan-out `materialize` with hold-on-dirty, rollback, past-tense roll-up | Planned | [`phases/phase-3-materialize-and-fanout.md`](./phases/phase-3-materialize-and-fanout.md) |

## Decisions

- [ADR-001: Adopt embedded assets + lock manifest as the machine-wide propagation index](./decisions/ADR-001-lock-manifest-as-propagation-index.md)
- [ADR-002: Auto-apply published framework updates; hold on dirty WIP](./decisions/ADR-002-auto-apply-and-hold-on-dirty.md)

## Relationship to the two prior initiatives

This initiative **resolves the tension** between them:

- **codex-copilot 02 (repository-portable-copilot)** removes the symlink
  auto-update model in favour of embedded, version-pinned assets + a tracked
  lock manifest. That trades away symlinks' automatic propagation for
  portability and reviewability.
- **claude-copilot 01 (ecosystem-extensions)** defines Control Tower and guided
  sync automation across the four tiers.

Component Sync **restores automatic propagation** — the thing symlinks gave for
free — but at the **machine level**, computed by `cc` from the very lock
manifests codex 02 introduces, and rendered by the Control Tower that claude 01
defines. Portability and automatic propagation stop being a trade-off.

## Validation Contract

Cannot be called complete until evidence-bound QA demonstrates:

- discovery enumerates every lock-manifested project on a fixture machine with
  no false positives/negatives;
- freshness correctly classifies current vs outdated for both global-once and
  per-project components;
- a materialize run over a fixture project with a **project-owned override**
  leaves that file byte-for-byte unchanged (fitness function: post-run checksum
  of every `ownership: project` file equals pre-run);
- a materialize run over a project with **dirty WIP touching a framework-owned
  path** returns `held` and changes zero files;
- a failed apply returns `rolled-back` with the prior version restored;
- the fan-out roll-up JSON validates against the frozen `schemaVersion` and maps
  onto every Arc 4 screen with no computation on the render side.

## Follow-ups (cross-repo, not done here)

- **Cross-link codex 02 ← this initiative.** Add a pointer paragraph in
  `codex-copilot/docs/40-initiatives/02-repository-portable-copilot/README.md`
  naming Component Sync as its machine-wide propagation companion (portability
  initiative removes symlinks; this one restores automatic propagation via the
  lock manifests it introduces). **Not edited here** — different repo, other
  sessions may be active. Owner/next session to apply.
- **Canonical-path drift (R8).** This repo keeps initiatives at
  `docs/80-initiatives/`; the ecosystem standard's canonical path is
  `docs/40-initiatives/` and flags `80-initiatives` as a hard failure. Placed
  here to sit beside the existing `01-ecosystem-extensions` sibling. Migrating
  both to `40-initiatives` (and backfilling `01`'s frontmatter + generating the
  index) is a separate, repo-wide cleanup — out of scope for this initiative.
- **Checker not installed here.** claude-copilot has no `check-initiatives.sh`
  pre-commit hook and no generated `README.md` index. Adopting the initiative
  package from `knowledge-copilot/00-best-practices/03-templates/07-initiative-package`
  would enforce this standard on every commit.

## Current Summary

Approved for build. The design (lock manifest + three machine-wide `cc` verbs +
fan-out roll-up + never-destroy rules) is ratified in this README and the two
ADRs. Implementation has not begun; the PRD/tasks join is TBD. WS-A-style schema
freeze (Phase 1) gates the read verbs (Phase 2), which gate the write/fan-out
verbs (Phase 3). Control Tower rendering is downstream and out of scope here.
