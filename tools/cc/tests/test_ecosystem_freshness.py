"""Tests for cc.core.ecosystem.freshness -- the pure freshness fold +
local lock fingerprint.

All paths are tmp_path-injected; the autouse fixture asserts Path.home()
is never resolved.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem.freshness import (
    build_per_layer_freshness,
    compute_freshness,
    current_lock_sha,
)


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


# ---------------------------------------------------------------------------
# build_per_layer_freshness() -- update-slice gap #2
# ---------------------------------------------------------------------------


def _canonical_lock_bytes(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _make_fixture_source_repo(tmp_path: Path, name: str, lock_data: dict) -> tuple[Path, str]:
    """Init a local git repo publishing `refs/copilot/lock` -> the blob sha
    of `lock_data`'s canonical JSON bytes (mirror.py's lock-pointer
    convention). Returns (repo_path, published_blob_sha)."""
    repo = tmp_path / f"{name}-source"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    lock_file = repo / "copilot.lock.json"
    lock_file.write_bytes(_canonical_lock_bytes(lock_data))

    blob_sha = subprocess.run(
        ["git", "hash-object", "-w", "copilot.lock.json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    subprocess.run(["git", "update-ref", "refs/copilot/lock", blob_sha], cwd=repo, check=True)
    return repo, blob_sha


def _write_local_mirror_lock(mirror_root: Path, layer_id: str, lock_data: dict) -> None:
    """Simulate a layer's already-cloned local mirror carrying its own
    checked-out `copilot.lock.json` at `<mirror_root>/<layer id>/`."""
    layer_dir = mirror_root / layer_id
    layer_dir.mkdir(parents=True, exist_ok=True)
    (layer_dir / "copilot.lock.json").write_bytes(_canonical_lock_bytes(lock_data))


def test_build_per_layer_freshness_mixed_shas(tmp_path):
    mirror_root = tmp_path / "mirrors"

    # foundation: local mirror matches the remote's published lock -- fresh.
    foundation_data = {"foundation": {"agents": {"sec": "abc1234"}}}
    foundation_repo, foundation_sha = _make_fixture_source_repo(
        tmp_path, "foundation", foundation_data
    )
    _write_local_mirror_lock(mirror_root, "foundation", foundation_data)

    # org: local mirror is BEHIND the remote's published lock -- stale.
    org_remote_data = {"org": {"agents": {"sec": "newnewnew"}}}
    org_repo, org_remote_sha = _make_fixture_source_repo(tmp_path, "org", org_remote_data)
    org_local_data = {"org": {"agents": {"sec": "oldoldold"}}}
    _write_local_mirror_lock(mirror_root, "org", org_local_data)

    layers = [
        {"id": "foundation", "source": {"repo": str(foundation_repo)}},
        {"id": "org", "source": {"repo": str(org_repo)}},
    ]

    results = build_per_layer_freshness(layers, _mirror_root=mirror_root)

    by_id = {r["id"]: r for r in results}
    assert by_id["foundation"]["latest"] == foundation_sha
    assert by_id["foundation"]["current"] == foundation_sha
    assert by_id["foundation"]["stale"] is False
    assert by_id["foundation"]["offline"] is False

    assert by_id["org"]["latest"] == org_remote_sha
    assert by_id["org"]["current"] != org_remote_sha
    assert by_id["org"]["current"] is not None
    assert by_id["org"]["stale"] is True
    assert by_id["org"]["offline"] is False


def test_build_per_layer_freshness_unreachable_layer_is_offline_and_stale_none(tmp_path):
    mirror_root = tmp_path / "mirrors"
    unreachable_repo = tmp_path / "does-not-exist-at-all"

    # A local mirror DOES already exist (prior successful sync) -- current
    # is known, but the remote poll is unreachable, so stale must still be
    # None (never coerced), and offline must be True.
    _write_local_mirror_lock(mirror_root, "dept-finance", {"dept": {"skills": {"x": "1"}}})

    layers = [{"id": "dept-finance", "source": {"repo": str(unreachable_repo)}}]

    results = build_per_layer_freshness(layers, _mirror_root=mirror_root)

    assert len(results) == 1
    entry = results[0]
    assert entry["id"] == "dept-finance"
    assert entry["current"] is not None
    assert entry["latest"] is None
    assert entry["stale"] is None
    assert entry["offline"] is True


def test_build_per_layer_freshness_local_path_only_layer_is_honest_not_offline(tmp_path):
    """A layer with no `source.repo` (local-path-only, e.g. `personal`)
    has nothing to poll -- honest 'nothing to check', NOT an offline
    condition (mirrors build_freshness_report()'s own
    'no source configured' distinction)."""
    mirror_root = tmp_path / "mirrors"
    layers = [{"id": "personal", "source": {"path": str(tmp_path / "personal-vault")}}]

    results = build_per_layer_freshness(layers, _mirror_root=mirror_root)

    assert len(results) == 1
    entry = results[0]
    assert entry["id"] == "personal"
    assert entry["current"] is None
    assert entry["latest"] is None
    assert entry["stale"] is None
    assert entry["offline"] is False


def test_build_per_layer_freshness_empty_layers_returns_empty_list(tmp_path):
    assert build_per_layer_freshness([], _mirror_root=tmp_path / "mirrors") == []


def test_build_per_layer_freshness_latest_lookup_injection_avoids_real_git(tmp_path):
    """`_latest_lookup` lets a caller inject the remote poll result
    directly per layer id -- no `git ls-remote` invoked at all."""
    mirror_root = tmp_path / "mirrors"
    _write_local_mirror_lock(mirror_root, "foundation", {"a": "1"})

    results = build_per_layer_freshness(
        [{"id": "foundation", "source": {"repo": "https://example.invalid/never-reached.git"}}],
        _mirror_root=mirror_root,
        _latest_lookup={"foundation": "injected-sha-value-000"},
    )

    assert results[0]["latest"] == "injected-sha-value-000"
    assert results[0]["offline"] is False


def test_build_per_layer_freshness_never_resolves_home_when_injected(tmp_path):
    # The autouse _no_real_home fixture would fail this test if
    # build_per_layer_freshness touched Path.home() at all when
    # _mirror_root is supplied.
    build_per_layer_freshness(
        [{"id": "personal", "source": {}}], _mirror_root=tmp_path / "mirrors"
    )
