"""One Python-owned machine-to-project setup journey.

The desktop application may render this report later, but it must not repeat
any discovery, authority, mutation, or verification decision implemented here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from cc.commands.onboard import build_ecosystem_onboard_report
from cc.commands.store import build_store_verify_report
from cc.core.config import resolve_key
from cc.core.ecosystem.reconciliation import (
    assess_reconciliation,
    build_apply_report,
    build_plan_report,
    build_recover_report,
)
from cc.core.ecosystem.reconciliation_types import parse_reconciliation_request
from cc.core.ecosystem.setup_journey_diagnostics import (
    write_setup_journey_diagnostic,
)
from cc.core.ecosystem.setup_preflight import build_setup_prepare_report

ReportBuilder = Callable[[], dict[str, Any]]


def _failure(phase: str, error: Exception) -> dict[str, Any]:
    del error
    return {
        "phase": phase,
        "result": "blocked",
        "error": {
            "code": f"{phase}-unavailable",
            "detail": "This setup phase could not complete safely.",
        },
    }


def _default_request(assessment: Mapping[str, Any]) -> dict[str, Any] | None:
    selections = assessment.get("default_selection", [])
    if not isinstance(selections, list) or not selections:
        return None
    projects_by_path = {
        str(project.get("path")): project
        for project in assessment.get("projects", [])
        if isinstance(project, Mapping)
    }
    roots: list[str] = []
    projects: list[dict[str, Any]] = []
    for selection in selections:
        if not isinstance(selection, Mapping):
            continue
        path = selection.get("path")
        components = selection.get("components")
        project = projects_by_path.get(str(path))
        root = project.get("root") if isinstance(project, Mapping) else None
        if (
            not isinstance(path, str)
            or not isinstance(root, str)
            or not isinstance(components, list)
            or not components
        ):
            continue
        if root not in roots:
            roots.append(root)
        item: dict[str, Any] = {"path": path, "components": list(components)}
        recipe_ids = selection.get("recipe_ids")
        if isinstance(recipe_ids, Mapping) and recipe_ids:
            item["recipe_ids"] = dict(recipe_ids)
        projects.append(item)
    if not projects:
        return None
    return {"schema_version": "1.0", "roots": roots, "projects": projects}


def build_setup_journey_report(
    *,
    recover_builder: ReportBuilder = build_recover_report,
    prepare_builder: ReportBuilder = build_setup_prepare_report,
    ecosystem_builder: Callable[..., dict[str, Any]] = build_ecosystem_onboard_report,
    store_builder: ReportBuilder = build_store_verify_report,
    assess_builder: ReportBuilder = assess_reconciliation,
    plan_builder: Callable[..., dict[str, Any]] = build_plan_report,
    apply_builder: Callable[..., dict[str, Any]] = build_apply_report,
    diagnostics_writer: Callable[[Mapping[str, Any]], dict[str, Any]] = (
        write_setup_journey_diagnostic
    ),
    max_project_passes: int = 4,
) -> dict[str, Any]:
    """Recover, prepare, update, apply safe work, and verify the whole scope."""
    phases: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    try:
        recovery = recover_builder()
    except Exception as exc:
        recovery = _failure("recover", exc)
    phases.append(recovery)
    if recovery.get("result") not in {"ready", "applied"}:
        return _result(phases, actions, None, diagnostics_writer)

    try:
        preparation = prepare_builder()
    except Exception as exc:
        preparation = _failure("prepare", exc)
    phases.append(preparation)
    actions.extend(preparation.get("completed_actions", []))

    configured_org = resolve_key("github_app.org")
    repository_root = resolve_key("paths.repositories_root")
    if not isinstance(configured_org, str) or not configured_org.strip():
        ecosystem = {
            "phase": "ecosystem",
            "result": "blocked",
            "error": {
                "code": "organization-unconfigured",
                "detail": "The GitHub organization is not configured on this Mac.",
            },
        }
    else:
        try:
            ecosystem = ecosystem_builder(
                org=configured_org,
                products=("claude", "codex"),
                apply=True,
                repository_root=(
                    repository_root
                    if isinstance(repository_root, str) and repository_root
                    else None
                ),
            )
            ecosystem = {"phase": "ecosystem", **ecosystem}
        except Exception as exc:
            ecosystem = _failure("ecosystem", exc)
    phases.append(ecosystem)
    actions.extend(ecosystem.get("completed_actions", []))

    try:
        store = {"phase": "store", **store_builder()}
    except Exception as exc:
        store = _failure("store", exc)
    phases.append(store)

    assessment: dict[str, Any] | None = None
    for _pass in range(max_project_passes):
        try:
            assessment = assess_builder()
        except Exception as exc:
            phases.append(_failure("assess", exc))
            return _result(phases, actions, None, diagnostics_writer)
        request_payload = _default_request(assessment)
        if request_payload is None:
            break
        request = parse_reconciliation_request(request_payload)
        try:
            plan = plan_builder(request)
            apply = apply_builder(request, str(plan["plan_id"]))
        except Exception as exc:
            phases.append(_failure("projects", exc))
            break
        phases.extend((plan, apply))
        actions.extend(apply.get("ledger", []))
        if not any(
            item.get("status") in {"applied", "unchanged"}
            for item in apply.get("ledger", [])
            if isinstance(item, Mapping)
        ):
            break
        try:
            checkpoint = prepare_builder()
        except Exception as exc:
            checkpoint = _failure("prepare", exc)
        phases.append(checkpoint)
        actions.extend(checkpoint.get("completed_actions", []))

    # A project may become dirty while the longer machine scan is running.
    # Make the last action before verification another Product-only checkpoint
    # and shared-repository refresh, then assess that resulting state.
    try:
        final_preparation = prepare_builder()
    except Exception as exc:
        final_preparation = _failure("prepare", exc)
    phases.append(final_preparation)
    actions.extend(final_preparation.get("completed_actions", []))

    try:
        final_assessment = assess_builder()
    except Exception as exc:
        phases.append(_failure("verify", exc))
        return _result(phases, actions, None, diagnostics_writer)
    phases.append({**final_assessment, "phase": "verify-all"})
    return _result(phases, actions, final_assessment, diagnostics_writer)


def _result(
    phases: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    assessment: dict[str, Any] | None,
    diagnostics_writer: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    latest_required: dict[str, dict[str, Any]] = {}
    for phase in phases:
        name = phase.get("phase")
        if name in {"recover", "prepare", "ecosystem", "store"}:
            latest_required[str(name)] = phase
    phase_holds = [
        phase
        for phase in latest_required.values()
        if phase.get("result") not in {"ready", "applied"}
        and not (
            phase.get("phase") == "prepare"
            and phase.get("result") == "action-required"
            and not phase.get("holds")
        )
    ]
    if assessment is None or assessment.get("result") != "ready":
        phase_holds.append(
            {
                "phase": "verify-all",
                "result": (
                    assessment.get("result") if assessment is not None else "blocked"
                ),
                "summary": (
                    assessment.get("machine_summary")
                    if assessment is not None
                    else {"title": "Final verification did not complete."}
                ),
                "next_actions": (
                    assessment.get("next_actions", []) if assessment is not None else []
                ),
            }
        )
    ready = (
        assessment is not None
        and assessment.get("result") == "ready"
        and not phase_holds
    )
    report = {
        "schema_version": "1.0",
        "phase": "setup-journey",
        "result": "ready" if ready else "action-required",
        "operational": ready,
        "confidence": 0.95 if ready else 0.0,
        "completed_actions": actions,
        "phases": phases,
        "assessment": assessment,
        "holds": phase_holds,
        "summary": {
            "headline": (
                "This Mac and every Product project are ready."
                if ready
                else "Setup still has named work to resolve."
            ),
            "detail": (
                "Python independently verified the machine, ecosystem hierarchy, and every approved Product project."
                if ready
                else "No operational claim was made because at least one Python verification or setup phase is not ready."
            ),
        },
    }
    try:
        report["diagnostics"] = diagnostics_writer(report)
    except Exception:
        report["diagnostics"] = {
            "schema_version": "1.0",
            "state": "unavailable",
            "path": None,
            "detail": (
                "The setup result is available, but its support report "
                "could not be saved."
            ),
        }
    return report


__all__ = ["build_setup_journey_report"]
