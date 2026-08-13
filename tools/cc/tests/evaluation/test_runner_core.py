from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from cc.core.evaluation._authority import _test_authority, _test_completed_output
from cc.core.evaluation.artifact import (
    _write_artifact,
    write_comparison_record,
    write_run_record,
)
from cc.core.evaluation.comparison import pair_control_runs
from cc.core.evaluation.identity import (
    build_consumption_receipt,
    consumption_receipt_document,
    content_receipt_identity,
    runtime_receipt_document,
    runtime_receipt_identity,
)
from cc.core.evaluation.models import (
    ContentReceipt,
    CriterionComparison,
    CriterionRelation,
    EvaluationCell,
    GateObservation,
    GateState,
    LayerContentReceipt,
    LayerVariant,
    PreflightGate,
    PreflightState,
    RunState,
    RuntimeName,
    RuntimeOutput,
    RuntimeReceipt,
)
from cc.core.evaluation.preflight import evaluate_preflight
from cc.core.evaluation.runner import EvaluationRunner, RuntimeAdapterFailure


def _sha(character: str) -> str:
    return character * 64


def _runtime(*, configuration_marker: str = "base") -> RuntimeReceipt:
    return RuntimeReceipt(
        runtime=RuntimeName.CLAUDE,
        executable_sha256=_sha("1"),
        runtime_version="2.1.0",
        model_version=None,
        tool_availability=("agent", "knowledge", "tc"),
        adapter_name="journey-adapter",
        adapter_version=f"v2.1-{configuration_marker}",
        capability_flags=("continuity", "optional-transport"),
    )


def _layer(tier: str, index: int) -> LayerContentReceipt:
    characters = "23456789abcdef"
    marker = characters[index]
    return LayerContentReceipt(
        product="codex-copilot",
        tier=tier,
        repository_identifier=f"synthetic/{tier}",
        immutable_ref=f"refs/tags/synthetic-{tier}-v1",
        tree_sha256=_sha(marker),
        signer_identity="SHA256:SYNTHETICFOUNDATION",
        policy_sha256=_sha(characters[index + 1]),
        manifest_sha256=_sha(characters[index + 2]),
        lock_sha256=_sha(characters[index + 3]),
        contribution_ids=(f"synthetic-{tier}-contribution",),
        content_digests=(_sha(characters[index + 4]),),
        resolution_action="accumulated",
        materialized_destinations=(f"knowledge/{tier}.md",),
    )


def _content(variant: LayerVariant) -> ContentReceipt:
    tiers = {
        LayerVariant.FOUNDATION: ("foundation",),
        LayerVariant.ORGANIZATION: ("foundation", "organization"),
        LayerVariant.DEPARTMENT: ("foundation", "organization", "department"),
        LayerVariant.PERSONAL: (
            "foundation",
            "organization",
            "department",
            "personal",
        ),
    }[variant]
    return ContentReceipt(
        variant=variant,
        entitlement_receipt_sha256=_sha("a"),
        layers=tuple(_layer(tier, index) for index, tier in enumerate(tiers)),
        composed_content_sha256=_sha("b" if len(tiers) == 1 else "c"),
        materialization_sha256=_sha("d" if len(tiers) == 1 else "e"),
    )


def _observations() -> tuple[GateObservation, ...]:
    return tuple(
        GateObservation(
            gate,
            GateState.PASS,
            "verified",
            "framework",
            "signed-evidence",
            __import__(
                "cc.core.evaluation.models", fromlist=["_EVIDENCE_AUTHORITY"]
            )._EVIDENCE_AUTHORITY,
        )
        for gate in PreflightGate
    )


def _cell(
    variant: LayerVariant = LayerVariant.FOUNDATION,
    *,
    runtime_configuration_sha256: str | None = None,
    case_id: str = "eval-01",
    attempt: int = 1,
    parent_attempt_sha256: str | None = None,
) -> EvaluationCell:
    runtime = _runtime()
    content = _content(variant)
    prompt = _sha("f")
    consumption = build_consumption_receipt(
        task_id=296,
        runtime_receipt=runtime,
        content_receipt=content,
        prompt_evidence_sha256=prompt,
        journey_evidence_sha256=_sha("0"),
        route_evidence_sha256=_sha("1"),
        continuity_evidence_sha256=_sha("2"),
    )
    return EvaluationCell(
        case_id=case_id,
        revision=1,
        fixture_sha256=_sha("3"),
        prompt_evidence_sha256=prompt,
        variant=variant,
        runtime_receipt=runtime,
        content_receipt=content,
        consumption_receipt=consumption,
        attempt=attempt,
        attempt_policy_sha256=_sha("4"),
        runtime_configuration_sha256=runtime_configuration_sha256 or _sha("5"),
        tool_configuration_sha256=_sha("6"),
        parent_attempt_sha256=parent_attempt_sha256,
    )


class _Runtime:
    def __init__(
        self,
        output: RuntimeOutput | Exception | None = None,
        *,
        complete: bool = True,
    ) -> None:
        self.calls = 0
        self.complete = complete
        self.output = output or RuntimeOutput(
            output_text="Synthetic result with cited evidence.",
            controlled_artifact_path="outputs/eval-01.txt",
            output_location_class="shared-output",
        )

    def execute(self, cell: EvaluationCell) -> RuntimeOutput | object:
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        return (
            _test_completed_output(cell, self.output, evidence_sha256=_sha("7"))
            if self.complete
            else self.output
        )


class _RunnerHarness:
    def __init__(
        self,
        runtime: _Runtime,
        observations: tuple[GateObservation, ...] | None,
    ) -> None:
        self.runtime = runtime
        self.observations = observations or _observations()
        self.runner: EvaluationRunner | None = None

    def run(self, cell: EvaluationCell):
        if self.runner is None:
            facts = {
                item.gate: (item.state, item.reason, item.actor, item.prerequisite)
                for item in self.observations
            }
            self.runner = EvaluationRunner(
                self.runtime,
                _test_authority(cell, facts),
            )
        return self.runner.run(cell)

    @property
    def records(self):
        return self.runner.records if self.runner else ()


def _runner(
    runtime: _Runtime,
    *,
    observations: tuple[GateObservation, ...] | None = None,
    complete: bool = True,
) -> _RunnerHarness:
    runtime.complete = complete
    return _RunnerHarness(runtime, observations)


def test_receipt_identities_are_canonical_and_value_suppressing() -> None:
    runtime = _runtime()
    content = _content(LayerVariant.ORGANIZATION)
    receipt = build_consumption_receipt(
        task_id=296,
        runtime_receipt=runtime,
        content_receipt=content,
        prompt_evidence_sha256=_sha("1"),
        journey_evidence_sha256=_sha("2"),
        route_evidence_sha256=_sha("3"),
        continuity_evidence_sha256=_sha("4"),
    )

    assert runtime_receipt_identity(runtime) == runtime_receipt_identity(runtime)
    assert receipt.runtime_receipt_sha256 == runtime_receipt_identity(runtime)
    assert receipt.content_receipt_sha256 == content_receipt_identity(content)
    persisted = json.dumps(
        {
            "runtime": runtime_receipt_document(runtime),
            "consumption": consumption_receipt_document(receipt),
        }
    )
    assert "/Users/" not in persisted
    assert "secret" not in persisted.casefold()


def test_preflight_requires_exact_complete_gate_packet() -> None:
    missing = _observations()[:-1]
    assert evaluate_preflight(missing).state is PreflightState.INVALID
    duplicated = _observations() + (_observations()[0],)
    result = evaluate_preflight(duplicated)
    assert result.state is PreflightState.INVALID
    assert any(item.reason == "duplicate-evidence" for item in result.observations)


def test_only_runtime_capability_can_be_unsupported() -> None:
    runtime_unsupported = tuple(
        replace(item, state=GateState.UNSUPPORTED, reason="capability-absent")
        if item.gate is PreflightGate.RUNTIME_CAPABILITY
        else item
        for item in _observations()
    )
    assert evaluate_preflight(runtime_unsupported).state is PreflightState.UNSUPPORTED

    journey_unsupported = tuple(
        replace(item, state=GateState.UNSUPPORTED, reason="transport-unavailable")
        if item.gate is PreflightGate.JOURNEY_EVIDENCE
        else item
        for item in _observations()
    )
    assert evaluate_preflight(journey_unsupported).state is PreflightState.INVALID


def test_runner_never_calls_adapter_when_gate_is_not_valid() -> None:
    missing = _observations()[:-1]
    runtime = _Runtime()
    record = _runner(runtime, observations=missing).run(_cell())
    assert record.state is RunState.INVALID
    assert runtime.calls == 0

    unsupported = tuple(
        replace(item, state=GateState.UNSUPPORTED, reason="capability-absent")
        if item.gate is PreflightGate.RUNTIME_CAPABILITY
        else item
        for item in _observations()
    )
    record = _runner(runtime, observations=unsupported).run(_cell())
    assert record.state is RunState.UNSUPPORTED
    assert runtime.calls == 0


def test_runner_derives_receipt_binding_gate_and_fails_closed() -> None:
    cell = _cell()
    tampered = replace(
        cell.consumption_receipt,
        invocation_envelope_sha256=_sha("9"),
    )
    runtime = _Runtime()
    record = _runner(runtime).run(replace(cell, consumption_receipt=tampered))
    assert record.state is RunState.INVALID
    assert runtime.calls == 0
    assert any(
        item.reason == "receipt-binding-mismatch"
        for item in record.preflight.observations
    )


def test_runner_executes_one_injected_call_and_records_only_digests() -> None:
    runtime = _Runtime()
    record = _runner(runtime).run(_cell())
    assert record.state is RunState.COMPLETED
    assert runtime.calls == 1
    assert record.output_sha256 is not None
    assert record.controlled_artifact_path == "outputs/eval-01.txt"
    assert "Synthetic result" not in json.dumps(record.__dict__, default=str)


def test_runner_sanitizes_errors_and_rejects_unsafe_shared_output() -> None:
    failure = _Runtime(RuntimeAdapterFailure("runtime-timeout"))
    record = _runner(failure).run(_cell())
    assert record.state is RunState.TECHNICAL_ERROR
    assert record.technical_error_reason == "runtime-timeout"

    generic = _Runtime(RuntimeError("password=do-not-persist-this"))
    record = _runner(generic).run(_cell())
    assert record.technical_error_reason == "runtime-adapter-failure"
    assert "password" not in json.dumps(record.__dict__, default=str)

    unsafe = _Runtime(
        RuntimeOutput(
            output_text="PRIVATE_PERSONAL must not enter a shared artifact",
            controlled_artifact_path="outputs/eval-01.txt",
            output_location_class="shared-output",
        )
    )
    record = _runner(unsafe).run(_cell())
    assert record.state is RunState.INVALID
    assert record.output_sha256 is None


def test_control_pairing_uses_exact_comparability_without_a_score() -> None:
    control = _runner(_Runtime()).run(_cell(LayerVariant.FOUNDATION))
    layered = _runner(_Runtime()).run(_cell(LayerVariant.ORGANIZATION))
    relation = CriterionComparison(
        criterion="evidence-discipline",
        relation=CriterionRelation.IMPROVED,
        control_evidence_sha256=(_sha("1"),),
        layered_evidence_sha256=(_sha("2"),),
    )
    comparison = pair_control_runs(control, layered, relations=(relation,))
    assert comparison.hard_gate_state is PreflightState.VALID
    assert comparison.relations == (relation,)
    assert "score" not in json.dumps(comparison.__dict__, default=str).casefold()

    changed = _runner(_Runtime()).run(
        _cell(LayerVariant.ORGANIZATION, runtime_configuration_sha256=_sha("8"))
    )
    with pytest.raises(ValueError, match="not comparable"):
        pair_control_runs(control, changed)


def test_content_addressed_artifacts_are_canonical_and_idempotent(
    tmp_path: Path,
) -> None:
    control = _runner(_Runtime()).run(_cell(LayerVariant.FOUNDATION))
    layered = _runner(_Runtime()).run(_cell(LayerVariant.ORGANIZATION))
    comparison = pair_control_runs(control, layered)

    run_receipt = write_run_record(tmp_path, control)
    repeated = write_run_record(tmp_path, control)
    comparison_receipt = write_comparison_record(tmp_path, comparison)
    assert run_receipt == repeated
    assert (tmp_path / run_receipt.relative_path).is_file()
    assert (tmp_path / comparison_receipt.relative_path).is_file()
    assert run_receipt.sha256 in run_receipt.relative_path
    assert not tuple(tmp_path.rglob("*.tmp"))


def test_artifact_writer_rejects_aggregate_fields_and_symlink_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Aggregate"):
        _write_artifact(
            tmp_path,
            artifact_type="comparison-record",
            payload={"criteria": [{"criterion_score": 10}]},
        )

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        _write_artifact(
            linked,
            artifact_type="run-record",
            payload={"schema_version": "1.0"},
        )


def test_callers_cannot_mint_passing_gate_or_valid_preflight() -> None:
    with pytest.raises(ValueError, match="verifier-issued"):
        GateObservation(
            PreflightGate.FIXTURE_CONTRACT,
            GateState.PASS,
            "verified",
            "framework",
            "signed-evidence",
        )
    with pytest.raises(ValueError, match="verifier-issued"):
        from cc.core.evaluation.models import PreflightResult

        PreflightResult(
            PreflightState.VALID,
            (),
            _sha("1"),
            _sha("2"),
        )


def test_receipt_fields_reject_mutable_refs_bad_signers_and_disclosure_paths() -> None:
    layer = _layer("foundation", 0)
    with pytest.raises(ValueError, match="signed tag"):
        replace(layer, immutable_ref="refs/heads/main")
    with pytest.raises(ValueError, match="signer fingerprint"):
        replace(layer, signer_identity="self-asserted")
    with pytest.raises(ValueError, match="exact relative path"):
        replace(layer, materialized_destinations=("Users/pabs/result.md",))
    with pytest.raises(ValueError, match="exact relative path"):
        RuntimeOutput(
            "safe",
            "outputs/token-value.txt",
            "shared-output",
        )


def test_dispatch_is_not_completion_without_correlated_completion_proof() -> None:
    runtime = _Runtime()
    record = _runner(runtime, complete=False).run(_cell())
    assert record.state is RunState.DISPATCH_AUTHORIZED
    assert record.completion_evidence_sha256 is None
    assert runtime.calls == 1
    with pytest.raises(ValueError, match="completed"):
        pair_control_runs(record, record)


def test_route_and_continuity_bind_preflight_and_comparability() -> None:
    original_cell = _cell()
    changed_receipt = replace(
        original_cell.consumption_receipt,
        route_evidence_sha256=_sha("8"),
        continuity_evidence_sha256=_sha("9"),
    )
    original = _runner(_Runtime()).run(original_cell)
    changed = _runner(_Runtime()).run(
        replace(original_cell, consumption_receipt=changed_receipt)
    )
    assert original.preflight.subject_sha256 != changed.preflight.subject_sha256
    assert original.comparability_sha256 != changed.comparability_sha256


def test_comparison_rejects_inapplicable_and_nonadjacent_case_pairs() -> None:
    foundation = _runner(_Runtime()).run(_cell(LayerVariant.FOUNDATION))
    department = _runner(_Runtime()).run(_cell(LayerVariant.DEPARTMENT))
    with pytest.raises(ValueError, match="exact applicable"):
        pair_control_runs(foundation, department)

    eval_five_foundation = _runner(_Runtime()).run(
        _cell(LayerVariant.FOUNDATION, case_id="eval-05")
    )
    eval_five_department = _runner(_Runtime()).run(
        _cell(LayerVariant.DEPARTMENT, case_id="eval-05")
    )
    assert pair_control_runs(eval_five_foundation, eval_five_department)


def test_retry_lineage_requires_preserved_matching_parent_and_keeps_all_attempts() -> (
    None
):
    runner = _runner(_Runtime())
    first = runner.run(_cell())
    retry = runner.run(_cell(attempt=2, parent_attempt_sha256=first.run_sha256))
    assert retry.state is RunState.COMPLETED
    assert len(runner.records) == 2

    bad_runtime = _Runtime()
    bad = runner.run(
        _cell(
            LayerVariant.ORGANIZATION,
            attempt=2,
            parent_attempt_sha256=first.run_sha256,
        )
    )
    assert bad.state is RunState.INVALID
    assert bad_runtime.calls == 0
    assert len(runner.records) == 3


@pytest.mark.parametrize(
    "field",
    [
        "criterionScore",
        "evaluation.score",
        "scores",
        "Total-Value",
        "AVERAGE_RESULT",
        "percentile",
        "winningRank",
    ],
)
def test_artifact_rejects_semantic_aggregate_key_variants(
    tmp_path: Path, field: str
) -> None:
    with pytest.raises(ValueError, match="Aggregate"):
        _write_artifact(
            tmp_path,
            artifact_type="comparison-record",
            payload={"nested": [{field: 1}]},
        )


def test_public_package_exposes_no_authority_issuer_or_generic_writer() -> None:
    package = importlib.import_module("cc.core.evaluation")
    artifact = importlib.import_module("cc.core.evaluation.artifact")
    runner = importlib.import_module("cc.core.evaluation.runner")
    preflight = importlib.import_module("cc.core.evaluation.preflight")
    for name in (
        "TrustedEvidenceVerifier",
        "TrustedCompletionVerifier",
        "AttemptLedger",
        "write_artifact",
        "_test_authority",
        "_test_completed_output",
    ):
        assert not hasattr(package, name)
    assert not hasattr(artifact, "write_artifact")
    assert not hasattr(runner, "TrustedCompletionVerifier")
    assert not hasattr(runner, "AttemptLedger")
    assert not hasattr(preflight, "TrustedEvidenceVerifier")


def test_unsealed_authority_cannot_execute_adapter() -> None:
    runtime = _Runtime()
    record = EvaluationRunner(runtime, lambda _cell: True).run(_cell())
    assert record.state is RunState.INVALID
    assert runtime.calls == 0


def test_unsealed_completion_cannot_claim_completed() -> None:
    class _ForgedRuntime(_Runtime):
        def execute(self, cell: EvaluationCell) -> object:
            self.calls += 1
            return {
                "output": self.output,
                "completion_evidence_sha256": _sha("0"),
            }

    record = _runner(_ForgedRuntime()).run(_cell())
    assert record.state is RunState.TECHNICAL_ERROR


def test_forged_run_and_comparison_records_cannot_be_minted_or_written(
    tmp_path: Path,
) -> None:

    record = _runner(_Runtime()).run(_cell())
    with pytest.raises(ValueError, match="runner-issued"):
        replace(record, run_sha256=_sha("9"), _authority=None)
    forged = replace(record, run_sha256=_sha("9"))
    with pytest.raises(ValueError, match="authentic"):
        write_run_record(tmp_path, forged)

    comparison = pair_control_runs(
        _runner(_Runtime()).run(_cell(LayerVariant.FOUNDATION)),
        _runner(_Runtime()).run(_cell(LayerVariant.ORGANIZATION)),
    )
    with pytest.raises(ValueError, match="coordinator-issued"):
        replace(comparison, comparison_sha256=_sha("8"), _authority=None)
    forged_comparison = replace(comparison, comparison_sha256=_sha("8"))
    with pytest.raises(ValueError, match="authentic"):
        write_comparison_record(tmp_path, forged_comparison)


def test_attempt_history_is_read_only_and_rejects_changed_identity() -> None:
    runner = _runner(_Runtime())
    first = runner.run(_cell())
    snapshot = runner.records
    assert snapshot == (first,)
    assert isinstance(snapshot, tuple)
    assert not hasattr(runner, "attempt_ledger")
    assert not hasattr(runner, "preserve")
