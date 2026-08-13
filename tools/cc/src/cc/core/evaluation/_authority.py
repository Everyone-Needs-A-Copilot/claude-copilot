"""Private authority boundary for evaluation evidence.

Nothing in this module is re-exported by ``cc.core.evaluation``. Production
issuance consumes the verified fixture loader and TASK-296 ledger inspection;
the adapter stays fail-closed until signed TASK-297 evidence exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from cc.core.evaluation.identity import (
    consumption_receipt_identity,
    content_receipt_identity,
    runtime_receipt_identity,
)
from cc.core.evaluation.models import (
    _EVIDENCE_AUTHORITY,
    EvaluationCell,
    GateObservation,
    GateState,
    PreflightGate,
    PreflightResult,
)
from cc.core.evaluation.preflight import evaluate_preflight
from cc.core.evaluation.schema import canonical_sha256

_AUTHORITY_TOKEN = object()


def _cell_subject(cell: EvaluationCell) -> str:
    return canonical_sha256(
        {
            "case_id": cell.case_id,
            "revision": cell.revision,
            "fixture_sha256": cell.fixture_sha256,
            "runtime_receipt_sha256": runtime_receipt_identity(cell.runtime_receipt),
            "content_receipt_sha256": content_receipt_identity(cell.content_receipt),
            "consumption_receipt_sha256": consumption_receipt_identity(
                cell.consumption_receipt
            ),
            "prompt_evidence_sha256": cell.prompt_evidence_sha256,
        }
    )


@dataclass(frozen=True)
class _EvaluationAuthority:
    subject_sha256: str
    preflight: PreflightResult
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _AUTHORITY_TOKEN:
            raise ValueError("Evaluation authority is invalid.")

    def applies_to(self, cell: EvaluationCell) -> bool:
        return self.subject_sha256 == _cell_subject(cell)


def _observation(
    gate: PreflightGate,
    state: GateState,
    reason: str,
    actor: str,
    prerequisite: str,
) -> GateObservation:
    return GateObservation(
        gate,
        state,
        reason,
        actor,
        prerequisite,
        _EVIDENCE_AUTHORITY if state is GateState.PASS else None,
    )


def _production_authority(
    cell: EvaluationCell,
    *,
    loaded_fixture: object,
    journey_run_id: str,
    journey_ledger: object,
) -> _EvaluationAuthority:
    """Consume verified production inputs; stay fail-closed before TASK-297.

    TASK-296 can prove dispatch authorization but not specialist completion,
    and TASK-297 has not yet supplied the signed entitlement/content authority.
    Consequently this production adapter truthfully cannot issue a fully VALID
    evaluation authority yet.
    """

    from cc.core.evaluation.fixtures import LoadedFixture
    from cc.core.evaluation.journey_runtime import TcJourneyLedger, inspect_run

    facts: dict[PreflightGate, tuple[GateState, str, str, str]] = {}
    if isinstance(loaded_fixture, LoadedFixture) and (
        loaded_fixture.fixture_sha256 == cell.fixture_sha256
        and loaded_fixture.fixture.case_id == cell.case_id
        and loaded_fixture.fixture.revision == cell.revision
    ):
        facts[PreflightGate.FIXTURE_CONTRACT] = (
            GateState.PASS,
            "verified",
            "fixture-loader",
            "digest-bound-fixture",
        )
    if isinstance(journey_ledger, TcJourneyLedger):
        try:
            state = inspect_run(journey_run_id, ledger=journey_ledger)
        except (OSError, TypeError, ValueError):
            state = {}
        if (
            state.get("evidence_claim") == "dispatch_observed_and_authorized_only"
            and state.get("prompt_sha256") == cell.prompt_evidence_sha256
            and state.get("task_id") == cell.consumption_receipt.task_id
        ):
            facts[PreflightGate.JOURNEY_EVIDENCE] = (
                GateState.PASS,
                "dispatch-authorized",
                "task296-ledger",
                "verified-dispatch-ledger",
            )
    # No production PASS exists for signed content/entitlement until TASK-297.
    facts[PreflightGate.ENTITLEMENT_AND_PINS] = (
        GateState.UNSUPPORTED,
        "signed-content-unavailable",
        "publisher",
        "task297-signed-content",
    )
    observations = tuple(
        _observation(gate, *fact)
        for gate, fact in sorted(facts.items(), key=lambda x: x[0].value)
    )
    subject = _cell_subject(cell)
    return _EvaluationAuthority(
        subject,
        evaluate_preflight(observations, subject_sha256=subject),
        _AUTHORITY_TOKEN,
    )
