---
name: protocol-router
description: Use when a request needs specialist routing before implementation, including bugs, feature work, architecture changes, UX work, security-sensitive changes, or tc-backed delivery planning.
---

# Protocol Router

Use this skill to classify the request and choose the right specialist flow before coding.

## Classification

| Request type | Start with |
|--------------|------------|
| bug, regression, test failure | `qa` |
| backend feature, refactor, architecture, performance | `ta` |
| user-facing feature, workflow, product experience | `sd` or `uxd` |
| physical product, connected product, hardware/software touchpoint | `ind` |
| visual polish, design system, component styling | `uids` or `uid` |
| auth, permissions, secrets, trust boundaries | `sec` in addition to primary flow |
| docs, onboarding, references | `doc` |
| deploy, CI, env, infrastructure | `do` |

## Codex rule

If the user did not explicitly ask for subagents, apply the specialist lens in the main session.

If the user explicitly asked for delegation or parallel work, you may spawn subagents after deciding:

1. what the immediate local step is
2. which work can safely run in parallel

## Standard flow

1. classify the request
2. identify the specialist sequence
3. check whether a `tc` PRD or task exists
4. create missing task records if the work is substantial
5. execute the specialist flow
6. verify with `qa` before closing implementation work

## Routing patterns

Read `../protocol/references/generated-workflows.md` for the catalog-derived
sequences. This router classifies requests; it does not maintain another copy
of the workflow graph.

## References

Read `references/routing-matrix.md` when you need the full mapping.
