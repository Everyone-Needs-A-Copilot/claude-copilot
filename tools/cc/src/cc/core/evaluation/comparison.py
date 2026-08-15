"""Exact control pairing without aggregate behavioral scores."""

from __future__ import annotations

from cc.core.evaluation.identity import runtime_receipt_identity
from cc.core.evaluation.models import (
    _COMPARISON_AUTHORITY,
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
_APPLICABLE_PAIRS = {
    "eval-01": {(LayerVariant.FOUNDATION, LayerVariant.ORGANIZATION)},
    "eval-02": {(LayerVariant.FOUNDATION, LayerVariant.ORGANIZATION)},
    "eval-03": {(LayerVariant.FOUNDATION, LayerVariant.ORGANIZATION)},
    "eval-04": {(LayerVariant.FOUNDATION, LayerVariant.ORGANIZATION)},
    "eval-05": {(LayerVariant.FOUNDATION, LayerVariant.DEPARTMENT)},
    "eval-06": {(LayerVariant.FOUNDATION, LayerVariant.ORGANIZATION)},
    "eval-07": {(LayerVariant.DEPARTMENT, LayerVariant.PERSONAL)},
}
_JUDGMENT_COMPARISON_AUTHORITY = object()
_ISSUED_COMPARISONS: dict[int, ComparisonRecord] = {}


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
            "route_evidence_sha256": cell.consumption_receipt.route_evidence_sha256,
            "attempt_policy_sha256": cell.attempt_policy_sha256,
            "command_policy_sha256": cell.command_policy_sha256,
        }
    )


def pair_control_runs(
    control: RunRecord,
    layered: RunRecord,
    *,
    relations: tuple[CriterionComparison, ...] = (),
    control_judgment_sha256: str = "",
    layered_judgment_sha256: str = "",
    _judgment_authority: object | None = None,
) -> ComparisonRecord:
    """Create a pair only for the authenticated judgment coordinator."""

    from cc.core.evaluation.runner import verify_run_record_identity

    if not verify_run_record_identity(control) or not verify_run_record_identity(
        layered
    ):
        raise ValueError("Only authentic runner-issued records can be compared.")
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
    applicable = _APPLICABLE_PAIRS.get(control.case_id, set())
    if (
        control.case_id != layered.case_id
        or (control.variant, layered.variant) not in applicable
    ):
        raise ValueError(
            "Runs are not the exact applicable control pair for this case."
        )
    criteria = tuple(item.criterion for item in relations)
    if not criteria or len(criteria) != len(set(criteria)):
        raise ValueError("Comparison requires unique, nonempty criterion relations.")
    if _judgment_authority is not _JUDGMENT_COMPARISON_AUTHORITY:
        raise ValueError(
            "Comparison issuance requires authenticated criterion judgments."
        )
    if any(
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for digest in (control_judgment_sha256, layered_judgment_sha256)
    ):
        raise ValueError("Comparison requires exact durable judgment identities.")

    document = {
        "schema_version": "1.0",
        "comparability_sha256": control.comparability_sha256,
        "control_run_sha256": control.run_sha256,
        "layered_run_sha256": layered.run_sha256,
        "control_judgment_sha256": control_judgment_sha256,
        "layered_judgment_sha256": layered_judgment_sha256,
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
    record = ComparisonRecord(
        schema_version="1.0",
        comparison_sha256=canonical_sha256(document),
        comparability_sha256=control.comparability_sha256,
        control_run_sha256=control.run_sha256,
        layered_run_sha256=layered.run_sha256,
        control_judgment_sha256=control_judgment_sha256,
        layered_judgment_sha256=layered_judgment_sha256,
        relations=relations,
        hard_gate_state=PreflightState.VALID,
        _authority=_COMPARISON_AUTHORITY,
    )
    _ISSUED_COMPARISONS[id(record)] = record
    return record


def comparison_record_document(record: ComparisonRecord) -> dict[str, object]:
    if not verify_comparison_record_identity(record):
        raise ValueError("Comparison record is not authentic.")
    return {
        "schema_version": record.schema_version,
        "comparison_sha256": record.comparison_sha256,
        "comparability_sha256": record.comparability_sha256,
        "control_run_sha256": record.control_run_sha256,
        "layered_run_sha256": record.layered_run_sha256,
        "control_judgment_sha256": record.control_judgment_sha256,
        "layered_judgment_sha256": record.layered_judgment_sha256,
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


def verify_comparison_record_identity(record: ComparisonRecord) -> bool:
    document = {
        "schema_version": record.schema_version,
        "comparability_sha256": record.comparability_sha256,
        "control_run_sha256": record.control_run_sha256,
        "layered_run_sha256": record.layered_run_sha256,
        "control_judgment_sha256": record.control_judgment_sha256,
        "layered_judgment_sha256": record.layered_judgment_sha256,
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
    return (
        getattr(record, "_authority", None) is _COMPARISON_AUTHORITY
        and _ISSUED_COMPARISONS.get(id(record)) is record
        and record.comparison_sha256 == canonical_sha256(document)
    )
