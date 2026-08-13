"""Dependency-injected evaluation coordinator with explicit authorities."""

from __future__ import annotations

import hashlib
import re
from typing import Callable, Protocol

from cc.core.evaluation.comparison import comparability_identity
from cc.core.evaluation.identity import (
    consumption_receipt_identity,
    content_receipt_identity,
    invocation_envelope_identity,
    runtime_receipt_identity,
)
from cc.core.evaluation.models import (
    _COMPLETION_AUTHORITY,
    CompletionProof,
    EvaluationCell,
    GateObservation,
    PreflightGate,
    PreflightResult,
    PreflightState,
    RunRecord,
    RunState,
    RuntimeOutput,
)
from cc.core.evaluation.preflight import (
    TrustedEvidenceVerifier,
    evaluate_preflight,
    issue_failure,
)
from cc.core.evaluation.safety import (
    FixtureSafetyViolation,
    require_safe_synthetic_text,
)
from cc.core.evaluation.schema import canonical_sha256

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class InjectedRuntimeRunner(Protocol):
    def execute(self, cell: EvaluationCell) -> RuntimeOutput: ...


CompletionProbe = Callable[[EvaluationCell, RuntimeOutput, str], str | None]


class TrustedCompletionVerifier:
    """Issue a correlated completion proof from an injected trusted probe."""

    def __init__(self, probe: CompletionProbe) -> None:
        self._probe = probe

    def verify(
        self, cell: EvaluationCell, output: RuntimeOutput, output_sha256: str
    ) -> CompletionProof | None:
        try:
            evidence_sha256 = self._probe(cell, output, output_sha256)
            if evidence_sha256 is None:
                return None
            return CompletionProof(
                invocation_envelope_sha256=cell.consumption_receipt.invocation_envelope_sha256,
                output_sha256=output_sha256,
                artifact_path_sha256=hashlib.sha256(
                    output.controlled_artifact_path.encode()
                ).hexdigest(),
                evidence_sha256=evidence_sha256,
                _authority=_COMPLETION_AUTHORITY,
            )
        except (TypeError, ValueError, OSError, PermissionError, TimeoutError):
            return None


class AttemptLedger:
    """Preserve every run and prove retry parent identity locally."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}

    def parent_for(self, cell: EvaluationCell) -> RunRecord | None:
        if cell.parent_attempt_sha256 is None:
            return None
        return self._records.get(cell.parent_attempt_sha256)

    def preserve(self, record: RunRecord) -> None:
        existing = self._records.get(record.run_sha256)
        if existing is not None and existing != record:
            raise ValueError("Attempt identity collision.")
        self._records[record.run_sha256] = record

    def records(self) -> tuple[RunRecord, ...]:
        return tuple(self._records.values())


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
    actor: str = "framework",
    prerequisite: str = "verified-evidence",
) -> tuple[GateObservation, ...]:
    return tuple(item for item in observations if item.gate is not gate) + (
        issue_failure(
            gate,
            reason=reason,
            actor=actor,
            prerequisite=prerequisite,
        ),
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


def _lineage_valid(cell: EvaluationCell, ledger: AttemptLedger) -> bool:
    if cell.attempt == 1:
        return cell.parent_attempt_sha256 is None
    parent = ledger.parent_for(cell)
    return bool(
        parent
        and parent.case_id == cell.case_id
        and parent.revision == cell.revision
        and parent.variant is cell.variant
        and parent.runtime is cell.runtime_receipt.runtime
        and parent.attempt == cell.attempt - 1
        and parent.runtime_receipt_sha256
        == runtime_receipt_identity(cell.runtime_receipt)
    )


def _preflight_for(
    cell: EvaluationCell,
    verifier: TrustedEvidenceVerifier,
    ledger: AttemptLedger,
) -> PreflightResult:
    observations = verifier.verify(cell)
    if not _binding_valid(cell):
        observations = _replace_gate(
            observations,
            PreflightGate.RESOLUTION_IDENTITY,
            reason="receipt-binding-mismatch",
        )
    if not _lineage_valid(cell, ledger):
        observations = _replace_gate(
            observations,
            PreflightGate.ATTEMPT_POLICY,
            reason="attempt-lineage-invalid",
            prerequisite="preserved-parent-attempt",
        )
    subject_sha256 = canonical_sha256(
        {
            "case_id": cell.case_id,
            "fixture_sha256": cell.fixture_sha256,
            "runtime_receipt_sha256": runtime_receipt_identity(cell.runtime_receipt),
            "content_receipt_sha256": content_receipt_identity(cell.content_receipt),
            "consumption_receipt_sha256": consumption_receipt_identity(
                cell.consumption_receipt
            ),
            "route_evidence_sha256": cell.consumption_receipt.route_evidence_sha256,
            "continuity_evidence_sha256": cell.consumption_receipt.continuity_evidence_sha256,
        }
    )
    return evaluate_preflight(observations, subject_sha256=subject_sha256)


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
        "schema_version": "1.1",
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
        schema_version="1.1",
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
        comparability_sha256=str(document["comparability_sha256"]),
        runtime_receipt_sha256=str(document["runtime_receipt_sha256"]),
        content_receipt_sha256=str(document["content_receipt_sha256"]),
        consumption_receipt_sha256=str(document["consumption_receipt_sha256"]),
        preflight=preflight,
        state=state,
        output_sha256=output_sha256,
        controlled_artifact_path=controlled_artifact_path,
        completion_evidence_sha256=completion_evidence_sha256,
        technical_error_reason=technical_error_reason,
    )


def run_record_document(record: RunRecord) -> dict[str, object]:
    return {
        key: value
        for key, value in {
            **record.__dict__,
            "variant": record.variant.value,
            "runtime": record.runtime.value,
            "preflight": _preflight_document(record.preflight),
            "state": record.state.value,
        }.items()
        if not key.startswith("_")
    }


class EvaluationRunner:
    def __init__(
        self,
        runtime: InjectedRuntimeRunner,
        evidence_verifier: TrustedEvidenceVerifier,
        *,
        completion_verifier: TrustedCompletionVerifier | None = None,
        attempt_ledger: AttemptLedger | None = None,
    ) -> None:
        self._runtime = runtime
        self._evidence_verifier = evidence_verifier
        self._completion_verifier = completion_verifier
        self._ledger = attempt_ledger or AttemptLedger()

    @property
    def attempt_ledger(self) -> AttemptLedger:
        return self._ledger

    def _finish(self, record: RunRecord) -> RunRecord:
        self._ledger.preserve(record)
        return record

    def run(self, cell: EvaluationCell) -> RunRecord:
        preflight = _preflight_for(cell, self._evidence_verifier, self._ledger)
        if preflight.state is PreflightState.INVALID:
            return self._finish(
                _record(cell, preflight=preflight, state=RunState.INVALID)
            )
        if preflight.state is PreflightState.UNSUPPORTED:
            return self._finish(
                _record(cell, preflight=preflight, state=RunState.UNSUPPORTED)
            )
        try:
            output = self._runtime.execute(cell)
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
            return self._finish(_record(cell, preflight=failed, state=RunState.INVALID))

        output_sha256 = hashlib.sha256(output.output_text.encode()).hexdigest()
        proof = (
            self._completion_verifier.verify(cell, output, output_sha256)
            if self._completion_verifier
            else None
        )
        state = RunState.COMPLETED if proof else RunState.DISPATCH_AUTHORIZED
        return self._finish(
            _record(
                cell,
                preflight=preflight,
                state=state,
                output_sha256=output_sha256,
                controlled_artifact_path=output.controlled_artifact_path,
                completion_evidence_sha256=proof.evidence_sha256 if proof else None,
            )
        )
