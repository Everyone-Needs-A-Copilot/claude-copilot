"""Restore a project from a migration backup manifest."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from cc.core.project_migrate.apply import MANIFEST
from cc.core.project_migrate.model import MigrateError
from cc.core.project_migrate.util import atomic_write, sha256_file


def _restore_file(src: Path, path: Path, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.rollback")
    shutil.copy2(src, tmp)
    os.chmod(tmp, mode | 0o200)
    os.replace(tmp, path)
    os.chmod(path, mode)


def _undo_external(entry: dict[str, Any], base: Path, restored: list[str], conflicts: list[str]) -> None:
    path = Path(entry["path"])
    current = sha256_file(path) if path.is_file() and not path.is_symlink() else None
    if (path.exists() or path.is_symlink()) and current != entry.get("sha_after"):
        conflicts.append(f"{path}: changed since migration, left in place")
    elif entry.get("absent_before"):
        if path.exists() or path.is_symlink():
            path.unlink()
            restored.append(str(path))
    elif current != entry.get("sha_before"):
        _restore_file(base / entry["backup"], path, entry.get("mode", 0o644))
        restored.append(str(path))
    for d in reversed(entry.get("made_dirs", [])):
        try:
            Path(d).rmdir()
        except OSError:
            pass


def rollback_migration(backup_dir: Path | str) -> dict[str, Any]:
    backup = Path(backup_dir).expanduser()
    mf = backup / MANIFEST if backup.is_dir() else backup
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MigrateError("no-manifest", f"cannot read rollback manifest at {mf}: {exc}") from exc
    root = Path(manifest["project"])
    base = mf.parent
    restored: list[str] = []
    conflicts: list[str] = []
    if manifest.get("status") == "rolled-back":
        return {"project": str(root), "restored": [], "conflicts": [], "already_rolled_back": True}
    for entry in reversed(manifest.get("entries", [])):
        rel, kind = entry["path"], entry["kind"]
        path = root / rel
        if kind == "external":
            _undo_external(entry, base, restored, conflicts)
            continue
        if kind == "created-dir":
            try:
                path.rmdir()
            except OSError:
                pass
            continue
        if kind == "created-link":
            if path.is_symlink() and os.readlink(path) == entry.get("link_after"):
                path.unlink()
                if entry.get("link_before") is not None:
                    path.symlink_to(entry["link_before"])
                restored.append(rel)
            elif path.is_symlink() or path.exists():
                conflicts.append(f"{rel}: changed since migration, left in place")
            continue
        if kind == "created":
            if sha256_file(path) == entry.get("sha_after"):
                path.unlink()
                restored.append(rel)
            elif path.exists():
                conflicts.append(f"{rel}: changed since migration, left in place")
            continue
        if kind == "modified" and "sha_after" not in entry:
            # interrupted before the write was recorded: undo whatever may have landed
            if entry.get("absent_before"):
                if path.is_file() and not path.is_symlink():
                    path.unlink()
                    restored.append(rel)
                continue
            if sha256_file(path) == entry.get("sha_before"):
                continue
        elif kind == "modified" and path.exists() and sha256_file(path) != entry.get("sha_after"):
            conflicts.append(f"{rel}: changed since migration, left in place")
            continue
        if kind == "modified" and "link_target" in entry:
            if path.is_symlink():
                continue
            if path.is_file() and sha256_file(path) != entry.get("sha_after"):
                conflicts.append(f"{rel}: changed since migration, left in place")
                continue
            if path.is_file():
                path.unlink()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(entry["link_target"])
            restored.append(rel)
            continue
        if kind in ("deleted", "modified") and "backup" in entry:
            if kind == "deleted" and (path.exists() or path.is_symlink()):
                if sha256_file(path) != entry.get("sha_before"):
                    conflicts.append(f"{rel}: a different file exists, left in place")
                continue
            _restore_file(base / entry["backup"], path, entry.get("mode", 0o644))
            restored.append(rel)
        elif kind == "unlinked" and "link_target" in entry:
            if path.is_symlink() or path.exists():
                conflicts.append(f"{rel}: path exists, left in place")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(entry["link_target"])
            restored.append(rel)
    if not conflicts and manifest.get("status") != "failed":
        manifest["status"] = "rolled-back"
        atomic_write(mf, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), 0o644)
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
