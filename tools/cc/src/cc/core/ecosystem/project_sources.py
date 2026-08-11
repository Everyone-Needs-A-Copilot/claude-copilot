"""Resolve WHICH tier's copy of a project-install item actually lands on
disk — the wiring `core/ecosystem/workspaces.py`'s `_claude_plan()` was
missing (copilot-control-tower docs/10-reference/four-tier-topology.md,
ecosystem-architecture.md §3.1): a project used to always copy the
`claude` product's protocol and agents from a SINGLE root
(`paths.claude_copilot_root`, historically the foundation checkout) and
never consulted `copilot.layers.yml` at all — so personal → department →
organization → foundation inheritance never reached a project install, no
matter what a nearer tier declared.

This module is READ-ONLY (same posture as `commands/resolve.py`: never
clones/fetches, never acquires the copilot lock, never writes anything)
and reuses the EXISTING resolution machinery rather than rebuilding it:
`core/ecosystem/manifest.py` (load + validate the layer manifest),
`core/ecosystem/mirror.py` (subpath/mirror-checkout path synthesis —
shared with `cc resolve --explain`, so the two can never disagree about
WHERE a layer's content actually lives), `core/ecosystem/discovery.py`
(best-effort local content scan), and `core/ecosystem/resolver.py` (the
pure nearest-tier-wins fold). The one piece of new logic here is the
SUBSTANCE gate (`core/ecosystem/substance.py`): the resolver's fold
assumes the nearest declaring tier's content is real, and an inert
scaffold must not be allowed to shadow a farther tier's real content
merely by existing — see `resolve_claude_content()`'s docstring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, NamedTuple, Optional, Sequence

from cc.core.config import resolve_key
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers
from cc.core.ecosystem.mirror import synthesize_effective_layers
from cc.core.ecosystem.resolver import resolve_layers
from cc.core.ecosystem.substance import is_substantive

# Dimensions a project install ever asks the ladder to resolve. Framework
# scaffolding (fitness-check.sh, hooks, eval fixtures, the CLAUDE.md
# template) has no ladder concept — it always ships from the foundation
# root, same as before this module existed; see workspaces.py's `_claude_plan()`.
INSTALL_DIMENSIONS: tuple[str, ...] = ("agents", "commands")

# Sentinel distinguishing "no override passed" (auto-resolve via
# `resolve_key`) from an explicit `None` argument — same convention as
# `commands/resolve.py`'s `_UNSET`.
_UNSET: Any = object()


class ResolvedItem(NamedTuple):
    """One resolved `(dimension, item)`'s answer: where its content
    actually lives, which layer supplied it, and whether the ladder
    resolved it at all (`False` means: no manifest configured, no `claude`
    layers, or no tier declared this item — the pre-ladder foundation-root
    fallback applied instead)."""

    path: Path
    layer: str
    ladder_resolved: bool


def _find_item_child(dim_dir: Path, item: str) -> Optional[Path]:
    """Locate the on-disk file/dir for `item` under `dim_dir` — mirrors
    `discovery.py`'s own naming convention (a directory entry's name IS the
    item name; a file entry's *stem* is), so a resolved item always maps
    back to the exact file `discover_contributions()` found it as."""
    if not dim_dir.is_dir():
        return None
    direct_dir = dim_dir / item
    if direct_dir.is_dir():
        return direct_dir
    matches = sorted(path for path in dim_dir.glob(f"{item}.*") if path.is_file())
    if matches:
        return matches[0]
    direct_file = dim_dir / item
    if direct_file.is_file():
        return direct_file
    return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _chain_for(entry: dict[str, Any]) -> list[str]:
    """Nearest-first layer ids for one resolved item: the winner, then
    every shadowed layer in the resolver's own nearest-shadowed-first
    order (`resolver.py`'s `_resolve_override()`)."""
    return [entry["winning_layer"], *(shadow["layer"] for shadow in entry.get("shadowed") or ())]


def _select_substantive(
    entry: dict[str, Any], *, source_roots: Mapping[str, Path]
) -> Optional[tuple[str, Path]]:
    """
    Walk `entry`'s winner→shadowed chain nearest-first and return the first
    `(layer, path)` whose content is substantive (`substance.is_substantive`).

    An item whose bytes cannot be decoded as text (a non-markdown asset) is
    treated as substantive by construction — the placeholder heuristic
    (draft/TODO/undersized) is a prose check and has nothing to assert
    about binary content.

    Falls back to the FARTHEST resolved candidate in the chain (typically
    the foundation) if nothing passes the substance gate — this never
    drops an item the ladder found SOMETHING for; it only ever reorders
    which tier's copy of it applies. Returns `None` only when NO layer in
    the chain has the item's content on disk at all (the caller degrades
    to its own foundation-root fallback in that case).
    """
    dimension = entry["dimension"]
    item = entry["item"]

    candidates: list[tuple[str, Path]] = []
    for layer_id in _chain_for(entry):
        root = source_roots.get(layer_id)
        if root is None:
            continue
        child = _find_item_child(root / dimension, item)
        if child is not None:
            candidates.append((layer_id, child))

    for index, (layer_id, path) in enumerate(candidates):
        text = _read_text(path)
        if text is None:
            return layer_id, path  # binary/non-text content -- substance N/A

        shadow_size = 0
        for _next_layer, next_path in candidates[index + 1 :]:
            shadow_size = next_path.stat().st_size
            break

        if is_substantive(text, shadow_size=shadow_size):
            return layer_id, path

    return candidates[-1] if candidates else None


def resolve_claude_content(
    *,
    foundation_root: Path,
    items: Mapping[str, Sequence[str]],
    manifest_path: Any = _UNSET,
    mirror_root_base: Any = _UNSET,
    _layers: Optional[list[dict[str, Any]]] = None,
) -> dict[tuple[str, str], ResolvedItem]:
    """
    Resolve one source `Path` per requested `(dimension, item)` pair for
    the `claude` product, nearest SUBSTANTIVE tier wins — personal (rank
    10) › department (20) › organization (30) › foundation (40), matching
    `cc resolve --explain`'s own precedence (`core/ecosystem/resolver.py`).

    `items`: e.g. `{"commands": ["protocol", "continue"], "agents":
    [<roster names>]}` — the exact set `_claude_plan()` needs; this
    function never widens the search beyond what's asked for.

    Falls back to `foundation_root / ".claude" / <dimension> / "<item>.md"`
    (today's pre-ladder behavior, byte-for-byte) whenever: no manifest is
    configured (`layers.manifest`), the manifest has no `claude`-product
    layers, the manifest fails to load/validate, or a specific item is not
    declared by ANY tier in the manifest — so a machine with an
    incomplete or absent ladder degrades to exactly what shipped before
    this module existed, never a missing file and never a crash.

    PER-ARTIFACT, NOT PER-ROOT: resolution identity is `(dimension, item)`,
    exactly like the resolver it delegates to — if the organization tier
    declares 2 of the 16 roster agents and the foundation declares all 16,
    every requested item still resolves (the project gets 16), with only
    the organization's 2 overriding the foundation's versions of those two.

    THE PLACEHOLDER TRAP (live incident, 2026-08): naive nearest-tier-wins
    would let an org tier's `commands/protocol.md` scaffold — a `TODO(`
    stub reproducing the foundation's protocol underneath it, a stale fork
    besides — silently shadow the foundation's real protocol the moment a
    manifest is wired in. `_select_substantive()` walks the resolved
    winner/shadowed chain and skips any candidate that reads as an inert
    scaffold (`core/ecosystem/substance.py`), landing on the nearest tier
    that actually has real content — an empty or placeholder declaration
    can never win merely by being nearer.

    Never touches `~/.claude/cc/copilot.lock.json` (or any other lock):
    the lock is a point-in-time record of what a PRIOR `cc update` last
    materialized to the MACHINE root and can go stale (e.g. after a tier
    grows new content with no `cc update` run since); a project install
    always resolves against the LIVE content on disk, the same source of
    truth `cc resolve --explain` reports, so this path can never disagree
    with what a fresh `cc update` would also compute.
    """
    resolved: dict[tuple[str, str], ResolvedItem] = {}

    def _fallback(dimension: str, item: str) -> ResolvedItem:
        return ResolvedItem(
            path=foundation_root / ".claude" / dimension / f"{item}.md",
            layer="<foundation-root>",
            ladder_resolved=False,
        )

    for dimension, names in items.items():
        for item in names:
            resolved[(dimension, item)] = _fallback(dimension, item)

    if _layers is not None:
        layers = _layers
    else:
        path = manifest_path if manifest_path is not _UNSET else resolve_key("layers.manifest")
        if not path:
            return resolved
        try:
            layers = load_layers(path)
        except ManifestError:
            return resolved

    claude_layers = [layer for layer in layers if layer.get("product") == "claude"]
    if not claude_layers:
        return resolved

    try:
        validate_layers(claude_layers)
        base = (
            Path(mirror_root_base).expanduser()
            if mirror_root_base is not _UNSET
            else Path(str(resolve_key("paths.mirrors_root"))).expanduser()
        )
        effective_layers = synthesize_effective_layers(claude_layers, mirror_root_base=base)
    except ManifestError:
        return resolved

    source_roots: dict[str, Path] = {}
    for layer in effective_layers:
        raw_path = (layer.get("source") or {}).get("path")
        if raw_path:
            source_roots[layer["id"]] = Path(str(raw_path)).expanduser()

    contributions = discover_contributions(effective_layers, dimensions=INSTALL_DIMENSIONS)
    try:
        resolved_set = resolve_layers(effective_layers, contributions)
    except ManifestError:
        return resolved

    by_key = {(entry["dimension"], entry["item"]): entry for entry in resolved_set}
    for dimension, names in items.items():
        for item in names:
            entry = by_key.get((dimension, item))
            if entry is None:
                continue
            winner = _select_substantive(entry, source_roots=source_roots)
            if winner is None:
                continue
            layer_id, path = winner
            resolved[(dimension, item)] = ResolvedItem(
                path=path, layer=layer_id, ladder_resolved=True
            )

    return resolved
