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

Discovery is bounded to explicitly configured roots and the existing project
registry. It never scans a home directory or disk implicitly, never follows
symlinks, and never treats an arbitrary ``.claude`` directory as installation
proof.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from cc.core.config import resolve_key
from cc.core.ecosystem.projects import (
    PROJECT_LOCK_FILENAME,
    PROJECT_SCOPED_PRODUCTS,
    _read_registry,
    read_project_lock,
    write_project_lock,
)

PROJECT_DECLARATION_FILENAME = "copilot.project.json"
PERSONAL_PROJECTS_FILENAME = "personal-projects.json"
SUPPORTED_COMPONENTS = ("claude", "codex")
_SKIP_DIR_NAMES = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}
)

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


def _lock_components(project: Path) -> set[str]:
    try:
        raw = json.loads((project / PROJECT_LOCK_FILENAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()
    entries = raw.get("components", []) if isinstance(raw, dict) else []
    if not isinstance(entries, list):
        return set()
    return {
        entry.get("component")
        for entry in entries
        if isinstance(entry, dict) and entry.get("component") in PROJECT_SCOPED_PRODUCTS
    }


def installed_components(project: Path | str) -> list[str]:
    """Return only components proven by explicit framework-owned markers."""
    root = Path(project)
    installed = _lock_components(root)
    try:
        if (root / ".mcp.json").is_file() and (root / ".claude/commands/protocol.md").is_file():
            installed.add("claude")
        metadata = root / ".codex-copilot.json"
        plugin_manifest = root / "plugins/codex-copilot/.codex-plugin/plugin.json"
        if metadata.is_file() and plugin_manifest.is_file():
            installed.add("codex")
    except OSError:
        pass
    return [component for component in SUPPORTED_COMPONENTS if component in installed]


def recommended_components(project: Path | str, *, which: Callable[[str], Optional[str]] = shutil.which) -> list[str]:
    installed = installed_components(project)
    detected = set(installed)
    if which("claude"):
        detected.add("claude")
    if which("codex"):
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
    run: Run = _run,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> dict[str, Any]:
    root = Path(project).expanduser()
    declaration, declaration_error = read_declaration(root)
    installed = installed_components(root)
    declared = list(declaration.get("components", []))
    recommended = recommended_components(root, which=which)
    key = project_id(root, run=run)
    registry_path = Path(personal_registry) if personal_registry is not None else default_personal_registry()
    personal = read_personal_registry(registry_path)
    associated = bool(key and key in personal["projects"])

    if not _is_git_root(root):
        state, detail = "blocked", "This folder is not a project workspace."
    elif declaration_error:
        state, detail = "blocked", declaration_error
    elif declared:
        missing = [component for component in declared if component not in installed]
        if missing:
            state, detail = "activation-required", "Shared Copilot setup is present but is not active on this Mac."
        else:
            state, detail = "ready", "Copilot is ready for this project."
    elif installed:
        state, detail = "ready", "Copilot is ready for this project."
    else:
        state, detail = "setup-available", "Copilot can be set up for this project."

    return {
        "path": str(root.resolve()),
        "name": root.name,
        "project_id": key,
        "state": state,
        "detail": detail,
        "declared_components": declared,
        "installed_components": installed,
        "recommended_components": recommended,
        "personal_profile": {
            "state": "associated" if associated else ("available" if key else "local-only"),
            "project_id": key,
        },
    }


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
    copies = [
        (source / ".claude/commands/protocol.md", project / ".claude/commands/protocol.md"),
        (source / ".claude/commands/continue.md", project / ".claude/commands/continue.md"),
        (source / ".claude/fitness-check.sh", project / ".claude/fitness-check.sh"),
    ]
    copies.extend(
        (source / f".claude/agents/{agent}.md", project / f".claude/agents/{agent}.md")
        for agent in roster
    )
    for src, _dst in copies:
        if not src.is_file():
            raise ActivationError("The Claude Copilot installer is incomplete.")
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
    installed = set(installed_components(root))
    for component in components:
        if component not in installed:
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
