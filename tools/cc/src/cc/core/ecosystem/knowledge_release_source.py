"""Authenticate an active release snapshot with the existing signed Git authority.

The release receipt selects a version; it never grants read authority by itself.
Its repository binding, signed object identity and frozen item bytes must agree.
Ordinary authoring inputs continue to use working-tree provenance separately.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Sequence

from cc.core.ecosystem.policy import (
    GitItemProvenance,
    GitTreeSnapshot,
    read_git_tree_snapshot,
    verify_git_tree_release,
)
from cc.core.ecosystem.repository_scope import repository_identity
from cc.core.release.engine import layout, schema


class KnowledgeReleaseSourceError(ValueError):
    """A matching current release failed to authenticate its Knowledge item."""


def _nominal(path: Path | str) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _component_name(layer: dict[str, Any]) -> str | None:
    role = layer.get("role")
    if role in (layout.TIER_FOUNDATION, layout.TIER_ORGANIZATION):
        return f"knowledge/{role}"
    if role == "department" and layer.get("unit") == "accounting":
        return f"knowledge/{layout.TIER_DEPARTMENT_ACCOUNTING}"
    return None


def _frozen_directory(path: Path) -> bool:
    metadata = path.lstat()
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and stat.S_IMODE(metadata.st_mode) == 0o555
    )


def _read_frozen_file(path: Path, mode: int) -> bytes | None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != mode
        ):
            return None
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            return None
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _snapshot_matches(root: Path, snapshot: GitTreeSnapshot) -> bool:
    expected = {item.path: item for item in snapshot.files}
    directories = {
        str(parent)
        for item in snapshot.files
        for parent in Path(item.path).parents
        if str(parent) != "."
    }
    observed_files: set[str] = set()
    observed_directories: set[str] = set()
    if not _frozen_directory(root):
        return False

    def fail_walk(error: OSError) -> None:
        raise error

    for current, children, files in os.walk(root, followlinks=False, onerror=fail_walk):
        parent = Path(current)
        for name in children:
            child = parent / name
            if not _frozen_directory(child):
                return False
            observed_directories.add(child.relative_to(root).as_posix())
        for name in files:
            child = parent / name
            relative = child.relative_to(root).as_posix()
            item = expected.get(relative)
            if (
                item is None
                or _read_frozen_file(child, item.mode & ~0o222) != item.content
            ):
                return False
            observed_files.add(relative)
    return observed_files == set(expected) and observed_directories == directories


def resolve_current_knowledge_release(
    repository: Path,
    layer: dict[str, Any],
    allowed_signers: Sequence[str],
    relative_path: str,
) -> tuple[GitItemProvenance, GitTreeSnapshot] | None:
    """Return authenticated active object bytes for a matching central tier.

    ``None`` means this repository is not the active central component; it does
    not grant unsigned compatibility. The caller retains its strict authoring
    verifier. Once the component's source matches, any mismatch fails closed.
    """
    name = _component_name(layer)
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise KnowledgeReleaseSourceError("The active Knowledge item path is unsafe.")
    current = layout.current_path()
    if name is None or not (current.exists() or current.is_symlink()):
        return None
    try:
        root = current.resolve(strict=True)
        manifest = schema.load(root)
        component = manifest.component(name)
        if _nominal(component.source) != repository:
            return None
        if (
            not current.is_symlink()
            or root.parent != _nominal(layout.releases_dir())
            or component.kind != layout.KIND_SIGNED
            or component.path != name
            or component.tier != name.split("/", 1)[1]
            or not _frozen_directory(root)
        ):
            raise KnowledgeReleaseSourceError(
                "The active Knowledge release path is unsafe."
            )
        receipt = _read_frozen_file(root / layout.MANIFEST_NAME, 0o444)
        if receipt is None or schema.validate(json.loads(receipt)) != manifest:
            raise KnowledgeReleaseSourceError(
                "The active Knowledge release receipt is unsafe."
            )
        item_root = root
        for part in (Path(component.path) / relative).parts:
            if part in (".", ".."):
                raise KnowledgeReleaseSourceError(
                    "The active Knowledge item path is unsafe."
                )
            item_root /= part
            if not _frozen_directory(item_root):
                raise KnowledgeReleaseSourceError(
                    "The active Knowledge item is not immutable."
                )
        expected_repository = repository_identity(
            (layer.get("source") or {}).get("repo")
        )
        origin = subprocess.run(
            ["git", "-C", str(repository), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if (
            expected_repository is None
            or repository_identity(origin.stdout.strip()) != expected_repository
        ):
            raise KnowledgeReleaseSourceError(
                "The active Knowledge source repository does not match."
            )
        verified = verify_git_tree_release(
            repository, relative_path, allowed_signers, ref=component.ref
        )
        if (
            verified is None
            or verified.release.commit != component.commit
            or verified.signer != component.signer
        ):
            raise KnowledgeReleaseSourceError(
                "The active Knowledge release lacks matching signed provenance."
            )
        snapshot = read_git_tree_snapshot(verified.repository_root, verified.tree)
        if snapshot is None or not _snapshot_matches(item_root, snapshot):
            raise KnowledgeReleaseSourceError(
                "The active Knowledge skills do not match their signed release."
            )
        if (
            current.resolve(strict=True) != root
            or _read_frozen_file(root / layout.MANIFEST_NAME, 0o444) != receipt
        ):
            raise KnowledgeReleaseSourceError(
                "The active Knowledge release changed during resolution; retry."
            )
        return verified, snapshot
    except KnowledgeReleaseSourceError:
        raise
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise KnowledgeReleaseSourceError(
            "The active Knowledge release could not be authenticated."
        ) from exc
