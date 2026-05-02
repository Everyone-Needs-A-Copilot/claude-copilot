"""Tests for config merge: precedence, project wins, env vars."""

from __future__ import annotations

import pytest

from cc.core.config import get_resolved_config, resolve_key


# ---------------------------------------------------------------------------
# Project wins over machine
# ---------------------------------------------------------------------------

def test_project_wins_over_machine():
    cfg = get_resolved_config(
        _machine={"paths": {"memory": "/machine/memory"}},
        _project={"paths": {"memory": "/project/memory"}},
    )
    assert cfg["paths.memory"] == "/project/memory"


def test_machine_used_when_project_absent():
    cfg = get_resolved_config(
        _machine={"paths": {"memory": "/machine/memory"}},
        _project={},
    )
    assert cfg["paths.memory"] == "/machine/memory"


def test_project_partial_override_preserves_machine_keys():
    """Project sets only one key; machine values for other keys are retained."""
    cfg = get_resolved_config(
        _machine={
            "paths": {"memory": "/machine/memory", "shared_docs": "/machine/docs"},
        },
        _project={
            "paths": {"memory": "/project/memory"},
        },
    )
    assert cfg["paths.memory"] == "/project/memory"
    assert cfg["paths.shared_docs"] == "/machine/docs"


# ---------------------------------------------------------------------------
# Env var wins over everything
# ---------------------------------------------------------------------------

def test_env_var_wins_over_project_and_machine(monkeypatch):
    monkeypatch.setenv("CC_PATHS_MEMORY", "/env/memory")
    cfg = get_resolved_config(
        _machine={"paths": {"memory": "/machine/memory"}},
        _project={"paths": {"memory": "/project/memory"}},
    )
    assert cfg["paths.memory"] == "/env/memory"


def test_env_var_wins_for_resolve_key(monkeypatch):
    monkeypatch.setenv("CC_PATHS_MEMORY", "/env/memory")
    value = resolve_key("paths.memory", _machine={}, _project={})
    assert value == "/env/memory"


def test_env_var_not_set_falls_through(monkeypatch):
    monkeypatch.delenv("CC_PATHS_MEMORY", raising=False)
    value = resolve_key(
        "paths.memory",
        _machine={"paths": {"memory": "/machine/memory"}},
        _project={},
    )
    assert value == "/machine/memory"


# ---------------------------------------------------------------------------
# Scope-restricted resolve_key
# ---------------------------------------------------------------------------

def test_resolve_key_machine_scope_returns_machine():
    value = resolve_key(
        "paths.memory",
        scope="machine",
        _machine={"paths": {"memory": "/machine/memory"}},
        _project={"paths": {"memory": "/project/memory"}},
    )
    assert value == "/machine/memory"


def test_resolve_key_project_scope_returns_project():
    value = resolve_key(
        "paths.memory",
        scope="project",
        _machine={"paths": {"memory": "/machine/memory"}},
        _project={"paths": {"memory": "/project/memory"}},
    )
    assert value == "/project/memory"


def test_resolve_key_project_scope_returns_none_when_not_set():
    value = resolve_key(
        "paths.memory",
        scope="project",
        _machine={},
        _project={},
    )
    assert value is None


def test_resolve_key_effective_scope_default():
    """Effective scope (None) prefers project → machine → default."""
    value = resolve_key(
        "paths.memory",
        scope=None,
        _machine={"paths": {"memory": "/machine/memory"}},
        _project={},
    )
    assert value == "/machine/memory"
