"""Canonical phase-two finalization from signed private assessor evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from cc.core.evaluation.artifact import (
    LoadedDurableRunEvidence,
    _open_linked_bytes,
    _open_root_directory,
    _write_standalone_evidence_document,
    close_artifact_receipt,
    write_criterion_judgment,
)
from cc.core.evaluation.assessment import (
    LoadedDurableAssessmentManifestEvidence,
)
from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
from cc.core.evaluation.judgment import (
    LoadedDurableJudgmentEvidence,
    build_criterion_judgment,
    compare_criterion_judgments,
    issue_durable_comparison,
    load_assessor_authorization,
    load_durable_criterion_judgment,
)
from cc.core.evaluation.matrix import EvaluationMatrix
from cc.core.evaluation.models import RunState
from cc.core.evaluation.portfolio import (
    DurableComparisonEvidence,
    _matrix_is_authentic,
    load_durable_comparison_evidence,
    verify_portfolio_record_identity,
)
from cc.core.evaluation.report import (
    LoadedDurableExecutionEvidence,
    persist_completed_execution,
    verify_execution_report_identity,
)
from cc.core.evaluation.safety import require_safe_synthetic_text
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256

FINALIZATION_SCHEMA_VERSION = "1.0"
FINALIZATION_BUNDLE_SCHEMA_VERSION = "1.0"
_TASK_ID = 285
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MAX_DATABASE_BYTES = 64 * 1024 * 1024
_MAX_WORK_PRODUCT_BYTES = 4 * 1024 * 1024
_MAX_FINALIZATION_BUNDLE_BYTES = 385 * 1024 * 1024
_WORK_PRODUCT_TYPES = frozenset(
    {
        "test",
        "test-report",
        "validation-review",
        "verification",
        "verification-report",
    }
)
_WORK_PRODUCT_VERDICTS = frozenset(
    {"APPROVED", "APPROVED-WITH-MINOR-FIXES", "REJECTED"}
)
_FINALIZATION_AUTHORITY = object()
_LOADED_FINALIZATION_AUTHORITY = object()
_ISSUED_FINALIZATIONS: weakref.WeakValueDictionary[int, FinalizationRecord] = (
    weakref.WeakValueDictionary()
)
_ISSUED_LOADED_FINALIZATIONS: weakref.WeakValueDictionary[
    int, LoadedFinalizedEvaluationEvidence
] = weakref.WeakValueDictionary()


def _require_digest(value: str, field_name: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


@dataclass(frozen=True)
class AssessorArtifactReference:
    """Address-only reference to one detached-signed private assessment."""

    run_sha256: str
    authorization_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("run_sha256", self.run_sha256),
            ("authorization_sha256", self.authorization_sha256),
            ("signature_sha256", self.signature_sha256),
        ):
            _require_digest(value, field_name)


@dataclass(frozen=True)
class TaskCopilotWorkProductEvidence:
    task_id: int
    work_product_id: int
    work_product_type: str
    qa_verdict: str
    work_product_sha256: str

    def __post_init__(self) -> None:
        if (
            self.task_id != _TASK_ID
            or self.work_product_id < 1
            or self.work_product_type not in _WORK_PRODUCT_TYPES
            or self.qa_verdict not in _WORK_PRODUCT_VERDICTS
        ):
            raise ValueError("Task Copilot work-product evidence is invalid.")
        _require_digest(self.work_product_sha256, "work_product_sha256")


@dataclass(frozen=True)
class FinalizationRecord:
    schema_version: str
    finalization_sha256: str
    task_id: int
    matrix_sha256: str
    assessment_manifest_sha256: str
    assessment_bundle_sha256: str
    assessor_artifacts_sha256: str
    task_copilot_work_product_id: int
    task_copilot_work_product_sha256: str
    execution_sha256: str
    execution_bundle_sha256: str
    portfolio_sha256: str
    acceptance_state: str
    completed_assessments: int
    unsupported_dispositions: int
    judgment_sha256: tuple[str, ...]
    comparison_sha256: tuple[str, ...]
    blockers: tuple[str, ...]
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _FINALIZATION_AUTHORITY
            or self.schema_version != FINALIZATION_SCHEMA_VERSION
            or self.task_id != _TASK_ID
            or self.acceptance_state not in {"accepted", "rejected"}
            or self.completed_assessments < 0
            or self.unsupported_dispositions < 0
            or self.completed_assessments + self.unsupported_dispositions != 28
            or self.judgment_sha256 != tuple(sorted(set(self.judgment_sha256)))
            or self.comparison_sha256 != tuple(sorted(set(self.comparison_sha256)))
            or self.blockers != tuple(sorted(set(self.blockers)))
            or any(not _CODE.fullmatch(item) for item in self.blockers)
            or (self.acceptance_state == "accepted") != (not self.blockers)
        ):
            raise ValueError("Finalization record fields are contradictory.")
        for field_name, value in (
            ("finalization_sha256", self.finalization_sha256),
            ("matrix_sha256", self.matrix_sha256),
            ("assessment_manifest_sha256", self.assessment_manifest_sha256),
            ("assessment_bundle_sha256", self.assessment_bundle_sha256),
            ("assessor_artifacts_sha256", self.assessor_artifacts_sha256),
            (
                "task_copilot_work_product_sha256",
                self.task_copilot_work_product_sha256,
            ),
            ("execution_sha256", self.execution_sha256),
            ("execution_bundle_sha256", self.execution_bundle_sha256),
            ("portfolio_sha256", self.portfolio_sha256),
            *(("judgment_sha256", item) for item in self.judgment_sha256),
            *(("comparison_sha256", item) for item in self.comparison_sha256),
        ):
            _require_digest(value, field_name)


def _finalization_identity_document(value: FinalizationRecord) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "task_id": value.task_id,
        "matrix_sha256": value.matrix_sha256,
        "assessment_manifest_sha256": value.assessment_manifest_sha256,
        "assessment_bundle_sha256": value.assessment_bundle_sha256,
        "assessor_artifacts_sha256": value.assessor_artifacts_sha256,
        "task_copilot_work_product_id": value.task_copilot_work_product_id,
        "task_copilot_work_product_sha256": (value.task_copilot_work_product_sha256),
        "execution_sha256": value.execution_sha256,
        "execution_bundle_sha256": value.execution_bundle_sha256,
        "portfolio_sha256": value.portfolio_sha256,
        "acceptance_state": value.acceptance_state,
        "completed_assessments": value.completed_assessments,
        "unsupported_dispositions": value.unsupported_dispositions,
        "judgment_sha256": list(value.judgment_sha256),
        "comparison_sha256": list(value.comparison_sha256),
        "blockers": list(value.blockers),
    }


def finalization_record_document(value: FinalizationRecord) -> dict[str, object]:
    """Return the shared, value-suppressing phase-two evidence record."""

    if not verify_finalization_record_identity(value):
        raise ValueError("Finalization record is not authentic.")
    return {
        **_finalization_identity_document(value),
        "finalization_sha256": value.finalization_sha256,
    }


def verify_finalization_record_identity(value: FinalizationRecord) -> bool:
    return bool(
        isinstance(value, FinalizationRecord)
        and _ISSUED_FINALIZATIONS.get(id(value)) is value
        and value._authority is _FINALIZATION_AUTHORITY
        and value.finalization_sha256
        == canonical_sha256(_finalization_identity_document(value))
    )


@dataclass(frozen=True)
class LoadedFinalizedEvaluationEvidence:
    """One retained private bundle authorizing the complete phase-two result."""

    record: FinalizationRecord
    execution: LoadedDurableExecutionEvidence = field(repr=False, compare=False)
    judgments: tuple[LoadedDurableJudgmentEvidence, ...] = field(
        repr=False, compare=False
    )
    comparisons: tuple[DurableComparisonEvidence, ...] = field(
        repr=False, compare=False
    )
    bundle_artifact_sha256: str
    _bundle_capability: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _LOADED_FINALIZATION_AUTHORITY:
            raise ValueError("Loaded finalization evidence is not verifier-issued.")
        _require_digest(self.bundle_artifact_sha256, "bundle_artifact_sha256")

    def validate(self) -> bool:
        if _ISSUED_LOADED_FINALIZATIONS.get(id(self)) is not self:
            return False
        try:
            valid = bool(
                verify_finalization_record_identity(self.record)
                and verify_execution_report_identity(self.execution.report)
                and verify_portfolio_record_identity(self.execution.portfolio)
                and self.record.execution_sha256
                == self.execution.report.execution_sha256
                and self.record.execution_bundle_sha256
                == self.execution.bundle_artifact_sha256
                and self.record.portfolio_sha256
                == self.execution.portfolio.portfolio_sha256
                and self.record.acceptance_state
                == self.execution.report.acceptance_state
                and self.record.blockers == self.execution.report.blockers
                and self.record.judgment_sha256
                == tuple(
                    sorted(item.judgment.judgment_sha256 for item in self.judgments)
                )
                and self.record.comparison_sha256
                == tuple(
                    sorted(item.record.comparison_sha256 for item in self.comparisons)
                )
            )
            # The one retained finalization bundle is the sole filesystem
            # authority. Revalidating it is deliberately the final filesystem
            # operation before a successful return.
            if not valid:
                return False
            self._bundle_capability.validate()
            return True
        except (AttributeError, OSError, TypeError, ValueError):
            return False

    def close(self) -> None:
        if _ISSUED_LOADED_FINALIZATIONS.get(id(self)) is not self:
            return
        _ISSUED_LOADED_FINALIZATIONS.pop(id(self), None)
        self._bundle_capability.close()
        self.execution.close()
        for item in self.comparisons:
            item.close()
        for item in self.judgments:
            item.close()


def _stable_file_identity(value: os.stat_result) -> tuple[int, ...]:
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


def _require_private_directory(value: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        raise ValueError("Task Copilot evidence directory must be owner-only.")


def _require_private_leaf(value: os.stat_result, *, maximum_size: int) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.getuid()
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_size < 1
        or value.st_size > maximum_size
    ):
        raise ValueError("Task Copilot evidence file must be owner-only.")


def _read_retained_file(descriptor: int, expected: os.stat_result) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    remaining = expected.st_size
    while remaining:
        chunk = os.read(descriptor, min(remaining, 1024 * 1024))
        if not chunk:
            raise ValueError("Evidence file ended before its declared size.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


@dataclass
class _RetainedTaskCopilotSnapshot:
    """Descriptor-anchored view of one quiescent private Task Copilot store."""

    root: Path
    anchor_fd: int
    root_fd: int
    database_fd: int
    root_identity: tuple[int, ...]
    database_identity: tuple[int, ...]
    work_product_directory_fd: int | None = None
    work_product_fd: int | None = None
    work_product_directory_identity: tuple[int, ...] | None = None
    work_product_identity: tuple[int, ...] | None = None
    work_product_name: str | None = None

    @classmethod
    def open(cls, database_path: Path) -> _RetainedTaskCopilotSnapshot:
        if not database_path.is_absolute():
            raise ValueError("Task Copilot database path must be absolute.")
        resolved_database = database_path.resolve(strict=True)
        root = database_path.parent
        if database_path != resolved_database or root != root.resolve(strict=True):
            raise ValueError("Task Copilot database path must be canonical.")
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        anchor_fd = root_fd = database_fd = None
        try:
            anchor_fd = os.open(
                root.parent, os.O_RDONLY | directory | no_follow | cloexec
            )
            root_fd = os.open(
                root.name,
                os.O_RDONLY | directory | no_follow | cloexec,
                dir_fd=anchor_fd,
            )
            root_stat = os.fstat(root_fd)
            named_root = os.stat(root.name, dir_fd=anchor_fd, follow_symlinks=False)
            _require_private_directory(root_stat)
            if _stable_file_identity(root_stat) != _stable_file_identity(named_root):
                raise ValueError("Task Copilot evidence root identity differs.")
            database_fd = os.open(
                database_path.name,
                os.O_RDONLY | no_follow | cloexec,
                dir_fd=root_fd,
            )
            database_stat = os.fstat(database_fd)
            _require_private_leaf(database_stat, maximum_size=_MAX_DATABASE_BYTES)
            result = cls(
                root,
                anchor_fd,
                root_fd,
                database_fd,
                _stable_file_identity(root_stat),
                _stable_file_identity(database_stat),
            )
            if not result.validate():
                anchor_fd = root_fd = database_fd = None
                result.close()
                raise ValueError("Task Copilot evidence snapshot is invalid.")
            anchor_fd = root_fd = database_fd = None
            return result
        finally:
            for descriptor in (database_fd, root_fd, anchor_fd):
                if descriptor is not None:
                    os.close(descriptor)

    def _require_quiescent(self) -> bool:
        for suffix in ("-wal", "-shm"):
            try:
                os.stat(
                    f"tasks.db{suffix}",
                    dir_fd=self.root_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            return False
        return True

    def database_bytes(self) -> bytes:
        before = os.fstat(self.database_fd)
        if _stable_file_identity(before) != self.database_identity:
            raise ValueError("Task Copilot database identity changed.")
        return _read_retained_file(self.database_fd, before)

    def work_product_bytes(self, work_product_id: int, declared_path: str) -> bytes:
        expected = self.root / "wp" / f"{work_product_id}.md"
        if Path(declared_path) != expected:
            raise ValueError("Task Copilot work-product path is not canonical.")
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        if (
            self.work_product_directory_fd is not None
            or self.work_product_fd is not None
        ):
            raise ValueError("Task Copilot work-product evidence was already opened.")
        self.work_product_directory_fd = os.open(
            "wp",
            os.O_RDONLY | directory | no_follow | cloexec,
            dir_fd=self.root_fd,
        )
        directory_stat = os.fstat(self.work_product_directory_fd)
        _require_private_directory(directory_stat)
        self.work_product_directory_identity = _stable_file_identity(directory_stat)
        self.work_product_name = f"{work_product_id}.md"
        self.work_product_fd = os.open(
            self.work_product_name,
            os.O_RDONLY | no_follow | cloexec,
            dir_fd=self.work_product_directory_fd,
        )
        leaf_stat = os.fstat(self.work_product_fd)
        _require_private_leaf(leaf_stat, maximum_size=_MAX_WORK_PRODUCT_BYTES)
        self.work_product_identity = _stable_file_identity(leaf_stat)
        return _read_retained_file(self.work_product_fd, leaf_stat)

    def validate(self) -> bool:
        try:
            root_stat = os.fstat(self.root_fd)
            named_root = os.stat(
                self.root.name,
                dir_fd=self.anchor_fd,
                follow_symlinks=False,
            )
            database_stat = os.fstat(self.database_fd)
            named_database = os.stat(
                "tasks.db",
                dir_fd=self.root_fd,
                follow_symlinks=False,
            )
            valid = bool(
                _stable_file_identity(root_stat) == self.root_identity
                and _stable_file_identity(named_root) == self.root_identity
                and _stable_file_identity(database_stat) == self.database_identity
                and _stable_file_identity(named_database) == self.database_identity
                and self._require_quiescent()
            )
            if self.work_product_fd is None:
                return valid
            if (
                self.work_product_directory_fd is None
                or self.work_product_directory_identity is None
                or self.work_product_identity is None
                or self.work_product_name is None
            ):
                return False
            directory_stat = os.fstat(self.work_product_directory_fd)
            named_directory = os.stat(
                "wp",
                dir_fd=self.root_fd,
                follow_symlinks=False,
            )
            leaf_stat = os.fstat(self.work_product_fd)
            named_leaf = os.stat(
                self.work_product_name,
                dir_fd=self.work_product_directory_fd,
                follow_symlinks=False,
            )
            return bool(
                valid
                and _stable_file_identity(directory_stat)
                == self.work_product_directory_identity
                and _stable_file_identity(named_directory)
                == self.work_product_directory_identity
                and _stable_file_identity(leaf_stat) == self.work_product_identity
                and _stable_file_identity(named_leaf) == self.work_product_identity
            )
        except (FileNotFoundError, OSError, TypeError, ValueError):
            return False

    def close(self) -> None:
        descriptors = (
            self.work_product_fd,
            self.work_product_directory_fd,
            self.database_fd,
            self.root_fd,
            self.anchor_fd,
        )
        self.work_product_fd = None
        self.work_product_directory_fd = None
        self.database_fd = -1
        self.root_fd = -1
        self.anchor_fd = -1
        for descriptor in descriptors:
            if descriptor is not None and descriptor >= 0:
                os.close(descriptor)


def _work_product_content(
    snapshot: _RetainedTaskCopilotSnapshot,
    row: tuple[object, ...],
) -> tuple[str, str]:
    content, file_path = row[4], row[5]
    if isinstance(content, str) and content and file_path is None:
        return content, "inline"
    if content is None and isinstance(file_path, str) and file_path:
        raw = snapshot.work_product_bytes(int(row[0]), file_path)
        try:
            return raw.decode("utf-8"), "content-addressed-file"
        except UnicodeDecodeError as exc:
            raise ValueError("Task Copilot work product is not UTF-8.") from exc
    raise ValueError("Task Copilot work-product content is unavailable.")


def _load_task_copilot_work_product(
    database_path: Path,
    work_product_id: int,
    *,
    matrix_sha256: str,
    assessment_manifest_sha256: str,
    assessment_bundle_sha256: str,
) -> TaskCopilotWorkProductEvidence:
    if work_product_id < 1:
        raise ValueError("Task Copilot work-product id is invalid.")
    retained = _RetainedTaskCopilotSnapshot.open(database_path)
    try:
        raw_database = retained.database_bytes()
        if not raw_database.startswith(b"SQLite format 3\x00"):
            raise ValueError("Task Copilot database format is invalid.")
        with tempfile.TemporaryDirectory(prefix="cc-finalize-tc-") as directory:
            temporary_root = Path(directory)
            temporary_root.chmod(0o700)
            database_snapshot = temporary_root / "tasks.db"
            descriptor = os.open(
                database_snapshot,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
            )
            try:
                offset = 0
                while offset < len(raw_database):
                    written = os.write(descriptor, raw_database[offset:])
                    if written < 1:
                        raise OSError("Task Copilot snapshot write made no progress.")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            connection = sqlite3.connect(f"file:{database_snapshot}?mode=ro", uri=True)
            try:
                columns = tuple(
                    item[1]
                    for item in connection.execute("PRAGMA table_info(work_products)")
                )
                if columns != (
                    "id",
                    "task_id",
                    "type",
                    "title",
                    "content",
                    "file_path",
                    "agent",
                    "guard",
                    "created_at",
                ):
                    raise ValueError("Task Copilot work-product schema is unsupported.")
                row = connection.execute(
                    "SELECT id, task_id, type, title, content, file_path, agent, "
                    "guard, created_at FROM work_products WHERE id = ?",
                    (work_product_id,),
                ).fetchone()
            finally:
                connection.close()
        if row is None or len(row) != 9:
            raise ValueError("Task Copilot work product is unavailable.")
        content, storage = _work_product_content(retained, row)
        if len(content.encode()) > _MAX_WORK_PRODUCT_BYTES:
            raise ValueError("Task Copilot work product exceeds the evidence limit.")
        task_id, work_product_type, title, agent, guard, created_at = (
            row[1],
            row[2],
            row[3],
            row[6],
            row[7],
            row[8],
        )
        verdicts = re.findall(
            r"(?m)^VERDICT: (APPROVED|APPROVED-WITH-MINOR-FIXES|REJECTED)$",
            content,
        )
        matrix_markers = re.findall(r"(?m)^MATRIX_SHA256: ([0-9a-f]{64})$", content)
        manifest_markers = re.findall(
            r"(?m)^ASSESSMENT_MANIFEST_SHA256: ([0-9a-f]{64})$",
            content,
        )
        bundle_markers = re.findall(
            r"(?m)^ASSESSMENT_BUNDLE_SHA256: ([0-9a-f]{64})$",
            content,
        )
        if (
            task_id != _TASK_ID
            or work_product_type not in _WORK_PRODUCT_TYPES
            or not isinstance(title, str)
            or not title
            or len(title) > 512
            or guard != "clean"
            or not isinstance(created_at, str)
            or not created_at
            or len(verdicts) != 1
            or verdicts[0] not in _WORK_PRODUCT_VERDICTS
            or not re.search(r"(?m)^ARTIFACT: [a-z][a-z0-9-]*(?: .*)?$", content)
            or matrix_markers != [matrix_sha256]
            or manifest_markers != [assessment_manifest_sha256]
            or bundle_markers != [assessment_bundle_sha256]
        ):
            raise ValueError(
                "Task Copilot work product is not exact phase-two evidence."
            )
        require_safe_synthetic_text(
            content,
            location_class="private-assessor-rationale",
        )
        identity = {
            "schema_version": "task-copilot-work-product-link-v1",
            "task_id": task_id,
            "work_product_id": work_product_id,
            "work_product_type": work_product_type,
            "qa_verdict": verdicts[0],
            "title_sha256": hashlib.sha256(title.encode()).hexdigest(),
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "storage": storage,
            "agent_sha256": hashlib.sha256(str(agent or "").encode()).hexdigest(),
            "guard": guard,
            "created_at_sha256": hashlib.sha256(created_at.encode()).hexdigest(),
            "matrix_sha256": matrix_sha256,
            "assessment_manifest_sha256": assessment_manifest_sha256,
            "assessment_bundle_sha256": assessment_bundle_sha256,
        }
        result = TaskCopilotWorkProductEvidence(
            task_id,
            work_product_id,
            str(work_product_type),
            verdicts[0],
            canonical_sha256(identity),
        )
        if not retained.validate():
            raise ValueError("Task Copilot evidence changed during verification.")
        return result
    finally:
        retained.close()


def _terminal_records(
    assessment: LoadedDurableAssessmentManifestEvidence,
) -> dict[str, LoadedDurableRunEvidence]:
    if not isinstance(assessment, LoadedDurableAssessmentManifestEvidence) or not (
        assessment.validate()
    ):
        raise ValueError("Finalization requires the exact assessment bundle.")
    by_sha = {}
    for item in assessment.runs:
        if not isinstance(item, LoadedDurableRunEvidence) or not item.validate():
            raise ValueError("Assessment run evidence is invalid.")
        if item.record.run_sha256 in by_sha:
            raise ValueError("Assessment run evidence is duplicated.")
        by_sha[item.record.run_sha256] = item
    result = {}
    for cell in assessment.manifest.cells:
        item = by_sha.get(cell.terminal_run_sha256)
        if (
            item is None
            or item.record.state is not cell.terminal_state
            or item.record.fixture_sha256 != cell.fixture_sha256
            or item.record.output_sha256 != cell.output_sha256
        ):
            raise ValueError("Assessment terminal run binding changed.")
        result[cell.terminal_run_sha256] = item
    if len(result) != 28:
        raise ValueError("Assessment terminal run coverage is incomplete.")
    return result


def _fixture_map(fixtures: tuple[LoadedFixture, ...]) -> dict[str, LoadedFixture]:
    result = {
        item.fixture.case_id: item
        for item in fixtures
        if isinstance(item, LoadedFixture) and verify_loaded_fixture(item)
    }
    if len(fixtures) != 7 or len(result) != 7:
        raise ValueError("Finalization fixture evidence is incomplete.")
    return result


def _assessment_outputs(
    assessment: LoadedDurableAssessmentManifestEvidence,
) -> dict[str, str]:
    capability = assessment._bundle_capability
    capability.validate()
    raw = getattr(capability, "_content", None)
    if (
        not isinstance(raw, bytes)
        or hashlib.sha256(raw).hexdigest() != assessment.bundle_artifact_sha256
    ):
        raise ValueError("Assessment bundle bytes are unavailable.")
    document = json.loads(raw)
    if not isinstance(document, Mapping) or canonical_json_bytes(document) != raw:
        raise ValueError("Assessment bundle document is not canonical.")
    retained = document.get("retained_artifacts")
    if not isinstance(retained, list):
        raise ValueError("Assessment bundle retained evidence is unavailable.")
    outputs: dict[str, str] = {}
    for item in retained:
        if not isinstance(item, Mapping) or item.get("artifact_type") != (
            "runtime-quarantine"
        ):
            continue
        digest, content = item.get("sha256"), item.get("content")
        if not isinstance(digest, str) or not isinstance(content, str):
            raise ValueError("Assessment output evidence is malformed.")
        try:
            decoded = base64.b64decode(content, validate=True)
            output = decoded.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("Assessment output evidence is malformed.") from exc
        if hashlib.sha256(decoded).hexdigest() != digest or digest in outputs:
            raise ValueError("Assessment output evidence identity changed.")
        require_safe_synthetic_text(output, location_class="private-runtime-output")
        outputs[digest] = output
    expected = {
        item.output_sha256
        for item in assessment.manifest.cells
        if item.terminal_state is RunState.COMPLETED
    }
    if None in expected or set(outputs) != expected:
        raise ValueError("Assessment output coverage is incomplete.")
    capability.validate()
    return outputs


def _reference_identity(
    references: tuple[AssessorArtifactReference, ...],
) -> str:
    return canonical_sha256(
        {
            "schema_version": "assessment-reference-set-v1",
            "references": [
                {
                    "run_sha256": item.run_sha256,
                    "authorization_sha256": item.authorization_sha256,
                    "signature_sha256": item.signature_sha256,
                }
                for item in references
            ],
        }
    )


def _issue_finalization_record(
    assessment: LoadedDurableAssessmentManifestEvidence,
    references: tuple[AssessorArtifactReference, ...],
    work_product: TaskCopilotWorkProductEvidence,
    execution: LoadedDurableExecutionEvidence,
    judgments: tuple[LoadedDurableJudgmentEvidence, ...],
    comparisons: tuple[DurableComparisonEvidence, ...],
) -> FinalizationRecord:
    completed = sum(
        item.terminal_state is RunState.COMPLETED for item in assessment.manifest.cells
    )
    unsupported = 28 - completed
    provisional = FinalizationRecord(
        FINALIZATION_SCHEMA_VERSION,
        "0" * 64,
        _TASK_ID,
        assessment.manifest.matrix_sha256,
        assessment.manifest_artifact_sha256,
        assessment.bundle_artifact_sha256,
        _reference_identity(references),
        work_product.work_product_id,
        work_product.work_product_sha256,
        execution.report.execution_sha256,
        execution.bundle_artifact_sha256,
        execution.portfolio.portfolio_sha256,
        execution.report.acceptance_state,
        completed,
        unsupported,
        tuple(sorted(item.judgment.judgment_sha256 for item in judgments)),
        tuple(sorted(item.record.comparison_sha256 for item in comparisons)),
        execution.report.blockers,
        _FINALIZATION_AUTHORITY,
    )
    result = FinalizationRecord(
        **{
            **provisional.__dict__,
            "finalization_sha256": canonical_sha256(
                _finalization_identity_document(provisional)
            ),
        }
    )
    _ISSUED_FINALIZATIONS[id(result)] = result
    return result


def _finalization_bundle_document(
    record: FinalizationRecord,
    execution: LoadedDurableExecutionEvidence,
) -> dict[str, object]:
    execution_capability = execution._bundle_capability
    execution_capability.validate()
    raw = getattr(execution_capability, "_content", None)
    if (
        not isinstance(raw, bytes)
        or hashlib.sha256(raw).hexdigest() != execution.bundle_artifact_sha256
    ):
        raise ValueError("Execution bundle bytes are unavailable.")
    execution_bundle = json.loads(raw)
    if (
        not isinstance(execution_bundle, Mapping)
        or canonical_json_bytes(execution_bundle) != raw
    ):
        raise ValueError("Execution bundle is not canonical.")
    document: dict[str, object] = {
        "schema_version": FINALIZATION_BUNDLE_SCHEMA_VERSION,
        "privacy_class": "private-evaluation-evidence",
        "finalization_record": finalization_record_document(record),
        "execution_bundle_sha256": execution.bundle_artifact_sha256,
        "execution_bundle": execution_bundle,
    }
    if len(canonical_json_bytes(document)) > _MAX_FINALIZATION_BUNDLE_BYTES:
        raise ValueError("Finalization bundle exceeds the private evidence limit.")
    execution_capability.validate()
    return document


def _load_finalization_bundle(
    root: Path,
    record: FinalizationRecord,
    execution: LoadedDurableExecutionEvidence,
    judgments: tuple[LoadedDurableJudgmentEvidence, ...],
    comparisons: tuple[DurableComparisonEvidence, ...],
) -> LoadedFinalizedEvaluationEvidence | None:
    document = _finalization_bundle_document(record, execution)
    digest = canonical_sha256(document)
    root_fd: int | None = None
    capability = None
    try:
        root_fd = _open_root_directory(root)
        raw, capability = _open_linked_bytes(
            root_fd,
            "evaluation-finalization-bundle",
            f"{digest}.json",
            digest,
            maximum_size=_MAX_FINALIZATION_BUNDLE_BYTES,
        )
        stored = json.loads(raw)
        if (
            not isinstance(stored, Mapping)
            or canonical_json_bytes(stored) != raw
            or stored != document
        ):
            return None
        capability.validate()
        loaded = LoadedFinalizedEvaluationEvidence(
            record,
            execution,
            judgments,
            comparisons,
            digest,
            capability,
            _LOADED_FINALIZATION_AUTHORITY,
        )
        _ISSUED_LOADED_FINALIZATIONS[id(loaded)] = loaded
        capability = None
        if not loaded.validate():
            loaded.close()
            return None
        return loaded
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if capability is not None:
            capability.close()
        if root_fd is not None:
            os.close(root_fd)


def finalize_effectiveness_evaluation(
    *,
    root: Path,
    matrix: EvaluationMatrix,
    fixtures: tuple[LoadedFixture, ...],
    assessment: LoadedDurableAssessmentManifestEvidence,
    evidence_vault: Path,
    assessor_artifacts: tuple[AssessorArtifactReference, ...],
    task_copilot_database: Path,
    task_copilot_work_product_id: int,
) -> LoadedFinalizedEvaluationEvidence:
    """Finalize existing runs; never accept caller-authored semantic judgments."""

    if (
        not _matrix_is_authentic(matrix)
        or not assessment.validate()
        or matrix.matrix_sha256 != assessment.manifest.matrix_sha256
    ):
        raise ValueError("Finalization requires the exact assessment matrix.")
    terminals = _terminal_records(assessment)
    fixture_by_case = _fixture_map(fixtures)
    outputs = _assessment_outputs(assessment)
    completed = {
        digest: item
        for digest, item in terminals.items()
        if item.record.state is RunState.COMPLETED
    }
    references = tuple(sorted(assessor_artifacts, key=lambda item: item.run_sha256))
    if len(references) != len({item.run_sha256 for item in references}) or {
        item.run_sha256 for item in references
    } != set(completed):
        raise ValueError("Signed assessor reference coverage is incomplete.")
    reference_by_run = {item.run_sha256: item for item in references}
    work_product = _load_task_copilot_work_product(
        task_copilot_database,
        task_copilot_work_product_id,
        matrix_sha256=matrix.matrix_sha256,
        assessment_manifest_sha256=assessment.manifest_artifact_sha256,
        assessment_bundle_sha256=assessment.bundle_artifact_sha256,
    )
    if work_product.qa_verdict == "REJECTED":
        raise ValueError("Task Copilot QA rejected phase-two finalization.")

    built = []
    for run_sha256, item in sorted(completed.items()):
        fixture = fixture_by_case.get(item.record.case_id)
        output = outputs.get(item.record.output_sha256 or "")
        if fixture is None or output is None:
            raise ValueError("Completed assessment evidence is incomplete.")
        reference = reference_by_run[run_sha256]
        authorization = load_assessor_authorization(
            item.record,
            evidence_vault=evidence_vault,
            authorization_sha256=reference.authorization_sha256,
            signature_sha256=reference.signature_sha256,
        )
        document = json.loads(authorization._assessment_document_json)
        if not isinstance(document, Mapping):
            raise ValueError("Signed assessment document is malformed.")
        judgment = build_criterion_judgment(
            item.record,
            fixture,
            output,
            document,
            assessor_authorization=authorization,
        )
        built.append((item, fixture, output, reference, judgment))
    if not assessment.validate():
        raise ValueError("Assessment bundle changed during signed evidence loading.")

    judgments: list[LoadedDurableJudgmentEvidence] = []
    comparisons: list[DurableComparisonEvidence] = []
    execution: LoadedDurableExecutionEvidence | None = None
    audit_receipt = None
    bundle_receipt = None
    try:
        for item, fixture, output, reference, judgment in built:
            receipt = write_criterion_judgment(
                root,
                judgment,
                loaded_run=item,
            )
            try:
                loaded = load_durable_criterion_judgment(
                    root,
                    receipt.sha256,
                    loaded_run=item,
                    loaded_fixture=fixture,
                    output_text=output,
                    evidence_vault=evidence_vault,
                    authorization_sha256=reference.authorization_sha256,
                    signature_sha256=reference.signature_sha256,
                )
            finally:
                close_artifact_receipt(receipt)
            if loaded is None or not loaded.validate():
                raise ValueError("Criterion judgment could not be durably reloaded.")
            judgments.append(loaded)

        judgment_by_run = {item.judgment.run_sha256: item for item in judgments}
        plans_by_pair = {}
        for plan in matrix.cells:
            plans_by_pair.setdefault((plan.case_id, plan.runtime), []).append(plan)
        terminal_by_key = {
            (
                item.record.case_id,
                item.record.variant,
                item.record.runtime,
            ): item
            for item in terminals.values()
        }
        for pair_key in sorted(
            plans_by_pair,
            key=lambda item: (item[0], item[1].value),
        ):
            plans = plans_by_pair[pair_key]
            control_plan = next(item for item in plans if item.role == "control")
            layered_plan = next(item for item in plans if item.role == "layered")
            control_run = terminal_by_key[
                (pair_key[0], control_plan.variant, pair_key[1])
            ]
            layered_run = terminal_by_key[
                (pair_key[0], layered_plan.variant, pair_key[1])
            ]
            if (
                control_run.record.state is RunState.UNSUPPORTED
                or layered_run.record.state is RunState.UNSUPPORTED
            ):
                continue
            control = judgment_by_run[control_run.record.run_sha256]
            layered = judgment_by_run[layered_run.record.run_sha256]
            if not control.judgment.hard_gate_passed or not (
                layered.judgment.hard_gate_passed
            ):
                continue
            try:
                draft = compare_criterion_judgments(
                    control_run.record,
                    layered_run.record,
                    control.judgment,
                    layered.judgment,
                )
            except ValueError as exc:
                if "Protected criterion regression" not in str(exc):
                    raise
                continue
            _record, receipt = issue_durable_comparison(
                root,
                control=control,
                layered=layered,
                draft=draft,
            )
            try:
                loaded = load_durable_comparison_evidence(
                    root,
                    receipt.sha256,
                    control=control,
                    layered=layered,
                )
            finally:
                close_artifact_receipt(receipt)
            if loaded is None or not loaded.validate():
                raise ValueError("Comparison could not be durably reloaded.")
            comparisons.append(loaded)

        execution = persist_completed_execution(
            root,
            matrix,
            runs=assessment.runs,
            judgments=tuple(judgments),
            comparisons=tuple(comparisons),
        )
        if not execution.validate() or not assessment.validate():
            raise ValueError("Final execution evidence is not durable.")
        record = _issue_finalization_record(
            assessment,
            references,
            work_product,
            execution,
            tuple(judgments),
            tuple(comparisons),
        )
        audit_receipt = _write_standalone_evidence_document(
            root,
            "evaluation-finalization",
            _finalization_identity_document(record),
        )
        if audit_receipt.sha256 != record.finalization_sha256:
            raise ValueError("Finalization audit artifact identity changed.")
        bundle_document = _finalization_bundle_document(record, execution)
        bundle_receipt = _write_standalone_evidence_document(
            root,
            "evaluation-finalization-bundle",
            bundle_document,
        )
        loaded = _load_finalization_bundle(
            root,
            record,
            execution,
            tuple(judgments),
            tuple(comparisons),
        )
        if loaded is None or loaded.bundle_artifact_sha256 != bundle_receipt.sha256:
            raise ValueError("Finalization bundle could not be durably reloaded.")
        execution = None
        judgments = []
        comparisons = []
        return loaded
    finally:
        if bundle_receipt is not None:
            close_artifact_receipt(bundle_receipt)
        if audit_receipt is not None:
            close_artifact_receipt(audit_receipt)
        if execution is not None:
            execution.close()
        for item in comparisons:
            item.close()
        for item in judgments:
            item.close()


__all__ = [
    "FINALIZATION_BUNDLE_SCHEMA_VERSION",
    "FINALIZATION_SCHEMA_VERSION",
    "AssessorArtifactReference",
    "FinalizationRecord",
    "LoadedFinalizedEvaluationEvidence",
    "TaskCopilotWorkProductEvidence",
    "finalization_record_document",
    "finalize_effectiveness_evaluation",
    "verify_finalization_record_identity",
]
