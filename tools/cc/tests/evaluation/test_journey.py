from __future__ import annotations

import hashlib
import threading
from types import SimpleNamespace

import pytest
from cc.core.evaluation.journey import (
    CapabilityReceipt,
    DeterministicJourneyAdapter,
    JourneyCase,
    KnowledgeComposition,
    KnowledgeReceipt,
    KnowledgeReceiptVerifier,
    RouteEvent,
    RouteTrace,
    SecurityReceipt,
    TcContinuationStore,
    TrustedKnowledgeSourcePolicy,
)


def verified_receipt(content: str, contribution: str) -> KnowledgeReceipt:
    policy = TrustedKnowledgeSourcePolicy(
        repository="local-fixture",
        ref="v1.0.0",
        tree="a" * 40,
        signer="SHA256:test",
        runtime="claude",
        adapter_version="knowledge-v1",
        contributions=frozenset({contribution}),
    )
    return KnowledgeReceiptVerifier(policy).issue(
        layer="organization", contribution=contribution, source_content=content
    )


class Protocol:
    runtime = "claude"

    def trace(self, prompt: str) -> RouteTrace:
        return RouteTrace(
            "feature",
            ("ta", "me", "qa"),
            self.runtime,
            "protocol-v1",
            (
                RouteEvent("transition", "ta", "architecture required"),
                RouteEvent("transition", "me", "implementation required"),
                RouteEvent("checkpoint", "me", "implementation stored before QA"),
                RouteEvent("transition", "qa", "independent verification required"),
                RouteEvent("skip", "sec", "no new trust boundary in synthetic case"),
            ),
        )


class Knowledge:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    def compose(self, *, specialist: str, prompt: str) -> KnowledgeComposition:
        self.calls.append(specialist)
        if self.error:
            raise self.error
        content = f"synthetic context for {specialist}"
        receipt = verified_receipt(content, f"skills/{specialist}")
        return KnowledgeComposition(content, (receipt,), (content,))


class UntypedKnowledge:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def compose(self, *, specialist: str, prompt: str):
        self.calls.append(specialist)
        return self.result


class ExplosiveKnowledgeResult:
    @property
    def content(self):
        raise AssertionError("malformed Knowledge fields must not be accessed")


class Capability:
    def __init__(self, result=None, error=None):
        self.result = (
            CapabilityReceipt("repo-status", "available", "synthetic")
            if result is None
            else result
        )
        self.error = error

    def invoke(self, *, case_id: str) -> CapabilityReceipt:
        if self.error:
            raise self.error
        return self.result


class Security:
    def __init__(self, result=SecurityReceipt("allowed", "fixture-policy"), error=None):
        self.result = result
        self.error = error

    def authorize(self, *, case_id: str) -> SecurityReceipt:
        if self.error:
            raise self.error
        return self.result


class Rows:
    def __init__(self):
        self.rows = {}

    def store_wp(self, **values):
        row_id = len(self.rows) + 1
        self.rows[row_id] = {"id": row_id, **values}
        return self.rows[row_id]

    def get_wp(self, *, wp_id):
        return self.rows[wp_id]

    def list_wps(self, *, task=None, type_=None):
        return [
            row
            for row in reversed(tuple(self.rows.values()))
            if (task is None or row.get("task_id") == task)
            and (type_ is None or row.get("type_") == type_)
        ]


def adapters(*, runtime="claude", capability=None, knowledge=None):
    rows = Rows()
    protocol = Protocol()
    protocol.runtime = runtime
    store = TcContinuationStore(
        task_id=296,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
    )
    selected_knowledge = knowledge or Knowledge()
    return (
        rows,
        protocol,
        store,
        selected_knowledge,
        DeterministicJourneyAdapter(
            protocol=protocol,
            knowledge=selected_knowledge,
            capability=capability or Capability(),
            security=Security(),
            continuation=store,
        ),
    )


def test_fresh_adapter_resumes_exact_next_stage_without_duplication():
    rows, protocol, store, _knowledge, first = adapters()
    paused, locator = first.start(JourneyCase("case-1", "build interview synthesis", 1))
    assert paused.completed_specialists == ("ta",)
    assert paused.next_specialist == "me"
    assert len(rows.rows) == 1

    resumed_knowledge = Knowledge()
    fresh = DeterministicJourneyAdapter(
        protocol=protocol,
        knowledge=resumed_knowledge,
        capability=Capability(),
        security=Security(),
        continuation=store,
    )
    resumed = fresh.resume(locator)
    assert resumed.completed_specialists == ("ta", "me", "qa")
    assert [item.specialist for item in resumed.invocations] == ["ta", "me", "qa"]
    assert len(rows.rows) == 2

    calls_before_replay = tuple(resumed_knowledge.calls)
    replayed = fresh.resume(locator)
    assert replayed == resumed
    assert tuple(resumed_knowledge.calls) == calls_before_replay
    assert len(rows.rows) == 2


@pytest.mark.parametrize(
    "error,state", [(TimeoutError(), "timeout"), (OSError(), "malformed")]
)
def test_optional_capability_failures_preserve_core_route(error, state):
    _rows, _protocol, _store, _knowledge, adapter = adapters(
        capability=Capability(error=error)
    )
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "STRUCTURALLY_INTEGRATED"
    assert evidence.capability.state == state


def test_security_denial_is_fail_closed():
    rows, protocol, store, knowledge, _adapter = adapters()
    adapter = DeterministicJourneyAdapter(
        protocol=protocol,
        knowledge=knowledge,
        capability=Capability(),
        security=Security(SecurityReceipt("denied", "policy")),
        continuation=store,
    )
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "INVALID"
    assert evidence.completed_specialists == ()
    assert evidence.next_specialist == "ta"
    assert knowledge.calls == []


@pytest.mark.parametrize(
    "error", [PermissionError("denied"), OSError("auth unavailable")]
)
def test_mandatory_security_errors_fail_closed_before_knowledge(error):
    _rows, protocol, store, knowledge, _adapter = adapters()
    adapter = DeterministicJourneyAdapter(
        protocol=protocol,
        knowledge=knowledge,
        capability=Capability(),
        security=Security(error=error),
        continuation=store,
    )
    evidence, _ = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "INVALID"
    assert knowledge.calls == []


def test_untyped_malformed_capability_result_is_typed_fail_open():
    _rows, _protocol, _store, _knowledge, adapter = adapters(
        capability=Capability(result={})
    )
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "STRUCTURALLY_INTEGRATED"
    assert evidence.capability == CapabilityReceipt("optional-operations", "malformed")


def test_permission_denial_from_operational_boundary_fails_closed():
    _rows, _protocol, _store, knowledge, adapter = adapters(
        capability=Capability(error=PermissionError("denied"))
    )
    evidence, _ = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "INVALID"
    assert knowledge.calls == []


def test_missing_required_knowledge_returns_invalid_evidence():
    missing = Knowledge(error=ValueError("required Knowledge unavailable"))
    _rows, _protocol, _store, _knowledge, adapter = adapters(knowledge=missing)
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "INVALID"
    assert evidence.completed_specialists == ()
    assert evidence.next_specialist == "ta"
    assert evidence.limitations == ("required-knowledge-invalid:ta",)


@pytest.mark.parametrize(
    "malformed",
    [
        {},
        None,
        SimpleNamespace(wrong_field="context"),
        SimpleNamespace(content=42, receipts="wrong-type"),
        ExplosiveKnowledgeResult(),
    ],
    ids=["dict", "none", "wrong-field", "wrong-type", "unreadable-fields"],
)
def test_malformed_untyped_knowledge_returns_invalid_without_field_access(malformed):
    knowledge = UntypedKnowledge(malformed)
    _rows, _protocol, _store, _knowledge, adapter = adapters(knowledge=knowledge)
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "INVALID"
    assert evidence.completed_specialists == ()
    assert evidence.next_specialist == "ta"
    assert evidence.limitations == ("required-knowledge-invalid:ta",)
    assert knowledge.calls == ["ta"]


def test_tampered_continuation_is_rejected():
    rows, _protocol, _store, _knowledge, adapter = adapters()
    _paused, locator = adapter.start(JourneyCase("case-1", "problem", 1))
    rows.rows[locator.work_product_id]["content"] = rows.rows[locator.work_product_id][
        "content"
    ].replace('"case-1"', '"case-2"')
    with pytest.raises(ValueError, match="integrity"):
        adapter.resume(locator)


def test_codex_is_enumerated_as_explicit_parity_gap():
    _rows, _protocol, _store, _knowledge, adapter = adapters(runtime="codex")
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "UNSUPPORTED"
    assert evidence.limitations == ("codex-knowledge-parity-unproven",)


def test_knowledge_bytes_must_match_attributable_receipt():
    receipt = KnowledgeReceipt(
        "organization", "v1", "a" * 40, "signer", "skill", "b" * 64, "claude", "v1"
    )
    with pytest.raises(ValueError, match="does not bind"):
        KnowledgeComposition("composed bytes", (receipt,), ("different bytes",))


def test_unrelated_composed_content_and_unauthenticated_source_are_rejected():
    source = "source"
    receipt = verified_receipt(source, "skill")
    with pytest.raises(ValueError, match="canonical"):
        KnowledgeComposition("INJECTED", (receipt,), (source,))
    manual = KnowledgeReceipt(
        "organization",
        "v1",
        "a" * 40,
        "signer",
        "skill",
        hashlib.sha256(source.encode()).hexdigest(),
        "claude",
        "v1",
    )
    with pytest.raises(ValueError, match="not authenticated"):
        KnowledgeComposition(source, (manual,), (source,))


def test_safe_looking_fabricated_identity_and_counterfeit_proof_are_rejected():
    source = "source"
    attacker = KnowledgeReceipt(
        "organization",
        "attacker-ref",
        "a" * 40,
        "attacker-signer",
        "skills/ta",
        hashlib.sha256(source.encode()).hexdigest(),
        "claude",
        "attacker-adapter",
    )
    assert not attacker.is_authenticated
    with pytest.raises(ValueError, match="not authenticated"):
        KnowledgeComposition(source, (attacker,), (source,))
    counterfeit = KnowledgeReceipt(
        "organization",
        "v1",
        "a" * 40,
        "signer",
        "skills/ta",
        hashlib.sha256(source.encode()).hexdigest(),
        "claude",
        "v1",
        _verification=object(),
    )
    assert not counterfeit.is_authenticated
    with pytest.raises(ValueError, match="not authenticated"):
        KnowledgeComposition(source, (counterfeit,), (source,))


def test_verifier_binds_every_policy_identity_and_source_bytes():
    source = "source"
    policy = TrustedKnowledgeSourcePolicy(
        "trusted-repo",
        "v1",
        "a" * 40,
        "trusted-signer",
        "claude",
        "v1",
        frozenset({"skills/ta"}),
    )
    receipt = KnowledgeReceiptVerifier(policy).issue(
        layer="organization", contribution="skills/ta", source_content=source
    )
    assert receipt.is_authenticated
    assert KnowledgeComposition(source, (receipt,), (source,)).content == source
    with pytest.raises(ValueError, match="not allowed"):
        KnowledgeReceiptVerifier(policy).issue(
            layer="organization", contribution="skills/me", source_content=source
        )


def test_continuation_row_identity_and_plaintext_privacy_are_enforced():
    rows, _protocol, store, _knowledge, adapter = adapters()
    secret_prompt = "token=secret /Users/alice/private"
    _evidence, locator = adapter.start(JourneyCase("case-1", secret_prompt, 1))
    persisted = rows.rows[locator.work_product_id]["content"]
    assert secret_prompt not in persisted
    assert hashlib.sha256(secret_prompt.encode()).hexdigest() in persisted
    rows.rows[locator.work_product_id]["task_id"] = 999
    with pytest.raises(ValueError, match="identity"):
        store.load(locator)


def test_concurrent_resume_executes_suffix_and_completion_once():
    rows, protocol, store, _knowledge, first = adapters()
    _paused, locator = first.start(JourneyCase("race", "problem", 1))
    knowledge = Knowledge()
    results = []
    errors = []

    def resume():
        try:
            adapter = DeterministicJourneyAdapter(
                protocol=protocol,
                knowledge=knowledge,
                capability=Capability(),
                security=Security(),
                continuation=store,
            )
            results.append(adapter.resume(locator))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=resume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert results[0] == results[1]
    assert knowledge.calls == ["me", "qa"]
    completions = [
        row
        for row in rows.rows.values()
        if str(row["title"]).startswith("Journey completion:")
    ]
    assert len(completions) == 1


def test_route_trace_requires_ordered_transitions_and_reasoned_checkpoint_skip():
    trace = Protocol().trace("problem")
    assert tuple(event.kind for event in trace.events) == (
        "transition",
        "transition",
        "checkpoint",
        "transition",
        "skip",
    )
    with pytest.raises(ValueError, match="malformed"):
        RouteEvent("skip", "sec", "")
    with pytest.raises(ValueError, match="do not match"):
        RouteTrace(
            "feature",
            ("ta",),
            "claude",
            "protocol-v1",
            (RouteEvent("transition", "me", "wrong transition"),),
        )
