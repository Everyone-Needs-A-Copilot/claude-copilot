"""The one classifier for copied framework files: the planner decides and `--scan` counts with this."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional

from cc.core.ecosystem.project_ownership import declares_project_owner
from cc.core.project_migrate.known import Known

SCAN_ROOTS = (".claude", ".codex", ".agents", "plugins", "scripts")
_SKIP_DIRS = {".git", ".venv", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__", ".obsidian"}
_NEVER = (".claude/memory", ".claude/cc", ".claude/worktrees", ".claude/settings.json",
          ".claude/settings.local.json", ".codex/hooks.json")


def _excluded(rel: str) -> bool:
    return any(rel == n or rel.startswith(n + "/") for n in _NEVER)


def candidates(root: Path) -> Iterator[str]:
    """Project-relative files and symlinks where a framework copy can sit."""
    for base in SCAN_ROOTS:
        top = root / base
        if top.is_symlink() or not top.is_dir():
            continue
        for dp, dns, fns in os.walk(top):
            dns[:] = sorted(d for d in dns if d not in _SKIP_DIRS)
            for name in sorted(fns + [d for d in dns if (Path(dp) / d).is_symlink()]):
                if name == ".DS_Store":
                    continue
                rel = (Path(dp) / name).relative_to(root).as_posix()
                if not _excluded(rel):
                    yield rel


def classify(root: Path, rel: str, known: Known) -> Optional[tuple[str, str]]:
    """("delete" | "unlink" | "keep-owner", blob id) when `rel` is a content-matched framework copy."""
    index = known.framework_index
    path = root / rel
    if not index or not (path.is_symlink() or path.is_file()):
        return None
    if path.is_symlink() and not path.exists():
        return None  # broken links are pack links: handled by the pack-link step
    blob = index.matches(path)
    if blob is None:
        return None
    if path.is_symlink():
        return "unlink", blob
    return ("keep-owner" if declares_project_owner(path) else "delete"), blob
