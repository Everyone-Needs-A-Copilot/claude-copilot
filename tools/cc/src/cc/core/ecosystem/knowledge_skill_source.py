"""Authenticated Knowledge skill sources.

Configured Knowledge repositories predate the ecosystem manifest and remain
valid when no signed layer declares them.  Once a matching effective layer
declares signer policy, however, the mutable checkout is no longer authority:
the signed annotated tag and its exact skill-tree Git object are.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
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
from cc.core.ecosystem.project_locking import (
    UnsafeProjectPath,
    ensure_private_directory,
    fsync_directory,
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


def _snapshot_cache_root() -> Path:
    """Return a private, non-symlinked root for authenticated snapshots."""
    from cc.core import config

    raw = config.resolve_key("skills.cache_dir")
    cache_root = _nominal(raw or Path.home() / ".claude" / "cache" / "skills")
    snapshots = cache_root / "signed-knowledge-v1"
    try:
        ensure_private_directory(cache_root, boundary=cache_root)
        ensure_private_directory(snapshots, boundary=cache_root)
    except (OSError, UnsafeProjectPath) as exc:
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot cache is unsafe."
        ) from exc
    return snapshots


def _snapshot_binding(
    *,
    repository: str,
    layer: str,
    ref: str,
    tree: str,
    signer: str,
    snapshot: GitTreeSnapshot,
) -> str:
    encoded = json.dumps(
        [
            "signed-knowledge-v1",
            repository,
            layer,
            ref,
            tree,
            signer,
            snapshot.fingerprint(),
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_directories(snapshot: GitTreeSnapshot) -> set[str]:
    result: set[str] = set()
    for item in snapshot.files:
        parent = Path(item.path).parent
        while parent != Path("."):
            result.add(parent.as_posix())
            parent = parent.parent
    return result


def _read_private_file(path: Path, *, expected_mode: int) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != expected_mode
        ):
            return None
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _snapshot_matches(target: Path, snapshot: GitTreeSnapshot) -> bool:
    """Require exact bytes, shape, modes, and ownership in a cached tree."""
    try:
        root_metadata = target.lstat()
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_ISLNK(root_metadata.st_mode)
            or root_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(root_metadata.st_mode) != 0o500
        ):
            return False
        expected_files = {item.path: item for item in snapshot.files}
        expected_directories = _snapshot_directories(snapshot)
        observed_files: set[str] = set()
        observed_directories: set[str] = set()
        for root, directories, files in os.walk(target, followlinks=False):
            root_path = Path(root)
            for name in directories:
                candidate = root_path / name
                metadata = candidate.lstat()
                relative = candidate.relative_to(target).as_posix()
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o500
                ):
                    return False
                observed_directories.add(relative)
            for name in files:
                candidate = root_path / name
                relative = candidate.relative_to(target).as_posix()
                expected = expected_files.get(relative)
                if expected is None:
                    return False
                expected_mode = 0o500 if expected.mode & 0o111 else 0o400
                content = _read_private_file(candidate, expected_mode=expected_mode)
                if content is None or content != expected.content:
                    return False
                observed_files.add(relative)
        return (
            observed_files == set(expected_files)
            and observed_directories == expected_directories
        )
    except (OSError, ValueError):
        return False


def _make_stage_writable(stage: Path) -> None:
    """Best-effort cleanup preparation for an unpublished private stage."""
    if not stage.exists() or stage.is_symlink():
        return
    for root, directories, files in os.walk(stage, topdown=False, followlinks=False):
        for name in files:
            try:
                (Path(root) / name).chmod(0o600)
            except OSError:
                pass
        for name in directories:
            try:
                (Path(root) / name).chmod(0o700)
            except OSError:
                pass
    try:
        stage.chmod(0o700)
    except OSError:
        pass


def _materialize_snapshot(
    snapshot: GitTreeSnapshot,
    *,
    repository: str,
    layer: str,
    ref: str,
    tree: str,
    signer: str,
) -> Path:
    """Atomically publish exact Git-object bytes under a private digest path."""
    base = _snapshot_cache_root()
    binding = _snapshot_binding(
        repository=repository,
        layer=layer,
        ref=ref,
        tree=tree,
        signer=signer,
        snapshot=snapshot,
    )
    target = base / binding
    if target.exists() or target.is_symlink():
        if _snapshot_matches(target, snapshot):
            return target
        raise KnowledgeSkillSourceError(
            "A cached Knowledge snapshot failed integrity verification."
        )

    stage = Path(tempfile.mkdtemp(prefix=f".{binding}.", dir=base))
    try:
        stage.chmod(0o700)
        for item in snapshot.files:
            destination = stage / item.path
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                destination,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(item.content)
                handle.flush()
                os.fsync(handle.fileno())
            final_mode = 0o500 if item.mode & 0o111 else 0o400
            destination.chmod(final_mode)

        directories = sorted(
            (candidate for candidate in stage.rglob("*") if candidate.is_dir()),
            key=lambda candidate: len(candidate.parts),
            reverse=True,
        )
        for directory in directories:
            fsync_directory(directory)
            directory.chmod(0o500)
        fsync_directory(stage)
        stage.chmod(0o500)

        try:
            os.rename(stage, target)
        except OSError:
            if not _snapshot_matches(target, snapshot):
                raise
        fsync_directory(base)
        if not _snapshot_matches(target, snapshot):
            raise KnowledgeSkillSourceError(
                "The authenticated Knowledge snapshot changed during publication."
            )
        return target
    except KnowledgeSkillSourceError:
        raise
    except OSError as exc:
        raise KnowledgeSkillSourceError(
            "The authenticated Knowledge snapshot could not be published safely."
        ) from exc
    finally:
        if stage.exists() and stage != target:
            _make_stage_writable(stage)
            shutil.rmtree(stage, ignore_errors=True)


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
        layer_id = str(layer["id"])
        materialized_root = _materialize_snapshot(
            snapshot,
            repository=expected_repository,
            layer=layer_id,
            ref=verified.ref,
            tree=verified.tree,
            signer=verified.signer,
        )
        result.append(
            (
                materialized_root,
                VerifiedKnowledgeSkillSource(
                    skills_root=materialized_root,
                    repository_root=repository_root,
                    relative_path=verified.relative_path,
                    repository=expected_repository,
                    layer=layer_id,
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
