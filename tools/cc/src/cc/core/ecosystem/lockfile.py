"""READ-ONLY reader for the per-layer/per-dimension/per-item SHA pins.

ecosystem-architecture.md §9: "SHA-pinned lockfile per layer — the
reproducibility anchor everything else verifies against." This module
NEVER writes anything — `cc resolve` is read-only (no lock, no
materialize; mirrors `cc doctor`'s precedent in doctor.py). If the file is
absent or unreadable, every lookup gracefully degrades to "no recorded
sha" rather than raising, so a first-run machine (no lockfile yet) still
gets a usable `--explain` report (every `winning_sha` simply `None`)
instead of a crash.

NOTE (deferred, tracked): this data lockfile shares its conceptual name
("copilot.lock") with the UNRELATED advisory `flock` mutex file that
core/locking.py already uses for cc's self-serialization
(`resolve_memory_root("global") / "copilot.lock"`). The two are different
files serving different purposes today; this module deliberately does NOT
read/write that mutex file, and instead defaults to a distinct
`copilot.lock.json` path (see `default_lockfile_path()`) so the two never
collide on disk. Resolving the naming collision for real (should the data
lockfile also be called `copilot.lock`, and if so how do the mutex and the
data file coexist) is explicitly out of scope for this read-only slice —
left for whichever later slice actually introduces lockfile *writing*
(materialize).

Lock entry shape (ecosystem-architecture.md §3.3: "`copilot.lock`
(shareable, machine-agnostic): resolved SHAs + product/tier/role +
pins."): `{layer_id: {dimension: {item_name: sha}, "_meta": {product,
tier, role}}}`. `_meta` is a RESERVED per-layer key (never a real
dimension name — see dimensions.py, none of which is ever `"_meta"`), so
an existing flat `{layer_id: {dimension: {item: sha}}}` lockfile with no
`_meta` block remains byte-for-byte readable by every existing consumer
(`_recorded_sha()` in resolver.py never looks at `_meta`) -- adding
product/tier/role is purely additive, never a breaking reshape of the
per-item sha pins. `layer_meta()`/`set_layer_meta()` below are the
read/write helpers for this block; wiring them into the actual
materialize/update write path is a later slice (materialize.py/update.py
do not call these yet).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

# Reserved per-layer key holding descriptive (product/tier/role) metadata,
# alongside that layer's real dimension -> item -> sha pins. Never a real
# dimension name (see dimensions.py's DIMENSION_SEMANTICS keys), so its
# presence/absence never collides with `_recorded_sha()`'s dimension lookup.
LAYER_META_KEY = "_meta"


def default_lockfile_path() -> Optional[Path]:
    """
    Best-effort default location for the ecosystem lockfile.

    PROVISIONAL (owner to confirm once the materialize slice lands): lives
    at `<repo root>/copilot.lock.json`. Returns None (treated identically
    to "file absent") when there is no repo root to anchor to, rather than
    guessing a location.
    """
    from cc.core.config_paths import repo_root

    root = repo_root()
    if root is None:
        return None
    return root / "copilot.lock.json"


def read_lockfile(path: Optional[Path | str]) -> dict[str, dict[str, dict[str, str]]]:
    """
    Read the per-layer/per-dimension/per-item SHA pins.

    Shape: `{layer_id: {dimension: {item_name: sha}}}`, plus an optional
    reserved `_meta` block per layer (`layer_meta()`/`set_layer_meta()`
    below) carrying that layer's product/tier/role -- see module docstring.

    Read-only: never creates, writes, or locks anything. Returns `{}` if
    `path` is `None`, does not exist, or fails to parse as a JSON object —
    a missing/corrupt lockfile degrades to "no recorded SHAs" (every
    `winning_sha` / override-stale comparison falls back to `None`/unknown)
    rather than raising.
    """
    if path is None:
        return {}

    resolved = Path(path).expanduser()
    if not resolved.exists():
        return {}

    try:
        data: Any = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def layer_meta(lock: dict[str, Any], layer_id: str) -> dict[str, str]:
    """
    Best-effort per-layer descriptive metadata (`{"product": ..., "tier":
    ..., "role": ...}`) recorded alongside a layer's sha pins under the
    reserved `_meta` key (see `LAYER_META_KEY`).

    Degrades to `{}` -- same fail-open pattern as `read_lockfile()` -- when
    the layer or its `_meta` block is absent (e.g. an old-format lockfile
    written before this field existed, or a layer that was never
    materialized through the write path that populates it).
    """
    return dict(lock.get(layer_id, {}).get(LAYER_META_KEY, {}))


def set_layer_meta(
    lock: dict[str, Any],
    layer_id: str,
    *,
    product: str,
    tier: Optional[str] = None,
    role: Optional[str] = None,
) -> dict[str, Any]:
    """
    Record `{product, tier, role}` under `lock[layer_id]["_meta"]`, mutating
    and returning `lock` (mirrors the `setdefault`-chaining ergonomics
    materialize.py's own lock-building already uses).

    `tier`/`role` are optional today (four-tier-topology.md §4's manifest
    only names a single `role` field, which already carries the tier value
    e.g. "org"/"department"; both are accepted here so a caller can record
    either name -- or the same value under both -- without this module
    guessing which one the caller means).
    """
    entry = lock.setdefault(layer_id, {})
    meta: dict[str, str] = {"product": product}
    if tier is not None:
        meta["tier"] = tier
    if role is not None:
        meta["role"] = role
    entry[LAYER_META_KEY] = meta
    return lock


def write_lockfile(path: Path | str, lock: dict[str, dict[str, dict[str, str]]]) -> None:
    """
    Write the per-layer/per-dimension/per-item SHA pins.

    WS-A update-slice: `cc update` is the FIRST (and, today, only) writer of
    this file -- `cc resolve`/`cc doctor`/`cc freshness` remain strictly
    read-only (see this module's own docstring). Writes canonical
    (sort_keys, indent=2) JSON so the file diffs cleanly in source control
    for tiers that choose to commit it (ecosystem-architecture.md §3.3:
    "`copilot.lock` (shareable, machine-agnostic) ... safe to commit").

    Creates parent directories as needed. Callers are responsible for
    holding `copilot_lock()` around any write -- this function does not
    lock anything itself (mirrors every other single-purpose helper in
    core/ecosystem/; `commands/update.py` is what acquires the mutex).
    """
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
