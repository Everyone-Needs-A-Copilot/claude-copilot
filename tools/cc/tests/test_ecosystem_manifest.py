"""Tests for cc.core.ecosystem.manifest — load + validate the layer manifest.

Every case is exercised against in-memory layer dicts or a `tmp_path`
manifest file -- never against a real ~/.claude or a real remote.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    """Guard: no manifest test may resolve Path.home() -- every path used
    here must be an explicit tmp_path or in-memory value."""

    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _layer(**overrides) -> dict:
    base = {
        "id": "foundation",
        "role": "foundation",
        "rank": 40,
        "product": "claude",
        "source": {"repo": "https://example.invalid/foundation.git"},
        "auth": "anon",
        "activation": "always",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# load_layers()
# ---------------------------------------------------------------------------


def test_load_layers_from_list_passthrough():
    layers = [_layer(id="a", rank=10), _layer(id="b", rank=20)]
    loaded = load_layers(layers)
    assert loaded == layers
    # Must be a copy, not the same list object, so callers can't mutate the
    # caller's original by accident.
    assert loaded is not layers


def test_load_layers_from_yaml_file(tmp_path):
    manifest_path = tmp_path / "copilot.layers.yml"
    manifest_path.write_text(
        """
version: 1
layers:
  - id: personal
    role: personal
    rank: 10
    source:
      repo: git@github-personal:me/private.git
    auth: ssh-personal
    activation: always
  - id: foundation
    role: foundation
    rank: 40
    source:
      repo: https://example.invalid/foundation.git
    auth: anon
    activation: always
"""
    )
    layers = load_layers(manifest_path)
    assert [layer["id"] for layer in layers] == ["personal", "foundation"]
    assert layers[0]["rank"] == 10


def test_load_layers_missing_file_is_plain_language_error(tmp_path):
    missing = tmp_path / "does-not-exist.yml"
    with pytest.raises(ManifestError) as exc_info:
        load_layers(missing)
    assert "not found" in str(exc_info.value)
    assert "Traceback" not in str(exc_info.value)


def test_load_layers_invalid_yaml_is_plain_language_error(tmp_path):
    bad = tmp_path / "copilot.layers.yml"
    bad.write_text("layers: [this is: not, valid: yaml: at all")
    with pytest.raises(ManifestError) as exc_info:
        load_layers(bad)
    assert "not valid YAML" in str(exc_info.value)


def test_load_layers_missing_layers_key_is_plain_language_error(tmp_path):
    bad = tmp_path / "copilot.layers.yml"
    bad.write_text("version: 1\n")
    with pytest.raises(ManifestError) as exc_info:
        load_layers(bad)
    assert "top-level `layers:`" in str(exc_info.value)


def test_load_layers_layers_not_a_list_is_plain_language_error(tmp_path):
    bad = tmp_path / "copilot.layers.yml"
    bad.write_text("version: 1\nlayers: not-a-list\n")
    with pytest.raises(ManifestError) as exc_info:
        load_layers(bad)
    assert "must be a list" in str(exc_info.value)


# ---------------------------------------------------------------------------
# validate_layers()
# ---------------------------------------------------------------------------


def test_validate_layers_good_manifest_passes():
    layers = [
        _layer(id="personal", role="personal", rank=10),
        _layer(id="dept-eng", role="department", rank=20, unit="engineering"),
        _layer(id="org", role="org", rank=30),
        _layer(id="foundation", role="foundation", rank=40),
    ]
    assert validate_layers(layers) == layers


def test_validate_layers_open_role_vocabulary_passes():
    """`role` is an open string -- an unrecognized role must parse fine."""
    layers = [
        _layer(id="squad", role="squad", rank=5),
        _layer(id="foundation", rank=40),
    ]
    assert validate_layers(layers) == layers


def test_validate_layers_empty_manifest_errors():
    with pytest.raises(ManifestError, match="no layers declared"):
        validate_layers([])


def test_validate_layers_missing_required_field_is_plain_language():
    layers = [_layer(id="broken", rank=10, auth=None)]
    with pytest.raises(ManifestError) as exc_info:
        validate_layers(layers)
    message = str(exc_info.value)
    assert "broken" in message
    assert "auth" in message
    assert "Traceback" not in message


def test_validate_layers_empty_role_errors():
    layers = [_layer(id="broken", rank=10, role="   ")]
    with pytest.raises(ManifestError, match="role"):
        validate_layers(layers)


def test_validate_layers_missing_product_is_plain_language_error():
    layers = [_layer(id="broken", rank=10, product=None)]
    with pytest.raises(ManifestError) as exc_info:
        validate_layers(layers)
    message = str(exc_info.value)
    assert "broken" in message
    assert "product" in message
    assert "Traceback" not in message


def test_validate_layers_empty_product_errors():
    layers = [_layer(id="broken", rank=10, product="   ")]
    with pytest.raises(ManifestError, match="product"):
        validate_layers(layers)


def test_validate_layers_open_product_vocabulary_passes():
    """`product` is config-driven -- not a closed enum -- so an unrecognized
    value must still parse fine."""
    layers = [_layer(id="widget-layer", rank=40, product="widgets")]
    assert validate_layers(layers) == layers


def test_validate_layers_non_integer_rank_errors():
    layers = [_layer(id="broken", rank="ten")]
    with pytest.raises(ManifestError, match="non-integer"):
        validate_layers(layers)


def test_validate_layers_bool_rank_rejected():
    """bool is a subclass of int in Python -- must not silently pass as a rank."""
    layers = [_layer(id="broken", rank=True)]
    with pytest.raises(ManifestError, match="non-integer"):
        validate_layers(layers)


def test_validate_layers_equal_rank_hard_errors():
    layers = [
        _layer(id="dept-a", role="department", rank=20),
        _layer(id="dept-b", role="department", rank=20),
    ]
    with pytest.raises(ManifestError) as exc_info:
        validate_layers(layers)
    message = str(exc_info.value)
    assert "dept-a" in message and "dept-b" in message
    assert "rank 20" in message
    assert "Traceback" not in message


def test_validate_layers_out_of_order_rank_errors():
    """List order must agree with ascending rank."""
    layers = [
        _layer(id="org", role="org", rank=30),
        _layer(id="personal", role="personal", rank=10),
    ]
    with pytest.raises(ManifestError, match="out of order"):
        validate_layers(layers)


def test_validate_layers_missing_source_repo_errors():
    layers = [_layer(id="broken", rank=10, source={})]
    with pytest.raises(ManifestError, match="source"):
        validate_layers(layers)


def test_validate_layers_n_tier_beyond_four_passes():
    """Arity-independent: 6 layers with rank gaps validate fine."""
    layers = [
        _layer(id=f"layer-{rank}", role="custom", rank=rank)
        for rank in (5, 10, 15, 20, 30, 40)
    ]
    assert validate_layers(layers) == layers
