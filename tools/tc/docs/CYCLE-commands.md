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
│ validate         Validate ownership and dependencies without a database or   │
│                  dispatch.                                                   │
│ plan             Persist an approved cycle; identical retries are            │
│                  idempotent.                                                 │
│ status           Read streams, capacity queues, stale evidence and           │
│                  disposition.                                                │
│ ready            Return ready scopes and concrete wait reasons.              │
│ claim            Claim one ready scope after exact execution-root and        │
│                  capacity checks.                                            │
│ prepare          Create the planned new writer worktree/branch, recording    │
│                  its identity.                                               │
│ verify-dispatch  Consume one running claim's native dispatch permit;         │
│                  duplicate launches refuse.                                  │
│ record           Record contract/build/integration/QA/stopped/teardown       │
│                  outcomes.                                                   │
│ cleanup-plan     Inspect exact eligible cycle worktrees and preserved holds. │
│ cleanup          Retire eligible merged cycle worktrees; preserve branches   │
│                  and every hold.                                             │
│ smoke            Handshake overlapping local role processes and verify       │
│                  complete shutdown.                                          │
│ finish           Close the PRD only when all body tasks, workers and cycle   │
│                  resources resolve.                                          │
│ adapter          Discover one project's setup/check/teardown and declared    │
│                  isolation without execution.                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle validate`

```text

 Usage: cycle validate [OPTIONS]

 Validate ownership and dependencies without a database or dispatch.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --file        <path>  Schema-1 plan JSON. [required]                      │
│    --json                                                                    │
│    --help                Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle plan`

```text

 Usage: cycle plan [OPTIONS]

 Persist an approved cycle; identical retries are idempotent.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --file        <path>  Approved schema-1 plan JSON. [required]             │
│    --json                                                                    │
│    --help                Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle status`

```text

 Usage: cycle status [OPTIONS] {cycle}

 Read streams, capacity queues, stale evidence and disposition.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      <str>  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle ready`

```text

 Usage: cycle ready [OPTIONS] {cycle}

 Return ready scopes and concrete wait reasons.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      <str>  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle claim`

```text

 Usage: cycle claim [OPTIONS] {cycle} {stream}

 Claim one ready scope after exact execution-root and capacity checks.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       <str>  [required]                                           │
│ *    stream      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --agent                <str>   [required]                                 │
│ *  --cwd                  <path>  [required]                                 │
│    --branch               <str>                                              │
│    --lease-seconds        <int>   [default: 900]                             │
│    --json                                                                    │
│    --help                         Show this message and exit.                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle prepare`

```text

 Usage: cycle prepare [OPTIONS] {cycle} {stream}

 Create the planned new writer worktree/branch, recording its identity.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       <str>  [required]                                           │
│ *    stream      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle verify-dispatch`

```text

 Usage: cycle verify-dispatch [OPTIONS] {cycle} {stream}

 Consume one running claim's native dispatch permit; duplicate launches refuse.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       <str>  [required]                                           │
│ *    stream      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --role                <str>   [required]                                  │
│ *  --cwd                 <path>  [required]                                  │
│    --blocked-task        <int>   Pending-QA builder task that cannot consume │
│                                  an unrelated-work permit.                   │
│    --json                                                                    │
│    --help                        Show this message and exit.                 │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle record`

```text

 Usage: cycle record [OPTIONS] {cycle} {stream}

 Record contract/build/integration/QA/stopped/teardown outcomes.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle       <str>  [required]                                           │
│ *    stream      <str>  [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --event        <str>   [required]                                         │
│ *  --file         <path>  Evidence receipt JSON, including leaseToken for    │
│                           worker events.                                     │
│                           [required]                                         │
│    --json                                                                    │
│    --help                 Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle cleanup-plan`

```text

 Usage: cycle cleanup-plan [OPTIONS] {cycle}

 Inspect exact eligible cycle worktrees and preserved holds.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      <str>  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle cleanup`

```text

 Usage: cycle cleanup [OPTIONS] {cycle}

 Retire eligible merged cycle worktrees; preserve branches and every hold.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      <str>  [required]                                            │
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
│ --roles        <str>   Comma-separated role identifiers, no provider calls.  │
│                        [default: ta,me,qa,sec,doc,do,sd,uxd,uids,uid,ind]    │
│ --out          <path>  New JSON evidence path; existing files are preserved. │
│ --json                                                                       │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle finish`

```text

 Usage: cycle finish [OPTIONS] {cycle}

 Close the PRD only when all body tasks, workers and cycle resources resolve.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    cycle      <str>  [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `tc cycle adapter`

```text

 Usage: cycle adapter [OPTIONS] {project}

 Discover one project's setup/check/teardown and declared isolation without
 execution.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    project      <path>  [required]                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json                                                                       │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```
