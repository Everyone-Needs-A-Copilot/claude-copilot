"""Activation boundary controls; synthetic manifests are not signature proof.

The actual shared packet verifier is tested independently by the tc partition.
These cases exercise caller binding/refusal and actual unchanged pointer bytes.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cc.commands.release import release_app
from cc.core.release.engine import layout, schema
from cc.core.release.stage_gate import candidate_inputs_sha256, require_activation
from typer.testing import CliRunner


def candidate(tmp_path, version=None):
    home = tmp_path / "home"
    root = layout.release_dir("20261107T000000Z-candidate", home)
    framework = root / layout.COMPONENT_CLAUDE
    framework.mkdir(parents=True)
    entries = tuple(schema.Component(name, "foundation", layout.KIND_SIGNED,
                                    "5.36.0", "v5.36.0", "a" * 40,
                                    "/authored/source", name, "SHA256:fixture")
                    for name in layout.all_component_names())
    manifest = schema.Manifest(root.name, "2026-11-07T00:00:00Z", None, entries)
    (root / layout.MANIFEST_NAME).write_text(json.dumps(manifest.to_json()))
    if version is not None:
        (framework / "VERSION.json").write_text(json.dumps(version))
    return home, root, manifest


@pytest.mark.parametrize("version", [None, {}, [], {"framework": "invalid"},
                                     {"framework": "5.36.0"},
                                     {"framework": "5.36.0", "stagePolicyVersion": False},
                                     {"framework": "5.36.0", "stagePolicyVersion": 2}])
def test_missing_or_downgraded_policy_cannot_be_assumed_legacy(tmp_path, version):
    _, root, _ = candidate(tmp_path, version)
    with pytest.raises(ValueError):
        require_activation(root)


def test_prior_proper_framework_version_keeps_legacy_path(tmp_path):
    _, root, _ = candidate(tmp_path, {"framework": "5.35.4"})
    assert require_activation(root) == {"approved": True, "assurance": "legacy-unenrolled"}


@pytest.mark.parametrize("packet,digest", [(None, None), ("packet.json", None), (None, "a" * 64)])
def test_governed_release_requires_both_packet_and_digest(tmp_path, packet, digest):
    _, root, _ = candidate(tmp_path, {"framework": "5.36.0", "stagePolicyVersion": 1})
    with pytest.raises(ValueError, match="activation requires"):
        require_activation(root, packet=packet, packet_sha256=digest)


@pytest.mark.parametrize("field", ["name", "tier", "kind", "version", "ref", "commit", "signer"])
def test_every_component_identity_field_changes_composition_digest(tmp_path, field):
    _, _, manifest = candidate(tmp_path)
    rows = list(manifest.components)
    rows[-1] = replace(rows[-1], **{field: getattr(rows[-1], field) + "-changed"})
    assert candidate_inputs_sha256(replace(manifest, components=tuple(rows))) != candidate_inputs_sha256(manifest)


def test_machine_paths_and_manifest_order_do_not_change_composition_digest(tmp_path):
    _, _, manifest = candidate(tmp_path)
    moved = replace(manifest, components=tuple(replace(row, source="/other/root", path="other/path")
                                               for row in reversed(manifest.components)))
    assert candidate_inputs_sha256(moved) == candidate_inputs_sha256(manifest)


def test_activation_passes_exact_composition_and_signed_commit_to_shared_verifier(tmp_path, monkeypatch):
    from tc.services import cycle_stages

    _, root, manifest = candidate(tmp_path, {"framework": "5.36.0", "stagePolicyVersion": 1})
    observed = []

    def verify(**kwargs):
        observed.append(kwargs)
        return {"approved": True}

    monkeypatch.setattr(cycle_stages, "verify_packet", verify)
    packet = tmp_path / "packet.json"
    assert require_activation(root, packet=packet, packet_sha256="b" * 64)["approved"]
    assert observed == [{"file": packet, "sha256": "b" * 64,
                         "root": root / layout.COMPONENT_CLAUDE, "phase": "activate-ready",
                         "source_commit": "a" * 40,
                         "candidate_inputs_sha256": candidate_inputs_sha256(manifest)}]


def test_real_flip_command_refuses_before_changing_current_or_history(tmp_path, monkeypatch):
    home, root, _ = candidate(tmp_path, {"framework": "5.36.0", "stagePolicyVersion": 1})
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("COPILOT_HOME", raising=False)
    current = layout.current_path(home)
    current.symlink_to(Path("releases") / "20261106T000000Z-prior")
    before = current.readlink()
    result = CliRunner().invoke(release_app, ["flip", root.name, "--home", str(home)])
    assert result.exit_code != 0
    assert "activation requires" in result.output
    assert current.readlink() == before
    assert not layout.history_path(home).exists()
