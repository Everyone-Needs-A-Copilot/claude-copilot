---
initiative: 06-central-resolution
title: Central Resolution — One Release Pointer, Zero Per-Project Sync
status: in-progress
status_note: ADR-001 is Proposed until it lands and the pilot checkpoint (PRD-16 task 208) passes. Fleet migration waits for the owner's go-ahead.
owner: Pablo Alejo
created: 2026-11-06
execution_context:
  prd: 16
  tasks: null
superseded_by: null
---
# Central Resolution

Every project stops carrying copies of the framework. Claude Code and Codex resolve agents, commands, skills, hooks and plugins from one machine-level release pointer, `~/.copilot/current`, so a release reaches all projects and both runtimes in one flip and no project is touched.

## Why

Each project carried about 151 framework-owned files and two checksum locks, so any framework change made all 71 live projects stale and each needed its own reconcile and commit. The framework now only has to work on machines with the CSE installed, so the copies buy nothing.

## Decision

[ADR-001: One release pointer, zero per-project sync](decisions/ADR-001-central-release-pointer.md). It supersedes:

| Superseded decision | Repo |
|---|---|
| [component-sync ADR-001 (lock manifest as propagation index)](../04-component-sync/decisions/ADR-001-lock-manifest-as-propagation-index.md) | claude-copilot |
| [component-sync ADR-002 (auto-apply, hold on dirty)](../04-component-sync/decisions/ADR-002-auto-apply-and-hold-on-dirty.md) | claude-copilot |
| `docs/40-initiatives/02-repository-portable-copilot/decisions/ADR-001-embed-assets-and-derive-caches.md` (supersession note lands on branch `docs/central-resolution-adr`) | codex-copilot |

Hold-on-dirty survives only as a rule of the migration tool.

## What a project keeps

Memory entries, `tc` state, project sections of `CLAUDE.md` and `AGENTS.md`, `owner: project` items, and the `copilot.project.json` marker. Nothing else.

## Guides

- [One-time machine install](../../01-getting-started/03-machine-install.md) (how-to)
- [Historical note on reconcile defects](../../30-operations/21-cc-reconcile-single-project-scope-and-plan-expiry.md)

## Plan

Tracked as PRD-16 in Task Copilot. Order: ADR and install guide, P0 Codex coordinator guard, release pointer engine, link generator, hook shim, single Codex marketplace, `cc project init` and `migrate`, first real release, independent QA, pilot on one project with a hard stop for owner review, fleet migration, retirement of copy-model code, closeout.

## Preserved pre-publication reviews

The four review and estimate documents in this directory record the earlier central-resolution candidate, before the final corrective release. Their blockers and predictions are historical evidence, not the current release status. The published machine runtime uses Claude 5.35.4, cc 2.19.4 and Control Tower 0.7.1; PRD-16 remains open for the separately recorded unfinished work. Live task state and QA receipts remain authoritative in tc.
