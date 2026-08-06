"""Tests for Task 97: docs.* config defaults, env hydration, and docs_paths helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cc.core.config import DEFAULTS, get_resolved_config, resolve_key


# ---------------------------------------------------------------------------
# DEFAULTS contain docs.* keys
# ---------------------------------------------------------------------------


def test_defaults_has_docs_cache_dir():
    assert "docs.cache_dir" in DEFAULTS
    assert "~/.claude/cache/docs" in DEFAULTS["docs.cache_dir"]


def test_defaults_has_docs_cache_ttl():
    assert "docs.cache_ttl_hours" in DEFAULTS
    assert DEFAULTS["docs.cache_ttl_hours"] == 168


def test_defaults_has_docs_source_order():
    assert "docs.source_order" in DEFAULTS
    assert DEFAULTS["docs.source_order"] == "local,fetch"


def test_defaults_has_docs_context7_endpoint_as_none():
    assert "docs.context7_endpoint" in DEFAULTS
    assert DEFAULTS["docs.context7_endpoint"] is None


# ---------------------------------------------------------------------------
# get_resolved_config resolves docs.* correctly
# ---------------------------------------------------------------------------


def test_resolved_config_docs_cache_dir_expanded():
    """docs.cache_dir ~ is expanded to an absolute path."""
    cfg = get_resolved_config(_machine={}, _project={})
    value = cfg.get("docs.cache_dir")
    assert value is not None
    assert "~" not in value
    assert Path(value).is_absolute()


def test_resolved_config_docs_cache_ttl():
    cfg = get_resolved_config(_machine={}, _project={})
    assert cfg["docs.cache_ttl_hours"] == 168


def test_resolved_config_docs_source_order_default():
    cfg = get_resolved_config(_machine={}, _project={})
    assert cfg["docs.source_order"] == "local,fetch"


def test_resolved_config_docs_context7_endpoint_default_none():
    cfg = get_resolved_config(_machine={}, _project={})
    # None values are kept in the resolved dict but evaluate as None
    assert cfg.get("docs.context7_endpoint") is None


# ---------------------------------------------------------------------------
# Machine config can override docs.* keys
# ---------------------------------------------------------------------------


def test_machine_overrides_docs_cache_ttl():
    cfg = get_resolved_config(
        _machine={"docs": {"cache_ttl_hours": 48}},
        _project={},
    )
    assert cfg["docs.cache_ttl_hours"] == 48


def test_machine_overrides_docs_source_order():
    cfg = get_resolved_config(
        _machine={"docs": {"source_order": "local"}},
        _project={},
    )
    assert cfg["docs.source_order"] == "local"


def test_machine_overrides_docs_context7_endpoint():
    cfg = get_resolved_config(
        _machine={"docs": {"context7_endpoint": "https://example.com/ctx7"}},
        _project={},
    )
    assert cfg["docs.context7_endpoint"] == "https://example.com/ctx7"


# ---------------------------------------------------------------------------
# CC_DOCS_* env vars (env hydration)
# ---------------------------------------------------------------------------


def test_env_var_overrides_docs_cache_ttl(monkeypatch):
    monkeypatch.setenv("CC_DOCS_CACHE_TTL_HOURS", "72")
    cfg = get_resolved_config(_machine={}, _project={})
    # Env vars land as strings but should be present
    assert str(cfg["docs.cache_ttl_hours"]) == "72"


def test_env_var_overrides_docs_source_order(monkeypatch):
    monkeypatch.setenv("CC_DOCS_SOURCE_ORDER", "local")
    cfg = get_resolved_config(_machine={}, _project={})
    assert cfg["docs.source_order"] == "local"


def test_env_var_overrides_docs_cache_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_DOCS_CACHE_DIR", str(tmp_path / "override_cache"))
    cfg = get_resolved_config(_machine={}, _project={})
    assert cfg["docs.cache_dir"] == str(tmp_path / "override_cache")


# ---------------------------------------------------------------------------
# docs_paths helpers
# ---------------------------------------------------------------------------


def test_docs_cache_dir_creates_directory(tmp_path):
    from cc.core.docs_paths import docs_cache_dir

    target = tmp_path / "test_cache"
    result = docs_cache_dir(_override=target)
    assert result == target
    assert target.is_dir()


def test_docs_cache_dir_writes_gitignore(tmp_path):
    from cc.core.docs_paths import docs_cache_dir

    target = tmp_path / "cache_with_gitignore"
    docs_cache_dir(_override=target)
    gi = target / ".gitignore"
    assert gi.exists()
    content = gi.read_text()
    assert "*.db" in content


def test_docs_cache_ttl_hours_default():
    from cc.core.docs_paths import docs_cache_ttl_hours

    # Default without machine config override returns 168
    ttl = docs_cache_ttl_hours()
    assert ttl == 168


def test_docs_source_order_default():
    from cc.core.docs_paths import docs_source_order

    order = docs_source_order()
    assert order == ["local", "fetch"]


# ---------------------------------------------------------------------------
# Offline test: everything works with no network
# ---------------------------------------------------------------------------


def test_offline_foundation_no_network(tmp_path, monkeypatch):
    """Full offline check: config resolves and cache dir is created without any I/O beyond tmp_path."""
    from cc.core.docs_paths import docs_cache_dir, docs_cache_ttl_hours, docs_source_order

    # Ensure no accidental network calls by blocking socket (best-effort)
    import socket

    original_socket = socket.socket

    def no_network(*args, **kwargs):
        raise OSError("Network access forbidden in offline test")

    monkeypatch.setattr(socket, "socket", no_network)

    # All three helpers must succeed without network
    cache_root = docs_cache_dir(_override=tmp_path / "offline_cache")
    ttl = docs_cache_ttl_hours()
    order = docs_source_order()

    assert cache_root.is_dir()
    assert ttl == 168
    assert order == ["local", "fetch"]
