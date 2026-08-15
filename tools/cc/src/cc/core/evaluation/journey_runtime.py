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
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from cc.core.evaluation.journey import CapabilityReceipt, RouteEvent, RouteTrace

RUNTIME_SCHEMA_VERSION = "2.1"
RUNTIME_ADAPTER_VERSION = "journey-adapter-v2.1"
BEGIN_TITLE = "Journey v2.1 begin evidence"
PREPARE_TITLE = "Journey v2.1 preparation evidence"
BIND_TITLE = "Journey v2.1 prompt binding evidence"
DISPATCH_TITLE = "Journey v2.1 dispatch evidence"
PAUSE_TITLE = "Journey v2.1 pause evidence"
FINAL_TITLE = "Journey v2.1 final evidence"
MARKER_HEADER = "CC-JOURNEY-INVOCATION: "
KNOWLEDGE_BEGIN = "CC-JOURNEY-KNOWLEDGE-BEGIN"
KNOWLEDGE_END = "CC-JOURNEY-KNOWLEDGE-END"
_RUN = re.compile(r"^j2-(\d+)-([0-9a-f]{24})$")
_MARKER = re.compile(r"^[0-9a-f]{48}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SOURCE_REPOSITORY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,127})?$"
)
_SOURCE_REF = re.compile(
    r"^(?:refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/+\-]{0,191}|"
    r"sha256:[0-9a-f]{64})$"
)
_BARE_SEMVER_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")
_SOURCE_SIGNER = re.compile(
    r"^(?:SHA256:[A-Za-z0-9+/=_-]{4,128}|[a-z][a-z0-9-]{0,63})$"
)
_SOURCE_CONTRIBUTION = re.compile(r"^[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*$")
_SECRET = re.compile(r"(?i)(bearer|password|secret|token|api[_-]?key|credential)")
_CREDENTIAL_SHAPE = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})"
)
_EMAIL = re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}")
_PRIVATE_PATH = re.compile(r"(?i)(?:^|/)(?:Users|home|private|tmp|var|Volumes)(?:/|$)")


def _platform_global_lock_path(platform: str = sys.platform) -> str:
    """Return a stable, root-owned system directory used only as a lock FD."""

    if platform == "darwin":
        # `/tmp` is a symlink on macOS; the no-follow descriptor must bind the
        # canonical root-owned sticky directory instead.
        return "/private/tmp"
    if platform.startswith("linux"):
        # Hosted Linux provides `/tmp` itself as the root-owned sticky system
        # directory.  Retain its directory descriptor; never create a lock
        # file in a user-controlled temporary directory.
        return "/tmp"
    raise RuntimeError("Journey global locking is unsupported on this platform.")


_GLOBAL_LOCK_PATH = _platform_global_lock_path()
_SECURITY_AUTHORITY = object()
_ISSUED_SECURITY_AUTHORIZATIONS: dict[int, "SecurityAuthorization"] = {}
_COMMON_RECORD_KEYS = {
    "schema_version",
    "adapter_version",
    "task_id",
    "record_type",
    "run_id",
}
_RECORD_KEYS = {
    "begin": {"session_id_sha256", "prompt_sha256", "route", "security", "capability"},
    "prepare": {
        "stage_index",
        "specialist",
        "variant",
        "runtime",
        "invocation_marker",
        "composed_content_sha256",
        "sources",
        "security_sha256",
    },
    "prompt_binding": {
        "stage_index",
        "specialist",
        "invocation_marker",
        "prompt_sha256",
        "prepared_sha256",
    },
    "dispatch_authorization": {
        "stage_index",
        "specialist",
        "variant",
        "runtime",
        "session_id_sha256",
        "prompt_sha256",
        "composed_content_sha256",
        "sources",
        "security",
        "claim",
        "invocation_marker_sha256",
    },
    "pause_capsule": {"generation", "capsule", "capsule_sha256"},
    "final_authorization": {
        "result_json",
        "result_sha256",
        "dispatch_authorizations_sha256",
    },
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _has_disclosure(value: str) -> bool:
    return bool(
        value.startswith("/")
        or ".." in value.split("/")
        or _SECRET.search(value)
        or _CREDENTIAL_SHAPE.search(value)
        or _EMAIL.search(value)
        or _PRIVATE_PATH.search(value)
    )


def _safe_text(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value) or _has_disclosure(value):
        raise ValueError("Journey persisted identity is unsafe.")
    return value


def _safe_session(value: str) -> str:
    if not _SESSION.fullmatch(value) or "@" in value or _has_disclosure(value):
        raise ValueError("Session identity is unsafe.")
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
        if _ISSUED_SECURITY_AUTHORIZATIONS.get(id(self)) is not self:
            raise ValueError("Mandatory security authorization identity changed.")
        return {
            "state": self.state,
            "reason": self.reason,
            "policy_sha256": self.policy_sha256,
        }


class MandatorySecurityVerifier:
    """Issue an authenticated receipt from one closed mandatory policy probe."""

    def __init__(
        self, probe: Callable[[Mapping[str, Any]], tuple[str, str]] | None = None
    ) -> None:
        self._probe = probe or self._default_probe

    @staticmethod
    def _default_probe(context: Mapping[str, Any]) -> tuple[str, str]:
        # This is deliberately structural and closed.  It does not grant user
        # or provider authority; it proves that only a supported task-bound,
        # protocol-emitted Claude/Codex contract reached the runtime boundary.
        if context.get("runtime") not in {"claude", "codex"}:
            return "denied", "unsupported-runtime"
        if not _DIGEST.fullmatch(str(context.get("route_sha256", ""))):
            return "denied", "invalid-route-authority"
        if context.get("route_contract_version") != RUNTIME_SCHEMA_VERSION:
            return "denied", "invalid-route-contract"
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
        authorization = SecurityAuthorization(
            state,
            _safe_text(reason),
            _sha(
                "mandatory-security-v1\n"
                + canonical_context
                + "\n"
                + state
                + "\n"
                + reason
            ),
            _SECURITY_AUTHORITY,
        )
        _ISSUED_SECURITY_AUTHORIZATIONS[id(authorization)] = authorization
        return authorization


@dataclass(frozen=True)
class PreparedInvocation:
    run_id: str
    specialist: str
    variant: str
    runtime: str
    stage_index: int
    invocation_marker: str
    knowledge_payload: str
    agent_prompt_fragment: str
    composed_content_sha256: str
    sources: tuple[Mapping[str, Any], ...]
    prompt_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.variant not in {"F", "F+O", "F+O+D", "F+O+D+P"}:
            raise ValueError("Prepared invocation variant is invalid.")
        if self.runtime not in {"claude", "codex"}:
            raise ValueError("Prepared invocation runtime is invalid.")
        if any(source.get("runtime") != self.runtime for source in self.sources):
            raise ValueError("Prepared invocation source runtime is invalid.")

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
        lock_timeout: float = 5.0,
        allow_missing_guard: bool = False,
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
        self._allow_missing_guard = allow_missing_guard
        self._claim_descriptor: int | None = None
        self._claim_pid: int | None = None
        if lock_timeout <= 0:
            raise ValueError("Journey lock timeout must be positive.")
        self._lock_timeout = lock_timeout

    def append(self, title: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self._assert_claim()
        record = dict(payload)
        record.update(
            {
                "schema_version": RUNTIME_SCHEMA_VERSION,
                "adapter_version": RUNTIME_ADAPTER_VERSION,
                "task_id": self.task_id,
            }
        )
        content = _canonical(record)
        stored = self.invoke(
            self._store_wp,
            task_id=self.task_id,
            type_="evidence",
            title=title,
            content=content,
            agent="cc-journey",
        )
        try:
            changed = (
                int(stored.get("task_id", -1)) != self.task_id
                or self._row_type(stored) != "evidence"
                or stored.get("title") != title
                or stored.get("content") != content
                or stored.get("agent") != "cc-journey"
                or not self._guard_is_clean(stored)
            )
        finally:
            self._assert_claim()
        if changed:
            raise RuntimeError("Task Copilot changed journey evidence during storage.")
        return stored

    @staticmethod
    def _row_type(row: Mapping[str, Any]) -> object:
        return row.get("type_", row.get("type"))

    def _guard_is_clean(self, row: Mapping[str, Any]) -> bool:
        return row.get("guard") == "title=clean;content=clean" or (
            self._allow_missing_guard and "guard" not in row
        )

    def rows(self) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
        result: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        seen_summary_ids: set[int] = set()
        task_filter = None if self.task_id == 0 else self.task_id
        summaries = self.invoke(self._list_wps, task=task_filter, type_="evidence")
        for summary in summaries:
            try:
                summary_id = int(summary["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "Journey ledger summary identity is malformed."
                ) from exc
            if summary_id <= 0 or summary_id in seen_summary_ids:
                raise ValueError("Journey ledger row identity is invalid.")
            seen_summary_ids.add(summary_id)
            row = self.invoke(self._get_wp, wp_id=summary_id)
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
                or not self._guard_is_clean(summary)
                or not self._guard_is_clean(row)
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

    @staticmethod
    def _global_lock_descriptor() -> int:
        if _GLOBAL_LOCK_PATH != _platform_global_lock_path():
            raise RuntimeError("Journey global lock path is invalid.")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptor = -1
        try:
            before = os.lstat(_GLOBAL_LOCK_PATH)
            descriptor = os.open(_GLOBAL_LOCK_PATH, flags)
            opened = os.fstat(descriptor)
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise RuntimeError("Journey global lock is unavailable.") from exc
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or before.st_uid != 0
            or opened.st_uid != 0
            or not bool(before.st_mode & stat.S_ISVTX)
            or not bool(opened.st_mode & stat.S_ISVTX)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            os.close(descriptor)
            raise RuntimeError("Journey global lock identity is unsafe.")
        return descriptor

    @staticmethod
    def _validate_global_lock_descriptor(descriptor: int) -> None:
        try:
            current = os.lstat(_GLOBAL_LOCK_PATH)
            opened = os.fstat(descriptor)
        except OSError as exc:
            raise RuntimeError("Journey global lock identity changed.") from exc
        if (
            not stat.S_ISDIR(current.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or current.st_uid != 0
            or opened.st_uid != 0
            or not bool(current.st_mode & stat.S_ISVTX)
            or not bool(opened.st_mode & stat.S_ISVTX)
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise RuntimeError("Journey global lock identity changed.")

    def _assert_claim(self) -> None:
        if (
            self._claim_descriptor is None
            or self._claim_pid is None
            or os.getpid() != self._claim_pid
        ):
            raise RuntimeError("Journey claim process identity changed.")
        self._validate_global_lock_descriptor(self._claim_descriptor)

    def invoke(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run a callback without allowing a forked child to retain authority."""
        callback_pid = os.getpid()
        claimed = self._claim_descriptor is not None
        if claimed:
            self._assert_claim()
        try:
            result = callback(*args, **kwargs)
        finally:
            if os.getpid() != callback_pid:
                raise RuntimeError("Journey callback crossed a process boundary.")
            if claimed:
                self._assert_claim()
        return result

    @contextmanager
    def claim(self, identity: str) -> Iterator[None]:
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,160}", identity):
            raise ValueError("Journey lock identity is malformed.")
        if self._claim_descriptor is not None:
            raise RuntimeError("Journey ledger already holds a claim.")
        descriptor = self._global_lock_descriptor()
        claim_pid = os.getpid()
        try:
            deadline = time.monotonic() + self._lock_timeout
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Journey lock acquisition timed out."
                        ) from exc
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            self._claim_descriptor = descriptor
            self._claim_pid = claim_pid
            self._assert_claim()
            try:
                yield
            finally:
                if os.getpid() != claim_pid:
                    raise RuntimeError("Journey claim process identity changed.")
                self._assert_claim()
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                if os.getpid() != claim_pid:
                    raise RuntimeError("Journey claim process identity changed.")
                self._assert_claim()
        finally:
            self._claim_descriptor = None
            self._claim_pid = None
            os.close(descriptor)


def _task_from_run(run_id: str) -> int:
    match = _RUN.fullmatch(run_id)
    if match is None:
        raise ValueError("Journey run identifier is malformed.")
    return int(match.group(1))


def _route_from(value: Mapping[str, Any]) -> RouteTrace:
    try:
        return RouteTrace(
            classification=_safe_text(str(value["classification"])),
            specialists=tuple(_safe_text(str(item)) for item in value["specialists"]),
            runtime=_safe_text(str(value["runtime"])),
            contract_version=str(value["contract_version"]),
            events=tuple(
                RouteEvent(
                    kind=str(item["kind"]),
                    specialist=_safe_text(str(item["specialist"])),
                    reason=_safe_text(str(item["reason"])),
                )
                for item in value["events"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Stored protocol route is malformed.") from exc


def _source_dict(receipt: Any) -> dict[str, Any]:
    result = {
        "layer": getattr(receipt, "layer"),
        "tier": getattr(receipt, "tier", getattr(receipt, "role", None)),
        "repository": getattr(receipt, "repository"),
        "ref": getattr(receipt, "ref"),
        "tree": getattr(receipt, "tree"),
        "signer": getattr(receipt, "signer"),
        "contribution": getattr(receipt, "contribution"),
        "content_sha256": getattr(receipt, "content_sha256"),
        "runtime": getattr(receipt, "runtime"),
        "adapter_version": getattr(receipt, "adapter_version"),
    }
    if isinstance(result.get("ref"), str) and _BARE_SEMVER_TAG.fullmatch(result["ref"]):
        # Git provenance verification accepts the manifest's conventional
        # bare semver spelling. Persist the fully qualified immutable tag so
        # every downstream receipt has one canonical identity.
        result["ref"] = f"refs/tags/{result['ref']}"
    for key, value in result.items():
        if not isinstance(value, str):
            raise ValueError("Knowledge source receipt is malformed.")
        if _has_disclosure(value):
            raise ValueError("Knowledge source receipt is malformed.")
        if key in {"tree", "content_sha256"}:
            if not re.fullmatch(r"[0-9a-f]{40,64}", value):
                raise ValueError("Knowledge source receipt is malformed.")
        elif key == "repository":
            if not _SOURCE_REPOSITORY.fullmatch(value):
                raise ValueError("Knowledge source receipt is malformed.")
        elif key == "ref":
            if not _SOURCE_REF.fullmatch(value):
                raise ValueError("Knowledge source receipt is malformed.")
        elif key == "signer":
            if not _SOURCE_SIGNER.fullmatch(value):
                raise ValueError("Knowledge source receipt is malformed.")
        elif key == "contribution":
            if not _SOURCE_CONTRIBUTION.fullmatch(value):
                raise ValueError("Knowledge source receipt is malformed.")
        elif not _IDENTIFIER.fullmatch(value):
            raise ValueError("Knowledge source receipt is malformed.")
    return result


def _validate_sources(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("Knowledge source receipts are missing.")
    allowed = {
        "layer",
        "tier",
        "repository",
        "ref",
        "tree",
        "signer",
        "contribution",
        "content_sha256",
        "runtime",
        "adapter_version",
    }
    result = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != allowed:
            raise ValueError("Knowledge source receipt is malformed.")
        proxy = type("Receipt", (), dict(item))()
        result.append(_source_dict(proxy))
    return tuple(result)


def resolve_specialist_knowledge(
    specialist: str,
    variant: str,
    runtime: str,
) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Resolve the exact signed Knowledge subset for one evaluation variant.

    Each declared tier is authenticated even when it has no applicable
    specialist contribution. Only contributions that the canonical extension
    resolver actually applies are placed in the runtime payload and source
    list; signed absence remains a content-authority fact rather than invented
    prompt text.
    """
    from dataclasses import replace

    from cc.core.ecosystem.knowledge_skill_source import (
        resolve_knowledge_skill_sources,
    )
    from cc.core.extensions_resolver import (
        ACTION_APPLY,
        ACTION_NO_EXTENSION,
        ExtensionSkillBindings,
        compose_agent_content_with_receipts,
        resolve_extension,
    )

    expected_tiers = {
        "F": ("foundation",),
        "F+O": ("foundation", "organization"),
        "F+O+D": ("foundation", "organization", "department"),
        "F+O+D+P": ("foundation", "organization", "department", "personal"),
    }.get(variant)
    if expected_tiers is None or runtime != "claude":
        raise ValueError("Required exact Knowledge variant is unavailable.")
    signed_tiers = expected_tiers[:-1] if variant == "F+O+D+P" else expected_tiers
    try:
        verified = [
            source
            for _root, source in resolve_knowledge_skill_sources()
            if source is not None and source.role in signed_tiers
        ]
    except Exception as exc:
        raise ValueError("Required authenticated Knowledge is unavailable.") from exc
    by_tier = {source.role: source for source in verified}
    if len(by_tier) != len(verified) or set(by_tier) != set(signed_tiers):
        raise ValueError("Required exact Knowledge variant is unavailable.")
    ordered = [by_tier[tier] for tier in signed_tiers]
    knowledge_repos = tuple(str(source.repository_root) for source in ordered)
    source_bindings = {
        str(source.repository_root.expanduser().absolute()): (True, source)
        for source in ordered
    }
    skill_bindings = ExtensionSkillBindings(knowledge_repos, source_bindings)
    content = ""
    active_receipts: list[object] = []
    for source in ordered:
        repository_path = str(source.repository_root)
        resolution = resolve_extension(
            specialist,
            knowledge_repos=[repository_path],
            source_bindings=source_bindings,
            skill_bindings=skill_bindings,
        )
        if resolution.action == ACTION_NO_EXTENSION:
            continue
        if resolution.action != ACTION_APPLY:
            raise ValueError("Required authenticated Knowledge is unavailable.")
        safe_resolution = replace(resolution, source_repo=source.repository)
        composed = compose_agent_content_with_receipts(safe_resolution, content)
        if composed.content_sha256 != _sha(composed.content) or any(
            not item.is_authenticated for item in composed.receipts
        ):
            raise ValueError("Required authenticated Knowledge is unavailable.")
        if resolution.type == "override":
            active_receipts = list(composed.receipts)
        elif resolution.type == "extension":
            active_receipts.extend(composed.receipts)
        content = composed.content
    if not content:
        content = "No applicable signed Knowledge contribution for this specialist."
    sources = tuple(_source_dict(item) for item in active_receipts)
    if variant == "F+O+D+P" and specialist == "doc":
        from cc.evaluation_fixtures.personal_snapshot import (
            personal_snapshot_contribution,
        )

        personal_content, personal_source = personal_snapshot_contribution(
            runtime=runtime
        )
        content = f"{content}\n\n{personal_content}"
        sources = (*sources, _source_dict(type("Receipt", (), personal_source)()))
    if any(source["runtime"] != runtime for source in sources):
        raise ValueError("Required exact Knowledge variant is unavailable.")
    return content, sources


def _codex_specialist_projection(
    source: object, specialist: str
) -> tuple[str, tuple[dict[str, Any], ...]]:
    from urllib.parse import urlparse

    try:
        files = {item.path: item for item in source.snapshot.files}
    except (AttributeError, TypeError) as exc:
        raise ValueError("Required authenticated Codex plugin is unavailable.") from exc
    source_kind = str(getattr(source, "source_kind", "plugin"))
    if source_kind not in {"plugin", "activated-pack"}:
        raise ValueError("Authenticated Codex specialist source is invalid.")
    contribution = f"skills/{specialist}/SKILL.md"
    skill = files.get(contribution)
    manifest = files.get(
        ".codex-plugin/plugin.json" if source_kind == "plugin" else "pack.json"
    )
    if skill is None or manifest is None:
        raise ValueError("Required Codex specialist is unavailable.")
    try:
        content = skill.content.decode("utf-8")
        plugin = json.loads(manifest.content)
        if source_kind == "plugin":
            parsed = urlparse(str(plugin["repository"]))
            repository = parsed.path.strip("/").removesuffix(".git")
        else:
            specialists = plugin.get("specialists")
            if (
                plugin.get("name") != getattr(source, "plugin_name", None)
                or not isinstance(specialists, list)
                or specialist not in specialists
                or not getattr(source, "activation_sha256", None)
            ):
                raise ValueError("Authenticated Codex pack activation is invalid.")
            repository = str(getattr(source, "repository"))
    except (
        AttributeError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Authenticated Codex plugin manifest is invalid.") from exc
    receipt = _source_dict(
        type(
            "CodexReceipt",
            (),
            {
                "layer": source.layer,
                "tier": getattr(
                    source,
                    "role",
                    next(
                        (
                            role
                            for role in (
                                "personal",
                                "department",
                                "organization",
                                "foundation",
                            )
                            if role in str(source.layer)
                        ),
                        "",
                    ),
                ),
                "repository": repository,
                "ref": source.ref,
                "tree": source.tree,
                "signer": source.signer,
                "contribution": contribution,
                "content_sha256": _sha(content),
                "runtime": "codex",
                "adapter_version": str(
                    getattr(
                        source,
                        "adapter_version",
                        (
                            "codex-plugin-v1"
                            if source_kind == "plugin"
                            else "codex-pack-v1"
                        ),
                    )
                ),
            },
        )()
    )
    return content, (receipt,)


def resolve_codex_specialist_knowledge(
    specialist: str,
    variant: str,
    runtime: str,
    *,
    case_id: str | None = None,
) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Resolve one exact canonical additive Codex projection.

    The production issuer owns source, entitlement, lock, and retained-file
    authority. This journey boundary consumes that issuer rather than selecting
    a mutable global plugin or treating the nearest plugin as the whole ladder.
    """

    if runtime != "codex":
        raise ValueError("Required exact Codex variant is unavailable.")
    from cc.core.evaluation.content_authority import (
        CanonicalContentUnavailable,
        issue_canonical_codex_content,
    )
    from cc.core.evaluation.models import LayerVariant

    try:
        selected_variant = LayerVariant(variant)
        selected_case = case_id or {
            "uids": "eval-03",
            "cco": "eval-04",
            "cpa": "eval-05",
            "ta": "eval-06",
            "doc": "eval-07",
        }.get(specialist)
        projection = issue_canonical_codex_content(
            variant=selected_variant,
            specialist=specialist,
            case_id=selected_case,
        )
    except (CanonicalContentUnavailable, ValueError) as exc:
        raise ValueError(
            "Required additive Codex specialist and Knowledge projection is unavailable."
        ) from exc
    try:
        return projection.knowledge_payload, tuple(
            dict(item) for item in projection.knowledge_sources
        )
    finally:
        projection.close()


def _compose_codex_specialist_knowledge(
    specialist: str,
    variant: str,
    runtime: str,
    plugin_sources: Sequence[object],
    *,
    knowledge_projection: tuple[str, Sequence[Mapping[str, Any]]] | None = None,
) -> tuple[
    str,
    tuple[dict[str, Any], ...],
    str,
    tuple[tuple[str, str | None, dict[str, Any] | None], ...],
]:
    """Compose tier-owned additive plugins with exact signed Knowledge."""

    expected_tiers = {
        "F": ("foundation",),
        "F+O": ("foundation", "organization"),
        "F+O+D": ("foundation", "organization", "department"),
        "F+O+D+P": (
            "foundation",
            "organization",
            "department",
            "personal",
        ),
    }.get(variant)
    if expected_tiers is None or runtime != "codex":
        raise ValueError("Required exact Codex variant is unavailable.")
    signed_tiers = expected_tiers[:-1] if variant == "F+O+D+P" else expected_tiers
    by_tier = {
        str(getattr(item, "role", "")): item
        for item in plugin_sources
        if getattr(item, "role", None) in signed_tiers
    }
    if len(by_tier) != len(plugin_sources) or set(by_tier) != set(signed_tiers):
        raise ValueError("Required exact Codex plugin ladder is unavailable.")

    facts: list[tuple[str, str | None, dict[str, Any] | None]] = []
    for tier in signed_tiers:
        try:
            content, receipts = _codex_specialist_projection(by_tier[tier], specialist)
        except ValueError as exc:
            if str(exc) != "Required Codex specialist is unavailable.":
                raise
            facts.append((tier, None, None))
            continue
        if len(receipts) != 1:
            raise ValueError("Required exact Codex specialist is ambiguous.")
        facts.append((tier, content, dict(receipts[0])))
    contributing = [item for item in facts if item[1] is not None]
    if not contributing:
        raise ValueError("Required Codex specialist is unavailable.")
    winner_tier, winner_content, winner_receipt = contributing[-1]
    assert winner_content is not None and winner_receipt is not None

    if knowledge_projection is None:
        knowledge_content, knowledge_sources = resolve_specialist_knowledge(
            specialist,
            variant,
            "claude",
        )
    else:
        knowledge_content, knowledge_sources = knowledge_projection
        if not isinstance(knowledge_content, str) or not knowledge_content:
            raise ValueError("Required exact Knowledge variant is unavailable.")
    codex_knowledge_sources = tuple(
        {**dict(item), "runtime": "codex"} for item in knowledge_sources
    )
    payload = (
        winner_content
        + "\n\n---\n\n## Applicable signed Knowledge\n\n"
        + knowledge_content
    )
    sources = (*codex_knowledge_sources, winner_receipt)
    if any(item.get("runtime") != "codex" for item in sources):
        raise ValueError("Required exact Codex variant is unavailable.")
    return payload, sources, winner_tier, tuple(facts)


def _resolver_for_runtime(
    resolver: Callable[[str, str, str], tuple[str, tuple[dict[str, Any], ...]]],
    runtime: str,
) -> Callable[[str, str, str], tuple[str, tuple[dict[str, Any], ...]]]:
    if resolver is resolve_specialist_knowledge and runtime == "codex":
        return resolve_codex_specialist_knowledge
    return resolver


def _security_context(begin: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": begin["task_id"],
        "run_id": begin["run_id"],
        "session_sha256": begin["session_id_sha256"],
        "runtime": begin["route"]["runtime"],
        "route_contract_version": begin["route"]["contract_version"],
        "route_sha256": _sha(_canonical(begin["route"])),
        "prompt_sha256": begin["prompt_sha256"],
    }


def _require_security(
    begin: Mapping[str, Any],
    verifier: MandatorySecurityVerifier,
    ledger: TcJourneyLedger,
) -> dict[str, str]:
    receipt = ledger.invoke(verifier.authorize, _security_context(begin))
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
    session_id = _safe_session(session_id)
    trace = RouteTrace(
        classification=_safe_text(classification),
        specialists=tuple(_safe_text(item) for item in specialists),
        runtime=_safe_text(runtime),
        contract_version=RUNTIME_SCHEMA_VERSION,
        events=tuple(
            RouteEvent(
                item["kind"], _safe_text(item["specialist"]), _safe_text(item["reason"])
            )
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
    selected = ledger or TcJourneyLedger(task_id)
    payload["security"] = _require_security(
        payload, security or MandatorySecurityVerifier(), selected
    )
    payload["capability"] = asdict(
        selected.invoke(
            (capability or CliCopilotHealthCapabilityAdapter()).invoke,
            case_id=run_id,
        )
    )
    capability_detail = str(payload["capability"].get("detail", ""))
    if capability_detail and not re.fullmatch(
        r"sha256:[0-9a-f]{64}", capability_detail
    ):
        raise ValueError("Capability diagnostic is not redacted.")
    with selected.claim("begin-" + _sha(session_id)):
        if _active_runs_for_session(session_id, selected):
            raise ValueError("Session already has an active journey.")
        selected.append(BEGIN_TITLE, payload)
    return payload | {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "adapter_version": RUNTIME_ADAPTER_VERSION,
    }


def _expected_title(payload: Mapping[str, Any]) -> str:
    kind = payload.get("record_type")
    if kind == "begin":
        return BEGIN_TITLE
    if kind == "prepare":
        return PREPARE_TITLE
    if kind == "prompt_binding":
        return BIND_TITLE
    if kind == "dispatch_authorization":
        return DISPATCH_TITLE
    if kind == "pause_capsule":
        return PAUSE_TITLE
    if kind == "final_authorization":
        return FINAL_TITLE
    raise ValueError("Journey record type is invalid.")


def _state(run_id: str, ledger: TcJourneyLedger) -> dict[str, Any]:
    buckets = {
        key: []
        for key in (
            "begin",
            "prepare",
            "prompt_binding",
            "dispatch_authorization",
            "pause_capsule",
            "final_authorization",
        )
    }
    row_ids: dict[int, int] = {}
    seen_row_ids: set[int] = set()
    for row, payload in ledger.rows():
        if payload.get("run_id") != run_id:
            continue
        if payload.get("task_id") != _task_from_run(run_id) or row.get(
            "title"
        ) != _expected_title(payload):
            raise ValueError("Journey evidence identity is invalid.")
        kind = str(payload.get("record_type", ""))
        if kind not in buckets:
            raise ValueError("Journey evidence type is invalid.")
        row_id = int(row["id"])
        if row_id <= 0 or row_id in seen_row_ids:
            raise ValueError("Journey ledger row identity is invalid.")
        seen_row_ids.add(row_id)
        buckets[kind].append(payload)
        row_ids[id(payload)] = row_id
    if len(buckets["begin"]) != 1 or len(buckets["final_authorization"]) > 1:
        raise ValueError("Journey evidence is missing or ambiguous.")
    begin = buckets["begin"][0]
    begin_id = row_ids[id(begin)]
    if any(
        row_ids[id(item)] <= begin_id
        for kind, records in buckets.items()
        if kind != "begin"
        for item in records
    ):
        raise ValueError("Journey evidence chronology is invalid.")
    if buckets["final_authorization"]:
        final = buckets["final_authorization"][0]
        final_id = row_ids[id(final)]
        if any(
            row_id >= final_id
            for payload_id, row_id in row_ids.items()
            if payload_id != id(final)
        ):
            raise ValueError("Journey final chronology is invalid.")
    route_trace = _route_from(begin.get("route", {}))
    route = route_trace.specialists
    dispatches = sorted(
        buckets["dispatch_authorization"], key=lambda item: int(item["stage_index"])
    )
    completed = tuple(item["specialist"] for item in dispatches)
    if completed != route[: len(completed)] or tuple(
        item["stage_index"] for item in dispatches
    ) != tuple(range(len(dispatches))):
        raise ValueError("Journey dispatch ledger is out of route order.")
    for kind in ("prepare", "prompt_binding", "dispatch_authorization"):
        indices = [int(item["stage_index"]) for item in buckets[kind]]
        if len(indices) != len(set(indices)) or any(
            index < 0 or index >= len(route) for index in indices
        ):
            raise ValueError("Journey stage evidence is ambiguous.")
    preparations = {int(item["stage_index"]): item for item in buckets["prepare"]}
    bindings = {int(item["stage_index"]): item for item in buckets["prompt_binding"]}
    authorizations = {
        int(item["stage_index"]): item for item in buckets["dispatch_authorization"]
    }
    for stage, prepared in preparations.items():
        binding = bindings.get(stage)
        dispatched = authorizations.get(stage)
        if binding is not None and row_ids[id(prepared)] >= row_ids[id(binding)]:
            raise ValueError("Journey evidence chronology is invalid.")
        if dispatched is not None and (
            binding is None
            or row_ids[id(prepared)] >= row_ids[id(dispatched)]
            or row_ids[id(binding)] >= row_ids[id(dispatched)]
        ):
            raise ValueError("Journey evidence chronology is invalid.")
    if set(bindings) - set(preparations) or set(authorizations) - set(preparations):
        raise ValueError("Journey evidence chronology is invalid.")
    dispatch_ids = [
        row_ids[id(authorizations[stage])] for stage in range(len(authorizations))
    ]
    if dispatch_ids != sorted(dispatch_ids) or len(dispatch_ids) != len(authorizations):
        raise ValueError("Journey cross-stage chronology is invalid.")
    for stage in range(1, len(route)):
        prior = authorizations.get(stage - 1)
        later = tuple(
            item
            for item in (
                preparations.get(stage),
                bindings.get(stage),
                authorizations.get(stage),
            )
            if item is not None
        )
        if later and (
            prior is None
            or any(row_ids[id(prior)] >= row_ids[id(item)] for item in later)
        ):
            raise ValueError("Journey cross-stage chronology is invalid.")
    for kind in ("prepare", "dispatch_authorization"):
        for item in buckets[kind]:
            if list(_validate_sources(item.get("sources"))) != item.get("sources"):
                raise ValueError("Stored Knowledge source receipts are malformed.")
    pause_generations = [int(item["generation"]) for item in buckets["pause_capsule"]]
    if len(pause_generations) != len(set(pause_generations)) or any(
        generation < 0 or generation > len(route) for generation in pause_generations
    ):
        raise ValueError("Journey pause evidence is ambiguous.")
    pauses_in_order = sorted(
        buckets["pause_capsule"], key=lambda item: row_ids[id(item)]
    )
    if [int(item["generation"]) for item in pauses_in_order] != sorted(
        pause_generations
    ):
        raise ValueError("Journey pause chronology is invalid.")
    buckets["pause_capsule"] = pauses_in_order
    state = buckets | {"begin_record": begin, "route": route, "completed": completed}
    for item in buckets["pause_capsule"]:
        generation = int(item["generation"])
        cutoff = row_ids[id(item)]
        historical = state | {
            kind: [record for record in state[kind] if row_ids[id(record)] < cutoff]
            for kind in ("prepare", "prompt_binding", "dispatch_authorization")
        }
        if (
            len(historical["dispatch_authorization"]) != generation
            or any(
                int(record["stage_index"]) > generation
                for kind in ("prepare", "prompt_binding")
                for record in historical[kind]
            )
            or any(
                row_ids[id(record)] < cutoff for record in state["final_authorization"]
            )
        ):
            raise ValueError("Journey pause chronology is invalid.")
        expected = _capsule_for_generation(run_id, historical, generation)
        if item.get("capsule") != expected or item.get("capsule_sha256") != _sha(
            _canonical(expected)
        ):
            raise ValueError("Journey historical pause capsule changed.")
    if buckets["final_authorization"] and len(completed) != len(route):
        raise ValueError("Journey final evidence is premature.")
    return state


def _unfinished_public_state(run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
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
        "status": (
            "paused"
            if any(
                int(item["generation"]) == next_index for item in state["pause_capsule"]
            )
            else "active"
        ),
        "evidence_claim": "dispatch_observed_and_authorized_only",
        "route": begin["route"],
        "prompt_sha256": begin["prompt_sha256"],
        "security": begin["security"],
        "capability": begin["capability"],
        "dispatch_authorized_specialists": completed,
        "next_specialist": route[next_index] if next_index < len(route) else None,
        "next_stage_state": (
            (
                "prompt_bound"
                if next_index in bindings
                else "prepared" if next_index in preparations else "unprepared"
            )
            if next_index < len(route)
            else None
        ),
    }


def _terminal_result(run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    result = _unfinished_public_state(run_id, state)
    result.update(
        {
            "status": "all_dispatches_authorized",
            "next_specialist": None,
            "next_stage_state": None,
        }
    )
    return result


def _public_state(run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    if state["final_authorization"]:
        final = state["final_authorization"][0]
        result_json = final.get("result_json")
        if not isinstance(result_json, str):
            raise ValueError("Final authorization evidence is malformed.")
        dispatch_digest = _sha(_canonical(state["dispatch_authorization"]))
        expected_json = _canonical(_terminal_result(run_id, state))
        if (
            _sha(result_json) != final.get("result_sha256")
            or dispatch_digest != final.get("dispatch_authorizations_sha256")
            or result_json != expected_json
        ):
            raise ValueError("Final authorization evidence changed.")
        return json.loads(result_json)
    return _unfinished_public_state(run_id, state)


def inspect_run(
    run_id: str, *, ledger: TcJourneyLedger | None = None
) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    return _public_state(run_id, _state(run_id, selected))


def prepare_run(
    run_id: str,
    specialist: str,
    *,
    variant: str = "F",
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[
        [str, str, str], tuple[str, tuple[dict[str, Any], ...]]
    ] = resolve_specialist_knowledge,
    security: MandatorySecurityVerifier | None = None,
) -> PreparedInvocation:
    if variant not in {"F", "F+O", "F+O+D", "F+O+D+P"}:
        raise ValueError("Knowledge variant is invalid.")
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    with selected.claim(run_id):
        state = _state(run_id, selected)
        stage = len(state["completed"])
        if stage >= len(state["route"]) or state["route"][stage] != specialist:
            raise ValueError("Specialist is not the exact next protocol stage.")
        _require_security(
            state["begin_record"], security or MandatorySecurityVerifier(), selected
        )
        runtime = str(state["begin_record"]["route"]["runtime"])
        selected_resolver = _resolver_for_runtime(resolver, runtime)
        payload, raw_sources = selected.invoke(
            selected_resolver,
            specialist,
            variant,
            runtime,
        )
        sources = _validate_sources(raw_sources)
        if any(source["runtime"] != runtime for source in sources):
            raise ValueError("Knowledge runtime projection does not match the route.")
        if not payload or KNOWLEDGE_BEGIN in payload or KNOWLEDGE_END in payload:
            raise ValueError("Required Knowledge payload is malformed.")
        digest = _sha(payload)
        matches = [
            item for item in state["prepare"] if item.get("stage_index") == stage
        ]
        if matches:
            prepared = matches[0]
            if (
                prepared.get("specialist") != specialist
                or prepared.get("variant") != variant
                or prepared.get("runtime") != runtime
                or prepared.get("composed_content_sha256") != digest
                or prepared.get("sources") != list(sources)
            ):
                raise ValueError("Knowledge changed after preparation.")
            marker = str(prepared["invocation_marker"])
        else:
            marker = secrets.token_hex(24)
            selected.append(
                PREPARE_TITLE,
                {
                    "record_type": "prepare",
                    "run_id": run_id,
                    "stage_index": stage,
                    "specialist": specialist,
                    "variant": variant,
                    "runtime": runtime,
                    "invocation_marker": marker,
                    "composed_content_sha256": digest,
                    "sources": list(sources),
                    "security_sha256": _sha(
                        _canonical(state["begin_record"]["security"])
                    ),
                },
            )
        binding = next(
            (
                item
                for item in state["prompt_binding"]
                if item.get("stage_index") == stage
            ),
            None,
        )
    fragment = f"{MARKER_HEADER}{marker}\n{KNOWLEDGE_BEGIN}\n{payload}\n{KNOWLEDGE_END}"
    return PreparedInvocation(
        run_id=run_id,
        specialist=specialist,
        variant=variant,
        runtime=runtime,
        stage_index=stage,
        invocation_marker=marker,
        knowledge_payload=payload,
        agent_prompt_fragment=fragment,
        composed_content_sha256=digest,
        sources=sources,
        prompt_sha256=str(binding["prompt_sha256"]) if binding else None,
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
        prepared = [
            item for item in state["prepare"] if item.get("stage_index") == stage
        ]
        if len(prepared) != 1 or prepared[0].get("specialist") != specialist:
            raise ValueError("Exact next Agent prompt has not been prepared.")
        bindings = [
            item for item in state["prompt_binding"] if item.get("stage_index") == stage
        ]
        if bindings:
            if bindings[0].get("prompt_sha256") != prompt_sha256:
                raise ValueError("Full Agent prompt changed after binding.")
        else:
            selected.append(
                BIND_TITLE,
                {
                    "record_type": "prompt_binding",
                    "run_id": run_id,
                    "stage_index": stage,
                    "specialist": specialist,
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


def _capsule_for_generation(
    run_id: str, state: Mapping[str, Any], generation: int
) -> dict[str, Any]:
    begin = state["begin_record"]
    stage = generation
    dispatches = list(state["dispatch_authorization"][:generation])
    if len(dispatches) != generation:
        raise ValueError("Journey pause generation exceeds dispatch history.")
    prepared = next(
        (item for item in state["prepare"] if item.get("stage_index") == stage), None
    )
    binding = next(
        (item for item in state["prompt_binding"] if item.get("stage_index") == stage),
        None,
    )
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
        "dispatch_authorizations": dispatches,
        "prepared": prepared,
        "prompt_binding": binding,
        "next_stage_index": stage if stage < len(state["route"]) else None,
        "next_specialist": (
            state["route"][stage] if stage < len(state["route"]) else None
        ),
    }


def _capsule(run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    return _capsule_for_generation(run_id, state, len(state["completed"]))


def pause_run(
    run_id: str,
    *,
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[
        [str, str, str], tuple[str, tuple[dict[str, Any], ...]]
    ] = resolve_specialist_knowledge,
    security: MandatorySecurityVerifier | None = None,
) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(_task_from_run(run_id))
    initial = _state(run_id, selected)
    next_index = len(initial["completed"])
    if next_index < len(initial["route"]) and not any(
        item.get("stage_index") == next_index for item in initial["prepare"]
    ):
        prepare_run(
            run_id,
            initial["route"][next_index],
            ledger=selected,
            resolver=resolver,
            security=security,
        )
    with selected.claim(run_id):
        state = _state(run_id, selected)
        if state["final_authorization"]:
            return _public_state(run_id, state)
        capsule = _capsule(run_id, state)
        digest = _sha(_canonical(capsule))
        matches = [
            item
            for item in state["pause_capsule"]
            if int(item["generation"]) == len(state["completed"])
        ]
        if matches:
            stored = matches[0]
            if (
                stored.get("capsule") != capsule
                or stored.get("capsule_sha256") != digest
            ):
                raise ValueError(
                    "Journey pause capsule no longer matches runtime state."
                )
        else:
            selected.append(
                PAUSE_TITLE,
                {
                    "record_type": "pause_capsule",
                    "run_id": run_id,
                    "generation": len(state["completed"]),
                    "capsule": capsule,
                    "capsule_sha256": digest,
                },
            )
        return _public_state(run_id, _state(run_id, selected))


def _active_runs_for_session(session_id: str, ledger: TcJourneyLedger) -> list[str]:
    runs = []
    for row, payload in ledger.rows():
        if payload.get("record_type") == "begin" and payload.get(
            "session_id_sha256"
        ) == _sha(session_id):
            run_id = str(payload.get("run_id", ""))
            state = _state(
                run_id,
                TcJourneyLedger(
                    _task_from_run(run_id),
                    store_wp=ledger._store_wp,
                    get_wp=ledger._get_wp,
                    list_wps=ledger._list_wps,
                    lock_timeout=ledger._lock_timeout,
                    allow_missing_guard=ledger._allow_missing_guard,
                ),
            )
            if not state["final_authorization"]:
                runs.append(run_id)
    return sorted(set(runs))


def resume_run(
    task_id: int,
    *,
    run_id: str | None = None,
    ledger: TcJourneyLedger | None = None,
    resolver: Callable[
        [str], tuple[str, tuple[dict[str, Any], ...]]
    ] = resolve_specialist_knowledge,
    security: MandatorySecurityVerifier | None = None,
) -> dict[str, Any]:
    selected = ledger or TcJourneyLedger(task_id)
    states: dict[str, dict[str, Any]] = {}
    for row, payload in selected.rows():
        if payload.get("record_type") == "begin":
            candidate = str(payload.get("run_id", ""))
            states[candidate] = _state(candidate, selected)
    if run_id is None:
        active = [
            key
            for key, value in states.items()
            if any(
                int(item["generation"]) == len(value["completed"])
                for item in value["pause_capsule"]
            )
            and not value["final_authorization"]
        ]
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
    capsules = [
        item
        for item in state["pause_capsule"]
        if int(item["generation"]) == len(state["completed"])
    ]
    if len(capsules) != 1:
        raise ValueError("Journey continuation capsule is missing.")
    capsule = _capsule(run_id, state)
    stored = capsules[0]
    if stored.get("capsule") != capsule or stored.get("capsule_sha256") != _sha(
        _canonical(capsule)
    ):
        raise ValueError("Journey continuation capsule changed.")
    _require_security(
        state["begin_record"], security or MandatorySecurityVerifier(), selected
    )
    public = _public_state(run_id, state)
    if public["next_specialist"] is not None:
        public["prepared_invocation"] = prepare_run(
            run_id,
            public["next_specialist"],
            ledger=selected,
            resolver=resolver,
            security=security,
        ).public_dict()
    return public


def _store_final(run_id: str, ledger: TcJourneyLedger) -> None:
    state = _state(run_id, ledger)
    if state["final_authorization"] or len(state["completed"]) != len(state["route"]):
        return
    # Build the terminal value before adding the terminal row.  Its claim is
    # deliberately dispatch authorization, never specialist completion.
    result = _terminal_result(run_id, state)
    result_json = _canonical(result)
    ledger.append(
        FINAL_TITLE,
        {
            "record_type": "final_authorization",
            "run_id": run_id,
            "result_json": result_json,
            "result_sha256": _sha(result_json),
            "dispatch_authorizations_sha256": _sha(
                _canonical(state["dispatch_authorization"])
            ),
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
    resolver: Callable[
        [str], tuple[str, tuple[dict[str, Any], ...]]
    ] = resolve_specialist_knowledge,
    security: MandatorySecurityVerifier | None = None,
) -> dict[str, Any]:
    try:
        session_id = _safe_session(session_id)
        specialist = _safe_text(specialist)
    except ValueError as exc:
        raise ValueError("dispatch-arguments-malformed") from exc
    if not _DIGEST.fullmatch(prompt_sha256):
        raise ValueError("dispatch-arguments-malformed")
    if ledger_factory is TcJourneyLedger:
        try:
            from tc.db.connection import find_db_path
        except ImportError as exc:
            raise RuntimeError(
                "Task Copilot is unavailable; journey state cannot continue."
            ) from exc
        try:
            task_db = find_db_path()
        except OSError as exc:
            raise RuntimeError("Task Copilot state could not be inspected.") from exc
        if task_db is None:
            # With no durable ledger, no active journey can exist. An
            # unframed legacy dispatch is therefore provably no-active. A
            # supplied marker is still rejected: accepting one without its
            # evidence would turn absence of state into an authority bypass.
            if marker:
                raise ValueError("dispatch-marker-stale-or-ambiguous")
            return {"schema_version": RUNTIME_SCHEMA_VERSION, "state": "no_active"}
    probe = ledger_factory(0)
    if not marker:
        if _active_runs_for_session(session_id, probe):
            raise ValueError("active-journey-marker-required")
        return {"schema_version": RUNTIME_SCHEMA_VERSION, "state": "no_active"}
    if not _MARKER.fullmatch(marker) or not _DIGEST.fullmatch(knowledge_sha256):
        raise ValueError("dispatch-marker-malformed")
    candidates = [
        payload
        for row, payload in probe.rows()
        if payload.get("record_type") == "prepare"
        and payload.get("invocation_marker") == marker
    ]
    if len(candidates) != 1:
        raise ValueError("dispatch-marker-stale-or-ambiguous")
    prepared = candidates[0]
    run_id = str(prepared.get("run_id", ""))
    ledger = ledger_factory(_task_from_run(run_id))
    with ledger.claim(run_id):
        state = _state(run_id, ledger)
        stage = len(state["completed"])
        if state["final_authorization"]:
            _public_state(run_id, state)
            raise ValueError("dispatch-replay")
        if state["begin_record"].get("session_id_sha256") != _sha(session_id):
            raise ValueError("dispatch-session-mismatch")
        if stage == len(state["route"]):
            prior = (
                state["dispatch_authorization"][-1]
                if state["dispatch_authorization"]
                else None
            )
            if (
                prior is None
                or prior.get("specialist") != specialist
                or prior.get("variant") != prepared.get("variant")
                or prior.get("runtime") != prepared.get("runtime")
                or prior.get("session_id_sha256") != _sha(session_id)
                or prior.get("invocation_marker_sha256") != _sha(marker)
                or prior.get("prompt_sha256") != prompt_sha256
                or prior.get("composed_content_sha256") != knowledge_sha256
            ):
                raise ValueError("dispatch-route-order-mismatch")
            matching_preparations = [
                item
                for item in state["prepare"]
                if item.get("stage_index") == prior.get("stage_index")
                and item.get("invocation_marker") == marker
            ]
            if len(matching_preparations) != 1 or matching_preparations[0] != prepared:
                raise ValueError("dispatch-preparation-row-mismatch")
            matching_bindings = [
                item
                for item in state["prompt_binding"]
                if item.get("stage_index") == prior.get("stage_index")
            ]
            if (
                len(matching_bindings) != 1
                or matching_bindings[0].get("specialist") != specialist
                or matching_bindings[0].get("invocation_marker") != marker
                or matching_bindings[0].get("prompt_sha256") != prompt_sha256
                or matching_bindings[0].get("prepared_sha256")
                != _sha(_canonical(prepared))
            ):
                raise ValueError("dispatch-prompt-not-bound")
            result = {
                "schema_version": RUNTIME_SCHEMA_VERSION,
                "state": "dispatch_authorized",
                "evidence_claim": "dispatch_observed_and_authorized_only",
                "run_id": run_id,
                "stage_index": int(prior["stage_index"]),
                "dispatch_sha256": prompt_sha256,
            }
            _require_security(
                state["begin_record"], security or MandatorySecurityVerifier(), ledger
            )
            runtime = str(state["begin_record"]["route"]["runtime"])
            selected_resolver = _resolver_for_runtime(resolver, runtime)
            content, raw_sources = ledger.invoke(
                selected_resolver,
                specialist,
                str(prepared["variant"]),
                runtime,
            )
            sources = _validate_sources(raw_sources)
            if _sha(content) != knowledge_sha256 or list(sources) != prior.get(
                "sources"
            ):
                raise ValueError("dispatch-knowledge-changed")
            _store_final(run_id, ledger)
            return result
        if (
            prepared.get("stage_index") != stage
            or prepared.get("specialist") != specialist
            or prepared.get("runtime") != str(state["begin_record"]["route"]["runtime"])
        ):
            raise ValueError("dispatch-route-order-mismatch")
        scoped_preparations = [
            item
            for item in state["prepare"]
            if item.get("stage_index") == stage
            and item.get("invocation_marker") == marker
        ]
        if len(scoped_preparations) != 1 or scoped_preparations[0] != prepared:
            raise ValueError("dispatch-preparation-row-mismatch")
        bindings = [
            item for item in state["prompt_binding"] if item.get("stage_index") == stage
        ]
        expected_prepared_sha256 = _sha(_canonical(prepared))
        if (
            len(bindings) != 1
            or bindings[0].get("specialist") != specialist
            or bindings[0].get("invocation_marker") != marker
            or bindings[0].get("prepared_sha256") != expected_prepared_sha256
            or bindings[0].get("prompt_sha256") != prompt_sha256
        ):
            raise ValueError("dispatch-prompt-not-bound")
        _require_security(
            state["begin_record"], security or MandatorySecurityVerifier(), ledger
        )
        runtime = str(state["begin_record"]["route"]["runtime"])
        selected_resolver = _resolver_for_runtime(resolver, runtime)
        content, raw_sources = ledger.invoke(
            selected_resolver,
            specialist,
            str(prepared["variant"]),
            runtime,
        )
        sources = _validate_sources(raw_sources)
        if (
            _sha(content) != knowledge_sha256
            or knowledge_sha256 != prepared.get("composed_content_sha256")
            or list(sources) != prepared.get("sources")
        ):
            raise ValueError("dispatch-knowledge-changed")
        ledger.append(
            DISPATCH_TITLE,
            {
                "record_type": "dispatch_authorization",
                "run_id": run_id,
                "stage_index": stage,
                "specialist": specialist,
                "variant": prepared["variant"],
                "runtime": prepared["runtime"],
                "session_id_sha256": _sha(session_id),
                "prompt_sha256": prompt_sha256,
                "invocation_marker_sha256": _sha(marker),
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
    "CliCopilotHealthCapabilityAdapter",
    "MandatorySecurityVerifier",
    "PreparedInvocation",
    "SecurityAuthorization",
    "TcJourneyLedger",
    "begin_run",
    "bind_prompt",
    "inspect_run",
    "pause_run",
    "prepare_run",
    "resume_run",
    "resolve_codex_specialist_knowledge",
    "resolve_specialist_knowledge",
    "verify_dispatch",
]
