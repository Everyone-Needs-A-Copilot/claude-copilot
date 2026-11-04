# Parallel execution within protocol

Parallel work is the ordinary execution path of `/protocol` after the scoped outcome is approved. `/orchestrate` is deprecated and preserved only as a compatibility redirect. The owner does not manage worker launches, merges or housekeeping separately.

## The execution path

1. The coordinator loads the canonical organization policy with `cc skill get parallel-execution --scope machine --json`. Claude and Codex read the same source. If unavailable, protocol reports the fallback and uses the installed `tc cycle` guarded contract; missing capabilities are never presented as implemented behavior.
2. TA or the coordinator defines bounded deliverables, exclusive write ownership and concrete dependency events. Agreed interfaces unlock their consumers; a dependency on `contract` does not require waiting for provider implementation to merge. Research/design output ownership and synthesis use the same pattern without mandatory software checkout setup.
3. Register `tc cycle plan --file PLAN --json`. The validator rejects unsafe ownership/dependency plans before dispatch. `tc stream conflicts` remains a legacy check; cycle state is the current execution authority.
4. Query `tc cycle ready CYCLE --json`, claim the ready subset within runtime and resource permits, then actually invoke the native agent API. Refill capacity as work completes. Commands and claims do not themselves spawn native agents or prove execution.
5. One integrator merges local builder commits or one synthesis owner reconciles research/design evidence. Builders run focused checks and do not push; the integration owner performs required candidate-wide checks and outward steps only within their existing authority.
6. Independent QA partitions the coherent integrated state and covers cross-stream seams. Register the actual review execution root. Fix disjoint rejections concurrently, then refresh affected scopes, consumers and integration checks. Cycle receipts never replace the current task-bound QA gate.
7. Reconcile tasks and resource receipts, run project teardown, retire eligible resources under their applicable authority and report remaining owned holds.

## Internal coordinator commands

| Command | Effect |
|---|---|
| `tc cycle plan --file PLAN --json` | Validate and persist one approved scoped graph. |
| `tc cycle status CYCLE --json` | Read durable state and resource disposition. |
| `tc cycle ready CYCLE --json` | Read scopes eligible by dependency and capacity. |
| `tc cycle claim CYCLE STREAM --agent ID --cwd PATH --branch REF --json` | Record a claim after execution-root/branch preflight; branch is omitted when inapplicable. |
| `tc cycle record CYCLE STREAM --event EVENT --file RECEIPT --json` | Record actual contract, build, integration, acceptance, rejection, hold or release evidence. |
| `tc cycle cleanup-plan CYCLE --json` | Prepare exact retirement candidates and safety holds. |
| `tc cycle cleanup CYCLE --json` | Automatically remove only eligible recorded merged worktrees after fresh safety checks; preserve branches. |
| `tc cycle finish CYCLE --json` | Require accepted work, verified cleanup and no active PRD/body tasks. |
| `tc prd body-status PRD --json` | Enumerate the full task/stream body before closure. |
| `tc cycle smoke --roles sd,uxd,uids,uid,ta,me,qa,sec,doc,do,ind --json` | Run the provider-free local process lifecycle proof. |

Use `tc cycle --help` for supported schema and receipt details. `PLAN` has schemaVersion 1, id/task/runtime/root/capacity/resourceLimits/streams. Streams name id/task/role/kind/paths/readOnly/dependsOn/resource and optional worktree/branch. Dependencies name stream/event/reason. Avoid a second independently maintained schema.

## Isolation and throughput

One writer owns each checkout and each mutable output. Verify the worker's real cwd, repository root, branch/base and task database before writing. Worktrees isolate repository writes; they do not isolate ports, credentials, application databases, browser tenants or package caches. A project adapter declares setup, readiness, focused checks, integration, isolated state, teardown and retirement verification.

No arbitrary framework agent cap applies. Actual native slots, budgets and CPU/memory/disk/service capacity do. Queue unavailable resources visibly; use separate permits for heavy setup, builds, browsers and databases so useful light work can continue. A single worker is appropriate when the scope is genuinely coupled or dispatch overhead outweighs the gain.

Shared registries/types have one owner; separate contribution files or structured contributions avoid concurrent appends. “Additions only” is not a merge or semantic guarantee. Integration is serialized under one owner without imposing a global wait on unrelated workers.

## Cleanup and evidence

Each created resource has a receipt, owner, consumers, recovery and retirement conditions. A merged branch alone never proves its worktree disposable: check tracked, untracked and ignored work, unique commits, active consumers, current identity and successful teardown. Preserve uncertain resources and the coordinator's current checkout. Branch and other data deletion retain their existing exact approval requirements. The separately authorized merged-worktree cleanup exception is described in the canonical policy and shared work lifecycle.

## Cheap validation

The smoke starts and collects short local processes for each role label and verifies overlap and shutdown without provider calls. It checks the common lifecycle, not a model's specialist reasoning or the native runtime API. Verify native dispatch separately with a minimal fixed-output worker set under existing allocation/budget. Retain failures and distinguish actual native overlap from simulated roles. Re-run only affected checks when their source/runtime identity changes.

No speed improvement is guaranteed by loading instructions or passing the lifecycle smoke. Measure approved-plan-to-integrated-and-accepted elapsed time on comparable work with unchanged acceptance, while recording setup, queue, merge, QA rerun and resource overhead.

See [troubleshooting](02-orchestration-troubleshooting.md), [worktree isolation](05-worktree-isolation.md), and the [deprecated entrypoint](../../.claude/commands/orchestrate.md).
