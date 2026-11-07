# tc cycle command reference

Generated from the registered parser. Command callbacks were not executed. For intent, effects, configuration and recovery, read the companion CLI guide.

## `tc cycle`

```text

 Usage: cycle [OPTIONS] COMMAND [ARGS]...

 Protocol-owned ready-work coordination; no model calls. Guide:
 tools/tc/docs/CYCLE.md.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.      │
│ --show-completion             Show completion for the current shell, to copy │
│                               it or customize the installation.              │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ validate          Validate ownership and dependencies without a database or  │
│                   dispatch.                                                  │
│ plan              Persist an approved cycle; identical retries are           │
│                   idempotent.                                                │
│ status            Read streams, capacity queues, stale evidence and          │
│                   disposition.                                               │
│ ready             Return ready scopes and concrete wait reasons.             │
│ claim             Claim one ready scope after exact execution-root and       │
│                   capacity checks.                                           │
│ prepare           Create the planned new writer worktree/branch, recording   │
│                   its identity.                                              │
│ verify-dispatch   Consume one running claim's native dispatch permit;        │
│                   duplicate launches refuse.                                 │
│ record            Record contract/build/integration/QA/stopped/teardown      │
│                   outcomes.                                                  │
│ cleanup-plan      Inspect exact eligible cycle worktrees and preserved       │
│                   holds.                                                     │
│ cleanup           Retire eligible merged cycle worktrees; preserve branches  │
│                   and every hold.                                            │
│ smoke             Handshake overlapping local role processes and verify      │
│                   complete shutdown.                                         │
│ finish            Close the PRD only when all body tasks, workers and cycle  │
│                   resources resolve.                                         │
│ adapter           Discover one project's setup/check/teardown and declared   │
│                   isolation without execution.                               │
│ capability        Report supported control schemas, not native execution     │
│                   capabilities.                                              │
│ advance           Commit one source-bound stage transition; never dispatch   │
│                   workers.                                                   │
│ check             Refuse incomplete or stale stage acceptance.               │
│ audit             Report durable queue/native observations and explicit      │
│                   unknown intervals.                                         │
│ export            Export a new nonsecret release packet after phase          │
│                   acceptance.                                                │
│ verify-packet     Verify approved packet digest/source binding offline; no   │
│                   local task DB.                                             │
│ dispatch-context  Find active stage enrollment for omitted-envelope dispatch │
│                   protection.                                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle validate`

```text

 Usage: cycle validate [OPTIONS]

 Validate ownership and dependencies without a database or dispatch.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --file        PATH  Schema-1 plan JSON. [required]                        │
│    --json                                                                    │
│    --help              Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle plan`

```text

 Usage: cycle plan [OPTIONS]

 Persist an approved cycle; identical retries are idempotent.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --file        PATH  Approved schema-1 plan JSON. [required]               │
│    --json                                                                    │
│    --help              Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle status`

```text

 Usage: cycle status [OPTIONS] CYCLE

 Read streams, capacity queues, stale evidence and disposition.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle ready`

```text

 Usage: cycle ready [OPTIONS] CYCLE

 Return ready scopes and concrete wait reasons.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle claim`

```text

 Usage: cycle claim [OPTIONS] CYCLE STREAM

 Claim one ready scope after exact execution-root and capacity checks.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       TEXT  [required]                                            │
│ *    stream      TEXT  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --agent                TEXT     [required]                                │
│ *  --cwd                  PATH     [required]                                │
│    --branch               TEXT                                               │
│    --lease-seconds        INTEGER  [default: 900]                            │
│    --json                                                                    │
│    --help                          Show this message and exit.               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle prepare`

```text

 Usage: cycle prepare [OPTIONS] CYCLE STREAM

 Create the planned new writer worktree/branch, recording its identity.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       TEXT  [required]                                            │
│ *    stream      TEXT  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle verify-dispatch`

```text

 Usage: cycle verify-dispatch [OPTIONS] CYCLE STREAM

 Consume one running claim's native dispatch permit; duplicate launches refuse.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       TEXT  [required]                                            │
│ *    stream      TEXT  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --role                TEXT     [required]                                 │
│ *  --cwd                 PATH     [required]                                 │
│    --blocked-task        INTEGER  Pending-QA builder task that cannot        │
│                                   consume an unrelated-work permit.          │
│    --json                                                                    │
│    --help                         Show this message and exit.                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle record`

```text

 Usage: cycle record [OPTIONS] CYCLE STREAM

 Record contract/build/integration/QA/stopped/teardown outcomes.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       TEXT  [required]                                            │
│ *    stream      TEXT  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --event        TEXT  [required]                                           │
│ *  --file         PATH  Evidence receipt JSON, including leaseToken for      │
│                         worker events.                                       │
│                         [required]                                           │
│    --json                                                                    │
│    --help               Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle cleanup-plan`

```text

 Usage: cycle cleanup-plan [OPTIONS] CYCLE

 Inspect exact eligible cycle worktrees and preserved holds.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle cleanup`

```text

 Usage: cycle cleanup [OPTIONS] CYCLE

 Retire eligible merged cycle worktrees; preserve branches and every hold.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle smoke`

```text

 Usage: cycle smoke [OPTIONS]

 Handshake overlapping local role processes and verify complete shutdown.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --roles        TEXT  Comma-separated role identifiers, no provider calls.    │
│                      [default: ta,me,qa,sec,doc,do,sd,uxd,uids,uid,ind]      │
│ --out          PATH  New JSON evidence path; existing files are preserved.   │
│ --json                                                                       │
│ --help               Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle finish`

```text

 Usage: cycle finish [OPTIONS] CYCLE

 Close the PRD only when all body tasks, workers and cycle resources resolve.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle adapter`

```text

 Usage: cycle adapter [OPTIONS] PROJECT

 Discover one project's setup/check/teardown and declared isolation without
 execution.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    project      PATH  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle capability`

```text

 Usage: cycle capability [OPTIONS]

 Report supported control schemas, not native execution capabilities.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle advance`

```text

 Usage: cycle advance [OPTIONS] CYCLE

 Commit one source-bound stage transition; never dispatch workers.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --event                  TEXT     [required]                              │
│ *  --file                   PATH     [required]                              │
│    --expect-revision        INTEGER                                          │
│    --json                                                                    │
│    --help                            Show this message and exit.             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle check`

```text

 Usage: cycle check [OPTIONS] CYCLE

 Refuse incomplete or stale stage acceptance.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --phase            TEXT  [default: complete]                                 │
│ --candidate        TEXT                                                      │
│ --json                                                                       │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle audit`

```text

 Usage: cycle audit [OPTIONS] CYCLE

 Report durable queue/native observations and explicit unknown intervals.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle export`

```text

 Usage: cycle export [OPTIONS] CYCLE

 Export a new nonsecret release packet after phase acceptance.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      TEXT  [required]                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --phase        TEXT  [required]                                           │
│ *  --out          PATH  [required]                                           │
│    --json                                                                    │
│    --help               Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle verify-packet`

```text

 Usage: cycle verify-packet [OPTIONS]

 Verify approved packet digest/source binding offline; no local task DB.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --file                           PATH  [required]                         │
│ *  --sha256                         TEXT  [required]                         │
│ *  --root                           PATH  [required]                         │
│ *  --phase                          TEXT  [required]                         │
│    --source-commit                  TEXT                                     │
│    --candidate-inputs-sha256        TEXT                                     │
│    --json                                                                    │
│    --help                                 Show this message and exit.        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle dispatch-context`

```text

 Usage: cycle dispatch-context [OPTIONS]

 Find active stage enrollment for omitted-envelope dispatch protection.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --cwd         PATH  [required]                                            │
│    --json                                                                    │
│    --help              Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```
