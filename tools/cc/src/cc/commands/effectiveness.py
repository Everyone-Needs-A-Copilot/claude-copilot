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
from cc.evaluation_fixtures import (
    PACKAGED_BUNDLE_SHA256,
    PACKAGED_PERSONAL_LAYER_SHA256,
    packaged_cases_root,
    packaged_personal_layer_root,
)

effectiveness_app = typer.Typer(
    name="effectiveness",
    help="Inspect the EVAL-01..07 layered effectiveness matrix and readiness.",
    no_args_is_help=True,
)

_SIGNED_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TREE = re.compile(r"^[0-9a-f]{40,64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MODEL_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUIRED_SIGNED_LAYERS = (
    ("knowledge", "foundation"),
    ("knowledge", "organization"),
    ("knowledge", "department"),
    ("claude", "foundation"),
    ("claude", "organization"),
    ("claude", "department"),
    ("codex", "foundation"),
    ("codex", "organization"),
    ("codex", "department"),
)
_REQUIRED_PERSONAL_SNAPSHOTS = (
    ("knowledge", "personal"),
    ("claude", "personal"),
    ("codex", "personal"),
)


def _manifest_layers() -> list[dict[str, Any]]:
    from cc.core.config import resolve_key
    from cc.core.ecosystem.manifest import load_layers, validate_layers

    manifest = resolve_key("layers.manifest")
    if not manifest:
        return []
    return validate_layers(load_layers(manifest))


def _layer_statuses(
    layers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = []
    blockers = []
    for product, role in _REQUIRED_SIGNED_LAYERS:
        matches = [
            layer
            for layer in layers
            if layer.get("product") == product and layer.get("role") == role
        ]
        pinned = False
        if len(matches) == 1:
            source = matches[0].get("source") or {}
            policy = matches[0].get("policy") or {}
            proof = matches[0].get("_evaluation_proof") or {}
            pinned = bool(
                _SIGNED_TAG.fullmatch(str(source.get("ref", "")))
                and isinstance(policy.get("allowed_signers"), list)
                and policy["allowed_signers"]
                and proof.get("signature_verified") is True
                and proof.get("joined") is True
                and proof.get("layer") == matches[0].get("id")
                and proof.get("ref") == source.get("ref")
                and proof.get("signer") in policy["allowed_signers"]
                and _TREE.fullmatch(str(proof.get("tree", "")))
                and _DIGEST.fullmatch(str(proof.get("lease_sha256", "")))
                and _DIGEST.fullmatch(str(proof.get("lock_sha256", "")))
                and _DIGEST.fullmatch(str(proof.get("materialization_sha256", "")))
            )
        state = "ready" if pinned else "blocked"
        rows.append({"product": product, "role": role, "state": state})
        if not pinned:
            blockers.append(f"unverified-{product}-{role}")
    for product, role in _REQUIRED_PERSONAL_SNAPSHOTS:
        matches = [
            layer
            for layer in layers
            if layer.get("product") == product and layer.get("role") == role
        ]
        frozen = False
        if len(matches) == 1:
            source = matches[0].get("source") or {}
            proof = matches[0].get("_evaluation_proof") or {}
            frozen = bool(
                re.fullmatch(r"sha256:[0-9a-f]{64}", str(source.get("ref", "")))
                and proof.get("layer") == matches[0].get("id")
                and proof.get("ref") == source.get("ref")
                and proof.get("joined") is True
                and _DIGEST.fullmatch(str(proof.get("lock_sha256", "")))
                and _DIGEST.fullmatch(str(proof.get("materialization_sha256", "")))
            )
        rows.append(
            {
                "product": product,
                "role": role,
                "state": "ready" if frozen else "blocked",
            }
        )
        if not frozen:
            blockers.append(f"personal-snapshot-{product}-unavailable")
    return rows, blockers


def _runtime_statuses() -> tuple[list[dict[str, Any]], list[str]]:
    from cc.core.ecosystem.codex_plugin_source import resolve_codex_plugin_source
    from cc.core.evaluation.live_runtime import (
        _codex_native_executable,
        _executable_sha256,
        runtime_authentication_status,
    )
    from cc.core.evaluation.models import RuntimeName
    from cc.core.executables import resolve_executable

    rows = []
    blockers = []
    for runtime in ("claude", "codex"):
        resolved = resolve_executable(runtime)
        executable = None
        try:
            executable = (
                _codex_native_executable(Path(resolved))
                if runtime == "codex" and resolved is not None
                else Path(resolved) if resolved is not None else None
            )
            digest = _executable_sha256(executable) if executable else None
            authenticated, auth_reason = (
                runtime_authentication_status(RuntimeName(runtime), executable)
                if executable is not None
                else (False, "runtime-unavailable")
            )
        except (OSError, ValueError):
            digest = None
            authenticated, auth_reason = False, "auth-probe-unavailable"
        state = "ready" if digest and authenticated else "blocked"
        rows.append(
            {
                "runtime": runtime,
                "state": state,
                "executable_sha256": digest,
                "authentication": auth_reason,
            }
        )
        if digest is None:
            blockers.append(f"{runtime}-runtime-unavailable")
        elif not authenticated:
            blockers.append(f"{runtime}-runtime-not-authenticated")
    try:
        source = resolve_codex_plugin_source()
    except (OSError, ValueError):
        source = None
    if source is None:
        blockers.append("codex-plugin-projection-unavailable")
    else:
        rows[-1]["projection"] = {
            "layer": source.layer,
            "ref": source.ref,
            "tree": source.tree,
            "signer": source.signer,
        }
    blockers.append("codex-no-tool-isolation-unavailable")
    return rows, blockers


def build_effectiveness_readiness(
    fixtures_root: Optional[Path] = None,
    *,
    layers_loader: Callable[[], list[dict[str, Any]]] = _manifest_layers,
    runtime_loader: Callable[
        [], tuple[list[dict[str, Any]], list[str]]
    ] = _runtime_statuses,
) -> dict[str, Any]:
    """Return value-suppressing candidate readiness; never issue run authority."""

    fixtures_root = _resolve_fixtures_root(fixtures_root)
    matrix, _fixtures = build_matrix(fixtures_root)
    try:
        layers = layers_loader()
        layer_rows, layer_blockers = _layer_statuses(layers)
    except (OSError, ValueError):
        layer_rows = []
        layer_blockers = ["layer-manifest-unavailable"]
    runtime_rows, runtime_blockers = runtime_loader()
    candidate_blockers = sorted(set(layer_blockers + runtime_blockers))
    blockers = sorted(
        set(candidate_blockers + ["canonical-readiness-verifier-unavailable"])
    )
    return {
        "schema_version": "1.0",
        "matrix_sha256": matrix.matrix_sha256,
        "planned_cells": len(matrix.cells),
        "state": "blocked",
        "candidate_state": "satisfied" if not candidate_blockers else "blocked",
        "layers": layer_rows,
        "runtimes": runtime_rows,
        "blockers": blockers,
        "live_calls_started": 0,
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
    return validate_execution_report_document(value, matrix_sha256=matrix_sha256)


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
    if document["state"] != "completed":
        raise typer.Exit(2)
