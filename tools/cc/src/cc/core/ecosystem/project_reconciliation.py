"""Read-only project census and exact reconciliation plan composition.

The integration inspector remains authoritative for component evidence.  This
module adds only the orchestration facts it does not own: explicit selection,
Git stability, exclusion, independent component routes, recommendations, and
a schema-shaped preservation dossier.  It never writes a project or machine
state.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from cc.core.config import resolve_key
from cc.core.ecosystem.project_integration import inspect_project_integration
from cc.core.ecosystem.project_locking import (
    ProjectIdentity,
    ProjectIdentityMismatch,
    fingerprint_file_payload,
    fingerprint_symlink,
    inspect_project_identity,
)
from cc.core.ecosystem.reconciliation_recipes import (
    DEFAULT_RECIPE_REGISTRY,
    RecipePlan,
    RecipeValidationError,
    allowed_targets_for_components,
    authoritative_source_available,
    build_recipe_plan,
)
from cc.core.ecosystem.reconciliation_types import (
    SUPPORTED_COMPONENTS,
    ComponentAssessment,
    ComponentRoute,
    Evidence,
    ProjectAssessment,
    ProjectDossier,
    ProjectPresence,
    ProjectRoute,
)
from cc.core.ecosystem.repository_scope import (
    RepositoryScope,
    managed_ecosystem_repositories,
)
from cc.core.ecosystem.workspaces import discover_workspaces, is_project_excluded


class ProjectReconciliationError(ValueError):
    """A census selection is invalid or no longer matches inspected evidence."""


_PROHIBITED_ACTIONS = (
    "overwrite-project-instructions",
    "delete-project-capabilities",
    "rename-project-capabilities",
    "flatten-project-model",
    "modify-verified-component",
    "follow-external-symlink",
    "run-arbitrary-shell",
    "apply-arbitrary-patch",
    "trust-assistant-self-report",
    "skip-fresh-verification",
)

_PRESERVATION_PATHS = (
    "CLAUDE.md",
    "AGENTS.md",
    ".mcp.json",
    ".codex-copilot.json",
    "copilot.lock.json",
    "copilot.project.json",
    ".copilot/project-owner.json",
    ".claude/agents",
    ".claude/skills",
    ".claude/commands",
    ".claude/cc/config.json",
    ".claude/memory",
    ".agents/agents",
    ".agents/skills",
    ".agents/commands",
    ".agents/plugins/marketplace.json",
    "plugins",
    "scripts/copilot-gate.sh",
    "SOUL.md",
    "docs/01-architecture/12-architecture-guiding-principles.md",
    "docs/40-initiatives",
)

_ACTOR = {
    ComponentRoute.READY: "none",
    ComponentRoute.NOT_PRESENT: "person",
    ComponentRoute.NOT_SELECTED: "person",
    ComponentRoute.SAFE_SETUP_AVAILABLE: "cli",
    ComponentRoute.SAFE_UPDATE_AVAILABLE: "cli",
    ComponentRoute.CUSTOMIZED_GUIDED_ROUTE: "project-author",
    ComponentRoute.HELD: "project-author",
    ComponentRoute.OWNER_DECISION: "project-owner",
    ComponentRoute.COULD_NOT_VERIFY: "person",
    ComponentRoute.EXCLUDED: "person",
    ComponentRoute.SOURCE_UNAVAILABLE: "ecosystem-owner",
    ComponentRoute.NOT_APPLICABLE: "none",
}

_MANAGED_OUTPUT_TARGET_KINDS = {
    "claude": {
        "CLAUDE.md": "managed-text",
        ".mcp.json": "merged-json",
        "copilot.project.json": "merged-json",
    },
    "codex": {
        "AGENTS.md": "managed-text",
        ".codex-copilot.json": "merged-json",
        ".claude/skills/codex-copilot": "internal-symlink",
        "copilot.project.json": "merged-json",
    },
}


def _opaque_id(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_path(value: Path | str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ProjectReconciliationError("Project census paths must be absolute.")
    try:
        return candidate.resolve(strict=False)
    except OSError as exc:
        raise ProjectReconciliationError(
            "A selected project path could not be resolved."
        ) from exc


def _approved_roots(roots: Sequence[Path | str] | None) -> tuple[Path, ...]:
    raw: Any = roots
    if raw is None:
        raw = resolve_key("projects.roots") or []
    if isinstance(raw, (str, Path)):
        raw = [raw]
    return tuple(dict.fromkeys(_canonical_path(item) for item in raw))


def _canonical_selections(
    selections: Mapping[str, Sequence[str]] | None,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for raw_path, raw_components in (selections or {}).items():
        path = str(_canonical_path(raw_path))
        requested = tuple(raw_components)
        if (
            not requested
            or any(component not in SUPPORTED_COMPONENTS for component in requested)
            or len(requested) != len(set(requested))
            or path in result
        ):
            raise ProjectReconciliationError(
                "Every selected project needs a unique explicit Claude/Codex selection."
            )
        components = tuple(
            component for component in SUPPORTED_COMPONENTS if component in requested
        )
        result[path] = components
    return result


def _under_root(project: Path, root: Path) -> bool:
    try:
        project.relative_to(root)
    except ValueError:
        return False
    return True


def _project_root(project: Path, roots: Sequence[Path]) -> Path:
    matches = [root for root in roots if _under_root(project, root)]
    return max(matches, key=lambda item: len(item.parts)) if matches else project


def _git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    return subprocess.run(
        ("git", *arguments),
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _status_path(value: bytes) -> str:
    try:
        decoded = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProjectIdentityMismatch("A Git status path is not valid UTF-8.") from exc
    pure = PurePosixPath(decoded)
    if (
        not decoded
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in decoded
        or pure.as_posix() != decoded
    ):
        raise ProjectIdentityMismatch("A Git status path is unsafe.")
    return decoded


def _parse_porcelain_status(payload: bytes) -> tuple[str, ...]:
    if not payload:
        return ()
    if not payload.endswith(b"\0"):
        raise ProjectIdentityMismatch("Git status output is incomplete.")
    fields = payload[:-1].split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise ProjectIdentityMismatch("Git status output is malformed.")
        try:
            status = record[:2].decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise ProjectIdentityMismatch("Git status output is malformed.") from exc
        if any(code not in " MADRCU?!" for code in status):
            raise ProjectIdentityMismatch("Git status output uses an unknown state.")
        paths.append(_status_path(record[3:]))
        if "R" in status or "C" in status:
            if index >= len(fields):
                raise ProjectIdentityMismatch("Git rename status is incomplete.")
            paths.append(_status_path(fields[index]))
            index += 1
    if len(paths) != len(set(paths)):
        raise ProjectIdentityMismatch("Git status repeats a project path.")
    return tuple(paths)


def _git_state(
    project: Path,
) -> tuple[bool, bool, tuple[str, ...] | None, list[Evidence]]:
    environment = os.environ.copy()
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    status = subprocess.run(
        (
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ),
        cwd=project,
        env=environment,
        capture_output=True,
        text=False,
        check=False,
    )
    if status.returncode != 0:
        raise ProjectIdentityMismatch("The Git working tree could not be inspected.")
    try:
        dirty_paths: tuple[str, ...] | None = _parse_porcelain_status(status.stdout)
    except ProjectIdentityMismatch:
        dirty_paths = None
    dirty = dirty_paths is None or bool(dirty_paths)
    symbolic = _git(project, "symbolic-ref", "-q", "HEAD")
    if symbolic.returncode not in (0, 1):
        raise ProjectIdentityMismatch("The Git branch state could not be inspected.")
    detached = symbolic.returncode == 1
    evidence: list[Evidence] = [
        {
            "id": "git-working-tree",
            "state": "dirty" if dirty else "clean",
            "detail": (
                (
                    "Git status could not be parsed into safe project-relative paths."
                    if dirty_paths is None
                    else "Git reports tracked or untracked working-tree changes."
                )
                if dirty
                else "Git reports a clean working tree."
            ),
        },
        {
            "id": "git-head",
            "state": "detached" if detached else "attached",
            "detail": (
                "Git HEAD is detached."
                if detached
                else "Git HEAD is attached to a branch."
            ),
        },
    ]
    return dirty, detached, dirty_paths, evidence


def _safe_lock_path(relative: Any) -> str | None:
    if not isinstance(relative, str) or not relative:
        return None
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "\\" in relative
        or pure.as_posix() != relative
        or any(ord(character) < 32 or ord(character) == 127 for character in relative)
    ):
        return None
    return relative


def _anchored_leaf(project: Path, relative: str) -> tuple[str, bytes | str, int] | None:
    """Read one project leaf without following any project-relative symlink."""
    safe = _safe_lock_path(relative)
    if safe is None:
        return None
    parts = PurePosixPath(safe).parts
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(project, directory_flags)
        descriptors.append(current)
        for part in parts[:-1]:
            current = os.open(part, directory_flags | nofollow, dir_fd=current)
            descriptors.append(current)
        metadata = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            return "symlink", os.readlink(parts[-1], dir_fd=current), mode
        if not stat.S_ISREG(metadata.st_mode):
            return None
        leaf = os.open(parts[-1], flags | nofollow, dir_fd=current)
        descriptors.append(leaf)
        verified = os.fstat(leaf)
        if not stat.S_ISREG(verified.st_mode):
            return None
        chunks: list[bytes] = []
        while True:
            chunk = os.read(leaf, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return "file", b"".join(chunks), stat.S_IMODE(verified.st_mode)
    except OSError:
        return None
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _path_fingerprint(project: Path, relative: str) -> str | None:
    leaf = _anchored_leaf(project, relative)
    if leaf is None:
        return None
    kind, payload, mode = leaf
    if kind == "file" and isinstance(payload, bytes):
        return fingerprint_file_payload(payload, mode=mode)
    if kind == "symlink" and isinstance(payload, str):
        return fingerprint_symlink(payload)
    return None


def _framework_checksum(project: Path, relative: str) -> str | None:
    leaf = _anchored_leaf(project, relative)
    if leaf is None or leaf[0] != "file" or not isinstance(leaf[1], bytes):
        return None
    return "sha256:" + hashlib.sha256(leaf[1]).hexdigest()


def _sha256_fingerprint(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _framework_path_allowed(component: str, relative: str) -> bool:
    if component == "claude":
        return relative in {
            ".claude/commands/protocol.md",
            ".claude/commands/continue.md",
            ".claude/fitness-check.sh",
        } or relative.startswith(".claude/agents/")
    return relative == "scripts/copilot-gate.sh" or relative.startswith(
        "plugins/codex-copilot/"
    )


def _canonical_project_declaration(project: Path) -> bool:
    leaf = _anchored_leaf(project, "copilot.project.json")
    if leaf is None or leaf[0] != "file" or not isinstance(leaf[1], bytes):
        return False
    try:
        raw = json.loads(leaf[1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    components = raw.get("components") if isinstance(raw, dict) else None
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != "1.0"
        or not isinstance(components, list)
        or not components
        or any(component not in SUPPORTED_COMPONENTS for component in components)
        or tuple(components)
        != tuple(
            component for component in SUPPORTED_COMPONENTS if component in components
        )
    ):
        return False
    canonical = (json.dumps(raw, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return leaf[1] == canonical


def _dirty_paths_are_repeat_safe(
    project: Path,
    report: Mapping[str, Any],
    dirty_paths: tuple[str, ...] | None,
) -> bool:
    if dirty_paths is None or not dirty_paths:
        return dirty_paths == ()
    ready = {
        str(item.get("component"))
        for item in report.get("components", [])
        if isinstance(item, Mapping) and item.get("classification") == "ready"
    }
    if not ready:
        return False
    try:
        lock_leaf = _anchored_leaf(project, "copilot.lock.json")
        if (
            lock_leaf is None
            or lock_leaf[0] != "file"
            or not isinstance(lock_leaf[1], bytes)
        ):
            return False
        lock = json.loads(lock_leaf[1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(lock, dict)
        or lock.get("schema_version") != "1.0"
        or not isinstance(lock.get("components"), list)
    ):
        return False

    recorded: set[str] = set()
    seen_components: set[str] = set()
    for entry in lock["components"]:
        if not isinstance(entry, Mapping):
            return False
        component = entry.get("component")
        if component not in SUPPORTED_COMPONENTS or component in seen_components:
            return False
        seen_components.add(str(component))
        if component not in ready:
            continue
        files = entry.get("files")
        managed_outputs = entry.get("managed_outputs", [])
        if not isinstance(files, list) or not isinstance(managed_outputs, list):
            return False
        for file_info in files:
            if not isinstance(file_info, Mapping) or set(file_info) != {
                "path",
                "ownership",
                "checksum",
            }:
                return False
            relative = file_info.get("path")
            checksum = file_info.get("checksum")
            if (
                _safe_lock_path(relative) is None
                or file_info.get("ownership") != "framework"
                or not _sha256_fingerprint(checksum)
                or not _framework_path_allowed(str(component), str(relative))
                or relative in recorded
                or _framework_checksum(project, relative) != checksum
            ):
                return False
            recorded.add(str(relative))
        target_kinds = _MANAGED_OUTPUT_TARGET_KINDS[str(component)]
        for output in managed_outputs:
            if not isinstance(output, Mapping) or set(output) != {
                "path",
                "kind",
                "fingerprint",
            }:
                return False
            relative = output.get("path")
            kind = output.get("kind")
            fingerprint = output.get("fingerprint")
            if (
                _safe_lock_path(relative) is None
                or target_kinds.get(relative) != kind
                or not _sha256_fingerprint(fingerprint)
                or relative in recorded
                or _path_fingerprint(project, relative) != fingerprint
            ):
                return False
            if (
                relative == "copilot.project.json"
                and not _canonical_project_declaration(project)
            ):
                return False
            recorded.add(str(relative))

    # Dirty Product-owned files do not invalidate an already complete
    # integration. The locked framework files above still have to match their
    # fingerprints exactly, so this permits read-only verification while work
    # continues without permitting any reconciliation mutation.
    return True


def _component_presence(component: Mapping[str, Any]) -> bool | None:
    classification = str(component.get("classification", "could-not-verify"))
    if classification == "ready" or component.get("recognized_setup") is not None:
        return True
    missing = {
        str(item.get("id"))
        for item in component.get("missing_requirements", [])
        if isinstance(item, Mapping)
    }
    if classification == "safe-finish" and "component-setup" in missing:
        return False
    if classification in {"owner-decision", "could-not-verify"}:
        return None
    return True


def _component_route(
    component: Mapping[str, Any],
    *,
    selected: bool,
    any_selection: bool,
    excluded: bool,
    unstable: bool,
    ready_repeat_safe: bool = False,
) -> ComponentRoute:
    if excluded:
        return ComponentRoute.EXCLUDED
    classification = str(component.get("classification", "could-not-verify"))
    presence = _component_presence(component)
    if classification == "ready":
        route = ComponentRoute.READY
    elif classification == "owner-decision":
        route = ComponentRoute.OWNER_DECISION
    elif classification == "could-not-verify":
        route = ComponentRoute.COULD_NOT_VERIFY
    elif classification == "guided-integration":
        route = (
            ComponentRoute.SAFE_UPDATE_AVAILABLE
            if component.get("recognized_setup") is not None
            else ComponentRoute.CUSTOMIZED_GUIDED_ROUTE
        )
    elif classification == "safe-finish" and presence is False:
        route = (
            ComponentRoute.SAFE_SETUP_AVAILABLE
            if selected
            else (
                ComponentRoute.NOT_SELECTED
                if any_selection
                else ComponentRoute.NOT_PRESENT
            )
        )
    elif classification == "safe-finish":
        route = ComponentRoute.SAFE_UPDATE_AVAILABLE
    else:
        route = ComponentRoute.COULD_NOT_VERIFY
    if unstable and route not in {
        ComponentRoute.NOT_PRESENT,
        ComponentRoute.NOT_SELECTED,
        ComponentRoute.EXCLUDED,
    }:
        if route == ComponentRoute.READY and ready_repeat_safe:
            return route
        return ComponentRoute.HELD
    return route


def _component_evidence(component: Mapping[str, Any]) -> list[Evidence]:
    name = str(component.get("component", "unknown"))
    classification = str(component.get("classification", "could-not-verify"))
    evidence: list[Evidence] = [
        {
            "id": f"{name}-integration-classification",
            "state": classification,
            "detail": f"The authoritative inspector classified {name.title()} as {classification}.",
        }
    ]
    recognized = component.get("recognized_setup")
    if isinstance(recognized, Mapping):
        variant = str(recognized.get("variant_id", "recognized"))
        evidence.append(
            {
                "id": "recognized-setup",
                "state": variant,
                "detail": f"The authoritative inspector recognized {variant}.",
            }
        )
        for item in recognized.get("evidence", []):
            if not isinstance(item, Mapping):
                continue
            path = str(item.get("path", name))
            evidence.append(
                {
                    "id": f"{name}:{item.get('kind', 'evidence')}:{path}",
                    "state": str(item.get("state", "observed")),
                    "detail": str(item.get("detail", "Evidence was observed.")),
                }
            )
    return evidence


def _component_missing(component: Mapping[str, Any]) -> list[Evidence]:
    name = str(component.get("component", "unknown"))
    return [
        {
            "id": f"{name}:{item.get('id', 'requirement')}",
            "state": "missing",
            "detail": str(item.get("detail", "A required item is missing.")),
        }
        for item in component.get("missing_requirements", [])
        if isinstance(item, Mapping)
    ]


def _source_available(component: str) -> bool:
    configured = resolve_key(f"paths.{component}_copilot_root")
    return authoritative_source_available(component, configured)


def _recommendation(
    component: str, route: ComponentRoute, *, present: bool | None
) -> tuple[bool, str]:
    if route in {
        ComponentRoute.COULD_NOT_VERIFY,
        ComponentRoute.OWNER_DECISION,
        ComponentRoute.EXCLUDED,
        ComponentRoute.HELD,
        ComponentRoute.SOURCE_UNAVAILABLE,
        ComponentRoute.NOT_APPLICABLE,
    }:
        return False, "Resolve the named project route before selecting this component."
    recipe_routes = {
        ComponentRoute.NOT_PRESENT,
        ComponentRoute.NOT_SELECTED,
        ComponentRoute.SAFE_SETUP_AVAILABLE,
        ComponentRoute.SAFE_UPDATE_AVAILABLE,
        ComponentRoute.CUSTOMIZED_GUIDED_ROUTE,
    }
    if route in recipe_routes:
        if _source_available(component):
            return (
                True,
                f"An authoritative {component.title()} framework source is configured for the bounded recipe.",
            )
        return (
            False,
            f"No authoritative {component.title()} framework source was verified for the bounded recipe.",
        )
    if present is True:
        return (
            True,
            "Existing project evidence makes preserving this component applicable.",
        )
    return (
        False,
        f"No applicable {component.title()} project evidence was verified.",
    )


def _requires_owner_for_unreadable_config(
    project: Path, component: str, draft: Mapping[str, Any], route: ComponentRoute
) -> bool:
    if component != "codex" or route != ComponentRoute.COULD_NOT_VERIFY:
        return False
    missing = {
        str(item.get("id"))
        for item in draft.get("missing_requirements", [])
        if isinstance(item, Mapping)
    }
    if missing != {"valid-codex-config"}:
        return False
    try:
        metadata = (project / ".codex-copilot.json").lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode)


def _component_next_action(route: ComponentRoute, component: str) -> str:
    label = component.title()
    return {
        ComponentRoute.READY: f"Keep {label} verified; no project change is needed.",
        ComponentRoute.NOT_PRESENT: f"Select {label} only if this project should use it.",
        ComponentRoute.NOT_SELECTED: f"{label} was not selected; leave it unchanged.",
        ComponentRoute.SAFE_SETUP_AVAILABLE: f"Review the bounded {label} setup recipe.",
        ComponentRoute.SAFE_UPDATE_AVAILABLE: f"Review the recognized {label} update recipe.",
        ComponentRoute.CUSTOMIZED_GUIDED_ROUTE: f"Author and review a typed {label} recipe from the dossier.",
        ComponentRoute.HELD: f"Stabilize the Git project before changing {label}.",
        ComponentRoute.OWNER_DECISION: f"Ask the project owner to choose the {label} route.",
        ComponentRoute.COULD_NOT_VERIFY: f"Resolve the unreadable or unsafe {label} evidence.",
        ComponentRoute.EXCLUDED: f"{label} remains unchanged while the project is excluded.",
        ComponentRoute.SOURCE_UNAVAILABLE: f"Restore the verified {label} framework source, then assess again.",
        ComponentRoute.NOT_APPLICABLE: f"{label} project integration does not apply to this ecosystem repository.",
    }[route]


def _project_route(components: Sequence[ComponentAssessment]) -> ProjectRoute:
    states = {ComponentRoute(item["state"]) for item in components}
    for component_route, project_route in (
        (ComponentRoute.EXCLUDED, ProjectRoute.EXCLUDED),
        (ComponentRoute.COULD_NOT_VERIFY, ProjectRoute.COULD_NOT_VERIFY),
        (ComponentRoute.OWNER_DECISION, ProjectRoute.OWNER_DECISION),
        (ComponentRoute.HELD, ProjectRoute.HELD),
        (ComponentRoute.SOURCE_UNAVAILABLE, ProjectRoute.SOURCE_UNAVAILABLE),
        (
            ComponentRoute.CUSTOMIZED_GUIDED_ROUTE,
            ProjectRoute.CUSTOMIZED_GUIDED_ROUTE,
        ),
        (ComponentRoute.SAFE_UPDATE_AVAILABLE, ProjectRoute.SAFE_UPDATE_AVAILABLE),
        (ComponentRoute.SAFE_SETUP_AVAILABLE, ProjectRoute.SAFE_SETUP_AVAILABLE),
    ):
        if component_route in states:
            return project_route
    if states <= {ComponentRoute.NOT_PRESENT, ComponentRoute.NOT_SELECTED}:
        return ProjectRoute.COPILOT_NOT_PRESENT
    return ProjectRoute.READY


def _presence(values: Mapping[str, bool | None]) -> ProjectPresence:
    if any(value is None for value in values.values()):
        return ProjectPresence.UNKNOWN
    present = {name for name, value in values.items() if value}
    if present == {"claude", "codex"}:
        return ProjectPresence.BOTH
    if present == {"claude"}:
        return ProjectPresence.CLAUDE_ONLY
    if present == {"codex"}:
        return ProjectPresence.CODEX_ONLY
    return ProjectPresence.NONE


def _artifact_kind(path: str) -> str:
    pure = PurePosixPath(path)
    if path in {"CLAUDE.md", "AGENTS.md"}:
        return "instruction"
    if "agents" in pure.parts:
        return "agent"
    if "skills" in pure.parts:
        return "skill"
    if "commands" in pure.parts:
        return "command"
    if path.endswith(".json"):
        return "config"
    if "plugins" in pure.parts:
        return "plugin"
    return "project-file"


def _preservation(project: Path, report: Mapping[str, Any]) -> list[dict[str, str]]:
    artifacts: dict[str, dict[str, str]] = {}
    preservation = report.get("preservation", {})
    if isinstance(preservation, Mapping):
        for item in preservation.get("must_preserve", []):
            if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
                continue
            artifacts[item["path"]] = {
                "kind": str(item.get("kind", _artifact_kind(item["path"]))),
                "path": item["path"],
                "detail": str(item.get("detail", "Preserve this existing path.")),
            }
    for relative in _PRESERVATION_PATHS:
        try:
            (project / relative).lstat()
        except FileNotFoundError:
            continue
        except OSError:
            artifacts[relative] = {
                "kind": _artifact_kind(relative),
                "path": relative,
                "detail": "Preserve this path; its metadata could not be read safely.",
            }
        else:
            artifacts[relative] = {
                "kind": _artifact_kind(relative),
                "path": relative,
                "detail": "Preserve this existing project path and its contents.",
            }
    return [artifacts[path] for path in sorted(artifacts)]


def _blocker(code: str, actor: str, evidence: Evidence, action: str) -> dict[str, Any]:
    return {
        "code": code,
        "responsible_actor": actor,
        "evidence": [evidence],
        "next_action": action,
    }


def _next_action(route: ProjectRoute) -> str:
    return {
        ProjectRoute.READY: "No project mutation is needed; retain fresh verification.",
        ProjectRoute.COPILOT_NOT_PRESENT: "Choose any recommended components to create an exact setup plan.",
        ProjectRoute.SAFE_SETUP_AVAILABLE: "Review and confirm the bounded project setup plan.",
        ProjectRoute.SAFE_UPDATE_AVAILABLE: "Review and confirm the recognized update recipe.",
        ProjectRoute.CUSTOMIZED_GUIDED_ROUTE: "Review a project-specific typed recipe against the dossier.",
        ProjectRoute.HELD: "Commit, stash, or otherwise stabilize the project, then assess again.",
        ProjectRoute.OWNER_DECISION: "Obtain the named project-owner decision, then assess again.",
        ProjectRoute.COULD_NOT_VERIFY: "Resolve the named inspection failure without changing the project.",
        ProjectRoute.EXCLUDED: "Leave the project unchanged unless a person removes its exclusion.",
        ProjectRoute.SOURCE_UNAVAILABLE: "Restore the verified framework source once, then assess affected projects again.",
        ProjectRoute.ECOSYSTEM_MANAGED: "Keep this ecosystem repository under ecosystem management; project integration does not apply.",
    }[route]


def _could_not_verify_project(
    project: Path,
    approved_root: Path,
    selected: Sequence[str],
    detail: bool,
    error: Exception,
) -> ProjectAssessment:
    evidence: Evidence = {
        "id": "project-identity",
        "state": "could-not-verify",
        "detail": "The selected folder is not a safely readable Git project root.",
    }
    inspection_id = _opaque_id(
        {
            "project": str(project),
            "root": str(approved_root),
            "selected": list(selected),
            "identity": "could-not-verify",
            "error_type": type(error).__name__,
        }
    )
    components: list[ComponentAssessment] = []
    for component in SUPPORTED_COMPONENTS:
        is_selected = component in selected
        components.append(
            {
                "component": component,
                "state": ComponentRoute.COULD_NOT_VERIFY.value,
                "selected": is_selected,
                "recommended": False,
                "recommendation_reason": "Project identity must be verified before component selection.",
                "responsible_actor": "person",
                "evidence": [evidence],
                "missing_requirements": [evidence],
                "next_action": "Select a readable Git working-tree root.",
                "recipe_options": [],
            }
        )
    result: ProjectAssessment = {
        "path": str(project),
        "root": str(approved_root),
        "name": project.name,
        "scope": {"kind": "product-project"},
        "inspection_id": inspection_id,
        "presence": ProjectPresence.UNKNOWN.value,
        "route": ProjectRoute.COULD_NOT_VERIFY.value,
        "selected_components": list(selected),
        "components": components,
        "blockers": [
            _blocker(
                "unreadable-project-identity",
                "person",
                evidence,
                "Select a readable Git working-tree root and assess again.",
            )
        ],
        "next_action": _next_action(ProjectRoute.COULD_NOT_VERIFY),
    }
    if detail:
        result["dossier"] = {
            "inspection_id": inspection_id,
            "current_evidence": [evidence],
            "missing_requirements": [evidence],
            "preservation": [],
            "allowed_targets": allowed_targets_for_components(
                selected or SUPPORTED_COMPONENTS
            ),
            "prohibited_actions": list(_PROHIBITED_ACTIONS),
            "verification": [
                shlex.join(
                    ["cc", "workspace", "verify", "--project", str(project), "--json"]
                )
            ],
            "stop_conditions": [
                "Stop before any write until project identity is verified.",
                "Stop if the selected path is not the Git working-tree root.",
            ],
        }
    return result


def _ecosystem_managed_project(
    project: Path,
    approved_root: Path,
    scope: RepositoryScope,
) -> ProjectAssessment:
    evidence: Evidence = {
        "id": "ecosystem-repository-identity",
        "state": "verified",
        "detail": "The validated ecosystem manifest and this checkout's Git origin identify the same Copilot repository.",
    }
    inspection_id = _opaque_id(
        {
            "project": str(project),
            "root": str(approved_root),
            "scope": dict(scope),
        }
    )
    components: list[ComponentAssessment] = [
        {
            "component": component,
            "state": ComponentRoute.NOT_APPLICABLE.value,
            "selected": False,
            "recommended": False,
            "recommendation_reason": "Project integration does not apply to a proven ecosystem repository.",
            "responsible_actor": "none",
            "evidence": [evidence],
            "missing_requirements": [],
            "next_action": "Keep this repository under ecosystem management.",
            "recipe_options": [],
        }
        for component in SUPPORTED_COMPONENTS
    ]
    return {
        "path": str(project),
        "root": str(approved_root),
        "name": project.name,
        "scope": dict(scope),
        "inspection_id": inspection_id,
        "presence": ProjectPresence.UNKNOWN.value,
        "route": ProjectRoute.ECOSYSTEM_MANAGED.value,
        "selected_components": [],
        "components": components,
        "blockers": [],
        "next_action": _next_action(ProjectRoute.ECOSYSTEM_MANAGED),
    }


def assess_project(
    project: Path | str,
    *,
    approved_root: Path | str,
    selected_components: Sequence[str] = (),
    detail: bool = True,
) -> ProjectAssessment:
    """Assess one selected path without writing it or machine state."""
    path = _canonical_path(project)
    root = _canonical_path(approved_root)
    selected = tuple(dict.fromkeys(selected_components))
    if any(component not in SUPPORTED_COMPONENTS for component in selected):
        raise ProjectReconciliationError("A component selection is unsupported.")
    try:
        identity: ProjectIdentity = inspect_project_identity(path)
        dirty, detached, dirty_paths, git_evidence = _git_state(path)
        report = inspect_project_integration(path, detail=True)
    except (ProjectIdentityMismatch, OSError, RuntimeError) as exc:
        return _could_not_verify_project(path, root, selected, detail, exc)

    excluded = is_project_excluded(path)
    unstable = dirty or detached
    ready_repeat_safe = (
        dirty
        and not detached
        and _dirty_paths_are_repeat_safe(path, report, dirty_paths)
    )
    underlying = {
        str(item.get("component")): item
        for item in report.get("components", [])
        if isinstance(item, Mapping)
    }
    if set(underlying) != set(SUPPORTED_COMPONENTS):
        return _could_not_verify_project(
            path,
            root,
            selected,
            detail,
            ProjectReconciliationError("Component evidence is incomplete."),
        )

    any_selection = bool(selected)
    preservation = _preservation(path, report)
    eligibility_dossier = {"preservation": preservation}
    presence_values = {
        component: _component_presence(underlying[component])
        for component in SUPPORTED_COMPONENTS
    }
    components: list[ComponentAssessment] = []
    for component in SUPPORTED_COMPONENTS:
        draft = underlying[component]
        is_selected = component in selected
        route = _component_route(
            draft,
            selected=is_selected,
            any_selection=any_selection,
            excluded=excluded,
            unstable=unstable,
            ready_repeat_safe=ready_repeat_safe,
        )
        if _requires_owner_for_unreadable_config(path, component, draft, route):
            route = ComponentRoute.OWNER_DECISION
        recommended, reason = _recommendation(
            component,
            route,
            present=presence_values[component],
        )
        if (
            not recommended
            and route
            in {
                ComponentRoute.SAFE_SETUP_AVAILABLE,
                ComponentRoute.SAFE_UPDATE_AVAILABLE,
                ComponentRoute.CUSTOMIZED_GUIDED_ROUTE,
            }
            and not _source_available(component)
        ):
            route = ComponentRoute.SOURCE_UNAVAILABLE
        component_assessment: ComponentAssessment = {
            "component": component,
            "state": route.value,
            "selected": is_selected,
            "recommended": recommended,
            "recommendation_reason": reason,
            "responsible_actor": _ACTOR[route],
            "evidence": _component_evidence(draft),
            "missing_requirements": _component_missing(draft),
            "next_action": _component_next_action(route, component),
            "recipe_options": [],
        }
        if route == ComponentRoute.CUSTOMIZED_GUIDED_ROUTE and recommended:
            eligible = DEFAULT_RECIPE_REGISTRY.eligible(
                component=component,
                route=route,
                root=path,
                assessment=component_assessment,
                dossier=eligibility_dossier,
            )
            if eligible:
                directly_selectable = [
                    definition
                    for definition in eligible
                    if not definition.assistant_only
                ]
                # An assistant cannot add judgment when exactly one bounded
                # Python recipe is compatible with the inspected evidence.
                # Expose that single recipe directly; preserve assistant-only
                # filtering when multiple safe interpretations exist.
                if not directly_selectable and len(eligible) == 1:
                    directly_selectable = list(eligible)
                component_assessment["recipe_options"] = [
                    {
                        "recipe_id": definition.recipe_id,
                        "component": definition.component,
                        "summary": definition.summary,
                    }
                    for definition in directly_selectable
                ]
            else:
                route = ComponentRoute.OWNER_DECISION
                component_assessment.update(
                    {
                        "state": route.value,
                        "recommended": False,
                        "recommendation_reason": "No reviewed recipe covers every existing customized or conflicting artifact.",
                        "responsible_actor": _ACTOR[route],
                        "next_action": _component_next_action(route, component),
                    }
                )
        components.append(component_assessment)

    route = _project_route(components)
    inspection_id = _opaque_id(
        {
            "integration_inspection_id": report["inspection"]["id"],
            "project_identity": identity.as_dict(),
            "git": {
                "dirty": dirty,
                "detached": detached,
                "dirty_paths": list(dirty_paths) if dirty_paths is not None else None,
                "ready_repeat_safe": ready_repeat_safe,
            },
            "excluded": excluded,
            "selected_components": list(selected),
            "component_routes": [item["state"] for item in components],
        }
    )
    blockers: list[dict[str, Any]] = []
    if excluded:
        blockers.append(
            _blocker(
                "project-excluded",
                "person",
                {
                    "id": "exclusion-registry",
                    "state": "excluded",
                    "detail": "The machine-local exclusion registry contains this project.",
                },
                "Remove the exclusion only after a person explicitly opts in.",
            )
        )
    if dirty and not ready_repeat_safe:
        blockers.append(
            _blocker(
                "dirty-working-tree",
                "project-author",
                git_evidence[0],
                "Commit, stash, or otherwise stabilize existing changes.",
            )
        )
    if detached:
        blockers.append(
            _blocker(
                "detached-head",
                "project-author",
                git_evidence[1],
                "Attach HEAD to the intended branch before reconciliation.",
            )
        )
    for item in components:
        component_route = ComponentRoute(item["state"])
        if component_route not in {
            ComponentRoute.OWNER_DECISION,
            ComponentRoute.COULD_NOT_VERIFY,
            ComponentRoute.CUSTOMIZED_GUIDED_ROUTE,
            ComponentRoute.SOURCE_UNAVAILABLE,
        }:
            continue
        blockers.append(
            _blocker(
                f"{item['component']}-{component_route.value}",
                item["responsible_actor"],
                item["missing_requirements"][0]
                if item["missing_requirements"]
                else item["evidence"][0],
                item["next_action"],
            )
        )

    result: ProjectAssessment = {
        "path": str(path),
        "root": str(root),
        "name": path.name,
        "scope": {"kind": "product-project"},
        "inspection_id": inspection_id,
        "presence": _presence(presence_values).value,
        "route": route.value,
        "selected_components": list(selected),
        "components": components,
        "blockers": blockers,
        "next_action": _next_action(route),
    }
    if detail:
        current_evidence = [
            *git_evidence,
            *(
                evidence
                for component in components
                for evidence in component["evidence"]
            ),
        ]
        missing_requirements = [
            requirement
            for component in components
            for requirement in component["missing_requirements"]
        ]
        dossier_components = selected or tuple(
            item["component"]
            for item in components
            if ComponentRoute(item["state"])
            not in {
                ComponentRoute.READY,
                ComponentRoute.NOT_SELECTED,
                ComponentRoute.NOT_APPLICABLE,
            }
        )
        dossier: ProjectDossier = {
            "inspection_id": inspection_id,
            "current_evidence": current_evidence,
            "missing_requirements": missing_requirements,
            "preservation": preservation,
            "allowed_targets": list(
                allowed_targets_for_components(
                    dossier_components or SUPPORTED_COMPONENTS
                )
            ),
            "prohibited_actions": list(_PROHIBITED_ACTIONS),
            "verification": [
                shlex.join(
                    ["cc", "workspace", "verify", "--project", str(path), "--json"]
                )
            ],
            "stop_conditions": [
                "Stop if fresh project identity or Git state differs from this inspection.",
                "Stop before changing a target outside the allowed target list.",
                "Stop before changing a preserved project-owned path without a reviewed merge operation.",
                "Stop if fresh independent verification does not classify every targeted component ready.",
            ],
        }
        result["dossier"] = dossier
    return result


def build_project_census(
    *,
    roots: Sequence[Path | str] | None = None,
    selections: Mapping[str, Sequence[str]] | None = None,
    detail: bool = True,
    managed_repositories: Mapping[str, RepositoryScope] | None = None,
) -> list[ProjectAssessment]:
    """Discover every Git project under approved roots and assess it exactly once."""
    approved = _approved_roots(roots)
    selected = _canonical_selections(selections)
    if selected and not approved:
        raise ProjectReconciliationError(
            "Selected projects require at least one explicitly approved root."
        )
    for project in selected:
        if approved and not any(_under_root(Path(project), root) for root in approved):
            raise ProjectReconciliationError(
                "A selected project is outside every explicitly approved root."
            )

    discovered = {
        str(path.resolve()): path.resolve()
        for path in discover_workspaces(
            roots=approved,
            registry=Path("/dev/null"),
        )
    }
    for project in selected:
        discovered.setdefault(project, Path(project))
    managed = dict(
        managed_ecosystem_repositories()
        if managed_repositories is None
        else managed_repositories
    )
    projects: list[ProjectAssessment] = []
    for key in sorted(discovered):
        project = discovered[key]
        approved_root = _project_root(project, approved)
        scope = managed.get(key)
        if scope is not None:
            projects.append(_ecosystem_managed_project(project, approved_root, scope))
            continue
        projects.append(
            assess_project(
                project,
                approved_root=approved_root,
                selected_components=selected.get(key, ()),
                detail=detail,
            )
        )
    return projects


def build_project_plans(
    projects: Sequence[ProjectAssessment],
    selections: Mapping[str, Sequence[str]],
    recipe_ids: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[RecipePlan]]:
    """Return one public and one internal plan for every selected project."""
    selected = _canonical_selections(selections)
    explicit = {
        str(_canonical_path(path)): dict(component_recipe_ids)
        for path, component_recipe_ids in (recipe_ids or {}).items()
    }
    if any(path not in selected for path in explicit):
        raise RecipeValidationError(
            "A recipe id was supplied for a project that was not selected."
        )
    by_path = {str(_canonical_path(project["path"])): project for project in projects}
    if len(by_path) != len(projects):
        raise ProjectReconciliationError("The project census repeats a project path.")

    plans: list[RecipePlan] = []
    for path in sorted(selected):
        try:
            project = by_path[path]
        except KeyError as exc:
            raise ProjectReconciliationError(
                "A selected project is absent from the fresh census."
            ) from exc
        components = selected[path]
        if project.get("scope", {}).get("kind") == "ecosystem-repository":
            raise ProjectReconciliationError(
                "Ecosystem repositories are managed separately and cannot be planned as product projects."
            )
        if tuple(project["selected_components"]) != components:
            raise ProjectReconciliationError(
                "A project selection changed after the census; assess again."
            )
        fresh = assess_project(
            path,
            approved_root=project["root"],
            selected_components=components,
            detail="dossier" in project,
        )
        if fresh != project:
            raise ProjectReconciliationError(
                "Project evidence changed after the census; assess again."
            )
        plans.append(
            build_recipe_plan(
                fresh,
                components,
                explicit_recipe_ids=explicit.get(path),
            )
        )
    return [plan.public_dict() for plan in plans], plans


__all__ = [
    "ProjectReconciliationError",
    "assess_project",
    "build_project_census",
    "build_project_plans",
]
