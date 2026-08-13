from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
import sqlite3
import stat
import subprocess
import threading
import time
from pathlib import Path

import pytest
from cc.core.evaluation.journey import CapabilityReceipt
from cc.core.evaluation.journey_runtime import (
    CliCopilotHealthCapabilityAdapter,
    MandatorySecurityVerifier,
    TcJourneyLedger,
    begin_run,
    bind_prompt,
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
        allow_missing_guard=True,
    )


def ledger_factory(rows: Rows):
    return lambda task_id: ledger(rows, task_id)


def global_lock_worker(queue):
    rows = Rows()
    selected = TcJourneyLedger(
        296,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
        lock_timeout=0.05,
        allow_missing_guard=True,
    )
    try:
        with selected.claim("same-run"):
            queue.put("acquired")
    except RuntimeError as exc:
        queue.put(str(exc))


def global_lock_holder(ready, release):
    rows = Rows()
    selected = TcJourneyLedger(
        296,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
        lock_timeout=1.0,
        allow_missing_guard=True,
    )
    with selected.claim("same-run"):
        ready.set()
        release.wait(timeout=10)


def begin(rows: Rows, *, specialists=("me", "qa"), session="session-296"):
    return begin_run(
        task_id=296,
        runtime="claude",
        classification="implementation",
        specialists=specialists,
        events=[
            {"kind": "transition", "specialist": item, "reason": "protocol-supplied"}
            for item in specialists
        ],
        prompt_sha256="b" * 64,
        session_id=session,
        ledger=ledger(rows),
        capability=type(
            "Capability",
            (),
            {
                "invoke": lambda self, **_: CapabilityReceipt(
                    "cli-copilot-health", "unavailable"
                )
            },
        )(),
    )


def authorize(rows: Rows, prepared, *, prompt_sha="c" * 64, selected_resolver=resolver):
    bind_prompt(
        prepared.run_id,
        prepared.specialist,
        prompt_sha,
        ledger=ledger(rows),
    )
    return verify_dispatch(
        session_id="session-296",
        specialist=prepared.specialist,
        marker=prepared.invocation_marker,
        prompt_sha256=prompt_sha,
        knowledge_sha256=prepared.composed_content_sha256,
        ledger_factory=ledger_factory(rows),
        resolver=selected_resolver,
    )


def payload_for(row):
    return json.loads(row["content"])


def reassign_row_order(rows: Rows, ordered: list[dict]) -> None:
    rows.items = {}
    for row_id, row in enumerate(ordered, start=1):
        row["id"] = row_id
        rows.items[row_id] = row


def two_stage_progress(rows: Rows):
    started = begin(rows, specialists=("me", "qa", "sec"))
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    authorize(rows, first)
    second = prepare_run(
        started["run_id"], "qa", ledger=ledger(rows), resolver=resolver
    )
    authorize(rows, second, prompt_sha="d" * 64)
    return started


def test_begin_prepare_dispatch_pause_fresh_resume_and_next_dispatch():
    rows = Rows()
    started = begin(rows)
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    assert authorize(rows, first)["state"] == "dispatch_authorized"
    assert (
        pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)["status"]
        == "paused"
    )

    # A newly constructed ledger has no ambient state; it resumes from tc rows.
    resumed = resume_run(
        296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver
    )
    assert resumed["dispatch_authorized_specialists"] == ("me",)
    assert resumed["next_specialist"] == "qa"
    second = resumed["prepared_invocation"]
    bind_prompt(started["run_id"], "qa", "d" * 64, ledger=ledger(rows))
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
    final = inspect_run(started["run_id"], ledger=ledger(rows))
    assert final["status"] == "all_dispatches_authorized"
    assert final["evidence_claim"] == "dispatch_observed_and_authorized_only"


def test_no_active_legacy_and_missing_wrong_or_replayed_markers():
    rows = Rows()
    factory = ledger_factory(rows)
    assert (
        verify_dispatch(
            session_id="legacy",
            specialist="me",
            marker="",
            prompt_sha256="c" * 64,
            knowledge_sha256="",
            ledger_factory=factory,
            resolver=resolver,
        )["state"]
        == "no_active"
    )

    started = begin(rows)
    with pytest.raises(ValueError, match="active-journey-marker-required"):
        verify_dispatch(
            session_id="session-296",
            specialist="me",
            marker="",
            prompt_sha256="c" * 64,
            knowledge_sha256="",
            ledger_factory=factory,
            resolver=resolver,
        )
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
    with pytest.raises(ValueError, match="route-order"):
        verify_dispatch(
            session_id="session-296",
            specialist="qa",
            marker=prepared.invocation_marker,
            prompt_sha256="c" * 64,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=factory,
            resolver=resolver,
        )
    authorize(rows, prepared)
    with pytest.raises(ValueError, match="route-order"):
        verify_dispatch(
            session_id="session-296",
            specialist=prepared.specialist,
            marker=prepared.invocation_marker,
            prompt_sha256="c" * 64,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=factory,
            resolver=resolver,
        )


def test_signed_source_binding_is_rechecked_before_dispatch():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )

    def changed(specialist: str):
        content = "changed signed bytes"
        return content, (receipt(content, specialist),)

    with pytest.raises(ValueError, match="dispatch-knowledge-changed"):
        authorize(rows, prepared, selected_resolver=changed)
    assert (
        inspect_run(started["run_id"], ledger=ledger(rows))[
            "dispatch_authorized_specialists"
        ]
        == ()
    )


def test_concurrent_dispatch_consumes_tc_stage_exactly_once():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
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
    denied = [item for item in outcomes if item != "dispatch_authorized"]
    assert len(denied) == 1
    assert denied[0] in {
        "dispatch-route-order-mismatch",
        "Exact next Agent prompt has not been prepared.",
    }
    titles = [item["title"] for item in rows.items.values()]
    assert titles.count("Journey v2.1 dispatch evidence") == 1
    assert titles.count("Journey v2.1 final evidence") == 1


def test_final_write_failure_is_recoverable_without_second_dispatch_row():
    class FailFinalOnceRows(Rows):
        fail_final = True

        def store_wp(self, **values):
            if values["title"] == "Journey v2.1 final evidence" and self.fail_final:
                self.fail_final = False
                raise RuntimeError("injected final write failure")
            return super().store_wp(**values)

    rows = FailFinalOnceRows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
    bind_prompt(started["run_id"], "me", "c" * 64, ledger=ledger(rows))
    with pytest.raises(RuntimeError, match="injected final write failure"):
        verify_dispatch(
            session_id="session-296",
            specialist="me",
            marker=prepared.invocation_marker,
            prompt_sha256="c" * 64,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=ledger_factory(rows),
            resolver=resolver,
        )

    recovered = verify_dispatch(
        session_id="session-296",
        specialist="me",
        marker=prepared.invocation_marker,
        prompt_sha256="c" * 64,
        knowledge_sha256=prepared.composed_content_sha256,
        ledger_factory=ledger_factory(rows),
        resolver=resolver,
    )
    assert recovered["state"] == "dispatch_authorized"
    titles = [item["title"] for item in rows.items.values()]
    assert titles.count("Journey v2.1 dispatch evidence") == 1
    assert titles.count("Journey v2.1 final evidence") == 1


def test_exact_full_prompt_must_be_bound_before_dispatch():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
    with pytest.raises(ValueError, match="prompt-not-bound"):
        verify_dispatch(
            session_id="session-296",
            specialist="me",
            marker=prepared.invocation_marker,
            prompt_sha256="c" * 64,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=ledger_factory(rows),
            resolver=resolver,
        )
    bind_prompt(started["run_id"], "me", "c" * 64, ledger=ledger(rows))
    with pytest.raises(ValueError, match="prompt-not-bound"):
        verify_dispatch(
            session_id="session-296",
            specialist="me",
            marker=prepared.invocation_marker,
            prompt_sha256="d" * 64,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=ledger_factory(rows),
            resolver=resolver,
        )


def test_security_denial_stops_before_knowledge_and_dispatch():
    rows = Rows()
    denied = MandatorySecurityVerifier(lambda _context: ("denied", "policy-denied"))
    with pytest.raises(PermissionError, match="mandatory-security-not-allowed"):
        begin_run(
            task_id=296,
            runtime="claude",
            classification="implementation",
            specialists=("me",),
            events=(
                {
                    "kind": "transition",
                    "specialist": "me",
                    "reason": "protocol-supplied",
                },
            ),
            prompt_sha256="b" * 64,
            session_id="denied-session",
            ledger=ledger(rows),
            capability=type(
                "Explode",
                (),
                {
                    "invoke": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        AssertionError("capability called")
                    )
                },
            )(),
            security=denied,
        )
    assert rows.items == {}


def test_pause_capsule_detects_route_and_receipt_drift_and_no_journey_is_distinct():
    empty = Rows()
    assert resume_run(296, ledger=ledger(empty))["state"] == "no_journey"

    rows = Rows()
    started = begin(rows)
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
    authorize(rows, prepared)
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    begin_row = next(
        item
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 begin evidence"
    )
    payload = json.loads(begin_row["content"])
    payload["route"]["specialists"] = ["me", "sec"]
    begin_row["content"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError):
        resume_run(
            296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver
        )


def test_completed_resume_is_immutable_and_reads_no_knowledge():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
    authorize(rows, prepared)
    first = inspect_run(started["run_id"], ledger=ledger(rows))
    second = resume_run(
        296,
        run_id=started["run_id"],
        ledger=ledger(rows),
        resolver=lambda _specialist: (_ for _ in ()).throw(
            AssertionError("resolver called")
        ),
    )
    assert first == second

    begin_row = next(
        item
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 begin evidence"
    )
    changed = json.loads(begin_row["content"])
    changed["capability"] = {
        "name": "cli-copilot-health",
        "state": "available",
        "detail": "sha256:" + "f" * 64,
    }
    begin_row["content"] = json.dumps(changed, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="Final authorization evidence changed"):
        resume_run(296, run_id=started["run_id"], ledger=ledger(rows))


def test_three_stage_route_supports_pause_after_each_progress_point():
    rows = Rows()
    started = begin(rows, specialists=("me", "qa", "sec"))
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    authorize(rows, first)
    assert (
        pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)[
            "next_specialist"
        ]
        == "qa"
    )

    resumed = resume_run(
        296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver
    )
    second = resumed["prepared_invocation"]
    bind_prompt(started["run_id"], "qa", "d" * 64, ledger=ledger(rows))
    verify_dispatch(
        session_id="session-296",
        specialist="qa",
        marker=second["invocation_marker"],
        prompt_sha256="d" * 64,
        knowledge_sha256=second["composed_content_sha256"],
        ledger_factory=ledger_factory(rows),
        resolver=resolver,
    )
    second_pause = pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    assert second_pause["status"] == "paused"
    assert second_pause["next_specialist"] == "sec"
    assert [
        json.loads(item["content"])["generation"]
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 pause evidence"
    ] == [1, 2]


def test_every_historical_pause_capsule_is_validated():
    rows = Rows()
    started = begin(rows, specialists=("me", "qa", "sec"))
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    authorize(rows, first)
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    second = resume_run(
        296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver
    )["prepared_invocation"]
    bind_prompt(started["run_id"], "qa", "d" * 64, ledger=ledger(rows))
    verify_dispatch(
        session_id="session-296",
        specialist="qa",
        marker=second["invocation_marker"],
        prompt_sha256="d" * 64,
        knowledge_sha256=second["composed_content_sha256"],
        ledger_factory=ledger_factory(rows),
        resolver=resolver,
    )
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)

    first_pause = next(
        item
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 pause evidence"
        and json.loads(item["content"])["generation"] == 1
    )
    changed = json.loads(first_pause["content"])
    changed["capsule"]["next_specialist"] = "sec"
    first_pause["content"] = json.dumps(changed, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="historical pause capsule changed"):
        resume_run(
            296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver
        )


def test_late_lower_generation_pause_after_later_progress_is_rejected():
    rows = Rows()
    started = begin(rows, specialists=("me", "qa", "sec"))
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    authorize(rows, first)
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    second = resume_run(
        296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver
    )["prepared_invocation"]
    bind_prompt(started["run_id"], "qa", "d" * 64, ledger=ledger(rows))
    verify_dispatch(
        session_id="session-296",
        specialist="qa",
        marker=second["invocation_marker"],
        prompt_sha256="d" * 64,
        knowledge_sha256=second["composed_content_sha256"],
        ledger_factory=ledger_factory(rows),
        resolver=resolver,
    )

    pause_id, pause = next(
        (row_id, item)
        for row_id, item in rows.items.items()
        if item["title"] == "Journey v2.1 pause evidence"
    )
    rows.items.pop(pause_id)
    late_id = max(rows.items) + 1
    pause["id"] = late_id
    rows.items[late_id] = pause
    with pytest.raises(ValueError, match="pause chronology"):
        inspect_run(started["run_id"], ledger=ledger(rows))


def test_pause_generation_order_follows_tc_row_order():
    rows = Rows()
    started = begin(rows, specialists=("me", "qa", "sec"))
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    authorize(rows, first)
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    second = resume_run(
        296, run_id=started["run_id"], ledger=ledger(rows), resolver=resolver
    )["prepared_invocation"]
    bind_prompt(started["run_id"], "qa", "d" * 64, ledger=ledger(rows))
    verify_dispatch(
        session_id="session-296",
        specialist="qa",
        marker=second["invocation_marker"],
        prompt_sha256="d" * 64,
        knowledge_sha256=second["composed_content_sha256"],
        ledger_factory=ledger_factory(rows),
        resolver=resolver,
    )
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    pause_rows = [
        (row_id, item)
        for row_id, item in rows.items.items()
        if item["title"] == "Journey v2.1 pause evidence"
    ]
    first_id, first_pause = pause_rows[0]
    second_id, second_pause = pause_rows[1]
    rows.items.pop(first_id)
    rows.items.pop(second_id)
    first_pause["id"], second_pause["id"] = second_id, first_id
    rows.items[second_id], rows.items[first_id] = first_pause, second_pause
    with pytest.raises(ValueError, match="pause chronology"):
        inspect_run(started["run_id"], ledger=ledger(rows))


def test_pause_before_its_dispatch_prefix_is_rejected():
    rows = Rows()
    started = begin(rows, specialists=("me", "qa"))
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    authorize(rows, first)
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    pause = next(
        item
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 pause evidence"
    )
    reordered = {}
    for row_id, item in sorted(rows.items.items()):
        if item is pause:
            new_id = 2
        elif row_id >= 2:
            new_id = row_id + 1
        else:
            new_id = row_id
        item["id"] = new_id
        reordered[new_id] = item
    rows.items = reordered
    with pytest.raises(ValueError, match="pause chronology"):
        inspect_run(started["run_id"], ledger=ledger(rows))


def test_duplicate_pause_generation_is_rejected():
    rows = Rows()
    started = begin(rows, specialists=("me", "qa"))
    first = prepare_run(started["run_id"], "me", ledger=ledger(rows), resolver=resolver)
    authorize(rows, first)
    pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    pause = next(
        item.copy()
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 pause evidence"
    )
    pause["id"] = max(rows.items) + 1
    rows.items[pause["id"]] = pause
    with pytest.raises(ValueError, match="pause evidence is ambiguous"):
        inspect_run(started["run_id"], ledger=ledger(rows))


@pytest.mark.parametrize(
    "moved_stage_one_kinds",
    [
        ("prepare",),
        ("prepare", "prompt_binding"),
        ("prepare", "prompt_binding", "dispatch_authorization"),
    ],
)
def test_cross_stage_row_reassignment_is_rejected(moved_stage_one_kinds):
    rows = Rows()
    started = two_stage_progress(rows)
    original = list(rows.items.values())

    def matches(row, kind, stage):
        payload = payload_for(row)
        return payload["record_type"] == kind and payload.get("stage_index") == stage

    stage_zero_dispatch = next(
        row for row in original if matches(row, "dispatch_authorization", 0)
    )
    moved = [
        row
        for kind in moved_stage_one_kinds
        for row in original
        if matches(row, kind, 1)
    ]
    ordered = []
    for row in original:
        if row is stage_zero_dispatch:
            ordered.extend(moved)
        if row not in moved:
            ordered.append(row)
    reassign_row_order(rows, ordered)
    count = len(rows.items)

    with pytest.raises(ValueError, match="cross-stage chronology"):
        inspect_run(started["run_id"], ledger=ledger(rows))
    with pytest.raises(ValueError, match="cross-stage chronology"):
        pause_run(started["run_id"], ledger=ledger(rows), resolver=resolver)
    assert len(rows.items) == count


def test_real_tc_cross_stage_row_reassignment_is_rejected(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path("tools/tc/src").resolve()))
    from tc.api import create_prd, create_task, get_wp, list_wps, store_wp
    from tc.db.connection import init_db

    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    prd = create_prd(title="Chronology fixture", db_path=db_path)
    task_id = create_task(title="Chronology task", prd=prd["id"], db_path=db_path)["id"]

    def real_ledger(selected_task):
        return TcJourneyLedger(
            selected_task,
            store_wp=lambda **values: store_wp(**values, db_path=db_path),
            get_wp=lambda **values: get_wp(**values, db_path=db_path),
            list_wps=lambda **values: list_wps(**values, db_path=db_path),
        )

    capability = type(
        "Capability",
        (),
        {
            "invoke": lambda self, **_: CapabilityReceipt(
                "cli-copilot-health", "unavailable"
            )
        },
    )()
    started = begin_run(
        task_id=task_id,
        runtime="claude",
        classification="implementation",
        specialists=("me", "qa", "sec"),
        events=tuple(
            {
                "kind": "transition",
                "specialist": item,
                "reason": "protocol-supplied",
            }
            for item in ("me", "qa", "sec")
        ),
        prompt_sha256="b" * 64,
        session_id="real-chronology",
        ledger=real_ledger(task_id),
        capability=capability,
    )
    first = prepare_run(
        started["run_id"], "me", ledger=real_ledger(task_id), resolver=resolver
    )
    bind_prompt(started["run_id"], "me", "c" * 64, ledger=real_ledger(task_id))
    verify_dispatch(
        session_id="real-chronology",
        specialist="me",
        marker=first.invocation_marker,
        prompt_sha256="c" * 64,
        knowledge_sha256=first.composed_content_sha256,
        ledger_factory=real_ledger,
        resolver=resolver,
    )
    second = prepare_run(
        started["run_id"], "qa", ledger=real_ledger(task_id), resolver=resolver
    )
    bind_prompt(started["run_id"], "qa", "d" * 64, ledger=real_ledger(task_id))
    verify_dispatch(
        session_id="real-chronology",
        specialist="qa",
        marker=second.invocation_marker,
        prompt_sha256="d" * 64,
        knowledge_sha256=second.composed_content_sha256,
        ledger_factory=real_ledger,
        resolver=resolver,
    )

    summaries = list_wps(task=task_id, type_="evidence", db_path=db_path)
    full_rows = [get_wp(wp_id=row["id"], db_path=db_path) for row in summaries]
    stage_zero_dispatch = next(
        row
        for row in full_rows
        if payload_for(row)["record_type"] == "dispatch_authorization"
        and payload_for(row)["stage_index"] == 0
    )
    stage_one = sorted(
        (row for row in full_rows if payload_for(row).get("stage_index") == 1),
        key=lambda row: row["id"],
    )
    target_ids = [stage_zero_dispatch["id"], *(row["id"] for row in stage_one)]
    reordered_ids = [target_ids[-1], *target_ids[:-1]]
    with sqlite3.connect(db_path) as connection:
        for old_id in target_ids:
            connection.execute(
                "UPDATE work_products SET id = ? WHERE id = ?", (-old_id, old_id)
            )
        for old_id, new_id in zip(target_ids, reordered_ids, strict=True):
            connection.execute(
                "UPDATE work_products SET id = ? WHERE id = ?", (new_id, -old_id)
            )
        connection.commit()

    with pytest.raises(ValueError, match="cross-stage chronology"):
        inspect_run(started["run_id"], ledger=real_ledger(task_id))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("specialist", "qa"),
        ("invocation_marker", "f" * 48),
        ("prepared_sha256", "e" * 64),
    ],
)
def test_prompt_binding_must_match_exact_preparation(field, value):
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
    bind_prompt(started["run_id"], "me", "c" * 64, ledger=ledger(rows))
    binding_row = next(
        item
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 prompt binding evidence"
    )
    payload = json.loads(binding_row["content"])
    payload[field] = value
    binding_row["content"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    with pytest.raises(ValueError, match="dispatch-prompt-not-bound"):
        verify_dispatch(
            session_id="session-296",
            specialist="me",
            marker=prepared.invocation_marker,
            prompt_sha256="c" * 64,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=ledger_factory(rows),
            resolver=resolver,
        )


def test_terminal_evidence_rejects_dispatch_source_drift():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    prepared = prepare_run(
        started["run_id"], "me", ledger=ledger(rows), resolver=resolver
    )
    authorize(rows, prepared)
    dispatch_row = next(
        item
        for item in rows.items.values()
        if item["title"] == "Journey v2.1 dispatch evidence"
    )
    payload = json.loads(dispatch_row["content"])
    payload["sources"][0]["ref"] = "refs/tags/v9.9.9"
    dispatch_row["content"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="Final authorization evidence changed"):
        inspect_run(started["run_id"], ledger=ledger(rows))


def test_security_change_at_dispatch_stops_before_knowledge():
    rows = Rows()
    allowed = MandatorySecurityVerifier(
        lambda _context: ("allowed", "fixture-policy-authorized")
    )
    denied = MandatorySecurityVerifier(
        lambda _context: ("denied", "fixture-policy-denied")
    )
    started = begin_run(
        task_id=296,
        runtime="claude",
        classification="implementation",
        specialists=("me",),
        events=(
            {
                "kind": "transition",
                "specialist": "me",
                "reason": "protocol-supplied",
            },
        ),
        prompt_sha256="b" * 64,
        session_id="security-change",
        ledger=ledger(rows),
        capability=type(
            "Capability",
            (),
            {
                "invoke": lambda self, **_: CapabilityReceipt(
                    "cli-copilot-health", "unavailable"
                )
            },
        )(),
        security=allowed,
    )
    prepared = prepare_run(
        started["run_id"],
        "me",
        ledger=ledger(rows),
        resolver=resolver,
        security=allowed,
    )
    bind_prompt(started["run_id"], "me", "c" * 64, ledger=ledger(rows))

    def forbidden_resolver(_specialist):
        raise AssertionError("Knowledge was read after security denial")

    with pytest.raises(PermissionError, match="mandatory-security-not-allowed"):
        verify_dispatch(
            session_id="security-change",
            specialist="me",
            marker=prepared.invocation_marker,
            prompt_sha256="c" * 64,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=ledger_factory(rows),
            resolver=forbidden_resolver,
            security=denied,
        )


def test_tc_row_identity_and_payload_fields_fail_closed():
    rows = Rows()
    started = begin(rows, specialists=("me",))
    begin_row = next(iter(rows.items.values()))
    begin_row["agent"] = "attacker"
    with pytest.raises(ValueError, match="row identity"):
        inspect_run(started["run_id"], ledger=ledger(rows))

    begin_row["agent"] = "cc-journey"
    changed = json.loads(begin_row["content"])
    changed["unexpected"] = "injected"
    begin_row["content"] = json.dumps(changed, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="payload fields"):
        inspect_run(started["run_id"], ledger=ledger(rows))


def test_production_ledger_rejects_modified_or_missing_guards():
    rows = Rows()
    compatibility = ledger(rows)
    started = begin(rows, specialists=("me",))
    strict = TcJourneyLedger(
        296,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
    )
    with pytest.raises(ValueError, match="row identity"):
        inspect_run(started["run_id"], ledger=strict)

    for row in rows.items.values():
        row["guard"] = "title=modified:instruction-override;content=clean"
    with pytest.raises(ValueError, match="row identity"):
        inspect_run(started["run_id"], ledger=compatibility)


def test_resume_ambiguity_never_picks_newest():
    rows = Rows()
    first = begin(rows, specialists=("me",), session="session-one")
    second = begin(rows, specialists=("me",), session="session-two")
    pause_run(first["run_id"], ledger=ledger(rows), resolver=resolver)
    pause_run(second["run_id"], ledger=ledger(rows), resolver=resolver)
    with pytest.raises(ValueError, match="ambiguous"):
        resume_run(296, ledger=ledger(rows), resolver=resolver)


def test_global_lock_is_exact_root_owned_sticky_directory():
    rows = Rows()
    selected = TcJourneyLedger(
        296,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
        allow_missing_guard=True,
    )
    before = os.lstat("/private/tmp")
    with selected.claim("global-vnode"):
        current = os.lstat("/private/tmp")
        assert stat.S_ISDIR(current.st_mode)
        assert current.st_uid == 0
        assert current.st_mode & stat.S_ISVTX
        assert (current.st_dev, current.st_ino) == (before.st_dev, before.st_ino)


def test_lock_wait_is_bounded_and_fails_closed():
    rows = Rows()
    selected = TcJourneyLedger(
        296,
        store_wp=rows.store_wp,
        get_wp=rows.get_wp,
        list_wps=rows.list_wps,
        lock_timeout=0.03,
        allow_missing_guard=True,
    )
    descriptor = os.open("/private/tmp", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            with selected.claim("contended"):
                pass
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
    assert time.monotonic() - started < 0.5


def test_lock_rename_unlink_recreate_attack_cannot_split_claim_identity(tmp_path):
    assert os.geteuid() != 0
    before = os.lstat("/private/tmp")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=global_lock_holder, args=(ready, release))
    holder.start()
    assert ready.wait(timeout=10)
    try:
        with pytest.raises(PermissionError):
            os.rename("/private/tmp", tmp_path / "renamed-global-lock")
        with pytest.raises(OSError):
            os.unlink("/private/tmp")
        with pytest.raises(FileExistsError):
            os.mkdir("/private/tmp")

        queue = context.Queue()
        process = context.Process(target=global_lock_worker, args=(queue,))
        process.start()
        process.join(timeout=10)
        assert not process.is_alive()
        assert queue.get(timeout=2) == "Journey lock acquisition timed out."
    finally:
        release.set()
        holder.join(timeout=10)
        assert not holder.is_alive()
        assert holder.exitcode == 0

    after = os.lstat("/private/tmp")
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_store_revalidates_claim_before_after_and_after_verification(monkeypatch):
    rows = Rows()
    selected = ledger(rows)
    events = []
    original = selected._validate_global_lock_descriptor

    def validate(descriptor):
        events.append(("validate", os.getpid(), descriptor))
        original(descriptor)

    monkeypatch.setattr(selected, "_validate_global_lock_descriptor", validate)
    with selected.claim("validation-sequence"):
        before = len(events)
        selected.append(
            "Journey v2.1 begin evidence",
            {
                "record_type": "begin",
                "run_id": "j2-296-" + "a" * 24,
                "session_id_sha256": "b" * 64,
                "prompt_sha256": "c" * 64,
                "route": {
                    "classification": "implementation",
                    "specialists": ["me"],
                    "runtime": "claude",
                    "contract_version": "2.1",
                    "events": [
                        {
                            "kind": "transition",
                            "specialist": "me",
                            "reason": "protocol-supplied",
                        }
                    ],
                },
                "security": {
                    "state": "allowed",
                    "reason": "fixture-policy",
                    "policy_sha256": "d" * 64,
                },
                "capability": {
                    "name": "cli-copilot-health",
                    "state": "unavailable",
                    "detail": "",
                },
            },
        )
        store_validations = events[before:]
    assert len(store_validations) >= 4
    assert {pid for _, pid, _ in store_validations} == {os.getpid()}
    assert len({descriptor for _, _, descriptor in store_validations}) == 1


def test_store_identity_failure_before_callback_performs_no_store(monkeypatch):
    calls = []
    rows = Rows()
    selected = ledger(rows)
    with selected.claim("identity-failure"):
        original_validate = selected._validate_global_lock_descriptor
        original = selected._store_wp
        try:
            monkeypatch.setattr(
                selected,
                "_validate_global_lock_descriptor",
                lambda _descriptor: (_ for _ in ()).throw(
                    RuntimeError("Journey global lock identity changed.")
                ),
            )
            selected._store_wp = lambda **values: (
                calls.append(values),
                original(**values),
            )[1]
            with pytest.raises(RuntimeError, match="identity changed"):
                selected.append("Journey v2.1 preparation evidence", {})
            assert calls == []
        finally:
            selected._validate_global_lock_descriptor = original_validate


def test_forked_callback_child_cannot_continue_or_store():
    if not hasattr(os, "fork"):
        pytest.skip("raw fork is unavailable")
    rows = Rows()
    selected = ledger(rows)
    started = begin(rows, specialists=("me",))
    original_pid = os.getpid()
    child_status = []

    def forking_resolver(specialist):
        pid = os.fork()
        if pid == 0:
            return resolver(specialist)
        waited, status = os.waitpid(pid, 0)
        child_status.append((waited, status))
        return resolver(specialist)

    try:
        prepared = prepare_run(
            started["run_id"], "me", ledger=selected, resolver=forking_resolver
        )
    except RuntimeError as exc:
        if os.getpid() != original_pid:
            os._exit(0 if "process" in str(exc) else 2)
        raise

    assert os.getpid() == original_pid
    assert child_status and os.waitstatus_to_exitcode(child_status[0][1]) == 0
    assert prepared.specialist == "me"
    assert (
        sum(
            row["title"] == "Journey v2.1 preparation evidence"
            for row in rows.items.values()
        )
        == 1
    )


def test_runtime_contains_no_second_router_or_resolver():
    source = Path("tools/cc/src/cc/core/evaluation/journey_runtime.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "keyword_map",
        "flow_to_agents",
        "knowledge_repo_rank",
        "CC_KNOWLEDGE_REPOS",
        'glob("knowledge-manifest',
    )
    assert not any(item in source for item in forbidden)
    assert "resolve_extension(specialist)" in source

    hook = Path(".claude/hooks/pretool-check.sh").read_text(encoding="utf-8")
    dispatch = hook.rsplit("# Dispatch — rule sets run in order", 1)[1]
    assert dispatch.index("rule_qa_gate") < dispatch.index("rule_extension_resolution")
    assert dispatch.index("rule_path_scope") < dispatch.index("rule_journey_dispatch")
    assert dispatch.index("rule_journey_dispatch") < dispatch.index("exit 0")


@pytest.mark.parametrize(
    "unsafe",
    [
        "line\nfeed",
        "/Users/pabs/private",
        "api_token=value",
        "Pablo Alejo",
        "contact-pabs@example.com",
        "inspect-/Users/pabs/private",
        "sk-abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_persisted_classification_and_reasons_reject_unsafe_values(unsafe):
    rows = Rows()
    with pytest.raises(ValueError, match="unsafe"):
        begin_run(
            task_id=296,
            runtime="claude",
            classification=unsafe,
            specialists=("me",),
            events=(
                {
                    "kind": "transition",
                    "specialist": "me",
                    "reason": "protocol-supplied",
                },
            ),
            prompt_sha256="b" * 64,
            session_id="safe-session",
            ledger=ledger(rows),
            capability=type(
                "Capability",
                (),
                {
                    "invoke": lambda self, **_: CapabilityReceipt(
                        "cli-copilot-health", "unavailable"
                    )
                },
            )(),
        )


@pytest.mark.parametrize(
    "unsafe",
    [
        "Pablo Alejo",
        "contact-pabs@example.com",
        "inspect-/Users/pabs/private",
        "sk-abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_persisted_reason_and_session_reject_disclosure_values(unsafe):
    rows = Rows()
    capability = type(
        "Capability",
        (),
        {
            "invoke": lambda self, **_: CapabilityReceipt(
                "cli-copilot-health", "unavailable"
            )
        },
    )()
    with pytest.raises(ValueError, match="unsafe"):
        begin_run(
            task_id=296,
            runtime="claude",
            classification="implementation",
            specialists=("me",),
            events=({"kind": "transition", "specialist": "me", "reason": unsafe},),
            prompt_sha256="b" * 64,
            session_id="safe-session",
            ledger=ledger(rows),
            capability=capability,
        )
    with pytest.raises(ValueError, match="unsafe"):
        begin_run(
            task_id=296,
            runtime="claude",
            classification="implementation",
            specialists=("me",),
            events=(
                {
                    "kind": "transition",
                    "specialist": "me",
                    "reason": "protocol-supplied",
                },
            ),
            prompt_sha256="b" * 64,
            session_id=unsafe,
            ledger=ledger(rows),
            capability=capability,
        )


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("repository", "Users/pabs"),
        ("repository", "owner/contact-pabs@example.com"),
        ("signer", "contact-pabs@example.com"),
        ("signer", "sk-abcdefghijklmnopqrstuvwxyz"),
        ("contribution", "Users/pabs/private.extension.md"),
        ("contribution", "skills/contact-pabs@example.com"),
    ],
)
def test_knowledge_source_identities_reject_disclosure_values(field, unsafe):
    rows = Rows()
    started = begin(rows, specialists=("me",))

    def unsafe_resolver(specialist):
        content = f"signed context for {specialist}"
        source = receipt(content, specialist)
        source[field] = unsafe
        return content, (source,)

    with pytest.raises(ValueError, match="source receipt is malformed"):
        prepare_run(
            started["run_id"],
            "me",
            ledger=ledger(rows),
            resolver=unsafe_resolver,
        )


@pytest.mark.parametrize(
    ("resolver_result", "run_result", "state"),
    [
        (None, None, "unavailable"),
        (
            Path("/bin/false"),
            subprocess.CompletedProcess([], 2, "out", "err"),
            "nonzero",
        ),
        (
            Path("/bin/echo"),
            subprocess.CompletedProcess([], 0, "not-json", ""),
            "malformed",
        ),
        (
            Path("/bin/echo"),
            subprocess.CompletedProcess([], 0, '{"status":"ok"}', ""),
            "available",
        ),
    ],
)
def test_optional_health_matrix_is_typed_and_fail_open(
    resolver_result, run_result, state
):
    def run(*_args, **_kwargs):
        assert run_result is not None
        return run_result

    adapter = CliCopilotHealthCapabilityAdapter(
        resolver=lambda _name: resolver_result,
        run=run,
    )
    assert adapter.invoke(case_id="fixture").state == state


def test_real_tc_guard_safe_roundtrip_and_multiprocess_dispatch(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path("tools/tc/src").resolve()))
    from tc.api import create_prd, create_task, get_wp, list_wps, store_wp
    from tc.db.connection import init_db

    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    prd = create_prd(title="Journey QA fixture", db_path=db_path)
    task_id = create_task(
        title="Journey dispatch fixture", prd=prd["id"], db_path=db_path
    )["id"]

    def real_ledger(selected_task):
        return TcJourneyLedger(
            selected_task,
            store_wp=lambda **values: store_wp(**values, db_path=db_path),
            get_wp=lambda **values: get_wp(**values, db_path=db_path),
            list_wps=lambda **values: list_wps(**values, db_path=db_path),
        )

    capability = type(
        "Capability",
        (),
        {
            "invoke": lambda self, **_: CapabilityReceipt(
                "cli-copilot-health", "unavailable"
            )
        },
    )()
    started = begin_run(
        task_id=task_id,
        runtime="claude",
        classification="implementation",
        specialists=("me",),
        events=(
            {
                "kind": "transition",
                "specialist": "me",
                "reason": "protocol-supplied",
            },
        ),
        prompt_sha256="b" * 64,
        session_id="real-process-session",
        ledger=real_ledger(task_id),
        capability=capability,
    )
    prepared = prepare_run(
        started["run_id"], "me", ledger=real_ledger(task_id), resolver=resolver
    )
    bind_prompt(started["run_id"], "me", "c" * 64, ledger=real_ledger(task_id))

    def worker(queue):
        try:
            outcome = verify_dispatch(
                session_id="real-process-session",
                specialist="me",
                marker=prepared.invocation_marker,
                prompt_sha256="c" * 64,
                knowledge_sha256=prepared.composed_content_sha256,
                ledger_factory=real_ledger,
                resolver=resolver,
            )
            queue.put(("ok", outcome["state"]))
        except Exception as exc:  # pragma: no cover - asserted in parent
            queue.put(("error", str(exc)))

    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    processes = [context.Process(target=worker, args=(queue,)) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert not process.is_alive()
    outcomes = sorted(queue.get(timeout=2) for _ in processes)
    assert outcomes == [
        ("error", "dispatch-route-order-mismatch"),
        ("ok", "dispatch_authorized"),
    ]

    summaries = list_wps(task=task_id, type_="evidence", db_path=db_path)
    rows = [get_wp(wp_id=item["id"], db_path=db_path) for item in summaries]
    assert all(item["guard"] == "title=clean;content=clean" for item in rows)
    assert sum(item["title"] == "Journey v2.1 dispatch evidence" for item in rows) == 1
    assert sum(item["title"] == "Journey v2.1 final evidence" for item in rows) == 1
