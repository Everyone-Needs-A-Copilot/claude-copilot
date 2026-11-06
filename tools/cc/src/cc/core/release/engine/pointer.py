"""Atomic flip, rollback, status and history for ~/.copilot/current."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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


def _set_pointer(release_id: str, home: Path | str | None) -> None:
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


def flip(
    release_id: str,
    home: Path | str | None = None,
    *,
    action: str = "flip",
    reason: str = "",
    on_moved: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Replace `current` with a symlink to `release_id` via rename (atomic).

    The pointer and its history row stay consistent: if the history write
    fails, the pointer is restored to where it was before the flip.

    `on_moved(release_id)` brings dependent state (the links receipt) to the release the pointer
    now names. It runs before the history write and under the same guarantee: if it or the history
    write fails, the pointer is restored and `on_moved(previous)` runs best-effort.
    """
    target = layout.release_dir(release_id, home)
    schema.load(target)  # refuses unknown or invalid releases; current untouched
    previous = current_release_id(home)
    _set_pointer(release_id, home)
    record = {
        "ts": _now(),
        "action": action,
        "release": release_id,
        "previous": previous,
        "reason": reason,
    }
    try:
        if on_moved is not None:
            on_moved(release_id)
        append_history(home, record)
    except Exception as exc:
        try:
            if previous is not None:
                _set_pointer(previous, home)
                if on_moved is not None:
                    try:
                        on_moved(previous)
                    except Exception:  # noqa: BLE001 - the pointer restore is what must hold
                        pass
            else:
                layout.current_path(home).unlink(missing_ok=True)
        except Exception as undo:  # noqa: BLE001
            raise PointerError(
                f"move failed ({exc}) and pointer restore failed ({undo})"
            ) from exc
        raise PointerError(f"move failed; pointer restored to {previous}: {exc}") from exc
    return record


def _lineage(home: Path | str | None) -> list[str]:
    """Release stack replayed from history: flips push, rollbacks pop to target."""
    stack: list[str] = []
    for row in read_history(home):
        release = row.get("release")
        if not release:
            continue
        if row.get("action") == "rollback" and release in stack:
            del stack[len(stack) - stack[::-1].index(release):]
        else:
            stack.append(release)
    return stack


def earlier_releases(home: Path | str | None = None) -> list[str]:
    """Releases before `current` in history order, nearest first, still on disk."""
    current = current_release_id(home)
    stack = _lineage(home)
    if current in stack:
        stack = stack[: len(stack) - stack[::-1].index(current) - 1]
    available = set(list_releases(home))
    out: list[str] = []
    for candidate in reversed(stack):
        if candidate != current and candidate in available and candidate not in out:
            out.append(candidate)
    return out


def previous_release(home: Path | str | None = None) -> str | None:
    earlier = earlier_releases(home)
    return earlier[0] if earlier else None


def rollback(
    home: Path | str | None = None,
    *,
    to: str | None = None,
    steps: int = 1,
    reason: str = "",
    on_moved: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Roll back `steps` releases through history, or to the named release."""
    if to is None:
        if steps < 1:
            raise PointerError("steps must be at least 1")
        earlier = earlier_releases(home)
        if steps > len(earlier):
            raise PointerError(
                f"no earlier release: cannot roll back {steps} step(s); "
                f"{len(earlier)} earlier release(s) available"
            )
        to = earlier[steps - 1]
    if to == current_release_id(home):
        raise PointerError(f"{to} is already current")
    return flip(to, home, action="rollback", reason=reason, on_moved=on_moved)


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
