from __future__ import annotations

# Imported pytest fixture names are intentionally reused as test parameters.
# ruff: noqa: F401, F811
import base64
import copy
import hashlib
import json
from dataclasses import replace

import pytest
from cc.core.evaluation.assessment import (
    assessment_manifest_document,
    issue_assessment_manifest,
    load_durable_assessment_manifest,
    persist_assessment_manifest,
    verify_assessment_manifest_identity,
)
from cc.core.evaluation.matrix import EvaluationMatrix, build_matrix
from cc.core.evaluation.models import RunState, RuntimeName
from test_live_portfolio import (
    FIXTURES,
    ExactPortfolioEvidence,
    _unsupported_portfolio_inputs,
    exact_evidence,
)


def test_assessment_manifest_binds_exact_28_terminal_runs_without_private_values(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    _matrix, fixtures = build_matrix(FIXTURES)
    manifest = issue_assessment_manifest(
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=tuple(exact_evidence.runs),
    )
    document = assessment_manifest_document(manifest)

    assert manifest.phase_state == "awaiting-assessment"
    assert len(manifest.cells) == 28
    assert all(item.terminal_state is RunState.COMPLETED for item in manifest.cells)
    assert verify_assessment_manifest_identity(manifest)
    assert not verify_assessment_manifest_identity(copy.copy(manifest))
    assert not verify_assessment_manifest_identity(replace(manifest))
    serialized = str(document)
    for prohibited in (
        "problem_statement",
        "private_rationale",
        "oracle/expected",
        "output_text",
        "score",
        "rank",
        "winner",
    ):
        assert prohibited not in serialized


def test_assessment_manifest_records_unsupported_without_requesting_output(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    runs, _judgments, _comparisons = _unsupported_portfolio_inputs(exact_evidence)
    _matrix, fixtures = build_matrix(FIXTURES)
    manifest = issue_assessment_manifest(
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=runs,
    )
    unsupported = [
        item for item in manifest.cells if item.terminal_state is RunState.UNSUPPORTED
    ]

    assert len(unsupported) == 1
    assert unsupported[0].output_sha256 is None
    assert unsupported[0].controlled_artifact_path is None
    assert unsupported[0].runtime in RuntimeName


def test_assessment_manifest_rejects_missing_duplicate_or_copied_run(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    _matrix, fixtures = build_matrix(FIXTURES)
    with pytest.raises(ValueError, match="coverage"):
        issue_assessment_manifest(
            exact_evidence.matrix,
            fixtures=fixtures,
            runs=tuple(exact_evidence.runs[:-1]),
        )
    with pytest.raises(ValueError, match="lineage"):
        issue_assessment_manifest(
            exact_evidence.matrix,
            fixtures=fixtures,
            runs=(*exact_evidence.runs, exact_evidence.runs[0]),
        )
    copied = [*exact_evidence.runs]
    copied[0] = copy.copy(copied[0])
    with pytest.raises(ValueError, match="invalid"):
        issue_assessment_manifest(
            exact_evidence.matrix,
            fixtures=fixtures,
            runs=tuple(copied),
        )


def test_assessment_bundle_rejects_forged_reordered_packaged_matrix(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    _matrix, fixtures = build_matrix(FIXTURES)
    authentic = persist_assessment_manifest(
        exact_evidence.root,
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=tuple(exact_evidence.runs),
    )
    forged = object.__new__(EvaluationMatrix)
    object.__setattr__(forged, "schema_version", exact_evidence.matrix.schema_version)
    object.__setattr__(forged, "cells", tuple(reversed(exact_evidence.matrix.cells)))
    object.__setattr__(forged, "matrix_sha256", exact_evidence.matrix.matrix_sha256)

    with pytest.raises(ValueError, match="exact packaged matrix"):
        issue_assessment_manifest(
            forged,
            fixtures=fixtures,
            runs=tuple(exact_evidence.runs),
        )
    with pytest.raises(ValueError, match="exact packaged matrix"):
        persist_assessment_manifest(
            exact_evidence.root,
            forged,
            fixtures=fixtures,
            runs=tuple(exact_evidence.runs),
        )
    assert (
        load_durable_assessment_manifest(
            exact_evidence.root,
            authentic.manifest_artifact_sha256,
            forged,
            fixtures=fixtures,
            runs=tuple(exact_evidence.runs),
        )
        is None
    )
    authentic.close()


def test_assessment_manifest_persists_and_freshly_reloads_exact_run_lineages(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    _matrix, fixtures = build_matrix(FIXTURES)
    loaded = persist_assessment_manifest(
        exact_evidence.root,
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=tuple(exact_evidence.runs),
    )

    assert loaded.validate()
    assert loaded.manifest.phase_state == "awaiting-assessment"
    assert len(loaded.manifest.cells) == 28
    artifact = (
        exact_evidence.root
        / "assessment-manifest"
        / f"{loaded.manifest_artifact_sha256}.json"
    )
    assert artifact.is_file()
    assert artifact.stat().st_mode & 0o777 == 0o600
    bundle = (
        exact_evidence.root
        / "assessment-bundle"
        / f"{loaded.bundle_artifact_sha256}.json"
    )
    raw_bundle = bundle.read_bytes()
    bundle_document = json.loads(raw_bundle)
    assert bundle.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(raw_bundle).hexdigest() == loaded.bundle_artifact_sha256
    assert bundle_document["privacy_class"] == "private-evaluation-evidence"
    assert len(bundle_document["run_records"]) == len(exact_evidence.runs)
    retained = bundle_document["retained_artifacts"]
    assert sum(item["artifact_type"] == "runtime-quarantine" for item in retained) == 28
    assert all(
        hashlib.sha256(base64.b64decode(item["content"], validate=True)).hexdigest()
        == item["sha256"]
        for item in retained
    )

    copied = copy.copy(loaded)
    assert not copied.validate()
    copied.close()
    assert loaded.validate()

    reloaded = load_durable_assessment_manifest(
        exact_evidence.root,
        loaded.manifest_artifact_sha256,
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=tuple(exact_evidence.runs),
    )
    assert reloaded is not None
    assert reloaded.manifest is not loaded.manifest
    assert reloaded.manifest.manifest_sha256 == loaded.manifest.manifest_sha256
    assert reloaded.validate()

    loaded.close()
    loaded.close()
    assert not loaded.validate()
    assert reloaded.validate()
    reloaded.close()


@pytest.mark.parametrize("mutate_in_place", (False, True))
def test_assessment_bundle_rejects_mutation_but_survives_audit_manifest_replacement(
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
    mutate_in_place: bool,
) -> None:
    _matrix, fixtures = build_matrix(FIXTURES)
    loaded = persist_assessment_manifest(
        exact_evidence.root,
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=tuple(exact_evidence.runs),
    )
    assert (
        load_durable_assessment_manifest(
            exact_evidence.root,
            "f" * 64,
            exact_evidence.matrix,
            fixtures=fixtures,
            runs=tuple(exact_evidence.runs),
        )
        is None
    )
    artifact = (
        exact_evidence.root
        / "assessment-manifest"
        / f"{loaded.manifest_artifact_sha256}.json"
    )
    replacement = artifact.with_suffix(".replacement")
    replacement.write_bytes(artifact.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(artifact)
    assert loaded.validate()
    bundle = (
        exact_evidence.root
        / "assessment-bundle"
        / f"{loaded.bundle_artifact_sha256}.json"
    )
    original_validate = loaded._bundle_capability.validate
    swapped = False

    def swap_then_validate() -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            if mutate_in_place:
                content = bundle.read_bytes()
                bundle.write_bytes(content[:1] + b"!" + content[2:])
                bundle.chmod(0o600)
            else:
                bundle_replacement = bundle.with_suffix(".replacement")
                bundle_replacement.write_bytes(bundle.read_bytes())
                bundle_replacement.chmod(0o600)
                bundle_replacement.replace(bundle)
        original_validate()

    monkeypatch.setattr(loaded._bundle_capability, "validate", swap_then_validate)
    assert not loaded.validate()
    assert swapped
    loaded.close()
