"""Killable fake-upstream process proof for a future Codex broker boundary.

This module deliberately exposes no production runner or authorizer.  It proves
the process, credential, loopback, write-ahead, TLS, and cleanup mechanics using
only a synthetic retained auth file and a loopback TLS server.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from cc.core.evaluation import codex_broker as broker
from cc.core.evaluation import codex_isolation as isolation
from cc.core.evaluation.codex_isolation import (
    CodexLiveDispatch,
    CodexLiveDispatchContext,
    verify_codex_live_dispatch,
    verify_codex_live_dispatch_context,
)
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256

_MODULE_NAME = "cc.core.evaluation.codex_broker_process"
PROCESS_BROKER_TEST_RECEIPT_SCHEMA_VERSION = (
    "task285-codex-broker-process-test-receipt-v1"
)
PROCESS_BROKER_TEST_POLICY_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-codex-broker-process-test-policy-v1",
        "authorization_scope": "fake-upstream-process-boundary-only",
        "live_runtime_authorized": False,
        "worker": {
            "runtime": "isolated-python",
            "argv": ["<PYTHON>", "-I", "-m", _MODULE_NAME, "--test-worker"],
            "environment": {
                "HOME": "/var/empty",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_COLOR": "1",
                "PATH": "/usr/bin:/bin",
                "PYTHONNOUSERSITE": "1",
            },
            "new_session": True,
            "termination": ["TERM", "bounded-wait", "KILL", "exact-reap"],
        },
        "endpoint": broker.CHATGPT_RESPONSES_ENDPOINT,
        "method": "POST",
        "network": "loopback-fake-tls-only",
        "retries": 0,
        "cookies": False,
        "proxies": False,
        "prepared_cell_authority": "absent",
    }
)

_AUTH_FILE: Path | None = None
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FRAME_LIMIT = 64 * 1024
_CONFIG_LIMIT = 12 * 1024 * 1024
_WORKER_TIMEOUT_SECONDS = 8.0
_TERM_SECONDS = 0.5
_KILL_SECONDS = 2.0
_CHILD_SECONDS = 2.0
_LOCK = __import__("threading").RLock()
_RECEIPT_AUTHORITY = object()
_ISSUED_RECEIPTS: weakref.WeakValueDictionary[int, "CodexBrokerProcessTestReceipt"] = (
    weakref.WeakValueDictionary()
)

_WORKER_ENVIRONMENT = {
    "HOME": "/var/empty",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",
    "PATH": "/usr/bin:/bin",
    "PYTHONNOUSERSITE": "1",
}
_WORKER_RESULT_FIELDS = frozenset(
    {
        "account_commitment",
        "auth_commitment",
        "call_started_sha256",
        "completion_sha256",
        "identity_sha256",
        "intent_sha256",
        "interaction_count",
        "journal_sha256",
        "outcome",
        "request_bytes",
        "request_sha256",
        "response_bytes",
        "response_event_count",
        "response_semantic_sha256",
        "schema_version",
        "tls_certificate_sha256",
        "turn_state_commitment",
        "upstream_call_count",
        "upstream_status",
        "workspace_commitment",
    }
)
_JOURNAL_RESULT_FIELDS = frozenset(
    {
        "call_started_sha256",
        "completion_sha256",
        "intent_sha256",
        "journal_sha256",
    }
)

_SYNTHETIC_CHILD = r"""
import base64
import json
import signal
import socket
import sys
from urllib.parse import urlsplit

config = json.loads(sys.stdin.buffer.read().decode("utf-8"))
if config["behavior"] == "hang-after-start-ignore-child-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
raw = base64.b64decode(config["request_b64"], validate=True)
endpoint = urlsplit(config["endpoint"])
head = (
    f"POST {endpoint.path}/responses HTTP/1.1\r\n"
    f"Host: 127.0.0.1:{endpoint.port}\r\n"
    "Content-Type: application/json\r\n"
    f"Content-Length: {len(raw)}\r\n"
    f"x-cc-broker-nonce: {config['nonce']}\r\n"
)
if config["behavior"] == "child-authorization":
    head += "Authorization: Bearer child-forbidden\r\n"
request = (head + "\r\n").encode("ascii") + raw
connection = socket.create_connection(("127.0.0.1", endpoint.port), timeout=2)
try:
    connection.sendall(request)
    response = bytearray()
    while True:
        part = connection.recv(65536)
        if not part:
            break
        response.extend(part)
finally:
    connection.close()
for index in range(len(raw)):
    pass
raise SystemExit(0 if response.startswith(b"HTTP/1.1 200 OK\r\n") else 31)
"""


class CodexBrokerProcessUnavailable(ValueError):
    """The nonauthorizing process-boundary proof failed closed."""


def _require_digest(value: object, description: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CodexBrokerProcessUnavailable(f"{description} is not a digest.")
    return value


def _closed_json(raw: bytes, *, maximum: int) -> dict[str, Any]:
    if not raw or len(raw) > maximum:
        raise CodexBrokerProcessUnavailable("Process broker JSON exceeds its limit.")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=broker._reject_duplicates
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        broker.CodexBrokerUnavailable,
    ) as exc:
        raise CodexBrokerProcessUnavailable(
            "Process broker JSON is malformed."
        ) from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise CodexBrokerProcessUnavailable("Process broker JSON is not canonical.")
    return value


def _write_all(descriptor: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(descriptor, raw[offset:])
        if written < 1:
            raise CodexBrokerProcessUnavailable(
                "Process broker write made no progress."
            )
        offset += written


def _write_exclusive_at(directory_fd: int, name: str, raw: bytes) -> tuple[int, ...]:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None or not name or "/" in name:
        raise CodexBrokerProcessUnavailable("Process journal platform is unsupported.")
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | no_follow
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        _write_all(descriptor, raw)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if broker._identity(opened) != broker._identity(named):
            raise CodexBrokerProcessUnavailable("Process journal identity differs.")
        os.fsync(directory_fd)
        return broker._identity(opened)
    except CodexBrokerProcessUnavailable:
        raise
    except OSError as exc:
        raise CodexBrokerProcessUnavailable(
            "Process journal write failed closed."
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _frame(value: Mapping[str, object]) -> bytes:
    raw = canonical_json_bytes(dict(value))
    if len(raw) + 1 > _FRAME_LIMIT:
        raise CodexBrokerProcessUnavailable("Process broker frame exceeds its limit.")
    return raw + b"\n"


def _worker_emit(value: Mapping[str, object]) -> None:
    _write_all(sys.stdout.fileno(), _frame(value))
    sys.stdout.flush()


def _journal_identity(
    config: Mapping[str, Any], auth: broker._RetainedAuthSnapshot, key: bytearray
) -> dict[str, object]:
    return {
        "dispatch_sha256": _require_digest(config["dispatch_sha256"], "dispatch"),
        "authorization_sha256": _require_digest(
            config["authorization_sha256"], "authorization"
        ),
        "permit_sha256": _require_digest(config["permit_sha256"], "permit"),
        "cell_sha256": _require_digest(config["cell_sha256"], "cell"),
        "prompt_sha256": _require_digest(config["prompt_sha256"], "prompt"),
        "content_sha256": _require_digest(config["content_sha256"], "content"),
        "runtime_sha256": _require_digest(config["runtime_sha256"], "runtime"),
        "request_sha256": _require_digest(config["request_sha256"], "request"),
        "auth_commitment": auth.commitment(key),
        "account_commitment": auth.account_commitment(key),
        "workspace_commitment": auth.workspace_commitment(key),
        "endpoint": broker.CHATGPT_RESPONSES_ENDPOINT,
        "method": "POST",
        "attempt_id": _require_digest(config["attempt_id"], "attempt"),
        "process_policy_sha256": PROCESS_BROKER_TEST_POLICY_SHA256,
    }


def _verify_synthetic_auth(auth: broker._RetainedAuthSnapshot) -> None:
    """Keep this proof structurally incapable of using an operator credential."""

    if (
        bytes(auth.account_id) != b"acct_synthetic"
        or bytes(auth.workspace_id) != b"workspace_synthetic"
        or bytes(auth.refresh_token) != b"refresh-synthetic-secret"
        or not bytes(auth.access_token).endswith(b".signature")
        or not bytes(auth.id_token).endswith(b".signature")
    ):
        raise CodexBrokerProcessUnavailable(
            "Process broker proof requires fixed synthetic auth."
        )


def _spawn_synthetic_child(
    endpoint: str, nonce: str, raw: bytes, *, behavior: str
) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", _SYNTHETIC_CHILD],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd="/",
        env=_WORKER_ENVIRONMENT,
        close_fds=True,
        start_new_session=False,
    )
    if process.stdin is None:
        process.kill()
        process.wait()
        raise CodexBrokerProcessUnavailable("Synthetic child pipe is unavailable.")
    child_config = canonical_json_bytes(
        {
            "behavior": behavior,
            "endpoint": endpoint,
            "nonce": nonce,
            "request_b64": base64.b64encode(raw).decode("ascii"),
        }
    )
    try:
        process.stdin.write(child_config)
        process.stdin.close()
    except OSError:
        process.kill()
        process.wait()
        raise
    return process


def _finish_synthetic_child(process: subprocess.Popen[bytes]) -> None:
    try:
        return_code = process.wait(timeout=_CHILD_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=_KILL_SECONDS)
        raise CodexBrokerProcessUnavailable("Synthetic child exceeded its deadline.")
    if return_code != 0:
        raise CodexBrokerProcessUnavailable("Synthetic child failed closed.")


def _worker_execute(config: Mapping[str, Any]) -> dict[str, object]:
    now = config.get("now")
    if not isinstance(now, int) or isinstance(now, bool):
        raise CodexBrokerProcessUnavailable("Process broker clock differs.")
    try:
        request_raw = bytearray(base64.b64decode(config["request_b64"], validate=True))
    except (KeyError, TypeError, ValueError) as exc:
        raise CodexBrokerProcessUnavailable(
            "Process broker request is malformed."
        ) from exc
    if hashlib.sha256(request_raw).hexdigest() != config.get("request_sha256"):
        raise CodexBrokerProcessUnavailable("Process broker request identity differs.")

    expected: broker._ExpectedRequest | None = None
    auth: broker._RetainedAuthSnapshot | None = None
    upstream: broker._FakeTLSUpstream | None = None
    journal: broker._AttemptJournal | None = None
    listener: socket.socket | None = None
    connection: socket.socket | None = None
    child: subprocess.Popen[bytes] | None = None
    key = bytearray(base64.b64decode(config["hmac_key_b64"], validate=True))
    try:
        expected = broker._ExpectedRequest(
            bytearray(request_raw),
            config["cell_sha256"],
            config["prompt_sha256"],
            config["content_sha256"],
            config["runtime_sha256"],
            config["model"],
        )
        auth = broker._RetainedAuthSnapshot(Path(config["auth_file"]), now=now)
        _verify_synthetic_auth(auth)
        upstream = broker._issue_fake_tls_upstream(
            connect_host="127.0.0.1",
            port=config["fake_upstream_port"],
            ca_file=Path(config["fake_ca_file"]),
        )
        identity = _journal_identity(config, auth, key)
        journal = broker._AttemptJournal(Path(config["journal_root"]), identity)
        if config.get("test_behavior") == "hang-after-intent":
            time.sleep(60)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(broker._IDLE_TIMEOUT_SECONDS)
        nonce = secrets.token_hex(32)
        endpoint = f"http://127.0.0.1:{listener.getsockname()[1]}/v1/{nonce}"
        child = _spawn_synthetic_child(
            endpoint,
            nonce,
            bytes(request_raw),
            behavior=config["test_behavior"],
        )
        connection, _address = listener.accept()
        body = broker._parse_child_request(
            connection,
            nonce=nonce,
            port=listener.getsockname()[1],
        )
        if (
            not expected.matches(body)
            or not auth.validate(now=now)
            or not journal.validate()
        ):
            raise CodexBrokerProcessUnavailable(
                "Process broker pre-egress identity differs."
            )
        broker._verify_request_body(body, expected_model=expected.model)
        listener.settimeout(broker._QUIET_SECONDS)
        try:
            extra, _extra_address = listener.accept()
        except socket.timeout:
            extra = None
        if extra is not None:
            broker._send_child_failure(extra)
            extra.close()
            raise CodexBrokerProcessUnavailable(
                "Process broker saw an extra interaction."
            )

        journal.mark_started()
        if config.get("test_behavior") in {
            "hang-after-start",
            "hang-after-start-ignore-child-term",
        }:
            time.sleep(60)
        owner = broker._BrokerServerState(
            listener,
            nonce,
            expected,
            auth,
            upstream,
            journal,
            now,
            key,
            interactions=1,
            call_count=1,
        )
        response = broker._fake_tls_request(
            upstream,
            auth,
            body,
            now=now,
            owner=owner,
        )
        broker._send_child_response(connection, response)
        connection.close()
        connection = None
        _finish_synthetic_child(child)
        child = None
        if (
            not auth.validate(now=int(time.time()))
            or not upstream.validate()
            or not journal.validate()
            or owner.active_upstream_socket is not None
        ):
            raise CodexBrokerProcessUnavailable(
                "Process broker post-egress identity differs."
            )

        result = {
            "schema_version": "task285-codex-broker-process-worker-result-v1",
            "identity_sha256": canonical_sha256(identity),
            "request_sha256": hashlib.sha256(body).hexdigest(),
            "request_bytes": len(body),
            "response_semantic_sha256": response.semantic_sha256,
            "response_bytes": len(response.body),
            "response_event_count": response.event_count,
            "turn_state_commitment": hmac.new(
                key, response.turn_state.encode("ascii"), hashlib.sha256
            ).hexdigest(),
            "auth_commitment": identity["auth_commitment"],
            "account_commitment": identity["account_commitment"],
            "workspace_commitment": identity["workspace_commitment"],
            "tls_certificate_sha256": upstream.certificate_sha256,
            "upstream_call_count": 1,
            "upstream_status": response.status,
            "interaction_count": 1,
            "outcome": "fake-upstream-process-validated",
        }
        completion_raw = canonical_json_bytes(
            {
                **result,
                "schema_version": "task285-codex-broker-process-completion-v1",
            }
        )
        _write_exclusive_at(journal.chain.fd, "completion.json", completion_raw)
        result["intent_sha256"] = hashlib.sha256(journal.before).hexdigest()
        result["call_started_sha256"] = hashlib.sha256(journal.started_raw).hexdigest()
        result["completion_sha256"] = hashlib.sha256(completion_raw).hexdigest()
        result["journal_sha256"] = canonical_sha256(
            {
                "schema_version": "task285-codex-broker-process-journal-v1",
                "intent_sha256": result["intent_sha256"],
                "call_started_sha256": result["call_started_sha256"],
                "completion_sha256": result["completion_sha256"],
            }
        )
        return result
    finally:
        if connection is not None:
            broker._send_child_failure(connection)
            connection.close()
        if listener is not None:
            listener.close()
        if child is not None:
            child.kill()
            child.wait(timeout=_KILL_SECONDS)
        if journal is not None:
            journal.close()
        if upstream is not None:
            upstream.close()
        if auth is not None:
            auth.close()
        if expected is not None:
            expected.close()
        broker._zero(request_raw)
        broker._zero(key)


def _worker_main() -> int:
    try:
        framed_config = sys.stdin.buffer.readline(_CONFIG_LIMIT + 2)
        if not framed_config.endswith(b"\n"):
            raise CodexBrokerProcessUnavailable(
                "Process broker config framing differs."
            )
        config_raw = framed_config[:-1]
        config = _closed_json(config_raw, maximum=_CONFIG_LIMIT)
        if set(config) != {
            "attempt_id",
            "auth_file",
            "authorization_sha256",
            "cell_sha256",
            "content_sha256",
            "dispatch_sha256",
            "fake_ca_file",
            "fake_upstream_port",
            "hmac_key_b64",
            "journal_root",
            "model",
            "now",
            "permit_sha256",
            "prompt_sha256",
            "request_b64",
            "request_sha256",
            "runtime_sha256",
            "test_behavior",
        }:
            raise CodexBrokerProcessUnavailable("Process broker config differs.")
        _worker_emit(
            {
                "kind": "ready",
                "pid": os.getpid(),
                "pgid": os.getpgrp(),
                "sid": os.getsid(0),
            }
        )
        if sys.stdin.buffer.read(3) != b"GO\n":
            raise CodexBrokerProcessUnavailable(
                "Process broker launch was not acknowledged."
            )
        result = _worker_execute(config)
        _worker_emit({"kind": "result", "result": result})
        return 0
    except BaseException:
        try:
            _worker_emit({"kind": "failure", "reason": "worker-failed-closed"})
        except BaseException:
            pass
        return 70


@dataclass
class _RetainedProcessJournal:
    root: Path
    chain: broker._RetainedDirectoryChain = field(init=False, repr=False)
    descriptors: dict[str, int] = field(init=False, repr=False, default_factory=dict)
    identities: dict[str, tuple[int, ...]] = field(
        init=False, repr=False, default_factory=dict
    )
    raw: dict[str, bytes] = field(init=False, repr=False, default_factory=dict)
    documents: dict[str, dict[str, Any]] = field(
        init=False, repr=False, default_factory=dict
    )
    closed: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.chain = broker._RetainedDirectoryChain(self.root, private_tail=1)
        try:
            if tuple(sorted(os.listdir(self.chain.fd))) != (
                "call-started.json",
                "completion.json",
                "egress-intent.json",
            ):
                raise CodexBrokerProcessUnavailable("Process journal is incomplete.")
            for name in (
                "egress-intent.json",
                "call-started.json",
                "completion.json",
            ):
                self._retain(name)
            intent = self.documents["egress-intent.json"]
            started = self.documents["call-started.json"]
            completion = self.documents["completion.json"]
            if (
                intent.get("schema_version") != "task285-codex-broker-egress-intent-v1"
                or started.get("schema_version")
                != "task285-codex-broker-call-started-v1"
                or completion.get("schema_version")
                != "task285-codex-broker-process-completion-v1"
                or intent.get("call_started") != 0
                or started.get("call_started") != 1
                or {
                    key: value
                    for key, value in intent.items()
                    if key not in {"schema_version", "call_started"}
                }
                != {
                    key: value
                    for key, value in started.items()
                    if key not in {"schema_version", "call_started"}
                }
                or completion.get("identity_sha256")
                != canonical_sha256(
                    {
                        key: value
                        for key, value in intent.items()
                        if key not in {"schema_version", "call_started"}
                    }
                )
            ):
                raise CodexBrokerProcessUnavailable("Process journal lineage differs.")
            if not self.validate():
                raise CodexBrokerProcessUnavailable(
                    "Process journal changed during load."
                )
        except BaseException:
            self.close()
            raise

    def _retain(self, name: str) -> None:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise CodexBrokerProcessUnavailable(
                "Process journal no-follow is unavailable."
            )
        descriptor = os.open(
            name,
            os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
            dir_fd=self.chain.fd,
        )
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=self.chain.fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or broker._identity(opened) != broker._identity(named)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_size < 2
            or opened.st_size > _FRAME_LIMIT
        ):
            os.close(descriptor)
            raise CodexBrokerProcessUnavailable("Process journal leaf differs.")
        raw = os.read(descriptor, opened.st_size + 1)
        document = _closed_json(raw, maximum=_FRAME_LIMIT)
        self.descriptors[name] = descriptor
        self.identities[name] = broker._identity(opened)
        self.raw[name] = raw
        self.documents[name] = document

    @property
    def sha256(self) -> str:
        return canonical_sha256(
            {
                "schema_version": "task285-codex-broker-process-journal-v1",
                "intent_sha256": hashlib.sha256(
                    self.raw["egress-intent.json"]
                ).hexdigest(),
                "call_started_sha256": hashlib.sha256(
                    self.raw["call-started.json"]
                ).hexdigest(),
                "completion_sha256": hashlib.sha256(
                    self.raw["completion.json"]
                ).hexdigest(),
            }
        )

    def validate(self) -> bool:
        if self.closed or not self.chain.validate():
            return False
        try:
            if tuple(sorted(os.listdir(self.chain.fd))) != tuple(
                sorted(self.descriptors)
            ):
                return False
            for name, descriptor in self.descriptors.items():
                opened = os.fstat(descriptor)
                named = os.stat(name, dir_fd=self.chain.fd, follow_symlinks=False)
                if (
                    broker._identity(opened) != self.identities[name]
                    or broker._identity(named) != self.identities[name]
                ):
                    return False
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.read(descriptor, len(self.raw[name]) + 1) != self.raw[name]:
                    return False
            return True
        except OSError:
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for descriptor in self.descriptors.values():
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.descriptors.clear()
        self.chain.close()


@dataclass
class _ReceiptState:
    journal: _RetainedProcessJournal
    seal: object
    closed: bool = False


@dataclass(frozen=True)
class CodexBrokerProcessTestReceipt:
    """Sealed process proof which cannot authorize a live/model runtime."""

    schema_version: str
    receipt_sha256: str
    authorization_scope: str
    live_runtime_authorized: bool
    process_policy_sha256: str
    endpoint: str
    method: str
    attempt_id: str
    dispatch_sha256: str
    authorization_sha256: str
    permit_sha256: str
    cell_sha256: str
    prompt_sha256: str
    content_sha256: str
    runtime_sha256: str
    model: str
    native_binary_sha256: str
    model_catalog_sha256: str
    tool_registry_sha256: str
    request_sha256: str
    request_bytes: int
    response_semantic_sha256: str
    response_bytes: int
    response_event_count: int
    auth_commitment: str
    account_commitment: str
    workspace_commitment: str
    turn_state_commitment: str
    tls_certificate_sha256: str
    upstream_call_count: int
    upstream_status: int
    interaction_count: int
    journal_sha256: str
    worker_pid_commitment: str
    worker_pgid_commitment: str
    worker_exit_code: int
    worker_reaped: bool
    descendants_reaped: bool
    prepared_cell_authority: str
    outcome: str
    _state: _ReceiptState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def validate(self) -> bool:
        return verify_codex_broker_process_test_receipt(self)

    def close(self) -> None:
        with _LOCK:
            if _ISSUED_RECEIPTS.get(id(self)) is self:
                _ISSUED_RECEIPTS.pop(id(self), None)
                self._state.closed = True
                self._state.journal.close()


def _receipt_document(value: CodexBrokerProcessTestReceipt) -> dict[str, object]:
    return {
        name: getattr(value, name)
        for name in value.__dataclass_fields__
        if not name.startswith("_") and name != "receipt_sha256"
    }


def verify_codex_broker_process_test_receipt(value: object) -> bool:
    if not isinstance(value, CodexBrokerProcessTestReceipt):
        return False
    with _LOCK:
        try:
            return bool(
                _ISSUED_RECEIPTS.get(id(value)) is value
                and value._authority is _RECEIPT_AUTHORITY
                and value._seal is value._state.seal
                and not value._state.closed
                and value.authorization_scope == "fake-upstream-process-boundary-only"
                and value.live_runtime_authorized is False
                and value.prepared_cell_authority == "absent"
                and value.worker_exit_code == 0
                and value.worker_reaped is True
                and value.descendants_reaped is True
                and value._state.journal.validate()
                and value.journal_sha256 == value._state.journal.sha256
                and value.receipt_sha256 == canonical_sha256(_receipt_document(value))
            )
        except (AttributeError, TypeError, ValueError):
            return False


def codex_broker_process_test_receipt_document(
    value: CodexBrokerProcessTestReceipt,
) -> dict[str, object]:
    if not verify_codex_broker_process_test_receipt(value):
        raise CodexBrokerProcessUnavailable("Process broker receipt is not authentic.")
    return {"receipt_sha256": value.receipt_sha256, **_receipt_document(value)}


def _signal_before_reap(pid: int, *, group_ready: bool, signal_number: int) -> None:
    try:
        if group_ready:
            os.killpg(pid, signal_number)
        else:
            os.kill(pid, signal_number)
    except ProcessLookupError:
        pass
    except OSError as exc:
        if exc.errno != errno.ESRCH:
            raise CodexBrokerProcessUnavailable("Broker worker signal failed.") from exc


def _wait_sentinel(process: subprocess.Popen[bytes], timeout: float) -> bool:
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        return bool(selector.select(timeout))
    finally:
        selector.close()


def _terminate_and_reap(
    process: subprocess.Popen[bytes],
    *,
    group_ready: bool,
    output_eof: bool,
) -> tuple[int, bool]:
    del output_eof
    if group_ready:
        try:
            return_code = isolation._terminate_process_group(
                process,
                process_group_verified=True,
            )
        except isolation.CodexIsolationUnavailable as exc:
            raise CodexBrokerProcessUnavailable(
                "Broker worker process group could not be reaped."
            ) from exc
        return return_code, False
    _signal_before_reap(
        process.pid, group_ready=group_ready, signal_number=signal.SIGTERM
    )
    exited = _wait_sentinel(process, _TERM_SECONDS)
    killed = False
    if not exited:
        _signal_before_reap(
            process.pid,
            group_ready=group_ready,
            signal_number=signal.SIGKILL,
        )
        killed = True
        exited = _wait_sentinel(process, _KILL_SECONDS)
    if not exited:
        raise CodexBrokerProcessUnavailable("Broker worker could not be terminated.")
    return_code = process.wait(timeout=0)
    return return_code, killed


def _read_process_frames(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> tuple[dict[str, Any], dict[str, Any] | None, bool, bool, bool]:
    if process.stdout is None or process.stdin is None:
        raise CodexBrokerProcessUnavailable("Broker worker output is unavailable.")
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    selector = selectors.DefaultSelector()
    selector.register(descriptor, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    buffered = bytearray()
    ready: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    timed_out = False
    group_ready = False
    output_eof = False
    try:
        while time.monotonic() < deadline:
            events = selector.select(min(0.1, deadline - time.monotonic()))
            if not events:
                continue
            part = os.read(descriptor, 4096)
            if not part:
                output_eof = True
                break
            buffered.extend(part)
            if len(buffered) > _FRAME_LIMIT * 2:
                raise CodexBrokerProcessUnavailable(
                    "Broker worker output exceeds its limit."
                )
            while b"\n" in buffered:
                raw, _, remainder = buffered.partition(b"\n")
                buffered[:] = remainder
                frame = _closed_json(raw, maximum=_FRAME_LIMIT)
                if frame.get("kind") == "ready" and ready is None:
                    if (
                        set(frame) != {"kind", "pgid", "pid", "sid"}
                        or frame.get("pid") != process.pid
                        or frame.get("pgid") != process.pid
                        or frame.get("sid") != process.pid
                        or os.getpgid(process.pid) != process.pid
                        or os.getsid(process.pid) != process.pid
                    ):
                        raise CodexBrokerProcessUnavailable(
                            "Broker worker process identity differs."
                        )
                    ready = frame
                    group_ready = True
                    process.stdin.write(b"GO\n")
                    process.stdin.flush()
                    process.stdin.close()
                elif frame.get("kind") == "result" and result is None:
                    result = frame
                elif frame.get("kind") == "failure" and result is None:
                    result = frame
                else:
                    raise CodexBrokerProcessUnavailable(
                        "Broker worker frame lineage differs."
                    )
        else:
            timed_out = True
    finally:
        selector.close()
    if ready is None:
        raise CodexBrokerProcessUnavailable("Broker worker never established identity.")
    return ready, result, timed_out, group_ready, output_eof


def _launch_worker(
    config: Mapping[str, object], *, timeout: float
) -> tuple[dict[str, Any], int, int, int]:
    raw = canonical_json_bytes(dict(config))
    if len(raw) > _CONFIG_LIMIT:
        raise CodexBrokerProcessUnavailable("Broker worker config exceeds its limit.")
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", _MODULE_NAME, "--test-worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd="/",
        env=_WORKER_ENVIRONMENT,
        close_fds=True,
        start_new_session=True,
    )
    group_ready = False
    result: dict[str, Any] | None = None
    ready: dict[str, Any] | None = None
    timed_out = False
    output_eof = False
    try:
        if process.stdin is None:
            raise CodexBrokerProcessUnavailable("Broker worker input is unavailable.")
        process.stdin.write(raw + b"\n")
        process.stdin.flush()
        ready, result, timed_out, group_ready, output_eof = _read_process_frames(
            process, timeout=timeout
        )
    finally:
        return_code, killed = _terminate_and_reap(
            process,
            group_ready=group_ready,
            output_eof=output_eof,
        )
        if process.stdout is not None:
            process.stdout.close()
        if process.stdin is not None:
            process.stdin.close()
    if timed_out or killed:
        raise CodexBrokerProcessUnavailable("Broker worker exceeded its deadline.")
    if return_code != 0 or result is None or result.get("kind") != "result":
        raise CodexBrokerProcessUnavailable("Broker worker failed closed.")
    nested = result.get("result")
    if not isinstance(nested, dict):
        raise CodexBrokerProcessUnavailable("Broker worker result differs.")
    return nested, process.pid, int(ready["pgid"]), return_code


def _classify_process_attempt(root: Path) -> str:
    chain = broker._RetainedDirectoryChain(Path(root), private_tail=1)
    try:
        entries = tuple(sorted(os.listdir(chain.fd)))
        if entries == ("egress-intent.json",):
            return "no-call"
        if entries == ("call-started.json", "egress-intent.json"):
            return "consumed-indeterminate"
        if entries == (
            "call-started.json",
            "completion.json",
            "egress-intent.json",
        ):
            return "completed-untrusted-until-loaded"
        return "invalid"
    finally:
        chain.close()


def _exercise_fake_codex_broker_process(
    dispatch: CodexLiveDispatch,
    *,
    expected_request: broker._ExpectedRequest,
    fake_upstream: broker._FakeTLSUpstream,
    journal_root: Path,
    now: int,
    timeout: float = _WORKER_TIMEOUT_SECONDS,
    test_behavior: str = "run",
) -> CodexBrokerProcessTestReceipt:
    """Internal fake-only proof. It cannot accept a prepared production cell."""

    if (
        not verify_codex_live_dispatch(dispatch)
        or not isinstance(expected_request, broker._ExpectedRequest)
        or expected_request.closed
        or not fake_upstream.validate()
        or test_behavior
        not in {
            "run",
            "hang-after-intent",
            "hang-after-start",
            "hang-after-start-ignore-child-term",
            "child-authorization",
        }
        or timeout <= 0
        or not isinstance(_AUTH_FILE, Path)
        or not _AUTH_FILE.is_absolute()
    ):
        raise CodexBrokerProcessUnavailable(
            "Process broker proof input is unavailable."
        )
    key = bytearray(secrets.token_bytes(32))
    attempt_id = canonical_sha256(
        {
            "schema_version": "task285-codex-broker-process-attempt-v1",
            "dispatch_sha256": dispatch.dispatch_sha256,
            "request_sha256": expected_request.sha256,
            "nonce": secrets.token_hex(32),
        }
    )
    retained_journal: _RetainedProcessJournal | None = None
    result: dict[str, Any] | None = None
    worker_pid = -1
    worker_pgid = -1
    return_code = -1
    try:

        def run(context: CodexLiveDispatchContext) -> None:
            nonlocal result, worker_pid, worker_pgid, return_code
            if not verify_codex_live_dispatch_context(context):
                raise CodexBrokerProcessUnavailable("Process dispatch context differs.")
            config = {
                "attempt_id": attempt_id,
                "auth_file": str(_AUTH_FILE),
                "authorization_sha256": context.authorization_sha256,
                "cell_sha256": expected_request.cell_sha256,
                "content_sha256": expected_request.content_sha256,
                "dispatch_sha256": context.dispatch_sha256,
                "fake_ca_file": str(fake_upstream._certificate.path),
                "fake_upstream_port": fake_upstream.port,
                "hmac_key_b64": base64.b64encode(key).decode("ascii"),
                "journal_root": str(Path(journal_root)),
                "model": context.model,
                "now": now,
                "permit_sha256": context.permit_sha256,
                "prompt_sha256": expected_request.prompt_sha256,
                "request_b64": base64.b64encode(expected_request.raw).decode("ascii"),
                "request_sha256": expected_request.sha256,
                "runtime_sha256": expected_request.runtime_sha256,
                "test_behavior": test_behavior,
            }
            result, worker_pid, worker_pgid, return_code = _launch_worker(
                config, timeout=timeout
            )

        dispatch.run_once(run)
        if (
            result is None
            or _classify_process_attempt(journal_root)
            != "completed-untrusted-until-loaded"
        ):
            raise CodexBrokerProcessUnavailable(
                "Process broker did not complete exactly."
            )
        retained_journal = _RetainedProcessJournal(journal_root)
        intent = retained_journal.documents["egress-intent.json"]
        completion = retained_journal.documents["completion.json"]
        for name in (
            "request_sha256",
            "response_semantic_sha256",
            "auth_commitment",
            "account_commitment",
            "workspace_commitment",
            "turn_state_commitment",
            "tls_certificate_sha256",
        ):
            _require_digest(result.get(name), name)
        expected_identity = {
            "dispatch_sha256": dispatch.dispatch_sha256,
            "authorization_sha256": dispatch.authorization_sha256,
            "permit_sha256": dispatch.permit_sha256,
            "cell_sha256": expected_request.cell_sha256,
            "prompt_sha256": expected_request.prompt_sha256,
            "content_sha256": expected_request.content_sha256,
            "runtime_sha256": expected_request.runtime_sha256,
            "request_sha256": expected_request.sha256,
            "auth_commitment": result.get("auth_commitment"),
            "account_commitment": result.get("account_commitment"),
            "workspace_commitment": result.get("workspace_commitment"),
            "endpoint": broker.CHATGPT_RESPONSES_ENDPOINT,
            "method": "POST",
            "attempt_id": attempt_id,
            "process_policy_sha256": PROCESS_BROKER_TEST_POLICY_SHA256,
        }
        expected_intent = {
            "schema_version": "task285-codex-broker-egress-intent-v1",
            **expected_identity,
            "call_started": 0,
        }
        expected_completion = {
            **{
                name: value
                for name, value in result.items()
                if name not in _JOURNAL_RESULT_FIELDS
            },
            "schema_version": "task285-codex-broker-process-completion-v1",
        }
        if (
            set(result) != _WORKER_RESULT_FIELDS
            or intent != expected_intent
            or result.get("identity_sha256") != canonical_sha256(expected_identity)
            or completion != expected_completion
            or result.get("request_sha256") != expected_request.sha256
            or result.get("journal_sha256") != retained_journal.sha256
            or result.get("intent_sha256")
            != hashlib.sha256(retained_journal.raw["egress-intent.json"]).hexdigest()
            or result.get("call_started_sha256")
            != hashlib.sha256(retained_journal.raw["call-started.json"]).hexdigest()
            or result.get("completion_sha256")
            != hashlib.sha256(retained_journal.raw["completion.json"]).hexdigest()
            or result.get("upstream_call_count") != 1
            or result.get("interaction_count") != 1
            or result.get("upstream_status") != 200
            or result.get("outcome") != "fake-upstream-process-validated"
        ):
            raise CodexBrokerProcessUnavailable(
                "Process broker result identity differs."
            )
        pid_commitment = hmac.new(
            key, str(worker_pid).encode(), hashlib.sha256
        ).hexdigest()
        pgid_commitment = hmac.new(
            key, str(worker_pgid).encode(), hashlib.sha256
        ).hexdigest()
        seal = object()
        state = _ReceiptState(retained_journal, seal)
        values = {
            "schema_version": PROCESS_BROKER_TEST_RECEIPT_SCHEMA_VERSION,
            "receipt_sha256": "0" * 64,
            "authorization_scope": "fake-upstream-process-boundary-only",
            "live_runtime_authorized": False,
            "process_policy_sha256": PROCESS_BROKER_TEST_POLICY_SHA256,
            "endpoint": broker.CHATGPT_RESPONSES_ENDPOINT,
            "method": "POST",
            "attempt_id": attempt_id,
            "dispatch_sha256": dispatch.dispatch_sha256,
            "authorization_sha256": dispatch.authorization_sha256,
            "permit_sha256": dispatch.permit_sha256,
            "cell_sha256": expected_request.cell_sha256,
            "prompt_sha256": expected_request.prompt_sha256,
            "content_sha256": expected_request.content_sha256,
            "runtime_sha256": expected_request.runtime_sha256,
            "model": dispatch.model,
            "native_binary_sha256": dispatch.native_binary_sha256,
            "model_catalog_sha256": dispatch.model_catalog_sha256,
            "tool_registry_sha256": dispatch.tool_registry_sha256,
            "request_sha256": result["request_sha256"],
            "request_bytes": result["request_bytes"],
            "response_semantic_sha256": result["response_semantic_sha256"],
            "response_bytes": result["response_bytes"],
            "response_event_count": result["response_event_count"],
            "auth_commitment": result["auth_commitment"],
            "account_commitment": result["account_commitment"],
            "workspace_commitment": result["workspace_commitment"],
            "turn_state_commitment": result["turn_state_commitment"],
            "tls_certificate_sha256": result["tls_certificate_sha256"],
            "upstream_call_count": 1,
            "upstream_status": 200,
            "interaction_count": 1,
            "journal_sha256": retained_journal.sha256,
            "worker_pid_commitment": pid_commitment,
            "worker_pgid_commitment": pgid_commitment,
            "worker_exit_code": return_code,
            "worker_reaped": True,
            "descendants_reaped": True,
            "prepared_cell_authority": "absent",
            "outcome": "fake-upstream-process-validated",
            "_state": state,
            "_seal": seal,
            "_authority": _RECEIPT_AUTHORITY,
        }
        provisional = CodexBrokerProcessTestReceipt(**values)
        receipt = CodexBrokerProcessTestReceipt(
            **{
                **values,
                "receipt_sha256": canonical_sha256(_receipt_document(provisional)),
            }
        )
        with _LOCK:
            _ISSUED_RECEIPTS[id(receipt)] = receipt
        retained_journal = None
        return receipt
    finally:
        if retained_journal is not None:
            retained_journal.close()
        expected_request.close()
        fake_upstream.close()
        broker._zero(key)


__all__ = [
    "PROCESS_BROKER_TEST_POLICY_SHA256",
    "PROCESS_BROKER_TEST_RECEIPT_SCHEMA_VERSION",
    "CodexBrokerProcessTestReceipt",
    "CodexBrokerProcessUnavailable",
    "codex_broker_process_test_receipt_document",
    "verify_codex_broker_process_test_receipt",
]


if __name__ == "__main__" and sys.argv[1:] == ["--test-worker"]:
    raise SystemExit(_worker_main())
