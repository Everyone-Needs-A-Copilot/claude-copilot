from __future__ import annotations

# Imported pytest fixture names are intentionally reused as test parameters.
# ruff: noqa: F401, F811
import copy
import inspect
import json
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

import cc.core.evaluation.finalize as finalize_module
import pytest
from cc.core.evaluation.assessment import persist_assessment_manifest
from cc.core.evaluation.finalize import (
    AssessorArtifactReference,
    finalization_record_document,
    finalize_effectiveness_evaluation,
    verify_finalization_record_identity,
)
from cc.core.evaluation.matrix import build_matrix
from cc.core.evaluation.schema import canonical_json_bytes
from test_live_judgment import _document, _evidence_vault, _rationale_document
from test_live_portfolio import (
    FIXTURES,
    ExactPortfolioEvidence,
    _synthetic_output,
    exact_evidence,
)


def _copy_private_vault(source: Path, target: Path) -> None:
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.chmod(0o700)
    for artifact_type in (
        "assessor-authorization",
        "assessor-assessment",
        "assessor-private-rationale",
        "assessor-signature",
    ):
        destination = target / artifact_type
        destination.mkdir(mode=0o700, exist_ok=True)
        destination.chmod(0o700)
        for item in (source / artifact_type).iterdir():
            copied = destination / item.name
            shutil.copyfile(item, copied)
            copied.chmod(0o600)


def _signed_assessments(
    evidence: ExactPortfolioEvidence,
    fixtures,
    vault: Path,
    *,
    verdict: str = "demonstrated",
) -> tuple[AssessorArtifactReference, ...]:
    fixture_by_case = {item.fixture.case_id: item for item in fixtures}
    references = []
    for loaded_run in evidence.runs:
        record = loaded_run.record
        fixture = fixture_by_case[record.case_id]
        output = _synthetic_output(record)
        document = _document(record, fixture, output, verdict=verdict)
        rationale = _rationale_document(record, fixture.fixture.required_criteria)
        with _evidence_vault(record, document, rationale) as signed:
            source, authorization_sha256, signature_sha256 = signed
            _copy_private_vault(source, vault)
        references.append(
            AssessorArtifactReference(
                record.run_sha256,
                authorization_sha256,
                signature_sha256,
            )
        )
    return tuple(references)


def _task_copilot_database(
    root: Path,
    *,
    matrix_sha256: str,
    manifest_sha256: str,
    bundle_sha256: str,
    exact_markers: bool = True,
    qa_verdict: str = "APPROVED",
    external: bool = False,
) -> tuple[Path, int]:
    directory = root / "task-copilot"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    database = (directory / "tasks.db").resolve()
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE work_products ("
            "id INTEGER PRIMARY KEY, task_id INTEGER, type TEXT NOT NULL, "
            "title TEXT NOT NULL, content TEXT, file_path TEXT, agent TEXT, "
            "guard TEXT, created_at TEXT NOT NULL)"
        )
        manifest_marker = manifest_sha256 if exact_markers else "f" * 64
        content = "\n".join(
            (
                "ARTIFACT: test-run phase-two-finalization",
                f"VERDICT: {qa_verdict}",
                f"MATRIX_SHA256: {matrix_sha256}",
                f"ASSESSMENT_MANIFEST_SHA256: {manifest_marker}",
                f"ASSESSMENT_BUNDLE_SHA256: {bundle_sha256}",
            )
        )
        stored_content = content
        file_path = None
        if external:
            work_product_directory = directory / "wp"
            work_product_directory.mkdir(mode=0o700)
            work_product_directory.chmod(0o700)
            work_product = work_product_directory / "1104.md"
            work_product.write_text(content, encoding="utf-8")
            work_product.chmod(0o600)
            stored_content = None
            file_path = str(work_product)
        connection.execute(
            "INSERT INTO work_products "
            "(id, task_id, type, title, content, file_path, agent, guard, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1104,
                285,
                "test",
                "Independent phase-two evaluation assessment",
                stored_content,
                file_path,
                "independent-qa",
                "clean",
                "2026-08-15T00:00:00Z",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    database.chmod(0o600)
    return database, 1104


def _inputs(
    exact_evidence: ExactPortfolioEvidence,
    *,
    exact_work_product: bool = True,
    verdict: str = "demonstrated",
    qa_verdict: str = "APPROVED",
    external_work_product: bool = False,
):
    _matrix, fixtures = build_matrix(FIXTURES)
    assessment = persist_assessment_manifest(
        exact_evidence.root,
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=tuple(exact_evidence.runs),
    )
    vault = exact_evidence.root / "signed-assessor-vault"
    references = _signed_assessments(
        exact_evidence,
        fixtures,
        vault,
        verdict=verdict,
    )
    database, work_product_id = _task_copilot_database(
        exact_evidence.root,
        matrix_sha256=exact_evidence.matrix.matrix_sha256,
        manifest_sha256=assessment.manifest_artifact_sha256,
        bundle_sha256=assessment.bundle_artifact_sha256,
        exact_markers=exact_work_product,
        qa_verdict=qa_verdict,
        external=external_work_product,
    )
    return assessment, fixtures, vault, references, database, work_product_id


def test_finalize_consumes_only_signed_assessments_and_persists_rejected_report(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence
    )
    with patch(
        "cc.core.evaluation.judgment._verify_assessor_signature",
        return_value=True,
    ):
        loaded = finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )

    assert loaded.validate()
    assert loaded.execution.report.state == "completed"
    assert loaded.execution.report.acceptance_state == "rejected"
    assert loaded.record.acceptance_state == "rejected"
    assert loaded.record.completed_assessments == 28
    assert loaded.record.unsupported_dispositions == 0
    assert len(loaded.judgments) == 28
    assert len(loaded.comparisons) == 14
    assert loaded.record.blockers == loaded.execution.report.blockers
    assert verify_finalization_record_identity(loaded.record)
    assert not verify_finalization_record_identity(copy.copy(loaded.record))
    document = finalization_record_document(loaded.record)
    serialized = json.dumps(document, sort_keys=True)
    for prohibited in (
        "output_text",
        "private_rationale",
        "problem_statement",
        "authorization_sha256",
        "signature_sha256",
    ):
        assert prohibited not in serialized
    bundle = (
        exact_evidence.root
        / "evaluation-finalization-bundle"
        / f"{loaded.bundle_artifact_sha256}.json"
    )
    stored = json.loads(bundle.read_bytes())
    assert stored["finalization_record"] == document
    assert stored["execution_bundle_sha256"] == (
        loaded.execution.bundle_artifact_sha256
    )
    assert canonical_json_bytes(stored) == bundle.read_bytes()

    copied = copy.copy(loaded)
    assert not copied.validate()
    copied.close()
    assert loaded.validate()
    replacement = bundle.with_suffix(".replacement")
    replacement.write_bytes(bundle.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(bundle)
    assert not loaded.validate()
    loaded.close()
    loaded.close()
    assert not loaded.validate()
    assessment.close()


def test_finalize_rejects_missing_signed_reference_before_writes(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence
    )
    before = set((exact_evidence.root / "criterion-judgment").iterdir())
    with pytest.raises(ValueError, match="reference coverage"):
        finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references[:-1],
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    assert set((exact_evidence.root / "criterion-judgment").iterdir()) == before
    assessment.close()


def test_finalize_rejects_wrong_task_copilot_binding_and_exposes_no_raw_verdict_api(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence,
        exact_work_product=False,
    )
    before = set((exact_evidence.root / "criterion-judgment").iterdir())
    with pytest.raises(ValueError, match="exact phase-two evidence"):
        finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    assert set((exact_evidence.root / "criterion-judgment").iterdir()) == before
    parameters = inspect.signature(finalize_effectiveness_evaluation).parameters
    assert not {
        "judgments",
        "comparisons",
        "verdict",
        "assessment_document",
        "rationale",
    }.intersection(parameters)
    assessment.close()


def test_finalize_rejects_rejected_qa_work_product_before_judgment_writes(
    exact_evidence: ExactPortfolioEvidence,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence,
        qa_verdict="REJECTED",
    )
    before = set((exact_evidence.root / "criterion-judgment").iterdir())
    with pytest.raises(ValueError, match="QA rejected"):
        finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    assert set((exact_evidence.root / "criterion-judgment").iterdir()) == before
    assessment.close()


@pytest.mark.parametrize("target", ("database", "root", "work-product", "wp-root"))
def test_finalize_rejects_nonprivate_task_copilot_snapshot(
    exact_evidence: ExactPortfolioEvidence,
    target: str,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence,
        external_work_product=True,
    )
    selected = {
        "database": database,
        "root": database.parent,
        "work-product": database.parent / "wp" / f"{work_product_id}.md",
        "wp-root": database.parent / "wp",
    }[target]
    selected.chmod(0o644 if selected.is_file() else 0o755)
    before = set((exact_evidence.root / "criterion-judgment").iterdir())
    with pytest.raises(ValueError, match="owner-only"):
        finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    assert set((exact_evidence.root / "criterion-judgment").iterdir()) == before
    assessment.close()


def test_finalize_rejects_task_copilot_root_swap_between_db_and_external_wp(
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence,
        external_work_product=True,
    )
    original = finalize_module._work_product_content
    swapped = False

    def replace_root(snapshot, row):
        nonlocal swapped
        displaced = database.parent.with_name("task-copilot-displaced")
        database.parent.rename(displaced)
        database.parent.mkdir(mode=0o700)
        database.parent.chmod(0o700)
        replacement_wp = database.parent / "wp"
        replacement_wp.mkdir(mode=0o700)
        replacement_wp.chmod(0o700)
        replacement = replacement_wp / f"{work_product_id}.md"
        replacement.write_text(
            (displaced / "wp" / replacement.name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        replacement.chmod(0o600)
        swapped = True
        return original(snapshot, row)

    monkeypatch.setattr(finalize_module, "_work_product_content", replace_root)
    before = set((exact_evidence.root / "criterion-judgment").iterdir())
    with pytest.raises(ValueError, match="changed during verification"):
        finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    assert swapped
    assert set((exact_evidence.root / "criterion-judgment").iterdir()) == before
    assessment.close()


@pytest.mark.parametrize("suffix", ("-wal", "-shm"))
def test_finalize_rejects_task_copilot_database_sidecars_before_writes(
    exact_evidence: ExactPortfolioEvidence,
    suffix: str,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence
    )
    sidecar = Path(f"{database}{suffix}")
    sidecar.write_bytes(b"synthetic sidecar")
    sidecar.chmod(0o600)
    before = set((exact_evidence.root / "criterion-judgment").iterdir())
    with pytest.raises(ValueError, match="snapshot is invalid"):
        finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    assert set((exact_evidence.root / "criterion-judgment").iterdir()) == before
    assessment.close()


def test_finalize_rechecks_task_copilot_sidecar_absence_after_wp_read(
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence,
        external_work_product=True,
    )
    original = finalize_module._work_product_content

    def add_sidecar(snapshot, row):
        result = original(snapshot, row)
        sidecar = database.with_name("tasks.db-wal")
        sidecar.write_bytes(b"synthetic late sidecar")
        sidecar.chmod(0o600)
        return result

    monkeypatch.setattr(finalize_module, "_work_product_content", add_sidecar)
    before = set((exact_evidence.root / "criterion-judgment").iterdir())
    with pytest.raises(ValueError, match="changed during verification"):
        finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    assert set((exact_evidence.root / "criterion-judgment").iterdir()) == before
    assessment.close()


def test_loaded_finalization_revalidates_bundle_after_nested_identity_checks(
    exact_evidence: ExactPortfolioEvidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment, fixtures, vault, references, database, work_product_id = _inputs(
        exact_evidence
    )
    with patch(
        "cc.core.evaluation.judgment._verify_assessor_signature",
        return_value=True,
    ):
        loaded = finalize_effectiveness_evaluation(
            root=exact_evidence.root,
            matrix=exact_evidence.matrix,
            fixtures=fixtures,
            assessment=assessment,
            evidence_vault=vault,
            assessor_artifacts=references,
            task_copilot_database=database,
            task_copilot_work_product_id=work_product_id,
        )
    bundle = (
        exact_evidence.root
        / "evaluation-finalization-bundle"
        / f"{loaded.bundle_artifact_sha256}.json"
    )
    original = finalize_module.verify_execution_report_identity
    swapped = False

    def replace_after_first_bundle_check(value):
        nonlocal swapped
        replacement = bundle.with_suffix(".late-replacement")
        replacement.write_bytes(bundle.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(bundle)
        swapped = True
        return original(value)

    monkeypatch.setattr(
        finalize_module,
        "verify_execution_report_identity",
        replace_after_first_bundle_check,
    )
    assert not loaded.validate()
    assert swapped
    loaded.close()
    assessment.close()
