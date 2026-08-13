#!/usr/bin/env python3
"""Install one exact Claude Copilot commit as an immutable machine runtime.

The source checkout is authoring state, never the installed runtime.  This
installer archives an explicit commit, builds cc inside the commit-addressed
snapshot, makes that snapshot read-only, and only then publishes the cc shim
and VERSION.json's machineCommands.  Managed files are individually replaced
atomically under one lock and restored byte-for-byte if any publish step fails.

This module intentionally uses only the Python standard library: it is the
bootstrap boundary that runs before the snapshot's cc environment is active.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Sequence

_OBJECT_ID = re.compile(r"[0-9a-f]{40}")
_REQUIRED_MACHINE_COMMANDS = frozenset({"setup-project.md", "update-project.md"})
_REQUIRED_SNAPSHOT_FILES = (
    "VERSION.json",
    "tools/cc/install.sh",
    "tools/cc/pyproject.toml",
    "tools/cc/src/cc/core/conformance/roundtrip.py",
)
_MARKER_NAMES = (".source-commit", ".source-tree")


class FrameworkInstallError(RuntimeError):
    """A fail-closed framework installation error."""


@dataclass(frozen=True)
class CommandArtifact:
    name: str
    payload: bytes
    checksum: str


@dataclass(frozen=True)
class CapturedFile:
    exists: bool
    payload: bytes = b""
    mode: int = 0


@dataclass(frozen=True)
class TrackedArtifact:
    kind: str
    executable: bool = False
    checksum: str = ""
    link_target: str = ""


CcInstaller = Callable[[Path, Path], None]
CcVerifier = Callable[[Path], None]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_real_directory(path: Path, *, mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FrameworkInstallError(f"directory is unavailable: {path}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise FrameworkInstallError(f"directory must not be a symlink: {path}")


def _atomic_write(path: Path, payload: bytes, *, mode: int) -> None:
    _ensure_real_directory(path.parent)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_directory(path.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


def _capture_regular_file(path: Path) -> CapturedFile:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return CapturedFile(False)
    except OSError as exc:
        raise FrameworkInstallError(f"managed target is unavailable: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise FrameworkInstallError(
            f"managed target must be a regular file or absent: {path}"
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise FrameworkInstallError(f"managed target is unreadable: {path}") from exc
    return CapturedFile(True, payload, stat.S_IMODE(metadata.st_mode))


def _restore_file(path: Path, captured: CapturedFile) -> None:
    if captured.exists:
        _atomic_write(path, captured.payload, mode=captured.mode)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def _validate_object_id(value: str, *, label: str) -> str:
    if _OBJECT_ID.fullmatch(value) is None:
        raise FrameworkInstallError(
            f"{label} must be a full lowercase 40-character Git object ID"
        )
    return value


def _git(source_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-C", str(source_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrameworkInstallError("Git source verification could not run") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise FrameworkInstallError(detail)
    return result.stdout.strip()


def _verify_git_source(source_root: Path, commit: str, tree: str) -> None:
    top = Path(_git(source_root, "rev-parse", "--show-toplevel")).resolve()
    if top != source_root:
        raise FrameworkInstallError(
            f"source root must be the repository root: expected {top}, got {source_root}"
        )
    resolved_commit = _git(source_root, "rev-parse", f"{commit}^{{commit}}")
    if resolved_commit != commit:
        raise FrameworkInstallError("source commit did not resolve exactly")
    resolved_tree = _git(source_root, "rev-parse", f"{commit}^{{tree}}")
    if resolved_tree != tree:
        raise FrameworkInstallError(
            f"source tree mismatch: expected {tree}, Git resolved {resolved_tree}"
        )


def _member_parts(name: str) -> tuple[str, ...]:
    pure = PurePosixPath(name.rstrip("/"))
    if (
        not pure.parts
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise FrameworkInstallError(f"git archive contains an unsafe path: {name!r}")
    return pure.parts


def _extract_git_archive(source_root: Path, commit: str, destination: Path) -> None:
    """Extract a validated Git tar without ever following archived links."""

    with tempfile.TemporaryFile() as archive_file:
        try:
            result = subprocess.run(
                ("git", "-C", str(source_root), "archive", "--format=tar", commit),
                check=False,
                stdout=archive_file,
                stderr=subprocess.PIPE,
                timeout=60.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FrameworkInstallError("git archive could not run") from exc
        if result.returncode != 0:
            raise FrameworkInstallError(
                result.stderr.decode("utf-8", errors="replace").strip()
                or "git archive failed"
            )
        archive_file.seek(0)
        with tarfile.open(fileobj=archive_file, mode="r:") as archive:
            members = archive.getmembers()
            names: set[tuple[str, ...]] = set()
            link_paths: set[tuple[str, ...]] = set()
            normalized: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
            for member in members:
                parts = _member_parts(member.name)
                if parts in names:
                    raise FrameworkInstallError(
                        f"git archive contains a duplicate path: {member.name}"
                    )
                names.add(parts)
                if not (member.isdir() or member.isreg() or member.issym()):
                    raise FrameworkInstallError(
                        f"git archive contains an unsupported entry: {member.name}"
                    )
                if member.issym():
                    link_paths.add(parts)
                normalized.append((member, parts))

            for _member, parts in normalized:
                if any(parts[:index] in link_paths for index in range(1, len(parts))):
                    raise FrameworkInstallError(
                        "git archive contains content nested beneath a symlink"
                    )

            for member, parts in sorted(normalized, key=lambda row: len(row[1])):
                if not member.isdir():
                    continue
                target = destination.joinpath(*parts)
                target.mkdir(parents=True, exist_ok=False, mode=0o700)

            for member, parts in normalized:
                if not member.isreg():
                    continue
                target = destination.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(target, flags, member.mode & 0o777)
                try:
                    source = archive.extractfile(member)
                    if source is None:
                        raise FrameworkInstallError(
                            f"git archive file is unreadable: {member.name}"
                        )
                    with source, os.fdopen(descriptor, "wb", closefd=True) as output:
                        shutil.copyfileobj(source, output)
                        output.flush()
                        os.fsync(output.fileno())
                except BaseException:
                    with contextlib.suppress(OSError):
                        os.close(descriptor)
                    raise

            for member, parts in normalized:
                if not member.issym():
                    continue
                target = destination.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.symlink(member.linkname, target)

            for member, parts in sorted(
                normalized, key=lambda row: len(row[1]), reverse=True
            ):
                if member.isdir():
                    os.chmod(destination.joinpath(*parts), member.mode & 0o777)


def _git_archive_identity(source_root: Path, commit: str) -> dict[str, TrackedArtifact]:
    """Return the complete tracked identity encoded by ``git archive``."""

    with tempfile.TemporaryFile() as archive_file:
        try:
            result = subprocess.run(
                ("git", "-C", str(source_root), "archive", "--format=tar", commit),
                check=False,
                stdout=archive_file,
                stderr=subprocess.PIPE,
                timeout=60.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FrameworkInstallError("git archive identity could not run") from exc
        if result.returncode != 0:
            raise FrameworkInstallError(
                result.stderr.decode("utf-8", errors="replace").strip()
                or "git archive identity failed"
            )
        archive_file.seek(0)
        identity: dict[str, TrackedArtifact] = {}
        with tarfile.open(fileobj=archive_file, mode="r:") as archive:
            for member in archive.getmembers():
                relative = "/".join(_member_parts(member.name))
                if relative in identity:
                    raise FrameworkInstallError(
                        f"git archive contains a duplicate path: {member.name}"
                    )
                if member.isdir():
                    artifact = TrackedArtifact(kind="directory")
                elif member.isreg():
                    source = archive.extractfile(member)
                    if source is None:
                        raise FrameworkInstallError(
                            f"git archive file is unreadable: {member.name}"
                        )
                    with source:
                        checksum = _sha256(source.read())
                    artifact = TrackedArtifact(
                        kind="file",
                        executable=bool(member.mode & 0o111),
                        checksum=checksum,
                    )
                elif member.issym():
                    artifact = TrackedArtifact(
                        kind="symlink", link_target=member.linkname
                    )
                else:
                    raise FrameworkInstallError(
                        f"git archive contains an unsupported entry: {member.name}"
                    )
                identity[relative] = artifact
        return identity


def _is_installer_owned_extra(relative: str) -> bool:
    return (
        relative in _MARKER_NAMES
        or relative == "tools/cc/.venv"
        or relative.startswith("tools/cc/.venv/")
    )


def _validate_snapshot_tree(snapshot: Path, source_root: Path, commit: str) -> None:
    """Bind every reusable snapshot entry to the explicit Git commit tree.

    Git tracks the regular-file executable bit rather than full POSIX modes;
    the installed copy additionally requires every non-symlink entry to be
    read-only. Only the provenance marker pair and cc's built virtual
    environment may exist outside the tracked archive.
    """

    expected = _git_archive_identity(source_root, commit)
    for relative, artifact in expected.items():
        path = snapshot.joinpath(*PurePosixPath(relative).parts)
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise FrameworkInstallError(
                f"tracked snapshot entry is unavailable: {relative}"
            ) from exc

        if artifact.kind == "directory":
            if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
                raise FrameworkInstallError(
                    f"tracked snapshot entry has the wrong type: {relative}"
                )
            if metadata.st_mode & 0o222:
                raise FrameworkInstallError(
                    f"tracked snapshot directory is writable: {relative}"
                )
        elif artifact.kind == "file":
            if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
                raise FrameworkInstallError(
                    f"tracked snapshot entry has the wrong type: {relative}"
                )
            if metadata.st_mode & 0o222:
                raise FrameworkInstallError(
                    f"tracked snapshot file is writable: {relative}"
                )
            if bool(metadata.st_mode & 0o111) != artifact.executable:
                raise FrameworkInstallError(
                    f"tracked snapshot executable mode differs from Git: {relative}"
                )
            try:
                checksum = _sha256(path.read_bytes())
            except OSError as exc:
                raise FrameworkInstallError(
                    f"tracked snapshot file is unreadable: {relative}"
                ) from exc
            if checksum != artifact.checksum:
                raise FrameworkInstallError(
                    f"tracked snapshot content differs from Git: {relative}"
                )
        else:
            if not stat.S_ISLNK(metadata.st_mode):
                raise FrameworkInstallError(
                    f"tracked snapshot entry has the wrong type: {relative}"
                )
            try:
                link_target = os.readlink(path)
            except OSError as exc:
                raise FrameworkInstallError(
                    f"tracked snapshot symlink is unreadable: {relative}"
                ) from exc
            if link_target != artifact.link_target:
                raise FrameworkInstallError(
                    f"tracked snapshot symlink differs from Git: {relative}"
                )

    for path in snapshot.rglob("*"):
        relative = path.relative_to(snapshot).as_posix()
        if relative in expected:
            continue
        if not _is_installer_owned_extra(relative):
            raise FrameworkInstallError(
                f"snapshot contains an untracked extra entry: {relative}"
            )
        metadata = path.lstat()
        if not stat.S_ISLNK(metadata.st_mode) and metadata.st_mode & 0o222:
            raise FrameworkInstallError(
                f"installer-owned snapshot entry is writable: {relative}"
            )


def _read_regular(path: Path, *, readonly: bool = False) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FrameworkInstallError(
            f"required snapshot file is unavailable: {path}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise FrameworkInstallError(f"required snapshot file is not regular: {path}")
    if readonly and metadata.st_mode & 0o222:
        raise FrameworkInstallError(f"required snapshot file is writable: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FrameworkInstallError(
            f"required snapshot file is unreadable: {path}"
        ) from exc


def _load_machine_commands(
    snapshot: Path, *, readonly: bool = False
) -> tuple[CommandArtifact, ...]:
    raw_version = _read_regular(snapshot / "VERSION.json", readonly=readonly)
    try:
        version = json.loads(raw_version.decode("utf-8"))
        roster = version["components"]["commands"]["machineCommands"]
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FrameworkInstallError(
            "VERSION.json has no valid machineCommands roster"
        ) from exc
    if not isinstance(roster, list) or not roster:
        raise FrameworkInstallError(
            "VERSION.json machineCommands must be a non-empty list"
        )

    names: list[str] = []
    for entry in roster:
        if (
            not isinstance(entry, str)
            or not entry.endswith(".md")
            or Path(entry).name != entry
            or entry in {".", ".."}
        ):
            raise FrameworkInstallError(
                f"VERSION.json contains an unsafe machineCommands entry: {entry!r}"
            )
        if entry in names:
            raise FrameworkInstallError(
                f"VERSION.json contains a duplicate machineCommands entry: {entry}"
            )
        names.append(entry)
    if not _REQUIRED_MACHINE_COMMANDS.issubset(names):
        missing = sorted(_REQUIRED_MACHINE_COMMANDS.difference(names))
        raise FrameworkInstallError(
            "VERSION.json omits required operational machine commands: "
            + ", ".join(missing)
        )

    artifacts: list[CommandArtifact] = []
    for name in names:
        payload = _read_regular(
            snapshot / ".claude" / "commands" / name, readonly=readonly
        )
        artifacts.append(CommandArtifact(name, payload, _sha256(payload)))
    return tuple(artifacts)


def _make_tree_readonly(root: Path) -> None:
    paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in paths:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            continue
        mode = stat.S_IMODE(metadata.st_mode) & ~0o222
        if stat.S_ISDIR(metadata.st_mode):
            mode |= 0o500
        os.chmod(path, mode, follow_symlinks=False)
    os.chmod(root, (stat.S_IMODE(root.lstat().st_mode) & ~0o222) | 0o500)


def _validate_snapshot(
    snapshot: Path, source_root: Path, commit: str, tree: str
) -> tuple[CommandArtifact, ...]:
    try:
        metadata = snapshot.lstat()
    except OSError as exc:
        raise FrameworkInstallError(f"snapshot is unavailable: {snapshot}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or snapshot.is_symlink():
        raise FrameworkInstallError("snapshot must be a real directory")
    if metadata.st_mode & 0o222:
        raise FrameworkInstallError("snapshot root must be read-only")
    if (snapshot / ".git").exists() or (snapshot / ".git").is_symlink():
        raise FrameworkInstallError("installed snapshot must not contain .git")

    for name, expected in zip(_MARKER_NAMES, (commit, tree)):
        marker = snapshot / name
        payload = _read_regular(marker, readonly=True)
        try:
            actual = payload.decode("ascii").strip()
        except UnicodeError as exc:
            raise FrameworkInstallError(
                f"snapshot marker is not ASCII: {marker}"
            ) from exc
        if actual != expected:
            raise FrameworkInstallError(f"snapshot marker mismatch: {marker}")

    _validate_snapshot_tree(snapshot, source_root, commit)
    for relative in _REQUIRED_SNAPSHOT_FILES:
        _read_regular(snapshot / relative, readonly=True)
    commands = _load_machine_commands(snapshot, readonly=True)
    cc_entrypoint = snapshot / "tools" / "cc" / ".venv" / "bin" / "cc"
    _read_regular(cc_entrypoint, readonly=True)
    if not os.access(cc_entrypoint, os.X_OK):
        raise FrameworkInstallError("snapshot cc entry point is not executable")
    return commands


def _materialize_snapshot(
    source_root: Path,
    snapshots_root: Path,
    commit: str,
    tree: str,
) -> Path:
    snapshot = snapshots_root / f"claude-copilot-{commit}"
    if snapshot.exists() or snapshot.is_symlink():
        return snapshot

    stage = snapshots_root / f".claude-copilot-{commit}.archive-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        _extract_git_archive(source_root, commit, stage)
        for marker_name in _MARKER_NAMES:
            marker = stage / marker_name
            if marker.exists() or marker.is_symlink():
                raise FrameworkInstallError(
                    f"source archive unexpectedly contains reserved marker {marker_name}"
                )
        _atomic_write(
            stage / ".source-commit", f"{commit}\n".encode("ascii"), mode=0o444
        )
        _atomic_write(stage / ".source-tree", f"{tree}\n".encode("ascii"), mode=0o444)
        _load_machine_commands(stage)
        for relative in _REQUIRED_SNAPSHOT_FILES:
            _read_regular(stage / relative)
        os.replace(stage, snapshot)
        _fsync_directory(snapshots_root)
        return snapshot
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _default_cc_installer(snapshot: Path, staged_shim: Path) -> None:
    script = snapshot / "tools" / "cc" / "install.sh"
    try:
        subprocess.run(
            (
                "bash",
                str(script),
                "--shim-path",
                str(staged_shim),
                "--no-profile-update",
            ),
            check=True,
            timeout=300.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise FrameworkInstallError("cc snapshot build failed") from exc


def _default_cc_verifier(staged_shim: Path) -> None:
    try:
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(
            (str(staged_shim), "--version"),
            check=True,
            capture_output=True,
            env=environment,
            timeout=30.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise FrameworkInstallError("staged cc verification failed") from exc


def _remove_created_snapshot(snapshot: Path) -> None:
    def make_writable_and_retry(function, path, _error) -> None:  # noqa: ANN001
        with contextlib.suppress(OSError):
            os.chmod(path, 0o700)
        function(path)

    shutil.rmtree(snapshot, onerror=make_writable_and_retry)


@contextlib.contextmanager
def _install_lock(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise FrameworkInstallError(f"installer lock is unavailable: {path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FrameworkInstallError("installer lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _publish_runtime(
    *,
    commands: Sequence[CommandArtifact],
    staged_shim: Path,
    commands_root: Path,
    shim: Path,
    active_manifest: Path,
    manifest_payload: bytes,
    fail_after_publish: int | None = None,
) -> int:
    targets: list[tuple[Path, bytes, int, str]] = [
        (commands_root / item.name, item.payload, 0o644, item.checksum)
        for item in commands
    ]
    shim_payload = _read_regular(staged_shim)
    targets.append((shim, shim_payload, 0o755, _sha256(shim_payload)))
    targets.append(
        (active_manifest, manifest_payload, 0o600, _sha256(manifest_payload))
    )

    captured = {path: _capture_regular_file(path) for path, *_rest in targets}
    changed = sum(
        1
        for path, payload, _mode, _checksum in targets
        if not captured[path].exists or captured[path].payload != payload
    )
    published: list[Path] = []
    try:
        for index, (path, payload, mode, checksum) in enumerate(targets, start=1):
            _atomic_write(path, payload, mode=mode)
            published.append(path)
            if _sha256(_read_regular(path)) != checksum:
                raise FrameworkInstallError(f"published checksum mismatch: {path}")
            if fail_after_publish is not None and index == fail_after_publish:
                raise FrameworkInstallError("injected publish failure")
    except BaseException as publish_error:
        rollback_errors: list[str] = []
        for path in reversed(published):
            try:
                _restore_file(path, captured[path])
            except BaseException as rollback_error:  # noqa: BLE001
                rollback_errors.append(f"{path}: {rollback_error}")
        if rollback_errors:
            raise FrameworkInstallError(
                "publish failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from publish_error
        raise
    return changed


def install_framework_snapshot(
    *,
    source_root: Path,
    source_commit: str,
    source_tree: str,
    home: Path | None = None,
    cc_installer: CcInstaller = _default_cc_installer,
    cc_verifier: CcVerifier = _default_cc_verifier,
    _fail_after_publish: int | None = None,
) -> dict[str, object]:
    commit = _validate_object_id(source_commit, label="source commit")
    tree = _validate_object_id(source_tree, label="source tree")
    source = source_root.expanduser().resolve(strict=True)
    _verify_git_source(source, commit, tree)

    home_root = (home or Path.home()).expanduser()
    _ensure_real_directory(home_root)
    home_root = home_root.resolve(strict=True)
    copilot_root = home_root / ".copilot"
    snapshots_root = copilot_root / "framework-snapshots"
    commands_root = home_root / ".claude" / "commands"
    shim_root = home_root / ".local" / "bin"
    for directory in (copilot_root, snapshots_root, commands_root, shim_root):
        _ensure_real_directory(directory)

    lock_path = copilot_root / "framework-install.lock"
    with _install_lock(lock_path):
        snapshot = snapshots_root / f"claude-copilot-{commit}"
        existed_before = snapshot.exists() or snapshot.is_symlink()
        snapshot = _materialize_snapshot(source, snapshots_root, commit, tree)
        operation_root = copilot_root / f".framework-install-{uuid.uuid4().hex}"
        operation_root.mkdir(mode=0o700)
        staged_shim = operation_root / "cc"
        try:
            if existed_before:
                commands = _validate_snapshot(snapshot, source, commit, tree)
                runtime_cc = snapshot / "tools" / "cc" / ".venv" / "bin" / "cc"
                _atomic_write(staged_shim, _read_regular(runtime_cc), mode=0o755)
            else:
                try:
                    cc_installer(snapshot, staged_shim)
                    _read_regular(staged_shim)
                    cc_verifier(staged_shim)
                    _make_tree_readonly(snapshot)
                    commands = _validate_snapshot(snapshot, source, commit, tree)
                except BaseException:
                    _remove_created_snapshot(snapshot)
                    raise

            cc_verifier(staged_shim)
            shim_checksum = _sha256(_read_regular(staged_shim))
            manifest = {
                "schema_version": "1.0",
                "source_commit": commit,
                "source_tree": tree,
                "snapshot": str(snapshot),
                "cc": {
                    "path": str(home_root / ".local" / "bin" / "cc"),
                    "sha256": shim_checksum,
                },
                "machine_commands": [
                    {"name": item.name, "sha256": item.checksum} for item in commands
                ],
            }
            manifest_payload = (
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            changed = _publish_runtime(
                commands=commands,
                staged_shim=staged_shim,
                commands_root=commands_root,
                shim=shim_root / "cc",
                active_manifest=copilot_root / "framework-runtime.json",
                manifest_payload=manifest_payload,
                fail_after_publish=_fail_after_publish,
            )
        finally:
            shutil.rmtree(operation_root, ignore_errors=True)

    return {
        "result": "installed" if changed else "up-to-date",
        "source_commit": commit,
        "source_tree": tree,
        "snapshot": str(snapshot),
        "machine_commands": [item.name for item in commands],
        "changed_targets": changed,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument(
        "--home",
        type=Path,
        help="Alternate machine home root (primarily for isolated verification).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = install_framework_snapshot(
            source_root=arguments.source_root,
            source_commit=arguments.source_commit,
            source_tree=arguments.source_tree,
            home=arguments.home,
        )
    except (FrameworkInstallError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
