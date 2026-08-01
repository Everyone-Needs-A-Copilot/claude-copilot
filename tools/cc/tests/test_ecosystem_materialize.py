"""Tests for cc.core.ecosystem.materialize -- the reconciling sync.

These are the NEVER-DESTROY proofs (see the WS-A update-slice task brief):
  1. A dirty/personal file in a protected path is left BYTE-IDENTICAL
     across an update -- guard_personal() refuses to touch it.
  2. Pruning only removes items the engine previously materialized AND
     that left the resolved set -- an unrelated/personal file is never
     pruned.
  3. (mirror confinement -- see tests/test_ecosystem_mirror.py)

All roots are tmp_path-injected; the autouse fixture asserts Path.home()
is never resolved as a fallback -- materialize() never has a reason to
call it (every root is a required keyword argument).
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.materialize import (
    guard_personal,
    guard_personal_reason,
    materialize,
    materialize_ecosystem_config,
)
from cc.core.ecosystem.policy import evaluate as fail_closed_policy
from cc.core.ecosystem.policy import permissive_policy
from cc.core.ecosystem.resolver import resolve_layers


@pytest.fixture(autouse=True)
def _no_real_home(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError(
            "materialize test attempted to resolve Path.home() -- inject tmp_path instead"
        )

    monkeypatch.setattr(Path, "home", staticmethod(_boom))


def _layer(layer_id: str, rank: int, local_path: Path) -> dict:
    return {
        "id": layer_id,
        "role": "foundation",
        "rank": rank,
        "product": "claude",
        "source": {"repo": f"https://example.invalid/{layer_id}.git", "path": str(local_path)},
        "auth": "anon",
        "activation": "always",
    }


def _resolved_and_paths(tmp_path: Path, layer_root: Path, layer_id: str = "foundation"):
    layers = [_layer(layer_id, 40, layer_root)]
    contributions = discover_contributions(layers)
    resolved = resolve_layers(layers, contributions, lockfile={})
    source_paths = {layer_id: layer_root}
    return resolved, source_paths


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def _git_init_with_remote(repo: Path, remote_url: str = "https://example.invalid/org-repo.git") -> None:
    """A CLEAN, tracked git working tree with a configured remote -- the
    exact shape of the P0 incident's authoring repo (knowledge-copilot-
    internal): committed, not dirty, but a real clone of somewhere."""
    _git_init(repo)
    subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=repo, check=True)


def _fingerprint_tree(path: Path) -> str:
    """Whole-tree content fingerprint (sorted relative-path + bytes) --
    used to prove an authoring repo is BYTE-IDENTICAL before/after a
    materialize run that should have refused to touch it at all."""
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_file():
            digest.update(child.relative_to(path).as_posix().encode("utf-8"))
            digest.update(child.read_bytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# guard_personal()
# ---------------------------------------------------------------------------


def test_guard_personal_flags_path_under_a_personal_root(tmp_path):
    personal_root = tmp_path / "personal-vault"
    personal_root.mkdir()
    target = personal_root / "notes" / "x.md"

    assert guard_personal(target, personal_roots=[personal_root]) is True


def test_guard_personal_does_not_false_positive_on_similar_prefix(tmp_path):
    personal_root = tmp_path / "personal"
    personal_root.mkdir()
    (tmp_path / "personal-2").mkdir()
    unrelated = tmp_path / "personal-2" / "x.md"

    assert guard_personal(unrelated, personal_roots=[personal_root]) is False


def test_guard_personal_flags_dirty_git_working_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    tracked = repo / "agents" / "qa.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    # Now dirty it (uncommitted local edit).
    tracked.write_text("locally edited", encoding="utf-8")

    assert guard_personal(tracked, personal_roots=[]) is True


def test_guard_personal_clean_git_tree_is_not_flagged(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    tracked = repo / "agents" / "qa.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    assert guard_personal(tracked, personal_roots=[]) is False


def test_guard_personal_non_git_non_personal_path_is_not_flagged(tmp_path):
    plain = tmp_path / "materialize-root" / "agents" / "qa.md"
    plain.parent.mkdir(parents=True)
    plain.write_text("x", encoding="utf-8")

    assert guard_personal(plain, personal_roots=[]) is False


# ---------------------------------------------------------------------------
# guard_personal() -- WP-372 P0.3: symlink escape / clean tracked repo
# ---------------------------------------------------------------------------


def test_guard_personal_symlink_escaping_materialize_root_is_flagged(tmp_path):
    materialize_root = tmp_path / "claude-materialize"
    materialize_root.mkdir()

    authoring_repo = tmp_path / "org-authoring-repo"
    authoring_repo.mkdir()
    _git_init_with_remote(authoring_repo)
    (authoring_repo / "item.md").write_text("org content", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=authoring_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=authoring_repo, check=True)

    # The exact incident shape: a dimension directory that is ITSELF a
    # symlink into a real authoring checkout.
    (materialize_root / "knowledge").symlink_to(authoring_repo, target_is_directory=True)
    target = materialize_root / "knowledge" / "item.md"

    reason = guard_personal_reason(target, materialize_root=materialize_root)
    assert reason is not None
    assert "symlink" in reason
    assert str(materialize_root / "knowledge") in reason
    assert str(authoring_repo.resolve()) in reason
    assert guard_personal(target, materialize_root=materialize_root) is True


def test_guard_personal_symlink_within_root_still_works(tmp_path):
    """A symlink that stays confined inside the materialize root (a
    legitimate in-tree alias) must NOT be treated as an escape."""
    materialize_root = tmp_path / "claude-materialize"
    real_dir = materialize_root / "agents" / "_archive"
    real_dir.mkdir(parents=True)
    (real_dir / "qa.md").write_text("archived", encoding="utf-8")

    alias = materialize_root / "agents" / "qa-alias"
    alias.symlink_to(real_dir, target_is_directory=True)
    target = alias / "qa.md"

    assert guard_personal_reason(target, materialize_root=materialize_root) is None
    assert guard_personal(target, materialize_root=materialize_root) is False


def test_guard_personal_clean_tracked_repo_with_remote_flagged_without_symlink(tmp_path):
    """Direct misconfiguration (materialize_root itself IS an authoring
    checkout, no symlink involved) must also be caught -- the symlink is
    one mechanism for this hole, not the only one."""
    materialize_root = tmp_path / "materialize-root-is-authoring-repo"
    materialize_root.mkdir()
    _git_init_with_remote(materialize_root)
    target = materialize_root / "agents" / "qa.md"
    target.parent.mkdir(parents=True)
    target.write_text("org content", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=materialize_root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=materialize_root, check=True)

    reason = guard_personal_reason(target, materialize_root=materialize_root)
    assert reason is not None
    assert "configured remote" in reason
    assert guard_personal(target, materialize_root=materialize_root) is True


def test_guard_personal_clean_tracked_repo_check_not_applied_without_materialize_root(tmp_path):
    """The clean-tracked-repo check is gated on `materialize_root` being
    passed -- callers that never pass it (deprovision.py's mirror wipe,
    projects.py's fanout) must see their pre-P0.3 behavior unchanged."""
    repo = tmp_path / "repo-with-remote"
    repo.mkdir()
    _git_init_with_remote(repo)
    tracked = repo / "agents" / "qa.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    # No materialize_root passed -- checks 2/3 never run; a CLEAN tree
    # (even with a remote) is not flagged via checks 1/4 alone.
    assert guard_personal(tracked, personal_roots=[]) is False


def test_guard_personal_mirror_root_exempts_clean_tracked_repo_check(tmp_path):
    """A target that legitimately resolves into a registered mirror root
    must not be refused just for being a clean git repo with a remote --
    mirrors are disposable by construction."""
    materialize_root = tmp_path / "materialize-root"
    materialize_root.mkdir()
    mirror_root = tmp_path / "mirrors"
    mirror_clone = mirror_root / "some-tier"
    mirror_clone.mkdir(parents=True)
    _git_init_with_remote(mirror_clone)
    target = mirror_clone / "agents" / "qa.md"
    target.parent.mkdir(parents=True)
    target.write_text("mirror content", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=mirror_clone, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=mirror_clone, check=True)

    reason = guard_personal_reason(
        target, materialize_root=mirror_root, mirror_roots=[mirror_root]
    )
    assert reason is None


def test_guard_personal_clean_tree_without_remote_unprotected_even_with_materialize_root(
    tmp_path,
):
    """A bare `git init` scratch tree with NO remote configured (this test
    module's own `_git_init()` fixture shape) must stay unprotected even
    when `materialize_root` IS passed -- proves check 3 doesn't over-fire
    against every git-tracked materialize root, only ones with a remote."""
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    _git_init(materialize_root)  # no remote
    tracked = materialize_root / "agents" / "qa.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=materialize_root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=materialize_root, check=True)

    assert guard_personal_reason(tracked, materialize_root=materialize_root) is None


# ---------------------------------------------------------------------------
# materialize() -- reconcile correctness
# ---------------------------------------------------------------------------


def test_materialize_added_item_appears(tmp_path):
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("qa body", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    materialize_root = tmp_path / "materialize"

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    dest = materialize_root / "agents" / "qa.md"
    assert dest.read_text() == "qa body"
    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert len(ops) == 1 and ops[0]["op"] == "added"
    assert report["lock"]["foundation"]["agents"]["qa"]


def test_materialize_changed_item_updates(tmp_path):
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("v2", encoding="utf-8")

    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "agents" / "qa.md").write_text("v1", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    previous_lock = {"foundation": {"agents": {"qa": "old-sha"}}}

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock=previous_lock,
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    assert (materialize_root / "agents" / "qa.md").read_text() == "v2"
    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert ops[0]["op"] == "updated"


def test_materialize_unchanged_item_is_left_alone(tmp_path):
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("same", encoding="utf-8")

    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "agents" / "qa.md").write_text("same", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={"foundation": {"agents": {"qa": "some-sha"}}},
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert ops[0]["op"] == "unchanged"


def test_materialize_removed_from_resolved_is_pruned(tmp_path):
    """Reconcile correctness: an item that no longer resolves (removed
    upstream) is pruned from the materialize root."""
    layer_root = tmp_path / "foundation-src"
    layer_root.mkdir()  # no agents/ dir at all this round -- item is gone

    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "agents" / "qa.md").write_text("stale", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    assert resolved == []  # nothing resolves this round

    previous_lock = {"foundation": {"agents": {"qa": "old-sha"}}}

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock=previous_lock,
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    assert not (materialize_root / "agents" / "qa.md").exists()
    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert ops[0]["op"] == "pruned"
    assert "qa" not in report["lock"].get("foundation", {}).get("agents", {})


def test_materialize_ownership_move_across_layers_is_not_pruned(tmp_path):
    """An item still resolving (just under a DIFFERENT winning layer this
    round) must never be treated as orphaned/pruned."""
    old_layer_root = tmp_path / "org-src"
    old_layer_root.mkdir()  # org no longer contributes "qa" this round

    new_layer_root = tmp_path / "foundation-src"
    (new_layer_root / "agents").mkdir(parents=True)
    (new_layer_root / "agents" / "qa.md").write_text("from foundation now", encoding="utf-8")

    layers = [
        _layer("org", 20, old_layer_root),
        _layer("foundation", 40, new_layer_root),
    ]
    contributions = discover_contributions(layers)
    resolved = resolve_layers(layers, contributions, lockfile={})

    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)
    (materialize_root / "agents" / "qa.md").write_text("from org previously", encoding="utf-8")

    previous_lock = {"org": {"agents": {"qa": "org-sha"}}}

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock=previous_lock,
        layer_source_paths={"org": old_layer_root, "foundation": new_layer_root},
        policy=permissive_policy,
    )

    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert all(o["op"] != "pruned" for o in ops)
    assert (materialize_root / "agents" / "qa.md").read_text() == "from foundation now"


# ---------------------------------------------------------------------------
# NEVER-DESTROY #1: dirty/personal file stays byte-identical
# ---------------------------------------------------------------------------


def test_never_destroy_dirty_personal_file_untouched_across_update(tmp_path):
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("new upstream content", encoding="utf-8")

    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    _git_init(materialize_root)
    dest_file = materialize_root / "agents" / "qa.md"
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    dest_file.write_text("committed baseline", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=materialize_root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=materialize_root, check=True)

    # Human edits it locally -- uncommitted, dirty.
    dest_file.write_text("Bob's uncommitted personal edit", encoding="utf-8")
    hash_before = dest_file.read_bytes()

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    previous_lock = {"foundation": {"agents": {"qa": "old-sha"}}}

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock=previous_lock,
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    hash_after = dest_file.read_bytes()
    assert hash_after == hash_before  # BYTE-IDENTICAL -- never touched

    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert ops[0]["op"] == "held"
    assert "personal" in ops[0]["reason"] or "dirty" in ops[0]["reason"]


# ---------------------------------------------------------------------------
# NEVER-DESTROY #2: prune never touches an unrelated/personal file
# ---------------------------------------------------------------------------


def test_never_destroy_prune_never_touches_unrelated_personal_file(tmp_path):
    layer_root = tmp_path / "foundation-src"
    layer_root.mkdir()  # nothing resolves this round

    materialize_root = tmp_path / "materialize"
    (materialize_root / "agents").mkdir(parents=True)

    # A file the engine DID previously materialize and pin -- eligible for pruning.
    engine_owned = materialize_root / "agents" / "qa.md"
    engine_owned.write_text("engine-owned, orphaned this round", encoding="utf-8")

    # A file the engine never pinned at all -- must NEVER be pruned,
    # regardless of what's physically sitting next to it.
    unrelated_personal = materialize_root / "agents" / "personal-notes.md"
    unrelated_personal.write_text("Bob's own notes, not lock-tracked", encoding="utf-8")
    hash_before = unrelated_personal.read_bytes()

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    previous_lock = {"foundation": {"agents": {"qa": "old-sha"}}}

    materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock=previous_lock,
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    assert not engine_owned.exists()  # correctly pruned (orphaned, engine-owned)
    assert unrelated_personal.exists()  # NEVER pruned -- not in previous_lock at all
    assert unrelated_personal.read_bytes() == hash_before


def test_never_destroy_prune_skips_a_personal_protected_path(tmp_path):
    """Even if an item WAS previously lock-tracked, prune must still defer
    to guard_personal (e.g. the materialize root itself became a dirty
    git tree since)."""
    layer_root = tmp_path / "foundation-src"
    layer_root.mkdir()

    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    _git_init(materialize_root)
    tracked = materialize_root / "agents" / "qa.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=materialize_root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=materialize_root, check=True)
    tracked.write_text("dirty local edit", encoding="utf-8")
    hash_before = tracked.read_bytes()

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    previous_lock = {"foundation": {"agents": {"qa": "old-sha"}}}

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock=previous_lock,
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    assert tracked.exists()
    assert tracked.read_bytes() == hash_before
    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert ops[0]["op"] == "held"


# ---------------------------------------------------------------------------
# NEVER-DESTROY #3: WP-372 P0.3 -- REPRODUCE THE EXACT INCIDENT SHAPE
#
# The live P0: `~/.claude/knowledge` was a symlink into the org authoring
# repo `knowledge-copilot-internal` (clean, tracked, real remote). A
# materialize run resolved a personal-layer "knowledge" item, wrote/pruned
# through the symlink, and reconcile-deleted 12,537 lines of the org repo.
# These tests build that EXACT fixture shape (symlink dimension directory
# -> a separate, clean, git-tracked "authoring repo" with a remote and its
# own unrelated content) and assert the fixed guard refuses on both the
# write path and the prune path, with the authoring repo BYTE-IDENTICAL
# before/after and a structured (non-crashing) reason -- never a
# traceback, never a silent skip.
# ---------------------------------------------------------------------------


def _make_incident_fixture(tmp_path: Path):
    """Build the exact incident shape: `materialize_root/knowledge` is a
    symlink into a separate, clean, git-tracked authoring repo with a
    remote and its own real content (unrelated to anything this
    materialize run is trying to place). Returns
    (materialize_root, authoring_repo)."""
    materialize_root = tmp_path / "claude-materialize"
    materialize_root.mkdir()

    authoring_repo = tmp_path / "knowledge-copilot-internal"
    authoring_repo.mkdir()
    _git_init_with_remote(authoring_repo)
    (authoring_repo / "01-company").mkdir()
    (authoring_repo / "01-company" / "brand.md").write_text(
        "brand voice, unrelated to this materialize run", encoding="utf-8"
    )
    (authoring_repo / ".claude" / "agents").mkdir(parents=True)
    (authoring_repo / ".claude" / "agents" / "cw.md").write_text(
        "org agent extension", encoding="utf-8"
    )
    # The other 3 top-level names the real incident's personal layer
    # "owned" (and reconcile-deleted) alongside `.claude`.
    (authoring_repo / "docs").mkdir()
    (authoring_repo / "docs" / "consumption-contract.md").write_text(
        "org docs", encoding="utf-8"
    )
    (authoring_repo / "knowledge-manifest").mkdir()
    (authoring_repo / "knowledge-manifest" / "v1.json").write_text("{}", encoding="utf-8")
    (authoring_repo / "skills").mkdir()
    (authoring_repo / "skills" / "README.md").write_text("org skills", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=authoring_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "org content"], cwd=authoring_repo, check=True)

    (materialize_root / "knowledge").symlink_to(authoring_repo, target_is_directory=True)
    return materialize_root, authoring_repo


def test_incident_reproduction_write_path_refuses_through_symlinked_dimension(tmp_path):
    materialize_root, authoring_repo = _make_incident_fixture(tmp_path)
    fingerprint_before = _fingerprint_tree(authoring_repo)

    layer_root = tmp_path / "personal-src"
    (layer_root / "knowledge").mkdir(parents=True)
    (layer_root / "knowledge" / ".claude").mkdir()
    (layer_root / "knowledge" / ".claude" / "settings.json").write_text(
        "{}", encoding="utf-8"
    )
    resolved = [
        {
            "product": "claude",
            "dimension": "knowledge",
            "item": ".claude",
            "winning_layer": "claude-personal",
        }
    ]

    report = materialize(
        resolved,
        materialize_roots={"claude": materialize_root},
        layer_source_paths={"claude-personal": layer_root},
        layer_products={"claude-personal": "claude"},
        previous_lock={},
        policy=permissive_policy,
    )

    ops = [o for o in report["ops"] if o["item"] == ".claude"]
    assert len(ops) == 1
    assert ops[0]["op"] == "held"  # REFUSED -- never "added"/"updated"
    assert "symlink" in ops[0]["reason"]
    assert ops[0]["reason"]  # structured, non-empty -- never a crash

    # The authoring repo is BYTE-IDENTICAL after -- nothing was written
    # through the symlink.
    assert _fingerprint_tree(authoring_repo) == fingerprint_before
    assert (authoring_repo / ".claude" / "agents" / "cw.md").read_text() == "org agent extension"


def test_incident_reproduction_prune_path_refuses_through_symlinked_dimension(tmp_path):
    """Same fixture, but this time the item is no longer resolved at all
    this round (the prune path) -- reconcile-delete must ALSO refuse to
    delete through the symlink, exactly the mechanism that reconcile-
    deleted 12,537 lines of the real org repo."""
    materialize_root, authoring_repo = _make_incident_fixture(tmp_path)
    fingerprint_before = _fingerprint_tree(authoring_repo)

    layer_root = tmp_path / "personal-src"
    layer_root.mkdir()  # nothing resolves this round -- previously-lock-tracked item is "gone"

    previous_lock = {
        "claude-personal": {
            "knowledge": {
                ".claude": "old-sha",
                "docs": "old-sha",
                "knowledge-manifest": "old-sha",
                "skills": "old-sha",
            }
        }
    }

    report = materialize(
        [],
        materialize_roots={"claude": materialize_root},
        layer_source_paths={"claude-personal": layer_root},
        layer_products={"claude-personal": "claude"},
        previous_lock=previous_lock,
        policy=permissive_policy,
    )

    prune_ops = [o for o in report["ops"] if o["layer"] == "claude-personal"]
    assert prune_ops, "expected the prune loop to consider the 4 lock-tracked knowledge items"
    for op in prune_ops:
        assert op["op"] == "held"  # REFUSED -- never "pruned"
        assert "symlink" in op["reason"]

    # Nothing under the authoring repo was deleted or modified.
    assert _fingerprint_tree(authoring_repo) == fingerprint_before
    assert (authoring_repo / "01-company" / "brand.md").exists()
    assert (authoring_repo / ".claude" / "agents" / "cw.md").exists()


# ---------------------------------------------------------------------------
# Fail-closed policy default
# ---------------------------------------------------------------------------


def test_materialize_fail_closed_policy_blocks_unverified_item(tmp_path):
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("qa body", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    materialize_root = tmp_path / "materialize"

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        policy=fail_closed_policy,  # the PRODUCTION DEFAULT
    )

    assert not (materialize_root / "agents" / "qa.md").exists()
    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert ops[0]["op"] == "blocked"
    assert ops[0]["reason"] == "unverified"
    assert "foundation" not in report["lock"]  # nothing pinned -- never applied


def test_materialize_threads_layer_source_ref_into_policy_item(tmp_path):
    """G-9 (task 215 blocker fix): each layer's resolved/pinned
    `source.ref` reaches `policy.evaluate()`'s item dict as `item["ref"]`,
    so a foundation checkout that reached `reuse` via
    `parentless-snapshot-match` (task 209/G-7) can be verified against the
    commit the manifest actually pinned, not blind HEAD."""
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("qa body", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    materialize_root = tmp_path / "materialize"
    seen_refs = []

    def capture_ref_policy(item):
        seen_refs.append(item.get("ref"))
        return "allow"

    materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        layer_source_refs={"foundation": "v5.13.23"},
        policy=capture_ref_policy,
    )

    assert seen_refs == ["v5.13.23"]


def test_materialize_without_layer_source_refs_passes_none(tmp_path):
    """`layer_source_refs` is optional -- an omitted or unknown layer id
    must reach the policy item as `None`, never a KeyError, so every
    existing caller that doesn't know about pinned refs keeps working
    unchanged."""
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("qa body", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    materialize_root = tmp_path / "materialize"
    seen_refs = []

    def capture_ref_policy(item):
        seen_refs.append(item.get("ref"))
        return "allow"

    materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        policy=capture_ref_policy,
    )

    assert seen_refs == [None]


# ---------------------------------------------------------------------------
# Fold fallback: a policy-blocked OVERRIDE winner un-freezes to the next
# verified shadowed layer (task 220 Fix 1 -- WP-384's live regression: the
# org tier permanently wins commands/protocol's OVERRIDE fold but has no
# wired signer by design, so it is always `blocked: unverified`, and
# without a fallback the foundation's own (verified) copy underneath it
# could never materialize again).
# ---------------------------------------------------------------------------


def _two_layer_resolved(
    tmp_path: Path,
    *,
    winner_root: Path,
    shadow_root: Path,
    winner_id: str = "claude-organization",
    shadow_id: str = "claude-foundation",
    winner_rank: int = 20,
    shadow_rank: int = 40,
    lockfile: dict | None = None,
):
    layers = [
        _layer(winner_id, winner_rank, winner_root),
        _layer(shadow_id, shadow_rank, shadow_root),
    ]
    contributions = discover_contributions(layers)
    resolved = resolve_layers(layers, contributions, lockfile=lockfile or {})
    source_paths = {winner_id: winner_root, shadow_id: shadow_root}
    return resolved, source_paths


def test_materialize_falls_back_to_verified_shadow_when_winner_blocked(tmp_path):
    org_root = tmp_path / "org-src"
    (org_root / "commands").mkdir(parents=True)
    (org_root / "commands" / "protocol.md").write_text("org protocol", encoding="utf-8")

    foundation_root = tmp_path / "foundation-src"
    (foundation_root / "commands").mkdir(parents=True)
    (foundation_root / "commands" / "protocol.md").write_text(
        "foundation protocol", encoding="utf-8"
    )

    resolved, source_paths = _two_layer_resolved(
        tmp_path, winner_root=org_root, shadow_root=foundation_root
    )
    assert resolved[0]["winning_layer"] == "claude-organization"
    assert resolved[0]["shadowed"][0]["layer"] == "claude-foundation"

    def org_blocked_policy(item):
        return "block" if item["layer"] == "claude-organization" else "allow"

    materialize_root = tmp_path / "materialize"
    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        policy=org_blocked_policy,
    )

    materialized = materialize_root / "commands" / "protocol.md"
    assert materialized.read_text(encoding="utf-8") == "foundation protocol"

    op = next(o for o in report["ops"] if o["item"] == "protocol")
    assert op["op"] == "added"
    assert op["layer"] == "claude-foundation"  # the verified layer that actually landed
    assert op["blocked_winner"] == "claude-organization"  # the real, blocked winner
    assert op["reason"] is not None and "unverified" in op["reason"]

    # Materialized under the layer that actually supplied the content --
    # never silently pinned as if the blocked org layer had applied.
    assert report["lock"]["claude-foundation"]["commands"]["protocol"]
    assert "claude-organization" not in report["lock"]


def test_materialize_all_blocked_stays_blocked_honest_nothing_stale_kept(tmp_path):
    org_root = tmp_path / "org-src"
    (org_root / "commands").mkdir(parents=True)
    (org_root / "commands" / "protocol.md").write_text("org protocol", encoding="utf-8")

    foundation_root = tmp_path / "foundation-src"
    (foundation_root / "commands").mkdir(parents=True)
    (foundation_root / "commands" / "protocol.md").write_text(
        "foundation protocol", encoding="utf-8"
    )

    resolved, source_paths = _two_layer_resolved(
        tmp_path, winner_root=org_root, shadow_root=foundation_root
    )

    def all_blocked_policy(_item):
        return "block"

    materialize_root = tmp_path / "materialize"
    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        policy=all_blocked_policy,
    )

    assert not (materialize_root / "commands" / "protocol.md").exists()
    op = next(o for o in report["ops"] if o["item"] == "protocol")
    assert op["op"] == "blocked"
    assert op["layer"] == "claude-organization"  # still the real winner, honestly unapplied
    assert op["blocked_winner"] is None  # no substitution happened -- nothing to report
    assert op["reason"] == "unverified"
    assert report["lock"] == {}  # nothing pinned -- never applied, nothing stale kept


def test_materialize_winner_verified_no_fallback_substitution(tmp_path):
    """Both layers verify: the resolver's real winner materializes exactly
    as before Fix 1 -- the fallback path must never fire when it isn't
    needed."""
    org_root = tmp_path / "org-src"
    (org_root / "commands").mkdir(parents=True)
    (org_root / "commands" / "protocol.md").write_text("org protocol", encoding="utf-8")

    foundation_root = tmp_path / "foundation-src"
    (foundation_root / "commands").mkdir(parents=True)
    (foundation_root / "commands" / "protocol.md").write_text(
        "foundation protocol", encoding="utf-8"
    )

    resolved, source_paths = _two_layer_resolved(
        tmp_path, winner_root=org_root, shadow_root=foundation_root
    )

    materialize_root = tmp_path / "materialize"
    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        policy=permissive_policy,
    )

    materialized = materialize_root / "commands" / "protocol.md"
    assert materialized.read_text(encoding="utf-8") == "org protocol"

    op = next(o for o in report["ops"] if o["item"] == "protocol")
    assert op["op"] == "added"
    assert op["layer"] == "claude-organization"
    assert op["blocked_winner"] is None
    assert op["reason"] is None


def test_materialize_fallback_carries_forward_blocked_winners_own_prior_pin(tmp_path):
    """The blocked winner's own previously-recorded pin (if any -- e.g. a
    stale entry from before its content ever changed) is preserved
    untouched, not silently dropped or advanced, while the verified
    shadow layer's own prior pin is what actually informs `from`/`to` for
    the applied change."""
    org_root = tmp_path / "org-src"
    (org_root / "commands").mkdir(parents=True)
    (org_root / "commands" / "protocol.md").write_text("org protocol v2", encoding="utf-8")

    foundation_root = tmp_path / "foundation-src"
    (foundation_root / "commands").mkdir(parents=True)
    (foundation_root / "commands" / "protocol.md").write_text(
        "foundation protocol v2", encoding="utf-8"
    )

    previous_lock = {
        "claude-organization": {"commands": {"protocol": "org-sha-v1"}},
        "claude-foundation": {"commands": {"protocol": "foundation-sha-v1"}},
    }
    resolved, source_paths = _two_layer_resolved(
        tmp_path,
        winner_root=org_root,
        shadow_root=foundation_root,
        lockfile=previous_lock,
    )

    def org_blocked_policy(item):
        return "block" if item["layer"] == "claude-organization" else "allow"

    materialize_root = tmp_path / "materialize"
    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock=previous_lock,
        layer_source_paths=source_paths,
        policy=org_blocked_policy,
    )

    op = next(o for o in report["ops"] if o["item"] == "protocol")
    assert op["from_sha"] == "foundation-sha-v1"  # the SHADOW's own prior pin
    assert report["lock"]["claude-organization"]["commands"]["protocol"] == "org-sha-v1"
    assert report["lock"]["claude-foundation"]["commands"]["protocol"] != "foundation-sha-v1"


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------


def test_materialize_dry_run_computes_plan_without_writing(tmp_path):
    layer_root = tmp_path / "foundation-src"
    (layer_root / "agents").mkdir(parents=True)
    (layer_root / "agents" / "qa.md").write_text("qa body", encoding="utf-8")

    resolved, source_paths = _resolved_and_paths(tmp_path, layer_root)
    materialize_root = tmp_path / "materialize"

    report = materialize(
        resolved,
        materialize_root=materialize_root,
        previous_lock={},
        layer_source_paths=source_paths,
        policy=permissive_policy,
        dry_run=True,
    )

    assert not (materialize_root / "agents" / "qa.md").exists()
    ops = [o for o in report["ops"] if o["item"] == "qa"]
    assert ops[0]["op"] == "added"  # plan says it WOULD be added


def test_product_native_roots_keep_same_named_items_isolated(tmp_path):
    claude_source = tmp_path / "claude-source"
    codex_source = tmp_path / "codex-source"
    (claude_source / "skills" / "review").mkdir(parents=True)
    (claude_source / "skills" / "review" / "SKILL.md").write_text("claude")
    (codex_source / "plugins" / "review").mkdir(parents=True)
    (codex_source / "plugins" / "review" / "plugin.json").write_text("codex")

    resolved = [
        {"product": "claude", "dimension": "skills", "item": "review", "winning_layer": "claude-personal"},
        {"product": "codex", "dimension": "plugins", "item": "review", "winning_layer": "codex-personal"},
    ]
    claude_root = tmp_path / "claude-target"
    codex_root = tmp_path / "codex-target"

    report = materialize(
        resolved,
        materialize_roots={"claude": claude_root, "codex": codex_root},
        layer_source_paths={"claude-personal": claude_source, "codex-personal": codex_source},
        layer_products={"claude-personal": "claude", "codex-personal": "codex"},
        policy=permissive_policy,
    )

    assert (claude_root / "skills" / "review" / "SKILL.md").read_text() == "claude"
    assert (codex_root / "plugins" / "review" / "plugin.json").read_text() == "codex"
    assert {op["product"] for op in report["ops"]} == {"claude", "codex"}


def test_product_target_allowlist_blocks_cross_product_dimension(tmp_path):
    source = tmp_path / "codex-source"
    (source / "agents").mkdir(parents=True)
    (source / "agents" / "unsafe.md").write_text("must not cross")

    report = materialize(
        [{"product": "codex", "dimension": "agents", "item": "unsafe", "winning_layer": "codex-org"}],
        materialize_roots={"codex": tmp_path / "codex-target"},
        layer_source_paths={"codex-org": source},
        layer_products={"codex-org": "codex"},
        policy=permissive_policy,
    )

    assert report["ops"][0]["op"] == "blocked"
    assert report["ops"][0]["reason"] == "product target is not allowlisted"


# ---------------------------------------------------------------------------
# materialize_ecosystem_config() -- WP-372 P1.3(a)
# ---------------------------------------------------------------------------


def _claude_layer(layer_id: str, role: str, rank: int) -> dict:
    return {
        "id": layer_id,
        "role": role,
        "rank": rank,
        "product": "claude",
        "source": {"repo": f"https://example.invalid/{layer_id}.git"},
        "auth": "anon",
        "activation": "always",
    }


def test_materialize_ecosystem_config_delivers_org_file(tmp_path):
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    (org_root / "ecosystem.yml").write_text("org: acme\ndepartments: []\n", encoding="utf-8")
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()

    layers = [_claude_layer("claude-organization", "organization", 30)]
    op = materialize_ecosystem_config(
        layers,
        layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )

    assert op is not None
    assert op["op"] == "added"
    assert op["dimension"] == "ecosystem"
    assert op["layer"] == "claude-organization"
    dest = materialize_root / "ecosystem.yml"
    assert dest.read_text(encoding="utf-8") == "org: acme\ndepartments: []\n"


def test_materialize_ecosystem_config_unchanged_on_second_run(tmp_path):
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    (org_root / "ecosystem.yml").write_text("org: acme\n", encoding="utf-8")
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    layers = [_claude_layer("claude-organization", "organization", 30)]

    first = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )
    second = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )

    assert first["op"] == "added"
    assert second["op"] == "unchanged"


def test_materialize_ecosystem_config_updates_on_content_change(tmp_path):
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    ecosystem_file = org_root / "ecosystem.yml"
    ecosystem_file.write_text("org: acme\n", encoding="utf-8")
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    layers = [_claude_layer("claude-organization", "organization", 30)]

    materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )
    ecosystem_file.write_text("org: acme\ndepartments: [{unit: accounting}]\n", encoding="utf-8")
    second = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )

    assert second["op"] == "updated"
    dest = materialize_root / "ecosystem.yml"
    assert "accounting" in dest.read_text(encoding="utf-8")


def test_materialize_ecosystem_config_nearest_tier_wins(tmp_path):
    """A personal-tier ecosystem.yml (rank 10) beats the org-tier one
    (rank 30) -- same nearest-tier-wins precedence every OVERRIDE
    dimension already applies."""
    personal_root = tmp_path / "personal-mirror"
    personal_root.mkdir()
    (personal_root / "ecosystem.yml").write_text("org: personal-override\n", encoding="utf-8")
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    (org_root / "ecosystem.yml").write_text("org: acme\n", encoding="utf-8")
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()

    layers = [
        _claude_layer("claude-organization", "organization", 30),
        _claude_layer("claude-personal", "personal", 10),
    ]
    op = materialize_ecosystem_config(
        layers,
        layer_source_paths={
            "claude-organization": org_root,
            "claude-personal": personal_root,
        },
        materialize_root=materialize_root,
    )

    assert op["layer"] == "claude-personal"
    dest = materialize_root / "ecosystem.yml"
    assert "personal-override" in dest.read_text(encoding="utf-8")


def test_materialize_ecosystem_config_absent_everywhere_is_noop(tmp_path):
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()  # no ecosystem.yml inside
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    layers = [_claude_layer("claude-organization", "organization", 30)]

    op = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )

    assert op is None
    assert not (materialize_root / "ecosystem.yml").exists()


def test_materialize_ecosystem_config_ignores_non_claude_products(tmp_path):
    codex_root = tmp_path / "codex-mirror"
    codex_root.mkdir()
    (codex_root / "ecosystem.yml").write_text("org: acme\n", encoding="utf-8")
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()

    layers = [
        {
            "id": "codex-organization", "role": "organization", "rank": 30,
            "product": "codex",
            "source": {"repo": "https://example.invalid/codex-org.git"},
            "auth": "anon", "activation": "always",
        },
    ]
    op = materialize_ecosystem_config(
        layers, layer_source_paths={"codex-organization": codex_root},
        materialize_root=materialize_root,
    )

    assert op is None


def test_materialize_ecosystem_config_dry_run_never_writes(tmp_path):
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    (org_root / "ecosystem.yml").write_text("org: acme\n", encoding="utf-8")
    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    layers = [_claude_layer("claude-organization", "organization", 30)]

    op = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root, dry_run=True,
    )

    assert op["op"] == "added"  # plan says it WOULD be added
    assert not (materialize_root / "ecosystem.yml").exists()


def test_materialize_ecosystem_config_no_materialize_root_is_noop(tmp_path):
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    (org_root / "ecosystem.yml").write_text("org: acme\n", encoding="utf-8")
    layers = [_claude_layer("claude-organization", "organization", 30)]

    op = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=None,
    )

    assert op is None


def test_materialize_ecosystem_config_never_overwrites_dirty_personal_tree(tmp_path):
    """WP-372 P0.3 guard, applied to this new write path too: a materialize
    target sitting inside a dirty personal working tree is never
    overwritten -- reproduces the never-destroy proof this module's other
    tests already establish for the dimension pipeline, for this new
    single-file path."""
    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    (org_root / "ecosystem.yml").write_text("org: new-content\n", encoding="utf-8")

    materialize_root = tmp_path / "materialize"
    materialize_root.mkdir()
    _git_init(materialize_root)
    (materialize_root / "ecosystem.yml").write_text("org: personal-authored\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=materialize_root, check=True)
    # Deliberately left uncommitted (dirty) -- untracked/staged-but-uncommitted
    # is exactly the "dirty working tree" guard_personal_reason() protects.

    layers = [_claude_layer("claude-organization", "organization", 30)]
    op = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )

    assert op["op"] == "held"
    assert "protected" in op["reason"]
    assert (materialize_root / "ecosystem.yml").read_text(encoding="utf-8") == "org: personal-authored\n"


def test_materialize_ecosystem_config_refuses_symlinked_materialize_root(tmp_path):
    """WP-372 P0 reproduction, for this new write path: `materialize_root`
    itself resolving (via symlink) into a real, clean, tracked authoring
    repo with a remote must never be written through -- caught by
    `guard_personal_reason()`'s "clean tracked repo with a remote" check
    (the same check that closes the P0 incident's actual shape: the
    incident repo was clean, not dirty, at the moment it was destroyed)."""
    authoring_repo = tmp_path / "authoring-repo"
    authoring_repo.mkdir()
    _git_init_with_remote(authoring_repo)
    (authoring_repo / "ecosystem.yml").write_text("org: personal-authored\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=authoring_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=authoring_repo, check=True)

    materialize_root = tmp_path / "materialize"
    materialize_root.symlink_to(authoring_repo, target_is_directory=True)

    org_root = tmp_path / "org-mirror"
    org_root.mkdir()
    (org_root / "ecosystem.yml").write_text("org: new-content\n", encoding="utf-8")

    layers = [_claude_layer("claude-organization", "organization", 30)]
    op = materialize_ecosystem_config(
        layers, layer_source_paths={"claude-organization": org_root},
        materialize_root=materialize_root,
    )

    assert op["op"] == "held"
    assert "protected authoring repository" in op["reason"]
    assert (authoring_repo / "ecosystem.yml").read_text(encoding="utf-8") == "org: personal-authored\n"
    assert not (tmp_path / "codex-target" / "agents").exists()
