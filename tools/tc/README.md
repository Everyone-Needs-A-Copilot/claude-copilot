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
tc task create  --title "..." --prd <id> --agent <slug> --priority 0-3
tc task get     <id> [--json]
tc task list    [--status pending] [--agent me] [--prd <id>]
tc task update  <id> --status completed
tc task claim   <id> --agent <slug>
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
```

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
