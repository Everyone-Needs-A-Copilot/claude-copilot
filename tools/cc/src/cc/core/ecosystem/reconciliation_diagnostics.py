"""Closed, private reconciliation diagnostics and durable batch receipts.

This writer never serializes arbitrary reports, exceptions, environment
values, stdin, file bytes, or subprocess streams.  It rebuilds every project
receipt from a closed allowlist and replaces detail text with authored messages
for the reported status.  A per-project append is fsynced before the next batch
project begins, so a later crash cannot erase earlier peer outcomes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from cc.core.config_paths import machine_diagnostics_root
from cc.core.ecosystem.project_locking import (
    ProjectLockContention,
    ProjectLockError,
    advisory_file_lock,
    atomic_json_write,
    ensure_private_directory,
)

DIAGNOSTIC_SCHEMA_VERSION = "1.0"
DEFAULT_RETENTION = 20
_RUN_ID = re.compile(r"^run_[0-9a-f]{32}$")
_PLAN_ID = re.compile(r"^plan_[0-9a-f]{32}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPERATION_ID = re.compile(r"^op_[0-9a-f]{64}$")
_RECIPE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_VERSION = re.compile(
    r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]{0,63})?$"
)
_SCHEMA_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
_COMPONENTS = {"claude", "codex"}
_CLASSIFICATIONS = {
    "action-required",
    "blocked",
    "copilot-not-present",
    "could-not-verify",
    "customized-guided-route",
    "eligible",
    "excluded",
    "ecosystem-managed",
    "held",
    "not-present",
    "not-selected",
    "owner-decision",
    "ready",
    "safe-finish",
    "safe-setup-available",
    "safe-update-available",
    "source-unavailable",
    "selected",
    "unknown",
}
_BASE_EVIDENCE_IDS = {
    "available-component-source",
    "canonical-entry",
    "compatible-claude-entry",
    "compatible-codex-entry",
    "internal-skill-link",
    "readable-framework-file",
    "readable-plugin-tree",
    "recognized-setup",
    "required-lock-path",
    "valid-codex-config",
    "valid-framework-record",
    "valid-lock-entry",
    "valid-mcp-marker",
    "valid-owner-declaration",
    "valid-plugin-manifest",
    "verified-framework-file",
    "component-setup",
    "lock-record",
    "owner-direction",
    "project-owned-component-content",
    "readable-component-evidence",
    "readable-project-lock",
    "safe-recorded-path",
}
_EVIDENCE_IDS = _BASE_EVIDENCE_IDS | {
    f"{component}:{identifier}"
    for component in _COMPONENTS
    for identifier in _BASE_EVIDENCE_IDS
}
_TARGETS = {
    ".agents/plugins/marketplace.json",
    ".claude/agents",
    ".claude/cc/config.json",
    ".claude/commands/continue.md",
    ".claude/commands/protocol.md",
    ".claude/fitness-check.sh",
    ".claude/hooks/copilot-hook.sh",
    ".claude/settings.json",
    ".claude/memory/.gitignore",
    ".claude/memory/entries/.gitkeep",
    ".claude/skills/codex-copilot",
    ".codex-copilot.json",
    ".mcp.json",
    "AGENTS.md",
    "CLAUDE.md",
    "SOUL.md",
    "copilot.lock.json",
    "copilot.project.json",
    "docs/01-architecture/12-architecture-guiding-principles.md",
    "docs/40-initiatives",
    "plugins/codex-copilot",
    "scripts/copilot-gate.sh",
}
_TARGET_KINDS = {"directory", "file", "missing", "symlink", "uninspected"}
_OPERATION_KINDS = {
    "create-file-from-source",
    "copy-file-from-source",
    "copy-tree-from-source",
    "append-managed-block",
    "merge-json-keys",
    "replace-recognized-symlink-with-copy",
    "create-internal-relative-symlink",
    "upsert-lock-component",
    "write-project-declaration",
    "associate-personal-project",
    "register-settings-hooks",
}
_EXCEPTION_TYPES = {
    "KeyboardInterrupt",
    "OSError",
    "ProjectIdentityMismatch",
    "ProjectLockContention",
    "ReconciliationTransactionError",
    "RuntimeError",
    "SnapshotError",
    "SystemExit",
    "TransactionError",
    "UnsafeProjectPath",
}
_MACHINE_STATES = {"action-required", "could-not-verify", "ready", "unknown"}
_HELPER_STATES = {"incompatible", "missing", "ready", "unknown"}
_FRAMEWORK_STATES = {
    "could-not-verify",
    "incompatible",
    "missing",
    "ready",
    "unknown",
}
_AUTH_STATES = {
    "could-not-verify",
    "expired",
    "revoked",
    "signed-in",
    "signed-out",
    "unknown",
}
_CREDENTIAL_STATES = {
    "absent",
    "expired",
    "present",
    "store-unreachable",
    "unknown",
}
_CONNECTIVITY_STATES = {"could-not-verify", "offline", "online", "unknown"}
_LAYER_STATES = {
    "action-required",
    "could-not-verify",
    "not-configured",
    "ready",
    "unknown",
}
_DEPENDENCY_IDS = {"claude", "codex", "copilot", "gh", "git"}
_DEPENDENCY_STATES = {"missing", "ready", "unknown"}
_CENSUS_KEYS = {
    "copilot-not-present",
    "could-not-verify",
    "customized-guided-route",
    "excluded",
    "held",
    "not-present",
    "not-selected",
    "owner-decision",
    "ready",
    "safe-setup-available",
    "safe-update-available",
    "selected_projects",
    "total",
}
_OVERLAP_EXPLANATIONS = {
    "No overlapping project outcomes were reported.",
    (
        "Each project appears in exactly one project state. Claude and Codex "
        "are reported separately inside that project, so component outcomes "
        "may differ without changing the project count."
    ),
    (
        "Each discovered repository appears in exactly one scope and state. "
        "Ecosystem repositories are managed separately. Claude and Codex are "
        "reported independently inside each product project."
    ),
    "One updated component remains independently classified.",
}
_STATUSES = {
    "applied",
    "blocked",
    "rolled-back",
    "incomplete-rollback",
    "unchanged",
}
_VERIFICATION = {"ready", "failed", "not-run"}
_ROLLBACK = {"restored", "mismatch", "conflict", "unreadable"}
_DETAILS = {
    "applied": "Every targeted operation completed and fresh verification passed.",
    "blocked": "The project was left unchanged because a transaction guard refused it.",
    "rolled-back": "The project did not pass and every transaction-owned output was restored.",
    "incomplete-rollback": "At least one transaction-owned output could not be restored safely.",
    "unchanged": "The reviewed plan required no project mutation.",
}
_ROLLBACK_DETAILS = {
    "restored": "The target matches its saved pre-transaction fingerprint.",
    "mismatch": "The restored target did not match its saved fingerprint.",
    "conflict": "The target changed outside this transaction and was left alone.",
    "unreadable": "The target could not be restored and verified.",
}
_SAFE_EXCEPTION_DETAILS = {
    "stale-plan": "Fresh preflight evidence no longer matched the reviewed plan.",
    "lock-contention": "Another participating reconciliation held the project lock.",
    "unsafe-path": "A target could not be proven contained beneath the project.",
    "source-changed": "A configured source changed after the plan was reviewed.",
    "mutation-mismatch": "A typed operation did not produce its planned fingerprint.",
    "verification-failed": "Fresh component verification did not pass.",
    "interrupted": "The prior process stopped before reaching a terminal receipt.",
    "unexpected": "The transaction stopped on a classified internal error.",
}


class ReconciliationDiagnosticError(RuntimeError):
    pass


def _allowed_string(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


@dataclass(frozen=True)
class DiagnosticReference:
    schema_version: str
    id: str
    state: str
    path: Optional[str]
    created_at: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp(value: Optional[datetime] = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (
        current.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _directory(root: Optional[Path]) -> Path:
    base = (root or (machine_diagnostics_root() / "reconciliation")).expanduser()
    directory = base / "diagnostics"
    boundary = base if root is not None else machine_diagnostics_root()
    ensure_private_directory(directory, boundary=boundary)
    return directory


def _reference(
    run_id: str,
    *,
    state: str,
    path: Optional[Path],
    created_at: str,
) -> DiagnosticReference:
    return DiagnosticReference(
        schema_version=DIAGNOSTIC_SCHEMA_VERSION,
        id=run_id,
        state=state,
        path=str(path) if path is not None else None,
        created_at=created_at,
        detail=(
            "A private redacted reconciliation record was saved."
            if state == "available"
            else "The in-memory receipt is available, but its diagnostic record could not be saved."
        ),
    )


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ReconciliationDiagnosticError("The reconciliation run id is invalid.")


def _safe_rollback(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    safe: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        target = raw.get("target")
        status = raw.get("status")
        if not _allowed_string(target, _TARGETS) or not _allowed_string(
            status, _ROLLBACK
        ):
            continue
        safe.append(
            {
                "target": target,
                "status": str(status),
                "detail": _ROLLBACK_DETAILS[str(status)],
            }
        )
    return safe


def _safe_project_evidence(value: Any) -> dict[str, Any]:
    """Reduce transaction evidence to identifiers, states, versions, and hashes."""
    if not isinstance(value, Mapping):
        return {
            "preflight": None,
            "sources": [],
            "targets": [],
            "planned_operation_ids": [],
            "post_apply_verification": [],
            "exception": None,
        }
    preflight = value.get("preflight")
    safe_preflight = None
    if isinstance(preflight, Mapping):
        safe_preflight = {
            "identity_fingerprint": preflight.get("identity_fingerprint")
            if isinstance(preflight.get("identity_fingerprint"), str)
            and _FINGERPRINT.fullmatch(str(preflight["identity_fingerprint"]))
            else None,
            "inspection_id": preflight.get("inspection_id")
            if isinstance(preflight.get("inspection_id"), str)
            and _FINGERPRINT.fullmatch(str(preflight["inspection_id"]))
            else None,
            "classification": preflight.get("classification")
            if _allowed_string(preflight.get("classification"), _CLASSIFICATIONS)
            else "unknown",
            "components": [],
        }
        raw_components = preflight.get("components", [])
        if isinstance(raw_components, Sequence) and not isinstance(
            raw_components, (str, bytes)
        ):
            for item in raw_components:
                if not isinstance(item, Mapping):
                    continue
                component = item.get("component")
                if not _allowed_string(component, _COMPONENTS):
                    continue
                requirement_ids = item.get("requirement_ids", [])
                safe_preflight["components"].append(
                    {
                        "component": str(component),
                        "classification": (
                            str(item["classification"])
                            if _allowed_string(
                                item.get("classification"), _CLASSIFICATIONS
                            )
                            else "unknown"
                        ),
                        "requirement_ids": [
                            str(requirement)
                            for requirement in requirement_ids
                            if _allowed_string(requirement, _EVIDENCE_IDS)
                        ],
                    }
                )

    safe_sources: list[dict[str, Any]] = []
    for item in (
        value.get("sources", []) if isinstance(value.get("sources", []), list) else []
    ):
        if not isinstance(item, Mapping):
            continue
        fingerprint = item.get("fingerprint")
        if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
            continue
        component = item.get("component")
        if not _allowed_string(component, _COMPONENTS):
            continue
        version = item.get("version")
        safe_sources.append(
            {
                "component": str(component),
                "version": (
                    str(version)
                    if version == "unknown"
                    or isinstance(version, str)
                    and _VERSION.fullmatch(version)
                    else "unknown"
                ),
                "fingerprint": fingerprint,
            }
        )

    safe_targets: list[dict[str, Any]] = []
    for item in (
        value.get("targets", []) if isinstance(value.get("targets", []), list) else []
    ):
        if not isinstance(item, Mapping):
            continue
        before = item.get("before_fingerprint")
        if not isinstance(before, str) or not _FINGERPRINT.fullmatch(before):
            continue
        target = item.get("target")
        kind = item.get("kind")
        if not _allowed_string(target, _TARGETS) or not _allowed_string(
            kind, _TARGET_KINDS
        ):
            continue
        safe_targets.append(
            {
                "target": str(target),
                "kind": str(kind),
                "before_fingerprint": before,
            }
        )

    planned = value.get("planned_operation_ids", [])
    safe_planned = (
        [
            str(item)
            for item in planned
            if isinstance(item, str) and _OPERATION_ID.fullmatch(item)
        ]
        if isinstance(planned, list)
        else []
    )

    verification: list[dict[str, Any]] = []
    raw_verification = value.get("post_apply_verification", [])
    if isinstance(raw_verification, list):
        for item in raw_verification:
            if not isinstance(item, Mapping):
                continue
            component = item.get("component")
            state = item.get("state")
            if not _allowed_string(component, _COMPONENTS) or not _allowed_string(
                state, _VERIFICATION
            ):
                continue
            evidence_ids = item.get("evidence_ids", [])
            verification.append(
                {
                    "component": str(component),
                    "state": str(state),
                    "evidence_ids": [
                        str(evidence)
                        for evidence in evidence_ids
                        if _allowed_string(evidence, _EVIDENCE_IDS)
                    ],
                }
            )

    exception = value.get("exception")
    safe_exception = None
    if isinstance(exception, Mapping):
        code = str(exception.get("code", "unexpected"))
        if code not in _SAFE_EXCEPTION_DETAILS:
            code = "unexpected"
        safe_exception = {
            "type": (
                str(exception["type"])
                if _allowed_string(exception.get("type"), _EXCEPTION_TYPES)
                else "TransactionError"
            ),
            "code": code,
            "detail": _SAFE_EXCEPTION_DETAILS[code],
        }
    return {
        "preflight": safe_preflight,
        "sources": safe_sources,
        "targets": safe_targets,
        "planned_operation_ids": safe_planned,
        "post_apply_verification": verification,
        "exception": safe_exception,
    }


def _safe_machine_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    helper = value.get("helper") if isinstance(value.get("helper"), Mapping) else {}
    authentication = (
        value.get("authentication")
        if isinstance(value.get("authentication"), Mapping)
        else {}
    )
    connectivity = (
        value.get("connectivity")
        if isinstance(value.get("connectivity"), Mapping)
        else {}
    )
    layers = value.get("layers") if isinstance(value.get("layers"), Mapping) else {}
    frameworks: list[dict[str, str]] = []
    if isinstance(value.get("frameworks"), list):
        for item in value["frameworks"]:
            if isinstance(item, Mapping):
                component = item.get("component")
                if not _allowed_string(component, _COMPONENTS):
                    continue
                state = item.get("state")
                version = item.get("version")
                frameworks.append(
                    {
                        "component": str(component),
                        "state": (
                            str(state)
                            if _allowed_string(state, _FRAMEWORK_STATES)
                            else "unknown"
                        ),
                        "version": (
                            str(version)
                            if version == "unknown"
                            or isinstance(version, str)
                            and _VERSION.fullmatch(version)
                            else "unknown"
                        ),
                    }
                )
    dependencies: list[dict[str, str]] = []
    if isinstance(value.get("dependencies"), list):
        for item in value["dependencies"]:
            if isinstance(item, Mapping):
                identifier = item.get("id")
                if not _allowed_string(identifier, _DEPENDENCY_IDS):
                    continue
                state = item.get("state")
                dependencies.append(
                    {
                        "id": str(identifier),
                        "state": (
                            str(state)
                            if _allowed_string(state, _DEPENDENCY_STATES)
                            else "unknown"
                        ),
                    }
                )
    return {
        "state": (
            str(value["state"])
            if _allowed_string(value.get("state"), _MACHINE_STATES)
            else "unknown"
        ),
        "helper": {
            "state": (
                str(helper["state"])
                if _allowed_string(helper.get("state"), _HELPER_STATES)
                else "unknown"
            ),
            "version": (
                str(helper["version"])
                if helper.get("version") == "unknown"
                or isinstance(helper.get("version"), str)
                and _VERSION.fullmatch(str(helper["version"]))
                else "unknown"
            ),
        },
        "frameworks": frameworks,
        "authentication": {
            "state": (
                str(authentication["state"])
                if _allowed_string(authentication.get("state"), _AUTH_STATES)
                else "unknown"
            ),
            "credential_state": (
                str(authentication["credential_state"])
                if _allowed_string(
                    authentication.get("credential_state"), _CREDENTIAL_STATES
                )
                else "unknown"
            ),
        },
        "connectivity": {
            "state": (
                str(connectivity["state"])
                if _allowed_string(connectivity.get("state"), _CONNECTIVITY_STATES)
                else "unknown"
            )
        },
        "layers": {
            "state": (
                str(layers["state"])
                if _allowed_string(layers.get("state"), _LAYER_STATES)
                else "unknown"
            ),
            "ready": int(layers.get("ready", 0))
            if isinstance(layers.get("ready", 0), int)
            else 0,
            "total": int(layers.get("total", 0))
            if isinstance(layers.get("total", 0), int)
            else 0,
        },
        "dependencies": dependencies,
    }


def _safe_census(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): count
        for key, count in value.items()
        if _allowed_string(key, _CENSUS_KEYS) and isinstance(count, int) and count >= 0
    }


def _safe_text(value: Any, *, limit: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ReconciliationDiagnosticError(
            "A reviewed plan contains an invalid authored string."
        )
    return value


def _canonical_selection_request(
    value: Any, request_fingerprint: str
) -> dict[str, Any]:
    from cc.core.ecosystem.reconciliation_types import (
        canonical_request_json,
        parse_reconciliation_request,
    )

    try:
        request = parse_reconciliation_request(value)
        canonical = json.loads(canonical_request_json(request))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReconciliationDiagnosticError(
            "The canonical reconciliation request is invalid."
        ) from exc
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    if "sha256:" + hashlib.sha256(encoded).hexdigest() != request_fingerprint:
        raise ReconciliationDiagnosticError(
            "The canonical reconciliation request binding is invalid."
        )
    return canonical


def _safe_reviewed_plans(
    value: Any, canonical_request: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReconciliationDiagnosticError("The reviewed plans are invalid.")
    expected_paths = [
        item.get("path")
        for item in canonical_request.get("projects", [])
        if isinstance(item, Mapping)
    ]
    safe: list[dict[str, Any]] = []
    required = {
        "path",
        "inspection_id",
        "recipes",
        "sources",
        "operations",
        "preservation",
        "prohibited_actions",
        "verification",
    }
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ReconciliationDiagnosticError("A reviewed project plan is invalid.")
        path = raw.get("path")
        inspection_id = raw.get("inspection_id")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or not isinstance(inspection_id, str)
            or not _FINGERPRINT.fullmatch(inspection_id)
        ):
            raise ReconciliationDiagnosticError("A reviewed project plan is invalid.")

        recipes: list[dict[str, str]] = []
        recipe_components: set[str] = set()
        raw_recipes = raw.get("recipes")
        if not isinstance(raw_recipes, list) or not raw_recipes or len(raw_recipes) > 2:
            raise ReconciliationDiagnosticError("A reviewed recipe binding is invalid.")
        for recipe in raw_recipes:
            if not isinstance(recipe, Mapping) or set(recipe) != {
                "component",
                "recipe_id",
            }:
                raise ReconciliationDiagnosticError(
                    "A reviewed recipe binding is invalid."
                )
            component = recipe.get("component")
            recipe_id = recipe.get("recipe_id")
            if (
                component not in _COMPONENTS
                or component in recipe_components
                or not isinstance(recipe_id, str)
                or not _RECIPE_ID.fullmatch(recipe_id)
            ):
                raise ReconciliationDiagnosticError(
                    "A reviewed recipe binding is invalid."
                )
            recipe_components.add(str(component))
            recipes.append({"component": str(component), "recipe_id": recipe_id})

        sources: list[dict[str, str]] = []
        source_components: set[str] = set()
        raw_sources = raw.get("sources")
        if not isinstance(raw_sources, list) or len(raw_sources) > 2:
            raise ReconciliationDiagnosticError("A reviewed source binding is invalid.")
        for source in raw_sources:
            if not isinstance(source, Mapping) or set(source) != {
                "component",
                "version",
                "fingerprint",
            }:
                raise ReconciliationDiagnosticError(
                    "A reviewed source binding is invalid."
                )
            component = source.get("component")
            version = source.get("version")
            fingerprint = source.get("fingerprint")
            if (
                component not in recipe_components
                or component in source_components
                or not isinstance(version, str)
                or not (version == "unknown" or _VERSION.fullmatch(version))
                or not isinstance(fingerprint, str)
                or not _FINGERPRINT.fullmatch(fingerprint)
            ):
                raise ReconciliationDiagnosticError(
                    "A reviewed source binding is invalid."
                )
            source_components.add(str(component))
            sources.append(
                {
                    "component": str(component),
                    "version": version,
                    "fingerprint": fingerprint,
                }
            )

        operations: list[dict[str, Any]] = []
        operation_ids: set[str] = set()
        operation_targets: set[str] = set()
        raw_operations = raw.get("operations")
        if not isinstance(raw_operations, list):
            raise ReconciliationDiagnosticError("A reviewed operation is invalid.")
        for operation in raw_operations:
            operation_keys = {
                "id",
                "kind",
                "component",
                "target",
                "description",
                "expected_before_fingerprint",
                "source_fingerprint",
            }
            if not isinstance(operation, Mapping) or set(operation) != operation_keys:
                raise ReconciliationDiagnosticError("A reviewed operation is invalid.")
            operation_id = operation.get("id")
            target = operation.get("target")
            before = operation.get("expected_before_fingerprint")
            source_fingerprint = operation.get("source_fingerprint")
            if (
                not isinstance(operation_id, str)
                or not _OPERATION_ID.fullmatch(operation_id)
                or operation_id in operation_ids
                or operation.get("kind") not in _OPERATION_KINDS
                or operation.get("component") not in recipe_components
                or target not in _TARGETS
                or target in operation_targets
                or not isinstance(before, str)
                or not _FINGERPRINT.fullmatch(before)
                or source_fingerprint is not None
                and (
                    not isinstance(source_fingerprint, str)
                    or not _FINGERPRINT.fullmatch(source_fingerprint)
                )
            ):
                raise ReconciliationDiagnosticError("A reviewed operation is invalid.")
            operation_ids.add(operation_id)
            operation_targets.add(str(target))
            operations.append(
                {
                    "id": operation_id,
                    "kind": str(operation["kind"]),
                    "component": str(operation["component"]),
                    "target": str(target),
                    "description": _safe_text(operation.get("description")),
                    "expected_before_fingerprint": before,
                    "source_fingerprint": source_fingerprint,
                }
            )

        preservation: list[dict[str, str]] = []
        raw_preservation = raw.get("preservation")
        if not isinstance(raw_preservation, list):
            raise ReconciliationDiagnosticError("A preservation record is invalid.")
        for artifact in raw_preservation:
            if not isinstance(artifact, Mapping) or set(artifact) != {
                "kind",
                "path",
                "detail",
            }:
                raise ReconciliationDiagnosticError("A preservation record is invalid.")
            preservation.append(
                {
                    "kind": _safe_text(artifact.get("kind"), limit=128),
                    "path": _safe_text(artifact.get("path"), limit=4096),
                    "detail": _safe_text(artifact.get("detail")),
                }
            )

        def safe_strings(field: str) -> list[str]:
            values = raw.get(field)
            if (
                not isinstance(values, list)
                or (field == "verification" and not values)
                or any(not isinstance(item, str) for item in values)
                or len(values) != len(set(values))
            ):
                raise ReconciliationDiagnosticError(
                    f"The reviewed {field} list is invalid."
                )
            return [_safe_text(item) for item in values]

        safe.append(
            {
                "path": path,
                "inspection_id": inspection_id,
                "recipes": recipes,
                "sources": sources,
                "operations": operations,
                "preservation": preservation,
                "prohibited_actions": safe_strings("prohibited_actions"),
                "verification": safe_strings("verification"),
            }
        )
    if [item["path"] for item in safe] != expected_paths:
        raise ReconciliationDiagnosticError(
            "The reviewed plans do not match their canonical request."
        )
    return safe


def safe_project_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the schema-owned, content-free receipt vocabulary."""
    path = value.get("path")
    status = value.get("status")
    verification = value.get("verification")
    completed = value.get("completed_operation_ids", [])
    if (
        not isinstance(path, str)
        or not path
        or not _allowed_string(status, _STATUSES)
        or not _allowed_string(verification, _VERIFICATION)
        or not isinstance(completed, Sequence)
        or isinstance(completed, (str, bytes))
        or any(
            not isinstance(item, str) or not _OPERATION_ID.fullmatch(item)
            for item in completed
        )
    ):
        raise ReconciliationDiagnosticError("A project receipt has an invalid shape.")
    return {
        "path": path,
        "status": str(status),
        "detail": _DETAILS[str(status)],
        "completed_operation_ids": list(dict.fromkeys(completed)),
        "verification": str(verification),
        "rollback": _safe_rollback(value.get("rollback", [])),
        "evidence": _safe_project_evidence(value.get("diagnostic_evidence")),
    }


def _load_or_create(path: Path, run_id: str, created_at: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "kind": "ecosystem-reconciliation",
            "run_id": run_id,
            "created_at": created_at,
            "requested_plan_id": None,
            "fresh_plan_fingerprint": None,
            "request_fingerprint": None,
            "canonical_request": None,
            "reviewed_plans": None,
            "source_bindings": None,
            "projects": [],
            "finalized_at": None,
        }
    if path.is_symlink():
        raise ReconciliationDiagnosticError("The reconciliation record is symlinked.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReconciliationDiagnosticError(
            "The reconciliation record is unreadable."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != DIAGNOSTIC_SCHEMA_VERSION
        or payload.get("run_id") != run_id
        or not isinstance(payload.get("projects"), list)
    ):
        raise ReconciliationDiagnosticError("The reconciliation record is invalid.")
    return payload


def _prune(directory: Path, retention: int = DEFAULT_RETENTION) -> None:
    records: list[tuple[int, str, Path]] = []
    for candidate in directory.glob("reconciliation-run_*.json"):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            records.append((candidate.stat().st_mtime_ns, candidate.name, candidate))
        except OSError:
            continue
    records.sort(reverse=True)
    for _, _, candidate in records[max(1, retention) :]:
        try:
            candidate.unlink()
        except OSError:
            continue


def append_project_receipt(
    run_id: str,
    receipt: Mapping[str, Any],
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> DiagnosticReference:
    """Fsync one project outcome before a batch advances to its next peer."""
    _validate_run_id(run_id)
    safe = safe_project_receipt(receipt)
    created_at = _timestamp(now)
    try:
        directory = _directory(root)
        path = directory / f"reconciliation-{run_id}.json"
        with advisory_file_lock(directory / ".diagnostics.lock"):
            payload = _load_or_create(path, run_id, created_at)
            projects = [
                item
                for item in payload["projects"]
                if isinstance(item, dict) and item.get("path") != safe["path"]
            ]
            projects.append(safe)
            payload["projects"] = projects
            atomic_json_write(path, payload)
            _prune(directory)
        return _reference(run_id, state="available", path=path, created_at=created_at)
    except (
        OSError,
        ProjectLockContention,
        ProjectLockError,
        ReconciliationDiagnosticError,
    ):
        return _reference(run_id, state="unavailable", path=None, created_at=created_at)


def load_run_project_receipts(
    run_id: str, *, root: Optional[Path] = None
) -> tuple[dict[str, Any], ...]:
    """Read and strictly revalidate fsynced per-project recovery receipts."""
    _validate_run_id(run_id)
    directory = _directory(root)
    path = directory / f"reconciliation-{run_id}.json"
    with advisory_file_lock(directory / ".diagnostics.lock"):
        if not path.exists():
            return ()
        payload = _load_or_create(path, run_id, _timestamp())
        safe: list[dict[str, Any]] = []
        for item in payload.get("projects", []):
            if not isinstance(item, Mapping):
                raise ReconciliationDiagnosticError(
                    "A persisted project receipt is invalid."
                )
            candidate = {
                key: item.get(key)
                for key in (
                    "path",
                    "status",
                    "completed_operation_ids",
                    "verification",
                    "rollback",
                )
            }
            candidate["diagnostic_evidence"] = item.get("evidence")
            safe.append(safe_project_receipt(candidate))
        if len({item["path"] for item in safe}) != len(safe):
            raise ReconciliationDiagnosticError(
                "Persisted project receipts repeat a project."
            )
        return tuple(safe)


def finalize_run_diagnostic(
    run_id: str,
    plan_id: str,
    request_fingerprint: str,
    ledger: Sequence[Mapping[str, Any]],
    *,
    canonical_request: Mapping[str, Any],
    reviewed_plans: Sequence[Mapping[str, Any]],
    fresh_plan_fingerprint: str,
    helper_version: str = "unknown",
    schema_version: str = "1.0",
    machine_evidence: Optional[Mapping[str, Any]] = None,
    project_evidence: Optional[Sequence[Mapping[str, Any]]] = None,
    final_census: Optional[Mapping[str, int]] = None,
    overlap_explanation: str = "No overlapping project outcomes were reported.",
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> DiagnosticReference:
    """Atomically finalize the run from the same allowlisted ledger vocabulary."""
    _validate_run_id(run_id)
    if (
        not isinstance(plan_id, str)
        or not _PLAN_ID.fullmatch(plan_id)
        or not isinstance(request_fingerprint, str)
        or not _FINGERPRINT.fullmatch(request_fingerprint)
        or not isinstance(fresh_plan_fingerprint, str)
        or not _FINGERPRINT.fullmatch(fresh_plan_fingerprint)
        or not isinstance(helper_version, str)
        or helper_version != "unknown"
        and not _VERSION.fullmatch(helper_version)
        or not isinstance(schema_version, str)
        or not _SCHEMA_VERSION.fullmatch(schema_version)
    ):
        raise ReconciliationDiagnosticError("The final diagnostic binding is invalid.")
    safe_request = _canonical_selection_request(canonical_request, request_fingerprint)
    safe_plans = _safe_reviewed_plans(reviewed_plans, safe_request)
    safe_ledger = [safe_project_receipt(item) for item in ledger]
    if [item["path"] for item in safe_ledger] != [item["path"] for item in safe_plans]:
        raise ReconciliationDiagnosticError(
            "The final diagnostic ledger does not match its reviewed plans."
        )
    created_at = _timestamp(now)
    try:
        directory = _directory(root)
        path = directory / f"reconciliation-{run_id}.json"
        with advisory_file_lock(directory / ".diagnostics.lock"):
            payload = _load_or_create(path, run_id, created_at)
            persisted = {
                str(item.get("path")): item
                for item in payload.get("projects", [])
                if isinstance(item, Mapping) and isinstance(item.get("path"), str)
            }
            for item in safe_ledger:
                prior = persisted.get(item["path"])
                if isinstance(prior, Mapping):
                    item["evidence"] = _safe_project_evidence(prior.get("evidence"))
            if project_evidence is not None:
                by_path = {
                    str(item.get("path")): _safe_project_evidence(item)
                    for item in project_evidence
                    if isinstance(item, Mapping) and isinstance(item.get("path"), str)
                }
                for item in safe_ledger:
                    if item["path"] in by_path:
                        item["evidence"] = by_path[item["path"]]
            payload["helper_version"] = helper_version
            payload["contract_schema_version"] = schema_version
            payload["requested_plan_id"] = plan_id
            payload["fresh_plan_fingerprint"] = fresh_plan_fingerprint
            payload["request_fingerprint"] = request_fingerprint
            payload["canonical_request"] = safe_request
            payload["reviewed_plans"] = safe_plans
            payload["source_bindings"] = [
                {"path": item["path"], "sources": item["sources"]}
                for item in safe_plans
            ]
            payload["machine"] = _safe_machine_evidence(machine_evidence)
            payload["projects"] = safe_ledger
            payload["final_census"] = _safe_census(final_census)
            payload["overlap_explanation"] = (
                overlap_explanation
                if _allowed_string(overlap_explanation, _OVERLAP_EXPLANATIONS)
                else "No overlapping project outcomes were reported."
            )
            payload["finalized_at"] = created_at
            atomic_json_write(path, payload)
            _prune(directory)
        return _reference(run_id, state="available", path=path, created_at=created_at)
    except (
        OSError,
        ProjectLockContention,
        ProjectLockError,
        ReconciliationDiagnosticError,
    ):
        return _reference(run_id, state="unavailable", path=None, created_at=created_at)


__all__ = [
    "DEFAULT_RETENTION",
    "DIAGNOSTIC_SCHEMA_VERSION",
    "DiagnosticReference",
    "ReconciliationDiagnosticError",
    "append_project_receipt",
    "finalize_run_diagnostic",
    "load_run_project_receipts",
    "safe_project_receipt",
]
