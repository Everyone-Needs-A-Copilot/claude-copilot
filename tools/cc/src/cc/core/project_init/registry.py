"""Machine-local registry of initialised projects (replaces the projects.roots gate)."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Optional


def default_registry() -> Path:
    from cc.core.project_init.homes import copilot_home

    return copilot_home() / "registered-projects.json"


def register_project(project: Path, registry: Optional[Path] = None) -> bool:
    path = registry or default_registry()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive lock around read-modify-write so concurrent inits cannot lose entries.
    with open(path.parent / (path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return _register_locked(project, path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _register_locked(project: Path, path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        projects = [p for p in data.get("projects", []) if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        projects = []
    entry = str(project.resolve())
    if entry in projects:
        return False
    projects.append(entry)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".registered.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": "1.0", "projects": sorted(projects)}, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return True
