from __future__ import annotations

import base64
import copy
import hashlib
import inspect
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cc.core.evaluation import artifact as artifact_module
from cc.core.evaluation import comparison as comparison_module
from cc.core.evaluation import judgment as judgment_module
from cc.core.evaluation import live_runtime as live_runtime_module
from cc.core.evaluation import matrix as matrix_module
from cc.core.evaluation import portfolio as portfolio_module
from cc.core.evaluation import runner as runner_module
from cc.core.evaluation._authority import _cell_subject
from cc.core.evaluation.artifact import (
    LoadedDurableRunEvidence,
    write_comparison_record,
    write_criterion_judgment,
)
from cc.core.evaluation.comparison import (
    _JUDGMENT_COMPARISON_AUTHORITY,
    pair_control_runs,
)
from cc.core.evaluation.fixtures import load_fixture
from cc.core.evaluation.identity import build_consumption_receipt
from cc.core.evaluation.judgment import (
    CriterionJudgment,
    LoadedDurableJudgmentEvidence,
    compare_criterion_judgments,
)
from cc.core.evaluation.matrix import EvaluationMatrix, build_matrix
from cc.core.evaluation.models import (
    _EVIDENCE_AUTHORITY,
    CriterionAssessment,
    CriterionVerdict,
    GateObservation,
    GateState,
    HardRejectionAssessment,
    LayerVariant,
    PreflightGate,
    RunState,
    RuntimeName,
)
from cc.core.evaluation.portfolio import (
    DurableComparisonEvidence,
    bind_durable_comparison,
    load_durable_comparison_evidence,
    portfolio_record_document,
    verify_effectiveness_portfolio,
    verify_portfolio_record_identity,
)
from cc.core.evaluation.preflight import evaluate_preflight
from cc.core.evaluation.report import (
    blocked_execution_report_document,
    execution_report_document,
    load_durable_execution_evidence,
    persist_completed_execution,
    validate_execution_report_document,
    verify_execution_report_identity,
)
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256
from test_live_runtime import _authority
from test_runner_core import _cell as core_cell

FIXTURES = Path(__file__).parent / "fixtures" / "cases"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _cell_for_plan(plan, fixture_sha256: str):
    cell = core_cell(
        plan.variant,
        case_id=plan.case_id,
        runtime_configuration_sha256=_sha(
            f"runtime-configuration:{plan.case_id}:{plan.runtime.value}"
        ),
        command_policy_sha256=_sha(f"command-policy:{plan.runtime.value}"),
    )
    if plan.runtime is RuntimeName.CODEX:
        runtime = replace(
            cell.runtime_receipt,
            runtime=RuntimeName.CODEX,
            adapter_name="codex-exec",
            adapter_version="v1-test",
        )
        layers = tuple(
            replace(
                item,
                product=(
                    "codex-copilot"
                    if item.product == "claude-copilot"
                    else item.product
                ),
                source_runtime="codex",
                source_adapter_version=(
                    "codex-plugin-v1"
                    if item.product == "claude-copilot"
                    else item.source_adapter_version
                ),
                repository_identifier=item.repository_identifier.replace(
                    "claude-copilot", "codex-copilot"
                ),
            )
            for item in cell.content_receipt.layers
        )
        content = replace(cell.content_receipt, layers=layers)
        consumption = build_consumption_receipt(
            task_id=cell.consumption_receipt.task_id,
            runtime_receipt=runtime,
            content_receipt=content,
            prompt_evidence_sha256=cell.prompt_evidence_sha256,
            journey_evidence_sha256=cell.consumption_receipt.journey_evidence_sha256,
            route_evidence_sha256=cell.consumption_receipt.route_evidence_sha256,
            continuity_evidence_sha256=(
                cell.consumption_receipt.continuity_evidence_sha256
            ),
        )
        cell = replace(
            cell,
            runtime_receipt=runtime,
            content_receipt=content,
            consumption_receipt=consumption,
        )
    return replace(cell, fixture_sha256=fixture_sha256)


def _completed_record(cell, marker: str):
    output_sha256 = hashlib.sha256(_synthetic_output(cell).encode()).hexdigest()
    return runner_module._record(
        cell,
        preflight=_authority(cell).preflight,
        state=RunState.COMPLETED,
        output_sha256=output_sha256,
        controlled_artifact_path=f"runtime-quarantine/{output_sha256}.txt",
        completion_evidence_sha256=_sha(f"completion:{marker}"),
    )


def _synthetic_output(value) -> str:
    runtime = (
        value.runtime_receipt.runtime
        if hasattr(value, "runtime_receipt")
        else value.runtime
    )
    return (
        "Synthetic evidence-bound output for "
        f"{value.case_id}/{value.variant.value}/{runtime.value}."
    )


def _loaded_run(root: Path, record) -> LoadedDurableRunEvidence:
    receipt = artifact_module._write_standalone_evidence_document(
        root,
        "portfolio-test-run-capability",
        {"run_sha256": record.run_sha256},
    )
    capability = receipt._capability
    if record.state is RunState.COMPLETED:
        path, output_capability = live_runtime_module._store_output(
            root,
            _synthetic_output(record),
        )
        assert path == record.controlled_artifact_path
        capability = artifact_module._CompositeArtifactCapability(
            (capability, output_capability)
        )
    loaded = LoadedDurableRunEvidence(
        record,
        capability,
        artifact_module._LOADED_RUN_AUTHORITY,
    )
    artifact_module._ISSUED_LOADED_RUNS[id(loaded)] = loaded
    assert loaded.validate()
    return loaded


def _criterion_judgment(
    record,
    fixture,
    *,
    verdict: CriterionVerdict,
) -> CriterionJudgment:
    rationale_code = {
        CriterionVerdict.DEMONSTRATED: "evidence-supports-verdict",
        CriterionVerdict.PARTIAL: "evidence-partially-supports-verdict",
        CriterionVerdict.ABSENT: "no-supporting-evidence",
        CriterionVerdict.VIOLATED: "evidence-shows-violation",
    }[verdict]
    assessments = tuple(
        CriterionAssessment(
            criterion,
            verdict,
            (_sha(f"evidence:{record.run_sha256}:{criterion}"),),
            (record.content_receipt_sha256,),
            rationale_code,
            _sha(f"rationale:{record.run_sha256}:{criterion}"),
        )
        for criterion in fixture.fixture.required_criteria
    )
    hard_rejections = tuple(
        HardRejectionAssessment(rule, False, ())
        for rule in fixture.fixture.hard_rejection_rules
    )
    identity = judgment_module._criterion_judgment_identity_document(
        schema_version="1.0",
        run_sha256=record.run_sha256,
        assessor="publisher-attested-review",
        assessor_evidence_sha256=_sha(f"assessor:{record.run_sha256}"),
        signer_identity_sha256=_sha("signer"),
        oracle_sha256=fixture.oracle.sha256,
        private_rationale_commitment_sha256=_sha(
            f"private-rationale:{record.run_sha256}"
        ),
        assessments=assessments,
        hard_rejections=hard_rejections,
    )
    seal = object()
    judgment = CriterionJudgment(
        "1.0",
        record.run_sha256,
        "publisher-attested-review",
        _sha(f"assessor:{record.run_sha256}"),
        _sha("signer"),
        fixture.oracle.sha256,
        _sha(f"private-rationale:{record.run_sha256}"),
        assessments,
        hard_rejections,
        (),
        canonical_sha256(identity),
        seal,
        judgment_module._JUDGMENT_AUTHORITY,
    )
    judgment_module._JUDGMENT_SEALS[seal] = judgment.judgment_sha256
    assert judgment_module.verify_criterion_judgment_identity(judgment)
    return judgment


def _loaded_judgment(
    root: Path,
    loaded_run: LoadedDurableRunEvidence,
    fixture,
    *,
    verdict: CriterionVerdict,
) -> LoadedDurableJudgmentEvidence:
    judgment = _criterion_judgment(loaded_run.record, fixture, verdict=verdict)
    receipt = write_criterion_judgment(root, judgment, loaded_run=loaded_run)
    loaded = LoadedDurableJudgmentEvidence(
        judgment,
        loaded_run,
        receipt._capability,
        judgment_module._LOADED_JUDGMENT_AUTHORITY,
    )
    judgment_module._ISSUED_LOADED_JUDGMENTS[id(loaded)] = loaded
    assert loaded.validate()
    return loaded


def _durable_comparison(
    root: Path,
    control: LoadedDurableJudgmentEvidence,
    layered: LoadedDurableJudgmentEvidence,
) -> DurableComparisonEvidence:
    draft = compare_criterion_judgments(
        control.loaded_run.record,
        layered.loaded_run.record,
        control.judgment,
        layered.judgment,
    )
    record = pair_control_runs(
        control.loaded_run.record,
        layered.loaded_run.record,
        relations=draft.relations,
        control_judgment_sha256=draft.control_judgment_sha256,
        layered_judgment_sha256=draft.layered_judgment_sha256,
        _judgment_authority=_JUDGMENT_COMPARISON_AUTHORITY,
    )
    receipt = write_comparison_record(
        root,
        record,
        control_judgment=control,
        layered_judgment=layered,
    )
    return bind_durable_comparison(
        record,
        receipt,
        control=control,
        layered=layered,
    )


@dataclass
class ExactPortfolioEvidence:
    root: Path
    matrix: EvaluationMatrix
    cells: dict[tuple[str, LayerVariant, RuntimeName], object]
    runs: list[LoadedDurableRunEvidence]
    judgments: list[LoadedDurableJudgmentEvidence]
    comparisons: list[DurableComparisonEvidence]


@pytest.fixture
def exact_evidence(tmp_path: Path) -> ExactPortfolioEvidence:
    tmp_path.chmod(0o700)
    matrix, loaded_fixtures = build_matrix(FIXTURES)
    fixture_by_case = {item.fixture.case_id: item for item in loaded_fixtures}
    cells = {}
    runs = []
    judgments = []
    judgment_by_key = {}
    for plan in matrix.cells:
        fixture = fixture_by_case[plan.case_id]
        cell = _cell_for_plan(plan, fixture.fixture_sha256)
        key = (plan.case_id, plan.variant, plan.runtime)
        cells[key] = cell
        record = _completed_record(
            cell,
            ":".join(item.value if hasattr(item, "value") else item for item in key),
        )
        loaded_run = _loaded_run(tmp_path, record)
        loaded_judgment = _loaded_judgment(
            tmp_path,
            loaded_run,
            fixture,
            verdict=(
                CriterionVerdict.PARTIAL
                if plan.role == "control"
                else CriterionVerdict.DEMONSTRATED
            ),
        )
        runs.append(loaded_run)
        judgments.append(loaded_judgment)
        judgment_by_key[key] = loaded_judgment
    comparisons = []
    for case_id in tuple(dict.fromkeys(item.case_id for item in matrix.cells)):
        for runtime in RuntimeName:
            plans = [
                item
                for item in matrix.cells
                if item.case_id == case_id and item.runtime is runtime
            ]
            control_plan = next(item for item in plans if item.role == "control")
            layered_plan = next(item for item in plans if item.role == "layered")
            comparisons.append(
                _durable_comparison(
                    tmp_path,
                    judgment_by_key[(case_id, control_plan.variant, runtime)],
                    judgment_by_key[(case_id, layered_plan.variant, runtime)],
                )
            )
    return ExactPortfolioEvidence(
        tmp_path,
        matrix,
        cells,
        runs,
        judgments,
        comparisons,
    )


def _verify(evidence: ExactPortfolioEvidence, **changes):
    return verify_effectiveness_portfolio(
        changes.get("matrix", evidence.matrix),
        runs=tuple(changes.get("runs", evidence.runs)),
        judgments=tuple(changes.get("judgments", evidence.judgments)),
        comparisons=tuple(changes.get("comparisons", evidence.comparisons)),
    )


def test_real_exact_28_baseline_is_accepted_and_value_suppressing(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    record = _verify(exact_evidence)

    assert record.acceptance_state == "accepted"
    assert not record.blockers
    assert len(record.cells) == 28
    assert len(record.pairs) == 14
    assert len(record.parity) == 14
    assert len(record.attributions) == 14
    assert record.organization_contribution_cases == (
        "eval-01",
        "eval-02",
        "eval-03",
        "eval-04",
        "eval-06",
    )
    assert record.organization_extension_cases == ("eval-03", "eval-04")
    assert record.department_contribution_cases == ("eval-05",)
    assert verify_portfolio_record_identity(record)
    serialized = str(portfolio_record_document(record))
    for prohibited in (
        "output_text",
        "private_rationale",
        "oracle",
        "score",
        "rank",
        "winner",
        "average",
        "percent",
    ):
        assert prohibited not in serialized
    assert not verify_portfolio_record_identity(copy.copy(record))
    assert not verify_portfolio_record_identity(replace(record))
    assert not portfolio_module.verify_attribution_record_identity(
        copy.copy(record.attributions[0])
    )
    assert not portfolio_module.verify_runtime_parity_identity(
        copy.copy(record.parity[0])
    )


def test_missing_and_duplicate_evidence_fail_closed(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    assert _verify(exact_evidence, runs=exact_evidence.runs[:-1]).blockers == (
        "matrix-cell-coverage-incomplete",
    )
    assert (
        "attempt-lineage-invalid"
        in _verify(
            exact_evidence,
            runs=(*exact_evidence.runs, exact_evidence.runs[0]),
        ).blockers
    )
    assert (
        "completed-cell-judgment-invalid"
        in _verify(
            exact_evidence,
            judgments=exact_evidence.judgments[:-1],
        ).blockers
    )
    assert _verify(
        exact_evidence,
        judgments=(*exact_evidence.judgments, exact_evidence.judgments[0]),
    ).blockers == ("durable-judgment-duplicated",)
    assert (
        "completed-pair-comparison-missing"
        in _verify(
            exact_evidence,
            comparisons=exact_evidence.comparisons[:-1],
        ).blockers
    )
    assert (
        "comparison-pair-duplicated"
        in _verify(
            exact_evidence,
            comparisons=(*exact_evidence.comparisons, exact_evidence.comparisons[0]),
        ).blockers
    )


def test_malformed_retry_and_copied_nested_evidence_fail_closed(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    original = exact_evidence.runs[0]
    cell = exact_evidence.cells[
        (original.record.case_id, original.record.variant, original.record.runtime)
    ]
    retry_cell = replace(cell, attempt=2, parent_attempt_sha256=_sha("wrong-parent"))
    retry = _loaded_run(
        exact_evidence.root,
        _completed_record(retry_cell, "malformed-retry"),
    )
    assert (
        "attempt-lineage-invalid"
        in _verify(
            exact_evidence,
            runs=(*exact_evidence.runs, retry),
        ).blockers
    )

    copied_runs = [*exact_evidence.runs]
    copied_runs[0] = copy.copy(copied_runs[0])
    assert _verify(exact_evidence, runs=copied_runs).blockers == (
        "durable-run-evidence-invalid",
    )
    copied_comparisons = [*exact_evidence.comparisons]
    copied_comparisons[0] = copy.copy(copied_comparisons[0])
    assert _verify(exact_evidence, comparisons=copied_comparisons).blockers == (
        "durable-comparison-evidence-invalid",
    )


def _unsupported_record(cell):
    observations = tuple(
        GateObservation(
            gate,
            (
                GateState.UNSUPPORTED
                if gate is PreflightGate.RUNTIME_CAPABILITY
                else GateState.PASS
            ),
            (
                "runtime-capability-unavailable"
                if gate is PreflightGate.RUNTIME_CAPABILITY
                else "verified"
            ),
            "framework",
            "signed-evidence",
            (None if gate is PreflightGate.RUNTIME_CAPABILITY else _EVIDENCE_AUTHORITY),
        )
        for gate in PreflightGate
    )
    preflight = evaluate_preflight(observations, subject_sha256=_cell_subject(cell))
    return runner_module._record(
        cell,
        preflight=preflight,
        state=RunState.UNSUPPORTED,
    )


def test_unsupported_cell_and_diverged_parity_reject_acceptance(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    target = exact_evidence.runs[0]
    key = (
        target.record.case_id,
        target.record.variant,
        target.record.runtime,
    )
    unsupported = _loaded_run(
        exact_evidence.root,
        _unsupported_record(exact_evidence.cells[key]),
    )
    runs = [item for item in exact_evidence.runs if item is not target] + [unsupported]
    judgments = [
        item
        for item in exact_evidence.judgments
        if item.judgment.run_sha256 != target.record.run_sha256
    ]
    comparisons = [
        item
        for item in exact_evidence.comparisons
        if item.record.control_run_sha256 != target.record.run_sha256
        and item.record.layered_run_sha256 != target.record.run_sha256
    ]
    unsupported_result = _verify(
        exact_evidence,
        runs=runs,
        judgments=judgments,
        comparisons=comparisons,
    )
    assert unsupported_result.acceptance_state == "rejected"
    assert "runtime-parity-unsupported" in unsupported_result.blockers

    target_judgment = next(
        item
        for item in exact_evidence.judgments
        if item.loaded_run.record.runtime is RuntimeName.CODEX
        and item.loaded_run.record.variant is LayerVariant.ORGANIZATION
        and item.loaded_run.record.case_id == "eval-03"
    )
    changed = _loaded_judgment(
        exact_evidence.root,
        target_judgment.loaded_run,
        load_fixture(FIXTURES / "eval-03"),
        verdict=CriterionVerdict.PARTIAL,
    )
    changed_judgments = [
        changed if item is target_judgment else item
        for item in exact_evidence.judgments
    ]
    control = next(
        item
        for item in changed_judgments
        if item.loaded_run.record.runtime is RuntimeName.CODEX
        and item.loaded_run.record.variant is LayerVariant.FOUNDATION
        and item.loaded_run.record.case_id == "eval-03"
    )
    changed_comparison = _durable_comparison(
        exact_evidence.root,
        control,
        changed,
    )
    changed_comparisons = [
        (
            changed_comparison
            if item.record.layered_run_sha256
            == target_judgment.loaded_run.record.run_sha256
            else item
        )
        for item in exact_evidence.comparisons
    ]
    diverged = _verify(
        exact_evidence,
        judgments=changed_judgments,
        comparisons=changed_comparisons,
    )
    assert diverged.acceptance_state == "rejected"
    assert "runtime-parity-diverged" in diverged.blockers


def test_regression_and_citation_substitution_cannot_bind_durable_comparison(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    evidence = exact_evidence.comparisons[0]
    fixture = load_fixture(FIXTURES / evidence.control.loaded_run.record.case_id)
    regression_control = _criterion_judgment(
        evidence.control.loaded_run.record,
        fixture,
        verdict=CriterionVerdict.DEMONSTRATED,
    )
    regression_layered = _criterion_judgment(
        evidence.layered.loaded_run.record,
        fixture,
        verdict=CriterionVerdict.PARTIAL,
    )
    with pytest.raises(ValueError, match="regression"):
        compare_criterion_judgments(
            evidence.control.loaded_run.record,
            evidence.layered.loaded_run.record,
            regression_control,
            regression_layered,
        )

    changed_relations = tuple(
        replace(
            item,
            control_evidence_sha256=(_sha("substituted-citation"),),
        )
        for item in evidence.record.relations
    )
    substituted = pair_control_runs(
        evidence.control.loaded_run.record,
        evidence.layered.loaded_run.record,
        relations=changed_relations,
        control_judgment_sha256=evidence.control.judgment.judgment_sha256,
        layered_judgment_sha256=evidence.layered.judgment.judgment_sha256,
        _judgment_authority=_JUDGMENT_COMPARISON_AUTHORITY,
    )
    receipt = write_comparison_record(
        exact_evidence.root,
        substituted,
        control_judgment=evidence.control,
        layered_judgment=evidence.layered,
    )
    with pytest.raises(ValueError, match="exact retained"):
        bind_durable_comparison(
            substituted,
            receipt,
            control=evidence.control,
            layered=evidence.layered,
        )


def test_comparison_reloads_from_durable_bytes_and_exact_judgments(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    original = exact_evidence.comparisons[0]
    comparison_module._ISSUED_COMPARISONS.pop(id(original.record), None)

    reloaded = load_durable_comparison_evidence(
        exact_evidence.root,
        original.receipt.sha256,
        control=original.control,
        layered=original.layered,
    )

    assert reloaded is not None
    assert reloaded.record is not original.record
    assert reloaded.record.comparison_sha256 == original.record.comparison_sha256
    assert reloaded.validate()

    wrong_layered = next(
        item
        for item in exact_evidence.judgments
        if item.loaded_run.record.run_sha256
        != original.layered.loaded_run.record.run_sha256
        and item.loaded_run.record.case_id == original.layered.loaded_run.record.case_id
    )
    assert (
        load_durable_comparison_evidence(
            exact_evidence.root,
            original.receipt.sha256,
            control=original.control,
            layered=wrong_layered,
        )
        is None
    )


def test_comparison_reload_rejects_missing_or_substituted_artifact(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    original = exact_evidence.comparisons[0]
    path = exact_evidence.root / original.receipt.relative_path
    raw = path.read_bytes()
    path.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    path.chmod(0o600)
    assert (
        load_durable_comparison_evidence(
            exact_evidence.root,
            original.receipt.sha256,
            control=original.control,
            layered=original.layered,
        )
        is None
    )
    path.unlink()
    assert (
        load_durable_comparison_evidence(
            exact_evidence.root,
            original.receipt.sha256,
            control=original.control,
            layered=original.layered,
        )
        is None
    )
    path.write_bytes(raw)
    path.chmod(0o600)


@pytest.mark.parametrize("target_name", ("control", "layered"))
def test_comparison_reload_rejects_judgment_name_swap_during_comparison_open(
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    original = exact_evidence.comparisons[0]
    target = getattr(original, target_name)
    path = exact_evidence.root / "criterion-judgment" / target._capability._filename
    raw = path.read_bytes()
    open_linked = artifact_module._open_linked_document

    def swap_after_comparison_open(root_fd, artifact_type, digest):
        result = open_linked(root_fd, artifact_type, digest)
        if artifact_type == "comparison-record":
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(raw)
            replacement.chmod(0o600)
            replacement.replace(path)
        return result

    monkeypatch.setattr(
        artifact_module,
        "_open_linked_document",
        swap_after_comparison_open,
    )

    assert (
        load_durable_comparison_evidence(
            exact_evidence.root,
            original.receipt.sha256,
            control=original.control,
            layered=original.layered,
        )
        is None
    )
    assert not target.validate()


def test_forged_matrix_and_unsafe_issuers_are_rejected_or_absent(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    reversed_cells = tuple(reversed(exact_evidence.matrix.cells))
    forged = EvaluationMatrix(
        matrix_module.MATRIX_SCHEMA_VERSION,
        reversed_cells,
        canonical_sha256(matrix_module._matrix_document(reversed_cells)),
    )
    assert _verify(exact_evidence, matrix=forged).blockers == (
        "matrix-identity-invalid",
    )
    assert not hasattr(portfolio_module, "_issue_portfolio")
    assert not hasattr(portfolio_module, "_issue_attribution")
    assert not hasattr(portfolio_module, "_issue_parity")


def test_completed_execution_persists_and_freshly_reloads_exact_portfolio(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    loaded = persist_completed_execution(
        exact_evidence.root,
        exact_evidence.matrix,
        runs=tuple(exact_evidence.runs),
        judgments=tuple(exact_evidence.judgments),
        comparisons=tuple(exact_evidence.comparisons),
    )
    report = loaded.report
    document = execution_report_document(report)

    assert loaded.validate()
    assert report.state == "completed"
    assert report.acceptance_state == "accepted"
    assert report.initial_cells_started == 28
    assert report.total_attempts_started == 28
    assert not report.blockers
    assert (
        validate_execution_report_document(
            document,
            matrix_sha256=PACKAGED_MATRIX_SHA256,
        )
        == document
    )
    assert not verify_execution_report_identity(copy.copy(report))
    assert not verify_execution_report_identity(replace(report))

    copied_loaded = copy.copy(loaded)
    assert not copied_loaded.validate()
    copied_loaded.close()
    assert loaded.validate()

    reloaded = load_durable_execution_evidence(
        exact_evidence.root,
        report.execution_sha256,
        exact_evidence.matrix,
        runs=tuple(exact_evidence.runs),
        judgments=tuple(exact_evidence.judgments),
        comparisons=tuple(exact_evidence.comparisons),
    )
    assert reloaded is not None
    assert reloaded.report is not report
    assert reloaded.report.execution_sha256 == report.execution_sha256
    assert reloaded.validate()

    loaded.close()
    loaded.close()
    assert not loaded.validate()
    assert reloaded.validate()
    reloaded.close()


def test_private_execution_bundle_embeds_the_complete_bounded_evidence_set(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    loaded = persist_completed_execution(
        exact_evidence.root,
        exact_evidence.matrix,
        runs=tuple(exact_evidence.runs),
        judgments=tuple(exact_evidence.judgments),
        comparisons=tuple(exact_evidence.comparisons),
    )
    path = (
        exact_evidence.root
        / "execution-bundle"
        / f"{loaded.bundle_artifact_sha256}.json"
    )
    raw = path.read_bytes()
    document = json.loads(raw)

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert hashlib.sha256(raw).hexdigest() == loaded.bundle_artifact_sha256
    assert document["schema_version"] == "1.0"
    assert document["privacy_class"] == "private-evaluation-evidence"
    assert document["matrix"]["matrix_sha256"] == PACKAGED_MATRIX_SHA256
    assert len(document["run_records"]) == len(exact_evidence.runs)
    assert len(document["criterion_judgments"]) == len(exact_evidence.judgments)
    assert len(document["comparisons"]) == len(exact_evidence.comparisons)
    retained = document["retained_artifacts"]
    assert sum(item["artifact_type"] == "runtime-quarantine" for item in retained) == 28
    for item in retained:
        content = base64.b64decode(item["content"], validate=True)
        assert len(content) == item["size_bytes"]
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
    assert "private_rationale_text" not in raw.decode("utf-8")
    loaded.close()


def _unsupported_portfolio_inputs(
    exact_evidence: ExactPortfolioEvidence,
) -> tuple[
    tuple[LoadedDurableRunEvidence, ...],
    tuple[LoadedDurableJudgmentEvidence, ...],
    tuple[DurableComparisonEvidence, ...],
]:
    target = exact_evidence.runs[0]
    key = (
        target.record.case_id,
        target.record.variant,
        target.record.runtime,
    )
    unsupported = _loaded_run(
        exact_evidence.root,
        _unsupported_record(exact_evidence.cells[key]),
    )
    return (
        tuple(
            item if item is not target else unsupported for item in exact_evidence.runs
        ),
        tuple(
            item
            for item in exact_evidence.judgments
            if item.judgment.run_sha256 != target.record.run_sha256
        ),
        tuple(
            item
            for item in exact_evidence.comparisons
            if item.record.control_run_sha256 != target.record.run_sha256
            and item.record.layered_run_sha256 != target.record.run_sha256
        ),
    )


def test_completed_execution_preserves_rejected_portfolio_and_closed_blockers(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    runs, judgments, comparisons = _unsupported_portfolio_inputs(exact_evidence)

    loaded = persist_completed_execution(
        exact_evidence.root,
        exact_evidence.matrix,
        runs=runs,
        judgments=judgments,
        comparisons=comparisons,
    )
    document = execution_report_document(loaded.report)

    assert loaded.report.state == "completed"
    assert loaded.report.acceptance_state == "rejected"
    assert loaded.report.portfolio_artifact_sha256
    assert "runtime-parity-unsupported" in loaded.report.blockers
    assert (
        validate_execution_report_document(
            document,
            matrix_sha256=PACKAGED_MATRIX_SHA256,
        )
        == document
    )
    loaded.close()


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"state": "blocked"}, "failed validation"),
        ({"acceptance_state": "not-evaluated"}, "failed validation"),
        ({"acceptance_state": "accepted"}, "failed validation"),
        ({"blockers": []}, "failed validation"),
        ({"portfolio_sha256": None}, "failed validation"),
        ({"portfolio_artifact_sha256": None}, "failed validation"),
    ],
)
def test_execution_report_rejects_self_consistent_contradictions(
    exact_evidence: ExactPortfolioEvidence,
    changes: dict[str, object],
    error: str,
) -> None:
    runs, judgments, comparisons = _unsupported_portfolio_inputs(exact_evidence)
    loaded = persist_completed_execution(
        exact_evidence.root,
        exact_evidence.matrix,
        runs=runs,
        judgments=judgments,
        comparisons=comparisons,
    )
    document = execution_report_document(loaded.report)
    document.update(changes)
    identity = {
        key: value for key, value in document.items() if key != "execution_sha256"
    }
    document["execution_sha256"] = canonical_sha256(identity)

    with pytest.raises(ValueError, match=error):
        validate_execution_report_document(
            document,
            matrix_sha256=PACKAGED_MATRIX_SHA256,
        )
    loaded.close()


def test_blocked_execution_is_not_an_effectiveness_verdict() -> None:
    document = blocked_execution_report_document(
        PACKAGED_MATRIX_SHA256,
        "canonical-content-unavailable",
    )

    assert document["state"] == "blocked"
    assert document["acceptance_state"] == "not-evaluated"
    assert document["portfolio_sha256"] is None
    assert document["portfolio_artifact_sha256"] is None
    assert (
        validate_execution_report_document(
            document,
            matrix_sha256=PACKAGED_MATRIX_SHA256,
        )
        == document
    )


@pytest.mark.parametrize("artifact_type", ("portfolio-record", "execution-report"))
def test_durable_bundle_remains_top_level_authority_after_audit_artifact_replacement(
    exact_evidence: ExactPortfolioEvidence,
    artifact_type: str,
) -> None:
    loaded = persist_completed_execution(
        exact_evidence.root,
        exact_evidence.matrix,
        runs=tuple(exact_evidence.runs),
        judgments=tuple(exact_evidence.judgments),
        comparisons=tuple(exact_evidence.comparisons),
    )
    digest = (
        loaded.report.portfolio_artifact_sha256
        if artifact_type == "portfolio-record"
        else loaded.report.execution_sha256
    )
    path = exact_evidence.root / artifact_type / f"{digest}.json"
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(path)

    assert loaded.validate()
    assert (
        load_durable_execution_evidence(
            exact_evidence.root,
            loaded.report.execution_sha256,
            exact_evidence.matrix,
            runs=tuple(exact_evidence.runs),
            judgments=tuple(exact_evidence.judgments),
            comparisons=tuple(exact_evidence.comparisons),
        )
        is not None
    )
    loaded.close()


@pytest.mark.parametrize("replace_ancestor", (False, True))
def test_durable_execution_rejects_artifact_root_or_ancestor_replacement(
    exact_evidence: ExactPortfolioEvidence,
    replace_ancestor: bool,
) -> None:
    container = exact_evidence.root / "execution-container"
    container.mkdir(mode=0o700)
    report_root = container / "reports"
    report_root.mkdir(mode=0o700)
    loaded = persist_completed_execution(
        report_root,
        exact_evidence.matrix,
        runs=tuple(exact_evidence.runs),
        judgments=tuple(exact_evidence.judgments),
        comparisons=tuple(exact_evidence.comparisons),
    )
    target = container if replace_ancestor else report_root
    held = target.with_name(target.name + "-held")
    target.rename(held)
    target.mkdir(mode=0o700)
    if replace_ancestor:
        (target / "reports").mkdir(mode=0o700)

    try:
        assert not loaded.validate()
    finally:
        loaded.close()
        if replace_ancestor:
            (target / "reports").rmdir()
        target.rmdir()
        held.rename(target)


@pytest.mark.parametrize("mutate_in_place", (False, True))
def test_durable_execution_bundle_rejects_mutation_during_final_validation(
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
    mutate_in_place: bool,
) -> None:
    loaded = persist_completed_execution(
        exact_evidence.root,
        exact_evidence.matrix,
        runs=tuple(exact_evidence.runs),
        judgments=tuple(exact_evidence.judgments),
        comparisons=tuple(exact_evidence.comparisons),
    )
    path = (
        exact_evidence.root
        / "execution-bundle"
        / f"{loaded.bundle_artifact_sha256}.json"
    )
    original_validate = loaded._bundle_capability.validate
    swapped = False

    def swap_then_validate() -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            if mutate_in_place:
                content = path.read_bytes()
                path.write_bytes(content[:1] + b"!" + content[2:])
                path.chmod(0o600)
            else:
                replacement = path.with_suffix(".replacement")
                replacement.write_bytes(path.read_bytes())
                replacement.chmod(0o600)
                replacement.replace(path)
        original_validate()

    monkeypatch.setattr(loaded._bundle_capability, "validate", swap_then_validate)

    assert not loaded.validate()
    assert swapped
    loaded.close()


def test_durable_execution_bundle_survives_later_audit_input_replacement(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    runs, judgments, comparisons = _unsupported_portfolio_inputs(exact_evidence)
    loaded = persist_completed_execution(
        exact_evidence.root,
        exact_evidence.matrix,
        runs=runs,
        judgments=judgments,
        comparisons=comparisons,
    )
    unsupported = next(
        item for item in runs if item.record.state is RunState.UNSUPPORTED
    )
    capability = unsupported._capability
    path = exact_evidence.root / capability._artifact_type / capability._filename
    replacement = path.with_suffix(".replacement")
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(path)

    assert loaded.validate()
    assert not unsupported.validate()
    loaded.close()


def test_copied_judgment_and_comparison_close_cannot_revoke_authentic_evidence(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    judgment = exact_evidence.judgments[0]
    comparison = exact_evidence.comparisons[0]

    copy.copy(judgment).close()
    copy.copy(comparison).close()
    assert judgment.validate()
    assert comparison.validate()

    comparison.close()
    comparison.close()
    judgment.close()
    judgment.close()
    assert not comparison.validate()
    assert not judgment.validate()
    assert (
        "attributions"
        not in inspect.signature(verify_effectiveness_portfolio).parameters
    )
