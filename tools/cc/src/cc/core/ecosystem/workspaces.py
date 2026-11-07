"""Project-folder roots for Control Tower: which folders hold projects, and what they held when approved.

Only the root bookkeeping remains (`cc workspace roots|approve-root|forget-root|decline`). The
activation half of this module (copying framework files into a project, writing its
`copilot.lock.json`, inspecting copies against locks, reverting) was retired with the copy model:
`cc project init` is the one writer and nothing is copied into a project.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from cc.core.config import resolve_key

KNOWN_PROJECTS_FILENAME = "known-projects.json"
_SKIP_DIR_NAMES = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}
)

# Conventional folder names, directly under the user's home directory, worth
# proposing as a one-click "set this as my projects folder" candidate. Never
# widened and never itself a fallback default for `projects.roots` -- see the
# module docstring.
_CANDIDATE_ROOT_NAMES = ("Developer", "Sites", "Projects", "code")


def _is_git_root(path: Path) -> bool:
    try:
        marker = path / ".git"
        return marker.is_dir() or marker.is_file()
    except OSError:
        return False


def _scan_root(root: Path, *, max_depth: int) -> list[Path]:
    found: list[Path] = []

    def walk(current: Path, depth: int) -> None:
        try:
            if _is_git_root(current):
                found.append(current)
                return
            if depth >= max_depth:
                return
            children = sorted(current.iterdir())
        except OSError:
            return
        for child in children:
            try:
                if child.is_symlink() or not child.is_dir():
                    continue
                if child.name in _SKIP_DIR_NAMES or child.name.startswith("."):
                    continue
            except OSError:
                continue
            walk(child, depth + 1)

    walk(root, 0)
    return found


def _configured_root_paths() -> list[Path]:
    """Resolved, deduplicated `projects.roots` config entries. Invalid or
    unreadable entries are skipped, never raised (same fail-open posture as
    the rest of this module)."""
    raw_roots = resolve_key("projects.roots") or []
    if isinstance(raw_roots, str):
        raw_roots = [raw_roots]
    resolved: list[Path] = []
    seen: set[str] = set()
    for value in raw_roots:
        try:
            candidate = Path(str(value)).expanduser().resolve()
        except (OSError, TypeError, ValueError):
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved


def list_configured_roots(*, max_depth: int = 3) -> list[dict[str, Any]]:
    """Every folder currently approved for project discovery, with a count
    of the Git projects found inside it right now."""
    entries = []
    for root in _configured_root_paths():
        try:
            count = len(_scan_root(root, max_depth=max_depth)) if root.is_dir() else 0
        except OSError:
            count = 0
        entries.append({"name": root.name, "path": str(root), "project_count": count})
    return entries


def detect_candidate_roots(*, max_depth: int = 3) -> list[dict[str, Any]]:
    """Conventional folders under the user's home directory that look like a
    projects folder (already contain at least one Git project) and are not
    already an approved root. Offered for one-click approval; never scanned
    or approved automatically. See the module docstring for why this never
    widens to `$HOME` itself."""
    configured = {str(root) for root in _configured_root_paths()}
    home = Path.home()
    candidates: list[dict[str, Any]] = []
    for name in _CANDIDATE_ROOT_NAMES:
        folder = home / name
        try:
            if folder.is_symlink() or not folder.is_dir():
                continue
            resolved = folder.resolve()
        except OSError:
            continue
        if str(resolved) in configured:
            continue
        try:
            found = _scan_root(resolved, max_depth=max_depth)
        except OSError:
            continue
        if not found:
            continue
        candidates.append({"path": str(resolved), "label": name, "project_count": len(found)})
    return candidates


def default_known_projects_registry() -> Path:
    mirrors_root = Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    return mirrors_root.parent / KNOWN_PROJECTS_FILENAME


def read_known_projects_registry(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        raw: Any = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": "1.0", "roots": {}}
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        return {"schema_version": "1.0", "roots": {}}
    raw_roots = raw.get("roots")
    roots: dict[str, list[str]] = {}
    if isinstance(raw_roots, dict):
        for key, value in raw_roots.items():
            if isinstance(key, str) and isinstance(value, list):
                roots[key] = [item for item in value if isinstance(item, str)]
    return {"schema_version": "1.0", "roots": roots}


def record_root_grant(
    root: Path | str,
    *,
    registry: Optional[Path | str] = None,
    max_depth: int = 3,
) -> None:
    """Snapshot every project already inside `root` at the moment it is
    approved. Everything in this snapshot is EXISTING (always asked about);
    anything discovered under this root afterward is NEW (set up
    automatically -- see `workspace_status`). Call once, when a folder is
    newly approved; approving an already-approved folder again should not
    call this again, or a project added between the two approvals would be
    wrongly reclassified as existing."""
    target = Path(registry) if registry is not None else default_known_projects_registry()
    canonical_root = Path(root).expanduser()
    try:
        key = str(canonical_root.resolve())
    except OSError:
        key = str(canonical_root)
    try:
        found = _scan_root(canonical_root, max_depth=max_depth) if canonical_root.is_dir() else []
    except OSError:
        found = []
    snapshot = sorted({str(path.resolve()) for path in found})
    data = read_known_projects_registry(target)
    roots = dict(data["roots"])
    roots[key] = snapshot
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema_version": "1.0", "roots": roots}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def forget_root_grant(root: Path | str, *, registry: Optional[Path | str] = None) -> None:
    """Drop the grant-time snapshot for `root`. Called when a folder is no
    longer watched; approving it again later takes a fresh snapshot rather
    than reusing a stale one."""
    target = Path(registry) if registry is not None else default_known_projects_registry()
    candidate = Path(root).expanduser()
    try:
        key = str(candidate.resolve())
    except OSError:
        key = str(candidate)
    data = read_known_projects_registry(target)
    roots = dict(data["roots"])
    if key in roots:
        del roots[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"schema_version": "1.0", "roots": roots}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


