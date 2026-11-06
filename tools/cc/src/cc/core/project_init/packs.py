"""Derived, untracked pack links: <activatedBy>/skills/<skill> -> packs root."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


def default_packs_root() -> Path:
    return Path.home() / ".copilot" / "current" / "codex-copilot" / "packs"


def link_packs(
    project: Path, active_packs: list[Any], packs_root: Optional[Path] = None
) -> tuple[list[str], list[str]]:
    """Returns (relative link paths present, warnings). Never overwrites real files."""
    root = packs_root or default_packs_root()
    links: list[str] = []
    warnings: list[str] = []
    for pack in active_packs:
        if not isinstance(pack, dict) or not isinstance(pack.get("name"), str):
            continue
        name = pack["name"]
        if "/" in name or name.startswith("."):
            warnings.append(f"pack {name!r}: invalid name")
            continue
        skills = root / name / "skills"
        if not skills.is_dir():
            warnings.append(f"pack {name}: not found under {root}")
            continue
        activated = str(pack.get("activatedBy") or ".")
        base = (project / activated).resolve()
        try:
            base.relative_to(project.resolve())
        except ValueError:
            warnings.append(f"pack {name}: activatedBy escapes the project")
            continue
        dest_dir = base / "skills"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for skill in sorted(p for p in skills.iterdir() if p.is_dir()):
            dest = dest_dir / skill.name
            if dest.is_symlink():
                if os.readlink(dest) != str(skill):
                    dest.unlink()
                    dest.symlink_to(skill)
            elif dest.exists():
                warnings.append(f"{dest.relative_to(project.resolve())}: real path kept")
                continue
            else:
                dest.symlink_to(skill)
            links.append(str(dest.relative_to(project.resolve())))
    return links, warnings
