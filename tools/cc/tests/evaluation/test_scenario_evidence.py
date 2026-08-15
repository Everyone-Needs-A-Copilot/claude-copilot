from __future__ import annotations

# Imported pytest fixture names are intentionally reused as test parameters.
# ruff: noqa: F401, F811
import copy
import hashlib
import inspect
import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import cc.core.evaluation.codex_isolation as codex_isolation_module
import cc.core.evaluation.scenario_evidence as scenario_evidence_module
import pytest
from cc.core.ecosystem.policy import FOUNDATION_SSH_SIGNING_KEYS
from cc.core.evaluation.assessment import (
    LoadedDurableAssessmentManifestEvidence,
    persist_assessment_manifest,
)
from cc.core.evaluation.matrix import build_matrix
from cc.core.evaluation.scenario_evidence import (
    ScenarioEvidenceUnavailable,
    load_s04_continuity_bundle,
    load_s05_update_bundle,
    prepare_s04_publisher_claim,
    prepare_s05_publisher_claim,
    retain_s04_scenario_inputs,
    retain_s05_scenario_inputs,
    s04_continuity_evidence_document,
    s05_update_evidence_document,
    verify_s04_continuity_evidence,
    verify_s04_scenario_inputs,
    verify_s05_scenario_inputs,
    verify_s05_update_evidence,
    write_s04_continuity_bundle,
    write_s05_update_bundle,
)
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256
from test_live_portfolio import FIXTURES, ExactPortfolioEvidence, exact_evidence

_SIGNER = "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
_S04_NAMESPACE = "copilot-scenario-s04-v1"
_S05_NAMESPACE = "copilot-scenario-s05-v1"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _private_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _write_json(path: Path, value: object) -> Path:
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o600)
    return path.resolve()


def _write_bytes(path: Path, value: bytes) -> Path:
    path.write_bytes(value)
    path.chmod(0o600)
    return path.resolve()


@pytest.fixture
def publisher_key(tmp_path: Path) -> tuple[Path, str]:
    key = tmp_path / "publisher-key"
    subprocess.run(
        ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    public_key = " ".join(key.with_suffix(".pub").read_text().split()[:2])
    return key.resolve(), public_key


@pytest.fixture
def assessment(
    exact_evidence: ExactPortfolioEvidence,
) -> Iterator[LoadedDurableAssessmentManifestEvidence]:
    _matrix, fixtures = build_matrix(FIXTURES)
    loaded = persist_assessment_manifest(
        exact_evidence.root,
        exact_evidence.matrix,
        fixtures=fixtures,
        runs=tuple(exact_evidence.runs),
    )
    yield loaded
    loaded.close()


@contextmanager
def _publisher(public_key: str) -> Iterator[None]:
    with patch.dict(FOUNDATION_SSH_SIGNING_KEYS, {_SIGNER.upper(): public_key}):
        yield


def _sign(key: Path, claim: Path, namespace: str) -> Path:
    signature = Path(f"{claim}.sig")
    if signature.exists():
        signature.unlink()
    subprocess.run(
        [
            "/usr/bin/ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(key),
            "-n",
            namespace,
            str(claim),
        ],
        check=True,
        capture_output=True,
    )
    signature.chmod(0o600)
    return signature.resolve()


def _artifact_root_sha256(path: Path) -> str:
    opened = path.stat()
    return canonical_sha256(
        {
            "schema_version": "task285-artifact-root-identity-v1",
            "path_sha256": hashlib.sha256(str(path.resolve()).encode()).hexdigest(),
            "device": opened.st_dev,
            "inode": opened.st_ino,
            "mode": opened.st_mode & 0o7777,
            "owner": opened.st_uid,
        }
    )


def _s04_source_files(
    tmp_path: Path,
    assessment: LoadedDurableAssessmentManifestEvidence,
    publisher_key: tuple[Path, str],
) -> dict[str, object]:
    source = _private_root(tmp_path, "s04-source")
    artifact_root = _private_root(tmp_path, "s04-artifacts").resolve()
    artifact_sha256 = _artifact_root_sha256(artifact_root)
    pre_process = {
        "process_sha256": _sha("pre-process"),
        "session_sha256": _sha("pre-session"),
    }
    resumed_process = {
        "process_sha256": _sha("resumed-process"),
        "session_sha256": _sha("resumed-session"),
    }
    work_products = [
        {"id": 1, "type": "handoff", "artifact_sha256": _sha("handoff")},
        {"id": 2, "type": "implementation", "artifact_sha256": _sha("implementation")},
    ]
    capsule = _sha("pause-capsule")
    pre_document = {
        "schema_version": "task285-s04-tc-export-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "task_state": {
            "task_id": 285,
            "status": "in_progress",
            "revision": 1,
            "state_commitment_sha256": _sha("pre-task-state"),
        },
        "work_products": work_products,
        "process_identity": pre_process,
        "artifact_root_sha256": artifact_sha256,
        "pause_capsule_sha256": capsule,
        "continuation": None,
    }
    resumed_document = {
        "schema_version": "task285-s04-tc-export-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "task_state": {
            "task_id": 285,
            "status": "in_progress",
            "revision": 2,
            "state_commitment_sha256": _sha("resumed-task-state"),
        },
        "work_products": work_products,
        "process_identity": resumed_process,
        "artifact_root_sha256": artifact_sha256,
        "pause_capsule_sha256": capsule,
        "continuation": {
            "pause_capsule_sha256": capsule,
            "pre_pause_process_sha256": canonical_sha256(pre_process),
            "resumed_process_sha256": canonical_sha256(resumed_process),
            "artifact_root_sha256": artifact_sha256,
            "outcome": "continued",
            "resume_reason": "fresh-process-state-reloaded",
        },
    }
    pre = _write_json(source / "pre-pause.json", pre_document)
    resumed = _write_json(source / "resumed.json", resumed_document)
    claim = source / "claim.json"
    claim.write_bytes(
        prepare_s04_publisher_claim(
            pre_pause_tc_export=pre,
            resumed_tc_export=resumed,
            artifact_root=artifact_root,
            assessment=assessment,
        )
    )
    claim.chmod(0o600)
    signature = _sign(publisher_key[0], claim, _S04_NAMESPACE)
    return {
        "pre_pause_tc_export": pre,
        "resumed_tc_export": resumed,
        "artifact_root": artifact_root,
        "assessment": assessment,
        "publisher_claim": claim.resolve(),
        "publisher_signature": signature,
        "pre_document": pre_document,
        "resumed_document": resumed_document,
    }


def _retain_s04(files: dict[str, object], public_key: str):
    with _publisher(public_key):
        return retain_s04_scenario_inputs(
            **{
                key: value
                for key, value in files.items()
                if key not in {"pre_document", "resumed_document"}
            }
        )


def _project_tree_sha256(tree: list[dict[str, str]]) -> str:
    return canonical_sha256(tree)


def _receipt(kind: str, tree_sha256: str, ref: str) -> dict[str, object]:
    return {
        "schema_version": "task285-s05-immutable-receipt-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "receipt_kind": kind,
        "immutable_ref": ref,
        "tree_sha256": tree_sha256,
        "receipt_revision": 1,
    }


def _s05_source_files(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> dict[str, object]:
    source = _private_root(tmp_path, "s05-source")
    human = _sha("preserved-human-work")
    artifact_raw = b"synthetic resumed artifact"
    artifact_sha256 = hashlib.sha256(artifact_raw).hexdigest()
    before_tree = [
        {
            "path": "human/notes.md",
            "blob_sha256": human,
            "classification": "human-work",
        },
        {
            "path": "shared/component.json",
            "blob_sha256": _sha("component-before"),
            "classification": "shared-component",
        },
    ]
    after_tree = [
        {
            "path": "human/notes.md",
            "blob_sha256": human,
            "classification": "human-work",
        },
        {
            "path": "results/resumed.txt",
            "blob_sha256": artifact_sha256,
            "classification": "resumed-artifact",
        },
        {
            "path": "shared/component.json",
            "blob_sha256": _sha("component-after"),
            "classification": "shared-component",
        },
    ]
    before_tree_sha256 = _project_tree_sha256(before_tree)
    after_tree_sha256 = _project_tree_sha256(after_tree)
    before = _write_json(
        source / "before-project.json",
        {
            "schema_version": "task285-s05-project-export-v1",
            "matrix_sha256": PACKAGED_MATRIX_SHA256,
            "project_identity_sha256": _sha("project"),
            "tree": before_tree,
        },
    )
    after = _write_json(
        source / "after-project.json",
        {
            "schema_version": "task285-s05-project-export-v1",
            "matrix_sha256": PACKAGED_MATRIX_SHA256,
            "project_identity_sha256": _sha("project"),
            "tree": after_tree,
        },
    )
    before_source = _write_json(
        source / "before-source.json",
        _receipt("source", before_tree_sha256, "refs/tags/component-v1"),
    )
    after_source = _write_json(
        source / "after-source.json",
        _receipt("source", after_tree_sha256, "refs/tags/component-v2"),
    )
    before_content = _write_json(
        source / "before-content.json",
        _receipt("content", before_tree_sha256, "refs/tags/component-v1"),
    )
    after_content = _write_json(
        source / "after-content.json",
        _receipt("content", after_tree_sha256, "refs/tags/component-v2"),
    )
    artifact = _write_bytes(source / "resumed-artifact.txt", artifact_raw)
    rollback_ref = "refs/tags/component-v1"
    rollback = _write_json(
        source / "rollback.json",
        {
            "schema_version": "task285-s05-rollback-evidence-v1",
            "matrix_sha256": PACKAGED_MATRIX_SHA256,
            "rollback_ref": rollback_ref,
            "before_tree_sha256": before_tree_sha256,
            "after_tree_sha256": after_tree_sha256,
            "rollback_state": "ready",
        },
    )
    ledger_document = {
        "schema_version": "task285-s05-update-ledger-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "human_work_paths": ["human/notes.md"],
        "shared_component_paths": ["shared/component.json"],
        "resumed_artifact_path": "results/resumed.txt",
        "before_source_receipt_sha256": hashlib.sha256(
            before_source.read_bytes()
        ).hexdigest(),
        "after_source_receipt_sha256": hashlib.sha256(
            after_source.read_bytes()
        ).hexdigest(),
        "before_content_receipt_sha256": hashlib.sha256(
            before_content.read_bytes()
        ).hexdigest(),
        "after_content_receipt_sha256": hashlib.sha256(
            after_content.read_bytes()
        ).hexdigest(),
        "resumed_artifact_sha256": artifact_sha256,
        "rollback_evidence_sha256": hashlib.sha256(rollback.read_bytes()).hexdigest(),
        "rollback_ref": rollback_ref,
        "application_dependency": "none",
        "execution_surface": "cli-only",
        "update_outcome": "applied-and-human-work-preserved",
    }
    ledger = _write_json(source / "ledger.json", ledger_document)
    parameters = {
        "before_project_export": before,
        "after_project_export": after,
        "update_ledger": ledger,
        "before_source_receipt": before_source,
        "after_source_receipt": after_source,
        "before_content_receipt": before_content,
        "after_content_receipt": after_content,
        "resumed_artifact": artifact,
        "rollback_evidence": rollback,
    }
    claim = source / "claim.json"
    claim.write_bytes(prepare_s05_publisher_claim(**parameters))
    claim.chmod(0o600)
    signature = _sign(publisher_key[0], claim, _S05_NAMESPACE)
    return {
        **parameters,
        "publisher_claim": claim.resolve(),
        "publisher_signature": signature,
        "before_document": json.loads(before.read_bytes()),
        "after_document": json.loads(after.read_bytes()),
        "ledger_document": ledger_document,
    }


def _retain_s05(files: dict[str, object], public_key: str):
    with _publisher(public_key):
        return retain_s05_scenario_inputs(
            **{
                key: value
                for key, value in files.items()
                if key not in {"before_document", "after_document", "ledger_document"}
            }
        )


def _only_bundle(root: Path) -> Path:
    entries = list(root.iterdir())
    assert len(entries) == 1
    return entries[0]


def test_s04_signed_authentic_bundle_round_trips_without_private_values(
    tmp_path: Path,
    assessment: LoadedDurableAssessmentManifestEvidence,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s04_source_files(tmp_path, assessment, publisher_key)
    inputs = _retain_s04(files, publisher_key[1])
    root = _private_root(tmp_path, "s04-output")
    evidence = write_s04_continuity_bundle(root, inputs=inputs)
    document = s04_continuity_evidence_document(evidence)

    assert inputs.validate()
    assert evidence.validate()
    assert verify_s04_continuity_evidence(evidence)
    assert document["matrix_sha256"] == PACKAGED_MATRIX_SHA256
    assert document["publisher_signer"] == _SIGNER
    assert document["signature_namespace"] == _S04_NAMESPACE
    assert (
        document["pre_pause_work_products_sha256"]
        == document["resumed_work_products_sha256"]
    )
    assert document["artifact_root_sha256"] == document["resumed_artifact_root_sha256"]
    assert _only_bundle(root).stat().st_mode & 0o777 == 0o600
    serialized = json.dumps(document, sort_keys=True)
    assert "implementation" not in serialized
    assert "private output" not in serialized

    copied = copy.copy(evidence)
    copied.close()
    assert evidence.validate()
    assert not verify_s04_continuity_evidence(copied)
    assert not verify_s04_continuity_evidence(replace(evidence))
    evidence.close()
    assert not evidence.validate()

    fresh_inputs = _retain_s04(files, publisher_key[1])
    reloaded = load_s04_continuity_bundle(
        root,
        document["bundle_sha256"],
        inputs=fresh_inputs,
    )
    assert reloaded is not None
    assert reloaded.evidence_sha256 == document["evidence_sha256"]
    reloaded.close()


def test_s05_signed_authentic_bundle_proves_update_preservation_and_no_app(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    inputs = _retain_s05(files, publisher_key[1])
    root = _private_root(tmp_path, "s05-output")
    evidence = write_s05_update_bundle(root, inputs=inputs)
    document = s05_update_evidence_document(evidence)

    assert evidence.validate()
    assert verify_s05_update_evidence(evidence)
    assert (
        document["before_project_tree_sha256"] != document["after_project_tree_sha256"]
    )
    assert document["human_work_before_sha256"] == document["human_work_after_sha256"]
    assert (
        document["before_source_receipt_sha256"]
        != document["after_source_receipt_sha256"]
    )
    assert document["application_dependency"] == "none"
    assert document["execution_surface"] == "cli-only"
    assert (
        "application_dependency"
        not in inspect.signature(retain_s05_scenario_inputs).parameters
    )
    evidence.close()


def test_public_writers_and_loaders_cannot_mint_from_arbitrary_digests(
    tmp_path: Path,
) -> None:
    root = _private_root(tmp_path, "arbitrary")
    arbitrary = {
        "execution_sha256": _sha("execution"),
        "assessment_sha256": _sha("assessment"),
        "pre_pause_task_state_sha256": _sha("task"),
    }
    assert set(inspect.signature(write_s04_continuity_bundle).parameters) == {
        "root",
        "inputs",
    }
    assert set(inspect.signature(write_s05_update_bundle).parameters) == {
        "root",
        "inputs",
    }
    with pytest.raises(TypeError):
        write_s04_continuity_bundle(root, **arbitrary)
    with pytest.raises(TypeError):
        load_s04_continuity_bundle(root, _sha("bundle"))
    module = __import__("cc.core.evaluation.scenario_evidence", fromlist=["*"])
    assert "_issue_s04" not in module.__all__
    assert "_issue_s05" not in module.__all__
    assert "execution_sha256" not in inspect.signature(module._issue_s04).parameters
    assert (
        "before_project_tree_sha256"
        not in inspect.signature(module._issue_s05).parameters
    )
    assert not any(root.iterdir())


def test_s04_rejects_unapproved_assessment_or_signature(
    tmp_path: Path,
    assessment: LoadedDurableAssessmentManifestEvidence,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s04_source_files(tmp_path, assessment, publisher_key)
    with pytest.raises(ScenarioEvidenceUnavailable, match="assessment"):
        prepare_s04_publisher_claim(
            pre_pause_tc_export=files["pre_pause_tc_export"],
            resumed_tc_export=files["resumed_tc_export"],
            artifact_root=files["artifact_root"],
            assessment=copy.copy(assessment),
        )
    wrong_key = tmp_path / "wrong-key"
    subprocess.run(
        ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(wrong_key)],
        check=True,
        capture_output=True,
    )
    files["publisher_signature"] = _sign(
        wrong_key.resolve(), Path(files["publisher_claim"]), _S04_NAMESPACE
    )
    with pytest.raises(ScenarioEvidenceUnavailable, match="signature"):
        _retain_s04(files, publisher_key[1])


@pytest.mark.parametrize(
    "mutation", ("work-products", "process", "artifact", "outcome")
)
def test_s04_claim_preparation_rejects_broken_continuity(
    tmp_path: Path,
    assessment: LoadedDurableAssessmentManifestEvidence,
    publisher_key: tuple[Path, str],
    mutation: str,
) -> None:
    files = _s04_source_files(tmp_path, assessment, publisher_key)
    resumed = dict(files["resumed_document"])
    if mutation == "work-products":
        resumed["work_products"] = [
            {"id": 1, "type": "handoff", "artifact_sha256": _sha("lost")}
        ]
    elif mutation == "process":
        resumed["process_identity"] = files["pre_document"]["process_identity"]
    elif mutation == "artifact":
        resumed["artifact_root_sha256"] = _sha("substituted-root")
    else:
        resumed["continuation"] = {
            **resumed["continuation"],
            "outcome": "paused",
        }
    _write_json(Path(files["resumed_tc_export"]), resumed)
    with pytest.raises(ScenarioEvidenceUnavailable):
        prepare_s04_publisher_claim(
            pre_pause_tc_export=files["pre_pause_tc_export"],
            resumed_tc_export=files["resumed_tc_export"],
            artifact_root=files["artifact_root"],
            assessment=assessment,
        )


@pytest.mark.parametrize("mutation", ("human", "component", "no-app", "receipt"))
def test_s05_claim_preparation_rejects_substituted_update_evidence(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
    mutation: str,
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    if mutation in {"human", "component"}:
        after = dict(files["after_document"])
        tree = [dict(item) for item in after["tree"]]
        target = "human/notes.md" if mutation == "human" else "shared/component.json"
        for item in tree:
            if item["path"] == target:
                item["blob_sha256"] = (
                    _sha("changed-human")
                    if mutation == "human"
                    else files["before_document"]["tree"][1]["blob_sha256"]
                )
        after["tree"] = tree
        _write_json(Path(files["after_project_export"]), after)
    elif mutation == "no-app":
        ledger = dict(files["ledger_document"])
        ledger["application_dependency"] = "required"
        _write_json(Path(files["update_ledger"]), ledger)
    else:
        ledger = dict(files["ledger_document"])
        ledger["after_source_receipt_sha256"] = _sha("substitution")
        _write_json(Path(files["update_ledger"]), ledger)
    with pytest.raises(ScenarioEvidenceUnavailable):
        prepare_s05_publisher_claim(
            **{
                key: value
                for key, value in files.items()
                if key
                not in {
                    "publisher_claim",
                    "publisher_signature",
                    "before_document",
                    "after_document",
                    "ledger_document",
                }
            }
        )


def test_signed_input_mutation_revokes_evidence(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    inputs = _retain_s05(files, publisher_key[1])
    root = _private_root(tmp_path, "mutated-output")
    evidence = write_s05_update_bundle(root, inputs=inputs)
    artifact = Path(files["resumed_artifact"])
    artifact.write_bytes(b"mutated retained artifact")
    artifact.chmod(0o600)
    assert not inputs.validate()
    assert not evidence.validate()
    with pytest.raises(ScenarioEvidenceUnavailable, match="not authentic"):
        s05_update_evidence_document(evidence)
    evidence.close()


def test_mutable_derived_projection_cannot_change_or_mint_s05_evidence(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    inputs = _retain_s05(files, publisher_key[1])
    projection = inputs._state.derived
    projection["application_dependency"] = "required"
    projection["human_work_after_sha256"] = _sha("forged-human-work")

    assert inputs.validate()
    root = _private_root(tmp_path, "immutable-derived-output")
    evidence = write_s05_update_bundle(root, inputs=inputs)
    document = s05_update_evidence_document(evidence)
    assert document["application_dependency"] == "none"
    assert document["human_work_before_sha256"] == document["human_work_after_sha256"]
    evidence.close()

    forged_inputs = _retain_s05(files, publisher_key[1])
    forged = forged_inputs._state.derived
    forged["application_dependency"] = "required"
    forged_inputs._state.derived_raw = canonical_json_bytes(forged)
    assert not forged_inputs.validate()
    forged_root = _private_root(tmp_path, "forged-derived-output")
    with pytest.raises(ScenarioEvidenceUnavailable, match="unavailable"):
        write_s05_update_bundle(forged_root, inputs=forged_inputs)
    assert not any(forged_root.iterdir())
    forged_inputs.close()


@pytest.mark.parametrize("mutation", ("content", "same-byte-replacement"))
def test_retained_publisher_claim_mutation_revokes_input_authority(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
    mutation: str,
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    inputs = _retain_s05(files, publisher_key[1])
    claim = Path(files["publisher_claim"])
    if mutation == "content":
        claim.write_bytes(claim.read_bytes()[:-1] + b" ")
        claim.chmod(0o600)
    else:
        replacement = claim.with_name("same-byte-claim")
        replacement.write_bytes(claim.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(claim)
    assert not inputs.validate()
    inputs.close()


def test_claim_path_swap_during_signature_verification_fails_closed(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    claim = Path(files["publisher_claim"])
    original_wait = codex_isolation_module._wait_for_leader_without_reaping
    swapped = False

    def swap_then_wait(process, *, timeout):
        nonlocal swapped
        replacement = claim.with_name("replacement-claim")
        replacement.write_bytes(claim.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(claim)
        swapped = True
        return original_wait(process, timeout=timeout)

    with patch.object(
        codex_isolation_module,
        "_wait_for_leader_without_reaping",
        swap_then_wait,
    ):
        with pytest.raises(ScenarioEvidenceUnavailable, match="signature"):
            _retain_s05(files, publisher_key[1])
    assert swapped
    assert claim.exists()


def test_signature_timeout_reaps_descendants_before_they_can_mutate(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    marker = tmp_path / "signature-descendant-survived"
    fake = tmp_path / "fake-ssh-keygen"
    fake.write_text(
        "#!/bin/sh\n" f"(sleep 1; printf survived > {marker}) &\n" "sleep 20\n"
    )
    fake.chmod(0o700)
    started = time.monotonic()
    with (
        patch.object(scenario_evidence_module, "_SSH_KEYGEN", fake),
        patch.object(
            scenario_evidence_module,
            "_SIGNATURE_TIMEOUT_SECONDS",
            0.05,
        ),
        pytest.raises(ScenarioEvidenceUnavailable, match="signature"),
    ):
        _retain_s05(files, publisher_key[1])
    assert time.monotonic() - started < 3
    time.sleep(1.1)
    assert not marker.exists()


@pytest.mark.parametrize("mutation", ("content", "replacement", "extra", "mode"))
def test_bundle_mutation_or_namespace_drift_revokes_evidence(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
    mutation: str,
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    inputs = _retain_s05(files, publisher_key[1])
    root = _private_root(tmp_path, f"bundle-{mutation}")
    evidence = write_s05_update_bundle(root, inputs=inputs)
    path = _only_bundle(root)
    if mutation == "content":
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + b" ")
        path.chmod(0o600)
    elif mutation == "replacement":
        replacement_path = root / "replacement"
        replacement_path.write_bytes(path.read_bytes())
        replacement_path.chmod(0o600)
        replacement_path.replace(path)
    elif mutation == "extra":
        _write_bytes(root / "unexpected", b"unexpected")
    else:
        path.chmod(0o644)
    assert not evidence.validate()
    evidence.close()


def test_input_copy_close_is_noop_and_consumed_input_cannot_replay(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    inputs = _retain_s05(files, publisher_key[1])
    copied = copy.copy(inputs)
    copied.close()
    assert inputs.validate()
    assert not verify_s05_scenario_inputs(copied)
    first = _private_root(tmp_path, "first")
    evidence = write_s05_update_bundle(first, inputs=inputs)
    second = _private_root(tmp_path, "second")
    with pytest.raises(ScenarioEvidenceUnavailable, match="consumed"):
        write_s05_update_bundle(second, inputs=inputs)
    assert not any(second.iterdir())
    evidence.close()


@pytest.mark.parametrize("scenario", ("s04", "s05"))
def test_caller_reachable_consumed_reset_cannot_replay_inputs(
    tmp_path: Path,
    assessment: LoadedDurableAssessmentManifestEvidence,
    publisher_key: tuple[Path, str],
    scenario: str,
) -> None:
    source_root = tmp_path / scenario
    source_root.mkdir()
    if scenario == "s04":
        files = _s04_source_files(source_root, assessment, publisher_key)
        inputs = _retain_s04(files, publisher_key[1])
        writer = write_s04_continuity_bundle
    else:
        files = _s05_source_files(source_root, publisher_key)
        inputs = _retain_s05(files, publisher_key[1])
        writer = write_s05_update_bundle
    first_root = _private_root(source_root, "first-output")
    first = writer(first_root, inputs=inputs)
    inputs._state.consumed = False
    second_root = _private_root(source_root, "second-output")

    with pytest.raises(ScenarioEvidenceUnavailable, match="already consumed"):
        writer(second_root, inputs=inputs)

    assert first.validate()
    assert not any(second_root.iterdir())
    first.close()


@pytest.mark.parametrize("scenario", ("s04", "s05"))
@pytest.mark.parametrize("replacement", ("direct", "ancestor"))
def test_bundle_root_name_and_ancestor_replacement_revoke_evidence(
    tmp_path: Path,
    assessment: LoadedDurableAssessmentManifestEvidence,
    publisher_key: tuple[Path, str],
    scenario: str,
    replacement: str,
) -> None:
    case_root = tmp_path / f"{scenario}-{replacement}"
    case_root.mkdir()
    if scenario == "s04":
        files = _s04_source_files(case_root, assessment, publisher_key)
        inputs = _retain_s04(files, publisher_key[1])
        writer = write_s04_continuity_bundle
    else:
        files = _s05_source_files(case_root, publisher_key)
        inputs = _retain_s05(files, publisher_key[1])
        writer = write_s05_update_bundle
    scope = _private_root(case_root, "scope")
    output = _private_root(scope, "output")
    evidence = writer(output, inputs=inputs)

    if replacement == "direct":
        output.rename(scope / "displaced-output")
        replacement_root = _private_root(scope, "output")
    else:
        scope.rename(case_root / "displaced-scope")
        replacement_scope = _private_root(case_root, "scope")
        replacement_root = _private_root(replacement_scope, "output")
    sentinel = _write_bytes(replacement_root / "sentinel", b"harmless replacement")

    assert not evidence.validate()
    assert sentinel.read_bytes() == b"harmless replacement"
    evidence.close()
    assert sentinel.read_bytes() == b"harmless replacement"


@pytest.mark.parametrize("substitution", ("symlink", "hardlink", "mode"))
def test_retained_source_rejects_alias_or_public_mode(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
    substitution: str,
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    source = Path(files["resumed_artifact"])
    replacement_path = source.parent / "substituted-artifact"
    if substitution == "symlink":
        replacement_path.symlink_to(source)
    elif substitution == "hardlink":
        replacement_path.hardlink_to(source)
    else:
        replacement_path.write_bytes(source.read_bytes())
        replacement_path.chmod(0o644)
    files["resumed_artifact"] = (
        replacement_path.resolve()
        if substitution != "symlink"
        else replacement_path.absolute()
    )
    with pytest.raises(ScenarioEvidenceUnavailable):
        _retain_s05(files, publisher_key[1])


def test_duplicate_key_claim_and_wrong_namespace_signature_are_rejected(
    tmp_path: Path,
    publisher_key: tuple[Path, str],
) -> None:
    files = _s05_source_files(tmp_path, publisher_key)
    claim = Path(files["publisher_claim"])
    raw = claim.read_bytes().replace(
        b'{"derived":',
        b'{"derived":{},"derived":',
        1,
    )
    claim.write_bytes(raw)
    claim.chmod(0o600)
    files["publisher_signature"] = _sign(
        publisher_key[0], claim, "wrong-scenario-namespace"
    )
    with pytest.raises(ScenarioEvidenceUnavailable):
        _retain_s05(files, publisher_key[1])
