"""Framework-only problem-to-solution journey evidence.

This module does not classify requests, resolve Knowledge, call operational
services, or own task state.  It binds those existing/injected boundaries into
one deterministic receipt so structural integration can be tested without a
model, network access, credentials, or repository mutation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Mapping, Protocol, Sequence

SCHEMA_VERSION = "1.0"
ADAPTER_VERSION = "journey-adapter-v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TREE = re.compile(r"^[0-9a-f]{40,64}$")
_CAPABILITY_STATES = frozenset(
    {"available", "unavailable", "timeout", "nonzero", "malformed", "security-denied"}
)
_ROUTE_EVENT_KINDS = frozenset({"transition", "checkpoint", "skip"})
_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_COMPOSITION_SEPARATOR = "\n\n"
_SECRET_LIKE = re.compile(r"(?i)(bearer|password|secret|token|api[_-]?key)")
_VERIFIED_SOURCE_AUTHORITY = object()


def _is_safe_identity(value: str) -> bool:
    return bool(
        _SAFE_IDENTITY.fullmatch(value)
        and not value.startswith("/")
        and ".." not in value.split("/")
        and not _SECRET_LIKE.search(value)
    )


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class TrustedKnowledgeSourcePolicy:
    """Exact identity accepted by an upstream authenticated resolver."""

    repository: str
    ref: str
    tree: str
    signer: str
    runtime: str
    adapter_version: str
    contributions: frozenset[str]

    def __post_init__(self) -> None:
        identities = (
            self.repository,
            self.ref,
            self.signer,
            self.runtime,
            self.adapter_version,
            *self.contributions,
        )
        if (
            not self.contributions
            or not all(_is_safe_identity(item) for item in identities)
            or not _TREE.fullmatch(self.tree)
        ):
            raise ValueError("Trusted Knowledge source policy is malformed.")


class _VerifiedKnowledgeSourceProof:
    """Opaque proof issued only after exact policy and byte validation."""

    __slots__ = ("_claims",)

    def __init__(self, authority: object, claims: tuple[str, ...]) -> None:
        if authority is not _VERIFIED_SOURCE_AUTHORITY:
            raise TypeError("Verified Knowledge proof has no trusted issuer.")
        self._claims = claims

    def matches(self, claims: tuple[str, ...]) -> bool:
        return self._claims == claims

    def __deepcopy__(self, memo):
        return self


@dataclass(frozen=True)
class KnowledgeReceipt:
    """Identity and bytes of one winning Knowledge contribution."""

    layer: str
    ref: str
    tree: str
    signer: str
    contribution: str
    content_sha256: str
    runtime: str
    adapter_version: str
    repository: str = "local-fixture"
    _verification: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        required = (
            self.layer,
            self.ref,
            self.signer,
            self.contribution,
            self.runtime,
            self.adapter_version,
        )
        identities = required + (self.repository,)
        if (
            not all(identities)
            or not all(_is_safe_identity(item) for item in identities)
            or not _TREE.fullmatch(self.tree)
        ):
            raise ValueError("Knowledge receipt lacks immutable source identity.")
        if not _DIGEST.fullmatch(self.content_sha256):
            raise ValueError("Knowledge receipt has an invalid content digest.")

    def _claims(self) -> tuple[str, ...]:
        return (
            self.layer,
            self.repository,
            self.ref,
            self.tree,
            self.signer,
            self.contribution,
            self.content_sha256,
            self.runtime,
            self.adapter_version,
        )

    @property
    def is_authenticated(self) -> bool:
        proof = self._verification
        return isinstance(proof, _VerifiedKnowledgeSourceProof) and proof.matches(
            self._claims()
        )


class KnowledgeReceiptVerifier:
    """Trusted resolver projection that issues byte- and identity-bound receipts."""

    def __init__(self, policy: TrustedKnowledgeSourcePolicy) -> None:
        self._policy = policy

    def issue(
        self, *, layer: str, contribution: str, source_content: str
    ) -> KnowledgeReceipt:
        policy = self._policy
        if contribution not in policy.contributions:
            raise ValueError("Knowledge contribution is not allowed by source policy.")
        receipt = KnowledgeReceipt(
            layer=layer,
            ref=policy.ref,
            tree=policy.tree,
            signer=policy.signer,
            contribution=contribution,
            content_sha256=hashlib.sha256(source_content.encode()).hexdigest(),
            runtime=policy.runtime,
            adapter_version=policy.adapter_version,
            repository=policy.repository,
        )
        proof = _VerifiedKnowledgeSourceProof(
            _VERIFIED_SOURCE_AUTHORITY, receipt._claims()
        )
        return replace(receipt, _verification=proof)


@dataclass(frozen=True)
class KnowledgeComposition:
    """Exact composed bytes and their authenticated source receipts."""

    content: str
    receipts: tuple[KnowledgeReceipt, ...]
    source_contents: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.content
            or not self.receipts
            or len(self.receipts) != len(self.source_contents)
        ):
            raise ValueError("Required Knowledge composition is unavailable.")
        if any(
            receipt.content_sha256 != hashlib.sha256(content.encode()).hexdigest()
            for receipt, content in zip(self.receipts, self.source_contents)
        ):
            raise ValueError("Knowledge receipt does not bind the composed bytes.")
        if any(not receipt.is_authenticated for receipt in self.receipts):
            raise ValueError("Knowledge source receipt is not authenticated.")
        canonical_content = _COMPOSITION_SEPARATOR.join(self.source_contents)
        if self.content != canonical_content:
            raise ValueError(
                "Knowledge composition is not the canonical source composition."
            )


@dataclass(frozen=True)
class SecurityReceipt:
    state: str
    reason: str

    def __post_init__(self) -> None:
        if self.state not in {"allowed", "denied", "unavailable"} or not self.reason:
            raise ValueError("Mandatory security receipt is malformed.")


@dataclass(frozen=True)
class RouteEvent:
    """One protocol-emitted transition, checkpoint, or skipped stage."""

    kind: str
    specialist: str
    reason: str

    def __post_init__(self) -> None:
        if (
            self.kind not in _ROUTE_EVENT_KINDS
            or not self.specialist
            or not self.reason
        ):
            raise ValueError("Protocol route event is malformed.")


@dataclass(frozen=True)
class RouteTrace:
    """Trace emitted by the supported protocol router; policy is not duplicated here."""

    classification: str
    specialists: tuple[str, ...]
    runtime: str
    contract_version: str
    events: tuple[RouteEvent, ...]

    def __post_init__(self) -> None:
        if not self.classification or not self.specialists:
            raise ValueError("Protocol route trace is incomplete.")
        if (
            not self.runtime
            or not self.contract_version
            or any(not item for item in self.specialists)
        ):
            raise ValueError("Protocol route trace is malformed.")
        transitions = tuple(
            event.specialist for event in self.events if event.kind == "transition"
        )
        if transitions != self.specialists:
            raise ValueError("Protocol route events do not match the specialist route.")


@dataclass(frozen=True)
class InvocationReceipt:
    specialist: str
    composed_content_sha256: str
    sources: tuple[KnowledgeReceipt, ...]

    def __post_init__(self) -> None:
        if (
            not self.specialist
            or not _DIGEST.fullmatch(self.composed_content_sha256)
            or not self.sources
        ):
            raise ValueError("Specialist invocation receipt is malformed.")


@dataclass(frozen=True)
class CapabilityReceipt:
    name: str
    state: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.name or self.state not in _CAPABILITY_STATES:
            raise ValueError("Operational capability receipt is malformed.")

    @property
    def core_may_continue(self) -> bool:
        return self.state != "security-denied"


@dataclass(frozen=True)
class JourneyCase:
    case_id: str
    prompt: str
    pause_after: int

    def __post_init__(self) -> None:
        if not self.case_id or not self.prompt or self.pause_after < 0:
            raise ValueError("Journey case is malformed.")


@dataclass(frozen=True)
class ContinuationLocator:
    task_id: int
    work_product_id: int
    capsule_sha256: str


@dataclass(frozen=True)
class JourneyEvidence:
    schema_version: str
    adapter_version: str
    outcome: str
    case_id: str
    route: RouteTrace
    invocations: tuple[InvocationReceipt, ...]
    capability: CapabilityReceipt
    security: SecurityReceipt
    prompt_sha256: str
    completed_specialists: tuple[str, ...]
    next_specialist: str | None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.schema_version != SCHEMA_VERSION
            or self.adapter_version != ADAPTER_VERSION
        ):
            raise ValueError("Journey evidence version is unsupported.")
        if self.outcome not in {"STRUCTURALLY_INTEGRATED", "UNSUPPORTED", "INVALID"}:
            raise ValueError("Journey outcome is invalid.")
        if not _DIGEST.fullmatch(self.prompt_sha256):
            raise ValueError("Journey prompt digest is invalid.")
        specialists = tuple(item.specialist for item in self.invocations)
        if specialists != self.completed_specialists:
            raise ValueError("Journey invocations do not match completed stages.")
        if tuple(self.route.specialists[: len(specialists)]) != specialists:
            raise ValueError("Journey invocations are not a protocol-route prefix.")
        expected_next = (
            self.route.specialists[len(specialists)]
            if len(specialists) < len(self.route.specialists)
            else None
        )
        if self.next_specialist != expected_next:
            raise ValueError("Journey next stage does not match the protocol route.")

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for invocation in value["invocations"]:
            for source in invocation["sources"]:
                source.pop("_verification", None)
        detail = value["capability"].get("detail", "")
        if detail and not detail.startswith("sha256:"):
            value["capability"]["detail"] = (
                "sha256:" + hashlib.sha256(detail.encode()).hexdigest()
            )
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> JourneyEvidence:
        try:
            route_value = value["route"]
            capability_value = value["capability"]
            route = RouteTrace(
                classification=str(route_value["classification"]),
                specialists=tuple(route_value["specialists"]),
                runtime=str(route_value["runtime"]),
                contract_version=str(route_value["contract_version"]),
                events=tuple(RouteEvent(**event) for event in route_value["events"]),
            )
            invocations = tuple(
                InvocationReceipt(
                    specialist=str(item["specialist"]),
                    composed_content_sha256=str(item["composed_content_sha256"]),
                    sources=tuple(
                        KnowledgeReceipt(**source) for source in item["sources"]
                    ),
                )
                for item in value["invocations"]
            )
            return cls(
                schema_version=str(value["schema_version"]),
                adapter_version=str(value["adapter_version"]),
                outcome=str(value["outcome"]),
                case_id=str(value["case_id"]),
                route=route,
                invocations=invocations,
                capability=CapabilityReceipt(**capability_value),
                security=SecurityReceipt(**value["security"]),
                prompt_sha256=str(value["prompt_sha256"]),
                completed_specialists=tuple(value["completed_specialists"]),
                next_specialist=value.get("next_specialist"),
                limitations=tuple(value.get("limitations") or ()),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Stored journey evidence is malformed.") from exc


class ProtocolRouteAdapter(Protocol):
    def trace(self, prompt: str) -> RouteTrace: ...


class KnowledgeAdapter(Protocol):
    def compose(self, *, specialist: str, prompt: str) -> KnowledgeComposition: ...


class OperationalCapabilityAdapter(Protocol):
    def invoke(self, *, case_id: str) -> CapabilityReceipt: ...


class SecurityAdapter(Protocol):
    def authorize(self, *, case_id: str) -> SecurityReceipt: ...


class ContinuationStore(Protocol):
    def save(self, capsule: Mapping[str, Any]) -> ContinuationLocator: ...

    def load(self, locator: ContinuationLocator) -> Mapping[str, Any]: ...

    def load_completion(
        self, locator: ContinuationLocator
    ) -> Mapping[str, Any] | None: ...

    def save_completion(
        self, locator: ContinuationLocator, evidence: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def claim(self, locator: ContinuationLocator): ...


class TcContinuationStore:
    """Thin adapter over Task Copilot's public work-product API.

    Callables are injected so ``cc`` does not acquire a package dependency on
    ``tc``.  Production binds ``tc.api.store_wp/get_wp``; tests can use an
    isolated store.  The locator contains only task id, work-product id, and
    the capsule hash, so a fresh process can resume without ambient state.
    """

    def __init__(
        self,
        *,
        task_id: int,
        store_wp: Callable[..., Mapping[str, Any]],
        get_wp: Callable[..., Mapping[str, Any]],
        list_wps: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._task_id = task_id
        self._store_wp = store_wp
        self._get_wp = get_wp
        self._list_wps = list_wps
        self._local_completions: dict[str, Mapping[str, Any]] = {}

    def save(self, capsule: Mapping[str, Any]) -> ContinuationLocator:
        content = _canonical(capsule)
        row = self._store_wp(
            task_id=self._task_id,
            type_="evidence",
            title=f"Journey continuation: {capsule['case_id']}",
            content=content,
            agent="cc-journey",
        )
        return ContinuationLocator(self._task_id, int(row["id"]), _digest(capsule))

    def load(self, locator: ContinuationLocator) -> Mapping[str, Any]:
        if locator.task_id != self._task_id:
            raise ValueError("Continuation task identity changed.")
        row = self._get_wp(wp_id=locator.work_product_id)
        expected_title_prefix = "Journey continuation: "
        if (
            int(row.get("task_id", -1)) != self._task_id
            or row.get("type_", row.get("type")) != "evidence"
            or not str(row.get("title", "")).startswith(expected_title_prefix)
        ):
            raise ValueError("Continuation work product identity is invalid.")
        try:
            capsule = json.loads(str(row["content"]))
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Continuation work product is malformed.") from exc
        if not isinstance(capsule, dict) or _digest(capsule) != locator.capsule_sha256:
            raise ValueError("Continuation capsule integrity check failed.")
        if row["title"] != expected_title_prefix + str(capsule.get("case_id", "")):
            raise ValueError("Continuation locator is not bound to its case.")
        return capsule

    @contextmanager
    def claim(self, locator: ContinuationLocator):
        """Serialize the full check/execute/complete suffix across processes."""
        key = f"{locator.task_id}-{locator.capsule_sha256}.lock"
        path = os.path.join(tempfile.gettempdir(), "cc-journey-" + key)
        with open(path, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _completion_title(locator: ContinuationLocator) -> str:
        return f"Journey completion: {locator.capsule_sha256}"

    def load_completion(self, locator: ContinuationLocator) -> Mapping[str, Any] | None:
        title = self._completion_title(locator)
        if self._list_wps is None:
            return self._local_completions.get(title)
        matches = [
            row
            for row in self._list_wps(task=self._task_id, type_="evidence")
            if row.get("title") == title
        ]
        if len(matches) > 1:
            raise ValueError("Continuation has duplicate completion evidence.")
        if not matches:
            return None
        row = self._get_wp(wp_id=int(matches[0]["id"]))
        if (
            int(row.get("task_id", -1)) != self._task_id
            or row.get("type_", row.get("type")) != "evidence"
            or row.get("title") != title
        ):
            raise ValueError("Continuation completion identity is invalid.")
        try:
            payload = json.loads(str(row["content"]))
            evidence = payload["evidence"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Continuation completion evidence is malformed.") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("locator") != asdict(locator)
            or not isinstance(evidence, dict)
            or payload.get("evidence_sha256") != _digest(evidence)
        ):
            raise ValueError("Continuation completion evidence is invalid.")
        return evidence

    def save_completion(
        self, locator: ContinuationLocator, evidence: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        existing = self.load_completion(locator)
        if existing is not None:
            return existing
        title = self._completion_title(locator)
        payload = {
            "locator": asdict(locator),
            "evidence": evidence,
            "evidence_sha256": _digest(evidence),
        }
        if self._list_wps is None:
            self._local_completions[title] = dict(evidence)
            return evidence
        self._store_wp(
            task_id=self._task_id,
            type_="evidence",
            title=title,
            content=_canonical(payload),
            agent="cc-journey",
        )
        return self.load_completion(locator) or evidence


class DeterministicJourneyAdapter:
    """Compose injected framework boundaries into attributable evidence."""

    def __init__(
        self,
        *,
        protocol: ProtocolRouteAdapter,
        knowledge: KnowledgeAdapter,
        capability: OperationalCapabilityAdapter,
        security: SecurityAdapter,
        continuation: ContinuationStore,
    ) -> None:
        self._protocol = protocol
        self._knowledge = knowledge
        self._capability = capability
        self._security = security
        self._continuation = continuation

    def start(self, case: JourneyCase) -> tuple[JourneyEvidence, ContinuationLocator]:
        route = self._protocol.trace(case.prompt)
        if case.pause_after > len(route.specialists):
            raise ValueError("Pause stage exceeds the protocol route.")
        security = self._safe_security(case.case_id)
        capability = (
            self._safe_capability(case.case_id)
            if security.state == "allowed"
            else CapabilityReceipt("optional-operations", "malformed")
        )
        evidence = self._run(
            case=case,
            route=route,
            capability=capability,
            security=security,
            completed=(),
            prior=(),
            stop=case.pause_after,
        )
        capsule = {
            "case_id": case.case_id,
            "prompt_sha256": hashlib.sha256(case.prompt.encode()).hexdigest(),
            "evidence": evidence.as_dict(),
        }
        return evidence, self._continuation.save(capsule)

    def resume(self, locator: ContinuationLocator) -> JourneyEvidence:
        with self._continuation.claim(locator):
            return self._resume_claimed(locator)

    def _resume_claimed(self, locator: ContinuationLocator) -> JourneyEvidence:
        completed_evidence = self._continuation.load_completion(locator)
        if completed_evidence is not None:
            return JourneyEvidence.from_dict(completed_evidence)
        capsule = self._continuation.load(locator)
        saved = capsule.get("evidence")
        if not isinstance(saved, dict):
            raise ValueError("Continuation evidence is missing.")
        route_data = saved.get("route")
        if not isinstance(route_data, dict):
            raise ValueError("Continuation route is missing.")
        route = JourneyEvidence.from_dict(saved).route
        prior = tuple(
            self._invocation_from_dict(item) for item in saved.get("invocations") or ()
        )
        completed = tuple(saved.get("completed_specialists") or ())
        capability_data = saved.get("capability") or {}
        capability = CapabilityReceipt(
            name=str(capability_data.get("name", "")),
            state=str(capability_data.get("state", "")),
            detail=str(capability_data.get("detail", "")),
        )
        security = SecurityReceipt(**saved.get("security", {}))
        prompt_sha256 = str(capsule.get("prompt_sha256", ""))
        if prompt_sha256 != saved.get("prompt_sha256") or not _DIGEST.fullmatch(
            prompt_sha256
        ):
            raise ValueError("Continuation prompt identity changed.")
        case = JourneyCase(
            str(capsule.get("case_id", "")),
            prompt_sha256,
            len(route.specialists),
        )
        evidence = self._run(
            case=case,
            route=route,
            capability=capability,
            security=security,
            completed=completed,
            prior=prior,
            stop=len(route.specialists),
        )
        stored = self._continuation.save_completion(locator, evidence.as_dict())
        return JourneyEvidence.from_dict(stored)

    def _run(
        self,
        *,
        case: JourneyCase,
        route: RouteTrace,
        capability: CapabilityReceipt,
        security: SecurityReceipt,
        completed: Sequence[str],
        prior: Sequence[InvocationReceipt],
        stop: int,
    ) -> JourneyEvidence:
        if tuple(route.specialists[: len(completed)]) != tuple(completed):
            raise ValueError("Completed stages are not a protocol-route prefix.")
        if len(prior) != len(completed):
            raise ValueError("Continuation evidence has missing or duplicate stages.")
        invocations = list(prior)
        invalid_reason: str | None = None
        if security.state != "allowed" or not capability.core_may_continue:
            invalid_reason = f"security-{security.state}"
        else:
            for specialist in route.specialists[len(completed) : stop]:
                try:
                    composition = self._knowledge.compose(
                        specialist=specialist, prompt=case.prompt
                    )
                    if not isinstance(composition, KnowledgeComposition):
                        raise TypeError(
                            "Knowledge adapter returned a malformed composition."
                        )
                    invocations.append(
                        InvocationReceipt(
                            specialist=specialist,
                            composed_content_sha256=hashlib.sha256(
                                composition.content.encode()
                            ).hexdigest(),
                            sources=composition.receipts,
                        )
                    )
                except (OSError, TypeError, ValueError):
                    invalid_reason = f"required-knowledge-invalid:{specialist}"
                    break
        finished = tuple(item.specialist for item in invocations)
        next_specialist = (
            route.specialists[len(finished)]
            if len(finished) < len(route.specialists)
            else None
        )
        runtime_limitations = (
            ()
            if route.runtime == "claude"
            else (f"{route.runtime}-knowledge-parity-unproven",)
        )
        limitations = runtime_limitations + (
            (invalid_reason,) if invalid_reason else ()
        )
        if invalid_reason is not None:
            outcome = "INVALID"
        elif route.runtime == "claude":
            outcome = "STRUCTURALLY_INTEGRATED"
        else:
            outcome = "UNSUPPORTED"
        return JourneyEvidence(
            schema_version=SCHEMA_VERSION,
            adapter_version=ADAPTER_VERSION,
            outcome=outcome,
            case_id=case.case_id,
            route=route,
            invocations=tuple(invocations),
            capability=capability,
            security=security,
            prompt_sha256=(
                case.prompt
                if _DIGEST.fullmatch(case.prompt)
                else hashlib.sha256(case.prompt.encode()).hexdigest()
            ),
            completed_specialists=finished,
            next_specialist=next_specialist,
            limitations=limitations,
        )

    def _safe_capability(self, case_id: str) -> CapabilityReceipt:
        try:
            result = self._capability.invoke(case_id=case_id)
            return (
                result
                if isinstance(result, CapabilityReceipt)
                else CapabilityReceipt("optional-operations", "malformed")
            )
        except PermissionError:
            return CapabilityReceipt("optional-operations", "security-denied")
        except TimeoutError:
            return CapabilityReceipt("optional-operations", "timeout")
        except (OSError, ValueError, TypeError):
            return CapabilityReceipt("optional-operations", "malformed")

    def _safe_security(self, case_id: str) -> SecurityReceipt:
        try:
            result = self._security.authorize(case_id=case_id)
            return (
                result
                if isinstance(result, SecurityReceipt)
                else SecurityReceipt("denied", "malformed-security-result")
            )
        except PermissionError:
            return SecurityReceipt("denied", "authorization-denied")
        except (OSError, TimeoutError, ValueError, TypeError):
            return SecurityReceipt("unavailable", "security-gate-unavailable")

    @staticmethod
    def _invocation_from_dict(value: Mapping[str, Any]) -> InvocationReceipt:
        return InvocationReceipt(
            specialist=str(value.get("specialist", "")),
            composed_content_sha256=str(value.get("composed_content_sha256", "")),
            sources=tuple(
                KnowledgeReceipt(**item) for item in value.get("sources") or ()
            ),
        )
