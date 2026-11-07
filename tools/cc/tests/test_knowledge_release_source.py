"""Current release receipts need signed object and exact immutable byte proof."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cc.core.ecosystem import entitlement
from cc.core.ecosystem.knowledge_release_source import (
    KnowledgeReleaseSourceError,
    resolve_current_knowledge_release,
)
from cc.core.ecosystem.knowledge_skill_source import (
    KNOWLEDGE_SKILLS_SUBPATH,
    KnowledgeSkillSourceError,
    resolve_knowledge_skill_sources,
)
from cc.core.ecosystem.policy import verify_git_item_provenance
from cc.core.ecosystem.project_locking import atomic_json_write
from cc.core.release.engine import layout
from tests.test_knowledge_skill_source import _layer, _run, _signed_knowledge_repo


@pytest.fixture
def released_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, fingerprint, public_key = _signed_knowledge_repo(tmp_path)
    monkeypatch.setattr(
        "cc.core.ecosystem.policy.FOUNDATION_SSH_SIGNING_KEYS",
        {fingerprint: public_key},
    )
    home = tmp_path.resolve() / "home"
    monkeypatch.setenv("COPILOT_HOME", str(home / ".copilot"))
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key: {"skills.cache_dir": str(tmp_path / "skill-cache")}.get(key),
    )
    root = home / ".copilot/releases/20261107T000000Z-aabbcc"
    item = root / "knowledge/foundation"
    shutil.copytree(repo / KNOWLEDGE_SKILLS_SUBPATH, item / KNOWLEDGE_SKILLS_SUBPATH)
    layer = _layer(repo, fingerprint) | {"role": "foundation", "rank": 40}
    rows = []
    for name in layout.all_component_names():
        rows.append(
            {
                "name": name,
                "tier": "",
                "kind": "record",
                "version": "",
                "ref": "",
                "commit": "",
                "source": "",
                "path": "",
                "signer": "",
            }
        )
    component = next(row for row in rows if row["name"] == "knowledge/foundation")
    component.update(
        {
            "tier": "foundation",
            "kind": "signed-tag",
            "version": "v1.0.0",
            "ref": "v1.0.0",
            "commit": _run(repo, "rev-parse", "v1.0.0^{commit}"),
            "source": str(repo),
            "path": "knowledge/foundation",
            "signer": fingerprint,
        }
    )
    manifest = {
        "schema": 1,
        "release": root.name,
        "created": "2026-11-07T00:00:00Z",
        "previous": None,
        "components": rows,
    }
    (root / "release.json").write_text(json.dumps(manifest))
    for current, _directories, files in os.walk(root, topdown=False):
        for name in files:
            path = Path(current) / name
            path.chmod(path.stat().st_mode & ~0o222)
        Path(current).chmod(0o555)
    (home / ".copilot/current").symlink_to(root)
    return repo, layer, root, component, manifest


def _resolve(fixture):
    repo, layer, _root, _component, _manifest = fixture
    return resolve_current_knowledge_release(
        repo, layer, layer["policy"]["allowed_signers"], KNOWLEDGE_SKILLS_SUBPATH
    )


def _save_manifest(fixture):
    path = fixture[2] / "release.json"
    path.chmod(0o644)
    path.write_text(json.dumps(fixture[4]))
    path.chmod(0o444)


def test_active_release_authenticates_without_trusting_authoring_bytes(released_source):
    repo, layer, _root, _component, _manifest = released_source
    authoring = repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting/SKILL.md"
    authoring.write_text("unreleased authoring content\n")
    assert (
        verify_git_item_provenance(
            repo,
            KNOWLEDGE_SKILLS_SUBPATH,
            layer["policy"]["allowed_signers"],
            ref="v1.0.0",
        )
        is None
    )
    verified, snapshot = _resolve(released_source)
    assert verified.ref == "v1.0.0"
    assert b"authorized body" in snapshot.files[0].content
    assert authoring.read_text() == "unreleased authoring content\n"
    pairs = resolve_knowledge_skill_sources(
        repositories=[str(repo)], manifest_source=[layer]
    )
    source = pairs[0][1]
    assert source is not None
    assert source.read_text(source.skill_files()[0]).endswith("authorized body\n")
    assert authoring.read_text() == "unreleased authoring content\n"


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "knowledge/organization"),
        ("kind", "live-link"),
        ("path", "knowledge/organization"),
        ("tier", "organization"),
        ("commit", "0" * 40),
        ("signer", "SHA256:wrong"),
        ("ref", "missing-tag"),
    ],
)
def test_receipt_identity_mismatches_fail_closed(released_source, field, value):
    released_source[3][field] = value
    _save_manifest(released_source)
    with pytest.raises(KnowledgeReleaseSourceError):
        _resolve(released_source)


def test_unsigned_tag_cannot_authenticate_a_release(released_source):
    _run(released_source[0], "tag", "unsigned")
    released_source[3]["ref"] = "unsigned"
    _save_manifest(released_source)
    with pytest.raises(KnowledgeReleaseSourceError, match="signed provenance"):
        _resolve(released_source)


@pytest.mark.parametrize(
    "mutation", ["bytes", "extra", "writable", "symlink", "directory", "missing"]
)
def test_snapshot_tampering_fails_closed(released_source, mutation):
    skills = released_source[2] / "knowledge/foundation" / KNOWLEDGE_SKILLS_SUBPATH
    file = skills / "accounting/SKILL.md"
    if mutation == "bytes":
        file.chmod(0o644)
        file.write_text("tampered release bytes\n")
        file.chmod(0o444)
    elif mutation == "extra":
        skills.chmod(0o755)
        (skills / "extra.md").write_text("unreleased addition\n")
        (skills / "extra.md").chmod(0o444)
        skills.chmod(0o555)
    elif mutation == "writable":
        file.chmod(0o644)
    elif mutation == "symlink":
        file.parent.chmod(0o755)
        file.rename(released_source[0].parent / "preserved-original")
        file.symlink_to(released_source[0].parent / "preserved-original")
        file.parent.chmod(0o555)
    elif mutation == "directory":
        skills.chmod(0o755)
        (skills / "extra-directory").mkdir()
        (skills / "extra-directory").chmod(0o555)
        skills.chmod(0o555)
    else:
        file.parent.chmod(0o755)
        file.rename(released_source[0].parent / "preserved-missing-file")
        file.parent.chmod(0o555)
    with pytest.raises(KnowledgeReleaseSourceError):
        _resolve(released_source)


def test_component_ancestor_symlink_is_rejected(released_source):
    component = released_source[2] / "knowledge/foundation"
    component.parent.chmod(0o755)
    preserved = component.parent / "preserved-foundation"
    component.rename(preserved)
    component.symlink_to(preserved)
    component.parent.chmod(0o555)
    with pytest.raises(KnowledgeReleaseSourceError):
        _resolve(released_source)


def test_current_pointer_cannot_escape_managed_releases(released_source):
    root = released_source[2]
    outside = released_source[0].parent / "outside" / root.name
    shutil.copytree(root, outside)
    current = root.parent.parent / "current"
    current.rename(current.with_name("preserved-current"))
    current.symlink_to(outside)
    with pytest.raises(KnowledgeReleaseSourceError, match="path is unsafe"):
        _resolve(released_source)


def test_wrong_policy_signer_is_not_receipt_authority(released_source):
    with pytest.raises(KnowledgeReleaseSourceError, match="signed provenance"):
        resolve_current_knowledge_release(
            released_source[0],
            released_source[1],
            ["SHA256:untrusted"],
            KNOWLEDGE_SKILLS_SUBPATH,
        )


def test_repository_origin_must_match_declared_layer(released_source):
    released_source[1]["source"]["repo"] = "git@github.com:other/knowledge.git"
    with pytest.raises(KnowledgeReleaseSourceError, match="repository does not match"):
        _resolve(released_source)


def test_receipt_replaced_during_resolution_is_rejected(released_source, monkeypatch):
    from cc.core.release.engine import schema

    original = schema.load

    def replace_receipt(root):
        result = original(root)
        released_source[3]["version"] = "changed after the initial read"
        _save_manifest(released_source)
        return result

    monkeypatch.setattr(schema, "load", replace_receipt)
    with pytest.raises(KnowledgeReleaseSourceError):
        _resolve(released_source)


def test_nonmatching_source_does_not_earn_release_authority(released_source):
    released_source[3]["source"] = str(released_source[0].parent / "other-repository")
    _save_manifest(released_source)
    assert _resolve(released_source) is None
    authoring = released_source[0] / KNOWLEDGE_SKILLS_SUBPATH / "accounting/SKILL.md"
    authoring.write_text("changed owner content\n")
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources(
            repositories=[str(released_source[0])], manifest_source=[released_source[1]]
        )


def test_without_current_release_authoring_provenance_stays_strict(released_source):
    root = released_source[2]
    current = root.parent.parent / "current"
    current.rename(current.with_name("preserved-current"))
    assert _resolve(released_source) is None
    (released_source[0] / KNOWLEDGE_SKILLS_SUBPATH / "accounting/SKILL.md").write_text(
        "owner edits\n"
    )
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources(
            repositories=[str(released_source[0])], manifest_source=[released_source[1]]
        )


def test_release_read_still_requires_current_entitlement(released_source, monkeypatch):
    repo, layer, root, foundation_component, manifest = released_source
    # Foundation is public even with auth=work.  Exercise revocation through a
    # genuinely protected organization release without changing fixture defaults.
    knowledge = root / "knowledge"
    knowledge.chmod(0o755)
    (knowledge / "foundation").rename(knowledge / "organization")
    knowledge.chmod(0o555)
    organization_component = next(
        row for row in manifest["components"] if row["name"] == "knowledge/organization"
    )
    organization_component.update(
        foundation_component
        | {
            "name": "knowledge/organization",
            "tier": "organization",
            "path": "knowledge/organization",
        }
    )
    foundation_component.update(
        {key: "" for key in foundation_component if key != "name"}
        | {"kind": "record"}
    )
    layer.update({"role": "organization", "rank": 30, "auth": "work"})
    _save_manifest(released_source)
    state_path = repo.parent / "entitlements.json"
    checked = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    state = {
        "schema_version": entitlement.ENTITLEMENT_SCHEMA_VERSION,
        "next_sequence": 2,
        "layers": {
            layer["id"]: {
                "layer": layer["id"],
                "product": "knowledge",
                "repo": "example/knowledge",
                "login": "person",
                "state": "entitled",
                "checked_at": checked,
                "last_entitled_at": checked,
                "revision": 1,
            }
        },
    }
    atomic_json_write(state_path, state)
    monkeypatch.setattr("cc.core.ecosystem.entitlement.current_login", lambda: "person")
    monkeypatch.setattr(
        "cc.core.ecosystem.entitlement.entitlement_state_path", lambda: state_path
    )
    source = resolve_knowledge_skill_sources(
        repositories=[str(repo)], manifest_source=[layer]
    )[0][1]
    assert source is not None and source.entitlement_binding is not None
    assert source.read_text(source.skill_files()[0]).endswith("authorized body\n")
    state["layers"][layer["id"]]["state"] = "revoked"
    state["layers"][layer["id"]]["revision"] = 2
    state["next_sequence"] = 3
    atomic_json_write(state_path, state)
    with pytest.raises(KnowledgeSkillSourceError, match="authorization changed"):
        source.read_text(source.skill_files()[0])
