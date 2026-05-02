"""Tests for sentinel resolution: @machine, @machine:key, @env, @disabled."""

from __future__ import annotations

import pytest

from cc.core.config import get_resolved_config, resolve_key
from cc.core.sentinels import resolve_sentinel, is_sentinel


# ---------------------------------------------------------------------------
# is_sentinel
# ---------------------------------------------------------------------------

def test_is_sentinel_at_machine():
    assert is_sentinel("@machine") is True


def test_is_sentinel_at_machine_key():
    assert is_sentinel("@machine:paths.shared_docs") is True


def test_is_sentinel_at_disabled():
    assert is_sentinel("@disabled") is True


def test_is_sentinel_at_env():
    assert is_sentinel("@env:SOME_VAR") is True


def test_is_sentinel_plain_string():
    assert is_sentinel("/usr/local/path") is False


def test_is_sentinel_none():
    assert is_sentinel(None) is False


def test_is_sentinel_number():
    assert is_sentinel(42) is False


# ---------------------------------------------------------------------------
# resolve_sentinel: @machine (same key)
# ---------------------------------------------------------------------------

def test_at_machine_resolves_same_key():
    machine = {"paths.shared_docs": "/machine/docs"}
    result = resolve_sentinel("@machine", same_key="paths.shared_docs", machine_config=machine)
    assert result == "/machine/docs"


def test_at_machine_returns_none_when_key_missing():
    machine = {}
    result = resolve_sentinel("@machine", same_key="paths.shared_docs", machine_config=machine)
    assert result is None


# ---------------------------------------------------------------------------
# resolve_sentinel: @machine:<other_key>
# ---------------------------------------------------------------------------

def test_at_machine_other_key():
    machine = {"paths.shared_docs": "/machine/docs"}
    result = resolve_sentinel(
        "@machine:paths.shared_docs",
        same_key="paths.some_other_key",
        machine_config=machine,
    )
    assert result == "/machine/docs"


def test_at_machine_other_key_missing_returns_none():
    machine = {}
    result = resolve_sentinel(
        "@machine:paths.missing",
        same_key="paths.x",
        machine_config=machine,
    )
    assert result is None


# ---------------------------------------------------------------------------
# resolve_sentinel: @disabled
# ---------------------------------------------------------------------------

def test_at_disabled_returns_none():
    result = resolve_sentinel("@disabled", same_key="paths.shared_docs", machine_config={})
    assert result is None


def test_at_disabled_in_get_resolved_config():
    cfg = get_resolved_config(
        _machine={"paths": {"shared_docs": "/machine/docs"}},
        _project={"paths": {"shared_docs": "@disabled"}},
    )
    assert cfg["paths.shared_docs"] is None


# ---------------------------------------------------------------------------
# resolve_sentinel: @env
# ---------------------------------------------------------------------------

def test_at_env_resolves_env_var(monkeypatch):
    monkeypatch.setenv("MY_CUSTOM_VAR", "/env/path")
    result = resolve_sentinel("@env:MY_CUSTOM_VAR", same_key="paths.x", machine_config={})
    assert result == "/env/path"


def test_at_env_returns_none_when_var_missing(monkeypatch):
    monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
    result = resolve_sentinel("@env:NONEXISTENT_VAR", same_key="paths.x", machine_config={})
    assert result is None


# ---------------------------------------------------------------------------
# Unknown sentinel passes through
# ---------------------------------------------------------------------------

def test_unknown_sentinel_passthrough():
    """Unknown @-prefixed values are returned literally (forward-compat)."""
    result = resolve_sentinel("@future:something", same_key="x", machine_config={})
    assert result == "@future:something"


# ---------------------------------------------------------------------------
# Integration: project config with @machine sentinel
# ---------------------------------------------------------------------------

def test_project_at_machine_resolves_via_get_resolved_config():
    """Property test: project @machine always returns machine value for the same key."""
    machine_value = "/machine/shared-docs"
    cfg = get_resolved_config(
        _machine={"paths": {"shared_docs": machine_value}},
        _project={"paths": {"shared_docs": "@machine"}},
    )
    assert cfg["paths.shared_docs"] == machine_value


def test_project_at_machine_cross_key():
    """@machine:other.key fetches a different key from machine config."""
    cfg = get_resolved_config(
        _machine={"paths": {"shared_docs": "/docs", "knowledge_repo": "/kr"}},
        _project={"paths": {"knowledge_repo": "@machine:paths.shared_docs"}},
    )
    assert cfg["paths.knowledge_repo"] == "/docs"


def test_resolve_key_with_at_machine_sentinel():
    """resolve_key with @machine sentinel returns machine value."""
    value = resolve_key(
        "paths.shared_docs",
        _machine={"paths": {"shared_docs": "/machine/docs"}},
        _project={"paths": {"shared_docs": "@machine"}},
    )
    assert value == "/machine/docs"
