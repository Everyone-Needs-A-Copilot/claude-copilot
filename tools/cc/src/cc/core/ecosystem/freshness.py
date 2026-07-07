"""Pure freshness computation: fingerprint the local resolved lock state and
fold it against a (possibly unknown) remote lock-pointer SHA.

WS-A slice 3 (freshness-slice) core module. See:
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/01-architecture/schemas/freshness.schema.json
  - copilot-control-tower/docs/reference/ecosystem-architecture.md §3.3

`cc/commands/freshness.py` wraps `compute_freshness()` + `current_lock_sha()`
in the versioned `--json` envelope (`schema_version`, `offline`,
`checked_at`) the same way `cc/commands/doctor.py` wraps `_run_checks()`.

READ-ONLY: this module never writes anything and never takes the copilot
lock (core/locking.py) -- mirrors `cc resolve`'s and `cc doctor`'s
read-only precedent.

Honesty rule (mirrors doctor.py's "never a fabricated Healthy"): `stale`
is `None` -- structurally distinct from `False` -- whenever either SHA is
unknown (remote unreachable, or no local lock yet). Never coerce an
unknown into "up to date".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional, TypedDict

from cc.core.ecosystem.lockfile import default_lockfile_path, read_lockfile

# Sentinel distinguishing "no override passed" from an explicit None argument.
_UNSET: Any = object()


class FreshnessResult(TypedDict):
    current_lock_sha: Optional[str]
    latest_lock_sha: Optional[str]
    stale: Optional[bool]


def _git_blob_sha1(data: bytes) -> str:
    """
    Reproduce `git hash-object`'s blob SHA1 for `data`.

    This is deliberately NOT the sha256 "provisional content hash" scheme
    core/ecosystem/discovery.py uses for per-item diffing (that scheme is
    explicitly a local stand-in never meant to match anything published
    externally). Here, the owner-ratified lock-pointer convention
    (mirror.py's module docstring) defines "the current resolved lock-SHA"
    as a REAL git object identity a tier's source repo publishes via
    `git ls-remote` -- so the local fingerprint must use the identical
    `git hash-object` algorithm to ever be directly comparable, never a
    different hash family that would never match even when in sync.
    """
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324 (identity fingerprint, not a security hash)


def lock_fingerprint(lock: dict[str, Any]) -> str:
    """
    Always-defined git-blob-sha1 fingerprint of a lock dict (including the
    empty lock `{}`) -- unlike `current_lock_sha()`, this NEVER returns
    `None`. Backs `cc update --json`'s `lock_before`/`lock_after` fields
    (update.schema.json: both are non-nullable `git_sha` strings -- there is
    no "unknown" state for update the way there is for freshness's cheap
    poll, since a lock -- even an empty first-run one -- always exists as a
    concrete value the CLI can hash).
    """
    canonical = json.dumps(lock, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _git_blob_sha1(canonical)


def current_lock_sha(
    *,
    _lockfile: Optional[dict[str, Any]] = None,
    _lockfile_path: Any = _UNSET,
) -> Optional[str]:
    """
    Fingerprint of the local resolved lock state (`copilot.lock.json`),
    read via the READ-ONLY lockfile reader (lockfile.py's `read_lockfile`)
    -- never the raw file directly, so a missing/corrupt/empty lockfile
    degrades identically here as it does for `cc resolve` (honest `None`,
    never a crash).

    `None` when there is no local lock yet -- a first-run machine, not an
    error.
    """
    if _lockfile is not None:
        data = _lockfile
    else:
        path: Optional[Path] = (
            _lockfile_path if _lockfile_path is not _UNSET else default_lockfile_path()
        )
        data = read_lockfile(path)

    if not data:
        return None

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _git_blob_sha1(canonical)


def compute_freshness(current: Optional[str], latest: Optional[str]) -> FreshnessResult:
    """
    Pure fold: `{current_lock_sha, latest_lock_sha, stale}`.

    `stale`:
      - `True`  -- both SHAs known and differ.
      - `False` -- both SHAs known and match.
      - `None`  -- either SHA is unknown (remote unreachable/offline, or no
        local lock yet). NEVER coerced to `False` -- see module docstring.
    """
    if current is None or latest is None:
        stale: Optional[bool] = None
    else:
        stale = current != latest

    return {
        "current_lock_sha": current,
        "latest_lock_sha": latest,
        "stale": stale,
    }
