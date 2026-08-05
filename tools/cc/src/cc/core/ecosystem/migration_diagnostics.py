"""Durable, redacted evidence for project-integration migration runs.

The migration engine owns this record because it owns every project read,
write, rollback, and verification decision.  GUI clients receive only a
versioned reference to the resulting local file; they never reconstruct or
persist migration truth themselves.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from cc.core.config_paths import machine_diagnostics_root
from cc.core.write_guard import assert_write_is_isolated

DIAGNOSTIC_SCHEMA_VERSION = "1.0"
DEFAULT_RETENTION = 20
_PREFIX = "workspace-migration-"
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?token|password|secret|authorization)"
    r"\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_VALUE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})")


def _redact(value: Any, *, key: Optional[str] = None) -> Any:
    """Return a JSON-compatible copy with credential-shaped values removed."""
    normalized_key = (key or "").lower().replace("-", "_")
    if isinstance(value, dict):
        return {
            str(item_key): _redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        if normalized_key in {
            "api_key",
            "access_token",
            "authorization",
            "password",
            "secret",
            "token",
        }:
            return "<redacted>"
        cleaned = _SECRET_ASSIGNMENT.sub(r"\1<redacted>", value)
        cleaned = _BEARER_VALUE.sub(r"\1<redacted>", cleaned)
        cleaned = _KNOWN_TOKEN.sub("<redacted>", cleaned)
        return cleaned[:8000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _ensure_private_directory(path: Path, *, boundary: Path) -> None:
    """Create a private directory without accepting a symlinked boundary."""
    if boundary.parent.is_symlink() or boundary.is_symlink() or path.is_symlink():
        raise OSError("The diagnostics location is symlinked.")
    boundary.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True, exist_ok=True)
    if boundary.parent.is_symlink() or boundary.is_symlink() or path.is_symlink():
        raise OSError("The diagnostics location changed while it was prepared.")
    boundary.chmod(0o700)
    path.chmod(0o700)


def _prune(directory: Path, *, retention: int) -> None:
    records: list[tuple[int, str, Path]] = []
    for candidate in directory.glob(f"{_PREFIX}*.json"):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            records.append((candidate.stat().st_mtime_ns, candidate.name, candidate))
        except OSError:
            continue
    records.sort(reverse=True)
    for _, _, candidate in records[max(1, retention) :]:
        try:
            candidate.unlink()
        except OSError:
            continue


def write_workspace_migration_diagnostic(
    report: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    run_id: Optional[str] = None,
    retention: int = DEFAULT_RETENTION,
) -> dict[str, Any]:
    """Atomically persist one bounded migration record and return its reference.

    Failure is deliberately non-fatal: the command's in-memory action ledger is
    still authoritative for that invocation, and the returned reference tells
    clients that durable evidence was unavailable.
    """
    created = now or datetime.now(timezone.utc)
    identifier = run_id or uuid.uuid4().hex
    created_at = _timestamp(created)
    diagnostics_root = (root or machine_diagnostics_root()).expanduser()
    directory = diagnostics_root / "workspace-migrations"
    filename_stamp = created.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"{_PREFIX}{filename_stamp}-{identifier}.json"
    temporary_path: Optional[Path] = None

    reference: dict[str, Any] = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "id": identifier,
        "state": "unavailable",
        "path": None,
        "created_at": created_at,
        "detail": (
            "The migration receipt is available in this response, but its "
            "detailed diagnostic record could not be saved."
        ),
    }
    payload = _redact(
        {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "kind": "workspace-migration-apply",
            "run_id": identifier,
            "created_at": created_at,
            "report": report,
            "actions": actions,
        }
    )
    try:
        assert_write_is_isolated(target)
        _ensure_private_directory(directory, boundary=diagnostics_root)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=directory
        )
        temporary_path = Path(temporary)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, target)
        directory_descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        _prune(directory, retention=retention)
        reference.update(
            {
                "state": "available",
                "path": str(target),
                "detail": (
                    "A private, redacted diagnostic record was saved for this update."
                ),
            }
        )
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return reference


__all__ = [
    "DEFAULT_RETENTION",
    "DIAGNOSTIC_SCHEMA_VERSION",
    "write_workspace_migration_diagnostic",
]
