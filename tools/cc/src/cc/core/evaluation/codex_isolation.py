"""Offline proof of the model-visible tool registry emitted by native Codex."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import secrets
import selectors
import signal
import stat
import subprocess
import tempfile
import threading
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cc.core.evaluation.schema import canonical_sha256

ISOLATION_SCHEMA_VERSION = "task285-codex-tool-isolation-v1"
LIVE_AUTHORIZATION_SCHEMA_VERSION = "task285-codex-live-authorization-v1"
LIVE_PERMIT_SCHEMA_VERSION = "task285-codex-live-permit-v1"
LIVE_DISPATCH_SCHEMA_VERSION = "task285-codex-live-dispatch-v1"
LIVE_DISPATCH_CONTEXT_SCHEMA_VERSION = "task285-codex-live-dispatch-context-v1"
MINIMUM_CODEX_VERSION = (0, 147, 0)
OFFICIAL_CODEX_VERSION = "0.147.0"
OFFICIAL_CODEX_MODEL = "gpt-5.6-sol"
OFFICIAL_CODEX_NATIVE_SHA256 = (
    "19c4f144c5226a9f17c58e6f0fa854843b0f77a6eb420f40e2745a12f10f5d37"
)
OFFICIAL_CODEX_NATIVE_BYTES = 219_997_536
OFFICIAL_CODEX_CATALOG_SHA256 = (
    "2efe1eb3839a958971ed7ff5ca2693ec38b4f4d3352fab837ce83ce16e0f9169"
)
OFFICIAL_CODEX_PACKAGE_POLICY_SHA256 = (
    "4a0d1e3983dca39c4960ff37a6d6747706d0f9f56971fd43b03784453eb3591c"
)
OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY = (
    "d3d8921914f3404b2547568c9ee51eab30701930a656536270222f6cc0fc0617"
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MODEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_MESSAGE_ID = re.compile(r"^msg_[0-9a-f-]{36}$")
_MAX_BINARY_BYTES = 512 * 1024 * 1024
_MAX_CATALOG_BYTES = 4 * 1024 * 1024
_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_CAPTURE_INTERACTIONS = 2
_MAX_CAPTURE_BYTES = _MAX_REQUEST_BYTES
_MAX_VERSION_OUTPUT_BYTES = 4096
_VERSION_TIMEOUT_SECONDS = 10.0
_REQUEST_TIMEOUT_SECONDS = 20.0
_PROCESS_GROUP_TERM_SECONDS = 0.25
_PROCESS_GROUP_KILL_SECONDS = 1.0
_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
_REQUEST_PATH_TEMPLATE = "/v1/<NONCE>/responses"
_PROMPT = "Return exactly OK. Do not call tools."
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
_DISABLED_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode",
    "code_mode_buffered_exec",
    "code_mode_host",
    "code_mode_only",
    "computer_use",
    "enable_mcp_apps",
    "enable_request_compression",
    "goals",
    "guardian_approval",
    "hooks",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "multi_agent_v2",
    "plugin_sharing",
    "plugins",
    "recommended_plugins",
    "remote_plugin",
    "request_permissions_tool",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "unified_exec",
    "view_image",
    "workspace_dependencies",
)
_CONFIG_CONTRACT = {
    "schema_version": "codex-0.147-offline-config-v1",
    "approval_policy": "never",
    "sandbox": "read-only",
    "ephemeral": True,
    "ignore_user_config": True,
    "ignore_rules": True,
    "strict_config": True,
    "model_provider": {
        "name": "Loopback",
        "wire_api": "responses",
        "requires_openai_auth": False,
        "request_max_retries": 0,
        "stream_max_retries": 0,
        "nonce_header": "x-cc-isolation-nonce",
        "nonce_path": "/v1/<NONCE>",
    },
    "model_catalog_policy": {
        "tool_mode": "direct",
        "use_responses_lite": False,
        "multi_agent_version": None,
        "apply_patch_tool_type": None,
    },
    "web_search": "disabled",
    "tools": {
        "web_search": False,
        "update_plan": {"enabled": False},
        "experimental_request_user_input": {"enabled": False},
    },
    "capture_policy": {
        "maximum_interactions": _MAX_CAPTURE_INTERACTIONS,
        "maximum_aggregate_body_bytes": _MAX_CAPTURE_BYTES,
        "maximum_version_output_bytes": _MAX_VERSION_OUTPUT_BYTES,
    },
    "disabled_features": list(_DISABLED_FEATURES),
}
_ENVIRONMENT_CONTRACT = {
    "HOME": "<PRIVATE_HOME>",
    "CODEX_HOME": "<PRIVATE_CODEX_HOME>",
    "TMPDIR": "<PRIVATE_TMPDIR>",
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",
}
_SANDBOX_PROFILE_TEMPLATE = """(version 1)
(allow default)
(deny network*)
(allow network-outbound (remote ip \"localhost:<LOOPBACK_PORT>\"))
(deny file-write*)
(allow file-write* (subpath \"<PRIVATE_ROOT>\"))
"""
_CONFIG_CONTRACT_SHA256 = (
    "b8553a6438f2dfb0e42e0f07bc8011250a0514398df25681aa093eca0623136f"
)
_ARGV_CONTRACT_SHA256 = (
    "08ecaee50ad60fc8c8c142dc1e94fbbf69679155feea7460ceea7963e45f5bc3"
)
_ENVIRONMENT_CONTRACT_SHA256 = (
    "f3af8c786de2baa5c47f944a3de0f2b727ea97fb29a22f353bff8502c1fe286c"
)
_SANDBOX_CONTRACT_SHA256 = (
    "c5da6e25fff052dc297479707954b84c784d81e49b576c49cc261c3fe152f334"
)
_TOOL_REGISTRY_SHA256 = (
    "19ed4fda697b1ee9c81ce237b7bcf0ec9abab3741ffb181e63f1e19edc58b480"
)
_RECEIPT_AUTHORITY = object()
_ISSUED_RECEIPTS: weakref.WeakValueDictionary[int, "CodexIsolationReceipt"] = (
    weakref.WeakValueDictionary()
)
_LIVE_AUTHORIZATION_AUTHORITY = object()
_LIVE_PERMIT_AUTHORITY = object()
_LIVE_INPUT_AUTHORITY = object()
_LIVE_DISPATCH_AUTHORITY = object()
_LIVE_DISPATCH_CONTEXT_AUTHORITY = object()
_LIVE_AUTHORITY_LOCK = threading.RLock()
_ISSUED_LIVE_AUTHORIZATIONS: weakref.WeakValueDictionary[
    int, "CodexLiveAuthorization"
] = weakref.WeakValueDictionary()
_ISSUED_LIVE_PERMITS: weakref.WeakValueDictionary[int, "CodexLivePermit"] = (
    weakref.WeakValueDictionary()
)
_ISSUED_LIVE_INPUTS: weakref.WeakValueDictionary[int, Any] = (
    weakref.WeakValueDictionary()
)
_ISSUED_LIVE_DISPATCHES: weakref.WeakValueDictionary[int, Any] = (
    weakref.WeakValueDictionary()
)
_ISSUED_LIVE_DISPATCH_CONTEXTS: weakref.WeakValueDictionary[int, Any] = (
    weakref.WeakValueDictionary()
)
_AUTHORIZED_RECEIPTS: dict[int, weakref.ReferenceType[CodexIsolationReceipt]] = {}


def _official_registry_document() -> dict[str, object]:
    signature_key = "SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U"
    predicate_type = "https://slsa.dev/provenance/v1"
    return {
        "schema_version": "task285-official-codex-npm-registry-v1",
        "wrapper": {
            "name": "@openai/codex",
            "version": OFFICIAL_CODEX_VERSION,
            "dist": {
                "tarball": "https://registry.npmjs.org/@openai/codex/-/codex-0.147.0.tgz",
                "tarball_sha256": "d28b4fd4bd9f07ea71083d0cc40c579595cebbd4c10bc8ca98a6d385432e7255",
                "shasum": "1792030d147156695a2b86db0ec1a000ab9a83fc",
                "integrity": "sha512-EQLEXecAG2ptxI7UpBMo2TR/ga5596/c/OsYF/0LoUDh5JANZ7IoGqlzBEWbuEVQ76JePIbtTW/ihCkp1a7Z3w==",
                "signatures": [
                    {
                        "keyid": signature_key,
                        "sig": "MEYCIQCX0Q1t6NOIdLaE8IwpddUIj3TGSysVUrONZq+mNvogEQIhAOCoZMQK7aE0n42nYbqSYn2PKCwxP+d6oUlsosdfgnXK",
                    },
                    {
                        "keyid": signature_key,
                        "sig": "MEUCIQD906eFU8wio1g380qqPKCyp0L1Y54vn4PjY6/Ov6jbmwIgeg5PuTF99qsNL3ozeb7ruJ7/lb1Hunt4PnbpCgWfTNw=",
                    },
                ],
            },
            "attestation": {
                "url": "https://registry.npmjs.org/-/npm/v1/attestations/@openai%2fcodex@0.147.0",
                "predicate_type": predicate_type,
                "workflow": "https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/rust-v0.147.0",
                "repository_id": 965415649,
                "repository_owner_id": 14957082,
                "run_id": 31136011993,
                "run_attempt": 1,
                "oidc_issuer": "https://token.actions.githubusercontent.com",
                "conclusion": "success",
            },
        },
        "platform": {
            "name": "@openai/codex",
            "version": "0.147.0-darwin-arm64",
            "dist": {
                "tarball": "https://registry.npmjs.org/@openai/codex/-/codex-0.147.0-darwin-arm64.tgz",
                "tarball_sha256": "493de2d788c6ff01de222307c767231c1e6c802d5dd808523550fad6d972f4d3",
                "shasum": "10a1f074e7ac0d213cee58232e7d9297f7afb9f0",
                "integrity": "sha512-BEUVkiOW7kLcRyrMLfAr/h9wF8sRVJyZDy6OHtVn6QGDXiv3BvAZVTY1Pu9xF7KdIdkYXbp4uayN0aDQQaAUJw==",
                "signatures": [
                    {
                        "keyid": signature_key,
                        "sig": "MEUCIQCPO0kBTUtFzhyj94aK9GOlRfpqwYTCs5Ff/f8uEYo6ZwIgSgbkJTTTLmt96ZNMDOus26gMlE4ea05USzReECCFLPM=",
                    },
                    {
                        "keyid": signature_key,
                        "sig": "MEUCIQCTkkEGJz1UqcrsD74GjNShbjjj8BajWNLqlUpyX7t6sQIgLtTOPhBhkwzJVQjUjUAW/TV5Wod9DfaxUKld4fcie8Y=",
                    },
                ],
            },
            "attestation": {
                "url": "https://registry.npmjs.org/-/npm/v1/attestations/@openai%2fcodex@0.147.0-darwin-arm64",
                "predicate_type": predicate_type,
                "workflow": "https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/rust-v0.147.0",
                "repository_id": 965415649,
                "repository_owner_id": 14957082,
                "run_id": 31136011993,
                "run_attempt": 1,
                "oidc_issuer": "https://token.actions.githubusercontent.com",
                "conclusion": "success",
            },
            "native_signature": {
                "signer": "Developer ID Application: OpenAI OpCo, LLC (2DC432GLL2)",
                "team_id": "2DC432GLL2",
            },
        },
    }


def _official_package_policy_document() -> dict[str, object]:
    return {
        "schema_version": "task285-official-codex-package-policy-v1",
        "registry": _official_registry_document(),
        "native": {
            "format": "mach-o",
            "sha256": OFFICIAL_CODEX_NATIVE_SHA256,
            "bytes": OFFICIAL_CODEX_NATIVE_BYTES,
        },
        "model_catalog": {
            "model": OFFICIAL_CODEX_MODEL,
            "sha256": OFFICIAL_CODEX_CATALOG_SHA256,
            "tool_mode": "direct",
            "use_responses_lite": False,
            "multi_agent_version": None,
        },
        "source_attribution": {
            "annotated_tag": "rust-v0.147.0",
            "tag_object": "3ed6f04f6bf8b7c46299d1cb1ff99c74ce21a51d",
            "peeled_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
            "tree": "3828c818254d4c756585f5b59fe46b6fa3634765",
            "tag_cryptographically_signed": False,
            "commit_cryptographically_signed": False,
            "authority": "attribution-only",
        },
        "authorization_policy": {
            "registry_release_check_required": True,
            "npm_audit_signatures_verified": True,
            "sigstore_attestations_verified": True,
            "apple_code_signature_verified": True,
            "measurement_schema_version": ISOLATION_SCHEMA_VERSION,
            "measurement_scope": "offline-measurement-only",
            "measurement_live_runtime_authorized": False,
            "model_visible_tools": [],
        },
    }


def _official_framework_release_document() -> dict[str, object]:
    return {
        "schema_version": "task285-codex-framework-release-trust-v1",
        "trust_root": "signed-framework-release-source",
        "package_policy_sha256": OFFICIAL_CODEX_PACKAGE_POLICY_SHA256,
        "release_registry_equality_required": True,
    }


def _verify_release_contract_constants() -> None:
    for value in (
        OFFICIAL_CODEX_NATIVE_SHA256,
        OFFICIAL_CODEX_CATALOG_SHA256,
        OFFICIAL_CODEX_PACKAGE_POLICY_SHA256,
        OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY,
    ):
        _require_digest(value, "official Codex release identity")
    if (
        canonical_sha256(_official_package_policy_document())
        != OFFICIAL_CODEX_PACKAGE_POLICY_SHA256
        or canonical_sha256(_official_framework_release_document())
        != OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
    ):
        raise CodexIsolationUnavailable(
            "Official Codex release contract source changed."
        )


class CodexIsolationUnavailable(ValueError):
    """The staged Codex probe could not prove the closed isolation contract."""


def _require_digest(value: str, field_name: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise CodexIsolationUnavailable(f"{field_name} is not a SHA-256 digest.")


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if match is None:
        raise CodexIsolationUnavailable("Codex package version is not exact semver.")
    result = tuple(int(item) for item in match.groups())
    if result < MINIMUM_CODEX_VERSION:
        raise CodexIsolationUnavailable("Codex package version is below 0.147.0.")
    return result  # type: ignore[return-value]


def _stable_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _descriptor_bytes(descriptor: int, maximum: int) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise CodexIsolationUnavailable(
            "Probe inputs must be single-link regular files."
        )
    if before.st_size < 1 or before.st_size > maximum:
        raise CodexIsolationUnavailable("Probe input size is outside the closed limit.")
    os.lseek(descriptor, 0, os.SEEK_SET)
    value = bytearray()
    while len(value) <= maximum:
        chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(value)))
        if not chunk:
            break
        value.extend(chunk)
    after = os.fstat(descriptor)
    if (
        len(value) > maximum
        or len(value) != before.st_size
        or _stable_identity(before) != _stable_identity(after)
    ):
        raise CodexIsolationUnavailable("Probe input changed during retention.")
    return bytes(value)


class _RetainedInput:
    def __init__(
        self,
        path: Path,
        *,
        expected_name: str,
        expected_mode: int,
        maximum: int,
        expected_sha256: str,
        expected_uid: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.descriptor: int | None = None
        if not self.path.is_absolute() or self.path.name != expected_name:
            raise CodexIsolationUnavailable("Probe input name or path is not exact.")
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise CodexIsolationUnavailable("Platform lacks no-follow protections.")
        try:
            expected = self.path.lstat()
            self.descriptor = os.open(self.path, os.O_RDONLY | no_follow)
            opened = os.fstat(self.descriptor)
            if (
                not stat.S_ISREG(expected.st_mode)
                or (expected.st_dev, expected.st_ino) != (opened.st_dev, opened.st_ino)
                or opened.st_uid
                != (os.getuid() if expected_uid is None else expected_uid)
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != expected_mode
            ):
                raise CodexIsolationUnavailable(
                    "Probe input ownership, type, link count, or mode is not exact."
                )
            self.identity = _stable_identity(opened)
            self.content = _descriptor_bytes(self.descriptor, maximum)
            self.sha256 = hashlib.sha256(self.content).hexdigest()
            if self.sha256 != expected_sha256:
                raise CodexIsolationUnavailable("Probe input digest differs.")
        except CodexIsolationUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise CodexIsolationUnavailable(
                "Probe input cannot be retained safely."
            ) from exc

    def validate(self) -> bool:
        if self.descriptor is None:
            return False
        try:
            opened = os.fstat(self.descriptor)
            path_value = self.path.lstat()
            return bool(
                _stable_identity(opened) == self.identity
                and (path_value.st_dev, path_value.st_ino)
                == (opened.st_dev, opened.st_ino)
                and hashlib.sha256(
                    _descriptor_bytes(self.descriptor, len(self.content))
                ).hexdigest()
                == self.sha256
            )
        except (OSError, CodexIsolationUnavailable):
            return False

    def close(self) -> None:
        if self.descriptor is not None:
            try:
                os.close(self.descriptor)
            except OSError:
                pass
            self.descriptor = None


class _RetainedLiveInput:
    def __init__(
        self,
        path: Path,
        *,
        expected_name: str,
        expected_mode: int,
        maximum: int,
        expected_sha256: str,
        expected_bytes: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.parent_descriptor: int | None = None
        self.descriptor: int | None = None
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if (
            no_follow is None
            or directory is None
            or not self.path.is_absolute()
            or self.path.name != expected_name
            or self.path.parent != self.path.parent.resolve()
        ):
            raise CodexIsolationUnavailable(
                "Live Codex input path or name is not canonical."
            )
        try:
            parent_expected = self.path.parent.lstat()
            self.parent_descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | directory | no_follow,
            )
            parent_opened = os.fstat(self.parent_descriptor)
            named = os.stat(
                self.path.name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
            self.descriptor = os.open(
                self.path.name,
                os.O_RDONLY | no_follow,
                dir_fd=self.parent_descriptor,
            )
            opened = os.fstat(self.descriptor)
            if (
                not stat.S_ISDIR(parent_expected.st_mode)
                or (parent_expected.st_dev, parent_expected.st_ino)
                != (parent_opened.st_dev, parent_opened.st_ino)
                or parent_opened.st_uid != os.getuid()
                or not stat.S_ISREG(named.st_mode)
                or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
                or opened.st_uid != os.getuid()
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != expected_mode
                or (expected_bytes is not None and opened.st_size != expected_bytes)
            ):
                raise CodexIsolationUnavailable(
                    "Live Codex input identity, ownership, link count, or mode differs."
                )
            self.parent_identity = _stable_identity(parent_opened)
            self.identity = _stable_identity(opened)
            self.content = _descriptor_bytes(self.descriptor, maximum)
            self.size = len(self.content)
            self.sha256 = hashlib.sha256(self.content).hexdigest()
            if self.sha256 != expected_sha256:
                raise CodexIsolationUnavailable("Live Codex input digest differs.")
        except CodexIsolationUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise CodexIsolationUnavailable(
                "Live Codex input cannot be retained safely."
            ) from exc

    def validate(self) -> bool:
        if self.parent_descriptor is None or self.descriptor is None:
            return False
        try:
            parent = os.fstat(self.parent_descriptor)
            parent_named = self.path.parent.lstat()
            opened = os.fstat(self.descriptor)
            named = os.stat(
                self.path.name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
            return bool(
                _stable_identity(parent) == self.parent_identity
                and (parent_named.st_dev, parent_named.st_ino)
                == (parent.st_dev, parent.st_ino)
                and _stable_identity(opened) == self.identity
                and (named.st_dev, named.st_ino) == (opened.st_dev, opened.st_ino)
                and hashlib.sha256(
                    _descriptor_bytes(self.descriptor, self.size)
                ).hexdigest()
                == self.sha256
            )
        except (OSError, CodexIsolationUnavailable):
            return False

    def close(self) -> None:
        for name in ("descriptor", "parent_descriptor"):
            descriptor = getattr(self, name)
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, name, None)


@dataclass(frozen=True)
class _RetainedLiveInputs:
    native: _RetainedLiveInput
    catalog: _RetainedLiveInput
    model: str
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def validate(self) -> bool:
        with _LIVE_AUTHORITY_LOCK:
            return bool(
                _ISSUED_LIVE_INPUTS.get(id(self)) is self
                and self._authority is _LIVE_INPUT_AUTHORITY
                and self.model == OFFICIAL_CODEX_MODEL
                and self.native.sha256 == OFFICIAL_CODEX_NATIVE_SHA256
                and self.native.size == OFFICIAL_CODEX_NATIVE_BYTES
                and self.catalog.sha256 == OFFICIAL_CODEX_CATALOG_SHA256
                and self.native.validate()
                and self.catalog.validate()
            )

    def close(self) -> None:
        with _LIVE_AUTHORITY_LOCK:
            if _ISSUED_LIVE_INPUTS.get(id(self)) is self:
                _ISSUED_LIVE_INPUTS.pop(id(self), None)
                self.native.close()
                self.catalog.close()


class _RetainedPrivateRoot:
    def __init__(self, path: Path, expected_entries: tuple[str, ...]) -> None:
        self.path = Path(path)
        self.expected_entries = expected_entries
        self.parent_descriptor: int | None = None
        self.root_descriptor: int | None = None
        self.directory_descriptors: dict[str, int] = {}
        self.directory_identities: dict[str, tuple[int, int]] = {}
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if (
            no_follow is None
            or directory is None
            or not self.path.is_absolute()
            or self.path != self.path.resolve()
        ):
            raise CodexIsolationUnavailable("Private probe root is not canonical.")
        try:
            parent_expected = self.path.parent.lstat()
            self.parent_descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | directory | no_follow,
            )
            parent_opened = os.fstat(self.parent_descriptor)
            self.root_descriptor = os.open(
                self.path.name,
                os.O_RDONLY | directory | no_follow,
                dir_fd=self.parent_descriptor,
            )
            root_opened = os.fstat(self.root_descriptor)
            if (
                not stat.S_ISDIR(parent_expected.st_mode)
                or (parent_expected.st_dev, parent_expected.st_ino)
                != (parent_opened.st_dev, parent_opened.st_ino)
                or not stat.S_ISDIR(root_opened.st_mode)
                or root_opened.st_uid != os.getuid()
                or stat.S_IMODE(root_opened.st_mode) != 0o700
            ):
                raise CodexIsolationUnavailable("Private probe root identity differs.")
            self.parent_identity = (parent_opened.st_dev, parent_opened.st_ino)
            self.root_identity = (root_opened.st_dev, root_opened.st_ino)
            if not self.validate():
                raise CodexIsolationUnavailable("Private probe root is not exact.")
        except CodexIsolationUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise CodexIsolationUnavailable(
                "Private probe root cannot be retained safely."
            ) from exc

    def validate_identity(self) -> bool:
        if self.parent_descriptor is None or self.root_descriptor is None:
            return False
        try:
            parent = os.fstat(self.parent_descriptor)
            root = os.fstat(self.root_descriptor)
            parent_entry = os.stat(
                self.path.name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
            return bool(
                (parent.st_dev, parent.st_ino) == self.parent_identity
                and (root.st_dev, root.st_ino) == self.root_identity
                and (parent_entry.st_dev, parent_entry.st_ino) == self.root_identity
                and stat.S_ISDIR(root.st_mode)
            )
        except OSError:
            return False

    def _directories_validate(self) -> bool:
        if self.root_descriptor is None:
            return False
        try:
            for name, descriptor in self.directory_descriptors.items():
                opened = os.fstat(descriptor)
                path_value = os.stat(
                    name,
                    dir_fd=self.root_descriptor,
                    follow_symlinks=False,
                )
                if (
                    (opened.st_dev, opened.st_ino)
                    != self.directory_identities.get(name)
                    or (path_value.st_dev, path_value.st_ino)
                    != self.directory_identities.get(name)
                    or not stat.S_ISDIR(opened.st_mode)
                    or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) != 0o700
                ):
                    return False
            return True
        except OSError:
            return False

    def validate(self) -> bool:
        if not self.validate_identity() or self.root_descriptor is None:
            return False
        try:
            root = os.fstat(self.root_descriptor)
            return bool(
                root.st_uid == os.getuid()
                and stat.S_IMODE(root.st_mode) == 0o700
                and tuple(sorted(os.listdir(self.root_descriptor)))
                == self.expected_entries
                and self._directories_validate()
            )
        except OSError:
            return False

    def bind_expected_entries(
        self,
        expected_entries: tuple[str, ...],
        *,
        retained_directories: tuple[str, ...],
    ) -> None:
        if (
            self.expected_entries
            or self.directory_descriptors
            or self.root_descriptor is None
            or not self.validate_identity()
            or tuple(sorted(os.listdir(self.root_descriptor))) != expected_entries
            or any(name not in expected_entries for name in retained_directories)
        ):
            raise CodexIsolationUnavailable(
                "Private probe root contents cannot be bound exactly."
            )
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if no_follow is None or directory is None:
            raise CodexIsolationUnavailable("Platform lacks no-follow protections.")
        descriptors: dict[str, int] = {}
        identities: dict[str, tuple[int, int]] = {}
        try:
            for name in retained_directories:
                path_value = os.stat(
                    name,
                    dir_fd=self.root_descriptor,
                    follow_symlinks=False,
                )
                descriptor = os.open(
                    name,
                    os.O_RDONLY | directory | no_follow,
                    dir_fd=self.root_descriptor,
                )
                descriptors[name] = descriptor
                opened = os.fstat(descriptor)
                if (
                    (path_value.st_dev, path_value.st_ino)
                    != (opened.st_dev, opened.st_ino)
                    or not stat.S_ISDIR(opened.st_mode)
                    or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) != 0o700
                ):
                    raise CodexIsolationUnavailable(
                        "Private probe directory identity differs."
                    )
                identities[name] = (opened.st_dev, opened.st_ino)
        except CodexIsolationUnavailable:
            for descriptor in descriptors.values():
                os.close(descriptor)
            raise
        except OSError as exc:
            for descriptor in descriptors.values():
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise CodexIsolationUnavailable(
                "Private probe directories cannot be retained safely."
            ) from exc
        self.expected_entries = expected_entries
        self.directory_descriptors = descriptors
        self.directory_identities = identities
        if not self.validate():
            raise CodexIsolationUnavailable(
                "Private probe directories changed during retention."
            )

    def remove(self) -> None:
        if self.root_descriptor is None:
            raise CodexIsolationUnavailable(
                "Private probe root descriptor was released before cleanup."
            )
        try:
            root = os.fstat(self.root_descriptor)
            if (root.st_dev, root.st_ino) != self.root_identity or not stat.S_ISDIR(
                root.st_mode
            ):
                raise CodexIsolationUnavailable(
                    "Retained private probe inode changed before cleanup."
                )
            os.fchmod(self.root_descriptor, 0o700)
            for descriptor in self.directory_descriptors.values():
                os.fchmod(descriptor, 0o700)
            _clear_directory_at(self.root_descriptor)
            root = os.fstat(self.root_descriptor)
            if (root.st_dev, root.st_ino) != self.root_identity or os.listdir(
                self.root_descriptor
            ):
                raise CodexIsolationUnavailable(
                    "Retained private probe inode was not cleared exactly."
                )
        except CodexIsolationUnavailable:
            raise
        except OSError as exc:
            raise CodexIsolationUnavailable(
                "Retained private probe inode could not be cleared safely."
            ) from exc

    def close(self) -> None:
        for descriptor in self.directory_descriptors.values():
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.directory_descriptors = {}
        self.directory_identities = {}
        for name in ("root_descriptor", "parent_descriptor"):
            descriptor = getattr(self, name)
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, name, None)


def _clear_directory_at(directory: int) -> None:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise CodexIsolationUnavailable("Platform lacks safe cleanup primitives.")
    for name in sorted(os.listdir(directory)):
        if not name or name in {".", ".."} or "/" in name:
            raise CodexIsolationUnavailable("Private cleanup entry is not exact.")
        try:
            entry = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISDIR(entry.st_mode):
                os.unlink(name, dir_fd=directory)
                continue
            os.chmod(
                name,
                0o700,
                dir_fd=directory,
                follow_symlinks=False,
            )
            child = os.open(
                name,
                os.O_RDONLY | directory_flag | no_follow,
                dir_fd=directory,
            )
            try:
                opened = os.fstat(child)
                if (opened.st_dev, opened.st_ino) != (entry.st_dev, entry.st_ino):
                    raise CodexIsolationUnavailable(
                        "Private cleanup directory identity changed."
                    )
                _clear_directory_at(child)
                after = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (after.st_dev, after.st_ino) != (entry.st_dev, entry.st_ino):
                    raise CodexIsolationUnavailable(
                        "Private cleanup directory path changed."
                    )
                os.rmdir(name, dir_fd=directory)
            finally:
                os.close(child)
        except CodexIsolationUnavailable:
            raise
        except OSError as exc:
            raise CodexIsolationUnavailable(
                "Private cleanup entry could not be removed safely."
            ) from exc


def _closed_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise CodexIsolationUnavailable(
                    "Model catalog contains duplicate keys."
                )
            value[key] = item
        return value

    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexIsolationUnavailable("Model catalog is not exact JSON.") from exc
    if not isinstance(decoded, dict):
        raise CodexIsolationUnavailable("Model catalog must be an object.")
    return decoded


def verify_official_codex_registry_metadata(raw: bytes) -> bool:
    """Check a release-time registry projection; never issue runtime authority."""

    try:
        _verify_release_contract_constants()
        return _closed_json(raw) == _official_registry_document()
    except (AttributeError, TypeError, ValueError, CodexIsolationUnavailable):
        return False


def _verify_catalog(raw: bytes, *, package_version: str, model: str) -> str:
    value = _closed_json(raw)
    if (
        set(value) != {"client_version", "models"}
        or value.get("client_version") != package_version
    ):
        raise CodexIsolationUnavailable("Model catalog release identity differs.")
    models = value.get("models")
    if (
        not isinstance(models, list)
        or len(models) != 1
        or not isinstance(models[0], dict)
    ):
        raise CodexIsolationUnavailable("Model catalog must contain exactly one model.")
    selected = models[0]
    required = {
        "slug": model,
        "apply_patch_tool_type": None,
        "experimental_supported_tools": [],
        "supports_search_tool": False,
        "supports_tool_suggest": False,
        "supports_skills": False,
        "supports_plugins": False,
        "supports_apps": False,
        "tool_mode": "direct",
        "use_responses_lite": False,
        "multi_agent_version": None,
    }
    if not set(required).issubset(selected) or any(
        selected.get(key) != item for key, item in required.items()
    ):
        raise CodexIsolationUnavailable(
            "Model catalog does not suppress every model-dependent tool source."
        )
    messages = selected.get("model_messages")
    instructions = (
        messages.get("instructions_template") if isinstance(messages, dict) else None
    )
    if not isinstance(instructions, str) or not instructions:
        raise CodexIsolationUnavailable("Model catalog instructions are unavailable.")
    return instructions


def _native_format(raw: bytes) -> str:
    magic = raw[:4]
    if magic == b"\x7fELF":
        return "elf"
    if magic[:2] == b"MZ":
        return "pe"
    if magic in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    }:
        return "mach-o"
    raise CodexIsolationUnavailable("Codex executable is not a native binary.")


def _tool_registry_document() -> dict[str, object]:
    return {"schema_version": "codex-model-visible-tools-v1", "tools": []}


def _normalized_argv_document(
    argv: list[str],
    *,
    sandbox_profile: str,
    binary: Path,
    work: Path,
    catalog: Path,
    endpoint: str,
    model: str,
    nonce: str,
) -> dict[str, object]:
    normalized: list[str] = []
    for item in argv:
        if item == sandbox_profile:
            normalized.append("<PROFILE>")
        elif item == str(binary):
            normalized.append("<BINARY>")
        elif item == str(work):
            normalized.append("<WORK>")
        elif item == model:
            normalized.append("<MODEL>")
        else:
            normalized.append(
                item.replace(str(catalog), "<CATALOG>")
                .replace(endpoint, "<ENDPOINT>")
                .replace(nonce, "<NONCE>")
            )
    return {
        "schema_version": "codex-0.147-offline-argv-v1",
        "argv": normalized,
    }


def _argv_contract_document() -> dict[str, object]:
    nonce = "0" * 64
    endpoint = f"http://127.0.0.1:1/v1/{nonce}"
    binary = Path("/<BINARY>")
    work = Path("/<WORK>")
    catalog = Path("/<CATALOG>")
    model = "<MODEL>"
    profile = "<PROFILE>"
    argv = _codex_argv(
        sandbox_profile=profile,
        binary=binary,
        work=work,
        catalog=catalog,
        endpoint=endpoint,
        model=model,
        nonce=nonce,
    )
    return _normalized_argv_document(
        argv,
        sandbox_profile=profile,
        binary=binary,
        work=work,
        catalog=catalog,
        endpoint=endpoint,
        model=model,
        nonce=nonce,
    )


def _verify_contract_constants() -> None:
    if _SANDBOX_EXEC != Path("/usr/bin/sandbox-exec") or _CONFIG_CONTRACT.get(
        "capture_policy"
    ) != {
        "maximum_interactions": _MAX_CAPTURE_INTERACTIONS,
        "maximum_aggregate_body_bytes": _MAX_CAPTURE_BYTES,
        "maximum_version_output_bytes": _MAX_VERSION_OUTPUT_BYTES,
    }:
        raise CodexIsolationUnavailable("Offline isolation contract source changed.")
    values = (
        (canonical_sha256(_CONFIG_CONTRACT), _CONFIG_CONTRACT_SHA256),
        (canonical_sha256(_argv_contract_document()), _ARGV_CONTRACT_SHA256),
        (canonical_sha256(_ENVIRONMENT_CONTRACT), _ENVIRONMENT_CONTRACT_SHA256),
        (
            hashlib.sha256(_SANDBOX_PROFILE_TEMPLATE.encode("utf-8")).hexdigest(),
            _SANDBOX_CONTRACT_SHA256,
        ),
        (canonical_sha256(_tool_registry_document()), _TOOL_REGISTRY_SHA256),
    )
    if any(actual != expected for actual, expected in values):
        raise CodexIsolationUnavailable("Offline isolation contract source changed.")


def _sandbox_profile(private_root: Path, *, endpoint: str, nonce: str) -> str:
    root = str(private_root.resolve())
    if '"' in root or "\n" in root:
        raise CodexIsolationUnavailable(
            "Private probe root cannot be sandboxed exactly."
        )
    _host, port = _require_loopback_endpoint(endpoint, nonce=nonce)
    return _SANDBOX_PROFILE_TEMPLATE.replace("<PRIVATE_ROOT>", root).replace(
        "<LOOPBACK_PORT>", str(port)
    )


def _request_path(nonce: str) -> str:
    if not _NONCE.fullmatch(nonce):
        raise CodexIsolationUnavailable("Probe nonce is not exact.")
    return _REQUEST_PATH_TEMPLATE.replace("<NONCE>", nonce)


def _require_loopback_endpoint(endpoint: str, *, nonce: str) -> tuple[str, int]:
    _request_path(nonce)
    parsed = urlsplit(endpoint)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CodexIsolationUnavailable("Probe endpoint is malformed.") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.path != f"/v1/{nonce}"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise CodexIsolationUnavailable("Probe endpoint is not exact loopback HTTP.")
    return parsed.hostname, port


@dataclass(frozen=True)
class _CapturedRequest:
    method: str
    path: str
    headers: tuple[tuple[str, str], ...]
    raw_body: bytes = field(repr=False)
    body: dict[str, Any] | None = field(repr=False)


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    server: "_CaptureServer"

    def _capture(self, method: str) -> None:
        length_value = self.headers.get("Content-Length")
        raw = b""
        body: dict[str, Any] | None = None
        declared_bytes = 0
        if length_value is not None and length_value.isdigit():
            declared_bytes = int(length_value)
            if declared_bytes <= _MAX_REQUEST_BYTES:
                raw = self.rfile.read(declared_bytes)
                try:
                    decoded = _closed_json(raw)
                    if isinstance(decoded, dict):
                        body = decoded
                except CodexIsolationUnavailable:
                    pass
        self.server.record_capture(
            _CapturedRequest(
                method,
                self.path,
                tuple(
                    sorted((key.lower(), value) for key, value in self.headers.items())
                ),
                raw,
                body,
            ),
            declared_bytes=declared_bytes,
        )
        payload = b'{"error":{"message":"offline isolation probe complete"}}'
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(payload)

    def do_POST(self) -> None:
        self._capture("POST")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("do_") and len(name) > 3:
            return lambda: self._capture(name[3:])
        raise AttributeError(name)

    def log_message(self, _format: str, *args: object) -> None:
        del args


class _CaptureServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, nonce: str) -> None:
        _request_path(nonce)
        super().__init__(("127.0.0.1", 0), _CaptureHandler)
        self.nonce = nonce
        self.captures: list[_CapturedRequest] = []
        self.interaction_count = 0
        self.aggregate_body_bytes = 0
        self.capture_overflow = False
        self._capture_lock = threading.Lock()

    def record_capture(
        self,
        value: _CapturedRequest,
        *,
        declared_bytes: int,
    ) -> None:
        with self._capture_lock:
            self.interaction_count = min(
                self.interaction_count + 1,
                _MAX_CAPTURE_INTERACTIONS + 1,
            )
            self.aggregate_body_bytes = min(
                self.aggregate_body_bytes + declared_bytes,
                _MAX_CAPTURE_BYTES + 1,
            )
            if (
                self.interaction_count > _MAX_CAPTURE_INTERACTIONS
                or declared_bytes > _MAX_REQUEST_BYTES
                or self.aggregate_body_bytes > _MAX_CAPTURE_BYTES
            ):
                self.capture_overflow = True
            if len(self.captures) < _MAX_CAPTURE_INTERACTIONS:
                self.captures.append(value)


class _LoopbackCapture:
    def __init__(self, nonce: str) -> None:
        self.server = _CaptureServer(nonce)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1/{self.server.nonce}"

    def __enter__(self) -> "_LoopbackCapture":
        _require_loopback_endpoint(self.endpoint, nonce=self.server.nonce)
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _config_arguments(*, endpoint: str, catalog: Path, nonce: str) -> list[str]:
    _require_loopback_endpoint(endpoint, nonce=nonce)
    provider = (
        '{ name="Loopback", base_url='
        f'{_toml_string(endpoint)}, wire_api="responses", '
        'requires_openai_auth=false, http_headers={ "x-cc-isolation-nonce"='
        f"{_toml_string(nonce)} }}, request_max_retries=0, stream_max_retries=0 }}"
    )
    return [
        "-c",
        'model_provider="local"',
        "-c",
        f"model_catalog_json={_toml_string(str(catalog))}",
        "-c",
        f"model_providers.local={provider}",
        "-c",
        'web_search="disabled"',
        "-c",
        "tools.web_search=false",
        "-c",
        "tools.update_plan={enabled=false}",
        "-c",
        "tools.experimental_request_user_input={enabled=false}",
    ]


def _codex_argv(
    *,
    sandbox_profile: str,
    binary: Path,
    work: Path,
    catalog: Path,
    endpoint: str,
    model: str,
    nonce: str,
) -> list[str]:
    result = [
        str(_SANDBOX_EXEC),
        "-p",
        sandbox_profile,
        str(binary),
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--strict-config",
        "-C",
        str(work),
        "--model",
        model,
        "--sandbox",
        "read-only",
        *_config_arguments(endpoint=endpoint, catalog=catalog, nonce=nonce),
    ]
    for feature in _DISABLED_FEATURES:
        result.extend(("--disable", feature))
    result.append(_PROMPT)
    return result


def _private_environment(root: Path) -> dict[str, str]:
    return {
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "codex-home"),
        "TMPDIR": str(root / "tmp"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
    }


def _verify_private_environment(
    environment: dict[str, str],
    *,
    private_root: Path,
    retained_root: _RetainedPrivateRoot,
) -> None:
    expected = {
        "HOME": str(private_root / "home"),
        "CODEX_HOME": str(private_root / "codex-home"),
        "TMPDIR": str(private_root / "tmp"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
    }
    if (
        environment != expected
        or not retained_root.validate()
        or set(retained_root.directory_descriptors)
        != {"home", "codex-home", "tmp", "work"}
    ):
        raise CodexIsolationUnavailable("Private runtime environment identity differs.")


def _verify_runtime_contracts(
    *,
    argv: list[str],
    environment: dict[str, str],
    sandbox_profile: str,
    private_root: Path,
    binary: Path,
    work: Path,
    catalog: Path,
    endpoint: str,
    model: str,
    nonce: str,
    retained_root: _RetainedPrivateRoot,
) -> None:
    _verify_private_environment(
        environment,
        private_root=private_root,
        retained_root=retained_root,
    )
    normalized_environment = dict(environment)
    normalized_environment.update(
        {
            "HOME": "<PRIVATE_HOME>",
            "CODEX_HOME": "<PRIVATE_CODEX_HOME>",
            "TMPDIR": "<PRIVATE_TMPDIR>",
        }
    )
    _host, port = _require_loopback_endpoint(endpoint, nonce=nonce)
    normalized_profile = sandbox_profile.replace(
        str(private_root.resolve()), "<PRIVATE_ROOT>"
    ).replace(f"localhost:{port}", "localhost:<LOOPBACK_PORT>")
    if (
        normalized_environment != _ENVIRONMENT_CONTRACT
        or normalized_profile != _SANDBOX_PROFILE_TEMPLATE
        or canonical_sha256(
            _normalized_argv_document(
                argv,
                sandbox_profile=sandbox_profile,
                binary=binary,
                work=work,
                catalog=catalog,
                endpoint=endpoint,
                model=model,
                nonce=nonce,
            )
        )
        != _ARGV_CONTRACT_SHA256
    ):
        raise CodexIsolationUnavailable("Runtime isolation contract differs.")


def _runtime_config_document(argv: list[str]) -> dict[str, object]:
    try:
        start = argv.index("read-only") + 1
        end = argv.index("--disable", start)
    except ValueError as exc:
        raise CodexIsolationUnavailable(
            "Runtime configuration boundary differs."
        ) from exc
    arguments = argv[start:end]
    if len(arguments) % 2 or any(
        arguments[index] != "-c" for index in range(0, len(arguments), 2)
    ):
        raise CodexIsolationUnavailable("Runtime configuration arguments differ.")
    return {
        "schema_version": "codex-0.147-runtime-config-v1",
        "arguments": arguments,
    }


def _stage_file(root: Path, name: str, content: bytes, mode: int) -> Path:
    destination = root / name
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise CodexIsolationUnavailable("Platform lacks no-follow protections.")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
            mode,
        )
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset : offset + 1024 * 1024])
            if written <= 0:
                raise CodexIsolationUnavailable("Private staging made no progress.")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    except CodexIsolationUnavailable:
        raise
    except OSError as exc:
        raise CodexIsolationUnavailable(
            "Probe input could not be staged privately."
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return destination


def _stage_file_at(
    retained_root: _RetainedPrivateRoot,
    name: str,
    content: bytes,
    mode: int,
) -> Path:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if (
        no_follow is None
        or retained_root.root_descriptor is None
        or not retained_root.validate_identity()
        or not name
        or "/" in name
    ):
        raise CodexIsolationUnavailable("Private live staging root is not exact.")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
            mode,
            dir_fd=retained_root.root_descriptor,
        )
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset : offset + 1024 * 1024])
            if written <= 0:
                raise CodexIsolationUnavailable("Private staging made no progress.")
            offset += written
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(
            name,
            dir_fd=retained_root.root_descriptor,
            follow_symlinks=False,
        )
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise CodexIsolationUnavailable("Private staged input identity differs.")
    except CodexIsolationUnavailable:
        raise
    except OSError as exc:
        raise CodexIsolationUnavailable(
            "Live Codex input could not be staged privately."
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return retained_root.path / name


def _sandbox_exec_identity() -> tuple[str, int]:
    retained = _RetainedInput(
        _SANDBOX_EXEC,
        expected_name="sandbox-exec",
        expected_mode=0o755,
        maximum=2 * 1024 * 1024,
        expected_sha256=hashlib.sha256(_SANDBOX_EXEC.read_bytes()).hexdigest(),
        expected_uid=0,
    )
    try:
        return retained.sha256, len(retained.content)
    finally:
        retained.close()


def _retained_process_group_state(process_group: int) -> tuple[bool, bool, bool]:
    try:
        observed = subprocess.run(
            ["/bin/ps", "-axo", "pid=,pgid=,sess=,uid=,state="],
            check=True,
            capture_output=True,
            text=True,
            timeout=_PROCESS_GROUP_KILL_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodexIsolationUnavailable(
            "Probe process group membership could not be verified."
        ) from exc
    leader_state: str | None = None
    live_descendant = False
    descendant = False
    for line in observed.stdout.splitlines():
        fields = line.split()
        if len(fields) != 5 or not all(item.isdigit() for item in fields[:4]):
            continue
        pid, group, _session, owner = (int(item) for item in fields[:4])
        if group != process_group:
            continue
        if owner != os.getuid():
            raise CodexIsolationUnavailable("Probe process group ownership differs.")
        if pid == process_group:
            leader_state = fields[4]
        else:
            descendant = True
            if not fields[4].startswith("Z"):
                live_descendant = True
    if leader_state is None:
        raise CodexIsolationUnavailable(
            "Probe process-group leader was reaped before cleanup."
        )
    return leader_state.startswith("Z"), live_descendant, descendant


def _leader_exited_without_reaping(process: subprocess.Popen[bytes]) -> bool:
    return _retained_process_group_state(process.pid)[0]


def _wait_for_leader_without_reaping(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while not _leader_exited_without_reaping(process):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def _signal_retained_process_group(process_group: int, sent: signal.Signals) -> None:
    try:
        os.killpg(process_group, sent)
    except (ProcessLookupError, PermissionError) as exc:
        leader_exited, live_descendants, _descendants = _retained_process_group_state(
            process_group
        )
        if leader_exited and not live_descendants:
            return
        raise CodexIsolationUnavailable(
            "Probe process group could not be signaled safely."
        ) from exc


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    process_group_verified: bool = False,
) -> int:
    process_group = process.pid
    if process.returncode is not None or not process_group_verified:
        raise CodexIsolationUnavailable(
            "Probe process-group leader was reaped before cleanup."
        )
    deadline = time.monotonic() + _PROCESS_GROUP_TERM_SECONDS
    leader_exited, live_descendants, descendants = _retained_process_group_state(
        process_group
    )
    if not leader_exited or live_descendants:
        _signal_retained_process_group(process_group, signal.SIGTERM)
    while time.monotonic() < deadline:
        leader_exited, live_descendants, descendants = _retained_process_group_state(
            process_group
        )
        if leader_exited and not descendants:
            break
        time.sleep(0.01)
    leader_exited, live_descendants, descendants = _retained_process_group_state(
        process_group
    )
    if not leader_exited or live_descendants:
        _signal_retained_process_group(process_group, signal.SIGKILL)
    deadline = time.monotonic() + _PROCESS_GROUP_KILL_SECONDS
    while time.monotonic() < deadline:
        leader_exited, live_descendants, descendants = _retained_process_group_state(
            process_group
        )
        if leader_exited and not descendants:
            break
        time.sleep(0.01)
    leader_exited, live_descendants, descendants = _retained_process_group_state(
        process_group
    )
    try:
        returncode = process.wait(timeout=_PROCESS_GROUP_KILL_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise CodexIsolationUnavailable(
            "Probe process group could not be reaped."
        ) from exc
    if not leader_exited or descendants:
        raise CodexIsolationUnavailable("Probe process group survived forced cleanup.")
    return returncode


def _bounded_process_output(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> tuple[bytes, bytes, bool, bool]:
    streams = {
        "stdout": process.stdout,
        "stderr": process.stderr,
    }
    if any(value is None for value in streams.values()):
        raise CodexIsolationUnavailable("Probe output pipes were unavailable.")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        for name, stream in streams.items():
            if stream is None:
                raise CodexIsolationUnavailable("Probe output pipe was unavailable.")
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return bytes(output["stdout"]), bytes(output["stderr"]), True, False
            for key, _mask in selector.select(min(remaining, 0.1)):
                available = _MAX_VERSION_OUTPUT_BYTES - total + 1
                try:
                    chunk = os.read(key.fd, min(65536, max(1, available)))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if total + len(chunk) > _MAX_VERSION_OUTPUT_BYTES:
                    return (
                        bytes(output["stdout"]),
                        bytes(output["stderr"]),
                        False,
                        True,
                    )
                output[key.data].extend(chunk)
                total += len(chunk)
        return bytes(output["stdout"]), bytes(output["stderr"]), False, False
    finally:
        selector.close()


def _run_process_group(
    argv: list[str],
    *,
    work: Path,
    environment: dict[str, str],
    timeout: float,
    capture_output: bool,
    retained_root: _RetainedPrivateRoot,
) -> subprocess.CompletedProcess[bytes]:
    if not retained_root.validate():
        raise CodexIsolationUnavailable("Private probe root changed before execution.")
    output = subprocess.PIPE if capture_output else subprocess.DEVNULL
    process: subprocess.Popen[bytes] | None = None
    timed_out = False
    output_exceeded = False
    stdout: bytes | None = None
    stderr: bytes | None = None
    process_group_verified = False
    try:
        process = subprocess.Popen(
            argv,
            cwd=work,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
            close_fds=True,
        )
        try:
            process_group_verified = os.getpgid(process.pid) == process.pid
        except ProcessLookupError:
            process_group_verified = _leader_exited_without_reaping(process)
        if not process_group_verified:
            raise CodexIsolationUnavailable(
                "Probe process-group leader identity differs."
            )
        if capture_output:
            stdout, stderr, timed_out, output_exceeded = _bounded_process_output(
                process,
                timeout=timeout,
            )
        else:
            timed_out = not _wait_for_leader_without_reaping(
                process,
                timeout=timeout,
            )
    except OSError as exc:
        raise CodexIsolationUnavailable(
            "Probe process could not start safely."
        ) from exc
    finally:
        if process is not None:
            returncode = _terminate_process_group(
                process,
                process_group_verified=process_group_verified,
            )
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        if not retained_root.validate():
            raise CodexIsolationUnavailable(
                "Private probe root changed during execution."
            )
    if timed_out:
        raise CodexIsolationUnavailable("Probe process timed out and was reaped.")
    if output_exceeded:
        raise CodexIsolationUnavailable(
            "Probe process output exceeded the closed limit and was reaped."
        )
    if process is None:
        raise CodexIsolationUnavailable("Probe process was unavailable.")
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def _run_version(
    binary: Path,
    *,
    profile: str,
    environment: dict[str, str],
    expected_version: str,
    work: Path,
    retained_root: _RetainedPrivateRoot,
) -> None:
    completed = _run_process_group(
        [str(_SANDBOX_EXEC), "-p", profile, str(binary), "--version"],
        work=work,
        environment=environment,
        timeout=_VERSION_TIMEOUT_SECONDS,
        capture_output=True,
        retained_root=retained_root,
    )
    if (
        completed.returncode != 0
        or completed.stdout != f"codex-cli {expected_version}\n".encode("utf-8")
        or completed.stderr
    ):
        raise CodexIsolationUnavailable("Codex binary version identity differs.")


def _request_document(value: _CapturedRequest) -> dict[str, object]:
    return {
        "method": value.method,
        "path": value.path,
        "headers": [
            {"name": key, "value_sha256": hashlib.sha256(item.encode()).hexdigest()}
            for key, item in value.headers
        ],
        "body_sha256": hashlib.sha256(value.raw_body).hexdigest(),
        "body_bytes": len(value.raw_body),
    }


def _message_content(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, dict) or set(value) != {"type", "id", "role", "content"}:
        return None
    if value.get("type") != "message" or not isinstance(value.get("content"), list):
        return None
    identifier = value.get("id")
    if not isinstance(identifier, str) or not _MESSAGE_ID.fullmatch(identifier):
        return None
    result: list[str] = []
    for item in value["content"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"type", "text"}
            or item.get("type") != "input_text"
            or not isinstance(item.get("text"), str)
        ):
            return None
        result.append(item["text"])
    return tuple(result)


def _contains_tool_declaration(value: object, *, root: bool = True) -> bool:
    if isinstance(value, dict):
        if value.get("type") == "additional_tools" or (not root and "tools" in value):
            return True
        return any(
            _contains_tool_declaration(item, root=False) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_tool_declaration(item, root=False) for item in value)
    return False


def _verify_request(
    value: _CapturedRequest,
    *,
    model: str,
    nonce: str,
    model_instructions: str,
    work: Path,
) -> dict[str, object]:
    headers = dict(value.headers)
    nonce_headers = [
        item for name, item in value.headers if name == "x-cc-isolation-nonce"
    ]
    body = value.body
    if body is None:
        raise CodexIsolationUnavailable(
            "Outbound Responses request differs from the no-tools contract."
        )
    input_items = body.get("input")
    metadata = body.get("client_metadata")
    if not isinstance(input_items, list) or len(input_items) != 3:
        raise CodexIsolationUnavailable("Probe request input is not exact.")
    developer_content = _message_content(input_items[0])
    environment_content = _message_content(input_items[1])
    prompt_content = _message_content(input_items[2])
    developer = input_items[0] if isinstance(input_items[0], dict) else {}
    environment_item = input_items[1] if isinstance(input_items[1], dict) else {}
    prompt_item = input_items[2] if isinstance(input_items[2], dict) else {}
    environment_text = environment_content[0] if environment_content else ""
    if (
        value.method != "POST"
        or value.path != _request_path(nonce)
        or set(body) != _EXPECTED_REQUEST_FIELDS
        or body.get("model") != model
        or body.get("instructions") != model_instructions
        or body.get("tools") != []
        or _contains_tool_declaration(body)
        or body.get("tool_choice") != "auto"
        or body.get("parallel_tool_calls") is not True
        or body.get("stream") is not True
        or body.get("store") is not False
        or body.get("include") != ["reasoning.encrypted_content"]
        or body.get("reasoning") != {"effort": "low"}
        or body.get("text") != {"verbosity": "low"}
        or developer.get("role") != "developer"
        or environment_item.get("role") != "user"
        or prompt_item.get("role") != "user"
        or developer_content is None
        or len(developer_content) != 2
        or not developer_content[0].startswith("<skills_instructions>\n")
        or not developer_content[0].endswith("</skills_instructions>")
        or not developer_content[1].startswith("<permissions instructions>\n")
        or "`sandbox_mode` is `read-only`" not in developer_content[1]
        or environment_content is None
        or len(environment_content) != 1
        or not environment_text.startswith("<environment_context>\n")
        or not environment_text.endswith("</environment_context>")
        or f"<cwd>{work}</cwd>" not in environment_text
        or f"<workspace_roots><root>{work}</root></workspace_roots>"
        not in environment_text
        or prompt_content != (_PROMPT,)
        or not isinstance(metadata, dict)
        or set(metadata)
        != {
            "turn_id",
            "x-codex-installation-id",
            "thread_id",
            "session_id",
            "x-codex-window-id",
            "x-codex-turn-metadata",
        }
        or nonce_headers != [nonce]
        or any(
            name in headers
            for name in ("authorization", "cookie", "proxy-authorization", "x-api-key")
        )
        or not headers.get("content-type", "").startswith("application/json")
    ):
        raise CodexIsolationUnavailable(
            "Outbound Responses request differs from the no-tools contract."
        )
    try:
        turn_metadata = json.loads(metadata["x-codex-turn-metadata"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CodexIsolationUnavailable("Codex request metadata is malformed.") from exc
    if (
        not isinstance(turn_metadata, dict)
        or set(turn_metadata)
        != {
            "installation_id",
            "session_id",
            "thread_id",
            "turn_id",
            "window_id",
            "request_kind",
            "thread_source",
            "sandbox",
            "turn_started_at_unix_ms",
        }
        or metadata["x-codex-installation-id"] != turn_metadata.get("installation_id")
        or metadata["session_id"] != turn_metadata.get("session_id")
        or metadata["thread_id"] != turn_metadata.get("thread_id")
        or metadata["turn_id"] != turn_metadata.get("turn_id")
        or metadata["x-codex-window-id"] != turn_metadata.get("window_id")
        or body.get("prompt_cache_key") != metadata["thread_id"]
        or turn_metadata.get("request_kind") != "turn"
        or turn_metadata.get("thread_source") != "user"
        or turn_metadata.get("sandbox") != "seatbelt"
        or not isinstance(turn_metadata.get("turn_started_at_unix_ms"), int)
    ):
        raise CodexIsolationUnavailable("Codex request metadata differs.")
    return {
        "schema_version": "codex-no-tools-request-semantics-v1",
        "model": model,
        "instructions_sha256": hashlib.sha256(model_instructions.encode()).hexdigest(),
        "input_roles": ["developer", "user", "user"],
        "input_content_sha256": [
            [hashlib.sha256(item.encode()).hexdigest() for item in developer_content],
            [hashlib.sha256(environment_text.encode()).hexdigest()],
            [hashlib.sha256(_PROMPT.encode()).hexdigest()],
        ],
        "model_visible_tools": [],
        "nonce_sha256": hashlib.sha256(nonce.encode()).hexdigest(),
    }


@dataclass(frozen=True)
class CodexIsolationReceipt:
    schema_version: str
    receipt_sha256: str
    package_version: str
    model: str
    authorization_scope: str
    live_runtime_authorized: bool
    native_format: str
    native_binary_sha256: str
    native_binary_bytes: int
    model_catalog_sha256: str
    config_sha256: str
    config_contract_sha256: str
    argv_sha256: str
    argv_contract_sha256: str
    environment_sha256: str
    environment_contract_sha256: str
    sandbox_exec_sha256: str
    sandbox_contract_sha256: str
    sandbox_profile_sha256: str
    endpoint_sha256: str
    capture_nonce_sha256: str
    response_path: str
    request_sha256: str
    request_semantics_sha256: str
    transcript_sha256: str
    tool_registry_sha256: str
    request_count: int
    model_visible_tools: tuple[str, ...]
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _RECEIPT_AUTHORITY
            or self.schema_version != ISOLATION_SCHEMA_VERSION
            or self.authorization_scope != "offline-measurement-only"
            or self.live_runtime_authorized is not False
            or self.request_count != 1
            or self.model_visible_tools != ()
            or self.response_path != _REQUEST_PATH_TEMPLATE
        ):
            raise CodexIsolationUnavailable("Isolation receipt is not verifier-issued.")
        _version_tuple(self.package_version)
        if not _MODEL.fullmatch(self.model):
            raise CodexIsolationUnavailable("Isolation receipt model is not closed.")
        for value in (
            self.receipt_sha256,
            self.native_binary_sha256,
            self.model_catalog_sha256,
            self.config_sha256,
            self.config_contract_sha256,
            self.argv_sha256,
            self.argv_contract_sha256,
            self.environment_sha256,
            self.environment_contract_sha256,
            self.sandbox_exec_sha256,
            self.sandbox_contract_sha256,
            self.sandbox_profile_sha256,
            self.endpoint_sha256,
            self.capture_nonce_sha256,
            self.request_sha256,
            self.request_semantics_sha256,
            self.transcript_sha256,
            self.tool_registry_sha256,
        ):
            _require_digest(value, "isolation receipt identity")

    def validate(self) -> bool:
        return verify_codex_isolation_receipt(self)

    def close(self) -> None:
        with _LIVE_AUTHORITY_LOCK:
            _ISSUED_RECEIPTS.pop(id(self), None)


def _receipt_identity_document(value: CodexIsolationReceipt) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "package_version": value.package_version,
        "model": value.model,
        "authorization_scope": value.authorization_scope,
        "live_runtime_authorized": value.live_runtime_authorized,
        "native_format": value.native_format,
        "native_binary_sha256": value.native_binary_sha256,
        "native_binary_bytes": value.native_binary_bytes,
        "model_catalog_sha256": value.model_catalog_sha256,
        "config_sha256": value.config_sha256,
        "config_contract_sha256": value.config_contract_sha256,
        "argv_sha256": value.argv_sha256,
        "argv_contract_sha256": value.argv_contract_sha256,
        "environment_sha256": value.environment_sha256,
        "environment_contract_sha256": value.environment_contract_sha256,
        "sandbox_exec_sha256": value.sandbox_exec_sha256,
        "sandbox_contract_sha256": value.sandbox_contract_sha256,
        "sandbox_profile_sha256": value.sandbox_profile_sha256,
        "endpoint_sha256": value.endpoint_sha256,
        "capture_nonce_sha256": value.capture_nonce_sha256,
        "response_path": value.response_path,
        "request_sha256": value.request_sha256,
        "request_semantics_sha256": value.request_semantics_sha256,
        "transcript_sha256": value.transcript_sha256,
        "tool_registry_sha256": value.tool_registry_sha256,
        "request_count": value.request_count,
        "model_visible_tools": list(value.model_visible_tools),
    }


def codex_isolation_receipt_document(
    value: CodexIsolationReceipt,
) -> dict[str, object]:
    """Return the value-suppressing identities retained by an accepted probe."""

    if not verify_codex_isolation_receipt(value):
        raise CodexIsolationUnavailable("Isolation receipt is not exact.")
    return {**_receipt_identity_document(value), "receipt_sha256": value.receipt_sha256}


def verify_codex_isolation_receipt(value: CodexIsolationReceipt) -> bool:
    if (
        not isinstance(value, CodexIsolationReceipt)
        or _ISSUED_RECEIPTS.get(id(value)) is not value
        or value._authority is not _RECEIPT_AUTHORITY
    ):
        return False
    try:
        _verify_contract_constants()
        return bool(
            value.config_contract_sha256 == _CONFIG_CONTRACT_SHA256
            and value.argv_contract_sha256 == _ARGV_CONTRACT_SHA256
            and value.environment_contract_sha256 == _ENVIRONMENT_CONTRACT_SHA256
            and value.sandbox_contract_sha256 == _SANDBOX_CONTRACT_SHA256
            and value.tool_registry_sha256 == _TOOL_REGISTRY_SHA256
            and value.receipt_sha256
            == canonical_sha256(_receipt_identity_document(value))
        )
    except (TypeError, ValueError, CodexIsolationUnavailable):
        return False


@dataclass
class _LiveAuthorizationState:
    receipt: weakref.ReferenceType[CodexIsolationReceipt]
    seal: object
    consumed: bool = False
    closed: bool = False


@dataclass
class _LivePermitState:
    receipt: weakref.ReferenceType[CodexIsolationReceipt]
    seal: object
    closed: bool = False


@dataclass(frozen=True)
class CodexLiveAuthorization:
    """A sealed, one-shot binding of official provenance to one measurement."""

    schema_version: str
    authorization_sha256: str
    framework_release_identity: str
    package_policy_sha256: str
    measurement_receipt_sha256: str
    package_version: str
    model: str
    native_binary_sha256: str
    native_binary_bytes: int
    model_catalog_sha256: str
    config_sha256: str
    config_contract_sha256: str
    argv_sha256: str
    argv_contract_sha256: str
    environment_sha256: str
    environment_contract_sha256: str
    sandbox_exec_sha256: str
    sandbox_contract_sha256: str
    sandbox_profile_sha256: str
    request_semantics_sha256: str
    transcript_sha256: str
    tool_registry_sha256: str
    model_visible_tools: tuple[str, ...]
    live_runtime_authorized: bool
    _state: _LiveAuthorizationState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _LIVE_AUTHORIZATION_AUTHORITY
            or self.schema_version != LIVE_AUTHORIZATION_SCHEMA_VERSION
            or self.live_runtime_authorized is not True
            or self.model_visible_tools != ()
        ):
            raise CodexIsolationUnavailable(
                "Codex live authorization is not verifier-issued."
            )
        for value in (
            self.authorization_sha256,
            self.framework_release_identity,
            self.package_policy_sha256,
            self.measurement_receipt_sha256,
            self.native_binary_sha256,
            self.model_catalog_sha256,
            self.config_sha256,
            self.config_contract_sha256,
            self.argv_sha256,
            self.argv_contract_sha256,
            self.environment_sha256,
            self.environment_contract_sha256,
            self.sandbox_exec_sha256,
            self.sandbox_contract_sha256,
            self.sandbox_profile_sha256,
            self.request_semantics_sha256,
            self.transcript_sha256,
            self.tool_registry_sha256,
        ):
            _require_digest(value, "Codex live authorization identity")

    def validate(self) -> bool:
        return verify_codex_live_authorization(self)

    def _consume_retained_inputs(
        self,
        inputs: _RetainedLiveInputs,
        *,
        authority: object,
    ) -> CodexLivePermit:
        """Atomically consume this authorization for exact retained inputs."""

        with _LIVE_AUTHORITY_LOCK:
            issued = _ISSUED_LIVE_AUTHORIZATIONS.get(id(self)) is self
            if not issued or authority is not _LIVE_DISPATCH_AUTHORITY:
                raise CodexIsolationUnavailable(
                    "Codex live authorization could not be consumed exactly."
                )
            valid = _verify_live_authorization_unlocked(self)
            self._state.consumed = True
            _ISSUED_LIVE_AUTHORIZATIONS.pop(id(self), None)
            if not valid or not inputs.validate():
                self._state.closed = True
                raise CodexIsolationUnavailable(
                    "Codex live authorization could not be consumed exactly."
                )
            receipt = self._state.receipt()
            if receipt is None or not verify_codex_isolation_receipt(receipt):
                self._state.closed = True
                raise CodexIsolationUnavailable(
                    "Codex live authorization measurement is unavailable."
                )
            seal = object()
            state = _LivePermitState(weakref.ref(receipt), seal)
            provisional = CodexLivePermit(
                schema_version=LIVE_PERMIT_SCHEMA_VERSION,
                permit_sha256="0" * 64,
                authorization_sha256=self.authorization_sha256,
                framework_release_identity=self.framework_release_identity,
                package_policy_sha256=self.package_policy_sha256,
                measurement_receipt_sha256=self.measurement_receipt_sha256,
                package_version=self.package_version,
                model=self.model,
                native_binary_sha256=self.native_binary_sha256,
                model_catalog_sha256=self.model_catalog_sha256,
                config_sha256=self.config_sha256,
                config_contract_sha256=self.config_contract_sha256,
                argv_sha256=self.argv_sha256,
                argv_contract_sha256=self.argv_contract_sha256,
                environment_contract_sha256=self.environment_contract_sha256,
                sandbox_contract_sha256=self.sandbox_contract_sha256,
                request_semantics_sha256=self.request_semantics_sha256,
                transcript_sha256=self.transcript_sha256,
                tool_registry_sha256=self.tool_registry_sha256,
                model_visible_tools=(),
                live_runtime_authorized=True,
                _state=state,
                _seal=seal,
                _authority=_LIVE_PERMIT_AUTHORITY,
            )
            permit = CodexLivePermit(
                **{
                    **provisional.__dict__,
                    "permit_sha256": canonical_sha256(
                        _live_permit_identity_document(provisional)
                    ),
                }
            )
            _ISSUED_LIVE_PERMITS[id(permit)] = permit
            return permit

    def close(self) -> None:
        with _LIVE_AUTHORITY_LOCK:
            if _ISSUED_LIVE_AUTHORIZATIONS.get(id(self)) is self:
                self._state.closed = True
                _ISSUED_LIVE_AUTHORIZATIONS.pop(id(self), None)

    def revoke(self) -> None:
        self.close()


@dataclass(frozen=True)
class CodexLivePermit:
    """Opaque, active capability produced by one authorization consumption."""

    schema_version: str
    permit_sha256: str
    authorization_sha256: str
    framework_release_identity: str
    package_policy_sha256: str
    measurement_receipt_sha256: str
    package_version: str
    model: str
    native_binary_sha256: str
    model_catalog_sha256: str
    config_sha256: str
    config_contract_sha256: str
    argv_sha256: str
    argv_contract_sha256: str
    environment_contract_sha256: str
    sandbox_contract_sha256: str
    request_semantics_sha256: str
    transcript_sha256: str
    tool_registry_sha256: str
    model_visible_tools: tuple[str, ...]
    live_runtime_authorized: bool
    _state: _LivePermitState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _LIVE_PERMIT_AUTHORITY
            or self.schema_version != LIVE_PERMIT_SCHEMA_VERSION
            or self.live_runtime_authorized is not True
            or self.model_visible_tools != ()
        ):
            raise CodexIsolationUnavailable("Codex live permit is not verifier-issued.")
        for value in (
            self.permit_sha256,
            self.authorization_sha256,
            self.framework_release_identity,
            self.package_policy_sha256,
            self.measurement_receipt_sha256,
            self.native_binary_sha256,
            self.model_catalog_sha256,
            self.config_sha256,
            self.config_contract_sha256,
            self.argv_sha256,
            self.argv_contract_sha256,
            self.environment_contract_sha256,
            self.sandbox_contract_sha256,
            self.request_semantics_sha256,
            self.transcript_sha256,
            self.tool_registry_sha256,
        ):
            _require_digest(value, "Codex live permit identity")

    def validate(self) -> bool:
        return verify_codex_live_permit(self)

    def close(self) -> None:
        with _LIVE_AUTHORITY_LOCK:
            if _ISSUED_LIVE_PERMITS.get(id(self)) is self:
                self._state.closed = True
                _ISSUED_LIVE_PERMITS.pop(id(self), None)

    def __enter__(self) -> CodexLivePermit:
        if not self.validate():
            raise CodexIsolationUnavailable("Codex live permit is not active.")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _live_authorization_identity_document(
    value: CodexLiveAuthorization,
) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "framework_release_identity": value.framework_release_identity,
        "package_policy_sha256": value.package_policy_sha256,
        "measurement_receipt_sha256": value.measurement_receipt_sha256,
        "package_version": value.package_version,
        "model": value.model,
        "native_binary_sha256": value.native_binary_sha256,
        "native_binary_bytes": value.native_binary_bytes,
        "model_catalog_sha256": value.model_catalog_sha256,
        "config_sha256": value.config_sha256,
        "config_contract_sha256": value.config_contract_sha256,
        "argv_sha256": value.argv_sha256,
        "argv_contract_sha256": value.argv_contract_sha256,
        "environment_sha256": value.environment_sha256,
        "environment_contract_sha256": value.environment_contract_sha256,
        "sandbox_exec_sha256": value.sandbox_exec_sha256,
        "sandbox_contract_sha256": value.sandbox_contract_sha256,
        "sandbox_profile_sha256": value.sandbox_profile_sha256,
        "request_semantics_sha256": value.request_semantics_sha256,
        "transcript_sha256": value.transcript_sha256,
        "tool_registry_sha256": value.tool_registry_sha256,
        "model_visible_tools": list(value.model_visible_tools),
        "live_runtime_authorized": value.live_runtime_authorized,
    }


def _live_permit_identity_document(value: CodexLivePermit) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "authorization_sha256": value.authorization_sha256,
        "framework_release_identity": value.framework_release_identity,
        "package_policy_sha256": value.package_policy_sha256,
        "measurement_receipt_sha256": value.measurement_receipt_sha256,
        "package_version": value.package_version,
        "model": value.model,
        "native_binary_sha256": value.native_binary_sha256,
        "model_catalog_sha256": value.model_catalog_sha256,
        "config_sha256": value.config_sha256,
        "config_contract_sha256": value.config_contract_sha256,
        "argv_sha256": value.argv_sha256,
        "argv_contract_sha256": value.argv_contract_sha256,
        "environment_contract_sha256": value.environment_contract_sha256,
        "sandbox_contract_sha256": value.sandbox_contract_sha256,
        "request_semantics_sha256": value.request_semantics_sha256,
        "transcript_sha256": value.transcript_sha256,
        "tool_registry_sha256": value.tool_registry_sha256,
        "model_visible_tools": list(value.model_visible_tools),
        "live_runtime_authorized": value.live_runtime_authorized,
    }


def _authorization_matches_receipt(
    value: CodexLiveAuthorization,
    receipt: CodexIsolationReceipt,
) -> bool:
    return bool(
        value.measurement_receipt_sha256 == receipt.receipt_sha256
        and value.package_version == receipt.package_version
        and value.model == receipt.model
        and value.native_binary_sha256 == receipt.native_binary_sha256
        and value.native_binary_bytes == receipt.native_binary_bytes
        and value.model_catalog_sha256 == receipt.model_catalog_sha256
        and value.config_sha256 == receipt.config_sha256
        and value.config_contract_sha256 == receipt.config_contract_sha256
        and value.argv_sha256 == receipt.argv_sha256
        and value.argv_contract_sha256 == receipt.argv_contract_sha256
        and value.environment_sha256 == receipt.environment_sha256
        and value.environment_contract_sha256 == receipt.environment_contract_sha256
        and value.sandbox_exec_sha256 == receipt.sandbox_exec_sha256
        and value.sandbox_contract_sha256 == receipt.sandbox_contract_sha256
        and value.sandbox_profile_sha256 == receipt.sandbox_profile_sha256
        and value.request_semantics_sha256 == receipt.request_semantics_sha256
        and value.transcript_sha256 == receipt.transcript_sha256
        and value.tool_registry_sha256 == receipt.tool_registry_sha256
        and value.model_visible_tools == receipt.model_visible_tools
    )


def _verify_live_authorization_unlocked(value: CodexLiveAuthorization) -> bool:
    receipt = value._state.receipt()
    try:
        _verify_release_contract_constants()
        return bool(
            _ISSUED_LIVE_AUTHORIZATIONS.get(id(value)) is value
            and value._authority is _LIVE_AUTHORIZATION_AUTHORITY
            and value._seal is value._state.seal
            and not value._state.consumed
            and not value._state.closed
            and receipt is not None
            and verify_codex_isolation_receipt(receipt)
            and value.framework_release_identity
            == OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
            and value.package_policy_sha256 == OFFICIAL_CODEX_PACKAGE_POLICY_SHA256
            and value.package_version == OFFICIAL_CODEX_VERSION
            and value.model == OFFICIAL_CODEX_MODEL
            and value.native_binary_sha256 == OFFICIAL_CODEX_NATIVE_SHA256
            and value.native_binary_bytes == OFFICIAL_CODEX_NATIVE_BYTES
            and value.model_catalog_sha256 == OFFICIAL_CODEX_CATALOG_SHA256
            and value.config_contract_sha256 == _CONFIG_CONTRACT_SHA256
            and value.argv_contract_sha256 == _ARGV_CONTRACT_SHA256
            and value.environment_contract_sha256 == _ENVIRONMENT_CONTRACT_SHA256
            and value.sandbox_contract_sha256 == _SANDBOX_CONTRACT_SHA256
            and value.tool_registry_sha256 == _TOOL_REGISTRY_SHA256
            and value.model_visible_tools == ()
            and _authorization_matches_receipt(value, receipt)
            and value.authorization_sha256
            == canonical_sha256(_live_authorization_identity_document(value))
        )
    except (TypeError, ValueError, CodexIsolationUnavailable):
        return False


def verify_codex_live_authorization(value: CodexLiveAuthorization) -> bool:
    if not isinstance(value, CodexLiveAuthorization):
        return False
    with _LIVE_AUTHORITY_LOCK:
        return _verify_live_authorization_unlocked(value)


def _permit_matches_receipt(
    value: CodexLivePermit,
    receipt: CodexIsolationReceipt,
) -> bool:
    return bool(
        value.measurement_receipt_sha256 == receipt.receipt_sha256
        and value.package_version == receipt.package_version
        and value.model == receipt.model
        and value.native_binary_sha256 == receipt.native_binary_sha256
        and value.model_catalog_sha256 == receipt.model_catalog_sha256
        and value.config_sha256 == receipt.config_sha256
        and value.config_contract_sha256 == receipt.config_contract_sha256
        and value.argv_sha256 == receipt.argv_sha256
        and value.argv_contract_sha256 == receipt.argv_contract_sha256
        and value.environment_contract_sha256 == receipt.environment_contract_sha256
        and value.sandbox_contract_sha256 == receipt.sandbox_contract_sha256
        and value.request_semantics_sha256 == receipt.request_semantics_sha256
        and value.transcript_sha256 == receipt.transcript_sha256
        and value.tool_registry_sha256 == receipt.tool_registry_sha256
        and value.model_visible_tools == receipt.model_visible_tools
    )


def verify_codex_live_permit(value: CodexLivePermit) -> bool:
    if not isinstance(value, CodexLivePermit):
        return False
    with _LIVE_AUTHORITY_LOCK:
        receipt = value._state.receipt()
        try:
            _verify_release_contract_constants()
            return bool(
                _ISSUED_LIVE_PERMITS.get(id(value)) is value
                and value._authority is _LIVE_PERMIT_AUTHORITY
                and value._seal is value._state.seal
                and not value._state.closed
                and receipt is not None
                and verify_codex_isolation_receipt(receipt)
                and value.framework_release_identity
                == OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
                and value.package_policy_sha256 == OFFICIAL_CODEX_PACKAGE_POLICY_SHA256
                and value.package_version == OFFICIAL_CODEX_VERSION
                and value.model == OFFICIAL_CODEX_MODEL
                and value.native_binary_sha256 == OFFICIAL_CODEX_NATIVE_SHA256
                and value.model_catalog_sha256 == OFFICIAL_CODEX_CATALOG_SHA256
                and value.config_contract_sha256 == _CONFIG_CONTRACT_SHA256
                and value.argv_contract_sha256 == _ARGV_CONTRACT_SHA256
                and value.environment_contract_sha256 == _ENVIRONMENT_CONTRACT_SHA256
                and value.sandbox_contract_sha256 == _SANDBOX_CONTRACT_SHA256
                and value.tool_registry_sha256 == _TOOL_REGISTRY_SHA256
                and value.model_visible_tools == ()
                and _permit_matches_receipt(value, receipt)
                and value.permit_sha256
                == canonical_sha256(_live_permit_identity_document(value))
            )
        except (TypeError, ValueError, CodexIsolationUnavailable):
            return False


@dataclass
class _LiveDispatchState:
    inputs: _RetainedLiveInputs
    retained_root: _RetainedPrivateRoot
    staged_native: _RetainedLiveInput
    staged_catalog: _RetainedLiveInput
    permit: CodexLivePermit
    seal: object
    consumed: bool = False
    running: bool = False
    closed: bool = False


@dataclass
class _LiveDispatchContextState:
    dispatch: weakref.ReferenceType[CodexLiveDispatch]
    seal: object


@dataclass(frozen=True)
class CodexLiveDispatchContext:
    """One callback-scoped view of retained, privately staged live inputs."""

    schema_version: str
    context_sha256: str
    dispatch_sha256: str
    authorization_sha256: str
    permit_sha256: str
    native_binary: Path
    model_catalog: Path
    model: str
    _state: _LiveDispatchContextState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _LIVE_DISPATCH_CONTEXT_AUTHORITY
            or self.schema_version != LIVE_DISPATCH_CONTEXT_SCHEMA_VERSION
            or not self.native_binary.is_absolute()
            or not self.model_catalog.is_absolute()
            or self.model != OFFICIAL_CODEX_MODEL
        ):
            raise CodexIsolationUnavailable(
                "Codex live dispatch context is not verifier-issued."
            )
        for value in (
            self.context_sha256,
            self.dispatch_sha256,
            self.authorization_sha256,
            self.permit_sha256,
        ):
            _require_digest(value, "Codex live dispatch context identity")

    def validate(self) -> bool:
        return verify_codex_live_dispatch_context(self)


@dataclass(frozen=True)
class CodexLiveDispatch:
    """A sealed, exception-safe capability for exactly one adapter callback."""

    schema_version: str
    dispatch_sha256: str
    authorization_sha256: str
    permit_sha256: str
    framework_release_identity: str
    package_policy_sha256: str
    measurement_receipt_sha256: str
    model: str
    native_binary_sha256: str
    model_catalog_sha256: str
    tool_registry_sha256: str
    live_runtime_authorized: bool
    _state: _LiveDispatchState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _LIVE_DISPATCH_AUTHORITY
            or self.schema_version != LIVE_DISPATCH_SCHEMA_VERSION
            or self.live_runtime_authorized is not True
            or self.model != OFFICIAL_CODEX_MODEL
        ):
            raise CodexIsolationUnavailable(
                "Codex live dispatch is not verifier-issued."
            )
        for value in (
            self.dispatch_sha256,
            self.authorization_sha256,
            self.permit_sha256,
            self.framework_release_identity,
            self.package_policy_sha256,
            self.measurement_receipt_sha256,
            self.native_binary_sha256,
            self.model_catalog_sha256,
            self.tool_registry_sha256,
        ):
            _require_digest(value, "Codex live dispatch identity")

    def validate(self) -> bool:
        return verify_codex_live_dispatch(self)

    def run_once(self, callback: Any) -> Any:
        """Invoke one callback with staged retained inputs, then revoke everything."""

        if not callable(callback):
            raise CodexIsolationUnavailable("Codex live callback is not callable.")
        with _LIVE_AUTHORITY_LOCK:
            if (
                self._state.consumed
                or self._state.running
                or not _verify_codex_live_dispatch_unlocked(self)
            ):
                raise CodexIsolationUnavailable(
                    "Codex live dispatch is unavailable or already consumed."
                )
            self._state.consumed = True
            self._state.running = True
            seal = object()
            context_state = _LiveDispatchContextState(weakref.ref(self), seal)
            provisional = CodexLiveDispatchContext(
                schema_version=LIVE_DISPATCH_CONTEXT_SCHEMA_VERSION,
                context_sha256="0" * 64,
                dispatch_sha256=self.dispatch_sha256,
                authorization_sha256=self.authorization_sha256,
                permit_sha256=self.permit_sha256,
                native_binary=self._state.staged_native.path,
                model_catalog=self._state.staged_catalog.path,
                model=self.model,
                _state=context_state,
                _seal=seal,
                _authority=_LIVE_DISPATCH_CONTEXT_AUTHORITY,
            )
            context = CodexLiveDispatchContext(
                **{
                    **provisional.__dict__,
                    "context_sha256": canonical_sha256(
                        _live_dispatch_context_identity_document(provisional)
                    ),
                }
            )
            _ISSUED_LIVE_DISPATCH_CONTEXTS[id(context)] = context
        try:
            result = callback(context)
        except BaseException as exc:
            with _LIVE_AUTHORITY_LOCK:
                cleanup_error = _finish_live_dispatch_unlocked(self, context=context)
            if cleanup_error is not None:
                raise cleanup_error from exc
            raise
        with _LIVE_AUTHORITY_LOCK:
            post_valid = verify_codex_live_dispatch_context(context)
            cleanup_error = _finish_live_dispatch_unlocked(self, context=context)
        if cleanup_error is not None:
            raise cleanup_error
        if not post_valid:
            raise CodexIsolationUnavailable(
                "Codex live inputs changed during the dispatch callback."
            )
        return result

    def close(self) -> None:
        with _LIVE_AUTHORITY_LOCK:
            if _ISSUED_LIVE_DISPATCHES.get(id(self)) is self:
                if self._state.running:
                    raise CodexIsolationUnavailable(
                        "Codex live dispatch cannot close during its callback."
                    )
                error = _finish_live_dispatch_unlocked(self)
                if error is not None:
                    raise error

    def revoke(self) -> None:
        self.close()


def _live_dispatch_identity_document(value: CodexLiveDispatch) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "authorization_sha256": value.authorization_sha256,
        "permit_sha256": value.permit_sha256,
        "framework_release_identity": value.framework_release_identity,
        "package_policy_sha256": value.package_policy_sha256,
        "measurement_receipt_sha256": value.measurement_receipt_sha256,
        "model": value.model,
        "native_binary_sha256": value.native_binary_sha256,
        "model_catalog_sha256": value.model_catalog_sha256,
        "tool_registry_sha256": value.tool_registry_sha256,
        "live_runtime_authorized": value.live_runtime_authorized,
    }


def _live_dispatch_context_identity_document(
    value: CodexLiveDispatchContext,
) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "dispatch_sha256": value.dispatch_sha256,
        "authorization_sha256": value.authorization_sha256,
        "permit_sha256": value.permit_sha256,
        "native_binary": value.native_binary.name,
        "model_catalog": value.model_catalog.name,
        "model": value.model,
    }


def _live_dispatch_materials_validate(value: CodexLiveDispatch) -> bool:
    state = value._state
    return bool(
        state.inputs.validate()
        and state.retained_root.validate()
        and state.staged_native.validate()
        and state.staged_catalog.validate()
        and state.permit.validate()
        and state.permit.permit_sha256 == value.permit_sha256
        and state.permit.authorization_sha256 == value.authorization_sha256
        and state.staged_native.sha256 == value.native_binary_sha256
        and state.staged_catalog.sha256 == value.model_catalog_sha256
    )


def _verify_codex_live_dispatch_unlocked(value: CodexLiveDispatch) -> bool:
    try:
        _verify_release_contract_constants()
        return bool(
            _ISSUED_LIVE_DISPATCHES.get(id(value)) is value
            and value._authority is _LIVE_DISPATCH_AUTHORITY
            and value._seal is value._state.seal
            and not value._state.closed
            and (not value._state.consumed or value._state.running)
            and value.authorization_sha256 == value._state.permit.authorization_sha256
            and value.permit_sha256 == value._state.permit.permit_sha256
            and value.framework_release_identity
            == OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
            and value.package_policy_sha256 == OFFICIAL_CODEX_PACKAGE_POLICY_SHA256
            and value.model == OFFICIAL_CODEX_MODEL
            and value.native_binary_sha256 == OFFICIAL_CODEX_NATIVE_SHA256
            and value.model_catalog_sha256 == OFFICIAL_CODEX_CATALOG_SHA256
            and value.tool_registry_sha256 == _TOOL_REGISTRY_SHA256
            and value.dispatch_sha256
            == canonical_sha256(_live_dispatch_identity_document(value))
            and _live_dispatch_materials_validate(value)
        )
    except (TypeError, ValueError, CodexIsolationUnavailable):
        return False


def verify_codex_live_dispatch(value: CodexLiveDispatch) -> bool:
    if not isinstance(value, CodexLiveDispatch):
        return False
    with _LIVE_AUTHORITY_LOCK:
        return _verify_codex_live_dispatch_unlocked(value)


def verify_codex_live_dispatch_context(value: CodexLiveDispatchContext) -> bool:
    if not isinstance(value, CodexLiveDispatchContext):
        return False
    with _LIVE_AUTHORITY_LOCK:
        dispatch = value._state.dispatch()
        try:
            return bool(
                _ISSUED_LIVE_DISPATCH_CONTEXTS.get(id(value)) is value
                and value._authority is _LIVE_DISPATCH_CONTEXT_AUTHORITY
                and value._seal is value._state.seal
                and dispatch is not None
                and dispatch._state.running
                and _verify_codex_live_dispatch_unlocked(dispatch)
                and value.dispatch_sha256 == dispatch.dispatch_sha256
                and value.authorization_sha256 == dispatch.authorization_sha256
                and value.permit_sha256 == dispatch.permit_sha256
                and value.native_binary == dispatch._state.staged_native.path
                and value.model_catalog == dispatch._state.staged_catalog.path
                and value.model == dispatch.model
                and value.context_sha256
                == canonical_sha256(_live_dispatch_context_identity_document(value))
            )
        except (TypeError, ValueError, CodexIsolationUnavailable):
            return False


def _finish_live_dispatch_unlocked(
    value: CodexLiveDispatch,
    *,
    context: CodexLiveDispatchContext | None = None,
) -> CodexIsolationUnavailable | None:
    if _ISSUED_LIVE_DISPATCHES.get(id(value)) is not value:
        return None
    if context is not None:
        _ISSUED_LIVE_DISPATCH_CONTEXTS.pop(id(context), None)
    state = value._state
    state.running = False
    state.closed = True
    _ISSUED_LIVE_DISPATCHES.pop(id(value), None)
    state.permit.close()
    state.staged_native.close()
    state.staged_catalog.close()
    state.inputs.close()
    error: CodexIsolationUnavailable | None = None
    try:
        state.retained_root.remove()
    except CodexIsolationUnavailable as exc:
        error = exc
    finally:
        state.retained_root.close()
    return error


def authorize_codex_live_runtime(
    receipt: CodexIsolationReceipt,
    *,
    framework_release_identity: str,
    expected_package_policy: str,
) -> CodexLiveAuthorization:
    """Bind one authentic offline measurement to the pinned official release."""

    with _LIVE_AUTHORITY_LOCK:
        _verify_release_contract_constants()
        if (
            framework_release_identity != OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
            or expected_package_policy != OFFICIAL_CODEX_PACKAGE_POLICY_SHA256
            or not verify_codex_isolation_receipt(receipt)
            or receipt.package_version != OFFICIAL_CODEX_VERSION
            or receipt.model != OFFICIAL_CODEX_MODEL
            or receipt.native_format != "mach-o"
            or receipt.native_binary_sha256 != OFFICIAL_CODEX_NATIVE_SHA256
            or receipt.native_binary_bytes != OFFICIAL_CODEX_NATIVE_BYTES
            or receipt.model_catalog_sha256 != OFFICIAL_CODEX_CATALOG_SHA256
            or receipt.config_contract_sha256 != _CONFIG_CONTRACT_SHA256
            or receipt.argv_contract_sha256 != _ARGV_CONTRACT_SHA256
            or receipt.environment_contract_sha256 != _ENVIRONMENT_CONTRACT_SHA256
            or receipt.sandbox_contract_sha256 != _SANDBOX_CONTRACT_SHA256
            or receipt.tool_registry_sha256 != _TOOL_REGISTRY_SHA256
            or receipt.model_visible_tools != ()
        ):
            raise CodexIsolationUnavailable(
                "Codex measurement does not match the official package policy."
            )
        prior = _AUTHORIZED_RECEIPTS.get(id(receipt))
        if prior is not None and prior() is receipt:
            raise CodexIsolationUnavailable(
                "Codex measurement was already bound to an authorization."
            )

        receipt_id = id(receipt)

        def release_marker(
            reference: weakref.ReferenceType[CodexIsolationReceipt],
        ) -> None:
            with _LIVE_AUTHORITY_LOCK:
                if _AUTHORIZED_RECEIPTS.get(receipt_id) is reference:
                    _AUTHORIZED_RECEIPTS.pop(receipt_id, None)

        receipt_reference = weakref.ref(receipt, release_marker)
        _AUTHORIZED_RECEIPTS[receipt_id] = receipt_reference
        seal = object()
        state = _LiveAuthorizationState(receipt_reference, seal)
        try:
            provisional = CodexLiveAuthorization(
                schema_version=LIVE_AUTHORIZATION_SCHEMA_VERSION,
                authorization_sha256="0" * 64,
                framework_release_identity=OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY,
                package_policy_sha256=OFFICIAL_CODEX_PACKAGE_POLICY_SHA256,
                measurement_receipt_sha256=receipt.receipt_sha256,
                package_version=receipt.package_version,
                model=receipt.model,
                native_binary_sha256=receipt.native_binary_sha256,
                native_binary_bytes=receipt.native_binary_bytes,
                model_catalog_sha256=receipt.model_catalog_sha256,
                config_sha256=receipt.config_sha256,
                config_contract_sha256=receipt.config_contract_sha256,
                argv_sha256=receipt.argv_sha256,
                argv_contract_sha256=receipt.argv_contract_sha256,
                environment_sha256=receipt.environment_sha256,
                environment_contract_sha256=receipt.environment_contract_sha256,
                sandbox_exec_sha256=receipt.sandbox_exec_sha256,
                sandbox_contract_sha256=receipt.sandbox_contract_sha256,
                sandbox_profile_sha256=receipt.sandbox_profile_sha256,
                request_semantics_sha256=receipt.request_semantics_sha256,
                transcript_sha256=receipt.transcript_sha256,
                tool_registry_sha256=receipt.tool_registry_sha256,
                model_visible_tools=(),
                live_runtime_authorized=True,
                _state=state,
                _seal=seal,
                _authority=_LIVE_AUTHORIZATION_AUTHORITY,
            )
            authorization = CodexLiveAuthorization(
                **{
                    **provisional.__dict__,
                    "authorization_sha256": canonical_sha256(
                        _live_authorization_identity_document(provisional)
                    ),
                }
            )
            _ISSUED_LIVE_AUTHORIZATIONS[id(authorization)] = authorization
            return authorization
        except Exception:
            if _AUTHORIZED_RECEIPTS.get(receipt_id) is receipt_reference:
                _AUTHORIZED_RECEIPTS.pop(receipt_id, None)
            raise


def retain_codex_live_dispatch(
    authorization: CodexLiveAuthorization,
    *,
    native_binary: Path,
    model_catalog: Path,
    model: str,
) -> CodexLiveDispatch:
    """Retain exact official inputs and consume one authorization into one dispatch."""

    _verify_release_contract_constants()
    if (
        not isinstance(native_binary, Path)
        or not isinstance(model_catalog, Path)
        or model != OFFICIAL_CODEX_MODEL
        or not verify_codex_live_authorization(authorization)
    ):
        raise CodexIsolationUnavailable(
            "Codex live authorization or model is unavailable."
        )
    native: _RetainedLiveInput | None = None
    catalog: _RetainedLiveInput | None = None
    retained_root: _RetainedPrivateRoot | None = None
    staged_native: _RetainedLiveInput | None = None
    staged_catalog: _RetainedLiveInput | None = None
    permit: CodexLivePermit | None = None
    dispatch: CodexLiveDispatch | None = None
    inputs: _RetainedLiveInputs | None = None
    issued = False
    try:
        native = _RetainedLiveInput(
            Path(native_binary),
            expected_name="codex",
            expected_mode=0o755,
            maximum=_MAX_BINARY_BYTES,
            expected_sha256=OFFICIAL_CODEX_NATIVE_SHA256,
            expected_bytes=OFFICIAL_CODEX_NATIVE_BYTES,
        )
        catalog = _RetainedLiveInput(
            Path(model_catalog),
            expected_name="codex-model-catalog.json",
            expected_mode=0o600,
            maximum=_MAX_CATALOG_BYTES,
            expected_sha256=OFFICIAL_CODEX_CATALOG_SHA256,
        )
        if _native_format(native.content) != "mach-o":
            raise CodexIsolationUnavailable("Official Codex native format differs.")
        _verify_catalog(
            catalog.content,
            package_version=OFFICIAL_CODEX_VERSION,
            model=OFFICIAL_CODEX_MODEL,
        )
        inputs = _RetainedLiveInputs(
            native=native,
            catalog=catalog,
            model=model,
            _seal=object(),
            _authority=_LIVE_INPUT_AUTHORITY,
        )
        with _LIVE_AUTHORITY_LOCK:
            _ISSUED_LIVE_INPUTS[id(inputs)] = inputs
        temporary = tempfile.mkdtemp(prefix="cc-codex-live-dispatch-")
        private_root = Path(temporary).resolve()
        os.chmod(private_root, 0o700)
        retained_root = _RetainedPrivateRoot(private_root, ())
        staged_native_path = _stage_file_at(
            retained_root,
            "codex",
            native.content,
            0o755,
        )
        staged_catalog_path = _stage_file_at(
            retained_root,
            "codex-model-catalog.json",
            catalog.content,
            0o600,
        )
        retained_root.bind_expected_entries(
            ("codex", "codex-model-catalog.json"),
            retained_directories=(),
        )
        staged_native = _RetainedLiveInput(
            staged_native_path,
            expected_name="codex",
            expected_mode=0o755,
            maximum=_MAX_BINARY_BYTES,
            expected_sha256=OFFICIAL_CODEX_NATIVE_SHA256,
            expected_bytes=OFFICIAL_CODEX_NATIVE_BYTES,
        )
        staged_catalog = _RetainedLiveInput(
            staged_catalog_path,
            expected_name="codex-model-catalog.json",
            expected_mode=0o600,
            maximum=_MAX_CATALOG_BYTES,
            expected_sha256=OFFICIAL_CODEX_CATALOG_SHA256,
        )
        if (
            (staged_native.parent_identity[0], staged_native.parent_identity[1])
            != retained_root.root_identity
            or (staged_catalog.parent_identity[0], staged_catalog.parent_identity[1])
            != retained_root.root_identity
            or not inputs.validate()
            or not staged_native.validate()
            or not staged_catalog.validate()
            or not retained_root.validate()
        ):
            raise CodexIsolationUnavailable(
                "Codex live inputs changed during private staging."
            )
        permit = authorization._consume_retained_inputs(
            inputs,
            authority=_LIVE_DISPATCH_AUTHORITY,
        )
        seal = object()
        state = _LiveDispatchState(
            inputs=inputs,
            retained_root=retained_root,
            staged_native=staged_native,
            staged_catalog=staged_catalog,
            permit=permit,
            seal=seal,
        )
        provisional = CodexLiveDispatch(
            schema_version=LIVE_DISPATCH_SCHEMA_VERSION,
            dispatch_sha256="0" * 64,
            authorization_sha256=authorization.authorization_sha256,
            permit_sha256=permit.permit_sha256,
            framework_release_identity=authorization.framework_release_identity,
            package_policy_sha256=authorization.package_policy_sha256,
            measurement_receipt_sha256=authorization.measurement_receipt_sha256,
            model=model,
            native_binary_sha256=staged_native.sha256,
            model_catalog_sha256=staged_catalog.sha256,
            tool_registry_sha256=authorization.tool_registry_sha256,
            live_runtime_authorized=True,
            _state=state,
            _seal=seal,
            _authority=_LIVE_DISPATCH_AUTHORITY,
        )
        dispatch = CodexLiveDispatch(
            **{
                **provisional.__dict__,
                "dispatch_sha256": canonical_sha256(
                    _live_dispatch_identity_document(provisional)
                ),
            }
        )
        with _LIVE_AUTHORITY_LOCK:
            _ISSUED_LIVE_DISPATCHES[id(dispatch)] = dispatch
        if not dispatch.validate():
            raise CodexIsolationUnavailable(
                "Codex live dispatch could not be issued exactly."
            )
        issued = True
        return dispatch
    except CodexIsolationUnavailable:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise CodexIsolationUnavailable(
            "Codex live dispatch retention failed closed."
        ) from exc
    finally:
        if not issued:
            if dispatch is not None:
                with _LIVE_AUTHORITY_LOCK:
                    _finish_live_dispatch_unlocked(dispatch)
            else:
                if permit is not None:
                    permit.close()
                if staged_native is not None:
                    staged_native.close()
                if staged_catalog is not None:
                    staged_catalog.close()
                if inputs is not None:
                    inputs.close()
                else:
                    if native is not None:
                        native.close()
                    if catalog is not None:
                        catalog.close()
                if retained_root is not None:
                    try:
                        retained_root.remove()
                    except CodexIsolationUnavailable:
                        pass
                    finally:
                        retained_root.close()


def probe_codex_isolation(
    binary: Path,
    model_catalog: Path,
    *,
    package_version: str,
    expected_native_sha256: str,
    expected_catalog_sha256: str,
    model: str,
) -> CodexIsolationReceipt:
    """Measure one offline request; never authorize a live Codex runtime."""

    _verify_contract_constants()
    _version_tuple(package_version)
    _require_digest(expected_native_sha256, "native Codex binary")
    _require_digest(expected_catalog_sha256, "model catalog")
    if not _MODEL.fullmatch(model):
        raise CodexIsolationUnavailable("Model identity is not a closed slug.")
    binary_input: _RetainedInput | None = None
    catalog_input: _RetainedInput | None = None
    try:
        binary_input = _RetainedInput(
            Path(binary),
            expected_name="codex",
            expected_mode=0o755,
            maximum=_MAX_BINARY_BYTES,
            expected_sha256=expected_native_sha256,
        )
        catalog_input = _RetainedInput(
            Path(model_catalog),
            expected_name="codex-model-catalog.json",
            expected_mode=0o600,
            maximum=_MAX_CATALOG_BYTES,
            expected_sha256=expected_catalog_sha256,
        )
        native_format = _native_format(binary_input.content)
        model_instructions = _verify_catalog(
            catalog_input.content,
            package_version=package_version,
            model=model,
        )
        nonce = secrets.token_hex(32)
        _request_path(nonce)
        sandbox_exec_sha256, _sandbox_bytes = _sandbox_exec_identity()
        temporary = tempfile.mkdtemp(prefix="cc-codex-isolation-")
        private_root = Path(temporary).resolve()
        os.chmod(private_root, 0o700)
        retained_root: _RetainedPrivateRoot | None = None
        try:
            retained_root = _RetainedPrivateRoot(private_root, ())
            for name in ("home", "codex-home", "tmp", "work"):
                (private_root / name).mkdir(mode=0o700)
            staged_binary = _stage_file(
                private_root,
                "codex",
                binary_input.content,
                0o755,
            )
            staged_catalog = _stage_file(
                private_root,
                "codex-model-catalog.json",
                catalog_input.content,
                0o600,
            )
            retained_root.bind_expected_entries(
                (
                    "codex",
                    "codex-home",
                    "codex-model-catalog.json",
                    "home",
                    "tmp",
                    "work",
                ),
                retained_directories=("home", "codex-home", "tmp", "work"),
            )
            staged_binary_input = _RetainedInput(
                staged_binary,
                expected_name="codex",
                expected_mode=0o755,
                maximum=_MAX_BINARY_BYTES,
                expected_sha256=expected_native_sha256,
            )
            staged_catalog_input = _RetainedInput(
                staged_catalog,
                expected_name="codex-model-catalog.json",
                expected_mode=0o600,
                maximum=_MAX_CATALOG_BYTES,
                expected_sha256=expected_catalog_sha256,
            )
            try:
                environment = _private_environment(private_root)
                with _LoopbackCapture(nonce) as capture:
                    endpoint = capture.endpoint
                    _require_loopback_endpoint(endpoint, nonce=nonce)
                    profile = _sandbox_profile(
                        private_root,
                        endpoint=endpoint,
                        nonce=nonce,
                    )
                    _verify_private_environment(
                        environment,
                        private_root=private_root,
                        retained_root=retained_root,
                    )
                    _run_version(
                        staged_binary,
                        profile=profile,
                        environment=environment,
                        expected_version=package_version,
                        work=private_root / "work",
                        retained_root=retained_root,
                    )
                    if (
                        capture.server.interaction_count
                        or capture.server.captures
                        or capture.server.aggregate_body_bytes
                        or capture.server.capture_overflow
                    ):
                        raise CodexIsolationUnavailable(
                            "Codex version probe attempted a network request."
                        )
                    argv = _codex_argv(
                        sandbox_profile=profile,
                        binary=staged_binary,
                        work=private_root / "work",
                        catalog=staged_catalog,
                        endpoint=endpoint,
                        model=model,
                        nonce=nonce,
                    )
                    _verify_runtime_contracts(
                        argv=argv,
                        environment=environment,
                        sandbox_profile=profile,
                        private_root=private_root,
                        binary=staged_binary,
                        work=private_root / "work",
                        catalog=staged_catalog,
                        endpoint=endpoint,
                        model=model,
                        nonce=nonce,
                        retained_root=retained_root,
                    )
                    try:
                        completed = _run_process_group(
                            argv,
                            work=private_root / "work",
                            environment=environment,
                            timeout=_REQUEST_TIMEOUT_SECONDS,
                            capture_output=False,
                            retained_root=retained_root,
                        )
                    except CodexIsolationUnavailable as exc:
                        raise CodexIsolationUnavailable(
                            "Codex request probe failed closed."
                        ) from exc
                if (
                    completed.returncode != 1
                    or capture.server.interaction_count != 1
                    or len(capture.server.captures) != 1
                    or capture.server.capture_overflow
                    or capture.server.aggregate_body_bytes
                    != len(capture.server.captures[0].raw_body)
                ):
                    raise CodexIsolationUnavailable(
                        "Codex probe did not produce exactly one rejected offline request."
                    )
                request = capture.server.captures[0]
                request_semantics = _verify_request(
                    request,
                    model=model,
                    nonce=nonce,
                    model_instructions=model_instructions,
                    work=private_root / "work",
                )
                if (
                    not all(
                        value.validate()
                        for value in (
                            binary_input,
                            catalog_input,
                            staged_binary_input,
                            staged_catalog_input,
                        )
                    )
                    or not retained_root.validate()
                ):
                    raise CodexIsolationUnavailable(
                        "Probe inputs changed before evidence issuance."
                    )
                _verify_contract_constants()
                endpoint_sha256 = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
                transcript_sha256 = canonical_sha256(
                    {
                        "schema_version": "codex-loopback-transcript-v1",
                        "endpoint_sha256": endpoint_sha256,
                        "request_semantics": request_semantics,
                        "request": _request_document(request),
                        "response_status": 400,
                        "response_sha256": hashlib.sha256(
                            b'{"error":{"message":"offline isolation probe complete"}}'
                        ).hexdigest(),
                    }
                )
                seal = object()
                provisional = CodexIsolationReceipt(
                    ISOLATION_SCHEMA_VERSION,
                    "0" * 64,
                    package_version,
                    model,
                    "offline-measurement-only",
                    False,
                    native_format,
                    expected_native_sha256,
                    len(binary_input.content),
                    expected_catalog_sha256,
                    canonical_sha256(_runtime_config_document(argv)),
                    _CONFIG_CONTRACT_SHA256,
                    canonical_sha256({"argv": argv}),
                    _ARGV_CONTRACT_SHA256,
                    canonical_sha256(environment),
                    _ENVIRONMENT_CONTRACT_SHA256,
                    sandbox_exec_sha256,
                    _SANDBOX_CONTRACT_SHA256,
                    hashlib.sha256(profile.encode("utf-8")).hexdigest(),
                    endpoint_sha256,
                    hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
                    _REQUEST_PATH_TEMPLATE,
                    hashlib.sha256(request.raw_body).hexdigest(),
                    canonical_sha256(request_semantics),
                    transcript_sha256,
                    _TOOL_REGISTRY_SHA256,
                    1,
                    (),
                    seal,
                    _RECEIPT_AUTHORITY,
                )
                receipt = CodexIsolationReceipt(
                    **{
                        **provisional.__dict__,
                        "receipt_sha256": canonical_sha256(
                            _receipt_identity_document(provisional)
                        ),
                    }
                )
                _ISSUED_RECEIPTS[id(receipt)] = receipt
                return receipt
            finally:
                staged_binary_input.close()
                staged_catalog_input.close()
        finally:
            if retained_root is not None:
                try:
                    retained_root.remove()
                finally:
                    retained_root.close()
    except CodexIsolationUnavailable:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise CodexIsolationUnavailable("Codex isolation proof failed closed.") from exc
    finally:
        if binary_input is not None:
            binary_input.close()
        if catalog_input is not None:
            catalog_input.close()


__all__ = [
    "CodexIsolationReceipt",
    "CodexIsolationUnavailable",
    "CodexLiveAuthorization",
    "CodexLiveDispatch",
    "CodexLiveDispatchContext",
    "CodexLivePermit",
    "ISOLATION_SCHEMA_VERSION",
    "LIVE_AUTHORIZATION_SCHEMA_VERSION",
    "LIVE_DISPATCH_CONTEXT_SCHEMA_VERSION",
    "LIVE_DISPATCH_SCHEMA_VERSION",
    "LIVE_PERMIT_SCHEMA_VERSION",
    "MINIMUM_CODEX_VERSION",
    "OFFICIAL_CODEX_CATALOG_SHA256",
    "OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY",
    "OFFICIAL_CODEX_MODEL",
    "OFFICIAL_CODEX_NATIVE_SHA256",
    "OFFICIAL_CODEX_PACKAGE_POLICY_SHA256",
    "authorize_codex_live_runtime",
    "codex_isolation_receipt_document",
    "probe_codex_isolation",
    "retain_codex_live_dispatch",
    "verify_codex_isolation_receipt",
    "verify_codex_live_authorization",
    "verify_codex_live_dispatch",
    "verify_codex_live_dispatch_context",
    "verify_codex_live_permit",
    "verify_official_codex_registry_metadata",
]
