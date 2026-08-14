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
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from cc.core.ecosystem import entitlement
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers
from cc.core.ecosystem.materialize import stable_directory_content_sha
from cc.core.ecosystem.mirror import synthesize_effective_layers
from cc.core.ecosystem.policy import (
    GitTreeSnapshot,
    VerifiedSignedRelease,
    read_git_tree_snapshot,
    verify_git_item_provenance,
    verify_git_tree_release,
)
from cc.core.ecosystem.project_locking import (
    UnsafeProjectPath,
    advisory_file_lock,
    atomic_json_write,
    ensure_private_directory,
    fsync_directory,
)
from cc.core.ecosystem.repository_scope import repository_identity
from cc.core.ecosystem.resolver import resolve_layers

KNOWLEDGE_SKILLS_SUBPATH = "03-ai-enabling/01-skills"


class KnowledgeSkillSourceError(ValueError):
    """A signed Knowledge source could not earn read authority."""


@dataclass(frozen=True)
class ProtectedKnowledgeLockProjection:
    """One update-authorized lock pin derived from signed Knowledge objects."""

    layer: str
    repository: str
    ref: str
    tree: str
    signer: str
    binding: str
    item_tree: str
    release_tree: str
    content_sha256: str
    dimension: str = "plugins"
    item: str = "codex-copilot"


@dataclass(frozen=True)
class AuthenticatedKnowledgeContribution:
    layer: str
    role: str
    unit: str | None
    repository: str
    ref: str
    tree: str
    signer: str
    contribution: str
    content_sha256: str
    content: str
    runtime: str
    adapter_version: str = "knowledge-contribution-v1"

    @property
    def is_authenticated(self) -> bool:
        return True

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "layer": self.layer,
            "role": self.role,
            "unit": self.unit,
            "repository": self.repository,
            "ref": self.ref,
            "tree": self.tree,
            "signer": self.signer,
            "contribution": self.contribution,
            "content_sha256": self.content_sha256,
            "runtime": self.runtime,
            "adapter_version": self.adapter_version,
            "authenticated": True,
        }
        if include_content:
            result["content"] = self.content
        return result


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
    role: str
    unit: str | None
    release: VerifiedSignedRelease
    snapshot: GitTreeSnapshot
    snapshot_cache_root: Path
    entitlement_binding: entitlement.EntitlementBinding | None = None

    def authenticated_contribution(
        self, relative_path: str, *, runtime: str
    ) -> AuthenticatedKnowledgeContribution:
        """Read exact UTF-8 contribution bytes under current entitlement."""
        current = revalidate_knowledge_skill_source(self)
        return current.authenticated_contribution_from_verified_batch(
            relative_path,
            runtime=runtime,
        )

    def authenticated_contribution_from_verified_batch(
        self, relative_path: str, *, runtime: str
    ) -> AuthenticatedKnowledgeContribution:
        """Read one contribution from a caller-scoped verified source batch.

        The source must come directly from the current operation's
        ``resolve_knowledge_skill_sources`` result. The signed release tree is
        immutable, and protected reads still hold and validate the bound
        entitlement ledger lease. This avoids recursively resolving the same
        ladder for every contribution while preserving fresh validation at the
        start of each new operation.
        """
        current = self
        contribution = Path(relative_path)
        if contribution.is_absolute() or ".." in contribution.parts:
            raise KnowledgeSkillSourceError(
                "The Knowledge contribution path is unsafe."
            )

        def read_current() -> bytes:
            try:
                return current.release.read_blob(contribution.as_posix())
            except ValueError as exc:
                raise KnowledgeSkillSourceError(
                    "The requested Knowledge contribution is absent from its signed release."
                ) from exc

        if current.entitlement_binding is None:
            raw = read_current()
        else:
            valid, raw = entitlement.run_under_binding_leases(
                [current.entitlement_binding], read_current
            )
            if not valid or raw is None:
                raise KnowledgeSkillSourceError(
                    "Knowledge authorization changed before use; retry the command."
                )
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeSkillSourceError(
                "The requested Knowledge contribution is not valid UTF-8."
            ) from exc
        return AuthenticatedKnowledgeContribution(
            layer=current.layer,
            role=current.role,
            unit=current.unit,
            repository=current.repository,
            ref=current.ref,
            tree=current.release.tree,
            signer=current.signer,
            contribution=contribution.as_posix(),
            content_sha256=hashlib.sha256(raw).hexdigest(),
            content=content,
            runtime=runtime,
        )

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

        def read_current() -> bytes:
            with advisory_file_lock(
                _snapshot_lock_path(self.snapshot_cache_root), blocking=True
            ):
                if not _snapshot_matches(self.skills_root, self.snapshot):
                    raise KnowledgeSkillSourceError(
                        "The authenticated Knowledge snapshot is unavailable."
                    )
                expected_mode = 0o500 if item.mode & 0o111 else 0o400
                content = _read_private_file(path, expected_mode=expected_mode)
                if content != item.content:
                    raise KnowledgeSkillSourceError(
                        "The authenticated Knowledge snapshot changed before use."
                    )
                return content

        if self.entitlement_binding is None:
            content = read_current()
        else:
            valid, content = entitlement.run_under_binding_leases(
                [self.entitlement_binding], read_current
            )
            if not valid or content is None:
                raise KnowledgeSkillSourceError(
                    "Knowledge authorization changed before use; retry the command."
                )
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeSkillSourceError(
                "The requested Knowledge skill is not valid UTF-8."
            ) from exc


SNAPSHOT_INDEX_SCHEMA_VERSION = "1.0"
_SNAPSHOT_INDEX_NAME = "index.json"
_SNAPSHOT_LOCK_NAME = ".lifecycle.lock"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _snapshot_lock_path(base: Path) -> Path:
    return base / _SNAPSHOT_LOCK_NAME


def _snapshot_cache_root(*, create: bool = True) -> Path:
    """Return a private, non-symlinked root for authenticated snapshots."""
    from cc.core import config

    raw = config.resolve_key("skills.cache_dir")
    cache_root = _nominal(raw or Path.home() / ".claude" / "cache" / "skills")
    snapshots = cache_root / "signed-knowledge-v1"
    if not create and not snapshots.exists() and not snapshots.is_symlink():
        return snapshots
    try:
        ensure_private_directory(cache_root, boundary=cache_root)
        ensure_private_directory(snapshots, boundary=cache_root)
    except (OSError, UnsafeProjectPath) as exc:
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot cache is unsafe."
        ) from exc
    return snapshots


def _empty_snapshot_index() -> dict[str, Any]:
    return {"schema_version": SNAPSHOT_INDEX_SCHEMA_VERSION, "entries": {}}


def _valid_snapshot_entry(key: str, value: object) -> bool:
    if not _DIGEST.fullmatch(key) or not isinstance(value, dict):
        return False
    if set(value) != {
        "binding",
        "protected",
        "layer",
        "repository",
        "login",
        "revision",
        "ref",
        "tree",
        "signer",
        "state_path",
        "target",
        "status",
    }:
        return False
    target = value.get("target")
    relative = Path(target) if isinstance(target, str) else Path("/")
    protected = value.get("protected")
    protected_target = (
        len(relative.parts) == 4
        and relative.parts[0] == "protected"
        and all(_DIGEST.fullmatch(part) for part in relative.parts[1:])
    )
    public_target = (
        len(relative.parts) == 2
        and relative.parts[0] == "public"
        and _DIGEST.fullmatch(relative.parts[1])
    )
    return bool(
        value.get("binding") == key
        and isinstance(protected, bool)
        and isinstance(value.get("layer"), str)
        and value.get("layer")
        and isinstance(value.get("repository"), str)
        and value.get("repository")
        and (value.get("login") is None or isinstance(value.get("login"), str))
        and (
            value.get("revision") is None
            or isinstance(value.get("revision"), int)
            and not isinstance(value.get("revision"), bool)
            and value.get("revision") >= 0
        )
        and all(
            isinstance(value.get(field), str) and value.get(field)
            for field in ("ref", "tree", "signer")
        )
        and (
            isinstance(value.get("state_path"), str) and value.get("state_path")
            if protected
            else value.get("state_path") is None
        )
        and value.get("status") in {"pending", "active"}
        and isinstance(target, str)
        and not relative.is_absolute()
        and ".." not in relative.parts
        and (protected_target if protected else public_target)
        and relative.parts[-1] == key
        and (
            value.get("revision") is not None
            if protected
            else value.get("revision") is None and value.get("login") is None
        )
    )


def _load_snapshot_index(base: Path) -> dict[str, Any]:
    path = base / _SNAPSHOT_INDEX_NAME
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return _empty_snapshot_index()
    except OSError as exc:
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot index is unavailable."
        ) from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot index is unsafe."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot index is invalid."
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema_version", "entries"}
        or raw.get("schema_version") != SNAPSHOT_INDEX_SCHEMA_VERSION
        or not isinstance(raw.get("entries"), dict)
        or not all(
            _valid_snapshot_entry(key, value) for key, value in raw["entries"].items()
        )
    ):
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot index is invalid."
        )
    return raw


def _write_snapshot_index(base: Path, index: dict[str, Any]) -> None:
    try:
        atomic_json_write(base / _SNAPSHOT_INDEX_NAME, index)
    except (OSError, UnsafeProjectPath) as exc:
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot index could not be updated."
        ) from exc


def _scope_digest(*values: object) -> str:
    encoded = json.dumps(
        ["signed-knowledge-scope-v1", *values],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_relative_target(
    binding: str, *, layer: str, repository: str, login: str | None, revision: int
) -> Path:
    scope = _scope_digest(layer, repository, login)
    generation = _scope_digest(revision)
    return Path("protected") / scope / generation / binding


def _recover_snapshot_state(base: Path, index: dict[str, Any]) -> None:
    """Recover interrupted prune/publication without broad deletion authority."""
    changed = False
    entries = index["entries"]
    for key, entry in list(entries.items()):
        target = base / entry["target"]
        if entry["status"] == "pending" or not target.exists() or target.is_symlink():
            if target.exists() or target.is_symlink():
                _remove_snapshot_target(base, Path(entry["target"]))
            entries.pop(key)
            changed = True
    for candidate in base.iterdir():
        if not re.fullmatch(r"\.reap-[0-9a-f]{32}", candidate.name):
            continue
        try:
            metadata = candidate.lstat()
        except OSError:
            continue
        if (
            stat.S_ISDIR(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and metadata.st_uid == os.geteuid()
        ):
            _make_stage_writable(candidate)
            shutil.rmtree(candidate, ignore_errors=True)
    if changed:
        _write_snapshot_index(base, index)


def _remove_snapshot_target(base: Path, relative: Path) -> bool:
    protected_target = (
        len(relative.parts) == 4
        and relative.parts[0] == "protected"
        and all(_DIGEST.fullmatch(part) for part in relative.parts[1:])
    )
    public_target = (
        len(relative.parts) == 2
        and relative.parts[0] == "public"
        and bool(_DIGEST.fullmatch(relative.parts[1]))
    )
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not (protected_target or public_target)
    ):
        raise KnowledgeSkillSourceError(
            "The private Knowledge snapshot index contains an unsafe target."
        )
    target = base / relative
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise KnowledgeSkillSourceError(
            "A protected Knowledge snapshot could not be inspected."
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        try:
            target.unlink()
            fsync_directory(target.parent)
            return True
        except OSError as exc:
            raise KnowledgeSkillSourceError(
                "A protected Knowledge snapshot link could not be revoked."
            ) from exc
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise KnowledgeSkillSourceError(
            "A protected Knowledge snapshot target is unsafe."
        )
    tombstone = base / f".reap-{secrets.token_hex(16)}"
    try:
        os.rename(target, tombstone)
        fsync_directory(target.parent)
        fsync_directory(base)
    except OSError as exc:
        raise KnowledgeSkillSourceError(
            "A protected Knowledge snapshot could not be revoked atomically."
        ) from exc
    _make_stage_writable(tombstone)
    shutil.rmtree(tombstone, ignore_errors=True)
    return True


def _revoke_protected_root(base: Path) -> None:
    """Invalidate every protected pathname if its private index is corrupt."""
    protected = base / "protected"
    try:
        metadata = protected.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise KnowledgeSkillSourceError(
            "The protected Knowledge snapshot root could not be inspected."
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        try:
            protected.unlink()
            fsync_directory(base)
            return
        except OSError as exc:
            raise KnowledgeSkillSourceError(
                "The protected Knowledge snapshot root could not be revoked."
            ) from exc
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise KnowledgeSkillSourceError(
            "The protected Knowledge snapshot root is unsafe."
        )
    tombstone = base / f".reap-{secrets.token_hex(16)}"
    try:
        os.rename(protected, tombstone)
        fsync_directory(base)
    except OSError as exc:
        raise KnowledgeSkillSourceError(
            "The protected Knowledge snapshot root could not be revoked."
        ) from exc
    _make_stage_writable(tombstone)
    shutil.rmtree(tombstone, ignore_errors=True)


def prune_protected_knowledge_snapshots(
    *,
    layer: str | None = None,
    repository: str | None = None,
    state_path: Path | str | None = None,
    keep_login: str | None = None,
    keep_revision: int | None = None,
    cache_root: Path | str | None = None,
    dry_run: bool = False,
) -> int:
    """Prune exact indexed protected snapshots; never scan arbitrary paths."""
    base = (
        _nominal(cache_root)
        if cache_root is not None
        else _snapshot_cache_root(create=False)
    )
    if not base.exists():
        return 0
    with advisory_file_lock(_snapshot_lock_path(base), blocking=True):
        try:
            index = _load_snapshot_index(base)
        except KnowledgeSkillSourceError:
            # The index grants precise per-entry cleanup authority.  If it is
            # corrupt, invalidate only the dedicated protected root so a stale
            # disclosed path cannot survive by corrupting cleanup metadata.
            if not dry_run:
                _revoke_protected_root(base)
            raise
        _recover_snapshot_state(base, index)
        selected: list[tuple[str, dict[str, Any]]] = []
        normalized_state = (
            str(Path(state_path).expanduser()) if state_path is not None else None
        )
        for key, entry in index["entries"].items():
            if not entry["protected"]:
                continue
            if layer is not None and entry["layer"] != layer:
                continue
            if repository is not None and entry["repository"] != repository:
                continue
            if normalized_state is not None and entry["state_path"] != normalized_state:
                continue
            if (
                keep_revision is not None
                and entry["revision"] == keep_revision
                and entry["login"] == keep_login
            ):
                continue
            selected.append((key, entry))
        if dry_run:
            return len(selected)
        for key, entry in selected:
            _remove_snapshot_target(base, Path(entry["target"]))
            index["entries"].pop(key, None)
        if selected:
            _write_snapshot_index(base, index)
        return len(selected)


def prune_all_knowledge_snapshots(
    *, cache_root: Path | str, dry_run: bool = False
) -> int:
    """Hard-deprovision every exact framework-indexed Knowledge snapshot."""
    base = _nominal(cache_root)
    if not base.exists():
        return 0
    with advisory_file_lock(_snapshot_lock_path(base), blocking=True):
        index = _load_snapshot_index(base)
        _recover_snapshot_state(base, index)
        entries = list(index["entries"].items())
        if dry_run:
            return len(entries)
        for key, entry in entries:
            _remove_snapshot_target(base, Path(entry["target"]))
            index["entries"].pop(key, None)
        if entries:
            _write_snapshot_index(base, index)
        return len(entries)


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
            # The publication root remains 0700 so macOS can atomically
            # rename it during revocation.  Every descendant and file stays
            # read/execute-only and every read verifies the exact tree.
            or stat.S_IMODE(root_metadata.st_mode) != 0o700
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
    entitlement_binding: entitlement.EntitlementBinding | None,
    cache_root: Path | None = None,
) -> Path:
    """Atomically publish exact Git-object bytes under a private digest path."""
    base = cache_root if cache_root is not None else _snapshot_cache_root()
    content_binding = _snapshot_binding(
        repository=repository,
        layer=layer,
        ref=ref,
        tree=tree,
        signer=signer,
        snapshot=snapshot,
    )
    if entitlement_binding is None:
        binding = content_binding
        relative_target = Path("public") / binding
        index_entry = {
            "binding": binding,
            "protected": False,
            "layer": layer,
            "repository": repository,
            "login": None,
            "revision": None,
            "ref": ref,
            "tree": tree,
            "signer": signer,
            "state_path": None,
            "target": relative_target.as_posix(),
            "status": "pending",
        }
    else:
        # A protected cache identity is both content-addressed and authority-
        # generation-addressed.  Reauthorization may select the same Git tree,
        # but it must never revive the pathname disclosed by an older grant.
        binding = _scope_digest(
            content_binding,
            layer,
            repository,
            entitlement_binding.login,
            entitlement_binding.revision,
        )
        relative_target = _snapshot_relative_target(
            binding,
            layer=layer,
            repository=repository,
            login=entitlement_binding.login,
            revision=entitlement_binding.revision,
        )
        index_entry = {
            "binding": binding,
            "protected": True,
            "layer": layer,
            "repository": repository,
            "login": entitlement_binding.login,
            "revision": entitlement_binding.revision,
            "ref": ref,
            "tree": tree,
            "signer": signer,
            "state_path": entitlement_binding.state_path,
            "target": relative_target.as_posix(),
            "status": "pending",
        }
    target = base / relative_target
    ensure_private_directory(target.parent, boundary=base)

    index = _load_snapshot_index(base)
    _recover_snapshot_state(base, index)
    recorded = index["entries"].get(binding)
    if recorded is not None:
        if recorded != (index_entry | {"status": "active"}):
            raise KnowledgeSkillSourceError(
                "A Knowledge snapshot binding conflicts with its private index."
            )
        if _snapshot_matches(target, snapshot):
            return target
        raise KnowledgeSkillSourceError(
            "A cached Knowledge snapshot failed integrity verification."
        )
    index["entries"][binding] = index_entry
    _write_snapshot_index(base, index)

    if target.exists() or target.is_symlink():
        if _snapshot_matches(target, snapshot):
            return target
        raise KnowledgeSkillSourceError(
            "A cached Knowledge snapshot failed integrity verification."
        )

    stage = Path(tempfile.mkdtemp(prefix=f".{binding}.", dir=target.parent))
    try:
        stage.chmod(0o700)
        for item in snapshot.files:
            destination = stage / item.path
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(
                destination,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
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
        stage.chmod(0o700)

        try:
            os.rename(stage, target)
        except OSError:
            if not _snapshot_matches(target, snapshot):
                raise
        fsync_directory(target.parent)
        fsync_directory(base)
        if not _snapshot_matches(target, snapshot):
            raise KnowledgeSkillSourceError(
                "The authenticated Knowledge snapshot changed during publication."
            )
        index["entries"][binding]["status"] = "active"
        _write_snapshot_index(base, index)
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
    return (
        repository_identity(result.stdout.strip()) if result.returncode == 0 else None
    )


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


def resolve_protected_knowledge_lock_projections(
    layers: Iterable[dict[str, Any]],
    bindings: Iterable[entitlement.EntitlementBinding],
    *,
    cache_root: Path | str | None = None,
) -> tuple[ProtectedKnowledgeLockProjection, ...]:
    """Verify protected receipts and derive canonical Knowledge plugin pins.

    This function is deliberately called only by the mutating update
    transaction.  It grants no lock-write authority and ordinary Knowledge
    read resolution never invokes it.
    """
    layer_list = list(layers)
    if not layer_list:
        return ()
    binding_by_layer = {
        binding.layer: entitlement.EntitlementBinding.from_value(binding)
        for binding in bindings
    }
    base = (
        _nominal(cache_root)
        if cache_root is not None
        else _snapshot_cache_root(create=False)
    )
    contributions = discover_contributions(layer_list, dimensions=("plugins",))
    resolved = resolve_layers(layer_list, contributions, lockfile={})
    protected_winners = {
        str(item["winning_layer"])
        for item in resolved
        if item.get("dimension") == "plugins" and item.get("item") == "codex-copilot"
    }
    protected_layers = [
        layer
        for layer in layer_list
        if layer.get("product") == "knowledge"
        and entitlement.is_protected_layer(layer)
        and str(layer.get("id")) in protected_winners
    ]
    if not protected_layers:
        return ()
    try:
        metadata = base.lstat()
    except OSError as exc:
        raise KnowledgeSkillSourceError(
            "The protected Knowledge snapshot receipt is unavailable."
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise KnowledgeSkillSourceError(
            "The protected Knowledge snapshot receipt root is unsafe."
        )

    projections: list[ProtectedKnowledgeLockProjection] = []
    with advisory_file_lock(_snapshot_lock_path(base), blocking=True):
        index = _load_snapshot_index(base)
        _recover_snapshot_state(base, index)
        for layer in sorted(protected_layers, key=lambda value: value["rank"]):
            layer_id = str(layer.get("id") or "")
            binding = binding_by_layer.get(layer_id)
            source = layer.get("source") or {}
            source_root = source.get("path")
            ref = source.get("ref")
            repository = repository_identity(source.get("repo"))
            signers = _signed_policy(layer)
            if (
                binding is None
                or not binding.eligible
                or binding.state not in {"entitled", "offline-cached"}
                or binding.layer != layer_id
                or repository_identity(binding.repo) != repository
                or not isinstance(source_root, str)
                or not isinstance(ref, str)
                or not ref
                or repository is None
                or signers is None
            ):
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} lacks an active bound receipt."
                )
            repository_root = _nominal(source_root)
            if _origin(repository_root) != repository:
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has the wrong repository origin."
                )

            skills_verified = verify_git_item_provenance(
                repository_root, KNOWLEDGE_SKILLS_SUBPATH, signers, ref=ref
            )
            if skills_verified is None:
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has no verified skills receipt."
                )
            if _has_ignored_additions(repository_root, KNOWLEDGE_SKILLS_SUBPATH):
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has ignored skill additions."
                )
            skills_snapshot = read_git_tree_snapshot(
                repository_root, skills_verified.tree
            )
            if skills_snapshot is None:
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has an unsafe skill tree."
                )
            content_binding = _snapshot_binding(
                repository=repository,
                layer=layer_id,
                ref=skills_verified.ref,
                tree=skills_verified.tree,
                signer=skills_verified.signer,
                snapshot=skills_snapshot,
            )
            protected_binding = _scope_digest(
                content_binding,
                layer_id,
                repository,
                binding.login,
                binding.revision,
            )
            expected_target = _snapshot_relative_target(
                protected_binding,
                layer=layer_id,
                repository=repository,
                login=binding.login,
                revision=binding.revision,
            ).as_posix()
            expected_entry = {
                "binding": protected_binding,
                "protected": True,
                "layer": layer_id,
                "repository": repository,
                "login": binding.login,
                "revision": binding.revision,
                "ref": skills_verified.ref,
                "tree": skills_verified.tree,
                "signer": skills_verified.signer,
                "state_path": binding.state_path,
                "target": expected_target,
                "status": "active",
            }
            matching_receipts: list[tuple[str, dict[str, Any]]] = []
            for key, entry in index["entries"].items():
                revision = entry.get("revision")
                if (
                    entry.get("protected") is not True
                    or entry.get("status") != "active"
                    or entry.get("layer") != layer_id
                    or entry.get("repository") != repository
                    or entry.get("login") != binding.login
                    or not isinstance(revision, int)
                    or revision > binding.revision
                    or entry.get("ref") != skills_verified.ref
                    or entry.get("tree") != skills_verified.tree
                    or entry.get("signer") != skills_verified.signer
                    or entry.get("state_path") != binding.state_path
                ):
                    continue
                candidate_binding = _scope_digest(
                    content_binding,
                    layer_id,
                    repository,
                    binding.login,
                    revision,
                )
                candidate_target = _snapshot_relative_target(
                    candidate_binding,
                    layer=layer_id,
                    repository=repository,
                    login=binding.login,
                    revision=revision,
                ).as_posix()
                if (
                    key == candidate_binding
                    and entry.get("binding") == candidate_binding
                    and entry.get("target") == candidate_target
                ):
                    matching_receipts.append((key, entry))
            if not matching_receipts:
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has no matching active receipt."
                )
            # Preflight every pathname before changing any receipt state.  A
            # tampered older generation must not be removed and silently
            # replaced by clean Git bytes: that would erase the evidence that
            # blocked this transaction.  Validate the whole matching set first
            # so any mismatch preserves both the index and every target.
            if any(
                not _snapshot_matches(base / entry["target"], skills_snapshot)
                for _key, entry in matching_receipts
            ):
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} receipt bytes do not match."
                )
            # A fresh update observation advances the entitlement generation.
            # Never reuse the older disclosed pathname: revoke every matching
            # prior-generation target, then publish exact Git-object bytes at
            # the current binding.  A current-generation target is instead
            # integrity-checked by `_materialize_snapshot` below.
            prior_receipts = [
                (key, entry)
                for key, entry in matching_receipts
                if entry["revision"] < binding.revision
            ]
            for key, entry in prior_receipts:
                _remove_snapshot_target(base, Path(entry["target"]))
                index["entries"].pop(key, None)
            if prior_receipts:
                _write_snapshot_index(base, index)
            _materialize_snapshot(
                skills_snapshot,
                repository=repository,
                layer=layer_id,
                ref=skills_verified.ref,
                tree=skills_verified.tree,
                signer=skills_verified.signer,
                entitlement_binding=binding,
                cache_root=base,
            )
            refreshed_index = _load_snapshot_index(base)
            if refreshed_index["entries"].get(protected_binding) != expected_entry:
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} receipt rollover failed."
                )

            plugin_verified = verify_git_item_provenance(
                repository_root, "plugins/codex-copilot", signers, ref=ref
            )
            if plugin_verified is None:
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has no verified plugin tree."
                )
            if _has_ignored_additions(repository_root, plugin_verified.relative_path):
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has ignored plugin additions."
                )
            if any(
                getattr(plugin_verified.release, field)
                != getattr(skills_verified.release, field)
                for field in (
                    "ref",
                    "tag",
                    "commit",
                    "tree",
                    "signer",
                    "repository_root",
                )
            ):
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} receipts do not share one release."
                )
            plugin_snapshot = read_git_tree_snapshot(
                repository_root, plugin_verified.tree
            )
            if plugin_snapshot is None:
                raise KnowledgeSkillSourceError(
                    f"Protected Knowledge layer {layer_id!r} has an unsafe plugin tree."
                )
            projections.append(
                ProtectedKnowledgeLockProjection(
                    layer=layer_id,
                    repository=repository,
                    ref=ref,
                    tree=skills_verified.tree,
                    signer=skills_verified.signer,
                    binding=protected_binding,
                    item_tree=plugin_verified.tree,
                    release_tree=plugin_verified.release.tree,
                    content_sha256=stable_directory_content_sha(
                        (item.path, item.content) for item in plugin_snapshot.files
                    ),
                )
            )
    return tuple(projections)


def inspect_protected_knowledge_lock_projection(
    layer: dict[str, Any],
    *,
    cache_root: Path | str | None = None,
) -> ProtectedKnowledgeLockProjection | None:
    """Read and re-prove one protected Knowledge plugin lock projection.

    Unlike ``resolve_protected_knowledge_lock_projections()``, this inspector
    never rolls a receipt, writes the index, creates a cache directory, or
    consults the network.  It accepts evidence only when one active private
    receipt still matches the signed skills tree byte-for-byte and the plugin
    projection is derived from the same verified immutable release.
    """
    if layer.get("product") != "knowledge" or not entitlement.is_protected_layer(
        layer
    ):
        return None
    layer_id = str(layer.get("id") or "")
    source = layer.get("source") or {}
    source_root = source.get("path")
    ref = source.get("ref")
    repository = repository_identity(source.get("repo"))
    try:
        signers = _signed_policy(layer)
    except KnowledgeSkillSourceError:
        return None
    if (
        not layer_id
        or not isinstance(source_root, str)
        or not isinstance(ref, str)
        or not ref
        or repository is None
        or signers is None
    ):
        return None
    repository_root = _nominal(source_root)
    if _origin(repository_root) != repository:
        return None

    if cache_root is not None:
        base = _nominal(cache_root)
    else:
        from cc.core import config

        configured = config.resolve_key("skills.cache_dir")
        base = _nominal(
            configured or Path.home() / ".claude" / "cache" / "skills"
        ) / "signed-knowledge-v1"
    try:
        metadata = base.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            return None
        index = _load_snapshot_index(base)
    except (OSError, KnowledgeSkillSourceError):
        return None

    skills_verified = verify_git_tree_release(
        repository_root, KNOWLEDGE_SKILLS_SUBPATH, signers, ref=ref
    )
    if skills_verified is None:
        return None
    skills_snapshot = read_git_tree_snapshot(repository_root, skills_verified.tree)
    if skills_snapshot is None:
        return None
    actual_login = entitlement.current_login()
    if not actual_login:
        return None
    expected_state_path = str(entitlement.entitlement_state_path().expanduser())
    content_binding = _snapshot_binding(
        repository=repository,
        layer=layer_id,
        ref=skills_verified.ref,
        tree=skills_verified.tree,
        signer=skills_verified.signer,
        snapshot=skills_snapshot,
    )
    receipts: list[dict[str, Any]] = []
    for entry in index["entries"].values():
        revision = entry.get("revision")
        expected_binding = (
            _scope_digest(
                content_binding,
                layer_id,
                repository,
                actual_login,
                revision,
            )
            if isinstance(revision, int) and not isinstance(revision, bool)
            else None
        )
        expected_target = (
            _snapshot_relative_target(
                expected_binding,
                layer=layer_id,
                repository=repository,
                login=actual_login,
                revision=revision,
            ).as_posix()
            if expected_binding is not None
            else None
        )
        if (
            entry.get("protected") is not True
            or entry.get("status") != "active"
            or entry.get("layer") != layer_id
            or entry.get("repository") != repository
            or entry.get("login") != actual_login
            or entry.get("binding") != expected_binding
            or entry.get("target") != expected_target
            or entry.get("state_path") != expected_state_path
            or entry.get("ref") != skills_verified.ref
            or entry.get("tree") != skills_verified.tree
            or entry.get("signer") != skills_verified.signer
            or not _snapshot_matches(base / entry["target"], skills_snapshot)
        ):
            continue
        _eligible, decisions = entitlement.filter_eligible_layers(
            [layer],
            state_path=entry["state_path"],
            login=actual_login,
        )
        decision = decisions[0]
        if not decision.eligible or decision.revision != entry.get("revision"):
            continue
        receipts.append(entry)
    if len(receipts) != 1:
        return None
    receipt = receipts[0]

    plugin_verified = verify_git_tree_release(
        repository_root, "plugins/codex-copilot", signers, ref=ref
    )
    if plugin_verified is None or any(
        getattr(plugin_verified.release, field)
        != getattr(skills_verified.release, field)
        for field in (
            "ref",
            "tag",
            "commit",
            "tree",
            "signer",
            "repository_root",
        )
    ):
        return None
    plugin_snapshot = read_git_tree_snapshot(repository_root, plugin_verified.tree)
    if plugin_snapshot is None:
        return None
    return ProtectedKnowledgeLockProjection(
        layer=layer_id,
        repository=repository,
        ref=skills_verified.ref,
        tree=skills_verified.tree,
        signer=skills_verified.signer,
        binding=str(receipt["binding"]),
        item_tree=plugin_verified.tree,
        release_tree=plugin_verified.release.tree,
        content_sha256=stable_directory_content_sha(
            (item.path, item.content) for item in plugin_snapshot.files
        ),
    )


def _effective_knowledge_layers(
    knowledge: list[dict[str, Any]],
    mirror_root_base: Path | str,
    *,
    state_path: Path,
    login: str | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[entitlement.EntitlementDecision],
]:
    try:
        if not knowledge:
            return [], [], []
        eligible, decisions = entitlement.filter_eligible_layers(
            knowledge, state_path=state_path, login=login
        )
        effective = synthesize_effective_layers(
            knowledge, mirror_root_base=mirror_root_base
        )
    except (ManifestError, OSError, TypeError, ValueError) as exc:
        raise KnowledgeSkillSourceError(
            "The configured Knowledge layer manifest is invalid."
        ) from exc
    return effective, eligible, decisions


def knowledge_repository_requires_authenticated_source(
    repository_root: Path | str,
    *,
    manifest_source: Any = None,
    mirror_root_base: Path | str | None = None,
) -> bool:
    """Classify whether a configured repository may use mutable checkout bytes.

    Repositories absent from the layer manifest retain the explicit legacy
    unsigned compatibility path.  A matching protected layer or a layer with
    signer policy must instead produce a currently authorized, verified
    source; callers must not reinterpret its absence as unsigned authority.
    """
    from cc.core import config

    configured_manifest = (
        config.resolve_key("layers.manifest")
        if manifest_source is None
        else manifest_source
    )
    if not configured_manifest:
        return False
    try:
        layers = validate_layers(load_layers(configured_manifest))
        declared = [layer for layer in layers if layer.get("product") == "knowledge"]
        mirrors = (
            config.resolve_key("paths.mirrors_root")
            if mirror_root_base is None
            else mirror_root_base
        )
        effective = synthesize_effective_layers(
            declared,
            mirror_root_base=mirrors or Path.home() / ".copilot" / "mirrors",
        )
    except (ManifestError, OSError, TypeError, ValueError) as exc:
        raise KnowledgeSkillSourceError(
            "The configured Knowledge layer manifest is invalid."
        ) from exc

    nominal = _nominal(repository_root)
    matches = [
        layer
        for layer in effective
        if isinstance((layer.get("source") or {}).get("path"), str)
        and _nominal((layer.get("source") or {})["path"]) == nominal
    ]
    if len(matches) > 1:
        raise KnowledgeSkillSourceError(
            "A configured Knowledge repository matches more than one layer."
        )
    if not matches:
        return False
    layer = matches[0]
    return entitlement.is_protected_layer(layer) or _signed_policy(layer) is not None


def resolve_knowledge_skill_sources(
    *,
    repositories: Iterable[str] | None = None,
    manifest_source: Any = None,
    mirror_root_base: Path | str | None = None,
    entitlement_state_path_value: Path | str | None = None,
    entitlement_login: str | None = None,
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
    try:
        layers = validate_layers(load_layers(configured_manifest))
        declared_knowledge = [
            layer for layer in layers if layer.get("product") == "knowledge"
        ]
    except (ManifestError, OSError, TypeError, ValueError) as exc:
        raise KnowledgeSkillSourceError(
            "The configured Knowledge layer manifest is invalid."
        ) from exc
    mirrors = (
        config.resolve_key("paths.mirrors_root")
        if mirror_root_base is None
        else mirror_root_base
    )
    protected_declared = [
        layer for layer in declared_knowledge if entitlement.is_protected_layer(layer)
    ]
    if protected_declared:
        state_path = (
            Path(entitlement_state_path_value).expanduser()
            if entitlement_state_path_value is not None
            else entitlement.entitlement_state_path()
        )
        login = (
            entitlement_login
            if entitlement_login is not None
            else entitlement.current_login()
        )
    else:
        # Public/anonymous Knowledge must not require or even inspect account
        # state.  This sentinel is never consumed when no layer is protected.
        state_path = Path("/")
        login = None
    effective, eligible, decisions = _effective_knowledge_layers(
        declared_knowledge,
        mirrors or Path.home() / ".copilot" / "mirrors",
        state_path=state_path,
        login=login,
    )
    eligible_ids = {str(layer.get("id")) for layer in eligible}
    decision_by_id = {decision.layer: decision for decision in decisions}
    declared_by_id = {str(layer.get("id")): layer for layer in declared_knowledge}
    bindings = (
        entitlement.bind_layer_decisions(
            list(declared_by_id.values()),
            decisions,
            state_path=state_path,
            login=login,
        )
        if protected_declared
        else ()
    )
    binding_by_id = {binding.layer: binding for binding in bindings}

    def resolve_bound() -> list[tuple[Path, VerifiedKnowledgeSkillSource | None]]:
        result: list[tuple[Path, VerifiedKnowledgeSkillSource | None]] = []
        protected_ids = {
            layer_id
            for layer_id, layer in declared_by_id.items()
            if entitlement.is_protected_layer(layer)
        }
        base = _snapshot_cache_root()
        for layer_id in protected_ids:
            layer = declared_by_id[layer_id]
            source = layer.get("source") or {}
            repository = repository_identity(source.get("repo"))
            decision = decision_by_id.get(layer_id)
            if repository is None or decision is None:
                continue
            prune_protected_knowledge_snapshots(
                layer=layer_id,
                repository=repository,
                state_path=state_path,
                keep_login=login if decision.eligible else None,
                keep_revision=decision.revision if decision.eligible else None,
                cache_root=base,
            )

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
            layer_id = str(layer.get("id"))
            if layer_id not in eligible_ids:
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
            entitlement_binding = binding_by_id.get(layer_id)
            with advisory_file_lock(_snapshot_lock_path(base), blocking=True):
                materialized_root = _materialize_snapshot(
                    snapshot,
                    repository=expected_repository,
                    layer=layer_id,
                    ref=verified.ref,
                    tree=verified.tree,
                    signer=verified.signer,
                    entitlement_binding=entitlement_binding,
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
                        role=str(layer.get("role") or ""),
                        unit=(
                            str(layer.get("unit"))
                            if layer.get("unit") is not None
                            else None
                        ),
                        release=verified.release,
                        snapshot=snapshot,
                        snapshot_cache_root=base,
                        entitlement_binding=entitlement_binding,
                    ),
                )
            )
        return result

    valid, result = entitlement.run_under_binding_leases(bindings, resolve_bound)
    if not valid or result is None:
        raise KnowledgeSkillSourceError(
            "Knowledge authorization changed during resolution; retry the command."
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
        for field in (
            "skills_root",
            "repository",
            "layer",
            "ref",
            "tree",
            "signer",
            "role",
            "unit",
            "release",
            "snapshot_cache_root",
            "entitlement_binding",
        )
    ):
        raise KnowledgeSkillSourceError(
            "The Knowledge source changed after it was selected; retry the command."
        )
    return source


__all__ = [
    "AuthenticatedKnowledgeContribution",
    "KNOWLEDGE_SKILLS_SUBPATH",
    "KnowledgeSkillSourceError",
    "ProtectedKnowledgeLockProjection",
    "VerifiedKnowledgeSkillSource",
    "knowledge_repository_requires_authenticated_source",
    "prune_all_knowledge_snapshots",
    "prune_protected_knowledge_snapshots",
    "resolve_knowledge_skill_sources",
    "resolve_protected_knowledge_lock_projections",
    "revalidate_knowledge_skill_source",
]
