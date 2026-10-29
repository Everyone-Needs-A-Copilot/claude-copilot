"""Close-out review booleans on task metadata (A13) and the per-project summary."""
from __future__ import annotations

import json
import re
from typing import Optional

from tc.db.exceptions import TaskNotFound, ValidationError

FLAGS = ("scopeRecovered", "completionRecovered", "authorizationRepeated", "reworkFromAssumption")


def record_review(*, task_id: int, flags: dict, note: Optional[str], db_path=None) -> dict:
    from datetime import datetime, timezone
    from tc.services.tasks import update_task

    review = {k: bool(flags.get(k, False)) for k in FLAGS}
    review["note"] = note
    review["recordedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return update_task(task_id=task_id, metadata={"review": review}, db_path=db_path)


def review_summary(*, since: Optional[str] = None, db_path=None) -> dict:
    from tc.db.connection import get_db

    if since is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        raise ValidationError("--since must be YYYY-MM-DD")
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            "SELECT t.id, t.metadata, COALESCE((SELECT MAX(l.created_at) FROM agent_log l "
            "WHERE l.task_id = t.id AND l.action = 'completed'), t.updated_at) AS closed "
            "FROM tasks t WHERE t.status = 'completed'"
        ).fetchall()
    finally:
        conn.close()
    summary = {"since": since, "tasksCompleted": 0, "tasksReviewed": 0, **{k: 0 for k in FLAGS}}
    for row in rows:
        if since and row["closed"][:10] < since:
            continue
        summary["tasksCompleted"] += 1
        try:
            review = (json.loads(row["metadata"]) if row["metadata"] else {}).get("review")
        except ValueError:
            review = None
        if isinstance(review, dict):
            summary["tasksReviewed"] += 1
            for k in FLAGS:
                summary[k] += 1 if review.get(k) is True else 0
    return summary
