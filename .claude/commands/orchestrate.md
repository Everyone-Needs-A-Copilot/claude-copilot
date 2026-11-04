---
name: orchestrate
description: Deprecated compatibility redirect; parallel execution is built into protocol
alwaysAllow: true
---

# Orchestrate — deprecated

Parallel execution is part of `/protocol`; no separate orchestration workflow is required. Retain this entrypoint for old prompts and references, without creating another task board or a second approval gate.

Follow `.claude/commands/protocol.md` with the existing scoped plan/cycle. Its conditional organization-policy discovery loads one canonical source when present; otherwise report the guarded `tc cycle` fallback. Legacy arguments select protocol actions below, never a separate scheduler.
| Legacy request | Protocol action |
|---|---|
| no argument / `generate` | Frame the requested outcome and establish its scoped plan; reuse existing approval. |
| `start` | Validate the cycle, claim useful ready scopes, and actually dispatch native agents within resource/runtime limits. |
| `status` | Read `tc cycle status CYCLE --json` and summarize running, queued, blocked, integrated, accepted and held work. |
| `merge` | Route completed contributions to the single integration owner, then current independent verification and resource disposition. |

## `generate` (legacy planning compatibility)

Map the requested outcome through protocol and @agent-ta's normal planning. Reuse the current PRD, scoped approval and task board; inspect existing streams/tasks before writing and reuse their IDs. Only create a PRD when none covers this outcome. Preserve the approved scope, dependencies and verification tiers; a legacy invocation never grants new spending or bypasses a real owner decision.

The architecture output associates each task with `metadata.streamId` (a label), `streamName`, explicit owned `files` and input `dependencies`. For example:

```json
{"title":"Build auth middleware","metadata":{"streamId":"Stream-A","streamName":"Foundation","files":["src/auth.ts"],"dependencies":[]}}
```

Persist actual stream/task rows for the existing PRD:

1. If needed, `tc prd create --title "..." --description "..." --json`; capture the PRD ID. Otherwise keep its existing numeric ID.
2. For each distinct label without an existing stream, run `tc stream create --name "<streamName>" --prd <prd-id> --json`. Map the label to the returned **numeric** `id`; never pass `Stream-A` to a numeric option. Reuse matching existing stream IDs.
3. Per new task: `tc task create --title "..." --prd <prd-id> --stream <numeric-id> --description "..." --metadata '<json>' --json`. Preserve the full validated metadata JSON, including files and dependencies; keep already recorded tasks rather than duplicating them.
4. Read back `tc task list --stream <numeric-id> --json` and run `tc stream conflicts --json`. Missing ownership or overlapping writers must be resolved before dispatch. Persist actual task dependency links and the cycle's typed readiness events; labels in metadata alone do not enforce readiness.

This mapping keeps stream-scoped task queries and ownership checks connected to the plan. Omitting either stream membership or metadata silently leaves those consumers without the rows/files they need. Store the architecture work product and validate the same approved plan with `tc cycle plan --file PLAN --json`; planning records authorize no native worker by themselves.

## `start` (protocol execution)

Use the validated ready set and actual native capacity. Claim each owned scope and verify its execution root before native dispatch; record observed starts and exits. Refill free slots as inputs become ready, without waiting for unrelated streams to merge. Builders commit locally; one integration owner converges outputs and current independent QA covers the assembled seams.

For an explicitly authorized budget-capped Claude worker, the real CLI shape is `tc worker <task-id> --max-budget-usd <remaining-authorized-cap>`. The flag limits that worker; it never raises the project's lifetime paid-call allowance. Provider-free cycle smoke needs neither a paid call nor a live benchmark.

Do not print launch instructions as if work had started. Do not wait for unrelated streams to merge before dispatching a contract-ready consumer. Builders do not push. A clean merge alone never proves a worktree disposable. Prepare candidates with `tc cycle cleanup-plan CYCLE --json`, then `tc cycle cleanup CYCLE --json` automatically removes only receipt-matched fully integrated clean inactive worktrees after identity, teardown, stopped-agent, consumer and recovery checks. Preserve branches and uncertain resources; branch/other deletion retains exact approval.
