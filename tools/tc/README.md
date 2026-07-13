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
tc task list    [--status pending] [--agent me] [--prd <id>]
tc task update  <id> --status completed
tc task claim   <id> --agent <slug> [--max-budget-usd <float>]
tc task next    [--agent me]
tc task deps add    <id> --depends-on <id>
tc task deps remove <id> --depends-on <id>
```

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

### `tc solution` — the Outcome Ledger

Tracks a Solution (the CSE's unit of value: a completed artifact that resolves
a real person's real problem) end-to-end, feeding the outcome bars O-1
(TTFLS), O-2 (Completeness), O-3 (Speed, observed via the cse-bench
`solutions` collector), and O-5 (Survival). Lifecycle:

```bash
tc solution create --title "..." [--brief "..."] [--beneficiary "..."] \
    [--repo-path "..."] [--components framework,knowledge,integration]
tc solution lock-brief   <id> [--brief "..."]   # locks the intent contract; immutable once locked
tc solution mark-working <id>                    # O-1: t_working
tc solution mark-loveable <id>                   # O-1: t_loveable
tc solution log-usage    <id> [--kind usage|fix|feature] [--sessions N] [--tokens N] [--note "..."]
tc solution close        <id> --status shipped|abandoned|retired [--notes "..."] [--post-ship-window-days N]
tc solution get          <id> [--json]           # includes scope_log + usage_log
tc solution list         [--status ...] [--json]
```

Notes:
- The brief is immutable once locked -- calling `lock-brief` again records the
  attempted edit to an append-only scope-change log instead of rewriting it
  (`scope_change_recorded: true` in the response).
- `close --status shipped` requires the brief to already be locked (O-2
  measures completeness against it).
- The first `log-usage` call after shipping flips status `shipped -> in_use`
  (O-5's sustained-use signal); `log-usage --kind fix|feature` accumulates the
  post-ship fix-vs-feature ratio.
- Schema bootstrap is automatic and additive: the first `tc solution` command
  run against any existing `tasks.db` creates the ledger's tables
  transparently (`ensure_solutions_schema`, in `db/connection.py`) -- no `tc
  init` re-run needed.
- Every returned dict carries the PRD's literal entity shape as additive,
  derived views alongside the flat storage fields: `brief_lock: {text,
  locked_at}`, `post_ship: {fixes, features, window_days}`, and
  `components_used` decoded to an actual list (not a JSON-text string).

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

`tc worker` is the agent-dispatch surface for budget-bounded task execution.

**`--max-budget-usd <float>`** — per-task cost cap. Set it on `tc task create` or `tc task claim` to annotate the maximum USD the dispatched agent is permitted to spend on that task.

```bash
# Create a task with a $0.50 cost cap
tc task create --title "Generate unit tests" --prd 1 --agent qa --max-budget-usd 0.50

# Claim a task and declare a cap at claim time
tc task claim 42 --agent me --max-budget-usd 1.00
```

The flag is stored in task metadata (`metadata.max_budget_usd`). You can retrieve it:

```bash
tc task get 42 --json | python3 -c "import sys,json; t=json.load(sys.stdin); print(t.get('metadata',{}).get('max_budget_usd','unset'))"
```

**Current status — flag plumbing only (tc 1.3.0):** The value is stored and retrievable. Runtime enforcement — rejecting or halting a dispatch that would exceed the cap — is a **roadmap P1** item. Setting the flag now future-proofs your task graph for when enforcement ships.

**`tc worker` subcommand (dispatch surface):**

```bash
tc worker run   <task_id>   # dispatch task to its assigned agent (respects max_budget_usd when enforcement lands)
tc worker status <task_id>  # show dispatch state and budget annotation
```

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
      solution.py        # solution create/lock-brief/mark-working/mark-loveable/log-usage/close/get/list
      handoff.py         # (see main.py)
      log_cmd.py
      progress.py
      watch.py
    services/            # domain logic (called by CLI handlers and api.py)
      tasks.py           # create_task, add_dependency
      prds.py            # create_prd
      wp.py              # store_wp
      solutions.py       # the Outcome Ledger (W-1): create_solution, lock_brief, mark_working, mark_loveable, log_usage, close_solution
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
