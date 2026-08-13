from __future__ import annotations

import hashlib
import subprocess
import threading
from pathlib import Path

import pytest

from cc.core.evaluation.journey import CapabilityReceipt
from cc.core.evaluation.journey_runtime import (
    CliCopilotHealthCapabilityAdapter,
    TcJourneyLedger,
    begin_run,
    inspect_run,
    pause_run,
    prepare_run,
    resume_run,
    verify_dispatch,
)


class Rows:
    """Thread-safe stand-in for the public tc work-product signatures."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: dict[int, dict] = {}

    def store_wp(self, **values):
        with self._lock:
            row_id = len(self.items) + 1
            self.items[row_id] = {"id": row_id, **values}
            return self.items[row_id]

    def get_wp(self, *, wp_id):
        return self.items[wp_id]

    def list_wps(self, *, task=None, type_=None):
        with self._lock:
            rows = tuple(self.items.values())
        return [
            row
            for row in reversed(rows)
            if (task is None or row["task_id"] == task)
            and (type_ is None or row["type_"] == type_)
        ]


def receipt(content: str, specialist: str) -> dict[str, str]:
    return {
        "layer": "organization",
        "repository": "knowledge-fixture",
        "ref": "refs/tags/v1.0.0",
        "tree": "a" * 40,
        "signer": "SHA256:test-signer",
        "contribution": f"skills/{specialist}",
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "runtime": "claude",
        "adapter_version": "knowledge-v1",
    }


def resolver(specialist: str):
    content = f"signed context for {specialist}"
    return content, (receipt(content, specialist),)


def ledger(rows: Rows, task_id: int = 296) -> TcJourneyLedger:
    return TcJourneyLedger(
        task_id,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
    )


def ledger_factory(rows: Rows):
    return lambda task_id: ledger(rows, task_id)


def begin(rows: Rows, *, specialists=("me", "qa"), session="session-296"):
    return begin_run(
        task_id=296,
        runtime="claude",
        classification="implementation",
        specialists=specialists,
        events=[
            {"kind": "transition", "specialist": item, "reason": "protocol supplied"}
            for item in specialists
        ],
        prompt_sha256="b" * 64,
        session_id=session,
        ledger=ledger(rows),
        capability=type("Capability", (), {"invoke": lambda self, **_: CapabilityReceipt("cli-copilot-health", "unavailable")})(),
    )


def authorize(rows: Rows, prepared, *, prompt_sha="c" * 64, selected_resolver=resolver):
    return verify_dispatch(
        session_id="session-296",
        specialist=prepared.specialist,
        marker=prepared.invocation_marker,
        prompt_sha256=prompt_sha,
        knowledge_sha256=prepared.composed_content_sha256,
        ledger_factory=ledger_factory(rows),
        resolver=selected_resolver,
    )


def test_begin_prepare_dispatch_pause_fresh_resume_and_next_dispatch():
    rows = Rows()
    started = begin(rows)
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    assert authorize(rows, first)["state"] == "dispatch_authorized"
    assert pause_run(started["run_id"], ledger=ledger(rows))["status"] == "paused"

    # A newly constructed ledger has no ambient state; it resumes from tc rows.
    resumed = resume_run(296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver)
    assert resumed["completed_specialists"] == ("me",)
    assert resumed["next_specialist"] == "qa"
    second = resumed["prepared_invocation"]
    result = verify_dispatch(
        session_id="session-296",
        specialist="qa",
        marker=second["invocation_marker"],
        prompt_sha256="d" * 64,
        knowledge_sha256=second["composed_content_sha256"],
        ledger_factory=ledger_factory(rows),
        resolver=resolver,
    )
    assert result["state"] == "dispatch_authorized"
    assert inspect_run(started["run_id"], ledger=ledger(rows))["status"] == "completed"


def test_no_active_legacy_and_missing_wrong_or_replayed_markers():
    rows = Rows()
    factory = ledger_factory(rows)
    assert verify_dispatch(
        session_id="legacy", specialist="me", marker="", prompt_sha256="c" * 64,
        knowledge_sha256="", ledger_factory=factory, resolver=resolver,
    )["state"] == "no_active"

    started = begin(rows)
    with pytest.raises(ValueError, match="active-journey-marker-required"):
        verify_dispatch(
            session_id="session-296", specialist="me", marker="", prompt_sha256="c" * 64,
            knowledge_sha256="", ledger_factory=factory, resolver=resolver,
        )
    prepared = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    with pytest.raises(ValueError, match="route-order"):
        verify_dispatch(
            session_id="session-296", specialist="qa", marker=prepared.invocation_marker,
            prompt_sha256="c" * 64, knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=factory, resolver=resolver,
        )
    authorize(rows, prepared)
    with pytest.raises(ValueError, match="route-order"):
        authorize(rows, prepared)


def test_signed_source_binding_is_rechecked_before_dispatch():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)

    def changed(specialist: str):
        content = "changed signed bytes"
        return content, (receipt(content, specialist),)

    with pytest.raises(ValueError, match="dispatch-knowledge-changed"):
        authorize(rows, prepared, selected_resolver=changed)
    assert inspect_run(started["run_id"], ledger=ledger(rows))["completed_specialists"] == ()


def test_concurrent_dispatch_consumes_tc_stage_exactly_once():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            outcomes.append(authorize(rows, prepared)["state"])
        except ValueError as exc:
            outcomes.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("dispatch_authorized") == 1
    assert outcomes.count("dispatch-route-order-mismatch") == 1
    titles = [item["title"] for item in rows.items.values()]
    assert sum(title.startswith("Journey v2 dispatch: ") for title in titles) == 1
    assert sum(title.startswith("Journey v2 completion: ") for title in titles) == 1


@pytest.mark.parametrize(
    ("resolver_result", "run_result", "state"),
    [
        (None, None, "unavailable"),
        (Path("/bin/false"), subprocess.CompletedProcess([], 2, "out", "err"), "nonzero"),
        (Path("/bin/echo"), subprocess.CompletedProcess([], 0, "not-json", ""), "malformed"),
        (Path("/bin/echo"), subprocess.CompletedProcess([], 0, '{"status":"ok"}', ""), "available"),
    ],
)
def test_optional_health_matrix_is_typed_and_fail_open(resolver_result, run_result, state):
    def run(*_args, **_kwargs):
        assert run_result is not None
        return run_result

    adapter = CliCopilotHealthCapabilityAdapter(
        resolver=lambda _name: resolver_result,
        run=run,
    )
    assert adapter.invoke(case_id="fixture").state == state
