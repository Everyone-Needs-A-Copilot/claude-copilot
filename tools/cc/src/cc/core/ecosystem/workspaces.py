"""Bounded workspace discovery and portable Copilot project declarations.

This module deliberately keeps three kinds of state separate:

* ``copilot.project.json`` is a small, portable, shared declaration committed
  with a project. It says which host frameworks the project expects and never
  contains repository URLs, organization topology, credentials, ranks, or
  machine paths.
* ``copilot.lock.json`` remains the generated per-file installation record
  owned by Component Sync. A declaration is never treated as proof that those
  files were installed.
* the personal-project registry is machine-local and contains only an opaque
  project id plus product names. It is the seam a private personal checkout can
  later hydrate; it is never copied into the shared project automatically.
* the excluded-project registry is machine-local and holds only resolved
  project paths a person asked ``revert`` to stop offering automatic setup
  for. It is never a record of what was removed, only of what to leave alone.

Discovery is bounded to explicitly configured roots and the existing project
registry. It never scans a home directory or disk implicitly, never follows
symlinks, and never treats an arbitrary ``.claude`` directory as installation
proof.

Candidate root DETECTION (``detect_candidate_roots``) is a separate, narrower
operation: it only ever looks at a short, fixed list of conventional folder
names directly under the user's home directory (``~/Developer``, ``~/Sites``,
``~/Projects``, ``~/code``), and only reports one back if it exists and
already contains at least one Git project. It never widens to ``$HOME``
itself (that would reach ``~/Library``, iCloud ``~/Documents``, and
``~/Downloads`` -- see ``_SKIP_DIR_NAMES``'s silence on those names -- and
would trip macOS privacy prompts) and it never becomes a configured root by
itself; a person still approves one explicitly via ``approve-root``.

NOTE ON ``setup_policy`` (2026-07-24, superseded below): distinguishing a
project that already existed when its root was approved (always ``"ask"``)
from one created since (``"automatic"``, per the adopt-and-project-setup
spec) needed a persisted "known projects as of grant time" record. That
record now exists -- see ``KNOWN_PROJECTS_FILENAME`` and
``record_root_grant`` -- and ``workspace_status`` uses it below.

Two more machine-local, non-secret registries live next to it, same
directory, same posture as ``PERSONAL_PROJECTS_FILENAME`` /
``EXCLUDED_PROJECTS_FILENAME`` above:

* ``KNOWN_PROJECTS_FILENAME`` (``~/.copilot/known-projects.json``) --
  written once per approved root, at the moment it is approved
  (``record_root_grant``), holding every project already inside it at that
  instant. A project already in that snapshot is EXISTING (always
  ``"ask"``, because something of the person's is already there); a
  project discovered under that root afterward is not in the snapshot, so
  it is NEW (``"automatic"``, because there is nothing to protect yet).
  Forgetting a root drops its snapshot (``forget_root_grant``); approving
  it again later takes a fresh one.
* ``AUTOMATIC_SETUPS_FILENAME`` (``~/.copilot/automatic-setups.json``) --
  one entry per project actually set up automatically, written by whoever
  applies that setup (``record_automatic_setup``), read back as the
  "Projects set up for you" list (``recently_set_up``). Entries age out of
  that list after ``RECENTLY_SET_UP_WINDOW_HOURS`` -- this is a rolling
  notice, not a permanent history -- and are dropped immediately on
  ``revert_project`` (``forget_automatic_setup``), since an undone setup
  should stop being announced as done.

Automatic setup additionally holds when the target project's own working
tree already has uncommitted changes (``_has_uncommitted_changes``), even
when nothing collides by filename. This mirrors the system's existing
posture toward silent writes into someone's unsaved work (see Component
Sync's ADR-002, "hold on dirty," applied here to first setup rather than
updates): a fully un-asked act should never land in a tree that already
has real, unsaved content, so it falls back to being asked instead.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from cc.core.config import resolve_key
from cc.core.ecosystem.project_integration import inspect_project_integration
from cc.core.ecosystem.project_sources import resolve_claude_content
from cc.core.ecosystem.projects import (
    PROJECT_LOCK_FILENAME,
    _read_registry,
    read_project_lock,
    write_project_lock,
)
from cc.core.executables import resolve_executable

PROJECT_DECLARATION_FILENAME = "copilot.project.json"
PERSONAL_PROJECTS_FILENAME = "personal-projects.json"
EXCLUDED_PROJECTS_FILENAME = "excluded-projects.json"
KNOWN_PROJECTS_FILENAME = "known-projects.json"
AUTOMATIC_SETUPS_FILENAME = "automatic-setups.json"
INTEGRATION_HOLDS_FILENAME = "project-integration-holds.json"
# How long a completed automatic setup stays in `recently_set_up` before it
# ages out. A rolling "recently" window, not a permanent record.
RECENTLY_SET_UP_WINDOW_HOURS = 168.0
SUPPORTED_COMPONENTS = ("claude", "codex")
_SKIP_DIR_NAMES = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}
)

# Conventional folder names, directly under the user's home directory, worth
# proposing as a one-click "set this as my projects folder" candidate. Never
# widened and never itself a fallback default for `projects.roots` -- see the
# module docstring.
_CANDIDATE_ROOT_NAMES = ("Developer", "Sites", "Projects", "code")

Run = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def _run(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


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


def discover_workspaces(
    *,
    roots: Optional[Iterable[Path | str]] = None,
    registry: Optional[Path | str] = None,
    max_depth: int = 3,
) -> list[Path]:
    """Discover Git workspaces under approved roots plus the explicit registry."""
    if roots is None:
        roots = resolve_key("projects.roots") or []
    if registry is None:
        configured = resolve_key("projects.registry")
        registry_path = Path(str(configured)).expanduser() if configured else None
    else:
        registry_path = Path(registry).expanduser()

    found: dict[str, Path] = {}
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        for candidate in _scan_root(root, max_depth=max_depth):
            try:
                found[str(candidate.resolve())] = candidate.resolve()
            except OSError:
                continue

    for candidate in _read_registry(registry_path):
        try:
            if _is_git_root(candidate):
                found[str(candidate.resolve())] = candidate.resolve()
        except OSError:
            continue
    return [found[key] for key in sorted(found)]


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


def default_excluded_registry() -> Path:
    mirrors_root = Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    return mirrors_root.parent / EXCLUDED_PROJECTS_FILENAME


def read_excluded_registry(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        raw: Any = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": "1.0", "paths": []}
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        return {"schema_version": "1.0", "paths": []}
    paths = raw.get("paths")
    if not isinstance(paths, list):
        paths = []
    return {"schema_version": "1.0", "paths": [str(item) for item in paths if isinstance(item, str)]}


def mark_project_excluded(project: Path | str, *, registry: Path | str) -> None:
    """Record that `project` declined automatic setup, so it stops being
    offered automatically. Never removes or touches the project itself."""
    target = Path(registry)
    data = read_excluded_registry(target)
    resolved = str(Path(project).expanduser().resolve())
    paths = list(dict.fromkeys([*data["paths"], resolved]))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema_version": "1.0", "paths": paths}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def is_project_excluded(project: Path | str, *, registry: Optional[Path | str] = None) -> bool:
    registry_path = Path(registry) if registry is not None else default_excluded_registry()
    data = read_excluded_registry(registry_path)
    try:
        resolved = str(Path(project).expanduser().resolve())
    except OSError:
        return False
    return resolved in data["paths"]


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


def _root_for_project(project: Path, roots: Sequence[Path | str]) -> Optional[Path]:
    """The most specific configured root that contains `project`, if any."""
    resolved_project = project.resolve()
    matches = []
    for raw_root in roots:
        try:
            candidate = Path(raw_root).expanduser().resolve()
        except OSError:
            continue
        if resolved_project == candidate or candidate in resolved_project.parents:
            matches.append(candidate)
    if not matches:
        return None
    return max(matches, key=lambda item: len(item.parts))


def _known_at_grant(
    project: Path,
    *,
    roots: Sequence[Path | str],
    registry: Path | str,
) -> Optional[bool]:
    """True if `project` was already there when its root was approved
    (EXISTING, always asked about); False if it appeared afterward (NEW,
    set up automatically); None if `project` isn't inside any approved
    root, or that root was approved before this tracking existed -- the
    honest "ask" default either way."""
    root = _root_for_project(project, roots)
    if root is None:
        return None
    data = read_known_projects_registry(registry)
    known = data["roots"].get(str(root))
    if known is None:
        return None
    return str(project.resolve()) in set(known)


def _has_uncommitted_changes(project: Path, *, run: Run) -> bool:
    """True if `git status --porcelain` reports anything at all -- staged,
    unstaged, or untracked. Used only to keep automatic (un-asked) setup
    away from a project that already has real, unsaved work in it; never
    applied to the "ask" flow, which the person has already opted into
    explicitly. Fails closed: an unreadable git state is treated as dirty."""
    result = run(("git", "status", "--porcelain"), project)
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def default_automatic_setups_registry() -> Path:
    mirrors_root = Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    return mirrors_root.parent / AUTOMATIC_SETUPS_FILENAME


def read_automatic_setups_registry(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        raw: Any = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": "1.0", "projects": {}}
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        return {"schema_version": "1.0", "projects": {}}
    raw_projects = raw.get("projects")
    projects: dict[str, dict[str, Any]] = {}
    if isinstance(raw_projects, dict):
        for key, value in raw_projects.items():
            if isinstance(key, str) and isinstance(value, dict) and isinstance(value.get("at"), (int, float)):
                projects[key] = {"name": str(value.get("name", "")), "at": float(value["at"])}
    return {"schema_version": "1.0", "projects": projects}


def _prune_automatic_setups(
    projects: dict[str, dict[str, Any]], *, now: float, window_hours: float
) -> dict[str, dict[str, Any]]:
    cutoff = now - window_hours * 3600
    return {path: entry for path, entry in projects.items() if entry["at"] >= cutoff}


def record_automatic_setup(
    project: Path | str,
    *,
    name: str,
    registry: Optional[Path | str] = None,
    now: Optional[float] = None,
    window_hours: float = RECENTLY_SET_UP_WINDOW_HOURS,
) -> None:
    """Record that `project` was just set up without being asked, so it can
    be named in the person's "Projects set up for you" list
    (`recently_set_up`). Entries older than `window_hours` are dropped as
    part of this write."""
    target = Path(registry) if registry is not None else default_automatic_setups_registry()
    current_time = now if now is not None else time.time()
    data = read_automatic_setups_registry(target)
    projects = _prune_automatic_setups(dict(data["projects"]), now=current_time, window_hours=window_hours)
    resolved = str(Path(project).expanduser().resolve())
    projects[resolved] = {"name": name, "at": current_time}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema_version": "1.0", "projects": projects}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def forget_automatic_setup(project: Path | str, *, registry: Optional[Path | str] = None) -> None:
    """Remove `project` from the recent-automatic-setup record, e.g. once
    `revert_project` has undone it -- an undone setup should stop being
    announced as done. Safe to call even if it was never recorded."""
    target = Path(registry) if registry is not None else default_automatic_setups_registry()
    data = read_automatic_setups_registry(target)
    projects = dict(data["projects"])
    resolved = str(Path(project).expanduser().resolve())
    if resolved in projects:
        del projects[resolved]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"schema_version": "1.0", "projects": projects}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def recently_set_up(
    *,
    registry: Optional[Path | str] = None,
    now: Optional[float] = None,
    window_hours: float = RECENTLY_SET_UP_WINDOW_HOURS,
) -> list[dict[str, str]]:
    """The "Projects set up for you" list: one past-tense sentence per
    project set up automatically in the last `window_hours`, newest first.
    Never mutates anything -- safe to call on every status read."""
    target = Path(registry) if registry is not None else default_automatic_setups_registry()
    current_time = now if now is not None else time.time()
    data = read_automatic_setups_registry(target)
    cutoff = current_time - window_hours * 3600
    entries = sorted(
        (entry for entry in data["projects"].values() if entry["at"] >= cutoff),
        key=lambda entry: entry["at"],
        reverse=True,
    )
    return [{"name": entry["name"], "detail": f"Set your copilots up in {entry['name']}."} for entry in entries]


def read_declaration(project: Path | str) -> tuple[dict[str, Any], Optional[str]]:
    path = Path(project) / PROJECT_DECLARATION_FILENAME
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (json.JSONDecodeError, OSError):
        return {}, "The shared Copilot setup file is unreadable."
    if not isinstance(raw, dict):
        return {}, "The shared Copilot setup file must contain an object."
    if raw.get("schema_version") != "1.0":
        return {}, "The shared Copilot setup file uses an unsupported version."
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        return {}, "The shared Copilot setup file has no supported copilots."
    if any(component not in SUPPORTED_COMPONENTS for component in components):
        return {}, "The shared Copilot setup file names an unsupported copilot."
    if len(components) != len(set(components)):
        return {}, "The shared Copilot setup file contains duplicate copilots."
    return {"schema_version": "1.0", "components": components}, None


def write_declaration(project: Path | str, components: Sequence[str]) -> None:
    target = Path(project) / PROJECT_DECLARATION_FILENAME
    payload = {"schema_version": "1.0", "components": list(components)}
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def installed_components(project: Path | str) -> list[str]:
    """Return only components that pass the authoritative integration contract."""
    report = inspect_project_integration(project, detail=False)
    return list(report["verified_components"])


def recommended_components(
    project: Path | str,
    *,
    which: Callable[[str], Optional[str]] | None = None,
    _installed: Optional[Sequence[str]] = None,
) -> list[str]:
    installed = list(_installed) if _installed is not None else installed_components(project)
    detected = set(installed)

    def installed_path(command: str) -> str | None:
        path = resolve_executable(command)
        return str(path) if path is not None else None

    locator = which or installed_path
    if locator("claude"):
        detected.add("claude")
    if locator("codex"):
        detected.add("codex")
    if not detected:
        detected.update(SUPPORTED_COMPONENTS)
    return [component for component in SUPPORTED_COMPONENTS if component in detected]


def _normalized_origin(raw: str) -> Optional[str]:
    value = raw.strip()
    if not value:
        return None
    # SCP-like SSH form: user@host:owner/repo.git
    match = re.match(r"^(?:[^@/]+@)?([^:/]+):(.+)$", value)
    if match and "://" not in value:
        host, path = match.groups()
    else:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if not parsed.hostname:
            return None
        host, path = parsed.hostname, parsed.path
    clean_path = path.strip("/")
    if clean_path.endswith(".git"):
        clean_path = clean_path[:-4]
    if not host or not clean_path:
        return None
    return f"{host.lower()}/{clean_path.lower()}"


def project_id(project: Path | str, *, run: Run = _run) -> Optional[str]:
    root = Path(project)
    result = run(("git", "remote", "get-url", "origin"), root)
    if result.returncode != 0:
        return None
    normalized = _normalized_origin(result.stdout)
    if normalized is None:
        return None
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def default_personal_registry() -> Path:
    mirrors_root = Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    return mirrors_root.parent / PERSONAL_PROJECTS_FILENAME


def default_integration_holds_registry() -> Path:
    mirrors_root = Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    return mirrors_root.parent / INTEGRATION_HOLDS_FILENAME


def _integration_hold_key(project: Path | str) -> str:
    resolved = str(Path(project).expanduser().resolve())
    return "sha256:" + hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def read_integration_holds_registry(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        raw: Any = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": "1.0", "holds": {}}
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != "1.0"
        or not isinstance(raw.get("holds"), dict)
    ):
        return {"schema_version": "1.0", "holds": {}}
    holds: dict[str, dict[str, Any]] = {}
    for key, entry in raw["holds"].items():
        if (
            isinstance(key, str)
            and key.startswith("sha256:")
            and isinstance(entry, dict)
            and entry.get("classification") == "owner-decision"
            and isinstance(entry.get("inspection_id"), str)
            and isinstance(entry.get("plan_id"), str)
        ):
            at = entry.get("at")
            holds[key] = {
                "classification": "owner-decision",
                "inspection_id": entry["inspection_id"],
                "plan_id": entry["plan_id"],
                "at": float(at) if isinstance(at, (int, float)) else 0.0,
            }
    return {"schema_version": "1.0", "holds": holds}


def integration_hold(
    project: Path | str, *, registry: Optional[Path | str] = None
) -> Optional[dict[str, Any]]:
    target = (
        Path(registry)
        if registry is not None
        else default_integration_holds_registry()
    )
    return read_integration_holds_registry(target)["holds"].get(
        _integration_hold_key(project)
    )


def record_integration_hold(
    project: Path | str,
    *,
    inspection_id: str,
    plan_id: str,
    registry: Optional[Path | str] = None,
    now: Optional[float] = None,
) -> None:
    """Persist only an opaque, machine-local incomplete owner-decision hold."""
    target = (
        Path(registry)
        if registry is not None
        else default_integration_holds_registry()
    )
    data = read_integration_holds_registry(target)
    holds = dict(data["holds"])
    holds[_integration_hold_key(project)] = {
        "classification": "owner-decision",
        "inspection_id": inspection_id,
        "plan_id": plan_id,
        "at": time.time() if now is None else now,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"schema_version": "1.0", "holds": holds},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def clear_integration_hold(
    project: Path | str, *, registry: Optional[Path | str] = None
) -> None:
    target = (
        Path(registry)
        if registry is not None
        else default_integration_holds_registry()
    )
    data = read_integration_holds_registry(target)
    holds = dict(data["holds"])
    if holds.pop(_integration_hold_key(project), None) is None:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"schema_version": "1.0", "holds": holds},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_personal_registry(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        raw: Any = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": "1.0", "projects": {}}
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        return {"schema_version": "1.0", "projects": {}}
    projects = raw.get("projects")
    if not isinstance(projects, dict):
        projects = {}
    return {"schema_version": "1.0", "projects": projects}


def associate_personal_project(
    project_key: str,
    components: Sequence[str],
    *,
    registry: Path | str,
) -> None:
    target = Path(registry)
    data = read_personal_registry(target)
    projects = dict(data["projects"])
    projects[project_key] = {"components": list(components)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema_version": "1.0", "projects": projects}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def workspace_status(
    project: Path | str,
    *,
    personal_registry: Optional[Path | str] = None,
    exclude_registry: Optional[Path | str] = None,
    known_projects_registry: Optional[Path | str] = None,
    configured_roots: Optional[Sequence[Path | str]] = None,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
    run: Run = _run,
    which: Callable[[str], Optional[str]] | None = None,
    detail: bool = True,
    holds_registry: Optional[Path | str] = None,
) -> dict[str, Any]:
    root = Path(project).expanduser()
    declaration, declaration_error = read_declaration(root)
    integration = inspect_project_integration(
        root,
        claude_root=claude_root,
        codex_root=codex_root,
        detail=detail,
        owner_hold=integration_hold(root, registry=holds_registry) is not None,
    )
    installed = list(integration.pop("verified_components"))
    integration.pop("safe_component_kinds")
    integration.pop("safe_missing_paths")
    declared = list(declaration.get("components", []))
    recommended = recommended_components(root, which=which, _installed=installed)
    key = project_id(root, run=run)
    registry_path = Path(personal_registry) if personal_registry is not None else default_personal_registry()
    personal = read_personal_registry(registry_path)
    associated = bool(key and key in personal["projects"])

    if not _is_git_root(root):
        _force_unverifiable(
            integration, "This folder is not a project workspace."
        )
    elif declaration_error:
        _force_unverifiable(integration, declaration_error)

    classification = integration["classification"]
    if classification == "ready":
        state = "ready"
        status_detail = "Both Claude and Codex passed authoritative project verification."
    elif classification == "safe-finish":
        state = "activation-required" if declared else "setup-available"
        status_detail = (
            "This recognized project layout has one exact, reversible finish available."
        )
    elif classification == "guided-integration":
        state = "blocked"
        status_detail = (
            "Project-owned instructions or capabilities need guided integration."
        )
    elif classification == "owner-decision":
        state = "blocked"
        status_detail = "A prepared integration decision belongs to the project owner."
    else:
        state = "blocked"
        status_detail = "Required project integration evidence could not be verified."

    can_apply_now = bool(
        classification == "safe-finish" and integration["safe_action"]
    )
    apply_blocked_detail: Optional[str] = None
    if not can_apply_now and classification != "ready":
        apply_blocked_detail = status_detail

    excluded = is_project_excluded(root, registry=exclude_registry)
    if classification == "ready":
        setup_policy = "not-offered"
        policy_detail = "Copilot is verified here, so there's nothing to ask."
    elif excluded:
        setup_policy = "excluded"
        policy_detail = "You asked me not to set this project up again."
    elif classification != "safe-finish":
        setup_policy = "not-offered"
        policy_detail = "This project stays unchanged until the named actor completes the route."
    else:
        roots_for_policy = list(configured_roots) if configured_roots is not None else _configured_root_paths()
        known_registry_path = (
            Path(known_projects_registry) if known_projects_registry is not None else default_known_projects_registry()
        )
        existed_at_grant = _known_at_grant(root, roots=roots_for_policy, registry=known_registry_path)
        automatic_kind = (
            integration["safe_action"]
            and integration["safe_action"]["kind"] == "add-missing"
        )
        if (
            existed_at_grant is False
            and can_apply_now
            and automatic_kind
            and not _has_uncommitted_changes(root, run=run)
        ):
            setup_policy = "automatic"
            policy_detail = "This project is new, so I'll set it up for you without asking."
        else:
            setup_policy = "ask"
            policy_detail = "You'll be asked before anything is added here."

    return {
        "path": str(root.resolve()),
        "name": root.name,
        "project_id": key,
        "state": state,
        "detail": status_detail,
        "declared_components": declared,
        "installed_components": installed,
        "recommended_components": recommended,
        "personal_profile": {
            "state": "associated" if associated else ("available" if key else "local-only"),
            "project_id": key,
        },
        "setup_policy": setup_policy,
        "policy_detail": policy_detail,
        "can_apply_now": can_apply_now,
        "apply_blocked_detail": apply_blocked_detail,
        "undo": undo_status(root),
        **integration,
    }


def _force_unverifiable(integration: dict[str, Any], reason: str) -> None:
    """Replace an otherwise inspectable shape with a closed failure boundary."""
    integration["classification"] = "could-not-verify"
    integration["responsible_actor"] = "person"
    integration["safe_action"] = None
    integration["plan_available"] = False
    integration["integration_plan"] = None
    integration["diagnostic"] = None
    for component in integration["components"]:
        component["classification"] = "could-not-verify"
        component["recognized_setup"] = None
        component["missing_requirements"] = [
            {"id": "verifiable-project", "detail": reason}
        ]
        component["responsible_actor"] = "person"
        component["safe_action"] = None


class ActivationError(RuntimeError):
    """A safe, user-actionable project activation blocker."""


def _resolved_framework_root(config_key: str, supplied: Optional[Path | str]) -> Path:
    raw = supplied if supplied is not None else resolve_key(config_key)
    if not raw:
        raise ActivationError("The required Copilot installer is not available on this Mac.")
    return Path(str(raw)).expanduser()


def _claude_plan(project: Path, source: Path) -> tuple[list[tuple[Path, Path]], list[Path]]:
    version_path = source / "VERSION.json"
    try:
        version = json.loads(version_path.read_text(encoding="utf-8"))
        roster = list(version["components"]["agents"]["frameworkAgents"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        raise ActivationError("The Claude Copilot installer is incomplete.")
    roster.append("kc")

    # Ladder resolution (four-tier-topology.md): the protocol and every
    # roster agent resolve nearest-SUBSTANTIVE-tier-wins across personal ->
    # department -> organization -> foundation, per (dimension, item) --
    # never from `source` alone. `source` (the foundation checkout) is
    # still the fallback AND still the sole origin of everything that has
    # no ladder concept: fitness-check.sh, the hook, evals, and the project
    # template are framework scaffolding, not a tiered dimension.
    ladder_items = resolve_claude_content(
        foundation_root=source,
        items={"commands": ("protocol", "continue"), "agents": tuple(roster)},
    )
    copies = [
        (ladder_items[("commands", "protocol")].path, project / ".claude/commands/protocol.md"),
        (ladder_items[("commands", "continue")].path, project / ".claude/commands/continue.md"),
        (source / ".claude/fitness-check.sh", project / ".claude/fitness-check.sh"),
        (source / ".claude/hooks/copilot-hook.sh", project / ".claude/hooks/copilot-hook.sh"),
    ]
    copies.extend(
        (ladder_items[("agents", agent)].path, project / f".claude/agents/{agent}.md")
        for agent in roster
    )
    for src, _dst in copies:
        if not src.is_file():
            raise ActivationError("The Claude Copilot installer is incomplete.")
    # Eval cases travel with the framework like every other owned dimension.
    # Mirrors project_integration.py's _claude_source_files: globbed rather
    # than required, since a framework build predating evals (or a fresh
    # checkout with none yet authored) is not an installer defect.
    evals_dir = source / ".claude/evals"
    if evals_dir.is_dir():
        copies.extend(
            (path, project / path.relative_to(source))
            for path in sorted(evals_dir.rglob("*"))
            if path.is_file()
        )
    template = source / "templates/CLAUDE.template.md"
    if not template.is_file():
        raise ActivationError("The Claude Copilot project template is missing.")
    collisions = [dst for _src, dst in copies if dst.exists()]
    collisions.extend(
        target
        for target in (project / ".mcp.json", project / "CLAUDE.md")
        if target.exists()
    )
    return copies, collisions


def _codex_collisions(project: Path) -> list[Path]:
    targets = (
        project / "plugins/codex-copilot",
        project / ".claude/skills/codex-copilot",
        project / "scripts/copilot-gate.sh",
        project / ".agents/plugins/marketplace.json",
        project / ".codex-copilot.json",
        project / "AGENTS.md",
    )
    return [target for target in targets if target.exists() or target.is_symlink()]


def preflight_activation(
    project: Path | str,
    components: Sequence[str],
    *,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
) -> dict[str, Path]:
    """Validate every selected installer and collision before the first write."""
    root = Path(project).expanduser()
    existing_lock = read_project_lock(root / PROJECT_LOCK_FILENAME)
    if existing_lock and not isinstance(existing_lock.get("components"), list):
        raise ActivationError(
            "This project already uses a different Copilot lock format. Nothing was replaced."
        )
    installed = set(installed_components(root))
    resolved: dict[str, Path] = {}
    collisions: list[Path] = []
    if "claude" in components and "claude" not in installed:
        source = _resolved_framework_root("paths.claude_copilot_root", claude_root)
        _copies, found = _claude_plan(root, source)
        resolved["claude"] = source
        collisions.extend(found)
    if "codex" in components and "codex" not in installed:
        source = _resolved_framework_root("paths.codex_copilot_root", codex_root)
        script = source / "scripts/setup-project.sh"
        if not script.is_file():
            raise ActivationError("The Codex Copilot installer is incomplete.")
        resolved["codex"] = source
        collisions.extend(_codex_collisions(root))
    if collisions:
        raise ActivationError(
            "Existing project setup needs review before Copilot can add shared files. Nothing was changed."
        )
    return resolved


def _activate_codex(project: Path, source: Path, *, run: Run) -> None:
    result = run(
        (
            "bash",
            str(source / "scripts/setup-project.sh"),
            "--project",
            str(project),
            "--name",
            project.name,
            "--description",
            "Project using Copilot Control Tower",
            "--stack",
            "Unknown",
            "--framework-root",
            str(source),
            "--no-tc-init",
        ),
        project,
    )
    if result.returncode != 0:
        raise ActivationError("Codex Copilot could not finish project setup. Existing files were preserved.")


def _activate_claude(project: Path, source: Path) -> None:
    copies, collisions = _claude_plan(project, source)
    if collisions:
        raise ActivationError(
            "Existing project setup needs review before Claude Copilot can add shared files."
        )
    for src, dst in copies:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    (project / ".mcp.json").write_text('{"mcpServers":{}}\n', encoding="utf-8")
    template = (source / "templates/CLAUDE.template.md").read_text(encoding="utf-8")
    replacements = {
        "{{PROJECT_NAME}}": project.name,
        "{{PROJECT_DESCRIPTION}}": "Project using Copilot Control Tower",
        "{{TECH_STACK}}": "Unknown",
        "{{WORKSPACE_ID}}": project.name,
        "{{KNOWLEDGE_STATUS}}": "Inherited from this machine",
        "{{EXTERNAL_SKILLS_STATUS}}": "",
        "{{PROJECT_RULES}}": "Add project-specific rules here.",
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    (project / "CLAUDE.md").write_text(template, encoding="utf-8")
    config = project / ".claude/cc/config.json"
    if not config.exists():
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps(
                {"$schema": "cc-config-v1", "version": 1, "paths": {"knowledge_repo": "@machine"}},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    entries = project / ".claude/memory/entries"
    entries.mkdir(parents=True, exist_ok=True)
    (entries / ".gitkeep").touch(exist_ok=True)
    memory_ignore = project / ".claude/memory/.gitignore"
    if not memory_ignore.exists():
        memory_ignore.write_text("memory.db\nmemory.db-shm\nmemory.db-wal\n", encoding="utf-8")


def activate_components(
    project: Path | str,
    components: Sequence[str],
    *,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
    run: Run = _run,
) -> list[str]:
    """Activate selected products additively after an all-product preflight."""
    root = Path(project).expanduser().resolve()
    resolved = preflight_activation(
        root, components, claude_root=claude_root, codex_root=codex_root
    )
    activated: list[str] = []
    # Codex first: its installer performs its own complete collision preflight
    # before mutation. Claude's copy plan was already checked above.
    if "codex" in resolved:
        _activate_codex(root, resolved["codex"], run=run)
        activated.append("codex")
    if "claude" in resolved:
        _activate_claude(root, resolved["claude"])
        activated.append("claude")
    return activated


def _path_lexists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise ActivationError(
            "A safe-finish target could not be inspected. Nothing was changed."
        )


def _copy_missing_path(
    source: Path,
    target: Path,
    *,
    project: Path,
    created: list[Path],
) -> None:
    """Copy one staged target without replacing anything already present."""
    if not _path_lexists(source):
        raise ActivationError(
            "The staged Copilot setup is incomplete. Nothing was changed."
        )
    if _path_lexists(target):
        if source.is_dir() and not source.is_symlink() and target.is_dir():
            for child in sorted(source.iterdir()):
                _copy_missing_path(
                    child,
                    target / child.name,
                    project=project,
                    created=created,
                )
        return

    missing_parents: list[Path] = []
    parent = target.parent
    while parent != project and not _path_lexists(parent):
        missing_parents.append(parent)
        parent = parent.parent
    for directory in reversed(missing_parents):
        directory.mkdir()
        created.append(directory)

    if source.is_symlink():
        target.symlink_to(
            source.readlink(),
            target_is_directory=source.resolve().is_dir(),
        )
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)
    created.append(target)


def _rollback_safe_finish(
    *,
    project: Path,
    created: Sequence[Path],
    lock_existed: bool,
    lock_before: Optional[bytes],
) -> None:
    lock_path = project / PROJECT_LOCK_FILENAME
    for path in sorted(set(created), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError:
            continue
    try:
        if lock_existed and lock_before is not None:
            lock_path.write_bytes(lock_before)
        elif not lock_existed and (lock_path.exists() or lock_path.is_symlink()):
            lock_path.unlink()
    except OSError:
        pass


def finish_project_integration(
    project: Path | str,
    action_id: str,
    *,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
    run: Run = _run,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one immutable safe-finish action and verify the result.

    The action is re-inspected immediately before mutation.  Every target is
    rendered in an isolated staging directory and copied only when absent.
    Any failure restores the prior lock and removes paths created by this
    attempt.
    """
    root = Path(project).expanduser().resolve()
    before = inspect_project_integration(
        root,
        claude_root=claude_root,
        codex_root=codex_root,
        detail=True,
    )
    action = before.get("safe_action")
    if (
        before.get("classification") != "safe-finish"
        or not isinstance(action, dict)
        or action.get("id") != action_id
    ):
        raise ActivationError(
            "This safe-finish action is stale or no longer applies. The project was re-inspected and left unchanged."
        )

    lock_path = root / PROJECT_LOCK_FILENAME
    lock_existed = _path_lexists(lock_path)
    try:
        lock_before = lock_path.read_bytes() if lock_existed else None
    except OSError:
        raise ActivationError(
            "The project lock could not be backed up. Nothing was changed."
        )

    created: list[Path] = []
    components = list(action["components"])
    kinds = before["safe_component_kinds"]
    missing_paths = before["safe_missing_paths"]
    try:
        with tempfile.TemporaryDirectory(prefix="cc-safe-finish-") as temporary:
            stage = Path(temporary) / root.name
            stage.mkdir()
            if any(
                kinds.get(component) in ("add-missing", "repair-known")
                for component in components
            ):
                if "codex" in components and kinds.get("codex") != "adopt-existing":
                    codex_source = _resolved_framework_root(
                        "paths.codex_copilot_root", codex_root
                    )
                    _activate_codex(stage, codex_source, run=run)
                if "claude" in components and kinds.get("claude") != "adopt-existing":
                    claude_source = _resolved_framework_root(
                        "paths.claude_copilot_root", claude_root
                    )
                    _activate_claude(stage, claude_source)

                for component in components:
                    if kinds.get(component) == "adopt-existing":
                        continue
                    for rel_path in missing_paths.get(component, []):
                        _copy_missing_path(
                            stage / rel_path,
                            root / rel_path,
                            project=root,
                            created=created,
                        )

        write_install_lock(
            root,
            components,
            claude_root=claude_root,
            codex_root=codex_root,
        )
        after = inspect_project_integration(
            root,
            claude_root=claude_root,
            codex_root=codex_root,
            detail=True,
        )
        if after["classification"] != "ready":
            raise ActivationError(
                "The exact finish did not pass independent verification."
            )
        return before, after
    except (ActivationError, OSError, shutil.Error) as exc:
        _rollback_safe_finish(
            project=root,
            created=created,
            lock_existed=lock_existed,
            lock_before=lock_before,
        )
        if isinstance(exc, ActivationError):
            raise
        raise ActivationError(
            "Copilot could not finish this project safely. New writes were rolled back."
        ) from exc


def _checksum(path: Path) -> str:
    if path.is_symlink():
        payload = ("symlink:" + str(path.readlink())).encode("utf-8")
    else:
        payload = path.read_bytes()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_version(source: Path, component: str) -> str:
    try:
        if component == "claude":
            raw = json.loads((source / "VERSION.json").read_text(encoding="utf-8"))
            for key in ("framework", "version", "frameworkVersion"):
                value = raw.get(key)
                if isinstance(value, str) and value:
                    return value
        else:
            raw = json.loads(
                (source / "plugins/codex-copilot/.codex-plugin/plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            value = raw.get("version")
            if isinstance(value, str) and value:
                return value
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return "unknown"


def _installed_framework_files(project: Path, component: str) -> list[dict[str, str]]:
    if component == "claude":
        candidates = [
            project / ".claude/commands/protocol.md",
            project / ".claude/commands/continue.md",
            project / ".claude/fitness-check.sh",
            project / ".claude/hooks/copilot-hook.sh",
            *sorted((project / ".claude/agents").glob("*.md")),
        ]
    else:
        plugin = project / "plugins/codex-copilot"
        candidates = [
            *sorted(path for path in plugin.rglob("*") if path.is_file()),
            project / "scripts/copilot-gate.sh",
        ]
    files = []
    for path in candidates:
        try:
            if not path.is_file():
                continue
            files.append(
                {
                    "path": path.relative_to(project).as_posix(),
                    "ownership": "framework",
                    "checksum": _checksum(path),
                }
            )
        except OSError:
            continue
    return files


def write_install_lock(
    project: Path | str,
    components: Sequence[str],
    *,
    claude_root: Optional[Path | str] = None,
    codex_root: Optional[Path | str] = None,
) -> None:
    """Write/merge the generated ownership lock after installation proof exists."""
    root = Path(project).expanduser().resolve()
    target = root / PROJECT_LOCK_FILENAME
    existing = read_project_lock(target)
    if existing and not isinstance(existing.get("components"), list):
        raise ActivationError(
            "This project already uses a different Copilot lock format. Nothing was replaced."
        )
    entries = [
        entry
        for entry in existing.get("components", [])
        if isinstance(entry, dict) and entry.get("component") not in components
    ]
    integration = inspect_project_integration(
        root,
        claude_root=claude_root,
        codex_root=codex_root,
        detail=False,
    )
    component_reports = {
        item["component"]: item for item in integration["components"]
    }
    for component in components:
        component_report = component_reports.get(component, {})
        recognized = component_report.get("recognized_setup")
        if component_report.get("classification") not in ("ready", "safe-finish") or (
            component_report.get("classification") == "safe-finish"
            and recognized is None
        ):
            raise ActivationError(
                f"{component.title()} Copilot installation proof is missing; the project lock was not written."
            )
        source = _resolved_framework_root(
            f"paths.{component}_copilot_root",
            claude_root if component == "claude" else codex_root,
        )
        version = _source_version(source, component)
        entries.append(
            {
                "component": component,
                "version": version,
                "release_tag": None if version == "unknown" else f"v{version}",
                "files": _installed_framework_files(root, component),
            }
        )
    entries.sort(key=lambda item: str(item.get("component", "")))
    write_project_lock(
        target,
        {"schema_version": "1.0", "components": entries},
    )


class RevertError(RuntimeError):
    """A safe, user-actionable reason revert could not proceed."""


def undo_status(project: Path | str) -> dict[str, Any]:
    """Whether `revert_project` could remove anything right now, and the
    plain reason when it could not. Never mutates anything -- safe to call
    on every status read."""
    root = Path(project).expanduser()
    lock = read_project_lock(root / PROJECT_LOCK_FILENAME)
    entries = lock.get("components", []) if isinstance(lock, dict) else []
    if not isinstance(entries, list) or not entries:
        return {"available": False, "detail": "There's nothing here to undo yet."}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for file_info in entry.get("files", []) or []:
            if not isinstance(file_info, dict):
                continue
            rel_path = file_info.get("path")
            if not isinstance(rel_path, str) or not rel_path:
                continue
            target = root / rel_path
            try:
                if not target.exists() or _checksum(target) != file_info.get("checksum"):
                    return {
                        "available": False,
                        "detail": "You've changed these files since, so I'll leave them alone.",
                    }
            except OSError:
                return {
                    "available": False,
                    "detail": "You've changed these files since, so I'll leave them alone.",
                }
    return {
        "available": True,
        "detail": "Removes only what I added. Your own files are left alone.",
    }


def revert_project(
    project: Path | str,
    *,
    exclude_registry: Optional[Path | str] = None,
    automatic_setups_registry: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Remove only the framework files this Mac's own record proves it
    added, then record the project as excluded from automatic setup. Also
    covers a project that was set up automatically (same lock file, same
    files, same removal path) -- and drops it from `recently_set_up`, since
    an undone setup should stop being announced as done.

    Raises `RevertError` with the plain, user-facing reason (never a
    destructive fallback) when nothing can be safely removed -- either
    because nothing was recorded, or because a recorded file's checksum no
    longer matches what was written (the person edited it since).
    """
    root = Path(project).expanduser().resolve()
    status = undo_status(root)
    if not status["available"]:
        raise RevertError(status["detail"])

    lock_path = root / PROJECT_LOCK_FILENAME
    lock = read_project_lock(lock_path)
    entries = lock.get("components", []) if isinstance(lock, dict) else []
    removed_components: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        component = entry.get("component")
        for file_info in entry.get("files", []) or []:
            if not isinstance(file_info, dict):
                continue
            rel_path = file_info.get("path")
            if not isinstance(rel_path, str) or not rel_path:
                continue
            target = root / rel_path
            try:
                if target.is_file() or target.is_symlink():
                    target.unlink()
            except OSError:
                continue
        if isinstance(component, str):
            removed_components.append(component)

    # Best-effort tidy-up of framework-owned directories this run emptied.
    # Never removes a directory that still holds the person's own files.
    for stray in (
        root / ".claude/agents",
        root / ".claude/commands",
        root / "plugins/codex-copilot",
    ):
        try:
            if stray.is_dir() and not any(stray.iterdir()):
                stray.rmdir()
        except OSError:
            continue

    write_project_lock(lock_path, {"schema_version": "1.0", "components": []})
    registry_path = (
        Path(exclude_registry) if exclude_registry is not None else default_excluded_registry()
    )
    mark_project_excluded(root, registry=registry_path)
    forget_automatic_setup(root, registry=automatic_setups_registry)
    return {
        "removed": sorted(set(removed_components)),
        "kept": [],
        "detail": "Removed. Your own files were left alone, and I won't set this project up again unless you ask.",
    }
