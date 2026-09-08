"""Tests for `cc.core.conformance.root_causes`'s mirror-backed layer
resolution (task 52's regression fix).

Task 52 removed the literal `source.path` from the real `claude-foundation`/
`codex-foundation` manifest entries so those pinned layers resolve from
their immutable `~/.copilot/mirrors/<layer id>` mirror instead of a live
checkout. `_layer_source_path()`/`_foundation_source_path()` previously
hard-required a literal `source.path` and raised `LookupError` for any
layer that declares only `source.repo` -- breaking `run_rc1`/`run_rc2`/
`run_rc4` and the full regression sweep. This module tests the fix in
isolation, with an injected `mirror_root_base` so nothing here ever touches
the real `~/.copilot/mirrors` or `~/.claude/cc/config.json` (the real-machine
default resolution path is covered by the existing `@pytest.mark.machine`
tests in test_rc_regressions.py, which exercise it against the live
manifest).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.conformance import root_causes


def _layer(
    layer_id: str,
    *,
    product: str = "claude",
    rank: int = 40,
    role: str = "foundation",
    repo: str | None = "https://example.invalid/repo.git",
    path: str | None = None,
    subpath: str | None = None,
) -> dict:
    source: dict = {}
    if repo:
        source["repo"] = repo
        source["ref"] = "v1.0.0"
    if path:
        source["path"] = path
    if subpath:
        source["subpath"] = subpath
    return {
        "id": layer_id,
        "role": role,
        "rank": rank,
        "product": product,
        "source": source,
        "auth": "anon",
        "activation": "always",
    }


# ---------------------------------------------------------------------------
# _layer_source_path
# ---------------------------------------------------------------------------


def test_layer_source_path_returns_literal_path_unchanged(tmp_path):
    """A layer that still declares `source.path` (the pre-task-52 shape,
    and every non-foundation tier today) is completely unaffected -- the
    mirror fallback is never consulted."""
    layer = _layer("claude-personal", path="/some/checkout", role="personal", rank=10)
    result = root_causes._layer_source_path(layer, mirror_root_base=tmp_path)
    assert result == Path("/some/checkout")


def test_layer_source_path_falls_back_to_mirror_content_root(tmp_path):
    """No `source.path`, but `source.repo` present (the live claude-
    foundation/codex-foundation shape after task 52) -- resolves via the
    SAME `mirror.mirror_content_root()` computation `commands/update.py`
    and `commands/resolve.py` already share, not a re-derived one."""
    layer = _layer("claude-foundation")
    result = root_causes._layer_source_path(layer, mirror_root_base=tmp_path)
    assert result == tmp_path / "claude-foundation"


def test_layer_source_path_fallback_never_folds_subpath(tmp_path):
    """The claude-foundation layer's real shape declares `source.subpath:
    .claude`. RC1/RC2/RC4 need the REPO ROOT (they join `.claude/commands/
    ...` themselves) -- `_layer_source_path()` must return the bare mirror
    root, not the subpath-folded content root `synthesize_source_path()`
    would compute for materialize purposes."""
    layer = _layer("claude-foundation", subpath=".claude")
    result = root_causes._layer_source_path(layer, mirror_root_base=tmp_path)
    assert result == tmp_path / "claude-foundation"


def test_layer_source_path_still_raises_with_neither_path_nor_repo(tmp_path):
    """A layer with no local path AND no repo cannot be located at all --
    still an honest `LookupError`, unchanged from before this fix."""
    layer = _layer("orphan-layer", repo=None)
    with pytest.raises(LookupError, match="has no source.path"):
        root_causes._layer_source_path(layer, mirror_root_base=tmp_path)


def test_layer_source_path_default_mirror_root_base_resolves_real_machine(monkeypatch, tmp_path):
    """With no `mirror_root_base` argument (the shape `check_rc3`/
    `check_rc5` call it with), the fallback resolves through
    `_real_mirror_root_base(_default_home())` -- the same `Path.home()` +
    direct-config-read pattern the module already uses for the manifest
    and project roots (module docstring point 2), never `resolve_key()`."""
    monkeypatch.setattr(root_causes, "_default_home", lambda: tmp_path)
    layer = _layer("claude-foundation")
    result = root_causes._layer_source_path(layer)
    assert result == tmp_path / ".copilot" / "mirrors" / "claude-foundation"


# ---------------------------------------------------------------------------
# _foundation_source_path
# ---------------------------------------------------------------------------


def test_foundation_source_path_passes_through_mirror_root_base(tmp_path):
    layers = [_layer("claude-foundation"), _layer("codex-foundation", product="codex")]
    result = root_causes._foundation_source_path(
        layers, "codex", mirror_root_base=tmp_path
    )
    assert result == tmp_path / "codex-foundation"


def test_foundation_source_path_returns_none_when_product_absent(tmp_path):
    layers = [_layer("claude-foundation")]
    assert (
        root_causes._foundation_source_path(layers, "codex", mirror_root_base=tmp_path)
        is None
    )


# ---------------------------------------------------------------------------
# check_rc3 / check_rc5 -- a genuinely unresolvable layer is still skipped,
# not a hard crash (only reachable for a hand-built layer that never went
# through validate_layers's own "source.repo is required" gate).
# ---------------------------------------------------------------------------


def test_check_rc3_skips_a_layer_with_neither_path_nor_repo():
    layer = _layer("orphan-layer", repo=None)
    layer["source"] = {"ref": "v1.0.0"}
    results = root_causes.check_rc3(layers=[layer])
    assert results == ()


def test_check_rc5_skips_a_layer_with_neither_path_nor_repo():
    layer = _layer("orphan-variant", role="organization", rank=30)
    layer["source"] = {}
    results = root_causes.check_rc5(layers=[layer])
    assert results == ()
