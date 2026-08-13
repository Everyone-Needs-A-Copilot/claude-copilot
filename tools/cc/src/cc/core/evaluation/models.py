"""Closed, immutable models for versioned evaluation fixtures.

This module deliberately models fixture inputs only. Runtime execution,
Knowledge resolution, entitlement, and journey-consumption evidence remain at
their existing boundaries and are not inferred here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class LayerVariant(str, Enum):
    FOUNDATION = "F"
    ORGANIZATION = "F+O"
    DEPARTMENT = "F+O+D"
    PERSONAL = "F+O+D+P"


class RuntimeName(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"


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
