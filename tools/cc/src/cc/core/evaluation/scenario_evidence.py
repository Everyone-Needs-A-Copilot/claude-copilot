"""Signed, value-suppressing durable evidence for scenarios S-04 and S-05."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256

S04_SCHEMA_VERSION = "task285-s04-continuity-v1"
S05_SCHEMA_VERSION = "task285-s05-shared-update-v1"
S04_INPUT_SCHEMA_VERSION = "task285-s04-retained-input-v1"
S05_INPUT_SCHEMA_VERSION = "task285-s05-retained-input-v1"

_PRIVACY_CLASS = "value-suppressing-durable-evidence"
_PUBLISHER_SIGNER = "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
_PUBLISHER_PRINCIPAL = "enac-foundation"
_S04_NAMESPACE = "copilot-scenario-s04-v1"
_S05_NAMESPACE = "copilot-scenario-s05-v1"
_S04_PREFIX = "s04-continuity-"
_S05_PREFIX = "s05-shared-update-"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_RELATIVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")
_ROLLBACK_REF = re.compile(
    r"^(?:refs/tags/[A-Za-z0-9][A-Za-z0-9._/-]{0,190}|sha256:[0-9a-f]{64})$"
)
_MAX_INPUT_BYTES = 4 * 1024 * 1024
_MAX_BUNDLE_BYTES = 64 * 1024
_MAX_SIGNATURE_BYTES = 16 * 1024
_SIGNATURE_TIMEOUT_SECONDS = 8.0
_SSH_KEYGEN = Path("/usr/bin/ssh-keygen")
_LOCK = threading.RLock()

_S04_INPUT_AUTHORITY = object()
_S05_INPUT_AUTHORITY = object()
_S04_AUTHORITY = object()
_S05_AUTHORITY = object()
_ISSUED_S04_INPUTS: dict[int, "S04ScenarioInputs"] = {}
_ISSUED_S05_INPUTS: dict[int, "S05ScenarioInputs"] = {}
_ISSUED_S04: dict[int, "S04ContinuityEvidence"] = {}
_ISSUED_S05: dict[int, "S05UpdateEvidence"] = {}
_CONSUMED_S04_INPUTS: set[int] = set()
_CONSUMED_S05_INPUTS: set[int] = set()


class ScenarioEvidenceUnavailable(ValueError):
    """The retained and signed source evidence cannot prove the scenario."""


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ScenarioEvidenceUnavailable(f"{field_name} must be a SHA-256 digest.")
    return value


def _require_code(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise ScenarioEvidenceUnavailable(f"{field_name} is not a closed identifier.")
    return value


def _require_relative(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _RELATIVE.fullmatch(value):
        raise ScenarioEvidenceUnavailable(f"{field_name} is not a relative path.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ScenarioEvidenceUnavailable(f"{field_name} is not a canonical path.")
    return value


def _require_rollback_ref(value: object) -> str:
    if not isinstance(value, str) or not _ROLLBACK_REF.fullmatch(value):
        raise ScenarioEvidenceUnavailable("rollback_ref is not immutable.")
    if value.startswith("refs/tags/") and any(
        part in {"", ".", ".."} for part in value.removeprefix("refs/tags/").split("/")
    ):
        raise ScenarioEvidenceUnavailable("rollback_ref is not canonical.")
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


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioEvidenceUnavailable(
                "Signed scenario JSON has duplicate keys."
            )
        result[key] = value
    return result


def _canonical_document(raw: bytes, *, description: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        ScenarioEvidenceUnavailable,
    ) as exc:
        raise ScenarioEvidenceUnavailable(f"{description} is malformed.") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ScenarioEvidenceUnavailable(f"{description} is not canonical JSON.")
    return value


def _read_exact(descriptor: int, maximum: int) -> bytes:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_size < 2
        or before.st_size > maximum
    ):
        raise ScenarioEvidenceUnavailable("Retained scenario input is not exact.")
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = before.st_size
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(descriptor, min(remaining, 65536))
        if not chunk:
            raise ScenarioEvidenceUnavailable(
                "Retained scenario input read was incomplete."
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(descriptor)
    if _identity(before) != _identity(after):
        raise ScenarioEvidenceUnavailable(
            "Retained scenario input changed while reading."
        )
    return b"".join(chunks)


class _RetainedFile:
    def __init__(
        self,
        path: Path,
        *,
        maximum: int,
        expected_mode: int = 0o600,
        retained_parent: _RetainedDirectoryChain | None = None,
    ) -> None:
        self.path = Path(path)
        self.parent_fd = -1
        self.fd = -1
        self.closed = False
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if (
            no_follow is None
            or directory is None
            or not self.path.is_absolute()
            or self.path != self.path.resolve(strict=True)
        ):
            raise ScenarioEvidenceUnavailable("Retained input path is not canonical.")
        try:
            if retained_parent is None:
                self.parent_fd = os.open(
                    self.path.parent,
                    os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0),
                )
            else:
                if (
                    retained_parent.path != self.path.parent
                    or not retained_parent.validate()
                ):
                    raise ScenarioEvidenceUnavailable("Retained input parent differs.")
                self.parent_fd = os.dup(retained_parent.fd)
            self.fd = os.open(
                self.path.name,
                os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
                dir_fd=self.parent_fd,
            )
            parent = os.fstat(self.parent_fd)
            opened = os.fstat(self.fd)
            named = os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(parent.st_mode)
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != expected_mode
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise ScenarioEvidenceUnavailable(
                    "Retained input file is not private/exact."
                )
            self.parent_identity = _directory_identity(parent)
            self.file_identity = _identity(opened)
            self.raw = _read_exact(self.fd, maximum)
            self.sha256 = hashlib.sha256(self.raw).hexdigest()
            if not self.validate():
                raise ScenarioEvidenceUnavailable("Retained input changed during open.")
        except ScenarioEvidenceUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise ScenarioEvidenceUnavailable(
                "Retained input cannot be opened safely."
            ) from exc

    def validate(self) -> bool:
        if self.closed:
            return False
        try:
            parent = os.fstat(self.parent_fd)
            opened = os.fstat(self.fd)
            named = os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            return bool(
                _directory_identity(parent) == self.parent_identity
                and _identity(opened) == self.file_identity
                and _identity(named) == self.file_identity
                and _read_exact(self.fd, _MAX_INPUT_BYTES) == self.raw
            )
        except (OSError, ScenarioEvidenceUnavailable):
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for name in ("fd", "parent_fd"):
            descriptor = getattr(self, name)
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, name, -1)


class _RetainedDirectory:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.parent_fd = -1
        self.fd = -1
        self.closed = False
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if (
            no_follow is None
            or directory is None
            or not self.path.is_absolute()
            or self.path != self.path.resolve(strict=True)
        ):
            raise ScenarioEvidenceUnavailable("Artifact root path is not canonical.")
        try:
            self.parent_fd = os.open(
                self.path.parent,
                os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0),
            )
            self.fd = os.open(
                self.path.name,
                os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0),
                dir_fd=self.parent_fd,
            )
            parent = os.fstat(self.parent_fd)
            opened = os.fstat(self.fd)
            named = os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or opened.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise ScenarioEvidenceUnavailable("Artifact root is not private/exact.")
            self.parent_identity = _directory_identity(parent)
            self.root_identity = _identity(opened)
            self.sha256 = canonical_sha256(
                {
                    "schema_version": "task285-artifact-root-identity-v1",
                    "path_sha256": hashlib.sha256(str(self.path).encode()).hexdigest(),
                    "device": opened.st_dev,
                    "inode": opened.st_ino,
                    "mode": stat.S_IMODE(opened.st_mode),
                    "owner": opened.st_uid,
                }
            )
            if not self.validate():
                raise ScenarioEvidenceUnavailable("Artifact root changed during open.")
        except ScenarioEvidenceUnavailable:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise ScenarioEvidenceUnavailable(
                "Artifact root cannot be retained."
            ) from exc

    def validate(self) -> bool:
        if self.closed:
            return False
        try:
            parent = os.fstat(self.parent_fd)
            opened = os.fstat(self.fd)
            named = os.stat(
                self.path.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            return bool(
                _directory_identity(parent) == self.parent_identity
                and _identity(opened) == self.root_identity
                and _identity(named) == self.root_identity
            )
        except OSError:
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for name in ("fd", "parent_fd"):
            descriptor = getattr(self, name)
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, name, -1)


class _RetainedDirectoryChain:
    """Descriptor-retain every canonical directory link from `/` to a root."""

    def __init__(self, path: Path, *, final_mode: int) -> None:
        self.path = Path(path)
        self.final_mode = final_mode
        self.entries: list[tuple[str, int, tuple[int, ...]]] = []
        self.closed = False
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if (
            no_follow is None
            or directory is None
            or not self.path.is_absolute()
            or self.path != self.path.resolve(strict=True)
        ):
            raise ScenarioEvidenceUnavailable("Scenario root path is not canonical.")
        flags = os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0)
        descriptor = -1
        try:
            descriptor = os.open("/", flags)
            opened = os.fstat(descriptor)
            if not stat.S_ISDIR(opened.st_mode):
                raise ScenarioEvidenceUnavailable("Filesystem root is not exact.")
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
                    raise ScenarioEvidenceUnavailable(
                        "Scenario root directory link is not exact."
                    )
                self.entries.append((name, descriptor, _directory_identity(opened)))
                descriptor = -1
            final = os.fstat(self.fd)
            if (
                final.st_uid != os.geteuid()
                or stat.S_IMODE(final.st_mode) != self.final_mode
            ):
                raise ScenarioEvidenceUnavailable("Scenario root is not private/exact.")
            if not self.validate():
                raise ScenarioEvidenceUnavailable("Scenario root changed during open.")
        except ScenarioEvidenceUnavailable:
            if descriptor >= 0:
                os.close(descriptor)
            self.close()
            raise
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            self.close()
            raise ScenarioEvidenceUnavailable(
                "Scenario root cannot be retained safely."
            ) from exc

    @property
    def fd(self) -> int:
        return self.entries[-1][1] if self.entries else -1

    @property
    def identity(self) -> tuple[int, ...]:
        return self.entries[-1][2]

    def validate(self) -> bool:
        if self.closed or not self.entries:
            return False
        try:
            for index, (name, descriptor, identity) in enumerate(self.entries):
                if _directory_identity(os.fstat(descriptor)) != identity:
                    return False
                if index:
                    parent_fd = self.entries[index - 1][1]
                    named = os.stat(
                        name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    if _directory_identity(named) != identity:
                        return False
            final = os.fstat(self.fd)
            return bool(
                final.st_uid == os.geteuid()
                and stat.S_IMODE(final.st_mode) == self.final_mode
            )
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


def _allowed_signer_content(public_key: str) -> bytes:
    return (
        f'{_PUBLISHER_PRINCIPAL} namespaces="{_S04_NAMESPACE},{_S05_NAMESPACE}" '
        f"{public_key}\n"
    ).encode()


def _verify_publisher_signature(
    claim: _RetainedFile,
    signature: _RetainedFile,
    namespace: str,
) -> bool:
    from cc.core.ecosystem.policy import FOUNDATION_SSH_SIGNING_KEYS
    from cc.core.evaluation.codex_isolation import (
        _leader_exited_without_reaping,
        _terminate_process_group,
        _wait_for_leader_without_reaping,
    )

    public_key = FOUNDATION_SSH_SIGNING_KEYS.get(_PUBLISHER_SIGNER.upper())
    if public_key is None or namespace not in {_S04_NAMESPACE, _S05_NAMESPACE}:
        return False
    allowed_raw = _allowed_signer_content(public_key)
    allowed = None
    process: subprocess.Popen[bytes] | None = None
    process_group_verified = False
    returncode: int | None = None
    try:
        if not claim.validate() or not signature.validate():
            return False
        allowed = tempfile.TemporaryFile(prefix="cc-scenario-allowed-signers-")
        os.fchmod(allowed.fileno(), 0o600)
        allowed.write(allowed_raw)
        allowed.flush()
        os.fsync(allowed.fileno())
        allowed.seek(0)
        allowed_before = os.fstat(allowed.fileno())
        os.lseek(claim.fd, 0, os.SEEK_SET)
        os.lseek(signature.fd, 0, os.SEEK_SET)
        process = subprocess.Popen(
            [
                str(_SSH_KEYGEN),
                "-Y",
                "verify",
                "-f",
                f"/dev/fd/{allowed.fileno()}",
                "-I",
                _PUBLISHER_PRINCIPAL,
                "-n",
                namespace,
                "-s",
                f"/dev/fd/{signature.fd}",
            ],
            stdin=claim.fd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(allowed.fileno(), signature.fd),
            start_new_session=True,
        )
        try:
            process_group_verified = os.getpgid(process.pid) == process.pid
        except ProcessLookupError:
            process_group_verified = _leader_exited_without_reaping(process)
        if not process_group_verified:
            return False
        if not _wait_for_leader_without_reaping(
            process,
            timeout=_SIGNATURE_TIMEOUT_SECONDS,
        ):
            return False
        returncode = _terminate_process_group(
            process,
            process_group_verified=process_group_verified,
        )
        process = None
        allowed.seek(0)
        return bool(
            returncode == 0
            and _identity(os.fstat(allowed.fileno())) == _identity(allowed_before)
            and allowed.read() == allowed_raw
            and claim.validate()
            and signature.validate()
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    finally:
        if process is not None:
            try:
                _terminate_process_group(
                    process,
                    process_group_verified=process_group_verified,
                )
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        if allowed is not None:
            allowed.close()


@dataclass
class _InputState:
    files: tuple[_RetainedFile, ...]
    artifact_root: _RetainedDirectory | None
    assessment: object | None
    scenario_id: str
    derived_raw: bytes
    authority_sha256: str
    signature_sha256: str
    seal: object = field(default_factory=object)
    closed: bool = False

    @property
    def derived(self) -> dict[str, Any]:
        return _canonical_document(
            self.derived_raw,
            description="retained scenario derivation",
        )

    def _recompute(self) -> tuple[dict[str, Any], bytes]:
        if self.scenario_id == "s-04":
            if (
                self.artifact_root is None
                or self.assessment is None
                or len(self.files) != 4
            ):
                raise ScenarioEvidenceUnavailable("S-04 retained input shape differs.")
            pre_file, resumed_file, claim_file, _signature_file = self.files
            derived = _s04_derived(
                _s04_snapshot(
                    _canonical_document(
                        pre_file.raw,
                        description="pre-pause TC export",
                    ),
                    resumed=False,
                ),
                _s04_snapshot(
                    _canonical_document(
                        resumed_file.raw,
                        description="resumed TC export",
                    ),
                    resumed=True,
                ),
                self.artifact_root,
                self.assessment,
            )
            input_sha256 = {
                "pre_pause_tc_export_sha256": pre_file.sha256,
                "resumed_tc_export_sha256": resumed_file.sha256,
                "artifact_root_sha256": self.artifact_root.sha256,
                "assessment_bundle_sha256": derived["assessment_bundle_sha256"],
            }
            namespace = _S04_NAMESPACE
        elif self.scenario_id == "s-05":
            if (
                self.artifact_root is not None
                or self.assessment is not None
                or len(self.files) != 11
            ):
                raise ScenarioEvidenceUnavailable("S-05 retained input shape differs.")
            (
                before_file,
                after_file,
                ledger_file,
                before_source,
                after_source,
                before_content,
                after_content,
                artifact_file,
                rollback_file,
                claim_file,
                _signature_file,
            ) = self.files
            derived = _s05_derived(
                before_snapshot=_canonical_document(
                    before_file.raw,
                    description="before project export",
                ),
                after_snapshot=_canonical_document(
                    after_file.raw,
                    description="after project export",
                ),
                ledger=_canonical_document(
                    ledger_file.raw,
                    description="update ledger",
                ),
                before_source=before_source,
                after_source=after_source,
                before_content=before_content,
                after_content=after_content,
                resumed_artifact=artifact_file,
                rollback=rollback_file,
            )
            input_sha256 = {
                "before_project_export_sha256": before_file.sha256,
                "after_project_export_sha256": after_file.sha256,
                "update_ledger_file_sha256": ledger_file.sha256,
                "before_source_receipt_sha256": before_source.sha256,
                "after_source_receipt_sha256": after_source.sha256,
                "before_content_receipt_sha256": before_content.sha256,
                "after_content_receipt_sha256": after_content.sha256,
                "resumed_artifact_sha256": artifact_file.sha256,
                "rollback_evidence_sha256": rollback_file.sha256,
            }
            namespace = _S05_NAMESPACE
        else:
            raise ScenarioEvidenceUnavailable("Retained scenario kind differs.")
        expected_claim = canonical_json_bytes(
            _publisher_claim_document(
                scenario_id=self.scenario_id,
                namespace=namespace,
                input_sha256=input_sha256,
                derived=derived,
            )
        )
        if claim_file.raw != expected_claim:
            raise ScenarioEvidenceUnavailable(
                "Publisher claim no longer matches inputs."
            )
        return derived, expected_claim

    def validate(self) -> bool:
        if self.closed or not all(item.validate() for item in self.files):
            return False
        if self.artifact_root is not None and not self.artifact_root.validate():
            return False
        if (
            self.assessment is not None
            and not getattr(self.assessment, "validate", lambda: False)()
        ):
            return False
        try:
            derived, expected_claim = self._recompute()
            return bool(
                canonical_json_bytes(derived) == self.derived_raw
                and hashlib.sha256(expected_claim).hexdigest() == self.authority_sha256
                and hashlib.sha256(self.files[-1].raw).hexdigest()
                == self.signature_sha256
            )
        except (IndexError, KeyError, ScenarioEvidenceUnavailable, TypeError):
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for item in self.files:
            item.close()
        if self.artifact_root is not None:
            self.artifact_root.close()


@dataclass(frozen=True)
class S04ScenarioInputs:
    """Exact signed inputs from which S-04 output fields are derived."""

    schema_version: str
    authority_sha256: str
    signature_sha256: str
    publisher_signer: str
    signature_namespace: str
    _state: _InputState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def validate(self) -> bool:
        with _LOCK:
            return _verify_s04_inputs_unlocked(self)

    def close(self) -> None:
        with _LOCK:
            if _ISSUED_S04_INPUTS.get(id(self)) is self:
                _ISSUED_S04_INPUTS.pop(id(self), None)
                _CONSUMED_S04_INPUTS.discard(id(self))
                self._state.close()


@dataclass(frozen=True)
class S05ScenarioInputs:
    """Exact signed inputs from which S-05 output fields are derived."""

    schema_version: str
    authority_sha256: str
    signature_sha256: str
    publisher_signer: str
    signature_namespace: str
    _state: _InputState = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def validate(self) -> bool:
        with _LOCK:
            return _verify_s05_inputs_unlocked(self)

    def close(self) -> None:
        with _LOCK:
            if _ISSUED_S05_INPUTS.get(id(self)) is self:
                _ISSUED_S05_INPUTS.pop(id(self), None)
                _CONSUMED_S05_INPUTS.discard(id(self))
                self._state.close()


def _verify_s04_inputs_unlocked(value: object) -> bool:
    return bool(
        isinstance(value, S04ScenarioInputs)
        and _ISSUED_S04_INPUTS.get(id(value)) is value
        and value._authority is _S04_INPUT_AUTHORITY
        and value._seal is value._state.seal
        and value.schema_version == S04_INPUT_SCHEMA_VERSION
        and value.authority_sha256 == value._state.authority_sha256
        and value.signature_sha256 == value._state.signature_sha256
        and value.publisher_signer == _PUBLISHER_SIGNER
        and value.signature_namespace == _S04_NAMESPACE
        and value._state.validate()
    )


def _verify_s05_inputs_unlocked(value: object) -> bool:
    return bool(
        isinstance(value, S05ScenarioInputs)
        and _ISSUED_S05_INPUTS.get(id(value)) is value
        and value._authority is _S05_INPUT_AUTHORITY
        and value._seal is value._state.seal
        and value.schema_version == S05_INPUT_SCHEMA_VERSION
        and value.authority_sha256 == value._state.authority_sha256
        and value.signature_sha256 == value._state.signature_sha256
        and value.publisher_signer == _PUBLISHER_SIGNER
        and value.signature_namespace == _S05_NAMESPACE
        and value._state.validate()
    )


def verify_s04_scenario_inputs(value: object) -> bool:
    with _LOCK:
        return _verify_s04_inputs_unlocked(value)


def verify_s05_scenario_inputs(value: object) -> bool:
    with _LOCK:
        return _verify_s05_inputs_unlocked(value)


_S04_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "matrix_sha256",
        "task_state",
        "work_products",
        "process_identity",
        "artifact_root_sha256",
        "pause_capsule_sha256",
        "continuation",
    }
)
_S04_TASK_FIELDS = frozenset(
    {"task_id", "status", "revision", "state_commitment_sha256"}
)
_S04_WORK_PRODUCT_FIELDS = frozenset({"id", "type", "artifact_sha256"})
_S04_PROCESS_FIELDS = frozenset({"process_sha256", "session_sha256"})
_S04_CONTINUATION_FIELDS = frozenset(
    {
        "pause_capsule_sha256",
        "pre_pause_process_sha256",
        "resumed_process_sha256",
        "artifact_root_sha256",
        "outcome",
        "resume_reason",
    }
)


def _s04_snapshot(value: dict[str, Any], *, resumed: bool) -> dict[str, Any]:
    if (
        set(value) != _S04_SNAPSHOT_FIELDS
        or value.get("schema_version") != "task285-s04-tc-export-v1"
        or value.get("matrix_sha256") != PACKAGED_MATRIX_SHA256
    ):
        raise ScenarioEvidenceUnavailable("Task Copilot export contract differs.")
    task = value.get("task_state")
    work_products = value.get("work_products")
    process = value.get("process_identity")
    continuation = value.get("continuation")
    if (
        not isinstance(task, dict)
        or set(task) != _S04_TASK_FIELDS
        or task.get("task_id") != 285
        or task.get("status")
        not in ({"in_progress", "completed"} if resumed else {"in_progress"})
        or not isinstance(task.get("revision"), int)
        or isinstance(task.get("revision"), bool)
        or task["revision"] < 1
    ):
        raise ScenarioEvidenceUnavailable("Task Copilot task snapshot differs.")
    _require_digest(task.get("state_commitment_sha256"), "task state commitment")
    if not isinstance(work_products, list) or not work_products:
        raise ScenarioEvidenceUnavailable(
            "Task Copilot work-product snapshot is empty."
        )
    normalized_work_products = []
    for item in work_products:
        if (
            not isinstance(item, dict)
            or set(item) != _S04_WORK_PRODUCT_FIELDS
            or not isinstance(item.get("id"), int)
            or isinstance(item.get("id"), bool)
            or item["id"] < 1
        ):
            raise ScenarioEvidenceUnavailable(
                "Task Copilot work-product entry differs."
            )
        normalized_work_products.append(
            {
                "id": item["id"],
                "type": _require_code(item.get("type"), "work-product type"),
                "artifact_sha256": _require_digest(
                    item.get("artifact_sha256"), "work-product artifact"
                ),
            }
        )
    if normalized_work_products != sorted(
        normalized_work_products, key=lambda item: item["id"]
    ) or len({item["id"] for item in normalized_work_products}) != len(
        normalized_work_products
    ):
        raise ScenarioEvidenceUnavailable(
            "Task Copilot work products are not canonical."
        )
    if not isinstance(process, dict) or set(process) != _S04_PROCESS_FIELDS:
        raise ScenarioEvidenceUnavailable("Process identity snapshot differs.")
    normalized_process = {
        "process_sha256": _require_digest(
            process.get("process_sha256"), "process identity"
        ),
        "session_sha256": _require_digest(
            process.get("session_sha256"), "session identity"
        ),
    }
    artifact_root_sha256 = _require_digest(
        value.get("artifact_root_sha256"), "artifact root"
    )
    pause_capsule_sha256 = _require_digest(
        value.get("pause_capsule_sha256"), "pause capsule"
    )
    if resumed:
        if (
            not isinstance(continuation, dict)
            or set(continuation) != _S04_CONTINUATION_FIELDS
        ):
            raise ScenarioEvidenceUnavailable("Continuation outcome is absent.")
        normalized_continuation: dict[str, Any] | None = {
            "pause_capsule_sha256": _require_digest(
                continuation.get("pause_capsule_sha256"), "continued pause capsule"
            ),
            "pre_pause_process_sha256": _require_digest(
                continuation.get("pre_pause_process_sha256"),
                "continued pre-pause process",
            ),
            "resumed_process_sha256": _require_digest(
                continuation.get("resumed_process_sha256"), "continued resumed process"
            ),
            "artifact_root_sha256": _require_digest(
                continuation.get("artifact_root_sha256"), "continued artifact root"
            ),
            "outcome": continuation.get("outcome"),
            "resume_reason": continuation.get("resume_reason"),
        }
        if (
            normalized_continuation["outcome"] != "continued"
            or normalized_continuation["resume_reason"]
            != "fresh-process-state-reloaded"
        ):
            raise ScenarioEvidenceUnavailable("Continuation outcome contract differs.")
    elif continuation is not None:
        raise ScenarioEvidenceUnavailable("Pre-pause export cannot claim continuation.")
    else:
        normalized_continuation = None
    return {
        "task": task,
        "work_products": normalized_work_products,
        "process": normalized_process,
        "artifact_root_sha256": artifact_root_sha256,
        "pause_capsule_sha256": pause_capsule_sha256,
        "continuation": normalized_continuation,
    }


def _s04_assessment_identity(assessment: object) -> dict[str, str]:
    from cc.core.evaluation.artifact import LoadedDurableRunEvidence
    from cc.core.evaluation.assessment import LoadedDurableAssessmentManifestEvidence

    if not isinstance(assessment, LoadedDurableAssessmentManifestEvidence) or not (
        assessment.validate()
    ):
        raise ScenarioEvidenceUnavailable(
            "S-04 requires an authentic assessment bundle."
        )
    if (
        assessment.manifest.matrix_sha256 != PACKAGED_MATRIX_SHA256
        or assessment.manifest.task_id != 285
        or len(assessment.runs) != 28
    ):
        raise ScenarioEvidenceUnavailable("S-04 assessment coverage differs.")
    run_sha256 = []
    for item in assessment.runs:
        if not isinstance(item, LoadedDurableRunEvidence) or not item.validate():
            raise ScenarioEvidenceUnavailable("S-04 execution evidence is invalid.")
        run_sha256.append(item.record.run_sha256)
    if len(set(run_sha256)) != 28:
        raise ScenarioEvidenceUnavailable("S-04 execution coverage is duplicated.")
    return {
        "execution_sha256": canonical_sha256(
            {
                "schema_version": "task285-s04-execution-set-v1",
                "matrix_sha256": PACKAGED_MATRIX_SHA256,
                "run_sha256": sorted(run_sha256),
            }
        ),
        "assessment_sha256": assessment.manifest_artifact_sha256,
        "assessment_bundle_sha256": assessment.bundle_artifact_sha256,
    }


def _s04_derived(
    pre: dict[str, Any],
    resumed: dict[str, Any],
    artifact_root: _RetainedDirectory,
    assessment: object,
) -> dict[str, Any]:
    identity = _s04_assessment_identity(assessment)
    continuation = resumed["continuation"]
    if (
        pre["work_products"] != resumed["work_products"]
        or resumed["task"]["revision"] <= pre["task"]["revision"]
        or pre["process"] == resumed["process"]
        or pre["artifact_root_sha256"] != artifact_root.sha256
        or resumed["artifact_root_sha256"] != artifact_root.sha256
        or continuation is None
        or continuation["pause_capsule_sha256"] != pre["pause_capsule_sha256"]
        or continuation["pause_capsule_sha256"] != resumed["pause_capsule_sha256"]
        or continuation["pre_pause_process_sha256"] != canonical_sha256(pre["process"])
        or continuation["resumed_process_sha256"]
        != canonical_sha256(resumed["process"])
        or continuation["artifact_root_sha256"] != artifact_root.sha256
    ):
        raise ScenarioEvidenceUnavailable("S-04 retained continuity proof differs.")
    work_products_sha256 = canonical_sha256(pre["work_products"])
    return {
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "execution_sha256": identity["execution_sha256"],
        "assessment_sha256": identity["assessment_sha256"],
        "assessment_bundle_sha256": identity["assessment_bundle_sha256"],
        "pre_pause_task_state_sha256": canonical_sha256(pre["task"]),
        "pre_pause_work_products_sha256": work_products_sha256,
        "resumed_task_state_sha256": canonical_sha256(resumed["task"]),
        "resumed_work_products_sha256": work_products_sha256,
        "pre_pause_process_identity_sha256": canonical_sha256(pre["process"]),
        "resumed_process_identity_sha256": canonical_sha256(resumed["process"]),
        "artifact_root_sha256": artifact_root.sha256,
        "resumed_artifact_root_sha256": artifact_root.sha256,
        "continuation_outcome_sha256": canonical_sha256(continuation),
        "continuation_outcome": "continued",
        "resume_reason": "fresh-process-state-reloaded",
    }


def _validate_claim(
    claim: dict[str, Any],
    *,
    scenario_id: str,
    namespace: str,
    input_sha256: Mapping[str, str],
    derived: Mapping[str, Any],
) -> None:
    if set(claim) != {
        "schema_version",
        "scenario_id",
        "matrix_sha256",
        "publisher_signer",
        "signature_namespace",
        "input_sha256",
        "derived",
    } or any(
        (
            claim.get("schema_version") != "task285-scenario-publisher-claim-v1",
            claim.get("scenario_id") != scenario_id,
            claim.get("matrix_sha256") != PACKAGED_MATRIX_SHA256,
            claim.get("publisher_signer") != _PUBLISHER_SIGNER,
            claim.get("signature_namespace") != namespace,
            claim.get("input_sha256") != dict(input_sha256),
            claim.get("derived") != dict(derived),
        )
    ):
        raise ScenarioEvidenceUnavailable(
            "Publisher scenario claim differs from inputs."
        )


def _publisher_claim_document(
    *,
    scenario_id: str,
    namespace: str,
    input_sha256: Mapping[str, str],
    derived: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "task285-scenario-publisher-claim-v1",
        "scenario_id": scenario_id,
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "publisher_signer": _PUBLISHER_SIGNER,
        "signature_namespace": namespace,
        "input_sha256": dict(input_sha256),
        "derived": dict(derived),
    }


def prepare_s04_publisher_claim(
    *,
    pre_pause_tc_export: Path,
    resumed_tc_export: Path,
    artifact_root: Path,
    assessment: object,
) -> bytes:
    """Derive exact S-04 claim bytes for detached publisher signing."""

    pre_file: _RetainedFile | None = None
    resumed_file: _RetainedFile | None = None
    retained_root: _RetainedDirectory | None = None
    try:
        pre_file = _RetainedFile(Path(pre_pause_tc_export), maximum=_MAX_INPUT_BYTES)
        resumed_file = _RetainedFile(Path(resumed_tc_export), maximum=_MAX_INPUT_BYTES)
        retained_root = _RetainedDirectory(Path(artifact_root))
        derived = _s04_derived(
            _s04_snapshot(
                _canonical_document(pre_file.raw, description="pre-pause TC export"),
                resumed=False,
            ),
            _s04_snapshot(
                _canonical_document(resumed_file.raw, description="resumed TC export"),
                resumed=True,
            ),
            retained_root,
            assessment,
        )
        return canonical_json_bytes(
            _publisher_claim_document(
                scenario_id="s-04",
                namespace=_S04_NAMESPACE,
                input_sha256={
                    "pre_pause_tc_export_sha256": pre_file.sha256,
                    "resumed_tc_export_sha256": resumed_file.sha256,
                    "artifact_root_sha256": retained_root.sha256,
                    "assessment_bundle_sha256": derived["assessment_bundle_sha256"],
                },
                derived=derived,
            )
        )
    finally:
        for item in (pre_file, resumed_file):
            if item is not None:
                item.close()
        if retained_root is not None:
            retained_root.close()


def retain_s04_scenario_inputs(
    *,
    pre_pause_tc_export: Path,
    resumed_tc_export: Path,
    artifact_root: Path,
    assessment: object,
    publisher_claim: Path,
    publisher_signature: Path,
) -> S04ScenarioInputs:
    """Retain signed Task Copilot exports plus the authentic assessment bundle."""

    retained: list[_RetainedFile] = []
    retained_root: _RetainedDirectory | None = None
    try:
        pre_file = _RetainedFile(Path(pre_pause_tc_export), maximum=_MAX_INPUT_BYTES)
        retained.append(pre_file)
        resumed_file = _RetainedFile(Path(resumed_tc_export), maximum=_MAX_INPUT_BYTES)
        retained.append(resumed_file)
        claim_file = _RetainedFile(Path(publisher_claim), maximum=_MAX_BUNDLE_BYTES)
        retained.append(claim_file)
        signature_file = _RetainedFile(
            Path(publisher_signature), maximum=_MAX_SIGNATURE_BYTES
        )
        retained.append(signature_file)
        retained_root = _RetainedDirectory(Path(artifact_root))
        pre = _s04_snapshot(
            _canonical_document(pre_file.raw, description="pre-pause TC export"),
            resumed=False,
        )
        resumed = _s04_snapshot(
            _canonical_document(resumed_file.raw, description="resumed TC export"),
            resumed=True,
        )
        derived = _s04_derived(pre, resumed, retained_root, assessment)
        claim = _canonical_document(claim_file.raw, description="S-04 publisher claim")
        _validate_claim(
            claim,
            scenario_id="s-04",
            namespace=_S04_NAMESPACE,
            input_sha256={
                "pre_pause_tc_export_sha256": pre_file.sha256,
                "resumed_tc_export_sha256": resumed_file.sha256,
                "artifact_root_sha256": retained_root.sha256,
                "assessment_bundle_sha256": derived["assessment_bundle_sha256"],
            },
            derived=derived,
        )
        if not _verify_publisher_signature(
            claim_file,
            signature_file,
            _S04_NAMESPACE,
        ):
            raise ScenarioEvidenceUnavailable("S-04 publisher signature is invalid.")
        state = _InputState(
            tuple(retained),
            retained_root,
            assessment,
            "s-04",
            canonical_json_bytes(derived),
            claim_file.sha256,
            signature_file.sha256,
        )
        result = S04ScenarioInputs(
            S04_INPUT_SCHEMA_VERSION,
            state.authority_sha256,
            state.signature_sha256,
            _PUBLISHER_SIGNER,
            _S04_NAMESPACE,
            state,
            state.seal,
            _S04_INPUT_AUTHORITY,
        )
        with _LOCK:
            _ISSUED_S04_INPUTS[id(result)] = result
        retained = []
        retained_root = None
        if not result.validate():
            result.close()
            raise ScenarioEvidenceUnavailable("S-04 retained inputs changed.")
        return result
    except ScenarioEvidenceUnavailable:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ScenarioEvidenceUnavailable("S-04 inputs could not be retained.") from exc
    finally:
        for item in retained:
            item.close()
        if retained_root is not None:
            retained_root.close()


_S05_PROJECT_FIELDS = frozenset(
    {"schema_version", "matrix_sha256", "project_identity_sha256", "tree"}
)
_S05_TREE_FIELDS = frozenset({"path", "blob_sha256", "classification"})
_S05_LEDGER_FIELDS = frozenset(
    {
        "schema_version",
        "matrix_sha256",
        "human_work_paths",
        "shared_component_paths",
        "resumed_artifact_path",
        "before_source_receipt_sha256",
        "after_source_receipt_sha256",
        "before_content_receipt_sha256",
        "after_content_receipt_sha256",
        "resumed_artifact_sha256",
        "rollback_evidence_sha256",
        "rollback_ref",
        "application_dependency",
        "execution_surface",
        "update_outcome",
    }
)
_S05_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "matrix_sha256",
        "receipt_kind",
        "immutable_ref",
        "tree_sha256",
        "receipt_revision",
    }
)
_S05_ROLLBACK_FIELDS = frozenset(
    {
        "schema_version",
        "matrix_sha256",
        "rollback_ref",
        "before_tree_sha256",
        "after_tree_sha256",
        "rollback_state",
    }
)


def _project_snapshot(value: dict[str, Any]) -> tuple[str, dict[str, dict[str, str]]]:
    if (
        set(value) != _S05_PROJECT_FIELDS
        or value.get("schema_version") != "task285-s05-project-export-v1"
        or value.get("matrix_sha256") != PACKAGED_MATRIX_SHA256
    ):
        raise ScenarioEvidenceUnavailable("S-05 project export contract differs.")
    _require_digest(value.get("project_identity_sha256"), "project identity")
    raw_tree = value.get("tree")
    if not isinstance(raw_tree, list) or not raw_tree:
        raise ScenarioEvidenceUnavailable("S-05 project tree is empty.")
    tree: dict[str, dict[str, str]] = {}
    for item in raw_tree:
        if not isinstance(item, dict) or set(item) != _S05_TREE_FIELDS:
            raise ScenarioEvidenceUnavailable("S-05 project tree entry differs.")
        path = _require_relative(item.get("path"), "project tree path")
        classification = _require_code(
            item.get("classification"), "project tree classification"
        )
        if classification not in {
            "human-work",
            "shared-component",
            "resumed-artifact",
            "other",
        }:
            raise ScenarioEvidenceUnavailable("Project tree classification differs.")
        if path in tree:
            raise ScenarioEvidenceUnavailable("Project tree path is duplicated.")
        tree[path] = {
            "path": path,
            "blob_sha256": _require_digest(item.get("blob_sha256"), "project blob"),
            "classification": classification,
        }
    if list(tree) != sorted(tree):
        raise ScenarioEvidenceUnavailable("Project tree is not canonically ordered.")
    tree_sha256 = canonical_sha256(list(tree.values()))
    return tree_sha256, tree


def _receipt_document(
    value: dict[str, Any],
    *,
    kind: str,
    tree_sha256: str,
) -> None:
    if (
        set(value) != _S05_RECEIPT_FIELDS
        or value.get("schema_version") != "task285-s05-immutable-receipt-v1"
        or value.get("matrix_sha256") != PACKAGED_MATRIX_SHA256
        or value.get("receipt_kind") != kind
        or value.get("tree_sha256") != tree_sha256
        or value.get("receipt_revision") != 1
    ):
        raise ScenarioEvidenceUnavailable(f"S-05 {kind} receipt differs.")
    _require_rollback_ref(value.get("immutable_ref"))


def _ledger_document(value: dict[str, Any]) -> dict[str, Any]:
    if (
        set(value) != _S05_LEDGER_FIELDS
        or value.get("schema_version") != "task285-s05-update-ledger-v1"
        or value.get("matrix_sha256") != PACKAGED_MATRIX_SHA256
        or value.get("application_dependency") != "none"
        or value.get("execution_surface") != "cli-only"
        or value.get("update_outcome") != "applied-and-human-work-preserved"
    ):
        raise ScenarioEvidenceUnavailable("S-05 update ledger contract differs.")
    for field_name in (
        "before_source_receipt_sha256",
        "after_source_receipt_sha256",
        "before_content_receipt_sha256",
        "after_content_receipt_sha256",
        "resumed_artifact_sha256",
        "rollback_evidence_sha256",
    ):
        _require_digest(value.get(field_name), field_name)
    human = value.get("human_work_paths")
    components = value.get("shared_component_paths")
    if (
        not isinstance(human, list)
        or not human
        or not isinstance(components, list)
        or not components
    ):
        raise ScenarioEvidenceUnavailable("S-05 ledger path coverage is empty.")
    normalized_human = [_require_relative(item, "human work path") for item in human]
    normalized_components = [
        _require_relative(item, "shared component path") for item in components
    ]
    if (
        normalized_human != sorted(set(normalized_human))
        or normalized_components != sorted(set(normalized_components))
        or set(normalized_human) & set(normalized_components)
    ):
        raise ScenarioEvidenceUnavailable("S-05 ledger paths are not canonical.")
    resumed_artifact_path = _require_relative(
        value.get("resumed_artifact_path"), "resumed artifact path"
    )
    if resumed_artifact_path in set(normalized_human + normalized_components):
        raise ScenarioEvidenceUnavailable(
            "Resumed artifact path overlaps source inputs."
        )
    return {
        **value,
        "human_work_paths": normalized_human,
        "shared_component_paths": normalized_components,
        "resumed_artifact_path": resumed_artifact_path,
        "rollback_ref": _require_rollback_ref(value.get("rollback_ref")),
    }


def _s05_derived(
    *,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    ledger: dict[str, Any],
    before_source: _RetainedFile,
    after_source: _RetainedFile,
    before_content: _RetainedFile,
    after_content: _RetainedFile,
    resumed_artifact: _RetainedFile,
    rollback: _RetainedFile,
) -> dict[str, Any]:
    before_tree_sha256, before_tree = _project_snapshot(before_snapshot)
    after_tree_sha256, after_tree = _project_snapshot(after_snapshot)
    if before_tree_sha256 == after_tree_sha256:
        raise ScenarioEvidenceUnavailable("S-05 project tree did not change.")
    ledger = _ledger_document(ledger)
    human_paths = ledger["human_work_paths"]
    component_paths = ledger["shared_component_paths"]
    if any(
        path not in before_tree
        or path not in after_tree
        or before_tree[path] != after_tree[path]
        or before_tree[path]["classification"] != "human-work"
        for path in human_paths
    ):
        raise ScenarioEvidenceUnavailable("S-05 human work was not preserved exactly.")
    if any(
        path not in before_tree
        or path not in after_tree
        or before_tree[path]["classification"] != "shared-component"
        or after_tree[path]["classification"] != "shared-component"
        for path in component_paths
    ) or not any(before_tree[path] != after_tree[path] for path in component_paths):
        raise ScenarioEvidenceUnavailable("S-05 shared component update is absent.")
    artifact_path = ledger["resumed_artifact_path"]
    if (
        artifact_path not in after_tree
        or after_tree[artifact_path]["classification"] != "resumed-artifact"
        or after_tree[artifact_path]["blob_sha256"] != resumed_artifact.sha256
    ):
        raise ScenarioEvidenceUnavailable("S-05 resumed artifact identity differs.")
    expected_file_hashes = {
        "before_source_receipt_sha256": before_source.sha256,
        "after_source_receipt_sha256": after_source.sha256,
        "before_content_receipt_sha256": before_content.sha256,
        "after_content_receipt_sha256": after_content.sha256,
        "resumed_artifact_sha256": resumed_artifact.sha256,
        "rollback_evidence_sha256": rollback.sha256,
    }
    if any(ledger[key] != digest for key, digest in expected_file_hashes.items()):
        raise ScenarioEvidenceUnavailable("S-05 ledger does not bind retained bytes.")
    if (
        before_source.sha256 == after_source.sha256
        or before_content.sha256 == after_content.sha256
    ):
        raise ScenarioEvidenceUnavailable("S-05 immutable receipts did not advance.")
    _receipt_document(
        _canonical_document(before_source.raw, description="before source receipt"),
        kind="source",
        tree_sha256=before_tree_sha256,
    )
    _receipt_document(
        _canonical_document(after_source.raw, description="after source receipt"),
        kind="source",
        tree_sha256=after_tree_sha256,
    )
    _receipt_document(
        _canonical_document(before_content.raw, description="before content receipt"),
        kind="content",
        tree_sha256=before_tree_sha256,
    )
    _receipt_document(
        _canonical_document(after_content.raw, description="after content receipt"),
        kind="content",
        tree_sha256=after_tree_sha256,
    )
    rollback_document = _canonical_document(
        rollback.raw, description="rollback evidence"
    )
    if (
        set(rollback_document) != _S05_ROLLBACK_FIELDS
        or rollback_document.get("schema_version") != "task285-s05-rollback-evidence-v1"
        or rollback_document.get("matrix_sha256") != PACKAGED_MATRIX_SHA256
        or rollback_document.get("rollback_ref") != ledger["rollback_ref"]
        or rollback_document.get("before_tree_sha256") != before_tree_sha256
        or rollback_document.get("after_tree_sha256") != after_tree_sha256
        or rollback_document.get("rollback_state") != "ready"
    ):
        raise ScenarioEvidenceUnavailable("S-05 rollback evidence differs.")
    human_identity = [before_tree[path] for path in human_paths]
    return {
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "before_project_tree_sha256": before_tree_sha256,
        "after_project_tree_sha256": after_tree_sha256,
        "update_ledger_sha256": canonical_sha256(ledger),
        "human_work_before_sha256": canonical_sha256(human_identity),
        "human_work_after_sha256": canonical_sha256(human_identity),
        "before_source_receipt_sha256": before_source.sha256,
        "after_source_receipt_sha256": after_source.sha256,
        "before_content_receipt_sha256": before_content.sha256,
        "after_content_receipt_sha256": after_content.sha256,
        "resumed_artifact_sha256": resumed_artifact.sha256,
        "rollback_ref": ledger["rollback_ref"],
        "application_dependency": "none",
        "execution_surface": "cli-only",
        "update_outcome": "applied-and-human-work-preserved",
    }


def retain_s05_scenario_inputs(
    *,
    before_project_export: Path,
    after_project_export: Path,
    update_ledger: Path,
    before_source_receipt: Path,
    after_source_receipt: Path,
    before_content_receipt: Path,
    after_content_receipt: Path,
    resumed_artifact: Path,
    rollback_evidence: Path,
    publisher_claim: Path,
    publisher_signature: Path,
) -> S05ScenarioInputs:
    """Retain signed project/update bytes and derive the S-05 claim."""

    retained: list[_RetainedFile] = []
    try:
        paths = (
            (before_project_export, _MAX_INPUT_BYTES),
            (after_project_export, _MAX_INPUT_BYTES),
            (update_ledger, _MAX_INPUT_BYTES),
            (before_source_receipt, _MAX_INPUT_BYTES),
            (after_source_receipt, _MAX_INPUT_BYTES),
            (before_content_receipt, _MAX_INPUT_BYTES),
            (after_content_receipt, _MAX_INPUT_BYTES),
            (resumed_artifact, _MAX_INPUT_BYTES),
            (rollback_evidence, _MAX_INPUT_BYTES),
            (publisher_claim, _MAX_BUNDLE_BYTES),
            (publisher_signature, _MAX_SIGNATURE_BYTES),
        )
        for path, maximum in paths:
            retained.append(_RetainedFile(Path(path), maximum=maximum))
        (
            before_file,
            after_file,
            ledger_file,
            before_source,
            after_source,
            before_content,
            after_content,
            artifact_file,
            rollback_file,
            claim_file,
            signature_file,
        ) = retained
        derived = _s05_derived(
            before_snapshot=_canonical_document(
                before_file.raw, description="before project export"
            ),
            after_snapshot=_canonical_document(
                after_file.raw, description="after project export"
            ),
            ledger=_canonical_document(ledger_file.raw, description="update ledger"),
            before_source=before_source,
            after_source=after_source,
            before_content=before_content,
            after_content=after_content,
            resumed_artifact=artifact_file,
            rollback=rollback_file,
        )
        claim = _canonical_document(claim_file.raw, description="S-05 publisher claim")
        _validate_claim(
            claim,
            scenario_id="s-05",
            namespace=_S05_NAMESPACE,
            input_sha256={
                "before_project_export_sha256": before_file.sha256,
                "after_project_export_sha256": after_file.sha256,
                "update_ledger_file_sha256": ledger_file.sha256,
                "before_source_receipt_sha256": before_source.sha256,
                "after_source_receipt_sha256": after_source.sha256,
                "before_content_receipt_sha256": before_content.sha256,
                "after_content_receipt_sha256": after_content.sha256,
                "resumed_artifact_sha256": artifact_file.sha256,
                "rollback_evidence_sha256": rollback_file.sha256,
            },
            derived=derived,
        )
        if not _verify_publisher_signature(
            claim_file,
            signature_file,
            _S05_NAMESPACE,
        ):
            raise ScenarioEvidenceUnavailable("S-05 publisher signature is invalid.")
        state = _InputState(
            tuple(retained),
            None,
            None,
            "s-05",
            canonical_json_bytes(derived),
            claim_file.sha256,
            signature_file.sha256,
        )
        result = S05ScenarioInputs(
            S05_INPUT_SCHEMA_VERSION,
            state.authority_sha256,
            state.signature_sha256,
            _PUBLISHER_SIGNER,
            _S05_NAMESPACE,
            state,
            state.seal,
            _S05_INPUT_AUTHORITY,
        )
        with _LOCK:
            _ISSUED_S05_INPUTS[id(result)] = result
        retained = []
        if not result.validate():
            result.close()
            raise ScenarioEvidenceUnavailable("S-05 retained inputs changed.")
        return result
    except ScenarioEvidenceUnavailable:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ScenarioEvidenceUnavailable("S-05 inputs could not be retained.") from exc
    finally:
        for item in retained:
            item.close()


def prepare_s05_publisher_claim(
    *,
    before_project_export: Path,
    after_project_export: Path,
    update_ledger: Path,
    before_source_receipt: Path,
    after_source_receipt: Path,
    before_content_receipt: Path,
    after_content_receipt: Path,
    resumed_artifact: Path,
    rollback_evidence: Path,
) -> bytes:
    """Derive exact S-05 claim bytes for detached publisher signing."""

    retained: list[_RetainedFile] = []
    try:
        for path in (
            before_project_export,
            after_project_export,
            update_ledger,
            before_source_receipt,
            after_source_receipt,
            before_content_receipt,
            after_content_receipt,
            resumed_artifact,
            rollback_evidence,
        ):
            retained.append(_RetainedFile(Path(path), maximum=_MAX_INPUT_BYTES))
        (
            before_file,
            after_file,
            ledger_file,
            before_source,
            after_source,
            before_content,
            after_content,
            artifact_file,
            rollback_file,
        ) = retained
        derived = _s05_derived(
            before_snapshot=_canonical_document(
                before_file.raw, description="before project export"
            ),
            after_snapshot=_canonical_document(
                after_file.raw, description="after project export"
            ),
            ledger=_canonical_document(ledger_file.raw, description="update ledger"),
            before_source=before_source,
            after_source=after_source,
            before_content=before_content,
            after_content=after_content,
            resumed_artifact=artifact_file,
            rollback=rollback_file,
        )
        return canonical_json_bytes(
            _publisher_claim_document(
                scenario_id="s-05",
                namespace=_S05_NAMESPACE,
                input_sha256={
                    "before_project_export_sha256": before_file.sha256,
                    "after_project_export_sha256": after_file.sha256,
                    "update_ledger_file_sha256": ledger_file.sha256,
                    "before_source_receipt_sha256": before_source.sha256,
                    "after_source_receipt_sha256": after_source.sha256,
                    "before_content_receipt_sha256": before_content.sha256,
                    "after_content_receipt_sha256": after_content.sha256,
                    "resumed_artifact_sha256": artifact_file.sha256,
                    "rollback_evidence_sha256": rollback_file.sha256,
                },
                derived=derived,
            )
        )
    finally:
        for item in retained:
            item.close()


class _BundleCapability:
    def __init__(
        self,
        root: Path,
        filename: str,
        *,
        retained_root: _RetainedDirectoryChain | None = None,
    ) -> None:
        self.root = Path(root)
        self.filename = filename
        self.root_chain = retained_root or _RetainedDirectoryChain(
            self.root,
            final_mode=0o700,
        )
        self.file: _RetainedFile | None = None
        try:
            self.file = _RetainedFile(
                self.root / filename,
                maximum=_MAX_BUNDLE_BYTES,
                retained_parent=self.root_chain,
            )
            root_stat = os.fstat(self.root_chain.fd)
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.geteuid()
                or stat.S_IMODE(root_stat.st_mode) != 0o700
                or _directory_identity(root_stat) != self.root_chain.identity
                or _directory_identity(os.fstat(self.file.parent_fd))
                != self.root_chain.identity
                or tuple(sorted(os.listdir(self.root_chain.fd))) != (filename,)
            ):
                raise ScenarioEvidenceUnavailable("Scenario bundle root is not exact.")
            self.root_identity = _identity(root_stat)
            self.root_sha256 = canonical_sha256(
                {
                    "schema_version": "task285-scenario-root-v1",
                    "path_sha256": hashlib.sha256(str(self.root).encode()).hexdigest(),
                    "device": root_stat.st_dev,
                    "inode": root_stat.st_ino,
                }
            )
            self.document = _canonical_document(
                self.file.raw, description="scenario bundle"
            )
            if not self.validate():
                raise ScenarioEvidenceUnavailable(
                    "Scenario bundle changed during open."
                )
        except BaseException:
            if self.file is not None:
                self.file.close()
            self.root_chain.close()
            raise

    @property
    def raw(self) -> bytes:
        if self.file is None:
            raise ScenarioEvidenceUnavailable("Scenario bundle is closed.")
        return self.file.raw

    def validate(self) -> bool:
        try:
            return bool(
                self.file is not None
                and self.root_chain.validate()
                and self.file.validate()
                and _directory_identity(os.fstat(self.file.parent_fd))
                == self.root_chain.identity
                and _identity(os.fstat(self.root_chain.fd)) == self.root_identity
                and tuple(sorted(os.listdir(self.root_chain.fd))) == (self.filename,)
                and _canonical_document(self.file.raw, description="scenario bundle")
                == self.document
            )
        except (OSError, ScenarioEvidenceUnavailable):
            return False

    def close(self) -> None:
        if self.file is not None:
            self.file.close()
        self.root_chain.close()


@dataclass(frozen=True)
class S04ContinuityEvidence:
    schema_version: str
    evidence_sha256: str
    bundle_sha256: str
    bundle_root_sha256: str
    input_authority_sha256: str
    publisher_signature_sha256: str
    publisher_signer: str
    signature_namespace: str
    matrix_sha256: str
    execution_sha256: str
    assessment_sha256: str
    pre_pause_task_state_sha256: str
    pre_pause_work_products_sha256: str
    resumed_task_state_sha256: str
    resumed_work_products_sha256: str
    pre_pause_process_identity_sha256: str
    resumed_process_identity_sha256: str
    artifact_root_sha256: str
    resumed_artifact_root_sha256: str
    continuation_outcome_sha256: str
    continuation_outcome: str
    resume_reason: str
    privacy_class: str
    _capability: _BundleCapability = field(repr=False, compare=False)
    _inputs: S04ScenarioInputs = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _S04_AUTHORITY
            or self.schema_version != S04_SCHEMA_VERSION
            or self.continuation_outcome != "continued"
            or self.resume_reason != "fresh-process-state-reloaded"
            or self.privacy_class != _PRIVACY_CLASS
        ):
            raise ScenarioEvidenceUnavailable("S-04 evidence is not verifier-issued.")

    def validate(self) -> bool:
        return verify_s04_continuity_evidence(self)

    def close(self) -> None:
        with _LOCK:
            if _ISSUED_S04.get(id(self)) is self:
                _ISSUED_S04.pop(id(self), None)
                self._capability.close()
                self._inputs.close()


@dataclass(frozen=True)
class S05UpdateEvidence:
    schema_version: str
    evidence_sha256: str
    bundle_sha256: str
    bundle_root_sha256: str
    input_authority_sha256: str
    publisher_signature_sha256: str
    publisher_signer: str
    signature_namespace: str
    matrix_sha256: str
    before_project_tree_sha256: str
    after_project_tree_sha256: str
    update_ledger_sha256: str
    human_work_before_sha256: str
    human_work_after_sha256: str
    before_source_receipt_sha256: str
    after_source_receipt_sha256: str
    before_content_receipt_sha256: str
    after_content_receipt_sha256: str
    resumed_artifact_sha256: str
    rollback_ref: str
    application_dependency: str
    execution_surface: str
    update_outcome: str
    privacy_class: str
    _capability: _BundleCapability = field(repr=False, compare=False)
    _inputs: S05ScenarioInputs = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _S05_AUTHORITY
            or self.schema_version != S05_SCHEMA_VERSION
            or self.application_dependency != "none"
            or self.execution_surface != "cli-only"
            or self.update_outcome != "applied-and-human-work-preserved"
            or self.privacy_class != _PRIVACY_CLASS
        ):
            raise ScenarioEvidenceUnavailable("S-05 evidence is not verifier-issued.")

    def validate(self) -> bool:
        return verify_s05_update_evidence(self)

    def close(self) -> None:
        with _LOCK:
            if _ISSUED_S05.get(id(self)) is self:
                _ISSUED_S05.pop(id(self), None)
                self._capability.close()
                self._inputs.close()


def _output_document(inputs: S04ScenarioInputs | S05ScenarioInputs) -> dict[str, Any]:
    return {
        "schema_version": (
            S04_SCHEMA_VERSION
            if isinstance(inputs, S04ScenarioInputs)
            else S05_SCHEMA_VERSION
        ),
        "scenario_id": "s-04" if isinstance(inputs, S04ScenarioInputs) else "s-05",
        "input_authority_sha256": inputs.authority_sha256,
        "publisher_signature_sha256": inputs.signature_sha256,
        "publisher_signer": inputs.publisher_signer,
        "signature_namespace": inputs.signature_namespace,
        **{
            key: value
            for key, value in inputs._state.derived.items()
            if key != "assessment_bundle_sha256"
        },
        "privacy_class": _PRIVACY_CLASS,
    }


def _write_private_bundle(
    root: Path,
    prefix: str,
    document: dict[str, Any],
) -> tuple[str, _RetainedDirectoryChain]:
    raw = canonical_json_bytes(document)
    if len(raw) > _MAX_BUNDLE_BYTES:
        raise ScenarioEvidenceUnavailable("Scenario bundle exceeds its closed limit.")
    digest = hashlib.sha256(raw).hexdigest()
    filename = f"{prefix}{digest}.json"
    root = Path(root)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ScenarioEvidenceUnavailable("Scenario output root is not canonical.")
    retained_root: _RetainedDirectoryChain | None = None
    file_fd = -1
    try:
        retained_root = _RetainedDirectoryChain(root, final_mode=0o700)
        if os.listdir(retained_root.fd):
            raise ScenarioEvidenceUnavailable(
                "Scenario output root is not empty/exact."
            )
        file_fd = os.open(
            filename,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | no_follow
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=retained_root.fd,
        )
        offset = 0
        while offset < len(raw):
            written = os.write(file_fd, raw[offset:])
            if written < 1:
                raise ScenarioEvidenceUnavailable(
                    "Scenario bundle write made no progress."
                )
            offset += written
        os.fchmod(file_fd, 0o600)
        os.fsync(file_fd)
        opened_file = os.fstat(file_fd)
        named_file = os.stat(
            filename,
            dir_fd=retained_root.fd,
            follow_symlinks=False,
        )
        if (
            opened_file.st_nlink != 1
            or stat.S_IMODE(opened_file.st_mode) != 0o600
            or _identity(opened_file) != _identity(named_file)
            or not retained_root.validate()
        ):
            raise ScenarioEvidenceUnavailable("Scenario bundle write identity differs.")
        os.fsync(retained_root.fd)
        result = retained_root
        retained_root = None
        return digest, result
    except ScenarioEvidenceUnavailable:
        raise
    except OSError as exc:
        raise ScenarioEvidenceUnavailable(
            "Scenario bundle write failed closed."
        ) from exc
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if retained_root is not None:
            retained_root.close()


def _evidence_identity(
    capability: _BundleCapability,
    bundle_sha256: str,
) -> dict[str, Any]:
    return {
        "bundle_sha256": bundle_sha256,
        "bundle_root_sha256": capability.root_sha256,
        **capability.document,
    }


def _load_bundle(
    root: Path,
    prefix: str,
    bundle_sha256: str,
    *,
    retained_root: _RetainedDirectoryChain | None = None,
) -> _BundleCapability:
    _require_digest(bundle_sha256, "bundle_sha256")
    capability = _BundleCapability(
        Path(root),
        f"{prefix}{bundle_sha256}.json",
        retained_root=retained_root,
    )
    if hashlib.sha256(capability.raw).hexdigest() != bundle_sha256:
        capability.close()
        raise ScenarioEvidenceUnavailable("Scenario bundle digest differs.")
    return capability


def _issue_s04(
    capability: _BundleCapability,
    bundle_sha256: str,
    inputs: S04ScenarioInputs,
) -> S04ContinuityEvidence:
    expected = _output_document(inputs)
    with _LOCK:
        if (
            not _verify_s04_inputs_unlocked(inputs)
            or id(inputs) in _CONSUMED_S04_INPUTS
            or capability.document != expected
            or not capability.validate()
        ):
            raise ScenarioEvidenceUnavailable(
                "S-04 authentic inputs do not match bundle."
            )
        seal = object()
        fields = {key: value for key, value in expected.items() if key != "scenario_id"}
        provisional = S04ContinuityEvidence(
            evidence_sha256="0" * 64,
            bundle_sha256=bundle_sha256,
            bundle_root_sha256=capability.root_sha256,
            _capability=capability,
            _inputs=inputs,
            _seal=seal,
            _authority=_S04_AUTHORITY,
            **fields,
        )
        result = S04ContinuityEvidence(
            **{
                **provisional.__dict__,
                "evidence_sha256": canonical_sha256(
                    _evidence_identity(capability, bundle_sha256)
                ),
            }
        )
        _CONSUMED_S04_INPUTS.add(id(inputs))
        _ISSUED_S04[id(result)] = result
        return result


def _issue_s05(
    capability: _BundleCapability,
    bundle_sha256: str,
    inputs: S05ScenarioInputs,
) -> S05UpdateEvidence:
    expected = _output_document(inputs)
    with _LOCK:
        if (
            not _verify_s05_inputs_unlocked(inputs)
            or id(inputs) in _CONSUMED_S05_INPUTS
            or capability.document != expected
            or not capability.validate()
        ):
            raise ScenarioEvidenceUnavailable(
                "S-05 authentic inputs do not match bundle."
            )
        seal = object()
        fields = {key: value for key, value in expected.items() if key != "scenario_id"}
        provisional = S05UpdateEvidence(
            evidence_sha256="0" * 64,
            bundle_sha256=bundle_sha256,
            bundle_root_sha256=capability.root_sha256,
            _capability=capability,
            _inputs=inputs,
            _seal=seal,
            _authority=_S05_AUTHORITY,
            **fields,
        )
        result = S05UpdateEvidence(
            **{
                **provisional.__dict__,
                "evidence_sha256": canonical_sha256(
                    _evidence_identity(capability, bundle_sha256)
                ),
            }
        )
        _CONSUMED_S05_INPUTS.add(id(inputs))
        _ISSUED_S05[id(result)] = result
        return result


def write_s04_continuity_bundle(
    root: Path,
    *,
    inputs: S04ScenarioInputs,
) -> S04ContinuityEvidence:
    """Write S-04 only from one exact signed retained-input capability."""

    with _LOCK:
        available = verify_s04_scenario_inputs(inputs) and id(inputs) not in (
            _CONSUMED_S04_INPUTS
        )
    if not available:
        raise ScenarioEvidenceUnavailable(
            "S-04 retained inputs are unavailable or already consumed."
        )
    digest, retained_root = _write_private_bundle(
        root,
        _S04_PREFIX,
        _output_document(inputs),
    )
    capability: _BundleCapability | None = None
    try:
        capability = _load_bundle(
            root,
            _S04_PREFIX,
            digest,
            retained_root=retained_root,
        )
        retained_root = None
        result = _issue_s04(capability, digest, inputs)
        capability = None
        if not result.validate():
            result.close()
            raise ScenarioEvidenceUnavailable("S-04 bundle could not be reverified.")
        return result
    finally:
        if capability is not None:
            capability.close()
        if retained_root is not None:
            retained_root.close()


def write_s05_update_bundle(
    root: Path,
    *,
    inputs: S05ScenarioInputs,
) -> S05UpdateEvidence:
    """Write S-05 only from one exact signed retained-input capability."""

    with _LOCK:
        available = verify_s05_scenario_inputs(inputs) and id(inputs) not in (
            _CONSUMED_S05_INPUTS
        )
    if not available:
        raise ScenarioEvidenceUnavailable(
            "S-05 retained inputs are unavailable or already consumed."
        )
    digest, retained_root = _write_private_bundle(
        root,
        _S05_PREFIX,
        _output_document(inputs),
    )
    capability: _BundleCapability | None = None
    try:
        capability = _load_bundle(
            root,
            _S05_PREFIX,
            digest,
            retained_root=retained_root,
        )
        retained_root = None
        result = _issue_s05(capability, digest, inputs)
        capability = None
        if not result.validate():
            result.close()
            raise ScenarioEvidenceUnavailable("S-05 bundle could not be reverified.")
        return result
    finally:
        if capability is not None:
            capability.close()
        if retained_root is not None:
            retained_root.close()


def load_s04_continuity_bundle(
    root: Path,
    bundle_sha256: str,
    *,
    inputs: S04ScenarioInputs,
) -> S04ContinuityEvidence | None:
    """Fresh-load S-04 only while the signed source inputs remain authentic."""

    capability: _BundleCapability | None = None
    try:
        capability = _load_bundle(root, _S04_PREFIX, bundle_sha256)
        result = _issue_s04(capability, bundle_sha256, inputs)
        capability = None
        if not result.validate():
            result.close()
            return None
        return result
    except (OSError, TypeError, ValueError, ScenarioEvidenceUnavailable):
        return None
    finally:
        if capability is not None:
            capability.close()


def load_s05_update_bundle(
    root: Path,
    bundle_sha256: str,
    *,
    inputs: S05ScenarioInputs,
) -> S05UpdateEvidence | None:
    """Fresh-load S-05 only while the signed source inputs remain authentic."""

    capability: _BundleCapability | None = None
    try:
        capability = _load_bundle(root, _S05_PREFIX, bundle_sha256)
        result = _issue_s05(capability, bundle_sha256, inputs)
        capability = None
        if not result.validate():
            result.close()
            return None
        return result
    except (OSError, TypeError, ValueError, ScenarioEvidenceUnavailable):
        return None
    finally:
        if capability is not None:
            capability.close()


def verify_s04_continuity_evidence(value: object) -> bool:
    if not isinstance(value, S04ContinuityEvidence):
        return False
    with _LOCK:
        try:
            return bool(
                _ISSUED_S04.get(id(value)) is value
                and value._authority is _S04_AUTHORITY
                and _verify_s04_inputs_unlocked(value._inputs)
                and id(value._inputs) in _CONSUMED_S04_INPUTS
                and value._capability.validate()
                and value._capability.document == _output_document(value._inputs)
                and value.bundle_sha256
                == hashlib.sha256(value._capability.raw).hexdigest()
                and value.bundle_root_sha256 == value._capability.root_sha256
                and value.input_authority_sha256 == value._inputs.authority_sha256
                and value.publisher_signature_sha256 == value._inputs.signature_sha256
                and value.evidence_sha256
                == canonical_sha256(
                    _evidence_identity(value._capability, value.bundle_sha256)
                )
                and all(
                    getattr(value, key) == item
                    for key, item in value._capability.document.items()
                    if key != "scenario_id"
                )
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return False


def verify_s05_update_evidence(value: object) -> bool:
    if not isinstance(value, S05UpdateEvidence):
        return False
    with _LOCK:
        try:
            return bool(
                _ISSUED_S05.get(id(value)) is value
                and value._authority is _S05_AUTHORITY
                and _verify_s05_inputs_unlocked(value._inputs)
                and id(value._inputs) in _CONSUMED_S05_INPUTS
                and value._capability.validate()
                and value._capability.document == _output_document(value._inputs)
                and value.bundle_sha256
                == hashlib.sha256(value._capability.raw).hexdigest()
                and value.bundle_root_sha256 == value._capability.root_sha256
                and value.input_authority_sha256 == value._inputs.authority_sha256
                and value.publisher_signature_sha256 == value._inputs.signature_sha256
                and value.evidence_sha256
                == canonical_sha256(
                    _evidence_identity(value._capability, value.bundle_sha256)
                )
                and all(
                    getattr(value, key) == item
                    for key, item in value._capability.document.items()
                    if key != "scenario_id"
                )
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return False


def s04_continuity_evidence_document(
    value: S04ContinuityEvidence,
) -> dict[str, object]:
    if not verify_s04_continuity_evidence(value):
        raise ScenarioEvidenceUnavailable("S-04 evidence is not authentic.")
    return {
        **value._capability.document,
        "evidence_sha256": value.evidence_sha256,
        "bundle_sha256": value.bundle_sha256,
        "bundle_root_sha256": value.bundle_root_sha256,
    }


def s05_update_evidence_document(value: S05UpdateEvidence) -> dict[str, object]:
    if not verify_s05_update_evidence(value):
        raise ScenarioEvidenceUnavailable("S-05 evidence is not authentic.")
    return {
        **value._capability.document,
        "evidence_sha256": value.evidence_sha256,
        "bundle_sha256": value.bundle_sha256,
        "bundle_root_sha256": value.bundle_root_sha256,
    }


__all__ = [
    "S04_SCHEMA_VERSION",
    "S05_SCHEMA_VERSION",
    "S04ContinuityEvidence",
    "S04ScenarioInputs",
    "S05ScenarioInputs",
    "S05UpdateEvidence",
    "ScenarioEvidenceUnavailable",
    "load_s04_continuity_bundle",
    "load_s05_update_bundle",
    "prepare_s04_publisher_claim",
    "prepare_s05_publisher_claim",
    "retain_s04_scenario_inputs",
    "retain_s05_scenario_inputs",
    "s04_continuity_evidence_document",
    "s05_update_evidence_document",
    "verify_s04_continuity_evidence",
    "verify_s04_scenario_inputs",
    "verify_s05_scenario_inputs",
    "verify_s05_update_evidence",
    "write_s04_continuity_bundle",
    "write_s05_update_bundle",
]
