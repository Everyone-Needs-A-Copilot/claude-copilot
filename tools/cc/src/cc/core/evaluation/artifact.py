"""Canonical content-addressed evaluation artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote

from cc.core.evaluation.comparison import (
    verify_comparison_record_identity,
)
from cc.core.evaluation.models import (
    ArtifactReceipt,
    ComparisonRecord,
    EvaluationCell,
    GateState,
    PreflightGate,
    PreflightState,
    RunRecord,
    RunState,
    RuntimeOutput,
)
from cc.core.evaluation.runner import run_record_document, verify_run_record_identity
from cc.core.evaluation.safety import (
    FixtureSafetyViolation,
    require_safe_synthetic_text,
)
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256

_FORBIDDEN_AGGREGATES = frozenset(
    {"score", "total", "average", "percent", "percentage", "rank", "winner"}
)
_ARTIFACT_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
_ISSUED_ARTIFACT_RECEIPTS: dict[int, ArtifactReceipt] = {}
_RUN_DOCUMENT_KEYS = frozenset(
    {
        "schema_version",
        "run_sha256",
        "case_id",
        "revision",
        "variant",
        "runtime",
        "attempt",
        "parent_attempt_sha256",
        "fixture_sha256",
        "prompt_evidence_sha256",
        "attempt_policy_sha256",
        "runtime_configuration_sha256",
        "tool_configuration_sha256",
        "effective_full_prompt_sha256",
        "command_policy_sha256",
        "comparability_sha256",
        "runtime_receipt_sha256",
        "content_receipt_sha256",
        "consumption_receipt_sha256",
        "preflight",
        "state",
        "output_sha256",
        "controlled_artifact_path",
        "completion_evidence_sha256",
        "technical_error_reason",
        "technical_error_evidence_sha256",
    }
)


def _expected_run_identity(cell: EvaluationCell) -> dict[str, object]:
    from cc.core.evaluation.comparison import comparability_identity
    from cc.core.evaluation.identity import (
        consumption_receipt_identity,
        content_receipt_identity,
        runtime_receipt_identity,
    )

    return {
        "schema_version": "1.4",
        "case_id": cell.case_id,
        "revision": cell.revision,
        "variant": cell.variant.value,
        "runtime": cell.runtime_receipt.runtime.value,
        "attempt": cell.attempt,
        "parent_attempt_sha256": cell.parent_attempt_sha256,
        "fixture_sha256": cell.fixture_sha256,
        "prompt_evidence_sha256": cell.prompt_evidence_sha256,
        "attempt_policy_sha256": cell.attempt_policy_sha256,
        "runtime_configuration_sha256": cell.runtime_configuration_sha256,
        "tool_configuration_sha256": cell.tool_configuration_sha256,
        "effective_full_prompt_sha256": cell.effective_full_prompt_sha256,
        "command_policy_sha256": cell.command_policy_sha256,
        "comparability_sha256": comparability_identity(cell),
        "runtime_receipt_sha256": runtime_receipt_identity(cell.runtime_receipt),
        "content_receipt_sha256": content_receipt_identity(cell.content_receipt),
        "consumption_receipt_sha256": consumption_receipt_identity(
            cell.consumption_receipt
        ),
    }


def _record_matches_cell(record: RunRecord, cell: EvaluationCell) -> bool:
    expected = _expected_run_identity(cell)
    return all(
        (
            getattr(record, field).value
            if field in {"variant", "runtime"}
            else getattr(record, field)
        )
        == value
        for field, value in expected.items()
    )


def _document_matches_cell(
    document: Mapping[str, object], cell: EvaluationCell
) -> bool:
    return all(
        document.get(field) == value
        for field, value in _expected_run_identity(cell).items()
    )


def _reject_aggregate_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = "".join(
                character
                for character in unicodedata.normalize("NFKC", str(key)).casefold()
                if character.isalnum()
            )
            # This is an operational retry-lineage count, not an effectiveness
            # aggregate. Its exact closed name is part of the execution schema.
            if normalized == "totalattemptsstarted":
                _reject_aggregate_fields(item)
                continue
            if any(
                stem in normalized
                for stem in _FORBIDDEN_AGGREGATES
                | {"scores", "totals", "ranks", "winners"}
            ):
                raise ValueError("Aggregate evaluation fields are prohibited.")
            _reject_aggregate_fields(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_aggregate_fields(item)


def _write_all(file_descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(file_descriptor, content[offset:])
        if written < 1:
            raise OSError("Evaluation artifact write did not make progress.")
        offset += written


def _stable_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
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


def _stable_directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
    )


def _require_private_directory(
    file_descriptor: int, *, description: str
) -> os.stat_result:
    metadata = os.fstat(file_descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError(
            f"{description} must be a current-user-owned mode-0700 directory."
        )
    return metadata


def _require_named_directory(
    parent_fd: int,
    name: str,
    opened: os.stat_result,
    *,
    description: str,
) -> None:
    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if (
        not stat.S_ISDIR(named.st_mode)
        or named.st_uid != os.geteuid()
        or stat.S_IMODE(named.st_mode) != 0o700
        or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise ValueError(f"{description} path identity is not private and stable.")


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _descriptor_path(file_descriptor: int) -> Path:
    """Return the kernel-reported path for one retained directory descriptor."""

    if sys.platform == "darwin":
        import fcntl

        raw = fcntl.fcntl(file_descriptor, 50, b"\0" * 1024)
        value = raw.split(b"\0", 1)[0].decode()
    elif sys.platform.startswith("linux"):
        value = os.readlink(f"/proc/self/fd/{file_descriptor}")
    else:
        raise ValueError("Retained artifact-root path binding is unsupported.")
    path = Path(value)
    if not path.is_absolute() or Path(os.path.realpath(path)) != path:
        raise ValueError("Retained artifact-root path identity is not canonical.")
    return path


def _require_traversal_directory(file_descriptor: int, *, description: str) -> None:
    metadata = os.fstat(file_descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in {0, os.geteuid()}
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise ValueError(
            f"{description} must be trusted-owned without group/world write access."
        )


def _open_root_directory(root: Path) -> int:
    """Open every root component relative to a retained, non-symlink FD."""

    path = Path(root)
    if path.is_absolute():
        anchor = path.anchor
        components = path.parts[1:]
    else:
        anchor = "."
        components = path.parts
    current_fd = os.open(anchor, _directory_open_flags())
    try:
        _require_traversal_directory(current_fd, description="Artifact path anchor")
        for component in components:
            if component in {"", "."}:
                continue
            if component == "..":
                raise ValueError("Evaluation artifact root cannot traverse upward.")
            next_fd = os.open(
                component,
                _directory_open_flags(),
                dir_fd=current_fd,
            )
            try:
                _require_traversal_directory(
                    next_fd, description="Artifact path component"
                )
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        _require_private_directory(current_fd, description="Evaluation artifact root")
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _read_verified_artifact(
    type_fd: int,
    filename: str,
    *,
    digest: str,
    expected_content: bytes | None = None,
    maximum_size: int | None = None,
) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    file_fd = os.open(
        filename,
        os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
        dir_fd=type_fd,
    )
    try:
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or (maximum_size is not None and before.st_size > maximum_size)
            or (
                expected_content is not None and before.st_size != len(expected_content)
            )
        ):
            raise ValueError(
                "Existing evaluation artifact is not a private stable regular file."
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        after = os.fstat(file_fd)
        named = os.stat(filename, dir_fd=type_fd, follow_symlinks=False)
        if (
            _stable_file_identity(before) != _stable_file_identity(after)
            or not stat.S_ISREG(named.st_mode)
            or named.st_nlink != 1
            or named.st_uid != os.geteuid()
            or stat.S_IMODE(named.st_mode) != 0o600
            or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)
            or (expected_content is not None and content != expected_content)
            or hashlib.sha256(content).hexdigest() != digest
        ):
            raise ValueError("Content-addressed artifact identity collision.")
        return content
    finally:
        os.close(file_fd)


def _verify_named_artifact(
    type_fd: int, filename: str, content: bytes, digest: str
) -> None:
    """Bind verified bytes and inode to the final directory entry."""

    _read_verified_artifact(
        type_fd,
        filename,
        digest=digest,
        expected_content=content,
    )


def _verify_retained_artifact(
    leaf_fd: int,
    type_fd: int,
    filename: str,
    content: bytes,
    digest: str,
) -> None:
    """Verify exact bytes through a retained leaf FD and rebind its name."""

    before = os.fstat(leaf_fd)
    if before.st_nlink == 0:
        raise ValueError("Retained evaluation artifact identity changed.")
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size != len(content)
    ):
        raise ValueError(
            "Existing evaluation artifact is not a private stable regular file."
        )
    os.lseek(leaf_fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = before.st_size
    while remaining:
        chunk = os.read(leaf_fd, min(remaining, 65536))
        if not chunk:
            raise ValueError("Retained evaluation artifact is incomplete.")
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(leaf_fd)
    named = os.stat(filename, dir_fd=type_fd, follow_symlinks=False)
    if (
        b"".join(chunks) != content
        or hashlib.sha256(content).hexdigest() != digest
        or _stable_file_identity(before) != _stable_file_identity(after)
        or _stable_file_identity(named) != _stable_file_identity(after)
    ):
        raise ValueError("Retained evaluation artifact identity changed.")


class _ArtifactCapability:
    """Own retained root/type/leaf descriptors for one accepted artifact."""

    def __init__(
        self,
        root_fd: int,
        type_fd: int,
        leaf_fd: int,
        artifact_type: str,
        filename: str,
        content: bytes,
        digest: str,
    ) -> None:
        self._root_fd = root_fd
        self._type_fd = type_fd
        self._leaf_fd = leaf_fd
        self._parent_fd = -1
        self._root_path = _descriptor_path(root_fd)
        self._root_name = self._root_path.name
        self._parent_fd = os.open(self._root_path.parent, _directory_open_flags())
        self._root_identity = _stable_directory_identity(os.fstat(root_fd))
        self._artifact_type = artifact_type
        self._filename = filename
        self._content = content
        self._digest = digest

    def validate(self) -> None:
        if min(self._parent_fd, self._root_fd, self._type_fd, self._leaf_fd) < 0:
            raise ValueError("Artifact capability is closed.")
        root_opened = os.fstat(self._root_fd)
        root_named = os.stat(
            self._root_name,
            dir_fd=self._parent_fd,
            follow_symlinks=False,
        )
        if (
            _descriptor_path(self._root_fd) != self._root_path
            or _stable_directory_identity(root_opened) != self._root_identity
            or _stable_directory_identity(root_named) != self._root_identity
        ):
            raise ValueError("Evaluation artifact root path identity changed.")
        _require_private_directory(
            self._root_fd,
            description="Evaluation artifact root",
        )
        metadata = _require_private_directory(
            self._type_fd,
            description="Evaluation artifact type directory",
        )
        _require_named_directory(
            self._root_fd,
            self._artifact_type,
            metadata,
            description="Evaluation artifact type directory",
        )
        _verify_retained_artifact(
            self._leaf_fd,
            self._type_fd,
            self._filename,
            self._content,
            self._digest,
        )

    def close(self) -> None:
        for name in ("_leaf_fd", "_type_fd", "_root_fd", "_parent_fd"):
            descriptor = getattr(self, name, -1)
            if descriptor >= 0:
                os.close(descriptor)
                setattr(self, name, -1)

    def __del__(self) -> None:
        self.close()


class _CompositeArtifactCapability:
    """Retain one run artifact and every evidence document it references."""

    def __init__(self, capabilities: tuple[_ArtifactCapability, ...]) -> None:
        if not capabilities:
            raise ValueError("Composite artifact capability cannot be empty.")
        self._capabilities = capabilities

    def validate(self) -> None:
        for capability in self._capabilities:
            capability.validate()

    def close(self) -> None:
        for capability in self._capabilities:
            capability.close()

    def __del__(self) -> None:
        self.close()


_LOADED_RUN_AUTHORITY = object()
_ISSUED_LOADED_RUNS: dict[int, "LoadedDurableRunEvidence"] = {}


@dataclass(frozen=True)
class LoadedDurableRunEvidence:
    """Fresh-process, verifier-resealed run plus retained namespace proof."""

    record: RunRecord
    _capability: _CompositeArtifactCapability
    _authority: object

    def __post_init__(self) -> None:
        if self._authority is not _LOADED_RUN_AUTHORITY:
            raise ValueError("Loaded run evidence is not verifier-issued.")

    def validate(self) -> bool:
        if _ISSUED_LOADED_RUNS.get(id(self)) is not self:
            return False
        try:
            self._capability.validate()
        except (OSError, ValueError):
            return False
        return verify_run_record_identity(self.record)

    def close(self) -> None:
        """Revoke this loaded evidence and release every retained descriptor."""

        if _ISSUED_LOADED_RUNS.get(id(self)) is not self:
            return
        _ISSUED_LOADED_RUNS.pop(id(self), None)
        self._capability.close()


def verify_artifact_receipt(receipt: ArtifactReceipt) -> bool:
    """Revalidate a receipt through its retained leaf capability."""

    if _ISSUED_ARTIFACT_RECEIPTS.get(id(receipt)) is not receipt:
        return False
    capability = getattr(receipt, "_capability", None)
    if not isinstance(capability, (_ArtifactCapability, _CompositeArtifactCapability)):
        return False
    try:
        capability.validate()
    except (OSError, ValueError):
        return False
    return True


def close_artifact_receipt(receipt: ArtifactReceipt) -> None:
    """Revoke a durable-write receipt and release its retained descriptors."""

    if _ISSUED_ARTIFACT_RECEIPTS.get(id(receipt)) is not receipt:
        return
    _ISSUED_ARTIFACT_RECEIPTS.pop(id(receipt), None)
    capability = getattr(receipt, "_capability", None)
    close = getattr(capability, "close", None)
    if callable(close):
        close()


def _issue_artifact_receipt(
    *,
    artifact_type: str,
    sha256: str,
    relative_path: str,
    size_bytes: int,
    capability: object,
) -> ArtifactReceipt:
    receipt = ArtifactReceipt(
        artifact_type=artifact_type,
        sha256=sha256,
        relative_path=relative_path,
        size_bytes=size_bytes,
        _capability=capability,
    )
    _ISSUED_ARTIFACT_RECEIPTS[id(receipt)] = receipt
    return receipt


def _verify_storage_snapshot(
    root_fd: int,
    type_fd: int,
    artifact_type: str,
    filename: str,
    content: bytes,
    digest: str,
    *,
    leaf_fd: int | None = None,
) -> None:
    """Make the retained-FD validation the final operation before a receipt."""

    _require_private_directory(root_fd, description="Evaluation artifact root")
    type_metadata = _require_private_directory(
        type_fd, description="Evaluation artifact type directory"
    )
    if leaf_fd is None:
        _verify_named_artifact(type_fd, filename, content, digest)
    else:
        _verify_retained_artifact(leaf_fd, type_fd, filename, content, digest)
    _require_named_directory(
        root_fd,
        artifact_type,
        type_metadata,
        description="Evaluation artifact type directory",
    )
    if leaf_fd is not None:
        _verify_retained_artifact(leaf_fd, type_fd, filename, content, digest)


def _open_artifact_type_directory(
    root_fd: int, artifact_type: str, *, create: bool
) -> int:
    created = False
    if create:
        try:
            os.mkdir(artifact_type, mode=0o700, dir_fd=root_fd)
            created = True
            os.chmod(
                artifact_type,
                0o700,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
    type_fd = os.open(
        artifact_type,
        _directory_open_flags(),
        dir_fd=root_fd,
    )
    try:
        if created:
            os.fchmod(type_fd, 0o700)
        type_metadata = _require_private_directory(
            type_fd, description="Evaluation artifact type directory"
        )
        _require_named_directory(
            root_fd,
            artifact_type,
            type_metadata,
            description="Evaluation artifact type directory",
        )
        return type_fd
    except Exception:
        os.close(type_fd)
        raise


def _reject_disclosure_values(value: object) -> None:
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_disclosure_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_disclosure_values(item)
    elif isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value)
        decoded = normalized
        for _ in range(4):
            candidate = unquote(decoded)
            if candidate == decoded:
                break
            decoded = candidate
        if normalized != value or decoded != normalized:
            raise ValueError("Evaluation artifact metadata is not canonical.")
        try:
            require_safe_synthetic_text(decoded, location_class="artifact-metadata")
        except FixtureSafetyViolation as exc:
            raise ValueError(
                "Evaluation artifact metadata is disclosure-unsafe."
            ) from exc


def _write_linked_evidence_document(
    root_fd: int,
    artifact_type: str,
    document: Mapping[str, object],
    *,
    expected_sha256: str,
) -> _ArtifactCapability:
    """Write and retain one exact content-addressed receipt document."""

    content = canonical_json_bytes(dict(document))
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("Linked evidence identity does not match its document.")
    _reject_aggregate_fields(document)
    _reject_disclosure_values(document)
    filename = f"{expected_sha256}.json"
    staging_name = f".{expected_sha256}.{secrets.token_hex(12)}.tmp"
    type_fd = _open_artifact_type_directory(root_fd, artifact_type, create=True)
    artifact_fd: int | None = None
    durable_fd: int | None = None
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    try:
        metadata = _require_private_directory(
            type_fd,
            description="Evaluation evidence directory",
        )
        _require_named_directory(
            root_fd,
            artifact_type,
            metadata,
            description="Evaluation evidence directory",
        )
        try:
            artifact_fd = os.open(
                staging_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | cloexec,
                0o600,
                dir_fd=type_fd,
            )
            os.fchmod(artifact_fd, 0o600)
            _write_all(artifact_fd, content)
            os.fsync(artifact_fd)
            os.close(artifact_fd)
            artifact_fd = None
            os.link(
                staging_name,
                filename,
                src_dir_fd=type_fd,
                dst_dir_fd=type_fd,
                follow_symlinks=False,
            )
            os.unlink(staging_name, dir_fd=type_fd)
        except FileExistsError:
            try:
                os.unlink(staging_name, dir_fd=type_fd)
            except FileNotFoundError:
                pass
        durable_fd = os.open(
            filename,
            os.O_RDONLY | nofollow | cloexec,
            dir_fd=type_fd,
        )
        os.fsync(durable_fd)
        os.fsync(type_fd)
        os.fsync(root_fd)
        _verify_storage_snapshot(
            root_fd,
            type_fd,
            artifact_type,
            filename,
            content,
            expected_sha256,
            leaf_fd=durable_fd,
        )
        capability = _ArtifactCapability(
            os.dup(root_fd),
            os.dup(type_fd),
            durable_fd,
            artifact_type,
            filename,
            content,
            expected_sha256,
        )
        durable_fd = None
        capability.validate()
        return capability
    finally:
        if artifact_fd is not None:
            os.close(artifact_fd)
        if durable_fd is not None:
            os.close(durable_fd)
        try:
            os.unlink(staging_name, dir_fd=type_fd)
        except FileNotFoundError:
            pass
        os.close(type_fd)


def _linked_evidence_documents(
    cell: EvaluationCell,
    record: RunRecord,
    authenticated_output: RuntimeOutput | None,
) -> tuple[tuple[str, Mapping[str, object], str], ...]:
    from cc.core.evaluation.identity import (
        consumption_receipt_document,
        content_receipt_document,
        runtime_receipt_document,
    )

    documents: list[tuple[str, Mapping[str, object], str]] = [
        (
            "runtime-receipt",
            runtime_receipt_document(cell.runtime_receipt),
            record.runtime_receipt_sha256,
        ),
        (
            "content-receipt",
            content_receipt_document(cell.content_receipt),
            record.content_receipt_sha256,
        ),
        (
            "consumption-receipt",
            consumption_receipt_document(cell.consumption_receipt),
            record.consumption_receipt_sha256,
        ),
    ]
    if record.state is RunState.COMPLETED:
        from cc.core.evaluation.live_runtime import (
            AuthenticatedRuntimeOutput,
            runtime_completion_receipt_document,
        )

        if not isinstance(authenticated_output, AuthenticatedRuntimeOutput):
            raise ValueError("Completed evidence requires sealed runtime output.")
        receipt = authenticated_output.completion_receipt
        execution_document = json.loads(receipt._execution_policy_document)
        if not isinstance(execution_document, Mapping):
            raise ValueError("Execution policy receipt is malformed.")
        documents.extend(
            (
                (
                    "execution-policy-receipt",
                    execution_document,
                    receipt.execution_policy_sha256,
                ),
                (
                    "completion-receipt",
                    runtime_completion_receipt_document(receipt),
                    record.completion_evidence_sha256 or "",
                ),
            )
        )
    elif record.state is RunState.TECHNICAL_ERROR:
        from cc.core.evaluation.live_runtime import (
            runtime_technical_execution_document,
            runtime_technical_failure_document,
        )

        evidence_sha256 = record.technical_error_evidence_sha256 or ""
        receipt_document = runtime_technical_failure_document(evidence_sha256)
        execution_document = runtime_technical_execution_document(evidence_sha256)
        if receipt_document is None or execution_document is None:
            raise ValueError("Technical error lacks verifier-issued evidence.")
        execution_sha256 = receipt_document.get("execution_policy_sha256")
        if not isinstance(execution_sha256, str):
            raise ValueError("Technical execution-policy identity is absent.")
        documents.extend(
            (
                (
                    "execution-policy-receipt",
                    execution_document,
                    execution_sha256,
                ),
                (
                    "technical-failure-receipt",
                    receipt_document,
                    evidence_sha256,
                ),
            )
        )
    return tuple(documents)


def _write_artifact(
    root: Path,
    record: RunRecord | ComparisonRecord,
    *,
    cell: EvaluationCell | None = None,
    loaded_fixture: object = None,
    journey_run_id: str = "",
    journey_ledger: object = None,
    authenticated_output: RuntimeOutput | None = None,
) -> ArtifactReceipt:
    """Write only a production-revalidated record below a non-symlink root."""

    if isinstance(record, ComparisonRecord):
        raise ValueError(
            "Comparison artifacts require production completion authority."
        )
    if not isinstance(record, RunRecord):
        raise ValueError("Artifact writes require production-authoritative evidence.")
    artifact_type = "run-record"
    root_fd = _open_root_directory(root)
    type_fd: int | None = None
    capability: _ArtifactCapability | _CompositeArtifactCapability | None = None
    linked_capabilities: list[_ArtifactCapability] = []
    try:
        type_fd = _open_artifact_type_directory(root_fd, artifact_type, create=True)
        if not _production_record_valid(
            root,
            record,
            cell=cell,
            loaded_fixture=loaded_fixture,
            journey_run_id=journey_run_id,
            journey_ledger=journey_ledger,
            authenticated_output=authenticated_output,
            root_fd=root_fd,
            type_fd=type_fd,
        ):
            raise ValueError(
                "Artifact writes require production-authoritative evidence."
            )
        if cell is None:
            raise ValueError("Run evidence requires its exact evaluation cell.")
        for artifact_name, document, expected_sha256 in _linked_evidence_documents(
            cell,
            record,
            authenticated_output,
        ):
            linked_capabilities.append(
                _write_linked_evidence_document(
                    root_fd,
                    artifact_name,
                    document,
                    expected_sha256=expected_sha256,
                )
            )
        payload = run_record_document(record)
        _reject_aggregate_fields(payload)
        _reject_disclosure_values(payload)
        content = canonical_json_bytes(dict(payload))
        digest = hashlib.sha256(content).hexdigest()
        filename = f"{digest}.json"
        staging_name = f".{digest}.{secrets.token_hex(12)}.tmp"
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        artifact_fd: int | None = None
        durable_fd: int | None = None
        try:
            type_metadata = _require_private_directory(
                type_fd, description="Evaluation artifact type directory"
            )
            _require_named_directory(
                root_fd,
                artifact_type,
                type_metadata,
                description="Evaluation artifact type directory",
            )
            try:
                artifact_fd = os.open(
                    staging_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | cloexec,
                    0o600,
                    dir_fd=type_fd,
                )
                os.fchmod(artifact_fd, 0o600)
                _write_all(artifact_fd, content)
                os.fsync(artifact_fd)
                os.close(artifact_fd)
                artifact_fd = None
                os.link(
                    staging_name,
                    filename,
                    src_dir_fd=type_fd,
                    dst_dir_fd=type_fd,
                    follow_symlinks=False,
                )
                os.unlink(staging_name, dir_fd=type_fd)
            except FileExistsError:
                try:
                    os.unlink(staging_name, dir_fd=type_fd)
                except FileNotFoundError:
                    pass
            durable_fd = os.open(
                filename,
                os.O_RDONLY | nofollow | cloexec,
                dir_fd=type_fd,
            )
            os.fsync(durable_fd)
            os.fsync(type_fd)
            os.fsync(root_fd)
            _verify_storage_snapshot(
                root_fd,
                type_fd,
                artifact_type,
                filename,
                content,
                digest,
                leaf_fd=durable_fd,
            )
            capability = _ArtifactCapability(
                os.dup(root_fd),
                os.dup(type_fd),
                durable_fd,
                artifact_type,
                filename,
                content,
                digest,
            )
            durable_fd = None
            capability.validate()
            capability = _CompositeArtifactCapability(
                (capability, *linked_capabilities)
            )
            linked_capabilities = []
            capability.validate()
        except Exception:
            if artifact_fd is not None:
                os.close(artifact_fd)
            if durable_fd is not None:
                os.close(durable_fd)
            if capability is not None:
                capability.close()
                capability = None
            try:
                os.unlink(staging_name, dir_fd=type_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(type_fd)
            type_fd = None
    finally:
        if type_fd is not None:
            os.close(type_fd)
        for linked in linked_capabilities:
            linked.close()
        os.close(root_fd)
    return _issue_artifact_receipt(
        artifact_type=artifact_type,
        sha256=digest,
        relative_path=f"{artifact_type}/{filename}",
        size_bytes=len(content),
        capability=capability,
    )


def write_run_record(
    root: Path,
    record: RunRecord,
    *,
    cell: EvaluationCell,
    loaded_fixture: object = None,
    journey_run_id: str = "",
    journey_ledger: object = None,
    authenticated_output: RuntimeOutput | None = None,
) -> ArtifactReceipt:
    return _write_artifact(
        root,
        record,
        cell=cell,
        loaded_fixture=loaded_fixture,
        journey_run_id=journey_run_id,
        journey_ledger=journey_ledger,
        authenticated_output=authenticated_output,
    )


def write_comparison_record(
    root: Path,
    record: ComparisonRecord,
    *,
    control_judgment: object,
    layered_judgment: object,
) -> ArtifactReceipt:
    """Persist only an authentic comparison with exact judgment identities."""

    from cc.core.evaluation.judgment import LoadedDurableJudgmentEvidence

    if (
        not verify_comparison_record_identity(record)
        or not isinstance(control_judgment, LoadedDurableJudgmentEvidence)
        or not isinstance(layered_judgment, LoadedDurableJudgmentEvidence)
        or not control_judgment.validate()
        or not layered_judgment.validate()
        or record.control_run_sha256 != control_judgment.loaded_run.record.run_sha256
        or record.layered_run_sha256 != layered_judgment.loaded_run.record.run_sha256
        or record.control_judgment_sha256 != control_judgment.judgment.judgment_sha256
        or record.layered_judgment_sha256 != layered_judgment.judgment.judgment_sha256
    ):
        raise ValueError(
            "Comparison artifact requires an authentic coordinator record."
        )
    from cc.core.evaluation.comparison import comparison_record_document

    return _write_standalone_evidence_document(
        root,
        "comparison-record",
        comparison_record_document(record),
    )


def _write_standalone_evidence_document(
    root: Path,
    artifact_type: str,
    document: Mapping[str, object],
) -> ArtifactReceipt:
    """Persist one already-authorized shared document with a retained receipt."""

    digest = canonical_sha256(document)
    root_fd = _open_root_directory(root)
    capability: _ArtifactCapability | None = None
    try:
        capability = _write_linked_evidence_document(
            root_fd,
            artifact_type,
            document,
            expected_sha256=digest,
        )
        capability.validate()
        return _issue_artifact_receipt(
            artifact_type=artifact_type,
            sha256=digest,
            relative_path=f"{artifact_type}/{digest}.json",
            size_bytes=len(canonical_json_bytes(dict(document))),
            capability=capability,
        )
    except Exception:
        if capability is not None:
            capability.close()
        raise
    finally:
        os.close(root_fd)


def write_criterion_judgment(
    root: Path,
    judgment: object,
    *,
    loaded_run: LoadedDurableRunEvidence,
) -> ArtifactReceipt:
    """Persist a value-suppressing judgment only for a retained durable run."""

    from cc.core.evaluation.judgment import (
        CriterionJudgment,
        criterion_judgment_document,
        verify_criterion_judgment_identity,
    )

    if (
        not isinstance(judgment, CriterionJudgment)
        or not verify_criterion_judgment_identity(judgment)
        or not isinstance(loaded_run, LoadedDurableRunEvidence)
        or not loaded_run.validate()
        or judgment.run_sha256 != loaded_run.record.run_sha256
    ):
        raise ValueError("Judgment artifact requires exact durable run evidence.")
    return _write_standalone_evidence_document(
        root,
        "criterion-judgment",
        criterion_judgment_document(judgment),
    )


def _load_linked_document(
    root_fd: int,
    artifact_type: str,
    digest: str,
) -> dict[str, object]:
    type_fd = _open_artifact_type_directory(root_fd, artifact_type, create=False)
    try:
        raw = _read_verified_artifact(
            type_fd,
            f"{digest}.json",
            digest=digest,
            maximum_size=1_048_576,
        )
        value = json.loads(raw)
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise ValueError("Durable evidence document is not canonical.")
        metadata = _require_private_directory(
            type_fd,
            description="Evaluation evidence directory",
        )
        _require_named_directory(
            root_fd,
            artifact_type,
            metadata,
            description="Evaluation evidence directory",
        )
        return value
    finally:
        os.close(type_fd)


def _open_linked_document(
    root_fd: int,
    artifact_type: str,
    digest: str,
) -> tuple[dict[str, object], _ArtifactCapability]:
    """Load one canonical document and retain its root/type/leaf identity."""

    filename = f"{digest}.json"
    raw, capability = _open_linked_bytes(
        root_fd,
        artifact_type,
        filename,
        digest,
        maximum_size=1_048_576,
    )
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise ValueError("Durable evidence document is not canonical.")
        return value, capability
    except Exception:
        capability.close()
        raise


def _open_linked_bytes(
    root_fd: int,
    artifact_type: str,
    filename: str,
    digest: str,
    *,
    maximum_size: int,
) -> tuple[bytes, _ArtifactCapability]:
    type_fd = _open_artifact_type_directory(root_fd, artifact_type, create=False)
    leaf_fd: int | None = None
    try:
        raw = _read_verified_artifact(
            type_fd,
            filename,
            digest=digest,
            maximum_size=maximum_size,
        )
        leaf_fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=type_fd,
        )
        metadata = _require_private_directory(
            type_fd,
            description="Evaluation evidence directory",
        )
        _require_named_directory(
            root_fd,
            artifact_type,
            metadata,
            description="Evaluation evidence directory",
        )
        _verify_retained_artifact(leaf_fd, type_fd, filename, raw, digest)
        capability = _ArtifactCapability(
            os.dup(root_fd),
            os.dup(type_fd),
            leaf_fd,
            artifact_type,
            filename,
            raw,
            digest,
        )
        leaf_fd = None
        capability.validate()
        return raw, capability
    finally:
        if leaf_fd is not None:
            os.close(leaf_fd)
        os.close(type_fd)


def _retain_durable_run_evidence(
    root: Path,
    record: RunRecord,
) -> _CompositeArtifactCapability:
    if not verify_run_record_identity(record):
        raise ValueError("Run record is not authentic.")
    root_fd = _open_root_directory(root)
    capabilities: list[_ArtifactCapability] = []

    def document(artifact_type: str, digest: str) -> dict[str, object]:
        value, capability = _open_linked_document(
            root_fd,
            artifact_type,
            digest,
        )
        capabilities.append(capability)
        return value

    try:
        runtime = document("runtime-receipt", record.runtime_receipt_sha256)
        document("content-receipt", record.content_receipt_sha256)
        consumption = document("consumption-receipt", record.consumption_receipt_sha256)
        if (
            runtime.get("runtime") != record.runtime.value
            or consumption.get("runtime_receipt_sha256")
            != record.runtime_receipt_sha256
            or consumption.get("content_receipt_sha256")
            != record.content_receipt_sha256
            or consumption.get("prompt_evidence_sha256")
            != record.prompt_evidence_sha256
        ):
            raise ValueError("Durable run receipt bindings changed.")
        run_document = run_record_document(record)
        run_digest = canonical_sha256(run_document)
        if document("run-record", run_digest) != run_document:
            raise ValueError("Durable run document changed.")
        if record.state is RunState.COMPLETED:
            if (
                record.completion_evidence_sha256 is None
                or record.output_sha256 is None
                or record.controlled_artifact_path
                != f"runtime-quarantine/{record.output_sha256}.txt"
            ):
                raise ValueError("Completed output binding is invalid.")
            completion = document(
                "completion-receipt", record.completion_evidence_sha256
            )
            execution_digest = completion.get("execution_policy_sha256")
            if not isinstance(execution_digest, str):
                raise ValueError("Execution policy binding is absent.")
            execution = document("execution-policy-receipt", execution_digest)
            if (
                completion.get("runtime") != record.runtime.value
                or completion.get("adapter_name") != runtime.get("adapter_name")
                or completion.get("adapter_version") != runtime.get("adapter_version")
                or completion.get("model_version") != runtime.get("model_version")
                or completion.get("invocation_envelope_sha256")
                != consumption.get("invocation_envelope_sha256")
                or completion.get("runtime_configuration_sha256")
                != record.runtime_configuration_sha256
                or completion.get("tool_configuration_sha256")
                != record.tool_configuration_sha256
                or completion.get("full_prompt_sha256")
                != record.effective_full_prompt_sha256
                or completion.get("output_sha256") != record.output_sha256
                or completion.get("command_policy_sha256")
                != record.command_policy_sha256
                or execution.get("command_policy_sha256")
                != record.command_policy_sha256
            ):
                raise ValueError("Durable completion receipt bindings changed.")
            _raw, output_capability = _open_linked_bytes(
                root_fd,
                "runtime-quarantine",
                f"{record.output_sha256}.txt",
                record.output_sha256,
                maximum_size=8 * 1024 * 1024,
            )
            capabilities.append(output_capability)
        elif record.state is RunState.TECHNICAL_ERROR:
            evidence_sha256 = record.technical_error_evidence_sha256
            if evidence_sha256 is None:
                raise ValueError("Technical error evidence identity is absent.")
            technical = document("technical-failure-receipt", evidence_sha256)
            execution_digest = technical.get("execution_policy_sha256")
            if not isinstance(execution_digest, str):
                raise ValueError("Technical execution-policy binding is absent.")
            execution = document("execution-policy-receipt", execution_digest)
            if (
                technical.get("reason") != record.technical_error_reason
                or technical.get("runtime") != record.runtime.value
                or technical.get("case_id") != record.case_id
                or technical.get("revision") != record.revision
                or technical.get("variant") != record.variant.value
                or technical.get("attempt") != record.attempt
                or technical.get("runtime_configuration_sha256")
                != record.runtime_configuration_sha256
                or technical.get("tool_configuration_sha256")
                != record.tool_configuration_sha256
                or technical.get("effective_full_prompt_sha256")
                != record.effective_full_prompt_sha256
                or technical.get("command_policy_sha256")
                != record.command_policy_sha256
                or execution.get("command_policy_sha256")
                != record.command_policy_sha256
                or technical.get("termination_claim")
                != "process-group-terminated-before-adapter-return"
            ):
                raise ValueError("Durable technical failure bindings changed.")
        composite = _CompositeArtifactCapability(tuple(capabilities))
        capabilities = []
        composite.validate()
        return composite
    finally:
        for capability in capabilities:
            capability.close()
        os.close(root_fd)


def verify_durable_run_evidence(root: Path, record: RunRecord) -> bool:
    """Revalidate a persisted run and every exact receipt it references."""

    capability: _CompositeArtifactCapability | None = None
    try:
        capability = _retain_durable_run_evidence(root, record)
        capability.validate()
        return True
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    finally:
        if capability is not None:
            capability.close()


def _find_run_document(root: Path, run_sha256: str) -> dict[str, object] | None:
    root_fd: int | None = None
    type_fd: int | None = None
    matches: list[dict[str, object]] = []
    try:
        root_fd = _open_root_directory(root)
        type_fd = _open_artifact_type_directory(root_fd, "run-record", create=False)
        for name in os.listdir(type_fd):
            if not _ARTIFACT_NAME.fullmatch(name):
                continue
            try:
                raw = _read_verified_artifact(
                    type_fd,
                    name,
                    digest=name[:-5],
                    maximum_size=1_048_576,
                )
                value = json.loads(raw)
            except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and canonical_json_bytes(value) == raw
                and value.get("run_sha256") == run_sha256
            ):
                matches.append(value)
        metadata = _require_private_directory(
            type_fd,
            description="Evaluation run-record directory",
        )
        _require_named_directory(
            root_fd,
            "run-record",
            metadata,
            description="Evaluation run-record directory",
        )
        return matches[0] if len(matches) == 1 else None
    except (OSError, ValueError):
        return None
    finally:
        if type_fd is not None:
            os.close(type_fd)
        if root_fd is not None:
            os.close(root_fd)


def load_durable_completed_run(
    root: Path,
    run_sha256: str,
    *,
    cell: EvaluationCell,
    loaded_fixture: object = None,
    journey_run_id: str = "",
    journey_ledger: object = None,
) -> LoadedDurableRunEvidence | None:
    """Fresh-process loader that reseals only fully reverified COMPLETED evidence."""

    document = _find_run_document(root, run_sha256)
    if (
        document is None
        or set(document) != _RUN_DOCUMENT_KEYS
        or document.get("schema_version") != "1.4"
        or document.get("state") != RunState.COMPLETED.value
        or not _document_matches_cell(document, cell)
    ):
        return None
    from cc.core.evaluation._authority import _production_authority
    from cc.core.evaluation.runner import _preflight_document, _preflight_for, _record

    authority = None
    try:
        authority = _production_authority(
            cell,
            loaded_fixture=loaded_fixture,
            journey_run_id=journey_run_id,
            journey_ledger=journey_ledger,
        )
        expected_preflight = _preflight_for(
            cell,
            authority,
            root,
            loaded_fixture=loaded_fixture,
            journey_run_id=journey_run_id,
            journey_ledger=journey_ledger,
        )
        if expected_preflight.state is not PreflightState.VALID or document.get(
            "preflight"
        ) != _preflight_document(expected_preflight):
            return None
        output_sha256 = document.get("output_sha256")
        controlled_path = document.get("controlled_artifact_path")
        completion_sha256 = document.get("completion_evidence_sha256")
        if not all(
            isinstance(value, str)
            for value in (output_sha256, controlled_path, completion_sha256)
        ):
            return None
        record = _record(
            cell,
            preflight=expected_preflight,
            state=RunState.COMPLETED,
            output_sha256=output_sha256,
            controlled_artifact_path=controlled_path,
            completion_evidence_sha256=completion_sha256,
        )
        if record.run_sha256 != run_sha256 or run_record_document(record) != document:
            return None
        capability = _retain_durable_run_evidence(root, record)
        loaded = LoadedDurableRunEvidence(
            record,
            capability,
            _LOADED_RUN_AUTHORITY,
        )
        _ISSUED_LOADED_RUNS[id(loaded)] = loaded
        if not loaded.validate():
            capability.close()
            return None
        return loaded
    except (OSError, TypeError, ValueError):
        return None
    finally:
        if authority is not None:
            authority.close()


def load_durable_unsupported_run(
    root: Path,
    run_sha256: str,
    *,
    cell: EvaluationCell,
    loaded_fixture: object = None,
    journey_run_id: str = "",
    journey_ledger: object = None,
) -> LoadedDurableRunEvidence | None:
    """Fresh-process loader for an exact zero-output UNSUPPORTED disposition."""

    document = _find_run_document(root, run_sha256)
    if (
        document is None
        or set(document) != _RUN_DOCUMENT_KEYS
        or document.get("schema_version") != "1.4"
        or document.get("state") != RunState.UNSUPPORTED.value
        or not _document_matches_cell(document, cell)
    ):
        return None
    from cc.core.evaluation._authority import _production_authority
    from cc.core.evaluation.runner import (
        _RUNTIME_FAILURE_DISPOSITIONS,
        _preflight_document,
        _preflight_for,
        _record,
        _runtime_failure_record,
    )

    authority = None
    try:
        authority = _production_authority(
            cell,
            loaded_fixture=loaded_fixture,
            journey_run_id=journey_run_id,
            journey_ledger=journey_ledger,
        )
        expected_preflight = _preflight_for(
            cell,
            authority,
            root,
            loaded_fixture=loaded_fixture,
            journey_run_id=journey_run_id,
            journey_ledger=journey_ledger,
        )
        if document.get("preflight") == _preflight_document(expected_preflight):
            if expected_preflight.state is not PreflightState.UNSUPPORTED:
                return None
            record = _record(
                cell,
                preflight=expected_preflight,
                state=RunState.UNSUPPORTED,
            )
        else:
            preflight_document = document.get("preflight")
            observations = (
                preflight_document.get("observations")
                if isinstance(preflight_document, dict)
                else None
            )
            unsupported = (
                [
                    item
                    for item in observations
                    if isinstance(item, dict)
                    and item.get("gate") == PreflightGate.RUNTIME_CAPABILITY.value
                    and item.get("state") == GateState.UNSUPPORTED.value
                    and item.get("reason") in _RUNTIME_FAILURE_DISPOSITIONS
                ]
                if isinstance(observations, list)
                else []
            )
            if len(unsupported) != 1:
                return None
            record = _runtime_failure_record(
                cell,
                expected_preflight,
                str(unsupported[0]["reason"]),
            )
            if record.state is not RunState.UNSUPPORTED:
                return None
        if record.run_sha256 != run_sha256 or run_record_document(record) != document:
            return None
        capability = _retain_durable_run_evidence(root, record)
        loaded = LoadedDurableRunEvidence(
            record,
            capability,
            _LOADED_RUN_AUTHORITY,
        )
        _ISSUED_LOADED_RUNS[id(loaded)] = loaded
        if not loaded.validate():
            capability.close()
            return None
        return loaded
    except (OSError, TypeError, ValueError):
        return None
    finally:
        if authority is not None:
            authority.close()


def _completed_output_valid(
    root_fd: int,
    record: RunRecord,
    cell: EvaluationCell,
    authenticated_output: RuntimeOutput | None,
) -> bool:
    """Revalidate the sealed receipt and the exact private output file."""

    if authenticated_output is None:
        return False
    from cc.core.evaluation.live_runtime import verify_authenticated_completion

    proof = verify_authenticated_completion(
        cell,
        authenticated_output,
        record.output_sha256 or "",
    )
    if (
        proof is None
        or record.preflight.state is not PreflightState.VALID
        or proof.evidence_sha256 != record.completion_evidence_sha256
        or authenticated_output.controlled_artifact_path
        != record.controlled_artifact_path
        or hashlib.sha256(authenticated_output.output_text.encode()).hexdigest()
        != record.output_sha256
    ):
        return False
    if authenticated_output.output_location_class != "private-output":
        return False
    expected_path = f"runtime-quarantine/{record.output_sha256}.txt"
    if record.controlled_artifact_path != expected_path:
        return False
    capability = getattr(authenticated_output, "_artifact_capability", None)
    if (
        not isinstance(capability, _ArtifactCapability)
        or capability._artifact_type != "runtime-quarantine"
        or capability._filename != f"{record.output_sha256}.txt"
        or capability._content != authenticated_output.output_text.encode()
        or capability._digest != record.output_sha256
    ):
        return False
    try:
        capability.validate()
    except (OSError, ValueError):
        return False
    output_fd: int | None = None
    try:
        output_fd = _open_artifact_type_directory(
            root_fd,
            "runtime-quarantine",
            create=False,
        )
        encoded = authenticated_output.output_text.encode()
        _read_verified_artifact(
            output_fd,
            f"{record.output_sha256}.txt",
            digest=record.output_sha256,
            expected_content=encoded,
            maximum_size=8 * 1024 * 1024,
        )
        metadata = _require_private_directory(
            output_fd,
            description="Evaluation runtime quarantine directory",
        )
        _require_named_directory(
            root_fd,
            "runtime-quarantine",
            metadata,
            description="Evaluation runtime quarantine directory",
        )
    except (OSError, ValueError):
        return False
    finally:
        if output_fd is not None:
            os.close(output_fd)
    return True


def _production_record_valid(
    root: Path,
    record: RunRecord,
    *,
    cell: EvaluationCell | None,
    loaded_fixture: object,
    journey_run_id: str,
    journey_ledger: object,
    authenticated_output: RuntimeOutput | None,
    root_fd: int,
    type_fd: int,
) -> bool:
    """Revalidate durable claims; never rely on an in-memory seal alone."""

    if not verify_run_record_identity(record) or not isinstance(cell, EvaluationCell):
        return False
    from cc.core.evaluation._authority import _production_authority
    from cc.core.evaluation.runner import (
        _RUNTIME_FAILURE_DISPOSITIONS,
        _preflight_for,
        _runtime_failure_record,
    )

    authority = _production_authority(
        cell,
        loaded_fixture=loaded_fixture,
        journey_run_id=journey_run_id,
        journey_ledger=journey_ledger,
    )
    try:
        expected_preflight = _preflight_for(
            cell,
            authority,
            root,
            artifact_root_fd=root_fd,
            artifact_type_fd=type_fd,
            loaded_fixture=loaded_fixture,
            journey_run_id=journey_run_id,
            journey_ledger=journey_ledger,
        )
        if record.preflight != expected_preflight:
            changed = tuple(
                item
                for item in record.preflight.observations
                if item.reason in _RUNTIME_FAILURE_DISPOSITIONS
            )
            if len(changed) != 1:
                return False
            expected_failure = _runtime_failure_record(
                cell,
                expected_preflight,
                changed[0].reason,
            )
            if (
                expected_failure.state is not record.state
                or expected_failure.preflight != record.preflight
            ):
                return False
        if not _record_matches_cell(record, cell):
            return False
        if record.state is RunState.INVALID:
            return record.preflight.state is PreflightState.INVALID
        if record.state is RunState.UNSUPPORTED:
            return record.preflight.state is PreflightState.UNSUPPORTED
        if record.state is RunState.DISPATCH_AUTHORIZED:
            return (
                record.preflight.state is PreflightState.VALID
                and record.output_sha256 is None
                and record.controlled_artifact_path is None
                and record.completion_evidence_sha256 is None
            )
        if record.state is RunState.COMPLETED:
            return _completed_output_valid(
                root_fd,
                record,
                cell,
                authenticated_output,
            )
        if record.state is RunState.TECHNICAL_ERROR:
            from cc.core.evaluation.live_runtime import (
                runtime_technical_execution_document,
                runtime_technical_failure_document,
            )

            evidence_sha256 = record.technical_error_evidence_sha256 or ""
            technical = runtime_technical_failure_document(evidence_sha256)
            execution = runtime_technical_execution_document(evidence_sha256)
            return bool(
                record.preflight.state is PreflightState.VALID
                and record.technical_error_reason == "runtime-timeout"
                and technical is not None
                and execution is not None
                and canonical_sha256(technical) == evidence_sha256
                and canonical_sha256(execution)
                == technical.get("execution_policy_sha256")
                and technical.get("runtime") == record.runtime.value
                and technical.get("case_id") == record.case_id
                and technical.get("attempt") == record.attempt
                and technical.get("command_policy_sha256")
                == record.command_policy_sha256
            )
        return False
    finally:
        authority.close()


def load_run_record_document(
    root: Path,
    run_sha256: str,
    *,
    child_cell: EvaluationCell,
    loaded_fixture: object,
    journey_run_id: str,
    journey_ledger: object,
    lineage_depth: int,
    root_fd: int | None = None,
    type_fd: int | None = None,
) -> dict[str, object] | None:
    """Reload one canonical, production-acceptable parent from artifact storage."""

    if lineage_depth >= 32:
        return None
    owned_root_fd: int | None = None
    owned_type_fd: int | None = None
    try:
        owned_root_fd = (
            _open_root_directory(root) if root_fd is None else os.dup(root_fd)
        )
        _require_private_directory(
            owned_root_fd, description="Evaluation artifact root"
        )
        owned_type_fd = (
            _open_artifact_type_directory(owned_root_fd, "run-record", create=False)
            if type_fd is None
            else os.dup(type_fd)
        )
        type_metadata = _require_private_directory(
            owned_type_fd, description="Evaluation artifact type directory"
        )
        _require_named_directory(
            owned_root_fd,
            "run-record",
            type_metadata,
            description="Evaluation artifact type directory",
        )
    except (OSError, ValueError):
        if owned_type_fd is not None:
            os.close(owned_type_fd)
        if owned_root_fd is not None:
            os.close(owned_root_fd)
        return None
    try:
        names = os.listdir(owned_type_fd)
        for name in names:
            if not _ARTIFACT_NAME.fullmatch(name):
                continue
            try:
                raw = _read_verified_artifact(
                    owned_type_fd,
                    name,
                    digest=name[:-5],
                    maximum_size=1_048_576,
                )
            except (OSError, ValueError):
                continue
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                not isinstance(value, dict)
                or set(value) != _RUN_DOCUMENT_KEYS
                or value.get("schema_version") != "1.4"
                or canonical_json_bytes(value) != raw
            ):
                continue
            embedded = value.get("run_sha256")
            if embedded != run_sha256:
                continue
            identity_document = dict(value)
            identity_document.pop("run_sha256", None)
            if canonical_sha256(identity_document) != run_sha256:
                continue
            state = value.get("state")
            preflight = value.get("preflight")
            if not isinstance(preflight, dict):
                continue
            if state not in {
                RunState.INVALID.value,
                RunState.UNSUPPORTED.value,
                RunState.DISPATCH_AUTHORIZED.value,
            }:
                continue
            expected = {
                RunState.INVALID.value: PreflightState.INVALID.value,
                RunState.UNSUPPORTED.value: PreflightState.UNSUPPORTED.value,
                RunState.DISPATCH_AUTHORIZED.value: PreflightState.VALID.value,
            }[state]
            if preflight.get("state") != expected:
                continue
            attempt = value.get("attempt")
            parent_attempt = value.get("parent_attempt_sha256")
            if (
                not isinstance(attempt, int)
                or attempt != child_cell.attempt - 1
                or not (parent_attempt is None or isinstance(parent_attempt, str))
            ):
                continue
            parent_cell = replace(
                child_cell,
                attempt=attempt,
                parent_attempt_sha256=parent_attempt,
            )
            if not _document_matches_cell(value, parent_cell):
                continue
            from cc.core.evaluation._authority import _production_authority
            from cc.core.evaluation.runner import _preflight_document, _preflight_for

            authority = _production_authority(
                parent_cell,
                loaded_fixture=loaded_fixture,
                journey_run_id=journey_run_id,
                journey_ledger=journey_ledger,
            )
            try:
                authoritative_preflight = _preflight_for(
                    parent_cell,
                    authority,
                    root,
                    artifact_root_fd=owned_root_fd,
                    artifact_type_fd=owned_type_fd,
                    loaded_fixture=loaded_fixture,
                    journey_run_id=journey_run_id,
                    journey_ledger=journey_ledger,
                    lineage_depth=lineage_depth + 1,
                )
                if value.get("preflight") != _preflight_document(
                    authoritative_preflight
                ):
                    continue
                _reject_aggregate_fields(value)
                _reject_disclosure_values(value)
                try:
                    _verify_storage_snapshot(
                        owned_root_fd,
                        owned_type_fd,
                        "run-record",
                        name,
                        raw,
                        name[:-5],
                    )
                except (OSError, ValueError):
                    return None
                return value
            finally:
                authority.close()
    finally:
        os.close(owned_type_fd)
        os.close(owned_root_fd)
    return None
