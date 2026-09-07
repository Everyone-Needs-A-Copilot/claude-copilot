"""tc.services.qa — the task completion authority for QA evidence.

``check_task_qa(...)`` is the ONLY function ``tc.services.tasks.update_task``
calls to decide whether a task may transition to ``status='completed'``
when its metadata carries ``requiresQa=true`` (see ``update_task`` and the
requiresQa-at-creation policy documented in ``tc.services.tasks.create_task``
for defect 3). Both the CLI (``tc task update`` / `tc task check-qa`) and
``tc.api.update_task`` reach this same function object -- there is exactly
one completion authority, not one per caller.

This module owns exactly three concerns that ``tc.evidence`` does NOT:

  1. DB traversal -- which work products count as evidence for a task, and
     in what order (defect 5: a criterion set spread across several work
     products, not just the single latest ``type='test'`` row).
  2. Staleness / identity comparison against the CURRENT repository state
     (defect 4), via ``_current_identity`` (git revision + dirty-tree
     fingerprint) and ``tc.evidence.validate``'s IDENTITY comparison.
  3. Legacy-evidence policy, keyed on ``EVIDENCE_SCHEMA_VERSION`` (see
     LEGACY POLICY below).

Everything about what a SINGLE evidence packet must contain to be
well-formed lives in ``tc.evidence`` (pure, no DB/git/subprocess).

LEGACY POLICY (defect-3.4 migration requirement -- preserve history,
never silently upgrade old evidence to satisfy a stronger contract it
predates):

    A work product's content is "legacy-shaped"
    (``tc.evidence.parse.is_legacy_shaped``) when it carries a VERDICT
    and/or ARTIFACT line but no IDENTITY field at all. IDENTITY is the one
    field the v1 contract requires that no pre-v1 packet ever had, so its
    total absence is a reliable, self-contained version signal -- no stored
    schema-version number is needed on historical rows.

    * Task already ``status='completed'``: legacy evidence remains
      sufficient. ``check_task_qa`` returns ``approved=True``,
      ``legacy=True``, and a reason saying so. This never re-runs the
      stronger validator against history, so an already-completed task is
      not retroactively invalidated by a contract it predates.
    * Task NOT yet completed: legacy-shaped evidence alone does NOT satisfy
      the current (v{EVIDENCE_SCHEMA_VERSION}) predicate. ``check_task_qa``
      returns ``approved=False``, ``legacy=True``, and a reason naming the
      gap explicitly (never a silent pass), so legacy-shaped evidence can
      never be mistaken for satisfying the stronger contract going forward.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
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


def _current_identity(cwd: Optional[str] = None) -> Optional[dict]:
    """Best-effort current git revision + dirty-tree fingerprint (defect 4).

    Returns ``{"revision": <7-hex-char short sha>, "dirty": bool,
    "dirty_fingerprint": <12-hex-char digest of `git diff HEAD`>}``, or
    ``None`` when `cwd` is not inside a git repository (or git is
    unavailable) -- in which case staleness comparison is skipped rather
    than failing closed on an environment that cannot supply the signal at
    all (e.g. a fresh test database in a plain temp directory).

    The 7-character short revision matches git's own default short-sha
    length, so it is very likely to appear verbatim as a substring of
    whatever revision notation a QA agent wrote into IDENTITY (full sha,
    `git describe`, or its own 7-char short form) -- see
    ``tc.evidence.validate``'s comparison. The dirty-tree fingerprint is a
    much narrower, best-effort signal: it can only catch drift when the
    recorded IDENTITY explicitly claims "clean" (a real, checkable
    contradiction) or embeds a `dirty:<hex>`/`fingerprint:<hex>` token
    using the same convention -- there is no shared fingerprint algorithm
    a QA-authoring agent is required to reproduce, so silence on this half
    is not itself proof of staleness.
    """
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=5, check=False,
        )
        if revision.returncode != 0 or not revision.stdout.strip():
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd, capture_output=True, text=True, timeout=5, check=False,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=5, check=False,
        )
        dirty_fingerprint = None
        if diff.returncode == 0 and diff.stdout:
            dirty_fingerprint = hashlib.sha256(diff.stdout.encode("utf-8")).hexdigest()[:12]
        return {
            "revision": revision.stdout.strip(),
            "dirty": dirty,
            "dirty_fingerprint": dirty_fingerprint,
        }
    except (OSError, subprocess.SubprocessError):
        return None


def _db_repo_root(conn) -> Optional[str]:
    """Best-effort project root for `conn`'s attached database file.

    By convention the database lives at ``<project>/.copilot/tasks.db``, so
    its grandparent directory is the project checkout `_current_identity`
    should be scoped to -- deliberately NOT the process's ambient cwd,
    which in a test run is the tc/cc developer's own checkout rather than
    the (test-isolated) project the database belongs to.
    """
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except Exception:
        return None
    for row in rows:
        try:
            name, file = row["name"], row["file"]
        except (KeyError, IndexError, TypeError):
            name, file = row[1], row[2]
        if name == "main" and file:
            return str(Path(file).parent.parent)
    return None


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


def check_task_qa(*, task_id: int, conn=None, db_path: Optional[Path] = None) -> dict[str, Any]:
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

        current_identity = _current_identity(cwd=_db_repo_root(conn))

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
            if (task["status"] or "") == "completed":
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

        verdict = validate_packet(combined, current_identity=current_identity)
        if verdict["valid"]:
            result.update(approved=True, reason="Task-bound evidence packet passes")
        else:
            result.update(approved=False, reason=verdict["reason"])
        return result
    finally:
        if owns_conn:
            conn.close()
