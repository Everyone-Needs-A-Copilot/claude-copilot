"""`--scan ROOTS`: how many copied framework files and locks does each project still carry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from cc.core.project_migrate.known import CODEX_LOCK_FILE, LOCK_FILE, Known, build_known, read_lock
from cc.core.project_migrate.model import MigrateError
from cc.core.project_migrate.planner import SETTINGS, plan_migration
from cc.core.project_migrate.source_guard import SOURCE_LABEL
from cc.core.project_migrate.settings_hooks import strip_framework_hooks

_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".worktrees", ".obsidian"}
_PROJECT_SIGNS = (LOCK_FILE, CODEX_LOCK_FILE, "copilot.project.json", ".claude", ".codex", "plugins/codex-copilot")


def _is_project(p: Path) -> bool:
    return any((p / s).exists() or (p / s).is_symlink() for s in _PROJECT_SIGNS)


def find_projects(roots: Iterable[Path | str], depth: int = 2) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def walk(d: Path, level: int) -> None:
        try:
            real = d.resolve()
        except OSError:
            return
        if real in seen:
            return
        seen.add(real)
        if _is_project(d):
            found.append(d)
            return
        if level >= depth:
            return
        try:
            kids = sorted(c for c in d.iterdir() if c.is_dir() and not c.is_symlink() and c.name not in _SKIP)
        except OSError:
            return
        for c in kids:
            walk(c, level + 1)

    for r in roots:
        walk(Path(r).expanduser(), 0)
    return found


def scan_project(project: Path, known: Known, release_dir: Optional[Path | str] = None) -> dict[str, Any]:
    """Counts come from the planner's own decisions, so scan and migrate cannot disagree."""
    locks = [n for n in (LOCK_FILE, CODEX_LOCK_FILE) if (project / n).exists()]
    lock = read_lock(project)
    try:
        plan = plan_migration(project, known=known, allow_missing_codex=True, release_dir=release_dir)
        copied = sorted(a.path for a in plan.actions if a.detail.get("copy"))
        protected = sum(1 for k in plan.keeps if k.reason.startswith(SOURCE_LABEL))
    except MigrateError:
        copied, protected = [], 0
    hook_regs = 0
    sp = project / SETTINGS
    if sp.is_file():
        try:
            text = sp.read_text(encoding="utf-8")
            hook_regs = strip_framework_hooks(text, lock)[1]
        except (OSError, UnicodeError):
            pass
    return {"project": str(project), "locks": locks, "copied_files": len(copied), "copied_paths": copied, "protected": protected,
            "hook_registrations": hook_regs, "clean": not locks and not copied and hook_regs == 0}


def scan_projects(roots: Iterable[Path | str], *, known: Optional[Known] = None, depth: int = 2) -> dict[str, Any]:
    kn = known or build_known()
    rows = [scan_project(p, kn) for p in find_projects(roots, depth)]
    return {
        "projects": rows,
        "total": len(rows),
        "clean": sum(1 for r in rows if r["clean"]),
        "lock_files": sum(len(r["locks"]) for r in rows),
        "copied_files": sum(r["copied_files"] for r in rows),
        "protected": sum(r["protected"] for r in rows),
        "hook_registrations": sum(r["hook_registrations"] for r in rows),
    }
