"""Restore a project from a migration backup manifest."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from cc.core.project_migrate.apply import MANIFEST
from cc.core.project_migrate.model import MigrateError
from cc.core.project_migrate.util import sha256_file


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
    for entry in reversed(manifest.get("entries", [])):
        rel, kind = entry["path"], entry["kind"]
        path = root / rel
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
        if kind in ("deleted", "modified") and "backup" in entry:
            if kind == "deleted" and (path.exists() or path.is_symlink()):
                if sha256_file(path) != entry.get("sha_before"):
                    conflicts.append(f"{rel}: a different file exists, left in place")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.rollback")
            shutil.copy2(base / entry["backup"], tmp)
            os.chmod(tmp, entry.get("mode", 0o644) | 0o200)
            os.replace(tmp, path)
            os.chmod(path, entry.get("mode", 0o644))
            restored.append(rel)
        elif kind == "unlinked" and "link_target" in entry:
            if path.is_symlink() or path.exists():
                conflicts.append(f"{rel}: path exists, left in place")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(entry["link_target"])
            restored.append(rel)
    return {"project": str(root), "restored": sorted(restored), "conflicts": conflicts,
            "note": "Codex trust entry and project registry are not reverted."}
