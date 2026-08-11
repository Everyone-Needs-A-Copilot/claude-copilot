"""Tests for cc.core.ecosystem.project_sources — resolving a project
install's `claude` product content (protocol/commands + agents) through
the personal -> department -> organization -> foundation tier ladder,
nearest SUBSTANTIVE tier wins. This is the wiring
`core/ecosystem/workspaces.py`'s `_claude_plan()` was missing.

Every layer root here is a tmp_path fixture directory; nothing touches the
network or a real ~/.claude. `Path.home()` is poisoned (mirrors
test_ecosystem_discovery.py / test_resolve_contract.py's own posture) so a
test can never accidentally fall through to real machine config.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.ecosystem.project_sources import resolve_claude_content


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "project_sources test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _claude_layer(layer_id: str, *, role: str, rank: int, path: Path, subpath: str | None = None) -> dict:
    source = {"repo": f"https://example.invalid/{layer_id}.git", "path": str(path)}
    if subpath is not None:
        source["subpath"] = subpath
    return {
        "id": layer_id,
        "role": role,
        "rank": rank,
        "product": "claude",
        "source": source,
        "auth": "anon",
        "activation": "always",
    }


def _write(root: Path, dimension: str, item: str, text: str) -> None:
    target = root / dimension / f"{item}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fallback (pre-ladder) behavior -- never a missing file, never a crash
# ---------------------------------------------------------------------------


def test_no_manifest_falls_back_to_foundation_root_byte_for_byte(tmp_path):
    foundation_root = tmp_path / "foundation-checkout"
    _write(foundation_root / ".claude", "commands", "protocol", "foundation protocol")

    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        manifest_path=None,
    )

    item = resolved[("commands", "protocol")]
    assert item.path == foundation_root / ".claude" / "commands" / "protocol.md"
    assert item.ladder_resolved is False


def test_no_claude_product_layers_falls_back(tmp_path):
    foundation_root = tmp_path / "foundation-checkout"
    other_root = tmp_path / "knowledge-org"
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        _layers=[_claude_layer("knowledge-org", role="organization", rank=30, path=other_root) | {"product": "knowledge"}],
    )
    assert resolved[("commands", "protocol")].ladder_resolved is False


def test_broken_manifest_path_degrades_to_fallback(tmp_path):
    foundation_root = tmp_path / "foundation-checkout"
    broken = tmp_path / "not-a-real-manifest.yml"
    broken.write_text(": : not valid yaml : :", encoding="utf-8")

    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        manifest_path=broken,
    )
    assert resolved[("commands", "protocol")].ladder_resolved is False


def test_item_not_declared_by_any_tier_falls_back_to_foundation_root(tmp_path):
    foundation_root = tmp_path / "foundation-checkout"
    _write(foundation_root, "commands", "protocol", "foundation protocol")

    layers = [_claude_layer("foundation", role="foundation", rank=40, path=foundation_root)]
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol", "continue")},  # "continue" declared nowhere
        _layers=layers,
    )
    assert resolved[("commands", "continue")].ladder_resolved is False
    assert (
        resolved[("commands", "continue")].path
        == foundation_root / ".claude" / "commands" / "continue.md"
    )


# ---------------------------------------------------------------------------
# Per-artifact nearest-wins (requirement 1: NOT per-root)
# ---------------------------------------------------------------------------


def test_per_artifact_nearest_wins_not_per_root(tmp_path):
    """The organization tier overrides only ONE of two requested agents;
    the project still gets both -- the org's one item overriding the
    foundation's version of THAT item, never shrinking the set to just
    what the org declares."""
    foundation_root = tmp_path / "foundation-checkout"
    org_root = tmp_path / "org-checkout"
    _write(foundation_root, "agents", "cw", "foundation cw content, real and substantive")
    _write(foundation_root, "agents", "qa", "foundation qa content, real and substantive")
    _write(org_root, "agents", "cw", "organization's OWN cw override, real and substantive")

    layers = [
        _claude_layer("org", role="organization", rank=30, path=org_root),
        _claude_layer("foundation", role="foundation", rank=40, path=foundation_root),
    ]
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"agents": ("cw", "qa")},
        _layers=layers,
    )

    cw = resolved[("agents", "cw")]
    qa = resolved[("agents", "qa")]
    assert cw.ladder_resolved is True and cw.layer == "org"
    assert cw.path.read_text(encoding="utf-8") == "organization's OWN cw override, real and substantive"
    assert qa.ladder_resolved is True and qa.layer == "foundation"


# ---------------------------------------------------------------------------
# The placeholder trap (requirement 2): an empty/inert nearer tier must
# never shadow real upstream content.
# ---------------------------------------------------------------------------


def test_todo_placeholder_in_nearer_tier_does_not_win(tmp_path):
    foundation_root = tmp_path / "foundation-checkout"
    org_root = tmp_path / "org-checkout"
    real_protocol = "# Protocol\n\n" + ("Real instructions. " * 200)
    _write(foundation_root, "commands", "protocol", real_protocol)
    _write(
        org_root,
        "commands",
        "protocol",
        "TODO(pablo): this section is currently a no-op placeholder.\n\n" + real_protocol,
    )

    layers = [
        _claude_layer("org", role="organization", rank=30, path=org_root),
        _claude_layer("foundation", role="foundation", rank=40, path=foundation_root),
    ]
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        _layers=layers,
    )

    item = resolved[("commands", "protocol")]
    assert item.ladder_resolved is True
    assert item.layer == "foundation"
    assert item.path.read_text(encoding="utf-8") == real_protocol


def test_empty_file_in_nearer_tier_does_not_win(tmp_path):
    """The literal negative case the fix must prove: an EMPTY placeholder
    (no TODO marker, no draft frontmatter -- just disproportionately
    smaller than what it would shadow) still must not win merely by being
    nearer."""
    foundation_root = tmp_path / "foundation-checkout"
    org_root = tmp_path / "org-checkout"
    real_protocol = "# Protocol\n\n" + ("Real instructions. " * 200)
    _write(foundation_root, "commands", "protocol", real_protocol)
    _write(org_root, "commands", "protocol", "")  # empty placeholder

    layers = [
        _claude_layer("org", role="organization", rank=30, path=org_root),
        _claude_layer("foundation", role="foundation", rank=40, path=foundation_root),
    ]
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        _layers=layers,
    )

    item = resolved[("commands", "protocol")]
    assert item.layer == "foundation"
    assert item.path.read_text(encoding="utf-8") == real_protocol


def test_real_substantive_override_does_win(tmp_path):
    """The positive counterpart: once the org tier's content is real (no
    TODO marker, not draft, not undersized), nearest-wins applies exactly
    as expected -- the substance gate is not a blanket "never trust a
    non-foundation tier" rule."""
    foundation_root = tmp_path / "foundation-checkout"
    org_root = tmp_path / "org-checkout"
    _write(foundation_root, "commands", "protocol", "# Foundation protocol\n\nbase content.")
    _write(
        org_root,
        "commands",
        "protocol",
        "# ENAC protocol\n\nreal, substantive company-specific override content.",
    )

    layers = [
        _claude_layer("org", role="organization", rank=30, path=org_root),
        _claude_layer("foundation", role="foundation", rank=40, path=foundation_root),
    ]
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        _layers=layers,
    )

    item = resolved[("commands", "protocol")]
    assert item.ladder_resolved is True
    assert item.layer == "org"
    assert "ENAC protocol" in item.path.read_text(encoding="utf-8")


def test_removing_the_override_falls_back_to_foundation(tmp_path):
    """The end-to-end negative case, at unit scope: once the organization
    tier no longer declares the item at all (removed, not merely emptied),
    resolution falls back correctly to the foundation's real content."""
    foundation_root = tmp_path / "foundation-checkout"
    org_root = tmp_path / "org-checkout"
    org_root.mkdir()  # org tier exists but contributes nothing for "commands"
    _write(foundation_root, "commands", "protocol", "foundation protocol, unchanged")

    layers = [
        _claude_layer("org", role="organization", rank=30, path=org_root),
        _claude_layer("foundation", role="foundation", rank=40, path=foundation_root),
    ]
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        _layers=layers,
    )

    item = resolved[("commands", "protocol")]
    assert item.ladder_resolved is True
    assert item.layer == "foundation"
    assert item.path.read_text(encoding="utf-8") == "foundation protocol, unchanged"


# ---------------------------------------------------------------------------
# subpath join (the visible-checkout foundation layer shape)
# ---------------------------------------------------------------------------


def test_foundation_layer_with_subpath_is_resolved(tmp_path):
    """Mirrors the live manifest's `claude-foundation` entry: `source.path`
    is the repo root, `source.subpath: .claude` is where content actually
    lives -- exercises the shared `mirror.synthesize_effective_layers()`
    join this module reuses rather than re-deriving."""
    repo_root = tmp_path / "claude-copilot"
    _write(repo_root / ".claude", "agents", "kc", "kc agent body")

    layers = [
        _claude_layer(
            "foundation", role="foundation", rank=40, path=repo_root, subpath=".claude"
        )
    ]
    resolved = resolve_claude_content(
        foundation_root=repo_root,
        items={"agents": ("kc",)},
        _layers=layers,
    )

    item = resolved[("agents", "kc")]
    assert item.ladder_resolved is True
    assert item.path == repo_root / ".claude" / "agents" / "kc.md"


def test_invalid_subpath_degrades_to_fallback_not_a_crash(tmp_path):
    foundation_root = tmp_path / "foundation-checkout"
    _write(foundation_root, "commands", "protocol", "foundation protocol")

    layers = [
        _claude_layer(
            "foundation",
            role="foundation",
            rank=40,
            path=foundation_root,
            subpath="../escape",
        )
    ]
    resolved = resolve_claude_content(
        foundation_root=foundation_root,
        items={"commands": ("protocol",)},
        _layers=layers,
    )
    assert resolved[("commands", "protocol")].ladder_resolved is False
