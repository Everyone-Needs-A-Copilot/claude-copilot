"""Production witness for protocol-selected, Knowledge-backed Agent dispatches.

The protocol remains the only router and ``extensions_resolver`` remains the
only Knowledge resolver.  This module validates and persists their decisions;
it never infers either one.  A PreToolUse receipt proves only that dispatch was
observed and authorized, not that the specialist ran or completed successfully.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from cc.core.evaluation.journey import CapabilityReceipt, RouteEvent, RouteTrace

RUNTIME_SCHEMA_VERSION = "2.1"
RUNTIME_ADAPTER_VERSION = "journey-adapter-v2.1"
BEGIN_TITLE = "Journey v2.1 begin: "
PREPARE_TITLE = "Journey v2.1 preparation: "
BIND_TITLE = "Journey v2.1 prompt binding: "
DISPATCH_TITLE = "Journey v2.1 dispatch authorization: "
PAUSE_TITLE = "Journey v2.1 pause capsule: "
FINAL_TITLE = "Journey v2.1 final authorization evidence: "
MARKER_HEADER = "CC-JOURNEY-INVOCATION: "
KNOWLEDGE_BEGIN = "CC-JOURNEY-KNOWLEDGE-BEGIN"
KNOWLEDGE_END = "CC-JOURNEY-KNOWLEDGE-END"
_RUN = re.compile(r"^j2-(\d+)-([0-9a-f]{24})$")
_MARKER = re.compile(r"^[0-9a-f]{48}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:@/+\-]{0,255}$")
_SAFE_SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_SECRET = re.compile(r"(?i)(bearer|password|secret|token|api[_-]?key|credential)")
_SECURITY_AUTHORITY = object()
_COMMON_RECORD_KEYS = {"schema_version", "adapter_version", "task_id", "record_type", "run_id"}
_RECORD_KEYS = {
    "begin": {"session_id_sha256", "prompt_sha256", "route", "security", "capability"},
    "prepare": {
        "stage_index", "specialist", "invocation_marker", "composed_content_sha256",
        "sources", "security_sha256",
    },
    "prompt_binding": {
        "stage_index", "specialist", "invocation_marker", "prompt_sha256",
        "prepared_sha256",
    },
    "dispatch_authorization": {
        "stage_index", "specialist", "session_id_sha256", "prompt_sha256",
        "composed_content_sha256", "sources", "security", "claim",
    },
    "pause_capsule": {"capsule", "capsule_sha256"},
    "final_authorization": {
        "result_json", "result_sha256", "dispatch_authorizations_sha256",
    },
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _safe_text(value: str, *, source: bool = False) -> str:
    pattern = _SAFE_SOURCE if source else _SAFE_TEXT
    if (
        not pattern.fullmatch(value)
        or value.startswith("/")
        or ".." in value.split("/")
        or _SECRET.search(value)
    ):
        raise ValueError("Journey persisted identity is unsafe.")
    return value


def _validate_record_keys(payload: Mapping[str, Any]) -> None:
    kind = payload.get("record_type")
    allowed = _RECORD_KEYS.get(str(kind))
    if allowed is None or set(payload) != _COMMON_RECORD_KEYS | allowed:
        raise ValueError("Journey ledger payload fields are invalid.")


@dataclass(frozen=True)
class SecurityAuthorization:
    """Opaque verifier-issued mandatory security authorization."""

    state: str
    reason: str
    policy_sha256: str
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _SECURITY_AUTHORITY
            or self.state not in {"allowed", "denied", "unavailable"}
            or not _DIGEST.fullmatch(self.policy_sha256)
        ):
            raise ValueError("Mandatory security authorization is invalid.")
        _safe_text(self.reason)

    def public_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
            "reason": self.reason,
            "policy_sha256": self.policy_sha256,
        }


class MandatorySecurityVerifier:
    """Issue an authenticated receipt from one closed mandatory policy probe."""

    def __init__(self, probe: Callable[[Mapping[str, Any]], tuple[str, str]] | None = None) -> None:
        self._probe = probe or self._default_probe

    @staticmethod
    def _default_probe(context: Mapping[str, Any]) -> tuple[str, str]:
        # This is deliberately structural and closed.  It does not grant user
        # or provider authority; it proves that only the supported Claude,
        # task-bound, protocol-emitted contract reached the runtime boundary.
        if context.get("runtime") != "claude":
            return "denied", "unsupported-runtime"
        if not _DIGEST.fullmatch(str(context.get("route_sha256", ""))):
            return "denied", "invalid-route-authority"
        return "allowed", "protocol-route-authorized"

    def authorize(self, context: Mapping[str, Any]) -> SecurityAuthorization:
        canonical_context = _canonical(dict(context))
        try:
            result = self._probe(dict(context))
            if not isinstance(result, tuple) or len(result) != 2:
                raise TypeError
            state, reason = result
            if not isinstance(state, str) or not isinstance(reason, str):
                raise TypeError
        except (OSError, PermissionError, TimeoutError, TypeError, ValueError):
            state, reason = "unavailable", "security-verifier-unavailable"
        return SecurityAuthorization(
            state,
            _safe_text(reason),
            _sha("mandatory-security-v1\n" + canonical_context + "\n" + state + "\n" + reason),
            _SECURITY_AUTHORITY,
        )


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
    prompt_sha256: str | None = None

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
    """Strict, lazy binding to Task Copilot's public work-product API."""

    def __init__(
        self,
        task_id: int,
        *,
        store_wp: Callable[..., Mapping[str, Any]] | None = None,
        get_wp: Callable[..., Mapping[str, Any]] | None = None,
        list_wps: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        lock_dir: Path | None = None,
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
        self._lock_dir = lock_dir

    def append(self, title: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        record = dict(payload)
        record.update({
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "adapter_version": RUNTIME_ADAPTER_VERSION,
            "task_id": self.task_id,
        })
        return self._store_wp(
            task_id=self.task_id,
            type_="evidence",
            title=title,
            content=_canonical(record),
            agent="cc-journey",
        )

    @staticmethod
    def _row_type(row: Mapping[str, Any]) -> object:
        return row.get("type_", row.get("type"))

    def rows(self) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
        result: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        task_filter = None if self.task_id == 0 else self.task_id
        for summary in self._list_wps(task=task_filter, type_="evidence"):
            try:
                summary_id = int(summary["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Journey ledger summary identity is malformed.") from exc
            row = self._get_wp(wp_id=summary_id)
            title = str(row.get("title", ""))
            if not title.startswith("Journey v2.1 "):
                continue
            if (
                int(row.get("id", -1)) != summary_id
                or int(row.get("task_id", -1)) < 1
                or (self.task_id and int(row.get("task_id", -1)) != self.task_id)
                or self._row_type(row) != "evidence"
                or row.get("agent") != "cc-journey"
                or str(summary.get("title", "")) != title
                or int(summary.get("task_id", -1)) != int(row["task_id"])
                or self._row_type(summary) != "evidence"
            ):
                raise ValueError("Journey ledger row identity is invalid.")
            try:
                payload = json.loads(str(row["content"]))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Journey ledger contains malformed evidence.") from exc
            if (
                not isinstance(payload, dict)
                or payload.get("schema_version") != RUNTIME_SCHEMA_VERSION
                or payload.get("adapter_version") != RUNTIME_ADAPTER_VERSION
                or payload.get("task_id") != int(row["task_id"])
            ):
                raise ValueError("Journey ledger payload identity is invalid.")
            _validate_record_keys(payload)
            result.append((row, payload))
        return result

    def _private_lock_dir(self) -> Path:
        path = self._lock_dir or Path(tempfile.gettempdir()) / f"cc-journey-{os.getuid()}"
        try:
            path.mkdir(mode=0o700, parents=False, exist_ok=True)
            info = path.lstat()
        except OSError as exc:
            raise RuntimeError("Journey lock directory is unavailable.") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError("Journey lock directory is unsafe.")
        return path

    @contextmanager
    def claim(self, identity: str) -> Iterator[None]:
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,160}", identity):
            raise ValueError("Journey lock identity is malformed.")
        path = self._private_lock_dir() / f"{self.task_id}-{identity}.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise RuntimeError("Journey lock acquisition failed.") from exc
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            os.close(descriptor)
            raise RuntimeError("Journey lock file is unsafe.")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
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


def _route_from(value: Mapping[str, Any]) -> RouteTrace:
    try:
        return RouteTrace(
            classification=_safe_text(str(value["classification"])),
            specialists=tuple(_safe_text(str(item), source=True) for item in value["specialists"]),
            runtime=_safe_text(str(value["runtime"]), source=True),
            contract_version=str(value["contract_version"]),
            events=tuple(
                RouteEvent(
                    kind=str(item["kind"]),
                    specialist=_safe_text(str(item["specialist"]), source=True),
                    reason=_safe_text(str(item["reason"])),
                )
                for item in value["events"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Stored protocol route is malformed.") from exc


def _source_dict(receipt: Any) -> dict[str, Any]:
    result = {
        key: getattr(receipt, key)
        for key in (
            "layer", "repository", "ref", "tree", "signer", "contribution",
            "content_sha256", "runtime", "adapter_version",
        )
    }
    for key, value in result.items():
        if not isinstance(value, str):
            raise ValueError("Knowledge source receipt is malformed.")
        if key in {"tree", "content_sha256"}:
            if not re.fullmatch(r"[0-9a-f]{40,64}", value):
                raise ValueError("Knowledge source receipt is malformed.")
        else:
            _safe_text(value, source=True)
    return result


def _validate_sources(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("Knowledge source receipts are missing.")
    allowed = {
        "layer", "repository", "ref", "tree", "signer", "contribution",
        "content_sha256", "runtime", "adapter_version",
    }
    result = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != allowed:
            raise ValueError("Knowledge source receipt is malformed.")
        proxy = type("Receipt", (), dict(item))()
        result.append(_source_dict(proxy))
    return tuple(result)


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


def _security_context(begin: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": begin["task_id"],
        "run_id": begin["run_id"],
        "session_sha256": begin["session_id_sha256"],
        "runtime": begin["route"]["runtime"],
        "route_sha256": _sha(_canonical(begin["route"])),
        "prompt_sha256": begin["prompt_sha256"],
    }


def _require_security(begin: Mapping[str, Any], verifier: MandatorySecurityVerifier) -> dict[str, str]:
    receipt = verifier.authorize(_security_context(begin))
    if receipt.state != "allowed":
        raise PermissionError("mandatory-security-not-allowed")
    public = receipt.public_dict()
    stored = begin.get("security")
    if stored is not None and public != stored:
        raise PermissionError("mandatory-security-changed")
    return public


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
    security: MandatorySecurityVerifier | None = None,
) -> dict[str, Any]:
    if task_id < 1 or not _DIGEST.fullmatch(prompt_sha256):
        raise ValueError("Task or prompt identity is malformed.")
    if not session_id or len(session_id) > 256 or any(ord(char) < 32 for char in session_id):
        raise ValueError("Session identity is required.")
    trace = RouteTrace(
        classification=_safe_text(classification),
        specialists=tuple(_safe_text(item, source=True) for item in specialists),
        runtime=_safe_text(runtime, source=True),
        contract_version=RUNTIME_SCHEMA_VERSION,
        events=tuple(
            RouteEvent(item["kind"], _safe_text(item["specialist"], source=True), _safe_text(item["reason"]))
            for item in events
        ),
    )
    run_id = f"j2-{task_id}-{secrets.token_hex(12)}"
    payload: dict[str, Any] = {
        "record_type": "begin",
        "run_id": run_id,
        "task_id": task_id,
        "session_id_sha256": _sha(session_id),
        "prompt_sha256": prompt_sha256,
        "route": asdict(trace),
    }
    payload["security"] = _require_security(payload, security or MandatorySecurityVerifier())
    payload["capability"] = asdict((capability or CliCopilotHealthCapabilityAdapter()).invoke(case_id=run_id))
    capability_detail = str(payload["capability"].get("detail", ""))
    if capability_detail and not re.fullmatch(r"sha256:[0-9a-f]{64}", capability_detail):
        raise ValueError("Capability diagnostic is not redacted.")
    selected = ledger or TcJourneyLedger(task_id)
    with selected.claim("begin-" + _sha(session_id)):
        if _active_runs_for_session(session_id, selected):
            raise ValueError("Session already has an active journey.")
        selected.append(BEGIN_TITLE + run_id, payload)
    return payload | {"schema_version": RUNTIME_SCHEMA_VERSION, "adapter_version": RUNTIME_ADAPTER_VERSION}


def _expected_title(payload: Mapping[str, Any]) -> str:
    run_id = str(payload.get("run_id", ""))
    kind = payload.get("record_type")
    if kind == "begin":
        return BEGIN_TITLE + run_id
    if kind == "prepare":
        return f"{PREPARE_TITLE}{run_id}:{payload.get('stage_index')}"
    if kind == "prompt_binding":
        return f"{BIND_TITLE}{run_id}:{payload.get('stage_index')}"
    if kind == "dispatch_authorization":
        return f"{DISPATCH_TITLE}{run_id}:{payload.get('stage_index')}"
    if kind == "pause_capsule":
        return PAUSE_TITLE + run_id
    if kind == "final_authorization":
        return FINAL_TITLE + run_id
    raise ValueError("Journey record type is invalid.")


def _state(run_id: str, ledger: TcJourneyLedger) -> dict[str, Any]:
    buckets = {key: [] for key in ("begin", "prepare", "prompt_binding", "dispatch_authorization", "pause_capsule", "final_authorization")}
    for row, payload in ledger.rows():
        if payload.get("run_id") != run_id:
            continue
        if payload.get("task_id") != _task_from_run(run_id) or row.get("title") != _expected_title(payload):
            raise ValueError("Journey evidence identity is invalid.")
        kind = str(payload.get("record_type", ""))
        if kind not in buckets:
            raise ValueError("Journey evidence type is invalid.")
        buckets[kind].append(payload)
    if len(buckets["begin"]) != 1 or len(buckets["pause_capsule"]) > 1 or len(buckets["final_authorization"]) > 1:
        raise ValueError("Journey evidence is missing or ambiguous.")
    begin = buckets["begin"][0]
    route_trace = _route_from(begin.get("route", {}))
    route = route_trace.specialists
    dispatches = sorted(buckets["dispatch_authorization"], key=lambda item: int(item["stage_index"]))
    completed = tuple(item["specialist"] for item in dispatches)
    if completed != route[: len(completed)] or tuple(item["stage_index"] for item in dispatches) != tuple(range(len(dispatches))):
        raise ValueError("Journey dispatch ledger is out of route order.")
    for kind in ("prepare", "prompt_binding", "dispatch_authorization"):
        indices = [int(item["stage_index"]) for item in buckets[kind]]
        if len(indices) != len(set(indices)):
            raise ValueError("Journey stage evidence is ambiguous.")
    if buckets["final_authorization"] and len(completed) != len(route):
        raise ValueError("Journey final evidence is premature.")
    return buckets | {"begin_record": begin, "route": route, "completed": completed}


def _public_state(run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    if state["final_authorization"]:
        result_json = state["final_authorization"][0].get("result_json")
        if not isinstance(result_json, str):
            raise ValueError("Final authorization evidence is malformed.")
        result = json.loads(result_json)
        if _sha(result_json) != state["final_authorization"][0].get("result_sha256"):
            raise ValueError("Final authorization evidence changed.")
        return result
    completed = tuple(state["completed"])
    route = tuple(state["route"])
    begin = state["begin_record"]
    preparations = {int(item["stage_index"]): item for item in state["prepare"]}
    bindings = {int(item["stage_index"]): item for item in state["prompt_binding"]}
    next_index = len(completed)
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "adapter_version": RUNTIME_ADAPTER_VERSION,
        "run_id": run_id,
        "task_id": begin["task_id"],
        "status": "paused" if state["pause_capsule"] else "active",
        "evidence_claim": "dispatch_observed_and_authorized_only",
        "route": begin["route"],
        "prompt_sha256": begin["prompt_sha256"],
        "security": begin["security"],
        "capability": begin["capability"],
        "dispatch_authorized_specialists": completed,
        "next_specialist": route[next_index] if next_index < len(route) else None,
        "next_stage_state": (
            "prompt_bound" if next_index in bindings else "prepared" if next_index in preparations else "unprepared"
        ) if next_index < len(route) else None,
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
    security: MandatorySecurityVerifier | None = None,
) -> PreparedInvocation:
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    with selected.claim(run_id):
        state = _state(run_id, selected)
        stage = len(state["completed"])
        if stage >= len(state["route"]) or state["route"][stage] != specialist:
            raise ValueError("Specialist is not the exact next protocol stage.")
        _require_security(state["begin_record"], security or MandatorySecurityVerifier())
        payload, raw_sources = resolver(specialist)
        sources = _validate_sources(raw_sources)
        if not payload or KNOWLEDGE_BEGIN in payload or KNOWLEDGE_END in payload:
            raise ValueError("Required Knowledge payload is malformed.")
        digest = _sha(payload)
        matches = [item for item in state["prepare"] if item.get("stage_index") == stage]
        if matches:
            prepared = matches[0]
            if prepared.get("specialist") != specialist or prepared.get("composed_content_sha256") != digest or prepared.get("sources") != list(sources):
                raise ValueError("Knowledge changed after preparation.")
            marker = str(prepared["invocation_marker"])
        else:
            marker = secrets.token_hex(24)
            selected.append(
                f"{PREPARE_TITLE}{run_id}:{stage}",
                {
                    "record_type": "prepare", "run_id": run_id, "stage_index": stage,
                    "specialist": specialist, "invocation_marker": marker,
                    "composed_content_sha256": digest, "sources": list(sources),
                    "security_sha256": _sha(_canonical(state["begin_record"]["security"])),
                },
            )
        binding = next((item for item in state["prompt_binding"] if item.get("stage_index") == stage), None)
    fragment = f"{MARKER_HEADER}{marker}\n{KNOWLEDGE_BEGIN}\n{payload}\n{KNOWLEDGE_END}"
    return PreparedInvocation(
        run_id, specialist, stage, marker, payload, fragment, digest, sources,
        str(binding["prompt_sha256"]) if binding else None,
    )


def bind_prompt(
    run_id: str,
    specialist: str,
    prompt_sha256: str,
    *,
    ledger: TcJourneyLedger | None = None,
) -> dict[str, Any]:
    if not _DIGEST.fullmatch(prompt_sha256):
        raise ValueError("Full Agent prompt digest is malformed.")
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    with selected.claim(run_id):
        state = _state(run_id, selected)
        stage = len(state["completed"])
        prepared = [item for item in state["prepare"] if item.get("stage_index") == stage]
        if len(prepared) != 1 or prepared[0].get("specialist") != specialist:
            raise ValueError("Exact next Agent prompt has not been prepared.")
        bindings = [item for item in state["prompt_binding"] if item.get("stage_index") == stage]
        if bindings:
            if bindings[0].get("prompt_sha256") != prompt_sha256:
                raise ValueError("Full Agent prompt changed after binding.")
        else:
            selected.append(
                f"{BIND_TITLE}{run_id}:{stage}",
                {
                    "record_type": "prompt_binding", "run_id": run_id,
                    "stage_index": stage, "specialist": specialist,
                    "invocation_marker": prepared[0]["invocation_marker"],
                    "prompt_sha256": prompt_sha256,
                    "prepared_sha256": _sha(_canonical(prepared[0])),
                },
            )
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "state": "prompt_bound",
        "run_id": run_id,
        "stage_index": stage,
        "prompt_sha256": prompt_sha256,
    }


def _capsule(run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    begin = state["begin_record"]
    stage = len(state["completed"])
    prepared = next((item for item in state["prepare"] if item.get("stage_index") == stage), None)
    binding = next((item for item in state["prompt_binding"] if item.get("stage_index") == stage), None)
    return {
        "capsule_version": "journey-pause-v1",
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "adapter_version": RUNTIME_ADAPTER_VERSION,
        "task_id": begin["task_id"],
        "run_id": run_id,
        "route": begin["route"],
        "prompt_sha256": begin["prompt_sha256"],
        "capability": begin["capability"],
        "security": begin["security"],
        "dispatch_authorizations": list(state["dispatch_authorization"]),
        "prepared": prepared,
        "prompt_binding": binding,
        "next_stage_index": stage if stage < len(state["route"]) else None,
        "next_specialist": state["route"][stage] if stage < len(state["route"]) else None,
    }


def pause_run(
    run_id: str,
    *,
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
    security: MandatorySecurityVerifier | None = None,
) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    initial = _state(run_id, selected)
    next_index = len(initial["completed"])
    if next_index < len(initial["route"]) and not any(
        item.get("stage_index") == next_index for item in initial["prepare"]
    ):
        prepare_run(
            run_id, initial["route"][next_index], ledger=selected,
            resolver=resolver, security=security,
        )
    with selected.claim(run_id):
        state = _state(run_id, selected)
        if state["final_authorization"]:
            return _public_state(run_id, state)
        capsule = _capsule(run_id, state)
        digest = _sha(_canonical(capsule))
        if state["pause_capsule"]:
            stored = state["pause_capsule"][0]
            if stored.get("capsule") != capsule or stored.get("capsule_sha256") != digest:
                raise ValueError("Journey pause capsule no longer matches runtime state.")
        else:
            selected.append(
                PAUSE_TITLE + run_id,
                {"record_type": "pause_capsule", "run_id": run_id, "capsule": capsule, "capsule_sha256": digest},
            )
        return _public_state(run_id, _state(run_id, selected))


def _active_runs_for_session(session_id: str, ledger: TcJourneyLedger) -> list[str]:
    runs = []
    for row, payload in ledger.rows():
        if payload.get("record_type") == "begin" and payload.get("session_id_sha256") == _sha(session_id):
            run_id = str(payload.get("run_id", ""))
            state = _state(run_id, TcJourneyLedger(
                _task_from_run(run_id), store_wp=ledger._store_wp, get_wp=ledger._get_wp,
                list_wps=ledger._list_wps, lock_dir=ledger._lock_dir,
            ))
            if not state["final_authorization"]:
                runs.append(run_id)
    return sorted(set(runs))


def resume_run(
    task_id: int,
    *,
    run_id: str | None = None,
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
    security: MandatorySecurityVerifier | None = None,
) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(task_id)
    states: dict[str, dict[str, Any]] = {}
    for row, payload in selected.rows():
        if payload.get("record_type") == "begin":
            candidate = str(payload.get("run_id", ""))
            states[candidate] = _state(candidate, selected)
    if run_id is None:
        active = [key for key, value in states.items() if value["pause_capsule"] and not value["final_authorization"]]
        if not active:
            return {"schema_version": RUNTIME_SCHEMA_VERSION, "state": "no_journey"}
        if len(active) != 1:
            raise ValueError("Journey continuation is ambiguous.")
        run_id = active[0]
    if _task_from_run(run_id) != task_id or run_id not in states:
        raise ValueError("Journey continuation identity is invalid.")
    state = states[run_id]
    if state["final_authorization"]:
        return _public_state(run_id, state)
    if len(state["pause_capsule"]) != 1:
        raise ValueError("Journey continuation capsule is missing.")
    capsule = _capsule(run_id, state)
    stored = state["pause_capsule"][0]
    if stored.get("capsule") != capsule or stored.get("capsule_sha256") != _sha(_canonical(capsule)):
        raise ValueError("Journey continuation capsule changed.")
    _require_security(state["begin_record"], security or MandatorySecurityVerifier())
    public = _public_state(run_id, state)
    if public["next_specialist"] is not None:
        public["prepared_invocation"] = prepare_run(
            run_id, public["next_specialist"], ledger=selected, resolver=resolver,
            security=security,
        ).public_dict()
    return public


def _store_final(run_id: str, ledger: TcJourneyLedger) -> None:
    state = _state(run_id, ledger)
    if state["final_authorization"] or len(state["completed"]) != len(state["route"]):
        return
    # Build the terminal value before adding the terminal row.  Its claim is
    # deliberately dispatch authorization, never specialist completion.
    result = _public_state(run_id, state)
    result.update({
        "status": "all_dispatches_authorized",
        "next_specialist": None,
        "next_stage_state": None,
    })
    result_json = _canonical(result)
    ledger.append(
        FINAL_TITLE + run_id,
        {
            "record_type": "final_authorization", "run_id": run_id,
            "result_json": result_json, "result_sha256": _sha(result_json),
            "dispatch_authorizations_sha256": _sha(_canonical(state["dispatch_authorization"])),
        },
    )


def verify_dispatch(
    *,
    session_id: str,
    specialist: str,
    marker: str,
    prompt_sha256: str,
    knowledge_sha256: str,
    ledger_factory: Callable[[int], TcJourneyLedger] = TcJourneyLedger,
    resolver: Callable[[str], tuple[str, tuple[dict[str, Any], ...]]] = resolve_specialist_knowledge,
    security: MandatorySecurityVerifier | None = None,
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
    candidates = [
        payload for row, payload in probe.rows()
        if payload.get("record_type") == "prepare" and payload.get("invocation_marker") == marker
    ]
    if len(candidates) != 1:
        raise ValueError("dispatch-marker-stale-or-ambiguous")
    prepared = candidates[0]
    run_id = str(prepared.get("run_id", ""))
    ledger = ledger_factory(_task_from_run(run_id))
    with ledger.claim(run_id):
        state = _state(run_id, ledger)
        stage = len(state["completed"])
        if state["begin_record"].get("session_id_sha256") != _sha(session_id):
            raise ValueError("dispatch-session-mismatch")
        if prepared.get("stage_index") != stage or prepared.get("specialist") != specialist:
            raise ValueError("dispatch-route-order-mismatch")
        scoped_preparations = [
            item for item in state["prepare"]
            if item.get("stage_index") == stage
            and item.get("invocation_marker") == marker
        ]
        if len(scoped_preparations) != 1 or scoped_preparations[0] != prepared:
            raise ValueError("dispatch-preparation-row-mismatch")
        bindings = [item for item in state["prompt_binding"] if item.get("stage_index") == stage]
        if len(bindings) != 1 or bindings[0].get("prompt_sha256") != prompt_sha256:
            raise ValueError("dispatch-prompt-not-bound")
        _require_security(state["begin_record"], security or MandatorySecurityVerifier())
        content, raw_sources = resolver(specialist)
        sources = _validate_sources(raw_sources)
        if (
            _sha(content) != knowledge_sha256
            or knowledge_sha256 != prepared.get("composed_content_sha256")
            or list(sources) != prepared.get("sources")
        ):
            raise ValueError("dispatch-knowledge-changed")
        ledger.append(
            f"{DISPATCH_TITLE}{run_id}:{stage}",
            {
                "record_type": "dispatch_authorization", "run_id": run_id,
                "stage_index": stage, "specialist": specialist,
                "session_id_sha256": _sha(session_id),
                "prompt_sha256": prompt_sha256,
                "composed_content_sha256": knowledge_sha256,
                "sources": list(sources),
                "security": state["begin_record"]["security"],
                "claim": "dispatch_observed_and_authorized_only",
            },
        )
        _store_final(run_id, ledger)
    return {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "state": "dispatch_authorized",
        "evidence_claim": "dispatch_observed_and_authorized_only",
        "run_id": run_id,
        "stage_index": stage,
        "dispatch_sha256": prompt_sha256,
    }


__all__ = [
    "CliCopilotHealthCapabilityAdapter", "MandatorySecurityVerifier",
    "PreparedInvocation", "SecurityAuthorization", "TcJourneyLedger",
    "begin_run", "bind_prompt", "inspect_run", "pause_run", "prepare_run",
    "resume_run", "resolve_specialist_knowledge", "verify_dispatch",
]
