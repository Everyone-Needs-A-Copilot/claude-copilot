"""Advisory `flock` scaffold for cc's lifecycle-mutating verbs.

WS-A / doctor-slice (TASK-first-vertical-slice): Control Tower supervises
the `copilot`/`cc` CLI as a single process; the CLI self-serializes mutating
operations (`update`, `repair`, `deprovision`, ...) via `flock` on a shared
lockfile so at most one such operation runs at a time (see
copilot-control-tower CLAUDE.md invariant #2: "the CLI self-serializes via
flock on copilot.lock — the app is not the lock").

`cc doctor` is READ-ONLY and intentionally does NOT take this lock: it only
inspects state and never mutates anything, so serializing it against writers
would slow down health checks (which Control Tower polls) for no safety
benefit.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
from typing import Iterator, Optional

from cc.core.entry_store import resolve_memory_root


class LockContentionError(RuntimeError):
    """Raised when the copilot lock is already held by another operation."""


def lock_path() -> Path:
    """
    Return the path to the advisory `copilot.lock` file.

    PROVISIONAL DEFAULT (pending owner confirmation): lives at the root of
    cc's "global" memory tree (~/.claude/memory/copilot.lock), reusing
    `entry_store.resolve_memory_root("global")` — the existing root
    resolution helper for cc's on-disk state — rather than inventing a new
    location. Confirm this is the intended lock location with the CLI owner
    before the Control Tower app starts depending on it.
    """
    return resolve_memory_root("global") / "copilot.lock"


@contextlib.contextmanager
def copilot_lock(*, path: Optional[Path] = None) -> Iterator[None]:
    """
    Acquire the advisory copilot lock for the duration of the `with` block.

    Non-blocking: raises LockContentionError immediately if another copilot
    operation already holds the lock (mirrors the architecture's flock-based
    self-serialization — this helper does not queue/retry; callers decide
    whether to retry or surface the contention to the user).
    """
    target = path or lock_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # COPILOT_MANAGED_BY: no-op awareness hook. When set (e.g. by an MDM- or
    # Control-Tower-launched process), it does not currently change locking
    # behavior — it is plumbed through so a future lock-holder diagnostic can
    # report *who* holds the lock without changing acquisition semantics.
    managed_by = os.environ.get("COPILOT_MANAGED_BY")

    fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            suffix = f" [managed_by={managed_by}]" if managed_by else ""
            raise LockContentionError(
                f"Another copilot operation is already running (lock held: {target}){suffix}"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
