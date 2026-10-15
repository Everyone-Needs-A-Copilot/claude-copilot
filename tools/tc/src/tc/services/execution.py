"""Persistent execution limits for local task runners (not a security sandbox).

Reservations are conservative: a crashed or unreported run retains its entire
allowance. Round labels and process restarts never reset task totals. QA remains
the authority for product acceptance; a successful command is not QA approval.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
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
    # Append-only project budget ledger. Spend is computed from attempts, never stored
    # as a mutable counter, so nothing here can be reset.
    """CREATE TABLE IF NOT EXISTS execution_budgets (
    project_key TEXT NOT NULL, round INTEGER NOT NULL,
    calls INTEGER NOT NULL, micros INTEGER NOT NULL,
    period TEXT NOT NULL DEFAULT 'lifetime', authority TEXT NOT NULL,
    created REAL NOT NULL, used_calls INTEGER NOT NULL, used_micros INTEGER NOT NULL,
    PRIMARY KEY (project_key, round))""",
)

DECISION = "DECISION NEEDED: "
DEFAULT_NO_PROGRESS_N = 3
DEFAULT_CEILING_ATTEMPTS = 50
DEFAULT_CEILING_SECONDS = 6 * 3600
RECONCILE_GRACE_SECONDS = 60
MIGRATION_AUTHORITY = "policy: five-rule consolidation, approved by Pablo 2026-10-15"
_SETTLED = ("succeeded", "failed", "abandoned")


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


def _authority_list(authority):
    if (
        not isinstance(authority, list)
        or not authority
        or any(not isinstance(a, str) or not a.strip() for a in authority)
    ):
        raise ValidationError(
            "Keep explicit authorization references in a nonempty list"
        )
    return authority


def _is_v2(policy):
    return policy.get("policy_version", 1) >= 2


def register_limits(
    *,
    task_id,
    attempts=None,
    calls=0,
    cost_usd=0,
    authority=None,
    root=None,
    timeout_seconds=900,
    stale_seconds=300,
    no_progress_n=None,
    ceiling_attempts=None,
    ceiling_seconds=None,
    db_path=None,
):
    """Register once, or repeat byte-identical registration. No reset/raise API.

    With ``attempts`` the legacy v1 policy (fixed attempt cap, per-task money) is
    registered. Without it the task gets policy v2: no fixed attempt cap, a
    no-progress stop, a runaway ceiling, and paid calls drawn from the project
    budget (see ``set_budget``).
    """
    timeout_seconds = _integer(timeout_seconds, "timeout_seconds", 1)
    stale_seconds = _integer(stale_seconds, "stale_seconds", 1)
    v2 = attempts is None
    if v2:
        if calls or _micros(cost_usd):
            raise ValidationError(
                "Policy v2 tasks draw paid calls from the project budget; "
                "use tc execution budget set instead of per-task money"
            )
        no_progress_n = _integer(
            DEFAULT_NO_PROGRESS_N if no_progress_n is None else no_progress_n,
            "no_progress_n",
            1,
        )
        ceiling_attempts = _integer(
            DEFAULT_CEILING_ATTEMPTS if ceiling_attempts is None else ceiling_attempts,
            "ceiling_attempts",
            1,
        )
        ceiling_seconds = _integer(
            DEFAULT_CEILING_SECONDS if ceiling_seconds is None else ceiling_seconds,
            "ceiling_seconds",
            1,
        )
        authority = _authority_list(authority or [MIGRATION_AUTHORITY])
    else:
        attempts = _integer(attempts, "attempts", 1)
        calls = _integer(calls, "calls")
        authority = _authority_list(authority)
    with _db(db_path) as conn:
        contract = _contract(get_task(task_id=task_id, conn=conn))
        from tc.services.qa_contract import database_path

        p = {
            "attempts": ceiling_attempts if v2 else attempts,
            "calls": 0 if v2 else calls,
            "micros": 0 if v2 else _micros(cost_usd),
            "authority": authority,
            "root": str(Path(root or database_path(conn).parent.parent).resolve()),
            "sources": contract["sources"],
            "criteria": [c["id"] for c in contract["criteria"]],
            "contract_sha256": digest(contract),
            "timeout_seconds": timeout_seconds,
            "stale_seconds": stale_seconds,
        }
        if v2:
            p.update(
                policy_version=2,
                no_progress_n=no_progress_n,
                ceiling_attempts=ceiling_attempts,
                ceiling_seconds=ceiling_seconds,
            )
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
        if _is_v2(prior):
            raise ValidationError(
                "Policy v2 task: raise paid limits with tc execution budget set "
                "and the runaway ceiling with tc execution reopen"
            )
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
                DECISION
                + "a successor requires a new explicit owner authority not already recorded"
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


# --- Policy v2: project budget, auto-reconcile, progress and ceiling -----------


def _project_key(root):
    return str(Path(root).resolve())


def _default_project(conn):
    from tc.services.qa_contract import database_path

    return _project_key(database_path(conn).parent.parent)


def _project_usage(conn, project):
    """Lifetime paid usage across every task whose current policy root is ``project``.

    Computed from attempts on each call (running attempts count their full
    reservation, exactly as ``_usage`` does), so there is no counter to reset.
    """
    total = {"calls": 0, "micros": 0}
    for (task_id,) in conn.execute("SELECT task_id FROM execution_limits").fetchall():
        if _rounds(conn, task_id)[-1]["policy"]["root"] != project:
            continue
        used = _usage(_rows(conn, task_id))
        total["calls"] += used["calls"]
        total["micros"] += used["micros"]
    return total


def _budget_rounds(conn, project):
    return [
        {**dict(r), "authority": json.loads(r["authority"])}
        for r in conn.execute(
            "SELECT * FROM execution_budgets WHERE project_key=? ORDER BY round",
            (project,),
        )
    ]


def _budget(conn, project):
    """Absent budget means zero paid budget; local work is unaffected."""
    rounds = _budget_rounds(conn, project)
    return (
        (rounds[-1]["calls"], rounds[-1]["micros"], rounds)
        if rounds
        else (0, 0, rounds)
    )


def _append_budget(conn, project, calls, micros, authority):
    rounds = _budget_rounds(conn, project)
    used = _project_usage(conn, project)
    conn.execute(
        "INSERT INTO execution_budgets VALUES (?,?,?,?,?,?,?,?,?)",
        (
            project,
            len(rounds) + 1,
            calls,
            micros,
            "lifetime",
            json.dumps(authority),
            time.time(),
            used["calls"],
            used["micros"],
        ),
    )
    return len(rounds) + 1


def _budget_view(conn, project):
    calls, micros, rounds = _budget(conn, project)
    used = _project_usage(conn, project)
    return {
        "project": project,
        "period": "lifetime",
        "round": len(rounds),
        "calls": calls,
        "cost_usd": micros / 1_000_000,
        "used_calls": used["calls"],
        "used_cost_usd": used["micros"] / 1_000_000,
        "remaining_calls": calls - used["calls"],
        "remaining_cost_usd": (micros - used["micros"]) / 1_000_000,
        "authority": [a for r in rounds for a in r["authority"]],
        "rounds": [
            {k: r[k] for k in ("round", "calls", "micros", "created", "authority")}
            for r in rounds
        ],
    }


def budget_status(*, project=None, db_path=None):
    with _db(db_path) as conn:
        return _budget_view(
            conn, _project_key(project) if project else _default_project(conn)
        )


def set_budget(*, project=None, calls, cost_usd, authority, db_path=None):
    """Append a lifetime budget round for a project. Only an owner quote raises money.

    The quote must be new, and neither figure may drop below the previous round
    or below lifetime spend, so nothing is reset or hidden.
    """
    calls = _integer(calls, "calls")
    micros = _micros(cost_usd)
    authority = _authority_list(authority)
    with _db(db_path) as conn:
        project = _project_key(project) if project else _default_project(conn)
        prev_calls, prev_micros, rounds = _budget(conn, project)
        known = {a for r in rounds for a in r["authority"]}
        new = [a for a in dict.fromkeys(authority) if a not in known]
        if not new:
            raise ValidationError(
                DECISION + "a budget round requires a new verbatim owner authority "
                "not already recorded"
            )
        used = _project_usage(conn, project)
        for name, value, floor in (
            ("calls", calls, max(used["calls"], prev_calls)),
            ("micros", micros, max(used["micros"], prev_micros)),
        ):
            if value < floor:
                raise ValidationError(
                    f"Budget {name} is below lifetime spend or the previous round; budgets can only rise"
                )
        _append_budget(conn, project, calls, micros, new)
        return _budget_view(conn, project)


def _reserve_within_budget(conn, p, task_id, reserve_calls, reserve_micros):
    if not (reserve_calls or reserve_micros):
        return
    project = p["root"]
    budget_calls, budget_micros, _ = _budget(conn, project)
    used = _project_usage(conn, project)
    over_calls = max(0, used["calls"] + reserve_calls - budget_calls)
    over_micros = max(0, used["micros"] + reserve_micros - budget_micros)
    if over_calls or over_micros:
        raise ValidationError(
            f"{DECISION}${over_micros / 1_000_000:.2f} over {Path(project).name} "
            f"budget for {over_calls} more paid calls (task {task_id} requested "
            f"{reserve_calls} calls / ${reserve_micros / 1_000_000:.2f}; project budget "
            f"{budget_calls} calls / ${budget_micros / 1_000_000:.2f}, used "
            f"{used['calls']} calls / ${used['micros'] / 1_000_000:.2f}). "
            "Set one with: tc execution budget set"
        )


def _reconcile(conn, task_id, p):
    """Settle timed-out attempts that never reserved or used anything paid.

    Paid or partially consumed attempts keep their lock and full reservation.
    """
    now = time.time()
    abandoned = []
    for r in _rows(conn, task_id):
        if (
            r["state"] == "running"
            and r["reserved_calls"] == 0
            and r["reserved_micros"] == 0
            and r["calls"] == 0
            and r["micros"] == 0
            and r["started"] + p["timeout_seconds"] + RECONCILE_GRACE_SECONDS < now
        ):
            conn.execute(
                "UPDATE execution_attempts SET state='abandoned', ended=?, reason=? WHERE token=? AND state='running'",
                (
                    r["started"] + p["timeout_seconds"],
                    "auto-reconciled: timed out, zero paid",
                    r["token"],
                ),
            )
            abandoned.append(r["token"])
    return abandoned


def _normalized_evidence(row):
    """Fingerprint of what an attempt observed, ignoring digits (timings, counts).

    A tc receipt points at its raw output; that output is what repeats when an
    attempt learns nothing. Other artifacts fall back to their own hash.
    """
    try:
        path = Path(row["artifact"])
        if path.stat().st_size <= 1024 * 1024:
            data = json.loads(path.read_text())
            out = Path(data["output"])
            if out.stat().st_size <= 1024 * 1024:
                text = re.sub(r"\d+", "#", out.read_text(errors="replace"))
                return hashlib.sha256(text.encode()).hexdigest()
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return row["artifact_hash"]


def _progress(conn, p, task_id, rows, source=None):
    """Machine-checkable progress for a v2 task.

    An attempt makes progress when it passes a criterion for the first time,
    produces evidence not yet seen for its criterion, or runs on source not yet
    tried for its criterion. A diagnosis checkpoint on the current source opens a
    fresh window. Returns the trailing non-progress streak and cumulative runtime.
    """
    settled = [r for r in rows if r["state"] in _SETTLED]
    seen_pass, seen_evidence, seen_source, flags = set(), {}, {}, []
    for r in settled:
        c = r["criterion"]
        progress = False
        if r["state"] == "succeeded" and c not in seen_pass:
            seen_pass.add(c)
            progress = True
        evidence = _normalized_evidence(r) if r["artifact"] else None
        if evidence and evidence not in seen_evidence.setdefault(c, set()):
            seen_evidence[c].add(evidence)
            progress = True
        tried = seen_source.setdefault(c, set())
        sources = {x for x in (r["source"], r["end_source"]) if x}
        if sources - tried:
            progress = True
        tried |= sources
        flags.append(progress)
    window_start = 0
    if source is not None:
        for cp in conn.execute(
            "SELECT * FROM execution_checkpoints WHERE task_id=? AND kind='diagnosis' AND source=?",
            (task_id, source),
        ):
            try:
                if _artifact(cp["artifact"])[1] == cp["artifact_hash"]:
                    window_start = max(window_start, cp["through_started"])
            except (OSError, ValidationError):
                continue
    streak = 0
    for r, progressed in zip(reversed(settled), reversed(flags)):
        if progressed or r["started"] <= window_start:
            break
        streak += 1
    now = time.time()
    runtime = sum(
        ((r["ended"] if r["ended"] is not None else now) - r["started"])
        if r["state"] != "running"
        else now - r["started"]
        for r in rows
    )
    return {
        "non_progress_streak": streak,
        "no_progress_n": p["no_progress_n"],
        "runtime_seconds": round(max(runtime, 0), 3),
        "ceiling_seconds": p["ceiling_seconds"],
        "attempts": len(rows),
        "ceiling_attempts": p["ceiling_attempts"],
    }


def _halt(conn, p, task_id, rows, source=None):
    """None, or (state, report) when a v2 task must stop and report."""
    prog = _progress(conn, p, task_id, rows, source)
    if (
        prog["attempts"] >= p["ceiling_attempts"]
        or prog["runtime_seconds"] >= p["ceiling_seconds"]
    ):
        return "ceiling_reached", (
            f"{DECISION}restart task {task_id} past its runaway ceiling "
            f"({prog['attempts']}/{p['ceiling_attempts']} attempts, "
            f"{prog['runtime_seconds']:.0f}/{p['ceiling_seconds']}s). "
            "STOPPED: ceiling_reached. Reply with a decision, then run: tc execution reopen"
        )
    if prog["non_progress_streak"] >= p["no_progress_n"]:
        last = next((r for r in reversed(rows) if r["state"] in _SETTLED), None)
        return "no_progress", (
            f"STOPPED: no_progress on task {task_id}: {prog['non_progress_streak']} "
            f"consecutive attempts with no newly passing criterion and no new evidence "
            f"(criteria {p['criteria']}, attempts used {prog['attempts']}, last evidence "
            f"{last['artifact'] if last else None}). Change the source, then record a "
            "diagnosis (tc execution prove, then diagnose) to reopen; no approval is needed."
        )
    return None


def reopen_ceiling(
    *, task_id, decision, ceiling_attempts=None, ceiling_seconds=None, db_path=None
):
    """Raise a runaway ceiling after Pablo's recorded decision. No money, no quote."""
    if not isinstance(decision, str) or not decision.strip():
        raise ValidationError("Record the owner decision that reopens the ceiling")
    with _db(db_path) as conn:
        rounds = _rounds(conn, task_id)
        previous = rounds[-1]
        prior = previous["policy"]
        if not _is_v2(prior):
            raise ValidationError("Only policy v2 tasks have a runaway ceiling")
        p = _policy(conn, task_id)
        if any(r["state"] == "running" for r in _rows(conn, task_id)):
            raise ValidationError(
                "An attempt is unsettled; reconcile it before reopening"
            )
        if decision in {d for r in rounds for d in r["policy"].get("decisions", [])}:
            raise ValidationError(
                DECISION + "reopening needs a new owner decision not already recorded"
            )
        rows = _rows(conn, task_id)
        used = _usage(rows)
        runtime = _progress(conn, p, task_id, rows)["runtime_seconds"]
        attempts_cap = _integer(
            max(prior["ceiling_attempts"], used["attempts"]) + DEFAULT_CEILING_ATTEMPTS
            if ceiling_attempts is None
            else ceiling_attempts,
            "ceiling_attempts",
            1,
        )
        seconds_cap = _integer(
            int(max(prior["ceiling_seconds"], runtime)) + DEFAULT_CEILING_SECONDS
            if ceiling_seconds is None
            else ceiling_seconds,
            "ceiling_seconds",
            1,
        )
        if attempts_cap < prior["ceiling_attempts"] or seconds_cap < prior["ceiling_seconds"]:
            raise ValidationError("Ceilings can only rise")
        np = {
            **prior,
            "attempts": attempts_cap,
            "ceiling_attempts": attempts_cap,
            "ceiling_seconds": seconds_cap,
            "decisions": [*prior.get("decisions", []), decision],
            "kind": "reopen",
            "new_authority": [],
            "predecessor": previous["round"],
        }
        number = previous["round"] + 1
        conn.execute(
            "INSERT INTO execution_rounds VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                number,
                json.dumps(np),
                previous["round"],
                previous["created"],
                time.time(),
                used["attempts"],
                used["calls"],
                used["micros"],
            ),
        )
    return {**np, "round": number}


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
        v2 = _is_v2(p)
        if v2:
            _reconcile(conn, task_id, p)
        rows = _rows(conn, task_id)
        used = _usage(rows)
        if any(r["state"] == "running" for r in rows):
            raise ValidationError(
                "An attempt is unsettled; reconcile it before starting another round"
            )
        source = _source(p)
        if v2:
            halted = _halt(conn, p, task_id, rows, source)
            if halted:
                # Persist the auto-reconcile above even though this call refuses.
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                raise ValidationError(halted[1])
            _reserve_within_budget(conn, p, task_id, reserve_calls, reserve_micros)
        elif (
            used["attempts"] >= p["attempts"]
            or used["calls"] + reserve_calls > p["calls"]
            or used["micros"] + reserve_micros > p["micros"]
        ):
            raise ValidationError(
                DECISION
                + "Cumulative task execution limit reached; no round reset is permitted"
            )
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


def _v1_state(p, rows, now):
    """Describe a v1 task before migration."""
    used = _usage(rows)
    if any(r["state"] == "running" for r in rows):
        return "running"
    if (
        used["attempts"] >= p["attempts"]
        or used["calls"] > p["calls"]
        or used["micros"] > p["micros"]
    ):
        return "exhausted"
    return "idle"


def _migrated_policy(prior):
    return {
        **prior,
        "policy_version": 2,
        "kind": "migration",
        "migration_authority": MIGRATION_AUTHORITY,
        "no_progress_n": DEFAULT_NO_PROGRESS_N,
        "ceiling_attempts": DEFAULT_CEILING_ATTEMPTS,
        "ceiling_seconds": DEFAULT_CEILING_SECONDS,
        # Older runtimes read this round as a plain attempts cap; caps and
        # authority are carried unchanged so they still enforce something sane.
        "attempts": DEFAULT_CEILING_ATTEMPTS,
        "new_authority": [],
    }


def migrate_ledgers(*, db_path=None, task_id=None, dry_run=False, backup=True):
    """Append one policy-v2 round per v1 task; never rewrite earlier history.

    Existing per-task money approvals (calls, dollars, verbatim quotes) seed the
    project budget instead of being discarded. Lifetime attempts, calls and spend
    carry forward, so a task already past the ceiling reports ``ceiling_reached``.
    Tasks holding a paid or unexpired running attempt are skipped and reported.
    """
    report = {"dry_run": dry_run, "tasks": [], "budgets": [], "backup": None}
    db_file = _require_db_path(db_path)
    if not dry_run and backup:
        # Copy before the first write; append-only rounds make this the rollback.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = Path(str(db_file) + f".pre-migrate-{stamp}.bak")
        if not target.exists():
            src = sqlite3.connect(str(db_file))
            dst = sqlite3.connect(str(target))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            target.chmod(0o600)
        report["backup"] = str(target)
    now = time.time()
    with _db(db_path) as conn:
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT task_id FROM execution_limits ORDER BY task_id"
            ).fetchall()
        ]
        if task_id is not None:
            if task_id not in ids:
                raise ValidationError(f"Task {task_id} has no registered execution limits")
            ids = [task_id]
        seeds = {}
        for tid in ids:
            rounds = _rounds(conn, tid)
            previous = rounds[-1]
            prior = previous["policy"]
            if _is_v2(prior):
                report["tasks"].append({"task_id": tid, "result": "already_v2"})
                continue
            rows = _rows(conn, tid)
            before = _v1_state(prior, rows, now)
            reconcilable = [
                r
                for r in rows
                if r["state"] == "running"
                and not (r["reserved_calls"] or r["reserved_micros"] or r["calls"] or r["micros"])
                and r["started"] + prior["timeout_seconds"] + RECONCILE_GRACE_SECONDS < now
            ]
            running = [r for r in rows if r["state"] == "running"]
            entry = {"task_id": tid, "prior_state": before, "attempts": len(rows)}
            if running and len(reconcilable) != len(running):
                entry["result"] = "skipped_running_attempt"
                report["tasks"].append(entry)
                continue
            p2 = _migrated_policy(prior)
            if not dry_run:
                if reconcilable:
                    _reconcile(conn, tid, {**p2})
                    rows = _rows(conn, tid)
                number = previous["round"] + 1
                used = _usage(rows)
                conn.execute(
                    "INSERT INTO execution_rounds VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        tid,
                        number,
                        json.dumps({**p2, "predecessor": previous["round"]}),
                        previous["round"],
                        previous["created"],
                        now,
                        used["attempts"],
                        used["calls"],
                        used["micros"],
                    ),
                )
                entry["round"] = number
            else:
                rows = [
                    {**r, "state": "abandoned"} if r in reconcilable else r for r in rows
                ]
            # Resulting state under v2 rules, evaluated on the would-be policy.
            try:
                source = _source(p2)
            except (ValidationError, OSError):
                source = None
            halted = _halt(conn, {**p2, "criteria": p2["criteria"]}, tid, rows, source)
            entry["result"] = "migrated" if not dry_run else "would_migrate"
            entry["resulting_state"] = halted[0] if halted else "idle"
            entry["reconciled"] = len(reconcilable)
            report["tasks"].append(entry)
            seed = seeds.setdefault(
                prior["root"], {"calls": 0, "micros": 0, "authority": [], "tasks": []}
            )
            seed["calls"] += prior["calls"]
            seed["micros"] += prior["micros"]
            seed["authority"].extend(prior["authority"] if (prior["calls"] or prior["micros"]) else [])
            seed["tasks"].append(tid)
        for project, seed in seeds.items():
            prev_calls, prev_micros, _ = _budget(conn, project)
            view = {
                "project": project,
                "from_tasks": seed["tasks"],
                "add_calls": seed["calls"],
                "add_cost_usd": seed["micros"] / 1_000_000,
            }
            if seed["calls"] or seed["micros"]:
                if not dry_run:
                    quotes = list(dict.fromkeys(seed["authority"]))
                    _append_budget(
                        conn,
                        project,
                        prev_calls + seed["calls"],
                        prev_micros + seed["micros"],
                        [MIGRATION_AUTHORITY, *quotes],
                    )
                view["new_budget_calls"] = prev_calls + seed["calls"]
                view["new_budget_cost_usd"] = (prev_micros + seed["micros"]) / 1_000_000
            report["budgets"].append(view)
        if dry_run:
            conn.rollback()  # Dry run leaves the database byte-for-byte untouched.
    return report


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
            "kind": r["policy"].get("kind", "registration" if r["round"] == 1 else "successor"),
            "decision": r["policy"].get("decisions", [])[-1:] if r["policy"].get("kind") == "reopen" else [],
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
    v2 = _is_v2(p)
    source = None
    if not active and state == "idle":
        halted = None
        if v2:
            source = _source(p)
            halted = _halt(conn, p, task_id, rows, source)
        if halted:
            state = blocker = halted[0]
        elif not v2 and (
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
                    and r["state"] in ("failed", "abandoned")
                    and r["started"] > through
                ]
                if len(failures) >= 2:
                    state, blocker = "blocked", f"diagnosis_required:{criterion}"
                    break
    from tc.services.qa import check_task_qa

    if v2:
        budget = _budget_view(conn, p["root"])
        remaining = {
            "attempts": p["ceiling_attempts"] - usage["attempts"],
            "calls": budget["remaining_calls"],
            "cost_usd": budget["remaining_cost_usd"],
        }
        extra = {
            "budget": budget,
            "progress": _progress(
                conn, p, task_id, rows, source if source else _source(p)
            ),
        }
    else:
        remaining = {
            "attempts": p["attempts"] - usage["attempts"],
            "calls": p["calls"] - usage["calls"],
            "cost_usd": (p["micros"] - usage["micros"]) / 1_000_000,
        }
        extra = {}
    return {
        **extra,
        "task_id": task_id,
        "state": state,
        "blocker": blocker,
        "authority": p["authority"],
        "limits": p,
        "usage": {**usage, "cost_usd": usage["micros"] / 1_000_000},
        "remaining": remaining,
        "round": p["round"],
        "lineage": lineage,
        "attempts": rows,
        "qa_approved": False
        if active
        else check_task_qa(task_id=task_id, conn=conn)["approved"],
    }


def execution_status(*, task_id, db_path=None):
    with _db(db_path) as conn:
        p = _policy(conn, task_id)
        if _is_v2(p):
            _reconcile(conn, task_id, p)
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
