"""Signed, immutable Knowledge skill read enforcement."""

from __future__ import annotations

import json
import stat
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cc.commands.deprovision import build_deprovision_report
from cc.commands.update import build_update_report
from cc.core.ecosystem import entitlement
from cc.core.ecosystem.knowledge_skill_source import (
    KNOWLEDGE_SKILLS_SUBPATH,
    KnowledgeSkillSourceError,
    prune_all_knowledge_snapshots,
    resolve_knowledge_skill_sources,
    resolve_protected_knowledge_lock_projections,
)
from cc.core.ecosystem.materialize import stable_directory_content_sha
from cc.core.ecosystem.policy import read_git_tree_snapshot
from cc.core.ecosystem.project_locking import atomic_json_write
from cc.core.extensions_resolver import (
    ACTION_APPLY,
    ACTION_NO_EXTENSION,
    compose_agent_content_with_receipts,
    resolve_extension,
)
from cc.core.skill_store import (
    discover_skills,
    discover_skills_with_sources,
    get_skill_content,
    get_skill_content_with_receipt,
    revalidate_skill_path,
)
from cc.main import app
from typer.testing import CliRunner


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _signed_knowledge_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "knowledge"
    repo.mkdir()
    key = tmp_path / "release-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
    )
    fingerprint = subprocess.run(
        ["ssh-keygen", "-lf", f"{key}.pub", "-E", "sha256"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[1]
    public_key = " ".join(
        key.with_suffix(".pub").read_text(encoding="utf-8").split()[:2]
    )
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Knowledge Release Test"),
        ("config", "user.email", "knowledge@example.invalid"),
        ("config", "gpg.format", "ssh"),
        ("config", "user.signingkey", str(key)),
        ("remote", "add", "origin", "git@github.com:example/knowledge.git"),
    ):
        _run(repo, *args)
    skill = repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: accounting\ndescription: Signed accounting knowledge\n"
        "tags: [accounting]\n---\n\nauthorized body\n",
        encoding="utf-8",
    )
    extension = repo / ".claude" / "extensions" / "do.extension.md"
    extension.parent.mkdir(parents=True)
    extension.write_text("signed extension body\n", encoding="utf-8")
    plugin = repo / "plugins" / "codex-copilot" / "SKILL.md"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("signed codex plugin\n", encoding="utf-8")
    (repo / "knowledge-manifest.json").write_text(
        json.dumps(
            {
                "extensions": [
                    {
                        "agent": "do",
                        "type": "override",
                        "file": ".claude/extensions/do.extension.md",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _run(repo, "add", ".")
    _run(repo, "commit", "-q", "--no-gpg-sign", "-m", "knowledge")
    _run(repo, "tag", "-s", "v1.0.0", "-m", "release")
    return repo, fingerprint, public_key


def _layer(repo: Path, fingerprint: str, *, ref: str = "v1.0.0") -> dict:
    return {
        "id": "knowledge-test",
        "role": "personal",
        "rank": 10,
        "product": "knowledge",
        "source": {
            "repo": "git@github.com:example/knowledge.git",
            "ref": ref,
            "path": str(repo),
        },
        "auth": "anon",
        "activation": "always",
        "policy": {"allowed_signers": [fingerprint]},
    }


@pytest.fixture
def signed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, fingerprint, public_key = _signed_knowledge_repo(tmp_path)
    monkeypatch.setattr(
        "cc.core.ecosystem.policy.FOUNDATION_SSH_SIGNING_KEYS",
        {fingerprint: public_key},
    )
    monkeypatch.setattr("cc.core.config.resolve_knowledge_repos", lambda: [str(repo)])
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key: {
            "layers.manifest": [_layer(repo, fingerprint)],
            "paths.mirrors_root": str(tmp_path / "mirrors"),
            "skills.cache_dir": str(tmp_path / "skill-cache"),
        }.get(key),
    )
    return repo, fingerprint


@pytest.fixture
def protected_signed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, fingerprint, public_key = _signed_knowledge_repo(tmp_path)
    layer = _layer(repo, fingerprint) | {
        "role": "department",
        "auth": "work",
    }
    state_path = tmp_path / "entitlements.json"
    checked_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    atomic_json_write(
        state_path,
        {
            "schema_version": entitlement.ENTITLEMENT_SCHEMA_VERSION,
            "next_sequence": 2,
            "layers": {
                "knowledge-test": {
                    "layer": "knowledge-test",
                    "product": "knowledge",
                    "repo": "example/knowledge",
                    "login": "person",
                    "state": "entitled",
                    "checked_at": checked_at,
                    "last_entitled_at": checked_at,
                    "revision": 1,
                }
            },
        },
    )
    monkeypatch.setattr(
        "cc.core.ecosystem.policy.FOUNDATION_SSH_SIGNING_KEYS",
        {fingerprint: public_key},
    )
    monkeypatch.setattr("cc.core.config.resolve_knowledge_repos", lambda: [str(repo)])
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key: {
            "layers.manifest": [layer],
            "paths.mirrors_root": str(tmp_path / "mirrors"),
            "skills.cache_dir": str(tmp_path / "skill-cache"),
        }.get(key),
    )
    monkeypatch.setattr("cc.core.ecosystem.entitlement.current_login", lambda: "person")
    monkeypatch.setattr(
        "cc.core.ecosystem.entitlement.entitlement_state_path", lambda: state_path
    )
    return repo, layer, state_path, tmp_path / "skill-cache" / "signed-knowledge-v1"


def _discover_signed():
    pairs = resolve_knowledge_skill_sources()
    skills = discover_skills_with_sources([(pairs[0][0], "knowledge")])
    assert len(skills) == 1
    return skills[0]


def test_signed_tree_drives_discovery_and_get(signed_source):
    repo, _fingerprint = signed_source
    skill = _discover_signed()
    assert skill.name == "accounting"
    assert get_skill_content(skill).endswith("authorized body\n")
    assert repo not in skill.path.parents
    assert stat.S_IMODE(skill.path.stat().st_mode) == 0o400
    assert stat.S_IMODE(skill.path.parent.stat().st_mode) == 0o500
    revalidate_skill_path(skill)


def _protected_projection(protected_signed_source):
    _repo, layer, _state_path, cache_root = protected_signed_source
    source = _discover_signed()._knowledge_source
    assert source.entitlement_binding is not None
    projections = resolve_protected_knowledge_lock_projections(
        [layer], [source.entitlement_binding], cache_root=cache_root
    )
    assert len(projections) == 1
    return source, projections[0]


def test_protected_receipt_projects_exact_signed_plugin_lock_identity(
    protected_signed_source,
):
    source, projection = _protected_projection(protected_signed_source)
    plugin_tree = source.release.read_blob  # receipt remains immutable/read-capable
    assert callable(plugin_tree)
    snapshot = read_git_tree_snapshot(source.repository_root, projection.item_tree)
    assert snapshot is not None
    assert projection.layer == "knowledge-test"
    assert projection.repository == "example/knowledge"
    assert projection.ref == source.ref
    assert projection.tree == source.tree
    assert projection.signer == source.signer
    assert projection.release_tree == source.release.tree
    assert projection.content_sha256 == stable_directory_content_sha(
        (item.path, item.content) for item in snapshot.files
    )


def test_protected_projection_fails_when_active_receipt_is_missing(
    protected_signed_source,
):
    source, _projection = _protected_projection(protected_signed_source)
    cache_root = protected_signed_source[3]
    atomic_json_write(
        cache_root / "index.json", {"schema_version": "1.0", "entries": {}}
    )

    with pytest.raises(KnowledgeSkillSourceError, match="matching active receipt"):
        resolve_protected_knowledge_lock_projections(
            [protected_signed_source[1]],
            [source.entitlement_binding],
            cache_root=cache_root,
        )


def test_protected_projection_rejects_revoked_binding(protected_signed_source):
    source, _projection = _protected_projection(protected_signed_source)
    assert source.entitlement_binding is not None
    revoked = entitlement.EntitlementBinding(
        **(
            source.entitlement_binding.as_dict()
            | {"state": "revoked", "eligible": False}
        )
    )

    with pytest.raises(KnowledgeSkillSourceError, match="active bound receipt"):
        resolve_protected_knowledge_lock_projections(
            [protected_signed_source[1]],
            [revoked],
            cache_root=protected_signed_source[3],
        )


def test_protected_projection_rolls_receipt_to_current_entitlement_generation(
    protected_signed_source,
):
    source, projection = _protected_projection(protected_signed_source)
    assert source.entitlement_binding is not None
    cache_root = protected_signed_source[3]
    old_index = json.loads((cache_root / "index.json").read_text(encoding="utf-8"))
    old_target = cache_root / old_index["entries"][projection.binding]["target"]
    current = entitlement.EntitlementBinding(
        **(source.entitlement_binding.as_dict() | {"revision": 2})
    )

    projections = resolve_protected_knowledge_lock_projections(
        [protected_signed_source[1]], [current], cache_root=cache_root
    )

    assert len(projections) == 1
    assert projections[0].binding != projection.binding
    assert not old_target.exists()
    new_index = json.loads((cache_root / "index.json").read_text(encoding="utf-8"))
    assert new_index["entries"][projections[0].binding]["revision"] == 2
    assert new_index["entries"][projections[0].binding]["status"] == "active"


def _tamper_protected_receipt(cache_root: Path, binding: str) -> tuple[Path, bytes]:
    index_path = cache_root / "index.json"
    index_before = index_path.read_bytes()
    index = json.loads(index_before)
    target = cache_root / index["entries"][binding]["target"]
    skill = target / "accounting" / "SKILL.md"
    skill.chmod(0o600)
    skill.write_text("tampered receipt bytes\n", encoding="utf-8")
    return target, index_before


def test_protected_projection_preserves_tampered_prior_receipt_on_rollover(
    protected_signed_source,
):
    source, projection = _protected_projection(protected_signed_source)
    assert source.entitlement_binding is not None
    cache_root = protected_signed_source[3]
    old_target, index_before = _tamper_protected_receipt(cache_root, projection.binding)
    current = entitlement.EntitlementBinding(
        **(source.entitlement_binding.as_dict() | {"revision": 2})
    )

    with pytest.raises(KnowledgeSkillSourceError, match="receipt bytes do not match"):
        resolve_protected_knowledge_lock_projections(
            [protected_signed_source[1]], [current], cache_root=cache_root
        )

    assert old_target.is_dir()
    assert (old_target / "accounting" / "SKILL.md").read_text() == (
        "tampered receipt bytes\n"
    )
    assert (cache_root / "index.json").read_bytes() == index_before


def test_update_tampered_rollover_aborts_without_receipt_or_lock_mutation(
    protected_signed_source, tmp_path, monkeypatch
):
    _repo, layer, state_path, cache_root = protected_signed_source
    _source, projection = _protected_projection(protected_signed_source)
    old_target, index_before = _tamper_protected_receipt(cache_root, projection.binding)
    ledger = json.loads(state_path.read_text(encoding="utf-8"))
    ledger["next_sequence"] = 3
    ledger["layers"][layer["id"]]["revision"] = 2
    atomic_json_write(state_path, ledger)
    monkeypatch.setattr(
        "cc.commands.update.entitlement.observe_layer",
        lambda *_args, **_kwargs: entitlement.EntitlementDecision(
            layer=layer["id"],
            state="entitled",
            eligible=True,
            responsible_actor="none",
            recovery="none",
            revision=2,
        ),
    )
    lock_path = tmp_path / "copilot.lock.json"
    previous_lock = {
        layer["id"]: {
            "plugins": {"codex-copilot": projection.content_sha256},
            "_meta": {"product": "knowledge", "role": "department"},
        }
    }
    atomic_json_write(lock_path, previous_lock)
    lock_before = lock_path.read_bytes()

    with pytest.raises(KnowledgeSkillSourceError, match="receipt bytes do not match"):
        build_update_report(
            _layers=[layer],
            _previous_lock=previous_lock,
            _lockfile_path=lock_path,
            _lock_write_path=lock_path,
            _mirror_root=tmp_path / "mirrors",
            _materialize_root=tmp_path / "materialize",
            _personal_roots=[],
            _entitlement_login="person",
            _entitlement_token="token",
            _entitlement_state_path=state_path,
            _entitlement_now=datetime.now(timezone.utc),
            _knowledge_snapshot_root=cache_root,
        )

    assert old_target.is_dir()
    assert (old_target / "accounting" / "SKILL.md").read_text() == (
        "tampered receipt bytes\n"
    )
    assert (cache_root / "index.json").read_bytes() == index_before
    assert lock_path.read_bytes() == lock_before


def test_protected_projection_rejects_mismatched_index_signer(
    protected_signed_source,
):
    source, projection = _protected_projection(protected_signed_source)
    cache_root = protected_signed_source[3]
    index = json.loads((cache_root / "index.json").read_text(encoding="utf-8"))
    index["entries"][projection.binding]["signer"] = "SHA256:mismatch"
    atomic_json_write(cache_root / "index.json", index)

    with pytest.raises(KnowledgeSkillSourceError, match="matching active receipt"):
        resolve_protected_knowledge_lock_projections(
            [protected_signed_source[1]],
            [source.entitlement_binding],
            cache_root=cache_root,
        )


def test_ordinary_knowledge_read_has_no_ecosystem_lock_write_authority(
    signed_source, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("ordinary read attempted an ecosystem lock write")

    monkeypatch.setattr("cc.core.ecosystem.lockfile.write_lockfile", forbidden)
    assert _discover_signed().name == "accounting"


def test_signed_skill_get_returns_exact_authenticated_receipt(signed_source):
    _repo, _fingerprint = signed_source
    skill = _discover_signed()
    result = get_skill_content_with_receipt(skill, runtime="claude")

    assert result.content.endswith("authorized body\n")
    assert result.is_authenticated is True
    assert result.receipt.layer == "knowledge-test"
    assert result.receipt.role == "personal"
    assert result.receipt.repository == "example/knowledge"
    assert result.receipt.ref == "v1.0.0"
    assert result.receipt.tree == skill._knowledge_source.release.tree
    assert result.receipt.signer == skill._knowledge_source.signer
    assert result.receipt.contribution.endswith("/accounting/SKILL.md")
    assert (
        result.receipt.content_sha256
        == __import__("hashlib").sha256(result.content.encode("utf-8")).hexdigest()
    )
    assert result.receipt.runtime == "claude"


def test_signed_release_blob_read_ignores_checkout_and_tag_switch(signed_source):
    repo, _fingerprint = signed_source
    source = _discover_signed()._knowledge_source
    expected = source.release.read_blob(".claude/extensions/do.extension.md")
    (repo / ".claude/extensions/do.extension.md").write_text(
        "mutable checkout replacement\n", encoding="utf-8"
    )
    _run(repo, "tag", "-f", "v1.0.0", "HEAD")

    assert source.release.read_blob(".claude/extensions/do.extension.md") == expected


def test_existing_resolver_composes_signed_extension_with_receipt(signed_source):
    repo, _fingerprint = signed_source
    resolution = resolve_extension("do", knowledge_repos=[str(repo)])
    composed = compose_agent_content_with_receipts(resolution, "base ignored")

    assert resolution.action == ACTION_APPLY
    assert composed.content == "signed extension body\n"
    assert len(composed.receipts) == 1
    assert composed.receipts[0].contribution == ".claude/extensions/do.extension.md"
    assert composed.receipts[0].content_sha256 == composed.content_sha256


def test_signed_extension_checkout_mutation_cannot_change_composition(signed_source):
    repo, _fingerprint = signed_source
    resolution = resolve_extension("do", knowledge_repos=[str(repo)])
    (repo / ".claude/extensions/do.extension.md").write_text(
        "attacker checkout bytes\n", encoding="utf-8"
    )

    composed = compose_agent_content_with_receipts(resolution, "")
    assert composed.content == "signed extension body\n"
    assert "attacker" not in composed.content


def test_tracked_mutation_fails_closed_before_discovery(signed_source):
    repo, _fingerprint = signed_source
    (repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting" / "SKILL.md").write_text(
        "malicious working-tree body\n", encoding="utf-8"
    )
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources()


def test_untracked_and_ignored_additions_fail_closed(signed_source):
    repo, _fingerprint = signed_source
    injected = repo / KNOWLEDGE_SKILLS_SUBPATH / "injected" / "SKILL.md"
    injected.parent.mkdir()
    injected.write_text("untracked injection\n", encoding="utf-8")
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources()
    injected.unlink()
    (repo / ".gitignore").write_text(
        f"/{KNOWLEDGE_SKILLS_SUBPATH}/injected/\n", encoding="utf-8"
    )
    _run(repo, "add", ".gitignore")
    _run(repo, "commit", "-q", "--no-gpg-sign", "-m", "ignore rule after release")
    injected.write_text("ignored injection\n", encoding="utf-8")
    with pytest.raises(
        KnowledgeSkillSourceError, match="signed release|ignored local additions"
    ):
        resolve_knowledge_skill_sources()


def test_wrong_ref_signer_and_origin_fail_closed(
    signed_source, monkeypatch: pytest.MonkeyPatch
):
    repo, fingerprint = signed_source
    config = {
        "layers.manifest": [_layer(repo, fingerprint, ref="missing")],
        "paths.mirrors_root": str(repo.parent / "mirrors"),
    }
    monkeypatch.setattr("cc.core.config.resolve_key", lambda key: config.get(key))
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources()

    config["layers.manifest"] = [_layer(repo, "SHA256:not-compiled")]
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources()

    config["layers.manifest"] = [_layer(repo, fingerprint)]
    _run(repo, "remote", "set-url", "origin", "git@github.com:other/repo.git")
    with pytest.raises(KnowledgeSkillSourceError, match="wrong repository origin"):
        resolve_knowledge_skill_sources()


def test_unsigned_tag_and_symlinked_item_fail_closed(
    signed_source, monkeypatch: pytest.MonkeyPatch
):
    repo, fingerprint = signed_source
    _run(repo, "tag", "unsigned")
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key: {
            "layers.manifest": [_layer(repo, fingerprint, ref="unsigned")],
            "paths.mirrors_root": str(repo.parent / "mirrors"),
        }.get(key),
    )
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources()

    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key: {
            "layers.manifest": [_layer(repo, fingerprint)],
            "paths.mirrors_root": str(repo.parent / "mirrors"),
        }.get(key),
    )
    target = repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting" / "SKILL.md"
    original = target.read_text(encoding="utf-8")
    target.unlink()
    outside = repo.parent / "outside-skill"
    outside.write_text(original, encoding="utf-8")
    target.symlink_to(outside)
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources()


def test_symlinked_skill_ancestor_fails_closed(signed_source):
    repo, _fingerprint = signed_source
    skill_dir = repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting"
    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    (skill_dir / "SKILL.md").unlink()
    skill_dir.rmdir()
    outside = repo.parent / "outside-accounting"
    outside.mkdir()
    (outside / "SKILL.md").write_text(content, encoding="utf-8")
    skill_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(KnowledgeSkillSourceError, match="signed release"):
        resolve_knowledge_skill_sources()


def test_mutation_after_discovery_blocks_get_and_path(signed_source):
    repo, _fingerprint = signed_source
    skill = _discover_signed()
    checkout_skill = repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting" / "SKILL.md"
    checkout_skill.write_text("changed after selection\n", encoding="utf-8")
    with pytest.raises(KnowledgeSkillSourceError):
        get_skill_content(skill)
    with pytest.raises(KnowledgeSkillSourceError):
        revalidate_skill_path(skill)


@pytest.mark.parametrize(
    ("arguments", "forbidden"),
    [
        (["skill", "search", "accounting"], "changed after selection"),
        (["skill", "get", "accounting"], "changed after selection"),
        (["skill", "path", "accounting"], KNOWLEDGE_SKILLS_SUBPATH),
    ],
)
def test_cli_search_get_and_path_fail_closed_on_mutable_tamper(
    signed_source, arguments: list[str], forbidden: str
):
    repo, _fingerprint = signed_source
    (repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting" / "SKILL.md").write_text(
        "changed after selection\n", encoding="utf-8"
    )
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 1
    assert "do not match their signed release" in result.output
    assert forbidden not in result.output


def test_path_returns_immutable_snapshot_not_mutable_checkout(signed_source):
    repo, _fingerprint = signed_source
    result = CliRunner().invoke(
        app, ["skill", "path", "accounting", "--scope", "knowledge"]
    )
    assert result.exit_code == 0, result.output
    emitted = Path(result.output.strip())
    assert repo not in emitted.parents

    checkout_skill = repo / KNOWLEDGE_SKILLS_SUBPATH / "accounting" / "SKILL.md"
    checkout_skill.write_text("attacker bytes after path return\n", encoding="utf-8")

    assert emitted.read_text(encoding="utf-8").endswith("authorized body\n")
    assert "attacker bytes" not in emitted.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "arguments",
    [
        ["skill", "list", "--scope", "knowledge", "--json"],
        ["skill", "search", "accounting", "--scope", "knowledge", "--json"],
    ],
)
def test_path_bearing_json_uses_snapshot_not_checkout(
    signed_source, arguments: list[str]
):
    repo, _fingerprint = signed_source
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output
    path = Path(json.loads(result.output)[0]["path"])
    assert repo not in path.parents
    assert path.read_text(encoding="utf-8").endswith("authorized body\n")


def test_cached_snapshot_tamper_fails_closed(signed_source):
    skill = _discover_signed()
    skill.path.chmod(0o600)
    skill.path.write_text("tampered cached bytes\n", encoding="utf-8")

    with pytest.raises(KnowledgeSkillSourceError, match="snapshot failed integrity"):
        resolve_knowledge_skill_sources()


def test_public_signed_knowledge_is_account_free(
    signed_source, monkeypatch: pytest.MonkeyPatch
):
    def unexpected_account_access():
        raise AssertionError("public Knowledge consulted account state")

    monkeypatch.setattr(
        "cc.core.ecosystem.entitlement.current_login", unexpected_account_access
    )
    monkeypatch.setattr(
        "cc.core.ecosystem.entitlement.entitlement_state_path",
        unexpected_account_access,
    )

    skill = _discover_signed()
    assert get_skill_content(skill).endswith("authorized body\n")


def test_protected_index_is_private_token_free_and_revision_scoped(
    protected_signed_source,
):
    _repo, _layer, state_path, cache_root = protected_signed_source
    skill = _discover_signed()
    index_path = cache_root / "index.json"
    serialized = index_path.read_text(encoding="utf-8")
    index = json.loads(serialized)
    entry = next(iter(index["entries"].values()))

    assert stat.S_IMODE(cache_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(index_path.stat().st_mode) == 0o600
    assert "token" not in serialized.casefold()
    assert entry["layer"] == "knowledge-test"
    assert entry["repository"] == "example/knowledge"
    assert entry["login"] == "person"
    assert entry["revision"] == 1
    assert entry["state_path"] == str(state_path)
    assert entry["ref"] == "v1.0.0"
    assert entry["tree"] == skill._knowledge_source.tree
    assert all(
        value not in entry["target"]
        for value in ("knowledge-test", "example/knowledge", "person")
    )


@pytest.mark.parametrize(
    ("login", "token", "status", "expected_state"),
    [
        ("person", "token", 404, "revoked"),
        ("new-person", "token", 404, "unentitled"),
        (None, None, None, "signed-out"),
    ],
)
def test_protected_prior_path_is_pruned_on_terminal_observation(
    protected_signed_source,
    login: str | None,
    token: str | None,
    status: int | None,
    expected_state: str,
):
    repo, layer, state_path, _cache_root = protected_signed_source
    skill = _discover_signed()
    stale_path = skill.path
    assert stale_path.is_file()

    decision = entitlement.observe_layer(
        layer,
        login=login,
        token=token,
        get_json=lambda *_args, **_kwargs: status,
        state_path=state_path,
    )

    assert decision.state == expected_state
    assert decision.eligible is False
    assert not stale_path.exists()
    with pytest.raises(FileNotFoundError):
        stale_path.read_bytes()
    if login == "new-person":
        assert resolve_knowledge_skill_sources(entitlement_login=login) == []
    else:
        assert resolve_knowledge_skill_sources() == []
    assert (repo / KNOWLEDGE_SKILLS_SUBPATH).is_dir()


def test_protected_extension_revocation_never_falls_back_to_checkout(
    protected_signed_source,
):
    repo, layer, state_path, _cache_root = protected_signed_source
    initial = resolve_extension("do", knowledge_repos=[str(repo)])
    assert initial.action == ACTION_APPLY
    assert compose_agent_content_with_receipts(initial, "base").content == (
        "signed extension body\n"
    )

    decision = entitlement.observe_layer(
        layer,
        login="person",
        token="token",
        get_json=lambda *_args, **_kwargs: 404,
        state_path=state_path,
    )
    assert decision.state == "revoked"
    (repo / ".claude/extensions/do.extension.md").write_text(
        "ATTACKER AFTER REVOKE\n", encoding="utf-8"
    )

    revoked = resolve_extension("do", knowledge_repos=[str(repo)])
    composed = compose_agent_content_with_receipts(revoked, "base")

    assert revoked.action == ACTION_NO_EXTENSION
    assert revoked.contributions == ()
    assert composed.content == "base"
    assert composed.receipts == ()
    assert "ATTACKER" not in composed.content


def test_offline_eligible_revision_retains_then_reauth_supersedes_snapshot(
    protected_signed_source,
):
    _repo, layer, state_path, _cache_root = protected_signed_source
    skill = _discover_signed()
    prior_path = skill.path

    offline = entitlement.observe_layer(
        layer,
        login="person",
        token="token",
        get_json=lambda *_args, **_kwargs: None,
        state_path=state_path,
    )
    assert offline.state == "offline-cached"
    assert offline.eligible is True
    assert not prior_path.exists()
    refreshed = _discover_signed()
    assert refreshed.path != prior_path
    assert refreshed.path.is_file()

    live = entitlement.observe_layer(
        layer,
        login="person",
        token="token",
        get_json=lambda *_args, **_kwargs: 200,
        state_path=state_path,
    )
    assert live.eligible is True
    assert not refreshed.path.exists()


def test_protected_read_and_revoke_serialize_without_partial_bytes(
    protected_signed_source, monkeypatch: pytest.MonkeyPatch
):
    _repo, layer, state_path, _cache_root = protected_signed_source
    skill = _discover_signed()
    entered = threading.Event()
    release = threading.Event()
    original = skill._knowledge_source.snapshot.files[0].content

    from cc.core.ecosystem import knowledge_skill_source as source_module

    real_read = source_module._read_private_file

    def delayed_read(path, *, expected_mode):
        entered.set()
        assert release.wait(timeout=5)
        return real_read(path, expected_mode=expected_mode)

    monkeypatch.setattr(source_module, "_read_private_file", delayed_read)
    result: list[str] = []

    reader = threading.Thread(
        target=lambda: result.append(skill._knowledge_source.read_text(skill.path))
    )
    reader.start()
    assert entered.wait(timeout=5)

    revoke_done = threading.Event()

    def revoke():
        entitlement.observe_layer(
            layer,
            login="person",
            token="token",
            get_json=lambda *_args, **_kwargs: 404,
            state_path=state_path,
        )
        revoke_done.set()

    revoker = threading.Thread(target=revoke)
    revoker.start()
    assert not revoke_done.wait(timeout=0.1)
    release.set()
    reader.join(timeout=5)
    revoker.join(timeout=5)

    assert result and result[0].encode("utf-8") == original
    assert revoke_done.is_set()
    assert not skill.path.exists()


def test_superseded_offline_observation_cannot_restore_revoked_snapshot(
    protected_signed_source,
):
    _repo, layer, state_path, _cache_root = protected_signed_source
    skill = _discover_signed()
    stale_path = skill.path
    entered = threading.Event()
    release = threading.Event()
    results: list[entitlement.EntitlementDecision] = []

    def delayed_offline(_url, _token):
        entered.set()
        assert release.wait(timeout=5)
        return None

    old = threading.Thread(
        target=lambda: results.append(
            entitlement.observe_layer(
                layer,
                login="person",
                token="token",
                get_json=delayed_offline,
                state_path=state_path,
            )
        )
    )
    old.start()
    assert entered.wait(timeout=5)
    revoked = entitlement.observe_layer(
        layer,
        login="person",
        token="token",
        get_json=lambda *_args, **_kwargs: 404,
        state_path=state_path,
    )
    assert revoked.state == "revoked"
    assert not stale_path.exists()

    release.set()
    old.join(timeout=5)
    assert results and results[0].superseded is True
    assert results[0].eligible is False
    assert not stale_path.exists()
    assert resolve_knowledge_skill_sources() == []


def test_superseded_old_identity_cannot_prune_new_reauthorization(
    protected_signed_source,
):
    _repo, layer, state_path, _cache_root = protected_signed_source
    old_skill = _discover_signed()
    entered = threading.Event()
    release = threading.Event()
    results: list[entitlement.EntitlementDecision] = []

    def delayed_denial(_url, _token):
        entered.set()
        assert release.wait(timeout=5)
        return 404

    old = threading.Thread(
        target=lambda: results.append(
            entitlement.observe_layer(
                layer,
                login="person",
                token="token",
                get_json=delayed_denial,
                state_path=state_path,
            )
        )
    )
    old.start()
    assert entered.wait(timeout=5)
    reauthorized = entitlement.observe_layer(
        layer,
        login="new-person",
        token="token",
        get_json=lambda *_args, **_kwargs: 200,
        state_path=state_path,
    )
    assert reauthorized.eligible is True
    assert not old_skill.path.exists()
    pairs = resolve_knowledge_skill_sources(entitlement_login="new-person")
    new_skill = discover_skills(
        [pairs[0][0]],
        source_label="knowledge",
        _knowledge_source=pairs[0][1],
    )[0]
    assert new_skill.path.is_file()

    release.set()
    old.join(timeout=5)
    assert results and results[0].superseded is True
    assert results[0].eligible is True
    assert new_skill.path.is_file()


def test_hard_prune_recovers_pending_and_removes_indexed_snapshots(
    protected_signed_source,
):
    _repo, _layer, _state_path, cache_root = protected_signed_source
    skill = _discover_signed()
    assert skill.path.exists()
    assert prune_all_knowledge_snapshots(cache_root=cache_root) == 1
    assert not skill.path.exists()
    index = json.loads((cache_root / "index.json").read_text(encoding="utf-8"))
    assert index["entries"] == {}


def test_interrupted_publication_is_recovered_without_reviving_path(
    protected_signed_source,
):
    _repo, _layer, _state_path, cache_root = protected_signed_source
    skill = _discover_signed()
    index_path = cache_root / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entry = next(iter(index["entries"].values()))
    entry["status"] = "pending"
    atomic_json_write(index_path, index)

    assert prune_all_knowledge_snapshots(cache_root=cache_root) == 0
    assert not skill.path.exists()
    recovered = json.loads(index_path.read_text(encoding="utf-8"))
    assert recovered["entries"] == {}


def test_symlinked_snapshot_index_fails_closed_and_preserves_outside(
    protected_signed_source,
):
    _repo, _layer, _state_path, cache_root = protected_signed_source
    skill = _discover_signed()
    index_path = cache_root / "index.json"
    outside = cache_root.parent / "outside-index.json"
    outside.write_text(index_path.read_text(encoding="utf-8"), encoding="utf-8")
    index_path.unlink()
    index_path.symlink_to(outside)

    with pytest.raises(KnowledgeSkillSourceError, match="index is unsafe"):
        prune_all_knowledge_snapshots(cache_root=cache_root)
    # Hard-prune rejects corrupted metadata without following the link.  The
    # entitlement path uses the protected-only emergency invalidation below.
    assert skill.path.exists()
    assert outside.is_file()

    with pytest.raises(KnowledgeSkillSourceError, match="index is unsafe"):
        entitlement.observe_layer(
            protected_signed_source[1],
            login="person",
            token="token",
            get_json=lambda *_args, **_kwargs: 404,
            state_path=protected_signed_source[2],
        )
    assert not skill.path.exists()
    assert outside.is_file()


def test_revocation_unlinks_replaced_snapshot_without_following_it(
    protected_signed_source,
):
    _repo, layer, state_path, cache_root = protected_signed_source
    skill = _discover_signed()
    snapshot_root = skill._knowledge_source.skills_root
    outside = cache_root.parent / "outside-protected-tree"
    snapshot_root.rename(outside)
    snapshot_root.symlink_to(outside, target_is_directory=True)
    assert skill.path.is_file()

    decision = entitlement.observe_layer(
        layer,
        login="person",
        token="token",
        get_json=lambda *_args, **_kwargs: 404,
        state_path=state_path,
    )

    assert decision.state == "revoked"
    assert not snapshot_root.exists()
    assert not snapshot_root.is_symlink()
    assert (outside / "accounting" / "SKILL.md").is_file()


def test_protected_revocation_preserves_account_free_public_snapshot(
    protected_signed_source, monkeypatch: pytest.MonkeyPatch
):
    repo, protected_layer, state_path, _cache_root = protected_signed_source
    protected_skill = _discover_signed()
    public_layer = protected_layer | {"role": "personal", "auth": "anon"}
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key: {
            "layers.manifest": [public_layer],
            "paths.mirrors_root": str(repo.parent / "mirrors"),
            "skills.cache_dir": str(repo.parent / "skill-cache"),
        }.get(key),
    )
    public_skill = _discover_signed()
    assert public_skill.path != protected_skill.path

    entitlement.observe_layer(
        protected_layer,
        login="person",
        token="token",
        get_json=lambda *_args, **_kwargs: 404,
        state_path=state_path,
    )

    assert not protected_skill.path.exists()
    assert public_skill.path.is_file()
    assert public_skill.path.read_text(encoding="utf-8").endswith("authorized body\n")


def test_hard_deprovision_prunes_exact_index_and_preserves_unrelated_cache(
    protected_signed_source,
):
    _repo, _layer, _state_path, cache_root = protected_signed_source
    skill = _discover_signed()
    unrelated = cache_root / "not-framework-owned.txt"
    unrelated.write_text("keep", encoding="utf-8")

    report = build_deprovision_report(
        _lockfile_path=cache_root.parent / "missing.lock.json",
        _mirror_root=cache_root.parent / "mirrors",
        _materialize_root=cache_root.parent / "materialized",
        _knowledge_snapshot_root=cache_root,
        _mode="hard",
        _personal_roots=[],
    )

    assert report["removed"]["materialized"] == 1
    assert not skill.path.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
