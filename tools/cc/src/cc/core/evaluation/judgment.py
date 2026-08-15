"""Evidence-bound criterion judgments for completed live evaluation runs."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from cc.core.evaluation.comparison import (
    _JUDGMENT_COMPARISON_AUTHORITY,
    pair_control_runs,
)
from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
from cc.core.evaluation.models import (
    ComparisonRecord,
    CriterionAssessment,
    CriterionComparison,
    CriterionRelation,
    CriterionVerdict,
    HardRejectionAssessment,
    RunRecord,
    RunState,
)
from cc.core.evaluation.runner import verify_run_record_identity
from cc.core.evaluation.schema import canonical_json_bytes, canonical_sha256

_ASSESSOR_PRINCIPAL = "publisher-attested-review"
_ASSESSORS = frozenset({_ASSESSOR_PRINCIPAL})
_ASSESSOR_SIGNER = "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
_ASSESSOR_NAMESPACE = "copilot-effectiveness-assessment"
_AUTHORIZATION_KEYS = frozenset(
    {
        "schema_version",
        "run_sha256",
        "assessor",
        "oracle_sha256",
        "assessment_document_sha256",
        "private_rationale_document_sha256",
        "rationale_commitment_key",
        "signer",
        "namespace",
    }
)
_DOCUMENT_KEYS = frozenset(
    {
        "schema_version",
        "run_sha256",
        "assessor",
        "oracle_sha256",
        "criteria",
        "hard_rejections",
    }
)
_CRITERION_KEYS = frozenset(
    {
        "criterion",
        "verdict",
        "spans",
        "rationale_code",
        "private_rationale_commitment_sha256",
    }
)
_REJECTION_KEYS = frozenset({"rule", "triggered", "spans"})
_SPAN_KEYS = frozenset({"start", "end", "sha256"})
_VERDICT_ORDER = {
    CriterionVerdict.VIOLATED: 0,
    CriterionVerdict.ABSENT: 1,
    CriterionVerdict.PARTIAL: 2,
    CriterionVerdict.DEMONSTRATED: 3,
}
_PROTECTED_CRITERIA = frozenset(
    {
        "safety-and-privacy",
        "user-ownership",
        "evidence",
        "evidence-discipline",
        "factual-restraint",
        "appropriate-methodology",
        "specialist-craft",
        "applicable-craft",
    }
)
_ASSESSOR_AUTHORITY = object()
_JUDGMENT_AUTHORITY = object()
_COMPARISON_DRAFT_AUTHORITY = object()
_ASSESSOR_SEALS: dict[object, str] = {}
_JUDGMENT_SEALS: dict[object, str] = {}


@dataclass(frozen=True)
class AssessorAuthorization:
    run_sha256: str
    assessor: str
    evidence_sha256: str
    signer_identity_sha256: str
    assessment_document_sha256: str
    oracle_sha256: str
    private_rationale_document_sha256: str
    private_rationale_commitment_sha256: str
    private_rationale_commitments: tuple[tuple[str, str], ...]
    _assessment_document_json: str = field(repr=False, compare=False)
    _rationale_commitment_key: str = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)
    _authority: object

    def __post_init__(self) -> None:
        if (
            self._authority is not _ASSESSOR_AUTHORITY
            or self.assessor not in _ASSESSORS
            or len(self.run_sha256) != 64
            or len(self.evidence_sha256) != 64
            or len(self.signer_identity_sha256) != 64
            or len(self.assessment_document_sha256) != 64
            or len(self.oracle_sha256) != 64
            or len(self.private_rationale_document_sha256) != 64
            or len(self.private_rationale_commitment_sha256) != 64
            or not self.private_rationale_commitments
            or len(self._rationale_commitment_key) != 64
            or hashlib.sha256(self._assessment_document_json.encode()).hexdigest()
            != self.assessment_document_sha256
        ):
            raise ValueError("Assessor authorization is invalid.")
        if any(
            not criterion or len(digest) != 64
            for criterion, digest in self.private_rationale_commitments
        ):
            raise ValueError("Assessor private rationale identity is invalid.")


def _assessor_authorization_binding(value: AssessorAuthorization) -> str:
    return canonical_sha256(
        {
            "run_sha256": value.run_sha256,
            "assessor": value.assessor,
            "evidence_sha256": value.evidence_sha256,
            "signer_identity_sha256": value.signer_identity_sha256,
            "assessment_document_sha256": value.assessment_document_sha256,
            "oracle_sha256": value.oracle_sha256,
            "private_rationale_document_sha256": (
                value.private_rationale_document_sha256
            ),
            "private_rationale_commitment_sha256": (
                value.private_rationale_commitment_sha256
            ),
            "private_rationale_commitments": [
                list(item) for item in value.private_rationale_commitments
            ],
            "assessment_document_json_sha256": hashlib.sha256(
                value._assessment_document_json.encode()
            ).hexdigest(),
            "rationale_commitment_key_sha256": hashlib.sha256(
                value._rationale_commitment_key.encode()
            ).hexdigest(),
        }
    )


def _verify_assessor_authorization(value: AssessorAuthorization) -> bool:
    return (
        isinstance(value, AssessorAuthorization)
        and value._authority is _ASSESSOR_AUTHORITY
        and _ASSESSOR_SEALS.get(value._seal) == _assessor_authorization_binding(value)
    )


def _sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _allowed_signer_content(public_key: str) -> bytes:
    return f"{_ASSESSOR_PRINCIPAL} {public_key}\n".encode()


def _stage_private_file(path: Path, content: bytes) -> int:
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written < 1:
                raise OSError("Assessor signature staging made no progress.")
            offset += written
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _validate_staged_file(
    descriptor: int, path: Path, content: bytes, expected: os.stat_result
) -> None:
    current = os.fstat(descriptor)
    named = path.stat(follow_symlinks=False)
    os.lseek(descriptor, 0, os.SEEK_SET)
    observed = os.read(descriptor, len(content) + 1)
    os.lseek(descriptor, 0, os.SEEK_SET)
    if (
        observed != content
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
        or (named.st_dev, named.st_ino) != (current.st_dev, current.st_ino)
        or current.st_nlink != 1
        or current.st_size != len(content)
    ):
        raise ValueError("Assessor verifier input identity changed.")


def _verify_assessor_signature(authorization_raw: bytes, signature_raw: bytes) -> bool:
    """Verify a detached company-key signature without persisting private text."""

    from cc.core.ecosystem.policy import FOUNDATION_SSH_SIGNING_KEYS

    public_key = FOUNDATION_SSH_SIGNING_KEYS.get(_ASSESSOR_SIGNER.upper())
    if public_key is None:
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="cc-assessor-signature-") as directory:
            root = Path(directory)
            root.chmod(0o700)
            allowed = root / "allowed_signers"
            signature = root / "authorization.sig"
            allowed_content = _allowed_signer_content(public_key)
            allowed_fd = _stage_private_file(allowed, allowed_content)
            signature_fd = _stage_private_file(signature, signature_raw)
            try:
                allowed_identity = os.fstat(allowed_fd)
                signature_identity = os.fstat(signature_fd)
                _validate_staged_file(
                    allowed_fd, allowed, allowed_content, allowed_identity
                )
                _validate_staged_file(
                    signature_fd, signature, signature_raw, signature_identity
                )
                result = subprocess.run(
                    [
                        "/usr/bin/ssh-keygen",
                        "-Y",
                        "verify",
                        "-f",
                        f"/dev/fd/{allowed_fd}",
                        "-I",
                        _ASSESSOR_PRINCIPAL,
                        "-n",
                        _ASSESSOR_NAMESPACE,
                        "-s",
                        f"/dev/fd/{signature_fd}",
                    ],
                    input=authorization_raw,
                    capture_output=True,
                    timeout=8,
                    check=False,
                    pass_fds=(allowed_fd, signature_fd),
                )
                _validate_staged_file(
                    allowed_fd, allowed, allowed_content, allowed_identity
                )
                _validate_staged_file(
                    signature_fd, signature, signature_raw, signature_identity
                )
                return result.returncode == 0
            finally:
                os.close(allowed_fd)
                os.close(signature_fd)
    except (OSError, subprocess.SubprocessError):
        return False


def load_assessor_authorization(
    record: RunRecord,
    *,
    evidence_vault: Path,
    authorization_sha256: str,
    signature_sha256: str,
) -> AssessorAuthorization:
    """Load publisher-signed evidence from a private content-addressed vault."""

    if (
        not verify_run_record_identity(record)
        or len(authorization_sha256) != 64
        or len(signature_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in authorization_sha256 + signature_sha256
        )
    ):
        raise ValueError("Assessor authorization requires an authentic run.")
    from cc.core.evaluation.artifact import (
        _CompositeArtifactCapability,
        _open_linked_bytes,
        _open_root_directory,
    )

    capabilities = []
    root_fd: int | None = None
    try:
        root_fd = _open_root_directory(evidence_vault)

        def read(
            artifact_type: str,
            digest: str,
            suffix: str,
            maximum_size: int,
        ) -> bytes:
            raw, capability = _open_linked_bytes(
                root_fd,
                artifact_type,
                f"{digest}.{suffix}",
                digest,
                maximum_size=maximum_size,
            )
            capabilities.append(capability)
            return raw

        authorization_raw = read(
            "assessor-authorization", authorization_sha256, "json", 16_384
        )
        authorization_document = json.loads(authorization_raw)
        if (
            not isinstance(authorization_document, Mapping)
            or set(authorization_document) != _AUTHORIZATION_KEYS
            or canonical_json_bytes(authorization_document) != authorization_raw
            or authorization_document.get("schema_version") != "1.0"
            or authorization_document.get("run_sha256") != record.run_sha256
            or authorization_document.get("assessor") not in _ASSESSORS
            or authorization_document.get("signer") != _ASSESSOR_SIGNER
            or authorization_document.get("namespace") != _ASSESSOR_NAMESPACE
        ):
            raise ValueError("Signed assessor authorization is malformed.")
        assessment_sha256 = authorization_document.get("assessment_document_sha256")
        rationale_document_sha256 = authorization_document.get(
            "private_rationale_document_sha256"
        )
        rationale_commitment_key = authorization_document.get(
            "rationale_commitment_key"
        )
        oracle_sha256 = authorization_document.get("oracle_sha256")
        if any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in (
                assessment_sha256,
                rationale_document_sha256,
                oracle_sha256,
                rationale_commitment_key,
            )
        ):
            raise ValueError("Signed assessor authorization is malformed.")
        assessment_sha256 = str(assessment_sha256)
        rationale_document_sha256 = str(rationale_document_sha256)
        oracle_sha256 = str(oracle_sha256)
        rationale_commitment_key = str(rationale_commitment_key)
        raw = read("assessor-assessment", assessment_sha256, "json", 262_144)
        rationale_raw = read(
            "assessor-private-rationale",
            rationale_document_sha256,
            "json",
            262_144,
        )
        signature_raw = read("assessor-signature", signature_sha256, "sig", 16_384)
        document = json.loads(raw)
        rationale_document = json.loads(rationale_raw)
        composite = _CompositeArtifactCapability(tuple(capabilities))
        capabilities = []
        composite.validate()
        if not _verify_assessor_signature(authorization_raw, signature_raw):
            raise ValueError("Assessor authorization signature is invalid.")
        composite.validate()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Signed assessor evidence is unavailable.") from exc
    finally:
        for capability in capabilities:
            capability.close()
        if "composite" in locals():
            composite.close()
        if root_fd is not None:
            os.close(root_fd)
    if (
        not isinstance(document, Mapping)
        or set(document) != _DOCUMENT_KEYS
        or canonical_json_bytes(document) != raw
        or document.get("schema_version") != "1.0"
        or document.get("run_sha256") != record.run_sha256
        or document.get("assessor") not in _ASSESSORS
        or document.get("oracle_sha256") != oracle_sha256
        or not isinstance(document.get("criteria"), list)
        or not isinstance(document.get("hard_rejections"), list)
        or not isinstance(rationale_document, Mapping)
        or set(rationale_document) != {"schema_version", "run_sha256", "rationales"}
        or canonical_json_bytes(rationale_document) != rationale_raw
        or rationale_document.get("schema_version") != "1.0"
        or rationale_document.get("run_sha256") != record.run_sha256
        or not isinstance(rationale_document.get("rationales"), list)
    ):
        raise ValueError("Signed assessor evidence is malformed.")
    rationale_identities: list[tuple[str, str]] = []
    commitment_key = bytes.fromhex(rationale_commitment_key)
    for item in rationale_document["rationales"]:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"criterion", "rationale"}
            or not isinstance(item.get("criterion"), str)
            or not isinstance(item.get("rationale"), str)
            or not item["criterion"]
            or not item["rationale"]
            or len(item["rationale"]) > 2048
        ):
            raise ValueError("Signed assessor private rationale is malformed.")
        from cc.core.evaluation.safety import require_safe_synthetic_text

        require_safe_synthetic_text(
            item["rationale"], location_class="private-assessor-rationale"
        )
        rationale_identities.append(
            (
                item["criterion"],
                hmac.new(
                    commitment_key,
                    canonical_json_bytes(
                        {
                            "run_sha256": record.run_sha256,
                            "criterion": item["criterion"],
                            "rationale": item["rationale"],
                        }
                    ),
                    hashlib.sha256,
                ).hexdigest(),
            )
        )
    if len(rationale_identities) != len({item[0] for item in rationale_identities}):
        raise ValueError("Signed assessor private rationales are duplicated.")
    assessment_criteria = tuple(
        item.get("criterion") if isinstance(item, Mapping) else None
        for item in document["criteria"]
    )
    if tuple(item[0] for item in rationale_identities) != assessment_criteria:
        raise ValueError("Signed private rationales do not match the assessment.")
    signer_identity = {
        "signer": _ASSESSOR_SIGNER,
        "namespace": _ASSESSOR_NAMESPACE,
        "authorization_sha256": authorization_sha256,
        "signature_sha256": signature_sha256,
        "ssh_keygen_sha256": _sha256_file(Path("/usr/bin/ssh-keygen")),
        "storage_class": "local-private-content-addressed-vault",
    }
    signer_identity_sha256 = canonical_sha256(signer_identity)
    rationale_document_commitment_sha256 = hmac.new(
        commitment_key,
        rationale_raw,
        hashlib.sha256,
    ).hexdigest()
    evidence_sha256 = canonical_sha256(
        {
            "assessment_document_sha256": assessment_sha256,
            "private_rationale_commitment_sha256": (
                rationale_document_commitment_sha256
            ),
            "signer_identity": signer_identity,
        }
    )
    seal = object()
    authorization = AssessorAuthorization(
        record.run_sha256,
        str(document["assessor"]),
        evidence_sha256,
        signer_identity_sha256,
        assessment_sha256,
        str(document["oracle_sha256"]),
        rationale_document_sha256,
        rationale_document_commitment_sha256,
        tuple(rationale_identities),
        raw.decode("utf-8"),
        rationale_commitment_key,
        seal,
        _ASSESSOR_AUTHORITY,
    )
    _ASSESSOR_SEALS[seal] = _assessor_authorization_binding(authorization)
    return authorization


@dataclass(frozen=True)
class CriterionJudgment:
    schema_version: str
    run_sha256: str
    assessor: str
    assessor_evidence_sha256: str
    signer_identity_sha256: str
    oracle_sha256: str
    private_rationale_commitment_sha256: str
    assessments: tuple[CriterionAssessment, ...]
    hard_rejections: tuple[HardRejectionAssessment, ...]
    triggered_rejections: tuple[str, ...]
    judgment_sha256: str
    _seal: object = field(repr=False, compare=False)
    _authority: object

    def __post_init__(self) -> None:
        if self._authority is not _JUDGMENT_AUTHORITY or any(
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in (
                self.assessor_evidence_sha256,
                self.signer_identity_sha256,
                self.oracle_sha256,
                self.private_rationale_commitment_sha256,
            )
        ):
            raise ValueError("Criterion judgment is not verifier-issued.")
        if self.triggered_rejections != tuple(
            item.rule for item in self.hard_rejections if item.triggered
        ):
            raise ValueError("Criterion judgment hard-rejection identity changed.")

    @property
    def hard_gate_passed(self) -> bool:
        return not self.triggered_rejections and not any(
            item.criterion in _PROTECTED_CRITERIA
            and item.verdict is CriterionVerdict.VIOLATED
            for item in self.assessments
        )


_LOADED_JUDGMENT_AUTHORITY = object()
_ISSUED_LOADED_JUDGMENTS: dict[int, "LoadedDurableJudgmentEvidence"] = {}


@dataclass(frozen=True)
class LoadedDurableJudgmentEvidence:
    """Freshly reverified judgment with its run and retained shared artifact."""

    judgment: CriterionJudgment
    loaded_run: object = field(repr=False, compare=False)
    _capability: object = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _LOADED_JUDGMENT_AUTHORITY:
            raise ValueError("Loaded judgment evidence is not verifier-issued.")

    def validate(self) -> bool:
        if _ISSUED_LOADED_JUDGMENTS.get(id(self)) is not self:
            return False
        try:
            self._capability.validate()
        except (OSError, ValueError):
            return False
        return bool(
            getattr(self.loaded_run, "validate", lambda: False)()
            and verify_criterion_judgment_identity(self.judgment)
            and self.judgment.run_sha256 == self.loaded_run.record.run_sha256
        )

    def close(self) -> None:
        """Revoke only this exact loaded judgment capability."""

        if _ISSUED_LOADED_JUDGMENTS.get(id(self)) is not self:
            return
        _ISSUED_LOADED_JUDGMENTS.pop(id(self), None)
        self._capability.close()


@dataclass(frozen=True)
class ComparisonDraft:
    control_run_sha256: str
    layered_run_sha256: str
    control_judgment_sha256: str
    layered_judgment_sha256: str
    relations: tuple[CriterionComparison, ...]
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _COMPARISON_DRAFT_AUTHORITY or not self.relations:
            raise ValueError("Comparison draft is not verifier-issued.")


def _criterion_judgment_identity_document(
    *,
    schema_version: str,
    run_sha256: str,
    assessor: str,
    assessor_evidence_sha256: str,
    signer_identity_sha256: str,
    oracle_sha256: str,
    private_rationale_commitment_sha256: str,
    assessments: tuple[CriterionAssessment, ...],
    hard_rejections: tuple[HardRejectionAssessment, ...],
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "run_sha256": run_sha256,
        "assessor": assessor,
        "assessor_evidence_sha256": assessor_evidence_sha256,
        "signer_identity_sha256": signer_identity_sha256,
        "oracle_sha256": oracle_sha256,
        "private_rationale_commitment_sha256": private_rationale_commitment_sha256,
        "assessments": [
            {
                "criterion": item.criterion,
                "verdict": item.verdict.value,
                "evidence_sha256": list(item.evidence_sha256),
                "content_receipt_sha256": list(item.content_receipt_sha256),
                "rationale_code": item.rationale_code,
                "private_rationale_commitment_sha256": (
                    item.rationale_commitment_sha256
                ),
            }
            for item in assessments
        ],
        "hard_rejections": [
            {
                "rule": item.rule,
                "triggered": item.triggered,
                "evidence_sha256": list(item.evidence_sha256),
            }
            for item in hard_rejections
        ],
    }


def criterion_judgment_document(judgment: CriterionJudgment) -> dict[str, object]:
    """Return the exact shared, value-suppressing judgment document."""

    if not verify_criterion_judgment_identity(judgment):
        raise ValueError("Criterion judgment is not authentic.")
    document = _criterion_judgment_identity_document(
        schema_version=judgment.schema_version,
        run_sha256=judgment.run_sha256,
        assessor=judgment.assessor,
        assessor_evidence_sha256=judgment.assessor_evidence_sha256,
        signer_identity_sha256=judgment.signer_identity_sha256,
        oracle_sha256=judgment.oracle_sha256,
        private_rationale_commitment_sha256=(
            judgment.private_rationale_commitment_sha256
        ),
        assessments=judgment.assessments,
        hard_rejections=judgment.hard_rejections,
    )
    return {**document, "judgment_sha256": judgment.judgment_sha256}


def verify_criterion_judgment_identity(judgment: CriterionJudgment) -> bool:
    if getattr(judgment, "_authority", None) is not _JUDGMENT_AUTHORITY:
        return False
    document = _criterion_judgment_identity_document(
        schema_version=judgment.schema_version,
        run_sha256=judgment.run_sha256,
        assessor=judgment.assessor,
        assessor_evidence_sha256=judgment.assessor_evidence_sha256,
        signer_identity_sha256=judgment.signer_identity_sha256,
        oracle_sha256=judgment.oracle_sha256,
        private_rationale_commitment_sha256=(
            judgment.private_rationale_commitment_sha256
        ),
        assessments=judgment.assessments,
        hard_rejections=judgment.hard_rejections,
    )
    return (
        judgment.judgment_sha256 == canonical_sha256(document)
        and _JUDGMENT_SEALS.get(judgment._seal) == judgment.judgment_sha256
    )


def load_durable_criterion_judgment(
    root: Path,
    artifact_sha256: str,
    *,
    loaded_run: object,
    loaded_fixture: LoadedFixture,
    output_text: str,
    evidence_vault: Path,
    authorization_sha256: str,
    signature_sha256: str,
) -> LoadedDurableJudgmentEvidence | None:
    """Reload and reseal a judgment from durable run and signed private evidence."""

    from cc.core.evaluation.artifact import (
        LoadedDurableRunEvidence,
        _open_linked_document,
        _open_root_directory,
    )

    if (
        not isinstance(loaded_run, LoadedDurableRunEvidence)
        or not loaded_run.validate()
    ):
        return None
    root_fd: int | None = None
    capability = None
    try:
        authorization = load_assessor_authorization(
            loaded_run.record,
            evidence_vault=evidence_vault,
            authorization_sha256=authorization_sha256,
            signature_sha256=signature_sha256,
        )
        assessment = json.loads(authorization._assessment_document_json)
        if not isinstance(assessment, Mapping):
            return None
        rebuilt = build_criterion_judgment(
            loaded_run.record,
            loaded_fixture,
            output_text,
            assessment,
            assessor_authorization=authorization,
        )
        root_fd = _open_root_directory(root)
        document, capability = _open_linked_document(
            root_fd,
            "criterion-judgment",
            artifact_sha256,
        )
        if document != criterion_judgment_document(rebuilt):
            return None
        loaded = LoadedDurableJudgmentEvidence(
            rebuilt,
            loaded_run,
            capability,
            _LOADED_JUDGMENT_AUTHORITY,
        )
        _ISSUED_LOADED_JUDGMENTS[id(loaded)] = loaded
        capability = None
        if not loaded.validate():
            loaded._capability.close()
            return None
        return loaded
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if capability is not None:
            capability.close()
        if root_fd is not None:
            os.close(root_fd)


def _span_evidence(span: object, *, output_text: str, output_sha256: str) -> str:
    if not isinstance(span, Mapping) or set(span) != _SPAN_KEYS:
        raise ValueError("Criterion evidence span is malformed.")
    start, end, declared = span.get("start"), span.get("end"), span.get("sha256")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 0
        or end <= start
        or end > len(output_text)
        or not isinstance(declared, str)
    ):
        raise ValueError("Criterion evidence span is malformed.")
    selected = output_text[start:end]
    if hashlib.sha256(selected.encode()).hexdigest() != declared:
        raise ValueError("Criterion evidence span digest changed.")
    return canonical_sha256(
        {
            "output_sha256": output_sha256,
            "start": start,
            "end": end,
            "span_sha256": declared,
        }
    )


def build_criterion_judgment(
    record: RunRecord,
    loaded: LoadedFixture,
    output_text: str,
    document: Mapping[str, Any],
    *,
    assessor_authorization: AssessorAuthorization | None = None,
) -> CriterionJudgment:
    """Validate exact criteria and cited output spans; never infer a score."""

    if (
        not verify_run_record_identity(record)
        or record.state is not RunState.COMPLETED
        or record.output_sha256 != hashlib.sha256(output_text.encode()).hexdigest()
        or not verify_loaded_fixture(loaded)
        or loaded.fixture_sha256 != record.fixture_sha256
        or loaded.fixture.case_id != record.case_id
        or set(document) != _DOCUMENT_KEYS
        or document.get("schema_version") != "1.0"
        or document.get("run_sha256") != record.run_sha256
        or document.get("assessor") not in _ASSESSORS
        or not isinstance(assessor_authorization, AssessorAuthorization)
        or not _verify_assessor_authorization(assessor_authorization)
        or assessor_authorization.run_sha256 != record.run_sha256
        or assessor_authorization.assessor != document.get("assessor")
        or assessor_authorization.assessment_document_sha256
        != canonical_sha256(document)
        or assessor_authorization.oracle_sha256 != loaded.oracle.sha256
        or document.get("oracle_sha256") != loaded.oracle.sha256
    ):
        raise ValueError("Criterion judgment is not bound to a completed run.")
    raw_criteria = document.get("criteria")
    if not isinstance(raw_criteria, list):
        raise ValueError("Criterion judgment criteria are malformed.")
    assessments: list[CriterionAssessment] = []
    authorized_rationales = dict(assessor_authorization.private_rationale_commitments)
    for item in raw_criteria:
        if not isinstance(item, Mapping) or set(item) != _CRITERION_KEYS:
            raise ValueError("Criterion judgment criteria are malformed.")
        spans = item.get("spans")
        if not isinstance(spans, list) or not spans:
            raise ValueError("Criterion judgment requires cited output spans.")
        verdict = CriterionVerdict(str(item.get("verdict", "")))
        rationale_code = str(item.get("rationale_code", ""))
        if (
            rationale_code
            != {
                CriterionVerdict.DEMONSTRATED: "evidence-supports-verdict",
                CriterionVerdict.PARTIAL: "evidence-partially-supports-verdict",
                CriterionVerdict.ABSENT: "no-supporting-evidence",
                CriterionVerdict.VIOLATED: "evidence-shows-violation",
            }[verdict]
        ):
            raise ValueError("Criterion rationale does not match its verdict.")
        criterion = str(item.get("criterion", ""))
        rationale_commitment_sha256 = str(
            item.get("private_rationale_commitment_sha256", "")
        )
        if authorized_rationales.get(criterion) != rationale_commitment_sha256:
            raise ValueError("Private rationale is not signed assessor evidence.")
        assessments.append(
            CriterionAssessment(
                criterion=criterion,
                verdict=verdict,
                evidence_sha256=tuple(
                    _span_evidence(
                        span,
                        output_text=output_text,
                        output_sha256=record.output_sha256,
                    )
                    for span in spans
                ),
                content_receipt_sha256=(record.content_receipt_sha256,),
                rationale_code=rationale_code,
                rationale_commitment_sha256=rationale_commitment_sha256,
            )
        )
    criteria = tuple(item.criterion for item in assessments)
    if criteria != loaded.fixture.required_criteria or len(set(criteria)) != len(
        criteria
    ):
        raise ValueError(
            "Criterion judgment must cover exact required criteria in order."
        )

    raw_rejections = document.get("hard_rejections")
    if not isinstance(raw_rejections, list):
        raise ValueError("Hard-rejection judgments are malformed.")
    observed_rules: list[str] = []
    triggered: list[str] = []
    rejection_evidence: list[HardRejectionAssessment] = []
    for item in raw_rejections:
        if not isinstance(item, Mapping) or set(item) != _REJECTION_KEYS:
            raise ValueError("Hard-rejection judgments are malformed.")
        rule, state, spans = item.get("rule"), item.get("triggered"), item.get("spans")
        if (
            not isinstance(rule, str)
            or not isinstance(state, bool)
            or not isinstance(spans, list)
            or (state and not spans)
            or (not state and spans)
        ):
            raise ValueError("Hard-rejection judgments are malformed.")
        evidence = tuple(
            _span_evidence(
                span, output_text=output_text, output_sha256=record.output_sha256
            )
            for span in spans
        )
        observed_rules.append(rule)
        if state:
            triggered.append(rule)
        rejection_evidence.append(
            HardRejectionAssessment(
                rule=rule,
                triggered=state,
                evidence_sha256=evidence,
            )
        )
    if tuple(observed_rules) != loaded.fixture.hard_rejection_rules:
        raise ValueError("Judgment must cover exact hard-rejection rules in order.")
    try:
        oracle = json.loads(loaded.oracle.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Private oracle is malformed.") from exc
    if (
        not isinstance(oracle, Mapping)
        or tuple(oracle.get("reject_conditions") or ())
        != loaded.fixture.hard_rejection_rules
    ):
        raise ValueError("Private oracle rejection contract changed.")
    prohibited = oracle.get("prohibited_shared_markers") or ()
    if not isinstance(prohibited, list) or any(
        not isinstance(marker, str) or not marker for marker in prohibited
    ):
        prohibited = []
    detected = {
        marker.casefold()
        for marker in prohibited
        if marker.casefold() in output_text.casefold()
    }
    if detected and "upward-personal-disclosure" not in triggered:
        raise ValueError("Private oracle detected an unreported hard rejection.")
    identity_document = _criterion_judgment_identity_document(
        schema_version="1.0",
        run_sha256=record.run_sha256,
        assessor=str(document["assessor"]),
        assessor_evidence_sha256=assessor_authorization.evidence_sha256,
        signer_identity_sha256=assessor_authorization.signer_identity_sha256,
        oracle_sha256=assessor_authorization.oracle_sha256,
        private_rationale_commitment_sha256=(
            assessor_authorization.private_rationale_commitment_sha256
        ),
        assessments=tuple(assessments),
        hard_rejections=tuple(rejection_evidence),
    )
    seal = object()
    judgment = CriterionJudgment(
        schema_version="1.0",
        run_sha256=record.run_sha256,
        assessor=str(document["assessor"]),
        assessor_evidence_sha256=assessor_authorization.evidence_sha256,
        signer_identity_sha256=assessor_authorization.signer_identity_sha256,
        oracle_sha256=assessor_authorization.oracle_sha256,
        private_rationale_commitment_sha256=(
            assessor_authorization.private_rationale_commitment_sha256
        ),
        assessments=tuple(assessments),
        hard_rejections=tuple(rejection_evidence),
        triggered_rejections=tuple(triggered),
        judgment_sha256=canonical_sha256(identity_document),
        _seal=seal,
        _authority=_JUDGMENT_AUTHORITY,
    )
    _JUDGMENT_SEALS[seal] = judgment.judgment_sha256
    return judgment


def compare_criterion_judgments(
    control_record: RunRecord,
    layered_record: RunRecord,
    control: CriterionJudgment,
    layered: CriterionJudgment,
) -> ComparisonDraft:
    if (
        not verify_criterion_judgment_identity(control)
        or not verify_criterion_judgment_identity(layered)
        or control.run_sha256 != control_record.run_sha256
        or layered.run_sha256 != layered_record.run_sha256
        or not control.hard_gate_passed
        or not layered.hard_gate_passed
    ):
        raise ValueError("Hard-rejected or mismatched judgments cannot be compared.")
    control_by_criterion = {item.criterion: item for item in control.assessments}
    layered_by_criterion = {item.criterion: item for item in layered.assessments}
    if tuple(control_by_criterion) != tuple(layered_by_criterion):
        raise ValueError("Control and layered criteria differ.")
    relations = []
    for criterion, control_item in control_by_criterion.items():
        layered_item = layered_by_criterion[criterion]
        control_order = _VERDICT_ORDER[control_item.verdict]
        layered_order = _VERDICT_ORDER[layered_item.verdict]
        relation = (
            CriterionRelation.IMPROVED
            if layered_order > control_order
            else (
                CriterionRelation.REGRESSED
                if layered_order < control_order
                else CriterionRelation.SAME
            )
        )
        if relation is CriterionRelation.REGRESSED or (
            layered_item.verdict is CriterionVerdict.VIOLATED
            and control_item.verdict is not CriterionVerdict.VIOLATED
        ):
            raise ValueError(
                "Protected criterion regression rejects the layered comparison."
            )
        relations.append(
            CriterionComparison(
                criterion=criterion,
                relation=relation,
                control_evidence_sha256=control_item.evidence_sha256,
                layered_evidence_sha256=layered_item.evidence_sha256,
            )
        )
    return ComparisonDraft(
        control_run_sha256=control_record.run_sha256,
        layered_run_sha256=layered_record.run_sha256,
        control_judgment_sha256=control.judgment_sha256,
        layered_judgment_sha256=layered.judgment_sha256,
        relations=tuple(relations),
        _authority=_COMPARISON_DRAFT_AUTHORITY,
    )


def issue_durable_comparison(
    root: Path,
    *,
    control: LoadedDurableJudgmentEvidence,
    layered: LoadedDurableJudgmentEvidence,
    draft: ComparisonDraft,
) -> tuple[ComparisonRecord, object]:
    """Issue and persist a comparison only from reloaded durable judgments."""

    if (
        not isinstance(control, LoadedDurableJudgmentEvidence)
        or not isinstance(layered, LoadedDurableJudgmentEvidence)
        or not control.validate()
        or not layered.validate()
        or not isinstance(draft, ComparisonDraft)
        or draft._authority is not _COMPARISON_DRAFT_AUTHORITY
        or draft.control_run_sha256 != control.judgment.run_sha256
        or draft.layered_run_sha256 != layered.judgment.run_sha256
        or draft.control_judgment_sha256 != control.judgment.judgment_sha256
        or draft.layered_judgment_sha256 != layered.judgment.judgment_sha256
    ):
        raise ValueError("Comparison issuance requires exact durable judgments.")
    expected = compare_criterion_judgments(
        control.loaded_run.record,
        layered.loaded_run.record,
        control.judgment,
        layered.judgment,
    )
    if draft != expected:
        raise ValueError("Comparison draft differs from durable judgments.")
    record = pair_control_runs(
        control.loaded_run.record,
        layered.loaded_run.record,
        relations=expected.relations,
        control_judgment_sha256=expected.control_judgment_sha256,
        layered_judgment_sha256=expected.layered_judgment_sha256,
        _judgment_authority=_JUDGMENT_COMPARISON_AUTHORITY,
    )
    from cc.core.evaluation.artifact import write_comparison_record

    receipt = write_comparison_record(
        root,
        record,
        control_judgment=control,
        layered_judgment=layered,
    )
    return record, receipt


def _load_durable_comparison(
    root: Path,
    artifact_sha256: str,
    *,
    control: LoadedDurableJudgmentEvidence,
    layered: LoadedDurableJudgmentEvidence,
) -> tuple[ComparisonRecord, object] | None:
    """Private loader used only by the composite durable-evidence verifier."""

    if (
        len(artifact_sha256) != 64
        or any(character not in "0123456789abcdef" for character in artifact_sha256)
        or not isinstance(control, LoadedDurableJudgmentEvidence)
        or not isinstance(layered, LoadedDurableJudgmentEvidence)
        or not control.validate()
        or not layered.validate()
    ):
        return None
    from cc.core.evaluation.artifact import (
        _issue_artifact_receipt,
        _open_linked_document,
        _open_root_directory,
    )
    from cc.core.evaluation.comparison import comparison_record_document

    root_fd: int | None = None
    capability = None
    try:
        draft = compare_criterion_judgments(
            control.loaded_run.record,
            layered.loaded_run.record,
            control.judgment,
            layered.judgment,
        )
        root_fd = _open_root_directory(root)
        document, capability = _open_linked_document(
            root_fd,
            "comparison-record",
            artifact_sha256,
        )
        if not control.validate() or not layered.validate():
            return None
        record = pair_control_runs(
            control.loaded_run.record,
            layered.loaded_run.record,
            relations=draft.relations,
            control_judgment_sha256=draft.control_judgment_sha256,
            layered_judgment_sha256=draft.layered_judgment_sha256,
            _judgment_authority=_JUDGMENT_COMPARISON_AUTHORITY,
        )
        if document != comparison_record_document(record):
            return None
        capability.validate()
        if not control.validate() or not layered.validate():
            return None
        receipt = _issue_artifact_receipt(
            artifact_type="comparison-record",
            sha256=artifact_sha256,
            relative_path=f"comparison-record/{artifact_sha256}.json",
            size_bytes=len(canonical_json_bytes(document)),
            capability=capability,
        )
        capability = None
        return record, receipt
    except (OSError, TypeError, ValueError):
        return None
    finally:
        if capability is not None:
            capability.close()
        if root_fd is not None:
            os.close(root_fd)


__all__ = [
    "CriterionJudgment",
    "build_criterion_judgment",
    "compare_criterion_judgments",
    "load_assessor_authorization",
]
