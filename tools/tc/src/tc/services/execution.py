"""Persistent execution limits for local task runners (not a security sandbox).

Reservations are conservative: a crashed or unreported run retains its entire
allowance. Round labels and process restarts never reset task totals. QA remains
the authority for product acceptance; a successful command is not QA approval.
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from tc.db.exceptions import ValidationError
from tc.services.qa_contract import digest, source_manifest, validate_contract
from tc.services.tasks import _open_conn, _require_db_path, get_task

_TABLES = (
    "CREATE TABLE IF NOT EXISTS execution_limits (task_id INTEGER PRIMARY KEY REFERENCES tasks(id), policy TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS execution_attempts (
    token TEXT PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
    criterion TEXT NOT NULL, label TEXT NOT NULL, source TEXT NOT NULL,
    state TEXT NOT NULL, reserved_calls INTEGER NOT NULL, reserved_micros INTEGER NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0, micros INTEGER NOT NULL DEFAULT 0,
    started REAL NOT NULL, ended REAL, artifact TEXT, artifact_hash TEXT,
    end_source TEXT, reason TEXT)""",
    """CREATE TABLE IF NOT EXISTS execution_checkpoints (
    id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
    criterion TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
    artifact TEXT NOT NULL, artifact_hash TEXT NOT NULL, created REAL NOT NULL,
    through_started REAL NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS execution_rounds (
    task_id INTEGER NOT NULL REFERENCES tasks(id), round INTEGER NOT NULL,
    policy TEXT NOT NULL, predecessor_round INTEGER NOT NULL,
    predecessor_created REAL, created REAL NOT NULL,
    used_attempts INTEGER NOT NULL, used_calls INTEGER NOT NULL,
    used_micros INTEGER NOT NULL, PRIMARY KEY (task_id, round))""",
)


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _micros(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError()
        return int((amount * 1_000_000).to_integral_value(rounding="ROUND_CEILING"))
    except (InvalidOperation, ValueError, OverflowError):
        raise ValidationError("Cost must be finite and nonnegative") from None


@contextmanager
def _db(db_path):
    conn = _open_conn(_require_db_path(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        for sql in _TABLES:
            conn.execute(sql)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _contract(task):
    metadata = task.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return validate_contract(metadata.get("acceptanceContract"))


def _rounds(conn, task_id):
    """Ordered lineage; round 1 is the immutable registration (its time predates this record)."""
    row = conn.execute(
        "SELECT policy FROM execution_limits WHERE task_id=?", (task_id,)
    ).fetchone()
    if not row:
        raise ValidationError(f"Task {task_id} has no registered execution limits")
    rounds = [{"round": 1, "policy": json.loads(row[0]), "created": None}]
    for r in conn.execute(
        "SELECT * FROM execution_rounds WHERE task_id=? ORDER BY round", (task_id,)
    ):
        rounds.append(
            {
                "round": r["round"],
                "policy": json.loads(r["policy"]),
                "created": r["created"],
            }
        )
    return rounds


def _policy(conn, task_id):
    """The current (latest) round's policy; usage is always lifetime for the task."""
    latest = _rounds(conn, task_id)[-1]
    p = {**latest["policy"], "round": latest["round"]}
    if digest(_contract(get_task(task_id=task_id, conn=conn))) != p["contract_sha256"]:
        raise ValidationError(
            "Acceptance scope changed after execution limits were registered"
        )
    return p


def _source(p):
    return digest(source_manifest(Path(p["root"]), p["sources"]))


def _artifact(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
        raise ValidationError("Evidence must be a regular file <=20 MiB")
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(conn, task_id):
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM execution_attempts WHERE task_id=? ORDER BY started, token",
            (task_id,),
        )
    ]


def _usage(rows):
    return {
        "attempts": len(rows),
        "calls": sum(
            max(r["calls"], r["reserved_calls"])
            if r["state"] == "running"
            else r["calls"]
            for r in rows
        ),
        "micros": sum(
            max(r["micros"], r["reserved_micros"])
            if r["state"] == "running"
            else r["micros"]
            for r in rows
        ),
    }


def register_limits(
    *,
    task_id,
    attempts,
    calls,
    cost_usd,
    authority,
    root=None,
    timeout_seconds=900,
    stale_seconds=300,
    db_path=None,
):
    """Register once, or repeat byte-identical registration. No reset/raise API."""
    attempts = _integer(attempts, "attempts", 1)
    calls = _integer(calls, "calls")
    timeout_seconds = _integer(timeout_seconds, "timeout_seconds", 1)
    stale_seconds = _integer(stale_seconds, "stale_seconds", 1)
    if (
        not isinstance(authority, list)
        or not authority
        or any(not isinstance(a, str) or not a.strip() for a in authority)
    ):
        raise ValidationError(
            "Keep explicit authorization references in a nonempty list"
        )
    with _db(db_path) as conn:
        contract = _contract(get_task(task_id=task_id, conn=conn))
        from tc.services.qa_contract import database_path

        p = {
            "attempts": attempts,
            "calls": calls,
            "micros": _micros(cost_usd),
            "authority": authority,
            "root": str(Path(root or database_path(conn).parent.parent).resolve()),
            "sources": contract["sources"],
            "criteria": [c["id"] for c in contract["criteria"]],
            "contract_sha256": digest(contract),
            "timeout_seconds": timeout_seconds,
            "stale_seconds": stale_seconds,
        }
        _source(p)  # Invalid/missing source scopes fail before registration.
        old = conn.execute(
            "SELECT policy FROM execution_limits WHERE task_id=?", (task_id,)
        ).fetchone()
        if old and json.loads(old[0]) != p:
            raise ValidationError(
                "Execution limits are immutable; changing rounds cannot reset or expand them"
            )
        conn.execute(
            "INSERT OR IGNORE INTO execution_limits VALUES (?,?)",
            (task_id, json.dumps(p)),
        )
    return p


def succeed_limits(
    *,
    task_id,
    attempts,
    calls,
    cost_usd,
    authority,
    timeout_seconds=None,
    stale_seconds=None,
    db_path=None,
):
    """Open a successor round: lifetime caps may only rise, nothing is erased.

    Usage and failure history live per task, so every counter and checkpoint
    carries forward by construction. A diagnosis is a separate act and is not
    implied here. The new owner authority must differ from every earlier one.
    """
    attempts = _integer(attempts, "attempts", 1)
    calls = _integer(calls, "calls")
    micros = _micros(cost_usd)
    if (
        not isinstance(authority, list)
        or not authority
        or any(not isinstance(a, str) or not a.strip() for a in authority)
    ):
        raise ValidationError(
            "Keep explicit authorization references in a nonempty list"
        )
    with _db(db_path) as conn:
        rounds = _rounds(conn, task_id)  # Refuses when nothing is registered.
        previous = rounds[-1]
        prior = previous["policy"]
        timeout_seconds = _integer(
            prior["timeout_seconds"] if timeout_seconds is None else timeout_seconds,
            "timeout_seconds",
            1,
        )
        stale_seconds = _integer(
            prior["stale_seconds"] if stale_seconds is None else stale_seconds,
            "stale_seconds",
            1,
        )
        _policy(conn, task_id)  # Scope must still match the frozen contract.
        if any(r["state"] == "running" for r in _rows(conn, task_id)):
            raise ValidationError(
                "An attempt is unsettled; reconcile it before opening a successor"
            )
        known = {a for r in rounds for a in r["policy"]["authority"]}
        new = [a for a in dict.fromkeys(authority) if a not in known]
        if not new:
            raise ValidationError(
                "A successor requires a new explicit owner authority not already recorded"
            )
        used = _usage(_rows(conn, task_id))
        for name, value, floor in (
            ("attempts", attempts, max(used["attempts"], prior["attempts"])),
            ("calls", calls, max(used["calls"], prior["calls"])),
            ("micros", micros, max(used["micros"], prior["micros"])),
        ):
            if value < floor:
                raise ValidationError(
                    f"Successor {name} cap is below lifetime used or the predecessor cap; successors can only raise caps"
                )
        p = {
            **prior,
            "attempts": attempts,
            "calls": calls,
            "micros": micros,
            "authority": [*prior["authority"], *new],
            "new_authority": new,
            "timeout_seconds": timeout_seconds,
            "stale_seconds": stale_seconds,
            "predecessor": previous["round"],
        }
        number = previous["round"] + 1
        conn.execute(
            "INSERT INTO execution_rounds VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                number,
                json.dumps(p),
                previous["round"],
                previous["created"],
                time.time(),
                used["attempts"],
                used["calls"],
                used["micros"],
            ),
        )
    return {**p, "round": number}


def protect_update(conn, task_id, old_metadata, new_metadata, old_status, new_status):
    """Shared task API/CLI mutation guard. Legacy tasks remain compatible."""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_limits'"
    ).fetchone():
        return
    row = conn.execute(
        "SELECT policy FROM execution_limits WHERE task_id=?", (task_id,)
    ).fetchone()
    if not row:
        return
    if old_metadata.get("acceptanceContract") != new_metadata.get("acceptanceContract"):
        raise ValidationError(
            "Execution scope is frozen; acceptance contract cannot change after limits registration"
        )
    if old_status == "completed" and new_status not in (None, "completed"):
        from tc.services.qa import check_task_qa

        if check_task_qa(task_id=task_id, conn=conn)["approved"]:
            raise ValidationError(
                "Current QA still approves this task; do not reopen passing work"
            )
    if (
        new_status == "completed"
        and conn.execute(
            "SELECT 1 FROM execution_attempts WHERE task_id=? AND state='running'",
            (task_id,),
        ).fetchone()
    ):
        raise ValidationError(
            "Unsettled execution reservations prevent task completion"
        )


def begin_attempt(
    *, task_id, criterion, label, reserve_calls=0, reserve_usd=0, db_path=None
):
    reserve_calls = _integer(reserve_calls, "reserve_calls")
    reserve_micros = _micros(reserve_usd)
    if not isinstance(label, str) or not label.strip():
        raise ValidationError("Attempt label is required")
    with _db(db_path) as conn:
        p = _policy(conn, task_id)
        if criterion not in p["criteria"]:
            raise ValidationError(
                "Criterion is outside the registered acceptance scope"
            )
        task = get_task(task_id=task_id, conn=conn)
        if task["status"] in ("completed", "cancelled", "blocked"):
            raise ValidationError(f"Task is {task['status']}; execution not started")
        from tc.services.qa import check_task_qa

        if check_task_qa(task_id=task_id, conn=conn)["approved"]:
            raise ValidationError(
                "Current source-bound QA already passes; reuse the evidence"
            )
        rows = _rows(conn, task_id)
        used = _usage(rows)
        if any(r["state"] == "running" for r in rows):
            raise ValidationError(
                "An attempt is unsettled; reconcile it before starting another round"
            )
        if (
            used["attempts"] >= p["attempts"]
            or used["calls"] + reserve_calls > p["calls"]
            or used["micros"] + reserve_micros > p["micros"]
        ):
            raise ValidationError(
                "Cumulative task execution limit reached; no round reset is permitted"
            )
        source = _source(p)
        checkpoint = conn.execute(
            "SELECT * FROM execution_checkpoints WHERE task_id=? AND criterion=? AND kind='diagnosis' ORDER BY id DESC LIMIT 1",
            (task_id, criterion),
        ).fetchone()
        through = 0
        if (
            checkpoint
            and checkpoint["source"] == source
            and _artifact(checkpoint["artifact"])[1] == checkpoint["artifact_hash"]
        ):
            through = checkpoint["through_started"]
        failures = [
            r
            for r in rows
            if r["criterion"] == criterion
            and r["state"] in ("failed", "abandoned")
            and r["started"] > through
        ]
        if len(failures) >= 2:
            raise ValidationError(
                "Two failed attempts require changed source and a successful regression checkpoint before retry"
            )
        token = str(uuid4())
        conn.execute(
            "INSERT INTO execution_attempts(token,task_id,criterion,label,source,state,reserved_calls,reserved_micros,started) VALUES (?,?,?,?,?,'running',?,?,?)",
            (
                token,
                task_id,
                criterion,
                label,
                source,
                reserve_calls,
                reserve_micros,
                time.time(),
            ),
        )
    return {
        "token": token,
        "task_id": task_id,
        "criterion": criterion,
        "source": source,
        "timeout_seconds": p["timeout_seconds"],
        "authority": p["authority"],
    }


def _attempt(conn, token):
    row = conn.execute(
        "SELECT * FROM execution_attempts WHERE token=?", (token,)
    ).fetchone()
    if not row or row["state"] != "running":
        raise ValidationError("Attempt is absent or already settled")
    return dict(row)


def consume_call(*, token, db_path=None):
    """Atomic preflight: call before sending an external request, including retries."""
    with _db(db_path) as conn:
        r = _attempt(conn, token)
        p = _policy(conn, r["task_id"])
        if _source(p) != r["source"]:
            raise ValidationError("Source changed during the reserved attempt")
        if (
            r["calls"] >= r["reserved_calls"]
            or r["micros"] >= r["reserved_micros"]
            and r["reserved_micros"] > 0
        ):
            raise ValidationError("Attempt call or cost reservation exhausted")
        if time.time() - r["started"] > p["timeout_seconds"]:
            raise ValidationError("Attempt deadline exceeded")
        conn.execute(
            "UPDATE execution_attempts SET calls=calls+1 WHERE token=?", (token,)
        )
    return {"calls": r["calls"] + 1}


def settle_attempt(
    *, token, succeeded, artifact, calls=None, cost_usd=None, reason="", db_path=None
):
    """Retain full reserved usage when receipts are unavailable. Idempotency is refused."""
    if type(succeeded) is not bool:
        raise ValidationError("succeeded must be a boolean")
    path, sha = _artifact(artifact)
    with _db(db_path) as conn:
        r = _attempt(conn, token)
        p = _policy(conn, r["task_id"])
        count = r["reserved_calls"] if calls is None else _integer(calls, "calls")
        cost = r["reserved_micros"] if cost_usd is None else _micros(cost_usd)
        if count < r["calls"] or cost < r["micros"]:
            raise ValidationError("Receipts cannot reduce already observed usage")
        exceeded = count > r["reserved_calls"] or cost > r["reserved_micros"]
        state = "succeeded" if succeeded and not exceeded else "failed"
        conn.execute(
            "UPDATE execution_attempts SET state=?,calls=?,micros=?,ended=?,artifact=?,artifact_hash=?,end_source=?,reason=? WHERE token=?",
            (
                state,
                count,
                cost,
                time.time(),
                path,
                sha,
                _source(p),
                "reservation exceeded" if exceeded else reason,
                token,
            ),
        )
    return {
        "state": state,
        "calls": count,
        "cost_usd": cost / 1_000_000,
        "exceeded": exceeded,
    }


def diagnosis_checkpoint(*, task_id, criterion, regression, db_path=None):
    """A runner receipt must prove a successful regression on changed source.

    Never executes evidence text. This validates provenance/structure, not whether
    the test's assertions are adequate; QA still reviews test integrity.
    """
    path, sha = _artifact(regression)
    result = json.loads(Path(path).read_text())
    with _db(db_path) as conn:
        p = _policy(conn, task_id)
        source = _source(p)
        recorded = conn.execute(
            "SELECT 1 FROM execution_checkpoints WHERE task_id=? AND criterion=? AND kind='regression' AND source=? AND artifact=? AND artifact_hash=?",
            (task_id, criterion, source, path, sha),
        ).fetchone()
        if not recorded:
            raise ValidationError(
                "Regression must be recorded by tc execution prove on this source"
            )
        rows = [
            r
            for r in _rows(conn, task_id)
            if r["criterion"] == criterion and r["state"] in ("failed", "abandoned")
        ]
        if criterion not in p["criteria"] or not rows:
            raise ValidationError("No failed criterion to diagnose")
        if source == rows[-1]["source"]:
            raise ValidationError("Source is unchanged since the failed attempt")
        if (
            result.get("exit_code") != 0
            or result.get("task_id") != task_id
            or result.get("criterion") != criterion
            or result.get("source_before") != source
            or result.get("source_after") != source
            or not result.get("command")
        ):
            raise ValidationError(
                "Regression receipt must be successful and bound to this task, criterion and current source"
            )
        conn.execute(
            "INSERT INTO execution_checkpoints(task_id,criterion,kind,source,artifact,artifact_hash,created,through_started) VALUES (?,?,'diagnosis',?,?,?,?,?)",
            (task_id, criterion, source, path, sha, time.time(), rows[-1]["started"]),
        )
    return {"criterion": criterion, "source": source, "artifact_sha256": sha}


def has_limits(*, task_id, conn):
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_limits'"
    ).fetchone()
    return bool(
        table
        and conn.execute(
            "SELECT 1 FROM execution_limits WHERE task_id=?", (task_id,)
        ).fetchone()
    )


def snapshot(*, task_id, conn):
    """Read on the caller's connection so handoffs preserve transaction semantics."""
    p = _policy(conn, task_id)
    task = get_task(task_id=task_id, conn=conn)
    rows = _rows(conn, task_id)
    active = next((r for r in rows if r["state"] == "running"), None)
    state = "awaiting_result" if active else "idle"
    if active and time.time() - active["started"] > p["stale_seconds"]:
        state = "stale_progress"
    if task["status"] in ("completed", "cancelled", "blocked"):
        state = task["status"]
    usage = _usage(rows)
    rounds = _rounds(conn, task_id)
    lineage = [
        {
            "round": r["round"],
            "created": r["created"],
            "superseded": r["round"] < rounds[-1]["round"],
            "predecessor": r["policy"].get("predecessor"),
            "caps": {
                "attempts": r["policy"]["attempts"],
                "calls": r["policy"]["calls"],
                "cost_usd": r["policy"]["micros"] / 1_000_000,
            },
            "authority": r["policy"].get("new_authority", r["policy"]["authority"]),
        }
        for r in rounds
    ]
    blocker = None
    if not active and state == "idle":
        if (
            usage["attempts"] >= p["attempts"]
            or usage["calls"] > p["calls"]
            or usage["micros"] > p["micros"]
        ):
            state, blocker = "blocked", "cumulative_limit"
        else:
            source = _source(p)
            for criterion in p["criteria"]:
                checkpoint = conn.execute(
                    "SELECT * FROM execution_checkpoints WHERE task_id=? AND criterion=? AND kind='diagnosis' ORDER BY id DESC LIMIT 1",
                    (task_id, criterion),
                ).fetchone()
                through = 0
                if checkpoint and checkpoint["source"] == source:
                    try:
                        if (
                            _artifact(checkpoint["artifact"])[1]
                            == checkpoint["artifact_hash"]
                        ):
                            through = checkpoint["through_started"]
                    except OSError:
                        pass
                failures = [
                    r
                    for r in rows
                    if r["criterion"] == criterion
                    and r["state"] == "failed"
                    and r["started"] > through
                ]
                if len(failures) >= 2:
                    state, blocker = "blocked", f"diagnosis_required:{criterion}"
                    break
    from tc.services.qa import check_task_qa

    return {
        "task_id": task_id,
        "state": state,
        "blocker": blocker,
        "authority": p["authority"],
        "limits": p,
        "usage": {**usage, "cost_usd": usage["micros"] / 1_000_000},
        "remaining": {
            "attempts": p["attempts"] - usage["attempts"],
            "calls": p["calls"] - usage["calls"],
            "cost_usd": (p["micros"] - usage["micros"]) / 1_000_000,
        },
        "round": p["round"],
        "lineage": lineage,
        "attempts": rows,
        "qa_approved": False
        if active
        else check_task_qa(task_id=task_id, conn=conn)["approved"],
    }


def execution_status(*, task_id, db_path=None):
    with _db(db_path) as conn:
        return snapshot(task_id=task_id, conn=conn)


def record_regression(*, task_id, criterion, artifact, db_path=None):
    path, sha = _artifact(artifact)
    result = json.loads(Path(path).read_text())
    with _db(db_path) as conn:
        p = _policy(conn, task_id)
        source = _source(p)
        if (
            criterion not in p["criteria"]
            or result.get("exit_code") != 0
            or result.get("source_before") != source
            or result.get("source_after") != source
        ):
            raise ValidationError("Regression did not pass on stable current source")
        conn.execute(
            "INSERT INTO execution_checkpoints(task_id,criterion,kind,source,artifact,artifact_hash,created) VALUES (?,?,'regression',?,?,?,?)",
            (task_id, criterion, source, path, sha, time.time()),
        )
