"""Non-authorizing declaration of subjects for one packaged Codex matrix cell.

Digest strings cannot prove that their underlying values were retained or
verified.  This module therefore provides a descriptive frozen value only.  A
dispatch path must never treat it as permission or as a prepared runtime
capability.  Production execution requires a separate verifier-owned capability
derived from authentic retained inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from cc.core.evaluation.matrix import MatrixCellPlan, build_matrix
from cc.core.evaluation.models import LayerVariant, RuntimeName
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256, packaged_cases_root

PREPARED_CODEX_DECLARATION_SCHEMA_VERSION = "task285-prepared-codex-declaration-v1"
PREPARED_CODEX_MODEL = "gpt-5.6-sol"
PREPARED_CODEX_ADAPTER_NAME = "codex-noninteractive"
PREPARED_CODEX_ADAPTER_VERSION = "v1"

PREPARED_CODEX_MODEL_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-prepared-codex-model-v1",
        "runtime": RuntimeName.CODEX.value,
        "model": PREPARED_CODEX_MODEL,
    }
)
PREPARED_CODEX_ADAPTER_SHA256 = canonical_sha256(
    {
        "schema_version": "task285-prepared-codex-adapter-v1",
        "runtime": RuntimeName.CODEX.value,
        "adapter_name": PREPARED_CODEX_ADAPTER_NAME,
        "adapter_version": PREPARED_CODEX_ADAPTER_VERSION,
    }
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _require_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError(f"Prepared Codex {label} must be a SHA-256 digest.")


def _plan_document(plan: MatrixCellPlan) -> dict[str, object]:
    return {
        "case_id": plan.case_id,
        "revision": plan.revision,
        "variant": plan.variant.value,
        "runtime": plan.runtime.value,
        "role": plan.role,
        "fixture_packet_sha256": plan.fixture_packet_sha256,
        "route_classification": plan.route_classification,
        "expected_specialist": plan.expected_specialist,
        "route_contract_sha256": plan.route_contract_sha256,
    }


def _canonical_codex_plan(
    case_id: str,
    variant: LayerVariant,
    role: str,
) -> tuple[MatrixCellPlan, str]:
    """Resolve one selector from the released matrix, never a caller-made plan."""

    if (
        not isinstance(case_id, str)
        or not isinstance(variant, LayerVariant)
        or role not in {"control", "layered"}
    ):
        raise ValueError("Prepared Codex cell selector is invalid.")
    matrix, fixtures = build_matrix(packaged_cases_root())
    if matrix.matrix_sha256 != PACKAGED_MATRIX_SHA256 or len(matrix.cells) != 28:
        raise ValueError("Packaged evaluation matrix identity is invalid.")
    selected = tuple(
        plan
        for plan in matrix.cells
        if plan.case_id == case_id
        and plan.variant is variant
        and plan.runtime is RuntimeName.CODEX
        and plan.role == role
    )
    loaded = tuple(item for item in fixtures if item.fixture.case_id == case_id)
    if len(selected) != 1 or len(loaded) != 1:
        raise ValueError("Prepared Codex cell selector is not preregistered.")
    return selected[0], loaded[0].fixture_sha256


_DIGEST_FIELDS = (
    "declaration_sha256",
    "matrix_sha256",
    "plan_sha256",
    "fixture_packet_sha256",
    "route_contract_sha256",
    "fixture_sha256",
    "route_sha256",
    "journey_sha256",
    "ledger_sha256",
    "prompt_sha256",
    "model_sha256",
    "adapter_sha256",
    "canonical_content_projection_sha256",
    "artifact_root_sha256",
    "staged_executable_sha256",
    "catalog_sha256",
)


@dataclass(frozen=True)
class PreparedCodexCellDeclaration:
    """Descriptive subject set; never proof or permission to dispatch."""

    schema_version: str
    declaration_sha256: str
    authority: str
    dispatch_authorized: bool
    matrix_sha256: str
    plan_sha256: str
    case_id: str
    revision: int
    variant: LayerVariant
    runtime: RuntimeName
    role: str
    fixture_packet_sha256: str
    route_classification: str
    expected_specialist: str
    route_contract_sha256: str
    fixture_sha256: str
    route_sha256: str
    journey_sha256: str
    ledger_sha256: str
    prompt_sha256: str
    model: str
    model_sha256: str
    adapter_name: str
    adapter_version: str
    adapter_sha256: str
    canonical_content_projection_sha256: str
    artifact_root_sha256: str
    staged_executable_sha256: str
    catalog_sha256: str

    def __post_init__(self) -> None:
        if (
            self.schema_version != PREPARED_CODEX_DECLARATION_SCHEMA_VERSION
            or self.authority != "none"
            or self.dispatch_authorized is not False
            or self.matrix_sha256 != PACKAGED_MATRIX_SHA256
            or self.runtime is not RuntimeName.CODEX
            or self.model != PREPARED_CODEX_MODEL
            or self.model_sha256 != PREPARED_CODEX_MODEL_SHA256
            or self.adapter_name != PREPARED_CODEX_ADAPTER_NAME
            or self.adapter_version != PREPARED_CODEX_ADAPTER_VERSION
            or self.adapter_sha256 != PREPARED_CODEX_ADAPTER_SHA256
        ):
            raise ValueError("Prepared Codex declaration policy is invalid.")
        for label in _DIGEST_FIELDS:
            _require_digest(getattr(self, label), label)


def _declaration_body(value: PreparedCodexCellDeclaration) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "authority": value.authority,
        "dispatch_authorized": value.dispatch_authorized,
        "matrix_sha256": value.matrix_sha256,
        "plan_sha256": value.plan_sha256,
        "case_id": value.case_id,
        "revision": value.revision,
        "variant": value.variant.value,
        "runtime": value.runtime.value,
        "role": value.role,
        "fixture_packet_sha256": value.fixture_packet_sha256,
        "route_classification": value.route_classification,
        "expected_specialist": value.expected_specialist,
        "route_contract_sha256": value.route_contract_sha256,
        "fixture_sha256": value.fixture_sha256,
        "route_sha256": value.route_sha256,
        "journey_sha256": value.journey_sha256,
        "ledger_sha256": value.ledger_sha256,
        "prompt_sha256": value.prompt_sha256,
        "model": value.model,
        "model_sha256": value.model_sha256,
        "adapter_name": value.adapter_name,
        "adapter_version": value.adapter_version,
        "adapter_sha256": value.adapter_sha256,
        "canonical_content_projection_sha256": (
            value.canonical_content_projection_sha256
        ),
        "artifact_root_sha256": value.artifact_root_sha256,
        "staged_executable_sha256": value.staged_executable_sha256,
        "catalog_sha256": value.catalog_sha256,
    }


_DOCUMENT_KEYS = frozenset(
    {
        "schema_version",
        "declaration_sha256",
        "authority",
        "dispatch_authorized",
        "matrix_sha256",
        "plan_sha256",
        "case_id",
        "revision",
        "variant",
        "runtime",
        "role",
        "fixture_packet_sha256",
        "route_classification",
        "expected_specialist",
        "route_contract_sha256",
        "fixture_sha256",
        "route_sha256",
        "journey_sha256",
        "ledger_sha256",
        "prompt_sha256",
        "model",
        "model_sha256",
        "adapter_name",
        "adapter_version",
        "adapter_sha256",
        "canonical_content_projection_sha256",
        "artifact_root_sha256",
        "staged_executable_sha256",
        "catalog_sha256",
    }
)


def prepared_codex_declaration_document_is_well_formed(
    document: Mapping[str, object],
) -> bool:
    """Check structural coherence only; this result never conveys authority."""

    try:
        if not isinstance(document, Mapping) or frozenset(document) != _DOCUMENT_KEYS:
            return False
        string_fields = _DOCUMENT_KEYS - {"revision", "dispatch_authorized"}
        if any(type(document[key]) is not str for key in string_fields):
            return False
        if (
            type(document["revision"]) is not int
            or type(document["dispatch_authorized"]) is not bool
        ):
            return False
        variant = LayerVariant(str(document["variant"]))
        plan, fixture_sha256 = _canonical_codex_plan(
            str(document["case_id"]),
            variant,
            str(document["role"]),
        )
        body = {key: document[key] for key in document if key != "declaration_sha256"}
        if (
            document["schema_version"] != PREPARED_CODEX_DECLARATION_SCHEMA_VERSION
            or document["authority"] != "none"
            or document["dispatch_authorized"] is not False
            or document["declaration_sha256"] != canonical_sha256(body)
            or document["matrix_sha256"] != PACKAGED_MATRIX_SHA256
            or document["plan_sha256"] != canonical_sha256(_plan_document(plan))
            or document["revision"] != plan.revision
            or document["runtime"] != RuntimeName.CODEX.value
            or document["fixture_packet_sha256"] != plan.fixture_packet_sha256
            or document["route_classification"] != plan.route_classification
            or document["expected_specialist"] != plan.expected_specialist
            or document["route_contract_sha256"] != plan.route_contract_sha256
            or document["fixture_sha256"] != fixture_sha256
            or document["route_sha256"] != plan.route_contract_sha256
            or document["model"] != PREPARED_CODEX_MODEL
            or document["model_sha256"] != PREPARED_CODEX_MODEL_SHA256
            or document["adapter_name"] != PREPARED_CODEX_ADAPTER_NAME
            or document["adapter_version"] != PREPARED_CODEX_ADAPTER_VERSION
            or document["adapter_sha256"] != PREPARED_CODEX_ADAPTER_SHA256
        ):
            return False
        return all(
            _DIGEST.fullmatch(str(document[field_name]))
            for field_name in _DIGEST_FIELDS
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False


def prepared_codex_declaration_document(
    value: PreparedCodexCellDeclaration,
) -> dict[str, object]:
    """Return one coherent value-suppressing, non-authorizing document."""

    if not isinstance(value, PreparedCodexCellDeclaration):
        raise ValueError("Prepared Codex declaration is malformed.")
    document = {
        **_declaration_body(value),
        "declaration_sha256": value.declaration_sha256,
    }
    if not prepared_codex_declaration_document_is_well_formed(document):
        raise ValueError("Prepared Codex declaration is malformed.")
    return document


def declare_prepared_codex_cell(
    *,
    case_id: str,
    variant: LayerVariant,
    role: str,
    fixture_sha256: str,
    route_sha256: str,
    journey_sha256: str,
    ledger_sha256: str,
    prompt_sha256: str,
    model_sha256: str,
    adapter_sha256: str,
    canonical_content_projection_sha256: str,
    artifact_root_sha256: str,
    staged_executable_sha256: str,
    catalog_sha256: str,
) -> PreparedCodexCellDeclaration:
    """Describe digest subjects without attesting that they are authentic."""

    plan, packaged_fixture_sha256 = _canonical_codex_plan(case_id, variant, role)
    subjects = {
        "fixture_sha256": fixture_sha256,
        "route_sha256": route_sha256,
        "journey_sha256": journey_sha256,
        "ledger_sha256": ledger_sha256,
        "prompt_sha256": prompt_sha256,
        "model_sha256": model_sha256,
        "adapter_sha256": adapter_sha256,
        "canonical_content_projection_sha256": (canonical_content_projection_sha256),
        "artifact_root_sha256": artifact_root_sha256,
        "staged_executable_sha256": staged_executable_sha256,
        "catalog_sha256": catalog_sha256,
    }
    for label, digest in subjects.items():
        _require_digest(digest, label)
    if (
        fixture_sha256 != packaged_fixture_sha256
        or route_sha256 != plan.route_contract_sha256
    ):
        raise ValueError("Prepared Codex packaged subject is invalid.")
    if (
        model_sha256 != PREPARED_CODEX_MODEL_SHA256
        or adapter_sha256 != PREPARED_CODEX_ADAPTER_SHA256
    ):
        raise ValueError("Prepared Codex runtime policy subject is invalid.")

    values = {
        "schema_version": PREPARED_CODEX_DECLARATION_SCHEMA_VERSION,
        "declaration_sha256": "0" * 64,
        "authority": "none",
        "dispatch_authorized": False,
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "plan_sha256": canonical_sha256(_plan_document(plan)),
        "case_id": plan.case_id,
        "revision": plan.revision,
        "variant": plan.variant,
        "runtime": plan.runtime,
        "role": plan.role,
        "fixture_packet_sha256": plan.fixture_packet_sha256,
        "route_classification": plan.route_classification,
        "expected_specialist": plan.expected_specialist,
        "route_contract_sha256": plan.route_contract_sha256,
        **subjects,
        "model": PREPARED_CODEX_MODEL,
        "adapter_name": PREPARED_CODEX_ADAPTER_NAME,
        "adapter_version": PREPARED_CODEX_ADAPTER_VERSION,
    }
    provisional = PreparedCodexCellDeclaration(**values)
    return PreparedCodexCellDeclaration(
        **{
            **values,
            "declaration_sha256": canonical_sha256(_declaration_body(provisional)),
        }
    )


__all__ = [
    "PREPARED_CODEX_ADAPTER_NAME",
    "PREPARED_CODEX_ADAPTER_SHA256",
    "PREPARED_CODEX_ADAPTER_VERSION",
    "PREPARED_CODEX_DECLARATION_SCHEMA_VERSION",
    "PREPARED_CODEX_MODEL",
    "PREPARED_CODEX_MODEL_SHA256",
    "PreparedCodexCellDeclaration",
    "declare_prepared_codex_cell",
    "prepared_codex_declaration_document",
    "prepared_codex_declaration_document_is_well_formed",
]
