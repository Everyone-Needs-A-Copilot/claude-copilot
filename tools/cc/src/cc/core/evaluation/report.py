"""Durable execution reports for one exact effectiveness portfolio."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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
)
from cc.core.evaluation.comparison import comparison_record_document
from cc.core.evaluation.judgment import (
    LoadedDurableJudgmentEvidence,
    criterion_judgment_document,
)
from cc.core.evaluation.matrix import EvaluationMatrix, matrix_document
from cc.core.evaluation.portfolio import (
    DurableComparisonEvidence,
    PortfolioRecord,
    portfolio_record_document,
    verify_effectiveness_portfolio,
    verify_portfolio_record_identity,
)
from cc.core.evaluation.runner import run_record_document
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256

EXECUTION_REPORT_SCHEMA_VERSION = "1.0"
EXECUTION_BUNDLE_SCHEMA_VERSION = "1.0"
_MAX_EXECUTION_BUNDLE_BYTES = 384 * 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_EXECUTION_AUTHORITY = object()
_LOADED_EXECUTION_AUTHORITY = object()
_ISSUED_EXECUTIONS: weakref.WeakValueDictionary[int, ExecutionReport] = (
    weakref.WeakValueDictionary()
)
_ISSUED_LOADED_EXECUTIONS: weakref.WeakValueDictionary[
    int, LoadedDurableExecutionEvidence
] = weakref.WeakValueDictionary()


@dataclass(frozen=True)
class ExecutionReport:
    """Verifier-issued outcome of completing the preregistered evidence process."""

    schema_version: str
    execution_sha256: str
    matrix_sha256: str
    state: str
    acceptance_state: str
    initial_cells_started: int
    total_attempts_started: int
    portfolio_sha256: str
    portfolio_artifact_sha256: str
    blockers: tuple[str, ...]
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _EXECUTION_AUTHORITY
            or self.schema_version != EXECUTION_REPORT_SCHEMA_VERSION
        ):
            raise ValueError("Execution report is not verifier-issued.")
        if not _execution_fields_valid(self):
            raise ValueError("Execution report fields are contradictory.")


def _execution_identity_document(value: ExecutionReport) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "matrix_sha256": value.matrix_sha256,
        "state": value.state,
        "acceptance_state": value.acceptance_state,
        "initial_cells_started": value.initial_cells_started,
        "total_attempts_started": value.total_attempts_started,
        "portfolio_sha256": value.portfolio_sha256,
        "portfolio_artifact_sha256": value.portfolio_artifact_sha256,
        "blockers": list(value.blockers),
    }


def execution_report_document(value: ExecutionReport) -> dict[str, object]:
    """Return the JSON-safe execution envelope exposed to the CLI."""

    if not verify_execution_report_identity(value):
        raise ValueError("Execution report is not authentic.")
    return {
        **_execution_identity_document(value),
        "execution_sha256": value.execution_sha256,
    }


def _execution_fields_valid(value: ExecutionReport) -> bool:
    return bool(
        _DIGEST.fullmatch(value.execution_sha256)
        and value.matrix_sha256 == PACKAGED_MATRIX_SHA256
        and value.state == "completed"
        and value.acceptance_state in {"accepted", "rejected"}
        and value.initial_cells_started == 28
        and 28 <= value.total_attempts_started <= 56
        and _DIGEST.fullmatch(value.portfolio_sha256)
        and _DIGEST.fullmatch(value.portfolio_artifact_sha256)
        and value.blockers == tuple(sorted(set(value.blockers)))
        and all(_CODE.fullmatch(item) for item in value.blockers)
        and (value.acceptance_state == "accepted") == (not value.blockers)
    )


def verify_execution_report_identity(value: ExecutionReport) -> bool:
    """Reject copied/replaced reports even when their public hash is recomputed."""

    return bool(
        isinstance(value, ExecutionReport)
        and _ISSUED_EXECUTIONS.get(id(value)) is value
        and value._authority is _EXECUTION_AUTHORITY
        and _execution_fields_valid(value)
        and value.execution_sha256
        == canonical_sha256(_execution_identity_document(value))
    )


def _attempt_counts(portfolio: PortfolioRecord) -> tuple[int, int]:
    if (
        not verify_portfolio_record_identity(portfolio)
        or portfolio.matrix_sha256 != PACKAGED_MATRIX_SHA256
        or len(portfolio.cells) != 28
        or len(
            {
                (item.case_id, item.revision, item.variant, item.runtime)
                for item in portfolio.cells
            }
        )
        != 28
        or any(not item.attempt_lineage_sha256 for item in portfolio.cells)
    ):
        raise ValueError("Completed execution requires one exact 28-cell portfolio.")
    total = sum(len(item.attempt_lineage_sha256) for item in portfolio.cells)
    if not 28 <= total <= 56:
        raise ValueError("Portfolio retry lineage exceeds the released attempt policy.")
    return 28, total


def _issue_execution_report(
    portfolio: PortfolioRecord,
    *,
    portfolio_artifact_sha256: str,
) -> ExecutionReport:
    initial, total = _attempt_counts(portfolio)
    seal = object()
    provisional = ExecutionReport(
        EXECUTION_REPORT_SCHEMA_VERSION,
        "0" * 64,
        portfolio.matrix_sha256,
        "completed",
        portfolio.acceptance_state,
        initial,
        total,
        portfolio.portfolio_sha256,
        portfolio_artifact_sha256,
        portfolio.blockers,
        seal,
        _EXECUTION_AUTHORITY,
    )
    result = ExecutionReport(
        **{
            **provisional.__dict__,
            "execution_sha256": canonical_sha256(
                _execution_identity_document(provisional)
            ),
        }
    )
    _ISSUED_EXECUTIONS[id(result)] = result
    return result


def validate_execution_report_document(
    value: object,
    *,
    matrix_sha256: str,
) -> dict[str, object]:
    """Validate an issuer report without treating its claims as durable authority."""

    expected_keys = {
        "schema_version",
        "execution_sha256",
        "matrix_sha256",
        "state",
        "acceptance_state",
        "initial_cells_started",
        "total_attempts_started",
        "portfolio_sha256",
        "portfolio_artifact_sha256",
        "blockers",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ValueError("Canonical execution report has an invalid shape.")
    document = dict(value)
    identity = {
        key: item for key, item in document.items() if key != "execution_sha256"
    }
    blockers = document["blockers"]
    initial = document["initial_cells_started"]
    total = document["total_attempts_started"]
    state = document["state"]
    acceptance = document["acceptance_state"]
    portfolio_sha256 = document["portfolio_sha256"]
    portfolio_artifact = document["portfolio_artifact_sha256"]
    common = bool(
        document["schema_version"] == EXECUTION_REPORT_SCHEMA_VERSION
        and document["matrix_sha256"] == matrix_sha256 == PACKAGED_MATRIX_SHA256
        and _DIGEST.fullmatch(str(document["execution_sha256"]))
        and document["execution_sha256"] == canonical_sha256(identity)
        and isinstance(initial, int)
        and not isinstance(initial, bool)
        and 0 <= initial <= 28
        and isinstance(total, int)
        and not isinstance(total, bool)
        and initial <= total <= 56
        and isinstance(blockers, list)
        and blockers == sorted(set(blockers))
        and all(isinstance(item, str) and _CODE.fullmatch(item) for item in blockers)
    )
    blocked = bool(
        state == "blocked"
        and acceptance == "not-evaluated"
        and portfolio_sha256 is None
        and portfolio_artifact is None
        and blockers
    )
    completed = bool(
        state == "completed"
        and acceptance in {"accepted", "rejected"}
        and initial == 28
        and _DIGEST.fullmatch(str(portfolio_sha256))
        and _DIGEST.fullmatch(str(portfolio_artifact))
        and (acceptance == "accepted") == (not blockers)
    )
    if not common or not (blocked or completed):
        raise ValueError("Canonical execution report failed validation.")
    return document


def blocked_execution_report_document(
    matrix_sha256: str,
    reason: str,
) -> dict[str, object]:
    """Describe failure to finish the evidence process, never portfolio rejection."""

    if matrix_sha256 != PACKAGED_MATRIX_SHA256 or not _CODE.fullmatch(reason):
        raise ValueError("Blocked execution identity is invalid.")
    identity: dict[str, object] = {
        "schema_version": EXECUTION_REPORT_SCHEMA_VERSION,
        "matrix_sha256": matrix_sha256,
        "state": "blocked",
        "acceptance_state": "not-evaluated",
        "initial_cells_started": 0,
        "total_attempts_started": 0,
        "portfolio_sha256": None,
        "portfolio_artifact_sha256": None,
        "blockers": [reason],
    }
    return {**identity, "execution_sha256": canonical_sha256(identity)}


@dataclass(frozen=True)
class LoadedDurableExecutionEvidence:
    """One retained private bundle authorizing the complete execution evidence."""

    report: ExecutionReport
    portfolio: PortfolioRecord
    runs: tuple[LoadedDurableRunEvidence, ...] = field(repr=False, compare=False)
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
        if self._authority is not _LOADED_EXECUTION_AUTHORITY:
            raise ValueError("Loaded execution evidence is not verifier-issued.")
        if not _DIGEST.fullmatch(self.bundle_artifact_sha256):
            raise ValueError("Execution bundle identity is invalid.")

    def validate(self) -> bool:
        if _ISSUED_LOADED_EXECUTIONS.get(id(self)) is not self:
            return False
        try:
            self._bundle_capability.validate()
            return bool(
                verify_execution_report_identity(self.report)
                and verify_portfolio_record_identity(self.portfolio)
                and self.report.portfolio_sha256 == self.portfolio.portfolio_sha256
                and self.report.acceptance_state == self.portfolio.acceptance_state
                and self.report.blockers == self.portfolio.blockers
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return False

    def close(self) -> None:
        if _ISSUED_LOADED_EXECUTIONS.get(id(self)) is not self:
            return
        _ISSUED_LOADED_EXECUTIONS.pop(id(self), None)
        self._bundle_capability.close()


def _recomputed_portfolio(
    matrix: EvaluationMatrix,
    runs: tuple[LoadedDurableRunEvidence, ...],
    judgments: tuple[LoadedDurableJudgmentEvidence, ...],
    comparisons: tuple[DurableComparisonEvidence, ...],
) -> PortfolioRecord:
    portfolio = verify_effectiveness_portfolio(
        matrix,
        runs=runs,
        judgments=judgments,
        comparisons=comparisons,
    )
    _attempt_counts(portfolio)
    return portfolio


def _retained_artifact_capabilities(value: object) -> tuple[object, ...]:
    capability = getattr(value, "_capability", None)
    nested = getattr(capability, "_capabilities", None)
    if isinstance(nested, tuple) and nested:
        return nested
    if capability is not None:
        return (capability,)
    raise ValueError("Execution evidence lacks retained artifact bytes.")


def _execution_bundle_document(
    matrix: EvaluationMatrix,
    report: ExecutionReport,
    portfolio: PortfolioRecord,
    runs: tuple[LoadedDurableRunEvidence, ...],
    judgments: tuple[LoadedDurableJudgmentEvidence, ...],
    comparisons: tuple[DurableComparisonEvidence, ...],
) -> dict[str, object]:
    """Embed every top-level document and retained run/output byte exactly once."""

    assets: dict[tuple[str, str], dict[str, object]] = {}
    capability_sources: list[object] = []
    for item in runs:
        retained = _retained_artifact_capabilities(item)
        if item.record.state.value == "completed":
            output_matches = [
                capability
                for capability in retained
                if getattr(capability, "_artifact_type", None) == "runtime-quarantine"
                and getattr(capability, "_digest", None) == item.record.output_sha256
            ]
            if len(output_matches) != 1:
                raise ValueError("Completed bundle output evidence is incomplete.")
        capability_sources.extend(retained)
    for item in judgments:
        capability_sources.extend(_retained_artifact_capabilities(item))
    for item in comparisons:
        capability_sources.extend(_retained_artifact_capabilities(item.receipt))
    for capability in capability_sources:
        capability.validate()
        artifact_type = getattr(capability, "_artifact_type", None)
        digest = getattr(capability, "_digest", None)
        content = getattr(capability, "_content", None)
        if (
            not isinstance(artifact_type, str)
            or not _CODE.fullmatch(artifact_type)
            or not isinstance(digest, str)
            or not _DIGEST.fullmatch(digest)
            or not isinstance(content, bytes)
            or hashlib.sha256(content).hexdigest() != digest
        ):
            raise ValueError("Retained execution artifact identity changed.")
        key = (artifact_type, digest)
        row = {
            "artifact_type": artifact_type,
            "sha256": digest,
            "size_bytes": len(content),
            "encoding": "base64",
            "content": base64.b64encode(content).decode("ascii"),
        }
        if key in assets and assets[key] != row:
            raise ValueError("Duplicate execution artifact bytes differ.")
        assets[key] = row
    document: dict[str, object] = {
        "schema_version": EXECUTION_BUNDLE_SCHEMA_VERSION,
        "privacy_class": "private-evaluation-evidence",
        "matrix": matrix_document(matrix),
        "execution_report": _execution_identity_document(report),
        "portfolio": portfolio_record_document(portfolio),
        "run_records": sorted(
            (run_record_document(item.record) for item in runs),
            key=canonical_sha256,
        ),
        "criterion_judgments": sorted(
            (criterion_judgment_document(item.judgment) for item in judgments),
            key=canonical_sha256,
        ),
        "comparisons": sorted(
            (comparison_record_document(item.record) for item in comparisons),
            key=canonical_sha256,
        ),
        "retained_artifacts": [assets[key] for key in sorted(assets)],
    }
    if len(canonical_json_bytes(document)) > _MAX_EXECUTION_BUNDLE_BYTES:
        raise ValueError("Execution bundle exceeds the private evidence limit.")
    return document


def persist_completed_execution(
    root: Path,
    matrix: EvaluationMatrix,
    *,
    runs: tuple[LoadedDurableRunEvidence, ...],
    judgments: tuple[LoadedDurableJudgmentEvidence, ...],
    comparisons: tuple[DurableComparisonEvidence, ...],
) -> LoadedDurableExecutionEvidence:
    """Persist and fresh-reload one completed accepted or rejected portfolio."""

    portfolio = _recomputed_portfolio(matrix, runs, judgments, comparisons)
    portfolio_receipt = _write_standalone_evidence_document(
        root,
        "portfolio-record",
        portfolio_record_document(portfolio),
    )
    execution_receipt = None
    bundle_receipt = None
    try:
        report = _issue_execution_report(
            portfolio,
            portfolio_artifact_sha256=portfolio_receipt.sha256,
        )
        execution_receipt = _write_standalone_evidence_document(
            root,
            "execution-report",
            _execution_identity_document(report),
        )
        if execution_receipt.sha256 != report.execution_sha256:
            raise ValueError("Execution artifact identity changed during persistence.")
        bundle_receipt = _write_standalone_evidence_document(
            root,
            "execution-bundle",
            _execution_bundle_document(
                matrix,
                report,
                portfolio,
                runs,
                judgments,
                comparisons,
            ),
        )
        loaded = load_durable_execution_evidence(
            root,
            report.execution_sha256,
            matrix,
            runs=runs,
            judgments=judgments,
            comparisons=comparisons,
        )
        if loaded is None:
            raise ValueError("Completed execution could not be durably reloaded.")
        if loaded.bundle_artifact_sha256 != bundle_receipt.sha256:
            loaded.close()
            raise ValueError("Execution bundle identity changed during persistence.")
        return loaded
    finally:
        if bundle_receipt is not None:
            close_artifact_receipt(bundle_receipt)
        if execution_receipt is not None:
            close_artifact_receipt(execution_receipt)
        close_artifact_receipt(portfolio_receipt)


def load_durable_execution_evidence(
    root: Path,
    execution_sha256: str,
    matrix: EvaluationMatrix,
    *,
    runs: tuple[LoadedDurableRunEvidence, ...],
    judgments: tuple[LoadedDurableJudgmentEvidence, ...],
    comparisons: tuple[DurableComparisonEvidence, ...],
) -> LoadedDurableExecutionEvidence | None:
    """Recompute and retain the full portfolio/report chain after restart."""

    if not _DIGEST.fullmatch(execution_sha256):
        return None
    root_fd: int | None = None
    bundle_capability = None
    try:
        portfolio = _recomputed_portfolio(matrix, runs, judgments, comparisons)
        portfolio_document = portfolio_record_document(portfolio)
        portfolio_artifact_sha256 = canonical_sha256(portfolio_document)
        expected = _issue_execution_report(
            portfolio,
            portfolio_artifact_sha256=portfolio_artifact_sha256,
        )
        if expected.execution_sha256 != execution_sha256:
            return None
        bundle_document = _execution_bundle_document(
            matrix,
            expected,
            portfolio,
            runs,
            judgments,
            comparisons,
        )
        bundle_artifact_sha256 = canonical_sha256(bundle_document)
        root_fd = _open_root_directory(root)
        raw_bundle, bundle_capability = _open_linked_bytes(
            root_fd,
            "execution-bundle",
            f"{bundle_artifact_sha256}.json",
            bundle_artifact_sha256,
            maximum_size=_MAX_EXECUTION_BUNDLE_BYTES,
        )
        stored_bundle = json.loads(raw_bundle)
        if (
            not isinstance(stored_bundle, dict)
            or canonical_json_bytes(stored_bundle) != raw_bundle
            or stored_bundle != bundle_document
        ):
            return None
        bundle_capability.validate()
        loaded = LoadedDurableExecutionEvidence(
            expected,
            portfolio,
            runs,
            judgments,
            comparisons,
            bundle_artifact_sha256,
            bundle_capability,
            _LOADED_EXECUTION_AUTHORITY,
        )
        _ISSUED_LOADED_EXECUTIONS[id(loaded)] = loaded
        bundle_capability = None
        if not loaded.validate():
            loaded.close()
            return None
        return loaded
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if bundle_capability is not None:
            bundle_capability.close()
        if root_fd is not None:
            os.close(root_fd)


__all__ = [
    "EXECUTION_REPORT_SCHEMA_VERSION",
    "ExecutionReport",
    "LoadedDurableExecutionEvidence",
    "blocked_execution_report_document",
    "execution_report_document",
    "load_durable_execution_evidence",
    "persist_completed_execution",
    "validate_execution_report_document",
    "verify_execution_report_identity",
]
