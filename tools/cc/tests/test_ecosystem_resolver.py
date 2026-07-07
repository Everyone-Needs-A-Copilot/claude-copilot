"""Pure unit matrix for cc.core.ecosystem.resolver.resolve_layers().

Every test here is 100% in-memory (layer dicts + contribution/lockfile
dicts) -- no filesystem, no network, no ~/.claude. This is the bulk of the
WS-A resolve-slice coverage per the resolver being a PURE fold.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.ecosystem.manifest import ManifestError
from cc.core.ecosystem.resolver import resolve_layers


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "resolver test attempted to resolve Path.home() -- resolver is pure, "
            "inject data instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _layer(layer_id: str, rank: int, role: str = "org", product: str = "claude", **extra) -> dict:
    layer = {
        "id": layer_id,
        "role": role,
        "rank": rank,
        "product": product,
        "source": {"repo": f"https://example.invalid/{layer_id}.git"},
        "auth": "anon",
        "activation": "always",
    }
    layer.update(extra)
    return layer


FOUR_TIER_LAYERS = [
    _layer("personal-pablo", 10, role="personal", product="claude"),
    _layer("dept-engineering", 20, role="department", product="claude", unit="engineering"),
    _layer("org-acme", 30, role="org", product="claude"),
    _layer("foundation", 40, role="foundation", product="claude"),
]


def _by_item(items, item_name, dimension=None):
    matches = [
        entry
        for entry in items
        if entry["item"] == item_name
        and (dimension is None or entry["dimension"] == dimension)
    ]
    assert matches, f"no resolved item named {item_name!r} (dimension={dimension})"
    return matches[0]


# ---------------------------------------------------------------------------
# override dimension: nearest-layer-wins + shadow chain
# ---------------------------------------------------------------------------


def test_override_nearest_layer_wins():
    contributions = {
        "personal-pablo": {"skills": {"qa": "sha-personal"}},
        "dept-engineering": {"skills": {"qa": "sha-dept"}},
        "org-acme": {"skills": {"qa": "sha-org"}},
        "foundation": {"skills": {"qa": "sha-foundation"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    qa = _by_item(items, "qa", "skills")
    assert qa["winning_layer"] == "personal-pablo"


def test_override_shadow_chain_is_full_and_ordered_nearest_first():
    contributions = {
        "personal-pablo": {"skills": {"qa": "sha-personal"}},
        "dept-engineering": {"skills": {"qa": "sha-dept"}},
        "org-acme": {"skills": {"qa": "sha-org"}},
        "foundation": {"skills": {"qa": "sha-foundation"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    qa = _by_item(items, "qa", "skills")
    shadow_layers = [s["layer"] for s in qa["shadowed"]]
    assert shadow_layers == ["dept-engineering", "org-acme", "foundation"]


def test_override_item_only_present_in_lower_layers_still_resolves():
    """An item never overridden by personal/dept still resolves to whichever
    layer actually contributes it (org here), with an empty shadow chain
    below it (nothing further down contributes)."""
    contributions = {
        "org-acme": {"agents": {"deploy": "sha-org"}},
        "foundation": {"agents": {"deploy": "sha-foundation"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    deploy = _by_item(items, "deploy", "agents")
    assert deploy["winning_layer"] == "org-acme"
    assert [s["layer"] for s in deploy["shadowed"]] == ["foundation"]


def test_override_item_only_in_one_layer_has_no_shadow():
    contributions = {"foundation": {"commands": {"env": "sha-foundation"}}}
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    env = _by_item(items, "env", "commands")
    assert env["winning_layer"] == "foundation"
    assert env["shadowed"] == []


# ---------------------------------------------------------------------------
# product: CARRIED metadata from the winning layer, resolution unchanged
# ---------------------------------------------------------------------------


def test_override_item_carries_winning_layers_product():
    """`product` on a resolved item is copied from the WINNING layer's own
    `product` field -- never re-derived, never resolved."""
    layers = [
        _layer("personal-pablo", 10, role="personal", product="claude"),
        _layer("dept-engineering", 20, role="department", product="knowledge", unit="engineering"),
        _layer("org-acme", 30, role="org", product="cli"),
        _layer("foundation", 40, role="foundation", product="codex"),
    ]
    contributions = {
        "dept-engineering": {"skills": {"qa": "sha-dept"}},
        "org-acme": {"skills": {"qa": "sha-org"}},
        "foundation": {"skills": {"qa": "sha-foundation"}},
    }
    items = resolve_layers(layers, contributions)
    qa = _by_item(items, "qa", "skills")
    assert qa["winning_layer"] == "dept-engineering"
    assert qa["product"] == "knowledge"


def test_accumulate_items_each_carry_their_own_contributing_layers_product():
    layers = [
        _layer("dept-engineering", 20, role="department", product="knowledge", unit="engineering"),
        _layer("org-acme", 30, role="org", product="cli"),
        _layer("foundation", 40, role="foundation", product="claude"),
    ]
    contributions = {
        "dept-engineering": {"knowledge": {"deploy-runbook": "sha-d"}},
        "org-acme": {"knowledge": {"onboarding": "sha-o"}},
        "foundation": {"knowledge": {"framework-docs": "sha-f"}},
    }
    items = resolve_layers(layers, contributions)
    by_item = {entry["item"]: entry["product"] for entry in items}
    assert by_item == {
        "deploy-runbook": "knowledge",
        "onboarding": "cli",
        "framework-docs": "claude",
    }


def test_override_shadowed_entries_carry_their_own_product_too():
    layers = [
        _layer("personal-pablo", 10, role="personal", product="claude"),
        _layer("org-acme", 30, role="org", product="knowledge"),
    ]
    contributions = {
        "personal-pablo": {"skills": {"qa": "sha-personal"}},
        "org-acme": {"skills": {"qa": "sha-org"}},
    }
    items = resolve_layers(layers, contributions)
    qa = _by_item(items, "qa", "skills")
    org_shadow = next(s for s in qa["shadowed"] if s["layer"] == "org-acme")
    assert org_shadow["product"] == "knowledge"


# ---------------------------------------------------------------------------
# accumulate dimension: every contributor is its own entry, ordered
# ---------------------------------------------------------------------------


def test_accumulate_every_layer_contributes_its_own_entry():
    contributions = {
        "personal-pablo": {"knowledge": {"tax-notes": "sha-p"}},
        "dept-engineering": {"knowledge": {"deploy-runbook": "sha-d"}},
        "org-acme": {"knowledge": {"onboarding": "sha-o"}},
        "foundation": {"knowledge": {"framework-docs": "sha-f"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    knowledge_items = [entry for entry in items if entry["dimension"] == "knowledge"]
    assert len(knowledge_items) == 4
    assert all(entry["shadowed"] == [] for entry in knowledge_items)


def test_accumulate_ordering_is_nearest_layer_first():
    """Same-named knowledge item contributed by multiple layers accumulates
    as separate entries (never shadowed), ordered nearest-rank-first."""
    contributions = {
        "personal-pablo": {"knowledge": {"qa": "sha-p"}},
        "dept-engineering": {"knowledge": {"qa": "sha-d"}},
        "org-acme": {"knowledge": {"qa": "sha-o"}},
        "foundation": {"knowledge": {"qa": "sha-f"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    qa_entries = [
        entry
        for entry in items
        if entry["dimension"] == "knowledge" and entry["item"] == "qa"
    ]
    assert [entry["winning_layer"] for entry in qa_entries] == [
        "personal-pablo",
        "dept-engineering",
        "org-acme",
        "foundation",
    ]
    assert all(entry["shadowed"] == [] for entry in qa_entries)


def test_project_local_dimension_is_skipped_entirely():
    """`tasks` is project-local (not tiered) -- the resolver must not emit
    resolved entries for it at all."""
    contributions = {"personal-pablo": {"tasks": {"todo": "sha-p"}}}
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    assert items == []


# ---------------------------------------------------------------------------
# winning_sha sourced from the lockfile; null when unavailable
# ---------------------------------------------------------------------------


def test_winning_sha_comes_from_lockfile():
    contributions = {"foundation": {"agents": {"sec": "live-sha"}}}
    lockfile = {"foundation": {"agents": {"sec": "recorded-sha"}}}
    items = resolve_layers(FOUR_TIER_LAYERS, contributions, lockfile=lockfile)
    sec = _by_item(items, "sec", "agents")
    assert sec["winning_sha"] == "recorded-sha"


def test_winning_sha_is_null_when_lockfile_has_no_entry():
    contributions = {"foundation": {"agents": {"sec": "live-sha"}}}
    items = resolve_layers(FOUR_TIER_LAYERS, contributions, lockfile={})
    sec = _by_item(items, "sec", "agents")
    assert sec["winning_sha"] is None


def test_winning_sha_is_null_when_no_lockfile_given_at_all():
    contributions = {"foundation": {"agents": {"sec": "live-sha"}}}
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    sec = _by_item(items, "sec", "agents")
    assert sec["winning_sha"] is None


# ---------------------------------------------------------------------------
# fail-closed security fields
# ---------------------------------------------------------------------------


def test_fail_closed_fields_never_fabricated():
    contributions = {"foundation": {"agents": {"sec": "live-sha"}}}
    items = resolve_layers(FOUR_TIER_LAYERS, contributions)
    sec = _by_item(items, "sec", "agents")
    assert sec["signer_of_introducing_commit"] is None
    assert sec["live_hash_matches"] is False


# ---------------------------------------------------------------------------
# override-stale detection (ecosystem-architecture.md §7.4)
# ---------------------------------------------------------------------------


def test_override_stale_flagged_when_shadowed_upstream_moved():
    """Personal overrides org `qa`; org's live content has moved since the
    last recorded (lockfile) sha for org -- the shadowed org entry must be
    flagged stale."""
    contributions = {
        "personal-pablo": {"skills": {"qa": "sha-personal"}},
        "org-acme": {"skills": {"qa": "sha-org-NEW"}},
    }
    lockfile = {
        "org-acme": {"skills": {"qa": "sha-org-OLD"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions, lockfile=lockfile)
    qa = _by_item(items, "qa", "skills")
    org_shadow = next(s for s in qa["shadowed"] if s["layer"] == "org-acme")
    assert org_shadow["stale"] is True
    assert org_shadow["recorded_sha"] == "sha-org-OLD"
    assert org_shadow["current_sha"] == "sha-org-NEW"


def test_override_not_stale_when_shadowed_upstream_unchanged():
    contributions = {
        "personal-pablo": {"skills": {"qa": "sha-personal"}},
        "org-acme": {"skills": {"qa": "sha-org-SAME"}},
    }
    lockfile = {
        "org-acme": {"skills": {"qa": "sha-org-SAME"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions, lockfile=lockfile)
    qa = _by_item(items, "qa", "skills")
    org_shadow = next(s for s in qa["shadowed"] if s["layer"] == "org-acme")
    assert org_shadow["stale"] is False


def test_override_not_stale_when_no_recorded_sha_to_compare():
    """No prior lockfile entry for the shadowed layer -- there is nothing to
    compare against, so it must NOT be reported stale (unknown != changed)."""
    contributions = {
        "personal-pablo": {"skills": {"qa": "sha-personal"}},
        "org-acme": {"skills": {"qa": "sha-org-NEW"}},
    }
    items = resolve_layers(FOUR_TIER_LAYERS, contributions, lockfile={})
    qa = _by_item(items, "qa", "skills")
    org_shadow = next(s for s in qa["shadowed"] if s["layer"] == "org-acme")
    assert org_shadow["stale"] is False


# ---------------------------------------------------------------------------
# equal-rank hard-error, propagated from manifest validation
# ---------------------------------------------------------------------------


def test_equal_rank_hard_errors_before_folding_anything():
    layers = [
        _layer("dept-a", 20, role="department"),
        _layer("dept-b", 20, role="department"),
    ]
    with pytest.raises(ManifestError, match="rank 20"):
        resolve_layers(layers, contributions={})


# ---------------------------------------------------------------------------
# arity independence -- N layers beyond 4, no hardcoded tier count
# ---------------------------------------------------------------------------


def test_resolver_is_arity_independent_beyond_four_tiers():
    layers = [
        _layer("squad", 5, role="squad", product="cli"),
        _layer("personal-pablo", 10, role="personal", product="claude"),
        _layer("dept-engineering", 20, role="department", product="claude"),
        _layer("dept-platform", 21, role="department", product="claude"),
        _layer("org-acme", 30, role="org", product="claude"),
        _layer("foundation", 40, role="foundation", product="claude"),
    ]
    contributions = {
        "squad": {"skills": {"qa": "sha-squad"}},
        "personal-pablo": {"skills": {"qa": "sha-personal"}},
        "dept-engineering": {"skills": {"qa": "sha-dept-eng"}},
        "dept-platform": {"skills": {"qa": "sha-dept-platform"}},
        "org-acme": {"skills": {"qa": "sha-org"}},
        "foundation": {"skills": {"qa": "sha-foundation"}},
    }
    items = resolve_layers(layers, contributions)
    qa = _by_item(items, "qa", "skills")
    assert qa["winning_layer"] == "squad"
    assert qa["product"] == "cli"
    assert [s["layer"] for s in qa["shadowed"]] == [
        "personal-pablo",
        "dept-engineering",
        "dept-platform",
        "org-acme",
        "foundation",
    ]
