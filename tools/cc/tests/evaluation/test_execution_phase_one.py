from __future__ import annotations

# Imported pytest fixture names are intentionally reused as test parameters.
# ruff: noqa: F401, F811
from types import SimpleNamespace

import cc.core.evaluation.artifact as artifact_module
import cc.core.evaluation.execution as execution
import pytest
from cc.core.evaluation.execution import (
    EvaluationExecutionUnavailable,
    _execute_phase_one_matrix,
    _persist_phase_one_handoff,
)
from cc.core.evaluation.matrix import build_matrix
from cc.core.evaluation.models import RunState, RuntimeName
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import packaged_cases_root
from test_live_portfolio import (
    FIXTURES,
    ExactPortfolioEvidence,
    _loaded_run,
    _unsupported_record,
    exact_evidence,
)


def _phase_one_runs(evidence: ExactPortfolioEvidence):
    result = []
    replacements = []
    for item in evidence.runs:
        if item.record.runtime is RuntimeName.CLAUDE:
            result.append(item)
            continue
        key = (
            item.record.case_id,
            item.record.variant,
            item.record.runtime,
        )
        replacement = _loaded_run(
            evidence.root,
            _unsupported_record(evidence.cells[key]),
        )
        result.append(replacement)
        replacements.append(replacement)
    return tuple(result), replacements


def test_phase_one_handoff_persists_exact_14_completed_14_unsupported_bundle(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    _matrix, fixtures = build_matrix(FIXTURES)
    runs, replacements = _phase_one_runs(exact_evidence)
    try:
        document = _persist_phase_one_handoff(
            exact_evidence.matrix,
            fixtures,
            runs,
            exact_evidence.root,
            live_calls_started=14,
        )
    finally:
        for item in replacements:
            item.close()

    identity = {
        key: value for key, value in document.items() if key != "execution_sha256"
    }
    assert document["schema_version"] == "task285-phase-one-execution-v1"
    assert document["state"] == "awaiting-assessment"
    assert document["acceptance_state"] == "not-evaluated"
    assert document["initial_cells_started"] == 28
    assert document["total_attempts_started"] == 28
    assert document["live_calls_started"] == 14
    assert document["completed_cells"] == 14
    assert document["unsupported_cells"] == 14
    assert document["blockers"] == []
    assert document["terminal_run_sha256"] == [item.record.run_sha256 for item in runs]
    assert document["execution_sha256"] == canonical_sha256(identity)
    assert (
        exact_evidence.root
        / "assessment-manifest"
        / f"{document['assessment_manifest_sha256']}.json"
    ).is_file()
    assert (
        exact_evidence.root
        / "assessment-bundle"
        / f"{document['assessment_bundle_sha256']}.json"
    ).is_file()
    assert "output" not in " ".join(document)


def test_phase_one_coordinator_runs_exact_claude_loop_and_zero_call_codex(
    tmp_path,
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix, fixtures = build_matrix(FIXTURES)
    cells = exact_evidence.cells
    prepared_plans = []
    executed_plans = []
    codex_calls = []
    loaded = []
    captured = {}

    class Loaded:
        def __init__(self, cell, state, run_sha256):
            self.record = SimpleNamespace(
                case_id=cell.case_id,
                variant=cell.variant,
                runtime=cell.runtime_receipt.runtime,
                state=state,
                run_sha256=run_sha256,
            )
            self.closed = False
            loaded.append(self)

        def validate(self):
            return not self.closed

        def close(self):
            self.closed = True

    def prepare(plan, fixture, artifact_root, ledger):
        prepared_plans.append(plan)
        cell = cells[(plan.case_id, plan.variant, plan.runtime)]
        return SimpleNamespace(
            cell=cell,
            journey_run_id=f"journey-{len(prepared_plans)}",
            ledger=ledger,
            fixture=fixture,
            artifact_root=artifact_root,
        )

    def execute_prepared(prepared, fixture, artifact_root):
        assert fixture is prepared.fixture
        assert artifact_root == prepared.artifact_root
        executed_plans.append(prepared.cell)
        run_sha256 = canonical_sha256(
            {
                "case_id": prepared.cell.case_id,
                "variant": prepared.cell.variant.value,
                "runtime": "claude",
            }
        )
        return {
            "state": "completed",
            "live_calls_started": 1,
            "run_sha256": run_sha256,
        }

    def load_completed(_root, run_sha256, **kwargs):
        return Loaded(kwargs["cell"], RunState.COMPLETED, run_sha256)

    codex_plans = tuple(
        item for item in matrix.cells if item.runtime is RuntimeName.CODEX
    )
    codex_sha256s = [
        canonical_sha256(
            {
                "case_id": plan.case_id,
                "variant": plan.variant.value,
                "runtime": "codex",
            }
        )
        for plan in codex_plans
    ]

    def execute_codex(*args):
        codex_calls.append(args)
        return {
            "state": "unsupported",
            "live_calls_started": 0,
            "run_sha256s": codex_sha256s,
        }

    def issue_codex(plan, _fixture):
        return cells[(plan.case_id, plan.variant, plan.runtime)]

    def load_unsupported(_root, run_sha256, **kwargs):
        return Loaded(kwargs["cell"], RunState.UNSUPPORTED, run_sha256)

    def persist(matrix_value, fixtures_value, runs, root, *, live_calls_started):
        captured.update(
            matrix=matrix_value,
            fixtures=fixtures_value,
            runs=runs,
            root=root,
            live_calls_started=live_calls_started,
        )
        return {"state": "awaiting-assessment", "live_calls_started": 14}

    monkeypatch.setattr(execution, "_prepare_claude_cell", prepare)
    monkeypatch.setattr(execution, "_execute_prepared_claude_cell", execute_prepared)
    monkeypatch.setattr(execution, "_execute_codex_zero_call_matrix", execute_codex)
    monkeypatch.setattr(execution, "_issue_codex_zero_call_cell", issue_codex)
    monkeypatch.setattr(artifact_module, "load_durable_completed_run", load_completed)
    monkeypatch.setattr(
        artifact_module,
        "load_durable_unsupported_run",
        load_unsupported,
    )
    monkeypatch.setattr(execution, "_persist_phase_one_handoff", persist)
    artifact_root = tmp_path / "artifacts"

    document = _execute_phase_one_matrix(
        matrix,
        fixtures,
        artifact_root,
        ledger_factory=lambda plan: SimpleNamespace(plan=plan),
    )

    assert document == {"state": "awaiting-assessment", "live_calls_started": 14}
    assert prepared_plans == [
        item for item in matrix.cells if item.runtime is RuntimeName.CLAUDE
    ]
    assert len(executed_plans) == 14
    assert len(codex_calls) == 1
    assert captured["matrix"] is matrix
    assert captured["fixtures"] == fixtures
    assert captured["root"] == artifact_root
    assert captured["live_calls_started"] == 14
    assert [
        (item.record.case_id, item.record.variant, item.record.runtime)
        for item in captured["runs"]
    ] == [(item.case_id, item.variant, item.runtime) for item in matrix.cells]
    assert len(loaded) == 28
    assert all(item.closed for item in loaded)


def test_public_issuer_still_blocks_before_phase_one_coordinator(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def coordinator(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("phase one must remain unreachable")

    monkeypatch.setattr(execution, "_execute_phase_one_matrix", coordinator)
    monkeypatch.setattr(
        execution,
        "_require_canonical_readiness",
        lambda _matrix, _models: (_ for _ in ()).throw(
            EvaluationExecutionUnavailable(
                "canonical-content-materialized-lock-mismatch"
            )
        ),
    )

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="canonical-content-materialized-lock-mismatch",
    ):
        execution.issue_matrix_execution(
            fixtures_root=packaged_cases_root(),
            artifact_root=tmp_path / "artifacts",
            runtime_models={
                "claude": execution.CLAUDE_EVALUATION_MODEL,
                "codex": execution.CODEX_EVALUATION_MODEL,
            },
        )

    assert not called
    assert not (tmp_path / "artifacts").exists()


def test_phase_one_claude_failure_closes_prepared_and_never_starts_codex(
    tmp_path,
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix, fixtures = build_matrix(FIXTURES)
    closed = []
    codex_called = False

    class Prepared:
        def __init__(self, plan, fixture, ledger):
            self.cell = exact_evidence.cells[(plan.case_id, plan.variant, plan.runtime)]
            self.journey_run_id = "journey-failure"
            self.ledger = ledger
            self.fixture = fixture

        def close(self):
            closed.append(self)

    def prepare(plan, fixture, _root, ledger):
        return Prepared(plan, fixture, ledger)

    def execute_prepared(_prepared, _fixture, _root):
        raise EvaluationExecutionUnavailable("claude-attempt-technical-error")

    def execute_codex(*_args):
        nonlocal codex_called
        codex_called = True
        raise AssertionError("Codex disposition must wait for Claude completion")

    monkeypatch.setattr(execution, "_prepare_claude_cell", prepare)
    monkeypatch.setattr(execution, "_execute_prepared_claude_cell", execute_prepared)
    monkeypatch.setattr(execution, "_execute_codex_zero_call_matrix", execute_codex)

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="claude-attempt-technical-error",
    ):
        _execute_phase_one_matrix(
            matrix,
            fixtures,
            tmp_path / "artifacts",
            ledger_factory=lambda plan: SimpleNamespace(plan=plan),
        )

    assert len(closed) == 1
    assert not codex_called
    assert not (tmp_path / "artifacts" / "assessment-manifest").exists()
