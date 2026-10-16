# Work lifecycle

Apply to coding, research, design, operations and advice, including direct specialist invocation. Load once per task; revisit changed sources. The coordinator owns continuity and disposition; specialists record decisions; independent QA reviews evidence; the human owner authorizes destruction. Small work uses its existing record or response, not another task, board or retrospective.

## Start or resume

Resolve current task, source identity, owner authority, unfinished obligations and acceptance evidence. Preserve cumulative failures, attempts, spend and frozen scope across handoffs. Search narrowly for relevant lessons; follow original source pointers. Record applicability and the decision/check changed, or searched scope and no relevant lesson.

Before freezing substantial QA-required work, include observable `WORK-LIFECYCLE` acceptance: applicable learning or justified no-match, current checkpoint, artifact disposition, verified holds and required retirement results. Existing source-bound `tc` QA remains authoritative. Do not silently retrofit frozen contracts, reset budgets or replace original acceptance; report omissions and route scope changes to coordinator/owner. Missing required evidence fails its criterion.

## Proactive worktree housekeeping

At start/resume, including a new PRD or initiative, and at finish, merge, pause or handoff, the coordinator inspects relevant project worktrees without waiting for `/cleanup`. Use `git worktree list --porcelain` and the existing task's ownership/disposition record; inspect the current project's worktrees only. Recheck changed state rather than repeating full inventories.

For retirement candidates, verify integration into the intended branch, unique commits, tracked/untracked/ignored work, active processes/consumers, links and evidence dependencies. Merge alone never proves eligibility. Hold dirty or unique work until explicitly preserved and dispositioned; hold active dependencies. Each hold names owner, reason and next action. Do not remove another developer's work or the checkout running this session.

When eligible, prepare exact paths, verified recovery, dependency checks and rollback using the sequence below, then visibly ask: “Work is complete. These worktrees can be removed: [exact packet]. Recovery and dependency checks passed. Approve removal?” At start, say “Previous work has cleanup candidates” instead of claiming new work is complete. Do not bury the request in a work product or wait for the user to remember cleanup. Reuse unchanged prior approval; recheck drift before execution. Otherwise keep approval pending in the existing record without blocking unrelated new work. If none qualify, record no candidates or owned holds. After approval, execute and verify; preparation is not removal.

## During work

Maintain the existing task/work product and one narrative. Record consequential decisions, rejected approaches, measured failures/corrections and original evidence. Give temporary artifacts, including worktrees, a purpose, owner, consumers and retirement condition when created. Preserve software, LLM stubs, fixtures, unique developer work, original QA, approvals and cumulative execution history; summaries never replace them.

A reusable lesson states **applicability → failure → changed decision/check → evidence → boundary/counterexample**. Keep project rules local; promote supported lessons, distinguishing owner instructions from inference. Memory is a selective pointer, not duplicate prose or a routine session transcript.

## Pause or handoff

Preserve tested identity, approvals, failed criteria, charged usage, pending work, artifact locations and next owner/action in the existing record, retaining authoritative journey/run capsules. Distinguish awaiting results, idle, stale, blocked and complete. A live process is not progress; pausing is not acceptance. The incoming coordinator reconciles handoff against live state, including pending cleanup approval.

## Finish and clean up

Consolidate completed work into its maintained README/equivalent: outcome, decisions, failures/corrections, bounded lessons and unfinished obligations. Supporting documents require current need; no empty scaffolding. Retain legitimate software, deliverables and evidence separately.

Use this sequence for proactive retirement or explicit `/cleanup`:

1. Measure scoped files/directories/bytes and reading path; verify branch, dirty state, unique commits, task authority, consumers, links and evidence dependencies. Age proves nothing.
2. Distill knowledge into the existing narrative, reconcile contradictions and review preservation fidelity.
3. Classify required active assets, necessary inactive originals, redundant narratives, reproducible artifacts and unresolved holds. Archive only necessary inactive originals when useful, in one private collection with concise catalog, membership/checksums and tested restoration. Keep active fixtures usable. An in-project archive is not an independent backup.
4. Prepare exact paths, verified Git/archive recovery or demonstrated regeneration, dependency checks and rollback. Obtain exact human approval before deletion, destructive overwrites/moves or task/memory archival. Routine authorized editing/consolidation needs no new approval. Broad intent and summary quality do not grant destructive approval. Preserve database execution history; uncertainty is a hold.
5. Execute approved paths only after drift/consumer rechecks. Verify retained dependencies and recovery; remove approved loose duplicates after archive verification. Report actual gross/net file/directory/byte reduction, including archives and process evidence. Inventory, backup, compression or summary alone is not cleanup.

Report delivery acceptance separately from cleanup. An owned hold satisfies disposition only when acceptance permits; it never satisfies required removal. Retaining it needs no fresh approval. Required cleanup undone means optimization remains incomplete.

## Later use and measurement

Track **recorded → applied → outcome measured → independently accepted** in the existing record. Link later decisions/checks and observed results to lessons; retain negative outcomes/counterexamples, narrowing or retiring misleading guidance. Retrieval alone proves no product benefit.

Compare fresh-reader accuracy and files/words consulted, changed decisions, recurrence/rework under unchanged quality criteria, independent QA/owner outcomes, net growth and recoverability. Record baseline, scope, method and limitations; no new dashboard or guaranteed benefit.

## Compact record template

Use the existing task/WP; explain inapplicable fields:

- Task/body, owner, checkpoint, source identity, authority:
- Lesson/source/boundary or searched scope/no-match:
- Changed decision/check, result/evidence, learning state:
- Outcome, failures/corrections, obligations, next owner/action:
- Artifacts/worktrees: purpose/consumers, disposition, recovery, exact approval/pending request:
- Gross/net counts/bytes, reading path, verification, limitations:
- Product acceptance / cleanup status (separate):

This instruction/evidence-review contract uses existing task gates; it is not a daemon, automatic deletion hook, lesson validator or universal enforcer. Checkpoints need no provider calls.
