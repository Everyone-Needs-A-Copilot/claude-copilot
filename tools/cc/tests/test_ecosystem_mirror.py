"""Tests for cc.core.ecosystem.mirror -- the READ-ONLY mirror-root
resolution + cheap lock-pointer read.

Uses local `file://`-style (plain-path) fixture git repos so nothing ever
touches a real remote, ~/.claude, or ~/.copilot. All mirror-root
resolution is tmp_path-injected; the autouse fixture below asserts
Path.home() is never resolved as a fallback.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem import mirror


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "mirror test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _canonical_lock_bytes(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _make_fixture_repo(
    tmp_path: Path, lock_data: dict, *, ref: str
) -> tuple[Path, str]:
    """Init a local git repo, publish `ref` -> the blob sha of `lock_data`'s
    canonical JSON bytes (the lock-pointer convention -- see mirror.py's
    module docstring). Returns (repo_path, published_blob_sha)."""
    repo = tmp_path / "tier-source"
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

    subprocess.run(["git", "update-ref", ref, blob_sha], cwd=repo, check=True)
    return repo, blob_sha


# ---------------------------------------------------------------------------
# mirror_root()
# ---------------------------------------------------------------------------


def test_mirror_root_uses_injected_root(tmp_path):
    root = mirror.mirror_root("foundation", _root=tmp_path)
    assert root == tmp_path / "foundation"


def test_mirror_root_different_tiers_are_distinct(tmp_path):
    assert mirror.mirror_root("org", _root=tmp_path) != mirror.mirror_root(
        "dept-finance", _root=tmp_path
    )


def test_mirror_root_never_resolves_home_when_injected(tmp_path):
    # The autouse _no_real_home fixture would fail this test if mirror_root
    # touched Path.home() at all when _root is supplied.
    mirror.mirror_root("personal", _root=tmp_path)


# ---------------------------------------------------------------------------
# latest_lock_sha()
# ---------------------------------------------------------------------------


def test_latest_lock_sha_reads_published_ref(tmp_path):
    repo, blob_sha = _make_fixture_repo(
        tmp_path,
        {"foundation": {"agents": {"sec": "abc1234"}}},
        ref="refs/copilot/lock",
    )

    result = mirror.latest_lock_sha(str(repo), "refs/copilot/lock")
    assert result == blob_sha


def test_latest_lock_sha_default_ref_matches_convention(tmp_path):
    repo, blob_sha = _make_fixture_repo(
        tmp_path,
        {"foundation": {"agents": {"sec": "abc1234"}}},
        ref="refs/copilot/lock",
    )

    result = mirror.latest_lock_sha(str(repo))
    assert result == blob_sha
    assert mirror.DEFAULT_LOCK_POINTER_REF == "refs/copilot/lock"


def test_latest_lock_sha_missing_ref_returns_none(tmp_path):
    repo, _ = _make_fixture_repo(
        tmp_path,
        {"foundation": {"agents": {"sec": "abc1234"}}},
        ref="refs/copilot/lock",
    )

    # Ask for a ref that was never published.
    result = mirror.latest_lock_sha(str(repo), "refs/copilot/does-not-exist")
    assert result is None


def test_latest_lock_sha_unreachable_source_returns_none_not_raise(tmp_path):
    unreachable = tmp_path / "does-not-exist-at-all"
    result = mirror.latest_lock_sha(str(unreachable), "refs/copilot/lock")
    assert result is None


def test_latest_lock_sha_never_raises_on_bad_git_invocation(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert mirror.latest_lock_sha("https://example.invalid/repo.git") is None


# ---------------------------------------------------------------------------
# resolve_transport() / clone_or_update_mirror() stub
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("auth", ["ssh-personal", "ssh-work", "anon"])
def test_resolve_transport_identity_for_supported_auth(auth):
    assert mirror.resolve_transport("git@github-personal:x/y.git", auth) == (
        "git@github-personal:x/y.git"
    )


def test_resolve_transport_gh_app_not_implemented():
    with pytest.raises(NotImplementedError):
        mirror.resolve_transport("https://example.invalid/repo.git", "gh-app:my-slug")


def test_clone_or_update_mirror_is_stubbed():
    with pytest.raises(NotImplementedError):
        mirror.clone_or_update_mirror()
