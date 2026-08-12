"""Authenticated Knowledge skill sources.

Configured Knowledge repositories predate the ecosystem manifest and remain
valid when no signed layer declares them.  Once a matching effective layer
declares signer policy, however, the mutable checkout is no longer authority:
the signed annotated tag and its exact skill-tree Git object are.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from cc.core.ecosystem import entitlement
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers
from cc.core.ecosystem.mirror import synthesize_effective_layers
from cc.core.ecosystem.policy import (
    GitTreeSnapshot,
    read_git_tree_snapshot,
    verify_git_item_provenance,
)
from cc.core.ecosystem.repository_scope import repository_identity

KNOWLEDGE_SKILLS_SUBPATH = "03-ai-enabling/01-skills"


class KnowledgeSkillSourceError(ValueError):
    """A signed Knowledge source could not earn read authority."""


@dataclass(frozen=True)
class VerifiedKnowledgeSkillSource:
    skills_root: Path
    repository_root: Path
    relative_path: str
    repository: str
    layer: str
    ref: str
    tree: str
    signer: str
    snapshot: GitTreeSnapshot

    def skill_files(self) -> tuple[Path, ...]:
        """Return SKILL.md paths enumerated by the immutable Git tree."""
        return tuple(
            self.skills_root / item.path
            for item in self.snapshot.files
            if item.path == "SKILL.md" or item.path.endswith("/SKILL.md")
        )

    def read_text(self, path: Path) -> str:
        """Read one skill from authenticated object bytes, never the checkout."""
        relative = _relative_skill_path(self.skills_root, path)
        item = next((row for row in self.snapshot.files if row.path == relative), None)
        if item is None:
            raise KnowledgeSkillSourceError(
                "The requested Knowledge skill is absent from its signed release."
            )
        try:
            return item.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeSkillSourceError(
                "The requested Knowledge skill is not valid UTF-8."
            ) from exc


def _nominal(path: Path | str) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _relative_skill_path(root: Path, path: Path) -> str:
    nominal = _nominal(path)
    try:
        relative = nominal.relative_to(root)
    except ValueError as exc:
        raise KnowledgeSkillSourceError(
            "The requested Knowledge skill escapes its signed source."
        ) from exc
    if relative.is_absolute() or ".." in relative.parts:
        raise KnowledgeSkillSourceError(
            "The requested Knowledge skill escapes its signed source."
        )
    return relative.as_posix()


def _origin(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return repository_identity(result.stdout.strip()) if result.returncode == 0 else None


def _has_ignored_additions(root: Path, relative_path: str) -> bool:
    """Reject ignored files that Git's ordinary untracked listing omits."""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--",
                relative_path,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return result.returncode != 0 or bool(result.stdout.strip())


def _signed_policy(layer: dict[str, Any]) -> list[str] | None:
    policy = layer.get("policy")
    signers = policy.get("allowed_signers") if isinstance(policy, dict) else None
    if not isinstance(signers, list) or not signers:
        return None
    if not all(isinstance(item, str) and item.strip() for item in signers):
        raise KnowledgeSkillSourceError(
            "A Knowledge layer declares an invalid signer policy."
        )
    return signers


def _effective_knowledge_layers(
    manifest_source: Any, mirror_root_base: Path | str
) -> tuple[list[dict[str, Any]], set[str]]:
    try:
        layers = validate_layers(load_layers(manifest_source))
        knowledge = [layer for layer in layers if layer.get("product") == "knowledge"]
        if not knowledge:
            return [], set()
        eligible, _decisions = entitlement.filter_eligible_layers(knowledge)
        effective = synthesize_effective_layers(
            knowledge, mirror_root_base=mirror_root_base
        )
    except (ManifestError, OSError, TypeError, ValueError) as exc:
        raise KnowledgeSkillSourceError(
            "The configured Knowledge layer manifest is invalid."
        ) from exc
    return effective, {str(layer.get("id")) for layer in eligible}


def resolve_knowledge_skill_sources(
    *,
    repositories: Iterable[str] | None = None,
    manifest_source: Any = None,
    mirror_root_base: Path | str | None = None,
) -> list[tuple[Path, VerifiedKnowledgeSkillSource | None]]:
    """Resolve configured roots and authenticate every signed matching layer.

    The ``None`` source is the explicit compatibility state for a configured
    repository that has no signed matching layer.  A signed but ineligible
    layer is excluded; a signed eligible layer that cannot verify blocks.
    """
    from cc.core import config

    configured_repositories = list(
        config.resolve_knowledge_repos() if repositories is None else repositories
    )
    configured_manifest = (
        config.resolve_key("layers.manifest")
        if manifest_source is None
        else manifest_source
    )
    if not configured_manifest:
        return [
            (_nominal(repo) / KNOWLEDGE_SKILLS_SUBPATH, None)
            for repo in configured_repositories
            if (_nominal(repo) / KNOWLEDGE_SKILLS_SUBPATH).is_dir()
        ]
    mirrors = (
        config.resolve_key("paths.mirrors_root")
        if mirror_root_base is None
        else mirror_root_base
    )
    effective, eligible_ids = _effective_knowledge_layers(
        configured_manifest, mirrors or Path.home() / ".copilot" / "mirrors"
    )
    result: list[tuple[Path, VerifiedKnowledgeSkillSource | None]] = []
    for repo_value in configured_repositories:
        repo = _nominal(repo_value)
        skills_root = repo / KNOWLEDGE_SKILLS_SUBPATH
        matches = [
            layer
            for layer in effective
            if isinstance((layer.get("source") or {}).get("path"), str)
            and _nominal((layer.get("source") or {})["path"]) == repo
        ]
        if len(matches) > 1:
            raise KnowledgeSkillSourceError(
                "A configured Knowledge repository matches more than one layer."
            )
        if not matches:
            if skills_root.is_dir():
                result.append((skills_root, None))
            continue
        layer = matches[0]
        signers = _signed_policy(layer)
        if signers is None:
            if skills_root.is_dir():
                result.append((skills_root, None))
            continue
        if str(layer.get("id")) not in eligible_ids:
            continue
        source = layer.get("source") or {}
        ref = source.get("ref")
        expected_repository = repository_identity(source.get("repo"))
        if not isinstance(ref, str) or not ref or expected_repository is None:
            raise KnowledgeSkillSourceError(
                "The effective Knowledge layer lacks immutable source provenance."
            )
        verified = verify_git_item_provenance(
            repo, KNOWLEDGE_SKILLS_SUBPATH, signers, ref=ref
        )
        if verified is None:
            raise KnowledgeSkillSourceError(
                "The effective Knowledge skills do not match their signed release."
            )
        repository_root = Path(verified.repository_root)
        if _origin(repository_root) != expected_repository:
            raise KnowledgeSkillSourceError(
                "The effective Knowledge checkout has the wrong repository origin."
            )
        if _has_ignored_additions(repository_root, verified.relative_path):
            raise KnowledgeSkillSourceError(
                "The effective Knowledge skills contain ignored local additions."
            )
        snapshot = read_git_tree_snapshot(repository_root, verified.tree)
        if snapshot is None:
            raise KnowledgeSkillSourceError(
                "The signed Knowledge skill tree contains an unsafe Git object."
            )
        result.append(
            (
                skills_root,
                VerifiedKnowledgeSkillSource(
                    skills_root=skills_root,
                    repository_root=repository_root,
                    relative_path=verified.relative_path,
                    repository=expected_repository,
                    layer=str(layer["id"]),
                    ref=verified.ref,
                    tree=verified.tree,
                    signer=verified.signer,
                    snapshot=snapshot,
                ),
            )
        )
    return result


def revalidate_knowledge_skill_source(
    expected: VerifiedKnowledgeSkillSource,
) -> VerifiedKnowledgeSkillSource:
    """Require the same layer/ref/tree/signer to remain currently authorized."""
    current = resolve_knowledge_skill_sources()
    source = next(
        (candidate for root, candidate in current if root == expected.skills_root),
        None,
    )
    if source is None or any(
        getattr(source, field) != getattr(expected, field)
        for field in ("repository", "layer", "ref", "tree", "signer")
    ):
        raise KnowledgeSkillSourceError(
            "The Knowledge source changed after it was selected; retry the command."
        )
    return source


__all__ = [
    "KNOWLEDGE_SKILLS_SUBPATH",
    "KnowledgeSkillSourceError",
    "VerifiedKnowledgeSkillSource",
    "resolve_knowledge_skill_sources",
    "revalidate_knowledge_skill_source",
]
