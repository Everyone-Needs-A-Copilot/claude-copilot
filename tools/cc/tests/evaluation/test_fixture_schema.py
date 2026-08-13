from __future__ import annotations

import copy

import pytest
from cc.core.evaluation.schema import (
    SchemaViolation,
    canonical_json_bytes,
    canonical_sha256,
    validate_document,
)


def fixture_document() -> dict:
    return {
        "schema_version": "1.0",
        "case_id": "eval-05",
        "revision": 1,
        "fixture_namespace": "SYNTHETIC-EVAL05",
        "problem_statement": "Reconcile the synthetic evidence packet.",
        "evidence_files": [
            {
                "path": "input/summary.txt",
                "sha256": "a" * 64,
                "media_type": "text/plain",
                "synthetic_fixture": True,
                "fixture_namespace": "SYNTHETIC-EVAL05",
            }
        ],
        "layer_variants": ["F", "F+O+D"],
        "runtimes": ["claude", "codex"],
        "required_criteria": ["evidence-trace", "factual-restraint"],
        "hard_rejection_rules": ["invented-value"],
        "journey_requirements": ["route-evidence", "continuity-evidence"],
        "private_oracle": {"path": "oracle/expected.json", "sha256": "b" * 64},
    }


def test_closed_draft_2020_fixture_schema_accepts_exact_contract():
    validate_document(fixture_document())


@pytest.mark.parametrize(
    "mutate,expected_location",
    [
        (lambda value: value.update({"score": 1}), "/"),
        (
            lambda value: value["evidence_files"][0].update({"source_value": "hidden"}),
            "/evidence_files/0",
        ),
        (lambda value: value.update({"schema_version": "2.0"}), "/schema_version"),
        (lambda value: value.update({"layer_variants": ["F+P"]}), "/layer_variants/0"),
        (
            lambda value: value["evidence_files"][0].update(
                {"synthetic_fixture": False}
            ),
            "/evidence_files/0/synthetic_fixture",
        ),
    ],
)
def test_schema_rejects_unknown_or_unregistered_contract_fields(
    mutate, expected_location
):
    value = fixture_document()
    mutate(value)
    with pytest.raises(SchemaViolation) as caught:
        validate_document(value)
    assert expected_location in {issue.location for issue in caught.value.issues}


def test_canonical_identity_is_key_order_independent_and_float_free():
    first = fixture_document()
    second = dict(reversed(tuple(first.items())))
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_sha256(first) == canonical_sha256(second)
    assert len(canonical_sha256(first)) == 64

    invalid = copy.deepcopy(first)
    invalid["revision"] = 1.0
    with pytest.raises(TypeError, match="Floating-point"):
        canonical_sha256(invalid)
