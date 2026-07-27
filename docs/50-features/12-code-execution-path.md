# Code Execution Path

**Diátaxis mode:** How-to / Reference

Agents can compose multiple Task Copilot or Memory Copilot operations in a single `python3` block, avoiding the overhead of N sequential Bash round-trips. This is the recommended path for multi-step operations.

---

## Why Use the API Facades

Each `tc` or `cc` CLI invocation forks a subprocess, spawns Python, opens the database, runs a command, prints JSON, and exits. For a sequence of 5 operations that produces a compact result, the overhead can exceed 5× the useful work.

Using the importable facades instead:

| Approach | Calls | Output returned to context |
|----------|-------|---------------------------|
| 5 × CLI `tc task create ...` | 5 subprocesses | ~35 lines of JSON |
| 1 × `python3` block using `tc.api` | 1 subprocess | 1 summary line |

The ~99% intermediate-output win comes from two sources: the subprocess-per-call cost is eliminated, and **only the final `print()` line enters the agent context** — all intermediate state stays inside the process.

---

## The Two Facades

### `tc.api` — Task Copilot

```
tools/tc/src/tc/api.py
```

Flat re-export of service functions. All functions return plain dicts, raise typed exceptions, and accept an optional `conn` parameter for batching inside a single SQLite transaction.

**Typical imports:**

```python
from tc.api import (
    create_prd, get_prd, update_prd, list_prds,
    create_task, get_task, update_task, list_tasks,
    add_dependency, remove_dependency, next_task, claim_task,
    store_wp, get_wp, list_wps, search_wps,
    handoff_task, list_log, get_progress,
    create_stream, get_stream, list_streams,
    transaction,
    # exceptions
    TcError, TaskNotFound, PrdNotFound, WorkProductNotFound,
    ValidationError, ConflictError,
)
from tc.db.connection import get_db, find_db_path
```

### `cc.api` — Memory Copilot

```
tools/cc/src/cc/api.py
```

Flat re-export of memory and skill helpers.

**Typical imports:**

```python
from cc.api import (
    memory_store, memory_get, memory_list, memory_delete,
    memory_search,
    skill_get, skill_list,
    # exceptions
    MemoryError, EntryNotFound, EntryValidationError, SkillNotFound,
)
```

---

## The R5 Caveat — Never Mix `tc` and `cc` in One Block

`tc` and `cc` are installed in separate Python virtual environments. They do **not** share `sys.path`. Importing from both in a single `python3 - <<'PY'` heredoc will raise `ModuleNotFoundError` at runtime.

**Always scope each code-execution block to one tool:**

```python
# CORRECT — tc-only block
from tc.api import create_prd, create_task, transaction
from tc.db.connection import get_db, find_db_path
# ...

# CORRECT — cc-only block
from cc.api import memory_store, memory_search
# ...

# WRONG — mixed block (will fail with ModuleNotFoundError)
from tc.api import create_prd
from cc.api import memory_store   # ← ModuleNotFoundError
```

If you need both `tc` and `cc` operations in a single agent step, use two sequential `python3` blocks — one for each tool.

---

## Service Modules

The service layer under `tools/tc/src/tc/services/` contains the canonical business logic. The `tc.api` facade re-exports from these modules:

| Module | Key functions |
|--------|--------------|
| `tasks.py` | `create_task`, `get_task`, `update_task`, `list_tasks`, `add_dependency`, `next_task`, `claim_task` |
| `prds.py` | `create_prd`, `get_prd`, `update_prd`, `list_prds` |
| `wp.py` | `store_wp`, `get_wp`, `list_wps`, `search_wps` |
| `streams.py` | `create_stream`, `get_stream`, `list_streams` |
| `handoff.py` | `handoff_task` |
| `log.py` | `list_log` |
| `progress.py` | `get_progress` |

See `tools/tc/README.md` and `tools/cc/README.md` for full function signatures and field-level documentation.

---

## Pattern: Create PRD + Tasks in One Block

```python
python3 - << 'PY'
from tc.api import create_prd, create_task, add_dependency, transaction
from tc.db.connection import get_db, find_db_path

db_path = find_db_path()
conn = get_db(db_path)
try:
    with transaction(conn):
        prd = create_prd(title="Checkout v2", conn=conn)
        specs = [
            {"title": "Schema migration", "priority": 0, "agent": "me"},
            {"title": "API endpoints",    "priority": 1, "agent": "me"},
            {"title": "UI components",    "priority": 2, "agent": "me"},
        ]
        ids = [create_task(prd=prd["id"], **s, conn=conn)["id"] for s in specs]
        for prev, cur in zip(ids, ids[1:]):
            add_dependency(task_id=cur, depends_on=prev, conn=conn)
finally:
    conn.close()
print(f"PRD-{prd['id']}: {len(ids)} tasks, {len(ids)-1} deps")
PY
```

Output returned to agent context: one line, ~20 tokens.

---

## Pattern: Store Multiple Work Products

```python
python3 - << 'PY'
from tc.api import store_wp, transaction
from tc.db.connection import get_db, find_db_path

db_path = find_db_path()
conn = get_db(db_path)
try:
    with transaction(conn):
        wp1 = store_wp(task_id="TASK-42", wp_type="implementation",
                       title="Auth middleware", content="...", conn=conn)
        wp2 = store_wp(task_id="TASK-42", wp_type="test_results",
                       title="Test run output", content="...", conn=conn)
finally:
    conn.close()
print(f"stored WP-{wp1['id']} and WP-{wp2['id']}")
PY
```

---

## Pattern: Memory Store + Search (cc-only block)

```python
python3 - << 'PY'
from cc.api import memory_store, memory_search

eid = memory_store(
    entry_type="decision",
    content="Use WAL mode for SQLite — prevents reader/writer contention",
    tags=["sqlite", "performance"],
)
hits = memory_search("WAL SQLite")
print(f"stored {eid['id'][:8]}, search returned {len(hits)} hits")
PY
```

---

## When to Use CLI vs. API

| Situation | Use |
|-----------|-----|
| Single operation, output needed inline | `tc task create --json` / `cc memory store` CLI |
| 2+ operations that share state or need a transaction | `tc.api` / `cc.api` in a python3 block |
| Result only needs to be a compact summary | `tc.api` block with a single `print()` |
| Mixed tc + cc operations | Two separate python3 blocks |

---

## See Also

- `tools/tc/README.md` — full `tc.api` reference
- `tools/cc/README.md` — full `cc.api` reference
- [Memory FTS5 Search](./13-memory-fts5.md) — how `memory_search` works under the hood
- [Goal-Driven Agents](./04-goal-driven-agents.md) — agent iteration patterns that compose these calls
