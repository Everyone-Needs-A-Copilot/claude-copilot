"""Tests for `cc.core.ecosystem.mirror.mirror_content_root()` -- the bare
mirror-clone-root computation extracted out of `synthesize_source_path()`
(WP-373, the task-52 regression fix) so a caller that needs the CHECKOUT
ROOT itself (git plumbing, or a relative path the caller supplies on top of
the repo root) can share the identical computation `synthesize_source_path()`
uses for its own subpath-folded result, rather than re-deriving it.

`cc.core.conformance.root_causes._layer_source_path()` is the new caller
this extraction exists for; see tests/conformance/test_root_causes_mirror_
fallback.py for its own behavior. This file only exercises
`mirror_content_root()` and confirms `synthesize_source_path()`'s existing,
already-tested behavior is unchanged by the refactor.
"""

from __future__ import annotations

from pathlib import Path

from cc.core.ecosystem import mirror


def _pathless_layer(layer_id: str = "claude-foundation", *, product: str = "claude") -> dict:
    return {
        "id": layer_id,
        "role": "foundation",
        "rank": 40,
        "product": product,
        "source": {"repo": f"https://example.invalid/{layer_id}.git", "ref": "v1.0.0"},
        "auth": "anon",
        "activation": "always",
    }


def test_mirror_content_root_flat_for_non_externally_consumed_product(tmp_path):
    layer = _pathless_layer("claude-foundation", product="claude")
    root = mirror.mirror_content_root(layer, mirror_root_base=tmp_path)
    assert root == tmp_path / "claude-foundation"


def test_mirror_content_root_nested_for_externally_consumed_product(tmp_path):
    layer = _pathless_layer("knowledge-foundation", product="knowledge")
    root = mirror.mirror_content_root(layer, mirror_root_base=tmp_path)
    assert root == tmp_path / "knowledge" / "knowledge-foundation"


def test_mirror_content_root_never_folds_subpath(tmp_path):
    """The bare checkout root -- unlike `synthesize_source_path()`, a
    declared `source.subpath` is NOT joined on top. A caller that needs
    the repo root (git plumbing, or its own relative join on top of the
    repo root -- e.g. `root_causes.py`'s RC1/RC2/RC4 checks, which join
    `.claude/commands/...` or `scripts/...` themselves) wants this."""
    layer = _pathless_layer("claude-foundation", product="claude")
    layer["source"]["subpath"] = ".claude"
    root = mirror.mirror_content_root(layer, mirror_root_base=tmp_path)
    assert root == tmp_path / "claude-foundation"


def test_mirror_content_root_none_when_local_path_already_set(tmp_path):
    layer = _pathless_layer("claude-foundation", product="claude")
    layer["source"]["path"] = "/some/local/checkout"
    assert mirror.mirror_content_root(layer, mirror_root_base=tmp_path) is None


def test_mirror_content_root_none_when_no_repo(tmp_path):
    layer = {
        "id": "claude-personal",
        "role": "personal",
        "rank": 10,
        "product": "claude",
        "source": {},
    }
    assert mirror.mirror_content_root(layer, mirror_root_base=tmp_path) is None


def test_mirror_content_root_expands_user_in_base(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    layer = _pathless_layer("claude-foundation", product="claude")
    root = mirror.mirror_content_root(layer, mirror_root_base="~/mirrors")
    assert root == tmp_path / "mirrors" / "claude-foundation"


def test_synthesize_source_path_still_folds_subpath_after_the_refactor(tmp_path):
    """`synthesize_source_path()` now delegates its checkout-root piece to
    `mirror_content_root()` -- confirm its own, already-established
    contract (subpath IS folded in) is unchanged by that refactor."""
    layer = _pathless_layer("claude-foundation", product="claude")
    layer["source"]["subpath"] = ".claude"
    resolved = mirror.synthesize_source_path(layer, mirror_root_base=tmp_path)
    assert resolved == tmp_path / "claude-foundation" / ".claude"


def test_synthesize_source_path_matches_mirror_content_root_when_no_subpath(tmp_path):
    layer = _pathless_layer("codex-foundation", product="codex")
    content_root = mirror.mirror_content_root(layer, mirror_root_base=tmp_path)
    synthesized = mirror.synthesize_source_path(layer, mirror_root_base=tmp_path)
    assert content_root == synthesized == tmp_path / "codex-foundation"
