from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import cc.evaluation_fixtures as evaluation_fixtures
import pytest
from cc.commands import effectiveness
from cc.commands.effectiveness import build_effectiveness_readiness
from cc.commands.eval import eval_app
from cc.core.evaluation import readiness as readiness_module
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import (
    PACKAGED_BUNDLE_SHA256,
    PACKAGED_MATRIX_SHA256,
    PACKAGED_PERSONAL_LAYER_SHA256,
    PackagedFixtureUnavailable,
    packaged_cases_root,
)
from test_readiness import _install_ready_probes
from typer.testing import CliRunner

FIXTURES = Path(__file__).parent / "fixtures" / "cases"


def _execution_report(
    *,
    acceptance_state: str = "accepted",
    blockers: list[str] | None = None,
) -> dict[str, object]:
    blocker_values = [] if blockers is None else blockers
    identity: dict[str, object] = {
        "schema_version": "1.0",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "state": "completed",
        "acceptance_state": acceptance_state,
        "initial_cells_started": 28,
        "total_attempts_started": 28,
        "portfolio_sha256": "1" * 64,
        "portfolio_artifact_sha256": "2" * 64,
        "blockers": blocker_values,
    }
    return {**identity, "execution_sha256": canonical_sha256(identity)}


def _phase_one_report() -> dict[str, object]:
    identity: dict[str, object] = {
        "schema_version": "task285-phase-one-execution-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "state": "awaiting-assessment",
        "acceptance_state": "not-evaluated",
        "initial_cells_started": 28,
        "total_attempts_started": 28,
        "live_calls_started": 14,
        "completed_cells": 14,
        "unsupported_cells": 14,
        "assessment_manifest_sha256": "1" * 64,
        "assessment_bundle_sha256": "2" * 64,
        "terminal_run_sha256": [f"{index:064x}" for index in range(1, 29)],
        "blockers": [],
    }
    return {**identity, "execution_sha256": canonical_sha256(identity)}


def test_matrix_cli_emits_exact_28_cells_without_live_calls() -> None:
    result = CliRunner().invoke(
        eval_app,
        [
            "effectiveness",
            "matrix",
            "--fixtures-root",
            str(FIXTURES),
            "--json",
        ],
    )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["planned_cells"] == 28
    assert document["live_calls_started"] == 0
    assert len(document["cells"]) == 28


def test_matrix_cli_defaults_to_installed_immutable_fixture_bundle() -> None:
    result = CliRunner().invoke(
        eval_app,
        ["effectiveness", "matrix", "--json"],
    )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["matrix_sha256"] == PACKAGED_MATRIX_SHA256
    assert document["fixture_bundle_sha256"] == PACKAGED_BUNDLE_SHA256
    assert document["personal_layer_sha256"] == PACKAGED_PERSONAL_LAYER_SHA256
    assert document["planned_cells"] == 28
    assert document["live_calls_started"] == 0


def test_packaged_fixture_bundle_exactly_matches_preregistered_source() -> None:
    packaged = packaged_cases_root()
    packaged_files = {
        item.relative_to(packaged).as_posix(): item.read_bytes()
        for item in packaged.rglob("*")
        if item.is_file()
    }
    source_files = {
        item.relative_to(FIXTURES).as_posix(): item.read_bytes()
        for item in FIXTURES.rglob("*")
        if item.is_file()
    }

    assert packaged_files == source_files
    assert len(packaged_files) == 31
    assert evaluation_fixtures._bundle_sha256(packaged) == PACKAGED_BUNDLE_SHA256


@pytest.mark.parametrize("extra_kind", ["file", "directory", "symlink"])
def test_packaged_fixture_bundle_rejects_unregistered_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_kind: str,
) -> None:
    source_package = Path(evaluation_fixtures.__file__).parent
    copied_package = tmp_path / "evaluation_fixtures"
    shutil.copytree(source_package, copied_package, symlinks=True)
    cases = copied_package / "cases"
    extra = cases / "unregistered"
    if extra_kind == "file":
        extra.write_text("unregistered")
    elif extra_kind == "directory":
        extra.mkdir()
    else:
        extra.symlink_to("eval-01")
    monkeypatch.setattr(
        evaluation_fixtures,
        "__file__",
        str(copied_package / "__init__.py"),
    )

    with pytest.raises(
        PackagedFixtureUnavailable,
        match="differs from preregistration|non-file entry",
    ):
        evaluation_fixtures.packaged_cases_root()


def test_wheel_metadata_includes_fixture_tree_with_its_parent_package() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"

    assert 'packages = ["src/cc"]' in pyproject.read_text()
    assert packaged_cases_root().is_relative_to(pyproject.parent / "src" / "cc")


def test_readiness_returns_exact_sealed_report_without_candidate_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_ready_probes(monkeypatch)

    document = build_effectiveness_readiness()

    assert document["state"] == "ready"
    assert document["matrix_sha256"] == PACKAGED_MATRIX_SHA256
    assert len(document["cells"]) == len(calls) == 28
    assert [item["runtime"] for item in document["runtimes"]] == [
        "claude",
        "codex",
    ]
    assert document["live_calls_started"] == 0
    assert document["artifacts_written"] == 0
    assert document["readiness_sha256"] == canonical_sha256(
        {key: value for key, value in document.items() if key != "readiness_sha256"}
    )
    assert "candidate_state" not in document
    assert "layers" not in document


def test_readiness_nonpackaged_root_returns_nonauthorizing_blocked_envelope() -> None:
    document = build_effectiveness_readiness(FIXTURES)

    assert document["schema_version"] == ("task285-canonical-readiness-unavailable-v1")
    assert document["state"] == "blocked"
    assert document["matrix_sha256"] == PACKAGED_MATRIX_SHA256
    assert document["cells"] == []
    assert document["runtimes"] == []
    assert document["blockers"] == ["preregistered-matrix-unavailable"]
    assert document["readiness_sha256"] is None
    assert document["live_calls_started"] == 0
    assert document["artifacts_written"] == 0


def test_readiness_cli_surfaces_exact_canonical_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_ready_probes(monkeypatch)
    ready_content = readiness_module._probe_content_plan

    def content(plan):
        if plan.case_id == "eval-01":
            return None, None, "canonical-content-materialized-lock-mismatch"
        return ready_content(plan)

    monkeypatch.setattr(readiness_module, "_probe_content_plan", content)

    result = CliRunner().invoke(
        eval_app,
        ["effectiveness", "readiness", "--json"],
    )

    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["state"] == "blocked"
    assert document["blockers"] == ["canonical-content-materialized-lock-mismatch"]
    assert len(document["cells"]) == 28
    assert len(document["runtimes"]) == 2
    assert document["live_calls_started"] == 0
    assert document["artifacts_written"] == 0


def test_run_blocks_before_artifact_creation_when_issuer_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "must-not-exist"
    monkeypatch.setattr(effectiveness, "_execution_boundary", lambda: None)

    result = CliRunner().invoke(
        eval_app,
        [
            "effectiveness",
            "run",
            "--artifact-root",
            str(artifact_root),
            "--claude-model",
            "claude-exact-model",
            "--codex-model",
            "codex-exact-model",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert not artifact_root.exists()
    document = json.loads(result.stdout)
    assert document["blockers"] == ["canonical-execution-issuer-unavailable"]
    assert document["acceptance_state"] == "not-evaluated"
    assert document["initial_cells_started"] == 0
    assert document["matrix_sha256"] == PACKAGED_MATRIX_SHA256
    assert document["portfolio_sha256"] is None
    assert document["portfolio_artifact_sha256"] is None
    assert document["state"] == "blocked"
    assert document["total_attempts_started"] == 0
    assert (
        effectiveness._validated_execution_report(
            document,
            matrix_sha256=PACKAGED_MATRIX_SHA256,
        )
        == document
    )


def test_run_passes_only_exact_operator_inputs_to_production_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "private-artifacts"
    observed: dict[str, Any] = {}

    class Unavailable(Exception):
        reason = "synthetic-unavailable"

    def issuer(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return _execution_report()

    monkeypatch.setattr(
        effectiveness,
        "_execution_boundary",
        lambda: (issuer, Unavailable),
    )

    result = CliRunner().invoke(
        eval_app,
        [
            "effectiveness",
            "run",
            "--artifact-root",
            str(artifact_root),
            "--claude-model",
            "claude-exact-model",
            "--codex-model",
            "codex-exact-model",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert observed == {
        "fixtures_root": packaged_cases_root(),
        "artifact_root": artifact_root,
        "runtime_models": {
            "claude": "claude-exact-model",
            "codex": "codex-exact-model",
        },
    }
    assert json.loads(result.stdout) == _execution_report()


def test_run_exposes_phase_one_as_awaiting_assessment_not_final_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Unavailable(Exception):
        reason = "synthetic-unavailable"

    report = _phase_one_report()
    monkeypatch.setattr(
        effectiveness,
        "_execution_boundary",
        lambda: (lambda **_kwargs: report, Unavailable),
    )

    result = CliRunner().invoke(
        eval_app,
        [
            "effectiveness",
            "run",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--claude-model",
            "claude-exact-model",
            "--codex-model",
            "codex-exact-model",
            "--json",
        ],
    )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document == report
    assert document["state"] == "awaiting-assessment"
    assert document["acceptance_state"] == "not-evaluated"
    assert "portfolio_sha256" not in document


def test_run_returns_success_when_completed_portfolio_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Unavailable(Exception):
        reason = "synthetic-unavailable"

    report = _execution_report(
        acceptance_state="rejected",
        blockers=["runtime-parity-unsupported"],
    )
    monkeypatch.setattr(
        effectiveness,
        "_execution_boundary",
        lambda: (lambda **_kwargs: report, Unavailable),
    )

    result = CliRunner().invoke(
        eval_app,
        [
            "effectiveness",
            "run",
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--claude-model",
            "claude-exact-model",
            "--codex-model",
            "codex-exact-model",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == report


def test_run_surfaces_stable_production_unavailability_without_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class Unavailable(Exception):
        def __init__(self, reason: str) -> None:
            self.reason = reason

    def issuer(**_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise Unavailable("signed-source-receipt-unavailable")

    monkeypatch.setattr(
        effectiveness,
        "_execution_boundary",
        lambda: (issuer, Unavailable),
    )

    result = CliRunner().invoke(
        eval_app,
        [
            "effectiveness",
            "run",
            "--artifact-root",
            str(tmp_path / "unused"),
            "--claude-model",
            "claude-exact-model",
            "--codex-model",
            "codex-exact-model",
            "--json",
        ],
    )

    assert result.exit_code == 2
    assert calls == 1
    document = json.loads(result.stdout)
    assert document["blockers"] == ["signed-source-receipt-unavailable"]
    assert document["initial_cells_started"] == 0
    assert document["total_attempts_started"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("matrix_sha256", "f" * 64),
        ("initial_cells_started", True),
        ("total_attempts_started", 27),
        ("blockers", ["z-blocker", "a-blocker"]),
        ("portfolio_artifact_sha256", None),
    ],
)
def test_run_rejects_malformed_production_execution_reports(
    field: str,
    value: object,
) -> None:
    report = _execution_report()
    report[field] = value

    with pytest.raises(ValueError, match="failed validation"):
        effectiveness._validated_execution_report(
            report,
            matrix_sha256=PACKAGED_MATRIX_SHA256,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acceptance_state", "accepted"),
        ("live_calls_started", 15),
        ("completed_cells", True),
        ("unsupported_cells", 13),
        ("blockers", ["not-assessed"]),
        ("terminal_run_sha256", ["1" * 64] * 28),
        ("assessment_bundle_sha256", "f" * 63),
    ],
)
def test_run_rejects_substituted_phase_one_handoffs(
    field: str,
    value: object,
) -> None:
    report = _phase_one_report()
    report[field] = value
    identity = {key: item for key, item in report.items() if key != "execution_sha256"}
    report["execution_sha256"] = canonical_sha256(identity)

    with pytest.raises(ValueError, match="Phase-one execution report"):
        effectiveness._validated_execution_report(
            report,
            matrix_sha256=PACKAGED_MATRIX_SHA256,
        )
