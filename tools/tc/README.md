# tc — Task Copilot CLI

Agent-agnostic task management CLI for AI development workflows. Stores PRDs, tasks, dependencies, and work products in a local SQLite database (`.copilot/tasks.db`).

---

## Install

```bash
cd tools/tc && pip install -e .
```

The `tc` binary is placed on your `PATH` (standard pip scripts install).

---

## Quick Start

```bash
# Initialise a database in the current directory
tc init

# Create a PRD
tc prd create --title "Checkout v2" --description "Redesign checkout flow"

# Create tasks linked to the PRD
tc task create --title "Schema migration" --prd 1 --priority 0 --agent me
tc task create --title "API endpoints"    --prd 1 --priority 1 --agent me

# Wire a dependency (task 2 depends on task 1)
tc task deps add 2 --depends-on 1

# Store a work product for a task
tc wp store --task 1 --type implementation --title "Migration notes" --content "..."

# Progress overview
tc progress

# Hand off a task between agents
tc handoff --from me --to qa --task 1 --context "Ready for review"
```

---

## Code-Execution Path (Programmatic API — PREFER for >=3 ops)

For agents performing 3+ related operations, import `tc.api` in a **single** `python3` Bash block instead of multiple CLI calls. Each CLI call echoes a full JSON payload back into context; a python3 block returns only what you `print()`.

**Import surface:** `from tc.api import create_prd, create_task, add_dependency, store_wp, transaction`

### Worked example — "PRD + 18 tasks + wire dependencies" (one Bash call)

**TODAY (CLI, one call each):** 1 prd create + 18 task create + 17 deps add = 36 round-trips, ~36 JSON payloads re-entering context. ~36 calls × 250-600 tokens ≈ 9,000–20,000 tokens of intermediate output.

**WITH code-execution (one Bash call):**

```bash
python3 - << 'PY'
from tc.api import create_prd, create_task, add_dependency, transaction
from tc.db.connection import get_db, find_db_path

db_path = find_db_path()
conn = get_db(db_path)
try:
    with transaction(conn):
        prd = create_prd(title="Checkout v2", description="Redesign checkout", conn=conn)
        specs = [
            {"title": "Schema migration",  "priority": 0, "agent": "me"},
            {"title": "API endpoints",     "priority": 1, "agent": "me"},
            {"title": "Frontend cart",     "priority": 1, "agent": "me"},
            # ... up to 18 tasks
        ]
        ids = [create_task(prd=prd["id"], **s, conn=conn)["id"] for s in specs]
        for prev, cur in zip(ids, ids[1:]):
            add_dependency(task_id=cur, depends_on=prev, conn=conn)
finally:
    conn.close()
print(f"PRD-{prd['id']}: {len(ids)} tasks {ids[0]}..{ids[-1]}, {len(ids)-1} deps wired")
PY
```

Returns to context: **one line, ~25 tokens** — a ~99% reduction on intermediate output.

### Rules

- PREFER code-execution for >=3 related tc ops (create PRD + tasks, batch WP stores, wire deps).
- KEEP CLI for single one-shot ops: `tc task get 40 --json`, one `tc wp store`, one `tc task update --status completed`.
- CRITICAL: tc and cc are in separate environments. Keep each block to ONE tool (tc-only OR cc-only).
- Batched ops inside `transaction()` are all-or-nothing — safer than today's partial-progress across N CLI calls.
- Typed exceptions: `TaskNotFound`, `PrdNotFound`, `ValidationError`, `ConflictError` — wrap in try/except and print a compact error line.

### Typed exceptions

```python
from tc.api import create_task, TaskNotFound, ValidationError
try:
    task = create_task(title="My task", priority=5)  # invalid priority
except ValidationError as e:
    print(f"ERROR: {e}")
```

### `transaction()` — batch N ops in one connection

```python
from tc.api import create_task, add_dependency, transaction
from tc.db.connection import get_db, find_db_path

conn = get_db(find_db_path())
try:
    with transaction(conn):   # commits on exit, rolls back on exception
        t1 = create_task(title="First",  conn=conn)
        t2 = create_task(title="Second", conn=conn)
        add_dependency(task_id=t2["id"], depends_on=t1["id"], conn=conn)
finally:
    conn.close()
```

---

## CLI Reference

### `tc task`

```bash
tc task create  --title "..." --prd <id> --agent <slug> --priority 0-3 [--max-budget-usd <float>]
tc task get     <id> [--json]
tc task list    [--status pending] [--agent me] [--prd <id>] [--include-parked | --parked]
tc task update  <id> --status completed
tc task claim   <id> --agent <slug> [--max-budget-usd <float>]
tc task next    [--agent me]
tc task deps add    <id> --depends-on <id>
tc task deps remove <id> --depends-on <id>

# Stale triage
tc task stale   [--days 30] [--json]
tc task park    <id>... --reason "..."   |  tc task park --stale [--days N] --reason "..."
tc task unpark  <id>...
tc task cancel  <id>... --reason "..."   |  tc task cancel --stale [--days N] --reason "..."
```

Every status change is written to the activity log (`tc log`), with JSON details naming the previous status and, inside Claude Code or Codex, the session that made it (`CLAUDE_CODE_SESSION_ID` / `CODEX_THREAD_ID`).

**Stale triage.** `tc task stale` lists open tasks (pending, in progress, blocked) whose latest activity, the later of the row's update and its newest log entry, is at least `--days` old. For each, decide: keep working, **park** it, or **cancel** it with a reason. A parked task is set aside, not finished: it keeps its status (an in-progress task returns to pending and loses its claim), records `metadata.parked = {"at", "reason"}`, and is skipped by `tc task next` and hidden from `tc task list` unless `--include-parked` or `--parked` is given. `tc task unpark` brings it back. Cancel records `metadata.cancelReason`. Park and cancel are all-or-nothing across the IDs given, and nothing is ever deleted.

### `tc archive` / `tc history`

```bash
tc archive [--days 14] [--dry-run] [--json]
tc history list   [--limit 50]
tc history search "<words>"        # titles and work-product text
tc history get    <id>             # task, activity log, work products
tc history restore <id>...
```

Finished tasks (completed or cancelled) whose latest activity is at least `--days` old move, with their activity log, work products and dependency rows, from `.copilot/tasks.db` into `.copilot/tasks.db-history`, a file with the same schema. A finished task stays while any task left in `tasks.db` still points at it as parent or dependency. Nothing is deleted, task IDs are never reused, and `tc history restore` moves tasks back. The history file is committed with the project, like `tasks.db`.

Archiving also runs automatically, at most once a day, after a writing `tc task` command (`update`, `park`, `unpark`, `cancel`). Turn it off with `TC_AUTO_ARCHIVE=0`; change the age with `TC_ARCHIVE_DAYS`. `tc progress` and `tc task list` cover only `tasks.db`.

### Task state is committed with the project

```bash
tc db track [--check]
```

A project commits `.copilot/tasks.db`, `.copilot/tasks.db-history` and `.copilot/wp/`, so its tasks, history and work products travel with the repository between machines. SQLite's `-wal`, `-shm` and `-journal` files and `.copilot/tasks.db-archive-stamp` stay ignored. `tc init` writes this rule into the project's `.gitignore` as one managed block; `tc db track` applies it to an existing project, and `--check` exits 1 if a project is not at the standard. A bare `.copilot/` rule becomes `.copilot/*`, which ignores the same contents but lets the task files back in. **Public repositories opt out:** work products hold internal notes and machine paths, so a `.gitignore` containing the line `# tc: task state stays local` is never changed and its task state stays out of Git.

Each `tc` command closes its connection, which folds the WAL into `tasks.db`, so the committed file is current. SQLite files cannot be merged: work on one machine at a time and pull before you start. Git-mergeable task files are the planned successor (codex-copilot ADR-001).

**Git worktrees share one task list.** Inside a linked worktree (a sibling checkout from `git worktree add`, or an agent worktree under `.claude/worktrees/`), tc reads and writes the main checkout's `.copilot/tasks.db`. The worktree's own copy is only the snapshot its branch checked out; writing to it would fork the project's tasks. tc finds the main checkout from the worktree's `.git` file without running git. Set `TC_WORKTREE_DB=local` to use the worktree's own copy. Switching branches in the main checkout still replaces `tasks.db` with that branch's committed snapshot; commit or pull task state before switching.

### `tc prd`

```bash
tc prd create  --title "..." [--description "..."] [--content "..."]
tc prd get     <id> [--json]
tc prd list    [--status active]
tc prd update  <id> [--title "..."] [--status completed]
```

### `tc wp`

```bash
tc wp store  --task <id> --type <type> --title "..." [--content "..."] [--file path]
tc wp get    <id>
tc wp list   [--task <id>] [--type <type>]
tc wp search "<query>"
tc wp render <id> --html            # render to .copilot/renders/WP-<id>.html (token-free)
tc wp render <id> --html --out /custom/path.html  # override output path
```

**HTML rendering** produces a fully self-contained file (inline CSS, vanilla JS, no CDN) at `.copilot/renders/WP-<id>.html`. The CLI prints only the absolute path to stdout — the HTML body never enters the context window. Auto-detects one of three templates based on content:

| Template | Trigger | Feature |
|----------|---------|---------|
| Severity | P0/P1/P2 or CRITICAL/HIGH/MEDIUM/LOW in content | Color-coded legend, severity-class CSS on rows |
| Variant grid | ≥ 2 headings containing "option/variant/alternative/approach/solution" | Tabbed comparison layout |
| Rendered diff | `\`\`\`diff` block or ≥ 3 `+x`/`-x` diff lines | Diff viewer with syntax highlighting |

All rendered files include "Copy as Markdown" and "Copy as JSON" buttons. Long-form content (≥ 100 newlines) gets a Rendered / Source tab switcher.

### `tc stream`

```bash
tc stream create --name "..."
tc stream list
tc stream get <id>
```

### `tc progress / tc handoff / tc log`

```bash
tc progress                        # task count by status per stream
tc handoff --from me --to qa --task <id> --context "..."
tc log --task <id> [--limit 20]
```

### `tc worker`

`tc worker <task_id>` is the non-interactive dispatch path: it runs `claude --print --output-format json --agent <agent> [--max-budget-usd <float>] [--model <model>] <prompt>` for the given task.

```bash
tc worker 42                             # dispatch task 42 with no cap
tc worker 42 --max-budget-usd 2.50       # cap at $2.50
tc worker 42 --max-budget-usd 2.50 --model claude-opus-4-5
tc worker 42 --dry-run --json            # print the command as JSON, don't run it
```

**`--max-budget-usd <float>`** is a native, harness-enforced spending cap — passed straight through to `claude --print --max-budget-usd`, which kills the run at the API boundary once the cap is hit. There is no separate enforcement layer to wait on; passing the flag *is* enforcement.

What `tc worker` adds on top of that: every dispatch's `total_cost_usd` / `num_turns` / `stop_reason` / `terminal_reason` is recorded to `agent_log` (`tc log --task <id>`), and if the harness kills the run for exceeding its cap, the task is released back to `pending` with its claim cleared instead of being left stuck `in_progress` under a dead run's claim.

There is no `tc worker run` / `tc worker status` subcommand and no `--max-budget-usd` flag on `tc task create` / `tc task claim` — `tc worker <task_id> --max-budget-usd <float>` is the only surface for this.

---

### `tc deploy`

Deploy commands for CI/CD integration. The deploy CLI used is config-gated — no vendor is hardcoded.

```bash
tc deploy wait <app_id> --task <id>   # trigger deploy, poll until terminal, store report as WP
```

**Configure the deploy CLI** (required before first use):

```bash
# Via cc config (machine or project layer)
cc config set deploy.cli "my-deploy-tool"

# Or via env var (takes precedence)
export CC_DEPLOY_CLI="my-deploy-tool"
```

---

### `tc watch`

```bash
tc watch                           # live dashboard
tc watch --compact --refresh 10
```

---

## Work Product Externalization

When a WP's `--content` exceeds **8 KB** (`WP_CONTENT_SIZE_THRESHOLD`), `tc wp store` writes the payload to a file in `.copilot/wp/` and stores a reference in the database rather than inlining the content. This prevents large analysis outputs from bloating context when the WP is retrieved via `tc wp get`. The threshold is exposed as `WP_CONTENT_SIZE_THRESHOLD` in `tc/__init__.py` and can be adjusted for local environments.

---

## Layout

```
tools/tc/
  pyproject.toml
  src/tc/
    __init__.py          # version, WP_CONTENT_SIZE_THRESHOLD constant
    main.py              # Typer app + top-level commands (progress, handoff, log, watch)
    api.py               # flat importable facade for code-execution use
    commands/            # one module per subcommand group
      task.py            # task create/get/list/update/claim/next/deps
      prd.py             # prd create/get/list/update
      wp.py              # wp store/get/list/search
      stream.py          # stream create/get/list/update
      handoff.py         # (see main.py)
      log_cmd.py
      progress.py
      watch.py
    services/            # domain logic (called by CLI handlers and api.py)
      tasks.py           # create_task, add_dependency
      prds.py            # create_prd
      wp.py              # store_wp
      render_html.py     # render_wp_html — token-free HTML output (auto-detects template)
    db/
      connection.py      # get_db, init_db, find_db_path, transaction()
      schema.py          # CREATE TABLE statements
      models.py          # TypedDict row types
      exceptions.py      # TcError, TaskNotFound, ValidationError, ConflictError, ...
    formatting/          # output_json, output_table, output_error_json
    utils/
      errors.py          # error_exit, require_db, EXIT_* codes
  tests/
    conftest.py
    test_task.py
    test_prd.py
    test_wp.py
    test_services.py     # service layer + api facade + transaction tests
    ...
```

## Evidence v2 migration and installation

QA-required pending tasks now need a registered acceptance contract and captured
source identity. Completed pre-v2 history remains readable, labelled historical.
This is a breaking completion-contract change; no stored evidence is rewritten.

```json
{"schemaVersion":2,"criteria":[{"id":"C1","expected":"The named input produces the required result"}],"sources":["src","tests"]}
```

Run `tc task contract ID --file acceptance.json`, then
`tc task evidence-identity ID` **before** executing QA; retain the exact identity
line with criterion/expected/observed/baseline/artifact/verdict evidence. Capture
again after tests and compare. Source, task description, criteria, runtime, or
configuration changes invalidate the identity; rerun verification. Sources are
explicit: include dependencies and configuration that can change the result.
Put generated artifacts in `.copilot` outside source scopes. Hashes do not prove
that observations happened; QA remains responsible for behavioral evidence.

The CLI and `tc.api.capture_qa_identity` use the same implementation. Task
completion enforces dependencies and cannot downgrade requiresQa. Registering a
new contract on completed work requires reopening and fresh evidence.

Install standalone development tc with `bash tools/tc/install.sh`; its prior
launcher is backed up and source/dependency receipts are written inside the venv.
`tc provenance --json` verifies without changing anything. `--record` is an
explicit installation operation, never a verification fallback. Development
receipts describe mutable checkouts; release installation uses verified source
snapshots and publishes cc/tc together with rollback. Ambient PYTHONPATH and
PYTHONHOME are removed during install verification to prevent checkout borrowing.

## Persistent execution limits

For iterative QA work, register the task's v2 acceptance contract first, then
freeze its execution budget. Caps belong to the task, not the round label or
agent process. Registration is immutable; a handoff cannot raise it or erase
prior attempts. Authorization references are carried verbatim in status and
handoff output.

```sh
tc execution register 42 --attempts 3 --calls 12 --usd 1.50 \
  --timeout 900 --stale 300 --authority 'owner approval: message or WP reference'
tc execution run 42 --criterion DELIVERY --label qualification \
  --calls 4 --usd 0.50 --usage-file /absolute/fresh-report.json -- python run_case.py
tc execution status 42
```

Choose caps from the actual workload: each AI attempt must have enough allowance
for its complete write/review/repair/re-review loop. Register before spending;
do not split a failing criterion into another task to reset its budget.
`--root` selects the source worktree when the task database is shared.

The runner executes from the registered root without a shell, with a process-group
timeout, and writes private output/receipt files under
`.copilot/execution/<task>/<attempt>/`. A fresh usage report supplies
`network_calls` and `recorded_cost_usd`; missing receipts retain the full reserved
allowance. Crashed reservations remain outstanding and prevent another attempt.
Reconcile one with `tc execution settle TOKEN --artifact REPORT`; only supply
`--calls` and `--usd` when actual measured usage is available. Never infer zero
spend from a missing report. Overruns are retained and block further spending.

After two failed attempts for a criterion, paid repetition stops. Locate the
enforcing code, fix the measured cause, and run its corrective regression:

```sh
tc execution prove 42 --criterion DELIVERY -- python -m pytest tests/test_delivery.py
tc execution diagnose 42 --criterion DELIVERY --regression /path/from/prove/result.json
```

The checkpoint must be a runner-recorded passing result on changed, stable
source. It unlocks diagnosis only; **it does not reset any cumulative cap**.
The prove command requests strict-stub transport; QA must still judge whether
the regression proves the cause. A command exit of zero is not a QA verdict.

### Successor ledgers

A successor ledger continues the same task and criteria after a registration is exhausted. It is the only sanctioned way to continue after an exhausted registration. A successor carries all consumed usage and failures forward, requires a new explicit owner authority, can only raise lifetime caps, never resets anything, and is recorded in status lineage. The agent must quote the owner's authority verbatim.

```sh
tc execution succeed 42 --attempts 40 --calls 200 --usd 6.00 \
  --authority 'owner approval: verbatim quote or WP reference'
```

Caps are lifetime totals, not fresh allowances; `status` shows each round, lifetime usage and `remaining` (new cap minus lifetime used). Creation is refused when no registration exists, when no `--authority` differs byte-for-byte from every earlier one, when any cap is below lifetime usage or the predecessor cap, or while an attempt is unsettled. The predecessor row stays immutable and is marked superseded; `register` on that task still accepts only a byte-identical repeat. A successor of a successor follows the same rules. A successor is not a diagnosis: failed-attempt history and blocked states are inherited, and `diagnose` is still required.

`tc worker` requires limits, `--criterion`, and `--max-budget-usd` for QA tasks.
It reserves before launch and records the native harness's measured cost.
Legacy non-QA workers retain their existing behavior. Worker model turns are
not counted as application transport requests. Passing current source-bound QA
prevents redundant guarded runs and reopening completed passing tasks. Scope
metadata cannot be widened after registration.

For application transports, call `tc.api.consume_call(token=...,
db_path=...)` **before each actual outbound request, including retries**. The
runner exports `TC_EXECUTION_TOKEN` and `TC_EXECUTION_DB`. This atomically counts
requests and rejects exhausted, expired or source-stale reservations. Retain the
provider's per-request cost/token bound and report actual total cost at settlement.
Without that transport integration, request counts/cost are reserved and
reconciled, not intercepted. Neither this local tool nor its environment flags
sandbox arbitrary shell commands or block network access by themselves.

Status distinguishes idle, awaiting a result, stale unresolved execution,
blocked, and terminal task state. Staleness is an overdue-evidence signal, not
proof a process died. It is checked on demand; no daemon is installed. Use newly
persisted result artifacts to report progress. Handoffs preserve this state and
authorization references without turning them into QA approval.

These controls are local execution discipline, not a security boundary against
an actor who can edit the SQLite database, manufacture reports, or bypass tc.
Existing QA evidence and test-integrity requirements remain the acceptance gate.
