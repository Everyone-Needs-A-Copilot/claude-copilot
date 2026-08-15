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
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import (
    PACKAGED_BUNDLE_SHA256,
    PACKAGED_MATRIX_SHA256,
    PACKAGED_PERSONAL_LAYER_SHA256,
    PackagedFixtureUnavailable,
    packaged_cases_root,
)
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


def _signed_layers() -> list[dict[str, object]]:
    rows = []
    for product in ("knowledge", "claude", "codex"):
        for rank, role in enumerate(
            ("foundation", "organization", "department"),
            start=1,
        ):
            layer_id = f"{product}-{role}"
            rows.append(
                {
                    "id": layer_id,
                    "product": product,
                    "role": role,
                    "rank": rank,
                    "source": {"ref": "v1.2.3"},
                    "policy": {"allowed_signers": ["SHA256:SYNTHETIC"]},
                    "_evaluation_proof": {
                        "signature_verified": True,
                        "joined": True,
                        "layer": layer_id,
                        "ref": "v1.2.3",
                        "tree": "1" * 40,
                        "signer": "SHA256:SYNTHETIC",
                        "lease_sha256": "2" * 64,
                        "lock_sha256": "3" * 64,
                        "materialization_sha256": "4" * 64,
                    },
                }
            )
    for product in ("knowledge", "claude", "codex"):
        layer_id = f"{product}-personal"
        ref = "sha256:" + "5" * 64
        rows.append(
            {
                "id": layer_id,
                "product": product,
                "role": "personal",
                "rank": 0,
                "source": {"ref": ref},
                "policy": {"allowed_signers": []},
                "_evaluation_proof": {
                    "joined": True,
                    "layer": layer_id,
                    "ref": ref,
                    "lock_sha256": "6" * 64,
                    "materialization_sha256": "7" * 64,
                },
            }
        )
    return rows


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


def test_readiness_never_mints_canonical_authority_from_candidate_status() -> None:
    document = build_effectiveness_readiness(
        FIXTURES,
        layers_loader=_signed_layers,
        runtime_loader=lambda: (
            [
                {
                    "runtime": "claude",
                    "state": "ready",
                    "executable_sha256": "1" * 64,
                },
                {
                    "runtime": "codex",
                    "state": "ready",
                    "executable_sha256": "2" * 64,
                },
            ],
            [],
        ),
    )

    assert document["state"] == "blocked"
    assert document["candidate_state"] == "satisfied"
    assert document["planned_cells"] == 28
    assert document["live_calls_started"] == 0
    assert document["blockers"] == ["canonical-readiness-verifier-unavailable"]


def test_readiness_reports_unsigned_layer_by_product_and_role() -> None:
    layers = _signed_layers()
    target = next(
        item
        for item in layers
        if item["product"] == "codex" and item["role"] == "organization"
    )
    target["source"] = {"ref": "main"}
    target["policy"] = {"allowed_signers": []}

    document = build_effectiveness_readiness(
        FIXTURES,
        layers_loader=lambda: layers,
        runtime_loader=lambda: ([], []),
    )

    assert "unverified-codex-organization" in document["blockers"]


def test_readiness_rejects_tag_and_signer_without_verified_materialization() -> None:
    layers = _signed_layers()
    target = next(
        item
        for item in layers
        if item["product"] == "codex" and item["role"] == "organization"
    )
    target.pop("_evaluation_proof")

    document = build_effectiveness_readiness(
        FIXTURES,
        layers_loader=lambda: layers,
        runtime_loader=lambda: ([], []),
    )

    assert document["state"] == "blocked"
    assert "unverified-codex-organization" in document["blockers"]


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
