"""Tests for cc.core.ecosystem.freshness -- the pure freshness fold +
local lock fingerprint.

All paths are tmp_path-injected; the autouse fixture asserts Path.home()
is never resolved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cc.core.ecosystem.freshness import compute_freshness, current_lock_sha


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "freshness test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


# ---------------------------------------------------------------------------
# current_lock_sha()
# ---------------------------------------------------------------------------


def test_current_lock_sha_none_when_no_lockfile_path(tmp_path):
    missing = tmp_path / "copilot.lock.json"
    assert current_lock_sha(_lockfile_path=missing) is None


def test_current_lock_sha_none_when_lockfile_injected_empty():
    assert current_lock_sha(_lockfile={}) is None


def test_current_lock_sha_deterministic_for_injected_lockfile():
    data = {"foundation": {"agents": {"sec": "abc1234"}}}
    sha1 = current_lock_sha(_lockfile=data)
    sha2 = current_lock_sha(_lockfile=data)
    assert sha1 == sha2
    assert sha1 is not None
    # A git blob-sha1-style fingerprint: 40 lowercase hex chars.
    assert len(sha1) == 40
    assert all(c in "0123456789abcdef" for c in sha1)


def test_current_lock_sha_matches_git_hash_object_convention():
    """The fingerprint must be reproducible with a real `git hash-object`
    over the canonical (sort_keys, no-whitespace) JSON bytes -- this is
    what makes it directly comparable to a mirror's published
    lock-pointer ref (see mirror.py's module docstring)."""
    import hashlib

    data = {"foundation": {"agents": {"sec": "abc1234"}}}
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    header = f"blob {len(canonical)}\0".encode("ascii")
    expected = hashlib.sha1(header + canonical).hexdigest()

    assert current_lock_sha(_lockfile=data) == expected


def test_current_lock_sha_key_order_independent():
    """Reading the SAME logical lock state via differently-ordered dicts
    must fingerprint identically (canonical JSON, not raw file bytes)."""
    a = {
        "foundation": {"agents": {"sec": "abc1234"}},
        "org": {"skills": {"x": "def5678"}},
    }
    b = {
        "org": {"skills": {"x": "def5678"}},
        "foundation": {"agents": {"sec": "abc1234"}},
    }
    assert current_lock_sha(_lockfile=a) == current_lock_sha(_lockfile=b)


def test_current_lock_sha_reads_real_file_via_lockfile_reader(tmp_path):
    lockfile_path = tmp_path / "copilot.lock.json"
    data = {"foundation": {"agents": {"sec": "abc1234"}}}
    lockfile_path.write_text(json.dumps(data), encoding="utf-8")

    from_file = current_lock_sha(_lockfile_path=lockfile_path)
    from_injected = current_lock_sha(_lockfile=data)
    assert from_file == from_injected


def test_current_lock_sha_corrupt_file_is_none_not_raise(tmp_path):
    lockfile_path = tmp_path / "copilot.lock.json"
    lockfile_path.write_text("{not valid json", encoding="utf-8")

    assert current_lock_sha(_lockfile_path=lockfile_path) is None


# ---------------------------------------------------------------------------
# compute_freshness()
# ---------------------------------------------------------------------------


def test_compute_freshness_fresh_when_shas_match():
    result = compute_freshness("abc1234", "abc1234")
    assert result == {
        "current_lock_sha": "abc1234",
        "latest_lock_sha": "abc1234",
        "stale": False,
    }


def test_compute_freshness_stale_when_shas_differ():
    result = compute_freshness("abc1234", "def5678")
    assert result["stale"] is True


def test_compute_freshness_unknown_when_latest_is_none():
    """Offline / unreachable remote -- stale must be None, NEVER False."""
    result = compute_freshness("abc1234", None)
    assert result["stale"] is None


def test_compute_freshness_unknown_when_current_is_none():
    """No local lock yet -- stale must be None, NEVER False."""
    result = compute_freshness(None, "def5678")
    assert result["stale"] is None


def test_compute_freshness_unknown_when_both_none():
    result = compute_freshness(None, None)
    assert result["stale"] is None
