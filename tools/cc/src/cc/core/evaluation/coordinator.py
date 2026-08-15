"""Atomic, durable attempt claims for preregistered evaluation cells."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from cc.core.evaluation.identity import (
    consumption_receipt_identity,
    content_receipt_identity,
    runtime_receipt_identity,
)
from cc.core.evaluation.models import EvaluationCell, RunRecord, RunState
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256


def attempt_claim_document(cell: EvaluationCell) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "case_id": cell.case_id,
        "revision": cell.revision,
        "variant": cell.variant.value,
        "runtime": cell.runtime_receipt.runtime.value,
        "attempt": cell.attempt,
        "parent_attempt_sha256": cell.parent_attempt_sha256,
        "fixture_sha256": cell.fixture_sha256,
        "prompt_evidence_sha256": cell.prompt_evidence_sha256,
        "attempt_policy_sha256": cell.attempt_policy_sha256,
        "runtime_receipt_sha256": runtime_receipt_identity(cell.runtime_receipt),
        "content_receipt_sha256": content_receipt_identity(cell.content_receipt),
        "consumption_receipt_sha256": consumption_receipt_identity(
            cell.consumption_receipt
        ),
        "runtime_configuration_sha256": cell.runtime_configuration_sha256,
        "tool_configuration_sha256": cell.tool_configuration_sha256,
        "effective_full_prompt_sha256": cell.effective_full_prompt_sha256,
        "command_policy_sha256": cell.command_policy_sha256,
    }


def attempt_slot_identity(cell: EvaluationCell) -> str:
    """Identify the exclusive preregistered slot, independent of claim payload."""

    return _attempt_slot_identity_values(
        case_id=cell.case_id,
        revision=cell.revision,
        variant=cell.variant.value,
        runtime=cell.runtime_receipt.runtime.value,
        attempt=cell.attempt,
    )


def _attempt_slot_identity_values(
    *,
    case_id: str,
    revision: int,
    variant: str,
    runtime: str,
    attempt: int,
) -> str:
    return canonical_sha256(
        {
            "schema_version": "1.0",
            "case_id": case_id,
            "revision": revision,
            "variant": variant,
            "runtime": runtime,
            "attempt": attempt,
        }
    )


def _verify_retained_slot(
    descriptor: int,
    type_fd: int,
    filename: str,
    *,
    expected_content: bytes | None = None,
    maximum_size: int = 1024 * 1024,
) -> bytes:
    from cc.core.evaluation.artifact import _stable_file_identity

    os.lseek(descriptor, 0, os.SEEK_SET)
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size > maximum_size
    ):
        raise ValueError("Evaluation attempt evidence is untrusted.")
    chunks = []
    remaining = before.st_size
    while remaining:
        chunk = os.read(descriptor, min(remaining, 65536))
        if not chunk:
            raise ValueError("Evaluation attempt evidence is incomplete.")
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    after = os.fstat(descriptor)
    named = os.stat(filename, dir_fd=type_fd, follow_symlinks=False)
    if (
        (expected_content is not None and content != expected_content)
        or _stable_file_identity(before) != _stable_file_identity(after)
        or _stable_file_identity(after) != _stable_file_identity(named)
    ):
        raise ValueError("Evaluation attempt evidence changed.")
    return content


def _open_private_slot(
    type_fd: int,
    filename: str,
    *,
    expected_content: bytes | None = None,
    maximum_size: int = 1024 * 1024,
) -> tuple[int, bytes]:
    descriptor = os.open(
        filename,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        dir_fd=type_fd,
    )
    try:
        content = _verify_retained_slot(
            descriptor,
            type_fd,
            filename,
            expected_content=expected_content,
            maximum_size=maximum_size,
        )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor, content


def _read_private_slot(type_fd: int, filename: str) -> bytes:
    descriptor, content = _open_private_slot(type_fd, filename)
    os.close(descriptor)
    return content


def load_technical_retry_parent(
    root: Path,
    child_cell: EvaluationCell,
) -> dict[str, object] | None:
    """Load only an exact, durable, retriable attempt-1 technical result."""

    from cc.core.evaluation.artifact import (
        _open_artifact_type_directory,
        _open_root_directory,
        _require_named_directory,
        _require_private_directory,
    )
    from cc.core.evaluation.attempt_policy import (
        ATTEMPT_POLICY_SHA256,
        is_retriable_technical_reason,
    )

    if child_cell.attempt != 2 or child_cell.attempt_policy_sha256 != (
        ATTEMPT_POLICY_SHA256
    ):
        return None
    filename = (
        _attempt_slot_identity_values(
            case_id=child_cell.case_id,
            revision=child_cell.revision,
            variant=child_cell.variant.value,
            runtime=child_cell.runtime_receipt.runtime.value,
            attempt=1,
        )
        + ".json"
    )
    root_fd: int | None = None
    claim_fd: int | None = None
    result_fd: int | None = None
    try:
        root_fd = _open_root_directory(root)
        claim_fd = _open_artifact_type_directory(root_fd, "attempt-claim", create=False)
        result_fd = _open_artifact_type_directory(
            root_fd, "attempt-result", create=False
        )
        claim_leaf_fd, claim_raw = _open_private_slot(claim_fd, filename)
        result_leaf_fd, result_raw = _open_private_slot(result_fd, filename)
        claim = json.loads(claim_raw)
        result = json.loads(result_raw)
        if (
            not isinstance(claim, dict)
            or not isinstance(result, dict)
            or canonical_json_bytes(claim) != claim_raw
            or canonical_json_bytes(result) != result_raw
        ):
            return None
        run = result.get("run_record")
        if not isinstance(run, dict):
            return None
        run_identity = run.get("run_sha256")
        run_body = {key: value for key, value in run.items() if key != "run_sha256"}
        stable_fields = (
            "case_id",
            "revision",
            "variant",
            "runtime",
            "fixture_sha256",
            "prompt_evidence_sha256",
            "attempt_policy_sha256",
            "runtime_receipt_sha256",
            "content_receipt_sha256",
            "consumption_receipt_sha256",
            "runtime_configuration_sha256",
            "tool_configuration_sha256",
            "effective_full_prompt_sha256",
            "command_policy_sha256",
        )
        child_claim = attempt_claim_document(child_cell)
        if (
            result.get("schema_version") != "1.0"
            or result.get("slot_sha256") != filename[:-5]
            or result.get("attempt_claim_sha256") != canonical_sha256(claim)
            or run_identity != child_cell.parent_attempt_sha256
            or run_identity != canonical_sha256(run_body)
            or run.get("schema_version") != "1.4"
            or run.get("state") != "technical-error"
            or run.get("attempt") != 1
            or run.get("parent_attempt_sha256") is not None
            or run.get("attempt_policy_sha256") != ATTEMPT_POLICY_SHA256
            or not is_retriable_technical_reason(run.get("technical_error_reason"))
            or not isinstance(result.get("technical_failure_receipt"), dict)
            or canonical_sha256(result["technical_failure_receipt"])
            != run.get("technical_error_evidence_sha256")
            or not isinstance(result.get("technical_execution_policy"), dict)
            or not isinstance(run.get("preflight"), dict)
            or run["preflight"].get("state") != "VALID"
            or any(claim.get(field) != run.get(field) for field in stable_fields)
            or any(
                claim.get(field) != child_claim.get(field) for field in stable_fields
            )
            or claim.get("attempt") != 1
            or claim.get("parent_attempt_sha256") is not None
        ):
            return None
        technical = result["technical_failure_receipt"]
        if (
            technical.get("schema_version") != "1.0"
            or technical.get("reason") != run.get("technical_error_reason")
            or technical.get("runtime") != run.get("runtime")
            or technical.get("adapter_name") != child_cell.runtime_receipt.adapter_name
            or technical.get("adapter_version")
            != child_cell.runtime_receipt.adapter_version
            or technical.get("case_id") != run.get("case_id")
            or technical.get("revision") != run.get("revision")
            or technical.get("variant") != run.get("variant")
            or technical.get("attempt") != 1
            or technical.get("runtime_configuration_sha256")
            != run.get("runtime_configuration_sha256")
            or technical.get("tool_configuration_sha256")
            != run.get("tool_configuration_sha256")
            or technical.get("effective_full_prompt_sha256")
            != run.get("effective_full_prompt_sha256")
            or technical.get("command_policy_sha256")
            != run.get("command_policy_sha256")
            or technical.get("termination_claim")
            != "process-group-terminated-before-adapter-return"
            or canonical_sha256(result["technical_execution_policy"])
            != technical.get("execution_policy_sha256")
            or result["technical_execution_policy"].get("command_policy_sha256")
            != run.get("command_policy_sha256")
        ):
            return None
        for descriptor, name, description in (
            (claim_fd, "attempt-claim", "Evaluation attempt claim directory"),
            (result_fd, "attempt-result", "Evaluation attempt result directory"),
        ):
            metadata = _require_private_directory(descriptor, description=description)
            _require_named_directory(root_fd, name, metadata, description=description)
        _verify_retained_slot(
            claim_leaf_fd,
            claim_fd,
            filename,
            expected_content=claim_raw,
        )
        _verify_retained_slot(
            result_leaf_fd,
            result_fd,
            filename,
            expected_content=result_raw,
        )
        return result
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if "result_leaf_fd" in locals():
            os.close(result_leaf_fd)
        if "claim_leaf_fd" in locals():
            os.close(claim_leaf_fd)
        if result_fd is not None:
            os.close(result_fd)
        if claim_fd is not None:
            os.close(claim_fd)
        if root_fd is not None:
            os.close(root_fd)


def claim_attempt(root: Path, cell: EvaluationCell) -> bool:
    """Atomically reserve one exact attempt before any runtime subprocess."""

    from cc.core.evaluation.artifact import (
        _open_artifact_type_directory,
        _open_root_directory,
        _require_named_directory,
        _require_private_directory,
        _stable_file_identity,
        _write_all,
    )

    document = attempt_claim_document(cell)
    content = canonical_json_bytes(document)
    slot_sha256 = attempt_slot_identity(cell)
    filename = f"{slot_sha256}.json"
    root_fd = _open_root_directory(root)
    claim_fd: int | None = None
    type_fd: int | None = None
    try:
        type_fd = _open_artifact_type_directory(
            root_fd,
            "attempt-claim",
            create=True,
        )
        try:
            claim_fd = os.open(
                filename,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=type_fd,
            )
        except FileExistsError:
            # The immutable slot name is the lock. It may still be written by
            # the winning process, so do not race that writer by inspecting it.
            return False
        os.fchmod(claim_fd, 0o600)
        _write_all(claim_fd, content)
        os.fsync(claim_fd)
        os.close(claim_fd)
        claim_fd = None
        os.fsync(type_fd)
        os.fsync(root_fd)
        claim_fd = os.open(
            filename,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=type_fd,
        )
        try:
            metadata = os.fstat(claim_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size != len(content)
            ):
                raise ValueError("Evaluation attempt claim is untrusted.")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(claim_fd, min(remaining, 65536))
                if not chunk:
                    raise ValueError("Evaluation attempt claim is incomplete.")
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(claim_fd)
            named = os.stat(filename, dir_fd=type_fd, follow_symlinks=False)
            if (
                b"".join(chunks) != content
                or _stable_file_identity(metadata) != _stable_file_identity(after)
                or _stable_file_identity(named) != _stable_file_identity(after)
            ):
                raise ValueError("Evaluation attempt claim changed.")
        finally:
            os.close(claim_fd)
            claim_fd = None
        metadata = _require_private_directory(
            type_fd,
            description="Evaluation attempt claim directory",
        )
        _require_named_directory(
            root_fd,
            "attempt-claim",
            metadata,
            description="Evaluation attempt claim directory",
        )
        return True
    finally:
        if claim_fd is not None:
            os.close(claim_fd)
        if type_fd is not None:
            os.close(type_fd)
        os.close(root_fd)


def attempt_result_document(
    cell: EvaluationCell,
    record: RunRecord,
) -> dict[str, object]:
    """Bind one terminal runner result to the exact durable start claim."""

    from cc.core.evaluation.runner import run_record_document

    claim = attempt_claim_document(cell)
    run_document = run_record_document(record)
    for field in (
        "case_id",
        "revision",
        "variant",
        "runtime",
        "attempt",
        "parent_attempt_sha256",
        "fixture_sha256",
        "prompt_evidence_sha256",
        "attempt_policy_sha256",
        "runtime_receipt_sha256",
        "content_receipt_sha256",
        "consumption_receipt_sha256",
        "runtime_configuration_sha256",
        "tool_configuration_sha256",
        "effective_full_prompt_sha256",
        "command_policy_sha256",
    ):
        if run_document[field] != claim[field]:
            raise ValueError("Terminal result does not match its attempt claim.")
    technical_failure_receipt = None
    technical_execution_policy = None
    if record.state is RunState.TECHNICAL_ERROR:
        from cc.core.evaluation.live_runtime import (
            runtime_technical_execution_document,
            runtime_technical_failure_document,
        )

        technical_failure_receipt = runtime_technical_failure_document(
            record.technical_error_evidence_sha256 or ""
        )
        if technical_failure_receipt is None:
            raise ValueError("Technical result lacks verifier-issued timeout evidence.")
        technical_execution_policy = runtime_technical_execution_document(
            record.technical_error_evidence_sha256 or ""
        )
        if technical_execution_policy is None:
            raise ValueError("Technical result lacks execution-policy evidence.")
    return {
        "schema_version": "1.0",
        "slot_sha256": attempt_slot_identity(cell),
        "attempt_claim_sha256": canonical_sha256(claim),
        "run_record": run_document,
        "technical_failure_receipt": technical_failure_receipt,
        "technical_execution_policy": technical_execution_policy,
    }


def finalize_attempt(root: Path, cell: EvaluationCell, record: RunRecord) -> None:
    """Durably record the one terminal result for a claimed matrix slot."""

    from cc.core.evaluation.artifact import (
        _open_artifact_type_directory,
        _open_root_directory,
        _require_named_directory,
        _require_private_directory,
        _write_all,
    )

    claim = canonical_json_bytes(attempt_claim_document(cell))
    result = canonical_json_bytes(attempt_result_document(cell, record))
    filename = f"{attempt_slot_identity(cell)}.json"
    root_fd = _open_root_directory(root)
    claim_type_fd: int | None = None
    claim_leaf_fd: int | None = None
    result_type_fd: int | None = None
    result_fd: int | None = None
    try:
        claim_type_fd = _open_artifact_type_directory(
            root_fd,
            "attempt-claim",
            create=False,
        )
        claim_leaf_fd, _ = _open_private_slot(
            claim_type_fd,
            filename,
            expected_content=claim,
            maximum_size=64 * 1024,
        )
        claim_type_metadata = _require_private_directory(
            claim_type_fd,
            description="Evaluation attempt claim directory",
        )
        _require_named_directory(
            root_fd,
            "attempt-claim",
            claim_type_metadata,
            description="Evaluation attempt claim directory",
        )
        result_type_fd = _open_artifact_type_directory(
            root_fd,
            "attempt-result",
            create=True,
        )
        try:
            result_fd = os.open(
                filename,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=result_type_fd,
            )
        except FileExistsError as exc:
            raise ValueError(
                "Evaluation attempt already has a terminal result."
            ) from exc
        os.fchmod(result_fd, 0o600)
        _write_all(result_fd, result)
        os.fsync(result_fd)
        os.fsync(result_type_fd)
        os.fsync(root_fd)
        _verify_retained_slot(
            result_fd,
            result_type_fd,
            filename,
            expected_content=result,
            maximum_size=1_048_576,
        )
        result_type_metadata = _require_private_directory(
            result_type_fd,
            description="Evaluation attempt result directory",
        )
        _require_named_directory(
            root_fd,
            "attempt-result",
            result_type_metadata,
            description="Evaluation attempt result directory",
        )
        # The exact claim leaf remains open throughout result creation. These
        # retained-leaf checks are deliberately last so a same-UID pathname
        # replacement during either directory check cannot authorize a result.
        _verify_retained_slot(
            claim_leaf_fd,
            claim_type_fd,
            filename,
            expected_content=claim,
            maximum_size=64 * 1024,
        )
        _verify_retained_slot(
            result_fd,
            result_type_fd,
            filename,
            expected_content=result,
            maximum_size=1_048_576,
        )
    finally:
        if result_fd is not None:
            os.close(result_fd)
        if result_type_fd is not None:
            os.close(result_type_fd)
        if claim_leaf_fd is not None:
            os.close(claim_leaf_fd)
        if claim_type_fd is not None:
            os.close(claim_type_fd)
        os.close(root_fd)


__all__ = [
    "attempt_claim_document",
    "attempt_result_document",
    "attempt_slot_identity",
    "claim_attempt",
    "finalize_attempt",
]
