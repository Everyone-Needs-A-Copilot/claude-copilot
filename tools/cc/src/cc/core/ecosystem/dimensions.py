"""The override/accumulate semantics table, AS DATA.

Source of truth: copilot-control-tower/docs/reference/ecosystem-architecture.md
§3.1 "The authoritative resolution-semantics matrix". Rows are dimensions;
the matrix shows semantics is per-DIMENSION, not per (dimension, tier) pair
today (every tier applies the same fold for a given dimension) — so this is
a flat dimension -> semantics table, not a 2-D matrix. If a future tier ever
needs a *different* fold for the same dimension, this table is the seam to
extend (add a per-layer-role override), not a reason to hardcode tiers.
"""

from __future__ import annotations

# --- Semantics values -------------------------------------------------------

OVERRIDE = "override"
ACCUMULATE = "accumulate"
ACCUMULATE_READ = "accumulate-read"
PERSONAL_WRITE = "personal-write"
PROJECT_LOCAL = "project-local"

# --- The table (ecosystem-architecture.md §3.1) -----------------------------

DIMENSION_SEMANTICS: dict[str, str] = {
    "agents": OVERRIDE,
    "skills": OVERRIDE,
    "commands": OVERRIDE,
    "protocol": OVERRIDE,
    "knowledge": ACCUMULATE,
    "memory": PERSONAL_WRITE,
    "tasks": PROJECT_LOCAL,
    "cli-integrations": OVERRIDE,
    # Codex-native distributable unit. A plugin stays atomic so its manifest,
    # skills, hooks, and assets cannot be resolved from different layers.
    "plugins": OVERRIDE,
}

# --- Groupings the resolver folds by ----------------------------------------

# "nearest layer wins, every other contributor is reported in shadowed[]"
OVERRIDE_LIKE: frozenset[str] = frozenset({OVERRIDE, PERSONAL_WRITE})

# "every contributing layer's copy is its own resolved entry, ordered
# nearest-first — nothing is shadowed"
ACCUMULATE_LIKE: frozenset[str] = frozenset({ACCUMULATE, ACCUMULATE_READ})

# bound to the working tree, not tiered — the resolver skips these entirely
NOT_TIERED: frozenset[str] = frozenset({PROJECT_LOCAL})


def semantics_for(dimension: str, table: dict[str, str] | None = None) -> str:
    """
    Return the fold semantics for `dimension`.

    Unknown dimensions (not present in the table) default to OVERRIDE — the
    conservative choice: a dimension that silently accumulated when it
    should have overridden could leak or duplicate content, whereas
    defaulting an unrecognized dimension to override only ever shadows an
    extra copy (safe failure mode).
    """
    return (table or DIMENSION_SEMANTICS).get(dimension, OVERRIDE)
