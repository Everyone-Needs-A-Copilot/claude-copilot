"""One evidence predicate for inspection and task completion."""
import json
import re

from tc.db.exceptions import TaskNotFound, ValidationError
from tc.services.wp import get_wp

ARTIFACT = re.compile(r"^\s*ARTIFACT:\s*(test-run|file-check|diff-check|screenshot-check|a11y-check|design-fidelity-check)\|\S.+$", re.M)
VERDICT = re.compile(r"^\s*VERDICT:\s*(APPROVED-WITH-MINOR-FIXES|APPROVED|REJECTED)\s*$", re.M)
IMPLEMENTATION_TYPES = ("code", "implementation", "bugfix", "implementation_summary", "implementation-summary")


def task_metadata(raw):
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw or {}
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid task metadata") from exc
    if not isinstance(value, dict):
        raise ValidationError("Task metadata must be an object")
    return value


def check_task_qa(*, task_id, conn=None, db_path=None):
    from tc.services.tasks import _open_conn, _require_db_path
    owns_conn = conn is None
    if owns_conn:
        conn = _open_conn(_require_db_path(db_path))
    try:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise TaskNotFound(f"task #{task_id} not found")
        test = conn.execute("SELECT id FROM work_products WHERE task_id=? AND type='test' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
        result = {"task_id": task_id, "approved": False, "work_product_id": None,
                  "reason": "No task-bound test evidence"}
        if test is None:
            return result
        wp = get_wp(wp_id=test["id"], conn=conn)
        result["work_product_id"] = wp["id"]
        placeholders = ",".join("?" for _ in IMPLEMENTATION_TYPES)
        later = conn.execute(f"SELECT id FROM work_products WHERE task_id=? AND id>? AND type IN ({placeholders}) LIMIT 1",
                             (task_id, wp["id"], *IMPLEMENTATION_TYPES)).fetchone()
        if later:
            result["reason"] = "Implementation evidence is newer than QA"
            return result
        content = wp.get("content") or ""
        verdicts = VERDICT.findall(content)
        if len(verdicts) != 1 or verdicts[0] == "REJECTED" or not ARTIFACT.search(content):
            result["reason"] = "Latest test requires one passing verdict and an ARTIFACT marker"
            return result
        result.update(approved=True, reason="Latest task-bound test evidence passes")
        return result
    finally:
        if owns_conn:
            conn.close()
