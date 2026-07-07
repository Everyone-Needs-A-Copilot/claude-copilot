"""Tests for cc.core.ecosystem.mirror -- the READ-ONLY mirror-root
resolution + cheap lock-pointer read.

Uses local `file://`-style (plain-path) fixture git repos so nothing ever
touches a real remote, ~/.claude, or ~/.copilot. All mirror-root
resolution is tmp_path-injected; the autouse fixture below asserts
Path.home() is never resolved as a fallback.
"""

from __future__ import annotations

import json
import shutil
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


def _make_content_repo(
    tmp_path: Path, files: dict[str, str], *, name: str = "source", branch: str = "main"
) -> Path:
    """Init a local git repo with real content on `branch`, one commit."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True)
    for relpath, content in files.items():
        target = repo / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


# ---------------------------------------------------------------------------
# clone_or_update_mirror() -- real clone/fetch+reset lifecycle (update-slice)
# ---------------------------------------------------------------------------


def test_clone_or_update_mirror_clones_when_absent(tmp_path):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"

    result = mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root
    )

    assert result["ok"] is True
    assert result["offline"] is False
    assert result["action"] == "cloned"
    assert result["path"] == str(mirror_root / "foundation")
    assert (mirror_root / "foundation" / "agents" / "sec.md").read_text() == "v1"


def test_clone_or_update_mirror_updates_via_fetch_reset(tmp_path):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"

    first = mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root
    )

    # Upstream advances.
    (source / "agents" / "sec.md").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "commit", "-aqm", "v2"], cwd=source, check=True)

    second = mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root
    )

    assert second["ok"] is True
    assert second["action"] == "updated"
    assert second["head_sha"] != first["head_sha"]
    assert (mirror_root / "foundation" / "agents" / "sec.md").read_text() == "v2"


def test_clone_or_update_mirror_never_destroy_proof_confined_to_tier_subdir(tmp_path):
    """NEVER-DESTROY #3: mirror reset --hard writes stay confined to
    <mirror_root>/<tier> -- nothing outside it is ever touched."""
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"
    mirror_root.mkdir()

    # A sentinel completely outside mirror_root.
    outside_sentinel = tmp_path / "outside-sentinel.txt"
    outside_sentinel.write_text("do not touch", encoding="utf-8")

    # A sentinel for an unrelated tier inside mirror_root.
    other_tier_dir = mirror_root / "other-tier"
    other_tier_dir.mkdir()
    other_tier_sentinel = other_tier_dir / "marker.txt"
    other_tier_sentinel.write_text("other tier content", encoding="utf-8")

    before_outside = outside_sentinel.read_bytes()
    before_other_tier = other_tier_sentinel.read_bytes()

    mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root
    )
    # And a second call (the fetch+reset path) to exercise reset --hard too.
    (source / "agents" / "sec.md").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "commit", "-aqm", "v2"], cwd=source, check=True)
    mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root
    )

    assert outside_sentinel.read_bytes() == before_outside
    assert other_tier_sentinel.read_bytes() == before_other_tier
    # Only the "foundation" tier subdir was created/modified.
    assert set(p.name for p in mirror_root.iterdir()) == {"other-tier", "foundation"}


def test_clone_or_update_mirror_offline_is_honest_no_crash(tmp_path):
    unreachable_source = str(tmp_path / "does-not-exist-at-all")
    mirror_root = tmp_path / "mirrors"

    result = mirror.clone_or_update_mirror(
        "foundation", unreachable_source, "main", mirror_root=mirror_root
    )

    assert result["ok"] is False
    assert result["offline"] is True
    assert result["error"]
    # No partial/corrupt clone left behind.
    assert not (mirror_root / "foundation" / ".git").exists()


def test_clone_or_update_mirror_offline_leaves_existing_cache_untouched(tmp_path):
    """A prior good clone must never be destroyed just because a later
    fetch/reset attempt goes offline."""
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"

    mirror.clone_or_update_mirror("foundation", str(source), "main", mirror_root=mirror_root)
    cached_content_before = (mirror_root / "foundation" / "agents" / "sec.md").read_bytes()

    # Source becomes unreachable (simulate by pointing fetch at a dead path
    # via a broken 'origin' remote is complex; simplest honest simulation:
    # remove the source repo entirely so `git fetch` fails).
    shutil.rmtree(source)

    result = mirror.clone_or_update_mirror("foundation", str(source), "main", mirror_root=mirror_root)

    assert result["offline"] is True
    assert (mirror_root / "foundation" / "agents" / "sec.md").read_bytes() == cached_content_before


def test_clone_or_update_mirror_never_resolves_home_when_injected(tmp_path):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    # The autouse _no_real_home fixture would fail this test if
    # clone_or_update_mirror touched Path.home() at all when mirror_root
    # is supplied.
    mirror.clone_or_update_mirror("foundation", str(source), "main", mirror_root=tmp_path / "mirrors")
