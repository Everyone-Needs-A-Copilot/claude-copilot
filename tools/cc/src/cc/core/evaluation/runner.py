"""Dependency-injected evaluation coordinator with sealed evidence authority."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Protocol

from cc.core.evaluation._authority import _EvaluationAuthority, _production_authority
from cc.core.evaluation.comparison import comparability_identity
from cc.core.evaluation.identity import (
    consumption_receipt_identity,
    content_receipt_identity,
    invocation_envelope_identity,
    runtime_receipt_identity,
)
from cc.core.evaluation.models import (
    _RUN_RECORD_AUTHORITY,
    EvaluationCell,
    GateObservation,
    PreflightGate,
    PreflightResult,
    PreflightState,
    RunRecord,
    RunState,
    RuntimeOutput,
)
from cc.core.evaluation.preflight import evaluate_preflight, issue_failure
from cc.core.evaluation.safety import (
    FixtureSafetyViolation,
    require_safe_synthetic_text,
)
from cc.core.evaluation.schema import canonical_sha256

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class InjectedRuntimeRunner(Protocol):
    def execute(self, cell: EvaluationCell) -> RuntimeOutput | object: ...


class RuntimeAdapterFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        if not _IDENTIFIER.fullmatch(reason):
            raise ValueError("Runtime failure reason must be a stable identifier.")
        self.reason = reason
        super().__init__(reason)


def _replace_gate(
    observations: tuple[GateObservation, ...],
    gate: PreflightGate,
    *,
    reason: str,
    prerequisite: str = "verified-evidence",
) -> tuple[GateObservation, ...]:
    return tuple(item for item in observations if item.gate is not gate) + (
        issue_failure(gate, reason=reason, prerequisite=prerequisite),
    )


def _binding_valid(cell: EvaluationCell) -> bool:
    runtime_sha256 = runtime_receipt_identity(cell.runtime_receipt)
    content_sha256 = content_receipt_identity(cell.content_receipt)
    return (
        cell.variant is cell.content_receipt.variant
        and cell.consumption_receipt.runtime_receipt_sha256 == runtime_sha256
        and cell.consumption_receipt.content_receipt_sha256 == content_sha256
        and cell.consumption_receipt.prompt_evidence_sha256
        == cell.prompt_evidence_sha256
        and cell.consumption_receipt.invocation_envelope_sha256
        == invocation_envelope_identity(
            runtime_receipt_sha256=runtime_sha256,
            content_receipt_sha256=content_sha256,
            composed_content_sha256=cell.content_receipt.composed_content_sha256,
            prompt_evidence_sha256=cell.prompt_evidence_sha256,
            journey_evidence_sha256=cell.consumption_receipt.journey_evidence_sha256,
        )
    )


def _lineage_valid(
    cell: EvaluationCell,
    artifact_root: Path | None,
    *,
    artifact_root_fd: int | None,
    artifact_type_fd: int | None,
    loaded_fixture: object,
    journey_run_id: str,
    journey_ledger: object,
    lineage_depth: int,
) -> bool:
    if cell.attempt == 1:
        return cell.parent_attempt_sha256 is None
    if artifact_root is None and artifact_root_fd is None:
        return False
    from cc.core.evaluation.artifact import load_run_record_document

    parent = load_run_record_document(
        artifact_root,
        cell.parent_attempt_sha256 or "",
        child_cell=cell,
        loaded_fixture=loaded_fixture,
        journey_run_id=journey_run_id,
        journey_ledger=journey_ledger,
        lineage_depth=lineage_depth,
        root_fd=artifact_root_fd,
        type_fd=artifact_type_fd,
    )
    return bool(
        parent
        and parent["case_id"] == cell.case_id
        and parent["revision"] == cell.revision
        and parent["variant"] == cell.variant.value
        and parent["runtime"] == cell.runtime_receipt.runtime.value
        and parent["attempt"] == cell.attempt - 1
        and parent["runtime_receipt_sha256"]
        == runtime_receipt_identity(cell.runtime_receipt)
    )


def _preflight_for(
    cell: EvaluationCell,
    authority: _EvaluationAuthority,
    artifact_root: Path | None,
    *,
    artifact_root_fd: int | None = None,
    artifact_type_fd: int | None = None,
    loaded_fixture: object = None,
    journey_run_id: str = "",
    journey_ledger: object = None,
    lineage_depth: int = 0,
) -> PreflightResult:
    if not isinstance(authority, _EvaluationAuthority) or not authority.applies_to(
        cell
    ):
        observations: tuple[GateObservation, ...] = ()
    else:
        observations = authority.preflight.observations
    if not _binding_valid(cell):
        observations = _replace_gate(
            observations,
            PreflightGate.RESOLUTION_IDENTITY,
            reason="receipt-binding-mismatch",
        )
    if not _lineage_valid(
        cell,
        artifact_root,
        artifact_root_fd=artifact_root_fd,
        artifact_type_fd=artifact_type_fd,
        loaded_fixture=loaded_fixture,
        journey_run_id=journey_run_id,
        journey_ledger=journey_ledger,
        lineage_depth=lineage_depth,
    ):
        observations = _replace_gate(
            observations,
            PreflightGate.ATTEMPT_POLICY,
            reason="attempt-lineage-invalid",
            prerequisite="preserved-parent-attempt",
        )
    return evaluate_preflight(
        observations, subject_sha256=authority.preflight.subject_sha256
    )


def _preflight_document(result: PreflightResult) -> dict[str, object]:
    return {
        "state": result.state.value,
        "subject_sha256": result.subject_sha256,
        "result_sha256": result.result_sha256,
        "observations": [
            {
                "gate": item.gate.value,
                "state": item.state.value,
                "reason": item.reason,
                "actor": item.actor,
                "prerequisite": item.prerequisite,
            }
            for item in result.observations
        ],
    }


def _record_document(record: RunRecord, *, include_identity: bool) -> dict[str, object]:
    document = {
        "schema_version": record.schema_version,
        "case_id": record.case_id,
        "revision": record.revision,
        "variant": record.variant.value,
        "runtime": record.runtime.value,
        "attempt": record.attempt,
        "parent_attempt_sha256": record.parent_attempt_sha256,
        "fixture_sha256": record.fixture_sha256,
        "prompt_evidence_sha256": record.prompt_evidence_sha256,
        "attempt_policy_sha256": record.attempt_policy_sha256,
        "runtime_configuration_sha256": record.runtime_configuration_sha256,
        "tool_configuration_sha256": record.tool_configuration_sha256,
        "comparability_sha256": record.comparability_sha256,
        "runtime_receipt_sha256": record.runtime_receipt_sha256,
        "content_receipt_sha256": record.content_receipt_sha256,
        "consumption_receipt_sha256": record.consumption_receipt_sha256,
        "preflight": _preflight_document(record.preflight),
        "state": record.state.value,
        "output_sha256": record.output_sha256,
        "controlled_artifact_path": record.controlled_artifact_path,
        "completion_evidence_sha256": record.completion_evidence_sha256,
        "technical_error_reason": record.technical_error_reason,
    }
    if include_identity:
        document["run_sha256"] = record.run_sha256
    return document


def verify_run_record_identity(record: RunRecord) -> bool:
    return getattr(
        record, "_authority", None
    ) is _RUN_RECORD_AUTHORITY and record.run_sha256 == canonical_sha256(
        _record_document(record, include_identity=False)
    )


def _record(
    cell: EvaluationCell,
    *,
    preflight: PreflightResult,
    state: RunState,
    output_sha256: str | None = None,
    controlled_artifact_path: str | None = None,
    completion_evidence_sha256: str | None = None,
    technical_error_reason: str | None = None,
) -> RunRecord:
    base = dict(
        schema_version="1.2",
        run_sha256="0" * 64,
        case_id=cell.case_id,
        revision=cell.revision,
        variant=cell.variant,
        runtime=cell.runtime_receipt.runtime,
        attempt=cell.attempt,
        parent_attempt_sha256=cell.parent_attempt_sha256,
        fixture_sha256=cell.fixture_sha256,
        prompt_evidence_sha256=cell.prompt_evidence_sha256,
        attempt_policy_sha256=cell.attempt_policy_sha256,
        runtime_configuration_sha256=cell.runtime_configuration_sha256,
        tool_configuration_sha256=cell.tool_configuration_sha256,
        comparability_sha256=comparability_identity(cell),
        runtime_receipt_sha256=runtime_receipt_identity(cell.runtime_receipt),
        content_receipt_sha256=content_receipt_identity(cell.content_receipt),
        consumption_receipt_sha256=consumption_receipt_identity(
            cell.consumption_receipt
        ),
        preflight=preflight,
        state=state,
        output_sha256=output_sha256,
        controlled_artifact_path=controlled_artifact_path,
        completion_evidence_sha256=completion_evidence_sha256,
        technical_error_reason=technical_error_reason,
        _authority=_RUN_RECORD_AUTHORITY,
    )
    provisional = RunRecord(**base)
    base["run_sha256"] = canonical_sha256(
        _record_document(provisional, include_identity=False)
    )
    return RunRecord(**base)


def run_record_document(record: RunRecord) -> dict[str, object]:
    if not verify_run_record_identity(record):
        raise ValueError("Run record is not authentic.")
    return _record_document(record, include_identity=True)


class EvaluationRunner:
    def __init__(
        self,
        runtime: InjectedRuntimeRunner,
        *,
        loaded_fixture: object = None,
        journey_run_id: str = "",
        journey_ledger: object = None,
        artifact_root: Path | None = None,
    ) -> None:
        self._runtime = runtime
        self._loaded_fixture = loaded_fixture
        self._journey_run_id = journey_run_id
        self._journey_ledger = journey_ledger
        self._artifact_root = artifact_root
        records: dict[str, RunRecord] = {}

        def preserve(record: RunRecord) -> None:
            if not verify_run_record_identity(record):
                raise ValueError("Runner-issued record identity changed.")
            existing = records.get(record.run_sha256)
            if existing is not None and existing is not record:
                raise ValueError("Attempt identity collision.")
            records[record.run_sha256] = record

        self.__records_snapshot = lambda: tuple(records.values())
        self.__preserve = preserve

    @property
    def records(self) -> tuple[RunRecord, ...]:
        return self.__records_snapshot()

    def _finish(self, record: RunRecord) -> RunRecord:
        self.__preserve(record)
        return record

    def run(self, cell: EvaluationCell) -> RunRecord:
        authority = _production_authority(
            cell,
            loaded_fixture=self._loaded_fixture,
            journey_run_id=self._journey_run_id,
            journey_ledger=self._journey_ledger,
        )
        preflight = _preflight_for(
            cell,
            authority,
            self._artifact_root,
            loaded_fixture=self._loaded_fixture,
            journey_run_id=self._journey_run_id,
            journey_ledger=self._journey_ledger,
        )
        if preflight.state is PreflightState.INVALID:
            return self._finish(
                _record(
                    cell,
                    preflight=preflight,
                    state=RunState.INVALID,
                )
            )
        if preflight.state is PreflightState.UNSUPPORTED:
            return self._finish(
                _record(
                    cell,
                    preflight=preflight,
                    state=RunState.UNSUPPORTED,
                )
            )
        try:
            result = self._runtime.execute(cell)
        except RuntimeAdapterFailure as exc:
            return self._finish(
                _record(
                    cell,
                    preflight=preflight,
                    state=RunState.TECHNICAL_ERROR,
                    technical_error_reason=exc.reason,
                )
            )
        except Exception:
            return self._finish(
                _record(
                    cell,
                    preflight=preflight,
                    state=RunState.TECHNICAL_ERROR,
                    technical_error_reason="runtime-adapter-failure",
                )
            )
        output = result
        if not isinstance(output, RuntimeOutput):
            return self._finish(
                _record(
                    cell,
                    preflight=preflight,
                    state=RunState.TECHNICAL_ERROR,
                    technical_error_reason="runtime-adapter-failure",
                )
            )
        try:
            require_safe_synthetic_text(
                output.output_text, location_class=output.output_location_class
            )
        except FixtureSafetyViolation:
            failed = evaluate_preflight(
                _replace_gate(
                    preflight.observations,
                    PreflightGate.SAFETY_SCAN,
                    reason="unsafe-output",
                    prerequisite="safe-output",
                ),
                subject_sha256=preflight.subject_sha256,
            )
            return self._finish(
                _record(
                    cell,
                    preflight=failed,
                    state=RunState.INVALID,
                )
            )
        output_sha256 = hashlib.sha256(output.output_text.encode()).hexdigest()
        proof = _verify_completion(cell, output, output_sha256)
        proof_valid = bool(
            proof
            and proof.invocation_envelope_sha256
            == cell.consumption_receipt.invocation_envelope_sha256
            and proof.output_sha256 == output_sha256
            and proof.artifact_path_sha256
            == hashlib.sha256(output.controlled_artifact_path.encode()).hexdigest()
        )
        return self._finish(
            _record(
                cell,
                preflight=preflight,
                state=RunState.COMPLETED
                if proof_valid
                else RunState.DISPATCH_AUTHORIZED,
                output_sha256=output_sha256,
                controlled_artifact_path=output.controlled_artifact_path,
                completion_evidence_sha256=proof.evidence_sha256
                if proof_valid
                else None,
            )
        )


def _verify_completion(
    cell: EvaluationCell, output: RuntimeOutput, output_sha256: str
) -> object | None:
    """Production completion remains unavailable until an authenticated adapter lands."""

    return None
