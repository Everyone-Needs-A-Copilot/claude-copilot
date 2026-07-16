"""Tests for cc.core.ecosystem.component_status -- the per-(product, layer)
sync checkers that fold into `cc doctor --json`'s `checkers[]`.

All paths are tmp_path-injected (or in-memory dicts); the autouse fixture
below asserts Path.home() is never resolved as a fallback -- mirrors
core/ecosystem/mirror.py's / core/ecosystem/freshness.py's own test
convention.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem import mirror
from cc.core.ecosystem.component_status import Checker, compute_component_checkers
from cc.core.ecosystem.freshness import lock_fingerprint


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "component_status test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _layer(**overrides) -> dict:
    base = {
        "id": "foundation",
        "role": "foundation",
        "rank": 40,
        "product": "knowledge",
        "source": {"repo": "https://example.invalid/foundation.git"},
        "auth": "anon",
        "activation": "always",
    }
    base.update(overrides)
    return base


def _never_reaches_remote(_repo: str, _ref: str):
    return None


# ---------------------------------------------------------------------------
# checker id / attribution
# ---------------------------------------------------------------------------


def test_checker_id_is_product_layer_sync():
    layer = _layer(id="org", product="cli")
    checkers, _ = compute_component_checkers(
        [layer], lockfile={}, latest_sha_fn=lambda repo, ref: "abc1234"
    )
    assert checkers[0].id == "cli-org-sync"
    assert checkers[0].layer == "org"
    assert checkers[0].product == "cli"


def test_skips_malformed_layer_missing_id_or_product():
    """A layer manifest.validate_layers() should already have rejected --
    defensively skipped here rather than crashing a health check."""
    checkers, offline = compute_component_checkers(
        [{"product": "cli"}, {"id": "org"}], lockfile={}, latest_sha_fn=lambda r, f: "x"
    )
    assert checkers == []
    assert offline is False


# ---------------------------------------------------------------------------
# severity fold: pass / warn-behind / warn-offline
# ---------------------------------------------------------------------------


def test_pass_when_local_matches_remote():
    layer = _layer(id="org")
    lock = {"org": {"agents": {"sec": "abc1234"}}}
    local_sha = lock_fingerprint(lock["org"])

    checkers, offline = compute_component_checkers(
        [layer], lockfile=lock, latest_sha_fn=lambda repo, ref: local_sha
    )

    assert len(checkers) == 1
    checker = checkers[0]
    assert checker.severity == "pass"
    assert checker.local_sha == local_sha
    assert checker.remote_sha == local_sha
    assert "matches remote" in checker.detail
    assert offline is False


def test_warn_behind_when_shas_differ():
    layer = _layer(id="org")
    lock = {"org": {"agents": {"sec": "abc1234"}}}

    checkers, offline = compute_component_checkers(
        [layer], lockfile=lock, latest_sha_fn=lambda repo, ref: "def5678def5678def5678def5678def5678123"
    )

    checker = checkers[0]
    assert checker.severity == "warn"
    assert checker.remote_sha == "def5678def5678def5678def5678def5678123"
    assert checker.repair == "cc update"
    assert "behind remote" in checker.detail
    assert offline is False


def test_local_sha_none_when_layer_never_materialized():
    layer = _layer(id="org")

    checkers, _ = compute_component_checkers(
        [layer], lockfile={}, latest_sha_fn=lambda repo, ref: "abc1234"
    )

    checker = checkers[0]
    assert checker.local_sha is None
    assert checker.severity == "warn"  # None != "abc1234" -- behind, not fabricated pass


def test_local_sha_excludes_reserved_meta_block():
    """The `_meta` block (product/tier/role) is descriptive, not a content
    pin -- must not perturb the fingerprint or count as "has local content"."""
    layer = _layer(id="org")
    lock_with_meta = {
        "org": {"agents": {"sec": "abc1234"}, "_meta": {"product": "knowledge", "tier": "org"}}
    }
    lock_without_meta = {"org": {"agents": {"sec": "abc1234"}}}

    checkers_a, _ = compute_component_checkers(
        [layer], lockfile=lock_with_meta, latest_sha_fn=_never_reaches_remote
    )
    checkers_b, _ = compute_component_checkers(
        [layer], lockfile=lock_without_meta, latest_sha_fn=_never_reaches_remote
    )
    assert checkers_a[0].local_sha == checkers_b[0].local_sha


def test_local_sha_none_when_layer_has_only_meta_block():
    layer = _layer(id="org")
    lock = {"org": {"_meta": {"product": "knowledge"}}}

    checkers, _ = compute_component_checkers(
        [layer], lockfile=lock, latest_sha_fn=lambda repo, ref: "abc1234"
    )
    assert checkers[0].local_sha is None


def test_warn_offline_and_signal_when_remote_unreachable_and_no_mirror():
    layer = _layer(id="org")
    lock = {"org": {"agents": {"sec": "abc1234"}}}

    checkers, offline = compute_component_checkers(
        [layer], lockfile=lock, latest_sha_fn=_never_reaches_remote, mirror_root=None
    )

    checker = checkers[0]
    assert checker.severity == "warn"
    assert checker.remote_sha is None
    assert "could not reach remote" in checker.detail
    assert offline is True


def test_no_repo_source_never_calls_latest_sha_fn(tmp_path):
    calls: list[str] = []

    def _tracking(repo, ref):
        calls.append(repo)
        return "shouldnt-happen"

    layer = _layer(id="personal", source={})
    checkers, offline = compute_component_checkers(
        [layer], lockfile={}, latest_sha_fn=_tracking
    )

    assert calls == []
    assert checkers[0].remote_sha is None
    assert offline is True


# ---------------------------------------------------------------------------
# mirror-clone-HEAD fallback -- when the lock-pointer poll comes back
# unknown but a mirror already exists on disk
# ---------------------------------------------------------------------------


def _make_content_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=repo, check=True)
    for relpath, content in files.items():
        target = repo / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_falls_back_to_mirror_clone_head_when_lock_pointer_unknown(tmp_path):
    source = _make_content_repo(tmp_path, {"agents/sec.md": "v1"})
    mirror_root = tmp_path / "mirrors"

    sync = mirror.clone_or_update_mirror("foundation", str(source), "main", mirror_root=mirror_root)
    assert sync["ok"] is True

    layer = _layer(id="foundation", source={"repo": str(source), "ref": "main"})

    checkers, offline = compute_component_checkers(
        [layer],
        lockfile={},
        latest_sha_fn=_never_reaches_remote,
        mirror_root=mirror_root,
    )

    checker = checkers[0]
    assert checker.remote_sha == sync["head_sha"]
    assert checker.remote_sha is not None
    # A real fallback value was found -- this is not the "could not reach
    # remote at all" case, so no offline signal.
    assert offline is False


def test_mirror_root_none_never_falls_back_and_never_touches_home(tmp_path):
    """No mirror_root injected (None) -- the fallback must cleanly no-op,
    never attempt to resolve Path.home() itself."""
    layer = _layer(id="foundation")
    checkers, offline = compute_component_checkers(
        [layer], lockfile={}, latest_sha_fn=_never_reaches_remote, mirror_root=None
    )
    assert checkers[0].remote_sha is None
    assert offline is True


def test_mirror_root_present_but_no_clone_on_disk_is_none(tmp_path):
    layer = _layer(id="foundation")
    checkers, offline = compute_component_checkers(
        [layer], lockfile={}, latest_sha_fn=_never_reaches_remote, mirror_root=tmp_path / "mirrors"
    )
    assert checkers[0].remote_sha is None
    assert offline is True


# ---------------------------------------------------------------------------
# to_contract_dict()
# ---------------------------------------------------------------------------


def test_to_contract_dict_field_set_matches_corpus_shape():
    checker = Checker(
        id="knowledge-foundation-sync",
        severity="pass",
        layer="foundation",
        product="knowledge",
        detail="foundation tip matches remote",
        local_sha="a1b2c3d",
        remote_sha="a1b2c3d",
    )
    d = checker.to_contract_dict()
    assert d == {
        "id": "knowledge-foundation-sync",
        "severity": "pass",
        "destructive": False,
        "layer": "foundation",
        "product": "knowledge",
        "detail": "foundation tip matches remote",
        "local_sha": "a1b2c3d",
        "remote_sha": "a1b2c3d",
    }


def test_to_contract_dict_omits_absent_optional_fields():
    checker = Checker(id="x", severity="warn")
    d = checker.to_contract_dict()
    assert d == {"id": "x", "severity": "warn", "destructive": False}
