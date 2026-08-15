from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from cc.core.evaluation import execution
from cc.core.evaluation.content_authority import CanonicalContentUnavailable
from cc.core.evaluation.execution import (
    CLAUDE_EVALUATION_MODEL,
    CODEX_EVALUATION_MODEL,
    EvaluationExecutionUnavailable,
    issue_matrix_execution,
)
from cc.core.evaluation.matrix import build_matrix
from cc.core.evaluation.models import LayerVariant, RuntimeName
from cc.evaluation_fixtures import packaged_cases_root


def _models() -> dict[str, str]:
    return {
        "claude": CLAUDE_EVALUATION_MODEL,
        "codex": CODEX_EVALUATION_MODEL,
    }


def test_execution_boundary_accepts_only_exact_packaged_inputs_and_starts_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    observed = []

    def blocked(matrix, runtime_models) -> None:
        observed.append(matrix.matrix_sha256)
        assert runtime_models == _models()
        raise EvaluationExecutionUnavailable("codex-content-projection-unavailable")

    monkeypatch.setattr(execution, "_require_canonical_readiness", blocked)

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="codex-content-projection-unavailable",
    ):
        issue_matrix_execution(
            fixtures_root=packaged_cases_root(),
            artifact_root=artifact_root,
            runtime_models=_models(),
        )

    assert len(observed) == 1
    assert not artifact_root.exists()


def test_codex_zero_call_matrix_persists_all_fourteen_unsupported_cells(
    tmp_path: Path,
) -> None:
    matrix, fixtures = build_matrix(packaged_cases_root())
    artifact_root = tmp_path / "artifacts"

    report = execution._execute_codex_zero_call_matrix(
        matrix,
        fixtures,
        artifact_root,
    )

    assert report["schema_version"] == "task285-codex-unsupported-v1"
    assert report["matrix_sha256"] == matrix.matrix_sha256
    assert report["state"] == "unsupported"
    assert report["reason"] == "codex-no-tool-isolation-unavailable"
    assert report["live_calls_started"] == 0
    assert len(report["run_sha256s"]) == len(set(report["run_sha256s"])) == 14
    assert len(tuple((artifact_root / "run-record").glob("*.json"))) == 14
    assert len(tuple((artifact_root / "runtime-receipt").glob("*.json"))) == 1
    assert len(tuple((artifact_root / "content-receipt").glob("*.json"))) == 14
    assert len(tuple((artifact_root / "consumption-receipt").glob("*.json"))) == 14


def test_codex_zero_call_matrix_rejects_missing_fixture_before_any_artifact(
    tmp_path: Path,
) -> None:
    matrix, fixtures = build_matrix(packaged_cases_root())
    artifact_root = tmp_path / "artifacts"

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="preregistered-fixtures-unavailable",
    ):
        execution._execute_codex_zero_call_matrix(
            matrix,
            fixtures[:-1],
            artifact_root,
        )

    assert not artifact_root.exists()


@pytest.mark.parametrize(
    "runtime_models",
    (
        {"claude": "fable", "codex": CODEX_EVALUATION_MODEL},
        {"claude": CLAUDE_EVALUATION_MODEL, "codex": "default"},
        {"claude": CLAUDE_EVALUATION_MODEL},
        {
            "claude": CLAUDE_EVALUATION_MODEL,
            "codex": CODEX_EVALUATION_MODEL,
            "other": "model",
        },
    ),
)
def test_execution_boundary_rejects_alias_default_missing_or_extra_models(
    tmp_path: Path,
    runtime_models: dict[str, str],
) -> None:
    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="runtime-model-policy-invalid",
    ):
        issue_matrix_execution(
            fixtures_root=packaged_cases_root(),
            artifact_root=tmp_path / "artifacts",
            runtime_models=runtime_models,
        )


def test_execution_boundary_rejects_byte_identical_unregistered_fixture_copy(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "copied-cases"
    shutil.copytree(packaged_cases_root(), copied)

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="preregistered-matrix-unavailable",
    ):
        issue_matrix_execution(
            fixtures_root=copied,
            artifact_root=tmp_path / "artifacts",
            runtime_models=_models(),
        )


@pytest.mark.parametrize("kind", ("relative", "permissive", "symlink"))
def test_execution_boundary_rejects_untrusted_artifact_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    if kind == "relative":
        selected = Path("relative-artifacts")
    elif kind == "permissive":
        selected = tmp_path / "permissive"
        selected.mkdir(mode=0o755)
        selected.chmod(0o755)
    else:
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        selected = tmp_path / "linked"
        selected.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(
        execution,
        "_require_canonical_readiness",
        lambda _matrix, _models: pytest.fail("readiness must not run"),
    )

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="artifact-root-policy-invalid",
    ):
        issue_matrix_execution(
            fixtures_root=packaged_cases_root(),
            artifact_root=selected,
            runtime_models=_models(),
        )


def test_execution_boundary_rejects_symlinked_ancestor_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical"
    nested = canonical / "nested"
    nested.mkdir(parents=True, mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(canonical, target_is_directory=True)
    selected = alias / "nested" / "artifacts"
    monkeypatch.setattr(
        execution,
        "_require_canonical_readiness",
        lambda _matrix, _models: pytest.fail("readiness must not run"),
    )

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="artifact-root-policy-invalid",
    ):
        issue_matrix_execution(
            fixtures_root=packaged_cases_root(),
            artifact_root=selected,
            runtime_models=_models(),
        )

    assert not selected.exists()


def test_claude_readiness_checks_every_exact_plan_and_closes_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix, _fixtures = build_matrix(packaged_cases_root())
    calls: list[tuple[str, LayerVariant, str, object | None]] = []
    projections = []
    receipts = []

    class Receipt:
        closed = False

        def close(self) -> None:
            self.closed = True

    class Projection:
        def __init__(self, receipt: object | None) -> None:
            self.receipt = receipt
            self.closed = False

        def close(self) -> None:
            self.closed = True
            if self.receipt is not None:
                self.receipt.close()

    def materialize(_destination: Path) -> Receipt:
        receipt = Receipt()
        receipts.append(receipt)
        return receipt

    def issue(**kwargs) -> Projection:
        calls.append(
            (
                kwargs["case_id"],
                kwargs["variant"],
                kwargs["specialist"],
                kwargs["personal_snapshot_receipt"],
            )
        )
        projection = Projection(kwargs["personal_snapshot_receipt"])
        projections.append(projection)
        return projection

    monkeypatch.setattr(
        "cc.evaluation_fixtures.personal_snapshot.materialize_personal_snapshot",
        materialize,
    )
    monkeypatch.setattr(
        "cc.core.evaluation.content_authority.issue_canonical_claude_content",
        issue,
    )
    monkeypatch.setattr(
        "cc.core.evaluation.content_authority.verify_canonical_content_projection",
        lambda value: isinstance(value, Projection) and not value.closed,
    )

    execution._verify_canonical_claude_content(matrix)

    expected = [item for item in matrix.cells if item.runtime is RuntimeName.CLAUDE]
    assert len(calls) == len(expected) == 14
    assert [item[:3] for item in calls] == [
        (item.case_id, item.variant, item.expected_specialist) for item in expected
    ]
    personal = [item for item in calls if item[1] is LayerVariant.PERSONAL]
    assert len(personal) == 1
    assert personal[0][0:3] == ("eval-07", LayerVariant.PERSONAL, "doc")
    assert personal[0][3] is receipts[0]
    assert all(item[3] is None for item in calls if item is not personal[0])
    assert all(item.closed for item in projections)
    assert all(item.closed for item in receipts)


def test_claude_readiness_preserves_exact_source_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix, _fixtures = build_matrix(packaged_cases_root())
    monkeypatch.setattr(
        "cc.core.evaluation.content_authority.issue_canonical_claude_content",
        lambda **_kwargs: (_ for _ in ()).throw(
            CanonicalContentUnavailable("materialized-lock-mismatch")
        ),
    )

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="canonical-content-materialized-lock-mismatch",
    ):
        execution._verify_canonical_claude_content(matrix)


def test_claude_readiness_converts_unknown_source_failure_to_closed_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix, _fixtures = build_matrix(packaged_cases_root())
    monkeypatch.setattr(
        "cc.core.evaluation.content_authority.issue_canonical_claude_content",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("untrusted implementation detail")
        ),
    )

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="canonical-content-verifier-unavailable",
    ):
        execution._verify_canonical_claude_content(matrix)


def test_personal_materialization_failure_closes_without_escaping_verifier_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix, _fixtures = build_matrix(packaged_cases_root())
    personal = next(
        item
        for item in matrix.cells
        if item.runtime is RuntimeName.CLAUDE and item.variant is LayerVariant.PERSONAL
    )
    selected = SimpleNamespace(cells=(personal,))
    monkeypatch.setattr(
        "cc.evaluation_fixtures.personal_snapshot.materialize_personal_snapshot",
        lambda _path: (_ for _ in ()).throw(ValueError("private source detail")),
    )

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="canonical-content-verifier-unavailable",
    ):
        execution._verify_canonical_claude_content(selected)


def test_personal_cleanup_failure_is_closed_after_every_capability_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix, _fixtures = build_matrix(packaged_cases_root())
    personal = next(
        item
        for item in matrix.cells
        if item.runtime is RuntimeName.CLAUDE and item.variant is LayerVariant.PERSONAL
    )
    selected = SimpleNamespace(cells=(personal,))

    class Temporary:
        def __init__(self, **_kwargs) -> None:
            self.name = str(tmp_path / "temporary")
            Path(self.name).mkdir(mode=0o700)

        def cleanup(self) -> None:
            raise OSError("synthetic cleanup failure")

    class Receipt:
        closes = 0

        def close(self) -> None:
            self.closes += 1

    class Projection:
        closes = 0

        def close(self) -> None:
            self.closes += 1

    receipt = Receipt()
    projection = Projection()
    monkeypatch.setattr(execution.tempfile, "TemporaryDirectory", Temporary)
    monkeypatch.setattr(
        "cc.evaluation_fixtures.personal_snapshot.materialize_personal_snapshot",
        lambda _path: receipt,
    )
    monkeypatch.setattr(
        "cc.core.evaluation.content_authority.issue_canonical_claude_content",
        lambda **_kwargs: projection,
    )
    monkeypatch.setattr(
        "cc.core.evaluation.content_authority.verify_canonical_content_projection",
        lambda value: value is projection,
    )

    with pytest.raises(
        EvaluationExecutionUnavailable,
        match="canonical-content-cleanup-failed",
    ):
        execution._verify_canonical_claude_content(selected)

    assert projection.closes == 1
    assert receipt.closes == 1


@pytest.mark.parametrize(
    ("result", "reason"),
    (
        ((False, "auth-probe-unavailable"), "claude-auth-probe-unavailable"),
        (ValueError("unsafe auth source"), "claude-runtime-not-authenticated"),
        (OSError("staging failed"), "claude-runtime-not-authenticated"),
    ),
)
def test_runtime_auth_source_projection_and_staging_fail_with_stable_reason(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
    reason: str,
) -> None:
    monkeypatch.setattr(
        "cc.core.executables.resolve_executable",
        lambda _runtime: "/private/synthetic-runtime",
    )

    def status(*_args, **_kwargs):
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(
        "cc.core.evaluation.live_runtime.runtime_authentication_status",
        status,
    )

    with pytest.raises(EvaluationExecutionUnavailable, match=reason):
        execution._verify_runtime_authentication()
