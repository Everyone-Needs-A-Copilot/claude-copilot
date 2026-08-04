"""Private, expiring assistant sessions and proposal capabilities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from cc.core.config_paths import machine_diagnostics_root
from cc.core.ecosystem.project_locking import (
    advisory_file_lock,
    atomic_json_write,
    ensure_private_directory,
)

_SESSION_ID = re.compile(r"^session_[0-9a-f]{32}$")
_PROPOSAL_ID = re.compile(r"^proposal_[0-9a-f]{32}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_SESSION_STATES = {"prepared", "running", "completed", "rejected", "proposed"}


class AssistantStoreError(RuntimeError):
    pass


class AssistantNotFound(AssistantStoreError):
    pass


class AssistantExpired(AssistantStoreError):
    pass


class AssistantAlreadyUsed(AssistantStoreError):
    pass


class AssistantBindingMismatch(AssistantStoreError):
    pass


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _now(value: Optional[datetime]) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise AssistantBindingMismatch("Assistant state has an invalid expiry.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssistantBindingMismatch("Assistant state has an invalid expiry.") from exc


def _state_root(root: Optional[Path]) -> Path:
    return (root or (machine_diagnostics_root() / "reconciliation" / "assistant")).expanduser()


def _directory(name: str, root: Optional[Path]) -> Path:
    state = _state_root(root)
    directory = state / name
    boundary = state if root is not None else machine_diagnostics_root()
    ensure_private_directory(directory, boundary=boundary)
    return directory


def session_directory(session_id: str, root: Optional[Path] = None) -> Path:
    if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
        raise AssistantNotFound("The assistant session does not exist.")
    directory = _directory("sessions", root) / session_id
    ensure_private_directory(directory, boundary=_state_root(root))
    return directory


def _session_path(session_id: str, root: Optional[Path]) -> Path:
    return session_directory(session_id, root) / "session.json"


def _proposal_path(proposal_id: str, root: Optional[Path]) -> Path:
    if not isinstance(proposal_id, str) or _PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise AssistantNotFound("The assistant proposal does not exist.")
    return _directory("proposals", root) / f"{proposal_id}.json"


def _load_private(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AssistantNotFound("The private assistant state is unavailable.") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise AssistantBindingMismatch("The private assistant state is unsafe.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssistantBindingMismatch("The private assistant state is unreadable.") from exc
    if not isinstance(value, dict):
        raise AssistantBindingMismatch("The private assistant state is invalid.")
    return value


def _validate_session(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "storage_schema_version",
        "session_id",
        "state",
        "created_at",
        "expires_at",
        "base_request",
        "request_fingerprint",
        "packet",
        "packet_fingerprint",
        "policy_fingerprint",
        "job_fingerprint",
        "state_fingerprint",
        "candidates",
        "selected_projects",
        "selections",
        "proposal_id",
        "failure_code",
    }
    if set(value) != required:
        raise AssistantBindingMismatch("The assistant session shape is invalid.")
    session_id = value.get("session_id")
    state = value.get("state")
    if (
        value.get("storage_schema_version") != "1.0"
        or not isinstance(session_id, str)
        or _SESSION_ID.fullmatch(session_id) is None
        or state not in _SESSION_STATES
        or not isinstance(value.get("base_request"), dict)
        or not isinstance(value.get("packet"), dict)
        or not isinstance(value.get("candidates"), list)
        or not isinstance(value.get("selected_projects"), list)
        or not isinstance(value.get("selections"), list)
        or value.get("proposal_id") is not None
        and (
            not isinstance(value.get("proposal_id"), str)
            or _PROPOSAL_ID.fullmatch(str(value.get("proposal_id"))) is None
        )
    ):
        raise AssistantBindingMismatch("The assistant session is invalid.")
    for field in ("request_fingerprint", "packet_fingerprint", "policy_fingerprint"):
        raw = value.get(field)
        if not isinstance(raw, str) or _FINGERPRINT.fullmatch(raw) is None:
            raise AssistantBindingMismatch("The assistant session binding is invalid.")
    if fingerprint(value["base_request"]) != value["request_fingerprint"]:
        raise AssistantBindingMismatch("The assistant request binding changed.")
    if fingerprint(value["packet"]) != value["packet_fingerprint"]:
        raise AssistantBindingMismatch("The assistant packet binding changed.")
    projects = value["base_request"].get("projects")
    expected_projects = (
        [item.get("path") for item in projects]
        if isinstance(projects, list) and all(isinstance(item, dict) for item in projects)
        else None
    )
    if (
        expected_projects != value["selected_projects"]
        or len(value["selected_projects"]) != len(set(value["selected_projects"]))
        or any(not isinstance(item, dict) for item in value["candidates"])
        or any(not isinstance(item, dict) for item in value["selections"])
    ):
        raise AssistantBindingMismatch("The assistant selected projects are invalid.")
    candidate_ids = [item.get("candidate_id") for item in value["candidates"]]
    if (
        any(not isinstance(item, str) for item in candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
    ):
        raise AssistantBindingMismatch("The assistant candidate catalog is invalid.")
    immutable = {
        "base_request": value["base_request"],
        "packet": value["packet"],
        "candidates": value["candidates"],
        "selected_projects": value["selected_projects"],
        "policy_fingerprint": value["policy_fingerprint"],
    }
    if fingerprint(immutable) != value.get("job_fingerprint"):
        raise AssistantBindingMismatch("The assistant job binding changed.")
    mutable = {
        "job_fingerprint": value["job_fingerprint"],
        "state": value["state"],
        "selections": value["selections"],
        "proposal_id": value["proposal_id"],
        "failure_code": value["failure_code"],
    }
    if fingerprint(mutable) != value.get("state_fingerprint"):
        raise AssistantBindingMismatch("The assistant session state binding changed.")
    _parse_timestamp(value.get("created_at"))
    _parse_timestamp(value.get("expires_at"))
    return dict(value)


def create_session(
    *,
    base_request: Mapping[str, Any],
    packet: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    selected_projects: Sequence[str],
    policy_fingerprint: str,
    ttl_seconds: int = 1800,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0 or ttl_seconds > 86400:
        raise AssistantStoreError("Assistant lifetime must be between 1 and 86400 seconds.")
    if not isinstance(policy_fingerprint, str) or _FINGERPRINT.fullmatch(policy_fingerprint) is None:
        raise AssistantBindingMismatch("The assistant policy fingerprint is invalid.")
    created = _now(now)
    identifier = session_id or f"session_{secrets.token_hex(16)}"
    if _SESSION_ID.fullmatch(identifier) is None:
        raise AssistantBindingMismatch("The assistant session id is invalid.")
    canonical_request = json.loads(json.dumps(dict(base_request), sort_keys=True))
    canonical_packet = json.loads(json.dumps(dict(packet), sort_keys=True))
    canonical_candidates = json.loads(json.dumps(list(candidates), sort_keys=True))
    raw = {
        "storage_schema_version": "1.0",
        "session_id": identifier,
        "state": "prepared",
        "created_at": _timestamp(created),
        "expires_at": _timestamp(created + timedelta(seconds=ttl_seconds)),
        "base_request": canonical_request,
        "request_fingerprint": fingerprint(canonical_request),
        "packet": canonical_packet,
        "packet_fingerprint": fingerprint(canonical_packet),
        "policy_fingerprint": policy_fingerprint,
        "candidates": canonical_candidates,
        "selected_projects": list(selected_projects),
        "selections": [],
        "proposal_id": None,
        "failure_code": None,
    }
    raw["job_fingerprint"] = fingerprint(
        {
            "base_request": raw["base_request"],
            "packet": raw["packet"],
            "candidates": raw["candidates"],
            "selected_projects": raw["selected_projects"],
            "policy_fingerprint": raw["policy_fingerprint"],
        }
    )
    raw["state_fingerprint"] = fingerprint(
        {
            "job_fingerprint": raw["job_fingerprint"],
            "state": raw["state"],
            "selections": raw["selections"],
            "proposal_id": raw["proposal_id"],
            "failure_code": raw["failure_code"],
        }
    )
    validated = _validate_session(raw)
    atomic_json_write(_session_path(identifier, root), validated)
    return validated


def load_session(
    session_id: str, *, root: Optional[Path] = None, now: Optional[datetime] = None
) -> dict[str, Any]:
    raw = _validate_session(_load_private(_session_path(session_id, root)))
    if raw["session_id"] != session_id:
        raise AssistantBindingMismatch("The assistant session id binding changed.")
    if _now(now) >= _parse_timestamp(raw["expires_at"]):
        raise AssistantExpired("The assistant session expired.")
    return raw


def claim_session(
    session_id: str, *, root: Optional[Path] = None, now: Optional[datetime] = None
) -> dict[str, Any]:
    path = _session_path(session_id, root)
    with advisory_file_lock(path.parent / ".session.lock"):
        raw = load_session(session_id, root=root, now=now)
        if raw["state"] != "prepared":
            raise AssistantAlreadyUsed("The assistant session was already run.")
        raw["state"] = "running"
        raw["state_fingerprint"] = fingerprint(
            {
                "job_fingerprint": raw["job_fingerprint"],
                "state": raw["state"],
                "selections": raw["selections"],
                "proposal_id": raw["proposal_id"],
                "failure_code": raw["failure_code"],
            }
        )
        atomic_json_write(path, raw)
        return raw


def complete_session(
    session_id: str,
    selections: Sequence[Mapping[str, Any]],
    *,
    root: Optional[Path] = None,
    failure_code: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    path = _session_path(session_id, root)
    with advisory_file_lock(path.parent / ".session.lock"):
        raw = load_session(session_id, root=root, now=now)
        if raw["state"] != "running":
            raise AssistantAlreadyUsed("The assistant session is not running.")
        raw["state"] = "rejected" if failure_code else "completed"
        raw["failure_code"] = failure_code
        raw["selections"] = (
            []
            if failure_code
            else json.loads(json.dumps(list(selections), sort_keys=True))
        )
        raw["state_fingerprint"] = fingerprint(
            {
                "job_fingerprint": raw["job_fingerprint"],
                "state": raw["state"],
                "selections": raw["selections"],
                "proposal_id": raw["proposal_id"],
                "failure_code": raw["failure_code"],
            }
        )
        atomic_json_write(path, raw)
        return _validate_session(raw)


def issue_proposal(
    session_id: str,
    *,
    resolved_request: Mapping[str, Any],
    owned_components: Mapping[str, Sequence[str]],
    plans_fingerprint: str,
    ttl_seconds: int = 900,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    path = _session_path(session_id, root)
    with advisory_file_lock(path.parent / ".session.lock"):
        session = load_session(session_id, root=root, now=now)
        if session["state"] == "proposed" and session.get("proposal_id"):
            return load_proposal(str(session["proposal_id"]), root=root, now=now)
        if session["state"] != "completed":
            raise AssistantAlreadyUsed("The assistant session has no completed selection.")
        if not isinstance(plans_fingerprint, str) or _FINGERPRINT.fullmatch(plans_fingerprint) is None:
            raise AssistantBindingMismatch("The assistant plan fingerprint is invalid.")
        created = _now(now)
        proposal_id = f"proposal_{secrets.token_hex(16)}"
        proposal = {
            "storage_schema_version": "1.0",
            "proposal_id": proposal_id,
            "session_id": session_id,
            "created_at": _timestamp(created),
            "expires_at": _timestamp(created + timedelta(seconds=ttl_seconds)),
            "base_request": session["base_request"],
            "request_fingerprint": session["request_fingerprint"],
            "resolved_request": json.loads(json.dumps(dict(resolved_request), sort_keys=True)),
            "owned_components": {
                str(path): list(components)
                for path, components in owned_components.items()
            },
            "packet_fingerprint": session["packet_fingerprint"],
            "policy_fingerprint": session["policy_fingerprint"],
            "plans_fingerprint": plans_fingerprint,
        }
        proposal["proposal_fingerprint"] = fingerprint(proposal)
        atomic_json_write(_proposal_path(proposal_id, root), proposal)
        session["state"] = "proposed"
        session["proposal_id"] = proposal_id
        session["state_fingerprint"] = fingerprint(
            {
                "job_fingerprint": session["job_fingerprint"],
                "state": session["state"],
                "selections": session["selections"],
                "proposal_id": session["proposal_id"],
                "failure_code": session["failure_code"],
            }
        )
        atomic_json_write(path, session)
        return proposal


def load_proposal(
    proposal_id: str, *, root: Optional[Path] = None, now: Optional[datetime] = None
) -> dict[str, Any]:
    raw = _load_private(_proposal_path(proposal_id, root))
    fingerprint_value = raw.pop("proposal_fingerprint", None)
    if (
        raw.get("storage_schema_version") != "1.0"
        or raw.get("proposal_id") != proposal_id
        or not isinstance(fingerprint_value, str)
        or _FINGERPRINT.fullmatch(fingerprint_value) is None
        or fingerprint(raw) != fingerprint_value
        or not isinstance(raw.get("base_request"), dict)
        or not isinstance(raw.get("resolved_request"), dict)
        or not isinstance(raw.get("owned_components"), dict)
        or not isinstance(raw.get("plans_fingerprint"), str)
        or _FINGERPRINT.fullmatch(str(raw.get("plans_fingerprint"))) is None
    ):
        raise AssistantBindingMismatch("The assistant proposal binding is invalid.")
    if _now(now) >= _parse_timestamp(raw.get("expires_at")):
        raise AssistantExpired("The assistant proposal expired.")
    return {**raw, "proposal_fingerprint": fingerprint_value}


__all__ = [
    "AssistantAlreadyUsed",
    "AssistantBindingMismatch",
    "AssistantExpired",
    "AssistantNotFound",
    "AssistantStoreError",
    "claim_session",
    "complete_session",
    "create_session",
    "fingerprint",
    "issue_proposal",
    "load_proposal",
    "load_session",
    "session_directory",
]
