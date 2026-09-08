"""New coverage for Fix (d): resolving a pinned foundation layer from its
immutable mirror instead of a manifest `source.path` pointing at a mutable
working checkout (layer-fix design section 5.4/2.4).

Companion to `test_ecosystem_policy.py` (signing fixture reused by direct
sibling import -- existing tests are read-only) and to the machine-config
change applied at `~/.config/copilot/copilot.layers.yml` (outside this repo,
backed up before editing per the task's evidence requirements).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_ecosystem_policy import _init_signing_repo  # noqa: E402

from cc.core.ecosystem import policy  # noqa: E402
from cc.core.ecosystem.codex_plugin_source import (  # noqa: E402
    CodexPluginSourceError,
    resolve_codex_plugin_source_with_bindings,
)


def _trust(monkeypatch: pytest.MonkeyPatch, fingerprint: str, public_key: str) -> None:
    """`resolve_codex_plugin_source_with_bindings` calls
    `verify_git_item_provenance` with no `_trusted_keys` override, so it
    resolves the real compiled `FOUNDATION_SSH_SIGNING_KEYS` at call time.
    Register this test's ephemeral signing key there for the duration of
    the test -- production trust wiring is untouched everywhere else."""
    monkeypatch.setattr(
        policy, "FOUNDATION_SSH_SIGNING_KEYS", {fingerprint: public_key}
    )


def _commit_signed_plugin(repo: Path, fingerprint: str, *, content: str = "v1 plugin\n") -> None:
    plugin_dir = repo / "plugins" / "codex-copilot"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "plugins/codex-copilot"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "add codex plugin"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "tag", "-s", "v1.0.0", "-m", "release"], cwd=repo, check=True
    )


def _layer(*, fingerprint: str, source_path: str | None) -> dict:
    source: dict = {"repo": "unused-for-a-local-mirror-clone", "ref": "v1.0.0"}
    if source_path is not None:
        source["path"] = source_path
    return {
        "id": "codex-foundation",
        "role": "foundation",
        "rank": 40,
        "product": "codex",
        "source": source,
        "auth": "anon",
        "activation": "always",
        "policy": {"allowed_signers": [fingerprint]},
    }


def test_binding_resolves_from_mirror_when_layer_declares_no_local_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, fingerprint, public_key = _init_signing_repo(tmp_path)
    _trust(monkeypatch, fingerprint, public_key)
    _commit_signed_plugin(repo, fingerprint)
    expected_tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "v1.0.0^{commit}:plugins/codex-copilot"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    mirror_root_base = tmp_path / "mirrors"
    mirror_target = mirror_root_base / "codex-foundation"
    subprocess.run(
        ["git", "clone", "--quiet", str(repo), str(mirror_target)], check=True
    )
    subprocess.run(
        ["git", "-C", str(mirror_target), "checkout", "--quiet", "v1.0.0"],
        check=True,
    )

    layer = _layer(fingerprint=fingerprint, source_path=None)

    source, _bindings = resolve_codex_plugin_source_with_bindings(
        manifest_path=[layer],
        mirror_root_base=mirror_root_base,
        entitlement_state_path=tmp_path / "entitlement-unused.json",
    )

    assert source is not None
    assert source.repository_root == mirror_target.resolve()
    assert source.tree == expected_tree
    assert source.ref == "v1.0.0"
    assert source.signer == fingerprint
    assert str(source.path) == str((mirror_target / "plugins/codex-copilot").resolve())


def test_a_dirty_sibling_working_checkout_does_not_affect_a_mirror_resolved_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole fix rests on: once the manifest layer carries
    NO `source.path`, nothing about a separate, mutable, dirty working
    checkout of the same repository can influence what the mirror-resolved
    binding reads -- there is no field left connecting the two."""
    repo, fingerprint, public_key = _init_signing_repo(tmp_path)
    _trust(monkeypatch, fingerprint, public_key)
    _commit_signed_plugin(repo, fingerprint, content="v1 plugin\n")
    expected_tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "v1.0.0^{commit}:plugins/codex-copilot"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    mirror_root_base = tmp_path / "mirrors"
    mirror_target = mirror_root_base / "codex-foundation"
    subprocess.run(
        ["git", "clone", "--quiet", str(repo), str(mirror_target)], check=True
    )
    subprocess.run(
        ["git", "-C", str(mirror_target), "checkout", "--quiet", "v1.0.0"],
        check=True,
    )

    # A SEPARATE live working checkout of the same origin repo, made dirty
    # with uncommitted, unpinned bytes -- the exact shape of the live
    # `/Users/pabs/Sites/CSE/codex-copilot` checkout on the real machine.
    live_checkout = tmp_path / "live-working-checkout"
    subprocess.run(
        ["git", "clone", "--quiet", str(repo), str(live_checkout)], check=True
    )
    (live_checkout / "plugins" / "codex-copilot" / "plugin.json").write_text(
        "UNCOMMITTED DEVELOPER CHANGES\n", encoding="utf-8"
    )

    layer = _layer(fingerprint=fingerprint, source_path=None)

    source, _bindings = resolve_codex_plugin_source_with_bindings(
        manifest_path=[layer],
        mirror_root_base=mirror_root_base,
        entitlement_state_path=tmp_path / "entitlement-unused.json",
    )

    assert source is not None
    assert source.tree == expected_tree
    assert source.repository_root == mirror_target.resolve()
    # The dirty live checkout was never touched or read.
    assert (
        live_checkout / "plugins" / "codex-copilot" / "plugin.json"
    ).read_text(encoding="utf-8") == "UNCOMMITTED DEVELOPER CHANGES\n"


def test_local_path_layer_pinned_to_a_tag_still_blocks_when_dirty(
    tmp_path: Path,
) -> None:
    """The CURRENT, unchanged, intended behavior: a layer that DOES declare
    `source.path` pointing at a mutable checkout still fails signed
    verification once that checkout diverges from the pinned tag's tree --
    `policy.py`'s verification is not weakened or bypassed anywhere in this
    fix."""
    repo, fingerprint, public_key = _init_signing_repo(tmp_path)
    _commit_signed_plugin(repo, fingerprint, content="v1 plugin\n")

    # Diverge the working checkout from the signed tag AFTER tagging --
    # exactly the live-checkout situation `source.path` used to declare.
    (repo / "plugins" / "codex-copilot" / "plugin.json").write_text(
        "developer is ahead of the release\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--no-gpg-sign", "-m", "unreleased work"],
        cwd=repo,
        check=True,
    )

    layer = _layer(fingerprint=fingerprint, source_path=str(repo))

    try:
        resolve_codex_plugin_source_with_bindings(
            manifest_path=[layer],
            mirror_root_base=tmp_path / "mirrors-unused",
            entitlement_state_path=tmp_path / "entitlement-unused.json",
        )
        raised = False
    except CodexPluginSourceError:
        raised = True

    assert raised, (
        "a signed-release layer resolving from a mutable, diverged working "
        "checkout must still fail closed -- this is the exact defect Fix (d) "
        "resolves by removing source.path, not by relaxing verification"
    )
