from __future__ import annotations

import hashlib
import hmac
import secrets
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from cc.core.evaluation.fixtures import load_fixture
from cc.core.evaluation.judgment import (
    build_criterion_judgment,
    compare_criterion_judgments,
    load_assessor_authorization,
    load_durable_criterion_judgment,
)
from cc.core.evaluation.models import (
    CriterionAssessment,
    CriterionVerdict,
    LayerVariant,
    RunState,
)
from cc.core.evaluation.schema import canonical_json_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "cases"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _completed(variant: LayerVariant = LayerVariant.FOUNDATION):
    from test_runner_core import _cell as core_cell
    from test_runner_core import _runner, _Runtime

    fixture_sha256 = load_fixture(FIXTURES / "eval-01").fixture_sha256
    base = replace(core_cell(variant), fixture_sha256=fixture_sha256)
    return _runner(_Runtime()).run(base), "Synthetic result with cited evidence."


def _span(output: str) -> dict[str, object]:
    return {
        "start": 0,
        "end": len(output),
        "sha256": hashlib.sha256(output.encode()).hexdigest(),
    }


def _rationale_text(criterion: str) -> str:
    return f"Private synthetic rationale for {criterion}."


def _rationale_document(record, criteria) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "run_sha256": record.run_sha256,
        "rationales": [
            {"criterion": criterion, "rationale": _rationale_text(criterion)}
            for criterion in criteria
        ],
    }


def _document(record, fixture, output, *, verdict="demonstrated"):
    rationale_code = {
        "demonstrated": "evidence-supports-verdict",
        "partial": "evidence-partially-supports-verdict",
        "absent": "no-supporting-evidence",
        "violated": "evidence-shows-violation",
    }[verdict]
    return {
        "schema_version": "1.0",
        "run_sha256": record.run_sha256,
        "assessor": "publisher-attested-review",
        "oracle_sha256": fixture.oracle.sha256,
        "criteria": [
            {
                "criterion": criterion,
                "verdict": verdict,
                "spans": [_span(output)],
                "rationale_code": rationale_code,
                "private_rationale_commitment_sha256": "0" * 64,
            }
            for criterion in fixture.fixture.required_criteria
        ],
        "hard_rejections": [
            {"rule": rule, "triggered": False, "spans": []}
            for rule in fixture.fixture.hard_rejection_rules
        ],
    }


def _write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_bytes(content)
    path.chmod(0o600)


@contextmanager
def _evidence_vault(
    record, document, rationale_document, *, populate_commitments: bool = True
):
    commitment_key = secrets.token_hex(32)
    rationale_raw = canonical_json_bytes(rationale_document)
    rationale_by_criterion = {
        item["criterion"]: item["rationale"]
        for item in rationale_document["rationales"]
    }
    if populate_commitments:
        for item in document["criteria"]:
            rationale = rationale_by_criterion.get(item["criterion"], "")
            item["private_rationale_commitment_sha256"] = hmac.new(
                bytes.fromhex(commitment_key),
                canonical_json_bytes(
                    {
                        "run_sha256": record.run_sha256,
                        "criterion": item["criterion"],
                        "rationale": rationale,
                    }
                ),
                hashlib.sha256,
            ).hexdigest()
    assessment_raw = canonical_json_bytes(document)
    assessment_sha256 = hashlib.sha256(assessment_raw).hexdigest()
    rationale_sha256 = hashlib.sha256(rationale_raw).hexdigest()
    authorization = {
        "schema_version": "1.0",
        "run_sha256": record.run_sha256,
        "assessor": "publisher-attested-review",
        "oracle_sha256": document["oracle_sha256"],
        "assessment_document_sha256": assessment_sha256,
        "private_rationale_document_sha256": rationale_sha256,
        "rationale_commitment_key": commitment_key,
        "signer": "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo",
        "namespace": "copilot-effectiveness-assessment",
    }
    authorization_raw = canonical_json_bytes(authorization)
    authorization_sha256 = hashlib.sha256(authorization_raw).hexdigest()
    signature_raw = b"synthetic detached signature\n"
    signature_sha256 = hashlib.sha256(signature_raw).hexdigest()
    with tempfile.TemporaryDirectory(
        prefix=".assessor-vault-",
        dir=REPOSITORY_ROOT if sys.platform.startswith("linux") else None,
    ) as directory:
        root = Path(directory).resolve()
        root.chmod(0o700)
        _write_private(
            root / "assessor-authorization" / f"{authorization_sha256}.json",
            authorization_raw,
        )
        _write_private(
            root / "assessor-assessment" / f"{assessment_sha256}.json",
            assessment_raw,
        )
        _write_private(
            root / "assessor-private-rationale" / f"{rationale_sha256}.json",
            rationale_raw,
        )
        _write_private(
            root / "assessor-signature" / f"{signature_sha256}.sig",
            signature_raw,
        )
        yield root, authorization_sha256, signature_sha256


def _authorization(
    record, document, rationale_document, *, populate_commitments: bool = True
):
    with _evidence_vault(
        record,
        document,
        rationale_document,
        populate_commitments=populate_commitments,
    ) as evidence:
        root, authorization_sha256, signature_sha256 = evidence
        with patch(
            "cc.core.evaluation.judgment._verify_assessor_signature",
            return_value=True,
        ):
            return load_assessor_authorization(
                record,
                evidence_vault=root,
                authorization_sha256=authorization_sha256,
                signature_sha256=signature_sha256,
            )


def _build(record, fixture, output, document):
    authorization = _authorization(
        record,
        document,
        _rationale_document(record, fixture.fixture.required_criteria),
    )
    return build_criterion_judgment(
        record,
        fixture,
        output,
        document,
        assessor_authorization=authorization,
    )


def _durable_completed(tmp_path: Path):
    from cc.core.evaluation.artifact import (
        load_durable_completed_run,
        write_run_record,
    )
    from cc.core.evaluation.live_runtime import ClaudeNonInteractiveAdapter
    from cc.core.evaluation.models import RuntimeName
    from cc.core.evaluation.runner import EvaluationRunner
    from test_live_runtime import (
        _adapter_cell,
        _authority,
        _claude_agent_projection,
        _claude_json,
        _prompt_packet,
    )

    fixture = load_fixture(FIXTURES / "eval-01")
    tmp_path.chmod(0o700)
    executable = tmp_path / "claude-judgment-fixture"
    executable.write_bytes(b"synthetic claude executable")
    executable.chmod(0o700)
    packet = _prompt_packet(RuntimeName.CLAUDE)

    def run(argv, **_kwargs):
        import subprocess

        return subprocess.CompletedProcess(argv, 0, _claude_json(), "")

    adapter = ClaudeNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=executable,
        run=run,
        agent_resolver=_claude_agent_projection,
    )
    cell = _adapter_cell(
        RuntimeName.CLAUDE,
        executable,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    cell = replace(cell, fixture_sha256=fixture.fixture_sha256)
    runner = EvaluationRunner(adapter, artifact_root=tmp_path)
    with patch(
        "cc.core.evaluation.runner._production_authority",
        return_value=_authority(cell),
    ):
        record = runner.run(cell)
    authenticated_output = runner.completion_output(record)
    assert authenticated_output is not None
    with patch(
        "cc.core.evaluation._authority._production_authority",
        side_effect=lambda *_args, **_kwargs: _authority(cell),
    ):
        write_run_record(
            tmp_path,
            record,
            cell=cell,
            authenticated_output=authenticated_output,
        )
        loaded_run = load_durable_completed_run(
            tmp_path,
            record.run_sha256,
            cell=cell,
        )
    assert loaded_run is not None
    return fixture, loaded_run, authenticated_output.output_text


def test_judgment_persists_and_reloads_from_durable_run_and_private_vault(
    tmp_path: Path,
) -> None:
    from cc.core.evaluation.artifact import (
        verify_artifact_receipt,
        write_criterion_judgment,
    )

    fixture, loaded_run, output = _durable_completed(tmp_path)
    record = loaded_run.record
    document = _document(record, fixture, output)
    rationales = _rationale_document(record, fixture.fixture.required_criteria)
    with _evidence_vault(record, document, rationales) as evidence:
        vault, authorization_sha256, signature_sha256 = evidence
        with patch(
            "cc.core.evaluation.judgment._verify_assessor_signature",
            return_value=True,
        ):
            authorization = load_assessor_authorization(
                record,
                evidence_vault=vault,
                authorization_sha256=authorization_sha256,
                signature_sha256=signature_sha256,
            )
            judgment = build_criterion_judgment(
                record,
                fixture,
                output,
                document,
                assessor_authorization=authorization,
            )
            receipt = write_criterion_judgment(
                tmp_path,
                judgment,
                loaded_run=loaded_run,
            )
            reloaded = load_durable_criterion_judgment(
                tmp_path,
                receipt.sha256,
                loaded_run=loaded_run,
                loaded_fixture=fixture,
                output_text=output,
                evidence_vault=vault,
                authorization_sha256=authorization_sha256,
                signature_sha256=signature_sha256,
            )
    assert reloaded is not None
    assert reloaded.judgment == judgment
    assert reloaded.validate()
    assert not replace(reloaded).validate()
    assert verify_artifact_receipt(receipt)

    judgment_path = tmp_path / receipt.relative_path
    replacement = judgment_path.with_suffix(".replacement")
    replacement.write_text('{"mutated":true}', encoding="utf-8")
    replacement.chmod(0o600)
    replacement.replace(judgment_path)
    assert not reloaded.validate()
    assert not verify_artifact_receipt(receipt)


def test_detached_assessor_signature_uses_exact_key_namespace_and_bytes() -> None:
    from cc.core.ecosystem.policy import FOUNDATION_SSH_SIGNING_KEYS
    from cc.core.evaluation import judgment as judgment_module

    with tempfile.TemporaryDirectory(prefix="cc-assessor-key-") as directory:
        root = Path(directory).resolve()
        key = root / "fixture-key"
        payload = root / "authorization.json"
        subprocess.run(
            ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
            capture_output=True,
        )
        authorization_raw = canonical_json_bytes({"synthetic": "authorization"})
        payload.write_bytes(authorization_raw)
        subprocess.run(
            [
                "/usr/bin/ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                "copilot-effectiveness-assessment",
                str(payload),
            ],
            check=True,
            capture_output=True,
        )
        signature_raw = Path(f"{payload}.sig").read_bytes()
        public_key = " ".join(key.with_suffix(".pub").read_text().split()[:2])
        with patch.dict(
            FOUNDATION_SSH_SIGNING_KEYS,
            {judgment_module._ASSESSOR_SIGNER.upper(): public_key},
        ):
            assert judgment_module._verify_assessor_signature(
                authorization_raw, signature_raw
            )
            assert not judgment_module._verify_assessor_signature(
                authorization_raw + b" ", signature_raw
            )
            assert not judgment_module._verify_assessor_signature(
                authorization_raw, signature_raw.replace(b"U1NI", b"V1NI", 1)
            )
            with patch.object(
                judgment_module,
                "_ASSESSOR_NAMESPACE",
                "wrong-assessment-namespace",
            ):
                assert not judgment_module._verify_assessor_signature(
                    authorization_raw, signature_raw
                )
            with patch.object(
                judgment_module,
                "_allowed_signer_content",
                return_value=f"unapproved-reviewer {public_key}\n".encode(),
            ):
                assert not judgment_module._verify_assessor_signature(
                    authorization_raw, signature_raw
                )

        wrong_key = root / "wrong-key"
        subprocess.run(
            [
                "/usr/bin/ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(wrong_key),
            ],
            check=True,
            capture_output=True,
        )
        wrong_public_key = " ".join(
            wrong_key.with_suffix(".pub").read_text().split()[:2]
        )
        with patch.dict(
            FOUNDATION_SSH_SIGNING_KEYS,
            {judgment_module._ASSESSOR_SIGNER.upper(): wrong_public_key},
        ):
            assert not judgment_module._verify_assessor_signature(
                authorization_raw, signature_raw
            )


def test_assessor_signature_rejects_staged_name_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cc.core.evaluation import judgment as judgment_module

    staged: list[Path] = []
    real_stage = judgment_module._stage_private_file

    def tracked_stage(path: Path, content: bytes) -> int:
        staged.append(path)
        return real_stage(path, content)

    def replace_staged_names(argv, **_kwargs):
        for path in staged:
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(b"attacker replacement")
            replacement.chmod(0o600)
            replacement.replace(path)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(judgment_module, "_stage_private_file", tracked_stage)
    monkeypatch.setattr(judgment_module.subprocess, "run", replace_staged_names)
    with pytest.raises(ValueError, match="input identity changed"):
        judgment_module._verify_assessor_signature(
            b'{"synthetic":"authorization"}', b"synthetic signature"
        )


def test_assessor_authorization_requires_private_vault_and_valid_signature() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    document = _document(record, fixture, output)
    rationales = _rationale_document(record, fixture.fixture.required_criteria)
    with _evidence_vault(record, document, rationales) as evidence:
        root, authorization_sha256, signature_sha256 = evidence
        root.chmod(0o755)
        with pytest.raises(ValueError, match="Signed assessor evidence is unavailable"):
            load_assessor_authorization(
                record,
                evidence_vault=root,
                authorization_sha256=authorization_sha256,
                signature_sha256=signature_sha256,
            )

    with _evidence_vault(record, document, rationales) as evidence:
        root, authorization_sha256, signature_sha256 = evidence
        with (
            patch(
                "cc.core.evaluation.judgment._verify_assessor_signature",
                return_value=False,
            ),
            pytest.raises(ValueError, match="Signed assessor evidence is unavailable"),
        ):
            load_assessor_authorization(
                record,
                evidence_vault=root,
                authorization_sha256=authorization_sha256,
                signature_sha256=signature_sha256,
            )


@pytest.mark.parametrize(
    "mutation",
    ("type-mode", "type-symlink", "leaf-mode", "missing-signature", "substitution"),
)
def test_assessor_vault_rejects_unsafe_or_changed_entries(mutation: str) -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    document = _document(record, fixture, output)
    rationales = _rationale_document(record, fixture.fixture.required_criteria)
    with _evidence_vault(record, document, rationales) as evidence:
        root, authorization_sha256, signature_sha256 = evidence
        if mutation == "type-mode":
            (root / "assessor-assessment").chmod(0o755)
        elif mutation == "type-symlink":
            original = root / "assessor-assessment"
            held = root / "held-assessment"
            original.rename(held)
            original.symlink_to(held, target_is_directory=True)
        elif mutation == "leaf-mode":
            next((root / "assessor-authorization").glob("*.json")).chmod(0o644)
        elif mutation == "missing-signature":
            next((root / "assessor-signature").glob("*.sig")).unlink()
        else:
            target = next((root / "assessor-authorization").glob("*.json"))
            target.write_text('{"substituted":true}', encoding="utf-8")
            target.chmod(0o600)
        with (
            patch(
                "cc.core.evaluation.judgment._verify_assessor_signature",
                return_value=True,
            ),
            pytest.raises(ValueError, match="Signed assessor evidence is unavailable"),
        ):
            load_assessor_authorization(
                record,
                evidence_vault=root,
                authorization_sha256=authorization_sha256,
                signature_sha256=signature_sha256,
            )


def test_private_rationale_rejects_secret_or_personal_data() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    document = _document(record, fixture, output)
    rationales = _rationale_document(record, fixture.fixture.required_criteria)
    rationales["rationales"][0][
        "rationale"
    ] = "Synthetic explanation bearer ghp_123456789012345678901234"
    with _evidence_vault(record, document, rationales) as evidence:
        root, authorization_sha256, signature_sha256 = evidence
        with (
            patch(
                "cc.core.evaluation.judgment._verify_assessor_signature",
                return_value=True,
            ),
            pytest.raises(ValueError, match="safety check failed"),
        ):
            load_assessor_authorization(
                record,
                evidence_vault=root,
                authorization_sha256=authorization_sha256,
                signature_sha256=signature_sha256,
            )


def test_assessor_authorization_binds_exact_assessment_and_private_rationale() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    signed_document = _document(record, fixture, output)
    rationales = _rationale_document(record, fixture.fixture.required_criteria)
    authorization = _authorization(record, signed_document, rationales)

    second_document = _document(record, fixture, output)
    second_authorization = _authorization(record, second_document, rationales)
    assert (
        authorization.private_rationale_commitment_sha256
        != second_authorization.private_rationale_commitment_sha256
    )
    assert dict(authorization.private_rationale_commitments) != dict(
        second_authorization.private_rationale_commitments
    )

    malicious_document = _document(record, fixture, output, verdict="partial")
    forged_authorization = replace(
        authorization,
        assessment_document_sha256=hashlib.sha256(
            canonical_json_bytes(malicious_document)
        ).hexdigest(),
        _assessment_document_json=canonical_json_bytes(malicious_document).decode(),
    )
    with pytest.raises(ValueError, match="not bound"):
        build_criterion_judgment(
            record,
            fixture,
            output,
            malicious_document,
            assessor_authorization=forged_authorization,
        )

    changed = _document(record, fixture, output, verdict="partial")
    with pytest.raises(ValueError, match="not bound"):
        build_criterion_judgment(
            record,
            fixture,
            output,
            changed,
            assessor_authorization=authorization,
        )

    missing = _rationale_document(record, fixture.fixture.required_criteria[:-1])
    with pytest.raises(ValueError, match="do not match the assessment"):
        _authorization(record, signed_document, missing)

    changed_rationale = dict(signed_document)
    changed_rationale["criteria"] = [dict(item) for item in signed_document["criteria"]]
    changed_rationale["criteria"][0]["private_rationale_commitment_sha256"] = "f" * 64
    changed_authorization = _authorization(
        record,
        changed_rationale,
        rationales,
        populate_commitments=False,
    )
    with pytest.raises(ValueError, match="not signed assessor evidence"):
        build_criterion_judgment(
            record,
            fixture,
            output,
            changed_rationale,
            assessor_authorization=changed_authorization,
        )


def test_judgment_requires_exact_criteria_and_digest_bound_output_spans() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    assert record.state is RunState.COMPLETED
    judgment = _build(record, fixture, output, _document(record, fixture, output))

    assert judgment.hard_gate_passed
    assert tuple(item.criterion for item in judgment.assessments) == (
        fixture.fixture.required_criteria
    )
    assert all(item.evidence_sha256 for item in judgment.assessments)

    missing = _document(record, fixture, output)
    missing["criteria"] = missing["criteria"][:-1]
    with pytest.raises(ValueError, match="private rationales do not match"):
        _build(record, fixture, output, missing)

    changed = _document(record, fixture, output)
    changed["criteria"][0]["spans"][0]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="span digest changed"):
        _build(record, fixture, output, changed)


def test_hard_rejection_is_preserved_and_blocks_comparison() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    document = _document(record, fixture, output)
    document["hard_rejections"][0] = {
        "rule": fixture.fixture.hard_rejection_rules[0],
        "triggered": True,
        "spans": [_span(output)],
    }
    rejected = _build(record, fixture, output, document)
    passed = _build(record, fixture, output, _document(record, fixture, output))
    assert not rejected.hard_gate_passed
    with pytest.raises(ValueError, match="Hard-rejected"):
        compare_criterion_judgments(record, record, rejected, passed)


def test_judgment_schema_rejects_aggregate_or_self_assessment_fields() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    document = _document(record, fixture, output)
    document["score"] = 100
    with pytest.raises(ValueError, match="Signed assessor evidence is malformed"):
        _build(record, fixture, output, document)
    document = _document(record, fixture, output)
    document["assessor"] = "runtime-self-assessment"
    with pytest.raises(ValueError, match="Signed assessor evidence is malformed"):
        _build(record, fixture, output, document)


def test_judgment_rejects_raw_rationale_text_from_shared_evidence() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    document = _document(record, fixture, output)
    criterion = document["criteria"][0]
    criterion["rationale"] = "The role-scope concern should stay private."
    with pytest.raises(ValueError, match="criteria are malformed"):
        _build(record, fixture, output, document)
    document = _document(record, fixture, output)
    document["criteria"][0]["rationale_code"] = "no-supporting-evidence"
    with pytest.raises(ValueError, match="does not match its verdict"):
        _build(record, fixture, output, document)


@pytest.mark.parametrize("verdict", tuple(CriterionVerdict))
@pytest.mark.parametrize(
    "rationale_code",
    (
        "evidence-supports-verdict",
        "evidence-partially-supports-verdict",
        "no-supporting-evidence",
        "evidence-shows-violation",
    ),
)
def test_assessment_model_enforces_exact_verdict_rationale_pair(
    verdict: CriterionVerdict,
    rationale_code: str,
) -> None:
    expected = {
        CriterionVerdict.DEMONSTRATED: "evidence-supports-verdict",
        CriterionVerdict.PARTIAL: "evidence-partially-supports-verdict",
        CriterionVerdict.ABSENT: "no-supporting-evidence",
        CriterionVerdict.VIOLATED: "evidence-shows-violation",
    }[verdict]
    kwargs = {
        "criterion": "scope-fit",
        "verdict": verdict,
        "evidence_sha256": ("1" * 64,),
        "content_receipt_sha256": ("2" * 64,),
        "rationale_code": rationale_code,
        "rationale_commitment_sha256": "3" * 64,
    }
    if rationale_code == expected:
        assert CriterionAssessment(**kwargs).rationale_code == expected
    else:
        with pytest.raises(ValueError, match="does not match its verdict"):
            CriterionAssessment(**kwargs)


def test_protected_criterion_regression_rejects_comparison() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    record, output = _completed()
    control = _build(
        record,
        fixture,
        output,
        _document(record, fixture, output, verdict="demonstrated"),
    )
    layered = _build(
        record, fixture, output, _document(record, fixture, output, verdict="violated")
    )

    with pytest.raises(ValueError, match="Hard-rejected"):
        compare_criterion_judgments(record, record, control, layered)


def test_protected_criterion_violations_reject_even_when_both_runs_match() -> None:
    fixture = load_fixture(FIXTURES / "eval-01")
    control_record, output = _completed()
    layered_record, _ = _completed(LayerVariant.ORGANIZATION)
    control = _build(
        control_record,
        fixture,
        output,
        _document(control_record, fixture, output, verdict="violated"),
    )
    layered = _build(
        layered_record,
        fixture,
        output,
        _document(layered_record, fixture, output, verdict="violated"),
    )

    assert not control.hard_gate_passed
    assert not layered.hard_gate_passed
    with pytest.raises(ValueError, match="Hard-rejected"):
        compare_criterion_judgments(control_record, layered_record, control, layered)
