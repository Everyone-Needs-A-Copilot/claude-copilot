from __future__ import annotations

import ast
import copy
import importlib
import json
import os
import stat
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cc.core.evaluation._authority import (
    _cell_subject,
    _EvaluationAuthority,
    _issue_evaluation_authority,
)
from cc.core.evaluation.artifact import (
    _open_root_directory,
    _reject_aggregate_fields,
    _verify_named_artifact,
    _verify_storage_snapshot,
    _write_artifact,
    close_artifact_receipt,
    load_durable_unsupported_run,
    load_run_record_document,
    verify_artifact_receipt,
    write_run_record,
)
from cc.core.evaluation.attempt_policy import ATTEMPT_POLICY_SHA256
from cc.core.evaluation.comparison import pair_control_runs
from cc.core.evaluation.coordinator import (
    claim_attempt,
    finalize_attempt,
    load_technical_retry_parent,
)
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
from cc.core.evaluation.runner import (
    _RUNTIME_FAILURE_DISPOSITIONS,
    EvaluationRunner,
    RuntimeAdapterFailure,
    _record_document,
    verify_run_record_identity,
)
from cc.core.evaluation.schema import canonical_sha256


@pytest.fixture(name="tmp_path")
def _private_artifact_root(tmp_path_factory: pytest.TempPathFactory):
    """Give artifact tests a secure root without relaxing production checks.

    GitHub's Linux runner places pytest's normal temporary directory below a
    user-replaceable ancestor.  Production correctly rejects that path.  On
    Linux, make the per-test mode-0700 directory inside the checked-out tree,
    whose ancestry is stable for the job.  macOS keeps pytest's canonical
    private temporary hierarchy and its existing traversal proof.
    """

    if not sys.platform.startswith("linux"):
        yield tmp_path_factory.mktemp("evaluation-artifact")
        return

    repo_root = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory(
        prefix=".cc-evaluation-artifact-", dir=repo_root
    ) as directory:
        root = Path(directory)
        root.chmod(0o700)
        yield root


def _sha(character: str) -> str:
    return character * 64


def _runtime(*, configuration_marker: str = "base") -> RuntimeReceipt:
    return RuntimeReceipt(
        runtime=RuntimeName.CLAUDE,
        executable_sha256=_sha("1"),
        runtime_version="2.1.0",
        model_version="test-model",
        tool_availability=("agent", "knowledge", "tc"),
        adapter_name="journey-adapter",
        adapter_version=f"v2.1-{configuration_marker}",
        capability_flags=("continuity", "optional-transport"),
    )


def _layer(
    product: str,
    tier: str,
    index: int,
    *,
    resolution_action: str | None = None,
) -> LayerContentReceipt:
    characters = "23456789abcdef"
    marker = characters[index]
    return LayerContentReceipt(
        product=product,
        tier=tier,
        source_layer_identifier=f"synthetic-{tier}",
        source_runtime="claude",
        source_adapter_version=(
            "claude-agent-v1" if product == "claude-copilot" else "knowledge-v1"
        ),
        repository_identifier=f"synthetic/{product}-{tier}",
        immutable_ref=f"refs/tags/synthetic-{product}-{tier}-v1",
        tree_sha256=_sha(marker),
        signer_identity="SHA256:SYNTHETICFOUNDATION",
        policy_sha256=_sha(characters[index + 1]),
        manifest_sha256=_sha(characters[index + 2]),
        lock_sha256=_sha(characters[index + 3]),
        contribution_ids=(f"synthetic-{product}-{tier}-contribution",),
        content_digests=(_sha(characters[index + 4]),),
        resolution_action=(
            resolution_action
            or ("selected" if product == "claude-copilot" else "accumulated")
        ),
        materialized_destinations=(f"{product}/{tier}.md",),
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
        layers=tuple(
            sorted(
                (
                    *(
                        _layer(
                            "claude-copilot",
                            tier,
                            index,
                            resolution_action=(
                                "selected" if tier == tiers[-1] else "shadowed"
                            ),
                        )
                        for index, tier in enumerate(tiers)
                    ),
                    *(
                        _layer("knowledge", tier, index + len(tiers))
                        for index, tier in enumerate(tiers)
                    ),
                ),
                key=lambda layer: (
                    tiers.index(layer.tier),
                    layer.product,
                    layer.repository_identifier,
                ),
            )
        ),
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
    attempt_policy_sha256: str | None = None,
    tool_configuration_sha256: str | None = None,
    effective_full_prompt_sha256: str | None = None,
    command_policy_sha256: str | None = None,
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
        attempt_policy_sha256=attempt_policy_sha256 or ATTEMPT_POLICY_SHA256,
        runtime_configuration_sha256=runtime_configuration_sha256 or _sha("5"),
        tool_configuration_sha256=tool_configuration_sha256 or _sha("6"),
        effective_full_prompt_sha256=effective_full_prompt_sha256 or _sha("7"),
        command_policy_sha256=command_policy_sha256 or _sha("8"),
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
        return self.output


class _TechnicalTimeoutRuntime(_Runtime):
    def execute(self, cell: EvaluationCell) -> object:
        from cc.core.evaluation.live_runtime import (
            RuntimeTerminalFailure,
            _issue_runtime_timeout_receipt,
        )

        self.calls += 1
        execution_policy = {
            "schema_version": "1.0",
            "command_policy_sha256": cell.command_policy_sha256,
            "execution_boundary": "synthetic-process-group-timeout",
        }
        receipt = _issue_runtime_timeout_receipt(
            cell,
            runtime=cell.runtime_receipt.runtime,
            adapter_name=cell.runtime_receipt.adapter_name,
            adapter_version=cell.runtime_receipt.adapter_version,
            execution_policy_document=execution_policy,
            timeout_seconds=1.0,
        )
        raise RuntimeTerminalFailure(
            "runtime-timeout",
            technical_receipt=receipt,
        )


def _test_authority(
    cell: EvaluationCell, observations: tuple[GateObservation, ...]
) -> _EvaluationAuthority:
    subject = _cell_subject(cell)
    return _issue_evaluation_authority(
        subject,
        evaluate_preflight(observations, subject_sha256=subject),
    )


def _test_completion(cell: EvaluationCell, output: RuntimeOutput) -> object:
    return SimpleNamespace(
        invocation_envelope_sha256=(
            cell.consumption_receipt.invocation_envelope_sha256
        ),
        output_sha256=__import__("hashlib")
        .sha256(output.output_text.encode())
        .hexdigest(),
        artifact_path_sha256=__import__("hashlib")
        .sha256(output.controlled_artifact_path.encode())
        .hexdigest(),
        evidence_sha256=_sha("7"),
    )


class _RunnerHarness:
    def __init__(
        self,
        runtime: _Runtime,
        observations: tuple[GateObservation, ...] | None,
        artifact_root: Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.observations = observations or _observations()
        self.runner: EvaluationRunner | None = None
        self.artifact_root = artifact_root

    def run(self, cell: EvaluationCell):
        if self.runner is None:
            self.runner = EvaluationRunner(
                self.runtime, artifact_root=self.artifact_root
            )
        authority = _test_authority(cell, self.observations)
        completion = (
            _test_completion(cell, self.runtime.output)
            if self.runtime.complete and isinstance(self.runtime.output, RuntimeOutput)
            else None
        )
        with (
            patch(
                "cc.core.evaluation.runner._production_authority",
                return_value=authority,
            ),
            patch(
                "cc.core.evaluation.runner._verify_completion",
                return_value=completion,
            ),
        ):
            return self.runner.run(cell)

    @property
    def records(self):
        return self.runner.records if self.runner else ()


def _runner(
    runtime: _Runtime,
    *,
    observations: tuple[GateObservation, ...] | None = None,
    complete: bool = True,
    artifact_root: Path | None = None,
) -> _RunnerHarness:
    runtime.complete = complete
    return _RunnerHarness(runtime, observations, artifact_root)


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
        (
            replace(item, state=GateState.UNSUPPORTED, reason="capability-absent")
            if item.gate is PreflightGate.RUNTIME_CAPABILITY
            else item
        )
        for item in _observations()
    )
    assert evaluate_preflight(runtime_unsupported).state is PreflightState.UNSUPPORTED

    journey_unsupported = tuple(
        (
            replace(item, state=GateState.UNSUPPORTED, reason="transport-unavailable")
            if item.gate is PreflightGate.JOURNEY_EVIDENCE
            else item
        )
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
        (
            replace(item, state=GateState.UNSUPPORTED, reason="capability-absent")
            if item.gate is PreflightGate.RUNTIME_CAPABILITY
            else item
        )
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
    failure = _TechnicalTimeoutRuntime()
    record = _runner(failure).run(_cell())
    assert record.state is RunState.TECHNICAL_ERROR
    assert record.technical_error_reason == "runtime-timeout"

    generic = _Runtime(RuntimeError("password=do-not-persist-this"))
    record = _runner(generic).run(_cell())
    assert record.state is RunState.INVALID
    assert record.technical_error_reason is None
    assert any(
        item.reason == "runtime-adapter-failure"
        for item in record.preflight.observations
    )
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


def test_copied_timeout_receipt_cannot_authorize_technical_retry() -> None:
    from cc.core.evaluation.live_runtime import (
        RuntimeTerminalFailure,
        _issue_runtime_timeout_receipt,
    )

    cell = _cell()
    genuine = _issue_runtime_timeout_receipt(
        cell,
        runtime=cell.runtime_receipt.runtime,
        adapter_name=cell.runtime_receipt.adapter_name,
        adapter_version=cell.runtime_receipt.adapter_version,
        execution_policy_document={
            "schema_version": "1.0",
            "command_policy_sha256": cell.command_policy_sha256,
        },
        timeout_seconds=1.0,
    )
    forged = replace(genuine, timeout_milliseconds=2_000)

    class Runtime(_Runtime):
        def execute(self, _cell: EvaluationCell) -> object:
            raise RuntimeTerminalFailure(
                "runtime-timeout",
                technical_receipt=forged,
            )

    record = _runner(Runtime(), complete=False).run(cell)
    assert record.state is RunState.INVALID
    assert record.technical_error_evidence_sha256 is None
    assert any(
        item.reason == "runtime-timeout-unverified"
        for item in record.preflight.observations
    )


def test_control_pairing_uses_exact_comparability_without_a_score() -> None:
    control = _runner(_Runtime()).run(
        _cell(
            LayerVariant.FOUNDATION,
            runtime_configuration_sha256=_sha("a"),
            tool_configuration_sha256=_sha("b"),
            effective_full_prompt_sha256=_sha("c"),
        )
    )
    layered = _runner(_Runtime()).run(
        _cell(
            LayerVariant.ORGANIZATION,
            runtime_configuration_sha256=_sha("d"),
            tool_configuration_sha256=_sha("e"),
            effective_full_prompt_sha256=_sha("f"),
        )
    )
    relation = CriterionComparison(
        criterion="evidence-discipline",
        relation=CriterionRelation.IMPROVED,
        control_evidence_sha256=(_sha("1"),),
        layered_evidence_sha256=(_sha("2"),),
    )
    with pytest.raises(ValueError, match="authenticated criterion judgments"):
        pair_control_runs(control, layered, relations=(relation,))

    changed = _runner(_Runtime()).run(
        _cell(LayerVariant.ORGANIZATION, command_policy_sha256=_sha("9"))
    )
    with pytest.raises(ValueError, match="not comparable"):
        pair_control_runs(control, changed)


def test_content_addressed_artifacts_are_canonical_and_idempotent(
    tmp_path: Path,
) -> None:
    control_cell = _cell(LayerVariant.FOUNDATION)
    control = EvaluationRunner(_Runtime()).run(control_cell)
    layered = _runner(_Runtime()).run(_cell(LayerVariant.ORGANIZATION))
    completed_control = _runner(_Runtime()).run(_cell(LayerVariant.FOUNDATION))
    with pytest.raises(ValueError, match="nonempty criterion relations"):
        pair_control_runs(completed_control, layered)

    run_receipt = write_run_record(tmp_path, control, cell=control_cell)
    repeated = write_run_record(tmp_path, control, cell=control_cell)
    assert run_receipt == repeated
    assert (tmp_path / run_receipt.relative_path).is_file()
    assert run_receipt.sha256 in run_receipt.relative_path
    assert verify_artifact_receipt(run_receipt)
    assert not verify_artifact_receipt(replace(run_receipt, sha256=_sha("9")))
    assert not verify_artifact_receipt(
        replace(run_receipt, relative_path="run-record/" + _sha("9") + ".json")
    )
    assert not verify_artifact_receipt(
        replace(run_receipt, size_bytes=run_receipt.size_bytes + 1)
    )
    assert not tuple(tmp_path.rglob("*.tmp"))

    replacement = tmp_path / "replacement.json"
    replacement.write_text("replacement", encoding="utf-8")
    replacement.chmod(0o600)
    os.replace(replacement, tmp_path / run_receipt.relative_path)
    assert not verify_artifact_receipt(run_receipt)


def test_artifact_writer_enforces_private_modes_independent_of_umask(
    tmp_path: Path,
) -> None:
    cell = _cell()
    record = EvaluationRunner(_Runtime()).run(cell)
    previous_umask = os.umask(0o777)
    try:
        receipt = write_run_record(tmp_path, record, cell=cell)
    finally:
        os.umask(previous_umask)

    artifact_type = tmp_path / "run-record"
    artifact_path = tmp_path / receipt.relative_path
    assert stat.S_IMODE(artifact_type.stat().st_mode) == 0o700
    assert stat.S_IMODE(artifact_path.stat().st_mode) == 0o600
    assert artifact_type.stat().st_uid == os.geteuid()
    assert artifact_path.stat().st_uid == os.geteuid()


def test_copied_artifact_receipt_close_cannot_revoke_authentic_receipt(
    tmp_path: Path,
) -> None:
    cell = _cell()
    record = EvaluationRunner(_Runtime()).run(cell)
    receipt = write_run_record(tmp_path, record, cell=cell)

    close_artifact_receipt(copy.copy(receipt))
    assert verify_artifact_receipt(receipt)
    close_artifact_receipt(receipt)
    close_artifact_receipt(receipt)
    assert not verify_artifact_receipt(receipt)


def test_artifact_writer_rejects_unsafe_root_type_and_existing_file_modes(
    tmp_path: Path,
) -> None:
    cell = _cell()
    record = EvaluationRunner(_Runtime()).run(cell)

    tmp_path.chmod(0o777)
    with pytest.raises(ValueError, match="group/world write|mode-0700"):
        write_run_record(tmp_path, record, cell=cell)
    tmp_path.chmod(0o700)

    artifact_type = tmp_path / "run-record"
    artifact_type.mkdir(mode=0o700)
    artifact_type.chmod(0o777)
    with pytest.raises(ValueError, match="mode-0700"):
        write_run_record(tmp_path, record, cell=cell)
    artifact_type.chmod(0o700)

    receipt = write_run_record(tmp_path, record, cell=cell)
    artifact_path = tmp_path / receipt.relative_path
    artifact_path.chmod(0o666)
    with pytest.raises(ValueError, match="private stable regular file"):
        write_run_record(tmp_path, record, cell=cell)


def test_artifact_writer_rejects_wrong_effective_owner_and_symlink_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = _cell()
    record = EvaluationRunner(_Runtime()).run(cell)
    actual_uid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: actual_uid + 1)
    with pytest.raises(ValueError, match="trusted-owned|current-user-owned"):
        write_run_record(tmp_path, record, cell=cell)
    monkeypatch.undo()

    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (tmp_path / "run-record").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        write_run_record(tmp_path, record, cell=cell)


def test_artifact_root_descriptor_walk_rejects_ancestor_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supplied = tmp_path / "supplied"
    supplied.mkdir(mode=0o700)
    root = supplied / "root"
    root.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (target / "root").mkdir(mode=0o700)
    held = tmp_path / "held"
    real_open = os.open
    real_fstat = os.fstat
    swapped = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "root" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            supplied.rename(held)
            supplied.symlink_to(target, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapping_open)
    root_fd = _open_root_directory(root)
    try:
        assert (real_fstat(root_fd).st_dev, real_fstat(root_fd).st_ino) == (
            (held / "root").stat().st_dev,
            (held / "root").stat().st_ino,
        )
        assert (real_fstat(root_fd).st_dev, real_fstat(root_fd).st_ino) != (
            (target / "root").stat().st_dev,
            (target / "root").stat().st_ino,
        )
    finally:
        os.close(root_fd)


def test_artifact_writer_rejects_root_and_file_mode_final_snapshot_races(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = _cell()
    record = EvaluationRunner(_Runtime()).run(cell)
    real_fsync = os.fsync
    fsync_calls = 0

    def root_mode_race(file_descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        real_fsync(file_descriptor)
        if fsync_calls == 3:
            tmp_path.chmod(0o777)

    monkeypatch.setattr(os, "fsync", root_mode_race)
    with pytest.raises(ValueError, match="mode-0700"):
        write_run_record(tmp_path, record, cell=cell)
    monkeypatch.undo()
    tmp_path.chmod(0o700)

    receipt = write_run_record(tmp_path, record, cell=cell)
    artifact_path = tmp_path / receipt.relative_path
    real_fsync = os.fsync
    fsync_calls = 0

    def file_mode_race(file_descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        real_fsync(file_descriptor)
        if fsync_calls == 3:
            artifact_path.chmod(0o666)

    monkeypatch.setattr(os, "fsync", file_mode_race)
    with pytest.raises(ValueError, match="private stable regular file"):
        write_run_record(tmp_path, record, cell=cell)


def test_artifact_writer_rejects_aggregate_fields_and_symlink_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Aggregate"):
        _reject_aggregate_fields({"criteria": [{"criterion_score": 10}]})

    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    cell = _cell()
    with pytest.raises((OSError, ValueError)):
        write_run_record(linked, EvaluationRunner(_Runtime()).run(cell), cell=cell)


def test_artifact_writer_rejects_existing_identical_hardlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    cell = _cell()
    record = EvaluationRunner(_Runtime()).run(cell)
    receipt = write_run_record(source, record, cell=cell)
    (target / "run-record").mkdir(mode=0o700)
    (target / "run-record").chmod(0o700)
    os.link(source / receipt.relative_path, target / receipt.relative_path)
    with pytest.raises(ValueError, match="stable regular"):
        write_run_record(target, record, cell=cell)


def test_artifact_final_name_must_still_reference_verified_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_type = tmp_path / "run-record"
    artifact_type.mkdir()
    content = b'{"schema_version":"1.2"}'
    digest = __import__("hashlib").sha256(content).hexdigest()
    filename = f"{digest}.json"
    (artifact_type / filename).write_bytes(content)
    (artifact_type / filename).chmod(0o600)
    replacement = artifact_type / "replacement.json"
    replacement.write_bytes(b"replacement")
    type_fd = os.open(artifact_type, os.O_RDONLY | os.O_DIRECTORY)
    real_stat = os.stat
    swapped = False

    def replacing_stat(path, *args, **kwargs):
        nonlocal swapped
        if path == filename and not swapped:
            swapped = True
            os.replace(
                "replacement.json",
                filename,
                src_dir_fd=type_fd,
                dst_dir_fd=type_fd,
            )
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", replacing_stat)
    try:
        with pytest.raises(ValueError, match="identity collision"):
            _verify_named_artifact(type_fd, filename, content, digest)
    finally:
        os.close(type_fd)


def test_storage_snapshot_rejects_type_name_swap_after_artifact_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cc.core.evaluation.artifact as artifact_module

    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    artifact_type = root / "run-record"
    artifact_type.mkdir(mode=0o700)
    content = b'{"schema_version":"1.2"}'
    digest = __import__("hashlib").sha256(content).hexdigest()
    filename = f"{digest}.json"
    (artifact_type / filename).write_bytes(content)
    (artifact_type / filename).chmod(0o600)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    type_fd = os.open(artifact_type, os.O_RDONLY | os.O_DIRECTORY)
    real_verify = artifact_module._verify_named_artifact

    def swapping_verify(*args, **kwargs):
        real_verify(*args, **kwargs)
        artifact_type.rename(root / "held-run-record")
        artifact_type.mkdir(mode=0o700)

    monkeypatch.setattr(artifact_module, "_verify_named_artifact", swapping_verify)
    try:
        with pytest.raises(ValueError, match="path identity"):
            _verify_storage_snapshot(
                root_fd,
                type_fd,
                "run-record",
                filename,
                content,
                digest,
            )
    finally:
        os.close(type_fd)
        os.close(root_fd)


def test_storage_snapshot_retained_leaf_rejects_final_name_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cc.core.evaluation.artifact as artifact_module

    root = tmp_path / "store"
    root.mkdir(mode=0o700)
    artifact_type = root / "run-record"
    artifact_type.mkdir(mode=0o700)
    content = b'{"schema_version":"1.4"}'
    digest = __import__("hashlib").sha256(content).hexdigest()
    filename = f"{digest}.json"
    leaf = artifact_type / filename
    leaf.write_bytes(content)
    leaf.chmod(0o600)
    replacement = artifact_type / "replacement.json"
    replacement.write_bytes(b"replacement")
    replacement.chmod(0o600)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    type_fd = os.open(artifact_type, os.O_RDONLY | os.O_DIRECTORY)
    leaf_fd = os.open(leaf, os.O_RDONLY)
    real_require = artifact_module._require_named_directory

    def replacing_leaf(*args, **kwargs):
        os.replace(
            "replacement.json",
            filename,
            src_dir_fd=type_fd,
            dst_dir_fd=type_fd,
        )
        return real_require(*args, **kwargs)

    monkeypatch.setattr(artifact_module, "_require_named_directory", replacing_leaf)
    try:
        with pytest.raises(ValueError, match="identity changed"):
            _verify_storage_snapshot(
                root_fd,
                type_fd,
                "run-record",
                filename,
                content,
                digest,
                leaf_fd=leaf_fd,
            )
    finally:
        os.close(leaf_fd)
        os.close(type_fd)
        os.close(root_fd)


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
    layer = _layer("claude-copilot", "foundation", 0)
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
    record = EvaluationRunner(_Runtime()).run(_cell())
    with pytest.raises(ValueError, match="exactly 1.4"):
        replace(record, schema_version="1.2")


@pytest.mark.parametrize("variant", tuple(LayerVariant))
def test_cell_requires_knowledge_for_every_declared_tier(
    variant: LayerVariant,
) -> None:
    cell = _cell(variant)
    for tier in dict.fromkeys(layer.tier for layer in cell.content_receipt.layers):
        replacement_layers = []
        for layer in cell.content_receipt.layers:
            if (layer.tier, layer.product) == (tier, "knowledge"):
                layer = replace(
                    layer,
                    product="claude-copilot",
                    repository_identifier=f"synthetic/claude-copilot-{tier}-extra",
                )
            replacement_layers.append(layer)
        changed_content = replace(
            cell.content_receipt,
            layers=tuple(
                sorted(
                    replacement_layers,
                    key=lambda item: (
                        tuple(
                            dict.fromkeys(
                                layer.tier for layer in cell.content_receipt.layers
                            )
                        ).index(item.tier),
                        item.product,
                        item.repository_identifier,
                    ),
                )
            ),
        )
        with pytest.raises(ValueError, match="exactly one Knowledge product"):
            replace(cell, content_receipt=changed_content)


@pytest.mark.parametrize("variant", tuple(LayerVariant))
def test_cell_requires_one_nearest_wins_runtime_specialist_product(
    variant: LayerVariant,
) -> None:
    cell = _cell(variant)
    changed_content = replace(
        cell.content_receipt,
        layers=tuple(
            layer
            for layer in cell.content_receipt.layers
            if layer.product != "claude-copilot"
        ),
    )
    with pytest.raises(ValueError, match="runtime resolution attestation"):
        replace(cell, content_receipt=changed_content)


def test_cell_rejects_cross_runtime_product_substitution() -> None:
    cell = _cell(LayerVariant.FOUNDATION)
    changed_layers = tuple(
        (
            replace(layer, product="codex-copilot")
            if layer.product == "claude-copilot"
            else layer
        )
        for layer in cell.content_receipt.layers
    )
    changed_content = replace(cell.content_receipt, layers=changed_layers)
    with pytest.raises(ValueError, match="unrelated layer product"):
        replace(cell, content_receipt=changed_content)


def test_cell_rejects_duplicate_product_from_a_different_repository() -> None:
    cell = _cell(LayerVariant.FOUNDATION)
    knowledge = next(
        layer for layer in cell.content_receipt.layers if layer.product == "knowledge"
    )
    duplicate = replace(
        knowledge,
        repository_identifier="synthetic/knowledge-foundation-extra",
        immutable_ref="refs/tags/synthetic-knowledge-foundation-extra-v1",
    )
    changed_content = replace(
        cell.content_receipt,
        layers=tuple(
            sorted(
                cell.content_receipt.layers + (duplicate,),
                key=lambda item: (item.tier, item.product, item.repository_identifier),
            )
        ),
    )
    with pytest.raises(ValueError, match="exactly one Knowledge product"):
        replace(cell, content_receipt=changed_content)


def test_cell_rejects_duplicate_runtime_product_from_a_different_repository() -> None:
    cell = _cell(LayerVariant.ORGANIZATION)
    runtime_layer = next(
        layer
        for layer in cell.content_receipt.layers
        if layer.product == "claude-copilot"
    )
    duplicate = replace(
        runtime_layer,
        repository_identifier="synthetic/claude-copilot-organization-extra",
        immutable_ref="refs/tags/synthetic-claude-copilot-organization-extra-v1",
    )
    changed_content = replace(
        cell.content_receipt,
        layers=tuple(
            sorted(
                cell.content_receipt.layers + (duplicate,),
                key=lambda item: (
                    {"foundation": 0, "organization": 1}[item.tier],
                    item.product,
                    item.repository_identifier,
                ),
            )
        ),
    )
    with pytest.raises(ValueError, match="runtime resolution attestation"):
        replace(cell, content_receipt=changed_content)


@pytest.mark.parametrize(
    ("variant", "downgraded_tier"),
    (
        (LayerVariant.ORGANIZATION, "foundation"),
        (LayerVariant.DEPARTMENT, "organization"),
        (LayerVariant.PERSONAL, "department"),
    ),
)
def test_cell_accepts_authenticated_runtime_inheritance_from_a_lower_tier(
    variant: LayerVariant,
    downgraded_tier: str,
) -> None:
    cell = _cell(variant)
    selected = next(
        layer
        for layer in cell.content_receipt.layers
        if layer.product == "claude-copilot" and layer.resolution_action == "selected"
    )
    inherited = next(
        layer
        for layer in cell.content_receipt.layers
        if layer.product == "claude-copilot" and layer.tier == downgraded_tier
    )
    changed_content = replace(
        cell.content_receipt,
        layers=tuple(
            sorted(
                (
                    (
                        replace(
                            layer,
                            resolution_action="authenticated-absence",
                            contribution_ids=(),
                            content_digests=(),
                        )
                        if layer is selected
                        else (
                            replace(layer, resolution_action="selected")
                            if layer is inherited
                            else layer
                        )
                    )
                    for layer in cell.content_receipt.layers
                ),
                key=lambda item: (
                    {
                        "foundation": 0,
                        "organization": 1,
                        "department": 2,
                        "personal": 3,
                    }[item.tier],
                    item.product,
                    item.repository_identifier,
                ),
            )
        ),
    )
    changed_cell = replace(cell, content_receipt=changed_content)
    assert (
        next(
            layer
            for layer in changed_cell.content_receipt.layers
            if layer.product == "claude-copilot"
            and layer.resolution_action == "selected"
        ).tier
        == downgraded_tier
    )


def test_cell_rejects_lower_winner_when_a_higher_contribution_exists() -> None:
    cell = _cell(LayerVariant.ORGANIZATION)
    changed_content = replace(
        cell.content_receipt,
        layers=tuple(
            (
                replace(layer, resolution_action="selected")
                if layer.product == "claude-copilot" and layer.tier == "foundation"
                else (
                    replace(layer, resolution_action="shadowed")
                    if layer.product == "claude-copilot"
                    and layer.tier == "organization"
                    else layer
                )
            )
            for layer in cell.content_receipt.layers
        ),
    )
    with pytest.raises(ValueError, match="nearest-wins selection and inheritance"):
        replace(cell, content_receipt=changed_content)


def test_run_record_state_matrix_rejects_reflective_contradictions() -> None:
    from cc.core.evaluation.runner import _record

    cell = _cell()
    invalid = EvaluationRunner(_Runtime()).run(cell)
    with pytest.raises(ValueError, match="cannot carry result"):
        _record(
            cell,
            preflight=invalid.preflight,
            state=RunState.INVALID,
            output_sha256=_sha("8"),
            controlled_artifact_path="outputs/invalid.txt",
            completion_evidence_sha256=_sha("9"),
        )

    dispatch = _runner(_Runtime(), complete=False).run(cell)
    with pytest.raises(ValueError, match="unauthenticated output evidence"):
        replace(dispatch, completion_evidence_sha256=_sha("9"))
    completed = _runner(_Runtime()).run(cell)
    with pytest.raises(ValueError, match="correlated completion"):
        replace(completed, completion_evidence_sha256=None)
    technical = _runner(_TechnicalTimeoutRuntime()).run(cell)
    with pytest.raises(ValueError, match="stable reason and verifier evidence"):
        replace(technical, output_sha256=_sha("8"))


def test_dispatch_is_not_completion_without_correlated_completion_proof() -> None:
    runtime = _Runtime()
    record = _runner(runtime, complete=False).run(_cell())
    assert record.state is RunState.DISPATCH_AUTHORIZED
    assert record.completion_evidence_sha256 is None
    assert record.output_sha256 is None
    assert record.controlled_artifact_path is None
    assert runtime.calls == 1
    with pytest.raises(ValueError, match="completed"):
        pair_control_runs(record, record)


def test_route_substitution_changes_preflight_and_control_identity() -> None:
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


def test_variant_preparation_continuity_may_differ_between_controls() -> None:
    original_cell = _cell()
    changed_receipt = replace(
        original_cell.consumption_receipt,
        journey_evidence_sha256=_sha("8"),
        continuity_evidence_sha256=_sha("9"),
    )
    original = _runner(_Runtime()).run(original_cell)
    changed = _runner(_Runtime()).run(
        replace(original_cell, consumption_receipt=changed_receipt)
    )
    assert original.preflight.subject_sha256 != changed.preflight.subject_sha256
    assert original.comparability_sha256 == changed.comparability_sha256


def test_one_sided_authenticated_retry_keeps_pair_comparable() -> None:
    from cc.core.evaluation.comparison import comparability_identity

    control = _cell(LayerVariant.FOUNDATION)
    layered_retry = _cell(
        LayerVariant.ORGANIZATION,
        attempt=2,
        parent_attempt_sha256=_sha("9"),
    )
    assert comparability_identity(control) == comparability_identity(layered_retry)


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
    relation = CriterionComparison(
        criterion="department-method",
        relation=CriterionRelation.SAME,
        control_evidence_sha256=(_sha("1"),),
        layered_evidence_sha256=(_sha("2"),),
    )
    with pytest.raises(ValueError, match="authenticated criterion judgments"):
        pair_control_runs(
            eval_five_foundation,
            eval_five_department,
            relations=(relation,),
        )


def test_retry_lineage_accepts_only_durable_retriable_technical_result(
    tmp_path: Path,
) -> None:
    first_cell = _cell()
    first = _runner(
        _TechnicalTimeoutRuntime(),
        artifact_root=tmp_path,
    ).run(first_cell)
    assert first.state is RunState.TECHNICAL_ERROR
    runner = _runner(_Runtime(), complete=False, artifact_root=tmp_path)
    retry = runner.run(_cell(attempt=2, parent_attempt_sha256=first.run_sha256))
    assert retry.state is RunState.DISPATCH_AUTHORIZED
    assert len(runner.records) == 1


def test_retry_lineage_rejects_parent_artifact_with_unsafe_mode(
    tmp_path: Path,
) -> None:
    first_cell = _cell()
    first = _runner(
        _TechnicalTimeoutRuntime(),
        artifact_root=tmp_path,
    ).run(first_cell)
    result = next((tmp_path / "attempt-result").glob("*.json"))
    result.chmod(0o666)

    runtime = _Runtime()
    runner = _runner(runtime, complete=False, artifact_root=tmp_path)
    retry = runner.run(_cell(attempt=2, parent_attempt_sha256=first.run_sha256))
    assert retry.state is RunState.INVALID
    assert runtime.calls == 0
    assert (tmp_path / "attempt-result").is_dir()

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
    assert len(runner.records) == 2


def test_retry_policy_rejects_nontechnical_parent_states(tmp_path: Path) -> None:
    for index, runtime in enumerate(
        (
            _Runtime(),
            _Runtime(RuntimeAdapterFailure("unclassified")),
            _Runtime(RuntimeAdapterFailure("claude-model-mismatch")),
            _Runtime(RuntimeAdapterFailure("codex-prohibited-runtime-action")),
        )
    ):
        root = tmp_path / f"case-{index}"
        first_cell = _cell(case_id="eval-01")
        first = _runner(runtime, complete=False, artifact_root=root).run(first_cell)
        child_runtime = _Runtime()
        child = _runner(child_runtime, artifact_root=root).run(
            _cell(attempt=2, parent_attempt_sha256=first.run_sha256)
        )
        assert child.state is RunState.INVALID
        assert child_runtime.calls == 0


@pytest.mark.parametrize(
    ("reason", "expected_state", "failed_gate"),
    (
        ("runtime-timeout", RunState.INVALID, PreflightGate.RUNTIME_ADAPTER),
        ("claude-model-mismatch", RunState.INVALID, PreflightGate.RUNTIME_ADAPTER),
        (
            "codex-prohibited-runtime-action",
            RunState.INVALID,
            PreflightGate.NO_EXTERNAL_MUTATION,
        ),
        (
            "claude-agent-projection-unavailable",
            RunState.UNSUPPORTED,
            PreflightGate.RUNTIME_CAPABILITY,
        ),
        (
            "unrecognized-runtime-failure",
            RunState.INVALID,
            PreflightGate.RUNTIME_ADAPTER,
        ),
    ),
)
def test_runtime_failure_classification_is_closed_and_nonretryable_by_default(
    reason: str,
    expected_state: RunState,
    failed_gate: PreflightGate | None,
) -> None:
    record = _runner(_Runtime(RuntimeAdapterFailure(reason))).run(_cell())
    assert record.state is expected_state
    assert record.technical_error_reason == (
        reason if expected_state is RunState.TECHNICAL_ERROR else None
    )
    terminal_gate_state = (
        GateState.UNSUPPORTED
        if expected_state is RunState.UNSUPPORTED
        else GateState.FAIL
    )
    failures = tuple(
        item
        for item in record.preflight.observations
        if item.state is terminal_gate_state
    )
    if failed_gate is None:
        assert not failures
    else:
        assert any(item.gate is failed_gate for item in failures)


@pytest.mark.parametrize(
    "reason",
    (
        "codex-no-tool-isolation-unavailable",
        "claude-agent-projection-unavailable",
    ),
)
def test_capability_unavailable_is_durable_without_output_or_live_call(
    tmp_path: Path,
    reason: str,
) -> None:
    class CapabilityUnavailable:
        live_calls = 0

        def execute(self, _cell: EvaluationCell) -> object:
            raise RuntimeAdapterFailure(reason)

    cell = _cell()
    runtime = CapabilityUnavailable()
    authority = _test_authority(cell, _observations())
    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=authority,
    ):
        record = EvaluationRunner(runtime, artifact_root=tmp_path).run(cell)
    assert record.state is RunState.UNSUPPORTED
    assert record.preflight.state is PreflightState.UNSUPPORTED
    assert record.output_sha256 is None
    assert runtime.live_calls == 0

    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=lambda *_args, **_kwargs: _test_authority(
            cell,
            _observations(),
        ),
    ):
        receipt = write_run_record(tmp_path, record, cell=cell)
        loaded = load_durable_unsupported_run(
            tmp_path,
            record.run_sha256,
            cell=cell,
        )
    assert verify_artifact_receipt(receipt)
    assert loaded is not None
    assert loaded.record.state is RunState.UNSUPPORTED
    assert loaded.validate()
    copy.copy(loaded).close()
    assert loaded.validate()
    loaded.close()
    loaded.close()
    assert not loaded.validate()


def test_artifact_authorities_close_on_success_mismatch_exception_and_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls: list[_EvaluationAuthority] = []
    original_close = _EvaluationAuthority.close

    def tracked_close(authority: _EvaluationAuthority) -> None:
        close_calls.append(authority)
        original_close(authority)

    monkeypatch.setattr(_EvaluationAuthority, "close", tracked_close)

    class CapabilityUnavailable:
        def execute(self, _cell: EvaluationCell) -> object:
            raise RuntimeAdapterFailure("codex-no-tool-isolation-unavailable")

    cell = _cell()
    unsupported = _runner(
        CapabilityUnavailable(),
        complete=False,
        artifact_root=tmp_path,
    ).run(cell)
    close_calls.clear()
    issued: list[_EvaluationAuthority] = []

    def issue_exact(selected: EvaluationCell, **_kwargs) -> _EvaluationAuthority:
        authority = _test_authority(selected, _observations())
        issued.append(authority)
        return authority

    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=issue_exact,
    ):
        write_run_record(tmp_path, unsupported, cell=cell)
        loaded = load_durable_unsupported_run(
            tmp_path,
            unsupported.run_sha256,
            cell=cell,
        )
    assert loaded is not None
    assert issued
    assert all(
        sum(closed is authority for closed in close_calls) == 1 for authority in issued
    )

    issued.clear()
    close_calls.clear()

    def issue_mismatch(_selected: EvaluationCell, **_kwargs) -> _EvaluationAuthority:
        authority = _test_authority(
            _cell(case_id="eval-02"),
            _observations(),
        )
        issued.append(authority)
        return authority

    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=issue_mismatch,
    ):
        assert (
            load_durable_unsupported_run(
                tmp_path,
                unsupported.run_sha256,
                cell=cell,
            )
            is None
        )
    assert all(
        sum(closed is authority for closed in close_calls) == 1 for authority in issued
    )

    issued.clear()
    close_calls.clear()
    with (
        patch(
            "cc.core.evaluation._authority._production_authority",
            side_effect=issue_exact,
        ),
        patch(
            "cc.core.evaluation.runner._preflight_for",
            side_effect=ValueError("synthetic preflight failure"),
        ),
    ):
        assert (
            load_durable_unsupported_run(
                tmp_path,
                unsupported.run_sha256,
                cell=cell,
            )
            is None
        )
    assert all(
        sum(closed is authority for closed in close_calls) == 1 for authority in issued
    )

    lineage_root = tmp_path / "lineage"
    lineage_root.mkdir(mode=0o700)
    lineage_cell = _cell()
    parent = _runner(
        _Runtime(),
        complete=False,
        artifact_root=lineage_root,
    ).run(lineage_cell)
    issued.clear()
    close_calls.clear()
    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=issue_exact,
    ):
        write_run_record(lineage_root, parent, cell=lineage_cell)
    issued.clear()
    close_calls.clear()
    child = _cell(attempt=2, parent_attempt_sha256=parent.run_sha256)
    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=issue_exact,
    ):
        document = load_run_record_document(
            lineage_root,
            parent.run_sha256,
            child_cell=child,
            loaded_fixture=None,
            journey_run_id="",
            journey_ledger=None,
            lineage_depth=0,
        )
    assert document is not None
    assert all(
        sum(closed is authority for closed in close_calls) == 1 for authority in issued
    )


def test_every_emitted_runtime_terminal_reason_has_a_closed_disposition() -> None:
    from cc.core.evaluation import live_runtime

    module = ast.parse(Path(live_runtime.__file__).read_text(encoding="utf-8"))
    emitted = {
        node.args[0].value
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RuntimeTerminalFailure"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert emitted <= set(_RUNTIME_FAILURE_DISPOSITIONS)


def test_retry_policy_is_bounded_and_canonical() -> None:
    with pytest.raises(ValueError, match="canonical retry limit"):
        _cell(attempt=3, parent_attempt_sha256=_sha("8"))
    with pytest.raises(ValueError, match="attempt policy is not canonical"):
        _cell(attempt_policy_sha256=_sha("8"))


def test_retry_lineage_rejects_attempt_result_directory_replacement(
    tmp_path: Path,
) -> None:
    first = _runner(
        _TechnicalTimeoutRuntime(),
        artifact_root=tmp_path,
    ).run(_cell())
    held = tmp_path / "held-attempt-result"
    (tmp_path / "attempt-result").rename(held)
    (tmp_path / "attempt-result").mkdir(mode=0o700)
    runtime = _Runtime()
    retry = _runner(runtime, artifact_root=tmp_path).run(
        _cell(attempt=2, parent_attempt_sha256=first.run_sha256)
    )
    assert retry.state is RunState.INVALID
    assert runtime.calls == 0


def test_finalize_attempt_retains_claim_leaf_through_result_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = _cell()
    assert claim_attempt(tmp_path, cell)
    record = _runner(_TechnicalTimeoutRuntime()).run(cell)
    claim_path = next((tmp_path / "attempt-claim").glob("*.json"))
    held_path = claim_path.with_suffix(".held")
    real_require_named_directory = __import__(
        "cc.core.evaluation.artifact", fromlist=["_require_named_directory"]
    )._require_named_directory
    swapped = False

    def replace_claim_during_result_binding(
        parent_fd: int,
        name: str,
        opened: os.stat_result,
        *,
        description: str,
    ) -> None:
        nonlocal swapped
        real_require_named_directory(parent_fd, name, opened, description=description)
        if name == "attempt-result" and not swapped:
            swapped = True
            claim_path.rename(held_path)
            claim_path.write_text('{"mutated":true}', encoding="utf-8")
            claim_path.chmod(0o600)

    monkeypatch.setattr(
        "cc.core.evaluation.artifact._require_named_directory",
        replace_claim_during_result_binding,
    )
    with pytest.raises(ValueError, match="attempt evidence changed"):
        finalize_attempt(tmp_path, cell, record)
    assert swapped


def test_retry_parent_pair_verifier_rejects_post_finalize_claim_mutation(
    tmp_path: Path,
) -> None:
    first_cell = _cell()
    first = _runner(
        _TechnicalTimeoutRuntime(),
        artifact_root=tmp_path,
    ).run(first_cell)
    child = _cell(attempt=2, parent_attempt_sha256=first.run_sha256)
    assert load_technical_retry_parent(tmp_path, child) is not None

    claim_path = next((tmp_path / "attempt-claim").glob("*.json"))
    replacement = claim_path.with_suffix(".replacement")
    replacement.write_text('{"mutated":true}', encoding="utf-8")
    replacement.chmod(0o600)
    os.replace(replacement, claim_path)

    assert load_technical_retry_parent(tmp_path, child) is None


@pytest.mark.parametrize("artifact_type", ("attempt-claim", "attempt-result"))
@pytest.mark.parametrize("mutation", ("pretty", "duplicate-key"))
def test_retry_parent_rejects_noncanonical_or_duplicate_json_bytes(
    tmp_path: Path,
    artifact_type: str,
    mutation: str,
) -> None:
    first = _runner(
        _TechnicalTimeoutRuntime(),
        artifact_root=tmp_path,
    ).run(_cell())
    artifact_path = next((tmp_path / artifact_type).glob("*.json"))
    raw = artifact_path.read_bytes()
    if mutation == "pretty":
        changed = json.dumps(json.loads(raw), indent=2, sort_keys=False).encode()
    else:
        field = (
            b'"attempt":1,'
            if artifact_type == "attempt-claim"
            else (b'"schema_version":"1.0",')
        )
        changed = b"{" + field + raw[1:]
    artifact_path.write_bytes(changed)
    artifact_path.chmod(0o600)

    runtime = _Runtime()
    child = _runner(runtime, artifact_root=tmp_path).run(
        _cell(attempt=2, parent_attempt_sha256=first.run_sha256)
    )
    assert child.state is RunState.INVALID
    assert runtime.calls == 0


@pytest.mark.parametrize(
    "changed",
    (
        {"runtime_configuration_sha256": _sha("8")},
        {"tool_configuration_sha256": _sha("8")},
        {"effective_full_prompt_sha256": _sha("9")},
        {"command_policy_sha256": _sha("9")},
    ),
)
def test_retry_lineage_rejects_control_configuration_transplant(
    tmp_path: Path, changed: dict[str, str]
) -> None:
    first_cell = _cell()
    first = EvaluationRunner(_Runtime(), artifact_root=tmp_path).run(first_cell)
    write_run_record(tmp_path, first, cell=first_cell)
    runtime = _Runtime()
    child = _cell(
        attempt=2,
        parent_attempt_sha256=first.run_sha256,
        **changed,
    )
    record = _runner(runtime, artifact_root=tmp_path).run(child)
    assert record.state is RunState.INVALID
    assert runtime.calls == 0


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
        _reject_aggregate_fields({"nested": [{field: 1}]})


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
    with pytest.raises(TypeError):
        EvaluationRunner(runtime, lambda _cell: True)
    record = EvaluationRunner(runtime).run(_cell())
    assert record.state is RunState.INVALID
    assert runtime.calls == 0

    cell = _cell()
    copied = replace(_test_authority(cell, _observations()))
    copied_runtime = _Runtime()
    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=copied,
    ):
        copied_record = EvaluationRunner(copied_runtime).run(cell)
    assert copied_record.state is RunState.INVALID
    assert copied_runtime.calls == 0


def test_unsealed_completion_cannot_claim_completed() -> None:
    class _ForgedRuntime(_Runtime):
        def execute(self, cell: EvaluationCell) -> object:
            self.calls += 1
            return {
                "output": self.output,
                "completion_evidence_sha256": _sha("0"),
            }

    record = _runner(_ForgedRuntime()).run(_cell())
    assert record.state is RunState.INVALID


def test_forged_run_and_comparison_records_cannot_be_minted_or_written(
    tmp_path: Path,
) -> None:

    record = _runner(_Runtime()).run(_cell())
    with pytest.raises(ValueError, match="runner-issued"):
        replace(record, run_sha256=_sha("9"), _authority=None)
    forged = replace(record, run_sha256=_sha("9"))
    with pytest.raises(ValueError, match="production-authoritative"):
        write_run_record(tmp_path, forged, cell=_cell())
    changed = replace(record, technical_error_reason=None, case_id="eval-02")
    recomputed = replace(
        changed,
        run_sha256=canonical_sha256(_record_document(changed, include_identity=False)),
    )
    assert not verify_run_record_identity(recomputed)
    with pytest.raises(ValueError, match="production-authoritative"):
        write_run_record(tmp_path, recomputed, cell=_cell())

    with pytest.raises(ValueError, match="nonempty criterion relations"):
        pair_control_runs(
            _runner(_Runtime()).run(_cell(LayerVariant.FOUNDATION)),
            _runner(_Runtime()).run(_cell(LayerVariant.ORGANIZATION)),
        )


def test_attempt_history_is_read_only_and_rejects_changed_identity() -> None:
    runner = _runner(_Runtime())
    first = runner.run(_cell())
    snapshot = runner.records
    assert snapshot == (first,)
    assert isinstance(snapshot, tuple)
    assert not hasattr(runner, "attempt_ledger")
    assert not hasattr(runner, "preserve")


def test_imported_internal_writer_rejects_arbitrary_payload(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="production-authoritative"):
        _write_artifact(tmp_path, {"schema_version": "1.0"})
    record = EvaluationRunner(_Runtime()).run(_cell())
    with pytest.raises(ValueError, match="production-authoritative"):
        _write_artifact(tmp_path, record)
    with pytest.raises(TypeError):
        type(record)(**{**record.__dict__, "unexpected_score": 100})


def test_cross_runner_retry_parent_is_rejected_without_dispatch() -> None:
    first = _runner(_Runtime()).run(_cell())
    runtime = _Runtime()
    other = _runner(runtime)
    retry = other.run(_cell(attempt=2, parent_attempt_sha256=first.run_sha256))
    assert retry.state is RunState.INVALID
    assert runtime.calls == 0


@pytest.mark.parametrize(
    "path",
    (
        "outputs/%55sers/pabs/result.txt",
        "outputs/%2568ome/result.txt",
        "outputs/ｔｏｋｅｎ.txt",
        "outputs/fullwidth＠example.com.txt",
    ),
)
def test_output_paths_reject_percent_encoding_and_nfkc_confusables(path: str) -> None:
    with pytest.raises(ValueError, match="exact relative path"):
        RuntimeOutput("safe synthetic output", path, "shared-output")


def test_production_adapter_cannot_claim_completion() -> None:
    runtime = _Runtime()
    record = EvaluationRunner(runtime).run(_cell())
    assert record.state is RunState.INVALID
    assert record.completion_evidence_sha256 is None
    assert runtime.calls == 0


def test_reflection_cannot_persist_fabricated_completed_record(
    tmp_path: Path,
) -> None:
    from cc.core.evaluation.runner import _record

    cell = _cell()
    runner = _runner(_Runtime())
    authentic = runner.run(cell)
    fabricated = _record(
        cell,
        preflight=authentic.preflight,
        state=RunState.COMPLETED,
        output_sha256=_sha("8"),
        controlled_artifact_path="outputs/fabricated.txt",
        completion_evidence_sha256=_sha("9"),
    )
    assert fabricated.state is RunState.COMPLETED
    with pytest.raises(ValueError, match="production-authoritative"):
        write_run_record(tmp_path, fabricated, cell=cell)
