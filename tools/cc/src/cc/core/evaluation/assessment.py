"""Value-suppressing phase-one manifest for independent human assessment."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass, field
from pathlib import Path

from cc.core.evaluation.artifact import (
    LoadedDurableRunEvidence,
    _open_linked_bytes,
    _open_root_directory,
    _write_standalone_evidence_document,
    close_artifact_receipt,
)
from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
from cc.core.evaluation.matrix import EvaluationMatrix, matrix_document
from cc.core.evaluation.models import LayerVariant, RunState, RuntimeName
from cc.core.evaluation.portfolio import _matrix_is_authentic, _validated_lineage
from cc.core.evaluation.runner import run_record_document
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256

ASSESSMENT_MANIFEST_SCHEMA_VERSION = "1.0"
ASSESSMENT_BUNDLE_SCHEMA_VERSION = "1.0"
_MAX_ASSESSMENT_BUNDLE_BYTES = 384 * 1024 * 1024
ASSESSMENT_POLICY_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-assessment-policy-v1",
        "task_id": 285,
        "assessor": "publisher-attested-review",
        "authority": "detached-signature-private-vault",
        "work_product": "task-copilot-evidence-required",
        "model_self_assessment": "prohibited",
    }
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_TYPE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MANIFEST_AUTHORITY = object()
_ISSUED_MANIFESTS: weakref.WeakValueDictionary[int, AssessmentManifest] = (
    weakref.WeakValueDictionary()
)
_LOADED_MANIFEST_AUTHORITY = object()
_ISSUED_LOADED_MANIFESTS: weakref.WeakValueDictionary[
    int, LoadedDurableAssessmentManifestEvidence
] = weakref.WeakValueDictionary()


@dataclass(frozen=True)
class AssessmentManifestCell:
    case_id: str
    revision: int
    variant: LayerVariant
    runtime: RuntimeName
    terminal_state: RunState
    terminal_run_sha256: str
    attempt_lineage_sha256: tuple[str, ...]
    fixture_sha256: str
    criterion_contract_sha256: str
    runtime_receipt_sha256: str
    content_receipt_sha256: str
    consumption_receipt_sha256: str
    output_sha256: str | None
    controlled_artifact_path: str | None

    def __post_init__(self) -> None:
        if (
            self.terminal_state not in {RunState.COMPLETED, RunState.UNSUPPORTED}
            or not self.attempt_lineage_sha256
        ):
            raise ValueError("Assessment cell terminal lineage is invalid.")
        for digest in (
            self.terminal_run_sha256,
            *self.attempt_lineage_sha256,
            self.fixture_sha256,
            self.criterion_contract_sha256,
            self.runtime_receipt_sha256,
            self.content_receipt_sha256,
            self.consumption_receipt_sha256,
        ):
            if not _DIGEST.fullmatch(digest):
                raise ValueError("Assessment cell identity is invalid.")
        completed = self.terminal_state is RunState.COMPLETED
        if completed != bool(
            self.output_sha256
            and _DIGEST.fullmatch(self.output_sha256)
            and self.controlled_artifact_path
            == f"runtime-quarantine/{self.output_sha256}.txt"
        ):
            raise ValueError("Assessment output binding is invalid.")


@dataclass(frozen=True)
class AssessmentManifest:
    schema_version: str
    manifest_sha256: str
    matrix_sha256: str
    task_id: int
    phase_state: str
    assessment_policy_sha256: str
    cells: tuple[AssessmentManifestCell, ...]
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _MANIFEST_AUTHORITY
            or self.schema_version != ASSESSMENT_MANIFEST_SCHEMA_VERSION
            or self.matrix_sha256 != PACKAGED_MATRIX_SHA256
            or self.task_id != 285
            or self.phase_state != "awaiting-assessment"
            or self.assessment_policy_sha256 != ASSESSMENT_POLICY_SHA256
            or len(self.cells) != 28
            or not _DIGEST.fullmatch(self.manifest_sha256)
        ):
            raise ValueError("Assessment manifest is not verifier-issued.")


@dataclass(frozen=True)
class LoadedDurableAssessmentManifestEvidence:
    """Authorize the phase-one handoff through one retained private bundle."""

    manifest: AssessmentManifest
    manifest_artifact_sha256: str
    runs: tuple[LoadedDurableRunEvidence, ...] = field(repr=False, compare=False)
    bundle_artifact_sha256: str
    _bundle_capability: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _LOADED_MANIFEST_AUTHORITY
            or not _DIGEST.fullmatch(self.manifest_artifact_sha256)
            or not _DIGEST.fullmatch(self.bundle_artifact_sha256)
        ):
            raise ValueError("Loaded assessment manifest is not verifier-issued.")

    def validate(self) -> bool:
        if _ISSUED_LOADED_MANIFESTS.get(id(self)) is not self:
            return False
        try:
            self._bundle_capability.validate()
            return bool(
                verify_assessment_manifest_identity(self.manifest)
                and self.manifest_artifact_sha256
                == canonical_sha256(assessment_manifest_document(self.manifest))
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return False

    def close(self) -> None:
        if _ISSUED_LOADED_MANIFESTS.get(id(self)) is not self:
            return
        _ISSUED_LOADED_MANIFESTS.pop(id(self), None)
        self._bundle_capability.close()


def _cell_document(value: AssessmentManifestCell) -> dict[str, object]:
    return {
        "case_id": value.case_id,
        "revision": value.revision,
        "variant": value.variant.value,
        "runtime": value.runtime.value,
        "terminal_state": value.terminal_state.value,
        "terminal_run_sha256": value.terminal_run_sha256,
        "attempt_lineage_sha256": list(value.attempt_lineage_sha256),
        "fixture_sha256": value.fixture_sha256,
        "criterion_contract_sha256": value.criterion_contract_sha256,
        "runtime_receipt_sha256": value.runtime_receipt_sha256,
        "content_receipt_sha256": value.content_receipt_sha256,
        "consumption_receipt_sha256": value.consumption_receipt_sha256,
        "output_sha256": value.output_sha256,
        "controlled_artifact_path": value.controlled_artifact_path,
    }


def _manifest_identity_document(value: AssessmentManifest) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "matrix_sha256": value.matrix_sha256,
        "task_id": value.task_id,
        "phase_state": value.phase_state,
        "assessment_policy_sha256": value.assessment_policy_sha256,
        "cells": [_cell_document(item) for item in value.cells],
    }


def assessment_manifest_document(value: AssessmentManifest) -> dict[str, object]:
    if not verify_assessment_manifest_identity(value):
        raise ValueError("Assessment manifest is not authentic.")
    return {
        **_manifest_identity_document(value),
        "manifest_sha256": value.manifest_sha256,
    }


def verify_assessment_manifest_identity(value: AssessmentManifest) -> bool:
    return bool(
        isinstance(value, AssessmentManifest)
        and _ISSUED_MANIFESTS.get(id(value)) is value
        and value._authority is _MANIFEST_AUTHORITY
        and value.manifest_sha256
        == canonical_sha256(_manifest_identity_document(value))
        and len(
            {
                (item.case_id, item.revision, item.variant, item.runtime)
                for item in value.cells
            }
        )
        == 28
    )


def _criterion_contract(fixture: LoadedFixture) -> str:
    return canonical_sha256(
        {
            "fixture_sha256": fixture.fixture_sha256,
            "oracle_sha256": fixture.oracle.sha256,
            "required_criteria": list(fixture.fixture.required_criteria),
            "hard_rejection_rules": list(fixture.fixture.hard_rejection_rules),
            "assessor_input": "private-quarantine-output-only",
        }
    )


def issue_assessment_manifest(
    matrix: EvaluationMatrix,
    *,
    fixtures: tuple[LoadedFixture, ...],
    runs: tuple[LoadedDurableRunEvidence, ...],
) -> AssessmentManifest:
    """Issue the exact pause point after runs and before human judgment."""

    if not _matrix_is_authentic(matrix):
        raise ValueError("Assessment requires the exact packaged matrix.")
    fixture_by_case = {
        item.fixture.case_id: item
        for item in fixtures
        if isinstance(item, LoadedFixture) and verify_loaded_fixture(item)
    }
    if len(fixture_by_case) != 7 or len(fixtures) != 7:
        raise ValueError("Assessment fixture evidence is incomplete.")
    grouped: dict[
        tuple[str, int, LayerVariant, RuntimeName],
        list[LoadedDurableRunEvidence],
    ] = {}
    for item in runs:
        if not isinstance(item, LoadedDurableRunEvidence) or not item.validate():
            raise ValueError("Assessment run evidence is invalid.")
        record = item.record
        grouped.setdefault(
            (record.case_id, record.revision, record.variant, record.runtime), []
        ).append(item)
    expected = {
        (item.case_id, item.revision, item.variant, item.runtime)
        for item in matrix.cells
    }
    if set(grouped) != expected:
        raise ValueError("Assessment matrix-cell coverage is incomplete.")
    cells = []
    for plan in matrix.cells:
        key = (plan.case_id, plan.revision, plan.variant, plan.runtime)
        lineage = _validated_lineage(tuple(grouped[key]))
        fixture = fixture_by_case.get(plan.case_id)
        if lineage is None or fixture is None:
            raise ValueError("Assessment terminal lineage is invalid.")
        terminal = lineage[-1]
        if (
            terminal.fixture_sha256 != fixture.fixture_sha256
            or terminal.case_id != fixture.fixture.case_id
            or terminal.revision != fixture.fixture.revision
        ):
            raise ValueError("Assessment fixture/run binding changed.")
        cells.append(
            AssessmentManifestCell(
                case_id=plan.case_id,
                revision=plan.revision,
                variant=plan.variant,
                runtime=plan.runtime,
                terminal_state=terminal.state,
                terminal_run_sha256=terminal.run_sha256,
                attempt_lineage_sha256=tuple(item.run_sha256 for item in lineage),
                fixture_sha256=terminal.fixture_sha256,
                criterion_contract_sha256=_criterion_contract(fixture),
                runtime_receipt_sha256=terminal.runtime_receipt_sha256,
                content_receipt_sha256=terminal.content_receipt_sha256,
                consumption_receipt_sha256=terminal.consumption_receipt_sha256,
                output_sha256=terminal.output_sha256,
                controlled_artifact_path=terminal.controlled_artifact_path,
            )
        )
    seal = object()
    provisional = AssessmentManifest(
        ASSESSMENT_MANIFEST_SCHEMA_VERSION,
        "0" * 64,
        matrix.matrix_sha256,
        285,
        "awaiting-assessment",
        ASSESSMENT_POLICY_SHA256,
        tuple(cells),
        seal,
        _MANIFEST_AUTHORITY,
    )
    result = AssessmentManifest(
        **{
            **provisional.__dict__,
            "manifest_sha256": canonical_sha256(
                _manifest_identity_document(provisional)
            ),
        }
    )
    _ISSUED_MANIFESTS[id(result)] = result
    return result


def _retained_run_capabilities(value: LoadedDurableRunEvidence) -> tuple[object, ...]:
    capability = getattr(value, "_capability", None)
    nested = getattr(capability, "_capabilities", None)
    if isinstance(nested, tuple) and nested:
        return nested
    if capability is not None:
        return (capability,)
    raise ValueError("Assessment run lacks retained artifact bytes.")


def _assessment_bundle_document(
    matrix: EvaluationMatrix,
    manifest: AssessmentManifest,
    runs: tuple[LoadedDurableRunEvidence, ...],
) -> dict[str, object]:
    if not _matrix_is_authentic(matrix):
        raise ValueError("Assessment requires the exact packaged matrix.")
    assets: dict[tuple[str, str], dict[str, object]] = {}
    for item in runs:
        retained = _retained_run_capabilities(item)
        if item.record.state is RunState.COMPLETED:
            outputs = [
                capability
                for capability in retained
                if getattr(capability, "_artifact_type", None) == "runtime-quarantine"
                and getattr(capability, "_digest", None) == item.record.output_sha256
            ]
            if len(outputs) != 1:
                raise ValueError("Assessment bundle output evidence is incomplete.")
        for capability in retained:
            capability.validate()
            artifact_type = getattr(capability, "_artifact_type", None)
            digest = getattr(capability, "_digest", None)
            content = getattr(capability, "_content", None)
            if (
                not isinstance(artifact_type, str)
                or not _ARTIFACT_TYPE.fullmatch(artifact_type)
                or not isinstance(digest, str)
                or not _DIGEST.fullmatch(digest)
                or not isinstance(content, bytes)
                or hashlib.sha256(content).hexdigest() != digest
            ):
                raise ValueError("Assessment retained artifact identity changed.")
            key = (artifact_type, digest)
            row = {
                "artifact_type": artifact_type,
                "sha256": digest,
                "size_bytes": len(content),
                "encoding": "base64",
                "content": base64.b64encode(content).decode("ascii"),
            }
            if key in assets and assets[key] != row:
                raise ValueError("Duplicate assessment artifact bytes differ.")
            assets[key] = row
    manifest_document = assessment_manifest_document(manifest)
    document: dict[str, object] = {
        "schema_version": ASSESSMENT_BUNDLE_SCHEMA_VERSION,
        "privacy_class": "private-evaluation-evidence",
        "matrix": matrix_document(matrix),
        "assessment_manifest": manifest_document,
        "assessment_manifest_artifact_sha256": canonical_sha256(manifest_document),
        "run_records": sorted(
            (run_record_document(item.record) for item in runs),
            key=canonical_sha256,
        ),
        "retained_artifacts": [assets[key] for key in sorted(assets)],
    }
    if len(canonical_json_bytes(document)) > _MAX_ASSESSMENT_BUNDLE_BYTES:
        raise ValueError("Assessment bundle exceeds the private evidence limit.")
    return document


def load_durable_assessment_manifest(
    root: Path,
    manifest_artifact_sha256: str,
    matrix: EvaluationMatrix,
    *,
    fixtures: tuple[LoadedFixture, ...],
    runs: tuple[LoadedDurableRunEvidence, ...],
) -> LoadedDurableAssessmentManifestEvidence | None:
    """Recompute and retain a persisted assessment handoff after restart."""

    if not _DIGEST.fullmatch(manifest_artifact_sha256):
        return None
    root_fd: int | None = None
    bundle_capability = None
    try:
        expected = issue_assessment_manifest(matrix, fixtures=fixtures, runs=runs)
        expected_document = assessment_manifest_document(expected)
        if canonical_sha256(expected_document) != manifest_artifact_sha256:
            return None
        bundle_document = _assessment_bundle_document(matrix, expected, runs)
        bundle_artifact_sha256 = canonical_sha256(bundle_document)
        root_fd = _open_root_directory(root)
        raw_bundle, bundle_capability = _open_linked_bytes(
            root_fd,
            "assessment-bundle",
            f"{bundle_artifact_sha256}.json",
            bundle_artifact_sha256,
            maximum_size=_MAX_ASSESSMENT_BUNDLE_BYTES,
        )
        stored_bundle = json.loads(raw_bundle)
        if (
            not isinstance(stored_bundle, dict)
            or canonical_json_bytes(stored_bundle) != raw_bundle
            or stored_bundle != bundle_document
        ):
            return None
        bundle_capability.validate()
        loaded = LoadedDurableAssessmentManifestEvidence(
            expected,
            manifest_artifact_sha256,
            runs,
            bundle_artifact_sha256,
            bundle_capability,
            _LOADED_MANIFEST_AUTHORITY,
        )
        _ISSUED_LOADED_MANIFESTS[id(loaded)] = loaded
        bundle_capability = None
        if not loaded.validate():
            loaded.close()
            return None
        return loaded
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if bundle_capability is not None:
            bundle_capability.close()
        if root_fd is not None:
            os.close(root_fd)


def persist_assessment_manifest(
    root: Path,
    matrix: EvaluationMatrix,
    *,
    fixtures: tuple[LoadedFixture, ...],
    runs: tuple[LoadedDurableRunEvidence, ...],
) -> LoadedDurableAssessmentManifestEvidence:
    """Persist and fresh-reload the resumable phase-one assessment handoff."""

    manifest = issue_assessment_manifest(matrix, fixtures=fixtures, runs=runs)
    receipt = _write_standalone_evidence_document(
        root,
        "assessment-manifest",
        assessment_manifest_document(manifest),
    )
    bundle_receipt = None
    try:
        bundle_receipt = _write_standalone_evidence_document(
            root,
            "assessment-bundle",
            _assessment_bundle_document(matrix, manifest, runs),
        )
        loaded = load_durable_assessment_manifest(
            root,
            receipt.sha256,
            matrix,
            fixtures=fixtures,
            runs=runs,
        )
        if loaded is None:
            raise ValueError("Assessment manifest could not be durably reloaded.")
        if loaded.bundle_artifact_sha256 != bundle_receipt.sha256:
            loaded.close()
            raise ValueError("Assessment bundle identity changed during persistence.")
        return loaded
    finally:
        if bundle_receipt is not None:
            close_artifact_receipt(bundle_receipt)
        close_artifact_receipt(receipt)


__all__ = [
    "ASSESSMENT_BUNDLE_SCHEMA_VERSION",
    "ASSESSMENT_MANIFEST_SCHEMA_VERSION",
    "ASSESSMENT_POLICY_SHA256",
    "AssessmentManifest",
    "AssessmentManifestCell",
    "LoadedDurableAssessmentManifestEvidence",
    "assessment_manifest_document",
    "issue_assessment_manifest",
    "load_durable_assessment_manifest",
    "persist_assessment_manifest",
    "verify_assessment_manifest_identity",
]
