"""Fail-closed CLI surface for the preregistered effectiveness evaluation."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import typer

from cc.core.evaluation.matrix import build_matrix, matrix_document
from cc.core.evaluation.report import (
    blocked_execution_report_document,
    validate_execution_report_document,
)
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import (
    PACKAGED_BUNDLE_SHA256,
    PACKAGED_MATRIX_SHA256,
    PACKAGED_PERSONAL_LAYER_SHA256,
    packaged_cases_root,
    packaged_personal_layer_root,
)

effectiveness_app = typer.Typer(
    name="effectiveness",
    help="Inspect the EVAL-01..07 layered effectiveness matrix and readiness.",
    no_args_is_help=True,
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MODEL_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def build_effectiveness_readiness(
    fixtures_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Return the sealed canonical no-call snapshot, never dispatch authority."""

    from cc.core.evaluation.readiness import (
        RUNTIME_MODELS,
        CanonicalReadinessUnavailable,
        issue_canonical_readiness,
        readiness_document,
    )

    selected = _resolve_fixtures_root(fixtures_root)
    try:
        report = issue_canonical_readiness(
            fixtures_root=selected,
            runtime_models=RUNTIME_MODELS,
        )
        return readiness_document(report)
    except CanonicalReadinessUnavailable as exc:
        reason = exc.reason
    except (OSError, RuntimeError, TypeError, ValueError):
        reason = "canonical-readiness-unavailable"
    if not _IDENTIFIER.fullmatch(reason):
        reason = "canonical-readiness-unavailable"
    return {
        "schema_version": "task285-canonical-readiness-unavailable-v1",
        "state": "blocked",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "runtime_models_sha256": canonical_sha256(
            {
                "schema_version": "task285-runtime-model-policy-v1",
                "models": dict(sorted(RUNTIME_MODELS.items())),
            }
        ),
        "cells": [],
        "runtimes": [],
        "blockers": [reason],
        "live_calls_started": 0,
        "artifacts_written": 0,
        "readiness_sha256": None,
    }


def _resolve_fixtures_root(fixtures_root: Optional[Path]) -> Path:
    if fixtures_root is not None:
        return fixtures_root
    return packaged_cases_root()


def _execution_boundary() -> tuple[Callable[..., object], type[Exception]] | None:
    try:
        module = importlib.import_module("cc.core.evaluation.execution")
    except ImportError:
        return None
    issuer = getattr(module, "issue_matrix_execution", None)
    unavailable = getattr(module, "EvaluationExecutionUnavailable", None)
    if (
        not callable(issuer)
        or not isinstance(unavailable, type)
        or not issubclass(unavailable, Exception)
    ):
        return None
    return issuer, unavailable


def _blocked_execution_document(
    matrix_sha256: str,
    reason: str,
) -> dict[str, object]:
    return blocked_execution_report_document(matrix_sha256, reason)


def _validated_execution_report(
    value: object,
    *,
    matrix_sha256: str,
) -> dict[str, object]:
    if isinstance(value, Mapping) and value.get("schema_version") == (
        "task285-phase-one-execution-v1"
    ):
        return _validated_phase_one_report(value, matrix_sha256=matrix_sha256)
    return validate_execution_report_document(value, matrix_sha256=matrix_sha256)


def _validated_phase_one_report(
    value: Mapping[str, object],
    *,
    matrix_sha256: str,
) -> dict[str, object]:
    """Validate a resumable handoff without treating it as final acceptance."""

    expected_keys = {
        "schema_version",
        "matrix_sha256",
        "state",
        "acceptance_state",
        "initial_cells_started",
        "total_attempts_started",
        "live_calls_started",
        "completed_cells",
        "unsupported_cells",
        "assessment_manifest_sha256",
        "assessment_bundle_sha256",
        "terminal_run_sha256",
        "blockers",
        "execution_sha256",
    }
    if set(value) != expected_keys:
        raise ValueError("Phase-one execution report has an invalid shape.")
    document = dict(value)
    identity = {
        key: item for key, item in document.items() if key != "execution_sha256"
    }
    terminal = document["terminal_run_sha256"]
    if not (
        document["schema_version"] == "task285-phase-one-execution-v1"
        and document["matrix_sha256"] == matrix_sha256 == PACKAGED_MATRIX_SHA256
        and document["state"] == "awaiting-assessment"
        and document["acceptance_state"] == "not-evaluated"
        and all(
            type(document[field]) is int
            for field in (
                "initial_cells_started",
                "total_attempts_started",
                "live_calls_started",
                "completed_cells",
                "unsupported_cells",
            )
        )
        and document["initial_cells_started"] == 28
        and document["total_attempts_started"] == 28
        and document["live_calls_started"] == 14
        and document["completed_cells"] == 14
        and document["unsupported_cells"] == 14
        and _DIGEST.fullmatch(str(document["assessment_manifest_sha256"]))
        and _DIGEST.fullmatch(str(document["assessment_bundle_sha256"]))
        and isinstance(terminal, list)
        and all(isinstance(item, str) and _DIGEST.fullmatch(item) for item in terminal)
        and len(terminal) == len(set(terminal)) == 28
        and document["blockers"] == []
        and _DIGEST.fullmatch(str(document["execution_sha256"]))
        and document["execution_sha256"] == canonical_sha256(identity)
    ):
        raise ValueError("Phase-one execution report failed validation.")
    return document


def _run_effectiveness_matrix(
    *,
    artifact_root: Path,
    claude_model: str,
    codex_model: str,
) -> dict[str, object]:
    fixtures_root = packaged_cases_root()
    matrix, _fixtures = build_matrix(fixtures_root)
    boundary = _execution_boundary()
    if boundary is None:
        return _blocked_execution_document(
            matrix.matrix_sha256,
            "canonical-execution-issuer-unavailable",
        )
    issuer, unavailable = boundary
    try:
        report = issuer(
            fixtures_root=fixtures_root,
            artifact_root=artifact_root,
            runtime_models={"claude": claude_model, "codex": codex_model},
        )
    except unavailable as exc:
        reason = getattr(exc, "reason", "")
        if not isinstance(reason, str) or not _IDENTIFIER.fullmatch(reason):
            reason = "canonical-execution-unavailable"
        return _blocked_execution_document(matrix.matrix_sha256, reason)
    return _validated_execution_report(
        report,
        matrix_sha256=matrix.matrix_sha256,
    )


def _emit(document: Mapping[str, Any], output_json: bool) -> None:
    if output_json:
        typer.echo(json.dumps(dict(document), sort_keys=True))
        return
    typer.echo(f"state: {document.get('state', 'planned')}")
    if "acceptance_state" in document:
        typer.echo(f"acceptance: {document['acceptance_state']}")
    typer.echo(f"matrix: {document['matrix_sha256']}")
    typer.echo(
        f"cells: {document.get('planned_cells', len(document.get('cells', [])))}"
    )
    for blocker in document.get("blockers", []):
        typer.echo(f"blocked: {blocker}")


@effectiveness_app.command("matrix")
def effectiveness_matrix(
    fixtures_root: Optional[Path] = typer.Option(
        None,
        "--fixtures-root",
        exists=True,
        file_okay=False,
        readable=True,
    ),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Print the exact 28-cell EVAL-01..07 plan without starting a runtime."""

    matrix, _fixtures = build_matrix(_resolve_fixtures_root(fixtures_root))
    document = matrix_document(matrix)
    if fixtures_root is None:
        packaged_personal_layer_root()
        document["fixture_bundle_sha256"] = PACKAGED_BUNDLE_SHA256
        document["personal_layer_sha256"] = PACKAGED_PERSONAL_LAYER_SHA256
    document["state"] = "planned"
    document["planned_cells"] = len(matrix.cells)
    document["live_calls_started"] = 0
    _emit(document, output_json)


@effectiveness_app.command("readiness")
def effectiveness_readiness(
    fixtures_root: Optional[Path] = typer.Option(
        None,
        "--fixtures-root",
        exists=True,
        file_okay=False,
        readable=True,
    ),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Fail closed on unsigned/missing layer or runtime prerequisites."""

    document = build_effectiveness_readiness(fixtures_root)
    _emit(document, output_json)
    if document["state"] != "ready":
        raise typer.Exit(2)


@effectiveness_app.command("run")
def effectiveness_run(
    artifact_root: Path = typer.Option(
        ...,
        "--artifact-root",
        file_okay=False,
    ),
    claude_model: str = typer.Option(..., "--claude-model"),
    codex_model: str = typer.Option(..., "--codex-model"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run only through the production canonical execution issuer."""

    if not _MODEL_REFERENCE.fullmatch(claude_model) or not _MODEL_REFERENCE.fullmatch(
        codex_model
    ):
        raise typer.BadParameter("Model references must be exact stable identifiers.")
    document = _run_effectiveness_matrix(
        artifact_root=artifact_root,
        claude_model=claude_model,
        codex_model=codex_model,
    )
    _emit(document, output_json)
    if document["state"] not in {"completed", "awaiting-assessment"}:
        raise typer.Exit(2)
