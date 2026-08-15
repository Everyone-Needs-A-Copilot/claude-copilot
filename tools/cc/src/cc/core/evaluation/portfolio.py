"""Identity-bound exact-matrix acceptance and Claude/Codex parity evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from cc.core.evaluation.artifact import (
    LoadedDurableRunEvidence,
    close_artifact_receipt,
    verify_artifact_receipt,
)
from cc.core.evaluation.comparison import (
    comparison_record_document,
    verify_comparison_record_identity,
)
from cc.core.evaluation.judgment import (
    CriterionJudgment,
    LoadedDurableJudgmentEvidence,
    compare_criterion_judgments,
    verify_criterion_judgment_identity,
)
from cc.core.evaluation.matrix import (
    EvaluationMatrix,
    MatrixCellPlan,
    matrix_document,
)
from cc.core.evaluation.models import (
    ArtifactReceipt,
    ComparisonRecord,
    CriterionRelation,
    CriterionVerdict,
    LayerVariant,
    PreflightState,
    RunRecord,
    RunState,
    RuntimeName,
)
from cc.core.evaluation.runner import verify_run_record_identity
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256

PORTFOLIO_SCHEMA_VERSION = "1.0"
PARITY_SCHEMA_VERSION = "1.0"
ATTRIBUTION_SCHEMA_VERSION = "1.0"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_PROTECTED_CRITERIA = frozenset(
    {
        "safety-and-privacy",
        "user-ownership",
        "evidence",
        "evidence-discipline",
        "factual-restraint",
        "appropriate-methodology",
        "specialist-craft",
        "applicable-craft",
    }
)
_ORGANIZATION_CASES = frozenset({"eval-01", "eval-02", "eval-03", "eval-04", "eval-06"})
_EXTENSION_SPECIALISTS = frozenset({"uids", "cco"})
_TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.UNSUPPORTED})

_DURABLE_COMPARISON_AUTHORITY = object()
_ATTRIBUTION_AUTHORITY = object()
_PARITY_AUTHORITY = object()
_PORTFOLIO_AUTHORITY = object()
_ISSUED_DURABLE_COMPARISONS: dict[int, "DurableComparisonEvidence"] = {}
_ISSUED_ATTRIBUTIONS: dict[int, "AttributionRecord"] = {}
_ISSUED_PARITY_RECORDS: dict[int, "RuntimeParityRecord"] = {}
_ISSUED_PORTFOLIOS: dict[int, "PortfolioRecord"] = {}


def _require_digest(value: str, field_name: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


def _require_code(value: str, field_name: str) -> None:
    if not _CODE.fullmatch(value):
        raise ValueError(f"{field_name} must be a closed identifier.")


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class DurableComparisonEvidence:
    """Coordinator comparison plus its retained durable artifact and judgments."""

    record: ComparisonRecord
    receipt: ArtifactReceipt
    control: LoadedDurableJudgmentEvidence = field(repr=False, compare=False)
    layered: LoadedDurableJudgmentEvidence = field(repr=False, compare=False)
    binding_sha256: str
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _DURABLE_COMPARISON_AUTHORITY:
            raise ValueError("Durable comparison evidence is not verifier-issued.")
        _require_digest(self.binding_sha256, "binding_sha256")

    def validate(self) -> bool:
        return verify_durable_comparison_evidence(self)

    def close(self) -> None:
        """Revoke only this exact retained comparison artifact."""

        if _ISSUED_DURABLE_COMPARISONS.get(id(self)) is not self:
            return
        _ISSUED_DURABLE_COMPARISONS.pop(id(self), None)
        close_artifact_receipt(self.receipt)


def _durable_comparison_document(
    record: ComparisonRecord,
    receipt: ArtifactReceipt,
    control: LoadedDurableJudgmentEvidence,
    layered: LoadedDurableJudgmentEvidence,
) -> dict[str, object]:
    return {
        "comparison_sha256": record.comparison_sha256,
        "comparison_artifact_sha256": receipt.sha256,
        "control_run_sha256": control.loaded_run.record.run_sha256,
        "layered_run_sha256": layered.loaded_run.record.run_sha256,
        "control_judgment_sha256": control.judgment.judgment_sha256,
        "layered_judgment_sha256": layered.judgment.judgment_sha256,
    }


def bind_durable_comparison(
    record: ComparisonRecord,
    receipt: ArtifactReceipt,
    *,
    control: LoadedDurableJudgmentEvidence,
    layered: LoadedDurableJudgmentEvidence,
) -> DurableComparisonEvidence:
    """Bind the exact artifact receipt returned by durable comparison issuance."""

    try:
        expected = compare_criterion_judgments(
            control.loaded_run.record,
            layered.loaded_run.record,
            control.judgment,
            layered.judgment,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Comparison judgments cannot be reverified.") from exc
    if (
        not verify_comparison_record_identity(record)
        or not verify_artifact_receipt(receipt)
        or receipt.artifact_type != "comparison-record"
        or receipt.sha256 != canonical_sha256(comparison_record_document(record))
        or not control.validate()
        or not layered.validate()
        or record.control_run_sha256 != control.loaded_run.record.run_sha256
        or record.layered_run_sha256 != layered.loaded_run.record.run_sha256
        or record.control_judgment_sha256 != control.judgment.judgment_sha256
        or record.layered_judgment_sha256 != layered.judgment.judgment_sha256
        or record.relations != expected.relations
        or record.control_run_sha256 != expected.control_run_sha256
        or record.layered_run_sha256 != expected.layered_run_sha256
        or record.control_judgment_sha256 != expected.control_judgment_sha256
        or record.layered_judgment_sha256 != expected.layered_judgment_sha256
    ):
        raise ValueError("Comparison is not exact retained durable evidence.")
    binding = canonical_sha256(
        _durable_comparison_document(record, receipt, control, layered)
    )
    result = DurableComparisonEvidence(
        record,
        receipt,
        control,
        layered,
        binding,
        _DURABLE_COMPARISON_AUTHORITY,
    )
    _ISSUED_DURABLE_COMPARISONS[id(result)] = result
    return result


def verify_durable_comparison_evidence(value: DurableComparisonEvidence) -> bool:
    if (
        not isinstance(value, DurableComparisonEvidence)
        or _ISSUED_DURABLE_COMPARISONS.get(id(value)) is not value
        or value._authority is not _DURABLE_COMPARISON_AUTHORITY
    ):
        return False
    try:
        return bool(
            verify_comparison_record_identity(value.record)
            and verify_artifact_receipt(value.receipt)
            and value.control.validate()
            and value.layered.validate()
            and value.binding_sha256
            == canonical_sha256(
                _durable_comparison_document(
                    value.record,
                    value.receipt,
                    value.control,
                    value.layered,
                )
            )
        )
    except (OSError, TypeError, ValueError):
        return False


def load_durable_comparison_evidence(
    root: Path,
    artifact_sha256: str,
    *,
    control: LoadedDurableJudgmentEvidence,
    layered: LoadedDurableJudgmentEvidence,
) -> DurableComparisonEvidence | None:
    """Reload, recompute, and retain one exact comparison after restart."""

    from cc.core.evaluation.judgment import _load_durable_comparison

    loaded = _load_durable_comparison(
        root,
        artifact_sha256,
        control=control,
        layered=layered,
    )
    if loaded is None:
        return None
    record, receipt = loaded
    try:
        return bind_durable_comparison(
            record,
            receipt,
            control=control,
            layered=layered,
        )
    except (OSError, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AttributionRecord:
    schema_version: str
    attribution_sha256: str
    case_id: str
    runtime: RuntimeName
    control_variant: LayerVariant
    layered_variant: LayerVariant
    comparison_sha256: str
    route_contract_sha256: str
    specialist: str
    process_evidence_sha256: tuple[str, ...]
    context_evidence_sha256: tuple[str, ...]
    decision_evidence_sha256: tuple[str, ...]
    route_citations_sha256: tuple[str, ...]
    process_event_citations_sha256: tuple[str, ...]
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _ATTRIBUTION_AUTHORITY
            or self.schema_version != ATTRIBUTION_SCHEMA_VERSION
        ):
            raise ValueError("Attribution record is not verifier-issued.")
        _require_code(self.case_id, "case_id")
        _require_code(self.specialist, "specialist")
        for digest in (
            self.attribution_sha256,
            self.comparison_sha256,
            self.route_contract_sha256,
            *self.process_evidence_sha256,
            *self.context_evidence_sha256,
            *self.decision_evidence_sha256,
            *self.route_citations_sha256,
            *self.process_event_citations_sha256,
        ):
            _require_digest(digest, "attribution evidence")
        if not all(
            (
                self.process_evidence_sha256,
                self.context_evidence_sha256,
                self.decision_evidence_sha256,
                self.route_citations_sha256,
                self.process_event_citations_sha256,
            )
        ):
            raise ValueError(
                "Attribution requires process, context, and decision proof."
            )


def _attribution_identity_document(value: AttributionRecord) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "case_id": value.case_id,
        "runtime": value.runtime.value,
        "control_variant": value.control_variant.value,
        "layered_variant": value.layered_variant.value,
        "comparison_sha256": value.comparison_sha256,
        "route_contract_sha256": value.route_contract_sha256,
        "specialist": value.specialist,
        "process_evidence_sha256": list(value.process_evidence_sha256),
        "context_evidence_sha256": list(value.context_evidence_sha256),
        "decision_evidence_sha256": list(value.decision_evidence_sha256),
        "route_citations_sha256": list(value.route_citations_sha256),
        "process_event_citations_sha256": list(value.process_event_citations_sha256),
    }


def attribution_record_document(value: AttributionRecord) -> dict[str, object]:
    if not verify_attribution_record_identity(value):
        raise ValueError("Attribution record is not authentic.")
    return {
        **_attribution_identity_document(value),
        "attribution_sha256": value.attribution_sha256,
    }


def verify_attribution_record_identity(value: AttributionRecord) -> bool:
    return bool(
        isinstance(value, AttributionRecord)
        and _ISSUED_ATTRIBUTIONS.get(id(value)) is value
        and value._authority is _ATTRIBUTION_AUTHORITY
        and value.attribution_sha256
        == canonical_sha256(_attribution_identity_document(value))
    )


def _attribution_components(
    evidence: DurableComparisonEvidence,
    *,
    control_plan: MatrixCellPlan,
    layered_plan: MatrixCellPlan,
) -> dict[str, object]:
    """Validate and derive value-suppressing fields without issuing authority."""

    if not verify_durable_comparison_evidence(evidence):
        raise ValueError("Attribution requires retained comparison evidence.")
    control = evidence.control.loaded_run.record
    layered = evidence.layered.loaded_run.record
    record = evidence.record
    if (
        control.case_id != layered.case_id
        or control.runtime is not layered.runtime
        or control.case_id != control_plan.case_id
        or layered.case_id != layered_plan.case_id
        or control.variant is not control_plan.variant
        or layered.variant is not layered_plan.variant
        or control.runtime is not control_plan.runtime
        or layered.runtime is not layered_plan.runtime
        or control_plan.role != "control"
        or layered_plan.role != "layered"
        or control_plan.route_contract_sha256 != layered_plan.route_contract_sha256
        or control_plan.expected_specialist != layered_plan.expected_specialist
        or control.content_receipt_sha256 == layered.content_receipt_sha256
        or control.completion_evidence_sha256 is None
        or layered.completion_evidence_sha256 is None
        or record.control_run_sha256 != control.run_sha256
        or record.layered_run_sha256 != layered.run_sha256
    ):
        raise ValueError(
            "Comparison does not prove the preregistered route difference."
        )
    decision = _unique(
        digest
        for relation in record.relations
        for digest in (
            *relation.control_evidence_sha256,
            *relation.layered_evidence_sha256,
        )
    )
    process = _unique(
        (
            control.consumption_receipt_sha256,
            layered.consumption_receipt_sha256,
            control.completion_evidence_sha256,
            layered.completion_evidence_sha256,
        )
    )
    context = _unique((control.content_receipt_sha256, layered.content_receipt_sha256))
    route = _unique(
        (
            control_plan.route_contract_sha256,
            control.runtime_configuration_sha256,
            layered.runtime_configuration_sha256,
            control.consumption_receipt_sha256,
            layered.consumption_receipt_sha256,
        )
    )
    process_events = _unique(
        (control.completion_evidence_sha256, layered.completion_evidence_sha256)
    )
    return {
        "case_id": control.case_id,
        "runtime": control.runtime,
        "control_variant": control.variant,
        "layered_variant": layered.variant,
        "comparison_sha256": record.comparison_sha256,
        "route_contract_sha256": control_plan.route_contract_sha256,
        "specialist": control_plan.expected_specialist,
        "process_evidence_sha256": process,
        "context_evidence_sha256": context,
        "decision_evidence_sha256": decision,
        "route_citations_sha256": route,
        "process_event_citations_sha256": process_events,
    }


@dataclass(frozen=True)
class ParityCriterion:
    criterion: str
    claude_verdict: str
    codex_verdict: str
    state: str
    claude_evidence_sha256: tuple[str, ...]
    codex_evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_code(self.criterion, "criterion")
        if self.state not in {"equivalent", "diverged"}:
            raise ValueError("Criterion parity state is invalid.")
        for verdict in (self.claude_verdict, self.codex_verdict):
            if verdict not in {item.value for item in CriterionVerdict}:
                raise ValueError("Criterion parity verdict is invalid.")
        for digest in self.claude_evidence_sha256 + self.codex_evidence_sha256:
            _require_digest(digest, "parity evidence")


@dataclass(frozen=True)
class RuntimeParityRecord:
    schema_version: str
    parity_sha256: str
    case_id: str
    revision: int
    variant: LayerVariant
    claude_run_sha256: str
    codex_run_sha256: str
    claude_judgment_sha256: str | None
    codex_judgment_sha256: str | None
    state: str
    criteria: tuple[ParityCriterion, ...]
    unsupported_runtimes: tuple[str, ...]
    unsupported_reasons: tuple[str, ...]
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _PARITY_AUTHORITY
            or self.schema_version != PARITY_SCHEMA_VERSION
            or self.revision != 1
            or self.state not in {"equivalent", "diverged", "unsupported"}
        ):
            raise ValueError("Runtime parity record is not verifier-issued.")
        _require_code(self.case_id, "case_id")
        for digest in (
            self.parity_sha256,
            self.claude_run_sha256,
            self.codex_run_sha256,
        ):
            _require_digest(digest, "parity identity")
        for digest in (self.claude_judgment_sha256, self.codex_judgment_sha256):
            if digest is not None:
                _require_digest(digest, "parity judgment")
        for value in self.unsupported_runtimes + self.unsupported_reasons:
            _require_code(value, "unsupported disposition")
        if self.state == "unsupported":
            if (
                self.criteria
                or not self.unsupported_runtimes
                or not self.unsupported_reasons
            ):
                raise ValueError("Unsupported parity requires an explicit disposition.")
        elif (
            not self.criteria
            or self.unsupported_runtimes
            or self.unsupported_reasons
            or self.claude_judgment_sha256 is None
            or self.codex_judgment_sha256 is None
        ):
            raise ValueError("Supported parity requires exact criterion judgments.")


def _parity_identity_document(value: RuntimeParityRecord) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "case_id": value.case_id,
        "revision": value.revision,
        "variant": value.variant.value,
        "claude_run_sha256": value.claude_run_sha256,
        "codex_run_sha256": value.codex_run_sha256,
        "claude_judgment_sha256": value.claude_judgment_sha256,
        "codex_judgment_sha256": value.codex_judgment_sha256,
        "state": value.state,
        "criteria": [
            {
                "criterion": item.criterion,
                "claude_verdict": item.claude_verdict,
                "codex_verdict": item.codex_verdict,
                "state": item.state,
                "claude_evidence_sha256": list(item.claude_evidence_sha256),
                "codex_evidence_sha256": list(item.codex_evidence_sha256),
            }
            for item in value.criteria
        ],
        "unsupported_runtimes": list(value.unsupported_runtimes),
        "unsupported_reasons": list(value.unsupported_reasons),
    }


def runtime_parity_document(value: RuntimeParityRecord) -> dict[str, object]:
    if not verify_runtime_parity_identity(value):
        raise ValueError("Runtime parity record is not authentic.")
    return {
        **_parity_identity_document(value),
        "parity_sha256": value.parity_sha256,
    }


def verify_runtime_parity_identity(value: RuntimeParityRecord) -> bool:
    return bool(
        isinstance(value, RuntimeParityRecord)
        and _ISSUED_PARITY_RECORDS.get(id(value)) is value
        and value._authority is _PARITY_AUTHORITY
        and value.parity_sha256 == canonical_sha256(_parity_identity_document(value))
    )


@dataclass(frozen=True)
class PortfolioCellResult:
    case_id: str
    revision: int
    variant: LayerVariant
    runtime: RuntimeName
    terminal_run_sha256: str
    terminal_state: RunState
    attempt_lineage_sha256: tuple[str, ...]
    judgment_sha256: str | None
    unsupported_reasons: tuple[str, ...]


@dataclass(frozen=True)
class PairDisposition:
    case_id: str
    runtime: RuntimeName
    control_run_sha256: str
    layered_run_sha256: str
    state: str
    comparison_sha256: str | None
    attribution_sha256: str | None
    unsupported_runtimes: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioRecord:
    schema_version: str
    portfolio_sha256: str
    matrix_sha256: str
    acceptance_state: str
    cells: tuple[PortfolioCellResult, ...]
    pairs: tuple[PairDisposition, ...]
    parity: tuple[RuntimeParityRecord, ...]
    attributions: tuple[AttributionRecord, ...]
    organization_contribution_cases: tuple[str, ...]
    organization_extension_cases: tuple[str, ...]
    department_contribution_cases: tuple[str, ...]
    blockers: tuple[str, ...]
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _PORTFOLIO_AUTHORITY
            or self.schema_version != PORTFOLIO_SCHEMA_VERSION
            or self.acceptance_state not in {"accepted", "rejected"}
        ):
            raise ValueError("Portfolio record is not verifier-issued.")
        for digest in (self.portfolio_sha256, self.matrix_sha256):
            _require_digest(digest, "portfolio identity")
        for blocker in self.blockers:
            _require_code(blocker, "portfolio blocker")
        if (self.acceptance_state == "accepted") != (not self.blockers):
            raise ValueError("Portfolio acceptance does not match its blockers.")


def _cell_document(value: PortfolioCellResult) -> dict[str, object]:
    return {
        "case_id": value.case_id,
        "revision": value.revision,
        "variant": value.variant.value,
        "runtime": value.runtime.value,
        "terminal_run_sha256": value.terminal_run_sha256,
        "terminal_state": value.terminal_state.value,
        "attempt_lineage_sha256": list(value.attempt_lineage_sha256),
        "judgment_sha256": value.judgment_sha256,
        "unsupported_reasons": list(value.unsupported_reasons),
    }


def _pair_document(value: PairDisposition) -> dict[str, object]:
    return {
        "case_id": value.case_id,
        "runtime": value.runtime.value,
        "control_run_sha256": value.control_run_sha256,
        "layered_run_sha256": value.layered_run_sha256,
        "state": value.state,
        "comparison_sha256": value.comparison_sha256,
        "attribution_sha256": value.attribution_sha256,
        "unsupported_runtimes": list(value.unsupported_runtimes),
    }


def _portfolio_identity_document(value: PortfolioRecord) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "matrix_sha256": value.matrix_sha256,
        "acceptance_state": value.acceptance_state,
        "cells": [_cell_document(item) for item in value.cells],
        "pairs": [_pair_document(item) for item in value.pairs],
        "parity": [runtime_parity_document(item) for item in value.parity],
        "attributions": [
            attribution_record_document(item) for item in value.attributions
        ],
        "organization_contribution_cases": list(value.organization_contribution_cases),
        "organization_extension_cases": list(value.organization_extension_cases),
        "department_contribution_cases": list(value.department_contribution_cases),
        "blockers": list(value.blockers),
    }


def portfolio_record_document(value: PortfolioRecord) -> dict[str, object]:
    if not verify_portfolio_record_identity(value):
        raise ValueError("Portfolio record is not authentic.")
    return {
        **_portfolio_identity_document(value),
        "portfolio_sha256": value.portfolio_sha256,
    }


def verify_portfolio_record_identity(value: PortfolioRecord) -> bool:
    if (
        not isinstance(value, PortfolioRecord)
        or _ISSUED_PORTFOLIOS.get(id(value)) is not value
        or value._authority is not _PORTFOLIO_AUTHORITY
        or any(not verify_runtime_parity_identity(item) for item in value.parity)
        or any(
            not verify_attribution_record_identity(item) for item in value.attributions
        )
    ):
        return False
    try:
        return value.portfolio_sha256 == canonical_sha256(
            _portfolio_identity_document(value)
        )
    except (TypeError, ValueError):
        return False


def _matrix_is_authentic(matrix: EvaluationMatrix) -> bool:
    try:
        document = matrix_document(matrix)
        declared = str(document.pop("matrix_sha256"))
        return (
            declared
            == matrix.matrix_sha256
            == PACKAGED_MATRIX_SHA256
            == canonical_sha256(document)
            and len(matrix.cells) == 28
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _lineage_invariants(record: RunRecord) -> tuple[object, ...]:
    return (
        record.case_id,
        record.revision,
        record.variant,
        record.runtime,
        record.fixture_sha256,
        record.prompt_evidence_sha256,
        record.attempt_policy_sha256,
        record.runtime_configuration_sha256,
        record.tool_configuration_sha256,
        record.effective_full_prompt_sha256,
        record.command_policy_sha256,
        record.runtime_receipt_sha256,
        record.content_receipt_sha256,
        record.consumption_receipt_sha256,
    )


def _unsupported_reasons(record: RunRecord) -> tuple[str, ...]:
    return _unique(
        item.reason
        for item in record.preflight.observations
        if item.state.value == "unsupported"
    )


def _validated_lineage(
    records: tuple[LoadedDurableRunEvidence, ...],
) -> tuple[RunRecord, ...] | None:
    if not records or any(not item.validate() for item in records):
        return None
    lineage = tuple(
        sorted((item.record for item in records), key=lambda item: item.attempt)
    )
    if (
        tuple(item.attempt for item in lineage) != tuple(range(1, len(lineage) + 1))
        or len(lineage) > 2
        or len({_lineage_invariants(item) for item in lineage}) != 1
        or any(
            item.parent_attempt_sha256
            != (None if index == 0 else lineage[index - 1].run_sha256)
            for index, item in enumerate(lineage)
        )
        or any(item.state is not RunState.TECHNICAL_ERROR for item in lineage[:-1])
        or lineage[-1].state not in _TERMINAL_STATES
    ):
        return None
    terminal = lineage[-1]
    if terminal.state is RunState.COMPLETED:
        if terminal.preflight.state is not PreflightState.VALID:
            return None
    elif (
        terminal.preflight.state is not PreflightState.UNSUPPORTED
        or len(lineage) != 1
        or not _unsupported_reasons(terminal)
    ):
        return None
    return lineage


def _judgment_is_acceptable(
    value: LoadedDurableJudgmentEvidence,
    record: RunRecord,
) -> bool:
    judgment = value.judgment
    return bool(
        value.validate()
        and verify_criterion_judgment_identity(judgment)
        and judgment.run_sha256 == record.run_sha256
        and judgment.hard_gate_passed
        and not judgment.triggered_rejections
        and all(
            item.content_receipt_sha256 == (record.content_receipt_sha256,)
            for item in judgment.assessments
        )
        and not any(
            item.criterion in _PROTECTED_CRITERIA
            and item.verdict is CriterionVerdict.VIOLATED
            for item in judgment.assessments
        )
    )


def _parity_components(
    claude: PortfolioCellResult,
    codex: PortfolioCellResult,
    judgments: dict[str, CriterionJudgment],
) -> dict[str, object]:
    if claude.case_id != codex.case_id or claude.variant is not codex.variant:
        raise ValueError("Parity inputs do not describe one logical matrix cell.")
    unsupported = tuple(
        item.runtime.value
        for item in (claude, codex)
        if item.terminal_state is RunState.UNSUPPORTED
    )
    if unsupported:
        reasons = _unique((*claude.unsupported_reasons, *codex.unsupported_reasons))
        state = "unsupported"
        criteria: tuple[ParityCriterion, ...] = ()
    else:
        claude_judgment = judgments.get(claude.terminal_run_sha256)
        codex_judgment = judgments.get(codex.terminal_run_sha256)
        if claude_judgment is None or codex_judgment is None:
            raise ValueError("Supported parity requires exact judgments.")
        claude_by_criterion = {
            item.criterion: item for item in claude_judgment.assessments
        }
        codex_by_criterion = {
            item.criterion: item for item in codex_judgment.assessments
        }
        if tuple(claude_by_criterion) != tuple(codex_by_criterion):
            raise ValueError("Runtime parity criteria differ.")
        criteria = tuple(
            ParityCriterion(
                criterion,
                claude_item.verdict.value,
                codex_by_criterion[criterion].verdict.value,
                (
                    "equivalent"
                    if claude_item.verdict is codex_by_criterion[criterion].verdict
                    else "diverged"
                ),
                claude_item.evidence_sha256,
                codex_by_criterion[criterion].evidence_sha256,
            )
            for criterion, claude_item in claude_by_criterion.items()
        )
        state = (
            "equivalent"
            if all(item.state == "equivalent" for item in criteria)
            else "diverged"
        )
        unsupported = ()
        reasons = ()
    return {
        "case_id": claude.case_id,
        "revision": claude.revision,
        "variant": claude.variant,
        "claude_run_sha256": claude.terminal_run_sha256,
        "codex_run_sha256": codex.terminal_run_sha256,
        "claude_judgment_sha256": claude.judgment_sha256,
        "codex_judgment_sha256": codex.judgment_sha256,
        "state": state,
        "criteria": criteria,
        "unsupported_runtimes": unsupported,
        "unsupported_reasons": reasons,
    }


def _phase_minimum_blockers(
    pairs: tuple[PairDisposition, ...],
    parity: tuple[RuntimeParityRecord, ...],
    attributions: dict[str, AttributionRecord],
    comparisons: dict[str, ComparisonRecord],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    organization_cases: set[str] = set()
    extension_cases: set[str] = set()
    department_cases: set[str] = set()
    blockers: set[str] = set()
    for pair in pairs:
        if pair.state != "compared" or pair.comparison_sha256 is None:
            continue
        comparison = comparisons[pair.comparison_sha256]
        attribution = attributions.get(pair.comparison_sha256)
        improved = any(
            item.relation is CriterionRelation.IMPROVED for item in comparison.relations
        )
        if attribution is None:
            blockers.add("comparison-attribution-missing")
            continue
        if improved and pair.case_id in _ORGANIZATION_CASES:
            organization_cases.add(pair.case_id)
            if attribution.specialist in _EXTENSION_SPECIALISTS:
                extension_cases.add(pair.case_id)
        if improved and pair.case_id == "eval-05":
            department_cases.add(pair.case_id)
    if not {"eval-01", "eval-02"}.issubset(organization_cases):
        blockers.add("mandatory-organization-cases-missing")
    if len(organization_cases) < 3:
        blockers.add("organization-contribution-minimum-missing")
    if not extension_cases:
        blockers.add("specialist-extension-contribution-missing")
    if "eval-05" not in department_cases:
        blockers.add("department-contribution-missing")
    if any(item.state == "unsupported" for item in parity):
        blockers.add("runtime-parity-unsupported")
    if any(item.state == "diverged" for item in parity):
        blockers.add("runtime-parity-diverged")
    return (
        tuple(sorted(organization_cases)),
        tuple(sorted(extension_cases)),
        tuple(sorted(department_cases)),
        tuple(sorted(blockers)),
    )


def verify_effectiveness_portfolio(
    matrix: EvaluationMatrix,
    *,
    runs: tuple[LoadedDurableRunEvidence, ...],
    judgments: tuple[LoadedDurableJudgmentEvidence, ...],
    comparisons: tuple[DurableComparisonEvidence, ...],
) -> PortfolioRecord:
    """Verify one exact 28-cell portfolio; never infer missing live evidence."""

    def issue_portfolio(
        matrix_sha256: str,
        *,
        cells: tuple[PortfolioCellResult, ...] = (),
        pairs: tuple[PairDisposition, ...] = (),
        parity: tuple[RuntimeParityRecord, ...] = (),
        attributions: tuple[AttributionRecord, ...] = (),
        organization_cases: tuple[str, ...] = (),
        extension_cases: tuple[str, ...] = (),
        department_cases: tuple[str, ...] = (),
        blockers: tuple[str, ...] = (),
    ) -> PortfolioRecord:
        closed_blockers = set(blockers)
        if not closed_blockers and (
            matrix_sha256 != PACKAGED_MATRIX_SHA256
            or len(cells) != 28
            or len(pairs) != 14
            or len(parity) != 14
            or len(attributions) != 14
            or any(item.terminal_state is not RunState.COMPLETED for item in cells)
            or any(item.state != "compared" for item in pairs)
            or any(item.state != "equivalent" for item in parity)
            or len(organization_cases) < 3
            or not {"eval-01", "eval-02"}.issubset(organization_cases)
            or not extension_cases
            or department_cases != ("eval-05",)
        ):
            closed_blockers.add("portfolio-structure-incomplete")
        final_blockers = tuple(sorted(closed_blockers))
        provisional = PortfolioRecord(
            PORTFOLIO_SCHEMA_VERSION,
            "0" * 64,
            matrix_sha256,
            "rejected" if final_blockers else "accepted",
            cells,
            pairs,
            parity,
            attributions,
            organization_cases,
            extension_cases,
            department_cases,
            final_blockers,
            _PORTFOLIO_AUTHORITY,
        )
        result = PortfolioRecord(
            **{
                **provisional.__dict__,
                "portfolio_sha256": canonical_sha256(
                    _portfolio_identity_document(provisional)
                ),
            }
        )
        _ISSUED_PORTFOLIOS[id(result)] = result
        return result

    def issue_attribution(components: dict[str, object]) -> AttributionRecord:
        provisional = AttributionRecord(
            ATTRIBUTION_SCHEMA_VERSION,
            "0" * 64,
            str(components["case_id"]),
            components["runtime"],
            components["control_variant"],
            components["layered_variant"],
            str(components["comparison_sha256"]),
            str(components["route_contract_sha256"]),
            str(components["specialist"]),
            components["process_evidence_sha256"],
            components["context_evidence_sha256"],
            components["decision_evidence_sha256"],
            components["route_citations_sha256"],
            components["process_event_citations_sha256"],
            _ATTRIBUTION_AUTHORITY,
        )
        result = AttributionRecord(
            **{
                **provisional.__dict__,
                "attribution_sha256": canonical_sha256(
                    _attribution_identity_document(provisional)
                ),
            }
        )
        _ISSUED_ATTRIBUTIONS[id(result)] = result
        return result

    def issue_parity(components: dict[str, object]) -> RuntimeParityRecord:
        provisional = RuntimeParityRecord(
            PARITY_SCHEMA_VERSION,
            "0" * 64,
            str(components["case_id"]),
            int(components["revision"]),
            components["variant"],
            str(components["claude_run_sha256"]),
            str(components["codex_run_sha256"]),
            components["claude_judgment_sha256"],
            components["codex_judgment_sha256"],
            str(components["state"]),
            components["criteria"],
            components["unsupported_runtimes"],
            components["unsupported_reasons"],
            _PARITY_AUTHORITY,
        )
        result = RuntimeParityRecord(
            **{
                **provisional.__dict__,
                "parity_sha256": canonical_sha256(
                    _parity_identity_document(provisional)
                ),
            }
        )
        _ISSUED_PARITY_RECORDS[id(result)] = result
        return result

    matrix_sha256 = matrix.matrix_sha256 if _matrix_is_authentic(matrix) else "0" * 64
    if matrix_sha256 == "0" * 64:
        return issue_portfolio(matrix_sha256, blockers=("matrix-identity-invalid",))
    if any(
        not isinstance(item, LoadedDurableRunEvidence)
        or not item.validate()
        or not verify_run_record_identity(item.record)
        for item in runs
    ):
        return issue_portfolio(
            matrix_sha256, blockers=("durable-run-evidence-invalid",)
        )
    if any(
        not isinstance(item, LoadedDurableJudgmentEvidence) or not item.validate()
        for item in judgments
    ):
        return issue_portfolio(
            matrix_sha256, blockers=("durable-judgment-evidence-invalid",)
        )
    if any(not verify_durable_comparison_evidence(item) for item in comparisons):
        return issue_portfolio(
            matrix_sha256, blockers=("durable-comparison-evidence-invalid",)
        )

    expected = {
        (item.case_id, item.revision, item.variant, item.runtime): item
        for item in matrix.cells
    }
    grouped: dict[
        tuple[str, int, LayerVariant, RuntimeName],
        list[LoadedDurableRunEvidence],
    ] = {}
    for item in runs:
        key = (
            item.record.case_id,
            item.record.revision,
            item.record.variant,
            item.record.runtime,
        )
        grouped.setdefault(key, []).append(item)
    if set(grouped) != set(expected):
        return issue_portfolio(
            matrix_sha256, blockers=("matrix-cell-coverage-incomplete",)
        )

    judgment_by_run: dict[str, LoadedDurableJudgmentEvidence] = {}
    for item in judgments:
        run_sha256 = item.judgment.run_sha256
        if run_sha256 in judgment_by_run:
            return issue_portfolio(
                matrix_sha256, blockers=("durable-judgment-duplicated",)
            )
        judgment_by_run[run_sha256] = item

    cells: list[PortfolioCellResult] = []
    terminal_records: dict[tuple[str, int, LayerVariant, RuntimeName], RunRecord] = {}
    judgment_records: dict[str, CriterionJudgment] = {}
    blockers: set[str] = set()
    for key, plan in expected.items():
        lineage = _validated_lineage(tuple(grouped[key]))
        if lineage is None:
            blockers.add("attempt-lineage-invalid")
            continue
        terminal = lineage[-1]
        terminal_records[key] = terminal
        judgment_sha256: str | None = None
        reasons: tuple[str, ...] = ()
        if terminal.state is RunState.COMPLETED:
            loaded_judgment = judgment_by_run.get(terminal.run_sha256)
            if loaded_judgment is None or not _judgment_is_acceptable(
                loaded_judgment, terminal
            ):
                blockers.add("completed-cell-judgment-invalid")
            else:
                judgment_sha256 = loaded_judgment.judgment.judgment_sha256
                judgment_records[terminal.run_sha256] = loaded_judgment.judgment
        else:
            reasons = _unsupported_reasons(terminal)
            if terminal.run_sha256 in judgment_by_run:
                blockers.add("unsupported-cell-has-judgment")
        cells.append(
            PortfolioCellResult(
                plan.case_id,
                plan.revision,
                plan.variant,
                plan.runtime,
                terminal.run_sha256,
                terminal.state,
                tuple(item.run_sha256 for item in lineage),
                judgment_sha256,
                reasons,
            )
        )
    terminal_run_ids = {item.terminal_run_sha256 for item in cells}
    if set(judgment_by_run) - terminal_run_ids:
        blockers.add("judgment-outside-terminal-matrix")
    if blockers:
        return issue_portfolio(
            matrix_sha256,
            cells=tuple(cells),
            blockers=tuple(blockers),
        )

    comparison_by_pair: dict[tuple[str, RuntimeName], DurableComparisonEvidence] = {}
    comparison_records: dict[str, ComparisonRecord] = {}
    for item in comparisons:
        control = item.control.loaded_run.record
        layered = item.layered.loaded_run.record
        key = (control.case_id, control.runtime)
        if key in comparison_by_pair or layered.case_id != control.case_id:
            blockers.add("comparison-pair-duplicated")
            continue
        comparison_by_pair[key] = item
        comparison_records[item.record.comparison_sha256] = item.record
    attribution_by_comparison: dict[str, AttributionRecord] = {}

    cell_by_key = {(item.case_id, item.variant, item.runtime): item for item in cells}
    plans_by_pair: dict[tuple[str, RuntimeName], list[MatrixCellPlan]] = {}
    for plan in matrix.cells:
        plans_by_pair.setdefault((plan.case_id, plan.runtime), []).append(plan)
    pairs: list[PairDisposition] = []
    used_comparisons: set[tuple[str, RuntimeName]] = set()
    used_attributions: set[str] = set()
    for key in sorted(plans_by_pair, key=lambda item: (item[0], item[1].value)):
        plans = sorted(plans_by_pair[key], key=lambda item: item.role)
        control_plan = next(item for item in plans if item.role == "control")
        layered_plan = next(item for item in plans if item.role == "layered")
        control = cell_by_key[(key[0], control_plan.variant, key[1])]
        layered = cell_by_key[(key[0], layered_plan.variant, key[1])]
        unsupported = tuple(
            item.runtime.value
            for item in (control, layered)
            if item.terminal_state is RunState.UNSUPPORTED
        )
        evidence = comparison_by_pair.get(key)
        if unsupported:
            if evidence is not None:
                blockers.add("unsupported-pair-has-comparison")
            pairs.append(
                PairDisposition(
                    key[0],
                    key[1],
                    control.terminal_run_sha256,
                    layered.terminal_run_sha256,
                    "unsupported",
                    None,
                    None,
                    unsupported,
                )
            )
            continue
        if evidence is None:
            blockers.add("completed-pair-comparison-missing")
            continue
        record = evidence.record
        if (
            record.control_run_sha256 != control.terminal_run_sha256
            or record.layered_run_sha256 != layered.terminal_run_sha256
            or record.control_judgment_sha256 != control.judgment_sha256
            or record.layered_judgment_sha256 != layered.judgment_sha256
            or record.hard_gate_state is not PreflightState.VALID
            or any(
                item.relation is CriterionRelation.REGRESSED
                for item in record.relations
            )
        ):
            blockers.add("completed-pair-evidence-invalid")
            continue
        try:
            attribution = issue_attribution(
                _attribution_components(
                    evidence,
                    control_plan=control_plan,
                    layered_plan=layered_plan,
                )
            )
        except (TypeError, ValueError):
            blockers.add("completed-pair-attribution-invalid")
            continue
        attribution_by_comparison[record.comparison_sha256] = attribution
        used_comparisons.add(key)
        used_attributions.add(record.comparison_sha256)
        pairs.append(
            PairDisposition(
                key[0],
                key[1],
                control.terminal_run_sha256,
                layered.terminal_run_sha256,
                "compared",
                record.comparison_sha256,
                attribution.attribution_sha256,
                (),
            )
        )
    if set(comparison_by_pair) != used_comparisons:
        blockers.add("comparison-outside-completed-matrix")

    parity: list[RuntimeParityRecord] = []
    for case_id in tuple(dict.fromkeys(item.case_id for item in matrix.cells)):
        variants = tuple(
            dict.fromkeys(
                item.variant for item in matrix.cells if item.case_id == case_id
            )
        )
        for variant in variants:
            claude = cell_by_key[(case_id, variant, RuntimeName.CLAUDE)]
            codex = cell_by_key[(case_id, variant, RuntimeName.CODEX)]
            try:
                parity.append(
                    issue_parity(_parity_components(claude, codex, judgment_records))
                )
            except (TypeError, ValueError):
                blockers.add("runtime-parity-evidence-invalid")
    if len(parity) != 14:
        blockers.add("runtime-parity-coverage-incomplete")

    organization, extension, department, minimum_blockers = _phase_minimum_blockers(
        tuple(pairs),
        tuple(parity),
        attribution_by_comparison,
        comparison_records,
    )
    blockers.update(minimum_blockers)
    return issue_portfolio(
        matrix_sha256,
        cells=tuple(cells),
        pairs=tuple(pairs),
        parity=tuple(parity),
        attributions=tuple(
            attribution_by_comparison[key]
            for key in sorted(attribution_by_comparison)
            if key in used_attributions
        ),
        organization_cases=organization,
        extension_cases=extension,
        department_cases=department,
        blockers=tuple(blockers),
    )


__all__ = [
    "AttributionRecord",
    "DurableComparisonEvidence",
    "PairDisposition",
    "ParityCriterion",
    "PortfolioCellResult",
    "PortfolioRecord",
    "RuntimeParityRecord",
    "attribution_record_document",
    "bind_durable_comparison",
    "load_durable_comparison_evidence",
    "portfolio_record_document",
    "runtime_parity_document",
    "verify_attribution_record_identity",
    "verify_durable_comparison_evidence",
    "verify_effectiveness_portfolio",
    "verify_portfolio_record_identity",
    "verify_runtime_parity_identity",
]
