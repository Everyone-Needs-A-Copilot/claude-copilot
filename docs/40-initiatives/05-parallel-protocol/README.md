# Protocol-native parallel execution: Claude source delivery

CSE PRD4/task12 owns this stream; its canonical task database remains `/Volumes/Dev/Sites/CSE/.copilot/tasks.db`. This source worktree is `feat/protocol-orchestration-claude`, based on `4c2a63e`. It is not an installed or published release.

## Result

Protocol now loads the one organization `parallel-execution` skill, then validates/claims ready streams, actually invokes native agents, refills capacity, converges through one integration/synthesis owner, verifies current independent evidence and accounts for resources. The specialist stage sequence expresses genuine input/decision dependencies, not a global barrier. TA no longer waits for five tasks to consider streams. Builders commit locally; one integrator owns candidate-wide checks and pushes. Research/design outputs can proceed independently without unnecessary software worktrees.

Both `/orchestrate` source and its installation template are deprecated compatibility redirects. Their old printed-launch and immediate branch/worktree deletion instructions were removed. The protocol, agent scopes, project template, README, quick reference and execution/troubleshooting guides point to the same workflow. Cleanup and continue no longer recommend force-removing dirty worktrees.

The owner’s later direction authorizes automatic cleanup of recorded merged worktrees only after fresh full-integration, clean tracked/untracked/ignored state, unchanged identity, no active consumers, stopped-worker, successful teardown and recovery checks. Branches remain preserved by default. All other destructive authority remains unchanged. Task-manager closeout enumerates the full PRD/body including parked tasks, completes verified work through QA, cancels abandoned work with history, and refuses a finished body with active tasks or required unresolved blockers.

## Runtime gate

The existing pending-QA hook used to deny every Agent call except QA. It now grants only a provisional routing path for a structured cycle envelope. After normal extension/safety/journey prompt-and-Knowledge authorization succeeds, the final rule calls `tc cycle verify-dispatch`, which must consume one current matching claim. Malformed, missing, forged, wrong-role, wrong-cwd or replayed claims remain denied. A builder cannot use this path to restart its own scope while it awaits independent QA; an unrelated claimed scope may continue. The existing task completion/QA gate is unchanged.

Prompt envelope lines are `CYCLE: <id> STREAM: <id>` and `CYCLE-CWD: /absolute/root`, placed after any required journey Knowledge envelope. A marker alone is not authority. The consuming tc service validates claim/task/execution-root identity; the normal worker preflight still must verify the actual process cwd before writing. Authorization is not proof of native execution.

## Checks and failure evidence

- `python scripts/check-parallel-protocol.py --policy <canonical organization skill>`:22 checks passed with no provider calls. Evidence retained at `.copilot/parallel-protocol-check/run-rgeg0jt1/results.json` and per-case outputs. These tests use local verifier shims to exercise the hook boundary; the engine suite and integration QA must separately prove real transactional claims/replays.
- Positive cases: an unrelated claimed engineer and designer dispatch while another task awaits QA. Negative cases: untracked worker, bare marker, forged claim, wrong role, wrong cwd, same pending task, malformed response and denied Knowledge authorization. The Knowledge-denied case proves the cycle permit is not consumed before normal authorization.
- Existing unchanged `scripts/check-work-lifecycle.py`:3 checks passed. During the later owner-required body-closeout addition, lifecycle text grew to1001 words and correctly failed its existing under1000-word contract; wording was shortened without removing its safety requirements, then both checks passed. Original failure remains in `.copilot/parallel-protocol-check/run-1xg_kqyn/results.json` and the task transcript.
- `bash -n .claude/hooks/pretool-check.sh` and `git diff --check`:passed.
- No existing foundation test assertion was edited. The organization stream separately fixes its demonstrated stale exact skill roster and registers the newly requested canonical skill; its migration evidence is in that organization initiative.

No native Claude model call, paid CLI worker, outward action, installation, release or worktree removal was performed by this stream. Final integrated source QA and local activation belong to the coordinator.

## Activation recommendations

Keep original release-pinned checkouts clean. After merging and committing all streams, use the existing `scripts/install-framework-snapshot.py` against the integration worktree with exact `--source-root`, `--source-commit` and `--source-tree`; it archives committed source into an immutable snapshot before publishing cc/tc and machine commands. Default installation also handles the committed Codex plugin mirror; `--claude-only` intentionally leaves Codex unchanged. Do not hand-edit installed snapshots. The coordinator owns versioning and Codex mirror adoption before this operation.

The new canonical skill paths were absent from both `~/.claude/skills/parallel-execution` and `~/.codex/skills/parallel-execution` during this review. Link both to the same organization skill directory after its committed source is chosen; never overwrite a pre-existing path. Verify realpath equality and `cc skill get parallel-execution --scope machine --json`. Retain any worktree still consumed by those links; after release, point them to the released canonical source before retirement.

The supported project reconciliation path is `cc reconcile plan`/`apply`/`verify` using an exact reviewed selection request and returned plan ID. Inspect actual local help when constructing that request; no invented rollout flags or fleet-wide writes are authorized by this stream. Source delivery, local activation and publication remain distinct facts.

unknowns: actual native harness overlap, integration of the tc engine contract, installed activation and benchmark improvement require coordinator evidence; no speed or model-quality guarantee is made here.
