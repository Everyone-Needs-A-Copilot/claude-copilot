"""Non-authorizing fake-upstream proof for a constrained Codex ChatGPT broker."""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from cc.core.evaluation.codex_isolation import (
    CodexLiveDispatch,
    CodexLiveDispatchContext,
    verify_codex_live_dispatch,
    verify_codex_live_dispatch_context,
)
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256

BROKER_TEST_RECEIPT_SCHEMA_VERSION = "task285-codex-broker-test-receipt-v1"
CHATGPT_RESPONSES_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"

_AUTH_FILE = Path.home() / ".codex" / "auth.json"
_AUTH_FIELDS = frozenset({"OPENAI_API_KEY", "last_refresh", "tokens"})
_TOKEN_FIELDS = frozenset({"access_token", "account_id", "id_token", "refresh_token"})
_ACCOUNT_CLAIM = "https://api.openai.com/auth.chatgpt_account_id"
_WORKSPACE_CLAIM = "https://api.openai.com/auth.chatgpt_workspace_id"
_FEDRAMP_CLAIM = "https://api.openai.com/auth.fedramp"
_MAX_AUTH_BYTES = 128 * 1024
_MAX_HEADER_BYTES = 32 * 1024
_MAX_HEADER_LINE_BYTES = 4096
_MAX_HEADER_COUNT = 32
_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_SSE_BYTES = 4 * 1024 * 1024
_MAX_SSE_LINE_BYTES = 64 * 1024
_MAX_SSE_EVENTS = 256
_MAX_JSON_DEPTH = 32
_TOTAL_TIMEOUT_SECONDS = 20.0
_IDLE_TIMEOUT_SECONDS = 2.0
_QUIET_SECONDS = 0.075
_MINIMUM_TOKEN_LIFETIME_SECONDS = 300
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_MESSAGE_ID = re.compile(
    r"^msg_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_TURN_STATE = re.compile(r"^[A-Za-z0-9._~+/=-]{1,4096}$", re.ASCII)
_EXPECTED_REQUEST_FIELDS = frozenset(
    {
        "client_metadata",
        "include",
        "input",
        "instructions",
        "model",
        "parallel_tool_calls",
        "prompt_cache_key",
        "reasoning",
        "store",
        "stream",
        "text",
        "tool_choice",
        "tools",
    }
)
_CLIENT_METADATA_FIELDS = frozenset(
    {
        "session_id",
        "thread_id",
        "turn_id",
        "x-codex-installation-id",
        "x-codex-turn-metadata",
        "x-codex-window-id",
    }
)
_TURN_METADATA_FIELDS = frozenset(
    {
        "installation_id",
        "request_kind",
        "sandbox",
        "session_id",
        "thread_id",
        "thread_source",
        "turn_id",
        "turn_started_at_unix_ms",
        "window_id",
    }
)
_ALLOWED_INBOUND_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "content-length",
        "content-type",
        "host",
        "user-agent",
        "x-cc-broker-nonce",
    }
)
_PROHIBITED_INBOUND_HEADERS = frozenset(
    {
        "authorization",
        "chatgpt-account-id",
        "cookie",
        "expect",
        "forwarded",
        "proxy-authorization",
        "te",
        "transfer-encoding",
        "upgrade",
        "x-api-key",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-openai-fedramp",
    }
)
_PROHIBITED_RESPONSE_HEADERS = frozenset(
    {
        "proxy-authenticate",
        "set-cookie",
        "www-authenticate",
    }
)
_ALLOWED_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "content-type",
        "date",
        "server",
        "x-codex-turn-state",
    }
)
_WORKER_SHUTDOWN_SECONDS = _TOTAL_TIMEOUT_SECONDS + _IDLE_TIMEOUT_SECONDS + 2.0
_LOCK = threading.RLock()
_RECEIPT_AUTHORITY = object()
_FAKE_UPSTREAM_AUTHORITY = object()
_ISSUED_RECEIPTS: dict[int, "CodexBrokerTestReceipt"] = {}
_ISSUED_FAKE_UPSTREAMS: dict[int, "_FakeTLSUpstream"] = {}

_INBOUND_POLICY_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-codex-broker-inbound-policy-v1",
        "listener": "ipv4-loopback-only",
        "method": "POST",
        "path": "/v1/<NONCE>/responses",
        "allowed_headers": sorted(_ALLOWED_INBOUND_HEADERS),
        "prohibited_headers": sorted(_PROHIBITED_INBOUND_HEADERS),
        "maximum_header_bytes": _MAX_HEADER_BYTES,
        "maximum_header_line_bytes": _MAX_HEADER_LINE_BYTES,
        "maximum_header_count": _MAX_HEADER_COUNT,
        "maximum_request_bytes": _MAX_REQUEST_BYTES,
        "interaction_count": 1,
    }
)
_BODY_POLICY_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-codex-broker-body-policy-v1",
        "fields": sorted(_EXPECTED_REQUEST_FIELDS),
        "store": False,
        "stream": True,
        "tools": [],
        "maximum_json_depth": _MAX_JSON_DEPTH,
        "duplicate_keys": "rejected-recursively",
        "client_metadata_fields": sorted(_CLIENT_METADATA_FIELDS),
        "turn_metadata_fields": sorted(_TURN_METADATA_FIELDS),
        "input_roles": ["developer", "user", "user"],
        "identifier_format": "lowercase-uuid",
        "input_item_schema": {
            "fields": ["content", "id", "role", "type"],
            "type": "message",
            "content_fields": ["text", "type"],
            "content_type": "input_text",
        },
        "forwarding": "exact-verified-raw-bytes",
    }
)
_TLS_POLICY_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-codex-broker-fake-tls-policy-v1",
        "production_endpoint": CHATGPT_RESPONSES_ENDPOINT,
        "fake_connect_host": "127.0.0.1",
        "server_name": "chatgpt.com",
        "minimum_tls": "1.2",
        "redirects": False,
        "retries": 0,
        "proxy": False,
    }
)
_SSE_POLICY_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-codex-broker-sse-policy-v1",
        "content_type": "text/event-stream",
        "maximum_bytes": _MAX_SSE_BYTES,
        "maximum_line_bytes": _MAX_SSE_LINE_BYTES,
        "maximum_events": _MAX_SSE_EVENTS,
        "created": 1,
        "completed": 1,
        "allowed_middle_events": ["response.output_text.delta"],
        "tool_events": "rejected-before-child-delivery",
    }
)
BROKER_TEST_POLICY_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-codex-broker-test-policy-v1",
        "authorization_scope": "fake-upstream-test-only",
        "live_runtime_authorized": False,
        "inbound_policy_sha256": _INBOUND_POLICY_SHA256,
        "body_policy_sha256": _BODY_POLICY_SHA256,
        "tls_policy_sha256": _TLS_POLICY_SHA256,
        "sse_policy_sha256": _SSE_POLICY_SHA256,
    }
)


class CodexBrokerUnavailable(ValueError):
    """The nonauthorizing broker proof failed closed."""


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise CodexBrokerUnavailable(f"{field_name} is not a SHA-256 digest.")
    return value


def _require_turn_state(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not _TURN_STATE.fullmatch(value)
    ):
        raise CodexBrokerUnavailable("Upstream turn state differs.")
    return value


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid)


def _zero(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CodexBrokerUnavailable("Broker JSON contains duplicate keys.")
        result[key] = value
    return result


def _json_depth(value: object, depth: int = 0) -> int:
    if depth > _MAX_JSON_DEPTH:
        raise CodexBrokerUnavailable("Broker JSON nesting exceeds its closed limit.")
    if isinstance(value, dict):
        return max(
            (_json_depth(item, depth + 1) for item in value.values()), default=depth
        )
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value), default=depth)
    return depth


def _closed_json(raw: bytes, *, canonical: bool) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexBrokerUnavailable("Broker JSON is malformed.") from exc
    if not isinstance(value, dict):
        raise CodexBrokerUnavailable("Broker JSON must be an object.")
    _json_depth(value)
    if canonical and canonical_json_bytes(value) != raw:
        raise CodexBrokerUnavailable("Broker JSON is not canonical.")
    return value


def _decode_jwt_claims(token: str, *, description: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        raise CodexBrokerUnavailable(f"{description} is not a closed JWT.")
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise CodexBrokerUnavailable(f"{description} payload is malformed.") from exc
    return _closed_json(raw, canonical=False)


class _RetainedDirectoryChain:
    def __init__(
        self,
        path: Path,
        *,
        private_tail: int,
    ) -> None:
        self.path = Path(path)
        self.private_tail = private_tail
        self.entries: list[tuple[str, int, tuple[int, ...]]] = []
        self.closed = False
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if (
            no_follow is None
            or directory is None
            or not self.path.is_absolute()
            or self.path != self.path.resolve(strict=True)
            or private_tail < 1
        ):
            raise CodexBrokerUnavailable("Retained directory path is not canonical.")
        flags = os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0)
        descriptor = -1
        try:
            descriptor = os.open("/", flags)
            opened = os.fstat(descriptor)
            self.entries.append(("/", descriptor, _directory_identity(opened)))
            descriptor = -1
            for name in self.path.parts[1:]:
                parent_fd = self.entries[-1][1]
                descriptor = os.open(name, flags, dir_fd=parent_fd)
                opened = os.fstat(descriptor)
                named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if not stat.S_ISDIR(opened.st_mode) or _directory_identity(
                    opened
                ) != _directory_identity(named):
                    raise CodexBrokerUnavailable("Retained directory link differs.")
                self.entries.append((name, descriptor, _directory_identity(opened)))
                descriptor = -1
            if not self.validate():
                raise CodexBrokerUnavailable("Retained directory changed during open.")
        except CodexBrokerUnavailable:
            if descriptor >= 0:
                os.close(descriptor)
            self.close()
            raise
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            self.close()
            raise CodexBrokerUnavailable(
                "Directory cannot be retained safely."
            ) from exc

    @property
    def fd(self) -> int:
        return self.entries[-1][1] if self.entries else -1

    @property
    def identity(self) -> tuple[int, ...]:
        return self.entries[-1][2]

    def validate(self) -> bool:
        if self.closed or len(self.entries) <= self.private_tail:
            return False
        try:
            for index, (name, descriptor, identity) in enumerate(self.entries):
                current = os.fstat(descriptor)
                if _directory_identity(current) != identity:
                    return False
                if index:
                    named = os.stat(
                        name,
                        dir_fd=self.entries[index - 1][1],
                        follow_symlinks=False,
                    )
                    if _directory_identity(named) != identity:
                        return False
            for _name, descriptor, _identity_value in self.entries[
                -self.private_tail :
            ]:
                current = os.fstat(descriptor)
                if (
                    current.st_uid != os.geteuid()
                    or stat.S_IMODE(current.st_mode) != 0o700
                ):
                    return False
            return True
        except OSError:
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for _name, descriptor, _identity_value in reversed(self.entries):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.entries.clear()


class _RetainedAuthSnapshot:
    def __init__(self, path: Path, *, now: int) -> None:
        self.path = Path(path)
        self.chain: _RetainedDirectoryChain | None = None
        self.fd = -1
        self.closed = False
        self.raw = bytearray()
        self.access_token = bytearray()
        self.account_id = bytearray()
        self.workspace_id = bytearray()
        self.id_token = bytearray()
        self.refresh_token = bytearray()
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None or self.path.name != "auth.json":
            raise CodexBrokerUnavailable("Canonical Codex auth path differs.")
        try:
            self.chain = _RetainedDirectoryChain(self.path.parent, private_tail=2)
            self.fd = os.open(
                self.path.name,
                os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
                dir_fd=self.chain.fd,
            )
            opened = os.fstat(self.fd)
            named = os.stat(
                self.path.name,
                dir_fd=self.chain.fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(opened.st_mode)
                or _identity(opened) != _identity(named)
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_size < 2
                or opened.st_size > _MAX_AUTH_BYTES
            ):
                raise CodexBrokerUnavailable("Codex auth file is not private/exact.")
            self.file_identity = _identity(opened)
            self.raw = self._read()
            document = _closed_json(bytes(self.raw), canonical=False)
            if (
                set(document) != _AUTH_FIELDS
                or document.get("OPENAI_API_KEY") is not None
            ):
                raise CodexBrokerUnavailable(
                    "Codex auth mode is not exact ChatGPT auth."
                )
            if not isinstance(document.get("last_refresh"), str):
                raise CodexBrokerUnavailable("Codex auth refresh identity is absent.")
            tokens = document.get("tokens")
            if not isinstance(tokens, dict) or set(tokens) != _TOKEN_FIELDS:
                raise CodexBrokerUnavailable("Codex ChatGPT token shape differs.")
            for name in _TOKEN_FIELDS:
                value = tokens.get(name)
                if (
                    not isinstance(value, str)
                    or not value
                    or len(value.encode()) > 16 * 1024
                ):
                    raise CodexBrokerUnavailable(
                        "Codex ChatGPT token value is unavailable."
                    )
            self.access_token = bytearray(tokens["access_token"].encode())
            self.account_id = bytearray(tokens["account_id"].encode())
            self.id_token = bytearray(tokens["id_token"].encode())
            self.refresh_token = bytearray(tokens["refresh_token"].encode())
            access_claims = _decode_jwt_claims(
                tokens["access_token"], description="access token"
            )
            id_claims = _decode_jwt_claims(tokens["id_token"], description="ID token")
            account = tokens["account_id"]
            access_workspace = access_claims.get(_WORKSPACE_CLAIM)
            id_workspace = id_claims.get(_WORKSPACE_CLAIM)
            expiry = access_claims.get("exp")
            if (
                not isinstance(expiry, int)
                or isinstance(expiry, bool)
                or expiry - now < _MINIMUM_TOKEN_LIFETIME_SECONDS
                or access_claims.get(_ACCOUNT_CLAIM) != account
                or id_claims.get(_ACCOUNT_CLAIM) != account
                or not isinstance(access_workspace, str)
                or not access_workspace
                or id_workspace != access_workspace
                or access_claims.get(_FEDRAMP_CLAIM, False) is not False
                or id_claims.get(_FEDRAMP_CLAIM, False) is not False
            ):
                raise CodexBrokerUnavailable("ChatGPT auth refresh is required.")
            self.workspace_id = bytearray(access_workspace.encode())
            self.expires_at = expiry
            if not self.validate(now=now):
                raise CodexBrokerUnavailable("Codex auth changed during retention.")
        except CodexBrokerUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise CodexBrokerUnavailable(
                "Codex auth cannot be retained safely."
            ) from exc

    def _read(self) -> bytearray:
        before = os.fstat(self.fd)
        if before.st_size < 2 or before.st_size > _MAX_AUTH_BYTES:
            raise CodexBrokerUnavailable("Codex auth size differs.")
        os.lseek(self.fd, 0, os.SEEK_SET)
        raw = bytearray()
        remaining = before.st_size
        while remaining:
            chunk = os.read(self.fd, min(65536, remaining))
            if not chunk:
                _zero(raw)
                raise CodexBrokerUnavailable("Codex auth read was incomplete.")
            raw.extend(chunk)
            remaining -= len(chunk)
        if _identity(os.fstat(self.fd)) != _identity(before):
            _zero(raw)
            raise CodexBrokerUnavailable("Codex auth changed while reading.")
        return raw

    def validate(self, *, now: int) -> bool:
        if (
            self.closed
            or self.chain is None
            or self.expires_at - now < _MINIMUM_TOKEN_LIFETIME_SECONDS
        ):
            return False
        current = bytearray()
        try:
            named = os.stat(
                self.path.name,
                dir_fd=self.chain.fd,
                follow_symlinks=False,
            )
            if (
                not self.chain.validate()
                or _identity(os.fstat(self.fd)) != self.file_identity
                or _identity(named) != self.file_identity
            ):
                return False
            current = self._read()
            return hmac.compare_digest(current, self.raw)
        except (OSError, CodexBrokerUnavailable):
            return False
        finally:
            _zero(current)

    def authorization_header(self) -> str:
        if self.closed:
            raise CodexBrokerUnavailable("Codex auth is closed.")
        return "Bearer " + self.access_token.decode("utf-8")

    def account_header(self) -> str:
        if self.closed:
            raise CodexBrokerUnavailable("Codex auth is closed.")
        return self.account_id.decode("utf-8")

    def commitment(self, key: bytes) -> str:
        return hmac.new(key, self.raw, hashlib.sha256).hexdigest()

    def account_commitment(self, key: bytes) -> str:
        return hmac.new(key, self.account_id, hashlib.sha256).hexdigest()

    def workspace_commitment(self, key: bytes) -> str:
        return hmac.new(key, self.workspace_id, hashlib.sha256).hexdigest()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for value in (
            self.raw,
            self.access_token,
            self.account_id,
            self.workspace_id,
            self.id_token,
            self.refresh_token,
        ):
            _zero(value)
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        if self.chain is not None:
            self.chain.close()
            self.chain = None


@dataclass
class _ExpectedRequest:
    raw: bytearray
    cell_sha256: str
    prompt_sha256: str
    content_sha256: str
    runtime_sha256: str
    model: str
    closed: bool = False

    def __post_init__(self) -> None:
        for name in (
            "cell_sha256",
            "prompt_sha256",
            "content_sha256",
            "runtime_sha256",
        ):
            _require_digest(getattr(self, name), name)
        if not self.raw or len(self.raw) > _MAX_REQUEST_BYTES:
            raise CodexBrokerUnavailable("Expected request bytes differ.")
        _verify_request_body(bytes(self.raw), expected_model=self.model)

    @property
    def sha256(self) -> str:
        if self.closed:
            raise CodexBrokerUnavailable("Expected request is closed.")
        return hashlib.sha256(self.raw).hexdigest()

    def matches(self, raw: bytes) -> bool:
        return not self.closed and hmac.compare_digest(raw, self.raw)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        _zero(self.raw)


def _contains_prohibited_model_input(value: object, *, root: bool = True) -> bool:
    if isinstance(value, dict):
        kind = value.get("type")
        if isinstance(kind, str) and (
            "tool" in kind or "function" in kind or "computer" in kind
        ):
            return True
        if not root and "tools" in value:
            return True
        for key, item in value.items():
            lowered = key.lower()
            if lowered in {
                "additional_tools",
                "attachments",
                "file_id",
                "image_url",
                "previous_response_id",
                "url",
            }:
                return True
            if _contains_prohibited_model_input(item, root=False):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_prohibited_model_input(item, root=False) for item in value)
    return False


def _verify_request_body(raw: bytes, *, expected_model: str) -> dict[str, Any]:
    if len(raw) > _MAX_REQUEST_BYTES:
        raise CodexBrokerUnavailable("Codex request exceeds its closed limit.")
    body = _closed_json(raw, canonical=False)
    client_metadata = body.get("client_metadata")
    inputs = body.get("input")
    if (
        set(body) != _EXPECTED_REQUEST_FIELDS
        or body.get("model") != expected_model
        or body.get("tools") != []
        or body.get("tool_choice") != "auto"
        or body.get("parallel_tool_calls") is not True
        or body.get("stream") is not True
        or body.get("store") is not False
        or body.get("include") != ["reasoning.encrypted_content"]
        or body.get("reasoning") != {"effort": "low"}
        or body.get("text") != {"verbosity": "low"}
        or not isinstance(body.get("instructions"), str)
        or not body["instructions"]
        or not isinstance(client_metadata, dict)
        or set(client_metadata) != _CLIENT_METADATA_FIELDS
        or not isinstance(inputs, list)
        or len(inputs) != 3
    ):
        raise CodexBrokerUnavailable(
            "Codex request body differs from the tool-free contract."
        )

    identifiers = {
        name: client_metadata.get(name)
        for name in (
            "session_id",
            "thread_id",
            "turn_id",
            "x-codex-installation-id",
            "x-codex-window-id",
        )
    }
    if (
        any(not isinstance(value, str) or not value for value in identifiers.values())
        or any(
            not _UUID.fullmatch(identifiers[name])
            for name in (
                "session_id",
                "thread_id",
                "turn_id",
                "x-codex-installation-id",
            )
        )
        or identifiers["session_id"] != identifiers["thread_id"]
        or identifiers["x-codex-window-id"] != f'{identifiers["thread_id"]}:0'
        or body.get("prompt_cache_key") != identifiers["thread_id"]
        or not isinstance(client_metadata.get("x-codex-turn-metadata"), str)
    ):
        raise CodexBrokerUnavailable("Codex client metadata differs.")
    turn_metadata_raw = client_metadata["x-codex-turn-metadata"].encode("utf-8")
    turn_metadata = _closed_json(turn_metadata_raw, canonical=False)
    started = turn_metadata.get("turn_started_at_unix_ms")
    if (
        set(turn_metadata) != _TURN_METADATA_FIELDS
        or turn_metadata.get("installation_id")
        != identifiers["x-codex-installation-id"]
        or turn_metadata.get("session_id") != identifiers["session_id"]
        or turn_metadata.get("thread_id") != identifiers["thread_id"]
        or turn_metadata.get("turn_id") != identifiers["turn_id"]
        or turn_metadata.get("window_id") != identifiers["x-codex-window-id"]
        or turn_metadata.get("request_kind") != "turn"
        or turn_metadata.get("thread_source") != "user"
        or turn_metadata.get("sandbox") != "seatbelt"
        or not isinstance(started, int)
        or isinstance(started, bool)
        or started < 0
    ):
        raise CodexBrokerUnavailable("Codex turn metadata differs.")

    expected_roles = ("developer", "user", "user")
    for index, (item, expected_role) in enumerate(zip(inputs, expected_roles)):
        if (
            not isinstance(item, dict)
            or set(item) != {"content", "id", "role", "type"}
            or item.get("type") != "message"
            or item.get("role") != expected_role
            or not isinstance(item.get("id"), str)
            or not _MESSAGE_ID.fullmatch(item["id"])
            or not isinstance(item.get("content"), list)
            or not item["content"]
        ):
            raise CodexBrokerUnavailable(
                f"Codex input message {index} differs from its closed schema."
            )
        for content in item["content"]:
            if (
                not isinstance(content, dict)
                or set(content) != {"text", "type"}
                or content.get("type") != "input_text"
                or not isinstance(content.get("text"), str)
                or not content["text"]
            ):
                raise CodexBrokerUnavailable(
                    f"Codex input message {index} content differs."
                )
    return body


@dataclass(frozen=True)
class _FakeTLSUpstream:
    connect_host: str
    port: int
    certificate_sha256: str
    _certificate: _RetainedCertificate = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def validate(self) -> bool:
        return bool(
            _ISSUED_FAKE_UPSTREAMS.get(id(self)) is self
            and self._authority is _FAKE_UPSTREAM_AUTHORITY
            and self._seal is not None
            and self.connect_host == "127.0.0.1"
            and 0 < self.port < 65536
            and _DIGEST.fullmatch(self.certificate_sha256)
            and self._certificate.validate()
            and self.certificate_sha256 == self._certificate.der_sha256
        )

    def close(self) -> None:
        with _LOCK:
            if _ISSUED_FAKE_UPSTREAMS.get(id(self)) is self:
                _ISSUED_FAKE_UPSTREAMS.pop(id(self), None)
                self._certificate.close()


class _RetainedCertificate:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.chain = _RetainedDirectoryChain(self.path.parent, private_tail=1)
        self.fd = -1
        self.closed = False
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            self.chain.close()
            raise CodexBrokerUnavailable("Platform lacks no-follow protections.")
        try:
            self.fd = os.open(
                self.path.name,
                os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
                dir_fd=self.chain.fd,
            )
            opened = os.fstat(self.fd)
            named = os.stat(
                self.path.name,
                dir_fd=self.chain.fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(opened.st_mode)
                or _identity(opened) != _identity(named)
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_size < 64
                or opened.st_size > 128 * 1024
            ):
                raise CodexBrokerUnavailable("Fake TLS certificate is not exact.")
            self.file_identity = _identity(opened)
            os.lseek(self.fd, 0, os.SEEK_SET)
            self.pem = os.read(self.fd, opened.st_size)
            if len(self.pem) != opened.st_size:
                raise CodexBrokerUnavailable(
                    "Fake TLS certificate read was incomplete."
                )
            try:
                der = ssl.PEM_cert_to_DER_cert(self.pem.decode("ascii"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise CodexBrokerUnavailable(
                    "Fake TLS certificate is malformed."
                ) from exc
            self.der_sha256 = hashlib.sha256(der).hexdigest()
            if not self.validate():
                raise CodexBrokerUnavailable(
                    "Fake TLS certificate changed during open."
                )
        except CodexBrokerUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise CodexBrokerUnavailable(
                "Fake TLS certificate cannot be retained."
            ) from exc

    def validate(self) -> bool:
        if self.closed or self.fd < 0 or not self.chain.validate():
            return False
        try:
            opened = os.fstat(self.fd)
            named = os.stat(
                self.path.name,
                dir_fd=self.chain.fd,
                follow_symlinks=False,
            )
            os.lseek(self.fd, 0, os.SEEK_SET)
            return bool(
                _identity(opened) == self.file_identity
                and _identity(named) == self.file_identity
                and os.read(self.fd, len(self.pem) + 1) == self.pem
            )
        except OSError:
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        self.chain.close()


def _issue_fake_tls_upstream(
    *,
    connect_host: str,
    port: int,
    ca_file: Path,
) -> _FakeTLSUpstream:
    """Test-only authority. It is intentionally absent from ``__all__``."""

    if (
        connect_host != "127.0.0.1"
        or not isinstance(port, int)
        or isinstance(port, bool)
        or not 0 < port < 65536
        or not isinstance(ca_file, Path)
        or not ca_file.is_absolute()
    ):
        raise CodexBrokerUnavailable("Fake TLS upstream identity differs.")
    certificate: _RetainedCertificate | None = None
    try:
        certificate = _RetainedCertificate(ca_file)
        seal = object()
        result = _FakeTLSUpstream(
            connect_host,
            port,
            certificate.der_sha256,
            certificate,
            seal,
            _FAKE_UPSTREAM_AUTHORITY,
        )
        with _LOCK:
            _ISSUED_FAKE_UPSTREAMS[id(result)] = result
        certificate = None
        return result
    finally:
        if certificate is not None:
            certificate.close()


@dataclass(frozen=True)
class _UpstreamResponse:
    status: int
    content_type: str
    turn_state: str
    body: bytes = field(repr=False)
    semantic_sha256: str
    event_count: int


def _parse_sse(raw: bytes) -> tuple[str, int]:
    if not raw or len(raw) > _MAX_SSE_BYTES or not raw.endswith(b"\n\n"):
        raise CodexBrokerUnavailable("Upstream SSE framing differs.")
    events: list[dict[str, Any]] = []
    event_names: list[str] = []
    for block in raw.split(b"\n\n")[:-1]:
        lines = block.split(b"\n")
        if (
            len(lines) != 2
            or any(not line or len(line) > _MAX_SSE_LINE_BYTES for line in lines)
            or not lines[0].startswith(b"event: ")
            or not lines[1].startswith(b"data: ")
        ):
            raise CodexBrokerUnavailable("Upstream SSE event framing differs.")
        try:
            event_name = lines[0][7:].decode("ascii")
        except UnicodeDecodeError as exc:
            raise CodexBrokerUnavailable("Upstream SSE event name differs.") from exc
        data = _closed_json(lines[1][6:], canonical=True)
        if data.get("type") != event_name:
            raise CodexBrokerUnavailable("Upstream SSE type differs from its frame.")
        if _contains_prohibited_model_input(data):
            raise CodexBrokerUnavailable("Upstream SSE contains a tool event.")
        event_names.append(event_name)
        events.append(data)
        if len(events) > _MAX_SSE_EVENTS:
            raise CodexBrokerUnavailable("Upstream SSE event count exceeds its limit.")
    if (
        len(events) < 2
        or event_names[0] != "response.created"
        or event_names[-1] != "response.completed"
        or event_names.count("response.created") != 1
        or event_names.count("response.completed") != 1
    ):
        raise CodexBrokerUnavailable("Upstream SSE terminal lineage differs.")
    created = events[0]
    completed = events[-1]
    if (
        set(created) != {"type", "response"}
        or not isinstance(created.get("response"), dict)
        or set(created["response"]) != {"id", "status"}
        or created["response"].get("status") != "in_progress"
        or not isinstance(created["response"].get("id"), str)
        or set(completed) != {"type", "response"}
        or not isinstance(completed.get("response"), dict)
        or set(completed["response"]) != {"id", "status", "output"}
        or completed["response"].get("id") != created["response"].get("id")
        or completed["response"].get("status") != "completed"
        or completed["response"].get("output") != []
    ):
        raise CodexBrokerUnavailable("Upstream SSE response lineage differs.")
    allowed_middle = {"response.output_text.delta"}
    if any(name not in allowed_middle for name in event_names[1:-1]):
        raise CodexBrokerUnavailable("Upstream SSE event kind is not closed.")
    for item in events[1:-1]:
        if (
            set(item) != {"type", "response_id", "delta"}
            or item.get("response_id") != created["response"].get("id")
            or not isinstance(item.get("delta"), str)
        ):
            raise CodexBrokerUnavailable("Upstream SSE delta differs.")
    return canonical_sha256(events), len(events)


def _fake_tls_request(
    upstream: _FakeTLSUpstream,
    auth: _RetainedAuthSnapshot,
    body: bytes,
    *,
    now: int,
    owner: _BrokerServerState,
) -> _UpstreamResponse:
    if not upstream.validate() or not auth.validate(now=now):
        raise CodexBrokerUnavailable("Fake upstream or retained auth is unavailable.")
    context = ssl.create_default_context(
        cadata=upstream._certificate.pem.decode("ascii")
    )
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    connection: http.client.HTTPConnection | None = None
    try:
        raw_socket = socket.create_connection(
            (upstream.connect_host, upstream.port),
            timeout=_TOTAL_TIMEOUT_SECONDS,
        )
        owner.retain_upstream_socket(raw_socket)
        tls_socket = context.wrap_socket(raw_socket, server_hostname="chatgpt.com")
        owner.replace_upstream_socket(raw_socket, tls_socket)
        raw_socket = None
        peer = tls_socket.getpeercert(binary_form=True)
        if hashlib.sha256(peer).hexdigest() != upstream.certificate_sha256:
            raise CodexBrokerUnavailable("Fake TLS peer certificate differs.")
        connection = http.client.HTTPConnection(
            "chatgpt.com", 443, timeout=_IDLE_TIMEOUT_SECONDS
        )
        connection.sock = tls_socket
        connection.putrequest(
            "POST",
            "/backend-api/codex/responses",
            skip_host=True,
            skip_accept_encoding=True,
        )
        connection.putheader("Accept", "text/event-stream")
        connection.putheader("Authorization", auth.authorization_header())
        connection.putheader("ChatGPT-Account-ID", auth.account_header())
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(len(body)))
        connection.putheader("Host", "chatgpt.com")
        connection.endheaders(body)
        response = connection.getresponse()
        headers: dict[str, str] = {}
        for name, value in response.getheaders():
            lowered = name.lower()
            if lowered in headers:
                raise CodexBrokerUnavailable("Upstream response repeats a header.")
            headers[lowered] = value
        if any(name in headers for name in _PROHIBITED_RESPONSE_HEADERS) or not set(
            headers
        ).issubset(_ALLOWED_RESPONSE_HEADERS):
            raise CodexBrokerUnavailable(
                "Upstream response contains a prohibited header."
            )
        content_type = headers.get("content-type", "")
        turn_state = _require_turn_state(headers.get("x-codex-turn-state"))
        if response.status != 200 or content_type != "text/event-stream":
            raise CodexBrokerUnavailable("Upstream response contract differs.")
        response_body = response.read(_MAX_SSE_BYTES + 1)
        semantic_sha256, event_count = _parse_sse(response_body)
        if not auth.validate(now=int(time.time())):
            raise CodexBrokerUnavailable("Codex auth changed during fake egress.")
        return _UpstreamResponse(
            response.status,
            content_type,
            turn_state,
            response_body,
            semantic_sha256,
            event_count,
        )
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise CodexBrokerUnavailable("Fake TLS upstream failed closed.") from exc
    finally:
        if connection is not None:
            connection.close()
        elif tls_socket is not None:
            tls_socket.close()
        if raw_socket is not None:
            raw_socket.close()
        owner.release_upstream_socket(tls_socket or raw_socket)


class _AttemptJournal:
    def __init__(self, root: Path, identity: Mapping[str, object]) -> None:
        self.root = Path(root)
        self.chain = _RetainedDirectoryChain(self.root, private_tail=1)
        self.fd = -1
        self.started_fd = -1
        self.closed = False
        self.started = False
        self.identity = dict(identity)
        if os.listdir(self.chain.fd):
            self.chain.close()
            raise CodexBrokerUnavailable("Broker journal root is not empty.")
        self.before = canonical_json_bytes(
            {
                "schema_version": "task285-codex-broker-egress-intent-v1",
                **self.identity,
                "call_started": 0,
            }
        )
        self.started_raw = canonical_json_bytes(
            {
                "schema_version": "task285-codex-broker-call-started-v1",
                **self.identity,
                "call_started": 1,
            }
        )
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            self.chain.close()
            raise CodexBrokerUnavailable("Platform lacks no-follow protections.")
        try:
            self.fd = os.open(
                "egress-intent.json",
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | no_follow
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=self.chain.fd,
            )
            self._rewrite(self.before)
            self.file_identity = _identity(os.fstat(self.fd))
            os.fsync(self.chain.fd)
            if not self.validate():
                raise CodexBrokerUnavailable("Broker journal changed during creation.")
        except CodexBrokerUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise CodexBrokerUnavailable(
                "Broker journal cannot be created safely."
            ) from exc

    def _rewrite(self, raw: bytes) -> None:
        os.lseek(self.fd, 0, os.SEEK_SET)
        offset = 0
        while offset < len(raw):
            written = os.write(self.fd, raw[offset:])
            if written < 1:
                raise CodexBrokerUnavailable("Broker journal write made no progress.")
            offset += written
        os.ftruncate(self.fd, len(raw))
        os.fchmod(self.fd, 0o600)
        os.fsync(self.fd)

    def mark_started(self) -> None:
        if self.started or not self.validate():
            raise CodexBrokerUnavailable("Broker egress was already attempted.")
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise CodexBrokerUnavailable("Platform lacks no-follow protections.")
        try:
            self.started_fd = os.open(
                "call-started.json",
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | no_follow
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=self.chain.fd,
            )
            offset = 0
            while offset < len(self.started_raw):
                written = os.write(self.started_fd, self.started_raw[offset:])
                if written < 1:
                    raise CodexBrokerUnavailable(
                        "Broker call marker write made no progress."
                    )
                offset += written
            os.fchmod(self.started_fd, 0o600)
            os.fsync(self.started_fd)
            self.started_identity = _identity(os.fstat(self.started_fd))
            os.fsync(self.chain.fd)
            self.started = True
            if not self.validate():
                raise CodexBrokerUnavailable("Broker egress journal update differs.")
        except CodexBrokerUnavailable:
            raise
        except OSError as exc:
            raise CodexBrokerUnavailable(
                "Broker call marker cannot be created safely."
            ) from exc

    def validate(self) -> bool:
        if self.closed or not self.chain.validate() or self.fd < 0:
            return False
        try:
            named = os.stat(
                "egress-intent.json",
                dir_fd=self.chain.fd,
                follow_symlinks=False,
            )
            opened = os.fstat(self.fd)
            if (
                _identity(opened) != self.file_identity
                or _identity(named) != self.file_identity
            ):
                return False
            os.lseek(self.fd, 0, os.SEEK_SET)
            if os.read(self.fd, len(self.before) + 1) != self.before:
                return False
            expected_entries = (
                ("call-started.json", "egress-intent.json")
                if self.started
                else ("egress-intent.json",)
            )
            if tuple(sorted(os.listdir(self.chain.fd))) != expected_entries:
                return False
            if not self.started:
                return self.started_fd < 0
            opened_started = os.fstat(self.started_fd)
            named_started = os.stat(
                "call-started.json",
                dir_fd=self.chain.fd,
                follow_symlinks=False,
            )
            os.lseek(self.started_fd, 0, os.SEEK_SET)
            return bool(
                _identity(opened_started) == self.started_identity
                and _identity(named_started) == self.started_identity
                and os.read(self.started_fd, len(self.started_raw) + 1)
                == self.started_raw
            )
        except OSError:
            return False

    @property
    def sha256(self) -> str:
        return canonical_sha256(
            {
                "schema_version": "task285-codex-broker-journal-v1",
                "intent_sha256": hashlib.sha256(self.before).hexdigest(),
                "call_started_sha256": (
                    hashlib.sha256(self.started_raw).hexdigest()
                    if self.started
                    else None
                ),
            }
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for name in ("started_fd", "fd"):
            descriptor = getattr(self, name)
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, name, -1)
        self.chain.close()


@dataclass
class _BrokerServerState:
    listener: socket.socket
    nonce: str
    expectation: _ExpectedRequest
    auth: _RetainedAuthSnapshot
    upstream: _FakeTLSUpstream
    journal: _AttemptJournal
    now: int
    hmac_key: bytearray
    interactions: int = 0
    poisoned: bool = False
    error: str | None = None
    request_sha256: str | None = None
    request_bytes: int = 0
    response: _UpstreamResponse | None = None
    call_count: int = 0
    stopped: bool = False
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    worker_terminated: threading.Event = field(default_factory=threading.Event)
    upstream_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    active_upstream_socket: socket.socket | None = field(default=None, repr=False)

    def retain_upstream_socket(self, value: socket.socket) -> None:
        with self.upstream_lock:
            if (
                self.cancel_requested.is_set()
                or self.active_upstream_socket is not None
            ):
                value.close()
                raise CodexBrokerUnavailable("Broker egress was cancelled.")
            self.active_upstream_socket = value

    def replace_upstream_socket(
        self,
        previous: socket.socket,
        replacement: socket.socket,
    ) -> None:
        with self.upstream_lock:
            if (
                self.cancel_requested.is_set()
                or self.active_upstream_socket is not previous
            ):
                replacement.close()
                raise CodexBrokerUnavailable("Broker egress was cancelled.")
            self.active_upstream_socket = replacement

    def release_upstream_socket(self, value: socket.socket | None) -> None:
        if value is None:
            return
        with self.upstream_lock:
            if self.active_upstream_socket is value:
                self.active_upstream_socket = None

    def cancel_upstream(self) -> None:
        self.cancel_requested.set()
        with self.upstream_lock:
            value = self.active_upstream_socket
        if value is None:
            return
        try:
            value.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            value.close()
        except OSError:
            pass


def _read_until(connection: socket.socket, marker: bytes, maximum: int) -> bytes:
    value = bytearray()
    while marker not in value:
        chunk = connection.recv(min(4096, maximum + 1 - len(value)))
        if not chunk:
            raise CodexBrokerUnavailable(
                "Child request ended before framing completed."
            )
        value.extend(chunk)
        if len(value) > maximum:
            raise CodexBrokerUnavailable("Child request framing exceeds its limit.")
    return bytes(value)


def _parse_child_request(
    connection: socket.socket,
    *,
    nonce: str,
    port: int,
) -> bytes:
    connection.settimeout(_IDLE_TIMEOUT_SECONDS)
    captured = _read_until(connection, b"\r\n\r\n", _MAX_HEADER_BYTES)
    head, remainder = captured.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    expected_target = f"/v1/{nonce}/responses".encode()
    if not lines or lines[0] != b"POST " + expected_target + b" HTTP/1.1":
        raise CodexBrokerUnavailable("Child request line differs.")
    if len(lines) - 1 > _MAX_HEADER_COUNT:
        raise CodexBrokerUnavailable("Child header count exceeds its limit.")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or len(line) > _MAX_HEADER_LINE_BYTES or b":" not in line:
            raise CodexBrokerUnavailable("Child header framing differs.")
        raw_name, raw_value = line.split(b":", 1)
        try:
            name = raw_name.decode("ascii").lower()
            value = raw_value.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise CodexBrokerUnavailable("Child header encoding differs.") from exc
        if (
            not _TOKEN_NAME.fullmatch(name)
            or name in headers
            or name in _PROHIBITED_INBOUND_HEADERS
            or name not in _ALLOWED_INBOUND_HEADERS
            or "\r" in value
            or "\n" in value
        ):
            raise CodexBrokerUnavailable("Child header set differs.")
        headers[name] = value
    length = headers.get("content-length", "")
    if (
        not {
            "host",
            "content-type",
            "content-length",
            "x-cc-broker-nonce",
        }.issubset(headers)
        or headers.get("host") != f"127.0.0.1:{port}"
        or headers.get("content-type") != "application/json"
        or headers.get("x-cc-broker-nonce") != nonce
        or not length.isdigit()
        or len(length) > 10
    ):
        raise CodexBrokerUnavailable("Child required headers differ.")
    declared = int(length)
    if declared < 2 or declared > _MAX_REQUEST_BYTES or len(remainder) > declared:
        raise CodexBrokerUnavailable("Child request body length differs.")
    body = bytearray(remainder)
    while len(body) < declared:
        chunk = connection.recv(min(65536, declared - len(body)))
        if not chunk:
            raise CodexBrokerUnavailable("Child request body was incomplete.")
        body.extend(chunk)
    connection.settimeout(0.01)
    try:
        extra = connection.recv(1)
    except (BlockingIOError, TimeoutError, socket.timeout):
        extra = b""
    if extra:
        raise CodexBrokerUnavailable("Child request contains pipelined bytes.")
    return bytes(body)


def _send_child_response(
    connection: socket.socket, response: _UpstreamResponse
) -> None:
    turn_state = _require_turn_state(response.turn_state)
    head = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/event-stream\r\n"
        f"Content-Length: {len(response.body)}\r\n"
        f"x-codex-turn-state: {turn_state}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    connection.sendall(head + response.body)


def _send_child_failure(connection: socket.socket) -> None:
    body = b'{"error":{"message":"broker request rejected"}}'
    response = (
        "HTTP/1.1 400 Bad Request\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        connection.sendall(response)
    except OSError:
        pass


def _serve_broker(state: _BrokerServerState) -> None:
    pending: socket.socket | None = None
    pending_body: bytes | None = None
    pending_at = 0.0
    state.listener.settimeout(0.025)
    try:
        while not state.stopped:
            if pending is not None and time.monotonic() - pending_at >= _QUIET_SECONDS:
                if state.poisoned or pending_body is None:
                    _send_child_failure(pending)
                else:
                    try:
                        if (
                            not state.expectation.matches(pending_body)
                            or not state.auth.validate(now=state.now)
                            or not state.journal.validate()
                        ):
                            raise CodexBrokerUnavailable(
                                "Child request identity changed."
                            )
                        _verify_request_body(
                            pending_body,
                            expected_model=state.expectation.model,
                        )
                        state.journal.mark_started()
                        state.call_count = 1
                        state.response = _fake_tls_request(
                            state.upstream,
                            state.auth,
                            pending_body,
                            now=state.now,
                            owner=state,
                        )
                        state.request_sha256 = hashlib.sha256(pending_body).hexdigest()
                        state.request_bytes = len(pending_body)
                        _send_child_response(pending, state.response)
                    except CodexBrokerUnavailable as exc:
                        state.poisoned = True
                        state.error = str(exc)
                        _send_child_failure(pending)
                pending.close()
                pending = None
                pending_body = None
            try:
                connection, _address = state.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if state.stopped:
                    break
                state.poisoned = True
                state.error = "Listener failed before shutdown."
                break
            state.interactions += 1
            if (
                state.interactions != 1
                or pending is not None
                or state.response is not None
            ):
                state.poisoned = True
                state.error = "Child made more than one broker interaction."
                _send_child_failure(connection)
                connection.close()
                continue
            try:
                body = _parse_child_request(
                    connection,
                    nonce=state.nonce,
                    port=state.listener.getsockname()[1],
                )
                if not state.expectation.matches(body):
                    raise CodexBrokerUnavailable(
                        "Child request body substitution detected."
                    )
                _verify_request_body(body, expected_model=state.expectation.model)
                pending = connection
                pending_body = body
                pending_at = time.monotonic()
            except CodexBrokerUnavailable as exc:
                state.poisoned = True
                state.error = str(exc)
                _send_child_failure(connection)
                connection.close()
    finally:
        if pending is not None:
            _send_child_failure(pending)
            pending.close()
        state.worker_terminated.set()


def _stop_broker_worker(
    state: _BrokerServerState,
    listener: socket.socket,
    worker: threading.Thread,
) -> bool:
    """Cancel exact egress and retain all authorities until the worker exits."""

    state.stopped = True
    state.cancel_upstream()
    try:
        listener.close()
    except OSError:
        pass
    deadline = time.monotonic() + _WORKER_SHUTDOWN_SECONDS
    while worker.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            state.poisoned = True
            state.error = "Broker worker exceeded its shutdown deadline."
            break
        worker.join(timeout=min(0.1, remaining))
    within_deadline = not worker.is_alive()
    if not within_deadline:
        # Every real egress phase owns a bounded socket and cancellation closes that
        # exact socket. This final wait is a fail-safe: retained credential, journal,
        # and TLS authorities must never close underneath a still-running worker.
        worker.join()
    return bool(
        within_deadline
        and not worker.is_alive()
        and state.worker_terminated.is_set()
        and state.active_upstream_socket is None
    )


@dataclass
class _ReceiptState:
    journal: _AttemptJournal
    seal: object
    closed: bool = False


@dataclass(frozen=True)
class CodexBrokerTestReceipt:
    """Sealed fake-upstream evidence that can never authorize a live runtime."""

    schema_version: str
    receipt_sha256: str
    authorization_scope: str
    live_runtime_authorized: bool
    endpoint: str
    method: str
    dispatch_sha256: str
    authorization_sha256: str
    permit_sha256: str
    cell_sha256: str
    prompt_sha256: str
    content_sha256: str
    runtime_sha256: str
    broker_policy_sha256: str
    inbound_policy_sha256: str
    body_policy_sha256: str
    tls_policy_sha256: str
    sse_policy_sha256: str
    auth_commitment: str
    account_commitment: str
    workspace_commitment: str
    tls_certificate_sha256: str
    request_sha256: str
    request_bytes: int
    response_semantic_sha256: str
    response_bytes: int
    response_event_count: int
    turn_state_commitment: str
    upstream_call_count: int
    upstream_status: int
    interaction_count: int
    journal_sha256: str
    cleanup_complete: bool
    outcome: str
    _state: _ReceiptState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _RECEIPT_AUTHORITY
            or self.schema_version != BROKER_TEST_RECEIPT_SCHEMA_VERSION
            or self.authorization_scope != "fake-upstream-test-only"
            or self.live_runtime_authorized is not False
            or self.endpoint != CHATGPT_RESPONSES_ENDPOINT
            or self.method != "POST"
            or self.broker_policy_sha256 != BROKER_TEST_POLICY_SHA256
            or self.inbound_policy_sha256 != _INBOUND_POLICY_SHA256
            or self.body_policy_sha256 != _BODY_POLICY_SHA256
            or self.tls_policy_sha256 != _TLS_POLICY_SHA256
            or self.sse_policy_sha256 != _SSE_POLICY_SHA256
            or self.upstream_call_count != 1
            or self.upstream_status != 200
            or self.interaction_count != 1
            or self.cleanup_complete is not True
            or self.outcome != "fake-upstream-validated"
        ):
            raise CodexBrokerUnavailable("Broker test receipt is not verifier-issued.")
        for name in (
            "receipt_sha256",
            "dispatch_sha256",
            "authorization_sha256",
            "permit_sha256",
            "cell_sha256",
            "prompt_sha256",
            "content_sha256",
            "runtime_sha256",
            "broker_policy_sha256",
            "inbound_policy_sha256",
            "body_policy_sha256",
            "tls_policy_sha256",
            "sse_policy_sha256",
            "auth_commitment",
            "account_commitment",
            "workspace_commitment",
            "tls_certificate_sha256",
            "request_sha256",
            "response_semantic_sha256",
            "turn_state_commitment",
            "journal_sha256",
        ):
            _require_digest(getattr(self, name), name)
        for name in (
            "request_bytes",
            "response_bytes",
            "response_event_count",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise CodexBrokerUnavailable("Broker receipt count differs.")

    def validate(self) -> bool:
        return verify_codex_broker_test_receipt(self)

    def close(self) -> None:
        with _LOCK:
            if _ISSUED_RECEIPTS.get(id(self)) is self:
                _ISSUED_RECEIPTS.pop(id(self), None)
                self._state.closed = True
                self._state.journal.close()


def _receipt_document(value: CodexBrokerTestReceipt) -> dict[str, object]:
    return {
        key: item
        for key, item in value.__dict__.items()
        if not key.startswith("_") and key != "receipt_sha256"
    }


def verify_codex_broker_test_receipt(value: object) -> bool:
    if not isinstance(value, CodexBrokerTestReceipt):
        return False
    with _LOCK:
        try:
            return bool(
                _ISSUED_RECEIPTS.get(id(value)) is value
                and value._authority is _RECEIPT_AUTHORITY
                and value._seal is value._state.seal
                and not value._state.closed
                and value._state.journal.started
                and value._state.journal.validate()
                and value.journal_sha256 == value._state.journal.sha256
                and value.receipt_sha256 == canonical_sha256(_receipt_document(value))
            )
        except (AttributeError, TypeError, ValueError, CodexBrokerUnavailable):
            return False


def codex_broker_test_receipt_document(
    value: CodexBrokerTestReceipt,
) -> dict[str, object]:
    if not verify_codex_broker_test_receipt(value):
        raise CodexBrokerUnavailable("Broker test receipt is not authentic.")
    return {"receipt_sha256": value.receipt_sha256, **_receipt_document(value)}


def _exercise_fake_codex_broker(
    dispatch: CodexLiveDispatch,
    *,
    expected_request: _ExpectedRequest,
    fake_upstream: _FakeTLSUpstream,
    journal_root: Path,
    child: Callable[[CodexLiveDispatchContext, str, str], object],
    now: int,
) -> CodexBrokerTestReceipt:
    """Exercise mechanics with fake TLS only; never a production/live entrypoint."""

    if not verify_codex_live_dispatch(dispatch):
        raise CodexBrokerUnavailable("Broker test dispatch is unavailable.")
    if not isinstance(expected_request, _ExpectedRequest) or expected_request.closed:
        raise CodexBrokerUnavailable("Broker test request authority is unavailable.")
    if not fake_upstream.validate():
        raise CodexBrokerUnavailable("Broker fake TLS authority is unavailable.")
    if not callable(child):
        raise CodexBrokerUnavailable("Broker child callback is unavailable.")

    def issue_receipt(
        state: _BrokerServerState,
        *,
        auth_commitment: str,
        account_commitment: str,
        workspace_commitment: str,
    ) -> CodexBrokerTestReceipt:
        if (
            state.poisoned
            or state.interactions != 1
            or state.call_count != 1
            or state.response is None
            or state.request_sha256 != expected_request.sha256
            or not state.journal.validate()
            or not state.worker_terminated.is_set()
            or state.active_upstream_socket is not None
        ):
            raise CodexBrokerUnavailable(
                "Broker proof did not reach one exact completion."
            )
        response = state.response
        seal = object()
        receipt_state = _ReceiptState(state.journal, seal)
        provisional = CodexBrokerTestReceipt(
            schema_version=BROKER_TEST_RECEIPT_SCHEMA_VERSION,
            receipt_sha256="0" * 64,
            authorization_scope="fake-upstream-test-only",
            live_runtime_authorized=False,
            endpoint=CHATGPT_RESPONSES_ENDPOINT,
            method="POST",
            dispatch_sha256=dispatch.dispatch_sha256,
            authorization_sha256=dispatch.authorization_sha256,
            permit_sha256=dispatch.permit_sha256,
            cell_sha256=expected_request.cell_sha256,
            prompt_sha256=expected_request.prompt_sha256,
            content_sha256=expected_request.content_sha256,
            runtime_sha256=expected_request.runtime_sha256,
            broker_policy_sha256=BROKER_TEST_POLICY_SHA256,
            inbound_policy_sha256=_INBOUND_POLICY_SHA256,
            body_policy_sha256=_BODY_POLICY_SHA256,
            tls_policy_sha256=_TLS_POLICY_SHA256,
            sse_policy_sha256=_SSE_POLICY_SHA256,
            auth_commitment=auth_commitment,
            account_commitment=account_commitment,
            workspace_commitment=workspace_commitment,
            tls_certificate_sha256=fake_upstream.certificate_sha256,
            request_sha256=state.request_sha256,
            request_bytes=state.request_bytes,
            response_semantic_sha256=response.semantic_sha256,
            response_bytes=len(response.body),
            response_event_count=response.event_count,
            turn_state_commitment=hmac.new(
                state.hmac_key,
                response.turn_state.encode(),
                hashlib.sha256,
            ).hexdigest(),
            upstream_call_count=1,
            upstream_status=response.status,
            interaction_count=1,
            journal_sha256=state.journal.sha256,
            cleanup_complete=True,
            outcome="fake-upstream-validated",
            _state=receipt_state,
            _seal=seal,
            _authority=_RECEIPT_AUTHORITY,
        )
        result = CodexBrokerTestReceipt(
            **{
                **provisional.__dict__,
                "receipt_sha256": canonical_sha256(_receipt_document(provisional)),
            }
        )
        with _LOCK:
            _ISSUED_RECEIPTS[id(result)] = result
        return result

    auth: _RetainedAuthSnapshot | None = None
    journal: _AttemptJournal | None = None
    listener: socket.socket | None = None
    server_thread: threading.Thread | None = None
    server_state: _BrokerServerState | None = None
    receipt: CodexBrokerTestReceipt | None = None
    hmac_key = bytearray(secrets.token_bytes(32))
    try:
        auth = _RetainedAuthSnapshot(_AUTH_FILE, now=now)
        auth_commitment = auth.commitment(hmac_key)
        account_commitment = auth.account_commitment(hmac_key)
        workspace_commitment = auth.workspace_commitment(hmac_key)
        journal = _AttemptJournal(
            journal_root,
            {
                "dispatch_sha256": dispatch.dispatch_sha256,
                "authorization_sha256": dispatch.authorization_sha256,
                "permit_sha256": dispatch.permit_sha256,
                "cell_sha256": expected_request.cell_sha256,
                "prompt_sha256": expected_request.prompt_sha256,
                "content_sha256": expected_request.content_sha256,
                "runtime_sha256": expected_request.runtime_sha256,
                "request_sha256": expected_request.sha256,
                "auth_commitment": auth_commitment,
                "account_commitment": account_commitment,
                "workspace_commitment": workspace_commitment,
                "endpoint": CHATGPT_RESPONSES_ENDPOINT,
                "method": "POST",
            },
        )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        nonce = secrets.token_hex(32)
        if not _NONCE.fullmatch(nonce):
            raise CodexBrokerUnavailable("Broker nonce generation failed.")
        server_state = _BrokerServerState(
            listener,
            nonce,
            expected_request,
            auth,
            fake_upstream,
            journal,
            now,
            hmac_key,
        )
        server_thread = threading.Thread(
            target=_serve_broker,
            args=(server_state,),
            name="cc-codex-broker-test",
            daemon=False,
        )
        server_thread.start()
        endpoint = f"http://127.0.0.1:{listener.getsockname()[1]}/v1/{nonce}"

        def invoke(context: CodexLiveDispatchContext) -> object:
            if not verify_codex_live_dispatch_context(context):
                raise CodexBrokerUnavailable("Codex dispatch context is unavailable.")
            return child(context, endpoint, nonce)

        dispatch.run_once(invoke)
        time.sleep(_QUIET_SECONDS * 2)
        shutdown_clean = _stop_broker_worker(server_state, listener, server_thread)
        listener = None
        server_thread = None
        if not shutdown_clean:
            raise CodexBrokerUnavailable("Broker worker shutdown was not bounded.")
        if not auth.validate(now=now):
            raise CodexBrokerUnavailable("Codex auth changed after broker completion.")
        receipt = issue_receipt(
            server_state,
            auth_commitment=auth_commitment,
            account_commitment=account_commitment,
            workspace_commitment=workspace_commitment,
        )
        journal = None
        return receipt
    finally:
        if (
            server_state is not None
            and listener is not None
            and server_thread is not None
        ):
            _stop_broker_worker(server_state, listener, server_thread)
            listener = None
            server_thread = None
        elif listener is not None:
            listener.close()
        if auth is not None:
            auth.close()
        expected_request.close()
        fake_upstream.close()
        if journal is not None:
            journal.close()
        _zero(hmac_key)


__all__ = [
    "BROKER_TEST_POLICY_SHA256",
    "BROKER_TEST_RECEIPT_SCHEMA_VERSION",
    "CHATGPT_RESPONSES_ENDPOINT",
    "CodexBrokerTestReceipt",
    "CodexBrokerUnavailable",
    "codex_broker_test_receipt_document",
    "verify_codex_broker_test_receipt",
]
