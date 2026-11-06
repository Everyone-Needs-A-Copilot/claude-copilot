"""Machine-local registry of initialised projects (replaces the projects.roots gate)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional


def default_registry() -> Path:
    return Path.home() / ".copilot" / "registered-projects.json"


def register_project(project: Path, registry: Optional[Path] = None) -> bool:
    path = registry or default_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        projects = [p for p in data.get("projects", []) if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        projects = []
    entry = str(project.resolve())
    if entry in projects:
        return False
    projects.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".registered.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": "1.0", "projects": sorted(projects)}, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return True
