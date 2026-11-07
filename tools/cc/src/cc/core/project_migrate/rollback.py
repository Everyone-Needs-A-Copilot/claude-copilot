"""Restore migration receipts without following replacement ancestor symlinks."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

from cc.core.project_migrate.apply import MANIFEST
from cc.core.project_migrate.model import MigrateError


@contextmanager
def _parent(root: Path, relative: str, *, create: bool = False):
    """Pin every directory before use; all later operations are relative to its fd."""
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(p in ("..", ".") for p in rel.parts):
        raise ValueError(f"unsafe relative path: {relative}")
    # Resolve system aliases above the owned root (e.g. macOS /var), never the
    # owned root itself or a project/backup-relative ancestor.
    root = root.parent.resolve(strict=True) / root.name
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    try:
        for part in rel.parts[:-1]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, dir_fd=fd)
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, rel.name
        # A rename may move the pinned directory while a restoration is in
        # progress. Never report completion for a different named ancestor.
        named = os.stat(root / rel.parent, follow_symlinks=False)
        pinned = os.fstat(fd)
        if (named.st_dev, named.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise ValueError("rollback ancestor changed during restoration")
    finally:
        os.close(fd)


def _state(fd: int, name: str) -> tuple[str, str | None]:
    try:
        meta = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return "absent", None
    if stat.S_ISLNK(meta.st_mode):
        return "link", os.readlink(name, dir_fd=fd)
    if not stat.S_ISREG(meta.st_mode):
        return "other", None
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        with os.fdopen(handle, "rb", closefd=False) as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            return "file", "sha256:" + digest.hexdigest()
    finally:
        os.close(handle)


def _backup(base: Path, entry: dict[str, Any]) -> bytes:
    with _parent(base, entry["backup"]) as (fd, name):
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(handle, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("backup is not a regular file")
            data = stream.read()
    if "sha256:" + hashlib.sha256(data).hexdigest() != entry.get("sha_before"):
        raise ValueError("backup no longer matches its recorded hash")
    return data


def _write(fd: int, name: str, data: bytes, mode: int) -> None:
    temp = f".{name}.rollback-{uuid.uuid4().hex}"
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(handle, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), mode)
    # No path is resolved again after validation; a swapped ancestor cannot
    # redirect either the temporary write or its atomic destination rename.
    os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)


def _undo(entry: dict[str, Any], root: Path, base: Path) -> bool:
    rel, kind = entry["path"], entry["kind"]
    if kind == "external":
        target = Path(rel)
        if not target.is_absolute() or ".." in target.parts:
            raise ValueError("external path is not absolute and normalized")
        # Walk the entire external parent chain, allowing only the system root
        # aliases already resolved in the recorded canonical absolute path.
        root, rel = Path(target.anchor), str(target.relative_to(target.anchor))
    restore = kind in ("deleted", "modified", "unlinked", "external")
    try:
        context = _parent(root, rel, create=restore)
        with context as (fd, name):
            current_kind, current = _state(fd, name)
            if kind == "created-dir":
                try:
                    os.rmdir(name, dir_fd=fd)
                except OSError:
                    pass
                return False
            if kind == "created-link":
                if current_kind == "link" and current == entry.get("link_after"):
                    os.unlink(name, dir_fd=fd)
                    if entry.get("link_before") is not None:
                        os.symlink(entry["link_before"], name, dir_fd=fd)
                    return True
                if current_kind != "absent":
                    raise ValueError("changed since migration, left in place")
                return False
            if kind == "created" or (kind == "external" and entry.get("absent_before")):
                if current_kind == "file" and current == entry.get("sha_after"):
                    os.unlink(name, dir_fd=fd)
                    return True
                if current_kind != "absent":
                    raise ValueError("changed since migration, left in place")
                return False
            if kind == "unlinked":
                if current_kind != "absent":
                    raise ValueError("path exists, left in place")
                os.symlink(entry["link_target"], name, dir_fd=fd)
                return True
            if kind == "modified" and "sha_after" not in entry:
                if entry.get("absent_before"):
                    if current_kind == "file":
                        os.unlink(name, dir_fd=fd)
                        return True
                    if current_kind != "absent":
                        raise ValueError("changed since migration, left in place")
                    return False
                if current_kind == "file" and current == entry.get("sha_before"):
                    return False
            elif kind in ("modified", "external") and current_kind != "absent":
                if current_kind != "file" or current != entry.get("sha_after"):
                    # A repeated restore may already have the original file.
                    if current_kind == "file" and current == entry.get("sha_before"):
                        return False
                    if kind == "modified" and current_kind == "link" and current == entry.get("link_target"):
                        return False
                    raise ValueError("changed since migration, left in place")
            if kind == "modified" and "link_target" in entry:
                if current_kind == "link":
                    if current != entry["link_target"]:
                        raise ValueError("changed symlink, left in place")
                    return False
                if current_kind == "file":
                    os.unlink(name, dir_fd=fd)
                os.symlink(entry["link_target"], name, dir_fd=fd)
                return True
            if kind == "deleted" and current_kind != "absent":
                if current_kind != "file" or current != entry.get("sha_before"):
                    raise ValueError("a different file exists, left in place")
                return False
            if kind in ("deleted", "modified", "external") and "backup" in entry:
                _write(fd, name, _backup(base, entry), entry.get("mode", 0o644))
                return True
            return False
    except FileNotFoundError:
        if not restore:
            return False
        raise


def rollback_migration(backup_dir: Path | str) -> dict[str, Any]:
    backup = Path(backup_dir).expanduser()
    mf = backup / MANIFEST if backup.is_dir() else backup
    try:
        with _parent(mf.parent, mf.name) as (fd, name):
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            with os.fdopen(handle, "r", encoding="utf-8") as stream:
                manifest = json.load(stream)
    except (OSError, ValueError) as exc:
        raise MigrateError("no-manifest", f"cannot read rollback manifest at {mf}: {exc}") from exc
    root = Path(manifest["project"])
    if not root.is_absolute() or ".." in root.parts:
        raise MigrateError("unsafe-project", "rollback project must be an absolute normalized path")
    base = mf.parent
    restored: list[str] = []
    conflicts: list[str] = []
    if manifest.get("status") == "rolled-back":
        return {"project": str(root), "restored": [], "conflicts": [], "already_rolled_back": True}
    for entry in reversed(manifest.get("entries", [])):
        try:
            if _undo(entry, root, base):
                restored.append(entry["path"])
            if entry["kind"] == "external":
                target = Path(entry["path"])
                for directory in reversed(entry.get("made_dirs", [])):
                    candidate = Path(directory)
                    if not candidate.is_absolute() or ".." in candidate.parts or candidate not in target.parents:
                        raise ValueError("created directory is outside external restoration ancestry")
                    try:
                        with _parent(Path(candidate.anchor), str(candidate.relative_to(candidate.anchor))) as (fd, name):
                            os.rmdir(name, dir_fd=fd)
                    except OSError:
                        pass
        except (OSError, ValueError, KeyError) as exc:
            conflicts.append(f"{entry.get('path', '?')}: unsafe or changed rollback path: {exc}")
    if not conflicts and manifest.get("status") != "failed":
        manifest["status"] = "rolled-back"
        with _parent(base, mf.name) as (fd, name):
            _write(fd, name, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), 0o644)
    return {"project": str(root), "restored": sorted(restored), "conflicts": conflicts}


def find_manifest(project: Path | str, ident: str | None = None, backup_root: Path | str | None = None) -> Path:
    """Resolve the backup folder to roll back: an id, a folder/manifest path, or the latest applied run."""
    from cc.core.project_migrate.apply import default_backup_root

    root = Path(project).expanduser().resolve()
    if ident:
        direct = Path(ident).expanduser()
        if direct.exists():
            return direct
    base = (Path(backup_root).expanduser() if backup_root else default_backup_root()) / root.name
    if ident:
        if (base / ident / MANIFEST).is_file():
            return base / ident
        raise MigrateError("no-manifest", f"no migration backup '{ident}' under {base}")
    runs = sorted(d for d in base.glob("*/") if (d / MANIFEST).is_file()) if base.is_dir() else []
    for d in reversed(runs):
        try:
            m = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if m.get("status") == "applied" and Path(m.get("project", "")).resolve() == root:
            return d
    raise MigrateError("no-manifest", f"no applied migration to roll back for {root} under {base}")
