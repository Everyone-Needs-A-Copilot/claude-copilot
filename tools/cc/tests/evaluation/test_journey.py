from __future__ import annotations

import hashlib

import pytest

from cc.core.evaluation.journey import (
    CapabilityReceipt,
    DeterministicJourneyAdapter,
    JourneyCase,
    KnowledgeComposition,
    KnowledgeReceipt,
    RouteTrace,
    TcContinuationStore,
)


class Protocol:
    runtime = "claude"

    def trace(self, prompt: str) -> RouteTrace:
        return RouteTrace("feature", ("ta", "me", "qa"), self.runtime, "protocol-v1")


class Knowledge:
    def compose(self, *, specialist: str, prompt: str) -> KnowledgeComposition:
        content = f"synthetic context for {specialist}"
        receipt = KnowledgeReceipt(
            layer="organization",
            ref="v1.0.0",
            tree="a" * 40,
            signer="SHA256:test",
            contribution=f"skills/{specialist}",
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            runtime="claude",
            adapter_version="knowledge-v1",
        )
        return KnowledgeComposition(content, (receipt,), (content,))


class Capability:
    def __init__(self, result=None, error=None):
        self.result = result or CapabilityReceipt("repo-status", "available", "synthetic")
        self.error = error

    def invoke(self, *, case_id: str) -> CapabilityReceipt:
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


def adapters(*, runtime="claude", capability=None):
    rows = Rows()
    protocol = Protocol()
    protocol.runtime = runtime
    store = TcContinuationStore(task_id=296, store_wp=rows.store_wp, get_wp=rows.get_wp)
    return rows, protocol, store, DeterministicJourneyAdapter(
        protocol=protocol,
        knowledge=Knowledge(),
        capability=capability or Capability(),
        continuation=store,
    )


def test_fresh_adapter_resumes_exact_next_stage_without_duplication():
    rows, protocol, store, first = adapters()
    paused, locator = first.start(JourneyCase("case-1", "build interview synthesis", 1))
    assert paused.completed_specialists == ("ta",)
    assert paused.next_specialist == "me"
    assert len(rows.rows) == 1

    fresh = DeterministicJourneyAdapter(
        protocol=protocol,
        knowledge=Knowledge(),
        capability=Capability(),
        continuation=store,
    )
    resumed = fresh.resume(locator)
    assert resumed.completed_specialists == ("ta", "me", "qa")
    assert [item.specialist for item in resumed.invocations] == ["ta", "me", "qa"]
    assert len(rows.rows) == 1


@pytest.mark.parametrize("error,state", [(TimeoutError(), "timeout"), (OSError(), "malformed")])
def test_optional_capability_failures_preserve_core_route(error, state):
    _rows, _protocol, _store, adapter = adapters(capability=Capability(error=error))
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "STRUCTURALLY_INTEGRATED"
    assert evidence.capability.state == state


def test_security_denial_is_fail_closed():
    denied = Capability(CapabilityReceipt("repo-status", "security-denied"))
    _rows, _protocol, _store, adapter = adapters(capability=denied)
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "INVALID"


def test_tampered_continuation_is_rejected():
    rows, _protocol, _store, adapter = adapters()
    _paused, locator = adapter.start(JourneyCase("case-1", "problem", 1))
    rows.rows[locator.work_product_id]["content"] = rows.rows[locator.work_product_id][
        "content"
    ].replace('"case-1"', '"case-2"')
    with pytest.raises(ValueError, match="integrity"):
        adapter.resume(locator)


def test_codex_is_enumerated_as_explicit_parity_gap():
    _rows, _protocol, _store, adapter = adapters(runtime="codex")
    evidence, _locator = adapter.start(JourneyCase("case-1", "problem", 3))
    assert evidence.outcome == "UNSUPPORTED"
    assert evidence.limitations == ("codex-knowledge-parity-unproven",)


def test_knowledge_bytes_must_match_attributable_receipt():
    receipt = KnowledgeReceipt(
        "organization", "v1", "a" * 40, "signer", "skill", "b" * 64, "claude", "v1"
    )
    with pytest.raises(ValueError, match="does not bind"):
        KnowledgeComposition("composed bytes", (receipt,), ("different bytes",))
