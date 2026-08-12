"""Signed, immutable Knowledge skill read enforcement."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from cc.core.ecosystem.knowledge_skill_source import (
    KNOWLEDGE_SKILLS_SUBPATH,
    KnowledgeSkillSourceError,
    resolve_knowledge_skill_sources,
)
from cc.core.skill_store import (
    discover_skills_with_sources,
    get_skill_content,
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
    monkeypatch.setattr(
        "cc.core.config.resolve_knowledge_repos", lambda: [str(repo)]
    )
    monkeypatch.setattr(
        "cc.core.config.resolve_key",
        lambda key: {
            "layers.manifest": [_layer(repo, fingerprint)],
            "paths.mirrors_root": str(tmp_path / "mirrors"),
        }.get(key),
    )
    return repo, fingerprint


def _discover_signed():
    pairs = resolve_knowledge_skill_sources()
    skills = discover_skills_with_sources([(pairs[0][0], "knowledge")])
    assert len(skills) == 1
    return skills[0]


def test_signed_tree_drives_discovery_and_get(signed_source):
    skill = _discover_signed()
    assert skill.name == "accounting"
    assert get_skill_content(skill).endswith("authorized body\n")
    revalidate_skill_path(skill)


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
    with pytest.raises(KnowledgeSkillSourceError, match="signed release|ignored local additions"):
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
    skill.path.write_text("changed after selection\n", encoding="utf-8")
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
