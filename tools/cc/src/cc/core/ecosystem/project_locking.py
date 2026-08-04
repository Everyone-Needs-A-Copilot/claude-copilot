"""Canonical project identity, containment, and cross-process locking.

Reconciliation callers must enter :func:`project_lock` before fresh inspection
or mutation and keep the returned :class:`AnchoredProject` for every target
operation.  Targets are POSIX-style relative paths.  Parent components are
opened relative to an already-open project-root descriptor with
``O_DIRECTORY|O_NOFOLLOW``; no mutation helper follows a project symlink.

The lock lives in private machine state rather than the Git working tree, so
acquiring it never makes a clean project dirty.  Its key is derived from the
root and Git directory device/inode pairs, causing aliases of the same checkout
to contend while a plan remains additionally bound to the canonical path.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Optional

from cc.core.config_paths import machine_diagnostics_root
from cc.core.write_guard import assert_write_is_isolated

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_HEAD_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ProjectLockError(RuntimeError):
    """Base class for identity, containment, and locking failures."""


class ProjectLockContention(ProjectLockError):
    """Another participating process already owns this project lock."""


class ProjectIdentityMismatch(ProjectLockError):
    """The selected project is no longer the checkout bound to the plan."""


class UnsafeProjectPath(ProjectLockError):
    """A target is absolute, traversing, symlinked, or otherwise unsupported."""


@dataclass(frozen=True)
class ProjectIdentity:
    path: str
    device: int
    inode: int
    owner_uid: int
    git_dir: str
    git_device: int
    git_inode: int
    git_owner_uid: int
    head_oid: Optional[str]
    head_ref: Optional[str]
    fingerprint: str
    lock_key: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_value(
        cls, value: "ProjectIdentity | Mapping[str, Any]"
    ) -> "ProjectIdentity":
        if isinstance(value, cls):
            return value
        try:
            return cls(
                path=str(value["path"]),
                device=int(value["device"]),
                inode=int(value["inode"]),
                owner_uid=int(value["owner_uid"]),
                git_dir=str(value["git_dir"]),
                git_device=int(value["git_device"]),
                git_inode=int(value["git_inode"]),
                git_owner_uid=int(value["git_owner_uid"]),
                head_oid=(
                    str(value["head_oid"])
                    if value.get("head_oid") is not None
                    else None
                ),
                head_ref=(
                    str(value["head_ref"])
                    if value.get("head_ref") is not None
                    else None
                ),
                fingerprint=str(value["fingerprint"]),
                lock_key=str(value["lock_key"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectIdentityMismatch(
                "The stored project identity is invalid."
            ) from exc


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def fingerprint_missing() -> str:
    return _sha256(["missing"])


def fingerprint_file_payload(payload: bytes, *, mode: int = 0o644) -> str:
    return _sha256(["file", mode, hashlib.sha256(payload).hexdigest()])


def fingerprint_symlink(link_value: str) -> str:
    return _sha256(["symlink", link_value])


def _source_tree_manifest(source: Path, prefix: str = "") -> list[list[Any]]:
    rows: list[list[Any]] = []
    for child in sorted(source.iterdir(), key=lambda candidate: candidate.name):
        child_stat = child.lstat()
        item = f"{prefix}/{child.name}" if prefix else child.name
        mode = stat.S_IMODE(child_stat.st_mode)
        if stat.S_ISREG(child_stat.st_mode):
            rows.append(
                [item, "file", mode, hashlib.sha256(child.read_bytes()).hexdigest()]
            )
        elif stat.S_ISDIR(child_stat.st_mode):
            rows.append([item, "directory", mode])
            rows.extend(_source_tree_manifest(child, item))
        elif stat.S_ISLNK(child_stat.st_mode):
            raise UnsafeProjectPath("A transaction tree source contains a symlink.")
        else:
            raise UnsafeProjectPath("A transaction source contains a special file.")
    return rows


def fingerprint_tree_source(source: Path | str, *, mode: int = 0o755) -> str:
    candidate = Path(source).expanduser()
    if candidate.is_symlink() or not candidate.is_dir():
        raise UnsafeProjectPath("A transaction tree source is unavailable.")
    return _sha256(["directory", mode, _source_tree_manifest(candidate)])


def _default_state_root() -> Path:
    return machine_diagnostics_root() / "reconciliation"


def _effective_uid() -> int:
    return os.geteuid()


def ensure_private_directory(path: Path, *, boundary: Optional[Path] = None) -> Path:
    """Create a current-user-owned mode-0700 path through a no-follow chain."""
    expanded_target = path.expanduser()
    expanded_base = (boundary or expanded_target).expanduser()
    if not expanded_target.is_absolute() or not expanded_base.is_absolute():
        raise UnsafeProjectPath("Private state paths must be absolute.")
    target = Path(os.path.normpath(os.fspath(expanded_target)))
    base = Path(os.path.normpath(os.fspath(expanded_base)))
    if not target.is_absolute() or not base.is_absolute():
        raise UnsafeProjectPath("Private state paths must be absolute.")
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise UnsafeProjectPath("Private state escaped its owned boundary.") from exc
    if base == Path("/"):
        raise UnsafeProjectPath("The private state boundary is too broad.")

    boundary_depth = len(base.parts) - 1
    descriptor = os.open("/", os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    try:
        for depth, part in enumerate(target.parts[1:], start=1):
            created = False
            try:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                    created = True
                    next_descriptor = os.open(
                        part,
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except OSError as exc:
                    raise UnsafeProjectPath(
                        "A private state directory could not be created safely."
                    ) from exc
            except OSError as exc:
                raise UnsafeProjectPath(
                    "A private state ancestor is symlinked or unavailable."
                ) from exc
            try:
                metadata = os.fstat(next_descriptor)
                effective_uid = _effective_uid()
                trusted_owners = {0, effective_uid}
                if depth < boundary_depth and metadata.st_uid not in trusted_owners:
                    raise UnsafeProjectPath(
                        "A private state ancestor has an untrusted owner."
                    )
                if (created or depth >= boundary_depth) and metadata.st_uid != (
                    effective_uid
                ):
                    raise UnsafeProjectPath(
                        "A private state directory is not owned by the current user."
                    )
                if depth >= boundary_depth:
                    os.fchmod(next_descriptor, 0o700)
            except Exception:
                os.close(next_descriptor)
                raise
            os.close(descriptor)
            descriptor = next_descriptor
    finally:
        os.close(descriptor)
    return target


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    """Write canonical JSON mode 0600, replace atomically, and fsync its dir."""
    assert_write_is_isolated(path)
    ensure_private_directory(path.parent, boundary=path.parent)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        temporary,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(dict(payload)) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


@contextlib.contextmanager
def advisory_file_lock(path: Path, *, blocking: bool = False) -> Iterator[None]:
    """Take a private mode-0600 flock without following a lockfile symlink."""
    ensure_private_directory(path.parent, boundary=path.parent)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | _NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(descriptor, flags)
        except OSError as exc:
            raise ProjectLockContention(
                "Another reconciliation is already running."
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _git_path(root: Path, argument: str) -> Path:
    result = subprocess.run(
        ("git", "rev-parse", argument),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ProjectIdentityMismatch(
            "The selected folder is not a readable Git project."
        )
    value = result.stdout.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ProjectIdentityMismatch("The project Git path is invalid.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ProjectIdentityMismatch("The project Git path is not absolute.")
    return Path(os.path.normpath(os.fspath(path)))


def _no_follow_directory_stat(path: Path) -> os.stat_result:
    """Open every lexical directory component without following symlinks."""
    descriptor = os.open("/", os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return os.fstat(descriptor)
    except OSError as exc:
        raise ProjectIdentityMismatch(
            "The project Git directory is symlinked or unavailable."
        ) from exc
    finally:
        os.close(descriptor)


def _git_head(root: Path) -> tuple[Optional[str], Optional[str]]:
    oid_result = subprocess.run(
        ("git", "rev-parse", "--verify", "HEAD^{commit}"),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if oid_result.returncode == 0:
        head_oid: Optional[str] = oid_result.stdout.strip().lower()
        if not _HEAD_OID.fullmatch(head_oid):
            raise ProjectIdentityMismatch("The project HEAD object is invalid.")
    else:
        head_oid = None

    ref_result = subprocess.run(
        ("git", "symbolic-ref", "-q", "HEAD"),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if ref_result.returncode == 0:
        head_ref: Optional[str] = ref_result.stdout.strip()
        if not head_ref.startswith("refs/"):
            raise ProjectIdentityMismatch("The project HEAD reference is invalid.")
    elif ref_result.returncode == 1:
        head_ref = None
    else:
        raise ProjectIdentityMismatch("The project HEAD state could not be read.")
    if head_oid is None:
        if head_ref is None:
            raise ProjectIdentityMismatch("The project HEAD state is unavailable.")
        unborn_result = subprocess.run(
            ("git", "show-ref", "--verify", "--quiet", head_ref),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if unborn_result.returncode != 1:
            raise ProjectIdentityMismatch("The project HEAD object is unavailable.")
    return head_oid, head_ref


def inspect_project_identity(project: Path | str) -> ProjectIdentity:
    """Return the canonical filesystem and Git identity of a non-symlink root."""
    selected = Path(project).expanduser()
    if not selected.is_absolute():
        raise ProjectIdentityMismatch("The selected project path must be absolute.")
    try:
        if selected.is_symlink():
            raise ProjectIdentityMismatch("The selected project root is a symlink.")
        canonical = selected.resolve(strict=True)
        root_stat = canonical.stat(follow_symlinks=False)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ProjectIdentityMismatch(
                "The selected project root is not a directory."
            )
        if root_stat.st_uid != _effective_uid():
            raise ProjectIdentityMismatch(
                "The selected project root is not owned by the current user."
            )
        top = _git_path(canonical, "--show-toplevel")
        if top != canonical:
            raise ProjectIdentityMismatch(
                "The selected folder is not the Git working-tree root."
            )
        git_entry = canonical / ".git"
        git_entry_stat = git_entry.lstat()
        if git_entry_stat.st_uid != _effective_uid():
            raise ProjectIdentityMismatch(
                "The project Git entry is not owned by the current user."
            )
        if stat.S_ISLNK(git_entry_stat.st_mode):
            raise ProjectIdentityMismatch("The project Git directory is symlinked.")
        if not (
            stat.S_ISDIR(git_entry_stat.st_mode) or stat.S_ISREG(git_entry_stat.st_mode)
        ):
            raise ProjectIdentityMismatch("The project Git entry is invalid.")
        declared_git_stat: Optional[os.stat_result] = None
        if stat.S_ISREG(git_entry_stat.st_mode):
            descriptor = os.open(git_entry, os.O_RDONLY | _NOFOLLOW)
            try:
                raw_gitfile = os.read(descriptor, 4097)
            finally:
                os.close(descriptor)
            if len(raw_gitfile) > 4096:
                raise ProjectIdentityMismatch("The project Git file is invalid.")
            try:
                gitfile = raw_gitfile.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise ProjectIdentityMismatch(
                    "The project Git file is invalid."
                ) from exc
            if not gitfile.startswith("gitdir: "):
                raise ProjectIdentityMismatch("The project Git file is invalid.")
            declared = Path(gitfile.removeprefix("gitdir: "))
            if not declared.is_absolute():
                declared = canonical / declared
            declared = Path(os.path.normpath(os.fspath(declared)))
            declared_git_stat = _no_follow_directory_stat(declared)
        git_dir = _git_path(canonical, "--absolute-git-dir")
        git_stat = _no_follow_directory_stat(git_dir)
        if declared_git_stat is not None and (
            declared_git_stat.st_dev != git_stat.st_dev
            or declared_git_stat.st_ino != git_stat.st_ino
        ):
            raise ProjectIdentityMismatch("The project Git file binding changed.")
        if git_stat.st_uid != _effective_uid():
            raise ProjectIdentityMismatch(
                "The project Git directory is not owned by the current user."
            )
        head_oid, head_ref = _git_head(canonical)
    except (OSError, RuntimeError) as exc:
        if isinstance(exc, ProjectIdentityMismatch):
            raise
        raise ProjectIdentityMismatch(
            "The project identity could not be read safely."
        ) from exc

    binding = {
        "path": str(canonical),
        "device": root_stat.st_dev,
        "inode": root_stat.st_ino,
        "owner_uid": root_stat.st_uid,
        "git_dir": str(git_dir),
        "git_device": git_stat.st_dev,
        "git_inode": git_stat.st_ino,
        "git_owner_uid": git_stat.st_uid,
        "head_oid": head_oid,
        "head_ref": head_ref,
    }
    lock_binding = {
        key: binding[key] for key in ("device", "inode", "git_device", "git_inode")
    }
    return ProjectIdentity(
        **binding,
        fingerprint=_sha256(binding),
        lock_key=hashlib.sha256(_canonical_json(lock_binding)).hexdigest(),
    )


def normalize_relative_target(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise UnsafeProjectPath("A transaction target is not a safe relative path.")
    raw_parts = value.split("/")
    if value.startswith("/") or any(part in ("", ".", "..") for part in raw_parts):
        raise UnsafeProjectPath("A transaction target escaped the project root.")
    return tuple(raw_parts)


class AnchoredProject:
    """Filesystem operations anchored to an open, identity-checked root fd."""

    def __init__(self, identity: ProjectIdentity, descriptor: int):
        self.identity = identity
        self._fd = descriptor

    @property
    def path(self) -> Path:
        return Path(self.identity.path)

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def _open_parent(self, target: str, *, create: bool = False) -> tuple[int, str]:
        parts = normalize_relative_target(target)
        descriptor = os.dup(self._fd)
        try:
            for part in parts[:-1]:
                try:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                    os.fsync(descriptor)
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                        dir_fd=descriptor,
                    )
                os.close(descriptor)
                descriptor = next_fd
            return descriptor, parts[-1]
        except FileNotFoundError:
            os.close(descriptor)
            raise
        except OSError as exc:
            os.close(descriptor)
            raise UnsafeProjectPath(
                "A transaction target has an unavailable or symlinked parent."
            ) from exc

    def lstat(self, target: str) -> Optional[os.stat_result]:
        try:
            parent_fd, name = self._open_parent(target)
        except FileNotFoundError:
            return None
        try:
            try:
                return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
        finally:
            os.close(parent_fd)

    def missing_parent_paths(self, target: str) -> tuple[str, ...]:
        """Return lexical parent directories absent beneath the anchored root."""
        parts = normalize_relative_target(target)
        descriptor = os.dup(self._fd)
        missing = False
        result: list[str] = []
        try:
            for index, part in enumerate(parts[:-1], start=1):
                prefix = "/".join(parts[:index])
                if missing:
                    result.append(prefix)
                    continue
                try:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    missing = True
                    result.append(prefix)
                    continue
                except OSError as exc:
                    raise UnsafeProjectPath(
                        "A transaction target has an unavailable or symlinked parent."
                    ) from exc
                os.close(descriptor)
                descriptor = next_fd
            return tuple(result)
        finally:
            os.close(descriptor)

    def read_bytes(self, target: str) -> bytes:
        parent_fd, name = self._open_parent(target)
        try:
            descriptor = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
            try:
                with os.fdopen(descriptor, "rb", closefd=False) as handle:
                    return handle.read()
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_fd)

    def readlink(self, target: str) -> str:
        parent_fd, name = self._open_parent(target)
        try:
            return os.readlink(name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)

    def _manifest_fd(self, descriptor: int, prefix: str = "") -> list[list[Any]]:
        rows: list[list[Any]] = []
        for name in sorted(os.listdir(descriptor)):
            item = f"{prefix}/{name}" if prefix else name
            item_stat = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            mode = stat.S_IMODE(item_stat.st_mode)
            if stat.S_ISREG(item_stat.st_mode):
                child = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=descriptor)
                try:
                    digest = hashlib.sha256()
                    while True:
                        block = os.read(child, 1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                finally:
                    os.close(child)
                rows.append([item, "file", mode, digest.hexdigest()])
            elif stat.S_ISDIR(item_stat.st_mode):
                rows.append([item, "directory", mode])
                child = os.open(
                    name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=descriptor,
                )
                try:
                    rows.extend(self._manifest_fd(child, item))
                finally:
                    os.close(child)
            elif stat.S_ISLNK(item_stat.st_mode):
                rows.append(
                    [item, "symlink", mode, os.readlink(name, dir_fd=descriptor)]
                )
            else:
                raise UnsafeProjectPath("A transaction target contains a special file.")
        return rows

    def _export_tree_fd(self, descriptor: int, destination: Path) -> None:
        destination.mkdir(mode=0o700)
        for name in sorted(os.listdir(descriptor)):
            item_stat = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            mode = stat.S_IMODE(item_stat.st_mode)
            output = destination / name
            if stat.S_ISREG(item_stat.st_mode):
                source_fd = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=descriptor)
                destination_fd = os.open(
                    output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW, 0o600
                )
                try:
                    while True:
                        block = os.read(source_fd, 1024 * 1024)
                        if not block:
                            break
                        view = memoryview(block)
                        while view:
                            written = os.write(destination_fd, view)
                            view = view[written:]
                    os.fchmod(destination_fd, mode)
                    os.fsync(destination_fd)
                finally:
                    os.close(source_fd)
                    os.close(destination_fd)
            elif stat.S_ISDIR(item_stat.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=descriptor,
                )
                try:
                    self._export_tree_fd(child, output)
                    output.chmod(mode)
                finally:
                    os.close(child)
            elif stat.S_ISLNK(item_stat.st_mode):
                output.symlink_to(os.readlink(name, dir_fd=descriptor))
            else:
                raise UnsafeProjectPath("A transaction target contains a special file.")
        fsync_directory(destination)

    def export_tree(self, target: str, destination: Path) -> None:
        """Copy a directory snapshot without following any project symlink."""
        parent_fd, name = self._open_parent(target)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                self._export_tree_fd(descriptor, destination)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_fd)

    def _import_tree_path(self, source: Path, destination_fd: int) -> None:
        for item in sorted(source.iterdir(), key=lambda candidate: candidate.name):
            item_stat = item.lstat()
            mode = stat.S_IMODE(item_stat.st_mode)
            if stat.S_ISREG(item_stat.st_mode):
                source_fd = os.open(item, os.O_RDONLY | _NOFOLLOW)
                target_fd = os.open(
                    item.name,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
                    mode,
                    dir_fd=destination_fd,
                )
                try:
                    while True:
                        block = os.read(source_fd, 1024 * 1024)
                        if not block:
                            break
                        view = memoryview(block)
                        while view:
                            written = os.write(target_fd, view)
                            view = view[written:]
                    os.fchmod(target_fd, mode)
                    os.fsync(target_fd)
                finally:
                    os.close(source_fd)
                    os.close(target_fd)
            elif stat.S_ISDIR(item_stat.st_mode):
                os.mkdir(item.name, mode, dir_fd=destination_fd)
                child = os.open(
                    item.name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=destination_fd,
                )
                try:
                    os.fchmod(child, mode)
                    self._import_tree_path(item, child)
                    os.fsync(child)
                finally:
                    os.close(child)
            elif stat.S_ISLNK(item_stat.st_mode):
                os.symlink(os.readlink(item), item.name, dir_fd=destination_fd)
            else:
                raise UnsafeProjectPath("A transaction source contains a special file.")

    def install_tree(self, target: str, source: Path, *, mode: int = 0o755) -> None:
        """Stage a no-follow source tree, then install it beneath the root fd."""
        if source.is_symlink() or not source.is_dir():
            raise UnsafeProjectPath("A transaction tree source is unavailable.")
        parent_fd, name = self._open_parent(target, create=True)
        temporary = f".{name}.cc-{secrets.token_hex(8)}"
        try:
            os.mkdir(temporary, mode, dir_fd=parent_fd)
            temporary_fd = os.open(
                temporary,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                os.fchmod(temporary_fd, mode)
                self._import_tree_path(source, temporary_fd)
                os.fsync(temporary_fd)
            finally:
                os.close(temporary_fd)
            try:
                item_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                item_stat = None
            if item_stat is not None:
                if stat.S_ISDIR(item_stat.st_mode):
                    existing_fd = os.open(
                        name,
                        os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    try:
                        self._remove_tree_fd(existing_fd)
                    finally:
                        os.close(existing_fd)
                    os.rmdir(name, dir_fd=parent_fd)
                else:
                    os.unlink(name, dir_fd=parent_fd)
            os.rename(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
        finally:
            try:
                temporary_fd = os.open(
                    temporary,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except FileNotFoundError:
                temporary_fd = None
            if temporary_fd is not None:
                try:
                    self._remove_tree_fd(temporary_fd)
                finally:
                    os.close(temporary_fd)
                os.rmdir(temporary, dir_fd=parent_fd)
            os.close(parent_fd)

    def fingerprint(self, target: str) -> str:
        try:
            parent_fd, name = self._open_parent(target)
        except FileNotFoundError:
            return fingerprint_missing()
        try:
            try:
                item_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return fingerprint_missing()
            mode = stat.S_IMODE(item_stat.st_mode)
            if stat.S_ISREG(item_stat.st_mode):
                descriptor = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
                try:
                    digest = hashlib.sha256()
                    while True:
                        block = os.read(descriptor, 1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                finally:
                    os.close(descriptor)
                return _sha256(["file", mode, digest.hexdigest()])
            if stat.S_ISLNK(item_stat.st_mode):
                return fingerprint_symlink(os.readlink(name, dir_fd=parent_fd))
            if stat.S_ISDIR(item_stat.st_mode):
                descriptor = os.open(
                    name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=parent_fd,
                )
                try:
                    return _sha256(["directory", mode, self._manifest_fd(descriptor)])
                finally:
                    os.close(descriptor)
            raise UnsafeProjectPath("A transaction target is a special file.")
        finally:
            os.close(parent_fd)

    def atomic_write(self, target: str, payload: bytes, *, mode: int = 0o644) -> None:
        parent_fd, name = self._open_parent(target, create=True)
        temporary = f".{name}.cc-{secrets.token_hex(8)}"
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
                mode,
                dir_fd=parent_fd,
            )
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fchmod(descriptor, mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)

    def _remove_tree_fd(self, descriptor: int) -> None:
        for name in os.listdir(descriptor):
            item_stat = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(item_stat.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=descriptor,
                )
                try:
                    self._remove_tree_fd(child)
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=descriptor)
            else:
                os.unlink(name, dir_fd=descriptor)

    def remove(self, target: str) -> None:
        try:
            parent_fd, name = self._open_parent(target)
        except FileNotFoundError:
            return
        try:
            try:
                item_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISDIR(item_stat.st_mode):
                descriptor = os.open(
                    name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=parent_fd,
                )
                try:
                    self._remove_tree_fd(descriptor)
                finally:
                    os.close(descriptor)
                os.rmdir(name, dir_fd=parent_fd)
            else:
                os.unlink(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def remove_empty_parents(self, target: str, candidates: tuple[str, ...]) -> None:
        """Remove only originally missing, now-empty target parents deepest-first."""
        target_parts = normalize_relative_target(target)
        validated: list[tuple[str, ...]] = []
        for candidate in candidates:
            parts = normalize_relative_target(candidate)
            if len(parts) >= len(target_parts) or parts != target_parts[: len(parts)]:
                raise UnsafeProjectPath(
                    "A saved missing parent is outside its transaction target."
                )
            validated.append(parts)
        for parts in sorted(validated, key=len, reverse=True):
            relative = "/".join(parts)
            try:
                parent_fd, name = self._open_parent(relative)
            except FileNotFoundError:
                continue
            try:
                try:
                    item_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(item_stat.st_mode):
                    continue
                try:
                    os.rmdir(name, dir_fd=parent_fd)
                except OSError as exc:
                    if exc.errno in {errno.EEXIST, errno.ENOTEMPTY, errno.ENOTDIR}:
                        continue
                    raise
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)

    def atomic_symlink(
        self, target: str, link_value: str, *, allow_external_restore: bool = False
    ) -> None:
        link_parts = normalize_relative_target(target)
        if not allow_external_restore:
            link = PurePosixPath(link_value)
            if link.is_absolute() or not link_value or "\x00" in link_value:
                raise UnsafeProjectPath("An internal link would escape the project.")
            stack = list(link_parts[:-1])
            for part in link.parts:
                if part in ("", "."):
                    continue
                if part == "..":
                    if not stack:
                        raise UnsafeProjectPath(
                            "An internal link would escape the project."
                        )
                    stack.pop()
                else:
                    stack.append(part)
        parent_fd, name = self._open_parent(target, create=True)
        temporary = f".{name}.cc-{secrets.token_hex(8)}"
        try:
            os.symlink(link_value, temporary, dir_fd=parent_fd)
            os.replace(
                temporary,
                name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)


@contextlib.contextmanager
def project_lock(
    project: Path | str,
    *,
    expected_identity: Optional[ProjectIdentity | Mapping[str, Any]] = None,
    lock_root: Optional[Path] = None,
    blocking: bool = False,
) -> Iterator[AnchoredProject]:
    """Lock, re-identify, and open a project root without following its leaf."""
    before = inspect_project_identity(project)
    expected = (
        ProjectIdentity.from_value(expected_identity)
        if expected_identity is not None
        else before
    )
    if before != expected:
        raise ProjectIdentityMismatch(
            "The project no longer matches the reviewed plan."
        )
    state_root = (lock_root or (_default_state_root() / "locks")).expanduser()
    boundary = state_root if lock_root is not None else machine_diagnostics_root()
    ensure_private_directory(state_root, boundary=boundary)
    lockfile = state_root / f"project-{before.lock_key}.lock"
    with advisory_file_lock(lockfile, blocking=blocking):
        current = inspect_project_identity(project)
        if current != expected:
            raise ProjectIdentityMismatch(
                "The project changed while its lock was acquired."
            )
        descriptor = os.open(
            current.path,
            os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
        )
        anchored = AnchoredProject(current, descriptor)
        try:
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino) != (current.device, current.inode)
                or opened.st_uid != current.owner_uid
                or opened.st_uid != _effective_uid()
            ):
                raise ProjectIdentityMismatch(
                    "The project root changed while it was opened."
                )
            yield anchored
        finally:
            anchored.close()


def fingerprint_target(project: Path | str, target: str) -> str:
    """Read one bounded target fingerprint under the canonical project lock."""
    with project_lock(project) as anchored:
        return anchored.fingerprint(target)


BoundaryObserver = Callable[[str, Mapping[str, Any]], None]


__all__ = [
    "AnchoredProject",
    "BoundaryObserver",
    "ProjectIdentity",
    "ProjectIdentityMismatch",
    "ProjectLockContention",
    "ProjectLockError",
    "UnsafeProjectPath",
    "advisory_file_lock",
    "atomic_json_write",
    "ensure_private_directory",
    "fingerprint_file_payload",
    "fingerprint_missing",
    "fingerprint_symlink",
    "fingerprint_tree_source",
    "fingerprint_target",
    "fsync_directory",
    "inspect_project_identity",
    "normalize_relative_target",
    "project_lock",
]
