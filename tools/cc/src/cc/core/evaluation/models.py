"""Closed, immutable models for evaluation inputs and evidence artifacts.

Knowledge resolution, entitlement, and journey truth remain verifier-owned;
these records bind their disclosed evidence without inferring it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
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
_CONTENT_RESOLUTION_ACTIONS = frozenset(
    {"accumulated", "selected", "shadowed", "authenticated-absence"}
)


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
    model_version: str
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
        if self.runtime_version is not None:
            _reference(self.runtime_version, "reported version")
        _reference(self.model_version, "preregistered model")


@dataclass(frozen=True)
class LayerContentReceipt:
    product: str
    tier: str
    source_layer_identifier: str
    source_runtime: str
    source_adapter_version: str
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
    source_tree: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.product, "product")
        _identifier(self.tier, "tier")
        _identifier(self.source_layer_identifier, "source_layer_identifier")
        _identifier(self.source_runtime, "source_runtime")
        _reference(self.source_adapter_version, "source_adapter_version")
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
        if self.resolution_action not in _CONTENT_RESOLUTION_ACTIONS:
            raise ValueError("resolution_action is not a canonical layer decision.")
        for field_name in (
            "tree_sha256",
            "policy_sha256",
            "manifest_sha256",
            "lock_sha256",
        ):
            _digest(getattr(self, field_name), field_name)
        if self.source_tree is not None and not re.fullmatch(
            r"[0-9a-f]{40,64}", self.source_tree
        ):
            raise ValueError("source_tree must be an exact Git tree object id.")
        if self.resolution_action == "authenticated-absence":
            if self.contribution_ids or self.content_digests:
                raise ValueError("Authenticated absence cannot claim a contribution.")
        elif not self.contribution_ids or not self.content_digests:
            raise ValueError(
                "Contributing layers require contributions and content digests."
            )
        if len(self.contribution_ids) != len(self.content_digests):
            raise ValueError("Contributions and content digests require exact pairing.")
        if tuple(sorted(set(self.contribution_ids))) != self.contribution_ids:
            raise ValueError("contribution_ids must be sorted and unique.")
        if len(set(self.content_digests)) != len(self.content_digests):
            raise ValueError("content_digests must be unique.")
        for contribution in self.contribution_ids:
            _relative_path(contribution, "contribution_id")
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
            (
                layer.product,
                layer.tier,
                layer.repository_identifier,
                layer.immutable_ref,
                layer.tree_sha256,
            )
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
        actual_tiers = tuple(dict.fromkeys(layer.tier for layer in self.layers))
        if actual_tiers != expected_tiers:
            raise ValueError(
                "Content receipt layers do not match the declared variant."
            )
        tier_order = {tier: index for index, tier in enumerate(expected_tiers)}
        ordering = tuple(
            (
                tier_order[layer.tier],
                layer.product,
                layer.repository_identifier,
                layer.immutable_ref,
                layer.tree_sha256,
            )
            for layer in self.layers
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError(
                "Content receipt layers must use canonical tier and product order."
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
    effective_full_prompt_sha256: str
    command_policy_sha256: str
    parent_attempt_sha256: str | None = None

    def __post_init__(self) -> None:
        from cc.core.evaluation.attempt_policy import (
            ATTEMPT_POLICY_SHA256,
            MAX_ATTEMPTS,
        )

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
            "effective_full_prompt_sha256",
            "command_policy_sha256",
        ):
            _digest(getattr(self, field_name), field_name)
        if self.attempt_policy_sha256 != ATTEMPT_POLICY_SHA256:
            raise ValueError("Evaluation cell attempt policy is not canonical.")
        if self.attempt > MAX_ATTEMPTS:
            raise ValueError("Evaluation cell exceeds the canonical retry limit.")
        if (self.attempt == 1) != (self.parent_attempt_sha256 is None):
            raise ValueError("Evaluation cell retry parent shape is invalid.")
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
        runtime_product = f"{self.runtime_receipt.runtime.value}-copilot"
        for tier in expected_tiers:
            knowledge_layers = [
                layer
                for layer in self.content_receipt.layers
                if layer.tier == tier and layer.product == "knowledge"
            ]
            if len(knowledge_layers) != 1:
                raise ValueError(
                    "Evaluation cells require exactly one Knowledge product for "
                    "every declared tier."
                )
        allowed_products = {"knowledge", runtime_product}
        if any(
            layer.product not in allowed_products
            for layer in self.content_receipt.layers
        ):
            raise ValueError("Evaluation cells contain an unrelated layer product.")
        runtime_layers = []
        for tier in expected_tiers:
            matches = [
                layer
                for layer in self.content_receipt.layers
                if layer.tier == tier and layer.product == runtime_product
            ]
            if len(matches) != 1:
                raise ValueError(
                    "Evaluation cells require exactly one runtime resolution "
                    "attestation for every declared tier."
                )
            runtime_layers.extend(matches)
        selected_runtime = [
            layer for layer in runtime_layers if layer.resolution_action == "selected"
        ]
        zero_call_codex = bool(
            self.runtime_receipt.runtime is RuntimeName.CODEX
            and not selected_runtime
            and all(
                layer.resolution_action == "authenticated-absence"
                for layer in runtime_layers
            )
            and all(
                layer.resolution_action == "authenticated-absence"
                for layer in self.content_receipt.layers
                if layer.product == "knowledge"
            )
        )
        if len(selected_runtime) != 1 and not zero_call_codex:
            raise ValueError(
                "Evaluation cells require one exact nearest-wins runtime specialist."
            )
        if not zero_call_codex:
            selected_index = expected_tiers.index(selected_runtime[0].tier)
            for index, layer in enumerate(runtime_layers):
                if index == selected_index:
                    continue
                allowed_action = (
                    {"shadowed", "authenticated-absence"}
                    if index < selected_index
                    else {"authenticated-absence"}
                )
                if layer.resolution_action not in allowed_action:
                    raise ValueError(
                        "Runtime resolution attestations do not prove nearest-wins "
                        "selection and inheritance."
                    )
        for layer in self.content_receipt.layers:
            if layer.product == "knowledge" and layer.resolution_action not in {
                "accumulated",
                "shadowed",
                "authenticated-absence",
            }:
                raise ValueError(
                    "Knowledge resolution attestations must accumulate, shadow, or "
                    "prove absence."
                )
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
    effective_full_prompt_sha256: str
    command_policy_sha256: str
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
    technical_error_evidence_sha256: str | None
    _authority: object = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.4":
            raise ValueError("Run record schema_version must be exactly 1.4.")
        if self._authority is not _RUN_RECORD_AUTHORITY:
            raise ValueError("Run records must be runner-issued.")
        for field_name in (
            "run_sha256",
            "fixture_sha256",
            "prompt_evidence_sha256",
            "attempt_policy_sha256",
            "runtime_configuration_sha256",
            "tool_configuration_sha256",
            "effective_full_prompt_sha256",
            "command_policy_sha256",
            "comparability_sha256",
            "runtime_receipt_sha256",
            "content_receipt_sha256",
            "consumption_receipt_sha256",
        ):
            _digest(getattr(self, field_name), field_name)
        if self.parent_attempt_sha256 is not None:
            _digest(self.parent_attempt_sha256, "parent_attempt_sha256")
        if self.output_sha256 is not None:
            _digest(self.output_sha256, "output_sha256")
        if self.completion_evidence_sha256 is not None:
            _digest(
                self.completion_evidence_sha256,
                "completion_evidence_sha256",
            )
        if self.controlled_artifact_path is not None:
            _relative_path(self.controlled_artifact_path, "controlled_artifact_path")
        if self.technical_error_reason is not None:
            _identifier(self.technical_error_reason, "technical_error_reason")
        if self.technical_error_evidence_sha256 is not None:
            _digest(
                self.technical_error_evidence_sha256,
                "technical_error_evidence_sha256",
            )
        outputs = (self.output_sha256, self.controlled_artifact_path)
        if self.state in {RunState.INVALID, RunState.UNSUPPORTED}:
            if any(
                value is not None
                for value in outputs
                + (
                    self.completion_evidence_sha256,
                    self.technical_error_reason,
                    self.technical_error_evidence_sha256,
                )
            ):
                raise ValueError("Non-dispatched records cannot carry result fields.")
        elif self.state is RunState.DISPATCH_AUTHORIZED:
            if (
                any(value is not None for value in outputs)
                or self.completion_evidence_sha256 is not None
                or self.technical_error_reason is not None
                or self.technical_error_evidence_sha256 is not None
            ):
                raise ValueError(
                    "Dispatch records cannot claim unauthenticated output evidence."
                )
        elif self.state is RunState.COMPLETED:
            if (
                any(value is None for value in outputs)
                or self.completion_evidence_sha256 is None
                or self.technical_error_reason is not None
                or self.technical_error_evidence_sha256 is not None
            ):
                raise ValueError("Completed records require correlated completion.")
        elif self.state is RunState.TECHNICAL_ERROR and (
            any(value is not None for value in outputs)
            or self.completion_evidence_sha256 is not None
            or self.technical_error_reason is None
            or self.technical_error_evidence_sha256 is None
        ):
            raise ValueError(
                "Technical errors require a stable reason and verifier evidence."
            )


@dataclass(frozen=True)
class CriterionAssessment:
    criterion: str
    verdict: CriterionVerdict
    evidence_sha256: tuple[str, ...]
    content_receipt_sha256: tuple[str, ...]
    rationale_code: str
    rationale_commitment_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.criterion, "criterion")
        expected_rationale = {
            CriterionVerdict.DEMONSTRATED: "evidence-supports-verdict",
            CriterionVerdict.PARTIAL: "evidence-partially-supports-verdict",
            CriterionVerdict.ABSENT: "no-supporting-evidence",
            CriterionVerdict.VIOLATED: "evidence-shows-violation",
        }[self.verdict]
        if self.rationale_code != expected_rationale:
            raise ValueError("Assessment rationale code does not match its verdict.")
        if not self.evidence_sha256:
            raise ValueError("Criterion assessments require cited evidence.")
        for digest in self.evidence_sha256 + self.content_receipt_sha256:
            _digest(digest, "assessment evidence")
        _digest(
            self.rationale_commitment_sha256,
            "rationale_commitment_sha256",
        )


@dataclass(frozen=True)
class HardRejectionAssessment:
    rule: str
    triggered: bool
    evidence_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.rule, "hard rejection rule")
        if self.triggered != bool(self.evidence_sha256):
            raise ValueError("Hard rejection evidence must match its state.")
        for digest in self.evidence_sha256:
            _digest(digest, "hard rejection evidence")


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
    control_judgment_sha256: str
    layered_judgment_sha256: str
    relations: tuple[CriterionComparison, ...]
    hard_gate_state: PreflightState
    _authority: object = None

    def __post_init__(self) -> None:
        if self._authority is not _COMPARISON_AUTHORITY:
            raise ValueError("Comparison records must be coordinator-issued.")
        for digest in (
            self.comparison_sha256,
            self.comparability_sha256,
            self.control_run_sha256,
            self.layered_run_sha256,
            self.control_judgment_sha256,
            self.layered_judgment_sha256,
        ):
            _digest(digest, "comparison identity")


@dataclass(frozen=True)
class ArtifactReceipt:
    artifact_type: str
    sha256: str
    relative_path: str
    size_bytes: int
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _identifier(self.artifact_type, "artifact_type")
        _digest(self.sha256, "artifact sha256")
        _relative_path(self.relative_path, "artifact relative_path")
        if self.size_bytes < 1:
            raise ValueError("Artifact must not be empty.")
        if self._capability is None:
            raise ValueError("Artifact receipt requires a retained leaf capability.")
