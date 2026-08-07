"""Private, expiring, single-use reconciliation plan capabilities.

``issue_plan`` persists the exact reviewed plan behind a random opaque id.
``claim_plan`` atomically binds that id to the request and a freshly recomputed
plan fingerprint and transitions it to ``applying``. ``finish_plan`` consumes
the claim on every terminal outcome.  A plan is therefore neither a reusable
state hash nor an authority that survives changed inspection evidence.

The optional ``root`` parameter is an isolation seam for tests. Production
callers omit it and receive mode-0700 state under ``~/.claude/cc``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping, Optional, Sequence

from cc.core.config_paths import machine_diagnostics_root
from cc.core.ecosystem.project_locking import (
    ProjectLockError,
    advisory_file_lock,
    atomic_json_write,
    ensure_private_directory,
)

_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLAN_ID = re.compile(r"^plan_[0-9a-f]{32}$")
_RUN_ID = re.compile(r"^run_[0-9a-f]{32}$")
_OUTCOMES = {"applied", "partial", "blocked"}
_RECOVERY_OUTCOMES = {"applied", "rolled-back", "blocked", "incomplete-rollback"}
_INTENT_STATES = {
    "claiming",
    "applying",
    "outcome-recorded",
    "recovered-projects",
    "finalized",
    "abandoned",
}
_INTENT_TERMINAL = {"abandoned", "finalized"}


class PlanStoreError(RuntimeError):
    """Base class for safe plan refusal."""


class PlanNotFound(PlanStoreError):
    pass


class PlanExpired(PlanStoreError):
    pass


class PlanBindingMismatch(PlanStoreError):
    pass


class PlanAlreadyUsed(PlanStoreError):
    pass


@dataclass(frozen=True)
class PlanRecord:
    plan_id: str
    state: str
    request_fingerprint: str
    fresh_plan_fingerprint: str
    binding_fingerprint: str
    helper_version: str
    schema_version: str
    created_at: str
    expires_at: str
    plans: tuple[dict[str, Any], ...]
    canonical_request: dict[str, Any]
    outcome: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass(frozen=True)
class PlanClaim:
    plan_id: str
    claim_token: str
    request_fingerprint: str
    fresh_plan_fingerprint: str
    binding_fingerprint: str
    plans: tuple[dict[str, Any], ...]
    run_id: str


@dataclass(frozen=True)
class RecoveryContext:
    run_id: str
    plan_id: str
    plan_state: str
    state: str
    owner_pid: int
    owner_start_token: str
    owner_live: bool
    project_paths: tuple[str, ...]
    request_fingerprint: str
    fresh_plan_fingerprint: str
    binding_fingerprint: str
    helper_version: str
    schema_version: str
    canonical_request: dict[str, Any]
    plans: tuple[dict[str, Any], ...]
    outcome: Optional[str]
    ledger: tuple[dict[str, Any], ...]


def _now(value: Optional[datetime]) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_fingerprint(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise PlanBindingMismatch(f"{field} is not a reconciliation fingerprint.")


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_request(value: Mapping[str, Any]) -> dict[str, Any]:
    from cc.core.ecosystem.reconciliation_types import (
        canonical_request_json,
        parse_reconciliation_request,
    )

    try:
        request = parse_reconciliation_request(dict(value))
        canonical = json.loads(canonical_request_json(request))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PlanBindingMismatch(
            "The stored reconciliation request is invalid."
        ) from exc
    if not isinstance(canonical, dict):
        raise PlanBindingMismatch("The stored reconciliation request is invalid.")
    return canonical


def _state_root(root: Optional[Path]) -> Path:
    return (root or (machine_diagnostics_root() / "reconciliation")).expanduser()


def _plans_dir(root: Optional[Path]) -> Path:
    state = _state_root(root)
    directory = state / "plans"
    boundary = state if root is not None else machine_diagnostics_root()
    ensure_private_directory(directory, boundary=boundary)
    return directory


def _runs_dir(root: Optional[Path]) -> Path:
    state = _state_root(root)
    directory = state / "runs"
    boundary = state if root is not None else machine_diagnostics_root()
    ensure_private_directory(directory, boundary=boundary)
    return directory


def _canonical_plans(plans: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    if isinstance(plans, (str, bytes)) or not isinstance(plans, Sequence):
        raise PlanStoreError("A plan must contain a sequence of project plans.")
    try:
        encoded = json.dumps(list(plans), sort_keys=True, ensure_ascii=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PlanStoreError("The reviewed plan is not JSON-compatible.") from exc
    if len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
        raise PlanStoreError("The reviewed plan is too large to store safely.")
    if not isinstance(decoded, list) or any(
        not isinstance(item, dict) for item in decoded
    ):
        raise PlanStoreError("Every stored project plan must be an object.")
    return tuple(decoded)


def _canonical_ledger(
    ledger: Sequence[Mapping[str, Any]], project_paths: Sequence[str]
) -> tuple[dict[str, Any], ...]:
    from cc.core.ecosystem.reconciliation_diagnostics import safe_project_receipt

    if isinstance(ledger, (str, bytes)) or not isinstance(ledger, Sequence):
        raise PlanStoreError("A reconciliation ledger must be a sequence.")
    try:
        safe = [safe_project_receipt(item) for item in ledger]
    except (TypeError, ValueError, RuntimeError) as exc:
        raise PlanStoreError("The reconciliation ledger is invalid.") from exc
    for item in safe:
        item.pop("evidence", None)
    paths = [str(item["path"]) for item in safe]
    if paths != list(project_paths) or len(paths) != len(set(paths)):
        raise PlanStoreError(
            "The reconciliation ledger does not match its reviewed projects."
        )
    return tuple(safe)


def _binding(
    request_fingerprint: str,
    fresh_plan_fingerprint: str,
    helper_version: str,
    schema_version: str,
) -> str:
    payload = json.dumps(
        {
            "request_fingerprint": request_fingerprint,
            "fresh_plan_fingerprint": fresh_plan_fingerprint,
            "helper_version": helper_version,
            "schema_version": schema_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _record_path(plan_id: str, root: Optional[Path]) -> Path:
    if not _PLAN_ID.fullmatch(plan_id):
        raise PlanNotFound("The requested reconciliation plan does not exist.")
    return _plans_dir(root) / f"{plan_id}.json"


def _intent_path(run_id: str, root: Optional[Path]) -> Path:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise PlanBindingMismatch("The reconciliation run identifier is invalid.")
    return _runs_dir(root) / f"{run_id}.json"


def _project_paths(raw: Mapping[str, Any]) -> tuple[str, ...]:
    paths = tuple(
        item.get("path") for item in raw.get("plans", ()) if isinstance(item, Mapping)
    )
    if (
        len(paths) != len(raw.get("plans", ()))
        or any(not isinstance(path, str) or not path.startswith("/") for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise PlanNotFound("The reviewed reconciliation plan is invalid.")
    return tuple(str(path) for path in paths)


def _load(path: Path) -> dict[str, Any]:
    try:
        path.lstat()
    except OSError as exc:
        raise PlanNotFound("The requested reconciliation plan is unavailable.") from exc
    if path.is_symlink() or not path.is_file():
        raise PlanNotFound("The requested reconciliation plan is unavailable.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PlanNotFound("The requested reconciliation plan is unavailable.") from exc
    if not isinstance(raw, dict):
        raise PlanNotFound("The requested reconciliation plan is invalid.")
    return raw


def _validated_plan(raw: Mapping[str, Any]) -> dict[str, Any]:
    try:
        canonical_request = _canonical_request(raw["canonical_request"])
        plans = _canonical_plans(raw["plans"])
        request_fingerprint = str(raw["request_fingerprint"])
        fresh_plan_fingerprint = str(raw["fresh_plan_fingerprint"])
        helper_version = str(raw["helper_version"])
        schema_version = str(raw["schema_version"])
    except (KeyError, TypeError, PlanStoreError) as exc:
        raise PlanNotFound("The reviewed reconciliation plan is invalid.") from exc
    _validate_fingerprint(request_fingerprint, field="request_fingerprint")
    _validate_fingerprint(fresh_plan_fingerprint, field="fresh_plan_fingerprint")
    if (
        _fingerprint(canonical_request) != request_fingerprint
        or raw.get("binding_fingerprint")
        != _binding(
            request_fingerprint,
            fresh_plan_fingerprint,
            helper_version,
            schema_version,
        )
        or not helper_version
        or not schema_version
    ):
        raise PlanBindingMismatch(
            "The reviewed reconciliation plan binding is invalid."
        )
    requested_paths = [item["path"] for item in canonical_request.get("projects", [])]
    plan_paths = [item.get("path") for item in plans]
    if plan_paths != requested_paths or len(plan_paths) != len(set(plan_paths)):
        raise PlanBindingMismatch(
            "The reviewed reconciliation projects do not match their request."
        )
    return {**dict(raw), "canonical_request": canonical_request, "plans": list(plans)}


def _process_start_token(pid: int) -> str:
    try:
        result = subprocess.run(
            ("/bin/ps", "-o", "lstart=", "-p", str(pid)),
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    value = result.stdout.strip() if result.returncode == 0 else ""
    return _fingerprint({"pid": pid, "started": value}) if value else ""


def _owner_live(value: Any, start_token: Any) -> bool:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if not isinstance(start_token, str) or not start_token:
        return True
    current_token = _process_start_token(value)
    if not current_token:
        return True
    return secrets.compare_digest(current_token, start_token)


def _validated_intent(
    intent: Mapping[str, Any], plan: Mapping[str, Any]
) -> dict[str, Any]:
    state = intent.get("state")
    run_id = intent.get("run_id")
    plan_id = intent.get("plan_id")
    if (
        state not in _INTENT_STATES
        or not isinstance(run_id, str)
        or not _RUN_ID.fullmatch(run_id)
        or plan_id != plan.get("plan_id")
        or intent.get("binding_fingerprint") != plan.get("binding_fingerprint")
        or intent.get("request_fingerprint") != plan.get("request_fingerprint")
        or intent.get("fresh_plan_fingerprint") != plan.get("fresh_plan_fingerprint")
        or intent.get("helper_version") != plan.get("helper_version")
        or intent.get("schema_version") != plan.get("schema_version")
        or not isinstance(intent.get("owner_start_token"), str)
        or (
            intent.get("owner_pid") != 0
            and not _FINGERPRINT.fullmatch(str(intent.get("owner_start_token")))
        )
    ):
        raise PlanBindingMismatch("The reconciliation run intent binding is invalid.")
    canonical_request = _canonical_request(intent.get("canonical_request", {}))
    plans = _canonical_plans(intent.get("plans", ()))
    if (
        canonical_request != plan.get("canonical_request")
        or list(plans) != plan.get("plans")
        or _fingerprint(canonical_request) != intent.get("request_fingerprint")
    ):
        raise PlanBindingMismatch("The reconciliation run intent authority changed.")
    project_paths = intent.get("project_paths")
    expected_paths = _project_paths(plan)
    if not isinstance(project_paths, list) or tuple(project_paths) != expected_paths:
        raise PlanBindingMismatch("The reconciliation run projects are invalid.")
    result = {
        **dict(intent),
        "canonical_request": canonical_request,
        "plans": list(plans),
    }
    raw_ledger = intent.get("ledger", [])
    if state in {
        "outcome-recorded",
        "recovered-projects",
        "finalized",
        "abandoned",
    }:
        result["ledger"] = list(_canonical_ledger(raw_ledger, expected_paths))
    elif raw_ledger not in (None, []):
        raise PlanBindingMismatch("The reconciliation run ledger is premature.")
    return result


def _public_record(raw: Mapping[str, Any]) -> PlanRecord:
    return PlanRecord(
        plan_id=str(raw["plan_id"]),
        state=str(raw["state"]),
        request_fingerprint=str(raw["request_fingerprint"]),
        fresh_plan_fingerprint=str(raw["fresh_plan_fingerprint"]),
        binding_fingerprint=str(raw["binding_fingerprint"]),
        helper_version=str(raw["helper_version"]),
        schema_version=str(raw["schema_version"]),
        created_at=str(raw["created_at"]),
        expires_at=str(raw["expires_at"]),
        plans=tuple(dict(item) for item in raw.get("plans", [])),
        canonical_request=dict(raw["canonical_request"]),
        outcome=str(raw["outcome"]) if raw.get("outcome") is not None else None,
        finished_at=(
            str(raw["finished_at"]) if raw.get("finished_at") is not None else None
        ),
    )


def issue_plan(
    request_fingerprint: str,
    fresh_plan_fingerprint: str,
    plans: Sequence[Mapping[str, Any]],
    *,
    canonical_request: Mapping[str, Any],
    helper_version: str,
    schema_version: str,
    ttl_seconds: int = 900,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> PlanRecord:
    """Persist a new random reviewed capability bound to exact fresh evidence."""
    _validate_fingerprint(request_fingerprint, field="request_fingerprint")
    _validate_fingerprint(fresh_plan_fingerprint, field="fresh_plan_fingerprint")
    if not helper_version or not schema_version:
        raise PlanStoreError("Helper and schema versions are required plan bindings.")
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0 or ttl_seconds > 86400:
        raise PlanStoreError("Plan lifetime must be between 1 and 86400 seconds.")
    stored_plans = _canonical_plans(plans)
    stored_request = _canonical_request(canonical_request)
    if _fingerprint(stored_request) != request_fingerprint:
        raise PlanBindingMismatch(
            "The canonical request does not match its reconciliation fingerprint."
        )
    created = _now(now)
    plan_id = f"plan_{secrets.token_hex(16)}"
    raw: dict[str, Any] = {
        "storage_schema_version": "1.0",
        "plan_id": plan_id,
        "state": "reviewed",
        "request_fingerprint": request_fingerprint,
        "fresh_plan_fingerprint": fresh_plan_fingerprint,
        "binding_fingerprint": _binding(
            request_fingerprint,
            fresh_plan_fingerprint,
            helper_version,
            schema_version,
        ),
        "helper_version": helper_version,
        "schema_version": schema_version,
        "created_at": _timestamp(created),
        "expires_at": _timestamp(created + timedelta(seconds=ttl_seconds)),
        "plans": list(stored_plans),
        "canonical_request": stored_request,
        "claim_token_hash": None,
        "outcome": None,
        "finished_at": None,
    }
    validated = _validated_plan(raw)
    atomic_json_write(_record_path(plan_id, root), validated)
    return _public_record(validated)


def claim_plan(
    plan_id: str,
    request_fingerprint: str,
    fresh_plan_fingerprint: str,
    *,
    run_id: str,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> PlanClaim:
    """Atomically claim a still-fresh plan after recomputing its exact binding."""
    _validate_fingerprint(request_fingerprint, field="request_fingerprint")
    _validate_fingerprint(fresh_plan_fingerprint, field="fresh_plan_fingerprint")
    intent_path = _intent_path(run_id, root)
    path = _record_path(plan_id, root)
    lock_path = _plans_dir(root) / ".store.lock"
    with advisory_file_lock(lock_path):
        raw = _validated_plan(_load(path))
        if raw.get("state") != "reviewed":
            raise PlanAlreadyUsed("The reconciliation plan has already been claimed.")
        if _now(now) >= _parse_timestamp(str(raw.get("expires_at", ""))):
            raw["state"] = "expired"
            atomic_json_write(path, raw)
            raise PlanExpired("The reconciliation plan expired before apply.")
        if (
            raw.get("request_fingerprint") != request_fingerprint
            or raw.get("fresh_plan_fingerprint") != fresh_plan_fingerprint
        ):
            raise PlanBindingMismatch(
                "The reconciliation plan is stale or belongs to another request."
            )
        if intent_path.exists():
            raise PlanAlreadyUsed("The reconciliation run identifier was already used.")
        claimed_at = _timestamp(_now(now))
        owner_pid = os.getpid()
        owner_start_token = _process_start_token(owner_pid)
        if not owner_start_token:
            raise PlanStoreError(
                "The reconciliation process identity could not be persisted."
            )
        intent: dict[str, Any] = {
            "storage_schema_version": "1.0",
            "run_id": run_id,
            "plan_id": plan_id,
            "state": "claiming",
            "request_fingerprint": request_fingerprint,
            "fresh_plan_fingerprint": fresh_plan_fingerprint,
            "binding_fingerprint": str(raw["binding_fingerprint"]),
            "helper_version": str(raw["helper_version"]),
            "schema_version": str(raw["schema_version"]),
            "canonical_request": dict(raw["canonical_request"]),
            "plans": list(raw["plans"]),
            "project_paths": list(_project_paths(raw)),
            "owner_pid": owner_pid,
            "owner_start_token": owner_start_token,
            "created_at": claimed_at,
            "finished_at": None,
            "outcome": None,
            "ledger": [],
        }
        atomic_json_write(intent_path, intent)
        token = secrets.token_hex(32)
        raw["state"] = "applying"
        raw["run_id"] = run_id
        raw["claim_token_hash"] = hashlib.sha256(token.encode("ascii")).hexdigest()
        raw["claimed_at"] = claimed_at
        atomic_json_write(path, raw)
        intent["state"] = "applying"
        atomic_json_write(intent_path, intent)
        return PlanClaim(
            plan_id=plan_id,
            claim_token=token,
            request_fingerprint=request_fingerprint,
            fresh_plan_fingerprint=fresh_plan_fingerprint,
            binding_fingerprint=str(raw["binding_fingerprint"]),
            plans=tuple(dict(item) for item in raw["plans"]),
            run_id=run_id,
        )


def finish_plan(
    plan_id: str,
    claim_token: str,
    outcome: Literal["applied", "partial", "blocked"],
    *,
    ledger: Sequence[Mapping[str, Any]],
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> PlanRecord:
    """Consume plan authority while leaving its run pending for diagnostics."""
    if outcome not in _OUTCOMES:
        raise PlanStoreError("The plan outcome is not a terminal reconciliation state.")
    if not isinstance(claim_token, str) or not claim_token:
        raise PlanBindingMismatch("The plan claim token is missing.")
    path = _record_path(plan_id, root)
    lock_path = _plans_dir(root) / ".store.lock"
    with advisory_file_lock(lock_path):
        raw = _validated_plan(_load(path))
        if raw.get("state") != "applying":
            raise PlanAlreadyUsed("The reconciliation plan is not an active claim.")
        actual_hash = hashlib.sha256(claim_token.encode("ascii")).hexdigest()
        expected_hash = str(raw.get("claim_token_hash") or "")
        if not secrets.compare_digest(actual_hash, expected_hash):
            raise PlanBindingMismatch("The plan claim token does not match.")
        run_id = raw.get("run_id")
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise PlanBindingMismatch(
                "The reconciliation plan has no valid run intent."
            )
        intent_path = _intent_path(run_id, root)
        intent = _validated_intent(_load(intent_path), raw)
        if intent.get("state") not in {"claiming", "applying"}:
            raise PlanBindingMismatch(
                "The reconciliation run intent does not match its plan."
            )
        safe_ledger = _canonical_ledger(ledger, _project_paths(raw))
        recorded_at = _timestamp(_now(now))
        intent["state"] = (
            "recovered-projects"
            if any(item["status"] == "incomplete-rollback" for item in safe_ledger)
            else "outcome-recorded"
        )
        intent["outcome"] = outcome
        intent["ledger"] = list(safe_ledger)
        intent["outcome_recorded_at"] = recorded_at
        atomic_json_write(intent_path, intent)
        raw["state"] = "consumed"
        raw["outcome"] = outcome
        raw["finished_at"] = recorded_at
        raw["claim_token_hash"] = None
        atomic_json_write(path, raw)
        return _public_record(raw)


def incomplete_run_ids(*, root: Optional[Path] = None) -> tuple[str, ...]:
    """List every run that has not reached diagnostic-backed finalization."""
    result: list[str] = []
    for path in sorted(_runs_dir(root).glob("run_*.json")):
        if path.is_symlink() or not path.is_file():
            raise PlanNotFound("A reconciliation run intent is unavailable.")
        raw = _load(path)
        run_id = raw.get("run_id")
        if not isinstance(run_id, str) or path.name != f"{run_id}.json":
            raise PlanNotFound("A reconciliation run intent is invalid.")
        plan_id = raw.get("plan_id")
        if not isinstance(plan_id, str) or not _PLAN_ID.fullmatch(plan_id):
            raise PlanNotFound("A reconciliation run intent is invalid.")
        plan = _validated_plan(_load(_record_path(plan_id, root)))
        intent = _validated_intent(raw, plan)
        if intent.get("state") not in _INTENT_TERMINAL:
            result.append(run_id)
    return tuple(result)


@contextmanager
def recovery_lock(*, root: Optional[Path] = None) -> Iterator[None]:
    """Serialize explicit recovery scans without racing another recovery."""
    state = _state_root(root)
    boundary = state if root is not None else machine_diagnostics_root()
    ensure_private_directory(state, boundary=boundary)
    with advisory_file_lock(state / ".recovery.lock"):
        yield


def load_recovery_context(
    run_id: str,
    *,
    root: Optional[Path] = None,
) -> RecoveryContext:
    """Load immutable recovery authority without mutating projects or plans."""
    intent_path = _intent_path(run_id, root)
    lock_path = _plans_dir(root) / ".store.lock"
    with advisory_file_lock(lock_path):
        intent = _load(intent_path)
        plan_id = str(intent.get("plan_id"))
        if not _PLAN_ID.fullmatch(plan_id):
            raise PlanNotFound("The interrupted reconciliation plan is invalid.")
        plan_path = _record_path(plan_id, root)
        plan = _validated_plan(_load(plan_path))
        validated = _validated_intent(intent, plan)
        owner_pid = validated.get("owner_pid")
        return RecoveryContext(
            run_id=run_id,
            plan_id=plan_id,
            plan_state=str(plan.get("state")),
            state=str(validated["state"]),
            owner_pid=(
                owner_pid
                if isinstance(owner_pid, int) and not isinstance(owner_pid, bool)
                else 0
            ),
            owner_start_token=str(validated.get("owner_start_token") or ""),
            owner_live=_owner_live(owner_pid, validated.get("owner_start_token")),
            project_paths=tuple(validated["project_paths"]),
            request_fingerprint=str(validated["request_fingerprint"]),
            fresh_plan_fingerprint=str(validated["fresh_plan_fingerprint"]),
            binding_fingerprint=str(validated["binding_fingerprint"]),
            helper_version=str(validated["helper_version"]),
            schema_version=str(validated["schema_version"]),
            canonical_request=dict(validated["canonical_request"]),
            plans=tuple(dict(item) for item in validated["plans"]),
            outcome=(
                str(validated["outcome"])
                if validated.get("outcome") is not None
                else None
            ),
            ledger=tuple(dict(item) for item in validated.get("ledger", [])),
        )


def record_recovered_projects(
    run_id: str,
    outcome: Literal["applied", "rolled-back", "blocked", "incomplete-rollback"],
    ledger: Sequence[Mapping[str, Any]],
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> RecoveryContext:
    """Persist complete rollback-only recovery truth without finalizing the run."""
    if outcome not in _RECOVERY_OUTCOMES:
        raise PlanStoreError("The recovered transaction outcome is invalid.")
    intent_path = _intent_path(run_id, root)
    lock_path = _plans_dir(root) / ".store.lock"
    with advisory_file_lock(lock_path):
        intent = _load(intent_path)
        plan_id = str(intent.get("plan_id"))
        plan_path = _record_path(plan_id, root)
        plan = _validated_plan(_load(plan_path))
        validated = _validated_intent(intent, plan)
        if _owner_live(validated.get("owner_pid"), validated.get("owner_start_token")):
            raise PlanAlreadyUsed(
                "The reconciliation run is still owned by a live process."
            )
        if validated.get("state") not in {
            "claiming",
            "applying",
            "outcome-recorded",
            "recovered-projects",
        }:
            raise PlanAlreadyUsed("The reconciliation run cannot be recovered.")
        safe_ledger = _canonical_ledger(ledger, _project_paths(plan))
        recorded_at = _timestamp(_now(now))
        validated["state"] = (
            "recovered-projects"
            if outcome == "incomplete-rollback"
            else "outcome-recorded"
        )
        validated["outcome"] = outcome
        validated["ledger"] = list(safe_ledger)
        validated["outcome_recorded_at"] = recorded_at
        atomic_json_write(intent_path, validated)
        plan["state"] = "consumed"
        plan["outcome"] = outcome
        plan["finished_at"] = recorded_at
        plan["claim_token_hash"] = None
        atomic_json_write(plan_path, plan)
    return load_recovery_context(run_id, root=root)


def abandon_preclaim_run(
    run_id: str,
    *,
    ledger: Sequence[Mapping[str, Any]],
    diagnostic_id: str,
    diagnostic_state: str,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> RecoveryContext:
    """Abandon a true preclaim intent only after its bound record is durable."""
    if diagnostic_id != run_id or diagnostic_state != "available":
        raise PlanBindingMismatch(
            "A preclaim abandonment requires an available final diagnostic."
        )
    context = load_recovery_context(run_id, root=root)
    if context.state != "claiming" or context.plan_state != "reviewed":
        raise PlanAlreadyUsed("The reconciliation run passed its preclaim boundary.")
    safe_abandonment_ledger = _canonical_ledger(ledger, context.project_paths)
    _validated_final_diagnostic(
        context,
        root=root,
        expected_ledger=safe_abandonment_ledger,
    )
    intent_path = _intent_path(run_id, root)
    lock_path = _plans_dir(root) / ".store.lock"
    with advisory_file_lock(lock_path):
        intent = _load(intent_path)
        plan_id = str(intent.get("plan_id"))
        plan_path = _record_path(plan_id, root)
        plan = _validated_plan(_load(plan_path))
        validated = _validated_intent(intent, plan)
        if _owner_live(validated.get("owner_pid"), validated.get("owner_start_token")):
            raise PlanAlreadyUsed(
                "The reconciliation run is still owned by a live process."
            )
        if validated.get("state") != "claiming" or plan.get("state") != "reviewed":
            raise PlanAlreadyUsed(
                "The reconciliation run passed its preclaim boundary."
            )
        safe_ledger = _canonical_ledger(ledger, _project_paths(plan))
        finished_at = _timestamp(_now(now))
        validated["state"] = "abandoned"
        validated["outcome"] = "blocked"
        validated["ledger"] = list(safe_ledger)
        validated["outcome_recorded_at"] = finished_at
        validated["owner_pid"] = 0
        validated["owner_start_token"] = ""
        validated["finished_at"] = finished_at
        atomic_json_write(intent_path, validated)
        plan["state"] = "consumed"
        plan["outcome"] = "blocked"
        plan["finished_at"] = finished_at
        plan["claim_token_hash"] = None
        atomic_json_write(plan_path, plan)
    return load_recovery_context(run_id, root=root)


def _validated_final_diagnostic(
    context: RecoveryContext,
    *,
    root: Optional[Path],
    expected_ledger: Optional[Sequence[Mapping[str, Any]]] = None,
) -> None:
    from cc.core.ecosystem.reconciliation_diagnostics import safe_project_receipt

    state = _state_root(root)
    directory = state / "diagnostics"
    boundary = state if root is not None else machine_diagnostics_root()
    try:
        ensure_private_directory(directory, boundary=boundary)
    except ProjectLockError as exc:
        raise PlanBindingMismatch(
            "The final reconciliation diagnostic boundary is unsafe."
        ) from exc
    path = directory / f"reconciliation-{context.run_id}.json"
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise PlanBindingMismatch(
            "The final reconciliation diagnostic is unavailable."
        ) from exc
    if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
        raise PlanBindingMismatch("The final reconciliation diagnostic is unsafe.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PlanBindingMismatch(
            "The final reconciliation diagnostic is unavailable."
        ) from exc
    try:
        ledger_authority = (
            expected_ledger if expected_ledger is not None else context.ledger
        )
        diagnostic_ledger = []
        for item in payload.get("projects", []) if isinstance(payload, dict) else []:
            safe = safe_project_receipt(item)
            safe.pop("evidence", None)
            diagnostic_ledger.append(safe)
        safe_expected_ledger = []
        for item in ledger_authority:
            safe = safe_project_receipt(item)
            safe.pop("evidence", None)
            safe_expected_ledger.append(safe)
    except RuntimeError as exc:
        raise PlanBindingMismatch(
            "The final reconciliation diagnostic ledger is invalid."
        ) from exc
    expected_sources = [
        {"path": item["path"], "sources": item.get("sources", [])}
        for item in context.plans
    ]
    final_census = payload.get("final_census") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("run_id") != context.run_id
        or payload.get("requested_plan_id") != context.plan_id
        or payload.get("request_fingerprint") != context.request_fingerprint
        or payload.get("fresh_plan_fingerprint") != context.fresh_plan_fingerprint
        or payload.get("helper_version") != context.helper_version
        or payload.get("contract_schema_version") != context.schema_version
        or payload.get("canonical_request") != context.canonical_request
        or payload.get("reviewed_plans") != list(context.plans)
        or payload.get("source_bindings") != expected_sources
        or diagnostic_ledger != safe_expected_ledger
        or not isinstance(final_census, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for key, value in final_census.items()
        )
        or not isinstance(payload.get("finalized_at"), str)
    ):
        raise PlanBindingMismatch(
            "The final reconciliation diagnostic binding is invalid."
        )


def finalize_run_intent(
    run_id: str,
    *,
    diagnostic_id: str,
    diagnostic_state: str,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> RecoveryContext:
    """Mark one run terminal only after its original diagnostic is durable."""
    if diagnostic_id != run_id or diagnostic_state != "available":
        raise PlanBindingMismatch(
            "A reconciliation run requires an available final diagnostic."
        )
    context = load_recovery_context(run_id, root=root)
    if context.state == "finalized":
        return context
    if context.state != "outcome-recorded":
        raise PlanAlreadyUsed(
            "The reconciliation run has no complete recorded outcome."
        )
    _validated_final_diagnostic(context, root=root)
    intent_path = _intent_path(run_id, root)
    lock_path = _plans_dir(root) / ".store.lock"
    with advisory_file_lock(lock_path):
        plan = _validated_plan(_load(_record_path(context.plan_id, root)))
        intent = _validated_intent(_load(intent_path), plan)
        if intent.get("state") != "outcome-recorded":
            raise PlanAlreadyUsed(
                "The reconciliation run outcome changed before finalization."
            )
        intent["state"] = "finalized"
        intent["finished_at"] = _timestamp(_now(now))
        intent["owner_pid"] = 0
        intent["owner_start_token"] = ""
        atomic_json_write(intent_path, intent)
    return load_recovery_context(run_id, root=root)


__all__ = [
    "PlanAlreadyUsed",
    "PlanBindingMismatch",
    "PlanClaim",
    "PlanExpired",
    "PlanNotFound",
    "PlanRecord",
    "PlanStoreError",
    "RecoveryContext",
    "abandon_preclaim_run",
    "claim_plan",
    "finalize_run_intent",
    "finish_plan",
    "incomplete_run_ids",
    "issue_plan",
    "load_recovery_context",
    "record_recovered_projects",
    "recovery_lock",
]
