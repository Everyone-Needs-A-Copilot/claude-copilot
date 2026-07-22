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

import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.materialize import guard_personal, materialize
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
