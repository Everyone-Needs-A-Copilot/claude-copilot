"""Production ledger for an existing protocol route and Knowledge resolver.

This module is deliberately a witness, not a router.  It accepts an explicit
route chosen by the protocol, consumes the existing resolver's authenticated
composition, and records Task Copilot evidence for actual dispatches.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import secrets
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from cc.core.evaluation.journey import CapabilityReceipt, RouteEvent, RouteTrace

RUNTIME_SCHEMA_VERSION = "2.0"
RUNTIME_ADAPTER_VERSION = "journey-adapter-v2"
BEGIN_TITLE = "Journey v2 begin: "
PREPARE_TITLE = "Journey v2 preparation: "
DISPATCH_TITLE = "Journey v2 dispatch: "
PAUSE_TITLE = "Journey v2 pause: "
COMPLETION_TITLE = "Journey v2 completion: "
MARKER_HEADER = "CC-JOURNEY-INVOCATION: "
KNOWLEDGE_BEGIN = "CC-JOURNEY-KNOWLEDGE-BEGIN"
KNOWLEDGE_END = "CC-JOURNEY-KNOWLEDGE-END"
_RUN = re.compile(r"^j2-(\d+)-([0-9a-f]{24})$")
_MARKER = re.compile(r"^[0-9a-f]{48}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class PreparedInvocation:
    run_id: str
    specialist: str
    stage_index: int
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
        del case_id
        executable = self._resolver("copilot")
        if executable is None or not Path(executable).is_absolute():
            return CapabilityReceipt("cli-copilot-health", "unavailable")
        try:
            result = self._run(
                [str(executable), "--json", "health"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return CapabilityReceipt("cli-copilot-health", "timeout")
        except OSError:
            return CapabilityReceipt("cli-copilot-health", "unavailable")
        bounded = (result.stdout or "")[:8192] + (result.stderr or "")[:8192]
        detail = "sha256:" + _sha(bounded)
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
                raise RuntimeError(
                    "Task Copilot is unavailable; journey state cannot continue."
                ) from exc
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
        result: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        task_filter = None if self.task_id == 0 else self.task_id
        for summary in self._list_wps(task=task_filter, type_="evidence"):
            row = self._get_wp(wp_id=int(summary["id"]))
            title = str(row.get("title", ""))
            if not title.startswith("Journey v2 "):
                continue
            try:
                payload = json.loads(str(row["content"]))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Journey ledger contains malformed evidence.") from exc
            if not isinstance(payload, dict):
                raise ValueError("Journey ledger contains malformed evidence.")
            result.append((row, payload))
        return result

    @contextmanager
    def claim(self, identity: str) -> Iterator[None]:
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,160}", identity):
            raise ValueError("Journey lock identity is malformed.")
        path = Path(tempfile.gettempdir()) / f"cc-journey-{self.task_id}-{identity}.lock"
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _task_from_run(run_id: str) -> int:
    match = _RUN.fullmatch(run_id)
    if match is None:
        raise ValueError("Journey run identifier is malformed.")
    return int(match.group(1))


def _source_dict(receipt: Any) -> dict[str, Any]:
    return {
        key: getattr(receipt, key)
        for key in (
            "layer", "repository", "ref", "tree", "signer", "contribution",
            "content_sha256", "runtime", "adapter_version",
        )
    }


def resolve_specialist_knowledge(specialist: str) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Consume the existing resolver without adding precedence or fallback."""
    from cc.core.extensions_resolver import (
        ACTION_APPLY,
        compose_agent_content_with_receipts,
        resolve_extension,
    )

    resolution = resolve_extension(specialist)
    if resolution.action != ACTION_APPLY or not resolution.contributions:
        raise ValueError("Required authenticated Knowledge is unavailable.")
    composed = compose_agent_content_with_receipts(resolution, "")
    if (
        not composed.content
        or not composed.receipts
        or composed.content_sha256 != _sha(composed.content)
        or any(not item.is_authenticated for item in composed.receipts)
    ):
        raise ValueError("Required authenticated Knowledge is unavailable.")
    return composed.content, tuple(_source_dict(item) for item in composed.receipts)


def begin_run(
    *,
    task_id: int,
    runtime: str,
    classification: str,
    specialists: Sequence[str],
    events: Sequence[Mapping[str, str]],
    prompt_sha256: str,
    session_id: str,
    ledger: TcJourneyLedger | None = None,
    capability: CliCopilotHealthCapabilityAdapter | None = None,
) -> dict[str, Any]:
    if task_id < 1 or not _DIGEST.fullmatch(prompt_sha256):
        raise ValueError("Task or prompt identity is malformed.")
    if not session_id or len(session_id) > 256:
        raise ValueError("Session identity is required.")
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
        "capability": asdict((capability or CliCopilotHealthCapabilityAdapter()).invoke(case_id=run_id)),
    }
    selected = ledger or TcJourneyLedger(task_id)
    with selected.claim("begin-" + _sha(session_id)):
        active = _active_runs_for_session(session_id, selected)
        if active:
            raise ValueError("Session already has an active journey.")
        selected.append(BEGIN_TITLE + run_id, payload)
    return payload


def _state(run_id: str, ledger: TcJourneyLedger) -> dict[str, Any]:
    begins: list[Mapping[str, Any]] = []
    preparations: list[Mapping[str, Any]] = []
    dispatches: list[Mapping[str, Any]] = []
    pauses: list[Mapping[str, Any]] = []
    completions: list[Mapping[str, Any]] = []
    for row, payload in ledger.rows():
        if payload.get("run_id") != run_id:
            continue
        title = str(row.get("title", ""))
        if title == BEGIN_TITLE + run_id:
            begins.append(payload)
        elif title.startswith(PREPARE_TITLE + run_id + ":"):
            preparations.append(payload)
        elif title.startswith(DISPATCH_TITLE + run_id + ":"):
            dispatches.append(payload)
        elif title.startswith(PAUSE_TITLE + run_id):
            pauses.append(payload)
        elif title == COMPLETION_TITLE + run_id:
            completions.append(payload)
    if len(begins) != 1 or len(completions) > 1:
        raise ValueError("Journey evidence is missing or ambiguous.")
    route = tuple(begins[0]["route"]["specialists"])
    ordered = sorted(dispatches, key=lambda item: int(item["stage_index"]))
    completed = tuple(item["specialist"] for item in ordered)
    if completed != route[: len(completed)] or len(ordered) != len({item["stage_index"] for item in ordered}):
        raise ValueError("Journey dispatch ledger is out of route order.")
    if completions and len(completed) != len(route):
        raise ValueError("Journey completion evidence is premature.")
    return {
        "begin": begins[0], "preparations": preparations, "dispatches": ordered,
        "pauses": pauses, "completions": completions, "route": route,
        "completed": completed,
    }


def _public_state(run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    completed = tuple(state["completed"])
    route = tuple(state["route"])
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": state["begin"]["task_id"],
        "status": "completed" if len(completed) == len(route) else ("paused" if state["pauses"] else "active"),
        "route": state["begin"]["route"],
        "capability": state["begin"]["capability"],
        "completed_specialists": completed,
        "next_specialist": route[len(completed)] if len(completed) < len(route) else None,
    }


def inspect_run(run_id: str, *, ledger: TcJourneyLedger | None = None) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    return _public_state(run_id, _state(run_id, selected))


def prepare_run(
    run_id: str,
    specialist: str,
    *,
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
) -> PreparedInvocation:
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    with selected.claim(run_id):
        state = _state(run_id, selected)
        stage = len(state["completed"])
        if stage >= len(state["route"]) or state["route"][stage] != specialist:
            raise ValueError("Specialist is not the exact next protocol stage.")
        payload, sources = resolver(specialist)
        if not payload or not sources or KNOWLEDGE_BEGIN in payload or KNOWLEDGE_END in payload:
            raise ValueError("Required Knowledge payload is malformed.")
        digest = _sha(payload)
        matches = [item for item in state["preparations"] if item.get("stage_index") == stage]
        if len(matches) > 1:
            raise ValueError("Journey preparation evidence is ambiguous.")
        if matches:
            prepared = matches[0]
            if prepared.get("specialist") != specialist or prepared.get("composed_content_sha256") != digest or prepared.get("sources") != list(sources):
                raise ValueError("Knowledge changed after preparation.")
            marker = str(prepared["invocation_marker"])
        else:
            marker = secrets.token_hex(24)
            selected.append(
                f"{PREPARE_TITLE}{run_id}:{stage}",
                {"run_id": run_id, "stage_index": stage, "specialist": specialist,
                 "invocation_marker": marker, "composed_content_sha256": digest,
                 "sources": list(sources)},
            )
    fragment = f"{MARKER_HEADER}{marker}\n{KNOWLEDGE_BEGIN}\n{payload}\n{KNOWLEDGE_END}"
    return PreparedInvocation(run_id, specialist, stage, marker, payload, fragment, digest, sources)


def pause_run(run_id: str, *, ledger: TcJourneyLedger | None = None) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    with selected.claim(run_id):
        state = _state(run_id, selected)
        if state["completions"]:
            return _public_state(run_id, state)
        if not state["pauses"]:
            selected.append(PAUSE_TITLE + run_id, {"run_id": run_id, "completed_specialists": list(state["completed"])})
        return _public_state(run_id, _state(run_id, selected))


def _active_runs_for_session(session_id: str, ledger: TcJourneyLedger) -> list[str]:
    runs = []
    for row, payload in ledger.rows():
        if str(row.get("title", "")).startswith(BEGIN_TITLE) and payload.get("session_id") == session_id:
            run_id = str(payload.get("run_id", ""))
            if not _state(run_id, TcJourneyLedger(_task_from_run(run_id), store_wp=ledger._store_wp, get_wp=ledger._get_wp, list_wps=ledger._list_wps))["completions"]:
                runs.append(run_id)
    return sorted(set(runs))


def resume_run(
    task_id: int,
    *,
    run_id: str | None = None,
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(task_id)
    candidates = sorted({str(payload.get("run_id")) for row, payload in selected.rows() if str(row.get("title", "")).startswith(BEGIN_TITLE)})
    if run_id is None:
        active = [item for item in candidates if not _state(item, selected)["completions"]]
        if len(active) != 1:
            raise ValueError("Journey continuation is missing or ambiguous.")
        run_id = active[0]
    if _task_from_run(run_id) != task_id or run_id not in candidates:
        raise ValueError("Journey continuation identity is invalid.")
    state = _state(run_id, selected)
    public = _public_state(run_id, state)
    if public["next_specialist"] is not None:
        public["prepared_invocation"] = prepare_run(run_id, public["next_specialist"], ledger=selected, resolver=resolver).public_dict()
    return public


def verify_dispatch(
    *,
    session_id: str,
    specialist: str,
    marker: str,
    prompt_sha256: str,
    knowledge_sha256: str,
    ledger_factory: Callable[[int], TcJourneyLedger] = TcJourneyLedger,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
) -> dict[str, Any]:
    if not session_id or not specialist or not _DIGEST.fullmatch(prompt_sha256):
        raise ValueError("dispatch-arguments-malformed")
    probe = ledger_factory(0)
    if not marker:
        if _active_runs_for_session(session_id, probe):
            raise ValueError("active-journey-marker-required")
        return {"schema_version": RUNTIME_SCHEMA_VERSION, "state": "no_active"}
    if not _MARKER.fullmatch(marker) or not _DIGEST.fullmatch(knowledge_sha256):
        raise ValueError("dispatch-marker-malformed")
    candidates = [payload for row, payload in probe.rows() if str(row.get("title", "")).startswith(PREPARE_TITLE) and payload.get("invocation_marker") == marker]
    if len(candidates) != 1:
        raise ValueError("dispatch-marker-stale-or-ambiguous")
    prepared = candidates[0]
    run_id = str(prepared.get("run_id", ""))
    ledger = ledger_factory(_task_from_run(run_id))
    with ledger.claim(run_id):
        state = _state(run_id, ledger)
        stage = len(state["completed"])
        if state["begin"].get("session_id") != session_id:
            raise ValueError("dispatch-session-mismatch")
        if prepared.get("stage_index") != stage or prepared.get("specialist") != specialist:
            raise ValueError("dispatch-route-order-mismatch")
        content, sources = resolver(specialist)
        if _sha(content) != knowledge_sha256 or knowledge_sha256 != prepared.get("composed_content_sha256") or list(sources) != prepared.get("sources"):
            raise ValueError("dispatch-knowledge-changed")
        ledger.append(
            f"{DISPATCH_TITLE}{run_id}:{stage}",
            {"run_id": run_id, "stage_index": stage, "specialist": specialist,
             "session_id_sha256": _sha(session_id), "dispatch_sha256": prompt_sha256,
             "composed_content_sha256": knowledge_sha256, "sources": list(sources)},
        )
        if stage + 1 == len(state["route"]):
            ledger.append(COMPLETION_TITLE + run_id, {"run_id": run_id, "dispatch_sha256": prompt_sha256})
    return {"schema_version": RUNTIME_SCHEMA_VERSION, "state": "dispatch_authorized", "run_id": run_id, "stage_index": stage, "dispatch_sha256": prompt_sha256}


__all__ = [
    "CliCopilotHealthCapabilityAdapter", "PreparedInvocation", "TcJourneyLedger",
    "begin_run", "inspect_run", "pause_run", "prepare_run", "resume_run",
    "resolve_specialist_knowledge", "verify_dispatch",
]
