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
from cc.core.ecosystem.materialize import guard_personal, guard_personal_reason, materialize
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
    assert not (tmp_path / "codex-target" / "agents").exists()
