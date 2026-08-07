"""Closed, read-only recipe planning for project reconciliation.

This module describes mutations but never performs them.  Every operation uses
one of the closed :class:`RecipeOperationKind` values, an allowlisted relative
target, an exact before fingerprint, and a small typed payload understood by
the transaction engine.  ``public_dict`` deliberately omits that payload so
the versioned CLI contract remains a reviewable projection rather than an
arbitrary patch or shell executor.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from cc.core.config import resolve_key
from cc.core.ecosystem.project_locking import (
    ProjectIdentity,
    fingerprint_file_payload,
    fingerprint_missing,
    fingerprint_symlink,
    inspect_project_identity,
)
from cc.core.ecosystem.reconciliation_transaction import fingerprint_recipe_source
from cc.core.ecosystem.reconciliation_types import (
    SUPPORTED_COMPONENTS,
    ComponentRoute,
    ProjectAssessment,
    RecipeOperationKind,
)


class RecipeValidationError(ValueError):
    """A recipe is unknown, mismatched, or outside the typed safety boundary."""


_FINGERPRINT_PREFIX = "sha256:"

_COMMON_TARGETS = (
    "copilot.lock.json",
    "copilot.project.json",
)

_COMPONENT_TARGETS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "claude": (
            "CLAUDE.md",
            ".mcp.json",
            ".claude/commands/protocol.md",
            ".claude/commands/continue.md",
            ".claude/fitness-check.sh",
            ".claude/agents",
            ".claude/cc/config.json",
            ".claude/memory/entries/.gitkeep",
            ".claude/memory/.gitignore",
            *_COMMON_TARGETS,
        ),
        "codex": (
            "AGENTS.md",
            "plugins/codex-copilot",
            ".claude/skills/codex-copilot",
            "scripts/copilot-gate.sh",
            ".agents/plugins/marketplace.json",
            ".codex-copilot.json",
            ".claude/cc/config.json",
            ".claude/memory/entries/.gitkeep",
            ".claude/memory/.gitignore",
            "SOUL.md",
            "docs/01-architecture/12-architecture-guiding-principles.md",
            "docs/40-initiatives",
            *_COMMON_TARGETS,
        ),
    }
)

_PAYLOAD_KEYS: Mapping[RecipeOperationKind, frozenset[str]] = MappingProxyType(
    {
        RecipeOperationKind.CREATE_FILE_FROM_SOURCE: frozenset({"source_path", "mode"}),
        RecipeOperationKind.COPY_FILE_FROM_SOURCE: frozenset({"source_path", "mode"}),
        RecipeOperationKind.COPY_TREE_FROM_SOURCE: frozenset({"source_path"}),
        RecipeOperationKind.APPEND_MANAGED_BLOCK: frozenset({"block", "mode"}),
        RecipeOperationKind.MERGE_JSON_KEYS: frozenset({"keys"}),
        RecipeOperationKind.REPLACE_RECOGNIZED_SYMLINK_WITH_COPY: frozenset(
            {"source_path"}
        ),
        RecipeOperationKind.CREATE_INTERNAL_RELATIVE_SYMLINK: frozenset(
            {"link_target"}
        ),
        RecipeOperationKind.UPSERT_LOCK_COMPONENT: frozenset(
            {"component_entry", "replace_ecosystem_lock"}
        ),
        RecipeOperationKind.WRITE_PROJECT_DECLARATION: frozenset({"document"}),
        RecipeOperationKind.ASSOCIATE_PERSONAL_PROJECT: frozenset({"document"}),
    }
)

OPERATION_PAYLOAD_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {kind.value: tuple(sorted(keys)) for kind, keys in _PAYLOAD_KEYS.items()}
)


def allowed_targets_for_components(components: Sequence[str]) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(components))
    if not selected or any(
        component not in SUPPORTED_COMPONENTS for component in selected
    ):
        raise RecipeValidationError(
            "Allowed targets require an explicit closed component selection."
        )
    return tuple(
        dict.fromkeys(
            target for component in selected for target in _COMPONENT_TARGETS[component]
        )
    )


_CLAUDE_BLOCK = (
    "<!-- cc:project-integration:claude:v1:start -->\n"
    "## Claude Copilot\n\n"
    "This project uses the shared Claude Copilot framework. Preserve the "
    "project-specific instructions in this file and the installed `.claude/` "
    "capabilities.\n"
    "<!-- cc:project-integration:claude:v1:end -->\n"
)

_CODEX_BLOCK = (
    "<!-- cc:project-integration:codex:v1:start -->\n"
    "## Codex Copilot\n\n"
    "This project uses the project-local Codex Copilot plugin at "
    "`./plugins/codex-copilot`. Preserve project-specific instructions and "
    "capabilities.\n"
    "<!-- cc:project-integration:codex:v1:end -->\n"
)

_LEGACY_CODEX_GATE_WRAPPER = b'''#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$(cd "${ROOT_DIR}/plugins/codex-copilot" && pwd -P)"
FRAMEWORK_ROOT="$(cd "${PLUGIN_DIR}/../.." && pwd -P)"
SHARED_GATE="${FRAMEWORK_ROOT}/scripts/copilot-gate.sh"

if [[ ! -f "${SHARED_GATE}" ]]; then
  echo "copilot-gate: shared gate not found at ${SHARED_GATE}" >&2
  exit 2
fi

exec bash "${SHARED_GATE}" "$@"
'''


def _canonical_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return _FINGERPRINT_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bytes_hash(payload: bytes) -> str:
    return _FINGERPRINT_PREFIX + hashlib.sha256(payload).hexdigest()


def _target_manifest(path: Path, prefix: str = "") -> list[list[Any]]:
    rows: list[list[Any]] = []
    for child in sorted(path.iterdir(), key=lambda candidate: candidate.name):
        metadata = child.lstat()
        item = f"{prefix}/{child.name}" if prefix else child.name
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISREG(metadata.st_mode):
            rows.append(
                [item, "file", mode, hashlib.sha256(child.read_bytes()).hexdigest()]
            )
        elif stat.S_ISDIR(metadata.st_mode):
            rows.append([item, "directory", mode])
            rows.extend(_target_manifest(child, item))
        elif stat.S_ISLNK(metadata.st_mode):
            rows.append([item, "symlink", mode, str(child.readlink())])
        else:
            raise RecipeValidationError(
                "A reviewed recipe target contains a special file."
            )
    return rows


def _target_fingerprint(path: Path) -> str:
    """Match ``AnchoredProject.fingerprint`` without taking a write-side lock."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return fingerprint_missing()
    except OSError as exc:
        raise RecipeValidationError(
            "A reviewed recipe target could not be fingerprinted."
        ) from exc

    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISLNK(metadata.st_mode):
        try:
            return fingerprint_symlink(str(path.readlink()))
        except OSError as exc:
            raise RecipeValidationError(
                "A reviewed recipe symlink could not be fingerprinted."
            ) from exc
    if stat.S_ISREG(metadata.st_mode):
        try:
            return fingerprint_file_payload(path.read_bytes(), mode=mode)
        except OSError as exc:
            raise RecipeValidationError(
                "A reviewed recipe file could not be fingerprinted."
            ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise RecipeValidationError("A reviewed recipe target is a special file.")
    try:
        return _canonical_hash(["directory", mode, _target_manifest(path)])
    except OSError as exc:
        raise RecipeValidationError(
            "A reviewed recipe directory could not be fingerprinted."
        ) from exc


def _validate_fingerprint(value: str, *, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith(_FINGERPRINT_PREFIX)
        or len(value) != len(_FINGERPRINT_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise RecipeValidationError(f"{field} must be a sha256 fingerprint.")


def _validate_relative_target(component: str, target: str) -> None:
    if component not in SUPPORTED_COMPONENTS:
        raise RecipeValidationError(f"Unsupported recipe component: {component}.")
    pure = PurePosixPath(target)
    if not target or pure.is_absolute() or ".." in pure.parts:
        raise RecipeValidationError("Recipe targets must stay relative to the project.")
    if target not in _COMPONENT_TARGETS[component]:
        raise RecipeValidationError(
            f"Recipe target {target!r} is not allowlisted for {component}."
        )


def _validate_payload(kind: RecipeOperationKind, payload: Mapping[str, Any]) -> None:
    if not isinstance(kind, RecipeOperationKind):
        raise RecipeValidationError("Recipe operation kind is not in the closed set.")
    allowed = _PAYLOAD_KEYS[kind]
    try:
        json.dumps(dict(payload), sort_keys=True, ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise RecipeValidationError(
            "Recipe payloads must contain only JSON-compatible typed values."
        ) from exc
    keys = frozenset(payload)
    required = allowed - {"mode", "replace_ecosystem_lock"}
    if not required <= keys or not keys <= allowed:
        raise RecipeValidationError(
            f"{kind.value} uses missing or unsupported payload keys."
        )
    if "mode" in payload and (
        not isinstance(payload["mode"], int)
        or payload["mode"] < 0
        or payload["mode"] > 0o777
    ):
        raise RecipeValidationError("Recipe file mode must be a bounded integer.")
    if "replace_ecosystem_lock" in payload and payload["replace_ecosystem_lock"] is not True:
        raise RecipeValidationError(
            "The ecosystem-lock replacement marker must be exactly true."
        )
    if "source_path" in payload:
        source = payload["source_path"]
        if not isinstance(source, str) or not Path(source).is_absolute():
            raise RecipeValidationError("Recipe sources must be absolute paths.")
    if "block" in payload and (
        not isinstance(payload["block"], str) or not payload["block"]
    ):
        raise RecipeValidationError("A managed block must be non-empty text.")
    for mapping_key in ("keys", "component_entry", "document"):
        if mapping_key not in payload:
            continue
        value = payload[mapping_key]
        is_component_entries = (
            mapping_key == "component_entry"
            and isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
            and bool(value)
            and all(isinstance(item, Mapping) for item in value)
        )
        if not isinstance(value, Mapping) and not is_component_entries:
            raise RecipeValidationError(
                f"Recipe payload {mapping_key} must be an object."
            )
        if mapping_key == "component_entry":
            entries = list(value) if is_component_entries else [value]
            names = [item.get("component") for item in entries]
            if any(name not in SUPPORTED_COMPONENTS for name in names) or len(
                names
            ) != len(set(names)):
                raise RecipeValidationError(
                    "Lock component entries must be unique supported components."
                )
    if "link_target" in payload:
        link = payload["link_target"]
        pure = PurePosixPath(link) if isinstance(link, str) else None
        if pure is None or not link or pure.is_absolute() or "\x00" in link:
            raise RecipeValidationError(
                "Internal symlink targets must be project-relative and contained."
            )


@dataclass(frozen=True)
class RecipeOperation:
    id: str
    kind: RecipeOperationKind
    component: str
    target: str
    description: str
    expected_before_fingerprint: str
    source_fingerprint: str | None
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if (
            not self.id.startswith("op_")
            or len(self.id) != 67
            or any(character not in "0123456789abcdef" for character in self.id[3:])
        ):
            raise RecipeValidationError("Recipe operation id is not opaque.")
        _validate_relative_target(self.component, self.target)
        if not self.description:
            raise RecipeValidationError("Recipe operations require a description.")
        _validate_fingerprint(
            self.expected_before_fingerprint,
            field="expected_before_fingerprint",
        )
        if self.source_fingerprint is not None:
            _validate_fingerprint(self.source_fingerprint, field="source_fingerprint")
        source_kinds = {
            RecipeOperationKind.CREATE_FILE_FROM_SOURCE,
            RecipeOperationKind.COPY_FILE_FROM_SOURCE,
            RecipeOperationKind.COPY_TREE_FROM_SOURCE,
            RecipeOperationKind.REPLACE_RECOGNIZED_SYMLINK_WITH_COPY,
        }
        if (self.kind in source_kinds) != (self.source_fingerprint is not None):
            raise RecipeValidationError(
                "Recipe source operations require one exact source fingerprint."
            )
        _validate_payload(self.kind, self.payload)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "component": self.component,
            "target": self.target,
            "description": self.description,
            "expected_before_fingerprint": self.expected_before_fingerprint,
            "source_fingerprint": self.source_fingerprint,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.public_dict(), "payload": dict(self.payload)}


@dataclass(frozen=True)
class RecipePlan:
    path: str
    inspection_id: str
    expected_identity: ProjectIdentity
    selected_components: tuple[str, ...]
    recipes: tuple[tuple[str, str], ...]
    sources: tuple[dict[str, str], ...]
    operations: tuple[RecipeOperation, ...]
    preservation: tuple[dict[str, str], ...]
    allowed_targets: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    verification: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not Path(self.path).is_absolute():
            raise RecipeValidationError("Recipe plan path must be absolute.")
        if self.expected_identity.path != self.path:
            raise RecipeValidationError(
                "Recipe plan identity does not match the reviewed project."
            )
        if (
            not self.selected_components
            or any(
                component not in SUPPORTED_COMPONENTS
                for component in self.selected_components
            )
            or len(self.selected_components) != len(set(self.selected_components))
        ):
            raise RecipeValidationError(
                "Recipe plans require unique explicitly selected components."
            )
        _validate_fingerprint(self.inspection_id, field="inspection_id")
        source_components: set[str] = set()
        for source in self.sources:
            component = source.get("component")
            version = source.get("version")
            fingerprint = source.get("fingerprint")
            if (
                component not in self.selected_components
                or component in source_components
                or not isinstance(version, str)
                or not version
                or not isinstance(fingerprint, str)
            ):
                raise RecipeValidationError("Recipe source bindings are invalid.")
            _validate_fingerprint(fingerprint, field="source fingerprint")
            source_components.add(str(component))
        recipe_components = tuple(component for component, _ in self.recipes)
        recipe_ids = tuple(recipe_id for _, recipe_id in self.recipes)
        if (
            not self.recipes
            or len(recipe_components) != len(set(recipe_components))
            or len(recipe_ids) != len(set(recipe_ids))
            or any(
                component not in self.selected_components
                for component in recipe_components
            )
        ):
            raise RecipeValidationError(
                "Recipe plans require one unique component-scoped recipe binding."
            )
        if len(self.operations) != len({operation.id for operation in self.operations}):
            raise RecipeValidationError("Recipe plans repeat an operation id.")
        if len(self.operations) != len(
            {operation.target for operation in self.operations}
        ):
            raise RecipeValidationError(
                "Recipe plans must combine changes to one target into one operation."
            )
        allowed = set(self.allowed_targets)
        if any(operation.target not in allowed for operation in self.operations):
            raise RecipeValidationError(
                "A recipe operation falls outside the dossier target boundary."
            )
        if not self.verification or not self.stop_conditions:
            raise RecipeValidationError(
                "Recipe plans require verification and stop conditions."
            )

    def public_dict(self) -> dict[str, Any]:
        """Return exactly the frozen ``$defs.projectPlan`` projection."""
        return {
            "path": self.path,
            "inspection_id": self.inspection_id,
            "recipes": [
                {"component": component, "recipe_id": recipe_id}
                for component, recipe_id in self.recipes
            ],
            "sources": [dict(source) for source in self.sources],
            "operations": [operation.public_dict() for operation in self.operations],
            "preservation": [dict(item) for item in self.preservation],
            "prohibited_actions": list(self.prohibited_actions),
            "verification": list(self.verification),
        }

    def transaction_spec(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "inspection_id": self.inspection_id,
            "expected_identity": self.expected_identity.as_dict(),
            "selected_components": list(self.selected_components),
            "recipes": [
                {"component": component, "recipe_id": recipe_id}
                for component, recipe_id in self.recipes
            ],
            "sources": [dict(source) for source in self.sources],
            "operations": [operation.as_dict() for operation in self.operations],
            "preservation": [dict(item) for item in self.preservation],
            "allowed_targets": list(self.allowed_targets),
            "prohibited_actions": list(self.prohibited_actions),
            "verification": list(self.verification),
            "stop_conditions": list(self.stop_conditions),
        }

    def transaction_plan(self) -> Any:
        """Adapt lazily so planning has no mutation-engine import cycle."""
        if not self.operations:
            raise RecipeValidationError(
                "A zero-operation reconciliation receipt cannot be executed."
            )
        from cc.core.ecosystem.reconciliation_transaction import (
            transaction_plan_from_recipe,
        )

        return transaction_plan_from_recipe(self)


OperationBuilder = Callable[[Path, str], tuple[RecipeOperation, ...]]
RecipeEligibility = Callable[[Path, Mapping[str, Any], Mapping[str, Any]], bool]


@dataclass(frozen=True)
class RecipeDefinition:
    recipe_id: str
    component: str
    eligible_routes: frozenset[ComponentRoute]
    builder: OperationBuilder
    summary: str = "Apply one reviewed, component-scoped reconciliation strategy."
    eligibility: RecipeEligibility | None = None
    assistant_only: bool = False

    def __post_init__(self) -> None:
        if (
            not self.recipe_id
            or self.component not in SUPPORTED_COMPONENTS
            or not self.summary
        ):
            raise RecipeValidationError("Recipe definitions must be named and scoped.")
        if not self.eligible_routes:
            raise RecipeValidationError("Recipe definitions require an eligible route.")


class RecipeRegistry:
    """Immutable registry of reviewed recipes over a closed operation set."""

    def __init__(self, definitions: Sequence[RecipeDefinition]) -> None:
        by_id: dict[str, RecipeDefinition] = {}
        for definition in definitions:
            if definition.recipe_id in by_id:
                raise RecipeValidationError(
                    f"Duplicate recipe id: {definition.recipe_id}."
                )
            by_id[definition.recipe_id] = definition
        self._definitions: Mapping[str, RecipeDefinition] = MappingProxyType(by_id)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def require(
        self,
        recipe_id: str,
        *,
        component: str,
        route: ComponentRoute,
        root: Path | None = None,
        assessment: Mapping[str, Any] | None = None,
        dossier: Mapping[str, Any] | None = None,
    ) -> RecipeDefinition:
        try:
            definition = self._definitions[recipe_id]
        except KeyError as exc:
            raise RecipeValidationError(
                f"Recipe {recipe_id!r} is not in the reviewed registry."
            ) from exc
        if definition.component != component or route not in definition.eligible_routes:
            raise RecipeValidationError(
                f"Recipe {recipe_id!r} does not apply to {component} {route.value}."
            )
        if definition.eligibility is not None and (
            root is None
            or assessment is None
            or dossier is None
            or not definition.eligibility(root, assessment, dossier)
        ):
            raise RecipeValidationError(
                f"Recipe {recipe_id!r} no longer applies to the reviewed project evidence."
            )
        return definition

    def eligible(
        self,
        *,
        component: str,
        route: ComponentRoute,
        root: Path,
        assessment: Mapping[str, Any],
        dossier: Mapping[str, Any],
    ) -> tuple[RecipeDefinition, ...]:
        """Return stable Python-authored options for one exact component route."""
        return tuple(
            definition
            for definition in self._definitions.values()
            if definition.component == component
            and route in definition.eligible_routes
            and (
                definition.eligibility is None
                or definition.eligibility(root, assessment, dossier)
            )
        )


def _operation(
    *,
    root: Path,
    component: str,
    kind: RecipeOperationKind,
    target: str,
    description: str,
    payload: Mapping[str, Any],
    source: Path | None = None,
) -> RecipeOperation:
    if kind == RecipeOperationKind.CREATE_INTERNAL_RELATIVE_SYMLINK:
        link_value = str(payload.get("link_target", ""))
        stack = list(PurePosixPath(target).parts[:-1])
        for part in PurePosixPath(link_value).parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not stack:
                    raise RecipeValidationError(
                        "An internal recipe link would escape the project."
                    )
                stack.pop()
            else:
                stack.append(part)
    expected = _target_fingerprint(root / target)
    source_fingerprint = None
    if source is not None:
        source_fingerprint = fingerprint_recipe_source(
            source,
            tree=kind
            in {
                RecipeOperationKind.COPY_TREE_FROM_SOURCE,
                RecipeOperationKind.REPLACE_RECOGNIZED_SYMLINK_WITH_COPY,
            },
        )
    stable = {
        "kind": kind.value,
        "component": component,
        "target": target,
        "expected": expected,
        "source": source_fingerprint,
        "payload": payload,
    }
    operation_id = "op_" + _canonical_hash(stable).removeprefix(_FINGERPRINT_PREFIX)
    return RecipeOperation(
        id=operation_id,
        kind=kind,
        component=component,
        target=target,
        description=description,
        expected_before_fingerprint=expected,
        source_fingerprint=source_fingerprint,
        payload=MappingProxyType(dict(payload)),
    )


def validated_source_root(
    component: str, configured: Path | str | None = None
) -> Path:
    """Resolve one configured read-only framework source to a protected root.

    A configured source may be a compatibility symlink (the established
    ``~/.claude/copilot`` install is one), but the resolved directory must be
    owned by root/current user and must not be group- or world-writable. Every
    recipe still fingerprints the exact source bytes and rechecks them during
    execution; this does not relax any target-side symlink boundary.
    """
    if component not in SUPPORTED_COMPONENTS:
        raise RecipeValidationError("The authoritative framework source is unavailable.")
    configured = (
        configured
        if configured is not None
        else resolve_key(f"paths.{component}_copilot_root")
    )
    if not configured:
        raise RecipeValidationError(
            f"The authoritative {component.title()} source is unavailable."
        )
    source = Path(str(configured)).expanduser()
    try:
        resolved = source.resolve(strict=True)
        metadata = resolved.stat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise RecipeValidationError(
                f"The authoritative {component.title()} source is unavailable."
            )
        return resolved
    except OSError as exc:
        raise RecipeValidationError(
            f"The authoritative {component.title()} source is unavailable."
        ) from exc


def _source_root(component: str) -> Path:
    return validated_source_root(component)


def _version(source: Path, component: str) -> str:
    candidate = (
        (source / "VERSION.json", "framework")
        if component == "claude"
        else (
            source / "plugins/codex-copilot/.codex-plugin/plugin.json",
            "version",
        )
    )
    path, key = candidate
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise RecipeValidationError(
            f"The authoritative {component.title()} version is unavailable."
        ) from exc
    value = payload.get(key) if isinstance(payload, dict) else None
    if isinstance(value, str) and value:
        return value
    raise RecipeValidationError(
        f"The authoritative {component.title()} version is unavailable."
    )


def _framework_files(source: Path, component: str) -> list[dict[str, str]]:
    if component == "claude":
        try:
            agents = source / ".claude/agents"
            if agents.is_symlink() or not agents.is_dir():
                raise RecipeValidationError(
                    "The authoritative Claude file roster is unavailable."
                )
            agent_files = [
                candidate
                for candidate in sorted(agents.rglob("*"))
                if candidate.is_file() and not candidate.is_symlink()
            ]
        except OSError as exc:
            raise RecipeValidationError(
                "The authoritative Claude file roster is unavailable."
            ) from exc
        paths = [
            ".claude/commands/protocol.md",
            ".claude/commands/continue.md",
            ".claude/fitness-check.sh",
            *(candidate.relative_to(source).as_posix() for candidate in agent_files),
        ]
    else:
        plugin = source / "plugins/codex-copilot"
        gate = source / "scripts/copilot-gate.sh"
        try:
            if plugin.is_symlink() or not plugin.is_dir() or not gate.is_file():
                raise RecipeValidationError(
                    "The authoritative Codex file roster is unavailable."
                )
            source_files = [
                candidate
                for candidate in sorted(plugin.rglob("*"))
                if candidate.is_file() and not candidate.is_symlink()
            ]
        except OSError as exc:
            raise RecipeValidationError(
                "The authoritative Codex file roster is unavailable."
            ) from exc
        paths = [candidate.relative_to(source).as_posix() for candidate in source_files]
        paths.append("scripts/copilot-gate.sh")

    files: list[dict[str, str]] = []
    for relative in paths:
        path = source / relative
        try:
            if path.is_symlink() or not path.is_file():
                raise RecipeValidationError(
                    f"The authoritative source file {relative} is unsafe."
                )
            checksum = _bytes_hash(path.read_bytes())
        except OSError as exc:
            raise RecipeValidationError(
                f"The authoritative source file {relative} is unreadable."
            ) from exc
        files.append({"path": relative, "ownership": "framework", "checksum": checksum})
    return files


def _lock_entry(source: Path, component: str) -> dict[str, Any]:
    version = _version(source, component)
    return {
        "component": component,
        "version": version,
        "release_tag": f"v{version}",
        "files": _framework_files(source, component),
    }


def _ecosystem_lock_collision(root: Path) -> bool:
    try:
        raw = json.loads((root / "copilot.lock.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict) or not raw or "components" in raw:
        return False
    metadata = [
        value.get("_meta")
        for value in raw.values()
        if isinstance(value, dict) and isinstance(value.get("_meta"), dict)
    ]
    return len(metadata) == len(raw) and all(
        item.get("product") in {"knowledge", "cli", "claude", "codex"}
        and isinstance(item.get("role"), str)
        and item.get("tier") in {"personal", "department", "organization", "foundation"}
        and (
            item.get("source_sha") is None
            or (
                isinstance(item.get("source_sha"), str)
                and len(item["source_sha"]) == 40
            )
        )
        for item in metadata
    )


def _lock_payload(root: Path, entry: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"component_entry": entry}
    if _ecosystem_lock_collision(root):
        payload["replace_ecosystem_lock"] = True
    return payload


def _claude_customized_lock_entry(source: Path, root: Path) -> dict[str, Any]:
    entry = _lock_entry(source, "claude")
    owned_paths = {
        ".claude/commands/protocol.md",
        ".claude/commands/continue.md",
        ".claude/fitness-check.sh",
    }
    return {
        **entry,
        "ownership_mode": "customized-preserve",
        "files": [
            item
            for item in entry["files"]
            if item.get("path") in owned_paths
            and (
                _target_missing(root, str(item["path"]))
                or (
                    _safe_target_kind(root, str(item["path"])) == "regular"
                    and _bytes_hash((root / str(item["path"])).read_bytes())
                    == item.get("checksum")
                )
            )
        ],
    }


def _codex_customized_lock_entry(source: Path, root: Path) -> dict[str, Any]:
    entry = _lock_entry(source, "codex")
    plugin_missing = _target_missing(root, "plugins/codex-copilot")
    return {
        **entry,
        "ownership_mode": "customized-preserve",
        "files": [
            item
            for item in entry["files"]
            if (
                str(item["path"]).startswith("plugins/codex-copilot/")
                and plugin_missing
            )
            or (
                item.get("path") == "scripts/copilot-gate.sh"
                and (
                    _target_missing(root, "scripts/copilot-gate.sh")
                    or _legacy_codex_gate_wrapper(root)
                )
            )
            or (
                (root / str(item["path"])).is_file()
                and not (root / str(item["path"])).is_symlink()
                and _bytes_hash((root / str(item["path"])).read_bytes())
                == item.get("checksum")
            )
        ],
    }


def authoritative_source_available(
    component: str, configured: Path | str | None
) -> bool:
    """Verify that a configured source can produce the recipe's exact lock entry."""
    if component not in SUPPORTED_COMPONENTS or not configured:
        return False
    try:
        source = validated_source_root(component, configured)
        _lock_entry(source, component)
    except (OSError, RecipeValidationError):
        return False
    return True


def _source_binding(component: str) -> dict[str, str]:
    source = _source_root(component)
    entry = _lock_entry(source, component)
    return {
        "component": component,
        "version": str(entry["version"]),
        "fingerprint": _canonical_hash(
            {
                "component": component,
                "version": entry["version"],
                "files": entry["files"],
            }
        ),
    }


def _target_missing(root: Path, target: str) -> bool:
    try:
        (root / target).lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _legacy_codex_gate_wrapper(root: Path) -> bool:
    target = root / "scripts/copilot-gate.sh"
    try:
        return (
            target.is_file()
            and not target.is_symlink()
            and target.read_bytes() == _LEGACY_CODEX_GATE_WRAPPER
        )
    except OSError:
        return False


def _contained_missing_codex_bridge(root: Path) -> bool:
    bridge = root / ".claude/skills/codex-copilot"
    try:
        for ancestor in (root / ".claude", root / ".claude/skills"):
            metadata = ancestor.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                return False
        return (
            bridge.is_symlink()
            and str(bridge.readlink()) == "../../plugins/codex-copilot/skills"
            and not (root / "plugins/codex-copilot/skills").exists()
        )
    except OSError:
        return False


def _project_declaration_components(
    root: Path,
    project: ProjectAssessment,
    selected: Sequence[str],
) -> tuple[str, ...]:
    """Preserve every declared or already-present peer component."""
    target = root / "copilot.project.json"
    existing: Sequence[str] = ()
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RecipeValidationError(
            "The existing Copilot project declaration could not be inspected."
        ) from exc
    else:
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RecipeValidationError(
                "The existing Copilot project declaration is not a regular project file."
            )
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecipeValidationError(
                "The existing Copilot project declaration is unreadable."
            ) from exc
        components = raw.get("components") if isinstance(raw, Mapping) else None
        if (
            not isinstance(raw, Mapping)
            or raw.get("schema_version") != "1.0"
            or not isinstance(components, list)
            or not components
            or any(component not in SUPPORTED_COMPONENTS for component in components)
            or len(components) != len(set(components))
        ):
            raise RecipeValidationError(
                "The existing Copilot project declaration uses an unsupported shape."
            )
        existing = tuple(str(component) for component in components)

    present = {
        "claude-only": ("claude",),
        "codex-only": ("codex",),
        "both": SUPPORTED_COMPONENTS,
    }.get(str(project.get("presence")), ())
    retained = {*existing, *present, *selected}
    return tuple(
        component for component in SUPPORTED_COMPONENTS if component in retained
    )


def _claude_setup(root: Path, component: str) -> tuple[RecipeOperation, ...]:
    source = _source_root(component)
    operations: list[RecipeOperation] = []
    agents_missing = _target_missing(root, ".claude/agents")
    if _target_missing(root, "CLAUDE.md"):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.APPEND_MANAGED_BLOCK,
                target="CLAUDE.md",
                description="Add the bounded Claude Copilot project entry.",
                payload={"block": _CLAUDE_BLOCK, "mode": 0o644},
            )
        )
    if _target_missing(root, ".mcp.json"):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.MERGE_JSON_KEYS,
                target=".mcp.json",
                description="Create the empty project MCP server roster without credentials.",
                payload={"keys": {"mcpServers": {}}},
            )
        )
    for target in (
        ".claude/commands/protocol.md",
        ".claude/commands/continue.md",
        ".claude/fitness-check.sh",
    ):
        if _target_missing(root, target):
            operations.append(
                _operation(
                    root=root,
                    component=component,
                    kind=RecipeOperationKind.COPY_FILE_FROM_SOURCE,
                    target=target,
                    description=f"Install the missing framework-owned {target} file.",
                    source=source / target,
                    payload={
                        "source_path": str(source / target),
                        "mode": 0o755 if target.endswith(".sh") else 0o644,
                    },
                )
            )
    if agents_missing:
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.COPY_TREE_FROM_SOURCE,
                target=".claude/agents",
                description="Install the project-local Claude framework agent roster.",
                source=source / ".claude/agents",
                payload={"source_path": str(source / ".claude/agents")},
            )
        )
    lock_entry = _lock_entry(source, component)
    if not agents_missing:
        lock_entry = {
            **lock_entry,
            "files": [
                item
                for item in lock_entry["files"]
                if not str(item.get("path", "")).startswith(".claude/agents/")
                or (
                    (root / str(item["path"])).is_file()
                    and not (root / str(item["path"])).is_symlink()
                    and _bytes_hash((root / str(item["path"])).read_bytes())
                    == item.get("checksum")
                )
            ],
        }
    operations.append(
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
            target="copilot.lock.json",
            description="Record exact Claude framework-owned checksums.",
            payload=_lock_payload(root, lock_entry),
        )
    )
    return tuple(operations)


def _claude_legacy(root: Path, component: str) -> tuple[RecipeOperation, ...]:
    source = _source_root(component)
    return (
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.APPEND_MANAGED_BLOCK,
            target="CLAUDE.md",
            description="Append the bounded canonical Claude entry without replacing project instructions.",
            payload={"block": _CLAUDE_BLOCK, "mode": 0o644},
        ),
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
            target="copilot.lock.json",
            description="Refresh only the Claude lock component after verification.",
            payload=_lock_payload(root, _lock_entry(source, component)),
        ),
    )


def _codex_setup(root: Path, component: str) -> tuple[RecipeOperation, ...]:
    source = _source_root(component)
    operations: list[RecipeOperation] = []
    if _target_missing(root, "AGENTS.md"):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.APPEND_MANAGED_BLOCK,
                target="AGENTS.md",
                description="Add the bounded Codex Copilot project entry.",
                payload={"block": _CODEX_BLOCK, "mode": 0o644},
            )
        )
    plugin_source = source / "plugins/codex-copilot"
    if _target_missing(root, "plugins/codex-copilot"):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.COPY_TREE_FROM_SOURCE,
                target="plugins/codex-copilot",
                description="Install a portable project-local Codex plugin copy.",
                source=plugin_source,
                payload={"source_path": str(plugin_source)},
            )
        )
    if not _recognized_read_only_knowledge_link(
        root, ".claude/skills"
    ) and (
        _target_missing(root, ".claude/skills/codex-copilot")
        or _contained_missing_codex_bridge(root)
    ):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.CREATE_INTERNAL_RELATIVE_SYMLINK,
                target=".claude/skills/codex-copilot",
                description="Create the contained project-local Codex skill bridge.",
                payload={"link_target": "../../plugins/codex-copilot/skills"},
            )
        )
    gate_source = source / "scripts/copilot-gate.sh"
    if _target_missing(root, "scripts/copilot-gate.sh"):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.COPY_FILE_FROM_SOURCE,
                target="scripts/copilot-gate.sh",
                description="Install the project-local verification gate.",
                source=gate_source,
                payload={"source_path": str(gate_source), "mode": 0o755},
            )
        )
    if _target_missing(root, ".codex-copilot.json"):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.MERGE_JSON_KEYS,
                target=".codex-copilot.json",
                description="Record the portable project-local plugin without replacing other settings.",
                payload={
                    "keys": {
                        "installType": "copy",
                        "pluginPath": "./plugins/codex-copilot",
                    }
                },
            )
        )
    operations.append(
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
            target="copilot.lock.json",
            description="Record exact Codex framework-owned checksums.",
            payload=_lock_payload(root, _lock_entry(source, component)),
        )
    )
    return tuple(operations)


def _codex_legacy(root: Path, component: str) -> tuple[RecipeOperation, ...]:
    source = _source_root(component)
    plugin_source = source / "plugins/codex-copilot"
    gate_source = source / "scripts/copilot-gate.sh"
    operations = [
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.REPLACE_RECOGNIZED_SYMLINK_WITH_COPY,
            target="plugins/codex-copilot",
            description="Replace only the recognized legacy link with a portable plugin copy.",
            source=plugin_source,
            payload={"source_path": str(plugin_source)},
        ),
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.CREATE_INTERNAL_RELATIVE_SYMLINK,
            target=".claude/skills/codex-copilot",
            description="Replace the recognized bridge with a contained project-local bridge.",
            payload={"link_target": "../../plugins/codex-copilot/skills"},
        ),
    ]
    if (
        _target_missing(root, "scripts/copilot-gate.sh")
        or (root / "scripts/copilot-gate.sh").is_symlink()
        or _legacy_codex_gate_wrapper(root)
    ):
        operations.append(
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.COPY_FILE_FROM_SOURCE,
                target="scripts/copilot-gate.sh",
                description="Replace only a missing or recognized linked gate with the project-local gate.",
                source=gate_source,
                payload={"source_path": str(gate_source), "mode": 0o755},
            )
        )
    operations.extend(
        [
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.MERGE_JSON_KEYS,
                target=".codex-copilot.json",
                description="Change only the portable install keys and preserve every other setting.",
                payload={
                    "keys": {
                        "installType": "copy",
                        "pluginPath": "./plugins/codex-copilot",
                    }
                },
            ),
            _operation(
                root=root,
                component=component,
                kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
                target="copilot.lock.json",
                description="Refresh only the Codex lock component after verification.",
                payload=_lock_payload(root, _lock_entry(source, component)),
            ),
        ]
    )
    return tuple(operations)


def _replace_entry_operation(
    operations: Sequence[RecipeOperation],
    *,
    root: Path,
    component: str,
    target: str,
    block: str,
) -> tuple[RecipeOperation, ...]:
    """Use one bounded entry merge while retaining only missing-target setup work."""
    entry = _operation(
        root=root,
        component=component,
        kind=RecipeOperationKind.APPEND_MANAGED_BLOCK,
        target=target,
        description=(
            f"Append the reviewed bounded {component.title()} entry without replacing "
            "project-authored instructions."
        ),
        payload={"block": block, "mode": 0o644},
    )
    return (
        entry,
        *(operation for operation in operations if operation.target != target),
    )


def _requirement_ids(assessment: Mapping[str, Any]) -> frozenset[str]:
    component = str(assessment.get("component", ""))
    prefix = f"{component}:"
    result: set[str] = set()
    for item in assessment.get("missing_requirements", []):
        if not isinstance(item, Mapping):
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str):
            continue
        result.add(identifier.removeprefix(prefix))
    return frozenset(result)


def _preserved_paths(dossier: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        str(item["path"])
        for item in dossier.get("preservation", [])
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    )


def _safe_target_kind(root: Path, target: str) -> str:
    """Classify one relative target without following a project symlink."""
    candidate = root
    parts = PurePosixPath(target).parts
    for index, part in enumerate(parts):
        candidate /= part
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unsafe"
        if stat.S_ISLNK(metadata.st_mode):
            return "unsafe"
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            return "unsafe"
        if index == len(parts) - 1:
            if stat.S_ISREG(metadata.st_mode):
                return "regular"
            if stat.S_ISDIR(metadata.st_mode):
                return "directory"
            return "unsafe"
    return "unsafe"


def _safe_json_object(root: Path, target: str) -> bool:
    path = root / target
    if _safe_target_kind(root, target) != "regular":
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return False
    return isinstance(value, dict)


def _safe_claude_project_tree(root: Path) -> bool:
    """Reject unsafe Claude mutation targets and unrecognized shared links.

    Preservation recipes deliberately leave project-authored files in place.
    The only external links admitted here are exact, read-only links into a
    configured Knowledge ecosystem repository. Recipe operations never target
    those links or their descendants.
    """
    for target in ("CLAUDE.md", ".mcp.json"):
        if _safe_target_kind(root, target) == "unsafe":
            return False
    root_kind = _safe_target_kind(root, ".claude")
    if root_kind == "missing":
        return True
    if root_kind != "directory":
        return False
    pending: list[Path] = []
    for target in (
        ".claude/agents",
        ".claude/commands",
        ".claude/skills",
        ".claude/cc",
        ".claude/memory",
    ):
        kind = _safe_target_kind(root, target)
        if kind == "unsafe" and _recognized_read_only_knowledge_link(root, target):
            continue
        if kind == "unsafe" or kind == "regular":
            return False
        if kind == "directory":
            pending.append(root / target)
    if _safe_target_kind(root, ".claude/fitness-check.sh") == "unsafe":
        return False
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return False
        for entry in entries:
            try:
                if entry.is_symlink():
                    if _recognized_internal_codex_skill_bridge(
                        root, Path(entry.path)
                    ):
                        continue
                    return False
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif not entry.is_file(follow_symlinks=False):
                    return False
            except OSError:
                return False
    return True


def _recognized_internal_codex_skill_bridge(root: Path, path: Path) -> bool:
    """Admit only Codex's exact project-contained skill bridge.

    Claude preservation recipes never write through this link.  The target is
    the portable Codex plugin already contained by the same project, so this
    does not grant access to an external shared checkout or broaden the recipe
    mutation boundary.
    """
    try:
        if path.relative_to(root).as_posix() != ".claude/skills/codex-copilot":
            return False
        if path.readlink().as_posix() != "../../plugins/codex-copilot/skills":
            return False
        expected = (root / "plugins/codex-copilot/skills").resolve(strict=True)
        return path.resolve(strict=True) == expected and expected.is_dir()
    except (OSError, ValueError):
        return False


def _recognized_read_only_knowledge_link(root: Path, target: str) -> bool:
    link = root / target
    try:
        metadata = link.lstat()
        if not stat.S_ISLNK(metadata.st_mode):
            return False
        configured = resolve_key("paths.knowledge_repo")
        values = configured if isinstance(configured, list) else [configured]
        leaf = PurePosixPath(target).name
        resolved = link.resolve(strict=True)
        expected = {
            (Path(value).expanduser() / ".claude" / leaf).resolve(strict=True)
            for value in values
            if isinstance(value, str) and value
        }
    except (OSError, RecipeValidationError):
        return False
    return resolved in expected


def _claude_preserve_entry_eligible(
    root: Path, assessment: Mapping[str, Any], dossier: Mapping[str, Any]
) -> bool:
    del dossier
    if not _safe_claude_project_tree(root):
        return False
    requirements = _requirement_ids(assessment)
    if not requirements or not requirements <= {
        "compatible-claude-entry",
        "valid-mcp-marker",
    }:
        return False
    if "compatible-claude-entry" in requirements and _safe_target_kind(
        root, "CLAUDE.md"
    ) not in {"missing", "regular"}:
        return False
    return (
        "valid-mcp-marker" not in requirements
        or _safe_target_kind(root, ".mcp.json") == "missing"
    )


def _claude_assistant_preserve_entry_eligible(
    root: Path, assessment: Mapping[str, Any], dossier: Mapping[str, Any]
) -> bool:
    """Allow only the closed preservation recipe for readable customized Claude.

    Unlike the deterministic option, this route may also account for custom
    framework-owned files. The operation builder never overwrites them: it
    appends the Python-owned entry, creates only missing support paths, and
    refreshes the component lock. Existing paths remain transaction inputs.
    """
    del dossier
    if not _safe_claude_project_tree(root):
        return False
    requirements = _requirement_ids(assessment)
    if not requirements or "project-owned-component-content" not in requirements:
        return False
    if _safe_target_kind(root, "CLAUDE.md") not in {"missing", "regular"}:
        return False
    if "valid-mcp-marker" in requirements and _safe_target_kind(
        root, ".mcp.json"
    ) != "missing":
        return False
    return True


def _claude_legacy_knowledge_links_eligible(
    root: Path, assessment: Mapping[str, Any], dossier: Mapping[str, Any]
) -> bool:
    """Preserve a verified read-only Knowledge hierarchy without writing through it."""
    del dossier
    if not _safe_claude_project_tree(root) or not any(
        _recognized_read_only_knowledge_link(root, target)
        for target in (
            ".claude/agents",
            ".claude/commands",
            ".claude/skills",
        )
    ):
        return False
    requirements = _requirement_ids(assessment)
    if not requirements or not requirements <= {
        "compatible-claude-entry",
        "valid-mcp-marker",
        "project-owned-component-content",
    }:
        return False
    if _safe_target_kind(root, "CLAUDE.md") not in {"missing", "regular"}:
        return False
    return (
        "valid-mcp-marker" not in requirements
        or _safe_target_kind(root, ".mcp.json") == "missing"
    )


def _codex_preserve_entry_eligible(
    root: Path, assessment: Mapping[str, Any], dossier: Mapping[str, Any]
) -> bool:
    requirements = _requirement_ids(assessment)
    covered = {
        "compatible-codex-entry",
        "valid-codex-config",
        "valid-plugin-manifest",
        "internal-skill-link",
        "project-owned-component-content",
    }
    if not requirements or not requirements <= covered:
        return False
    if (
        "project-owned-component-content" in requirements
        and not _valid_existing_codex_custom_topology(root)
    ):
        return False
    preserved = _preserved_paths(dossier)
    if "compatible-codex-entry" in requirements and _safe_target_kind(
        root, "AGENTS.md"
    ) not in {"missing", "regular"}:
        return False
    missing_targets = {
        "valid-codex-config": ".codex-copilot.json",
        "valid-plugin-manifest": "plugins/codex-copilot",
        "internal-skill-link": ".claude/skills/codex-copilot",
    }
    for requirement, target in missing_targets.items():
        if requirement not in requirements:
            continue
        safe_missing = _safe_target_kind(root, target) == "missing"
        if requirement == "internal-skill-link":
            safe_missing = safe_missing or _contained_missing_codex_bridge(root)
        if not safe_missing:
            return False
        if any(path == target or path.startswith(f"{target}/") for path in preserved):
            return False
    return True


def _valid_existing_codex_custom_topology(root: Path) -> bool:
    config_path = root / ".codex-copilot.json"
    manifest_path = root / "plugins/codex-copilot/.codex-plugin/plugin.json"
    bridge = root / ".claude/skills/codex-copilot"
    gate = root / "scripts/copilot-gate.sh"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bridge_ok = (
            bridge.is_symlink()
            and str(bridge.readlink()) == "../../plugins/codex-copilot/skills"
            and (root / "plugins/codex-copilot/skills").is_dir()
        )
        gate_ok = _target_missing(root, "scripts/copilot-gate.sh") or (
            gate.is_file()
            and not gate.is_symlink()
            and gate.read_bytes()
            == (_source_root("codex") / "scripts/copilot-gate.sh").read_bytes()
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecipeValidationError):
        return False
    return (
        isinstance(config, dict)
        and config.get("installType") == "copy"
        and config.get("pluginPath") == "./plugins/codex-copilot"
        and isinstance(manifest, dict)
        and manifest.get("name") == "codex-copilot"
        and bridge_ok
        and gate_ok
    )


def _codex_config_merge_eligible(
    root: Path, assessment: Mapping[str, Any], dossier: Mapping[str, Any]
) -> bool:
    return (
        _requirement_ids(assessment) == {"valid-codex-config"}
        and ".codex-copilot.json" in _preserved_paths(dossier)
        and _safe_json_object(root, ".codex-copilot.json")
    )


def _claude_customized_preserve_entry(
    root: Path, component: str
) -> tuple[RecipeOperation, ...]:
    return _replace_entry_operation(
        _claude_setup(root, component),
        root=root,
        component=component,
        target="CLAUDE.md",
        block=_CLAUDE_BLOCK,
    )


def _claude_assistant_preserve_entry(
    root: Path, component: str
) -> tuple[RecipeOperation, ...]:
    source = _source_root(component)
    operations = _claude_customized_preserve_entry(root, component)
    bounded: list[RecipeOperation] = []
    for operation in operations:
        if operation.target == ".claude/agents":
            continue
        if operation.kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT:
            bounded.append(
                _operation(
                    root=root,
                    component=component,
                    kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
                    target="copilot.lock.json",
                    description="Record only the bounded Claude support files installed by this customized-preservation route.",
                    payload=_lock_payload(
                        root, _claude_customized_lock_entry(source, root)
                    ),
                )
            )
            continue
        bounded.append(operation)
    return tuple(bounded)


def _codex_customized_preserve_entry(
    root: Path, component: str
) -> tuple[RecipeOperation, ...]:
    source = _source_root(component)
    operations = _replace_entry_operation(
        _codex_setup(root, component),
        root=root,
        component=component,
        target="AGENTS.md",
        block=_CODEX_BLOCK,
    )
    return tuple(
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
            target="copilot.lock.json",
            description="Record only verified bounded Codex outputs while preserving customized plugin content.",
            payload=_lock_payload(
                root, _codex_customized_lock_entry(source, root)
            ),
        )
        if operation.kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT
        else operation
        for operation in operations
    )


def _codex_customized_merge_config(
    root: Path, component: str
) -> tuple[RecipeOperation, ...]:
    source = _source_root(component)
    return (
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.MERGE_JSON_KEYS,
            target=".codex-copilot.json",
            description="Set only the portable Codex plugin keys and preserve unrelated project settings.",
            payload={
                "keys": {
                    "installType": "copy",
                    "pluginPath": "./plugins/codex-copilot",
                }
            },
        ),
        _operation(
            root=root,
            component=component,
            kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
            target="copilot.lock.json",
            description="Record exact Codex framework-owned checksums after the bounded config merge.",
            payload=_lock_payload(root, _lock_entry(source, component)),
        ),
    )


def _receipt_operations(root: Path, component: str) -> tuple[RecipeOperation, ...]:
    del root, component
    return ()


_RECEIPT_ROUTES = (
    ComponentRoute.READY,
    ComponentRoute.NOT_PRESENT,
    ComponentRoute.NOT_SELECTED,
    ComponentRoute.HELD,
    ComponentRoute.OWNER_DECISION,
    ComponentRoute.COULD_NOT_VERIFY,
    ComponentRoute.EXCLUDED,
)


DEFAULT_RECIPE_REGISTRY = RecipeRegistry(
    (
        RecipeDefinition(
            "claude-project-setup-v1",
            "claude",
            frozenset({ComponentRoute.SAFE_SETUP_AVAILABLE}),
            _claude_setup,
        ),
        RecipeDefinition(
            "codex-project-setup-v1",
            "codex",
            frozenset({ComponentRoute.SAFE_SETUP_AVAILABLE}),
            _codex_setup,
        ),
        RecipeDefinition(
            "claude-canonical-entry-v1",
            "claude",
            frozenset({ComponentRoute.SAFE_UPDATE_AVAILABLE}),
            _claude_legacy,
        ),
        RecipeDefinition(
            "codex-portable-copy-v1",
            "codex",
            frozenset({ComponentRoute.SAFE_UPDATE_AVAILABLE}),
            _codex_legacy,
        ),
        RecipeDefinition(
            "claude-repair-known-v1",
            "claude",
            frozenset({ComponentRoute.SAFE_UPDATE_AVAILABLE}),
            _claude_setup,
        ),
        RecipeDefinition(
            "codex-repair-known-v1",
            "codex",
            frozenset({ComponentRoute.SAFE_UPDATE_AVAILABLE}),
            _codex_setup,
        ),
        RecipeDefinition(
            "claude.customized-preserve-entry.v1",
            "claude",
            frozenset({ComponentRoute.CUSTOMIZED_GUIDED_ROUTE}),
            _claude_customized_preserve_entry,
            "Preserve project-authored Claude instructions while adding the bounded framework entry and only missing framework-owned support files.",
            eligibility=_claude_preserve_entry_eligible,
        ),
        RecipeDefinition(
            "claude.assistant-preserve-entry.v1",
            "claude",
            frozenset({ComponentRoute.CUSTOMIZED_GUIDED_ROUTE}),
            _claude_assistant_preserve_entry,
            "Preserve customized Claude content while adding only the canonical framework entry and missing framework-owned support files.",
            eligibility=_claude_assistant_preserve_entry_eligible,
            assistant_only=True,
        ),
        RecipeDefinition(
            "claude.legacy-knowledge-links-preserve.v1",
            "claude",
            frozenset({ComponentRoute.CUSTOMIZED_GUIDED_ROUTE}),
            _claude_assistant_preserve_entry,
            "Preserve verified read-only Knowledge hierarchy links while adding only local Claude entry, marker, and lock evidence.",
            eligibility=_claude_legacy_knowledge_links_eligible,
        ),
        RecipeDefinition(
            "codex.customized-preserve-entry.v1",
            "codex",
            frozenset({ComponentRoute.CUSTOMIZED_GUIDED_ROUTE}),
            _codex_customized_preserve_entry,
            "Preserve project-authored Codex instructions while adding the bounded framework entry and only missing portable support files.",
            eligibility=_codex_preserve_entry_eligible,
        ),
        RecipeDefinition(
            "codex.customized-merge-config.v1",
            "codex",
            frozenset({ComponentRoute.CUSTOMIZED_GUIDED_ROUTE}),
            _codex_customized_merge_config,
            "Merge only the portable Codex plugin keys into a readable project config, preserve unrelated keys, and record exact framework checksums.",
            eligibility=_codex_config_merge_eligible,
        ),
        *(
            RecipeDefinition(
                f"{component}-{route.value}-receipt-v1",
                component,
                frozenset({route}),
                _receipt_operations,
            )
            for component in SUPPORTED_COMPONENTS
            for route in _RECEIPT_ROUTES
        ),
    )
)


def _component(project: ProjectAssessment, name: str) -> Mapping[str, Any]:
    try:
        return next(item for item in project["components"] if item["component"] == name)
    except StopIteration as exc:
        raise RecipeValidationError(
            f"Project {project['path']} has no {name} component assessment."
        ) from exc


def _recognized_variant(component: Mapping[str, Any]) -> str | None:
    for evidence in component.get("evidence", []):
        if evidence.get("id") == "recognized-setup":
            state = evidence.get("state")
            return state if isinstance(state, str) else None
    return None


def _default_recipe(component: Mapping[str, Any]) -> str | None:
    name = str(component["component"])
    route = ComponentRoute(str(component["state"]))
    if route == ComponentRoute.SAFE_SETUP_AVAILABLE:
        return f"{name}-project-setup-v1"
    if route == ComponentRoute.CUSTOMIZED_GUIDED_ROUTE:
        return None
    if route != ComponentRoute.SAFE_UPDATE_AVAILABLE:
        return f"{name}-{route.value}-receipt-v1"
    variant = _recognized_variant(component) or ""
    if name == "claude" and variant.startswith("claude-legacy-"):
        return "claude-canonical-entry-v1"
    if name == "codex" and variant.startswith("codex-legacy-"):
        return "codex-portable-copy-v1"
    return f"{name}-repair-known-v1"


def _managed_output_for_operation(
    root: Path, operation: RecipeOperation
) -> dict[str, str] | None:
    path = root / operation.target
    if operation.kind == RecipeOperationKind.APPEND_MANAGED_BLOCK:
        try:
            current = path.read_bytes()
        except FileNotFoundError:
            current = b""
        separator = (
            b""
            if not current or current.endswith(b"\n\n")
            else (b"\n" if current.endswith(b"\n") else b"\n\n")
        )
        content = current + separator + str(operation.payload["block"]).encode("utf-8")
        mode = int(
            operation.payload.get(
                "mode",
                stat.S_IMODE(path.lstat().st_mode) if path.exists() else 0o644,
            )
        )
        fingerprint = fingerprint_file_payload(content, mode=mode)
        kind = "managed-text"
    elif operation.kind == RecipeOperationKind.MERGE_JSON_KEYS:
        try:
            current_json = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            current_json = {}
        if not isinstance(current_json, dict):
            raise RecipeValidationError("A managed JSON target is not an object.")
        current_json.update(dict(operation.payload["keys"]))
        content = (json.dumps(current_json, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        mode = int(
            operation.payload.get(
                "mode",
                stat.S_IMODE(path.lstat().st_mode) if path.exists() else 0o644,
            )
        )
        fingerprint = fingerprint_file_payload(content, mode=mode)
        kind = "merged-json"
    elif operation.kind == RecipeOperationKind.CREATE_INTERNAL_RELATIVE_SYMLINK:
        fingerprint = fingerprint_symlink(str(operation.payload["link_target"]))
        kind = "internal-symlink"
    else:
        return None
    return {
        "path": operation.target,
        "kind": kind,
        "fingerprint": fingerprint,
    }


def _entry_with_managed_outputs(
    entry: Mapping[str, Any], outputs: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    result = dict(entry)
    if outputs:
        result["managed_outputs"] = [dict(output) for output in outputs]
    else:
        result.pop("managed_outputs", None)
    return result


def _existing_lock_entries(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "copilot.lock.json"
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    components = raw.get("components") if isinstance(raw, Mapping) else None
    if not isinstance(components, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in components:
        component = entry.get("component") if isinstance(entry, Mapping) else None
        if component not in SUPPORTED_COMPONENTS or component in result:
            return {}
        result[str(component)] = dict(entry)
    return result


def _managed_records(entry: Mapping[str, Any]) -> list[dict[str, str]]:
    records = entry.get("managed_outputs", [])
    if not isinstance(records, list):
        return []
    return [dict(item) for item in records if isinstance(item, Mapping)]


def _coalesce_lock_operations(
    root: Path, operations: Sequence[RecipeOperation]
) -> tuple[RecipeOperation, ...]:
    managed: dict[str, list[dict[str, str]]] = {
        component: [] for component in SUPPORTED_COMPONENTS
    }
    shared_output: dict[str, str] | None = None
    shared_owner: str | None = None
    for operation in operations:
        output = _managed_output_for_operation(root, operation)
        if output is not None:
            if output["path"] == "copilot.project.json":
                shared_output = output
                shared_owner = operation.component
            else:
                managed[operation.component].append(output)

    lock_operations = [
        operation
        for operation in operations
        if operation.kind == RecipeOperationKind.UPSERT_LOCK_COMPONENT
    ]
    if not lock_operations:
        return tuple(operations)

    incoming: dict[str, dict[str, Any]] = {}
    for operation in lock_operations:
        raw = operation.payload["component_entry"]
        entries = (
            list(raw)
            if isinstance(raw, Sequence) and not isinstance(raw, Mapping)
            else [raw]
        )
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise RecipeValidationError("A lock recipe entry is invalid.")
            component = str(entry.get("component", ""))
            if component not in SUPPORTED_COMPONENTS or component in incoming:
                raise RecipeValidationError("Lock recipe components are invalid.")
            incoming[component] = dict(entry)

    existing = _existing_lock_entries(root)
    mutated_targets = {
        component: {output["path"] for output in outputs}
        for component, outputs in managed.items()
    }
    enriched_entries: dict[str, dict[str, Any]] = {}
    for component, entry in incoming.items():
        retained = [
            output
            for output in _managed_records(existing.get(component, {}))
            if output.get("path") not in mutated_targets[component]
            and output.get("path") != "copilot.project.json"
        ]
        outputs = [*retained, *managed[component]]
        if component == shared_owner and shared_output is not None:
            outputs.append(shared_output)
        outputs.sort(key=lambda item: (item.get("path", ""), item.get("kind", "")))
        enriched_entries[component] = _entry_with_managed_outputs(entry, outputs)

    # A declaration is shared project state.  If a retained peer used to own
    # its evidence, include that peer lock entry in the same atomic upsert with
    # only the obsolete shared record removed.  This prevents duplicate or
    # stale self-authorizing evidence after a one-component update.
    for component, entry in existing.items():
        if component in enriched_entries:
            continue
        outputs = _managed_records(entry)
        if not any(output.get("path") == "copilot.project.json" for output in outputs):
            continue
        retained = [
            output for output in outputs if output.get("path") != "copilot.project.json"
        ]
        enriched_entries[component] = _entry_with_managed_outputs(entry, retained)

    entries = [enriched_entries[name] for name in sorted(enriched_entries)]
    combined = _operation(
        root=root,
        component=lock_operations[0].component,
        kind=RecipeOperationKind.UPSERT_LOCK_COMPONENT,
        target="copilot.lock.json",
        description="Atomically refresh the selected Claude and Codex lock components.",
        payload=_lock_payload(
            root, entries[0] if len(entries) == 1 else entries
        ),
    )
    result: list[RecipeOperation] = []
    inserted = False
    for operation in operations:
        if operation.kind != RecipeOperationKind.UPSERT_LOCK_COMPONENT:
            result.append(operation)
        elif not inserted:
            result.append(combined)
            inserted = True
    return tuple(result)


def build_recipe_plan(
    project: ProjectAssessment,
    selected_components: Sequence[str],
    *,
    explicit_recipe_ids: Mapping[str, str] | None = None,
    registry: RecipeRegistry = DEFAULT_RECIPE_REGISTRY,
) -> RecipePlan:
    selected = tuple(dict.fromkeys(selected_components))
    if not selected or any(item not in SUPPORTED_COMPONENTS for item in selected):
        raise RecipeValidationError(
            "Project plans require an explicit closed component selection."
        )

    explicit = dict(explicit_recipe_ids or {})
    if any(component not in selected for component in explicit):
        raise RecipeValidationError(
            "Recipe ids may be supplied only for explicitly selected components."
        )
    root = Path(project["path"])
    dossier = project.get("dossier") or {}
    chosen: list[RecipeDefinition] = []
    for name in selected:
        assessment = _component(project, name)
        route = ComponentRoute(str(assessment["state"]))
        recipe_id = _default_recipe(assessment)
        explicit_recipe_id = explicit.get(name)
        if explicit_recipe_id is not None:
            chosen.append(
                registry.require(
                    explicit_recipe_id,
                    component=name,
                    route=route,
                    root=root,
                    assessment=assessment,
                    dossier=dossier,
                )
            )
            continue
        if route == ComponentRoute.CUSTOMIZED_GUIDED_ROUTE:
            raise RecipeValidationError(
                f"The customized {name} route requires one reviewed component-scoped recipe id."
            )
        if recipe_id is not None:
            chosen.append(
                registry.require(
                    recipe_id,
                    component=name,
                    route=route,
                    root=root,
                    assessment=assessment,
                    dossier=dossier,
                )
            )
    built = tuple(
        (definition, definition.builder(root, definition.component))
        for definition in chosen
    )
    operations = tuple(
        operation for _, component_ops in built for operation in component_ops
    )
    sources = tuple(
        _source_binding(definition.component)
        for definition, component_ops in built
        if component_ops
    )
    if operations:
        declared_components = _project_declaration_components(root, project, selected)
        declaration = _operation(
            root=root,
            component=chosen[0].component,
            kind=RecipeOperationKind.MERGE_JSON_KEYS,
            target="copilot.project.json",
            description="Record selected components while preserving every declared or already-present peer.",
            payload={
                "keys": {
                    "schema_version": "1.0",
                    "components": list(declared_components),
                }
            },
        )
        operations = (*operations, declaration)

    # Lock evidence is composed only after every managed mutation is known.  In
    # particular, the project declaration merge preserves owner-authored keys,
    # so repeat safety must bind its exact post-merge bytes instead of assuming a
    # minimal declaration shape.
    operations = _coalesce_lock_operations(root, operations)

    allowed_targets = tuple(
        dict.fromkeys(
            [
                *dossier.get("allowed_targets", []),
                *(operation.target for operation in operations),
            ]
        )
    )
    verification = tuple(
        dossier.get(
            "verification",
            [f"cc workspace verify --project {project['path']} --json"],
        )
    )
    stop_conditions = tuple(
        dossier.get(
            "stop_conditions",
            ["Stop if fresh project evidence differs from this plan."],
        )
    )
    return RecipePlan(
        path=project["path"],
        inspection_id=project["inspection_id"],
        expected_identity=inspect_project_identity(root),
        selected_components=selected,
        recipes=tuple(
            (definition.component, definition.recipe_id) for definition in chosen
        ),
        sources=sources,
        operations=tuple(operations),
        preservation=tuple(dossier.get("preservation", [])),
        allowed_targets=allowed_targets,
        prohibited_actions=tuple(dossier.get("prohibited_actions", [])),
        verification=verification,
        stop_conditions=stop_conditions,
    )


__all__ = [
    "DEFAULT_RECIPE_REGISTRY",
    "OPERATION_PAYLOAD_KEYS",
    "RecipeDefinition",
    "RecipeOperation",
    "RecipePlan",
    "RecipeRegistry",
    "RecipeValidationError",
    "allowed_targets_for_components",
    "authoritative_source_available",
    "build_recipe_plan",
    "validated_source_root",
]
