"""Canonical content-addressed evaluation artifact storage."""

from __future__ import annotations

import hashlib
import os
import secrets
import unicodedata
from pathlib import Path
from typing import Mapping

from cc.core.evaluation.comparison import (
    comparison_record_document,
    verify_comparison_record_identity,
)
from cc.core.evaluation.models import ArtifactReceipt, ComparisonRecord, RunRecord
from cc.core.evaluation.runner import run_record_document, verify_run_record_identity
from cc.core.evaluation.safety import (
    FixtureSafetyViolation,
    require_safe_synthetic_text,
)
from cc.core.evaluation.schema import canonical_json_bytes

_ARTIFACT_TYPES = frozenset({"run-record", "comparison-record"})
_FORBIDDEN_AGGREGATES = frozenset(
    {"score", "total", "average", "percent", "percentage", "rank", "winner"}
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


def _reject_disclosure_values(value: object) -> None:
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_disclosure_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_disclosure_values(item)
    elif isinstance(value, str):
        try:
            require_safe_synthetic_text(value, location_class="artifact-metadata")
        except FixtureSafetyViolation as exc:
            raise ValueError(
                "Evaluation artifact metadata is disclosure-unsafe."
            ) from exc


def _write_artifact(
    root: Path,
    *,
    artifact_type: str,
    payload: Mapping[str, object],
) -> ArtifactReceipt:
    """Write one canonical artifact below an existing non-symlink root."""

    if artifact_type not in _ARTIFACT_TYPES:
        raise ValueError("Unsupported evaluation artifact type.")
    _reject_aggregate_fields(payload)
    _reject_disclosure_values(payload)
    content = canonical_json_bytes(dict(payload))
    digest = hashlib.sha256(content).hexdigest()
    filename = f"{digest}.json"
    staging_name = f".{digest}.{secrets.token_hex(12)}.tmp"
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow)
    artifact_fd: int | None = None
    try:
        try:
            os.mkdir(artifact_type, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        type_fd = os.open(
            artifact_type,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow,
            dir_fd=root_fd,
        )
        try:
            try:
                artifact_fd = os.open(
                    staging_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                    0o600,
                    dir_fd=type_fd,
                )
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
                os.fsync(type_fd)
            except FileExistsError:
                try:
                    os.unlink(staging_name, dir_fd=type_fd)
                except FileNotFoundError:
                    pass
                existing_fd = os.open(filename, os.O_RDONLY | nofollow, dir_fd=type_fd)
                try:
                    existing = b""
                    while True:
                        chunk = os.read(existing_fd, 65536)
                        if not chunk:
                            break
                        existing += chunk
                finally:
                    os.close(existing_fd)
                if existing != content:
                    raise ValueError("Content-addressed artifact identity collision.")
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


def write_run_record(root: Path, record: RunRecord) -> ArtifactReceipt:
    if not verify_run_record_identity(record):
        raise ValueError("Run artifact requires an authentic runner-issued record.")
    return _write_artifact(
        root,
        artifact_type="run-record",
        payload=run_record_document(record),
    )


def write_comparison_record(root: Path, record: ComparisonRecord) -> ArtifactReceipt:
    if not verify_comparison_record_identity(record):
        raise ValueError(
            "Comparison artifact requires an authentic coordinator record."
        )
    return _write_artifact(
        root,
        artifact_type="comparison-record",
        payload=comparison_record_document(record),
    )
