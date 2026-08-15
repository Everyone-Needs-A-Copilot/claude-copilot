from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest
from cc.core.evaluation import readiness as readiness_module
from cc.core.evaluation.matrix import build_matrix
from cc.core.evaluation.models import RuntimeName
from cc.core.evaluation.readiness import (
    RUNTIME_MODELS,
    CanonicalReadinessReport,
    CanonicalReadinessUnavailable,
    RuntimeReadiness,
    issue_canonical_readiness,
    readiness_document,
    verify_canonical_readiness,
)
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256, packaged_cases_root


def _ready_runtime(runtime: RuntimeName, model: str) -> RuntimeReadiness:
    broker_state = "not-required" if runtime is RuntimeName.CLAUDE else "ready"
    return RuntimeReadiness(
        runtime=runtime.value,
        model=model,
        state="ready",
        executable_state="ready",
        executable_sha256=canonical_sha256(
            {"runtime": runtime.value, "subject": "synthetic-native"}
        ),
        authentication_state="ready",
        authentication_evidence_sha256=canonical_sha256(
            {"runtime": runtime.value, "subject": "synthetic-auth"}
        ),
        broker_state=broker_state,
        broker_evidence_sha256=canonical_sha256(
            {"runtime": runtime.value, "subject": "synthetic-broker"}
        ),
        blockers=(),
    )


def _install_ready_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []

    def content(plan):
        calls.append((plan.case_id, plan.variant.value, plan.runtime.value))
        return (
            canonical_sha256(
                {
                    "case_id": plan.case_id,
                    "variant": plan.variant.value,
                    "runtime": plan.runtime.value,
                    "subject": "synthetic-content",
                }
            ),
            canonical_sha256(
                {
                    "case_id": plan.case_id,
                    "variant": plan.variant.value,
                    "runtime": plan.runtime.value,
                    "subject": "synthetic-projection",
                }
            ),
            None,
        )

    monkeypatch.setattr(readiness_module, "_probe_content_plan", content)
    monkeypatch.setattr(readiness_module, "_probe_runtime", _ready_runtime)
    return calls


def _unregistered_report(
    report: CanonicalReadinessReport,
    **changes,
) -> CanonicalReadinessReport:
    fields = {**report.__dict__, **changes, "readiness_sha256": "0" * 64}
    provisional = CanonicalReadinessReport(**fields)
    return CanonicalReadinessReport(
        **{
            **fields,
            "readiness_sha256": canonical_sha256(
                readiness_module._report_body(provisional)
            ),
        }
    )


def test_exact_synthetic_readiness_covers_all_cells_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_ready_probes(monkeypatch)

    report = issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=RUNTIME_MODELS,
    )
    document = readiness_document(report)
    matrix, _fixtures = build_matrix(packaged_cases_root())

    assert verify_canonical_readiness(report)
    assert report.state == "ready"
    assert report.matrix_sha256 == PACKAGED_MATRIX_SHA256
    assert len(report.cells) == 28
    assert len(set(calls)) == 28
    assert calls == [
        (plan.case_id, plan.variant.value, plan.runtime.value) for plan in matrix.cells
    ]
    assert all(item.state == "ready" for item in report.cells)
    assert report.blockers == ()
    assert report.live_calls_started == 0
    assert report.artifacts_written == 0
    assert document["readiness_sha256"] == canonical_sha256(
        {key: value for key, value in document.items() if key != "readiness_sha256"}
    )


def test_blocked_report_preserves_all_cell_dispositions_and_closed_broker_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_ready_probes(monkeypatch)
    ready_content = readiness_module._probe_content_plan

    def content(plan):
        if plan.runtime is RuntimeName.CODEX and plan.variant.value != "F":
            calls.append((plan.case_id, plan.variant.value, plan.runtime.value))
            return None, None, "canonical-content-materialized-lock-mismatch"
        return ready_content(plan)

    def runtime(runtime: RuntimeName, model: str) -> RuntimeReadiness:
        if runtime is RuntimeName.CLAUDE:
            return _ready_runtime(runtime, model)
        return RuntimeReadiness(
            runtime=runtime.value,
            model=model,
            state="blocked",
            executable_state="ready",
            executable_sha256=canonical_sha256({"runtime": runtime.value}),
            authentication_state="ready",
            authentication_evidence_sha256=canonical_sha256(
                {"runtime": runtime.value, "authentication": "synthetic"}
            ),
            broker_state="blocked",
            broker_evidence_sha256=canonical_sha256(
                {"runtime": runtime.value, "broker": "unavailable"}
            ),
            blockers=("codex-live-authorization-unavailable",),
        )

    monkeypatch.setattr(readiness_module, "_probe_content_plan", content)
    monkeypatch.setattr(readiness_module, "_probe_runtime", runtime)

    report = issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=RUNTIME_MODELS,
    )

    assert verify_canonical_readiness(report)
    assert report.state == "blocked"
    assert len(report.cells) == 28
    assert len(calls) == 28
    assert report.blockers == (
        "canonical-content-materialized-lock-mismatch",
        "codex-live-authorization-unavailable",
    )
    assert report.live_calls_started == 0
    assert report.artifacts_written == 0


def test_readiness_rejects_nonpackaged_matrix_and_model_alias(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        CanonicalReadinessUnavailable,
        match="preregistered-matrix-unavailable",
    ):
        issue_canonical_readiness(
            fixtures_root=tmp_path,
            runtime_models=RUNTIME_MODELS,
        )

    with pytest.raises(
        CanonicalReadinessUnavailable,
        match="runtime-model-policy-invalid",
    ):
        issue_canonical_readiness(
            fixtures_root=packaged_cases_root(),
            runtime_models={**RUNTIME_MODELS, "claude": "fable"},
        )


def test_readiness_copy_and_field_replacement_cannot_retain_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    report = issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=RUNTIME_MODELS,
    )

    shallow = copy.copy(report)
    forged = replace(report, state="blocked", blockers=("forged-blocker",))

    assert not verify_canonical_readiness(shallow)
    assert not verify_canonical_readiness(forged)
    assert verify_canonical_readiness(report)
    with pytest.raises(ValueError, match="identity is invalid"):
        readiness_document(forged)


def test_readiness_has_no_caller_evidence_issuer_and_direct_payloads_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    report = issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=RUNTIME_MODELS,
    )
    forged_cell = replace(
        report.cells[0],
        content_receipt_sha256=canonical_sha256({"forged": "cell"}),
    )
    forged_runtime = replace(
        report.runtimes[0],
        executable_sha256=canonical_sha256({"forged": "runtime"}),
    )

    assert not hasattr(readiness_module, "_issue_report")
    assert not verify_canonical_readiness(_unregistered_report(report))
    assert not verify_canonical_readiness(
        _unregistered_report(report, cells=report.cells[:-1])
    )
    assert not verify_canonical_readiness(
        _unregistered_report(
            report,
            cells=(forged_cell, *report.cells[1:]),
        )
    )
    assert not verify_canonical_readiness(
        _unregistered_report(
            report,
            runtimes=(forged_runtime, report.runtimes[1]),
        )
    )


def test_runtime_probe_subject_substitution_fails_before_report_issuance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)

    def substituted_runtime(runtime: RuntimeName, _model: str) -> RuntimeReadiness:
        other = (
            RuntimeName.CODEX if runtime is RuntimeName.CLAUDE else RuntimeName.CLAUDE
        )
        return _ready_runtime(other, RUNTIME_MODELS[other.value])

    monkeypatch.setattr(readiness_module, "_probe_runtime", substituted_runtime)

    with pytest.raises(
        CanonicalReadinessUnavailable,
        match="runtime-readiness-invalid",
    ):
        issue_canonical_readiness(
            fixtures_root=packaged_cases_root(),
            runtime_models=RUNTIME_MODELS,
        )


def test_nested_cell_mutation_and_recomputed_public_digest_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    report = issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=RUNTIME_MODELS,
    )

    object.__setattr__(
        report.cells[0],
        "content_receipt_sha256",
        canonical_sha256({"forged": "nested-content"}),
    )
    object.__setattr__(
        report,
        "readiness_sha256",
        canonical_sha256(readiness_module._report_body(report)),
    )

    assert not verify_canonical_readiness(report)


def test_nested_runtime_mutation_and_recomputed_public_digest_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    report = issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=RUNTIME_MODELS,
    )

    object.__setattr__(
        report.runtimes[0],
        "authentication_evidence_sha256",
        canonical_sha256({"forged": "nested-runtime"}),
    )
    object.__setattr__(
        report,
        "readiness_sha256",
        canonical_sha256(readiness_module._report_body(report)),
    )

    assert not verify_canonical_readiness(report)


def test_short_internal_matrix_cannot_be_sealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    matrix, _fixtures = build_matrix(packaged_cases_root())
    forged = object.__new__(type(matrix))
    object.__setattr__(forged, "schema_version", matrix.schema_version)
    object.__setattr__(forged, "cells", matrix.cells[:-1])
    object.__setattr__(forged, "matrix_sha256", matrix.matrix_sha256)
    monkeypatch.setattr(readiness_module, "_exact_matrix", lambda _root: forged)

    with pytest.raises(
        CanonicalReadinessUnavailable,
        match="readiness-verification-failed",
    ):
        issue_canonical_readiness(
            fixtures_root=packaged_cases_root(),
            runtime_models=RUNTIME_MODELS,
        )


def test_readiness_report_exposes_no_dispatch_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    report = issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=RUNTIME_MODELS,
    )

    assert not hasattr(report, "run_authorized")
    assert not hasattr(report, "begin_execution")
    assert not hasattr(report, "permit")


def test_readiness_document_is_value_suppressing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    document = readiness_document(
        issue_canonical_readiness(
            fixtures_root=packaged_cases_root(),
            runtime_models=RUNTIME_MODELS,
        )
    )
    rendered = str(document)

    assert "problem_statement" not in rendered
    assert "private_oracle" not in rendered
    assert "knowledge_payload" not in rendered
    assert "source.path" not in rendered
    assert str(Path.home()) not in rendered
