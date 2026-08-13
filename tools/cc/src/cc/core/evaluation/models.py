"""Closed, immutable models for evaluation inputs and evidence artifacts.

Knowledge resolution, entitlement, and journey truth remain verifier-owned;
these records bind their disclosed evidence without inferring it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,255}$")
_REPOSITORY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)
_SIGNER = re.compile(r"^SHA256:[A-Za-z0-9+/=_-]{8,128}$")
_DISCLOSURE = re.compile(
    r"(?i)(?:^|[/._-])(?:users|home|private|tmp|var|volumes)(?:[/._-]|$)|"
    r"(?:password|secret|token|credential|api[_-]?key)|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
)
_EVIDENCE_AUTHORITY = object()
_RUN_RECORD_AUTHORITY = object()
_COMPARISON_AUTHORITY = object()


def _digest(value: str, field_name: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest.")


def _identifier(value: str, field_name: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier.")


def _reference(value: str, field_name: str) -> None:
    if (
        not _SAFE_REFERENCE.fullmatch(value)
        or ".." in value.split("/")
        or _DISCLOSURE.search(value)
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
    ):
        raise ValueError(f"{field_name} must be a safe immutable reference.")


def _relative_path(value: str, field_name: str) -> None:
    parts = value.split("/")
    if (
        not value
        or not value.isascii()
        or value.startswith("/")
        or "\\" in value
        or "%" in value
        or any(part in {"", ".", ".."} for part in parts)
        or _DISCLOSURE.search(value)
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)
    ):
        raise ValueError(f"{field_name} must be an exact relative path.")


def _safe_statement(value: str, field_name: str) -> None:
    if (
        not value
        or len(value) > 2048
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded printable statement.")


class LayerVariant(str, Enum):
    FOUNDATION = "F"
    ORGANIZATION = "F+O"
    DEPARTMENT = "F+O+D"
    PERSONAL = "F+O+D+P"


class RuntimeName(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"


class PreflightState(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"


class GateState(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNSUPPORTED = "unsupported"


class PreflightGate(str, Enum):
    FIXTURE_CONTRACT = "fixture-contract"
    ENTITLEMENT_AND_PINS = "entitlement-and-pins"
    RESOLUTION_IDENTITY = "resolution-identity"
    RUNTIME_ADAPTER = "runtime-adapter"
    JOURNEY_EVIDENCE = "journey-evidence"
    REQUIRED_CONTENT = "required-content"
    SAFETY_SCAN = "safety-scan"
    PERSONAL_NON_LEAKAGE = "personal-non-leakage"
    NO_EXTERNAL_MUTATION = "no-external-mutation"
    ATTEMPT_POLICY = "attempt-policy"
    RUNTIME_CAPABILITY = "runtime-capability"


class RunState(str, Enum):
    COMPLETED = "completed"
    DISPATCH_AUTHORIZED = "dispatch-authorized"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"
    TECHNICAL_ERROR = "technical-error"


class CriterionVerdict(str, Enum):
    DEMONSTRATED = "demonstrated"
    PARTIAL = "partial"
    ABSENT = "absent"
    VIOLATED = "violated"


class CriterionRelation(str, Enum):
    IMPROVED = "improved"
    SAME = "same"
    REGRESSED = "regressed"
    NOT_COMPARABLE = "not-comparable"


@dataclass(frozen=True)
class EvidenceFile:
    path: str
    sha256: str
    media_type: str
    synthetic_fixture: bool
    fixture_namespace: str


@dataclass(frozen=True)
class PrivateOracle:
    path: str
    sha256: str


@dataclass(frozen=True)
class EvaluationFixture:
    schema_version: str
    case_id: str
    revision: int
    fixture_namespace: str
    problem_statement: str
    evidence_files: tuple[EvidenceFile, ...]
    layer_variants: tuple[LayerVariant, ...]
    runtimes: tuple[RuntimeName, ...]
    required_criteria: tuple[str, ...]
    hard_rejection_rules: tuple[str, ...]
    journey_requirements: tuple[str, ...]
    private_oracle: PrivateOracle

    @classmethod
    def from_validated_mapping(cls, value: Mapping[str, Any]) -> EvaluationFixture:
        """Construct from a mapping already accepted by fixture.schema.json."""

        evidence = tuple(EvidenceFile(**item) for item in value["evidence_files"])
        return cls(
            schema_version=value["schema_version"],
            case_id=value["case_id"],
            revision=value["revision"],
            fixture_namespace=value["fixture_namespace"],
            problem_statement=value["problem_statement"],
            evidence_files=evidence,
            layer_variants=tuple(
                LayerVariant(item) for item in value["layer_variants"]
            ),
            runtimes=tuple(RuntimeName(item) for item in value["runtimes"]),
            required_criteria=tuple(value["required_criteria"]),
            hard_rejection_rules=tuple(value["hard_rejection_rules"]),
            journey_requirements=tuple(value["journey_requirements"]),
            private_oracle=PrivateOracle(**value["private_oracle"]),
        )


@dataclass(frozen=True)
class RuntimeReceipt:
    runtime: RuntimeName
    executable_sha256: str
    runtime_version: str | None
    model_version: str | None
    tool_availability: tuple[str, ...]
    adapter_name: str
    adapter_version: str
    capability_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.executable_sha256, "executable_sha256")
        _identifier(self.adapter_name, "adapter_name")
        _reference(self.adapter_version, "adapter_version")
        for name in self.tool_availability + self.capability_flags:
            _identifier(name, "runtime capability")
        if tuple(sorted(set(self.tool_availability))) != self.tool_availability:
            raise ValueError("tool_availability must be sorted and unique.")
        if tuple(sorted(set(self.capability_flags))) != self.capability_flags:
            raise ValueError("capability_flags must be sorted and unique.")
        for version in (self.runtime_version, self.model_version):
            if version is not None:
                _reference(version, "reported version")


@dataclass(frozen=True)
class LayerContentReceipt:
    product: str
    tier: str
    repository_identifier: str
    immutable_ref: str
    tree_sha256: str
    signer_identity: str
    policy_sha256: str
    manifest_sha256: str
    lock_sha256: str
    contribution_ids: tuple[str, ...]
    content_digests: tuple[str, ...]
    resolution_action: str
    materialized_destinations: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.product, "product")
        _identifier(self.tier, "tier")
        if not _REPOSITORY.fullmatch(self.repository_identifier):
            raise ValueError(
                "repository_identifier must be a canonical owner/repository."
            )
        _reference(self.repository_identifier, "repository_identifier")
        _reference(self.immutable_ref, "immutable_ref")
        if not (
            self.immutable_ref.startswith("refs/tags/")
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.immutable_ref)
        ):
            raise ValueError("immutable_ref must be a signed tag or content object.")
        if not _SIGNER.fullmatch(self.signer_identity):
            raise ValueError("signer_identity must be a verified signer fingerprint.")
        _identifier(self.resolution_action, "resolution_action")
        for field_name in (
            "tree_sha256",
            "policy_sha256",
            "manifest_sha256",
            "lock_sha256",
        ):
            _digest(getattr(self, field_name), field_name)
        if not self.contribution_ids or not self.content_digests:
            raise ValueError(
                "Consumed layers require contributions and content digests."
            )
        if tuple(sorted(set(self.contribution_ids))) != self.contribution_ids:
            raise ValueError("contribution_ids must be sorted and unique.")
        if tuple(sorted(set(self.content_digests))) != self.content_digests:
            raise ValueError("content_digests must be sorted and unique.")
        for contribution in self.contribution_ids:
            _reference(contribution, "contribution_id")
        for digest in self.content_digests:
            _digest(digest, "content_digest")
        if (
            tuple(sorted(set(self.materialized_destinations)))
            != self.materialized_destinations
        ):
            raise ValueError("materialized_destinations must be sorted and unique.")
        for destination in self.materialized_destinations:
            _relative_path(destination, "materialized_destination")


@dataclass(frozen=True)
class ContentReceipt:
    variant: LayerVariant
    entitlement_receipt_sha256: str
    layers: tuple[LayerContentReceipt, ...]
    composed_content_sha256: str
    materialization_sha256: str

    def __post_init__(self) -> None:
        _digest(self.entitlement_receipt_sha256, "entitlement_receipt_sha256")
        _digest(self.composed_content_sha256, "composed_content_sha256")
        _digest(self.materialization_sha256, "materialization_sha256")
        if not self.layers:
            raise ValueError(
                "Content receipt must identify at least one consumed layer."
            )
        identities = tuple(
            (layer.product, layer.tier, layer.repository_identifier)
            for layer in self.layers
        )
        if len(identities) != len(set(identities)):
            raise ValueError("Content receipt layers must be unique.")
        expected_tiers = {
            LayerVariant.FOUNDATION: ("foundation",),
            LayerVariant.ORGANIZATION: ("foundation", "organization"),
            LayerVariant.DEPARTMENT: ("foundation", "organization", "department"),
            LayerVariant.PERSONAL: (
                "foundation",
                "organization",
                "department",
                "personal",
            ),
        }[self.variant]
        if tuple(layer.tier for layer in self.layers) != expected_tiers:
            raise ValueError(
                "Content receipt layers do not match the declared variant."
            )


@dataclass(frozen=True)
class ConsumptionReceipt:
    task_id: int
    runtime_receipt_sha256: str
    content_receipt_sha256: str
    prompt_evidence_sha256: str
    invocation_envelope_sha256: str
    journey_evidence_sha256: str
    route_evidence_sha256: str
    continuity_evidence_sha256: str

    def __post_init__(self) -> None:
        if self.task_id < 1:
            raise ValueError("task_id must be positive.")
        for field_name in (
            "runtime_receipt_sha256",
            "content_receipt_sha256",
            "prompt_evidence_sha256",
            "invocation_envelope_sha256",
            "journey_evidence_sha256",
            "route_evidence_sha256",
            "continuity_evidence_sha256",
        ):
            _digest(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class GateObservation:
    gate: PreflightGate
    state: GateState
    reason: str
    actor: str
    prerequisite: str
    _authority: object = None

    def __post_init__(self) -> None:
        _identifier(self.reason, "gate reason")
        _identifier(self.actor, "gate actor")
        _identifier(self.prerequisite, "gate prerequisite")
        if self.state is GateState.PASS and self._authority is not _EVIDENCE_AUTHORITY:
            raise ValueError("Passing gate evidence must be verifier-issued.")


@dataclass(frozen=True)
class PreflightResult:
    state: PreflightState
    observations: tuple[GateObservation, ...]
    subject_sha256: str
    result_sha256: str
    _authority: object = None

    def __post_init__(self) -> None:
        _digest(self.subject_sha256, "subject_sha256")
        _digest(self.result_sha256, "result_sha256")
        if (
            self.state is PreflightState.VALID
            and self._authority is not _EVIDENCE_AUTHORITY
        ):
            raise ValueError("Valid preflight results must be verifier-issued.")


@dataclass(frozen=True)
class EvaluationCell:
    case_id: str
    revision: int
    fixture_sha256: str
    prompt_evidence_sha256: str
    variant: LayerVariant
    runtime_receipt: RuntimeReceipt
    content_receipt: ContentReceipt
    consumption_receipt: ConsumptionReceipt
    attempt: int
    attempt_policy_sha256: str
    runtime_configuration_sha256: str
    tool_configuration_sha256: str
    parent_attempt_sha256: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"eval-[0-9]{2}", self.case_id):
            raise ValueError("case_id must use the eval-NN contract.")
        if self.revision < 1 or self.attempt < 1:
            raise ValueError("revision and attempt must be positive.")
        for field_name in (
            "fixture_sha256",
            "prompt_evidence_sha256",
            "attempt_policy_sha256",
            "runtime_configuration_sha256",
            "tool_configuration_sha256",
        ):
            _digest(getattr(self, field_name), field_name)
        if self.parent_attempt_sha256 is not None:
            _digest(self.parent_attempt_sha256, "parent_attempt_sha256")


@dataclass(frozen=True)
class RuntimeOutput:
    output_text: str
    controlled_artifact_path: str
    output_location_class: str

    def __post_init__(self) -> None:
        _relative_path(self.controlled_artifact_path, "controlled_artifact_path")
        if self.output_location_class not in {"private-output", "shared-output"}:
            raise ValueError("output_location_class is not supported.")


@dataclass(frozen=True)
class RunRecord:
    schema_version: str
    run_sha256: str
    case_id: str
    revision: int
    variant: LayerVariant
    runtime: RuntimeName
    attempt: int
    parent_attempt_sha256: str | None
    fixture_sha256: str
    prompt_evidence_sha256: str
    attempt_policy_sha256: str
    runtime_configuration_sha256: str
    tool_configuration_sha256: str
    comparability_sha256: str
    runtime_receipt_sha256: str
    content_receipt_sha256: str
    consumption_receipt_sha256: str
    preflight: PreflightResult
    state: RunState
    output_sha256: str | None
    controlled_artifact_path: str | None
    completion_evidence_sha256: str | None
    technical_error_reason: str | None
    _authority: object = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.2":
            raise ValueError("Run record schema_version must be exactly 1.2.")
        if self._authority is not _RUN_RECORD_AUTHORITY:
            raise ValueError("Run records must be runner-issued.")


@dataclass(frozen=True)
class CriterionAssessment:
    criterion: str
    verdict: CriterionVerdict
    evidence_sha256: tuple[str, ...]
    content_receipt_sha256: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        _identifier(self.criterion, "criterion")
        _safe_statement(self.rationale, "rationale")
        if not self.evidence_sha256:
            raise ValueError("Criterion assessments require cited evidence.")
        for digest in self.evidence_sha256 + self.content_receipt_sha256:
            _digest(digest, "assessment evidence")


@dataclass(frozen=True)
class CriterionComparison:
    criterion: str
    relation: CriterionRelation
    control_evidence_sha256: tuple[str, ...]
    layered_evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.criterion, "criterion")
        for digest in self.control_evidence_sha256 + self.layered_evidence_sha256:
            _digest(digest, "comparison evidence")


@dataclass(frozen=True)
class ComparisonRecord:
    schema_version: str
    comparison_sha256: str
    comparability_sha256: str
    control_run_sha256: str
    layered_run_sha256: str
    relations: tuple[CriterionComparison, ...]
    hard_gate_state: PreflightState
    _authority: object = None

    def __post_init__(self) -> None:
        if self._authority is not _COMPARISON_AUTHORITY:
            raise ValueError("Comparison records must be coordinator-issued.")


@dataclass(frozen=True)
class ArtifactReceipt:
    artifact_type: str
    sha256: str
    relative_path: str
    size_bytes: int

    def __post_init__(self) -> None:
        _identifier(self.artifact_type, "artifact_type")
        _digest(self.sha256, "artifact sha256")
        _relative_path(self.relative_path, "artifact relative_path")
        if self.size_bytes < 1:
            raise ValueError("Artifact must not be empty.")
