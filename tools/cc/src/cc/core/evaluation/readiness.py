"""Non-authorizing, value-suppressing readiness for the exact live matrix."""

from __future__ import annotations

import os
import re
import tempfile
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from cc.core.evaluation.identity import content_receipt_identity
from cc.core.evaluation.matrix import (
    EvaluationMatrix,
    MatrixCellPlan,
    build_matrix,
)
from cc.core.evaluation.models import LayerVariant, RuntimeName
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256, packaged_cases_root

CLAUDE_READINESS_MODEL = "claude-fable-5"
CODEX_READINESS_MODEL = "gpt-5.6-sol"
RUNTIME_MODELS = {
    RuntimeName.CLAUDE.value: CLAUDE_READINESS_MODEL,
    RuntimeName.CODEX.value: CODEX_READINESS_MODEL,
}
_BLOCKER = re.compile(r"^[a-z][a-z0-9-]{0,95}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY = object()
_ISSUED: weakref.WeakValueDictionary[int, "CanonicalReadinessReport"] = (
    weakref.WeakValueDictionary()
)


class CanonicalReadinessUnavailable(ValueError):
    """The caller did not select the released matrix/model contract."""

    def __init__(self, reason: str) -> None:
        if not _BLOCKER.fullmatch(reason):
            raise ValueError("Readiness blocker is not a stable identifier.")
        self.reason = reason
        super().__init__(reason)


def _require_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError(f"Readiness {label} is invalid.")


@dataclass(frozen=True)
class CellReadiness:
    case_id: str
    variant: str
    runtime: str
    role: str
    plan_sha256: str
    state: str
    content_receipt_sha256: str | None
    projection_evidence_sha256: str | None
    blocker: str | None

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"eval-0[1-7]", self.case_id)
            or self.variant not in {item.value for item in LayerVariant}
            or self.runtime not in {item.value for item in RuntimeName}
            or self.role not in {"control", "layered"}
            or self.state not in {"ready", "blocked"}
        ):
            raise ValueError("Cell readiness is invalid.")
        _require_digest(self.plan_sha256, "plan identity")
        if self.state == "ready":
            _require_digest(self.content_receipt_sha256, "content identity")
            _require_digest(self.projection_evidence_sha256, "projection identity")
            if self.blocker is not None:
                raise ValueError("Ready cell cannot declare a blocker.")
        elif (
            self.content_receipt_sha256 is not None
            or self.projection_evidence_sha256 is not None
            or not isinstance(self.blocker, str)
            or not _BLOCKER.fullmatch(self.blocker)
        ):
            raise ValueError("Blocked cell disposition is invalid.")


@dataclass(frozen=True)
class RuntimeReadiness:
    runtime: str
    model: str
    state: str
    executable_state: str
    executable_sha256: str | None
    authentication_state: str
    authentication_evidence_sha256: str | None
    broker_state: str
    broker_evidence_sha256: str
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.runtime not in {item.value for item in RuntimeName}
            or self.model != RUNTIME_MODELS.get(self.runtime)
            or self.state not in {"ready", "blocked"}
            or self.executable_state not in {"ready", "blocked"}
            or self.authentication_state not in {"ready", "blocked"}
            or self.broker_state not in {"ready", "not-required", "blocked"}
            or any(not _BLOCKER.fullmatch(item) for item in self.blockers)
            or tuple(sorted(set(self.blockers))) != self.blockers
        ):
            raise ValueError("Runtime readiness is invalid.")
        _require_digest(self.broker_evidence_sha256, "broker evidence")
        if self.executable_state == "ready":
            _require_digest(self.executable_sha256, "runtime executable")
        elif self.executable_sha256 is not None:
            raise ValueError("Unavailable runtime cannot claim an executable.")
        if self.authentication_state == "ready":
            if self.executable_state != "ready":
                raise ValueError("Authentication requires an exact runtime executable.")
            _require_digest(
                self.authentication_evidence_sha256,
                "authentication evidence",
            )
        elif self.authentication_evidence_sha256 is not None:
            raise ValueError("Blocked authentication cannot claim evidence.")
        expected_state = (
            "ready"
            if self.executable_state == "ready"
            and self.authentication_state == "ready"
            and self.broker_state in {"ready", "not-required"}
            and not self.blockers
            else "blocked"
        )
        if (
            self.state != expected_state
            or (self.state == "ready" and self.blockers)
            or (self.state == "blocked" and not self.blockers)
        ):
            raise ValueError("Runtime readiness state is contradictory.")


@dataclass(frozen=True)
class CanonicalReadinessReport:
    schema_version: str
    state: str
    matrix_sha256: str
    runtime_models_sha256: str
    cells: tuple[CellReadiness, ...]
    runtimes: tuple[RuntimeReadiness, ...]
    blockers: tuple[str, ...]
    live_calls_started: int
    artifacts_written: int
    readiness_sha256: str
    _seal: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _AUTHORITY:
            raise ValueError("Readiness report is not verifier-issued.")

    def validate(self) -> bool:
        return verify_canonical_readiness(self)


def _plan_document(plan: MatrixCellPlan) -> dict[str, object]:
    return {
        "case_id": plan.case_id,
        "revision": plan.revision,
        "variant": plan.variant.value,
        "runtime": plan.runtime.value,
        "role": plan.role,
        "fixture_packet_sha256": plan.fixture_packet_sha256,
        "route_classification": plan.route_classification,
        "expected_specialist": plan.expected_specialist,
        "route_contract_sha256": plan.route_contract_sha256,
    }


def _cell_document(value: CellReadiness) -> dict[str, object]:
    return {
        "case_id": value.case_id,
        "variant": value.variant,
        "runtime": value.runtime,
        "role": value.role,
        "plan_sha256": value.plan_sha256,
        "state": value.state,
        "content_receipt_sha256": value.content_receipt_sha256,
        "projection_evidence_sha256": value.projection_evidence_sha256,
        "blocker": value.blocker,
    }


def _runtime_document(value: RuntimeReadiness) -> dict[str, object]:
    return {
        "runtime": value.runtime,
        "model": value.model,
        "state": value.state,
        "executable_state": value.executable_state,
        "executable_sha256": value.executable_sha256,
        "authentication_state": value.authentication_state,
        "authentication_evidence_sha256": value.authentication_evidence_sha256,
        "broker_state": value.broker_state,
        "broker_evidence_sha256": value.broker_evidence_sha256,
        "blockers": list(value.blockers),
    }


def _report_body(value: CanonicalReadinessReport) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "state": value.state,
        "matrix_sha256": value.matrix_sha256,
        "runtime_models_sha256": value.runtime_models_sha256,
        "cells": [_cell_document(item) for item in value.cells],
        "runtimes": [_runtime_document(item) for item in value.runtimes],
        "blockers": list(value.blockers),
        "live_calls_started": value.live_calls_started,
        "artifacts_written": value.artifacts_written,
    }


def readiness_document(value: CanonicalReadinessReport) -> dict[str, object]:
    """Return the bounded public document for one authentic report."""

    if not verify_canonical_readiness(value):
        raise ValueError("Readiness report identity is invalid.")
    return {**_report_body(value), "readiness_sha256": value.readiness_sha256}


def _exact_matrix(fixtures_root: Path) -> EvaluationMatrix:
    try:
        selected = Path(fixtures_root)
        packaged = packaged_cases_root()
        if (
            not selected.is_absolute()
            or not selected.samefile(packaged)
            or Path(os.path.realpath(selected)) != selected
        ):
            raise CanonicalReadinessUnavailable("preregistered-matrix-unavailable")
        matrix, _fixtures = build_matrix(selected)
    except CanonicalReadinessUnavailable:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise CanonicalReadinessUnavailable("preregistered-matrix-unavailable") from exc
    if matrix.matrix_sha256 != PACKAGED_MATRIX_SHA256 or len(matrix.cells) != 28:
        raise CanonicalReadinessUnavailable("preregistered-matrix-unavailable")
    return matrix


def _exact_models(runtime_models: Mapping[str, str]) -> str:
    if (
        not isinstance(runtime_models, Mapping)
        or dict(runtime_models) != RUNTIME_MODELS
    ):
        raise CanonicalReadinessUnavailable("runtime-model-policy-invalid")
    return canonical_sha256(
        {
            "schema_version": "task285-runtime-model-policy-v1",
            "models": dict(sorted(RUNTIME_MODELS.items())),
        }
    )


def _probe_content_plan(
    plan: MatrixCellPlan,
) -> tuple[str | None, str | None, str | None]:
    """Resolve one content projection and close it before returning digests."""

    from cc.core.evaluation.content_authority import (
        CanonicalContentUnavailable,
        issue_canonical_claude_content,
        issue_canonical_codex_content,
        verify_canonical_content_projection,
    )
    from cc.evaluation_fixtures.personal_snapshot import materialize_personal_snapshot

    projection = None
    receipt = None
    temporary = None
    blocker = None
    content_sha256 = None
    projection_sha256 = None
    try:
        if plan.variant is LayerVariant.PERSONAL and plan.case_id == "eval-07":
            temporary = tempfile.TemporaryDirectory(
                prefix=".cc-evaluation-personal-readiness-"
            )
            private_root = Path(temporary.name)
            private_root.chmod(0o700)
            receipt = materialize_personal_snapshot(private_root / "personal-content")
        issuer = (
            issue_canonical_claude_content
            if plan.runtime is RuntimeName.CLAUDE
            else issue_canonical_codex_content
        )
        projection = issuer(
            variant=plan.variant,
            specialist=plan.expected_specialist,
            case_id=plan.case_id,
            personal_snapshot_receipt=receipt,
        )
        if (
            not verify_canonical_content_projection(projection)
            or projection.content_receipt.variant is not plan.variant
        ):
            raise CanonicalContentUnavailable("canonical-config-changed")
        content_sha256 = content_receipt_identity(projection.content_receipt)
        projection_sha256 = projection.evidence_sha256
    except CanonicalContentUnavailable as exc:
        blocker = f"canonical-content-{exc.reason}"
    except (OSError, RuntimeError, TypeError, ValueError):
        blocker = "canonical-content-verifier-unavailable"
    cleanup_failed = False
    for close in (getattr(projection, "close", None), getattr(receipt, "close", None)):
        if callable(close):
            try:
                close()
            except BaseException:
                cleanup_failed = True
    if temporary is not None:
        try:
            temporary.cleanup()
        except BaseException:
            cleanup_failed = True
    if cleanup_failed:
        return None, None, "canonical-content-cleanup-failed"
    if blocker is not None:
        return None, None, blocker
    return content_sha256, projection_sha256, None


def _probe_runtime(runtime: RuntimeName, model: str) -> RuntimeReadiness:
    """Probe local executable/auth facts; never construct a model request."""

    from cc.core.evaluation.live_runtime import (
        CLAUDE_ADAPTER_NAME,
        CLAUDE_ADAPTER_VERSION,
        CODEX_ADAPTER_NAME,
        CODEX_ADAPTER_VERSION,
        _codex_native_executable,
        _executable_sha256,
        runtime_authentication_status,
    )
    from cc.core.executables import resolve_executable

    executable_sha256 = None
    executable_state = "blocked"
    auth_sha256 = None
    auth_state = "blocked"
    blockers: set[str] = set()
    try:
        resolved = resolve_executable(runtime.value)
        if resolved is None:
            raise ValueError("Runtime executable is unavailable.")
        executable = Path(resolved)
        selected = (
            _codex_native_executable(executable)
            if runtime is RuntimeName.CODEX
            else executable
        )
        executable_sha256 = _executable_sha256(selected)
        executable_state = "ready"
        authenticated, reason = runtime_authentication_status(runtime, executable)
        if not authenticated:
            stable = (
                reason
                if isinstance(reason, str) and _BLOCKER.fullmatch(reason)
                else None
            )
            blockers.add(f"{runtime.value}-{stable or 'not-authenticated'}")
        else:
            auth_state = "ready"
            adapter_name, adapter_version = (
                (CLAUDE_ADAPTER_NAME, CLAUDE_ADAPTER_VERSION)
                if runtime is RuntimeName.CLAUDE
                else (CODEX_ADAPTER_NAME, CODEX_ADAPTER_VERSION)
            )
            auth_sha256 = canonical_sha256(
                {
                    "schema_version": "task285-runtime-auth-readiness-v1",
                    "runtime": runtime.value,
                    "model": model,
                    "executable_sha256": executable_sha256,
                    "adapter_name": adapter_name,
                    "adapter_version": adapter_version,
                    "authentication": "authenticated",
                }
            )
    except (OSError, RuntimeError, TypeError, ValueError):
        blockers.add(f"{runtime.value}-runtime-unavailable")
        executable_state = "blocked"
        executable_sha256 = None

    broker_state = "not-required"
    broker_reason = "claude-native-boundary"
    if runtime is RuntimeName.CODEX:
        broker_state = "blocked"
        broker_reason = "codex-live-authorization-unavailable"
        blockers.add(broker_reason)
    broker_sha256 = canonical_sha256(
        {
            "schema_version": "task285-runtime-broker-readiness-v1",
            "runtime": runtime.value,
            "model": model,
            "state": broker_state,
            "reason": broker_reason,
        }
    )
    ordered = tuple(sorted(blockers))
    return RuntimeReadiness(
        runtime=runtime.value,
        model=model,
        state=(
            "ready"
            if executable_state == "ready"
            and auth_state == "ready"
            and broker_state in {"ready", "not-required"}
            else "blocked"
        ),
        executable_state=executable_state,
        executable_sha256=executable_sha256,
        authentication_state=auth_state,
        authentication_evidence_sha256=auth_sha256,
        broker_state=broker_state,
        broker_evidence_sha256=broker_sha256,
        blockers=ordered,
    )


def _issue_report(
    matrix: EvaluationMatrix,
    runtime_models_sha256: str,
    cells: tuple[CellReadiness, ...],
    runtimes: tuple[RuntimeReadiness, ...],
) -> CanonicalReadinessReport:
    blockers = tuple(
        sorted(
            {
                *(item.blocker for item in cells if item.blocker is not None),
                *(blocker for runtime in runtimes for blocker in runtime.blockers),
            }
        )
    )
    state = "ready" if not blockers else "blocked"
    seal = object()
    provisional = CanonicalReadinessReport(
        schema_version="task285-canonical-readiness-v1",
        state=state,
        matrix_sha256=matrix.matrix_sha256,
        runtime_models_sha256=runtime_models_sha256,
        cells=cells,
        runtimes=runtimes,
        blockers=blockers,
        live_calls_started=0,
        artifacts_written=0,
        readiness_sha256="0" * 64,
        _seal=seal,
        _authority=_AUTHORITY,
    )
    result = CanonicalReadinessReport(
        **{
            **provisional.__dict__,
            "readiness_sha256": canonical_sha256(_report_body(provisional)),
        }
    )
    _ISSUED[id(result)] = result
    if not verify_canonical_readiness(result):
        raise ValueError("Readiness report could not be sealed.")
    return result


def verify_canonical_readiness(value: object) -> bool:
    if not isinstance(value, CanonicalReadinessReport):
        return False
    try:
        matrix, _fixtures = build_matrix(packaged_cases_root())
        expected_cells = tuple(
            (
                plan.case_id,
                plan.variant.value,
                plan.runtime.value,
                plan.role,
                canonical_sha256(_plan_document(plan)),
            )
            for plan in matrix.cells
        )
        actual_cells = tuple(
            (
                item.case_id,
                item.variant,
                item.runtime,
                item.role,
                item.plan_sha256,
            )
            for item in value.cells
        )
        if (
            _ISSUED.get(id(value)) is not value
            or value.schema_version != "task285-canonical-readiness-v1"
            or value.state not in {"ready", "blocked"}
            or value.matrix_sha256 != PACKAGED_MATRIX_SHA256
            or matrix.matrix_sha256 != PACKAGED_MATRIX_SHA256
            or value.runtime_models_sha256 != _exact_models(RUNTIME_MODELS)
            or len(value.cells) != 28
            or actual_cells != expected_cells
            or len(value.runtimes) != 2
            or value.live_calls_started != 0
            or value.artifacts_written != 0
            or value.readiness_sha256 != canonical_sha256(_report_body(value))
            or tuple(item.runtime for item in value.runtimes) != ("claude", "codex")
            or tuple(sorted(set(value.blockers))) != value.blockers
        ):
            return False
        expected_blockers = tuple(
            sorted(
                {
                    *(item.blocker for item in value.cells if item.blocker is not None),
                    *(
                        blocker
                        for runtime in value.runtimes
                        for blocker in runtime.blockers
                    ),
                }
            )
        )
        return bool(
            expected_blockers == value.blockers
            and value.state == ("ready" if not expected_blockers else "blocked")
            and all(
                item.state == ("ready" if item.blocker is None else "blocked")
                for item in value.cells
            )
        )
    except (
        AttributeError,
        CanonicalReadinessUnavailable,
        OSError,
        TypeError,
        ValueError,
    ):
        return False


def issue_canonical_readiness(
    *,
    fixtures_root: Path,
    runtime_models: Mapping[str, str],
) -> CanonicalReadinessReport:
    """Inspect exact prerequisites without authorizing or starting dispatch."""

    matrix = _exact_matrix(fixtures_root)
    runtime_models_sha256 = _exact_models(runtime_models)
    cells = []
    for plan in matrix.cells:
        content_sha256, projection_sha256, blocker = _probe_content_plan(plan)
        cells.append(
            CellReadiness(
                case_id=plan.case_id,
                variant=plan.variant.value,
                runtime=plan.runtime.value,
                role=plan.role,
                plan_sha256=canonical_sha256(_plan_document(plan)),
                state="ready" if blocker is None else "blocked",
                content_receipt_sha256=content_sha256,
                projection_evidence_sha256=projection_sha256,
                blocker=blocker,
            )
        )
    runtimes = tuple(
        _probe_runtime(runtime, RUNTIME_MODELS[runtime.value])
        for runtime in RuntimeName
    )
    return _issue_report(matrix, runtime_models_sha256, tuple(cells), runtimes)


__all__ = [
    "CLAUDE_READINESS_MODEL",
    "CODEX_READINESS_MODEL",
    "CanonicalReadinessReport",
    "CanonicalReadinessUnavailable",
    "CellReadiness",
    "RuntimeReadiness",
    "RUNTIME_MODELS",
    "issue_canonical_readiness",
    "readiness_document",
    "verify_canonical_readiness",
]
