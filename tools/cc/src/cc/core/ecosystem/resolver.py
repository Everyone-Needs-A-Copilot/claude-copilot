"""The resolver: a PURE product-scoped fold over a ranked layer manifest.

No I/O, no filesystem, no network — every input (layers, contributions,
lockfile) is a plain in-memory data structure the caller supplies. Real
callers assemble those from disk/git via manifest.py / discovery.py /
lockfile.py; this module never touches any of that itself
(ecosystem-architecture.md §3: "load the manifest, sort layers by rank, and
per PRODUCT and DIMENSION apply that dimension's semantics").

Arity-independent by construction: the fold is `for layer in ranked layers`
with no hardcoded tier count (four-tier-topology.md §3: "the resolver walk
... only the loop bound changes; no '3' anywhere").
"""

from __future__ import annotations

from typing import Any, Optional

from cc.core.ecosystem.dimensions import (
    ACCUMULATE_LIKE,
    DIMENSION_SEMANTICS,
    NOT_TIERED,
    semantics_for,
)
from cc.core.ecosystem.manifest import validate_layers

Layer = dict[str, Any]
# layer_id -> dimension -> item name -> live/current content sha (or None)
Contributions = dict[str, dict[str, dict[str, Optional[str]]]]
# layer_id -> dimension -> item name -> last-recorded/pinned sha
Lockfile = dict[str, dict[str, dict[str, str]]]


def _rank_sorted(layers: list[Layer]) -> list[Layer]:
    """Sort one product stack by rank after manifest validation."""
    return sorted(layers, key=lambda layer: layer["rank"])


def _product_stacks(layers: list[Layer]) -> list[tuple[str, list[Layer]]]:
    """Group layers by product, preserving first product appearance.

    Rank precedence is meaningful only inside a product. Keeping product
    order manifest-driven makes output stable without hardcoding a product
    vocabulary.
    """
    stacks: dict[str, list[Layer]] = {}
    for layer in layers:
        stacks.setdefault(layer["product"], []).append(layer)
    return [(product, _rank_sorted(stack)) for product, stack in stacks.items()]


def _recorded_sha(
    lockfile: Lockfile, layer_id: str, dimension: str, item: str
) -> Optional[str]:
    return lockfile.get(layer_id, {}).get(dimension, {}).get(item)


def _make_item(
    *,
    item: str,
    dimension: str,
    product: str,
    winning_layer: str,
    winning_sha: Optional[str],
    shadowed: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "item": item,
        "dimension": dimension,
        "product": product,
        "winning_layer": winning_layer,
        "winning_sha": winning_sha,
        "shadowed": shadowed,
        # Fail-closed (this slice): signature-verify and materialize have
        # not landed yet. NEVER fabricate "signed"/"matches" here — these
        # two fields become real once the policy/materialize modules exist
        # (see cc/commands/resolve.py's module docstring).
        "signer_of_introducing_commit": None,
        "live_hash_matches": False,
    }


def _contributing_layers(
    dimension: str, ranked: list[Layer], contributions: Contributions
) -> list[Layer]:
    return [
        layer for layer in ranked if dimension in contributions.get(layer["id"], {})
    ]


def _resolve_accumulate(
    dimension: str,
    ranked: list[Layer],
    contributions: Contributions,
    lockfile: Lockfile,
) -> list[dict[str, Any]]:
    """Every contributing layer's copy of an item is its OWN resolved entry,
    ordered nearest-layer-first — nothing is shadowed (ecosystem-architecture
    .md §3.1: "accumulate = all tiers contribute, ordered")."""
    results: list[dict[str, Any]] = []
    for layer in ranked:
        layer_items = contributions.get(layer["id"], {}).get(dimension, {})
        for item in sorted(layer_items):
            results.append(
                _make_item(
                    item=item,
                    dimension=dimension,
                    product=layer["product"],
                    winning_layer=layer["id"],
                    winning_sha=_recorded_sha(lockfile, layer["id"], dimension, item),
                    shadowed=[],
                )
            )
    return results


def _resolve_override(
    dimension: str,
    ranked: list[Layer],
    contributions: Contributions,
    lockfile: Lockfile,
) -> list[dict[str, Any]]:
    """Nearest-rank (highest-precedence) contributing layer wins per named
    item; every other contributing layer is reported in `shadowed[]`,
    nearest-shadowed first.

    Also implements override-stale detection (ecosystem-architecture.md
    §7.4): for each shadowed layer, if its live/current content sha differs
    from its own last-recorded lockfile sha, that shadowed entry is flagged
    `stale: true` — "a personal override whose shadowed upstream has
    moved" (the upstream layer's content has since changed since it was
    last resolved).
    """
    contributing = _contributing_layers(dimension, ranked, contributions)
    item_names = sorted(
        {
            item
            for layer in contributing
            for item in contributions[layer["id"]][dimension]
        }
    )

    results: list[dict[str, Any]] = []
    for item in item_names:
        chain = [
            layer
            for layer in contributing
            if item in contributions[layer["id"]][dimension]
        ]
        winner, *shadow_layers = (
            chain  # `contributing` is ranked ascending -> first = nearest = winner
        )

        shadowed: list[dict[str, Any]] = []
        for shadow in shadow_layers:
            live_sha = contributions[shadow["id"]][dimension].get(item)
            recorded_sha = _recorded_sha(lockfile, shadow["id"], dimension, item)
            stale = bool(live_sha and recorded_sha and live_sha != recorded_sha)
            shadowed.append(
                {
                    "layer": shadow["id"],
                    "rank": shadow["rank"],
                    "product": shadow.get("product"),
                    "recorded_sha": recorded_sha,
                    "current_sha": live_sha,
                    "stale": stale,
                }
            )

        results.append(
            _make_item(
                item=item,
                dimension=dimension,
                product=winner["product"],
                winning_layer=winner["id"],
                winning_sha=_recorded_sha(lockfile, winner["id"], dimension, item),
                shadowed=shadowed,
            )
        )
    return results


def resolve_layers(
    layers: list[Layer],
    contributions: Contributions,
    *,
    lockfile: Optional[Lockfile] = None,
    dimension_semantics: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """
    Fold `contributions` over `layers` into the resolved item set.

    Per item: `{item, dimension, product, winning_layer, winning_sha,
    shadowed[], signer_of_introducing_commit, live_hash_matches}` — matches
    resolve.schema.json's per-item shape. `product` is CARRIED metadata
    copied from the winning layer's own `product` field (manifest.py) —
    the fold itself is unchanged; product is copied, never resolved.

    Raises `ManifestError` (via `validate_layers`) on an invalid manifest —
    including the equal-rank hard-error — before folding anything.

    Resolution identity is `(product, dimension, item)`. Same-named items
    in different products coexist and never appear in each other's shadow
    chain. Ranks compete only inside one product stack.

    `winning_sha` is sourced from `lockfile` and is `None` when the
    lockfile has no recorded sha for that (layer, dimension, item) —
    e.g. a first-run machine with no `copilot.lock` yet.
    """
    validate_layers(layers)
    lockfile = lockfile or {}
    semantics_table = dimension_semantics or DIMENSION_SEMANTICS

    items: list[dict[str, Any]] = []
    for _product, ranked in _product_stacks(layers):
        layer_ids = {layer["id"] for layer in ranked}
        dimensions = sorted(
            {
                dimension
                for layer_id, layer_contributions in contributions.items()
                if layer_id in layer_ids
                for dimension in layer_contributions
            }
        )
        for dimension in dimensions:
            semantics = semantics_for(dimension, semantics_table)
            if semantics in NOT_TIERED:
                continue  # e.g. "tasks": project-local, not part of the layer stack
            if semantics in ACCUMULATE_LIKE:
                items.extend(
                    _resolve_accumulate(dimension, ranked, contributions, lockfile)
                )
            else:
                items.extend(
                    _resolve_override(dimension, ranked, contributions, lockfile)
                )

    return items
