from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from cc.core.ecosystem.project_plan_store import (
    PlanAlreadyUsed,
    PlanBindingMismatch,
    PlanExpired,
    claim_plan,
    finish_plan,
    incomplete_run_ids,
    issue_plan,
)
from cc.core.ecosystem.reconciliation_transaction import (
    recover_incomplete_transactions,
)

from cc.core.ecosystem import project_plan_store as plan_store


def _fingerprint(character: str) -> str:
    return "sha256:" + character * 64


def _run(character: str) -> str:
    return "run_" + character * 32


def _request(path: str) -> dict:
    return {
        "schema_version": "1.0",
        "roots": ["/projects"],
        "projects": [{"path": path, "components": ["claude"]}],
    }


def _request_fingerprint(path: str) -> str:
    encoded = json.dumps(
        _request(path), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _plan(path: str, *, executable: bool = False) -> dict:
    return {
        "path": path,
        "operations": ([{"id": "op_" + "d" * 64}] if executable else []),
    }


def test_owner_probe_failure_is_live_unverifiable_and_pid_reuse_is_dead(
    monkeypatch,
) -> None:
    monkeypatch.setattr(plan_store.os, "kill", lambda *_args: None)
    monkeypatch.setattr(plan_store, "_process_start_token", lambda _pid: "")
    assert plan_store._owner_live(12345, _fingerprint("a")) is True

    monkeypatch.setattr(
        plan_store, "_process_start_token", lambda _pid: _fingerprint("b")
    )
    assert plan_store._owner_live(12345, _fingerprint("a")) is False


def test_plan_ids_are_random_private_and_single_use(tmp_path) -> None:
    root = tmp_path / "state"
    first = issue_plan(
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        [_plan("/projects/one")],
        canonical_request=_request("/projects/one"),
        helper_version="2.6.0",
        schema_version="1.0",
        root=root,
    )
    second = issue_plan(
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        [_plan("/projects/one")],
        canonical_request=_request("/projects/one"),
        helper_version="2.6.0",
        schema_version="1.0",
        root=root,
    )
    assert first.plan_id != second.plan_id
    record = root / "plans" / f"{first.plan_id}.json"
    assert record.stat().st_mode & 0o777 == 0o600
    assert record.parent.stat().st_mode & 0o777 == 0o700

    claim = claim_plan(
        first.plan_id,
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        run_id=_run("1"),
        root=root,
    )
    intent = root / "runs" / f"{claim.run_id}.json"
    assert intent.stat().st_mode & 0o777 == 0o600
    assert intent.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(intent.read_text(encoding="utf-8"))["state"] == "applying"
    consumed = finish_plan(
        first.plan_id,
        claim.claim_token,
        "applied",
        ledger=[
            {
                "path": "/projects/one",
                "status": "unchanged",
                "completed_operation_ids": [],
                "verification": "ready",
                "rollback": [],
            }
        ],
        root=root,
    )
    assert consumed.state == "consumed"
    assert json.loads(intent.read_text(encoding="utf-8"))["state"] == "outcome-recorded"
    assert incomplete_run_ids(root=root) == (_run("1"),)
    with pytest.raises(PlanAlreadyUsed):
        claim_plan(
            first.plan_id,
            _request_fingerprint("/projects/one"),
            _fingerprint("b"),
            run_id=_run("2"),
            root=root,
        )


def test_claim_refuses_changed_request_or_fresh_plan(tmp_path) -> None:
    record = issue_plan(
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        [_plan("/projects/one")],
        canonical_request=_request("/projects/one"),
        helper_version="2.6.0",
        schema_version="1.0",
        root=tmp_path,
    )
    with pytest.raises(PlanBindingMismatch):
        claim_plan(
            record.plan_id,
            _fingerprint("c"),
            _fingerprint("b"),
            run_id=_run("3"),
            root=tmp_path,
        )
    with pytest.raises(PlanBindingMismatch):
        claim_plan(
            record.plan_id,
            _fingerprint("a"),
            _fingerprint("c"),
            run_id=_run("4"),
            root=tmp_path,
        )


def test_expired_plan_is_consumed_as_expired_without_claim(tmp_path) -> None:
    created = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    record = issue_plan(
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        [_plan("/projects/one")],
        canonical_request=_request("/projects/one"),
        helper_version="2.6.0",
        schema_version="1.0",
        ttl_seconds=30,
        root=tmp_path,
        now=created,
    )
    with pytest.raises(PlanExpired):
        claim_plan(
            record.plan_id,
            _request_fingerprint("/projects/one"),
            _fingerprint("b"),
            run_id=_run("5"),
            root=tmp_path,
            now=created + timedelta(seconds=31),
        )


def test_wrong_claim_token_cannot_finish_plan(tmp_path) -> None:
    record = issue_plan(
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        [_plan("/projects/one")],
        canonical_request=_request("/projects/one"),
        helper_version="2.6.0",
        schema_version="1.0",
        root=tmp_path,
    )
    claim_plan(
        record.plan_id,
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        run_id=_run("6"),
        root=tmp_path,
    )
    with pytest.raises(PlanBindingMismatch):
        finish_plan(record.plan_id, "wrong", "blocked", ledger=[], root=tmp_path)


def test_run_ids_are_durable_single_use_capabilities(tmp_path) -> None:
    first = issue_plan(
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        [_plan("/projects/one")],
        canonical_request=_request("/projects/one"),
        helper_version="2.6.0",
        schema_version="1.0",
        root=tmp_path,
    )
    second = issue_plan(
        _request_fingerprint("/projects/two"),
        _fingerprint("b"),
        [_plan("/projects/two")],
        canonical_request=_request("/projects/two"),
        helper_version="2.6.0",
        schema_version="1.0",
        root=tmp_path,
    )
    claim_plan(
        first.plan_id,
        _request_fingerprint("/projects/one"),
        _fingerprint("b"),
        run_id=_run("7"),
        root=tmp_path,
    )

    with pytest.raises(PlanAlreadyUsed):
        claim_plan(
            second.plan_id,
            _request_fingerprint("/projects/two"),
            _fingerprint("b"),
            run_id=_run("7"),
            root=tmp_path,
        )


def test_kill_between_plan_claim_and_first_journal_recovers_blocked_evidence(
    tmp_path,
) -> None:
    state = tmp_path / "state"
    run_id = _run("8")
    record = issue_plan(
        _request_fingerprint("/projects/example"),
        _fingerprint("b"),
        [_plan("/projects/example", executable=True)],
        canonical_request=_request("/projects/example"),
        helper_version="2.6.0",
        schema_version="1.0",
        root=state,
    )
    script = """
import os
import sys
from pathlib import Path
from cc.core.ecosystem import project_plan_store as store

original = store.atomic_json_write
writes = 0
def kill_after_claimed_plan(path, payload):
    global writes
    original(path, payload)
    writes += 1
    if writes == 2:
        os._exit(73)

store.atomic_json_write = kill_after_claimed_plan
store.claim_plan(
    sys.argv[1],
    sys.argv[2],
    sys.argv[3],
    run_id=sys.argv[4],
    root=Path(sys.argv[5]),
)
"""
    killed = subprocess.run(
        (
            sys.executable,
            "-c",
            script,
            record.plan_id,
            _request_fingerprint("/projects/example"),
            _fingerprint("b"),
            run_id,
            str(state),
        ),
        check=False,
    )
    assert killed.returncode == 73
    assert incomplete_run_ids(root=state) == (run_id,)

    receipts = recover_incomplete_transactions(root=state)

    assert len(receipts) == 1
    assert receipts[0]["path"] == "/projects/example"
    assert receipts[0]["status"] == "blocked"
    assert receipts[0]["completed_operation_ids"] == []
    assert receipts[0]["verification"] == "not-run"
    assert receipts[0]["rollback"] == []
    plan = json.loads(
        (state / "plans" / f"{record.plan_id}.json").read_text(encoding="utf-8")
    )
    intent = json.loads((state / "runs" / f"{run_id}.json").read_text(encoding="utf-8"))
    assert (plan["state"], plan["outcome"]) == ("consumed", "blocked")
    assert intent["state"] == "outcome-recorded"
    diagnostic = json.loads(
        (state / "diagnostics" / f"reconciliation-{run_id}.json").read_text(
            encoding="utf-8"
        )
    )
    exception = diagnostic["projects"][0]["evidence"]["exception"]
    assert exception["type"] == "TransactionError"
    assert exception["code"] == "interrupted"
    assert recover_incomplete_transactions(root=state) == []
