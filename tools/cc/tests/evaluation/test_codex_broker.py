from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import inspect
import json
import os
import socket
import ssl
import subprocess
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import cc.core.evaluation.codex_broker as broker
import pytest
from cc.core.evaluation.codex_broker import (
    CHATGPT_RESPONSES_ENDPOINT,
    CodexBrokerUnavailable,
    codex_broker_test_receipt_document,
    verify_codex_broker_test_receipt,
)
from cc.core.evaluation.codex_isolation import retain_codex_live_dispatch
from cc.core.evaluation.schema import canonical_json_bytes
from test_codex_isolation import MODEL, _synthetic_official_authorization


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _private_root(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root.resolve()


def _jwt(claims: dict[str, object]) -> str:
    def encoded(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encoded({'alg': 'none'})}.{encoded(claims)}.signature"


def _auth_file(
    tmp_path: Path,
    *,
    now: int,
    expiry_delta: int = 3600,
    account: str = "acct_synthetic",
    id_account: str | None = None,
    duplicate: bool = False,
) -> tuple[Path, dict[str, str]]:
    home = _private_root(tmp_path, "home")
    codex_home = _private_root(home, ".codex")
    claims = {
        "exp": now + expiry_delta,
        broker._ACCOUNT_CLAIM: account,
        broker._WORKSPACE_CLAIM: "workspace_synthetic",
        broker._FEDRAMP_CLAIM: False,
    }
    id_claims = {
        "exp": now + expiry_delta,
        broker._ACCOUNT_CLAIM: id_account or account,
        broker._WORKSPACE_CLAIM: "workspace_synthetic",
        broker._FEDRAMP_CLAIM: False,
    }
    secrets = {
        "access_token": _jwt(claims),
        "account_id": account,
        "id_token": _jwt(id_claims),
        "refresh_token": "refresh-synthetic-secret",
    }
    document = {
        "OPENAI_API_KEY": None,
        "last_refresh": "2026-08-15T00:00:00Z",
        "tokens": secrets,
    }
    path = codex_home / "auth.json"
    raw = json.dumps(document, separators=(",", ":")).encode()
    if duplicate:
        raw = raw.replace(b'"tokens":', b'"tokens":{},"tokens":', 1)
    path.write_bytes(raw)
    path.chmod(0o600)
    return path.resolve(), secrets


def _request_body(*, tool: bool = False) -> bytes:
    body: dict[str, Any] = {
        "client_metadata": {
            "turn_id": "01a00000-0000-7000-8000-000000000002",
            "thread_id": "01a00000-0000-7000-8000-000000000001",
        },
        "include": ["reasoning.encrypted_content"],
        "input": [
            {
                "type": "message",
                "id": "msg_01a00000-0000-7000-8000-000000000004",
                "role": "user",
                "content": [{"type": "input_text", "text": "Synthetic prompt"}],
            }
        ],
        "instructions": "Synthetic official instructions.",
        "model": MODEL,
        "parallel_tool_calls": True,
        "prompt_cache_key": "01a00000-0000-7000-8000-000000000001",
        "reasoning": {"effort": "low"},
        "store": False,
        "stream": True,
        "text": {"verbosity": "low"},
        "tool_choice": "auto",
        "tools": [],
    }
    if tool:
        body["tools"] = [{"type": "function", "name": "shell"}]
    return json.dumps(body, separators=(",", ":")).encode()


def _expected(raw: bytes) -> broker._ExpectedRequest:
    return broker._ExpectedRequest(
        bytearray(raw),
        _sha("cell"),
        _sha("prompt"),
        _sha("content"),
        _sha("runtime"),
        MODEL,
    )


def _sse(*, behavior: str = "success") -> bytes:
    identifier = "resp_synthetic"
    events: list[dict[str, object]] = [
        {
            "type": "response.created",
            "response": {"id": identifier, "status": "in_progress"},
        }
    ]
    if behavior == "tool":
        events.append(
            {
                "type": "response.function_call_arguments.delta",
                "response_id": identifier,
                "delta": "{}",
            }
        )
    else:
        events.append(
            {
                "type": "response.output_text.delta",
                "response_id": identifier,
                "delta": "OK",
            }
        )
    if behavior != "incomplete":
        events.append(
            {
                "type": "response.completed",
                "response": {"id": identifier, "status": "completed", "output": []},
            }
        )
    return b"".join(
        b"event: "
        + str(item["type"]).encode()
        + b"\n"
        + b"data: "
        + canonical_json_bytes(item)
        + b"\n\n"
        for item in events
    )


def _certificate(tmp_path: Path) -> tuple[Path, Path]:
    certificate = tmp_path / "chatgpt-test-cert.pem"
    key = tmp_path / "chatgpt-test-key.pem"
    subprocess.run(
        [
            "/usr/bin/openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=chatgpt.com",
            "-addext",
            "subjectAltName=DNS:chatgpt.com",
        ],
        check=True,
        capture_output=True,
    )
    certificate.chmod(0o600)
    key.chmod(0o600)
    return certificate.resolve(), key.resolve()


class _UpstreamState:
    def __init__(
        self,
        *,
        secrets: dict[str, str],
        behavior: str,
        mutate: Callable[[], None] | None = None,
    ) -> None:
        self.secrets = secrets
        self.behavior = behavior
        self.mutate = mutate
        self.calls = 0
        self.requests: list[dict[str, object]] = []


class _Handler(BaseHTTPRequestHandler):
    server: "_UpstreamServer"

    def do_POST(self) -> None:
        state = self.server.state
        state.calls += 1
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        state.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "account": self.headers.get("ChatGPT-Account-ID"),
                "host": self.headers.get("Host"),
                "accept": self.headers.get("Accept"),
                "body": raw,
            }
        )
        if state.mutate is not None:
            state.mutate()
        status = 500 if state.behavior == "status" else 200
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("x-codex-turn-state", "private-turn-state")
        if state.behavior == "cookie":
            self.send_header("Set-Cookie", "session=forbidden")
        body = _sse(behavior=state.behavior)
        if state.behavior == "malformed":
            body = b"data: {\n\n"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        del args


class _UpstreamServer(HTTPServer):
    def __init__(self, state: _UpstreamState) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.state = state


class _FakeTLS:
    def __init__(
        self,
        tmp_path: Path,
        secrets: dict[str, str],
        *,
        behavior: str = "success",
        mutate: Callable[[], None] | None = None,
    ) -> None:
        certificate, key = _certificate(tmp_path)
        self.certificate = certificate
        self.state = _UpstreamState(
            secrets=secrets,
            behavior=behavior,
            mutate=mutate,
        )
        self.server = _UpstreamServer(self.state)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=False)
        self.thread.start()
        self.authority = broker._issue_fake_tls_upstream(
            connect_host="127.0.0.1",
            port=self.server.server_address[1],
            ca_file=certificate,
        )

    def close(self) -> None:
        self.authority.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )
    return receipt, dispatch


def _post_child(raw: bytes) -> Callable[..., int]:
    def child(_context, endpoint: str, nonce: str) -> int:
        parsed = urlsplit(endpoint)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        connection.request(
            "POST",
            parsed.path + "/responses",
            body=raw,
            headers={
                "Content-Type": "application/json",
                "x-cc-broker-nonce": nonce,
            },
        )
        response = connection.getresponse()
        response.read()
        status = response.status
        connection.close()
        return status

    return child


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw: bytes | None = None,
    behavior: str = "success",
    child: Callable[..., object] | None = None,
    auth_kwargs: dict[str, object] | None = None,
    mutate: Callable[[], None] | None = None,
):
    now = int(time.time())
    auth_path, secrets = _auth_file(tmp_path, now=now, **(auth_kwargs or {}))
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)
    request = raw or _request_body()
    upstream = _FakeTLS(
        tmp_path,
        secrets,
        behavior=behavior,
        mutate=mutate,
    )
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        receipt = broker._exercise_fake_codex_broker(
            dispatch,
            expected_request=_expected(request),
            fake_upstream=upstream.authority,
            journal_root=journal,
            child=child or _post_child(request),
            now=now,
        )
        return receipt, upstream, journal, measurement, secrets
    except BaseException:
        upstream.close()
        measurement.close()
        raise


def test_exact_fake_tls_broker_proof_is_nonauthorizing_and_value_suppressing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, upstream, journal, measurement, secrets = _run(tmp_path, monkeypatch)
    try:
        document = codex_broker_test_receipt_document(receipt)
        serialized = json.dumps(document, sort_keys=True)
        assert receipt.validate()
        assert verify_codex_broker_test_receipt(receipt)
        assert document["authorization_scope"] == "fake-upstream-test-only"
        assert document["live_runtime_authorized"] is False
        assert document["endpoint"] == CHATGPT_RESPONSES_ENDPOINT
        assert document["upstream_call_count"] == 1
        assert document["interaction_count"] == 1
        assert document["cleanup_complete"] is True
        assert upstream.state.calls == 1
        request = upstream.state.requests[0]
        assert request["path"] == "/backend-api/codex/responses"
        assert request["authorization"] == f"Bearer {secrets['access_token']}"
        assert request["account"] == secrets["account_id"]
        assert request["host"] == "chatgpt.com"
        assert request["accept"] == "text/event-stream"
        for secret in secrets.values():
            assert secret not in serialized
            assert secret not in (journal / "egress-intent.json").read_text()
        assert "private-turn-state" not in serialized
        assert "Synthetic prompt" not in serialized
    finally:
        receipt.close()
        upstream.close()
        measurement.close()


def test_public_surface_exposes_no_production_runner_or_caller_secrets() -> None:
    assert "_exercise_fake_codex_broker" not in broker.__all__
    assert "_issue_fake_tls_upstream" not in broker.__all__
    assert not hasattr(broker, "run_codex_chatgpt_broker")
    assert not hasattr(broker, "authorize_codex_broker")
    document_signature = inspect.signature(codex_broker_test_receipt_document)
    assert tuple(document_signature.parameters) == ("value",)


@pytest.mark.parametrize(
    "auth_mutation",
    ("mode", "hardlink", "symlink", "duplicate", "near-expiry", "account"),
)
def test_auth_snapshot_rejects_inexact_or_refresh_required_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_mutation: str,
) -> None:
    now = int(time.time())
    kwargs: dict[str, object] = {}
    if auth_mutation == "duplicate":
        kwargs["duplicate"] = True
    elif auth_mutation == "near-expiry":
        kwargs["expiry_delta"] = 299
    elif auth_mutation == "account":
        kwargs["id_account"] = "acct_substituted"
    auth_path, secrets = _auth_file(tmp_path, now=now, **kwargs)
    if auth_mutation == "mode":
        auth_path.chmod(0o644)
    elif auth_mutation == "hardlink":
        os.link(auth_path, auth_path.with_name("auth-hardlink"))
    elif auth_mutation == "symlink":
        original = auth_path.with_name("auth-original")
        auth_path.rename(original)
        auth_path.symlink_to(original)
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)
    upstream = _FakeTLS(tmp_path, secrets)
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        with pytest.raises(
            CodexBrokerUnavailable,
            match="auth|refresh|path|duplicate",
        ):
            broker._exercise_fake_codex_broker(
                dispatch,
                expected_request=_expected(_request_body()),
                fake_upstream=upstream.authority,
                journal_root=journal,
                child=_post_child(_request_body()),
                now=now,
            )
        assert upstream.state.calls == 0
    finally:
        upstream.close()
        measurement.close()


@pytest.mark.parametrize(
    "behavior", ("tool", "incomplete", "malformed", "cookie", "status")
)
def test_sse_status_and_header_substitution_fail_after_exactly_one_accounted_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
) -> None:
    with pytest.raises(CodexBrokerUnavailable, match="completion"):
        _run(tmp_path, monkeypatch, behavior=behavior)
    journal = tmp_path / "journal" / "egress-intent.json"
    assert journal.exists()
    marker = tmp_path / "journal" / "call-started.json"
    assert marker.exists()
    assert json.loads(marker.read_text())["call_started"] == 1


@pytest.mark.parametrize("substitution", ("tool", "duplicate", "unknown"))
def test_substituted_request_body_is_rejected_before_listener_or_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    substitution: str,
) -> None:
    raw = _request_body(tool=substitution == "tool")
    if substitution == "duplicate":
        raw = raw.replace(b'"tools":[]', b'"tools":[],"tools":[]', 1)
    elif substitution == "unknown":
        raw = raw.replace(b"{", b'{"unknown":true,', 1)
    with pytest.raises(CodexBrokerUnavailable, match="tool-free|duplicate"):
        _run(tmp_path, monkeypatch, raw=raw)
    assert not any((tmp_path / "journal").iterdir())


@pytest.mark.parametrize("interaction", ("get-before-post", "wrong-nonce", "extra"))
def test_inbound_extra_method_nonce_or_connection_prevents_upstream_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interaction: str,
) -> None:
    raw = _request_body()

    def child(_context, endpoint: str, nonce: str) -> None:
        parsed = urlsplit(endpoint)

        def request(method: str, *, supplied_nonce: str = nonce) -> int:
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=2
            )
            try:
                connection.request(
                    method,
                    parsed.path + "/responses",
                    body=raw if method == "POST" else None,
                    headers={
                        "Content-Type": "application/json",
                        "x-cc-broker-nonce": supplied_nonce,
                    },
                )
                response = connection.getresponse()
                response.read()
                return response.status
            except OSError:
                return 0
            finally:
                connection.close()

        if interaction == "get-before-post":
            assert request("GET") == 400
            assert request("POST") in {0, 400}
        elif interaction == "wrong-nonce":
            assert request("POST", supplied_nonce="0" * 64) == 400
        else:
            first = threading.Thread(target=request, args=("POST",))
            first.start()
            time.sleep(0.01)
            assert request("POST") in {0, 400}
            first.join(timeout=2)

    now = int(time.time())
    auth_path, secrets = _auth_file(tmp_path, now=now)
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)
    upstream = _FakeTLS(tmp_path, secrets)
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        with pytest.raises(CodexBrokerUnavailable, match="completion"):
            broker._exercise_fake_codex_broker(
                dispatch,
                expected_request=_expected(raw),
                fake_upstream=upstream.authority,
                journal_root=journal,
                child=child,
                now=now,
            )
        assert upstream.state.calls == 0
        assert not (journal / "call-started.json").exists()
    finally:
        upstream.close()
        measurement.close()


@pytest.mark.parametrize(
    "substitution", ("authorization", "duplicate-length", "unknown")
)
def test_raw_inbound_header_injection_is_rejected_before_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    substitution: str,
) -> None:
    raw = _request_body()

    def child(_context, endpoint: str, nonce: str) -> None:
        parsed = urlsplit(endpoint)
        injected = {
            "authorization": "Authorization: Bearer child-forbidden\r\n",
            "duplicate-length": f"Content-Length: {len(raw)}\r\n",
            "unknown": "X-Unregistered: forbidden\r\n",
        }[substitution]
        request = (
            f"POST {parsed.path}/responses HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{parsed.port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(raw)}\r\n"
            f"x-cc-broker-nonce: {nonce}\r\n"
            f"{injected}"
            "\r\n"
        ).encode() + raw
        connection = socket.create_connection(("127.0.0.1", parsed.port), timeout=2)
        connection.sendall(request)
        connection.recv(4096)
        connection.close()

    now = int(time.time())
    auth_path, secrets = _auth_file(tmp_path, now=now)
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)
    upstream = _FakeTLS(tmp_path, secrets)
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        with pytest.raises(CodexBrokerUnavailable, match="completion"):
            broker._exercise_fake_codex_broker(
                dispatch,
                expected_request=_expected(raw),
                fake_upstream=upstream.authority,
                journal_root=journal,
                child=child,
                now=now,
            )
        assert upstream.state.calls == 0
        assert not (journal / "call-started.json").exists()
    finally:
        upstream.close()
        measurement.close()


def test_auth_in_place_mutation_during_upstream_revokes_receipt_without_secret_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(time.time())
    auth_path, secrets = _auth_file(tmp_path, now=now)
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)

    def mutate() -> None:
        auth_path.write_bytes(b'{"substituted":true}')
        auth_path.chmod(0o600)

    upstream = _FakeTLS(tmp_path, secrets, mutate=mutate)
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        with pytest.raises(CodexBrokerUnavailable, match="completion") as captured:
            broker._exercise_fake_codex_broker(
                dispatch,
                expected_request=_expected(_request_body()),
                fake_upstream=upstream.authority,
                journal_root=journal,
                child=_post_child(_request_body()),
                now=now,
            )
        assert upstream.state.calls == 1
        assert all(secret not in str(captured.value) for secret in secrets.values())
        assert (
            json.loads((journal / "call-started.json").read_text())["call_started"] == 1
        )
    finally:
        upstream.close()
        measurement.close()


def test_same_byte_auth_path_replacement_before_request_prevents_egress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(time.time())
    auth_path, secrets = _auth_file(tmp_path, now=now)
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)
    upstream = _FakeTLS(tmp_path, secrets)
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    raw = _request_body()

    def child(context, endpoint: str, nonce: str) -> int:
        replacement = auth_path.with_name("replacement-auth")
        replacement.write_bytes(auth_path.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(auth_path)
        return _post_child(raw)(context, endpoint, nonce)

    try:
        with pytest.raises(CodexBrokerUnavailable, match="completion"):
            broker._exercise_fake_codex_broker(
                dispatch,
                expected_request=_expected(raw),
                fake_upstream=upstream.authority,
                journal_root=journal,
                child=child,
                now=now,
            )
        assert upstream.state.calls == 0
        assert not (journal / "call-started.json").exists()
    finally:
        upstream.close()
        measurement.close()


def test_fake_tls_certificate_path_replacement_revokes_test_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(time.time())
    auth_path, secrets = _auth_file(tmp_path, now=now)
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)
    upstream = _FakeTLS(tmp_path, secrets)
    original = upstream.certificate.with_name("original-certificate")
    upstream.certificate.rename(original)
    upstream.certificate.write_bytes(original.read_bytes())
    upstream.certificate.chmod(0o600)
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)
    try:
        with pytest.raises(CodexBrokerUnavailable, match="TLS authority"):
            broker._exercise_fake_codex_broker(
                dispatch,
                expected_request=_expected(_request_body()),
                fake_upstream=upstream.authority,
                journal_root=journal,
                child=_post_child(_request_body()),
                now=now,
            )
        assert upstream.state.calls == 0
    finally:
        upstream.close()
        measurement.close()


def test_child_crash_closes_dispatch_listener_and_keeps_zero_call_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(time.time())
    auth_path, secrets = _auth_file(tmp_path, now=now)
    monkeypatch.setattr(broker, "_AUTH_FILE", auth_path)
    upstream = _FakeTLS(tmp_path, secrets)
    journal = _private_root(tmp_path, "journal")
    measurement, dispatch = _dispatch(tmp_path, monkeypatch)

    def crash(_context, _endpoint: str, _nonce: str) -> None:
        raise RuntimeError("synthetic child crash")

    try:
        with pytest.raises(RuntimeError, match="synthetic child crash"):
            broker._exercise_fake_codex_broker(
                dispatch,
                expected_request=_expected(_request_body()),
                fake_upstream=upstream.authority,
                journal_root=journal,
                child=crash,
                now=now,
            )
        assert not dispatch.validate()
        assert upstream.state.calls == 0
        assert not (journal / "call-started.json").exists()
        assert not any(
            thread.name == "cc-codex-broker-test" for thread in threading.enumerate()
        )
    finally:
        upstream.close()
        measurement.close()


def test_receipt_copy_replace_close_and_journal_mutation_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, upstream, journal, measurement, _secrets = _run(tmp_path, monkeypatch)
    try:
        copied = copy.copy(receipt)
        copied.close()
        assert receipt.validate()
        assert not verify_codex_broker_test_receipt(copied)
        assert not verify_codex_broker_test_receipt(replace(receipt))
        path = journal / "egress-intent.json"
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + b" ")
        path.chmod(0o600)
        assert not receipt.validate()
    finally:
        receipt.close()
        upstream.close()
        measurement.close()


@pytest.mark.parametrize("replacement", ("direct", "ancestor"))
def test_journal_root_or_ancestor_replacement_revokes_receipt_without_touching_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    receipt, upstream, journal, measurement, _secrets = _run(tmp_path, monkeypatch)
    displaced = None
    try:
        if replacement == "direct":
            displaced = journal.with_name("displaced-journal")
            journal.rename(displaced)
            journal.mkdir(mode=0o700)
            journal.chmod(0o700)
            replacement_root = journal
        else:
            displaced = tmp_path.with_name(tmp_path.name + "-displaced")
            tmp_path.rename(displaced)
            tmp_path.mkdir(mode=0o700)
            tmp_path.chmod(0o700)
            replacement_root = _private_root(tmp_path, "journal")
        sentinel = replacement_root / "sentinel"
        sentinel.write_bytes(b"harmless replacement")
        sentinel.chmod(0o600)
        assert not receipt.validate()
        receipt.close()
        assert sentinel.read_bytes() == b"harmless replacement"
    finally:
        receipt.close()
        upstream.close()
        measurement.close()
