"""Exact control pairing without aggregate behavioral scores."""

from __future__ import annotations

from cc.core.evaluation.identity import runtime_receipt_identity
from cc.core.evaluation.models import (
    ComparisonRecord,
    CriterionComparison,
    EvaluationCell,
    LayerVariant,
    PreflightState,
    RunRecord,
    RunState,
)
from cc.core.evaluation.schema import canonical_sha256

_VARIANT_ORDER = {
    LayerVariant.FOUNDATION: 0,
    LayerVariant.ORGANIZATION: 1,
    LayerVariant.DEPARTMENT: 2,
    LayerVariant.PERSONAL: 3,
}


def comparability_identity(cell: EvaluationCell) -> str:
    """Bind every controlled input except the intended content variant."""

    return canonical_sha256(
        {
            "case_id": cell.case_id,
            "revision": cell.revision,
            "fixture_sha256": cell.fixture_sha256,
            "prompt_evidence_sha256": cell.prompt_evidence_sha256,
            "runtime_receipt_sha256": runtime_receipt_identity(cell.runtime_receipt),
            "journey_task_id": cell.consumption_receipt.task_id,
            "attempt": cell.attempt,
            "parent_attempt_sha256": cell.parent_attempt_sha256,
            "attempt_policy_sha256": cell.attempt_policy_sha256,
            "runtime_configuration_sha256": cell.runtime_configuration_sha256,
            "tool_configuration_sha256": cell.tool_configuration_sha256,
        }
    )


def pair_control_runs(
    control: RunRecord,
    layered: RunRecord,
    *,
    relations: tuple[CriterionComparison, ...] = (),
) -> ComparisonRecord:
    """Create an attributable pair or fail before any behavioral claim."""

    if (
        control.state is not RunState.COMPLETED
        or layered.state is not RunState.COMPLETED
    ):
        raise ValueError("Only completed runs can enter behavioral comparison.")
    if (
        control.preflight.state is not PreflightState.VALID
        or layered.preflight.state is not PreflightState.VALID
    ):
        raise ValueError("Only preflight-valid runs can enter behavioral comparison.")
    if control.comparability_sha256 != layered.comparability_sha256:
        raise ValueError("Control inputs are not comparable.")
    if _VARIANT_ORDER[control.variant] >= _VARIANT_ORDER[layered.variant]:
        raise ValueError("The layered run must add exactly the intended higher tier.")
    criteria = tuple(item.criterion for item in relations)
    if len(criteria) != len(set(criteria)):
        raise ValueError("Criterion relations must be unique.")

    document = {
        "schema_version": "1.0",
        "comparability_sha256": control.comparability_sha256,
        "control_run_sha256": control.run_sha256,
        "layered_run_sha256": layered.run_sha256,
        "relations": [
            {
                "criterion": item.criterion,
                "relation": item.relation.value,
                "control_evidence_sha256": list(item.control_evidence_sha256),
                "layered_evidence_sha256": list(item.layered_evidence_sha256),
            }
            for item in relations
        ],
        "hard_gate_state": PreflightState.VALID.value,
    }
    return ComparisonRecord(
        schema_version="1.0",
        comparison_sha256=canonical_sha256(document),
        comparability_sha256=control.comparability_sha256,
        control_run_sha256=control.run_sha256,
        layered_run_sha256=layered.run_sha256,
        relations=relations,
        hard_gate_state=PreflightState.VALID,
    )


def comparison_record_document(record: ComparisonRecord) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "comparison_sha256": record.comparison_sha256,
        "comparability_sha256": record.comparability_sha256,
        "control_run_sha256": record.control_run_sha256,
        "layered_run_sha256": record.layered_run_sha256,
        "relations": [
            {
                "criterion": item.criterion,
                "relation": item.relation.value,
                "control_evidence_sha256": list(item.control_evidence_sha256),
                "layered_evidence_sha256": list(item.layered_evidence_sha256),
            }
            for item in record.relations
        ],
        "hard_gate_state": record.hard_gate_state.value,
    }
