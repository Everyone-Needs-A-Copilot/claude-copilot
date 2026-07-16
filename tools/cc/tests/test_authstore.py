"""Tests for cc.core.authstore — the non-secret identity pointer.

All roots are tmp_path-injected via `_root`; the autouse fixture below
asserts `Path.home()` is never resolved as a fallback (mirrors
core/ecosystem/mirror.py's test convention).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.authstore import (
    auth_root,
    clear_identity,
    identity_path,
    read_identity,
    write_identity,
)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "authstore test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


# ---------------------------------------------------------------------------
# auth_root() / identity_path()
# ---------------------------------------------------------------------------


def test_auth_root_uses_injected_root(tmp_path):
    assert auth_root(_root=tmp_path) == tmp_path


def test_identity_path_is_active_json_under_auth_root(tmp_path):
    assert identity_path(_root=tmp_path) == tmp_path / "active.json"


# ---------------------------------------------------------------------------
# read_identity() -- fail-open
# ---------------------------------------------------------------------------


def test_read_identity_missing_file_returns_empty_dict(tmp_path):
    assert read_identity(_root=tmp_path) == {}


def test_read_identity_corrupt_json_returns_empty_dict_not_raise(tmp_path):
    identity_path(_root=tmp_path).parent.mkdir(parents=True, exist_ok=True)
    identity_path(_root=tmp_path).write_text("{not valid json", encoding="utf-8")

    assert read_identity(_root=tmp_path) == {}


def test_read_identity_non_object_json_returns_empty_dict(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    identity_path(_root=tmp_path).write_text("[1, 2, 3]", encoding="utf-8")

    assert read_identity(_root=tmp_path) == {}


# ---------------------------------------------------------------------------
# write_identity() / read_identity() round-trip
# ---------------------------------------------------------------------------


def test_write_then_read_round_trip(tmp_path):
    identity = {"login": "octocat", "scopes": "read:org repo", "obtained_at": "2026-07-16T00:00:00Z"}
    written_path = write_identity(identity, _root=tmp_path)

    assert written_path == identity_path(_root=tmp_path)
    assert read_identity(_root=tmp_path) == identity


def test_write_identity_creates_auth_root(tmp_path):
    root = tmp_path / "auth"
    assert not root.exists()
    write_identity({"login": "octocat"}, _root=root)
    assert root.exists()


def test_write_identity_never_persists_token(tmp_path):
    """Even if a caller mistakenly passes a token, it must never be
    persisted -- this store is a non-secret pointer, never a credential
    store (see module docstring)."""
    write_identity(
        {
            "login": "octocat",
            "token": "ghp_should_never_be_written",
            "access_token": "also_never",
            "refresh_token": "also_never",
            "secret": "also_never",
        },
        _root=tmp_path,
    )
    stored = read_identity(_root=tmp_path)
    assert stored == {"login": "octocat"}
    raw = identity_path(_root=tmp_path).read_text(encoding="utf-8")
    assert "should_never_be_written" not in raw
    assert "also_never" not in raw


def test_write_identity_overwrites_previous_identity(tmp_path):
    write_identity({"login": "octocat"}, _root=tmp_path)
    write_identity({"login": "hubot"}, _root=tmp_path)
    assert read_identity(_root=tmp_path) == {"login": "hubot"}


# ---------------------------------------------------------------------------
# clear_identity()
# ---------------------------------------------------------------------------


def test_clear_identity_removes_existing_file(tmp_path):
    write_identity({"login": "octocat"}, _root=tmp_path)
    assert clear_identity(_root=tmp_path) is True
    assert read_identity(_root=tmp_path) == {}


def test_clear_identity_missing_file_returns_false(tmp_path):
    assert clear_identity(_root=tmp_path) is False
