"""Load + validate the ecosystem layer manifest (`copilot.layers.yml`).

Manifest shape: copilot-control-tower/docs/reference/four-tier-topology.md
§4. Accepts EITHER a path to a YAML manifest file OR an in-memory list of
layer dicts, so tests and callers can supply layers directly without a real
file on disk (the manifest need not exist yet for the resolver to be
exercised).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Layer shape (four-tier-topology.md §4):
#   {id, role, rank, product, unit?, source:{repo, ref, path?}, auth, activation}
# `unit` is optional (only meaningful for role="department"); everything
# else is required. `product` is a required, non-empty, config-driven
# string (e.g. "knowledge" | "cli" | "claude" | "codex" -- not a closed
# enum, adding a fifth product is a data edit, not a schema change). It is
# part of resolution identity: ranks and named items compete only inside
# one product stack. A layer belongs to exactly one product x tier.
REQUIRED_LAYER_FIELDS: tuple[str, ...] = (
    "id",
    "role",
    "rank",
    "product",
    "source",
    "auth",
    "activation",
)


class ManifestError(ValueError):
    """A layer manifest failed to load or validate.

    Message is always plain language (what's wrong + how to fix it), never
    a stack trace — callers (the CLI) print `str(exc)` directly to the
    user.
    """


def load_layers(source: Path | str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Load the raw layer list from either:
      - a list of layer dicts (already parsed — tests/callers pass data in
        directly, no file required), or
      - a path to a `copilot.layers.yml` file (`version: 1, layers: [...]`).

    Does NOT validate the result — call `validate_layers()` (or use
    `resolver.resolve_layers()`, which validates internally) before relying
    on the returned layers.
    """
    if isinstance(source, list):
        return [dict(layer) for layer in source]

    path = Path(source).expanduser()
    if not path.exists():
        raise ManifestError(
            f"Layer manifest not found: {path}\n"
            "Expected a copilot.layers.yml. If one doesn't exist yet, set "
            "`layers.manifest` once it does (`cc config set layers.manifest <path>`)."
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ManifestError(
            f"Layer manifest at {path} is not valid YAML: {exc}"
        ) from exc

    if not isinstance(raw, dict) or "layers" not in raw:
        raise ManifestError(
            f"Layer manifest at {path} must be a mapping with a top-level `layers:` list "
            "(e.g. `version: 1\\nlayers:\\n  - id: ...`)."
        )

    layers = raw["layers"]
    if not isinstance(layers, list):
        raise ManifestError(
            f"Layer manifest at {path}: `layers` must be a list, got {type(layers).__name__}."
        )

    return [dict(layer) for layer in layers]


def validate_layers(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Validate layer manifest invariants (four-tier-topology.md §4):

      - at least one layer is declared
      - every layer has all of REQUIRED_LAYER_FIELDS, non-empty
      - `role` is a non-empty string (open vocabulary — not a closed enum)
      - `product` is a non-empty string (config-driven — not a closed enum)
      - `rank` is an integer
      - ranks are UNIQUE WITHIN EACH PRODUCT — Claude rank 10 and Codex
        rank 10 may coexist, but two Claude layers at rank 10 hard-error
      - manifest list order agrees with ascending rank within each product
        stack (different product stacks may be interleaved)
      - layer ids are globally unique because contribution and lock maps
        use the id as their key
      - `source` is an object with at least a `repo` key

    Returns the same list, unchanged, on success — so callers can chain
    `validate_layers(load_layers(path))`. Raises ManifestError on any
    violation.
    """
    if not layers:
        raise ManifestError(
            "Layer manifest has no layers declared — nothing to resolve."
        )

    seen_ids: set[str] = set()
    seen_ranks: dict[str, dict[int, str]] = {}
    previous_rank: dict[str, int] = {}

    for idx, layer in enumerate(layers):
        layer_id = layer.get("id") or f"<unnamed layer at position {idx}>"

        missing = [
            field
            for field in REQUIRED_LAYER_FIELDS
            if field not in layer or layer[field] in (None, "")
        ]
        if missing:
            raise ManifestError(
                f"Layer {layer_id!r} is missing required field(s): {', '.join(missing)}. "
                f"Every layer needs: {', '.join(REQUIRED_LAYER_FIELDS)}."
            )

        role = layer["role"]
        if not isinstance(role, str) or not role.strip():
            raise ManifestError(
                f"Layer {layer_id!r} has an empty or non-string `role`."
            )

        product = layer["product"]
        if not isinstance(product, str) or not product.strip():
            raise ManifestError(
                f"Layer {layer_id!r} has an empty or non-string `product`. "
                "Every layer must declare which product it belongs to "
                "(e.g. 'knowledge', 'cli', 'claude', 'codex')."
            )

        if layer_id in seen_ids:
            raise ManifestError(
                f"Layer id {layer_id!r} is declared more than once. "
                "Layer ids must be globally unique."
            )
        seen_ids.add(layer_id)

        rank = layer["rank"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ManifestError(
                f"Layer {layer_id!r} has a non-integer `rank`: {rank!r}. "
                "Ranks must be whole numbers (lower number = higher precedence)."
            )

        product_ranks = seen_ranks.setdefault(product, {})
        if rank in product_ranks:
            raise ManifestError(
                f"Layers {product_ranks[rank]!r} and {layer_id!r} both declare "
                f"rank {rank} for product {product!r}. Ranks must be unique "
                "inside a product — give one of them a different rank "
                "(gaps of 10 are recommended so a new layer can be inserted later without renumbering)."
            )
        product_ranks[rank] = layer_id

        prev_rank = previous_rank.get(product)
        if prev_rank is not None and rank <= prev_rank:
            raise ManifestError(
                f"Layer {layer_id!r} (rank {rank}) is out of order for product "
                f"{product!r}: that product's layers must appear in ascending "
                f"rank order, but its previous layer had rank {prev_rank}. "
                "Reorder that product's layers so rank increases top-to-bottom "
                "(highest precedence first)."
            )
        previous_rank[product] = rank

        source = layer["source"]
        if not isinstance(source, dict) or not source.get("repo"):
            raise ManifestError(
                f"Layer {layer_id!r} `source` must be an object with at least a `repo` key."
            )

    return layers
