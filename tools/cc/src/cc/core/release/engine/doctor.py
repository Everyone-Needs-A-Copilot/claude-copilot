"""Release health checks backing `cc doctor --release` (fitness function 1)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import layout, pointer, schema


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


ExtraCheck = Callable[[Path], list[Check]]


def _worktree_links(root: Path) -> list[str]:
    bad = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            if path.is_symlink():
                target = Path(os.path.realpath(path))
                if ".worktrees" in target.parts:
                    bad.append(f"{path} -> {target}")
        dirnames[:] = [d for d in dirnames if not Path(dirpath, d).is_symlink()]
    return bad


def run(
    home: Path | str | None = None, *, extra: list[ExtraCheck] | None = None
) -> list[Check]:
    """Return all checks; callers fail when any `ok` is False."""
    checks: list[Check] = []
    info = pointer.status(home)
    checks.append(Check("pointer", info["present"] and info["error"] != "current is dangling",
                        info["error"] or f"current -> {info['release']}"))
    if not info["present"] or info["error"] == "current is dangling":
        return checks
    root = layout.current_path(home).resolve()
    try:
        manifest = schema.load(root)
        checks.append(Check("release.json", True, manifest.release_id))
    except schema.ReleaseSchemaError as exc:
        checks.append(Check("release.json", False, str(exc)))
        return checks
    broken = []
    for item in manifest.components:
        if item.kind != layout.KIND_RECORD and not (root / item.path).exists():
            broken.append(item.name)
    checks.append(Check("components", not broken, ", ".join(broken) or "all present"))
    live_bad = [
        f"{item.name} -> {os.path.realpath(root / item.path)}"
        for item in manifest.components
        if item.kind == layout.KIND_LIVE and ".worktrees" in Path(os.path.realpath(root / item.path)).parts
    ]
    links = _worktree_links(root) + live_bad
    checks.append(Check("no-worktree-links", not links, "; ".join(links) or "none"))
    checks.append(Check("pointer-not-worktree", ".worktrees" not in root.parts, str(root)))
    for hook in extra or []:  # e.g. Codex cache vs pointer (another stream)
        checks.extend(hook(root))
    return checks
