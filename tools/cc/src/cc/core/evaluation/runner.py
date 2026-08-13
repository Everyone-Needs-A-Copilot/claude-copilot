"""Dependency-injected evaluation coordinator.

This module does not route prompts, resolve Knowledge, judge model output, or
perform live service calls.  Callers inject the already-selected runtime
boundary and provide verifier-issued receipts.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

from cc.core.evaluation.comparison import comparability_identity
from cc.core.evaluation.identity import (
    consumption_receipt_identity,
    content_receipt_identity,
    invocation_envelope_identity,
    runtime_receipt_identity,
)
from cc.core.evaluation.models import (
    EvaluationCell,
    GateObservation,
    GateState,
    PreflightGate,
    PreflightResult,
    PreflightState,
    RunRecord,
    RunState,
    RuntimeOutput,
)
from cc.core.evaluation.preflight import evaluate_preflight
from cc.core.evaluation.safety import (
    FixtureSafetyViolation,
    require_safe_synthetic_text,
)
from cc.core.evaluation.schema import canonical_sha256

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class InjectedRuntimeRunner(Protocol):
    def execute(self, cell: EvaluationCell) -> RuntimeOutput: ...


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
    actor: str,
    prerequisite: str,
) -> tuple[GateObservation, ...]:
    replacement = GateObservation(
        gate,
        GateState.FAIL,
        reason,
        actor,
        prerequisite,
    )
    return tuple(item for item in observations if item.gate is not gate) + (
        replacement,
    )


def _binding_valid(cell: EvaluationCell) -> bool:
    runtime_sha256 = runtime_receipt_identity(cell.runtime_receipt)
    content_sha256 = content_receipt_identity(cell.content_receipt)
    expected_invocation = invocation_envelope_identity(
        runtime_receipt_sha256=runtime_sha256,
        content_receipt_sha256=content_sha256,
        composed_content_sha256=cell.content_receipt.composed_content_sha256,
        prompt_evidence_sha256=cell.prompt_evidence_sha256,
        journey_evidence_sha256=cell.consumption_receipt.journey_evidence_sha256,
    )
    return (
        cell.variant is cell.content_receipt.variant
        and cell.consumption_receipt.runtime_receipt_sha256 == runtime_sha256
        and cell.consumption_receipt.content_receipt_sha256 == content_sha256
        and cell.consumption_receipt.prompt_evidence_sha256
        == cell.prompt_evidence_sha256
        and cell.consumption_receipt.invocation_envelope_sha256 == expected_invocation
    )


def _preflight_for(cell: EvaluationCell) -> PreflightResult:
    observations = cell.observations
    if not _binding_valid(cell):
        observations = _replace_gate(
            observations,
            PreflightGate.RESOLUTION_IDENTITY,
            reason="receipt-binding-mismatch",
            actor="framework",
            prerequisite="verified-receipts",
        )
    return evaluate_preflight(observations)


def _preflight_document(result: PreflightResult) -> dict[str, object]:
    return {
        "state": result.state.value,
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
    document = {
        "schema_version": "1.0",
        "case_id": cell.case_id,
        "revision": cell.revision,
        "variant": cell.variant.value,
        "runtime": cell.runtime_receipt.runtime.value,
        "attempt": cell.attempt,
        "parent_attempt_sha256": cell.parent_attempt_sha256,
        "fixture_sha256": cell.fixture_sha256,
        "prompt_evidence_sha256": cell.prompt_evidence_sha256,
        "attempt_policy_sha256": cell.attempt_policy_sha256,
        "runtime_configuration_sha256": cell.runtime_configuration_sha256,
        "tool_configuration_sha256": cell.tool_configuration_sha256,
        "comparability_sha256": comparability_identity(cell),
        "runtime_receipt_sha256": runtime_receipt_identity(cell.runtime_receipt),
        "content_receipt_sha256": content_receipt_identity(cell.content_receipt),
        "consumption_receipt_sha256": consumption_receipt_identity(
            cell.consumption_receipt
        ),
        "preflight": _preflight_document(preflight),
        "state": state.value,
        "output_sha256": output_sha256,
        "controlled_artifact_path": controlled_artifact_path,
        "completion_evidence_sha256": completion_evidence_sha256,
        "technical_error_reason": technical_error_reason,
    }
    return RunRecord(
        schema_version="1.0",
        run_sha256=canonical_sha256(document),
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
        comparability_sha256=document["comparability_sha256"],
        runtime_receipt_sha256=document["runtime_receipt_sha256"],
        content_receipt_sha256=document["content_receipt_sha256"],
        consumption_receipt_sha256=document["consumption_receipt_sha256"],
        preflight=preflight,
        state=state,
        output_sha256=output_sha256,
        controlled_artifact_path=controlled_artifact_path,
        completion_evidence_sha256=completion_evidence_sha256,
        technical_error_reason=technical_error_reason,
    )


def run_record_document(record: RunRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "run_sha256": record.run_sha256,
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


class EvaluationRunner:
    def __init__(self, runtime: InjectedRuntimeRunner) -> None:
        self._runtime = runtime

    def run(self, cell: EvaluationCell) -> RunRecord:
        preflight = _preflight_for(cell)
        if preflight.state is PreflightState.INVALID:
            return _record(cell, preflight=preflight, state=RunState.INVALID)
        if preflight.state is PreflightState.UNSUPPORTED:
            return _record(cell, preflight=preflight, state=RunState.UNSUPPORTED)

        try:
            output = self._runtime.execute(cell)
        except RuntimeAdapterFailure as exc:
            return _record(
                cell,
                preflight=preflight,
                state=RunState.TECHNICAL_ERROR,
                technical_error_reason=exc.reason,
            )
        except Exception:
            return _record(
                cell,
                preflight=preflight,
                state=RunState.TECHNICAL_ERROR,
                technical_error_reason="runtime-adapter-failure",
            )

        try:
            require_safe_synthetic_text(
                output.output_text,
                location_class=output.output_location_class,
            )
        except FixtureSafetyViolation:
            failed = evaluate_preflight(
                _replace_gate(
                    preflight.observations,
                    PreflightGate.SAFETY_SCAN,
                    reason="unsafe-output",
                    actor="framework",
                    prerequisite="safe-output",
                )
            )
            return _record(cell, preflight=failed, state=RunState.INVALID)

        output_sha256 = hashlib.sha256(output.output_text.encode("utf-8")).hexdigest()
        return _record(
            cell,
            preflight=preflight,
            state=RunState.COMPLETED,
            output_sha256=output_sha256,
            controlled_artifact_path=output.controlled_artifact_path,
            completion_evidence_sha256=output.completion_evidence_sha256,
        )
