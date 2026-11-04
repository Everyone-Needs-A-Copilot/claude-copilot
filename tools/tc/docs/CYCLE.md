# Protocol cycle CLI

## Purpose

`tc cycle` is the internal coordination surface used by protocol in Claude Copilot and Codex Copilot. It records useful ready work, validated write ownership, native worker claims, consumed interfaces, integration, independent acceptance and resource disposition. The coordinator uses the runtime's native agent API; this command does not launch model providers, release software or replace the existing task QA gate. `/orchestrate` is deprecated; normal work enters protocol.

## Setup and identity

Install Task Copilot using `bash tools/tc/install.sh` from the framework checkout. This group requires tc 2.12.0 or its reviewed source. `tc version` identifies the selected executable; a development run uses `PYTHONPATH=tools/tc/src <selected-python> -m tc.main`. Run database-backed operations from the owning project or use the `tc.api` facade with explicit `db_path`. Normal linked worktrees share the main checkout's task database; `TC_WORKTREE_DB=local` explicitly selects a local snapshot. No credentials or tenant account are used by cycle commands. Native Claude/Codex authentication and runtime slot limits remain separate.

## Command discovery

Use `tc --help`, `tc cycle --help` and `tc cycle COMMAND --help` offline. The complete registered grammar is in [CYCLE-commands.md](CYCLE-commands.md); there are no cycle aliases or optional provider integrations. Commands are `validate`, `plan`, `status`, `ready`, `claim`, `prepare`, `verify-dispatch`, `record`, `cleanup-plan`, `cleanup`, `smoke`, `finish` and `adapter`. The companion `tc prd body-status PRD --json` inspects body-level closure eligibility. Existing `tc task`, `tc prd`, `tc execution`, `tc wp` and other groups are outside this group's generated reference and remain in the [package guide](../README.md) and their own help.

## Intent and examples

The identifiers `review`, `evidence`, `worker-1`, `/absolute/writer` and JSON filenames below are placeholders. The plan must use actual task IDs in the selected database and actual project paths.

| Intent | Command | Prerequisites and effects | Observable result |
|---|---|---|---|
| Read the project setup/isolation contract | `tc cycle adapter /absolute/project --json` | Filesystem-only discovery; no command execution | Explicit descriptor or honest file-only fallback |
| Check a plan without creating anything | `tc cycle validate --file plan.json --json` | Schema-1 JSON; no database needed | Normalized plan, or validation error |
| Register the approved body | `tc cycle plan --file plan.json --json` | Existing tc tasks; coordinator already has owner approval | Persisted cycle; identical retry preserves state |
| Discover work that can start | `tc cycle ready review --json` | Registered cycle | Ready scopes plus input/resource/worker wait reasons |
| Create a planned code worktree | `tc cycle prepare review evidence --json` | New path and branch; validated ownership | New worktree and private creation receipt |
| Claim native work | `tc cycle claim review evidence --agent worker-1 --cwd /absolute/writer --branch cycle/evidence --json` | Scope ready, correct checkout and branch, available permits | Exclusive lease token and execution identity |
| Authorize one native launch | `tc cycle verify-dispatch review evidence --role me --cwd /absolute/writer --json` | Current unexpired claim; existing prompt/Knowledge checks already passed | One consumed dispatch permit; duplicate launch refuses |
| Record a worker outcome | `tc cycle record review evidence --event built --file built.json --json` | Receipt artifact and current leaseToken | Focused output identity and retained event history |
| Account for runtime shutdown | `tc cycle record review evidence --event stopped --file stopped.json --json` | Coordinator observed native exit; receipt has leaseToken, stopped=true and artifact | Worker capacity becomes available |
| Inspect safe retirement | `tc cycle cleanup-plan review --json` | Integration, current acceptance and teardown receipts | Exact eligible worktrees and named holds |
| Retire eligible merged worktrees | `tc cycle cleanup review --json` | Owner's narrow automatic cleanup policy; repeated identity/consumer checks pass | Removed worktrees with receipts; branches preserved |
| Check quick startup and shutdown | `tc cycle smoke --roles sd,uxd,me,qa --out smoke-new.json --json` | Fresh evidence filename; no database or provider needed | Real overlapping role processes, complete exit, zero model tokens/calls |
| Close the completed body | `tc cycle finish review --json` | Fresh acceptance, cleanup complete, all PRD tasks terminal and workers stopped | PRD and eligible streams completed; task history retained |

A schema-1 plan contains `id`, `task`, `runtime` (`claude`, `codex` or `local`), absolute `root`, available worker `capacity` excluding the coordinator, `resourceLimits`, and `streams`. Each stream declares `id`, `task`, `role`, `kind` (`code`, `research`, `design`, `qa`, `operations`), `paths`, `readOnly`, `resource` and `dependsOn`. Writers have an absolute `worktree`; code writers also declare `branch`. Paths are literal relative paths or terminal `/**` directory claims; arbitrary globs, traversal and symlink aliases are refused. Read-only scopes explicitly use `paths: []`. Dependencies are `{stream,event,reason}`; event is `contract`, `built`, `integrated` or `accepted`, and reason names a real unavailable input.

Worker receipts use their current `leaseToken`. `contract` and `built` require an existing `artifact`. `integrated` requires the actual integration HEAD for code and a source match. `accepted` requires an independent `agent`, `verdict: approved`, the current `sourceFingerprint` from the integrated receipt, and `artifact`; QA-required tasks must also pass their existing tc QA gate. `stopped` requires observed shutdown (`stopped: true`) plus an artifact. `teardown` requires `passed: true`, a named `command` and an artifact. Use `tc cycle adapter PROJECT --json` once to read `.copilot/worktree-adapter.json`: schemaVersion 1, `commands` mapping setup/readiness/focused/integration/teardown to argv arrays, and `isolation` with explicit `stateful` boolean and nonempty `details`. Discovery never executes commands. Without a descriptor, existing package scripts named worktree:setup/worktree:teardown are reported as npm argv defaults; this does not prove database isolation. Otherwise the fallback declares filesystem-only isolation. A stream with `stateful: true` requires an explicit isolation adapter and `setupEvidence` JSON proving passed/isolated setup, exact cwd, and existing resource receipt paths before claim. These are project/setup receipts, not authority to provision application databases. Project setup, focused checks, isolated state and teardown remain declared project/coordinator responsibilities; `prepare` creates the checkout, not an inferred package installation or database. Keep authoritative evidence outside temporary worktrees.

## Inputs and outputs

All commands expose `--json`; plan/receipt inputs are JSON files, not stdin. The exact options, types and defaults are parser-derived in the reference. JSON success is one object on stdout; errors under `--json` use the existing tc error object and exit 4. Human mode prints JSON-shaped status or a diagnostic. `validate` and `smoke` do not require a task database; `smoke --out` refuses an existing file. There are no paid calls. Automation should inspect fields such as `ready`, `queued`, `stale`, `openBodyTasks`, `deliveryAccepted`, `cleanupComplete`, `removed` and `held`; a zero exit on cleanup can still contain preserved holds.

## Effects and verification

`validate` and `adapter` read files only. Status/readiness/cleanup-plan inspect local state and may initialize the cycle bookkeeping tables in an existing tc database. Plan/claim/record/verify-dispatch write durable SQLite records; verify-dispatch consumes one single-use permit. Prepare creates a new Git branch and worktree; it refuses adoption of existing paths. Cleanup removes only recorded eligible merged worktrees after fresh clean-state, identity, evidence, shutdown, process-consumer and teardown checks. It never deletes branch history, unknown resources, test databases or the coordinator/integration checkout. A missing process inspector causes a hold. Finish closes only an already-resolved body; it never mass-completes unfinished tasks or fabricates QA.

Smoke launches actual short local subprocesses for selected role labels, waits for all readiness handshakes, then releases and joins them. It reports observed overlap and residual process count. Its JSON explicitly says `nativeAgentDispatch: false`: it proves the cheap process lifecycle, not authenticated native-model dispatch or role reasoning quality. Minimal native dispatch evidence is a separate runtime check. Git/SQLite fixture tests cover actual integration and safe worktree retirement.

## Errors and recovery

Ownership overlap, missing paths, unknown dependencies, cycles, wrong cwd/branch and unsupported glob syntax fail before dispatch. Correct the approved plan and use a new cycle ID if its meaning changed; reusing an ID with a different plan is refused. A resource queue is a capacity wait, not an error. Expired claims remain occupied until the coordinator proves the original worker stopped; do not steal a lease. A failed native launch after permit consumption needs explicit observed-stop/release and a fresh claim before retrying.

A changed consumed contract refuses `built`; stop/release the worker and rebuild against the new input. Changed source or upstream receipts invalidate dependent acceptance. Retain rejection evidence and rerun affected independent checks. Dirty, unique, unmerged, active, drifted or evidence-bearing worktrees are held. Preserve/rebind required evidence and task execution roots outside a temporary checkout before retrying cleanup. A completed/cancelled task with a live claim still blocks PRD closure. Cancel abandoned work only through the existing owner-authorized closeout process with a handoff; cancellation does not mean a requirement passed.

## Maintenance

Canonical implementations are `tools/tc/src/tc/services/cycles.py`, `commands/cycle.py`, and the existing shared PRD/task/QA services. Both harnesses call this implementation. Regenerate the command reference using the selected interpreter and engine source:

```bash
PYTHONPATH=tools/tc/src python scripts/export-cli-reference.py tc.commands.cycle:cycle_app --name 'tc cycle' --require-purpose > tools/tc/docs/CYCLE-commands.md
```

Here `scripts/export-cli-reference.py` is the canonical CLI-standard helper in the selected cli-copilot foundation checkout; use its actual absolute path when it is not in the current repository. Check this guide with that checkout's `scripts/check-cli-guide.py tools/tc/docs/CYCLE.md`, compare a fresh parser export to the committed reference, and run the focused `tools/tc/tests/test_protocol_cycles.py` suite. Offline help/reference generation never invokes business callbacks. The older tc commands are explicitly excluded from this new group's reference, not silently treated as documented by it.
