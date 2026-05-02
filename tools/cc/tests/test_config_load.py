"""Tests for config loading: machine defaults, file loading, secrets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cc.core.config import (
    DEFAULTS,
    _flatten,
    get_resolved_config,
    load_machine_config,
    load_project_config,
    resolve_key,
    write_config,
    unset_config,
)
from cc.core.config_paths import machine_config_path


# ---------------------------------------------------------------------------
# Flatten helper
# ---------------------------------------------------------------------------

def test_flatten_simple():
    obj = {"paths": {"memory": "/tmp/mem", "docs": None}, "version": 1}
    flat = _flatten(obj)
    assert flat["paths.memory"] == "/tmp/mem"
    assert flat["paths.docs"] is None
    assert flat["version"] == 1


def test_flatten_deeply_nested():
    obj = {"a": {"b": {"c": "deep"}}}
    flat = _flatten(obj)
    assert flat["a.b.c"] == "deep"


def test_flatten_empty():
    assert _flatten({}) == {}


# ---------------------------------------------------------------------------
# Machine config defaults when file missing
# ---------------------------------------------------------------------------

def test_machine_defaults_when_missing(tmp_path, monkeypatch):
    """Machine config falls back to DEFAULTS when file doesn't exist."""
    # Point machine config to a non-existent file
    fake_path = tmp_path / "machine_config.json"
    monkeypatch.setattr(
        "cc.core.config.machine_config_path",
        lambda: fake_path,
    )
    # load_machine_config returns {} when file is absent
    from cc.core.config import load_machine_config as _load
    result = _load()
    assert result == {}


def test_get_resolved_returns_defaults_when_no_files():
    """get_resolved_config uses DEFAULTS when both configs are empty."""
    cfg = get_resolved_config(_machine={}, _project={})
    assert cfg["paths.memory"] is not None  # default is ~/ expanded
    assert cfg["memory.embedding_model"] == "none"


def test_default_memory_path_expanded():
    """Default memory path has ~ expanded to absolute path."""
    cfg = get_resolved_config(_machine={}, _project={})
    path = cfg["paths.memory"]
    assert path is not None
    assert "~" not in path
    assert Path(path).parts[0] == "/"


# ---------------------------------------------------------------------------
# Path expansion: ~ → absolute
# ---------------------------------------------------------------------------

def test_tilde_expansion_in_machine_config():
    cfg = get_resolved_config(
        _machine={"paths": {"memory": "~/my-memory"}},
        _project={},
    )
    assert cfg["paths.memory"].startswith("/")
    assert "my-memory" in cfg["paths.memory"]


def test_tilde_expansion_in_project_config():
    cfg = get_resolved_config(
        _machine={},
        _project={"paths": {"memory": "~/proj-memory"}},
    )
    assert cfg["paths.memory"].startswith("/")
    assert "proj-memory" in cfg["paths.memory"]


# ---------------------------------------------------------------------------
# Machine config wins over defaults
# ---------------------------------------------------------------------------

def test_machine_overrides_defaults():
    cfg = get_resolved_config(
        _machine={"memory": {"embedding_model": "all-MiniLM-L6-v2"}},
        _project={},
    )
    assert cfg["memory.embedding_model"] == "all-MiniLM-L6-v2"


# ---------------------------------------------------------------------------
# write_config / unset_config
# ---------------------------------------------------------------------------

def test_write_and_read_machine_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    write_config("paths.memory", "/tmp/test-memory")
    data = json.loads(cfg_file.read_text())
    assert data["paths"]["memory"] == "/tmp/test-memory"


def test_write_config_merges_with_existing(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/old"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    write_config("paths.shared_docs", "/new-docs")
    data = json.loads(cfg_file.read_text())
    # Both keys present
    assert data["paths"]["memory"] == "/old"
    assert data["paths"]["shared_docs"] == "/new-docs"


def test_unset_config_removes_key(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"paths": {"memory": "/mem", "docs": "/docs"}}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    removed = unset_config("paths.docs")
    assert removed is True
    data = json.loads(cfg_file.read_text())
    assert "docs" not in data.get("paths", {})
    assert data["paths"]["memory"] == "/mem"


def test_unset_config_returns_false_when_missing(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({}))
    monkeypatch.setattr("cc.core.config_paths.machine_config_path", lambda: cfg_file)
    monkeypatch.setattr("cc.core.config.machine_config_path", lambda: cfg_file)

    removed = unset_config("nonexistent.key")
    assert removed is False
