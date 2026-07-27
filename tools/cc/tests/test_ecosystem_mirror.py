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


# ---------------------------------------------------------------------------
# Private-repo transport: optional token auth (update-slice gap #1)
# ---------------------------------------------------------------------------


def _b64_basic_header(token: str) -> str:
    import base64

    encoded = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    return f"Authorization: Basic {encoded}"


def test_basic_auth_header_uses_x_access_token_convention():
    header = mirror._basic_auth_header("secret-token-123")
    assert header == _b64_basic_header("secret-token-123")
    assert header.startswith("Authorization: Basic ")


def test_resolve_effective_token_explicit_override_wins(tmp_path):
    # Explicit override applies even for a plain local path (not https) --
    # lets tests spy on the argv plumbing without a real https remote.
    assert mirror._resolve_effective_token(str(tmp_path), "explicit-token") == "explicit-token"


def test_resolve_effective_token_explicit_none_forces_anonymous():
    assert mirror._resolve_effective_token("https://example.invalid/repo.git", None) is None


def test_resolve_effective_token_auto_resolve_skipped_for_non_https_source(tmp_path):
    # Sentinel default ("not overridden") + a plain local path source must
    # NEVER call resolve_token() (which would hit authstore/keychain) --
    # asserted indirectly: this must not raise despite Path.home() being
    # poisoned by the autouse fixture.
    assert mirror._resolve_effective_token(str(tmp_path), mirror._UNSET) is None


def test_resolve_effective_token_auto_resolve_attempted_for_https_source(monkeypatch):
    monkeypatch.setattr(mirror, "resolve_token", lambda: "auto-resolved-token")
    assert (
        mirror._resolve_effective_token("https://example.invalid/repo.git", mirror._UNSET)
        == "auto-resolved-token"
    )


def test_resolve_token_soft_dependency_no_identity_returns_none():
    assert (
        mirror.resolve_token(
            _read_identity=lambda: {},
            _get_secret=lambda *a, **k: "should-never-be-reached",
            _keychain_service="svc",
        )
        is None
    )


def test_resolve_token_soft_dependency_identity_read_raises_returns_none():
    def _boom():
        raise RuntimeError("no identity file")

    assert (
        mirror.resolve_token(
            _read_identity=_boom,
            _get_secret=lambda *a, **k: "should-never-be-reached",
            _keychain_service="svc",
        )
        is None
    )


def test_resolve_token_soft_dependency_keychain_miss_returns_none():
    assert (
        mirror.resolve_token(
            _read_identity=lambda: {"login": "octocat"},
            _get_secret=lambda *a, **k: None,
            _keychain_service="svc",
        )
        is None
    )


def test_resolve_token_soft_dependency_keychain_raises_returns_none():
    def _boom(*_a, **_k):
        raise RuntimeError("Keychain unavailable")

    assert (
        mirror.resolve_token(
            _read_identity=lambda: {"login": "octocat"},
            _get_secret=_boom,
            _keychain_service="svc",
        )
        is None
    )


def test_resolve_token_uses_login_as_keychain_account_and_configured_service():
    calls = []

    def _spy_get_secret(account, *, service, **_kwargs):
        calls.append((account, service))
        return "the-real-token"

    result = mirror.resolve_token(
        _read_identity=lambda: {"login": "octocat", "scopes": "repo"},
        _get_secret=_spy_get_secret,
        _keychain_service="com.example.test",
    )

    assert result == "the-real-token"
    assert calls == [("octocat", "com.example.test")]


def test_clone_or_update_mirror_injects_auth_header_on_clone_and_fetch(tmp_path, monkeypatch):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"

    real_run = subprocess.run
    captured_argvs: list[list[str]] = []

    def _spy_run(argv, **kwargs):
        captured_argvs.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy_run)

    token = "my-secret-token"
    expected_header_arg = f"http.extraHeader={_b64_basic_header(token)}"

    # First call: clone.
    mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root, _token=token
    )
    clone_argv = next(a for a in captured_argvs if "clone" in a)
    assert clone_argv[0] == "git"
    assert clone_argv[1] == "-c"
    assert clone_argv[2] == expected_header_arg
    assert clone_argv.index("clone") > clone_argv.index(expected_header_arg)

    # Second call: fetch+reset (the "updated" path) must also carry it on
    # fetch (never on reset/rev-parse, which need no network auth).
    captured_argvs.clear()
    (source / "agents" / "sec.md").write_text("v2", encoding="utf-8")
    real_run(["git", "commit", "-aqm", "v2"], cwd=source, check=True)
    mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root, _token=token
    )
    fetch_argv = next(a for a in captured_argvs if "fetch" in a)
    assert expected_header_arg in fetch_argv

    reset_argv = next(a for a in captured_argvs if "reset" in a)
    assert "-c" not in reset_argv
    assert expected_header_arg not in reset_argv

    rev_parse_argv = next(a for a in captured_argvs if "rev-parse" in a)
    assert "-c" not in rev_parse_argv


def test_clone_or_update_mirror_token_never_written_to_git_config(tmp_path):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"
    token = "super-secret-do-not-persist"

    mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root, _token=token
    )

    git_config_text = (mirror_root / "foundation" / ".git" / "config").read_text(
        encoding="utf-8"
    )
    assert token not in git_config_text
    assert "extraHeader" not in git_config_text
    assert "Authorization" not in git_config_text

    # Second call exercises the fetch+reset ("updated") path too.
    (source / "agents" / "sec.md").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "commit", "-aqm", "v2"], cwd=source, check=True)
    mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root, _token=token
    )

    git_config_text_after = (mirror_root / "foundation" / ".git" / "config").read_text(
        encoding="utf-8"
    )
    assert token not in git_config_text_after
    assert "extraHeader" not in git_config_text_after


def test_clone_or_update_mirror_token_never_in_result_dict(tmp_path):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"
    token = "another-secret-token-value"

    result = mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root, _token=token
    )

    serialized = json.dumps(result)
    assert token not in serialized
    assert "Authorization" not in serialized


def test_clone_or_update_mirror_no_token_omits_extra_header_flag(tmp_path, monkeypatch):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"

    real_run = subprocess.run
    captured_argvs: list[list[str]] = []

    def _spy_run(argv, **kwargs):
        captured_argvs.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy_run)

    # Explicit anonymous (bypasses the https-only auto-resolve check).
    mirror.clone_or_update_mirror(
        "foundation", str(source), "main", mirror_root=mirror_root, _token=None
    )

    clone_argv = next(a for a in captured_argvs if "clone" in a)
    assert clone_argv == ["git", "clone", "--quiet", "--origin", "origin", str(source), str(mirror_root / "foundation")]
    assert "-c" not in clone_argv


def test_clone_or_update_mirror_default_https_source_soft_dependency_no_crash(tmp_path):
    """An https:// source with no `_token` override exercises the full
    auto-resolve path (resolve_token() -> authstore.read_identity(), which
    -- with no `_root` injected -- resolves the real `Path.home()`; this
    module's `_no_real_home` autouse fixture makes that raise
    `AssertionError`). `resolve_token()`'s soft-dependency contract
    (`except Exception: return None`) must swallow that and fall back to
    anonymous rather than letting it propagate -- proving the "never
    raises" contract even when the identity layer itself blows up, not
    just when it cleanly reports 'not signed in'."""
    mirror_root = tmp_path / "mirrors"

    result = mirror.clone_or_update_mirror(
        "foundation",
        "https://example.invalid/does-not-exist/repo.git",
        "main",
        mirror_root=mirror_root,
        timeout=2.0,
    )

    assert result["ok"] is False
    assert result["offline"] is True
