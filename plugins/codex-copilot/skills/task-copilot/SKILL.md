---
name: task-copilot
description: Use when work should be tracked with tc, including creating PRDs, tasks, handoffs, logs, and work products, or when preserving detailed outputs outside the chat context.
---

# Task Copilot

`tc` is the execution record. Use it instead of stuffing long plans or implementation logs into chat.

## Command rule

Use `--json` on commands that support it.

Preferred binary:

```bash
tc
```

Fallback:

```bash
./.venv-tc/bin/tc
```

## Core loop

1. retrieve the task
2. do the work
3. store the work product
4. complete the task

Commands:

```bash
tc task get <taskId> --json
tc wp store --task <taskId> --type <type> --title "..." --content "..." --json
tc task update <taskId> --status completed --json
```

## Code-Execution Path

Prefer the importable APIs for batches:

```bash
python3 - <<'PY'
from tc.api import create_prd, create_task, transaction
from tc.db.connection import get_db, find_db_path

conn = get_db(find_db_path())
try:
    with transaction(conn):
        prd = create_prd(title="Example", conn=conn)
        task = create_task(prd=prd["id"], title="Example task", conn=conn)
finally:
    conn.close()
print(f"PRD-{prd['id']} TASK-{task['id']}")
PY
```

Use a separate `cc.api` block for memory or skill batches. Do not import `tc.api` and `cc.api` in the same Python block.

## QA Metadata

Implementation tasks that require verification should use metadata like:

```json
{"requiresQa": true, "qaStatus": "pending"}
```

After QA approval, record `qaStatus`, `qaWpId`, and `verifiedAt` when possible. Use `scripts/copilot-gate.sh` to inspect the convention.

## When no task exists

Create the missing planning records:

```bash
tc prd create --title "..." --content "..." --json
tc task create --prd <id> --title "..." --description "..." --json
```

## Initiative boundary

Formal multi-phase initiative knowledge belongs in `docs/40-initiatives/NN-slug/`: goals, phase designs, decisions, validation evidence, and retrospectives. `tc` remains authoritative for live task state, dependencies, assignments, work products, and QA status.

Link the initiative README to its PRD and tasks. Do not reproduce a live task board in Markdown.

## Work-product guidance

Store detailed output when:

- the analysis is long
- decisions should survive the session
- another specialist should consume the result
- the final user response should stay short

Read `references/work-product-types.md` for type guidance.

For a large work product that benefits from token-free review, use
`tc wp render <id> --html`. The HTML is a rendering of the authoritative work
product, not a second source of task state.
