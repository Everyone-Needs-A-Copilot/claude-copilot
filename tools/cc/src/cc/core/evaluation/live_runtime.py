"""Authenticated terminal evidence for non-interactive evaluation runtimes.

This module does not route work, resolve Knowledge, or start a subprocess.  It
is the narrow authority boundary between a concrete runtime adapter and the
evaluation runner: native machine-readable terminal output is validated here,
then bound to the exact invocation envelope and controlled output artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from cc.core.evaluation.models import (
    EvaluationCell,
    RuntimeName,
    RuntimeOutput,
    RuntimeReceipt,
)
from cc.core.evaluation.safety import (
    FixtureSafetyViolation,
    require_safe_synthetic_text,
)
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256

CLAUDE_ADAPTER_NAME = "claude-noninteractive"
CLAUDE_ADAPTER_VERSION = "v1"
CODEX_ADAPTER_NAME = "codex-noninteractive"
CODEX_ADAPTER_VERSION = "v1"

_COMPLETION_AUTHORITY = object()
_TECHNICAL_FAILURE_AUTHORITY = object()
_COMPLETION_RECEIPT_SEALS: dict[object, "RuntimeCompletionReceipt"] = {}
_AUTHENTICATED_OUTPUT_SEALS: dict[object, "AuthenticatedRuntimeOutput"] = {}
_TECHNICAL_FAILURE_RECEIPTS: dict[object, "RuntimeTechnicalFailureReceipt"] = {}
_TECHNICAL_FAILURE_DOCUMENTS: dict[str, dict[str, object]] = {}
_TECHNICAL_EXECUTION_DOCUMENTS: dict[str, dict[str, object]] = {}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_BARE_SEMVER_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")
_CODEX_ALLOWED_ITEM_TYPES = frozenset({"agent_message", "reasoning"})
_CODEX_ALLOWED_EVENT_TYPES = frozenset(
    {
        "thread.started",
        "turn.started",
        "item.started",
        "item.completed",
        "turn.completed",
    }
)
_CODEX_DISABLED_FEATURES = (
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
)
_CODEX_LIVE_DISABLED_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode",
    "code_mode_buffered_exec",
    "code_mode_host",
    "code_mode_only",
    "computer_use",
    "enable_mcp_apps",
    "enable_request_compression",
    "goals",
    "guardian_approval",
    "hooks",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "multi_agent_v2",
    "plugin_sharing",
    "plugins",
    "recommended_plugins",
    "remote_plugin",
    "request_permissions_tool",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
)
_MAX_RUNTIME_OUTPUT_BYTES = 8 * 1024 * 1024


def _canonical_tag_ref(ref: str) -> str:
    return f"refs/tags/{ref}" if _BARE_SEMVER_TAG.fullmatch(ref) else ref


class RuntimeTerminalFailure(ValueError):
    """A runtime did not produce one authenticated successful terminal turn."""

    def __init__(self, reason: str, *, technical_receipt: object | None = None) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", reason):
            raise ValueError("Runtime terminal reason must be a stable identifier.")
        self.reason = reason
        self.technical_receipt = technical_receipt
        super().__init__(reason)


@dataclass(frozen=True)
class RuntimeTechnicalFailureReceipt:
    """Verifier-issued evidence for one bounded, process-cleaned timeout."""

    runtime: RuntimeName
    adapter_name: str
    adapter_version: str
    case_id: str
    revision: int
    variant: str
    attempt: int
    runtime_configuration_sha256: str
    tool_configuration_sha256: str
    effective_full_prompt_sha256: str
    command_policy_sha256: str
    execution_policy_sha256: str
    timeout_milliseconds: int
    reason: str
    evidence_sha256: str
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _TECHNICAL_FAILURE_AUTHORITY
            or self.reason != "runtime-timeout"
            or self.timeout_milliseconds < 1
            or self.timeout_milliseconds > 900_000
        ):
            raise ValueError("Runtime technical failure receipt is invalid.")
        for field_name in (
            "runtime_configuration_sha256",
            "tool_configuration_sha256",
            "effective_full_prompt_sha256",
            "command_policy_sha256",
            "execution_policy_sha256",
            "evidence_sha256",
        ):
            if not _DIGEST.fullmatch(getattr(self, field_name)):
                raise ValueError("Runtime technical failure identity is invalid.")


def _technical_failure_document(
    receipt: RuntimeTechnicalFailureReceipt,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "runtime": receipt.runtime.value,
        "adapter_name": receipt.adapter_name,
        "adapter_version": receipt.adapter_version,
        "case_id": receipt.case_id,
        "revision": receipt.revision,
        "variant": receipt.variant,
        "attempt": receipt.attempt,
        "runtime_configuration_sha256": receipt.runtime_configuration_sha256,
        "tool_configuration_sha256": receipt.tool_configuration_sha256,
        "effective_full_prompt_sha256": receipt.effective_full_prompt_sha256,
        "command_policy_sha256": receipt.command_policy_sha256,
        "execution_policy_sha256": receipt.execution_policy_sha256,
        "timeout_milliseconds": receipt.timeout_milliseconds,
        "reason": receipt.reason,
        "termination_claim": "process-group-terminated-before-adapter-return",
    }


def _issue_runtime_timeout_receipt(
    cell: EvaluationCell,
    *,
    runtime: RuntimeName,
    adapter_name: str,
    adapter_version: str,
    execution_policy_document: Mapping[str, object],
    timeout_seconds: float,
) -> RuntimeTechnicalFailureReceipt:
    execution_document = dict(execution_policy_document)
    execution_policy_sha256 = canonical_sha256(execution_document)
    values = {
        "runtime": runtime,
        "adapter_name": adapter_name,
        "adapter_version": adapter_version,
        "case_id": cell.case_id,
        "revision": cell.revision,
        "variant": cell.variant.value,
        "attempt": cell.attempt,
        "runtime_configuration_sha256": cell.runtime_configuration_sha256,
        "tool_configuration_sha256": cell.tool_configuration_sha256,
        "effective_full_prompt_sha256": cell.effective_full_prompt_sha256,
        "command_policy_sha256": cell.command_policy_sha256,
        "execution_policy_sha256": execution_policy_sha256,
        "timeout_milliseconds": int(timeout_seconds * 1000),
        "reason": "runtime-timeout",
    }
    seal = object()
    provisional = RuntimeTechnicalFailureReceipt(
        **values,
        evidence_sha256="0" * 64,
        _seal=seal,
        _authority=_TECHNICAL_FAILURE_AUTHORITY,
    )
    evidence_sha256 = canonical_sha256(_technical_failure_document(provisional))
    receipt = RuntimeTechnicalFailureReceipt(
        **values,
        evidence_sha256=evidence_sha256,
        _seal=seal,
        _authority=_TECHNICAL_FAILURE_AUTHORITY,
    )
    _TECHNICAL_FAILURE_RECEIPTS[seal] = receipt
    _TECHNICAL_FAILURE_DOCUMENTS[evidence_sha256] = _technical_failure_document(receipt)
    _TECHNICAL_EXECUTION_DOCUMENTS[evidence_sha256] = execution_document
    return receipt


def verify_runtime_technical_failure(
    cell: EvaluationCell,
    receipt: object,
    reason: str,
) -> bool:
    if not isinstance(receipt, RuntimeTechnicalFailureReceipt):
        return False
    document = _technical_failure_document(receipt)
    return bool(
        _TECHNICAL_FAILURE_RECEIPTS.get(receipt._seal) is receipt
        and receipt.reason == reason == "runtime-timeout"
        and receipt.runtime is cell.runtime_receipt.runtime
        and receipt.adapter_name == cell.runtime_receipt.adapter_name
        and receipt.adapter_version == cell.runtime_receipt.adapter_version
        and receipt.case_id == cell.case_id
        and receipt.revision == cell.revision
        and receipt.variant == cell.variant.value
        and receipt.attempt == cell.attempt
        and receipt.runtime_configuration_sha256 == cell.runtime_configuration_sha256
        and receipt.tool_configuration_sha256 == cell.tool_configuration_sha256
        and receipt.effective_full_prompt_sha256 == cell.effective_full_prompt_sha256
        and receipt.command_policy_sha256 == cell.command_policy_sha256
        and canonical_sha256(document) == receipt.evidence_sha256
    )


def runtime_technical_failure_document(
    evidence_sha256: str,
) -> dict[str, object] | None:
    document = _TECHNICAL_FAILURE_DOCUMENTS.get(evidence_sha256)
    return dict(document) if document is not None else None


def runtime_technical_execution_document(
    evidence_sha256: str,
) -> dict[str, object] | None:
    document = _TECHNICAL_EXECUTION_DOCUMENTS.get(evidence_sha256)
    return dict(document) if document is not None else None


@dataclass(frozen=True)
class RuntimeCompletionReceipt:
    """Value-suppressing proof of one successful, non-mutating runtime turn."""

    runtime: RuntimeName
    adapter_name: str
    adapter_version: str
    model_version: str
    invocation_envelope_sha256: str
    runtime_configuration_sha256: str
    tool_configuration_sha256: str
    full_prompt_sha256: str
    output_sha256: str
    artifact_path_sha256: str
    terminal_event_sha256: str
    command_policy_sha256: str
    execution_policy_sha256: str
    evidence_sha256: str
    _authority: object = field(repr=False, compare=False)
    _execution_policy_document: bytes = field(
        default=b"",
        repr=False,
        compare=False,
    )
    _seal: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _COMPLETION_AUTHORITY:
            raise ValueError("Runtime completion receipts must be adapter-issued.")
        if not _SESSION.fullmatch(self.model_version):
            raise ValueError("model_version must be an exact model identifier.")
        for field_name in (
            "invocation_envelope_sha256",
            "runtime_configuration_sha256",
            "tool_configuration_sha256",
            "full_prompt_sha256",
            "output_sha256",
            "artifact_path_sha256",
            "terminal_event_sha256",
            "command_policy_sha256",
            "execution_policy_sha256",
            "evidence_sha256",
        ):
            if not _DIGEST.fullmatch(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest.")
        try:
            execution_document = json.loads(self._execution_policy_document)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Execution policy receipt is malformed.") from exc
        if (
            not isinstance(execution_document, Mapping)
            or canonical_json_bytes(execution_document)
            != self._execution_policy_document
            or canonical_sha256(execution_document) != self.execution_policy_sha256
            or execution_document.get("command_policy_sha256")
            != self.command_policy_sha256
        ):
            raise ValueError("Execution policy receipt identity changed.")


@dataclass(frozen=True)
class AuthenticatedRuntimeOutput(RuntimeOutput):
    """Runtime output carrying an opaque adapter-issued completion receipt."""

    completion_receipt: RuntimeCompletionReceipt
    _completion_authority: object = field(repr=False, compare=False)
    _artifact_capability: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _seal: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self._completion_authority is not _COMPLETION_AUTHORITY:
            raise ValueError("Authenticated output must be adapter-issued.")


@dataclass(frozen=True)
class ClaudeAgentProjection:
    """One specialist agent read from an authenticated signed tier snapshot."""

    content: str
    layer: str
    ref: str
    tree: str
    signer: str
    content_sha256: str
    tier: str
    repository_identifier: str
    contribution: str

    @property
    def projection_sha256(self) -> str:
        return canonical_sha256(
            {
                "layer": self.layer,
                "ref": self.ref,
                "tree": self.tree,
                "signer": self.signer,
                "content_sha256": self.content_sha256,
                "tier": self.tier,
                "repository_identifier": self.repository_identifier,
                "contribution": self.contribution,
            }
        )

    @property
    def source_receipt(self) -> dict[str, str]:
        return {
            "layer": self.layer,
            "tier": self.tier,
            "repository": self.repository_identifier,
            "ref": self.ref,
            "tree": self.tree,
            "signer": self.signer,
            "contribution": self.contribution,
            "content_sha256": self.content_sha256,
            "runtime": RuntimeName.CLAUDE.value,
            "adapter_version": "claude-agent-v1",
        }


def _receipt_document(
    *,
    runtime: RuntimeName,
    adapter_name: str,
    adapter_version: str,
    model_version: str,
    invocation_envelope_sha256: str,
    runtime_configuration_sha256: str,
    tool_configuration_sha256: str,
    full_prompt_sha256: str,
    output_sha256: str,
    artifact_path_sha256: str,
    terminal_event_sha256: str,
    command_policy_sha256: str,
    execution_policy_sha256: str,
) -> dict[str, str]:
    return {
        "schema_version": "1.0",
        "runtime": runtime.value,
        "adapter_name": adapter_name,
        "adapter_version": adapter_version,
        "model_version": model_version,
        "invocation_envelope_sha256": invocation_envelope_sha256,
        "runtime_configuration_sha256": runtime_configuration_sha256,
        "tool_configuration_sha256": tool_configuration_sha256,
        "full_prompt_sha256": full_prompt_sha256,
        "output_sha256": output_sha256,
        "artifact_path_sha256": artifact_path_sha256,
        "terminal_event_sha256": terminal_event_sha256,
        "command_policy_sha256": command_policy_sha256,
        "execution_policy_sha256": execution_policy_sha256,
        "completion_claim": "successful-terminal-turn-without-runtime-tools",
    }


def runtime_completion_receipt_document(
    receipt: RuntimeCompletionReceipt,
) -> dict[str, str]:
    """Return the closed, value-suppressing completion evidence document."""

    return _receipt_document(
        runtime=receipt.runtime,
        adapter_name=receipt.adapter_name,
        adapter_version=receipt.adapter_version,
        model_version=receipt.model_version,
        invocation_envelope_sha256=receipt.invocation_envelope_sha256,
        runtime_configuration_sha256=receipt.runtime_configuration_sha256,
        tool_configuration_sha256=receipt.tool_configuration_sha256,
        full_prompt_sha256=receipt.full_prompt_sha256,
        output_sha256=receipt.output_sha256,
        artifact_path_sha256=receipt.artifact_path_sha256,
        terminal_event_sha256=receipt.terminal_event_sha256,
        command_policy_sha256=receipt.command_policy_sha256,
        execution_policy_sha256=receipt.execution_policy_sha256,
    )


def _issue_output(
    cell: EvaluationCell,
    *,
    runtime: RuntimeName,
    adapter_name: str,
    adapter_version: str,
    output_text: str,
    controlled_artifact_path: str,
    output_location_class: str,
    terminal_event_sha256: str,
    command_policy_sha256: str,
    full_prompt_sha256: str,
    artifact_capability: object | None = None,
    execution_policy_sha256: str | None = None,
    execution_policy_document: Mapping[str, object] | None = None,
) -> AuthenticatedRuntimeOutput:
    if cell.runtime_receipt.runtime is not runtime:
        raise RuntimeTerminalFailure("runtime-receipt-mismatch")
    if (
        cell.runtime_receipt.adapter_name != adapter_name
        or cell.runtime_receipt.adapter_version != adapter_version
    ):
        raise RuntimeTerminalFailure("runtime-adapter-mismatch")
    output_sha256 = hashlib.sha256(output_text.encode()).hexdigest()
    artifact_path_sha256 = hashlib.sha256(controlled_artifact_path.encode()).hexdigest()
    if execution_policy_document is None:
        execution_policy_document = {
            "schema_version": "1.0",
            "command_policy_sha256": command_policy_sha256,
            "execution_boundary": "sealed-terminal-unit-adapter",
        }
    execution_policy_bytes = canonical_json_bytes(dict(execution_policy_document))
    derived_execution_policy_sha256 = hashlib.sha256(execution_policy_bytes).hexdigest()
    if (
        execution_policy_sha256 is not None
        and execution_policy_sha256 != derived_execution_policy_sha256
    ):
        raise RuntimeTerminalFailure("runtime-receipt-mismatch")
    document = _receipt_document(
        runtime=runtime,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        model_version=cell.runtime_receipt.model_version,
        invocation_envelope_sha256=(
            cell.consumption_receipt.invocation_envelope_sha256
        ),
        runtime_configuration_sha256=cell.runtime_configuration_sha256,
        tool_configuration_sha256=cell.tool_configuration_sha256,
        full_prompt_sha256=full_prompt_sha256,
        output_sha256=output_sha256,
        artifact_path_sha256=artifact_path_sha256,
        terminal_event_sha256=terminal_event_sha256,
        command_policy_sha256=command_policy_sha256,
        execution_policy_sha256=derived_execution_policy_sha256,
    )
    receipt_seal = object()
    receipt = RuntimeCompletionReceipt(
        runtime=runtime,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        model_version=document["model_version"],
        invocation_envelope_sha256=document["invocation_envelope_sha256"],
        runtime_configuration_sha256=document["runtime_configuration_sha256"],
        tool_configuration_sha256=document["tool_configuration_sha256"],
        full_prompt_sha256=document["full_prompt_sha256"],
        output_sha256=output_sha256,
        artifact_path_sha256=artifact_path_sha256,
        terminal_event_sha256=terminal_event_sha256,
        command_policy_sha256=command_policy_sha256,
        execution_policy_sha256=document["execution_policy_sha256"],
        evidence_sha256=canonical_sha256(document),
        _authority=_COMPLETION_AUTHORITY,
        _execution_policy_document=execution_policy_bytes,
        _seal=receipt_seal,
    )
    _COMPLETION_RECEIPT_SEALS[receipt_seal] = receipt
    output_seal = object()
    output = AuthenticatedRuntimeOutput(
        output_text=output_text,
        controlled_artifact_path=controlled_artifact_path,
        output_location_class=output_location_class,
        completion_receipt=receipt,
        _completion_authority=_COMPLETION_AUTHORITY,
        _artifact_capability=artifact_capability,
        _seal=output_seal,
    )
    _AUTHENTICATED_OUTPUT_SEALS[output_seal] = output
    return output


def _json_object(raw: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeTerminalFailure("runtime-output-malformed") from exc
    if not isinstance(value, Mapping):
        raise RuntimeTerminalFailure("runtime-output-malformed")
    return value


def _authenticate_claude_terminal(
    cell: EvaluationCell,
    *,
    stdout: str,
    returncode: int,
    controlled_artifact_path: str,
    output_location_class: str,
    command_policy_sha256: str,
    full_prompt_sha256: str,
    stderr: str = "",
    artifact_capability: object | None = None,
    execution_policy_sha256: str | None = None,
    execution_policy_document: Mapping[str, object] | None = None,
) -> AuthenticatedRuntimeOutput:
    """Validate Claude Code ``--print --output-format json`` terminal output."""

    if returncode != 0:
        raise RuntimeTerminalFailure("claude-terminal-failed")
    value = _json_object(stdout)
    session_id = value.get("session_id")
    output_text = value.get("result")
    model_usage = value.get("modelUsage")
    usage = value.get("usage")
    model_evidence = (
        tuple(model_usage.values()) if isinstance(model_usage, Mapping) else ()
    )
    selected_model = (
        model_evidence[0].get("canonicalModel")
        if len(model_evidence) == 1 and isinstance(model_evidence[0], Mapping)
        else None
    )
    per_model_web_searches = (
        model_evidence[0].get("webSearchRequests")
        if len(model_evidence) == 1 and isinstance(model_evidence[0], Mapping)
        else None
    )
    server_tool_use = (
        usage.get("server_tool_use") if isinstance(usage, Mapping) else None
    )
    server_web_searches = (
        server_tool_use.get("web_search_requests")
        if isinstance(server_tool_use, Mapping)
        else None
    )
    if (
        value.get("type") != "result"
        or value.get("subtype") != "success"
        or value.get("is_error") is not False
        or value.get("stop_reason") != "end_turn"
        or value.get("terminal_reason") != "completed"
    ):
        raise RuntimeTerminalFailure("claude-terminal-state-invalid")
    if value.get("permission_denials") != []:
        raise RuntimeTerminalFailure("claude-permission-denied")
    if value.get("num_turns") != 1:
        raise RuntimeTerminalFailure("claude-turn-count-invalid")
    if selected_model != cell.runtime_receipt.model_version:
        raise RuntimeTerminalFailure("claude-model-mismatch")
    if per_model_web_searches != 0 or server_web_searches != 0:
        raise RuntimeTerminalFailure("claude-prohibited-runtime-action")
    if (
        not isinstance(session_id, str)
        or not _SESSION.fullmatch(session_id)
        or not isinstance(output_text, str)
        or not output_text.strip()
    ):
        raise RuntimeTerminalFailure("claude-terminal-evidence-invalid")
    terminal_event_sha256 = canonical_sha256(
        {
            "runtime": RuntimeName.CLAUDE.value,
            "terminal_type": value["type"],
            "terminal_subtype": value["subtype"],
            "is_error": value["is_error"],
            "model_version": selected_model,
            "num_turns": 1,
            "stop_reason": "end_turn",
            "terminal_reason": "completed",
            "permission_denials": [],
            "server_web_search_requests": 0,
            "model_web_search_requests": 0,
            "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
            "result_sha256": hashlib.sha256(output_text.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        }
    )
    return _issue_output(
        cell,
        runtime=RuntimeName.CLAUDE,
        adapter_name=CLAUDE_ADAPTER_NAME,
        adapter_version=CLAUDE_ADAPTER_VERSION,
        output_text=output_text,
        controlled_artifact_path=controlled_artifact_path,
        output_location_class=output_location_class,
        terminal_event_sha256=terminal_event_sha256,
        command_policy_sha256=command_policy_sha256,
        full_prompt_sha256=full_prompt_sha256,
        artifact_capability=artifact_capability,
        execution_policy_sha256=execution_policy_sha256,
        execution_policy_document=execution_policy_document,
    )


def _codex_events(stdout: str) -> tuple[Mapping[str, Any], ...]:
    events: list[Mapping[str, Any]] = []
    for raw_line in stdout.splitlines():
        if not raw_line.strip():
            continue
        events.append(_json_object(raw_line))
    if not events:
        raise RuntimeTerminalFailure("codex-terminal-empty")
    return tuple(events)


def _authenticate_codex_terminal(
    cell: EvaluationCell,
    *,
    stdout: str,
    returncode: int,
    final_message: str,
    controlled_artifact_path: str,
    output_location_class: str,
    command_policy_sha256: str,
    full_prompt_sha256: str,
    stderr: str = "",
    artifact_capability: object | None = None,
    execution_policy_sha256: str | None = None,
    execution_policy_document: Mapping[str, object] | None = None,
) -> AuthenticatedRuntimeOutput:
    """Validate Codex ``exec --json`` JSONL and its final-message file."""

    if returncode != 0:
        raise RuntimeTerminalFailure("codex-terminal-failed")
    events = _codex_events(stdout)
    types = tuple(event.get("type") for event in events)
    if (
        any(item not in _CODEX_ALLOWED_EVENT_TYPES for item in types)
        or types[:2] != ("thread.started", "turn.started")
        or types.count("thread.started") != 1
        or types.count("turn.started") != 1
        or types.count("turn.completed") != 1
        or "turn.failed" in types
        or "error" in types
        or types[-1] != "turn.completed"
    ):
        raise RuntimeTerminalFailure("codex-terminal-evidence-invalid")
    thread = next(event for event in events if event.get("type") == "thread.started")
    thread_id = thread.get("thread_id")
    if not isinstance(thread_id, str) or not _SESSION.fullmatch(thread_id):
        raise RuntimeTerminalFailure("codex-terminal-evidence-invalid")
    messages: list[str] = []
    event_shape: list[dict[str, object]] = []
    active_items: dict[str, str] = {}
    completed_items: set[str] = set()
    for event in events:
        item = event.get("item")
        if event.get("type") in {"item.started", "item.completed"}:
            if not isinstance(item, Mapping):
                raise RuntimeTerminalFailure("codex-terminal-evidence-invalid")
            item_type = item.get("type")
            item_id = item.get("id")
            if item_type not in _CODEX_ALLOWED_ITEM_TYPES:
                raise RuntimeTerminalFailure("codex-prohibited-runtime-action")
            if not isinstance(item_id, str) or not _SESSION.fullmatch(item_id):
                raise RuntimeTerminalFailure("codex-terminal-evidence-invalid")
            if event.get("type") == "item.started":
                if item_id in active_items or item_id in completed_items:
                    raise RuntimeTerminalFailure("codex-terminal-evidence-invalid")
                active_items[item_id] = str(item_type)
            elif active_items.pop(item_id, None) != item_type:
                raise RuntimeTerminalFailure("codex-terminal-evidence-invalid")
            else:
                completed_items.add(item_id)
            if event.get("type") == "item.completed" and item_type == "agent_message":
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise RuntimeTerminalFailure("codex-terminal-evidence-invalid")
                messages.append(text)
            event_shape.append(
                {
                    "type": event.get("type"),
                    "item_type": item_type,
                    "item_id_sha256": hashlib.sha256(item_id.encode()).hexdigest(),
                }
            )
        else:
            event_shape.append({"type": event.get("type")})
    if (
        active_items
        or len(messages) != 1
        or messages[0] != final_message
        or not final_message.strip()
    ):
        raise RuntimeTerminalFailure("codex-final-message-mismatch")
    terminal_event_sha256 = canonical_sha256(
        {
            "runtime": RuntimeName.CODEX.value,
            "model_version": cell.runtime_receipt.model_version,
            "thread_id_sha256": hashlib.sha256(thread_id.encode()).hexdigest(),
            "event_shape": event_shape,
            "result_sha256": hashlib.sha256(final_message.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        }
    )
    return _issue_output(
        cell,
        runtime=RuntimeName.CODEX,
        adapter_name=CODEX_ADAPTER_NAME,
        adapter_version=CODEX_ADAPTER_VERSION,
        output_text=final_message,
        controlled_artifact_path=controlled_artifact_path,
        output_location_class=output_location_class,
        terminal_event_sha256=terminal_event_sha256,
        command_policy_sha256=command_policy_sha256,
        full_prompt_sha256=full_prompt_sha256,
        artifact_capability=artifact_capability,
        execution_policy_sha256=execution_policy_sha256,
        execution_policy_document=execution_policy_document,
    )


def _executable_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise RuntimeTerminalFailure("runtime-executable-untrusted")
        with path.open("rb") as stream:
            while chunk := stream.read(65536):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeTerminalFailure("runtime-executable-unavailable") from exc
    return digest.hexdigest()


def _stage_executable(source: Path, workspace: Path, expected_sha256: str) -> Path:
    """Copy one verified executable inode into the private invocation root."""

    source_fd: int | None = None
    destination_fd: int | None = None
    destination = workspace / "runtime-executable"
    try:
        source_fd = os.open(
            source,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or not before.st_mode & 0o111:
            raise RuntimeTerminalFailure("runtime-executable-untrusted")
        destination_fd = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o700,
        )
        digest = hashlib.sha256()
        while chunk := os.read(source_fd, 65536):
            digest.update(chunk)
            offset = 0
            while offset < len(chunk):
                written = os.write(destination_fd, chunk[offset:])
                if written < 1:
                    raise OSError
                offset += written
        after = os.fstat(source_fd)
        named = source.lstat()

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if (
            identity(before) != identity(after)
            or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)
            or digest.hexdigest() != expected_sha256
        ):
            raise RuntimeTerminalFailure("runtime-executable-changed")
        os.fchmod(destination_fd, 0o700)
        os.fsync(destination_fd)
    except RuntimeTerminalFailure:
        raise
    except OSError as exc:
        raise RuntimeTerminalFailure("runtime-executable-unavailable") from exc
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if source_fd is not None:
            os.close(source_fd)
    if _executable_sha256(destination) != expected_sha256:
        raise RuntimeTerminalFailure("runtime-executable-changed")
    return destination


class _RetainedRuntimeInput:
    """Make the runtime consume exact bytes through one retained descriptor."""

    def __init__(self, path: Path, content: bytes) -> None:
        self.path = path
        self.content = content
        write_fd = os.open(
            path,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        self.fd = -1
        try:
            os.fchmod(write_fd, 0o600)
            offset = 0
            while offset < len(content):
                written = os.write(write_fd, content[offset:])
                if written < 1:
                    raise OSError("Runtime input write did not make progress.")
                offset += written
            os.fsync(write_fd)
            self._identity = self._stat_identity(os.fstat(write_fd))
            os.close(write_fd)
            write_fd = -1
            self.fd = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            self.validate()
        except Exception:
            if write_fd >= 0:
                os.close(write_fd)
            self.close()
            raise

    @staticmethod
    def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_uid,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    @property
    def descriptor_path(self) -> str:
        return f"/dev/fd/{self.fd}"

    def validate(self) -> None:
        if self.fd < 0:
            raise ValueError("Retained runtime input is closed.")
        before = os.fstat(self.fd)
        named = os.stat(self.path, follow_symlinks=False)
        os.lseek(self.fd, 0, os.SEEK_SET)
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(self.fd, min(remaining, 65536))
            if not chunk:
                raise ValueError("Retained runtime input is incomplete.")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(self.fd)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_uid != os.geteuid()
            or after.st_nlink != 1
            or stat.S_IMODE(after.st_mode) != 0o600
            or self._stat_identity(before) != self._identity
            or self._stat_identity(after) != self._identity
            or self._stat_identity(named) != self._identity
            or b"".join(chunks) != self.content
        ):
            raise RuntimeTerminalFailure("runtime-input-changed")
        os.lseek(self.fd, 0, os.SEEK_SET)

    def close(self) -> None:
        if getattr(self, "fd", -1) >= 0:
            os.close(self.fd)
            self.fd = -1


def _require_private_root(root: Path) -> Path:
    selected = Path(root)
    try:
        selected.mkdir(mode=0o700, parents=False, exist_ok=True)
        metadata = selected.lstat()
    except OSError as exc:
        raise RuntimeTerminalFailure("runtime-artifact-root-unavailable") from exc
    if (
        selected.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise RuntimeTerminalFailure("runtime-artifact-root-untrusted")
    return selected


def _store_output(root: Path, output_text: str) -> tuple[str, object]:
    """Quarantine runtime output through retained directory descriptors."""

    from cc.core.evaluation.artifact import (
        _ArtifactCapability,
        _open_artifact_type_directory,
        _open_root_directory,
        _read_verified_artifact,
        _require_named_directory,
        _require_private_directory,
    )

    encoded = output_text.encode()
    if not encoded or len(encoded) > _MAX_RUNTIME_OUTPUT_BYTES:
        raise RuntimeTerminalFailure("runtime-output-size-invalid")
    digest = hashlib.sha256(encoded).hexdigest()
    filename = f"{digest}.txt"
    root_fd: int | None = None
    output_fd: int | None = None
    leaf_fd: int | None = None
    capability: _ArtifactCapability | None = None
    try:
        root_fd = _open_root_directory(root)
        output_fd = _open_artifact_type_directory(
            root_fd,
            "runtime-quarantine",
            create=True,
        )
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(filename, flags, 0o600, dir_fd=output_fd)
        except FileExistsError:
            _read_verified_artifact(
                output_fd,
                filename,
                digest=digest,
                expected_content=encoded,
                maximum_size=_MAX_RUNTIME_OUTPUT_BYTES,
            )
        else:
            try:
                os.fchmod(descriptor, 0o600)
                offset = 0
                while offset < len(encoded):
                    written = os.write(descriptor, encoded[offset:])
                    if written < 1:
                        raise OSError
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(output_fd)
        os.fsync(root_fd)
        _read_verified_artifact(
            output_fd,
            filename,
            digest=digest,
            expected_content=encoded,
            maximum_size=_MAX_RUNTIME_OUTPUT_BYTES,
        )
        leaf_fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=output_fd,
        )
        metadata = _require_private_directory(
            output_fd,
            description="Evaluation runtime quarantine directory",
        )
        capability = _ArtifactCapability(
            os.dup(root_fd),
            os.dup(output_fd),
            leaf_fd,
            "runtime-quarantine",
            filename,
            encoded,
            digest,
        )
        leaf_fd = None
        capability.validate()
        _require_named_directory(
            root_fd,
            "runtime-quarantine",
            metadata,
            description="Evaluation runtime quarantine directory",
        )
    except RuntimeTerminalFailure:
        if capability is not None:
            capability.close()
            capability = None
        raise
    except (OSError, ValueError) as exc:
        if capability is not None:
            capability.close()
            capability = None
        raise RuntimeTerminalFailure("runtime-output-preservation-failed") from exc
    finally:
        if leaf_fd is not None:
            os.close(leaf_fd)
        if output_fd is not None:
            os.close(output_fd)
        if root_fd is not None:
            os.close(root_fd)
    if capability is None:
        raise RuntimeTerminalFailure("runtime-output-preservation-failed")
    return f"runtime-quarantine/{filename}", capability


def _require_safe_output(output_text: str, output_location_class: str) -> None:
    """Keep rejected runtime text out of the durable artifact namespace."""

    try:
        require_safe_synthetic_text(
            output_text,
            location_class=output_location_class,
        )
    except FixtureSafetyViolation as exc:
        raise RuntimeTerminalFailure("runtime-output-unsafe") from exc


def _initialize_empty_repository(workspace: Path) -> None:
    """Create the minimum unborn Git repository Codex requires, without hooks."""

    git = workspace / ".git"
    (git / "objects").mkdir(parents=True, mode=0o700)
    (git / "refs" / "heads").mkdir(parents=True, mode=0o700)
    (git / "HEAD").write_text("ref: refs/heads/evaluation\n", encoding="utf-8")
    (git / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
        encoding="utf-8",
    )


def _codex_projection(
    source: object, specialist: str
) -> tuple[str, tuple[dict[str, str], ...]]:
    try:
        from cc.core.evaluation.journey_runtime import _codex_specialist_projection

        return _codex_specialist_projection(source, specialist)
    except ValueError as exc:
        raise RuntimeTerminalFailure("codex-plugin-projection-invalid") from exc


def _materialize_codex_plugin(source: object, workspace: Path) -> str:
    target = workspace / "plugins" / "codex-copilot"
    target.mkdir(parents=True, mode=0o700)
    manifest_rows = []
    try:
        for item in source.snapshot.files:
            relative = PurePosixPath(item.path)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or item.mode not in {0o100644, 0o100755}
            ):
                raise RuntimeTerminalFailure("codex-plugin-projection-invalid")
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o700 if item.mode == 0o100755 else 0o600,
            )
            try:
                offset = 0
                while offset < len(item.content):
                    written = os.write(descriptor, item.content[offset:])
                    if written < 1:
                        raise OSError
                    offset += written
            finally:
                os.close(descriptor)
            manifest_rows.append(
                [item.path, item.mode, hashlib.sha256(item.content).hexdigest()]
            )
        marketplace = workspace / ".agents" / "plugins" / "marketplace.json"
        marketplace.parent.mkdir(parents=True, mode=0o700)
        marketplace.write_text(
            json.dumps(
                {
                    "name": "codex-copilot-evaluation",
                    "plugins": [
                        {
                            "name": "codex-copilot",
                            "source": {
                                "source": "local",
                                "path": "./plugins/codex-copilot",
                            },
                            "policy": {
                                "installation": "AVAILABLE",
                                "authentication": "ON_INSTALL",
                            },
                        }
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        marketplace.chmod(0o600)
    except RuntimeTerminalFailure:
        raise
    except OSError as exc:
        raise RuntimeTerminalFailure("codex-plugin-materialization-failed") from exc
    return canonical_sha256(
        {
            "tree": source.tree,
            "files": sorted(manifest_rows),
        }
    )


def _codex_source_projection_identity(source: object) -> str:
    try:
        rows = sorted(
            [
                item.path,
                item.mode,
                hashlib.sha256(item.content).hexdigest(),
            ]
            for item in source.snapshot.files
        )
        return canonical_sha256({"tree": source.tree, "files": rows})
    except (AttributeError, TypeError) as exc:
        raise RuntimeTerminalFailure("codex-plugin-projection-invalid") from exc


def _variant_roles(variant: object) -> frozenset[str]:
    from cc.core.evaluation.models import LayerVariant

    return {
        LayerVariant.FOUNDATION: frozenset({"foundation"}),
        LayerVariant.ORGANIZATION: frozenset({"foundation", "organization"}),
        LayerVariant.DEPARTMENT: frozenset(
            {"foundation", "organization", "department"}
        ),
        LayerVariant.PERSONAL: frozenset(
            {"foundation", "organization", "department", "personal"}
        ),
    }[variant]


def resolve_claude_agent_projection(
    variant: object,
    specialist: str,
) -> ClaudeAgentProjection:
    """Resolve an exact variant through the existing ladder, then verify bytes."""

    from cc.core.config import resolve_key
    from cc.core.ecosystem.manifest import load_layers, validate_layers
    from cc.core.ecosystem.policy import (
        read_git_tree_snapshot,
        verify_git_tree_release,
    )
    from cc.core.ecosystem.project_sources import resolve_all_claude_items

    configured = resolve_key("layers.manifest")
    if not configured:
        raise RuntimeTerminalFailure("claude-agent-projection-unavailable")
    try:
        layers = [
            item
            for item in load_layers(configured)
            if item.get("product") == "claude"
            and item.get("role") in _variant_roles(variant)
        ]
        validate_layers(layers)
        resolved = resolve_all_claude_items(_layers=layers).get(("agents", specialist))
        if resolved is None:
            raise RuntimeTerminalFailure("claude-agent-projection-unavailable")
        matches = [item for item in layers if item.get("id") == resolved.layer]
        if len(matches) != 1:
            raise RuntimeTerminalFailure("claude-agent-projection-unavailable")
        layer = matches[0]
        source = layer.get("source") or {}
        policy = layer.get("policy") or {}
        ref = source.get("ref")
        signers = policy.get("allowed_signers")
        if not isinstance(ref, str) or not isinstance(signers, list) or not signers:
            raise RuntimeTerminalFailure("claude-agent-projection-unsigned")
        selected = Path(resolved.path)
        repository = next(
            (
                candidate
                for candidate in (selected, *selected.parents)
                if (candidate / ".git").exists()
            ),
            None,
        )
        if repository is None:
            raise RuntimeTerminalFailure("claude-agent-projection-unavailable")
        relative_agents = selected.parent.relative_to(repository).as_posix()
        provenance = verify_git_tree_release(
            repository,
            relative_agents,
            signers,
            ref=ref,
        )
        if provenance is None:
            raise RuntimeTerminalFailure("claude-agent-projection-unverified")
        snapshot = read_git_tree_snapshot(repository, provenance.tree)
        if snapshot is None:
            raise RuntimeTerminalFailure("claude-agent-projection-unverified")
        files = [item for item in snapshot.files if item.path == selected.name]
        if len(files) != 1:
            raise RuntimeTerminalFailure("claude-agent-projection-unverified")
        content = files[0].content.decode("utf-8")
        repository_value = str(source.get("repo", ""))
        repository_identifier = (
            repository_value.rsplit(":", 1)[-1]
            .removeprefix("//")
            .split("github.com/", 1)[-1]
            .removesuffix(".git")
        )
    except RuntimeTerminalFailure:
        raise
    except (KeyError, OSError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeTerminalFailure("claude-agent-projection-unavailable") from exc
    return ClaudeAgentProjection(
        content=content,
        layer=str(layer["id"]),
        ref=_canonical_tag_ref(provenance.ref),
        tree=provenance.tree,
        signer=provenance.signer,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        tier=str(layer["role"]),
        repository_identifier=repository_identifier,
        contribution=(Path(relative_agents) / selected.name).as_posix(),
    )


RunCallable = Callable[..., subprocess.CompletedProcess[str]]


def _codex_native_executable(launcher: Path) -> Path:
    """Resolve the native Codex binary and avoid an env-selected interpreter."""

    try:
        header = launcher.read_bytes()[:128]
    except OSError as exc:
        raise RuntimeTerminalFailure("runtime-executable-unavailable") from exc
    if not header.startswith(b"#!/usr/bin/env node"):
        return launcher
    targets = {
        ("darwin", "arm64"): ("codex-darwin-arm64", "aarch64-apple-darwin"),
        ("darwin", "x86_64"): ("codex-darwin-x64", "x86_64-apple-darwin"),
        ("linux", "x86_64"): ("codex-linux-x64", "x86_64-unknown-linux-musl"),
        ("linux", "aarch64"): ("codex-linux-arm64", "aarch64-unknown-linux-musl"),
    }
    selected = targets.get((sys.platform, platform.machine().casefold()))
    if selected is None:
        raise RuntimeTerminalFailure("runtime-executable-chain-unsupported")
    package, triple = selected
    package_root = launcher.parent.parent
    candidate = (
        package_root
        / "node_modules"
        / "@openai"
        / package
        / "vendor"
        / triple
        / "bin"
        / "codex"
    )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RuntimeTerminalFailure("runtime-executable-chain-unavailable") from exc
    if not os.access(resolved, os.X_OK):
        raise RuntimeTerminalFailure("runtime-executable-chain-unavailable")
    _executable_sha256(resolved)
    return resolved


def _read_private_auth_file(source: Path) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            source,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o077
            or before.st_size < 2
            or before.st_size > 1024 * 1024
        ):
            raise RuntimeTerminalFailure("runtime-auth-source-untrusted")
        chunks = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        value = b"".join(chunks)
        after = os.fstat(descriptor)
        named = source.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino):
            raise RuntimeTerminalFailure("runtime-auth-source-changed")
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise RuntimeTerminalFailure("runtime-auth-source-untrusted")
        return value
    except RuntimeTerminalFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeTerminalFailure("runtime-auth-source-unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_private_file(path: Path, content: bytes) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written < 1:
                raise OSError
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        raise RuntimeTerminalFailure("runtime-auth-projection-failed") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _runtime_environment(
    workspace: Path,
    runtime: RuntimeName,
    *,
    codex_auth_source: Path | None = None,
) -> tuple[dict[str, str], dict[str, object]]:
    isolated_home = workspace / "runtime-home"
    isolated_tmp = workspace / "runtime-tmp"
    isolated_auth = workspace / "runtime-auth"
    for directory in (isolated_home, isolated_tmp, isolated_auth):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    environment = {
        "HOME": str(isolated_home),
        "TMPDIR": str(isolated_tmp),
        "LANG": "C.UTF-8",
    }
    semantics: dict[str, object] = {
        "HOME": "isolated-empty-home",
        "TMPDIR": "isolated-runtime-temp",
        "LANG": "fixed-c-utf8",
        "inherited_environment": [],
    }
    if runtime is RuntimeName.CLAUDE:
        account = pwd.getpwuid(os.geteuid())
        account_home = Path(account.pw_dir).resolve(strict=True)
        home_metadata = account_home.stat()
        if (
            not stat.S_ISDIR(home_metadata.st_mode)
            or home_metadata.st_uid != os.geteuid()
            or home_metadata.st_mode & 0o022
        ):
            raise RuntimeTerminalFailure("runtime-auth-source-untrusted")
        environment["HOME"] = str(account_home)
        environment["USER"] = account.pw_name
        semantics["HOME"] = "canonical-account-home-for-native-keychain-auth"
        semantics["USER"] = "canonical-effective-user-for-native-keychain-auth"
        semantics["claude_config"] = "disabled-by-safe-mode"
    else:
        source = codex_auth_source or Path.home() / ".codex" / "auth.json"
        auth = _read_private_auth_file(source)
        _write_private_file(isolated_auth / "auth.json", auth)
        environment["CODEX_HOME"] = str(isolated_auth)
        semantics["CODEX_HOME"] = "isolated-single-auth-file-projection"
        semantics["auth_projection"] = (
            "private-ephemeral-projection-no-source-or-credential-identity"
        )
    semantics["environment_keys"] = sorted(environment)
    semantics["exact_nonidentity_values"] = {"LANG": environment["LANG"]}
    return environment, semantics


def _run_process_group(
    argv: list[str],
    *,
    input: str,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[str]:
    encoded_input = input.encode("utf-8")
    with tempfile.TemporaryFile() as stdin_file:
        stdin_file.write(encoded_input)
        stdin_file.seek(0)
        process = subprocess.Popen(
            argv,
            stdin=stdin_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            shell=False,
            cwd=cwd,
            env=dict(env),
            start_new_session=True,
            pass_fds=pass_fds,
        )
    pgid = process.pid
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    sizes = {"stdout": 0, "stderr": 0}
    deadline = time.monotonic() + timeout

    def terminate_group() -> None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    selector = selectors.DefaultSelector()
    assert process.stdout is not None and process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            events = selector.select(min(remaining, 0.25))
            for key, _mask in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                channel = str(key.data)
                sizes[channel] += len(chunk)
                if sizes[channel] > _MAX_RUNTIME_OUTPUT_BYTES:
                    raise RuntimeTerminalFailure("runtime-output-size-invalid")
                (stdout_chunks if channel == "stdout" else stderr_chunks).append(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout)
        process.wait(timeout=remaining)
    finally:
        selector.close()
        terminate_group()
        if process.poll() is None:
            process.wait(timeout=1.0)
    try:
        stdout = b"".join(stdout_chunks).decode("utf-8")
        stderr = b"".join(stderr_chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeTerminalFailure("runtime-output-malformed") from exc
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def runtime_authentication_status(
    runtime: RuntimeName,
    executable: Path,
    *,
    codex_auth_source: Path | None = None,
) -> tuple[bool, str]:
    """Probe saved CLI authentication without exposing account or token fields."""

    selected = (
        _codex_native_executable(executable)
        if runtime is RuntimeName.CODEX
        else executable
    )
    with tempfile.TemporaryDirectory(prefix=f".{runtime.value}-auth-probe-") as raw:
        workspace = Path(raw)
        environment, _policy = _runtime_environment(
            workspace,
            runtime,
            codex_auth_source=codex_auth_source,
        )
        staged = _stage_executable(selected, workspace, _executable_sha256(selected))
        argv = (
            [str(staged), "auth", "status", "--json"]
            if runtime is RuntimeName.CLAUDE
            else [str(staged), "login", "status"]
        )
        try:
            result = _run_process_group(
                argv,
                input="",
                cwd=workspace,
                env=environment,
                timeout=15.0,
            )
        except (OSError, subprocess.SubprocessError, RuntimeTerminalFailure):
            return False, "auth-probe-unavailable"
    if runtime is RuntimeName.CODEX:
        return (
            (True, "authenticated")
            if result.returncode == 0
            else (False, "not-authenticated")
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, "auth-proof-malformed"
    if (
        result.returncode == 0
        and isinstance(value, Mapping)
        and value.get("loggedIn") is True
        and value.get("authMethod") not in {None, "none"}
    ):
        return True, "authenticated"
    return False, "not-authenticated"


class _NonInteractiveRuntimeAdapter:
    runtime: RuntimeName
    adapter_name: str
    adapter_version: str

    def __init__(
        self,
        prompt_packet: object,
        *,
        artifact_root: Path,
        executable: Path | None = None,
        timeout_seconds: float = 300.0,
        run: RunCallable | None = None,
    ) -> None:
        from cc.core.evaluation.matrix import RuntimePromptPacket

        if not isinstance(prompt_packet, RuntimePromptPacket):
            raise ValueError("Runtime adapter requires a verified prompt packet.")
        if (
            prompt_packet.runtime is not self.runtime
            or not prompt_packet.user_prompt_text
            or not prompt_packet.system_context_text
            or len(prompt_packet.user_prompt_text.encode()) > _MAX_RUNTIME_OUTPUT_BYTES
            or len(prompt_packet.system_context_text.encode())
            > _MAX_RUNTIME_OUTPUT_BYTES
            or any(
                source_runtime != self.runtime.value
                for source_runtime in prompt_packet.source_runtimes
            )
        ):
            raise ValueError("Runtime prompt must be non-empty and bounded.")
        if timeout_seconds <= 0 or timeout_seconds > 900:
            raise ValueError("Runtime timeout must be within 1-900 seconds.")
        self._prompt_packet = prompt_packet
        self._artifact_root = _require_private_root(artifact_root)
        selected_executable = (
            Path(executable) if executable else self._resolve_executable()
        )
        self._executable = self._normalize_executable(selected_executable)
        self._timeout = timeout_seconds
        self._run = run
        self._tool_configuration_sha256 = canonical_sha256(
            self._tool_configuration_document()
        )
        self._command_policy_sha256 = canonical_sha256(self._command_policy_document())

    @property
    def tool_configuration_sha256(self) -> str:
        return self._tool_configuration_sha256

    @property
    def effective_full_prompt_sha256(self) -> str:
        return self._effective_full_prompt_sha256()

    @property
    def command_policy_sha256(self) -> str:
        return self._command_policy_sha256

    @property
    def runtime_receipt(self) -> RuntimeReceipt:
        """Return the exact verifier-recomputable runtime contract for this adapter."""

        return RuntimeReceipt(
            runtime=self.runtime,
            executable_sha256=_executable_sha256(self._executable),
            runtime_version=None,
            model_version=self._model,
            tool_availability=(),
            adapter_name=self.adapter_name,
            adapter_version=self.adapter_version,
            capability_flags=(
                "external-mutation-prohibited",
                "native-terminal-verification",
                "noninteractive",
                "tools-disabled",
            ),
        )

    def _tool_configuration_document(self) -> Mapping[str, object]:
        return {
            "runtime": self.runtime.value,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "model_version": self._model,
            "tools": "disabled",
            "external_mutation": "prohibited",
        }

    def _command_policy_document(self) -> Mapping[str, object]:
        command_policy = getattr(self, "command_policy", None)
        if not callable(command_policy):
            raise RuntimeTerminalFailure("runtime-command-policy-unavailable")
        placeholder = (
            "CONTROLLED_SYSTEM_CONTEXT"
            if self.runtime is RuntimeName.CLAUDE
            else "CONTROLLED_FINAL_MESSAGE"
        )
        return {
            "schema_version": "1.0",
            "runtime": self.runtime.value,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "model_version": self._model,
            "executable_sha256": _executable_sha256(self._executable),
            "argv": list(command_policy(placeholder)),
            "stdin": "exact-user-prompt-packet",
            "workspace": "private-empty-git-repository",
            "environment": (
                "safe-mode-with-native-keychain-auth"
                if self.runtime is RuntimeName.CLAUDE
                else "isolated-single-auth-file-projection"
            ),
        }

    def _effective_full_prompt_sha256(self) -> str:
        return self._prompt_packet.full_prompt_sha256

    def _effective_source_receipts(self) -> tuple[Mapping[str, object], ...]:
        return self._prompt_packet.source_receipts

    def _resolve_executable(self) -> Path:
        from cc.core.executables import resolve_executable

        resolved = resolve_executable(self.runtime.value)
        if resolved is None:
            raise RuntimeTerminalFailure("runtime-executable-unavailable")
        return Path(resolved)

    def _normalize_executable(self, executable: Path) -> Path:
        return executable

    def _require_cell(self, cell: EvaluationCell) -> None:
        from cc.core.evaluation.identity import prepared_sources_match_content_receipt
        from cc.core.evaluation.matrix import runtime_configuration_identity

        actual_full_prompt_sha256 = canonical_sha256(
            {
                "system_context": self._prompt_packet.system_context_text,
                "user_input": self._prompt_packet.user_prompt_text,
            }
        )
        if (
            cell.case_id != self._prompt_packet.case_id
            or cell.revision != self._prompt_packet.revision
            or cell.variant is not self._prompt_packet.variant
            or cell.runtime_receipt.runtime is not self.runtime
            or cell.runtime_receipt.adapter_name != self.adapter_name
            or cell.runtime_receipt.adapter_version != self.adapter_version
            or cell.runtime_receipt.model_version != self._model
            or _executable_sha256(self._executable)
            != cell.runtime_receipt.executable_sha256
            or cell.prompt_evidence_sha256 != self._prompt_packet.prompt_evidence_sha256
            or cell.content_receipt.composed_content_sha256
            != self._prompt_packet.composed_content_sha256
            or not prepared_sources_match_content_receipt(
                cell.content_receipt,
                self._effective_source_receipts(),
            )
            or actual_full_prompt_sha256 != self._prompt_packet.full_prompt_sha256
            or cell.runtime_configuration_sha256
            != runtime_configuration_identity(self._prompt_packet)
            or cell.tool_configuration_sha256 != self.tool_configuration_sha256
            or cell.effective_full_prompt_sha256 != self.effective_full_prompt_sha256
            or cell.command_policy_sha256 != self.command_policy_sha256
        ):
            raise RuntimeTerminalFailure("runtime-receipt-mismatch")

    def _run_process(
        self,
        argv: list[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        pass_fds: tuple[int, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        try:
            if self._run is None:
                result = _run_process_group(
                    argv,
                    input=self._prompt_packet.user_prompt_text,
                    cwd=cwd,
                    env=environment,
                    timeout=self._timeout,
                    pass_fds=pass_fds,
                )
            else:
                result = self._run(
                    argv,
                    input=self._prompt_packet.user_prompt_text,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    check=False,
                    shell=False,
                    cwd=cwd,
                    env=dict(environment),
                    start_new_session=True,
                    pass_fds=pass_fds,
                )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeTerminalFailure("runtime-timeout") from exc
        except OSError as exc:
            raise RuntimeTerminalFailure("runtime-executable-failure") from exc
        if not isinstance(result.stdout, str) or len(result.stdout.encode()) > (
            _MAX_RUNTIME_OUTPUT_BYTES
        ):
            raise RuntimeTerminalFailure("runtime-output-size-invalid")
        return result

    def _execution_path(self, workspace: Path, cell: EvaluationCell) -> Path:
        if self._run is not None:
            return self._executable
        return _stage_executable(
            self._executable,
            workspace,
            cell.runtime_receipt.executable_sha256,
        )


class ClaudeNonInteractiveAdapter(_NonInteractiveRuntimeAdapter):
    """Claude Code adapter with tools, hooks, MCP, and persistence disabled."""

    runtime = RuntimeName.CLAUDE
    adapter_name = CLAUDE_ADAPTER_NAME
    adapter_version = CLAUDE_ADAPTER_VERSION

    def __init__(
        self,
        *args,
        model: str,
        agent_resolver: Callable[[object, str], ClaudeAgentProjection] = (
            resolve_claude_agent_projection
        ),
        **kwargs,
    ) -> None:
        if not _SESSION.fullmatch(model):
            raise ValueError("Runtime adapter requires an exact model identifier.")
        self._model = model
        prompt_packet = args[0] if args else kwargs.get("prompt_packet")
        if prompt_packet is None:
            raise ValueError("Runtime adapter requires a verified prompt packet.")
        self._agent_projection = agent_resolver(
            prompt_packet.variant,
            prompt_packet.specialist,
        )
        super().__init__(*args, **kwargs)

    def _tool_configuration_document(self) -> Mapping[str, object]:
        return {
            **super()._tool_configuration_document(),
            "agent_projection_sha256": self._agent_projection.projection_sha256,
            "command_policy": list(self.command_policy("CONTROLLED_SYSTEM_CONTEXT")),
            "specialist": self._prompt_packet.specialist,
            "environment": "safe-mode-with-native-keychain-auth",
        }

    def _effective_system_context(self) -> str:
        return (
            self._agent_projection.content
            + "\n\n"
            + self._prompt_packet.system_context_text
        )

    def _effective_full_prompt_sha256(self) -> str:
        return canonical_sha256(
            {
                "system_context": self._effective_system_context(),
                "user_input": self._prompt_packet.user_prompt_text,
            }
        )

    def _effective_source_receipts(self) -> tuple[Mapping[str, object], ...]:
        return self._prompt_packet.source_receipts + (
            self._agent_projection.source_receipt,
        )

    def command_policy(self, system_context_path: str) -> tuple[str, ...]:
        return (
            "-p",
            "--safe-mode",
            "--no-chrome",
            "--model",
            self._model,
            "--output-format",
            "json",
            "--no-session-persistence",
            "--permission-mode",
            "plan",
            "--tools",
            "",
            "--disallowedTools",
            "mcp__*",
            "--strict-mcp-config",
            "--append-system-prompt-file",
            system_context_path,
        )

    def execute(self, cell: EvaluationCell) -> RuntimeOutput:
        self._require_cell(cell)
        with tempfile.TemporaryDirectory(
            prefix=".claude-eval-", dir=self._artifact_root
        ) as temporary:
            workspace = Path(temporary)
            _initialize_empty_repository(workspace)
            system_context = _RetainedRuntimeInput(
                workspace / "system-context.md",
                self._effective_system_context().encode(),
            )
            environment, environment_policy = _runtime_environment(
                workspace,
                self.runtime,
            )
            argv = self.command_policy(system_context.descriptor_path)
            execution_path = self._execution_path(workspace, cell)
            execution_policy_document = {
                "schema_version": "1.0",
                "command_policy_sha256": self.command_policy_sha256,
                "argv": list(self.command_policy("CONTROLLED_SYSTEM_CONTEXT")),
                "environment": environment_policy,
                "staged_executable_sha256": _executable_sha256(execution_path),
                "system_context_sha256": hashlib.sha256(
                    self._effective_system_context().encode()
                ).hexdigest(),
                "source_receipts_sha256": canonical_sha256(
                    [dict(item) for item in self._effective_source_receipts()]
                ),
                "workspace": "private-empty-git-repository",
            }
            execution_policy_sha256 = canonical_sha256(execution_policy_document)
            try:
                try:
                    result = self._run_process(
                        [str(execution_path), *argv],
                        cwd=workspace,
                        environment=environment,
                        pass_fds=(system_context.fd,),
                    )
                except RuntimeTerminalFailure as exc:
                    if exc.reason != "runtime-timeout" or self._run is not None:
                        raise
                    system_context.validate()
                    receipt = _issue_runtime_timeout_receipt(
                        cell,
                        runtime=self.runtime,
                        adapter_name=self.adapter_name,
                        adapter_version=self.adapter_version,
                        execution_policy_document=execution_policy_document,
                        timeout_seconds=self._timeout,
                    )
                    raise RuntimeTerminalFailure(
                        "runtime-timeout",
                        technical_receipt=receipt,
                    ) from exc
                system_context.validate()
            finally:
                system_context.close()
        parsed = _json_object(result.stdout)
        output_text = parsed.get("result")
        if not isinstance(output_text, str):
            raise RuntimeTerminalFailure("claude-terminal-evidence-invalid")
        _require_safe_output(output_text, "private-output")
        controlled_path, artifact_capability = _store_output(
            self._artifact_root,
            output_text,
        )
        return _authenticate_claude_terminal(
            cell,
            stdout=result.stdout,
            returncode=result.returncode,
            controlled_artifact_path=controlled_path,
            output_location_class="private-output",
            command_policy_sha256=self.command_policy_sha256,
            full_prompt_sha256=self._effective_full_prompt_sha256(),
            stderr=result.stderr,
            artifact_capability=artifact_capability,
            execution_policy_sha256=execution_policy_sha256,
            execution_policy_document=execution_policy_document,
        )


class CodexNonInteractiveAdapter(_NonInteractiveRuntimeAdapter):
    """Codex adapter using ephemeral, config-free, read-only JSON execution."""

    runtime = RuntimeName.CODEX
    adapter_name = CODEX_ADAPTER_NAME
    adapter_version = CODEX_ADAPTER_VERSION

    def __init__(
        self,
        *args,
        model: str,
        source_resolver: Callable[[], object] | None = None,
        auth_source: Path | None = None,
        live_dispatch: object | None = None,
        **kwargs,
    ) -> None:
        if not _SESSION.fullmatch(model):
            raise ValueError("Runtime adapter requires an exact model identifier.")
        self._model = model
        if source_resolver is None:
            from cc.core.ecosystem.codex_plugin_source import (
                resolve_codex_plugin_source,
            )

            source_resolver = resolve_codex_plugin_source
        self._source_resolver = source_resolver
        self._auth_source = auth_source
        self._live_dispatch = live_dispatch
        if live_dispatch is not None:
            from cc.core.evaluation.codex_isolation import (
                verify_codex_live_dispatch,
            )

            if (
                not verify_codex_live_dispatch(live_dispatch)
                or getattr(live_dispatch, "model", None) != model
            ):
                raise RuntimeTerminalFailure("runtime-input-changed")
        self._source = self._source_resolver()
        if self._source is None:
            raise RuntimeTerminalFailure("codex-plugin-projection-unavailable")
        self._source_projection_sha256 = _codex_source_projection_identity(self._source)
        super().__init__(*args, **kwargs)

    def _tool_configuration_document(self) -> Mapping[str, object]:
        document = {
            **super()._tool_configuration_document(),
            "plugin_projection_sha256": self._source_projection_sha256,
            "command_policy": list(self.command_policy("CONTROLLED_FINAL_MESSAGE")),
            "environment": (
                "isolated-single-auth-file-projection"
                if self._live_dispatch is None
                else "retained-official-inputs-private-auth-projection"
            ),
        }
        if self._live_dispatch is not None:
            document["live_dispatch"] = {
                "dispatch_sha256": self._live_dispatch.dispatch_sha256,
                "authorization_sha256": self._live_dispatch.authorization_sha256,
                "permit_sha256": self._live_dispatch.permit_sha256,
                "framework_release_identity": (
                    self._live_dispatch.framework_release_identity
                ),
                "package_policy_sha256": self._live_dispatch.package_policy_sha256,
                "measurement_receipt_sha256": (
                    self._live_dispatch.measurement_receipt_sha256
                ),
                "native_binary_sha256": self._live_dispatch.native_binary_sha256,
                "model_catalog_sha256": self._live_dispatch.model_catalog_sha256,
                "tool_registry_sha256": self._live_dispatch.tool_registry_sha256,
            }
        return document

    def _normalize_executable(self, executable: Path) -> Path:
        return _codex_native_executable(executable)

    def command_policy(
        self,
        final_message_path: str,
        *,
        model_catalog_path: str = "CONTROLLED_MODEL_CATALOG",
        workspace_path: str = "CONTROLLED_WORKSPACE",
    ) -> tuple[str, ...]:
        if self._live_dispatch is not None:
            policy = (
                "--ask-for-approval",
                "never",
                "exec",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--strict-config",
                "-C",
                workspace_path,
                "--model",
                self._model,
                "--sandbox",
                "read-only",
                "-c",
                f"model_catalog_json={json.dumps(model_catalog_path)}",
                "-c",
                'web_search="disabled"',
                "-c",
                "tools.web_search=false",
                "-c",
                "tools.update_plan={enabled=false}",
                "-c",
                "tools.experimental_request_user_input={enabled=false}",
            )
            for feature in _CODEX_LIVE_DISABLED_FEATURES:
                policy += ("--disable", feature)
            return policy + (
                "--output-last-message",
                final_message_path,
                "-",
            )
        policy = (
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--strict-config",
            "--ignore-user-config",
            "--model",
            self._model,
        )
        for feature in _CODEX_DISABLED_FEATURES:
            policy += ("--disable", feature)
        return policy + (
            "--json",
            "--output-last-message",
            final_message_path,
            "-",
        )

    def _execute_with_paths(
        self,
        cell: EvaluationCell,
        *,
        execution_path: Path,
        model_catalog_path: Path | None,
        dispatch_context: object | None,
    ) -> tuple[
        subprocess.CompletedProcess[str],
        str,
        str,
        Mapping[str, object],
    ]:
        self._require_cell(cell)
        with tempfile.TemporaryDirectory(
            prefix=".codex-eval-", dir=self._artifact_root
        ) as temporary:
            workspace = Path(temporary)
            _initialize_empty_repository(workspace)
            source = self._source_resolver()
            if (
                source is None
                or _codex_source_projection_identity(source)
                != self._source_projection_sha256
            ):
                raise RuntimeTerminalFailure("codex-plugin-projection-unavailable")
            content, sources = _codex_projection(source, self._prompt_packet.specialist)
            declared_plugin_sources = tuple(
                item
                for item in self._prompt_packet.source_receipts
                if item.get("adapter_version") == "codex-plugin-v1"
            )
            if (
                tuple(dict(item) for item in sources) != declared_plugin_sources
                or content not in self._prompt_packet.system_context_text
            ):
                raise RuntimeTerminalFailure("codex-plugin-projection-changed")
            if (
                _materialize_codex_plugin(source, workspace)
                != self._source_projection_sha256
            ):
                raise RuntimeTerminalFailure("codex-plugin-projection-changed")
            instructions = workspace / "AGENTS.md"
            instructions.write_text(
                self._prompt_packet.system_context_text, encoding="utf-8"
            )
            instructions.chmod(0o600)
            final_path = workspace / "final-message.txt"
            descriptor = os.open(
                final_path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                original = os.fstat(descriptor)
                environment, environment_policy = _runtime_environment(
                    workspace,
                    self.runtime,
                    codex_auth_source=self._auth_source,
                )
                argv = list(
                    self.command_policy(
                        str(final_path),
                        model_catalog_path=(
                            str(model_catalog_path)
                            if model_catalog_path is not None
                            else "CONTROLLED_MODEL_CATALOG"
                        ),
                        workspace_path=str(workspace),
                    )
                )
                selected_execution_path = (
                    execution_path
                    if dispatch_context is not None
                    else self._execution_path(workspace, cell)
                )
                execution_policy_document = {
                    "schema_version": "1.0",
                    "command_policy_sha256": self.command_policy_sha256,
                    "argv": list(self.command_policy("CONTROLLED_FINAL_MESSAGE")),
                    "environment": environment_policy,
                    "staged_executable_sha256": _executable_sha256(
                        selected_execution_path
                    ),
                    "plugin_projection_sha256": self._source_projection_sha256,
                    "source_receipts_sha256": (
                        self._prompt_packet.source_receipts_sha256
                    ),
                    "project_instructions_sha256": hashlib.sha256(
                        self._prompt_packet.system_context_text.encode()
                    ).hexdigest(),
                    "workspace": "private-empty-git-repository",
                }
                if dispatch_context is not None:
                    execution_policy_document["live_dispatch"] = {
                        "context_sha256": dispatch_context.context_sha256,
                        "dispatch_sha256": dispatch_context.dispatch_sha256,
                        "authorization_sha256": (dispatch_context.authorization_sha256),
                        "permit_sha256": dispatch_context.permit_sha256,
                        "native_binary_sha256": _executable_sha256(
                            selected_execution_path
                        ),
                        "model_catalog_sha256": hashlib.sha256(
                            model_catalog_path.read_bytes()
                        ).hexdigest(),
                        "model": dispatch_context.model,
                    }
                execution_policy_sha256 = canonical_sha256(execution_policy_document)
                result = self._run_process(
                    [str(selected_execution_path), *argv],
                    cwd=workspace,
                    environment=environment,
                )
                named_before = os.stat(final_path, follow_symlinks=False)
                retained_before = os.fstat(descriptor)

                def inode_identity(value: os.stat_result) -> tuple[int, ...]:
                    return (
                        value.st_dev,
                        value.st_ino,
                        value.st_uid,
                        value.st_nlink,
                        stat.S_IMODE(value.st_mode),
                    )

                def stable_identity(value: os.stat_result) -> tuple[int, ...]:
                    return (
                        *inode_identity(value),
                        value.st_size,
                        value.st_mtime_ns,
                        value.st_ctime_ns,
                    )

                if (
                    not stat.S_ISREG(named_before.st_mode)
                    or not stat.S_ISREG(retained_before.st_mode)
                    or inode_identity(original) != inode_identity(retained_before)
                    or stable_identity(retained_before) != stable_identity(named_before)
                    or retained_before.st_size > _MAX_RUNTIME_OUTPUT_BYTES
                ):
                    raise RuntimeTerminalFailure("codex-final-message-untrusted")
                os.lseek(descriptor, 0, os.SEEK_SET)
                chunks = []
                total = 0
                while chunk := os.read(descriptor, 65536):
                    total += len(chunk)
                    if total > _MAX_RUNTIME_OUTPUT_BYTES:
                        raise RuntimeTerminalFailure("codex-final-message-untrusted")
                    chunks.append(chunk)
                raw_message = b"".join(chunks)
                if len(raw_message) > _MAX_RUNTIME_OUTPUT_BYTES:
                    raise RuntimeTerminalFailure("codex-final-message-untrusted")
                final_message = raw_message.decode("utf-8")
                retained_after = os.fstat(descriptor)
                named_after = os.stat(final_path, follow_symlinks=False)
                if stable_identity(retained_before) != stable_identity(
                    retained_after
                ) or stable_identity(retained_after) != stable_identity(named_after):
                    raise RuntimeTerminalFailure("codex-final-message-untrusted")
            except (OSError, UnicodeDecodeError) as exc:
                raise RuntimeTerminalFailure("codex-final-message-unavailable") from exc
            finally:
                os.close(descriptor)
        return (
            result,
            final_message,
            execution_policy_sha256,
            execution_policy_document,
        )

    def execute(self, cell: EvaluationCell) -> RuntimeOutput:
        if self._live_dispatch is None:
            if self._run is None:
                raise RuntimeTerminalFailure("codex-no-tool-isolation-unavailable")
            values = self._execute_with_paths(
                cell,
                execution_path=self._executable,
                model_catalog_path=None,
                dispatch_context=None,
            )
        else:
            from cc.core.evaluation.codex_isolation import (
                CodexIsolationUnavailable,
                verify_codex_live_dispatch,
                verify_codex_live_dispatch_context,
            )

            dispatch = self._live_dispatch
            # The retained official-input producer is approved, but the live
            # network/auth launch profile is not. Only injected, no-network
            # consumer tests may cross this boundary until that independent
            # production capability is verifier-issued.
            if self._run is None:
                try:
                    dispatch.close()
                except CodexIsolationUnavailable as exc:
                    raise RuntimeTerminalFailure("runtime-input-changed") from exc
                raise RuntimeTerminalFailure("codex-no-tool-isolation-unavailable")
            if not verify_codex_live_dispatch(dispatch):
                raise RuntimeTerminalFailure("runtime-input-changed")

            def consume(context):
                if (
                    not verify_codex_live_dispatch_context(context)
                    or context.model != self._model
                    or _executable_sha256(context.native_binary)
                    != cell.runtime_receipt.executable_sha256
                    or hashlib.sha256(context.model_catalog.read_bytes()).hexdigest()
                    != dispatch.model_catalog_sha256
                ):
                    raise RuntimeTerminalFailure("runtime-input-changed")
                return self._execute_with_paths(
                    cell,
                    execution_path=context.native_binary,
                    model_catalog_path=context.model_catalog,
                    dispatch_context=context,
                )

            try:
                values = dispatch.run_once(consume)
            except RuntimeTerminalFailure:
                raise
            except CodexIsolationUnavailable as exc:
                raise RuntimeTerminalFailure("runtime-input-changed") from exc
            finally:
                try:
                    dispatch.close()
                except CodexIsolationUnavailable as exc:
                    raise RuntimeTerminalFailure("runtime-input-changed") from exc

        result, final_message, execution_policy_sha256, execution_policy_document = (
            values
        )
        _require_safe_output(final_message, "private-output")
        controlled_path, artifact_capability = _store_output(
            self._artifact_root,
            final_message,
        )
        return _authenticate_codex_terminal(
            cell,
            stdout=result.stdout,
            returncode=result.returncode,
            final_message=final_message,
            controlled_artifact_path=controlled_path,
            output_location_class="private-output",
            command_policy_sha256=self.command_policy_sha256,
            full_prompt_sha256=self._effective_full_prompt_sha256(),
            stderr=result.stderr,
            artifact_capability=artifact_capability,
            execution_policy_sha256=execution_policy_sha256,
            execution_policy_document=execution_policy_document,
        )


def verify_authenticated_completion(
    cell: EvaluationCell,
    output: RuntimeOutput,
    output_sha256: str,
) -> RuntimeCompletionReceipt | None:
    """Return the sealed receipt only when every cell/output binding matches."""

    if not isinstance(output, AuthenticatedRuntimeOutput):
        return None
    if (
        output._completion_authority is not _COMPLETION_AUTHORITY
        or _AUTHENTICATED_OUTPUT_SEALS.get(output._seal) is not output
    ):
        return None
    receipt = output.completion_receipt
    if (
        receipt._authority is not _COMPLETION_AUTHORITY
        or _COMPLETION_RECEIPT_SEALS.get(receipt._seal) is not receipt
    ):
        return None
    if (
        receipt.runtime is not cell.runtime_receipt.runtime
        or receipt.adapter_name != cell.runtime_receipt.adapter_name
        or receipt.adapter_version != cell.runtime_receipt.adapter_version
        or receipt.model_version != cell.runtime_receipt.model_version
        or receipt.invocation_envelope_sha256
        != cell.consumption_receipt.invocation_envelope_sha256
        or receipt.runtime_configuration_sha256 != cell.runtime_configuration_sha256
        or receipt.tool_configuration_sha256 != cell.tool_configuration_sha256
        or receipt.full_prompt_sha256 != cell.effective_full_prompt_sha256
        or receipt.command_policy_sha256 != cell.command_policy_sha256
        or receipt.output_sha256 != output_sha256
        or receipt.artifact_path_sha256
        != hashlib.sha256(output.controlled_artifact_path.encode()).hexdigest()
    ):
        return None
    document = runtime_completion_receipt_document(receipt)
    return receipt if canonical_sha256(document) == receipt.evidence_sha256 else None


def close_authenticated_runtime_output(output: RuntimeOutput) -> None:
    """Revoke an authenticated output after durable evidence has retained it."""

    if not isinstance(output, AuthenticatedRuntimeOutput):
        return
    if _AUTHENTICATED_OUTPUT_SEALS.get(output._seal) is not output:
        return
    _AUTHENTICATED_OUTPUT_SEALS.pop(output._seal, None)
    receipt = output.completion_receipt
    if _COMPLETION_RECEIPT_SEALS.get(receipt._seal) is receipt:
        _COMPLETION_RECEIPT_SEALS.pop(receipt._seal, None)
    close = getattr(output._artifact_capability, "close", None)
    if callable(close):
        close()


__all__ = [
    "AuthenticatedRuntimeOutput",
    "ClaudeNonInteractiveAdapter",
    "CodexNonInteractiveAdapter",
    "RuntimeCompletionReceipt",
    "RuntimeTerminalFailure",
    "close_authenticated_runtime_output",
    "runtime_completion_receipt_document",
    "verify_authenticated_completion",
]
