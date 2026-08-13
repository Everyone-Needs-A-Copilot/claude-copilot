from __future__ import annotations

import copy
import json
import unicodedata
from importlib import resources

import pytest
from cc.core.evaluation.fixtures import FixtureLoadError, _canonical_relative_path
from cc.core.evaluation.schema import (
    SchemaViolation,
    canonical_json_bytes,
    canonical_sha256,
    validate_document,
)
from jsonschema import Draft202012Validator


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


@pytest.mark.parametrize(
    "control",
    ["\u007f", "\u0085", "\u202e", "\u2066"],
    ids=["del", "c1-next-line", "bidi-override", "bidi-isolate"],
)
def test_schema_and_invariant_both_reject_control_or_format_paths(control):
    value = fixture_document()
    path = f"input/control{control}.txt"
    value["evidence_files"][0]["path"] = path

    with pytest.raises(SchemaViolation):
        validate_document(value)
    with pytest.raises(FixtureLoadError, match="not canonical"):
        _canonical_relative_path(path)

    schema = json.loads(
        resources.files("cc.core.evaluation")
        .joinpath("schemas", "fixture.schema.json")
        .read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(value))


def test_boolean_is_not_an_integer_revision():
    value = fixture_document()
    value["revision"] = True
    with pytest.raises(SchemaViolation) as caught:
        validate_document(value)
    assert any(
        issue.location == "/revision" and issue.rule == "type"
        for issue in caught.value.issues
    )


def test_public_schema_and_invariant_reject_every_unicode_cc_cf_codepoint():
    schema = json.loads(
        resources.files("cc.core.evaluation")
        .joinpath("schemas", "fixture.schema.json")
        .read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    controls = (
        chr(codepoint)
        for codepoint in range(0x110000)
        if unicodedata.category(chr(codepoint)) in {"Cc", "Cf"}
    )
    for control in controls:
        value = fixture_document()
        path = f"input/control{control}.txt"
        value["evidence_files"][0]["path"] = path
        assert list(validator.iter_errors(value)), (
            f"schema accepted U+{ord(control):04X}"
        )
        with pytest.raises(FixtureLoadError):
            _canonical_relative_path(path)
