"""Tests for cc.core.ecosystem.lockfile — a READ-ONLY reader.

Confirms it never raises on missing/corrupt input and never writes
anything; all paths are tmp_path-injected, never a real ~/.claude.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.ecosystem.lockfile import (
    default_lockfile_path,
    layer_meta,
    read_lockfile,
    set_layer_meta,
)


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("lockfile test attempted to resolve Path.home()")

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def test_read_lockfile_none_path_returns_empty_dict():
    assert read_lockfile(None) == {}


def test_read_lockfile_missing_file_returns_empty_dict(tmp_path):
    missing = tmp_path / "copilot.lock.json"
    assert read_lockfile(missing) == {}


def test_read_lockfile_reads_real_content(tmp_path):
    lockfile_path = tmp_path / "copilot.lock.json"
    payload = {"foundation": {"agents": {"sec": "abc1234"}}}
    lockfile_path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_lockfile(lockfile_path) == payload


def test_read_lockfile_corrupt_json_returns_empty_dict_not_raise(tmp_path):
    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_text("{not valid json", encoding="utf-8")

    assert read_lockfile(lockfile_path) == {}


def test_read_lockfile_non_object_json_returns_empty_dict(tmp_path):
    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_text("[1, 2, 3]", encoding="utf-8")

    assert read_lockfile(lockfile_path) == {}


def test_read_lockfile_never_writes(tmp_path):
    """A read that finds nothing must not create the file as a side effect."""
    missing = tmp_path / "copilot.lock.json"
    read_lockfile(missing)
    assert not missing.exists()


def test_default_lockfile_path_stays_repo_local(monkeypatch, tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    monkeypatch.setattr("cc.core.config_paths.repo_root", lambda: repo)

    assert default_lockfile_path() == repo / "copilot.lock.json"


def test_default_lockfile_path_uses_isolated_machine_root_outside_repo(
    monkeypatch, tmp_path
):
    machine_root = tmp_path / "machine"
    monkeypatch.setattr("cc.core.config_paths.repo_root", lambda: None)
    monkeypatch.setenv("CC_MACHINE_ROOT", str(machine_root))

    assert default_lockfile_path() == machine_root / "copilot.lock.json"


# ---------------------------------------------------------------------------
# layer_meta() / set_layer_meta() -- product/tier/role (ecosystem-
# architecture.md §3.3) recorded alongside a layer's sha pins
# ---------------------------------------------------------------------------


def test_layer_meta_absent_layer_returns_empty_dict():
    assert layer_meta({}, "foundation") == {}


def test_layer_meta_layer_with_no_meta_block_returns_empty_dict():
    """An old-format (pre-product) lockfile with no `_meta` block at all must
    degrade to `{}`, never raise."""
    lock = {"foundation": {"agents": {"sec": "abc1234"}}}
    assert layer_meta(lock, "foundation") == {}


def test_set_layer_meta_records_product_tier_role():
    lock: dict = {}
    set_layer_meta(
        lock,
        "foundation",
        product="claude",
        tier="foundation",
        role="foundation",
        source_sha="a" * 40,
    )
    assert layer_meta(lock, "foundation") == {
        "product": "claude",
        "tier": "foundation",
        "role": "foundation",
        "source_sha": "a" * 40,
    }


def test_set_layer_meta_product_only_omits_tier_and_role():
    lock: dict = {}
    set_layer_meta(lock, "foundation", product="knowledge")
    assert layer_meta(lock, "foundation") == {"product": "knowledge"}


def test_set_layer_meta_does_not_disturb_existing_sha_pins():
    """Adding `_meta` alongside a layer's real dimension pins must never
    touch those pins -- `_meta` is additive, not a replacement of the leaf
    shape (never breaks an existing reader that only ever looks at real
    dimension names)."""
    lock = {"foundation": {"agents": {"sec": "abc1234"}}}
    set_layer_meta(lock, "foundation", product="claude")
    assert lock["foundation"]["agents"]["sec"] == "abc1234"
    assert lock["foundation"]["_meta"]["product"] == "claude"


def test_set_layer_meta_returns_the_same_lock_object():
    lock: dict = {}
    result = set_layer_meta(lock, "foundation", product="claude")
    assert result is lock
