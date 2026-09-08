"""One task-completion authority for CLI, API and native hooks.

Pending QA-required work needs a registered v2 acceptance contract, exact
criterion coverage and a machine-captured content identity. tc.evidence retains
its pure v1 text parser/structural validator; qa_contract owns database/source
binding. Completed pre-v2 history stays readable and is explicitly historical,
never evidence of current strict verification. Updating/reopening work requires
fresh v2 evidence. Artifact text is inspected, never executed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from tc.db.exceptions import TaskNotFound, ValidationError
from tc.evidence import EVIDENCE_SCHEMA_VERSION, parse_packet, validate_packet

# Work-product types the older predicate treated as "implementation
# changed" for the newer-than-evidence ordering check. Kept as a coarse,
# additional signal alongside the live-identity comparison below -- an
# implementation-type work product with a higher id than the evidence being
# checked is stale by ordering even when the packet's IDENTITY otherwise
# looks current (e.g. a caller who forgot to update IDENTITY at all).
IMPLEMENTATION_TYPES = ("code", "implementation", "bugfix", "implementation_summary", "implementation-summary")


def task_metadata(raw: Any) -> dict:
    """Parse a task's ``metadata`` column (JSON string, dict, or None) into
    a plain dict, raising ``ValidationError`` on malformed input."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw or {}
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid task metadata") from exc
    if not isinstance(value, dict):
        raise ValidationError("Task metadata must be an object")
    return value


def _evidence_work_products(task_id: int, conn) -> list[dict]:
    """Every work product for `task_id`, oldest to newest.

    Closes defect 5: the caller inspects every work product, not just the
    single latest ``type='test'`` row, so a criterion set spread across
    several work products (or an older passing one superseded only by
    unrelated later WPs) is visible.
    """
    from tc.services.wp import get_wp

    rows = conn.execute(
        "SELECT id FROM work_products WHERE task_id = ? ORDER BY id ASC",
        (task_id,),
    ).fetchall()
    return [get_wp(wp_id=row["id"], conn=conn) for row in rows]


def check_task_qa(*, task_id: int, conn=None, db_path: Optional[Path] = None, task_override: Optional[dict] = None) -> dict[str, Any]:
    """The completion predicate.

    Returns a dict with at least: ``task_id``, ``approved`` (bool),
    ``work_product_id`` (the evidence WP the verdict is based on, or
    None), ``reason`` (human-readable), and ``legacy`` (bool -- whether the
    governing evidence predates ``EVIDENCE_SCHEMA_VERSION``).

    Raises:
        TaskNotFound: if task_id does not exist.
    """
    from tc.services.tasks import _open_conn, _require_db_path

    owns_conn = conn is None
    if owns_conn:
        conn = _open_conn(_require_db_path(db_path))
    try:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            raise TaskNotFound(f"task #{task_id} not found")

        task = task_override or dict(task)
        result: dict[str, Any] = {
            "task_id": task_id,
            "approved": False,
            "work_product_id": None,
            "reason": "No task-bound evidence",
            "legacy": False,
        }

        work_products = _evidence_work_products(task_id, conn)
        if not work_products:
            return result

        # Completed pre-v2 history remains inspectable; pending work must migrate.
        historical = task["status"] == "completed" and not task_metadata(task["metadata"]).get("acceptanceContract")
        current_identity = None

        # Assemble the current criterion set (defect 5): walk newest to
        # oldest, collecting evidence-shaped work products. A work product
        # that carries its own VERDICT marks a QA-round boundary. The
        # newest such boundary (typically a final summary WP) belongs to
        # the CURRENT round and is included, along with every evidence-only
        # (no VERDICT of its own) work product newer than it or between it
        # and the next-older boundary -- e.g. one work product per test
        # area, with a final summary WP carrying the overall verdict. The
        # walk stops the moment a SECOND verdict-bearing work product is
        # reached (excluding it): that one belongs to an earlier, resolved
        # round (an old REJECTED, since fixed and re-approved), and must
        # not bleed into the current round as a spurious "conflicting
        # verdict".
        contributing: list[dict[str, Any]] = []
        verdict_boundaries_seen = 0
        for wp in reversed(work_products):
            content = wp.get("content") or ""
            packet = parse_packet(content)
            if not packet["verdicts"] and not packet["artifacts"]:
                continue  # not evidence-shaped; keep looking further back
            if packet["verdicts"]:
                verdict_boundaries_seen += 1
                if verdict_boundaries_seen > 1:
                    break  # an earlier round's boundary; stop before including it
            contributing.append({"wp": wp, "packet": packet, "content": content})

        if not contributing:
            return result

        result["work_product_id"] = contributing[0]["wp"]["id"]

        # Merge oldest-to-newest so a later restatement of IDENTITY/
        # BASELINE/UNTESTED supersedes an earlier one, and every
        # CRITERION/EXPECTED/OBSERVED/ARTIFACT/VERDICT line across the
        # contributing set is preserved. Merging BEFORE the legacy check
        # matters: a supplementary work product (e.g. Area 1 above) may
        # carry no IDENTITY of its own and rely on the round's final
        # summary work product for it -- legacy status is judged on the
        # ASSEMBLED set, never on an individual contributor in isolation.
        combined: dict[str, Any] = {
            "records": [],
            "identity": None,
            "baseline": None,
            "artifacts": [],
            "untested": None,
            "verdicts": [],
        }
        for item in reversed(contributing):
            packet = item["packet"]
            combined["records"].extend(packet["records"])
            combined["artifacts"].extend(packet["artifacts"])
            combined["verdicts"].extend(packet["verdicts"])
            if packet["identity"]:
                combined["identity"] = packet["identity"]
            if packet["baseline"]:
                combined["baseline"] = packet["baseline"]
            if packet["untested"]:
                combined["untested"] = packet["untested"]

        # Legacy policy (see module docstring): the assembled set is
        # legacy-shaped when it carries evidence at all but no IDENTITY
        # anywhere in it -- the pre-v1 shape no work product in the
        # contributing set can supply.
        if (combined["verdicts"] or combined["artifacts"]) and not combined["identity"]:
            result["legacy"] = True
            if historical:
                result.update(
                    approved=True,
                    reason=(
                        f"Legacy evidence (pre-schema-v{EVIDENCE_SCHEMA_VERSION}, no "
                        "IDENTITY field) is preserved for an already-completed task "
                        "and is not retroactively invalidated"
                    ),
                )
            else:
                result.update(
                    approved=False,
                    reason=(
                        f"Legacy evidence (no IDENTITY field) predates the schema "
                        f"v{EVIDENCE_SCHEMA_VERSION} evidence contract and does not "
                        "satisfy it; store a new QA work product using the "
                        "CRITERION/EXPECTED/OBSERVED/IDENTITY/.../VERDICT packet"
                    ),
                )
            return result

        newest_evidence_id = max(item["wp"]["id"] for item in contributing)
        placeholders = ",".join("?" for _ in IMPLEMENTATION_TYPES)
        later_impl = conn.execute(
            f"SELECT id FROM work_products WHERE task_id = ? AND id > ? AND type IN ({placeholders}) LIMIT 1",
            (task_id, newest_evidence_id, *IMPLEMENTATION_TYPES),
        ).fetchone()
        if later_impl:
            result.update(
                approved=False,
                reason="Implementation evidence is newer than this QA evidence",
            )
            return result

        if not historical:
            from tc.services.qa_contract import binding_errors
            errors = binding_errors(task, conn, combined)
            if errors:
                result.update(approved=False, reason=errors[0])
                return result
        verdict = validate_packet(combined, current_identity=current_identity)
        if verdict["valid"]:
            result.update(approved=True, legacy=historical, reason="Historical pre-v2 approval preserved; not current strict verification" if historical else "Task-bound evidence packet passes")
        else:
            result.update(approved=False, reason=verdict["reason"])
        return result
    finally:
        if owns_conn:
            conn.close()
