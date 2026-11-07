"""Read-only thin project state for central-resolution consumers.

An initialized project has the local wiring for both runtimes. This is not a
machine-health verdict: release health remains ``cc release doctor``. Discovery
uses explicit registrations and approved roots only, never a home-folder census.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from cc.core.project_init.codex_trust import default_codex_config, read_project_trust
from cc.core.project_init.marker import MARKER_FILENAME, MARKER_SCHEMA_VERSION, RUNTIMES
from cc.core.project_init.registry import default_registry, read_registered_projects
from cc.core.project_init.sections import SECTION_BEGIN, SECTION_END


def _linked_folder(path: Path) -> bool:
    return any(p.is_symlink() for p in (path, *path.parents))


def _registered(path: Path) -> tuple[set[str], list[str]]:
    try:
        return set(read_registered_projects(path)), []
    except ValueError as exc:
        return set(), [str(exc)]


def _trust(path: Path) -> tuple[dict, list[str]]:
    try:
        return read_project_trust(path), []
    except (OSError, ValueError):
        return {}, ["Codex settings could not be read. Existing files were preserved."]


def _inspect(root: Path, registered: set[str], trust: dict, errors: list[str]) -> dict[str, Any]:
    issues: list[str] = []
    blocked = list(errors)
    runtimes: list[str] = []
    if _linked_folder(root):
        blocked.append("Choose the actual project folder instead of a linked folder.")
    elif not root.is_dir():
        blocked.append("The project folder is not available.")
    else:
        marker_path = root / MARKER_FILENAME
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            if not isinstance(marker, dict):
                raise ValueError("marker must be an object")
        except FileNotFoundError:
            marker = {}
        except (OSError, ValueError):
            marker = {}
            blocked.append("The project's Copilot settings are unreadable or invalid; ask its owner to review them.")
        declared = marker.get("runtimes")
        if isinstance(declared, list):
            runtimes = [r for r in declared if isinstance(r, str)]
        if marker.get("schema_version") != MARKER_SCHEMA_VERSION or runtimes != list(RUNTIMES):
            issues.append("Connect this project to both Claude and Codex.")
        for name in ("CLAUDE.md", "AGENTS.md"):
            try:
                text = (root / name).read_text(encoding="utf-8", errors="surrogateescape")
            except FileNotFoundError:
                text = ""
            except OSError:
                blocked.append(f"The project's {name} could not be read.")
                continue
            begin, end = text.find(SECTION_BEGIN), text.find(SECTION_END)
            if begin < 0 and end < 0:
                issues.append(f"Add the central Copilot section to {name}, preserving the project's rules.")
            elif begin < 0 or end < begin or text.count(SECTION_BEGIN) != 1 or text.count(SECTION_END) != 1:
                blocked.append(f"The Copilot section in {name} is incomplete; ask the project owner to review it.")
        project_trust = trust.get(str(root))
        if project_trust is None:
            issues.append("Add this project to Codex's trusted projects.")
        elif not isinstance(project_trust, dict) or project_trust.get("trust_level") != "trusted":
            blocked.append("Codex has an existing access decision for this project; review it in Codex before setup.")
        if str(root) not in registered:
            issues.append("Register this project with the central installation.")
    state = "blocked" if blocked else ("needs-init" if issues else "initialized")
    detail = {
        "blocked": "This project needs a review before setup. Existing files were preserved.",
        "needs-init": "Connect this project to Claude and Codex. Its existing rules will be preserved.",
        "initialized": "This project is connected to Claude and Codex. Machine health is checked separately.",
    }[state]
    return {"path": str(root), "name": root.name, "state": state, "detail": detail,
            "can_initialize": state == "needs-init", "runtimes": runtimes, "issues": blocked + issues}


def project_status(
    project: Optional[Path | str] = None,
    *,
    all_projects: bool = False,
    codex_config: Optional[Path | str] = None,
    registry: Optional[Path | str] = None,
) -> dict[str, Any]:
    """Inspect exactly one folder, or registered projects plus approved roots.

    A scoped request never traverses approved roots. The all-project request
    reuses workspace root discovery's depth bound and symlink exclusion.
    """
    from cc.core.config import resolve_key
    from cc.core.ecosystem.workspaces import _scan_root

    registered, errors = _registered(Path(registry) if registry else default_registry())
    trust, trust_errors = _trust(Path(codex_config) if codex_config else default_codex_config())
    errors += trust_errors
    configured = resolve_key("projects.roots") or []
    if isinstance(configured, str):
        configured = [configured]
    roots = list(dict.fromkeys(Path(p).expanduser().absolute() for p in configured if isinstance(p, str)))
    declined = bool(resolve_key("projects.declined"))
    discovery = {"state": "declined" if declined else ("granted" if roots else "not-granted"),
                 "roots": [{"name": root.name, "path": str(root)} for root in roots]}
    if all_projects:
        candidates = {Path(p) for p in registered}
        if not declined:
            for root in roots:
                if _linked_folder(root):
                    errors.append("An approved project folder is now a linked folder; review that folder before discovery.")
                elif root.is_dir():
                    candidates.update(_scan_root(root, max_depth=3))
                else:
                    errors.append("An approved project folder is not available; review that folder before discovery.")
    else:
        candidates = {Path(project or ".").expanduser().absolute()}
    # Do not resolve a symlink before inspection: that would hide an unapproved
    # traversal. Ordinary paths are normalized to match init's canonical keys.
    candidates = {p if _linked_folder(p) else p.resolve() for p in candidates}
    rows = [_inspect(p, registered, trust, errors) for p in sorted(candidates)]
    return {"schema_version": "1.0", "result": "blocked" if errors or any(r["state"] == "blocked" for r in rows) else "ok",
            "projects": rows, "discovery": discovery, "errors": errors}
