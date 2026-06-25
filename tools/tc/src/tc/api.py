"""tc.api — flat, importable facade for code-execution use.

This is the single documented import surface for agents running multi-step
task/PRD/work-product operations in a single python3 block.  All functions:

  - Return plain Python dicts / lists-of-dicts.
  - Raise typed exceptions (never print, never sys.exit).
  - Accept an optional ``conn`` parameter so multiple ops can be batched in
    one transaction (use ``transaction()`` as context manager).
  - Are import-side-effect-free: no DB opened, no env read at import time.

CRITICAL: tc and cc live in separate installed environments.  Keep each
code-execution block scoped to ONE tool (tc-only OR cc-only).

Usage pattern — "create PRD + N tasks + wire dependencies" (one Bash call):
    python3 - << 'PY'
    from tc.api import create_prd, create_task, add_dependency, transaction
    from tc.db.connection import get_db
    from tc.db.connection import find_db_path

    db_path = find_db_path()
    conn = get_db(db_path)
    try:
        with transaction(conn):
            prd = create_prd(title="Checkout v2", conn=conn)
            specs = [
                {"title": "Schema migration", "priority": 0, "agent": "me"},
                {"title": "API endpoints",    "priority": 1, "agent": "me"},
                # ... more tasks
            ]
            ids = [create_task(prd=prd["id"], **s, conn=conn)["id"] for s in specs]
            for prev, cur in zip(ids, ids[1:]):
                add_dependency(task_id=cur, depends_on=prev, conn=conn)
    finally:
        conn.close()
    print(f"PRD-{prd['id']}: {len(ids)} tasks, {len(ids)-1} deps wired")
    PY

Returns to context: one line, ~25 tokens instead of ~36 round-trips.

For single one-shot ops the CLI is simpler:
    tc task create --title "Fix login" --prd 1 --json
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-export typed exceptions (callers can catch these)
# ---------------------------------------------------------------------------
from tc.db.exceptions import (
    ConflictError,
    DatabaseError,
    PrdNotFound,
    TaskNotFound,
    TcError,
    ValidationError,
    WorkProductNotFound,
)

# ---------------------------------------------------------------------------
# Re-export transaction helper
# ---------------------------------------------------------------------------
from tc.db.connection import transaction

# ---------------------------------------------------------------------------
# Re-export service functions (flat surface)
# ---------------------------------------------------------------------------
from tc.services.tasks import (
    add_dependency,
    claim_task,
    create_task,
    get_task,
    list_tasks,
    next_task,
    remove_dependency,
    update_task,
)
from tc.services.prds import (
    create_prd,
    get_prd,
    list_prds,
    update_prd,
)
from tc.services.wp import (
    get_wp,
    list_wps,
    search_wps,
    store_wp,
)
from tc.services.render_html import render_wp_html
from tc.services.handoff import handoff_task
from tc.services.log import list_log
from tc.services.progress import get_progress
from tc.services.streams import (
    StreamNotFound,
    create_stream,
    get_stream,
    list_streams,
)

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    # exceptions
    "TcError",
    "TaskNotFound",
    "PrdNotFound",
    "WorkProductNotFound",
    "ValidationError",
    "ConflictError",
    "DatabaseError",
    "StreamNotFound",
    # transaction helper
    "transaction",
    # task ops
    "create_task",
    "get_task",
    "list_tasks",
    "update_task",
    "claim_task",
    "next_task",
    "add_dependency",
    "remove_dependency",
    # prd ops
    "create_prd",
    "get_prd",
    "list_prds",
    "update_prd",
    # work product ops
    "store_wp",
    "get_wp",
    "list_wps",
    "search_wps",
    "render_wp_html",
    # handoff
    "handoff_task",
    # log
    "list_log",
    # progress
    "get_progress",
    # stream ops
    "create_stream",
    "get_stream",
    "list_streams",
]
