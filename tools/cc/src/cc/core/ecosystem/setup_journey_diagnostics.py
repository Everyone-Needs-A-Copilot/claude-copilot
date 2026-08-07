"""Private, redacted support evidence for the complete setup journey."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cc.core.config_paths import machine_diagnostics_root
from cc.core.ecosystem.project_locking import (
    ProjectLockError,
    atomic_json_write,
    ensure_private_directory,
)

DIAGNOSTIC_SCHEMA_VERSION = "1.0"
DEFAULT_RETENTION = 20
_PREFIX = "setup-journey-"


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _bounded_text(value: Any, *, limit: int = 1000) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    return value[:limit]


def _safe_phase(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    safe: dict[str, Any] = {}
    for key in (
        "phase",
        "result",
        "run_id",
        "plan_id",
        "detail",
        "organization",
        "scope",
    ):
        item = _bounded_text(value.get(key), limit=160)
        if item is not None:
            safe[key] = item
    checks = value.get("checks")
    if isinstance(checks, Mapping):
        safe_checks = {
            key: checks.get(key) is True
            for key in ("policy_valid", "positive_read", "negative_denied", "read_only")
            if isinstance(checks.get(key), bool)
        }
        if safe_checks:
            safe["checks"] = safe_checks
    evidence = value.get("evidence")
    if isinstance(evidence, Mapping):
        safe_evidence: dict[str, Any] = {}
        auth_mode = _bounded_text(evidence.get("auth_mode"), limit=80)
        if auth_mode is not None:
            safe_evidence["auth_mode"] = auth_mode
        for key in ("secret_count", "exit_code"):
            item = evidence.get(key)
            if isinstance(item, int) and not isinstance(item, bool):
                safe_evidence[key] = item
        if safe_evidence:
            safe["evidence"] = safe_evidence
    error = value.get("error")
    if isinstance(error, Mapping):
        code = _bounded_text(error.get("code"), limit=160)
        if code is not None:
            safe["error_code"] = code
    return safe or None


def _safe_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key)[:80]: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool)
    }


def _safe_action(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    safe: dict[str, Any] = {}
    for key in (
        "action",
        "kind",
        "status",
        "outcome",
        "component",
        "repository",
        "path",
        "commit",
    ):
        item = _bounded_text(value.get(key), limit=4096 if key == "path" else 240)
        if item is not None:
            safe[key] = item
    if "path" not in safe:
        target = _bounded_text(value.get("target"), limit=4096)
        if target is not None:
            safe["path"] = target
    if "commit" not in safe:
        commit = _bounded_text(value.get("to_sha"), limit=80)
        if commit is not None:
            safe["commit"] = commit
    for key in ("pushed", "residual_work"):
        item = value.get(key)
        if isinstance(item, bool):
            safe[key] = item
    return safe or None


def _safe_reference(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    path = _bounded_text(value.get("path"), limit=4096)
    state = _bounded_text(value.get("state"), limit=80)
    if state not in {"available", "unavailable"}:
        return None
    return {"state": state, "path": path if state == "available" else None}


def _collect_references(value: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []

    def visit(item: Any, *, inside_diagnostics: bool = False) -> None:
        if len(references) >= limit:
            return
        if inside_diagnostics:
            reference = _safe_reference(item)
            if reference is not None:
                if reference not in references:
                    references.append(reference)
                return
        if isinstance(item, Mapping):
            for key, child in item.items():
                if key in {"diagnostic", "diagnostics"}:
                    visit(child, inside_diagnostics=True)
                elif isinstance(child, (Mapping, list, tuple)):
                    visit(child, inside_diagnostics=inside_diagnostics)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child, inside_diagnostics=inside_diagnostics)

    visit(value)
    return references


def _safe_blockers(assessment: Mapping[str, Any]) -> list[dict[str, Any]]:
    machine = assessment.get("machine")
    raw = machine.get("blockers") if isinstance(machine, Mapping) else None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    blockers: list[dict[str, Any]] = []
    for value in raw[:200]:
        if not isinstance(value, Mapping):
            continue
        safe: dict[str, Any] = {}
        for source, target in (
            ("code", "code"),
            ("responsible_actor", "responsible_actor"),
            ("next_action", "next_action"),
        ):
            item = _bounded_text(value.get(source))
            if item is not None:
                safe[target] = item
        evidence = value.get("evidence")
        if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
            safe_evidence: list[dict[str, str]] = []
            for item in evidence[:100]:
                if not isinstance(item, Mapping):
                    continue
                identifier = _bounded_text(item.get("id"), limit=160)
                state = _bounded_text(item.get("state"), limit=80)
                row = {
                    key: candidate
                    for key, candidate in (("id", identifier), ("state", state))
                    if candidate is not None
                }
                if row:
                    safe_evidence.append(row)
            if safe_evidence:
                safe["evidence"] = safe_evidence
        if safe:
            blockers.append(safe)
    return blockers


def _safe_project_holds(assessment: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = assessment.get("projects")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    holds: list[dict[str, Any]] = []
    for value in raw[:1000]:
        if not isinstance(value, Mapping) or value.get("route") not in {
            "held",
            "owner-decision",
            "could-not-verify",
            "source-unavailable",
        }:
            continue
        safe: dict[str, Any] = {}
        for key in ("path", "route", "next_action"):
            item = _bounded_text(value.get(key), limit=4096 if key == "path" else 1000)
            if item is not None:
                safe[key] = item
        components = value.get("components")
        if isinstance(components, Sequence) and not isinstance(
            components, (str, bytes)
        ):
            safe["components"] = [
                {
                    key: item
                    for key in ("component", "state")
                    if (item := _bounded_text(component.get(key), limit=160))
                    is not None
                }
                for component in components
                if isinstance(component, Mapping)
            ]
        if safe:
            holds.append(safe)
    return holds


def safe_setup_journey_record(
    report: Mapping[str, Any], *, created_at: str, run_id: str
) -> dict[str, Any]:
    """Build an allowlisted record without file content, output, or credentials."""
    assessment = report.get("assessment")
    assessment = assessment if isinstance(assessment, Mapping) else {}
    summary = assessment.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    scope_counts = _safe_counts(summary.get("scope_counts"))
    project_counts = _safe_counts(summary.get("project_counts"))
    machine = assessment.get("machine")
    machine = machine if isinstance(machine, Mapping) else {}
    helper = machine.get("helper")
    helper = helper if isinstance(helper, Mapping) else {}
    raw_phases = report.get("phases")
    raw_phases = (
        raw_phases
        if isinstance(raw_phases, Sequence) and not isinstance(raw_phases, (str, bytes))
        else []
    )
    raw_actions = report.get("completed_actions")
    raw_actions = (
        raw_actions
        if isinstance(raw_actions, Sequence)
        and not isinstance(raw_actions, (str, bytes))
        else []
    )
    phases = [
        safe for value in raw_phases[:1000] if (safe := _safe_phase(value)) is not None
    ]
    actions = [
        safe
        for value in raw_actions[:1000]
        if (safe := _safe_action(value)) is not None
    ]
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "kind": "setup-journey-support-report",
        "run_id": run_id,
        "created_at": created_at,
        "verdict": {
            "result": _bounded_text(report.get("result"), limit=80),
            "operational": report.get("operational") is True,
            "confidence": report.get("confidence")
            if isinstance(report.get("confidence"), (int, float))
            else 0.0,
        },
        "machine": {
            "state": _bounded_text(machine.get("state"), limit=80),
            "helper_version": _bounded_text(helper.get("version"), limit=80),
            "blockers": _safe_blockers(assessment),
        },
        "projects": {
            "scope_counts": scope_counts,
            "project_counts": project_counts,
            "holds": _safe_project_holds(assessment),
        },
        "phases": phases,
        "completed_actions": actions,
        "nested_diagnostics": _collect_references(report),
        "privacy": (
            "This report omits file content, process output, environment values, "
            "repository addresses, and credentials. It may include local project paths."
        ),
    }


def _prune(directory: Path, *, retention: int) -> None:
    records: list[tuple[int, str, Path]] = []
    for candidate in directory.glob(f"{_PREFIX}*.json"):
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


def write_setup_journey_diagnostic(
    report: Mapping[str, Any],
    *,
    root: Path | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
    retention: int = DEFAULT_RETENTION,
) -> dict[str, Any]:
    """Persist one private support report; diagnostic failure is non-fatal."""
    created = now or datetime.now(timezone.utc)
    identifier = run_id or uuid.uuid4().hex
    created_at = _timestamp(created)
    diagnostics_root = (root or machine_diagnostics_root()).expanduser()
    directory = diagnostics_root / "control-tower"
    stamp = created.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{_PREFIX}{stamp}-{identifier}.json"
    reference: dict[str, Any] = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "id": identifier,
        "state": "unavailable",
        "path": None,
        "created_at": created_at,
        "detail": "The setup result is available, but its support report could not be saved.",
    }
    try:
        ensure_private_directory(directory, boundary=diagnostics_root)
        atomic_json_write(
            path,
            safe_setup_journey_record(report, created_at=created_at, run_id=identifier),
        )
        _prune(directory, retention=retention)
    except (OSError, ProjectLockError):
        return reference
    reference.update(
        {
            "state": "available",
            "path": str(path),
            "detail": "A private, redacted setup support report was saved.",
        }
    )
    return reference


__all__ = [
    "DEFAULT_RETENTION",
    "DIAGNOSTIC_SCHEMA_VERSION",
    "safe_setup_journey_record",
    "write_setup_journey_diagnostic",
]
