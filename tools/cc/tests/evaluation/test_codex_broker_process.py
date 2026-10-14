from __future__ import annotations

import copy
import json
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import cc.core.evaluation.codex_broker_process as process_broker
import pytest
from cc.core.evaluation.codex_broker_process import (
    CodexBrokerProcessUnavailable,
    codex_broker_process_test_receipt_document,
    verify_codex_broker_process_test_receipt,
)
from test_codex_broker import (
    _auth_file,
    _dispatch,
    _expected,
    _FakeTLS,
    _private_root,
    _request_body,
)


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    behavior: str = "run",
    upstream_behavior: str = "success",
    timeout: float = 8,
    auth_kwargs: dict[str, object] | None = None,
):
    now = int(time.time())
    auth_file, secrets = _auth_file(tmp_path, now=now, **(auth_kwargs or {}))
    monkeypatch.setattr(process_broker, "_AUTH_FILE", auth_file)
    upstream = _FakeTLS(tmp_path, secrets, behavior=upstream_behavior)
    journal = _private_root(tmp_path, "process-journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        receipt = process_broker._exercise_fake_codex_broker_process(
            dispatch,
            expected_request=_expected(_request_body()),
            fake_upstream=upstream.authority,
            journal_root=journal,
            now=now,
            timeout=timeout,
            test_behavior=behavior,
        )
        return receipt, upstream, journal, measurement, secrets
    except BaseException:
        upstream.close()
        measurement.close()
        raise


def test_process_boundary_proof_is_exact_nonauthorizing_and_value_suppressing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, upstream, journal, measurement, secrets = _run(tmp_path, monkeypatch)
    try:
        document = codex_broker_process_test_receipt_document(receipt)
        serialized = json.dumps(document, sort_keys=True)
        assert receipt.validate()
        assert verify_codex_broker_process_test_receipt(receipt)
        assert document["authorization_scope"] == "fake-upstream-process-boundary-only"
        assert document["live_runtime_authorized"] is False
        assert document["prepared_cell_authority"] == "absent"
        assert document["worker_exit_code"] == 0
        assert document["worker_reaped"] is True
        assert document["descendants_reaped"] is True
        assert document["upstream_call_count"] == 1
        assert document["interaction_count"] == 1
        assert upstream.state.calls == 1
        assert process_broker._classify_process_attempt(journal) == (
            "completed-untrusted-until-loaded"
        )
        assert tuple(sorted(path.name for path in journal.iterdir())) == (
            "call-started.json",
            "completion.json",
            "egress-intent.json",
        )
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in journal.iterdir())
        for secret in secrets.values():
            assert secret not in serialized
            assert all(secret not in path.read_text() for path in journal.iterdir())
        assert "Synthetic prompt" not in serialized
        assert str(process_broker._AUTH_FILE) not in serialized
        assert "private-turn-state" not in serialized
    finally:
        receipt.close()
        upstream.close()
        measurement.close()


def test_public_surface_has_no_runner_authorizer_or_fake_receipt_upgrade() -> None:
    assert process_broker._AUTH_FILE is None
    assert "_exercise_fake_codex_broker_process" not in process_broker.__all__
    assert not hasattr(process_broker, "authorize_codex_broker_process")
    assert not hasattr(process_broker, "run_codex_broker_process")
    assert not hasattr(process_broker, "consume_codex_broker_test_receipt")


def test_worker_launch_uses_closed_environment_new_session_and_no_secret_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[list[str], dict[str, object]]] = []
    original = process_broker.subprocess.Popen

    def retained_popen(argv, **kwargs):
        if list(argv)[-1:] == ["--test-worker"]:
            observed.append((list(argv), dict(kwargs)))
        return original(argv, **kwargs)

    monkeypatch.setattr(process_broker.subprocess, "Popen", retained_popen)
    receipt, upstream, _journal, measurement, secrets = _run(tmp_path, monkeypatch)
    try:
        assert len(observed) == 1
        argv, kwargs = observed[0]
        assert argv[-2:] == [process_broker.__name__, "--test-worker"]
        assert kwargs["start_new_session"] is True
        assert kwargs["close_fds"] is True
        assert kwargs["env"] == process_broker._WORKER_ENVIRONMENT
        serialized = json.dumps({"argv": argv, "env": kwargs["env"]})
        assert all(secret not in serialized for secret in secrets.values())
        assert str(process_broker._AUTH_FILE) not in serialized
    finally:
        receipt.close()
        upstream.close()
        measurement.close()


@pytest.mark.parametrize(
    ("behavior", "classification"),
    (
        ("hang-after-intent", "no-call"),
        ("hang-after-start", "consumed-indeterminate"),
        ("hang-after-start-ignore-child-term", "consumed-indeterminate"),
    ),
)
def test_killable_worker_is_reaped_and_restart_state_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
    classification: str,
) -> None:
    worker_pids: list[int] = []
    original = process_broker.subprocess.Popen

    def retained_popen(*args, **kwargs):
        result = original(*args, **kwargs)
        if list(args[0])[-1:] == ["--test-worker"]:
            worker_pids.append(result.pid)
        return result

    monkeypatch.setattr(process_broker.subprocess, "Popen", retained_popen)
    with pytest.raises(CodexBrokerProcessUnavailable, match="deadline"):
        _run(tmp_path, monkeypatch, behavior=behavior, timeout=0.4)
    assert len(worker_pids) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pids[0], 0)
    observed = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid="],
        check=True,
        capture_output=True,
        text=True,
    )
    process_groups = {
        int(line.split()[1])
        for line in observed.stdout.splitlines()
        if len(line.split()) == 2
    }
    assert worker_pids[0] not in process_groups
    assert (
        process_broker._classify_process_attempt(tmp_path / "process-journal")
        == classification
    )


def test_child_auth_header_is_rejected_before_egress_and_worker_is_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(CodexBrokerProcessUnavailable, match="failed closed"):
        _run(tmp_path, monkeypatch, behavior="child-authorization")
    assert (
        process_broker._classify_process_attempt(tmp_path / "process-journal")
        == "no-call"
    )
    assert not (tmp_path / "process-journal" / "call-started.json").exists()


@pytest.mark.parametrize("upstream_behavior", ("tool", "terminal-web-search"))
def test_tool_event_or_terminal_output_fails_after_one_accounted_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_behavior: str,
) -> None:
    with pytest.raises(CodexBrokerProcessUnavailable, match="failed closed"):
        _run(tmp_path, monkeypatch, upstream_behavior=upstream_behavior)
    assert (
        process_broker._classify_process_attempt(tmp_path / "process-journal")
        == "consumed-indeterminate"
    )
    started = json.loads(
        (tmp_path / "process-journal" / "call-started.json").read_text()
    )
    assert started["call_started"] == 1


@pytest.mark.parametrize(
    "auth_mutation",
    ("near-expiry", "mode", "non-synthetic"),
)
def test_auth_refresh_required_or_inexact_mode_is_zero_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_mutation: str,
) -> None:
    kwargs: dict[str, object] = {}
    if auth_mutation == "near-expiry":
        kwargs["expiry_delta"] = 299
    elif auth_mutation == "non-synthetic":
        kwargs["account"] = "acct_operator_like"
    now = int(time.time())
    auth_file, secrets = _auth_file(tmp_path, now=now, **kwargs)
    if auth_mutation == "mode":
        auth_file.chmod(0o644)
    monkeypatch.setattr(process_broker, "_AUTH_FILE", auth_file)
    upstream = _FakeTLS(tmp_path, secrets)
    journal = _private_root(tmp_path, "process-journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        with pytest.raises(CodexBrokerProcessUnavailable, match="failed closed"):
            process_broker._exercise_fake_codex_broker_process(
                dispatch,
                expected_request=_expected(_request_body()),
                fake_upstream=upstream.authority,
                journal_root=journal,
                now=now,
            )
        assert upstream.state.calls == 0
        assert not any(journal.iterdir())
    finally:
        upstream.close()
        measurement.close()


def test_receipt_copy_replace_and_journal_mutation_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, upstream, journal, measurement, _secrets = _run(tmp_path, monkeypatch)
    try:
        copied = copy.copy(receipt)
        copied.close()
        assert receipt.validate()
        assert not verify_codex_broker_process_test_receipt(copied)
        assert not verify_codex_broker_process_test_receipt(replace(receipt))
        path = journal / "completion.json"
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + b" ")
        path.chmod(0o600)
        assert not receipt.validate()
    finally:
        receipt.close()
        upstream.close()
        measurement.close()


def test_journal_root_replacement_revokes_without_touching_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, upstream, journal, measurement, _secrets = _run(tmp_path, monkeypatch)
    displaced = journal.with_name("displaced-process-journal")
    try:
        journal.rename(displaced)
        journal.mkdir(mode=0o700)
        journal.chmod(0o700)
        sentinel = journal / "sentinel"
        sentinel.write_bytes(b"harmless replacement")
        sentinel.chmod(0o600)
        assert not receipt.validate()
        receipt.close()
        assert sentinel.read_bytes() == b"harmless replacement"
    finally:
        receipt.close()
        upstream.close()
        measurement.close()
