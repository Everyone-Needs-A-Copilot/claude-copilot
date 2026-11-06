"""Atomic flip, rollback, status and history for ~/.copilot/current."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import layout, schema


class PointerError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_release_id(home: Path | str | None = None) -> str | None:
    """Release id `current` points at, or None when absent or not a symlink."""
    pointer = layout.current_path(home)
    if not pointer.is_symlink():
        return None
    return Path(os.readlink(pointer)).name


def list_releases(home: Path | str | None = None) -> list[str]:
    root = layout.releases_dir(home)
    if not root.is_dir():
        return []
    return sorted(
        item.name
        for item in root.iterdir()
        if schema.RELEASE_ID.fullmatch(item.name) and (item / layout.MANIFEST_NAME).is_file()
    )


def read_history(home: Path | str | None = None) -> list[dict[str, Any]]:
    path = layout.history_path(home)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def append_history(home: Path | str | None, record: dict[str, Any]) -> None:
    base = layout.copilot_home(home)
    base.mkdir(parents=True, exist_ok=True)
    with open(base / layout.HISTORY_LOCK_NAME, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(layout.history_path(home), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def flip(
    release_id: str,
    home: Path | str | None = None,
    *,
    action: str = "flip",
    reason: str = "",
) -> dict[str, Any]:
    """Replace `current` with a symlink to `release_id` via rename (atomic)."""
    target = layout.release_dir(release_id, home)
    schema.load(target)  # refuses unknown or invalid releases; current untouched
    previous = current_release_id(home)
    pointer = layout.current_path(home)
    temp = pointer.with_name(f".{layout.CURRENT_NAME}.{os.getpid()}.tmp")
    if temp.is_symlink() or temp.exists():
        temp.unlink()
    os.symlink(Path(layout.RELEASES_DIRNAME) / release_id, temp)
    try:
        os.replace(temp, pointer)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise PointerError(f"cannot replace {pointer}: {exc}") from exc
    record = {
        "ts": _now(),
        "action": action,
        "release": release_id,
        "previous": previous,
        "reason": reason,
    }
    append_history(home, record)
    return record


def previous_release(home: Path | str | None = None) -> str | None:
    """Most recent earlier release still on disk that is not the current one."""
    current = current_release_id(home)
    available = set(list_releases(home))
    for row in reversed(read_history(home)):
        candidate = row.get("release")
        if candidate and candidate != current and candidate in available:
            return candidate
    return None


def rollback(
    home: Path | str | None = None, *, to: str | None = None, reason: str = ""
) -> dict[str, Any]:
    target = to or previous_release(home)
    if target is None:
        raise PointerError("no previous release to roll back to")
    if target == current_release_id(home):
        raise PointerError(f"{target} is already current")
    return flip(target, home, action="rollback", reason=reason)


def status(home: Path | str | None = None) -> dict[str, Any]:
    pointer = layout.current_path(home)
    info: dict[str, Any] = {
        "pointer": str(pointer),
        "present": pointer.is_symlink(),
        "release": current_release_id(home),
        "valid": False,
        "error": None,
        "previous": previous_release(home),
        "releases": list_releases(home),
    }
    if not info["present"]:
        info["error"] = "current missing"
        return info
    if not pointer.exists():
        info["error"] = "current is dangling"
        return info
    try:
        manifest = schema.load(pointer.resolve())
        info["valid"] = True
        info["created"] = manifest.created
        info["components"] = {item.name: item.version for item in manifest.components}
    except schema.ReleaseSchemaError as exc:
        info["error"] = str(exc)
    return info
