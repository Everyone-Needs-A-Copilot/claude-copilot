from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
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
    load_durable_completed_run,
    verify_artifact_receipt,
    verify_durable_run_evidence,
    write_run_record,
)
from cc.core.evaluation.attempt_policy import ATTEMPT_POLICY_SHA256
from cc.core.evaluation.coordinator import (
    claim_attempt,
    finalize_attempt,
    load_technical_retry_parent,
)
from cc.core.evaluation.identity import (
    build_consumption_receipt,
    prepared_sources_match_content_receipt,
)
from cc.core.evaluation.live_runtime import (
    CLAUDE_ADAPTER_NAME,
    CLAUDE_ADAPTER_VERSION,
    CODEX_ADAPTER_NAME,
    CODEX_ADAPTER_VERSION,
    ClaudeAgentProjection,
    ClaudeNonInteractiveAdapter,
    CodexNonInteractiveAdapter,
    RuntimeCompletionReceipt,
    RuntimeTerminalFailure,
    _authenticate_claude_terminal,
    _authenticate_codex_terminal,
    _codex_native_executable,
    _codex_projection,
    _run_process_group,
    _stage_executable,
    close_authenticated_runtime_output,
    runtime_authentication_status,
    runtime_completion_receipt_document,
    verify_authenticated_completion,
)
from cc.core.evaluation.matrix import (
    RuntimePromptPacket,
    fixture_packet_document,
    route_contract_document,
    runtime_configuration_identity,
)
from cc.core.evaluation.models import (
    _EVIDENCE_AUTHORITY,
    ContentReceipt,
    EvaluationCell,
    GateObservation,
    GateState,
    LayerContentReceipt,
    LayerVariant,
    PreflightGate,
    RunState,
    RuntimeName,
    RuntimeOutput,
    RuntimeReceipt,
)
from cc.core.evaluation.preflight import evaluate_preflight
from cc.core.evaluation.runner import EvaluationRunner
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256


def _sha(character: str) -> str:
    return character * 64


def _claude_json(
    result: str = "Synthetic evidence-bound result.",
    *,
    session_id: str = "session-eval-01",
    model: str = "test-model",
    **changes: object,
) -> str:
    document: dict[str, object] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "session_id": session_id,
        "result": result,
        "permission_denials": [],
        "num_turns": 1,
        "stop_reason": "end_turn",
        "terminal_reason": "completed",
        "modelUsage": {model: {"canonicalModel": model, "webSearchRequests": 0}},
        "usage": {"server_tool_use": {"web_search_requests": 0}},
    }
    document.update(changes)
    return json.dumps(document)


def _claim_attempt_worker(
    root: str,
    cell: EvaluationCell,
    ready: multiprocessing.synchronize.Event,
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    ready.set()
    start.wait(5)
    try:
        results.put(claim_attempt(Path(root), cell))
    except Exception as exc:  # pragma: no cover - asserted through child result
        results.put((type(exc).__name__, str(exc)))


def _cell(runtime_name: RuntimeName) -> EvaluationCell:
    if runtime_name is RuntimeName.CLAUDE:
        adapter_name = CLAUDE_ADAPTER_NAME
        adapter_version = CLAUDE_ADAPTER_VERSION
    else:
        adapter_name = CODEX_ADAPTER_NAME
        adapter_version = CODEX_ADAPTER_VERSION
    runtime = RuntimeReceipt(
        runtime=runtime_name,
        executable_sha256=_sha("1"),
        runtime_version="test-runtime",
        model_version="test-model",
        tool_availability=(),
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        capability_flags=("noninteractive",),
    )
    layers = tuple(
        LayerContentReceipt(
            product=product,
            tier="foundation",
            source_layer_identifier="synthetic-foundation",
            source_runtime=runtime_name.value,
            source_adapter_version=(
                "claude-agent-v1"
                if product == "claude-copilot"
                else (
                    "codex-plugin-v1" if product == "codex-copilot" else "knowledge-v1"
                )
            ),
            repository_identifier=f"synthetic/{product}",
            immutable_ref=f"refs/tags/synthetic-{product}-v1",
            tree_sha256=_sha(marker),
            signer_identity="SHA256:SYNTHETICFOUNDATION",
            policy_sha256=_sha("3"),
            manifest_sha256=_sha("4"),
            lock_sha256=_sha("5"),
            contribution_ids=(f"synthetic-{product}",),
            content_digests=(_sha(digest_marker),),
            resolution_action=(
                "selected"
                if product == f"{runtime_name.value}-copilot"
                else "accumulated"
            ),
            materialized_destinations=(f"{product}/foundation.md",),
        )
        for product, marker, digest_marker in (
            (f"{runtime_name.value}-copilot", "2", "6"),
            ("knowledge", "3", "7"),
        )
    )
    content = ContentReceipt(
        variant=LayerVariant.FOUNDATION,
        entitlement_receipt_sha256=_sha("7"),
        layers=layers,
        composed_content_sha256=_sha("8"),
        materialization_sha256=_sha("9"),
    )
    prompt = _sha("a")
    consumption = build_consumption_receipt(
        task_id=285,
        runtime_receipt=runtime,
        content_receipt=content,
        prompt_evidence_sha256=prompt,
        journey_evidence_sha256=_sha("b"),
        route_evidence_sha256=_sha("c"),
        continuity_evidence_sha256=_sha("d"),
    )
    return EvaluationCell(
        case_id="eval-01",
        revision=1,
        fixture_sha256=_sha("e"),
        prompt_evidence_sha256=prompt,
        variant=LayerVariant.FOUNDATION,
        runtime_receipt=runtime,
        content_receipt=content,
        consumption_receipt=consumption,
        attempt=1,
        attempt_policy_sha256=ATTEMPT_POLICY_SHA256,
        runtime_configuration_sha256=_sha("0"),
        tool_configuration_sha256=_sha("1"),
        effective_full_prompt_sha256=_sha("4"),
        command_policy_sha256=(
            _sha("2") if runtime_name is RuntimeName.CLAUDE else _sha("3")
        ),
    )


def _cell_for_executable(runtime_name: RuntimeName, executable: Path) -> EvaluationCell:
    cell = _cell(runtime_name)
    runtime = replace(
        cell.runtime_receipt,
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
    )
    consumption = build_consumption_receipt(
        task_id=cell.consumption_receipt.task_id,
        runtime_receipt=runtime,
        content_receipt=cell.content_receipt,
        prompt_evidence_sha256=cell.prompt_evidence_sha256,
        journey_evidence_sha256=cell.consumption_receipt.journey_evidence_sha256,
        route_evidence_sha256=cell.consumption_receipt.route_evidence_sha256,
        continuity_evidence_sha256=(
            cell.consumption_receipt.continuity_evidence_sha256
        ),
    )
    return replace(cell, runtime_receipt=runtime, consumption_receipt=consumption)


def _prompt_packet(runtime: RuntimeName) -> RuntimePromptPacket:
    user_prompt = "Synthetic prompt."
    system_context = "Synthetic TASK-296 prepared context."
    source_receipts = (
        {
            "layer": "synthetic-foundation",
            "tier": "foundation",
            "repository": "synthetic/foundation",
            "ref": "refs/tags/synthetic-foundation-v1",
            "tree": _sha("2"),
            "signer": "SHA256:SYNTHETICFOUNDATION",
            "contribution": "synthetic-foundation",
            "content_sha256": _sha("6"),
            "runtime": runtime.value,
            "adapter_version": "knowledge-v1",
        },
    )
    return RuntimePromptPacket(
        case_id="eval-01",
        revision=1,
        variant=LayerVariant.FOUNDATION,
        runtime=runtime,
        fixture_packet_sha256=str(
            fixture_packet_document("eval-01")["fixture_packet_sha256"]
        ),
        prompt_evidence_sha256=_sha("a"),
        full_prompt_sha256=canonical_sha256(
            {"system_context": system_context, "user_input": user_prompt}
        ),
        user_prompt_text=user_prompt,
        system_context_text=system_context,
        source_runtimes=(runtime.value,),
        specialist="sd",
        invocation_marker="1" * 48,
        composed_content_sha256=_sha("c"),
        source_receipts=source_receipts,
        source_receipts_sha256=canonical_sha256(list(source_receipts)),
        route_contract_sha256=str(
            route_contract_document("eval-01")["route_contract_sha256"]
        ),
    )


def _codex_source():
    skill = b"Synthetic TASK-296 prepared context."
    plugin = json.dumps(
        {"repository": "https://github.com/synthetic/codex-copilot"}
    ).encode()
    return SimpleNamespace(
        layer="codex-foundation",
        ref="refs/tags/synthetic-v1",
        tree="3" * 40,
        signer="SHA256:SYNTHETIC",
        snapshot=SimpleNamespace(
            files=(
                SimpleNamespace(
                    path=".codex-plugin/plugin.json", mode=0o100644, content=plugin
                ),
                SimpleNamespace(
                    path="skills/sd/SKILL.md", mode=0o100644, content=skill
                ),
            )
        ),
    )


def _codex_prompt_packet() -> RuntimePromptPacket:
    source = _codex_source()
    _content, receipts = _codex_projection(source, "sd")
    base = _prompt_packet(RuntimeName.CODEX)
    combined = base.source_receipts + tuple(dict(item) for item in receipts)
    return replace(
        base,
        source_receipts=combined,
        source_receipts_sha256=canonical_sha256([dict(item) for item in combined]),
    )


def _adapter_cell(
    runtime: RuntimeName,
    executable: Path,
    packet: RuntimePromptPacket,
    tool_configuration_sha256: str,
    effective_full_prompt_sha256: str,
    command_policy_sha256: str,
) -> EvaluationCell:
    cell = _cell_for_executable(runtime, executable)
    sources = list(packet.source_receipts)
    if runtime is RuntimeName.CLAUDE:
        sources.append(_claude_agent_projection().source_receipt)
    sources.sort(
        key=lambda source: (
            (
                "claude-copilot"
                if source["adapter_version"] == "claude-agent-v1"
                else (
                    "codex-copilot"
                    if source["adapter_version"] == "codex-plugin-v1"
                    else "knowledge"
                )
            ),
            source["repository"],
        )
    )
    content = replace(
        cell.content_receipt,
        layers=tuple(
            LayerContentReceipt(
                product=(
                    "claude-copilot"
                    if source["adapter_version"] == "claude-agent-v1"
                    else (
                        "codex-copilot"
                        if source["adapter_version"] == "codex-plugin-v1"
                        else "knowledge"
                    )
                ),
                tier="foundation",
                source_layer_identifier=str(source["layer"]),
                source_runtime=str(source["runtime"]),
                source_adapter_version=str(source["adapter_version"]),
                repository_identifier=str(source["repository"]),
                immutable_ref=str(source["ref"]),
                tree_sha256=hashlib.sha256(str(source["tree"]).encode()).hexdigest(),
                signer_identity=str(source["signer"]),
                policy_sha256=_sha("3"),
                manifest_sha256=_sha("4"),
                lock_sha256=_sha("5"),
                contribution_ids=(str(source["contribution"]),),
                content_digests=(str(source["content_sha256"]),),
                resolution_action=(
                    "selected"
                    if source["adapter_version"]
                    in {"claude-agent-v1", "codex-plugin-v1"}
                    else "accumulated"
                ),
                materialized_destinations=("knowledge/foundation.md",),
                source_tree=str(source["tree"]),
            )
            for source in sources
        ),
        composed_content_sha256=packet.composed_content_sha256,
    )
    consumption = build_consumption_receipt(
        task_id=cell.consumption_receipt.task_id,
        runtime_receipt=cell.runtime_receipt,
        content_receipt=content,
        prompt_evidence_sha256=packet.prompt_evidence_sha256,
        journey_evidence_sha256=cell.consumption_receipt.journey_evidence_sha256,
        route_evidence_sha256=cell.consumption_receipt.route_evidence_sha256,
        continuity_evidence_sha256=(
            cell.consumption_receipt.continuity_evidence_sha256
        ),
    )
    return replace(
        cell,
        content_receipt=content,
        consumption_receipt=consumption,
        runtime_configuration_sha256=runtime_configuration_identity(packet),
        tool_configuration_sha256=tool_configuration_sha256,
        effective_full_prompt_sha256=effective_full_prompt_sha256,
        command_policy_sha256=command_policy_sha256,
    )


def _claude_agent_projection(*_args) -> ClaudeAgentProjection:
    content = "---\nname: sd\ndescription: Synthetic agent\n---\nSynthetic agent."
    return ClaudeAgentProjection(
        content=content,
        layer="claude-foundation",
        ref="refs/tags/synthetic-v1",
        tree="3" * 40,
        signer="SHA256:SYNTHETIC",
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        tier="foundation",
        repository_identifier="synthetic/claude-foundation",
        contribution=".claude/agents/sd.md",
    )


def _authority(cell: EvaluationCell) -> _EvaluationAuthority:
    observations = tuple(
        GateObservation(
            gate,
            GateState.PASS,
            "verified",
            "framework",
            "signed-evidence",
            _EVIDENCE_AUTHORITY,
        )
        for gate in PreflightGate
    )
    subject = _cell_subject(cell)
    return _issue_evaluation_authority(
        subject,
        evaluate_preflight(observations, subject_sha256=subject),
    )


def _claude_output(cell: EvaluationCell):
    return _authenticate_claude_terminal(
        cell,
        stdout=_claude_json(cost_usd=0.01),
        returncode=0,
        controlled_artifact_path="runtime-output/claude-eval-01.txt",
        output_location_class="shared-output",
        command_policy_sha256=_sha("2"),
        full_prompt_sha256=_sha("4"),
    )


def _codex_stream(*, item_type: str = "agent_message") -> str:
    events = [
        {"type": "thread.started", "thread_id": "thread-eval-01"},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {
                "id": "item-1",
                "type": item_type,
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "type": item_type,
                "text": "Synthetic evidence-bound result.",
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10}},
    ]
    return "\n".join(json.dumps(item) for item in events)


def test_claude_terminal_receipt_completes_only_the_bound_cell() -> None:
    cell = _cell(RuntimeName.CLAUDE)
    output = _claude_output(cell)
    output_sha256 = hashlib.sha256(output.output_text.encode()).hexdigest()
    receipt = verify_authenticated_completion(cell, output, output_sha256)

    assert receipt is output.completion_receipt
    assert receipt.runtime is RuntimeName.CLAUDE
    assert receipt.invocation_envelope_sha256 == (
        cell.consumption_receipt.invocation_envelope_sha256
    )
    assert "session-eval-01" not in json.dumps(receipt.__dict__, default=str)

    class Runtime:
        def execute(self, _cell):
            return output

    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=_authority(cell),
    ):
        record = EvaluationRunner(Runtime()).run(cell)
    assert record.state is RunState.COMPLETED
    assert record.completion_evidence_sha256 == receipt.evidence_sha256


def test_copied_authenticated_output_close_cannot_revoke_authentic_output() -> None:
    cell = _cell(RuntimeName.CLAUDE)
    output = _claude_output(cell)
    output_sha256 = hashlib.sha256(output.output_text.encode()).hexdigest()

    copied = copy.copy(output)
    assert verify_authenticated_completion(cell, copied, output_sha256) is None
    close_authenticated_runtime_output(copied)
    assert verify_authenticated_completion(cell, output, output_sha256) is not None

    close_authenticated_runtime_output(output)
    close_authenticated_runtime_output(output)
    assert verify_authenticated_completion(cell, output, output_sha256) is None


def test_generic_or_tampered_output_cannot_claim_completion() -> None:
    cell = _cell(RuntimeName.CLAUDE)
    generic = RuntimeOutput(
        "Synthetic evidence-bound result.",
        "runtime-output/claude-eval-01.txt",
        "shared-output",
    )
    digest = hashlib.sha256(generic.output_text.encode()).hexdigest()
    assert verify_authenticated_completion(cell, generic, digest) is None

    authenticated = _claude_output(cell)
    changed_receipt = replace(
        authenticated.completion_receipt,
        evidence_sha256=_sha("f"),
    )
    changed = replace(authenticated, completion_receipt=changed_receipt)
    assert verify_authenticated_completion(cell, changed, digest) is None
    changed_configuration = replace(
        authenticated.completion_receipt,
        runtime_configuration_sha256=_sha("e"),
    )
    forged_receipt = replace(
        changed_configuration,
        evidence_sha256=canonical_sha256(
            runtime_completion_receipt_document(changed_configuration)
        ),
    )
    forged_output = replace(authenticated, completion_receipt=forged_receipt)
    assert verify_authenticated_completion(cell, forged_output, digest) is None
    with pytest.raises(ValueError, match="Execution policy receipt identity changed"):
        replace(
            authenticated.completion_receipt,
            execution_policy_sha256=_sha("e"),
        )
    assert (
        verify_authenticated_completion(
            replace(cell, runtime_configuration_sha256=_sha("f")),
            authenticated,
            digest,
        )
        is None
    )
    assert (
        verify_authenticated_completion(
            replace(cell, tool_configuration_sha256=_sha("f")),
            authenticated,
            digest,
        )
        is None
    )
    assert (
        verify_authenticated_completion(
            replace(cell, effective_full_prompt_sha256=_sha("f")),
            authenticated,
            digest,
        )
        is None
    )
    assert (
        verify_authenticated_completion(
            replace(cell, command_policy_sha256=_sha("f")),
            authenticated,
            digest,
        )
        is None
    )

    with pytest.raises(ValueError, match="adapter-issued"):
        RuntimeCompletionReceipt(
            runtime=RuntimeName.CLAUDE,
            adapter_name=CLAUDE_ADAPTER_NAME,
            adapter_version=CLAUDE_ADAPTER_VERSION,
            model_version="test-model",
            invocation_envelope_sha256=_sha("1"),
            runtime_configuration_sha256=_sha("1"),
            tool_configuration_sha256=_sha("1"),
            output_sha256=_sha("2"),
            artifact_path_sha256=_sha("3"),
            terminal_event_sha256=_sha("4"),
            command_policy_sha256=_sha("5"),
            execution_policy_sha256=_sha("5"),
            full_prompt_sha256=_sha("4"),
            evidence_sha256=_sha("6"),
            _authority=object(),
        )


def test_claude_rejects_nonterminal_error_and_failure_shapes() -> None:
    cell = _cell(RuntimeName.CLAUDE)
    kwargs = {
        "cell": cell,
        "controlled_artifact_path": "runtime-output/claude-eval-01.txt",
        "output_location_class": "shared-output",
        "command_policy_sha256": _sha("2"),
        "full_prompt_sha256": _sha("4"),
    }
    with pytest.raises(RuntimeTerminalFailure, match="terminal-failed"):
        _authenticate_claude_terminal(stdout="{}", returncode=1, **kwargs)
    with pytest.raises(RuntimeTerminalFailure, match="terminal-state-invalid"):
        _authenticate_claude_terminal(
            stdout=json.dumps(
                {
                    "type": "result",
                    "subtype": "error",
                    "is_error": True,
                    "session_id": "session-eval-01",
                    "result": "Synthetic failure.",
                }
            ),
            returncode=0,
            **kwargs,
        )


@pytest.mark.parametrize(
    "changed",
    (
        {"permission_denials": [{"tool": "Bash"}]},
        {"num_turns": 2},
        {"stop_reason": "tool_use"},
        {"terminal_reason": "max_turns"},
        {"modelUsage": {}},
        {
            "modelUsage": {
                "test-model": {
                    "canonicalModel": "different-model",
                    "webSearchRequests": 0,
                }
            }
        },
        {
            "modelUsage": {
                "test-model": {
                    "canonicalModel": "test-model",
                    "webSearchRequests": 0,
                },
                "fallback-model": {
                    "canonicalModel": "fallback-model",
                    "webSearchRequests": 0,
                },
            }
        },
        {
            "modelUsage": {
                "test-model": {
                    "canonicalModel": "test-model",
                    "webSearchRequests": 1,
                }
            }
        },
        {"usage": {"server_tool_use": {"web_search_requests": 1}}},
    ),
)
def test_claude_rejects_nonexact_model_turn_permission_or_server_tool_evidence(
    changed: dict[str, object],
) -> None:
    cell = _cell(RuntimeName.CLAUDE)
    expected_reason = (
        "permission-denied"
        if "permission_denials" in changed
        else (
            "turn-count-invalid"
            if "num_turns" in changed
            else (
                "terminal-state-invalid"
                if "stop_reason" in changed or "terminal_reason" in changed
                else (
                    "model-mismatch"
                    if "modelUsage" in changed
                    and not any(
                        item.get("webSearchRequests") == 1
                        for item in changed["modelUsage"].values()
                    )
                    else "prohibited-runtime-action"
                )
            )
        )
    )
    with pytest.raises(RuntimeTerminalFailure, match=expected_reason):
        _authenticate_claude_terminal(
            cell,
            stdout=_claude_json(**changed),
            returncode=0,
            controlled_artifact_path="runtime-output/claude-eval-01.txt",
            output_location_class="shared-output",
            command_policy_sha256=_sha("2"),
            full_prompt_sha256=_sha("4"),
        )


def test_codex_requires_completed_turn_final_message_and_no_tool_events() -> None:
    cell = _cell(RuntimeName.CODEX)
    output = _authenticate_codex_terminal(
        cell,
        stdout=_codex_stream(),
        returncode=0,
        final_message="Synthetic evidence-bound result.",
        controlled_artifact_path="runtime-output/codex-eval-01.txt",
        output_location_class="shared-output",
        command_policy_sha256=_sha("3"),
        full_prompt_sha256=_sha("4"),
    )
    digest = hashlib.sha256(output.output_text.encode()).hexdigest()
    assert verify_authenticated_completion(cell, output, digest) is not None

    with pytest.raises(RuntimeTerminalFailure, match="prohibited-runtime-action"):
        _authenticate_codex_terminal(
            cell,
            stdout=_codex_stream(item_type="command_execution"),
            returncode=0,
            final_message="Synthetic evidence-bound result.",
            controlled_artifact_path="runtime-output/codex-eval-01.txt",
            output_location_class="shared-output",
            command_policy_sha256=_sha("3"),
            full_prompt_sha256=_sha("4"),
        )

    unknown = _codex_stream().replace(
        '{"type": "turn.started"}', '{"type": "future.event"}'
    )
    with pytest.raises(RuntimeTerminalFailure, match="terminal-evidence-invalid"):
        _authenticate_codex_terminal(
            cell,
            stdout=unknown,
            returncode=0,
            final_message="Synthetic evidence-bound result.",
            controlled_artifact_path="runtime-output/codex-eval-01.txt",
            output_location_class="shared-output",
            command_policy_sha256=_sha("3"),
            full_prompt_sha256=_sha("4"),
        )
    with pytest.raises(RuntimeTerminalFailure, match="final-message-mismatch"):
        _authenticate_codex_terminal(
            cell,
            stdout=_codex_stream(),
            returncode=0,
            final_message="Different result.",
            controlled_artifact_path="runtime-output/codex-eval-01.txt",
            output_location_class="shared-output",
            command_policy_sha256=_sha("3"),
            full_prompt_sha256=_sha("4"),
        )


def test_runtime_receipt_adapter_identity_is_not_interchangeable() -> None:
    claude_cell = _cell(RuntimeName.CLAUDE)
    codex_cell = _cell(RuntimeName.CODEX)
    with pytest.raises(RuntimeTerminalFailure, match="runtime-receipt-mismatch"):
        _authenticate_claude_terminal(
            codex_cell,
            stdout=_claude_json(),
            returncode=0,
            controlled_artifact_path="runtime-output/claude-eval-01.txt",
            output_location_class="shared-output",
            command_policy_sha256=_sha("2"),
            full_prompt_sha256=_sha("4"),
        )
    assert claude_cell.runtime_receipt.adapter_name != (
        codex_cell.runtime_receipt.adapter_name
    )


def test_claude_adapter_binds_restricted_argv_sanitized_env_and_output(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        system_path = Path(argv[argv.index("--append-system-prompt-file") + 1])
        system_text = system_path.read_text(encoding="utf-8")
        assert "Synthetic agent." in system_text
        assert "Synthetic TASK-296 prepared context." in system_text
        assert "--agent" not in argv
        return subprocess.CompletedProcess(
            argv,
            0,
            _claude_json(),
            "",
        )

    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    output = adapter.execute(cell)

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[0] == str(executable)
    assert "--safe-mode" in argv
    assert "--no-chrome" in argv
    assert argv[argv.index("--model") + 1] == "test-model"
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--permission-mode") + 1] == "plan"
    system_context = Path(argv[argv.index("--append-system-prompt-file") + 1])
    assert str(system_context).startswith("/dev/fd/")
    assert kwargs["pass_fds"] == (int(system_context.name),)
    assert kwargs["input"] == "Synthetic prompt."
    assert kwargs["shell"] is False
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert "PATH" not in kwargs["env"]
    assert "SHELL" not in kwargs["env"]
    assert set(kwargs["env"]) == {"HOME", "LANG", "TMPDIR", "USER"}
    workspace = Path(kwargs["cwd"])
    assert Path(kwargs["env"]["TMPDIR"]).parent == workspace
    assert kwargs["start_new_session"] is True
    assert output.controlled_artifact_path.startswith("runtime-quarantine/")
    assert output.output_location_class == "private-output"
    assert (
        output.completion_receipt.execution_policy_sha256
        != output.completion_receipt.command_policy_sha256
    )
    preserved = tmp_path / output.controlled_artifact_path
    assert preserved.read_text() == output.output_text
    assert preserved.stat().st_mode & 0o777 == 0o600


def test_claude_runtime_consumes_retained_system_context_and_rejects_name_swap(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-input-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)

    def run(argv, **kwargs):
        descriptor_path = Path(argv[argv.index("--append-system-prompt-file") + 1])
        assert "Synthetic agent." in descriptor_path.read_text(encoding="utf-8")
        named = Path(kwargs["cwd"]) / "system-context.md"
        replacement = named.with_suffix(".replacement")
        replacement.write_text("substituted system context", encoding="utf-8")
        replacement.chmod(0o600)
        replacement.replace(named)
        os.lseek(kwargs["pass_fds"][0], 0, os.SEEK_SET)
        assert "Synthetic agent." in descriptor_path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, _claude_json(), "")

    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    with pytest.raises(RuntimeTerminalFailure, match="runtime-input-changed"):
        adapter.execute(cell)


def test_verifier_issued_timeout_is_durable_and_authorizes_exact_retry(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-timeout-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)
    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        timeout_seconds=1.0,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    with (
        patch(
            "cc.core.evaluation.live_runtime._run_process_group",
            side_effect=subprocess.TimeoutExpired(["claude"], 1.0),
        ),
        patch(
            "cc.core.evaluation.runner._production_authority",
            return_value=_authority(cell),
        ),
    ):
        record = EvaluationRunner(adapter, artifact_root=tmp_path).run(cell)
    assert record.state is RunState.TECHNICAL_ERROR
    assert record.technical_error_reason == "runtime-timeout"
    assert record.technical_error_evidence_sha256 is not None

    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=lambda *_args, **_kwargs: _authority(cell),
    ):
        receipt = write_run_record(tmp_path, record, cell=cell)
    assert verify_artifact_receipt(receipt)
    assert verify_durable_run_evidence(tmp_path, record)
    child = replace(
        cell,
        attempt=2,
        parent_attempt_sha256=record.run_sha256,
    )
    assert load_technical_retry_parent(tmp_path, child) is not None
    result_path = next((tmp_path / "attempt-result").glob("*.json"))
    result = json.loads(result_path.read_bytes())
    result["technical_failure_receipt"]["timeout_milliseconds"] = 2_000
    result_path.write_bytes(canonical_json_bytes(result))
    result_path.chmod(0o600)
    assert load_technical_retry_parent(tmp_path, child) is None


@pytest.mark.parametrize("mutation", ("same-inode", "name-swap"))
def test_timeout_cannot_authorize_retry_after_runtime_input_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-timeout-input-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)
    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        timeout_seconds=1.0,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )

    def timeout_after_mutation(argv, **kwargs):
        named = Path(kwargs["cwd"]) / "system-context.md"
        if mutation == "same-inode":
            named.write_text("substituted system context", encoding="utf-8")
        else:
            replacement = named.with_suffix(".replacement")
            replacement.write_text("substituted system context", encoding="utf-8")
            replacement.chmod(0o600)
            replacement.replace(named)
        raise subprocess.TimeoutExpired(argv, 1.0)

    with (
        patch(
            "cc.core.evaluation.live_runtime._run_process_group",
            side_effect=timeout_after_mutation,
        ),
        patch(
            "cc.core.evaluation.runner._production_authority",
            return_value=_authority(cell),
        ),
    ):
        record = EvaluationRunner(adapter, artifact_root=tmp_path).run(cell)

    assert record.state is RunState.INVALID
    assert record.technical_error_reason is None
    assert record.technical_error_evidence_sha256 is None
    assert any(
        item.reason == "runtime-input-changed" for item in record.preflight.observations
    )


def test_claude_readiness_uses_adapter_equivalent_authenticated_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "claude-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    observed = {}

    def run(argv, **kwargs):
        observed.update({"argv": argv, "env": kwargs["env"]})
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps({"loggedIn": True, "authMethod": "keychain"}),
            "",
        )

    monkeypatch.setattr(
        "cc.core.evaluation.live_runtime._run_process_group",
        run,
    )
    authenticated, reason = runtime_authentication_status(
        RuntimeName.CLAUDE,
        executable,
    )

    assert (authenticated, reason) == (True, "authenticated")
    assert Path(observed["argv"][0]).name == "runtime-executable"
    assert observed["argv"][1:] == ["auth", "status", "--json"]
    assert set(observed["env"]) == {"HOME", "LANG", "TMPDIR", "USER"}


def test_executable_staging_rejects_source_name_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "runtime-source"
    source.write_bytes(b"first executable")
    source.chmod(0o700)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    real_lstat = Path.lstat

    def replacing_lstat(path: Path):
        if path == source:
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"second executable")
            replacement.chmod(0o700)
            replacement.replace(source)
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", replacing_lstat)
    with pytest.raises(RuntimeTerminalFailure, match="runtime-executable-changed"):
        _stage_executable(source, tmp_path, expected)


def test_process_group_output_is_bounded_before_decode(tmp_path: Path) -> None:
    with pytest.raises(RuntimeTerminalFailure, match="runtime-output-size-invalid"):
        _run_process_group(
            [
                sys.executable,
                "-c",
                "import os; os.write(2, b'x' * (9 * 1024 * 1024))",
            ],
            input="",
            cwd=tmp_path,
            env={"LANG": "C.UTF-8"},
            timeout=10.0,
        )


def test_codex_adapter_precreates_private_final_file_and_uses_read_only_policy(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "codex-fixture"
    executable.write_bytes(b"synthetic codex executable")
    executable.chmod(0o700)
    packet = _codex_prompt_packet()
    auth_source = tmp_path / "auth.json"
    auth_source.write_text('{"synthetic":"credential"}', encoding="utf-8")
    auth_source.chmod(0o600)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert "PATH" not in kwargs["env"]
        assert "SHELL" not in kwargs["env"]
        assert set(kwargs["env"]) == {"CODEX_HOME", "HOME", "LANG", "TMPDIR"}
        projected = Path(kwargs["env"]["CODEX_HOME"])
        assert tuple(item.name for item in projected.iterdir()) == ("auth.json",)
        assert (projected / "auth.json").stat().st_mode & 0o777 == 0o600
        final_path = Path(argv[argv.index("--output-last-message") + 1])
        assert final_path.is_file()
        assert final_path.stat().st_mode & 0o777 == 0o600
        final_path.write_text("Synthetic evidence-bound result.", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, _codex_stream(), "")

    adapter = CodexNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        source_resolver=_codex_source,
        auth_source=auth_source,
    )
    cell = _adapter_cell(
        RuntimeName.CODEX,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    output = adapter.execute(cell)

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[1:4] == ["exec", "--ephemeral", "--sandbox"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" not in argv
    assert "--strict-config" in argv
    assert argv[argv.index("--model") + 1] == "test-model"
    disabled = {
        argv[index + 1] for index, value in enumerate(argv) if value == "--disable"
    }
    assert {
        "apps",
        "browser_use",
        "computer_use",
        "goals",
        "hooks",
        "image_generation",
        "multi_agent",
        "multi_agent_v2",
        "plugins",
        "shell_snapshot",
        "shell_tool",
        "unified_exec",
    } == disabled
    assert "--json" in argv
    assert argv[-1] == "-"
    assert kwargs["input"] == "Synthetic prompt."
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is True
    workspace = Path(kwargs["cwd"])
    assert workspace.name.startswith(".codex-eval-")
    assert (tmp_path / output.controlled_artifact_path).read_text() == (
        "Synthetic evidence-bound result."
    )


def test_codex_adapter_rejects_pre_read_final_message_replacement(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "codex-fixture"
    executable.write_bytes(b"synthetic codex executable")
    executable.chmod(0o700)
    packet = _codex_prompt_packet()
    auth_source = tmp_path / "auth.json"
    auth_source.write_text('{"synthetic":"credential"}', encoding="utf-8")
    auth_source.chmod(0o600)

    def run(argv, **_kwargs):
        final_path = Path(argv[argv.index("--output-last-message") + 1])
        replacement = final_path.with_suffix(".replacement")
        replacement.write_text("Synthetic evidence-bound result.", encoding="utf-8")
        replacement.chmod(0o600)
        replacement.replace(final_path)
        return subprocess.CompletedProcess(argv, 0, _codex_stream(), "")

    adapter = CodexNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        source_resolver=_codex_source,
        auth_source=auth_source,
    )
    cell = _adapter_cell(
        RuntimeName.CODEX,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )

    with pytest.raises(RuntimeTerminalFailure, match="final-message-untrusted"):
        adapter.execute(cell)


def test_concrete_adapter_rejects_executable_receipt_mismatch(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-fixture"
    executable.write_bytes(b"different executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)
    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=lambda *_args, **_kwargs: pytest.fail("runtime must not execute"),
        agent_resolver=_claude_agent_projection,
    )
    with pytest.raises(RuntimeTerminalFailure, match="receipt-mismatch"):
        adapter.execute(_cell(RuntimeName.CLAUDE))


def test_claude_adapter_rejects_unsafe_output_before_preservation(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            _claude_json("Synthetic result containing token=EXPOSED123456789."),
            "",
        )

    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )

    with pytest.raises(RuntimeTerminalFailure, match="runtime-output-unsafe"):
        adapter.execute(cell)
    assert not (tmp_path / "runtime-output").exists()


@pytest.mark.parametrize(
    "private_output",
    (
        "Use a terse decision brief with explicit tradeoffs.",
        "The synthetic person prefers a concise decision memo that calls out trade-offs.",
        "The role-scope concern should stay private.",
    ),
)
def test_eval07_private_values_are_quarantined_before_authorized_promotion(
    tmp_path: Path,
    private_output: str,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            _claude_json(private_output, session_id="session-eval-07"),
            "",
        )

    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )

    output = adapter.execute(cell)
    assert output.output_location_class == "private-output"
    assert output.controlled_artifact_path.startswith("runtime-quarantine/")
    assert (tmp_path / output.controlled_artifact_path).read_text() == private_output
    assert not (tmp_path / "runtime-output").exists()


def test_runner_rejects_unauthenticated_terminal_failure_without_retry() -> None:
    cell = _cell(RuntimeName.CLAUDE)

    class Runtime:
        def execute(self, _cell):
            raise RuntimeTerminalFailure("claude-model-mismatch")

    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=_authority(cell),
    ):
        record = EvaluationRunner(Runtime()).run(cell)

    assert record.state is RunState.INVALID
    assert record.technical_error_reason is None
    assert any(
        observation.reason == "claude-model-mismatch"
        for observation in record.preflight.observations
    )


def test_completed_record_requires_same_sealed_output_and_private_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            _claude_json(),
            "",
        )

    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    runner = EvaluationRunner(adapter, artifact_root=tmp_path)
    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=_authority(cell),
    ):
        record = runner.run(cell)
    output = runner.completion_output(record)
    assert record.state is RunState.COMPLETED
    assert output is not None

    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=lambda *_args, **_kwargs: _authority(cell),
    ):
        with pytest.raises(ValueError, match="production-authoritative"):
            write_run_record(tmp_path, record, cell=cell)
        receipt = write_run_record(
            tmp_path,
            record,
            cell=cell,
            authenticated_output=output,
        )

    assert (tmp_path / receipt.relative_path).is_file()
    assert verify_durable_run_evidence(tmp_path, record)
    with patch(
        "cc.core.evaluation._authority._production_authority",
        return_value=_authority(cell),
    ):
        reloaded = load_durable_completed_run(
            tmp_path,
            record.run_sha256,
            cell=cell,
        )
    assert reloaded is not None
    assert reloaded.record == record
    assert reloaded.record is not record
    assert reloaded.validate()
    copied_loaded = replace(reloaded)
    assert copied_loaded is not reloaded
    assert not copied_loaded.validate()
    for artifact_type in (
        "runtime-receipt",
        "content-receipt",
        "consumption-receipt",
        "completion-receipt",
        "execution-policy-receipt",
    ):
        paths = tuple((tmp_path / artifact_type).glob("*.json"))
        assert len(paths) == 1
        assert paths[0].stat().st_mode & 0o777 == 0o600

    completion_path = next((tmp_path / "completion-receipt").glob("*.json"))
    completion_bytes = completion_path.read_bytes()
    replacement = completion_path.with_suffix(".replacement")
    replacement.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    replacement.chmod(0o600)
    replacement.replace(completion_path)
    assert not verify_durable_run_evidence(tmp_path, record)
    replacement.write_bytes(completion_bytes)
    replacement.chmod(0o600)
    replacement.replace(completion_path)
    assert verify_durable_run_evidence(tmp_path, record)

    execution_path = next((tmp_path / "execution-policy-receipt").glob("*.json"))
    execution_bytes = execution_path.read_bytes()
    execution_path.unlink()
    assert not verify_durable_run_evidence(tmp_path, record)
    execution_path.write_bytes(execution_bytes)
    execution_path.chmod(0o600)
    assert verify_durable_run_evidence(tmp_path, record)

    runtime_path = next((tmp_path / "runtime-receipt").glob("*.json"))
    real_require_named_directory = __import__(
        "cc.core.evaluation.artifact", fromlist=["_require_named_directory"]
    )._require_named_directory
    swapped = False

    def swap_early_receipt_before_final_composite_check(
        parent_fd: int,
        name: str,
        opened: os.stat_result,
        *,
        description: str,
    ) -> None:
        nonlocal swapped
        real_require_named_directory(
            parent_fd,
            name,
            opened,
            description=description,
        )
        if name == "runtime-quarantine" and not swapped:
            swapped = True
            replacement = runtime_path.with_suffix(".race")
            replacement.write_text('{"runtime":"changed"}', encoding="utf-8")
            replacement.chmod(0o600)
            replacement.replace(runtime_path)

    monkeypatch.setattr(
        "cc.core.evaluation.artifact._require_named_directory",
        swap_early_receipt_before_final_composite_check,
    )
    assert not verify_durable_run_evidence(tmp_path, record)
    assert swapped
    assert not reloaded.validate()
    monkeypatch.undo()

    (tmp_path / output.controlled_artifact_path).write_text(
        "Synthetic changed output.",
        encoding="utf-8",
    )
    assert not verify_durable_run_evidence(tmp_path, record)
    with (
        patch(
            "cc.core.evaluation._authority._production_authority",
            return_value=_authority(cell),
        ),
        pytest.raises(ValueError, match="production-authoritative"),
    ):
        write_run_record(
            tmp_path,
            record,
            cell=cell,
            authenticated_output=output,
        )


def test_duplicate_first_attempt_is_atomically_rejected_before_runtime(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    cell = _cell(RuntimeName.CLAUDE)
    output = _claude_output(cell)

    class Runtime:
        def __init__(self):
            self.calls = 0

        def execute(self, _cell):
            self.calls += 1
            return output

    first_runtime = Runtime()
    second_runtime = Runtime()
    with patch(
        "cc.core.evaluation.runner._production_authority",
        side_effect=lambda *_args, **_kwargs: _authority(cell),
    ):
        first = EvaluationRunner(first_runtime, artifact_root=tmp_path).run(cell)
        second = EvaluationRunner(second_runtime, artifact_root=tmp_path).run(cell)

    assert first.state is RunState.COMPLETED
    assert second.state is RunState.INVALID
    assert first_runtime.calls == 1
    assert second_runtime.calls == 0
    claims = tuple((tmp_path / "attempt-claim").glob("*.json"))
    assert len(claims) == 1
    assert claims[0].stat().st_mode & 0o777 == 0o600
    results = tuple((tmp_path / "attempt-result").glob("*.json"))
    assert len(results) == 1
    terminal = json.loads(results[0].read_bytes())
    assert terminal["run_record"]["run_sha256"] == first.run_sha256
    assert terminal["run_record"]["state"] == RunState.COMPLETED.value
    assert terminal["slot_sha256"] == claims[0].stem
    assert results[0].stem == claims[0].stem
    assert results[0].stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="already has a terminal result"):
        finalize_attempt(tmp_path, cell, first)
    with pytest.raises(ValueError, match="does not match"):
        finalize_attempt(
            tmp_path,
            replace(cell, runtime_configuration_sha256=_sha("9")),
            first,
        )
    assert json.loads(results[0].read_bytes()) == terminal


@pytest.mark.parametrize(
    "changed",
    (
        {"runtime_configuration_sha256": _sha("9")},
        {"tool_configuration_sha256": _sha("9")},
        {"effective_full_prompt_sha256": _sha("9")},
        {"command_policy_sha256": _sha("9")},
        {"fixture_sha256": _sha("9")},
        {"prompt_evidence_sha256": _sha("9")},
        {
            "content_receipt": replace(
                _cell(RuntimeName.CLAUDE).content_receipt,
                materialization_sha256=_sha("9"),
            )
        },
    ),
)
def test_attempt_slot_rejects_mutated_claim_payload(
    tmp_path: Path,
    changed: dict[str, object],
) -> None:
    tmp_path.chmod(0o700)
    cell = _cell(RuntimeName.CLAUDE)

    assert claim_attempt(tmp_path, cell) is True
    assert claim_attempt(tmp_path, replace(cell, **changed)) is False
    assert len(tuple((tmp_path / "attempt-claim").glob("*.json"))) == 1


def test_attempt_slot_is_exclusive_across_simultaneous_processes(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    context = multiprocessing.get_context("fork")
    start = context.Event()
    readies = (context.Event(), context.Event())
    results = context.Queue()
    cell = _cell(RuntimeName.CLAUDE)
    processes = tuple(
        context.Process(
            target=_claim_attempt_worker,
            args=(str(tmp_path), cell, ready, start, results),
        )
        for ready in readies
    )
    for process in processes:
        process.start()
    try:
        assert all(ready.wait(5) for ready in readies)
        start.set()
        observed = [results.get(timeout=5) for _process in processes]
    finally:
        start.set()
        for process in processes:
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)

    assert sorted(observed) == [False, True]
    assert all(process.exitcode == 0 for process in processes)
    assert len(tuple((tmp_path / "attempt-claim").glob("*.json"))) == 1


@pytest.mark.parametrize(
    "changed",
    (
        {"system_context_text": "Substituted system context."},
        {"source_receipts_sha256": _sha("f")},
        {"variant": LayerVariant.ORGANIZATION},
    ),
)
def test_adapter_rejects_prompt_source_or_variant_substitution(
    tmp_path: Path,
    changed: dict[str, object],
) -> None:
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    original = _prompt_packet(RuntimeName.CLAUDE)
    packet = replace(original, **changed)
    if "system_context_text" in changed:
        packet = replace(
            packet,
            full_prompt_sha256=canonical_sha256(
                {
                    "system_context": packet.system_context_text,
                    "user_input": packet.user_prompt_text,
                }
            ),
        )
    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=lambda *_args, **_kwargs: pytest.fail("runtime must not execute"),
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        original,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )

    with pytest.raises(RuntimeTerminalFailure, match="runtime-receipt-mismatch"):
        adapter.execute(cell)


def test_content_receipt_allows_multiple_products_per_tier_with_exact_source_coverage() -> (
    None
):
    plugin = _cell(RuntimeName.CODEX).content_receipt.layers[0]
    foundation_knowledge = replace(
        plugin,
        product="knowledge",
        source_layer_identifier="synthetic-foundation-knowledge",
        source_adapter_version="knowledge-v1",
        repository_identifier="synthetic/foundation-knowledge",
        tree_sha256=_sha("a"),
        source_tree=_sha("a"),
        contribution_ids=("foundation-method",),
        content_digests=(_sha("b"),),
        resolution_action="accumulated",
    )
    organization_runtime_absence = replace(
        plugin,
        tier="organization",
        source_layer_identifier="synthetic-organization-codex",
        repository_identifier="synthetic/organization-codex",
        immutable_ref="refs/tags/synthetic-organization-codex-v1",
        tree_sha256=_sha("e"),
        source_tree=_sha("e"),
        contribution_ids=(),
        content_digests=(),
        resolution_action="authenticated-absence",
    )
    organization_knowledge = replace(
        plugin,
        product="knowledge",
        tier="organization",
        source_layer_identifier="synthetic-organization-knowledge",
        source_adapter_version="knowledge-v1",
        repository_identifier="synthetic/organization-knowledge",
        immutable_ref="refs/tags/synthetic-organization-v1",
        tree_sha256=_sha("c"),
        source_tree=_sha("c"),
        contribution_ids=("organization-method",),
        content_digests=(_sha("d"),),
        resolution_action="accumulated",
    )
    content = ContentReceipt(
        variant=LayerVariant.ORGANIZATION,
        entitlement_receipt_sha256=_sha("7"),
        layers=(
            plugin,
            foundation_knowledge,
            organization_runtime_absence,
            organization_knowledge,
        ),
        composed_content_sha256=_sha("8"),
        materialization_sha256=_sha("9"),
    )

    def source(layer: LayerContentReceipt) -> dict[str, str]:
        return {
            "layer": layer.source_layer_identifier,
            "tier": layer.tier,
            "repository": layer.repository_identifier,
            "ref": layer.immutable_ref,
            "tree": layer.source_tree or layer.tree_sha256,
            "signer": layer.signer_identity,
            "contribution": layer.contribution_ids[0],
            "content_sha256": layer.content_digests[0],
            "runtime": layer.source_runtime,
            "adapter_version": layer.source_adapter_version,
        }

    sources = tuple(
        source(layer)
        for layer in content.layers
        if layer.resolution_action in {"selected", "accumulated"}
    )
    assert prepared_sources_match_content_receipt(content, sources)
    assert not prepared_sources_match_content_receipt(content, sources[:-1])
    assert not prepared_sources_match_content_receipt(content, sources + (sources[0],))
    assert not prepared_sources_match_content_receipt(
        content,
        (sources[0], {**sources[1], "repository": "synthetic/wrong-tier"}, sources[2]),
    )
    assert not prepared_sources_match_content_receipt(
        content,
        (sources[0], {**sources[1], "content_sha256": _sha("e")}, sources[2]),
    )
    for field, value in (
        ("layer", "synthetic-wrong-layer"),
        ("runtime", "claude"),
        ("adapter_version", "codex-plugin-v2"),
    ):
        assert not prepared_sources_match_content_receipt(
            content,
            (sources[0], {**sources[1], field: value}, sources[2]),
        )


def test_codex_terminal_requires_started_completed_item_identity_pair() -> None:
    cell = _cell(RuntimeName.CODEX)
    missing_start = "\n".join(
        line
        for line in _codex_stream().splitlines()
        if json.loads(line)["type"] != "item.started"
    )
    with pytest.raises(RuntimeTerminalFailure, match="terminal-evidence-invalid"):
        _authenticate_codex_terminal(
            cell,
            stdout=missing_start,
            returncode=0,
            final_message="Synthetic evidence-bound result.",
            controlled_artifact_path="runtime-output/codex-eval-01.txt",
            output_location_class="shared-output",
            command_policy_sha256=_sha("3"),
            full_prompt_sha256=_sha("4"),
        )
    mismatched = _codex_stream().replace(
        '"id": "item-1", "type": "agent_message", "text"',
        '"id": "item-2", "type": "agent_message", "text"',
    )
    with pytest.raises(RuntimeTerminalFailure, match="terminal-evidence-invalid"):
        _authenticate_codex_terminal(
            cell,
            stdout=mismatched,
            returncode=0,
            final_message="Synthetic evidence-bound result.",
            controlled_artifact_path="runtime-output/codex-eval-01.txt",
            output_location_class="shared-output",
            command_policy_sha256=_sha("3"),
            full_prompt_sha256=_sha("4"),
        )


def test_codex_node_launcher_resolves_to_exact_native_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "codex"
    launcher = package_root / "bin" / "codex.js"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    native = (
        package_root
        / "node_modules"
        / "@openai"
        / "codex-darwin-arm64"
        / "vendor"
        / "aarch64-apple-darwin"
        / "bin"
        / "codex"
    )
    native.parent.mkdir(parents=True)
    native.write_bytes(b"synthetic native codex")
    native.chmod(0o700)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        "cc.core.evaluation.live_runtime.platform.machine", lambda: "arm64"
    )

    assert _codex_native_executable(launcher) == native


def test_process_group_runner_kills_whole_session_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cc.core.evaluation.live_runtime import _run_process_group

    del monkeypatch
    killpg = patch(
        "cc.core.evaluation.live_runtime.os.killpg",
        wraps=__import__("os").killpg,
    )
    with killpg as killed, pytest.raises(subprocess.TimeoutExpired):
        _run_process_group(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            input="synthetic",
            cwd=tmp_path,
            env={"LANG": "C.UTF-8"},
            timeout=0.05,
        )
    assert any(call.args[1] == 15 for call in killed.call_args_list)
