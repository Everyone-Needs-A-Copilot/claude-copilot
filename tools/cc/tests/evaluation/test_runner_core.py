from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cc.core.evaluation.artifact import (
    write_artifact,
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
        )
        for gate in PreflightGate
    )


def _cell(
    variant: LayerVariant = LayerVariant.FOUNDATION,
    *,
    observations: tuple[GateObservation, ...] | None = None,
    runtime_configuration_sha256: str | None = None,
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
        case_id="eval-01",
        revision=1,
        fixture_sha256=_sha("3"),
        prompt_evidence_sha256=prompt,
        variant=variant,
        runtime_receipt=runtime,
        content_receipt=content,
        consumption_receipt=consumption,
        observations=observations if observations is not None else _observations(),
        attempt=1,
        attempt_policy_sha256=_sha("4"),
        runtime_configuration_sha256=runtime_configuration_sha256 or _sha("5"),
        tool_configuration_sha256=_sha("6"),
    )


class _Runtime:
    def __init__(self, output: RuntimeOutput | Exception | None = None) -> None:
        self.calls = 0
        self.output = output or RuntimeOutput(
            output_text="Synthetic result with cited evidence.",
            controlled_artifact_path="outputs/eval-01.txt",
            output_location_class="shared-output",
            completion_evidence_sha256=_sha("7"),
        )

    def execute(self, cell: EvaluationCell) -> RuntimeOutput:
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


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
    record = EvaluationRunner(runtime).run(_cell(observations=missing))
    assert record.state is RunState.INVALID
    assert runtime.calls == 0

    unsupported = tuple(
        replace(item, state=GateState.UNSUPPORTED, reason="capability-absent")
        if item.gate is PreflightGate.RUNTIME_CAPABILITY
        else item
        for item in _observations()
    )
    record = EvaluationRunner(runtime).run(_cell(observations=unsupported))
    assert record.state is RunState.UNSUPPORTED
    assert runtime.calls == 0


def test_runner_derives_receipt_binding_gate_and_fails_closed() -> None:
    cell = _cell()
    tampered = replace(
        cell.consumption_receipt,
        invocation_envelope_sha256=_sha("9"),
    )
    runtime = _Runtime()
    record = EvaluationRunner(runtime).run(replace(cell, consumption_receipt=tampered))
    assert record.state is RunState.INVALID
    assert runtime.calls == 0
    assert any(
        item.reason == "receipt-binding-mismatch"
        for item in record.preflight.observations
    )


def test_runner_executes_one_injected_call_and_records_only_digests() -> None:
    runtime = _Runtime()
    record = EvaluationRunner(runtime).run(_cell())
    assert record.state is RunState.COMPLETED
    assert runtime.calls == 1
    assert record.output_sha256 is not None
    assert record.controlled_artifact_path == "outputs/eval-01.txt"
    assert "Synthetic result" not in json.dumps(record.__dict__, default=str)


def test_runner_sanitizes_errors_and_rejects_unsafe_shared_output() -> None:
    failure = _Runtime(RuntimeAdapterFailure("runtime-timeout"))
    record = EvaluationRunner(failure).run(_cell())
    assert record.state is RunState.TECHNICAL_ERROR
    assert record.technical_error_reason == "runtime-timeout"

    generic = _Runtime(RuntimeError("password=do-not-persist-this"))
    record = EvaluationRunner(generic).run(_cell())
    assert record.technical_error_reason == "runtime-adapter-failure"
    assert "password" not in json.dumps(record.__dict__, default=str)

    unsafe = _Runtime(
        RuntimeOutput(
            output_text="PRIVATE_PERSONAL must not enter a shared artifact",
            controlled_artifact_path="outputs/eval-01.txt",
            output_location_class="shared-output",
            completion_evidence_sha256=_sha("7"),
        )
    )
    record = EvaluationRunner(unsafe).run(_cell())
    assert record.state is RunState.INVALID
    assert record.output_sha256 is None


def test_control_pairing_uses_exact_comparability_without_a_score() -> None:
    control = EvaluationRunner(_Runtime()).run(_cell(LayerVariant.FOUNDATION))
    layered = EvaluationRunner(_Runtime()).run(_cell(LayerVariant.ORGANIZATION))
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

    changed = EvaluationRunner(_Runtime()).run(
        _cell(LayerVariant.ORGANIZATION, runtime_configuration_sha256=_sha("8"))
    )
    with pytest.raises(ValueError, match="not comparable"):
        pair_control_runs(control, changed)


def test_content_addressed_artifacts_are_canonical_and_idempotent(
    tmp_path: Path,
) -> None:
    control = EvaluationRunner(_Runtime()).run(_cell(LayerVariant.FOUNDATION))
    layered = EvaluationRunner(_Runtime()).run(_cell(LayerVariant.ORGANIZATION))
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
        write_artifact(
            tmp_path,
            artifact_type="comparison-record",
            payload={"criteria": [{"criterion_score": 10}]},
        )

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        write_artifact(
            linked,
            artifact_type="run-record",
            payload={"schema_version": "1.0"},
        )
