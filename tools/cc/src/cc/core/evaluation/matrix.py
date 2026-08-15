"""Exact EVAL-01..07 matrix and runtime prompt packet construction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cc.core.evaluation.fixtures import (
    LoadedFixture,
    load_fixture,
    verify_loaded_fixture,
)
from cc.core.evaluation.journey_runtime import PreparedInvocation
from cc.core.evaluation.models import LayerVariant, RuntimeName
from cc.core.evaluation.schema import canonical_sha256

PROMPT_PACKET_SCHEMA_VERSION = "1.1"
MATRIX_SCHEMA_VERSION = "1.1"
ROUTE_CONTRACT_SCHEMA_VERSION = "task296-evaluation-route-v1"
_CASE_IDS = tuple(f"eval-{index:02d}" for index in range(1, 8))
_CASE_ROUTES = {
    "eval-01": ("service-design", "sd"),
    "eval-02": ("organizational-design", "sd"),
    "eval-03": ("ui-design", "uids"),
    "eval-04": ("creative-direction", "cco"),
    "eval-05": ("accounting-advisory", "cpa"),
    "eval-06": ("technical-architecture", "ta"),
    "eval-07": ("documentation", "doc"),
}
_CASE_PACKET_SHA256 = {
    "eval-01": "9b110725bd3c52c8ca066c3500c5a0cc9efa8df921d658d9f611e33d210a1ac0",
    "eval-02": "be56e9fd1f30136e75ce5dbe64c5447b989317da7304931fdb7dd50907eb26e6",
    "eval-03": "33ecb28c7a4c42b21a7edaf8dc34501f1daa3b1609b9c2c4482beb20df64fbc0",
    "eval-04": "e3f7e36694bb2abd5edaefbde7ed75b83b1249ef57c27a13f4fb51ce6bb30372",
    "eval-05": "20be2067c02c0d9115712269035c561d4e70ece5a081049b53be8ed8744a63b2",
    "eval-06": "2c92933f8e85db9b489152fcb7291527f9c433e059343d8362f0e31bdbf0211c",
    "eval-07": "b378ebe36eead2ec193d64472081e8b3a98764e46058cad924e4b42af3de7687",
}


def _route_contract_document(case_id: str) -> dict[str, object]:
    try:
        classification, specialist = _CASE_ROUTES[case_id]
    except KeyError as exc:
        raise ValueError("Evaluation route is not preregistered.") from exc
    return {
        "schema_version": ROUTE_CONTRACT_SCHEMA_VERSION,
        "case_id": case_id,
        "revision": 1,
        "classification": classification,
        "specialists": [specialist],
        "stages": [
            {
                "stage_index": 0,
                "specialist": specialist,
                "reason": "protocol-supplied",
            }
        ],
    }


def route_contract_document(case_id: str) -> dict[str, object]:
    """Return one closed route preregistration with its canonical identity."""

    document = _route_contract_document(case_id)
    return {
        **document,
        "route_contract_sha256": canonical_sha256(document),
    }


def fixture_packet_document(case_id: str) -> dict[str, object]:
    """Return one closed fixture-packet preregistration."""

    try:
        packet_sha256 = _CASE_PACKET_SHA256[case_id]
    except KeyError as exc:
        raise ValueError("Evaluation fixture packet is not preregistered.") from exc
    return {
        "case_id": case_id,
        "revision": 1,
        "fixture_packet_sha256": packet_sha256,
    }


def fixture_packet_identity(loaded: LoadedFixture) -> str:
    """Bind one case, its runtime evidence, and its private oracle declaration."""

    if not verify_loaded_fixture(loaded):
        raise ValueError("Matrix fixture packet is not verifier-issued.")
    document = {
        "schema_version": "evaluation-fixture-packet-v1",
        "case_id": loaded.fixture.case_id,
        "revision": loaded.fixture.revision,
        "case_sha256": loaded.fixture_sha256,
        "evidence": [
            {
                "path": item.path,
                "sha256": item.sha256,
                "media_type": item.media_type,
            }
            for item in loaded.evidence
        ],
        "private_oracle": {
            "path": loaded.oracle.path,
            "sha256": loaded.oracle.sha256,
        },
    }
    identity = canonical_sha256(document)
    if identity != _CASE_PACKET_SHA256.get(loaded.fixture.case_id):
        raise ValueError("Matrix fixture packet differs from preregistration.")
    return identity


@dataclass(frozen=True)
class MatrixCellPlan:
    case_id: str
    revision: int
    variant: LayerVariant
    runtime: RuntimeName
    role: str
    fixture_packet_sha256: str
    route_classification: str
    expected_specialist: str
    route_contract_sha256: str

    def __post_init__(self) -> None:
        if self.case_id not in _CASE_IDS or self.revision != 1:
            raise ValueError("Matrix cell is not preregistered.")
        if self.role not in {"control", "layered"}:
            raise ValueError("Matrix role must be control or layered.")
        route = route_contract_document(self.case_id)
        if (
            self.fixture_packet_sha256 != _CASE_PACKET_SHA256[self.case_id]
            or self.route_classification != route["classification"]
            or self.expected_specialist != route["specialists"][0]
            or self.route_contract_sha256 != route["route_contract_sha256"]
        ):
            raise ValueError("Matrix cell route is not preregistered.")


@dataclass(frozen=True)
class EvaluationMatrix:
    schema_version: str
    cells: tuple[MatrixCellPlan, ...]
    matrix_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != MATRIX_SCHEMA_VERSION or len(self.cells) != 28:
            raise ValueError("Evaluation matrix must contain the exact 28 cells.")
        if self.matrix_sha256 != canonical_sha256(_matrix_document(self.cells)):
            raise ValueError("Evaluation matrix identity is invalid.")


@dataclass(frozen=True)
class RuntimePromptPacket:
    case_id: str
    revision: int
    variant: LayerVariant
    runtime: RuntimeName
    fixture_packet_sha256: str
    prompt_evidence_sha256: str
    full_prompt_sha256: str
    user_prompt_text: str
    system_context_text: str
    source_runtimes: tuple[str, ...]
    specialist: str
    invocation_marker: str
    composed_content_sha256: str
    source_receipts: tuple[dict[str, object], ...]
    source_receipts_sha256: str
    route_contract_sha256: str

    def __post_init__(self) -> None:
        route = route_contract_document(self.case_id)
        if (
            self.revision != route["revision"]
            or self.fixture_packet_sha256 != _CASE_PACKET_SHA256.get(self.case_id)
            or self.specialist != route["specialists"][0]
            or self.route_contract_sha256 != route["route_contract_sha256"]
        ):
            raise ValueError("Runtime prompt route is not preregistered.")


def _matrix_document(cells: tuple[MatrixCellPlan, ...]) -> dict[str, object]:
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "cells": [
            {
                "case_id": cell.case_id,
                "revision": cell.revision,
                "variant": cell.variant.value,
                "runtime": cell.runtime.value,
                "role": cell.role,
                "fixture_packet_sha256": cell.fixture_packet_sha256,
                "route_classification": cell.route_classification,
                "expected_specialist": cell.expected_specialist,
                "route_contract_sha256": cell.route_contract_sha256,
            }
            for cell in cells
        ],
        "fixture_packets": [fixture_packet_document(case_id) for case_id in _CASE_IDS],
        "route_contracts": [route_contract_document(case_id) for case_id in _CASE_IDS],
    }


def matrix_document(matrix: EvaluationMatrix) -> dict[str, object]:
    document = _matrix_document(matrix.cells)
    document["matrix_sha256"] = matrix.matrix_sha256
    return document


def build_matrix(
    fixtures_root: Path,
) -> tuple[EvaluationMatrix, tuple[LoadedFixture, ...]]:
    loaded = tuple(load_fixture(fixtures_root / case_id) for case_id in _CASE_IDS)
    cells: list[MatrixCellPlan] = []
    for packet in loaded:
        fixture = packet.fixture
        packet_sha256 = fixture_packet_identity(packet)
        route = route_contract_document(fixture.case_id)
        for runtime in fixture.runtimes:
            for index, variant in enumerate(fixture.layer_variants):
                cells.append(
                    MatrixCellPlan(
                        case_id=fixture.case_id,
                        revision=fixture.revision,
                        variant=variant,
                        runtime=runtime,
                        role="control" if index == 0 else "layered",
                        fixture_packet_sha256=packet_sha256,
                        route_classification=str(route["classification"]),
                        expected_specialist=str(route["specialists"][0]),
                        route_contract_sha256=str(route["route_contract_sha256"]),
                    )
                )
    result = tuple(cells)
    if len({(item.case_id, item.variant, item.runtime) for item in result}) != 28:
        raise ValueError("Evaluation matrix contains duplicate or missing cells.")
    return (
        EvaluationMatrix(
            schema_version=MATRIX_SCHEMA_VERSION,
            cells=result,
            matrix_sha256=canonical_sha256(_matrix_document(result)),
        ),
        loaded,
    )


def prompt_evidence_identity(loaded: LoadedFixture) -> str:
    if not verify_loaded_fixture(loaded):
        raise ValueError("Runtime prompt fixture is not verifier-issued.")
    return canonical_sha256(
        {
            "fixture_sha256": loaded.fixture_sha256,
            "problem_statement": loaded.fixture.problem_statement,
            "evidence": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "media_type": item.media_type,
                }
                for item in loaded.evidence
            ],
        }
    )


def runtime_configuration_identity(packet: RuntimePromptPacket) -> str:
    """Bind the exact prepared context and synthetic input to one cell."""

    return canonical_sha256(
        {
            "schema_version": PROMPT_PACKET_SCHEMA_VERSION,
            "case_id": packet.case_id,
            "revision": packet.revision,
            "variant": packet.variant.value,
            "runtime": packet.runtime.value,
            "fixture_packet_sha256": packet.fixture_packet_sha256,
            "prompt_evidence_sha256": packet.prompt_evidence_sha256,
            "full_prompt_sha256": packet.full_prompt_sha256,
            "specialist": packet.specialist,
            "invocation_marker": packet.invocation_marker,
            "composed_content_sha256": packet.composed_content_sha256,
            "source_receipts_sha256": packet.source_receipts_sha256,
            "route_contract_sha256": packet.route_contract_sha256,
        }
    )


def _runtime_packet_document(
    loaded: LoadedFixture,
    *,
    variant: LayerVariant,
    runtime: RuntimeName,
) -> dict[str, object]:
    if not verify_loaded_fixture(loaded):
        raise ValueError("Runtime prompt fixture is not verifier-issued.")
    fixture = loaded.fixture
    if variant not in fixture.layer_variants or runtime not in fixture.runtimes:
        raise ValueError("Prompt cell is outside the preregistered fixture matrix.")
    evidence = []
    for item in loaded.evidence:
        try:
            content = item.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Runtime prompt evidence must be UTF-8.") from exc
        evidence.append(
            {
                "path": item.path,
                "sha256": item.sha256,
                "media_type": item.media_type,
                "content": content,
            }
        )
    return {
        "schema_version": PROMPT_PACKET_SCHEMA_VERSION,
        "problem_statement": fixture.problem_statement,
        "evidence": evidence,
    }


def build_runtime_prompt(
    loaded: LoadedFixture,
    *,
    variant: LayerVariant,
    runtime: RuntimeName,
    prepared: PreparedInvocation,
) -> RuntimePromptPacket:
    """Bind verified journey composition to the exact synthetic input packet."""

    runtime_packet = _runtime_packet_document(loaded, variant=variant, runtime=runtime)
    route = route_contract_document(loaded.fixture.case_id)
    if prepared.specialist != route["specialists"][0] or prepared.stage_index != 0:
        raise ValueError(
            "Prepared journey invocation does not match the preregistered route."
        )
    expected_tiers = {
        LayerVariant.FOUNDATION: {"foundation"},
        LayerVariant.ORGANIZATION: {"foundation", "organization"},
        LayerVariant.DEPARTMENT: {"foundation", "organization", "department"},
        LayerVariant.PERSONAL: {
            "foundation",
            "organization",
            "department",
            "personal",
        },
    }[variant]
    if (
        not prepared.agent_prompt_fragment
        or not prepared.knowledge_payload
        or prepared.variant != variant.value
        or prepared.runtime != runtime.value
        or any(source.get("runtime") != runtime.value for source in prepared.sources)
        or any(source.get("tier") not in expected_tiers for source in prepared.sources)
        or prepared.composed_content_sha256
        != hashlib.sha256(prepared.knowledge_payload.encode()).hexdigest()
    ):
        raise ValueError("Prepared journey invocation is not authenticated content.")
    user_prompt_text = json.dumps(
        runtime_packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    system_prefix = (
        prepared.agent_prompt_fragment
        if runtime is RuntimeName.CLAUDE
        else (
            prepared.agent_prompt_fragment
            + "\nUse the exact protocol-prepared specialist and Knowledge "
            "projection above as developer context."
        )
    )
    system_context_text = (
        system_prefix
        + "\n\nCC-EVALUATION-RUNTIME-POLICY\n"
        + "Solve the supplied synthetic problem using only its declared evidence. "
        + "Produce one shared evidence-bound solution artifact. Do not evaluate "
        + "yourself, call tools or external services, mutate any system, disclose "
        + "private personal markers, or claim authority reserved for a person."
    )
    if (
        loaded.oracle.path in user_prompt_text
        or loaded.oracle.sha256 in user_prompt_text
        or loaded.oracle.content.decode("utf-8") in user_prompt_text
    ):
        raise ValueError("Private oracle entered the runtime prompt.")
    full_prompt_sha256 = canonical_sha256(
        {
            "system_context": system_context_text,
            "user_input": user_prompt_text,
        }
    )
    return RuntimePromptPacket(
        case_id=loaded.fixture.case_id,
        revision=loaded.fixture.revision,
        variant=variant,
        runtime=runtime,
        fixture_packet_sha256=fixture_packet_identity(loaded),
        prompt_evidence_sha256=prompt_evidence_identity(loaded),
        full_prompt_sha256=full_prompt_sha256,
        user_prompt_text=user_prompt_text,
        system_context_text=system_context_text,
        source_runtimes=tuple(
            sorted({str(item["runtime"]) for item in prepared.sources})
        ),
        specialist=prepared.specialist,
        invocation_marker=prepared.invocation_marker,
        composed_content_sha256=prepared.composed_content_sha256,
        source_receipts=tuple(dict(item) for item in prepared.sources),
        source_receipts_sha256=canonical_sha256(
            [dict(item) for item in prepared.sources]
        ),
        route_contract_sha256=str(route["route_contract_sha256"]),
    )


__all__ = [
    "EvaluationMatrix",
    "MatrixCellPlan",
    "RuntimePromptPacket",
    "build_matrix",
    "build_runtime_prompt",
    "fixture_packet_document",
    "fixture_packet_identity",
    "matrix_document",
    "prompt_evidence_identity",
    "route_contract_document",
    "runtime_configuration_identity",
]
