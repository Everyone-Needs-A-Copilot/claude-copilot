from __future__ import annotations

import copy
from pathlib import Path

import pytest
from cc.core.evaluation import execution, readiness
from cc.core.evaluation.models import RuntimeName
from cc.core.evaluation.readiness import RuntimeReadiness
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import packaged_cases_root


def _models() -> dict[str, str]:
    return {
        "claude": execution.CLAUDE_EVALUATION_MODEL,
        "codex": execution.CODEX_EVALUATION_MODEL,
    }


def _install_readiness_probes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    content_blocker: str | None = None,
    codex_broker_ready: bool = False,
) -> None:
    def content(plan):
        if content_blocker is not None and plan.case_id == "eval-01":
            return None, None, content_blocker
        subject = {
            "case_id": plan.case_id,
            "variant": plan.variant.value,
            "runtime": plan.runtime.value,
        }
        return (
            canonical_sha256({**subject, "evidence": "content"}),
            canonical_sha256({**subject, "evidence": "projection"}),
            None,
        )

    def runtime(runtime_name: RuntimeName, model: str) -> RuntimeReadiness:
        broker_state = "not-required"
        blockers: tuple[str, ...] = ()
        if runtime_name is RuntimeName.CODEX:
            broker_state = "ready" if codex_broker_ready else "blocked"
            if not codex_broker_ready:
                blockers = ("codex-live-authorization-unavailable",)
        return RuntimeReadiness(
            runtime=runtime_name.value,
            model=model,
            state="ready" if not blockers else "blocked",
            executable_state="ready",
            executable_sha256=canonical_sha256(
                {"runtime": runtime_name.value, "evidence": "executable"}
            ),
            authentication_state="ready",
            authentication_evidence_sha256=canonical_sha256(
                {"runtime": runtime_name.value, "evidence": "authentication"}
            ),
            broker_state=broker_state,
            broker_evidence_sha256=canonical_sha256(
                {"runtime": runtime_name.value, "evidence": "broker"}
            ),
            blockers=blockers,
        )

    monkeypatch.setattr(readiness, "_probe_content_plan", content)
    monkeypatch.setattr(readiness, "_probe_runtime", runtime)


def _assert_public_execution_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    coordinator_calls = 0

    def coordinator(*_args, **_kwargs):
        nonlocal coordinator_calls
        coordinator_calls += 1
        raise AssertionError("Readiness cannot authorize phase one.")

    monkeypatch.setattr(execution, "_execute_phase_one_matrix", coordinator)
    artifact_root = tmp_path / "must-not-exist"
    with pytest.raises(execution.EvaluationExecutionUnavailable, match=reason):
        execution.issue_matrix_execution(
            fixtures_root=packaged_cases_root(),
            artifact_root=artifact_root,
            runtime_models=_models(),
        )
    assert coordinator_calls == 0
    assert not artifact_root.exists()


def test_blocked_readiness_maps_exact_reason_before_artifacts_or_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_readiness_probes(monkeypatch)

    _assert_public_execution_blocked(
        tmp_path,
        monkeypatch,
        "codex-live-authorization-unavailable",
    )


def test_multiple_readiness_blockers_map_in_stable_sorted_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_readiness_probes(
        monkeypatch,
        content_blocker="canonical-content-materialized-lock-mismatch",
    )

    _assert_public_execution_blocked(
        tmp_path,
        monkeypatch,
        "canonical-content-materialized-lock-mismatch",
    )


def test_even_authentic_ready_snapshot_cannot_authorize_phase_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_readiness_probes(monkeypatch, codex_broker_ready=True)

    _assert_public_execution_blocked(
        tmp_path,
        monkeypatch,
        "codex-live-authorization-unavailable",
    )


def test_copied_readiness_snapshot_rejects_before_artifacts_or_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_readiness_probes(monkeypatch, codex_broker_ready=True)
    report = readiness.issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=_models(),
    )
    copied = copy.copy(report)
    monkeypatch.setattr(
        readiness,
        "issue_canonical_readiness",
        lambda **_kwargs: copied,
    )

    _assert_public_execution_blocked(
        tmp_path,
        monkeypatch,
        "canonical-readiness-invalid",
    )


def test_nested_readiness_substitution_rejects_before_artifacts_or_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_readiness_probes(monkeypatch, codex_broker_ready=True)
    report = readiness.issue_canonical_readiness(
        fixtures_root=packaged_cases_root(),
        runtime_models=_models(),
    )
    object.__setattr__(
        report.cells[0],
        "projection_evidence_sha256",
        canonical_sha256({"forged": "projection"}),
    )
    object.__setattr__(
        report,
        "readiness_sha256",
        canonical_sha256(readiness._report_body(report)),
    )
    monkeypatch.setattr(
        readiness,
        "issue_canonical_readiness",
        lambda **_kwargs: report,
    )

    _assert_public_execution_blocked(
        tmp_path,
        monkeypatch,
        "canonical-readiness-invalid",
    )
