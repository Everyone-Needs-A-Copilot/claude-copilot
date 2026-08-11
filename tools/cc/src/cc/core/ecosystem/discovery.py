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

Per-layer dimension scoping (RC-5, core/conformance/root_causes.py): a
layer's own `copilot.layer.yml` `dimensions:` field, when present and
non-empty, is READ (`_declared_dimensions()`) and narrows which
sub-directories THIS layer is probed for, rather than blindly probing
every dimension name the caller passed. Before this, `dimensions:` was a
write-only field (`commands/onboard.py` scaffolds it) with no consumer
anywhere in the source tree; a layer with no declaration file at all falls
back to the caller-supplied `dimensions` tuple below, unchanged from
before this existed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

import yaml

from cc.core.ecosystem.dimensions import DIMENSION_SEMANTICS

# A layer's own self-declaration of what it carries (RC-5,
# core/conformance/root_causes.py) -- lives at the layer's repo root,
# alongside the content directories this module scans. `commands/onboard.py`
# scaffolds this file's `dimensions:` field; `_declared_dimensions()` below
# is its first real reader (previously WRITE-only -- see this module's own
# docstring update).
_LAYER_DECLARATION_FILENAME = "copilot.layer.yml"


def _declared_dimensions(layer_root: Path) -> Optional[tuple[str, ...]]:
    """A layer's own `<layer_root>/copilot.layer.yml` `dimensions:` list,
    when present and non-empty -- "what this tier actually carries",
    narrower than blindly probing every known dimension name.

    Returns `None` (never an empty tuple) when the declaration file is
    absent, unparseable, or names nothing, so `discover_contributions()`
    can tell "this layer declared nothing" apart from "this layer declared
    it carries nothing" and fall back to ITS OWN caller-supplied probe set
    for that layer -- best-effort, like every other read in this module:
    one layer's missing/broken declaration must never block discovery for
    any other layer."""
    declaration = layer_root / _LAYER_DECLARATION_FILENAME
    try:
        if not declaration.is_file():
            return None
        raw = yaml.safe_load(declaration.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    declared = raw.get("dimensions")
    if not isinstance(declared, list):
        return None
    names = tuple(name for name in declared if isinstance(name, str) and name)
    return names or None


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

    Per layer, the dimensions actually probed are `dimensions` (this
    parameter, the caller's upper bound) INTERSECTED with that layer's own
    `copilot.layer.yml` `dimensions:` declaration when one exists
    (`_declared_dimensions()`) — a layer that declares e.g. `[commands,
    plugins]` is never probed for `agents` even if the caller's default
    table includes it. A layer with no declaration file (or an empty one)
    is probed against the full caller-supplied `dimensions` tuple,
    unchanged from before this scoping existed.
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

        declared = _declared_dimensions(root)
        layer_dimensions = (
            tuple(dimension for dimension in dimensions if dimension in declared)
            if declared
            else dimensions
        )

        layer_contrib: dict[str, dict[str, str]] = {}
        for dimension in layer_dimensions:
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
