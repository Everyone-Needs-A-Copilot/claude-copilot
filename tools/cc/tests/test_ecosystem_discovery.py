"""Tests for cc.core.ecosystem.discovery — best-effort LOCAL contribution
scanning. Every layer root here is a tmp_path fixture directory; discovery
never touches the network or a real ~/.claude.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.ecosystem.discovery import discover_contributions


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("discovery test attempted to resolve Path.home()")

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _layer(layer_id: str, rank: int, local_path=None) -> dict:
    source = {"repo": f"https://example.invalid/{layer_id}.git"}
    if local_path is not None:
        source["path"] = str(local_path)
    return {
        "id": layer_id,
        "role": "foundation",
        "rank": rank,
        "source": source,
        "auth": "anon",
        "activation": "always",
    }


def test_discover_contributions_no_local_path_contributes_nothing():
    layers = [_layer("foundation", 40)]
    assert discover_contributions(layers) == {}


def test_discover_contributions_nonexistent_local_path_contributes_nothing(tmp_path):
    layers = [_layer("foundation", 40, local_path=tmp_path / "does-not-exist")]
    assert discover_contributions(layers) == {}


def test_discover_contributions_finds_dimension_files(tmp_path):
    layer_root = tmp_path / "foundation"
    (layer_root / "skills").mkdir(parents=True)
    (layer_root / "skills" / "testing-patterns.md").write_text("skill body")
    (layer_root / "agents").mkdir()
    (layer_root / "agents" / "qa.md").write_text("agent body")

    layers = [_layer("foundation", 40, local_path=layer_root)]
    contributions = discover_contributions(layers)

    assert set(contributions["foundation"]["skills"]) == {"testing-patterns"}
    assert set(contributions["foundation"]["agents"]) == {"qa"}


def test_discover_contributions_hashes_directory_items(tmp_path):
    """A skill that is a directory (SKILL.md inside a named folder) is
    hashed as a whole, not skipped."""
    layer_root = tmp_path / "foundation"
    skill_dir = layer_root / "skills" / "testing-patterns"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("body")

    layers = [_layer("foundation", 40, local_path=layer_root)]
    contributions = discover_contributions(layers)

    assert "testing-patterns" in contributions["foundation"]["skills"]
    sha = contributions["foundation"]["skills"]["testing-patterns"]
    assert isinstance(sha, str) and len(sha) == 64  # sha256 hex digest


def test_discover_contributions_hash_changes_when_content_changes(tmp_path):
    layer_root = tmp_path / "foundation"
    (layer_root / "agents").mkdir(parents=True)
    agent_file = layer_root / "agents" / "qa.md"
    agent_file.write_text("version 1")

    layers = [_layer("foundation", 40, local_path=layer_root)]
    first = discover_contributions(layers)["foundation"]["agents"]["qa"]

    agent_file.write_text("version 2")
    second = discover_contributions(layers)["foundation"]["agents"]["qa"]

    assert first != second


def test_discover_contributions_ignores_macos_metadata(tmp_path):
    layer_root = tmp_path / "foundation"
    skill_dir = layer_root / "skills" / "testing-patterns"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("body")
    (layer_root / "skills" / ".DS_Store").write_bytes(b"top-level metadata")
    nested_metadata = skill_dir / ".DS_Store"
    nested_metadata.write_bytes(b"nested metadata v1")

    layers = [_layer("foundation", 40, local_path=layer_root)]
    first = discover_contributions(layers)

    assert set(first["foundation"]["skills"]) == {"testing-patterns"}
    first_hash = first["foundation"]["skills"]["testing-patterns"]

    nested_metadata.write_bytes(b"nested metadata v2")
    second_hash = discover_contributions(layers)["foundation"]["skills"][
        "testing-patterns"
    ]
    assert second_hash == first_hash


def test_discover_contributions_honors_declared_dimensions(tmp_path):
    """A layer whose own `copilot.layer.yml` declares `dimensions:
    [commands]` is never probed for `agents`, even though it has a
    perfectly real `agents/` directory on disk and the caller's default
    probe table includes `agents` — RC-5's `dimensions:` field is now a
    real, consumed restriction, not write-only metadata."""
    layer_root = tmp_path / "organization"
    (layer_root / "commands").mkdir(parents=True)
    (layer_root / "commands" / "protocol.md").write_text("org protocol")
    (layer_root / "agents").mkdir()
    (layer_root / "agents" / "qa.md").write_text("stray, undeclared agent file")
    (layer_root / "copilot.layer.yml").write_text(
        "schema_version: '1.0'\n"
        "package:\n  role: organization\n  rank: 30\n  product: claude\n"
        "dimensions:\n  - commands\n"
    )

    layers = [_layer("organization", 30, local_path=layer_root)]
    contributions = discover_contributions(layers)

    assert set(contributions["organization"]) == {"commands"}
    assert set(contributions["organization"]["commands"]) == {"protocol"}


def test_discover_contributions_no_declaration_file_falls_back_to_full_table(tmp_path):
    """A layer with no `copilot.layer.yml` at all keeps today's behavior:
    every caller-supplied dimension is probed, unchanged."""
    layer_root = tmp_path / "foundation"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("agent body")
    (layer_root / "commands").mkdir()
    (layer_root / "commands" / "protocol.md").write_text("foundation protocol")

    layers = [_layer("foundation", 40, local_path=layer_root)]
    contributions = discover_contributions(layers)

    assert set(contributions["foundation"]) == {"agents", "commands"}


def test_discover_contributions_empty_declared_dimensions_falls_back(tmp_path):
    """A `copilot.layer.yml` with an empty (or absent) `dimensions:` list is
    treated the same as no declaration at all -- never a false claim that
    this layer contributes nothing."""
    layer_root = tmp_path / "department"
    (layer_root / "plugins").mkdir(parents=True)
    (layer_root / "plugins" / "codex-copilot.json").write_text("{}")
    (layer_root / "copilot.layer.yml").write_text(
        "schema_version: '1.0'\npackage:\n  role: department\n  rank: 20\n  product: claude\n"
        "dimensions: []\n"
    )

    layers = [_layer("department", 20, local_path=layer_root)]
    contributions = discover_contributions(
        layers, dimensions=("plugins",)
    )

    assert set(contributions["department"]) == {"plugins"}


def test_discover_contributions_layer_missing_id_is_skipped_not_raised(tmp_path):
    layer_root = tmp_path / "no-id"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("body")

    layers = [
        {
            "role": "foundation",
            "rank": 40,
            "source": {
                "repo": "https://example.invalid/x.git",
                "path": str(layer_root),
            },
            "auth": "anon",
            "activation": "always",
        }
    ]
    # Must not raise -- a malformed layer is skipped, not fatal.
    assert discover_contributions(layers) == {}
