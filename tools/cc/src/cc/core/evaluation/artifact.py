"""Canonical content-addressed evaluation artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import unicodedata
from dataclasses import replace
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
    PreflightState,
    RunRecord,
    RunState,
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
        "schema_version": "1.2",
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


def _verify_storage_snapshot(
    root_fd: int,
    type_fd: int,
    artifact_type: str,
    filename: str,
    content: bytes,
    digest: str,
) -> None:
    """Make the retained-FD validation the final operation before a receipt."""

    _require_private_directory(root_fd, description="Evaluation artifact root")
    type_metadata = _require_private_directory(
        type_fd, description="Evaluation artifact type directory"
    )
    _require_named_directory(
        root_fd,
        artifact_type,
        type_metadata,
        description="Evaluation artifact type directory",
    )
    _verify_named_artifact(type_fd, filename, content, digest)


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


def _write_artifact(
    root: Path,
    record: RunRecord | ComparisonRecord,
    *,
    cell: EvaluationCell | None = None,
    loaded_fixture: object = None,
    journey_run_id: str = "",
    journey_ledger: object = None,
) -> ArtifactReceipt:
    """Write only a production-revalidated record below a non-symlink root."""

    if isinstance(record, RunRecord) and _production_record_valid(
        root,
        record,
        cell=cell,
        loaded_fixture=loaded_fixture,
        journey_run_id=journey_run_id,
        journey_ledger=journey_ledger,
    ):
        artifact_type = "run-record"
        payload = run_record_document(record)
    elif isinstance(record, ComparisonRecord):
        raise ValueError(
            "Comparison artifacts require production completion authority."
        )
    else:
        raise ValueError("Artifact writes require production-authoritative evidence.")
    _reject_aggregate_fields(payload)
    _reject_disclosure_values(payload)
    content = canonical_json_bytes(dict(payload))
    digest = hashlib.sha256(content).hexdigest()
    filename = f"{digest}.json"
    staging_name = f".{digest}.{secrets.token_hex(12)}.tmp"
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    root_fd = _open_root_directory(root)
    artifact_fd: int | None = None
    try:
        created_type_directory = False
        try:
            os.mkdir(artifact_type, mode=0o700, dir_fd=root_fd)
            created_type_directory = True
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
            if created_type_directory:
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
            try:
                os.fsync(durable_fd)
            finally:
                os.close(durable_fd)
            os.fsync(type_fd)
            os.fsync(root_fd)
            _verify_storage_snapshot(
                root_fd,
                type_fd,
                artifact_type,
                filename,
                content,
                digest,
            )
        except Exception:
            if artifact_fd is not None:
                os.close(artifact_fd)
            try:
                os.unlink(staging_name, dir_fd=type_fd)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(type_fd)
    finally:
        os.close(root_fd)
    return ArtifactReceipt(
        artifact_type=artifact_type,
        sha256=digest,
        relative_path=f"{artifact_type}/{filename}",
        size_bytes=len(content),
    )


def write_run_record(
    root: Path,
    record: RunRecord,
    *,
    cell: EvaluationCell,
    loaded_fixture: object = None,
    journey_run_id: str = "",
    journey_ledger: object = None,
) -> ArtifactReceipt:
    return _write_artifact(
        root,
        record,
        cell=cell,
        loaded_fixture=loaded_fixture,
        journey_run_id=journey_run_id,
        journey_ledger=journey_ledger,
    )


def write_comparison_record(root: Path, record: ComparisonRecord) -> ArtifactReceipt:
    if not verify_comparison_record_identity(record):
        raise ValueError(
            "Comparison artifact requires an authentic coordinator record."
        )
    return _write_artifact(root, record)


def _production_record_valid(
    root: Path,
    record: RunRecord,
    *,
    cell: EvaluationCell | None,
    loaded_fixture: object,
    journey_run_id: str,
    journey_ledger: object,
) -> bool:
    """Revalidate durable claims; never rely on an in-memory seal alone."""

    if not verify_run_record_identity(record) or not isinstance(cell, EvaluationCell):
        return False
    from cc.core.evaluation._authority import _production_authority
    from cc.core.evaluation.runner import _preflight_for

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
    if record.preflight != expected_preflight:
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
            and record.output_sha256 is not None
            and record.controlled_artifact_path is not None
            and record.completion_evidence_sha256 is None
        )
    # TASK-297 has not supplied a production completion verifier. Neither a
    # COMPLETED nor a TECHNICAL_ERROR record is durable authority before then.
    return False


def load_run_record_document(
    root: Path,
    run_sha256: str,
    *,
    child_cell: EvaluationCell,
    loaded_fixture: object,
    journey_run_id: str,
    journey_ledger: object,
    lineage_depth: int,
) -> dict[str, object] | None:
    """Reload one canonical, production-acceptable parent from artifact storage."""

    if lineage_depth >= 32:
        return None
    root_fd: int | None = None
    type_fd: int | None = None
    try:
        root_fd = _open_root_directory(root)
        type_fd = os.open(
            "run-record",
            _directory_open_flags(),
            dir_fd=root_fd,
        )
        type_metadata = _require_private_directory(
            type_fd, description="Evaluation artifact type directory"
        )
        _require_named_directory(
            root_fd,
            "run-record",
            type_metadata,
            description="Evaluation artifact type directory",
        )
    except (OSError, ValueError):
        if type_fd is not None:
            os.close(type_fd)
        if root_fd is not None:
            os.close(root_fd)
        return None
    try:
        names = os.listdir(type_fd)
        for name in names:
            if not _ARTIFACT_NAME.fullmatch(name):
                continue
            try:
                raw = _read_verified_artifact(
                    type_fd,
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
                or value.get("schema_version") != "1.2"
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
            authoritative_preflight = _preflight_for(
                parent_cell,
                authority,
                root,
                loaded_fixture=loaded_fixture,
                journey_run_id=journey_run_id,
                journey_ledger=journey_ledger,
                lineage_depth=lineage_depth + 1,
            )
            if value.get("preflight") != _preflight_document(authoritative_preflight):
                continue
            _reject_aggregate_fields(value)
            _reject_disclosure_values(value)
            try:
                _verify_storage_snapshot(
                    root_fd,
                    type_fd,
                    "run-record",
                    name,
                    raw,
                    name[:-5],
                )
            except (OSError, ValueError):
                return None
            return value
    finally:
        os.close(type_fd)
        os.close(root_fd)
    return None
