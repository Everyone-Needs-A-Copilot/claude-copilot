"""Shared, closed vocabulary for Python-owned ecosystem reconciliation.

This module deliberately contains no inspection or mutation logic.  It is the
contract seam shared by machine assessment, project planning, the transaction
engine, and the CLI coordinator.  Swift consumes the versioned JSON emitted by
that coordinator and never recreates any of these decisions.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, NotRequired, TypedDict

RECONCILIATION_SCHEMA_VERSION = "1.0"
RECONCILIATION_REQUEST_SCHEMA_VERSION = "1.0"
SUPPORTED_COMPONENTS = ("claude", "codex")


class ProjectPresence(StrEnum):
    NONE = "none"
    CLAUDE_ONLY = "claude-only"
    CODEX_ONLY = "codex-only"
    BOTH = "both"
    UNKNOWN = "unknown"


class ProjectRoute(StrEnum):
    READY = "ready"
    COPILOT_NOT_PRESENT = "copilot-not-present"
    SAFE_SETUP_AVAILABLE = "safe-setup-available"
    SAFE_UPDATE_AVAILABLE = "safe-update-available"
    CUSTOMIZED_GUIDED_ROUTE = "customized-guided-route"
    HELD = "held"
    OWNER_DECISION = "owner-decision"
    COULD_NOT_VERIFY = "could-not-verify"
    EXCLUDED = "excluded"


class ComponentRoute(StrEnum):
    READY = "ready"
    NOT_PRESENT = "not-present"
    NOT_SELECTED = "not-selected"
    SAFE_SETUP_AVAILABLE = "safe-setup-available"
    SAFE_UPDATE_AVAILABLE = "safe-update-available"
    CUSTOMIZED_GUIDED_ROUTE = "customized-guided-route"
    HELD = "held"
    OWNER_DECISION = "owner-decision"
    COULD_NOT_VERIFY = "could-not-verify"
    EXCLUDED = "excluded"


class RecipeOperationKind(StrEnum):
    CREATE_FILE_FROM_SOURCE = "create-file-from-source"
    COPY_FILE_FROM_SOURCE = "copy-file-from-source"
    COPY_TREE_FROM_SOURCE = "copy-tree-from-source"
    APPEND_MANAGED_BLOCK = "append-managed-block"
    MERGE_JSON_KEYS = "merge-json-keys"
    REPLACE_RECOGNIZED_SYMLINK_WITH_COPY = "replace-recognized-symlink-with-copy"
    CREATE_INTERNAL_RELATIVE_SYMLINK = "create-internal-relative-symlink"
    UPSERT_LOCK_COMPONENT = "upsert-lock-component"
    WRITE_PROJECT_DECLARATION = "write-project-declaration"
    ASSOCIATE_PERSONAL_PROJECT = "associate-personal-project"


class Evidence(TypedDict):
    id: str
    state: str
    detail: str


class Blocker(TypedDict):
    code: str
    responsible_actor: str
    evidence: list[Evidence]
    next_action: str


class RecipeOption(TypedDict):
    recipe_id: str
    component: str
    summary: str


class ComponentAssessment(TypedDict):
    component: str
    state: str
    selected: bool
    recommended: bool
    recommendation_reason: str
    responsible_actor: str
    evidence: list[Evidence]
    missing_requirements: list[Evidence]
    next_action: str
    recipe_options: list[RecipeOption]


class ProjectDossier(TypedDict):
    inspection_id: str
    current_evidence: list[Evidence]
    missing_requirements: list[Evidence]
    preservation: list[dict[str, str]]
    allowed_targets: list[str]
    prohibited_actions: list[str]
    verification: list[str]
    stop_conditions: list[str]


class ProjectAssessment(TypedDict):
    path: str
    root: str
    name: str
    inspection_id: str
    presence: str
    route: str
    selected_components: list[str]
    components: list[ComponentAssessment]
    blockers: list[Blocker]
    next_action: str
    dossier: NotRequired[ProjectDossier]


class MachineAssessment(TypedDict):
    state: str
    helper: dict[str, Any]
    frameworks: list[dict[str, Any]]
    configuration: dict[str, Any]
    authentication: dict[str, Any]
    connectivity: dict[str, Any]
    layers: dict[str, Any]
    dependencies: list[dict[str, Any]]
    blockers: list[Blocker]
    next_action: str


@dataclass(frozen=True)
class ProjectSelection:
    path: str
    components: tuple[str, ...]
    recipe_ids: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": self.path,
            "components": list(self.components),
        }
        if self.recipe_ids:
            result["recipe_ids"] = dict(self.recipe_ids)
        return result


@dataclass(frozen=True)
class ReconciliationRequest:
    roots: tuple[str, ...]
    projects: tuple[ProjectSelection, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RECONCILIATION_REQUEST_SCHEMA_VERSION,
            "roots": list(self.roots),
            "projects": [project.as_dict() for project in self.projects],
        }


class RequestValidationError(ValueError):
    """A selection request is malformed before any inspection or mutation."""


_RECIPE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def _absolute_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RequestValidationError(f"{field} must be a non-empty path.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise RequestValidationError(
            f"{field} contains a prohibited control character."
        )
    if not value.startswith("/"):
        raise RequestValidationError(f"{field} must be a literal absolute path.")
    # The request contract is POSIX-only and deliberately does not expand '~'
    # or consult the filesystem. Collapse redundant separators and dot segments
    # so equivalent authority cannot bypass duplicate detection or fingerprints.
    return posixpath.normpath("/" + value.lstrip("/"))


def parse_reconciliation_request(payload: Any) -> ReconciliationRequest:
    """Parse the exact selection contract without touching the filesystem."""
    if not isinstance(payload, dict):
        raise RequestValidationError("The reconciliation request must be an object.")
    if set(payload) != {"schema_version", "roots", "projects"}:
        raise RequestValidationError(
            "The reconciliation request has missing or unsupported fields."
        )
    if payload["schema_version"] != RECONCILIATION_REQUEST_SCHEMA_VERSION:
        raise RequestValidationError(
            "The reconciliation request uses an incompatible schema version."
        )

    raw_roots = payload["roots"]
    if not isinstance(raw_roots, list) or not raw_roots:
        raise RequestValidationError("Select at least one approved project folder.")
    roots = tuple(
        _absolute_path(value, field=f"roots[{index}]")
        for index, value in enumerate(raw_roots)
    )
    if len(roots) != len(set(roots)):
        raise RequestValidationError("The reconciliation request repeats a root.")

    raw_projects = payload["projects"]
    if not isinstance(raw_projects, list) or not raw_projects:
        raise RequestValidationError("Select at least one project.")
    projects: list[ProjectSelection] = []
    for index, raw in enumerate(raw_projects):
        if (
            not isinstance(raw, dict)
            or not set(raw)
            <= {
                "path",
                "components",
                "recipe_ids",
            }
            or not {"path", "components"} <= set(raw)
        ):
            raise RequestValidationError(
                f"projects[{index}] has missing or unsupported fields."
            )
        path = _absolute_path(raw["path"], field=f"projects[{index}].path")
        components = raw["components"]
        if (
            not isinstance(components, list)
            or not components
            or any(item not in SUPPORTED_COMPONENTS for item in components)
            or len(components) != len(set(components))
        ):
            raise RequestValidationError(
                f"projects[{index}].components must explicitly select Claude, Codex, or both."
            )
        canonical_components = tuple(
            component for component in SUPPORTED_COMPONENTS if component in components
        )
        raw_recipe_ids = raw.get("recipe_ids", {})
        if (
            not isinstance(raw_recipe_ids, dict)
            or any(
                component not in canonical_components for component in raw_recipe_ids
            )
            or any(
                not isinstance(recipe_id, str)
                or _RECIPE_ID.fullmatch(recipe_id) is None
                for recipe_id in raw_recipe_ids.values()
            )
        ):
            raise RequestValidationError(
                f"projects[{index}].recipe_ids must map only selected components to bounded reviewed recipe ids."
            )
        recipe_ids = MappingProxyType(
            {
                component: str(raw_recipe_ids[component])
                for component in SUPPORTED_COMPONENTS
                if component in raw_recipe_ids
            }
        )
        projects.append(ProjectSelection(path, canonical_components, recipe_ids))

    if len(projects) != len({project.path for project in projects}):
        raise RequestValidationError("The reconciliation request repeats a project.")
    return ReconciliationRequest(roots, tuple(projects))


def canonical_request_json(request: ReconciliationRequest) -> str:
    return json.dumps(
        request.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


__all__ = [
    "Blocker",
    "ComponentAssessment",
    "ComponentRoute",
    "Evidence",
    "MachineAssessment",
    "ProjectAssessment",
    "ProjectDossier",
    "ProjectPresence",
    "ProjectRoute",
    "ProjectSelection",
    "RECONCILIATION_REQUEST_SCHEMA_VERSION",
    "RECONCILIATION_SCHEMA_VERSION",
    "RecipeOperationKind",
    "ReconciliationRequest",
    "RequestValidationError",
    "SUPPORTED_COMPONENTS",
    "canonical_request_json",
    "parse_reconciliation_request",
]
