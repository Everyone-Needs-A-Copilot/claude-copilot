"""Best-effort LOCAL discovery of per-layer, per-dimension contributions.

This is NOT the materialize engine — that is a later, engine-blocked slice
(mirrors cc/commands/lifecycle.py's `update`/`repair`/`deprovision` stubs,
which acquire the lock and honestly report "engine-blocked" rather than
improvising resolution/sync logic ahead of the real engine).

This module only looks at content a layer's manifest entry ALREADY makes
available locally: `source.path` pointing at a directory that already
exists on this machine (e.g. a personal layer checked out locally, or a
fixture manifest used for testing/demoing `resolve --explain`). A layer
with no local `source.path`, or whose path does not exist on disk, simply
contributes nothing — this module never clones, fetches, or touches the
network, and never raises on a missing/unreadable layer (best-effort: one
bad layer must not crash the whole resolve).

The per-item "sha" produced here is a lightweight content hash (sha256 of
file bytes, or of a stable file listing for directories) — NOT a real git
blob sha. Computing a true git object identity needs a git-aware
materialize step this slice does not build; this is a provisional stand-in
surfaced honestly (see cc/commands/resolve.py's fail-closed security
fields), not a claim of git identity or authenticity.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from cc.core.ecosystem.dimensions import DIMENSION_SEMANTICS


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_dir(path: Path) -> str:
    """Stable content hash over a directory's files (skill/agent "items"
    are often a directory, e.g. `skills/testing-patterns/SKILL.md`)."""
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_file():
            digest.update(child.relative_to(path).as_posix().encode("utf-8"))
            digest.update(child.read_bytes())
    return digest.hexdigest()


def discover_contributions(
    layers: list[dict[str, Any]],
    *,
    dimensions: tuple[str, ...] = tuple(DIMENSION_SEMANTICS),
) -> dict[str, dict[str, dict[str, str]]]:
    """
    Best-effort scan: for each layer with a local `source.path`, look for a
    subdirectory per dimension name and record each entry's
    `(item name -> content hash)`.

    Returns `{}` (or partial results) for layers/dimensions with nothing
    local — never raises on an individual layer's I/O failure, since a
    single unreadable layer should not prevent resolving the others.
    """
    contributions: dict[str, dict[str, dict[str, str]]] = {}

    for layer in layers:
        layer_id = layer.get("id")
        if not layer_id:
            continue

        local_root = (layer.get("source") or {}).get("path")
        if not local_root:
            continue

        try:
            root = Path(local_root).expanduser()
            if not root.is_dir():
                continue
        except (OSError, ValueError):
            continue

        layer_contrib: dict[str, dict[str, str]] = {}
        for dimension in dimensions:
            dim_dir = root / dimension
            try:
                if not dim_dir.is_dir():
                    continue
                items: dict[str, str] = {}
                for entry in sorted(dim_dir.iterdir()):
                    if entry.is_file():
                        items[entry.stem] = _hash_file(entry)
                    elif entry.is_dir():
                        items[entry.name] = _hash_dir(entry)
            except OSError:
                continue
            if items:
                layer_contrib[dimension] = items

        if layer_contrib:
            contributions[layer_id] = layer_contrib

    return contributions
