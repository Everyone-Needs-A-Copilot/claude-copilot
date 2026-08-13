"""Production witness for the existing protocol, Knowledge, hook, and tc path.

This module deliberately does not classify prompts or rank Knowledge.  It
accepts the route emitted by ``protocol.md`` and consumes only the existing
extension resolver's selected output.  Task Copilot work products are the
durable append-only dispatch ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cc.core.evaluation.journey import CapabilityReceipt, RouteEvent, RouteTrace

RUNTIME_SCHEMA_VERSION = "2.0"
RUNTIME_ADAPTER_VERSION = "journey-adapter-v2"
BEGIN_TITLE = "Journey v2 begin: "
PREPARE_TITLE = "Journey v2 preparation: "
DISPATCH_TITLE = "Journey v2 dispatch: "
_RUN = re.compile(r"^j2-(\d+)-([0-9a-f]{24})$")
_MARKER = re.compile(r"\[CC_JOURNEY_MARKER:([0-9a-f]{48})\]")
_BEGIN = "[CC_JOURNEY_KNOWLEDGE_BEGIN]"
_END = "[CC_JOURNEY_KNOWLEDGE_END]"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class PreparedInvocation:
    run_id: str
    specialist: str
    invocation_marker: str
    knowledge_payload: str
    agent_prompt_fragment: str
    composed_content_sha256: str
    sources: tuple[Mapping[str, Any], ...]

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


class CliCopilotHealthCapabilityAdapter:
    """Closed, optional, read-only CLI Copilot health probe."""

    def __init__(
        self,
        *,
        resolver: Callable[[str], Path | None] | None = None,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout: float = 4.0,
    ) -> None:
        if resolver is None:
            from cc.core.executables import resolve_executable

            resolver = resolve_executable
        self._resolver = resolver
        self._run = run
        self._timeout = timeout

    def invoke(self, *, case_id: str) -> CapabilityReceipt:
        executable = self._resolver("copilot")
        if executable is None:
            return CapabilityReceipt("cli-copilot-health", "unavailable")
        argv = [str(executable), "--json", "health"]
        try:
            result = self._run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CapabilityReceipt("cli-copilot-health", "timeout")
        except OSError:
            return CapabilityReceipt("cli-copilot-health", "unavailable")
        detail = "sha256:" + _sha((result.stdout or "")[:8192] + (result.stderr or "")[:8192])
        if result.returncode != 0:
            return CapabilityReceipt("cli-copilot-health", "nonzero", detail)
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return CapabilityReceipt("cli-copilot-health", "malformed", detail)
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            return CapabilityReceipt("cli-copilot-health", "malformed", detail)
        return CapabilityReceipt("cli-copilot-health", "available", detail)


class TcJourneyLedger:
    """Lazy binding to Task Copilot's public work-product API."""

    def __init__(
        self,
        task_id: int,
        *,
        store_wp: Callable[..., Mapping[str, Any]] | None = None,
        get_wp: Callable[..., Mapping[str, Any]] | None = None,
        list_wps: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        if store_wp is None or get_wp is None or list_wps is None:
            try:
                from tc.api import get_wp as tc_get_wp
                from tc.api import list_wps as tc_list_wps
                from tc.api import store_wp as tc_store_wp
            except ImportError as exc:
                raise RuntimeError("Task Copilot is unavailable; journey state cannot continue.") from exc
            store_wp, get_wp, list_wps = tc_store_wp, tc_get_wp, tc_list_wps
        self.task_id = task_id
        self._store_wp = store_wp
        self._get_wp = get_wp
        self._list_wps = list_wps

    def append(self, title: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._store_wp(
            task_id=self.task_id,
            type_="evidence",
            title=title,
            content=_canonical(payload),
            agent="cc-journey",
        )

    def rows(self) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
        result = []
        task_filter = None if self.task_id == 0 else self.task_id
        for summary in self._list_wps(task=task_filter, type_="evidence"):
            row = self._get_wp(wp_id=int(summary["id"]))
            try:
                payload = json.loads(str(row["content"]))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Journey ledger contains malformed evidence.") from exc
            if not isinstance(payload, dict):
                raise ValueError("Journey ledger contains malformed evidence.")
            result.append((row, payload))
        return result


def _task_from_run(run_id: str) -> int:
    match = _RUN.fullmatch(run_id)
    if match is None:
        raise ValueError("Journey run identifier is malformed.")
    return int(match.group(1))


def _source_dict(receipt: Any) -> dict[str, Any]:
    return {
        "layer": receipt.layer,
        "repository": receipt.repository,
        "ref": receipt.ref,
        "tree": receipt.tree,
        "signer": receipt.signer,
        "contribution": receipt.contribution,
        "content_sha256": receipt.content_sha256,
        "runtime": receipt.runtime,
        "adapter_version": receipt.adapter_version,
    }


def resolve_specialist_knowledge(specialist: str) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Consume the one existing resolver and require its signed projection."""
    from cc.core.extensions_resolver import (
        ACTION_APPLY,
        compose_agent_content_with_receipts,
        resolve_extension,
    )

    resolution = resolve_extension(specialist)
    if resolution.action != ACTION_APPLY or not resolution.contributions:
        raise ValueError("Required authenticated Knowledge is unavailable.")
    # This is the payload the existing resolver selected.  Do not add a
    # journey-specific repo walk, precedence comparison, or fallback.
    composed = compose_agent_content_with_receipts(resolution, "")
    receipts = composed.receipts
    if not receipts or any(not item.is_authenticated for item in receipts):
        raise ValueError("Required authenticated Knowledge is unavailable.")
    return composed.content, tuple(_source_dict(item) for item in receipts)


def begin_run(
    *,
    task_id: int,
    runtime: str,
    classification: str,
    specialists: Sequence[str],
    events: Sequence[Mapping[str, str]],
    prompt_sha256: str,
    session_id: str = "",
    ledger: TcJourneyLedger | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", prompt_sha256):
        raise ValueError("Prompt SHA-256 is malformed.")
    trace = RouteTrace(
        classification=classification,
        specialists=tuple(specialists),
        runtime=runtime,
        contract_version=RUNTIME_SCHEMA_VERSION,
        events=tuple(RouteEvent(**item) for item in events),
    )
    run_id = f"j2-{task_id}-{secrets.token_hex(12)}"
    payload = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "adapter_version": RUNTIME_ADAPTER_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "session_id": session_id,
        "prompt_sha256": prompt_sha256,
        "route": asdict(trace),
        "capability": asdict(CliCopilotHealthCapabilityAdapter().invoke(case_id=run_id)),
    }
    (ledger or TcJourneyLedger(task_id)).append(BEGIN_TITLE + run_id, payload)
    return payload


def _state(run_id: str, ledger: TcJourneyLedger) -> dict[str, Any]:
    begins: list[Mapping[str, Any]] = []
    preparations: list[Mapping[str, Any]] = []
    dispatches: list[Mapping[str, Any]] = []
    for row, payload in ledger.rows():
        title = str(row.get("title", ""))
        if payload.get("run_id") != run_id:
            continue
        if title == BEGIN_TITLE + run_id:
            begins.append(payload)
        elif title.startswith(PREPARE_TITLE + run_id + ":"):
            preparations.append(payload)
        elif title.startswith(DISPATCH_TITLE + run_id + ":"):
            dispatches.append(payload)
    if len(begins) != 1:
        raise ValueError("Journey begin evidence is missing or ambiguous.")
    route = tuple(begins[0]["route"]["specialists"])
    ordered_dispatch = sorted(dispatches, key=lambda item: int(item["stage_index"]))
    completed = tuple(item["specialist"] for item in ordered_dispatch)
    if completed != route[: len(completed)] or len(set(completed)) != len(completed):
        raise ValueError("Journey dispatch ledger is out of route order.")
    return {
        "begin": begins[0],
        "preparations": preparations,
        "dispatches": ordered_dispatch,
        "route": route,
        "completed": completed,
    }


def prepare_run(
    run_id: str,
    specialist: str,
    *,
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
) -> PreparedInvocation:
    task_id = _task_from_run(run_id)
    selected = ledger or TcJourneyLedger(task_id)
    state = _state(run_id, selected)
    stage = len(state["completed"])
    if stage >= len(state["route"]) or state["route"][stage] != specialist:
        raise ValueError("Specialist is not the exact next protocol stage.")
    payload, sources = resolver(specialist)
    if not payload or not sources or _BEGIN in payload or _END in payload:
        raise ValueError("Required Knowledge payload is malformed.")
    digest = _sha(payload)
    matches = [
        item
        for item in state["preparations"]
        if item.get("stage_index") == stage and item.get("specialist") == specialist
    ]
    if len(matches) > 1:
        raise ValueError("Journey preparation evidence is ambiguous.")
    if matches:
        prepared = matches[0]
        if prepared.get("composed_content_sha256") != digest or prepared.get("sources") != list(sources):
            raise ValueError("Knowledge changed after preparation.")
        marker = str(prepared["invocation_marker"])
    else:
        marker = secrets.token_hex(24)
        selected.append(
            f"{PREPARE_TITLE}{run_id}:{stage}",
            {
                "run_id": run_id,
                "stage_index": stage,
                "specialist": specialist,
                "invocation_marker": marker,
                "composed_content_sha256": digest,
                "sources": list(sources),
            },
        )
    fragment = f"[CC_JOURNEY_MARKER:{marker}]\n{_BEGIN}\n{payload}\n{_END}"
    return PreparedInvocation(run_id, specialist, marker, payload, fragment, digest, sources)


def verify_dispatch_hook(
    hook_payload: Mapping[str, Any],
    *,
    ledger_factory: Callable[[int], TcJourneyLedger] = TcJourneyLedger,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
) -> dict[str, Any]:
    if hook_payload.get("tool_name") != "Agent" or hook_payload.get("agent_type"):
        return {"allowed": True, "active": False}
    tool_input = hook_payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("Agent hook payload is malformed.")
    prompt = tool_input.get("prompt")
    specialist = tool_input.get("subagent_type")
    if not isinstance(prompt, str) or not isinstance(specialist, str):
        raise ValueError("Agent hook payload is malformed.")
    marker_match = _MARKER.search(prompt)
    if marker_match is None:
        session_id = str(hook_payload.get("session_id", ""))
        probe = ledger_factory(0)
        active = []
        for row, payload in probe.rows():
            if (
                row.get("title", "").startswith(BEGIN_TITLE)
                and payload.get("session_id") == session_id
            ):
                candidate_run = str(payload.get("run_id", ""))
                candidate = _state(candidate_run, ledger_factory(_task_from_run(candidate_run)))
                if len(candidate["completed"]) < len(candidate["route"]):
                    active.append(candidate_run)
        if active:
            raise ValueError("Active journey dispatch requires its exact next invocation marker.")
        return {"allowed": True, "active": False}
    marker = marker_match.group(1)

    # The marker contains no authority. Locate its unique tc preparation row.
    # tc's public list API permits an all-task evidence scan for this bounded
    # hook lookup; the run id then binds all subsequent reads to one task.
    probe = ledger_factory(0)
    candidates = []
    for row, payload in probe.rows():
        if row.get("title", "").startswith(PREPARE_TITLE) and payload.get("invocation_marker") == marker:
            candidates.append(payload)
    if len(candidates) != 1:
        raise ValueError("Journey invocation marker is stale or ambiguous.")
    prepared = candidates[0]
    run_id = str(prepared["run_id"])
    ledger = ledger_factory(_task_from_run(run_id))
    state = _state(run_id, ledger)
    stage = len(state["completed"])
    if prepared.get("stage_index") != stage or prepared.get("specialist") != specialist:
        raise ValueError("Journey dispatch is not the exact next specialist.")
    current_payload, current_sources = resolver(specialist)
    expected_fragment = (
        f"[CC_JOURNEY_MARKER:{marker}]\n{_BEGIN}\n{current_payload}\n{_END}"
    )
    if expected_fragment not in prompt or _sha(current_payload) != prepared.get("composed_content_sha256"):
        raise ValueError("Journey Knowledge payload changed before dispatch.")
    if list(current_sources) != prepared.get("sources"):
        raise ValueError("Journey Knowledge provenance changed before dispatch.")
    if any(item.get("stage_index") == stage for item in state["dispatches"]):
        raise ValueError("Journey stage was already dispatched.")
    dispatch_sha256 = _sha(prompt)
    ledger.append(
        f"{DISPATCH_TITLE}{run_id}:{stage}",
        {
            "run_id": run_id,
            "stage_index": stage,
            "specialist": specialist,
            "session_id_sha256": _sha(str(hook_payload.get("session_id", ""))),
            "dispatch_sha256": dispatch_sha256,
            "composed_content_sha256": prepared["composed_content_sha256"],
            "sources": prepared["sources"],
        },
    )
    return {"allowed": True, "active": True, "run_id": run_id, "dispatch_sha256": dispatch_sha256}


__all__ = [
    "CliCopilotHealthCapabilityAdapter",
    "PreparedInvocation",
    "TcJourneyLedger",
    "begin_run",
    "prepare_run",
    "resolve_specialist_knowledge",
    "verify_dispatch_hook",
]
