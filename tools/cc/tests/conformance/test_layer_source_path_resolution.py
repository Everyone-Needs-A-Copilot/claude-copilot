"""Regression + enforcement coverage for "how does a layer's real content
root get resolved when `copilot.layers.yml` declares no literal
`source.path`" -- the bug class this session hit THREE times independently
(`cc.core.conformance.root_causes._layer_source_path` / `_foundation_
source_path`, fixed by task 53; `cc.core.conformance.stack._resolve_cell_
source_path`, fixed by this task) before both were made to share
`cc.core.ecosystem.mirror.mirror_content_root()` as the one computation of
"where does this layer's disposable mirror clone live".

Two things this module is deliberately NOT trying to do:

  1. It does not re-litigate `mirror_content_root()`'s own path arithmetic
     -- that is `tests/test_ecosystem_mirror.py`'s job.
  2. It does not attempt an exhaustive "every possible future call site"
     enumeration. `TestSharedHelperEnforcement` below explains exactly what
     it catches and what it does not; that limitation is the honest
     boundary of what a test file importing two specific modules can prove
     about a third module nobody has written yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc.core.conformance import root_causes, stack
from cc.core.conformance.types import Verdict
from cc.core.ecosystem import mirror as mirror_module

from .conftest import git_commit_all, init_git_repo

pytestmark = pytest.mark.filterwarnings("ignore")


def _mirror_backed_layer(
    *, product: str = "claude", role: str = "foundation", rank: int = 40, ref: str = "v1.0.0"
) -> dict:
    """A layer with `source.repo` + `source.ref` and deliberately NO literal
    `source.path` -- the exact real-manifest shape task 52 left claude-
    foundation/codex-foundation in."""

    return {
        "id": f"{product}-{role}",
        "role": role,
        "rank": rank,
        "product": product,
        "source": {
            "repo": f"https://example.invalid/{product}-copilot.git",
            "ref": ref,
        },
        "auth": "anon",
        "activation": "always",
    }


def _mirror_clone(mirror_root_base: Path, layer: dict, *, ref: str) -> Path:
    """A real, tagged git repo materialized exactly where `mirror_content_
    root()` says this layer's clone lives -- the disk-truth counterpart of
    `_mirror_backed_layer()`'s manifest-truth."""

    clone_path = mirror_module.mirror_content_root(
        layer, mirror_root_base=mirror_root_base
    )
    assert clone_path is not None
    init_git_repo(clone_path)
    git_commit_all(clone_path, "initial")
    import subprocess

    subprocess.run(
        ["git", "-c", "tag.gpgSign=false", "tag", ref], cwd=clone_path, check=True
    )
    return clone_path


# ---------------------------------------------------------------------------
# stack._resolve_cell_source_path -- direct unit coverage
#
# Every fixture in test_layer2_stack.py's TestCsDecl/TestCsPath/
# TestCsRefValid/TestCsMirror classes sets a literal `source.path` (via the
# shared `_layer()` helper there), so the "no literal path, fall back to
# the mirror" branch stack.py added was previously exercised ONLY by the
# real-machine `TestMachineTruth` tests -- which can drift with whatever
# happens to be on the developer's disk that day. These pin the fallback
# itself, independent of machine state.
# ---------------------------------------------------------------------------


class TestResolveCellSourcePath:
    def test_prefers_literal_path_when_present(self, tmp_path):
        layer = _mirror_backed_layer()
        layer["source"]["path"] = str(tmp_path / "authoring-checkout")
        resolved = stack._resolve_cell_source_path(layer)
        assert resolved == Path(tmp_path / "authoring-checkout")

    def test_falls_back_to_mirror_content_root_when_path_absent(
        self, tmp_path, monkeypatch
    ):
        mirrors_root = tmp_path / "mirrors"
        monkeypatch.setattr(stack, "_mirrors_root", lambda: mirrors_root)
        layer = _mirror_backed_layer()
        resolved = stack._resolve_cell_source_path(layer)
        assert resolved == mirror_module.mirror_content_root(
            layer, mirror_root_base=mirrors_root
        )

    def test_returns_none_when_neither_path_nor_repo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(stack, "_mirrors_root", lambda: tmp_path / "mirrors")
        layer = {"id": "x", "role": "foundation", "rank": 40, "product": "x", "source": {}}
        assert stack._resolve_cell_source_path(layer) is None


# ---------------------------------------------------------------------------
# End-to-end: each CS-* check against a REAL mirror-backed cell (no literal
# source.path, a real tagged git clone at the exact resolved mirror
# location) -- the shape claude-foundation/codex-foundation are in on the
# real machine post task 52, reproduced under a controlled mirrors_root so
# these never depend on this developer's actual `~/.copilot/mirrors`.
# ---------------------------------------------------------------------------


class TestMirrorBackedCellEndToEnd:
    @pytest.fixture(autouse=True)
    def _mirror_backed_cell(self, tmp_path, monkeypatch):
        self.mirrors_root = tmp_path / "mirrors"
        monkeypatch.setattr(stack, "_mirrors_root", lambda: self.mirrors_root)
        monkeypatch.setattr(stack, "_resolve_live_authoring_alias", lambda: None)
        self.layer = _mirror_backed_layer()
        self.clone_path = _mirror_clone(self.mirrors_root, self.layer, ref="v1.0.0")
        self.manifest_path = tmp_path / "copilot.layers.yml"
        self.snapshot = stack.ManifestSnapshot(
            path=self.manifest_path, layers=(self.layer,), error=None
        )

    def test_cs_decl_treats_a_mirror_resolvable_cell_as_declared(self):
        result = stack.check_cs_decl(
            [("claude", "foundation")], [self.snapshot]
        )[0]
        assert result.verdict is Verdict.PASS, result.detail

    def test_cs_path_finds_the_real_mirror_clone(self):
        result = stack.check_cs_path([("claude", "foundation")], [self.snapshot])[0]
        assert result.verdict is Verdict.PASS, result.detail
        assert str(self.clone_path) in result.detail

    def test_cs_ref_valid_resolves_the_pinned_tag_in_the_mirror(self):
        result = stack.check_cs_ref_valid(
            [("claude", "foundation")], [self.snapshot]
        )[0]
        assert result.verdict is Verdict.PASS, result.detail

    def test_cs_ancestor_walks_ancestry_in_the_mirror_not_could_not_run(self):
        # Real evidence, not a degraded "nothing to check" -- a lightweight
        # tag on the sole commit of a freshly-initialized repo has no
        # `origin/main`/`main` to compare against yet, so this is an
        # honest SKIP (see stack.py's network-gating docstring), never the
        # pre-fix COULD_NOT_RUN caused by an unresolvable source path.
        result = stack.check_cs_ancestor(
            [("claude", "foundation")], [self.snapshot]
        )[0]
        assert result.verdict in (Verdict.SKIP, Verdict.PASS), result.detail
        assert "source.ref/source path unavailable" not in result.detail

    def test_cs_mirror_classifies_the_resolved_clone_as_a_managed_mirror(self):
        # This is the real behavioral change task 52 intended: a layer that
        # used to be an always-exempt authoring checkout (literal
        # source.path under a live checkout) is now a genuine disposable
        # mirror -- CS-MIRROR must say so with real evidence (PASS, clean,
        # unaliased), never SKIP-as-authoring (nothing in `classification.
        # toml` describes a disposable mirror path) and never COULD_NOT_RUN.
        result = stack.check_cs_mirror(
            [("claude", "foundation")], [self.snapshot]
        )[0]
        assert result.verdict is Verdict.PASS, result.detail
        assert "under the configured mirrors root" in result.detail


class TestMirrorBackedTierVariantCsDim:
    """CS-DIM only ever reads a tier-variant cell's source path (foundation
    cells are always SKIP before reaching it -- stack.py's own check_cs_dim
    docstring). Real manifest tier-variant cells all still declare a
    literal source.path today, so this fallback branch is currently
    inert in production -- covered here so it stays correct if a
    tier-variant layer is ever converted to mirror-backed the same way
    task 52 converted the two foundations."""

    def test_cs_dim_resolves_a_mirror_backed_tier_variant_cell(self, tmp_path, monkeypatch):
        mirrors_root = tmp_path / "mirrors"
        monkeypatch.setattr(stack, "_mirrors_root", lambda: mirrors_root)
        layer = _mirror_backed_layer(role="organization", rank=30)
        clone_path = mirror_module.mirror_content_root(
            layer, mirror_root_base=mirrors_root
        )
        assert clone_path is not None
        clone_path.mkdir(parents=True)
        (clone_path / "copilot.layer.yml").write_text(
            "dimensions: [plugins]\n", encoding="utf-8"
        )
        snapshot = stack.ManifestSnapshot(
            path=tmp_path / "copilot.layers.yml", layers=(layer,), error=None
        )
        result = stack.check_cs_dim(["claude"], [snapshot])
        organization_result = next(
            r for r in result if r.subject == "claude-organization"
        )
        assert organization_result.verdict is Verdict.PASS, organization_result.detail


# ---------------------------------------------------------------------------
# Closing the pattern: both known resolvers of "a layer's effective content
# root" must go through the SAME `mirror.mirror_content_root()` -- not
# merely produce coincidentally-equal answers today.
# ---------------------------------------------------------------------------


class TestSharedHelperEnforcement:
    """This is the enforcement mechanism, chosen over an exact "grep the
    repo, assert the module set is exactly {mirror.py, root_causes.py,
    stack.py}" test: a literal `source.get("path")` read appears in ~20
    files across `cc.core.ecosystem`/`cc.core.conformance` for entirely
    unrelated, legitimate reasons (writing a resolved path back after
    materializing it, reading an ALREADY mirror-folded layer downstream of
    `synthesize_effective_layers()`, checking presence for an unrelated
    validation). An exact-module-census test would need constant
    maintenance for every legitimate new caller and would not actually
    prove any of them resolve a path CORRECTLY -- decorative, not
    enforceable, exactly what this task warned against.

    Instead: monkeypatch the single shared symbol,
    `cc.core.ecosystem.mirror.mirror_content_root`, as it is imported into
    EACH resolver module, and assert both `stack._resolve_cell_source_path`
    and `root_causes._layer_source_path` reflect the patched return value
    for a layer with no literal `source.path`. If either resolver ever
    reverts to re-deriving the mirror location itself (a fourth/fifth
    divergent implementation) instead of calling through the shared
    symbol, patching that symbol has no effect on that resolver's output
    and this test fails.

    What this DOES catch: `stack.py` or `root_causes.py` silently
    inlining their own mirror-path arithmetic again, in whole or in part,
    instead of calling `mirror_content_root()`.

    What this does NOT catch: a brand-new THIRD module (e.g. some future
    `cc.core.conformance.<newcheck>.py`) independently re-implementing
    "prefer literal source.path, else derive a mirror path" without ever
    being wired into this test. Guarding against that requires either
    extending this test's import list the day that module is written, or
    a repo-wide structural convention (e.g. a lint rule) this task's scope
    does not include -- named here rather than silently assumed away.
    """

    def test_stack_and_root_causes_both_delegate_to_mirror_content_root(
        self, tmp_path, monkeypatch
    ):
        sentinel = tmp_path / "sentinel-mirror-content-root"
        calls: list[tuple[str | None, Path]] = []

        def _fake_mirror_content_root(layer, *, mirror_root_base, **_kwargs):
            calls.append((layer.get("id"), Path(mirror_root_base)))
            return sentinel

        # Patched on the SYMBOL each module imported into its own
        # namespace -- proves each module calls through ITS OWN reference
        # to the shared helper, not a coincidentally-identical private copy.
        monkeypatch.setattr(stack, "mirror_content_root", _fake_mirror_content_root)
        monkeypatch.setattr(
            root_causes, "mirror_content_root", _fake_mirror_content_root
        )
        monkeypatch.setattr(stack, "_mirrors_root", lambda: tmp_path / "mirrors")

        layer = _mirror_backed_layer()

        stack_result = stack._resolve_cell_source_path(layer)
        rc_result = root_causes._layer_source_path(
            layer, mirror_root_base=tmp_path / "mirrors"
        )

        assert stack_result == sentinel
        assert rc_result == sentinel
        assert len(calls) == 2, (
            "expected both stack._resolve_cell_source_path and "
            "root_causes._layer_source_path to call the shared "
            "mirror_content_root() exactly once each for this layer"
        )

    def test_stack_and_root_causes_agree_on_a_real_mirror_backed_fixture(
        self, tmp_path, monkeypatch
    ):
        """Complementary to the patched-symbol test above: with NO
        patching, both resolvers must compute the identical real
        filesystem path for the identical layer + mirror root -- the
        end-to-end proof that "delegates to the same symbol" and "agrees
        on the answer" are the same fact, not two coincidentally-aligned
        ones."""

        mirrors_root = tmp_path / "mirrors"
        monkeypatch.setattr(stack, "_mirrors_root", lambda: mirrors_root)
        layer = _mirror_backed_layer()

        stack_result = stack._resolve_cell_source_path(layer)
        rc_result = root_causes._layer_source_path(
            layer, mirror_root_base=mirrors_root
        )

        assert stack_result is not None
        assert stack_result == rc_result
