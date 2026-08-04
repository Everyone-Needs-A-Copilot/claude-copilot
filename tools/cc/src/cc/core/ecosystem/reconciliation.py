"""Coordinator for the Python-owned ecosystem reconciliation workflow.

Inspection, planning, mutation, verification, and durable evidence remain in
specialized Python modules.  This coordinator only composes those authorities
into one versioned report; callers may inject them for deterministic contract
tests.  GUI clients must treat the resulting JSON as authored truth.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from cc.core.ecosystem.reconciliation_types import (
    RECONCILIATION_SCHEMA_VERSION,
    SUPPORTED_COMPONENTS,
    ProjectRoute,
    ReconciliationRequest,
    canonical_request_json,
    parse_reconciliation_request,
)

MachineBuilder = Callable[[], dict[str, Any]]
CensusBuilder = Callable[..., list[dict[str, Any]]]
PlanBuilder = Callable[..., tuple[list[dict[str, Any]], list[Any]]]
_PLAN_ID = re.compile(r"^plan_[0-9a-f]{32}$")
_RUN_ID = re.compile(r"^run_[0-9a-f]{32}$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPERATION_ID = re.compile(r"^op_[0-9a-f]{64}$")
_CLAIM_TOKEN = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_LEDGER_STATUSES = {
    "applied",
    "blocked",
    "rolled-back",
    "incomplete-rollback",
    "unchanged",
}
_VERIFICATION_STATES = {"ready", "failed", "not-run"}
_ROLLBACK_STATUSES = {"restored", "mismatch", "conflict", "unreadable"}
_LEDGER_DETAILS = {
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


class ReconciliationError(RuntimeError):
    """A closed, plain-language reconciliation failure."""

    def __init__(self, code: str, detail: str, *, exit_code: int = 1) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.exit_code = exit_code


@dataclass(frozen=True)
class PreparedReconciliation:
    machine: dict[str, Any]
    projects: list[dict[str, Any]]
    public_plans: list[dict[str, Any]]
    execution_plans: list[Any]
    canonical_request: dict[str, Any]
    request_fingerprint: str
    plan_fingerprint: str


def _timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    return (
        current.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _run_id(value: str | None = None) -> str:
    return value or f"run_{uuid.uuid4().hex}"


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _claim_binding(prepared: PreparedReconciliation) -> str:
    return _fingerprint(
        {
            "request_fingerprint": prepared.request_fingerprint,
            "fresh_plan_fingerprint": prepared.plan_fingerprint,
            "helper_version": str(
                prepared.machine.get("helper", {}).get("version") or "unknown"
            ),
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
        }
    )


def _plan_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _validated_projects(
    projects: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    supported_routes = {route.value for route in ProjectRoute}
    for raw in projects:
        if not isinstance(raw, Mapping):
            raise ReconciliationError(
                "invalid-census",
                "The project census returned an unsupported project record.",
                exit_code=2,
            )
        project = dict(raw)
        path = project.get("path")
        route = project.get("route")
        if not isinstance(path, str) or not path or path in seen:
            raise ReconciliationError(
                "invalid-census",
                "The project census returned a missing or repeated project path.",
                exit_code=2,
            )
        if route not in supported_routes:
            raise ReconciliationError(
                "invalid-census",
                "The project census returned an unsupported project route.",
                exit_code=2,
            )
        seen.add(path)
        validated.append(project)
    return validated


def _normalized_path(value: str) -> Path:
    return Path(value)


def _is_beneath(path: str, roots: Sequence[str]) -> bool:
    selected = _normalized_path(path)
    return any(selected.is_relative_to(_normalized_path(raw)) for raw in roots)


def _validate_requested_authority(
    request: ReconciliationRequest,
    machine: Mapping[str, Any],
    projects: Sequence[Mapping[str, Any]],
) -> None:
    configuration = machine.get("configuration")
    approved = (
        configuration.get("approved_roots", [])
        if isinstance(configuration, Mapping)
        else []
    )
    approved_roots = {
        str(_normalized_path(value))
        for value in approved
        if isinstance(value, str) and value
    }
    if any(root not in approved_roots for root in request.roots):
        raise ReconciliationError(
            "unapproved-root",
            "Every requested project folder must still be approved by machine configuration.",
            exit_code=2,
        )
    if any(
        not _is_beneath(project.path, request.roots) for project in request.projects
    ):
        raise ReconciliationError(
            "project-outside-approved-root",
            "Every selected project must be contained by one requested project folder.",
            exit_code=2,
        )

    indexed = {str(project["path"]): project for project in projects}
    requested = {project.path: project for project in request.projects}
    if not set(requested) <= set(indexed):
        raise ReconciliationError(
            "incomplete-census",
            "The project census did not account for every selected project.",
            exit_code=2,
        )
    for path, selection in requested.items():
        project = indexed[path]
        if project.get("root") not in request.roots or not _is_beneath(
            path, request.roots
        ):
            raise ReconciliationError(
                "project-root-mismatch",
                "A selected project no longer belongs to its approved project folder.",
                exit_code=2,
            )
        selected_components = project.get("selected_components")
        if not isinstance(selected_components, list) or set(selected_components) != set(
            selection.components
        ):
            raise ReconciliationError(
                "selection-mismatch",
                "The project census did not preserve the exact component selection.",
                exit_code=2,
            )


def _validate_plans(
    request: ReconciliationRequest,
    projects: Sequence[Mapping[str, Any]],
    public_plans: Sequence[Mapping[str, Any]],
    execution_plans: Sequence[Any],
) -> None:
    requested_paths = {project.path for project in request.projects}
    public_paths = [plan.get("path") for plan in public_plans]
    if (
        len(public_paths) != len(set(public_paths))
        or set(public_paths) != requested_paths
    ):
        raise ReconciliationError(
            "incomplete-plan",
            "The reviewed plan did not account for every selected project exactly once.",
            exit_code=2,
        )
    execution_paths = [_plan_value(plan, "path") for plan in execution_plans]
    if (
        len(execution_paths) != len(set(execution_paths))
        or set(execution_paths) != requested_paths
    ):
        raise ReconciliationError(
            "invalid-execution-plan",
            "The executable plan did not account for every selected project exactly once.",
            exit_code=2,
        )
    execution_by_path = dict(zip(execution_paths, execution_plans, strict=True))

    routes = {str(project["path"]): str(project["route"]) for project in projects}
    unsafe_routes = {
        ProjectRoute.HELD.value,
        ProjectRoute.OWNER_DECISION.value,
        ProjectRoute.COULD_NOT_VERIFY.value,
        ProjectRoute.EXCLUDED.value,
    }
    for plan in public_plans:
        path = str(plan["path"])
        operations = plan.get("operations")
        if not isinstance(operations, list):
            raise ReconciliationError(
                "invalid-plan",
                "A reviewed project plan has an unsupported operation list.",
                exit_code=2,
            )
        if routes[path] in unsafe_routes and operations:
            raise ReconciliationError(
                "unsafe-plan",
                "A held, excluded, ambiguous, or unverifiable project cannot contain operations.",
                exit_code=2,
            )
        execution_operations = _plan_value(execution_by_path[path], "operations")
        if not isinstance(execution_operations, Sequence) or isinstance(
            execution_operations, (str, bytes)
        ):
            raise ReconciliationError(
                "invalid-execution-plan",
                "An executable project plan has an unsupported operation list.",
                exit_code=2,
            )
        public_operation_ids = [operation.get("id") for operation in operations]
        execution_operation_ids = [
            _plan_value(operation, "id") for operation in execution_operations
        ]
        if public_operation_ids != execution_operation_ids:
            raise ReconciliationError(
                "invalid-execution-plan",
                "Executable operations must match the exact reviewed public operations.",
                exit_code=2,
            )


def _summary(projects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    projects = _validated_projects(projects)
    counts = Counter(str(project.get("route")) for project in projects)
    project_counts = {route.value: counts[route.value] for route in ProjectRoute}
    project_counts["total"] = len(projects)
    selected = sum(bool(project.get("selected_components")) for project in projects)
    return {
        "project_counts": project_counts,
        "selected_projects": selected,
        "overlap_explanation": (
            "Each project appears in exactly one project state. Claude and Codex "
            "are reported separately inside that project, so component outcomes "
            "may differ without changing the project count."
        ),
    }


_DEFAULT_ACTIONABLE_ROUTES = {
    ProjectRoute.SAFE_SETUP_AVAILABLE.value,
    ProjectRoute.SAFE_UPDATE_AVAILABLE.value,
    ProjectRoute.CUSTOMIZED_GUIDED_ROUTE.value,
}
_DEFAULT_ACTIONABLE_COMPONENT_ROUTES = {
    "ready",
    "safe-setup-available",
    "safe-update-available",
    "customized-guided-route",
}


def _machine_summary(machine: Mapping[str, Any]) -> dict[str, str]:
    state = str(machine.get("state") or "could-not-verify")
    next_action = machine.get("next_action")
    detail = (
        str(next_action)
        if isinstance(next_action, str) and next_action
        else "Run a fresh assessment before changing any project."
    )
    if state == "ready":
        return {
            "state": state,
            "title": "This Mac has what it needs.",
            "detail": "Control Tower can safely prepare reviewed project plans.",
        }
    if state == "action-required":
        return {
            "state": state,
            "title": "This Mac needs attention.",
            "detail": detail,
        }
    return {
        "state": "could-not-verify",
        "title": "Control Tower could not safely confirm this Mac yet.",
        "detail": detail,
    }


def _default_selection_for(
    project: Mapping[str, Any], *, category: str
) -> dict[str, Any] | None:
    if project.get("route") not in _DEFAULT_ACTIONABLE_ROUTES:
        return None
    if project.get("selected_components") != list(SUPPORTED_COMPONENTS):
        return None
    components = project.get("components")
    if not isinstance(components, list) or len(components) != len(
        SUPPORTED_COMPONENTS
    ):
        return None

    recipe_ids: dict[str, str] = {}
    observed: list[str] = []
    for raw in components:
        if not isinstance(raw, Mapping):
            return None
        component = raw.get("component")
        route = raw.get("state")
        if (
            component not in SUPPORTED_COMPONENTS
            or component in observed
            or route not in _DEFAULT_ACTIONABLE_COMPONENT_ROUTES
            or raw.get("selected") is not True
            or raw.get("recommended") is not True
        ):
            return None
        observed.append(str(component))
        if route == "customized-guided-route":
            options = raw.get("recipe_options")
            if not isinstance(options, list) or len(options) != 1:
                return None
            option = options[0]
            if (
                not isinstance(option, Mapping)
                or option.get("component") != component
                or not isinstance(option.get("recipe_id"), str)
                or not option["recipe_id"]
            ):
                return None
            recipe_ids[str(component)] = str(option["recipe_id"])
    if observed != list(SUPPORTED_COMPONENTS):
        return None

    result: dict[str, Any] = {
        "path": str(project["path"]),
        "components": list(SUPPORTED_COMPONENTS),
        "category": category,
    }
    if recipe_ids:
        result["recipe_ids"] = recipe_ids
    return result


def _default_batch(
    projects: Sequence[Mapping[str, Any]], census_builder: CensusBuilder
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Return Python-authored default selections and a display-ready census.

    The first census contains unselected facts. Every project that is not fully
    ready is then assessed once with the universal Claude-plus-Codex selection.
    Only projects whose selected assessment is deterministic and safe enter the
    default batch. The GUI never repeats this eligibility decision.
    """
    baseline = _validated_projects(projects)
    candidate_paths = {
        str(project["path"])
        for project in baseline
        if not (
            project.get("route") == ProjectRoute.READY.value
            and project.get("presence") == "both"
        )
    }
    trial_by_path: dict[str, dict[str, Any]] = {}
    if candidate_paths:
        roots = list(
            dict.fromkeys(
                str(project["root"])
                for project in baseline
                if isinstance(project.get("root"), str) and project["root"]
            )
        )
        trial = _validated_projects(
            census_builder(
                roots=roots,
                selections={
                    path: list(SUPPORTED_COMPONENTS)
                    for path in sorted(candidate_paths)
                },
                detail=True,
            )
        )
        if {str(project["path"]) for project in trial} != {
            str(project["path"]) for project in baseline
        }:
            raise ReconciliationError(
                "invalid-census",
                "The project census changed while the safe default batch was being checked.",
                exit_code=2,
            )
        trial_by_path = {str(project["path"]): project for project in trial}

    selections: list[dict[str, Any]] = []
    rendered: list[dict[str, Any]] = []
    counts = {
        "new_setup": 0,
        "correction": 0,
        "ready": 0,
        "needs_review": 0,
        "selected": 0,
        "total": len(baseline),
    }
    for project in baseline:
        path = str(project["path"])
        if path not in candidate_paths:
            counts["ready"] += 1
            rendered.append(project)
            continue
        category = "new-setup" if project.get("presence") == "none" else "correction"
        trial_project = trial_by_path[path]
        selection = _default_selection_for(trial_project, category=category)
        if selection is None:
            counts["needs_review"] += 1
            rendered.append(project)
            continue
        selections.append(selection)
        counts["new_setup" if category == "new-setup" else "correction"] += 1
        counts["selected"] += 1
        rendered.append(trial_project)

    if (
        counts["new_setup"]
        + counts["correction"]
        + counts["ready"]
        + counts["needs_review"]
        != counts["total"]
        or counts["selected"] != counts["new_setup"] + counts["correction"]
    ):
        raise ReconciliationError(
            "invalid-census",
            "The default project batch counts did not reconcile.",
            exit_code=2,
        )
    return rendered, selections, counts


def _next_actions(
    machine: Mapping[str, Any], projects: Sequence[Mapping[str, Any]]
) -> list[str]:
    actions: list[str] = []
    machine_action = machine.get("next_action")
    if isinstance(machine_action, str) and machine_action:
        actions.append(machine_action)
    for project in projects:
        action = project.get("next_action")
        if isinstance(action, str) and action and action not in actions:
            actions.append(action)
    return actions or ["Nothing needs to be changed."]


def _assessment_result(
    machine: Mapping[str, Any], projects: Sequence[Mapping[str, Any]]
) -> str:
    if machine.get("state") == "could-not-verify":
        return "blocked"
    if any(
        project.get("route")
        in {
            ProjectRoute.HELD.value,
            ProjectRoute.OWNER_DECISION.value,
            ProjectRoute.COULD_NOT_VERIFY.value,
        }
        for project in projects
    ):
        return "action-required"
    if machine.get("state") != "ready" or any(
        project.get("route") != ProjectRoute.READY.value for project in projects
    ):
        return "action-required"
    return "ready"


def _diagnostic_dict(
    value: Any, *, run_id: str, now: datetime | None
) -> dict[str, Any]:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if isinstance(value, Mapping):
        state = value.get("state")
        identifier = value.get("id")
        path = value.get("path")
        created_at = value.get("created_at")
        if (
            value.get("schema_version") == RECONCILIATION_SCHEMA_VERSION
            and identifier == run_id
            and state in {"available", "unavailable"}
            and (
                (
                    state == "available"
                    and isinstance(path, str)
                    and path.startswith("/")
                    and "\n" not in path
                    and len(path) <= 4096
                )
                or (state == "unavailable" and path is None)
            )
            and isinstance(created_at, str)
            and _TIMESTAMP.fullmatch(created_at)
        ):
            return {
                "schema_version": RECONCILIATION_SCHEMA_VERSION,
                "id": run_id,
                "state": state,
                "path": path if state == "available" else None,
                "created_at": created_at,
                "detail": (
                    "A private redacted reconciliation record was saved."
                    if state == "available"
                    else "The in-memory receipt is available, but its diagnostic record could not be saved."
                ),
            }
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "id": run_id,
        "state": "unavailable",
        "path": None,
        "created_at": _timestamp(now),
        "detail": (
            "The in-memory receipt is available, but its diagnostic record "
            "could not be saved."
        ),
    }


def _blocked_ledger(
    plans: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "path": str(plan["path"]),
            "status": "blocked",
            "detail": "The project was left unchanged because the reviewed plan could not be claimed safely.",
            "completed_operation_ids": [],
            "verification": "not-run",
            "rollback": [],
        }
        for plan in plans
    ]


def _safe_relative_target(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    raw_parts = value.split("/")
    path = PurePosixPath(value)
    return not path.is_absolute() and all(
        part not in {"", ".", ".."} for part in raw_parts
    )


def _normalize_executor_receipt(
    value: Any,
    *,
    path: str,
    operation_ids: Sequence[str],
    operation_targets: Mapping[str, str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or value.get("path") != path:
        return None
    status = value.get("status")
    verification = value.get("verification")
    completed = value.get("completed_operation_ids")
    rollback = value.get("rollback")
    if (
        status not in _LEDGER_STATUSES - {"unchanged"}
        or verification not in _VERIFICATION_STATES
        or not isinstance(completed, list)
        or len(completed) != len(set(completed))
        or any(
            not isinstance(item, str)
            or not _OPERATION_ID.fullmatch(item)
            or item not in operation_ids
            for item in completed
        )
        or not isinstance(rollback, list)
    ):
        return None
    safe_rollback: list[dict[str, str]] = []
    for item in rollback:
        if not isinstance(item, Mapping):
            return None
        target = item.get("target")
        rollback_status = item.get("status")
        if (
            not _safe_relative_target(target)
            or target not in operation_targets.values()
            or rollback_status not in _ROLLBACK_STATUSES
        ):
            return None
        safe_rollback.append(
            {
                "target": target,
                "status": rollback_status,
                "detail": _ROLLBACK_DETAILS[rollback_status],
            }
        )
    if status == "applied" and (
        verification != "ready" or completed != list(operation_ids) or safe_rollback
    ):
        return None
    if completed != list(operation_ids[: len(completed)]):
        return None
    if status == "blocked" and (
        verification != "not-run" or completed or safe_rollback
    ):
        return None
    completed_targets = {operation_targets[item] for item in completed}
    rollback_targets = {item["target"] for item in safe_rollback}
    if len(rollback_targets) != len(safe_rollback):
        return None
    expected_rollback_order = [operation_targets[item] for item in reversed(completed)]
    if (
        status in {"rolled-back", "incomplete-rollback"}
        and [item["target"] for item in safe_rollback] != expected_rollback_order
    ):
        return None
    if status == "rolled-back" and (
        verification != "failed"
        or not completed
        or rollback_targets != completed_targets
        or any(item["status"] != "restored" for item in safe_rollback)
    ):
        return None
    if status == "incomplete-rollback" and (
        verification != "failed"
        or not completed
        or rollback_targets != completed_targets
        or not any(item["status"] != "restored" for item in safe_rollback)
    ):
        return None
    return {
        "path": path,
        "status": status,
        "detail": _LEDGER_DETAILS[status],
        "completed_operation_ids": completed,
        "verification": verification,
        "rollback": safe_rollback,
    }


def _validated_executor_ledger(
    executed: Any,
    execution_plans: Sequence[Any],
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    expected: dict[str, tuple[list[str], dict[str, str]]] = {}
    for plan in execution_plans:
        path = _plan_value(plan, "path")
        operations = _plan_value(plan, "operations")
        if not isinstance(path, str) or not isinstance(operations, Sequence):
            raise ReconciliationError(
                "invalid-execution-plan",
                "A guarded transaction plan has an unsupported shape.",
                exit_code=2,
            )
        expected[path] = (
            [str(_plan_value(operation, "id")) for operation in operations],
            {
                str(_plan_value(operation, "id")): str(_plan_value(operation, "target"))
                for operation in operations
            },
        )
    if not isinstance(executed, Sequence) or isinstance(executed, (str, bytes)):
        return {}, set(expected)
    valid: dict[str, dict[str, Any]] = {}
    invalid: set[str] = set()
    for raw in executed:
        path = raw.get("path") if isinstance(raw, Mapping) else None
        if not isinstance(path, str) or path not in expected or path in valid:
            invalid.add(path if isinstance(path, str) else "<invalid>")
            continue
        operation_ids, operation_targets = expected[path]
        normalized = _normalize_executor_receipt(
            raw,
            path=path,
            operation_ids=operation_ids,
            operation_targets=operation_targets,
        )
        if normalized is None:
            invalid.add(path)
        else:
            valid[path] = normalized
    invalid.update(set(expected) - set(valid))
    return valid, invalid


def _uncertain_receipt(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "status": "incomplete-rollback",
        "detail": (
            "The guarded executor did not return a valid receipt. Inspect this "
            "project and its private diagnostic before continuing."
        ),
        "completed_operation_ids": [],
        "verification": "not-run",
        "rollback": [],
    }


def _receipt_paths(value: Any, expected_paths: set[str]) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    return {
        str(item["path"])
        for item in value
        if isinstance(item, Mapping) and item.get("path") in expected_paths
    }


def _component_map(project: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(component.get("component")): component
        for component in project.get("components", [])
        if isinstance(component, Mapping)
        and component.get("component") in {"claude", "codex"}
    }


def _project_is_freshly_ready(
    project: Mapping[str, Any], selected_components: Sequence[str]
) -> bool:
    selected = set(selected_components)
    components = _component_map(project)
    return (
        project.get("route") == ProjectRoute.READY.value
        and set(project.get("selected_components", [])) == selected
        and bool(selected)
        and all(components.get(name, {}).get("state") == "ready" for name in selected)
    )


def _post_apply_contradictions(
    request: ReconciliationRequest,
    final_machine: Mapping[str, Any],
    final_projects: Sequence[Mapping[str, Any]],
    ledger: Sequence[Mapping[str, Any]],
) -> set[str]:
    if final_machine.get("state") == "could-not-verify":
        return {project.path for project in request.projects}
    selections = {project.path: project.components for project in request.projects}
    by_path = {str(project["path"]): project for project in final_projects}
    return {
        str(receipt["path"])
        for receipt in ledger
        if receipt.get("status") in {"applied", "unchanged"}
        and (
            str(receipt["path"]) not in by_path
            or not _project_is_freshly_ready(
                by_path[str(receipt["path"])],
                selections.get(str(receipt["path"]), ()),
            )
        )
    }


def _diagnostic_evidence(
    prepared: PreparedReconciliation,
    final_projects: Sequence[Mapping[str, Any]],
    ledger: Sequence[Mapping[str, Any]],
    *,
    excluded_paths: set[str],
    failure_code: str | None,
) -> list[dict[str, Any]]:
    """Build closed evidence for paths without transaction-authored receipts."""
    execution_by_path = {
        str(_plan_value(plan, "path")): plan for plan in prepared.execution_plans
    }
    final_by_path = {str(project["path"]): project for project in final_projects}
    receipt_by_path = {str(item["path"]): item for item in ledger}
    prepared_by_path = {str(project["path"]): project for project in prepared.projects}
    evidence: list[dict[str, Any]] = []
    for public in prepared.public_plans:
        path = str(public["path"])
        if path in excluded_paths:
            continue
        project = prepared_by_path[path]
        execution = execution_by_path[path]
        expected_identity = _plan_value(execution, "expected_identity")
        identity_fingerprint = _plan_value(expected_identity, "fingerprint")
        selected = set(project.get("selected_components", []))
        preflight_components = []
        for component_name, component in _component_map(project).items():
            if component_name not in selected:
                continue
            preflight_components.append(
                {
                    "component": component_name,
                    "classification": str(component.get("state") or "unknown"),
                    "requirement_ids": [
                        str(item.get("id"))
                        for item in component.get("missing_requirements", [])
                        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
                    ],
                }
            )
        operations = list(_plan_value(execution, "operations") or ())
        post_components = _component_map(final_by_path.get(path, {}))
        receipt_verification = receipt_by_path.get(path, {}).get(
            "verification", "not-run"
        )
        verification = [
            {
                "component": component,
                "state": (
                    "not-run"
                    if receipt_verification == "not-run"
                    else "ready"
                    if receipt_verification == "ready"
                    and post_components.get(component, {}).get("state") == "ready"
                    else "failed"
                ),
                "evidence_ids": [],
            }
            for component in sorted(selected)
        ]
        evidence.append(
            {
                "path": path,
                "preflight": {
                    "identity_fingerprint": identity_fingerprint,
                    "inspection_id": public.get("inspection_id"),
                    "classification": project.get("route"),
                    "components": preflight_components,
                },
                "sources": [
                    dict(source)
                    for source in (_plan_value(execution, "sources") or ())
                    if isinstance(source, Mapping)
                ],
                "targets": [
                    {
                        "target": _plan_value(operation, "target"),
                        "kind": "uninspected",
                        "before_fingerprint": _plan_value(
                            operation, "expected_before_fingerprint"
                        ),
                    }
                    for operation in operations
                ],
                "planned_operation_ids": [
                    _plan_value(operation, "id") for operation in operations
                ],
                "post_apply_verification": verification,
                "exception": (
                    {
                        "type": "TransactionError",
                        "code": failure_code,
                    }
                    if failure_code is not None
                    else None
                ),
            }
        )
    return evidence


def _zero_operation_receipt(project: Mapping[str, Any]) -> dict[str, Any]:
    selected = set(project.get("selected_components", []))
    component_states = {
        str(component.get("component")): str(component.get("state"))
        for component in project.get("components", [])
        if isinstance(component, Mapping)
    }
    verified = bool(selected) and all(
        component_states.get(component) == "ready" for component in selected
    )
    ready = project.get("route") == ProjectRoute.READY.value and verified
    return {
        "path": str(project["path"]),
        "status": "unchanged" if ready else "blocked",
        "detail": (
            "The reviewed plan required no project mutation."
            if ready
            else "The project was left unchanged because its current route does not permit a typed mutation."
        ),
        "completed_operation_ids": [],
        "verification": "ready" if ready else "not-run",
        "rollback": [],
    }


def _recovery_diagnostic_evidence(
    context: Any,
    final_projects: Sequence[Mapping[str, Any]],
    ledger: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild closed evidence from stored authority and one fresh census."""
    selected_by_path = {
        str(item.get("path")): {
            str(component)
            for component in item.get("components", [])
            if component in {"claude", "codex"}
        }
        for item in context.canonical_request.get("projects", [])
        if isinstance(item, Mapping)
    }
    final_by_path = {str(item["path"]): item for item in final_projects}
    receipt_by_path = {str(item["path"]): item for item in ledger}
    evidence: list[dict[str, Any]] = []
    for plan in context.plans:
        path = str(plan["path"])
        final_project = final_by_path.get(path, {})
        components = _component_map(final_project)
        selected = selected_by_path.get(path, set())
        receipt = receipt_by_path[path]
        operations = [
            item for item in plan.get("operations", []) if isinstance(item, Mapping)
        ]
        evidence.append(
            {
                "path": path,
                "preflight": {
                    "identity_fingerprint": None,
                    "inspection_id": plan.get("inspection_id"),
                    "classification": final_project.get("route", "unknown"),
                    "components": [
                        {
                            "component": component,
                            "classification": components.get(component, {}).get(
                                "state", "unknown"
                            ),
                            "requirement_ids": [
                                str(item.get("id"))
                                for item in components.get(component, {}).get(
                                    "missing_requirements", []
                                )
                                if isinstance(item, Mapping)
                                and isinstance(item.get("id"), str)
                            ],
                        }
                        for component in sorted(selected)
                    ],
                },
                "sources": [
                    dict(item)
                    for item in plan.get("sources", [])
                    if isinstance(item, Mapping)
                ],
                "targets": [
                    {
                        "target": item.get("target"),
                        "kind": "uninspected",
                        "before_fingerprint": item.get("expected_before_fingerprint"),
                    }
                    for item in operations
                ],
                "planned_operation_ids": [item.get("id") for item in operations],
                "post_apply_verification": [
                    {
                        "component": component,
                        "state": (
                            "ready"
                            if receipt.get("verification") == "ready"
                            and components.get(component, {}).get("state") == "ready"
                            else "failed"
                            if receipt.get("verification") == "failed"
                            else "not-run"
                        ),
                        "evidence_ids": [],
                    }
                    for component in sorted(selected)
                ],
                "exception": (
                    None
                    if receipt.get("status") in {"applied", "unchanged"}
                    else {"type": "TransactionError", "code": "interrupted"}
                ),
            }
        )
    return evidence


def _ledger_result(ledger: Sequence[Mapping[str, Any]]) -> str:
    statuses = [str(item.get("status")) for item in ledger]
    successes = sum(status in {"applied", "unchanged"} for status in statuses)
    failures = sum(
        status in {"blocked", "rolled-back", "incomplete-rollback"}
        for status in statuses
    )
    if any(status == "incomplete-rollback" for status in statuses):
        return "partial"
    if successes and failures:
        return "partial"
    if failures:
        return "blocked"
    return "applied"


def _default_machine_builder() -> dict[str, Any]:
    from cc.core.ecosystem.machine_assessment import build_machine_assessment

    return build_machine_assessment()


def _default_census_builder(**kwargs: Any) -> list[dict[str, Any]]:
    from cc.core.ecosystem.project_reconciliation import build_project_census

    return build_project_census(**kwargs)


def _default_plan_builder(**kwargs: Any) -> tuple[list[dict[str, Any]], list[Any]]:
    from cc.core.ecosystem.project_reconciliation import build_project_plans

    return build_project_plans(**kwargs)


def assess_reconciliation(
    *,
    machine_builder: MachineBuilder | None = None,
    census_builder: CensusBuilder | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Compose one complete, read-only machine and project assessment."""
    machine = (machine_builder or _default_machine_builder)()
    selected_census, default_selection, batch_summary = _default_batch(
        _validated_projects(
            (census_builder or _default_census_builder)(detail=True)
        ),
        census_builder or _default_census_builder,
    )
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "assess",
        "result": _assessment_result(machine, selected_census),
        "run_id": _run_id(run_id),
        "generated_at": _timestamp(now),
        "machine": machine,
        "machine_summary": _machine_summary(machine),
        "projects": selected_census,
        "default_selection": default_selection,
        "batch_summary": batch_summary,
        "summary": _summary(selected_census),
        "next_actions": _next_actions(machine, selected_census),
    }


def prepare_reconciliation(
    request: ReconciliationRequest,
    *,
    machine_builder: MachineBuilder | None = None,
    census_builder: CensusBuilder | None = None,
    plan_builder: PlanBuilder | None = None,
) -> PreparedReconciliation:
    """Freshly inspect and construct content-free plus executable plans."""
    selections = {
        project.path: list(project.components) for project in request.projects
    }
    recipe_ids = {
        project.path: dict(project.recipe_ids)
        for project in request.projects
        if project.recipe_ids
    }
    machine = (machine_builder or _default_machine_builder)()
    try:
        projects = _validated_projects(
            (census_builder or _default_census_builder)(
                roots=request.roots,
                selections=selections,
                detail=True,
            )
        )
    except ReconciliationError:
        raise
    except Exception as exc:
        raise ReconciliationError(
            "invalid-project-authority",
            "The selected project authority could not be inspected safely. Assess again before planning.",
            exit_code=2,
        ) from exc
    _validate_requested_authority(request, machine, projects)
    try:
        public_plans, execution_plans = (plan_builder or _default_plan_builder)(
            projects=projects,
            selections=selections,
            recipe_ids=recipe_ids,
        )
    except ReconciliationError:
        raise
    except Exception as exc:
        message = str(exc).lower()
        source_unavailable = (
            "authoritative" in message and "source" in message
        ) or any(
            token in message for token in ("source file", "source tree", "source root")
        )
        raise ReconciliationError(
            "recipe-unavailable" if source_unavailable else "invalid-recipe",
            (
                "The selected reviewed recipe is not available from the verified framework source. Repair the framework source, then assess again."
                if source_unavailable
                else "The selected recipe id is unknown or does not apply to this component state. Choose an option returned by the fresh assessment."
            ),
            exit_code=1 if source_unavailable else 2,
        ) from exc
    _validate_plans(request, projects, public_plans, execution_plans)
    canonical_request = json.loads(canonical_request_json(request))
    request_fingerprint = _fingerprint(canonical_request)
    selected_paths = {str(project.path) for project in request.projects}
    selected_projects = [
        project for project in projects if str(project["path"]) in selected_paths
    ]
    plan_fingerprint = _fingerprint(
        {
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
            "request_fingerprint": request_fingerprint,
            "machine": machine,
            "projects": selected_projects,
            "plans": public_plans,
        }
    )
    return PreparedReconciliation(
        machine,
        projects,
        public_plans,
        execution_plans,
        canonical_request,
        request_fingerprint,
        plan_fingerprint,
    )


def build_plan_report(
    request: ReconciliationRequest,
    *,
    machine_builder: MachineBuilder | None = None,
    census_builder: CensusBuilder | None = None,
    plan_builder: PlanBuilder | None = None,
    plan_issuer: Callable[..., Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Issue a private, expiring capability for one freshly reviewed plan."""
    prepared = prepare_reconciliation(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_builder=plan_builder,
    )
    if plan_issuer is None:
        from cc.core.ecosystem.project_plan_store import issue_plan

        plan_issuer = issue_plan
    issued = plan_issuer(
        request_fingerprint=prepared.request_fingerprint,
        fresh_plan_fingerprint=prepared.plan_fingerprint,
        plans=prepared.public_plans,
        canonical_request=prepared.canonical_request,
        helper_version=str(
            prepared.machine.get("helper", {}).get("version") or "unknown"
        ),
        schema_version=RECONCILIATION_SCHEMA_VERSION,
    )
    has_operations = any(plan.get("operations") for plan in prepared.public_plans)
    assessment_result = _assessment_result(prepared.machine, prepared.projects)
    projects_by_path = {str(project["path"]): project for project in prepared.projects}
    has_blocked_selection = any(
        not plan.get("operations")
        and projects_by_path[str(plan["path"])].get("route") != ProjectRoute.READY.value
        for plan in prepared.public_plans
    )
    result = (
        "blocked"
        if assessment_result == "blocked"
        else "action-required"
        if has_operations
        else "blocked"
        if has_blocked_selection
        else assessment_result
    )
    issued_plan_id = _plan_value(issued, "plan_id") or _plan_value(issued, "id")
    expires_at = _plan_value(issued, "expires_at")
    if not isinstance(issued_plan_id, str) or not isinstance(expires_at, str):
        raise ReconciliationError(
            "plan-store-error",
            "The private plan store returned an invalid capability.",
            exit_code=2,
        )
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "plan",
        "result": result,
        "run_id": _run_id(run_id),
        "generated_at": _timestamp(now),
        "machine": prepared.machine,
        "projects": prepared.projects,
        "summary": _summary(prepared.projects),
        "next_actions": _next_actions(prepared.machine, prepared.projects),
        "request_fingerprint": prepared.request_fingerprint,
        "plan_id": issued_plan_id,
        "expires_at": expires_at,
        "plans": prepared.public_plans,
    }


def build_apply_report(
    request: ReconciliationRequest,
    requested_plan_id: str,
    *,
    machine_builder: MachineBuilder | None = None,
    census_builder: CensusBuilder | None = None,
    plan_builder: PlanBuilder | None = None,
    plan_claimer: Callable[..., Any] | None = None,
    plan_finisher: Callable[..., Any] | None = None,
    plan_finalizer: Callable[..., Any] | None = None,
    recovery_checker: Callable[..., Sequence[str]] | None = None,
    transaction_adapter: Callable[[Any], Any] | None = None,
    transaction_executor: Callable[..., list[dict[str, Any]]] | None = None,
    diagnostic_finalizer: Callable[..., Any] | None = None,
    state_root: Path | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Claim, execute, verify, consume, and receipt one exact reviewed plan."""
    if not isinstance(requested_plan_id, str) or not _PLAN_ID.fullmatch(
        requested_plan_id
    ):
        raise ReconciliationError(
            "invalid-plan-id",
            "Provide the exact opaque plan identifier returned by plan.",
            exit_code=2,
        )
    if recovery_checker is None:
        from cc.core.ecosystem.project_plan_store import incomplete_run_ids

        recovery_checker = incomplete_run_ids
    try:
        pending_runs = tuple(recovery_checker(root=state_root))
    except Exception as exc:
        raise ReconciliationError(
            "recovery-required",
            "Private reconciliation recovery state is unreadable. Run reconcile recover before applying a new plan.",
        ) from exc
    if pending_runs:
        raise ReconciliationError(
            "recovery-required",
            "An interrupted reconciliation must be recovered before applying a new plan. Run cc reconcile recover --json, then create a fresh plan.",
        )

    current_run_id = _run_id(run_id)
    prepared = prepare_reconciliation(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
        plan_builder=plan_builder,
    )

    custom_plan_finisher = plan_finisher is not None
    if plan_claimer is None or plan_finisher is None or plan_finalizer is None:
        from cc.core.ecosystem.project_plan_store import (
            claim_plan,
            finalize_run_intent,
            finish_plan,
        )

        if plan_claimer is None:

            def stored_plan_claimer(*args: Any, **kwargs: Any) -> Any:
                return claim_plan(*args, **kwargs, root=state_root)

            plan_claimer = stored_plan_claimer
        if plan_finisher is None:

            def stored_plan_finisher(*args: Any, **kwargs: Any) -> Any:
                return finish_plan(*args, **kwargs, root=state_root)

            plan_finisher = stored_plan_finisher
        if plan_finalizer is None:
            if custom_plan_finisher:

                def noop_plan_finalizer(*_args: Any, **_kwargs: Any) -> None:
                    return None

                plan_finalizer = noop_plan_finalizer
            else:

                def stored_plan_finalizer(*args: Any, **kwargs: Any) -> Any:
                    return finalize_run_intent(*args, **kwargs, root=state_root)

                plan_finalizer = stored_plan_finalizer
    if transaction_adapter is None:
        from cc.core.ecosystem.reconciliation_transaction import (
            transaction_plan_from_recipe,
        )

        transaction_adapter = transaction_plan_from_recipe
    if transaction_executor is None:
        from cc.core.ecosystem.reconciliation_transaction import (
            execute_reconciliation,
        )

        def stored_transaction_executor(plans: Any, **kwargs: Any) -> Any:
            return execute_reconciliation(plans, **kwargs, root=state_root)

        transaction_executor = stored_transaction_executor
    if diagnostic_finalizer is None:
        from cc.core.ecosystem.reconciliation_diagnostics import (
            finalize_run_diagnostic,
        )

        def stored_diagnostic_finalizer(*args: Any, **kwargs: Any) -> Any:
            return finalize_run_diagnostic(*args, **kwargs, root=state_root)

        diagnostic_finalizer = stored_diagnostic_finalizer

    projects = prepared.projects
    ledger: list[dict[str, Any]] = []
    next_actions = _next_actions(prepared.machine, projects)
    claim: Any | None = None
    claimed = False
    claim_token_for_finish: str | None = None
    result = "blocked"
    transaction_receipt_paths: set[str] = set()
    diagnostic_failure_code: str | None = None
    execution_started = False

    try:
        if _assessment_result(prepared.machine, prepared.projects) == "blocked":
            raise ReconciliationError(
                "unsafe-machine-preflight",
                "The Mac could not be verified safely enough to apply this plan. Resolve its machine blockers, then create a fresh plan.",
            )
        claim = plan_claimer(
            requested_plan_id,
            prepared.request_fingerprint,
            prepared.plan_fingerprint,
            run_id=current_run_id,
        )
        claimed = True
        claim_token = _plan_value(claim, "claim_token")
        claim_binding = _plan_value(claim, "binding_fingerprint")
        if (
            _plan_value(claim, "plan_id") != requested_plan_id
            or not isinstance(claim_token, str)
            or not _CLAIM_TOKEN.fullmatch(claim_token)
            or _plan_value(claim, "request_fingerprint") != prepared.request_fingerprint
            or _plan_value(claim, "fresh_plan_fingerprint") != prepared.plan_fingerprint
            or claim_binding != _claim_binding(prepared)
            or _plan_value(claim, "run_id") != current_run_id
        ):
            raise ReconciliationError(
                "invalid-plan-claim",
                "The private plan store returned an invalid claim. Nothing was executed.",
                exit_code=2,
            )
        claim_token_for_finish = claim_token
        stored_plans = _plan_value(claim, "plans")
        if (
            not isinstance(stored_plans, Sequence)
            or isinstance(stored_plans, (str, bytes))
            or list(stored_plans) != prepared.public_plans
        ):
            raise ReconciliationError(
                "plan-binding-mismatch",
                "The claimed private plan did not match the freshly recomputed plan.",
            )

        executable_recipes = [
            plan for plan in prepared.execution_plans if _plan_value(plan, "operations")
        ]
        executable = [transaction_adapter(plan) for plan in executable_recipes]
        execution_started = True
        executed = transaction_executor(executable, run_id=current_run_id)
        transaction_receipt_paths = _receipt_paths(
            executed,
            {str(_plan_value(plan, "path")) for plan in executable_recipes},
        )
        by_path, ledger_errors = _validated_executor_ledger(
            executed,
            executable_recipes,
        )
        project_by_path = {str(project["path"]): project for project in projects}
        for public_plan in prepared.public_plans:
            path = str(public_plan["path"])
            if public_plan.get("operations"):
                receipt = by_path.get(path)
                if receipt is None:
                    receipt = _uncertain_receipt(path)
                ledger.append(receipt)
            else:
                ledger.append(_zero_operation_receipt(project_by_path[path]))
        result = _ledger_result(ledger)
        if ledger_errors:
            result = "partial"
            diagnostic_failure_code = "unexpected"
            next_actions = [
                "A guarded executor receipt was invalid. Inspect the selected projects and private diagnostic before continuing."
            ]
    except ReconciliationError as exc:
        if not ledger:
            ledger = _blocked_ledger(prepared.public_plans)
        next_actions = [exc.detail]
        result = (
            "partial"
            if any(
                item.get("status") in {"applied", "incomplete-rollback"}
                for item in ledger
            )
            else "blocked"
        )
        diagnostic_failure_code = (
            "stale-plan"
            if exc.code
            in {
                "plan-binding-mismatch",
                "unsafe-machine-preflight",
            }
            else "unexpected"
        )
    except Exception as exc:
        if claimed:
            if not ledger:
                project_by_path = {
                    str(project["path"]): project for project in prepared.projects
                }
                ledger = [
                    (
                        _uncertain_receipt(str(plan["path"]))
                        if execution_started and plan.get("operations")
                        else _zero_operation_receipt(project_by_path[str(plan["path"])])
                        if execution_started
                        else _blocked_ledger([plan])[0]
                    )
                    for plan in prepared.public_plans
                ]
            next_actions = [
                (
                    "The guarded transaction was interrupted after execution began. Run cc reconcile recover --json before another apply."
                    if execution_started
                    else "The guarded transaction stopped safely. Review the private diagnostic, then create a fresh plan."
                )
            ]
        else:
            ledger = _blocked_ledger(prepared.public_plans)
            safe_claim_failures = {
                "PlanNotFound": "The reviewed plan is unavailable. Create a fresh plan.",
                "PlanExpired": "The reviewed plan expired. Create a fresh plan.",
                "PlanBindingMismatch": "The project or request changed after review. Create and review a fresh plan.",
                "PlanAlreadyUsed": "The reviewed plan was already used. Create a fresh plan.",
            }
            next_actions = [
                safe_claim_failures.get(
                    type(exc).__name__,
                    "The private plan could not be claimed safely. Create a fresh plan.",
                )
            ]
        result = (
            "partial"
            if any(
                item.get("status") in {"applied", "incomplete-rollback"}
                for item in ledger
            )
            else "blocked"
        )
        diagnostic_failure_code = (
            "stale-plan"
            if type(exc).__name__
            in {
                "PlanNotFound",
                "PlanExpired",
                "PlanBindingMismatch",
                "PlanAlreadyUsed",
            }
            else "unexpected"
        )

    try:
        final_machine = (machine_builder or _default_machine_builder)()
        selections = {
            project.path: list(project.components) for project in request.projects
        }
        final_projects = _validated_projects(
            (census_builder or _default_census_builder)(
                roots=request.roots,
                selections=selections,
                detail=True,
            )
        )
        _validate_requested_authority(request, final_machine, final_projects)
        contradictions = _post_apply_contradictions(
            request,
            final_machine,
            final_projects,
            ledger,
        )
        if contradictions:
            result = (
                "partial"
                if any(item.get("status") == "applied" for item in ledger)
                else "blocked"
            )
            diagnostic_failure_code = "verification-failed"
            next_actions = [
                "Fresh verification contradicted the transaction receipt. Inspect the selected projects and private diagnostic before continuing."
            ]
    except Exception:
        final_machine = prepared.machine
        final_projects = prepared.projects
        if result == "applied":
            result = "partial"
        next_actions = [
            "The transaction receipt is available, but the final census could not be refreshed. Run verify before continuing."
        ]

    outcome_recorded = False
    if claimed and claim_token_for_finish is not None:
        outcome = result if result in {"partial", "blocked"} else "applied"
        try:
            finished_plan = plan_finisher(
                requested_plan_id,
                claim_token_for_finish,
                outcome,
                ledger=ledger,
            )
            outcome_recorded = (
                _plan_value(finished_plan, "state") != "recovered-projects"
            )
        except Exception:
            result = "partial" if _ledger_result(ledger) == "applied" else "blocked"
            next_actions = [
                "The project receipt is available, but its recovery state could not be recorded. Run cc reconcile recover --json before another apply."
            ]

    summary = _summary(final_projects)
    project_evidence = _diagnostic_evidence(
        prepared,
        final_projects,
        ledger,
        excluded_paths=transaction_receipt_paths,
        failure_code=diagnostic_failure_code,
    )
    try:
        diagnostic_value = diagnostic_finalizer(
            current_run_id,
            requested_plan_id,
            prepared.request_fingerprint,
            ledger,
            canonical_request=prepared.canonical_request,
            reviewed_plans=prepared.public_plans,
            helper_version=str(
                prepared.machine.get("helper", {}).get("version") or "unknown"
            ),
            schema_version=RECONCILIATION_SCHEMA_VERSION,
            fresh_plan_fingerprint=prepared.plan_fingerprint,
            machine_evidence=prepared.machine,
            project_evidence=project_evidence,
            final_census=summary["project_counts"],
            overlap_explanation=summary["overlap_explanation"],
        )
    except Exception:
        diagnostic_value = None
    diagnostic = _diagnostic_dict(
        diagnostic_value,
        run_id=current_run_id,
        now=now,
    )
    run_finalized = not claimed
    if outcome_recorded and diagnostic["state"] == "available":
        try:
            plan_finalizer(
                current_run_id,
                diagnostic_id=diagnostic["id"],
                diagnostic_state=diagnostic["state"],
            )
            run_finalized = True
        except Exception:
            run_finalized = False
    if claimed and not run_finalized:
        result = "partial" if _ledger_result(ledger) == "applied" else "blocked"
        next_actions = [
            "This run still requires durable recovery finalization. Run cc reconcile recover --json before another apply."
        ]
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "apply",
        "result": result,
        "run_id": current_run_id,
        "generated_at": _timestamp(now),
        "machine": final_machine,
        "projects": final_projects,
        "summary": summary,
        "next_actions": next_actions,
        "request_fingerprint": prepared.request_fingerprint,
        "requested_plan_id": requested_plan_id,
        "plan_id": requested_plan_id,
        "ledger": ledger,
        "diagnostics": diagnostic,
    }


def _recovery_outcome(ledger: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in ledger}
    if "incomplete-rollback" in statuses:
        return "incomplete-rollback"
    if "rolled-back" in statuses:
        return "rolled-back"
    if statuses and statuses <= {"applied", "unchanged"}:
        return "applied"
    return "blocked"


def build_recover_report(
    *,
    machine_builder: MachineBuilder | None = None,
    census_builder: CensusBuilder | None = None,
    recovery_lister: Callable[..., Sequence[str]] | None = None,
    context_loader: Callable[..., Any] | None = None,
    transaction_recoverer: Callable[..., list[dict[str, Any]]] | None = None,
    recovery_recorder: Callable[..., Any] | None = None,
    preclaim_abandoner: Callable[..., Any] | None = None,
    diagnostic_finalizer: Callable[..., Any] | None = None,
    run_finalizer: Callable[..., Any] | None = None,
    state_root: Path | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Recover pending private runs without accepting or rebuilding authority."""
    from cc.core.ecosystem.project_locking import ProjectLockContention
    from cc.core.ecosystem.project_plan_store import (
        abandon_preclaim_run,
        finalize_run_intent,
        incomplete_run_ids,
        load_recovery_context,
        record_recovered_projects,
        recovery_lock,
    )
    from cc.core.ecosystem.reconciliation_diagnostics import (
        finalize_run_diagnostic,
    )
    from cc.core.ecosystem.reconciliation_transaction import (
        recover_transaction_run,
    )

    recovery_lister = recovery_lister or incomplete_run_ids
    context_loader = context_loader or load_recovery_context
    transaction_recoverer = transaction_recoverer or recover_transaction_run
    recovery_recorder = recovery_recorder or record_recovered_projects
    preclaim_abandoner = preclaim_abandoner or abandon_preclaim_run
    diagnostic_finalizer = diagnostic_finalizer or finalize_run_diagnostic
    run_finalizer = run_finalizer or finalize_run_intent
    invocation_id = _run_id(run_id)
    recoveries: list[dict[str, Any]] = []
    finalized_count = 0
    pending_count = 0
    unsafe_count = 0

    try:
        lock_context = recovery_lock(root=state_root)
        with lock_context:
            pending_ids = tuple(recovery_lister(root=state_root))
            for interrupted_run_id in pending_ids:
                context = context_loader(interrupted_run_id, root=state_root)
                if context.owner_live:
                    ledger = _blocked_ledger(context.plans)
                    recoveries.append(
                        {
                            "interrupted_run_id": interrupted_run_id,
                            "requested_plan_id": context.plan_id,
                            "outcome": "blocked",
                            "ledger": ledger,
                            "diagnostics": _diagnostic_dict(
                                None, run_id=interrupted_run_id, now=now
                            ),
                        }
                    )
                    pending_count += 1
                    continue

                request = parse_reconciliation_request(context.canonical_request)
                preclaim = (
                    context.state == "claiming" and context.plan_state == "reviewed"
                )
                executable_plans = [
                    plan for plan in context.plans if plan.get("operations")
                ]
                executable_paths = {str(plan["path"]) for plan in executable_plans}
                transaction_failed = False
                if preclaim:
                    by_path: dict[str, dict[str, Any]] = {}
                    errors: set[str] = set()
                else:
                    try:
                        raw_ledger = transaction_recoverer(
                            interrupted_run_id,
                            root=state_root,
                        )
                    except Exception:
                        raw_ledger = []
                        transaction_failed = True
                    raw_executable = [
                        item
                        for item in raw_ledger
                        if isinstance(item, Mapping)
                        and item.get("path") in executable_paths
                    ]
                    unexpected = {
                        str(item.get("path"))
                        for item in raw_ledger
                        if not isinstance(item, Mapping)
                        or item.get("path")
                        not in {str(plan["path"]) for plan in context.plans}
                    }
                    by_path, errors = _validated_executor_ledger(
                        raw_executable,
                        executable_plans,
                    )
                    errors.update(unexpected)

                final_machine: Mapping[str, Any] = {}
                final_projects: list[dict[str, Any]] = []
                summary: dict[str, Any] = {
                    "project_counts": {},
                    "overlap_explanation": "No overlapping project outcomes were reported.",
                }
                try:
                    final_machine = (machine_builder or _default_machine_builder)()
                    selections = {
                        project.path: list(project.components)
                        for project in request.projects
                    }
                    final_projects = _validated_projects(
                        (census_builder or _default_census_builder)(
                            roots=request.roots,
                            selections=selections,
                            detail=True,
                        )
                    )
                    _validate_requested_authority(
                        request, final_machine, final_projects
                    )
                    summary = _summary(final_projects)
                    fresh_census = True
                except Exception:
                    fresh_census = False

                final_by_path = {
                    str(project["path"]): project for project in final_projects
                }
                if preclaim:
                    ordered_ledger = _blocked_ledger(context.plans)
                else:
                    ordered_ledger = []
                    for plan in context.plans:
                        path = str(plan["path"])
                        if plan.get("operations"):
                            ordered_ledger.append(
                                by_path.get(path, _uncertain_receipt(path))
                            )
                        elif fresh_census and path in final_by_path:
                            ordered_ledger.append(
                                _zero_operation_receipt(final_by_path[path])
                            )
                        else:
                            ordered_ledger.extend(_blocked_ledger([plan]))
                outcome = "blocked" if preclaim else _recovery_outcome(ordered_ledger)
                if errors or transaction_failed:
                    outcome = "incomplete-rollback"
                if fresh_census and _post_apply_contradictions(
                    request,
                    final_machine,
                    final_projects,
                    ordered_ledger,
                ):
                    outcome = "blocked"

                recorded: Any = None
                if not preclaim:
                    recorded = recovery_recorder(
                        interrupted_run_id,
                        outcome,
                        ordered_ledger,
                        root=state_root,
                    )
                try:
                    diagnostic_value = (
                        diagnostic_finalizer(
                            interrupted_run_id,
                            context.plan_id,
                            context.request_fingerprint,
                            ordered_ledger,
                            canonical_request=context.canonical_request,
                            reviewed_plans=context.plans,
                            helper_version=context.helper_version,
                            schema_version=context.schema_version,
                            fresh_plan_fingerprint=context.fresh_plan_fingerprint,
                            machine_evidence=final_machine,
                            project_evidence=_recovery_diagnostic_evidence(
                                context,
                                final_projects,
                                ordered_ledger,
                            ),
                            final_census=summary["project_counts"],
                            overlap_explanation=summary["overlap_explanation"],
                            root=state_root,
                        )
                        if fresh_census
                        else None
                    )
                except Exception:
                    diagnostic_value = None
                diagnostic = _diagnostic_dict(
                    diagnostic_value,
                    run_id=interrupted_run_id,
                    now=now,
                )
                finalized = False
                if diagnostic["state"] == "available":
                    try:
                        if preclaim:
                            preclaim_abandoner(
                                interrupted_run_id,
                                ledger=ordered_ledger,
                                diagnostic_id=diagnostic["id"],
                                diagnostic_state=diagnostic["state"],
                                root=state_root,
                            )
                        elif _plan_value(recorded, "state") == "outcome-recorded":
                            run_finalizer(
                                interrupted_run_id,
                                diagnostic_id=diagnostic["id"],
                                diagnostic_state=diagnostic["state"],
                                root=state_root,
                            )
                        else:
                            raise ReconciliationError(
                                "invalid-recovery-state",
                                "The recovered outcome was not durably recorded.",
                                exit_code=2,
                            )
                        finalized = True
                    except Exception:
                        finalized = False
                        if preclaim:
                            try:
                                finalized = (
                                    _plan_value(
                                        context_loader(
                                            interrupted_run_id,
                                            root=state_root,
                                        ),
                                        "state",
                                    )
                                    == "abandoned"
                                )
                            except Exception:
                                finalized = False
                recoveries.append(
                    {
                        "interrupted_run_id": interrupted_run_id,
                        "requested_plan_id": context.plan_id,
                        "outcome": outcome,
                        "ledger": ordered_ledger,
                        "diagnostics": diagnostic,
                    }
                )
                if finalized:
                    finalized_count += 1
                    if outcome == "incomplete-rollback":
                        unsafe_count += 1
                else:
                    pending_count += 1
    except ProjectLockContention as exc:
        raise ReconciliationError(
            "recovery-busy",
            "Another reconciliation recovery is already running.",
        ) from exc
    except ReconciliationError:
        raise
    except Exception as exc:
        raise ReconciliationError(
            "invalid-recovery-state",
            "Private reconciliation recovery state could not be validated safely.",
            exit_code=2,
        ) from exc

    result = (
        "partial"
        if (pending_count or unsafe_count) and finalized_count > unsafe_count
        else "blocked"
        if pending_count or unsafe_count
        else "ready"
    )
    next_actions = (
        ["No interrupted reconciliation requires recovery."]
        if not recoveries
        else ["Interrupted reconciliation recovery is complete."]
        if result == "ready"
        else [
            "At least one interrupted reconciliation still requires safe recovery. Resolve its rollback or diagnostic blocker before applying a new plan."
        ]
    )
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "recover",
        "result": result,
        "run_id": invocation_id,
        "generated_at": _timestamp(now),
        "recoveries": recoveries,
        "next_actions": next_actions,
    }


def build_verify_report(
    request: ReconciliationRequest,
    *,
    machine_builder: MachineBuilder | None = None,
    census_builder: CensusBuilder | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Fresh, strictly read-only verification for the explicit selection."""
    selections = {
        project.path: list(project.components) for project in request.projects
    }
    machine = (machine_builder or _default_machine_builder)()
    projects = _validated_projects(
        (census_builder or _default_census_builder)(
            roots=request.roots,
            selections=selections,
            detail=True,
        )
    )
    _validate_requested_authority(request, machine, projects)
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "verify",
        "result": _assessment_result(machine, projects),
        "run_id": _run_id(run_id),
        "generated_at": _timestamp(now),
        "machine": machine,
        "projects": projects,
        "summary": _summary(projects),
        "next_actions": _next_actions(machine, projects),
        "request_fingerprint": _fingerprint(
            json.loads(canonical_request_json(request))
        ),
    }


__all__ = [
    "PreparedReconciliation",
    "ReconciliationError",
    "assess_reconciliation",
    "build_apply_report",
    "build_plan_report",
    "build_recover_report",
    "build_verify_report",
    "prepare_reconciliation",
]
