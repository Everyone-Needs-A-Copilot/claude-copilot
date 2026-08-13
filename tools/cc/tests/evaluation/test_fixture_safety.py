from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from cc.core.evaluation.fixtures import FixtureLoadError, load_fixture
from cc.core.evaluation.safety import (
    FixtureSafetyViolation,
    require_safe_synthetic_text,
    scan_synthetic_text,
)
from cc.core.evaluation.schema import SchemaViolation


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_fixture(root: Path, *, evidence: bytes | None = None) -> dict:
    evidence = evidence or (
        b"SYNTHETIC-EVAL05\n"
        b"synthetic_amount_units=120\n"
        b"unit=SYNTHETIC_USD_FIXTURE\n"
        b"status=missing\n"
    )
    oracle = json.dumps(
        {
            "fixture_namespace": "SYNTHETIC-EVAL05",
            "expected_gap": "missing-source-evidence",
        },
        sort_keys=True,
    ).encode()
    (root / "input").mkdir(parents=True)
    (root / "oracle").mkdir()
    (root / "input" / "summary.txt").write_bytes(evidence)
    (root / "oracle" / "expected.json").write_bytes(oracle)
    document = {
        "schema_version": "1.0",
        "case_id": "eval-05",
        "revision": 1,
        "fixture_namespace": "SYNTHETIC-EVAL05",
        "problem_statement": "Reconcile the SYNTHETIC-EVAL05 packet.",
        "evidence_files": [
            {
                "path": "input/summary.txt",
                "sha256": _sha(evidence),
                "media_type": "text/plain",
                "synthetic_fixture": True,
                "fixture_namespace": "SYNTHETIC-EVAL05",
            }
        ],
        "layer_variants": ["F", "F+O+D"],
        "runtimes": ["claude", "codex"],
        "required_criteria": ["evidence-trace", "factual-restraint"],
        "hard_rejection_rules": ["invented-value", "unsupported-certainty"],
        "journey_requirements": ["route-evidence", "continuity-evidence"],
        "private_oracle": {"path": "oracle/expected.json", "sha256": _sha(oracle)},
    }
    (root / "case.json").write_text(json.dumps(document), encoding="utf-8")
    return document


def test_loader_verifies_exact_files_and_keeps_oracle_out_of_runtime_evidence(tmp_path):
    document = _write_fixture(tmp_path)
    loaded = load_fixture(tmp_path)

    assert loaded.fixture.case_id == "eval-05"
    assert loaded.fixture_sha256 == hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert tuple(item.path for item in loaded.evidence) == ("input/summary.txt",)
    assert all("oracle" not in item.path for item in loaded.evidence)


def test_loader_rejects_digest_mismatch_without_exposing_content(tmp_path):
    document = _write_fixture(tmp_path)
    document["evidence_files"][0]["sha256"] = "0" * 64
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="digest mismatch") as caught:
        load_fixture(tmp_path)
    assert "synthetic_amount_units" not in str(caught.value)


@pytest.mark.parametrize(
    "unsafe_path", ["../outside.txt", "/tmp/outside.txt", "input\\summary.txt"]
)
def test_loader_rejects_noncanonical_or_escaping_paths(tmp_path, unsafe_path):
    document = _write_fixture(tmp_path)
    document["evidence_files"][0]["path"] = unsafe_path
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises((SchemaViolation, FixtureLoadError)):
        load_fixture(tmp_path)


def test_loader_rejects_symlinked_evidence_even_when_target_digest_matches(tmp_path):
    document = _write_fixture(tmp_path)
    target = tmp_path / "outside.txt"
    target.write_text("SYNTHETIC-OUTSIDE", encoding="utf-8")
    evidence_path = tmp_path / "input" / "summary.txt"
    evidence_path.unlink()
    evidence_path.symlink_to(target)
    document["evidence_files"][0]["sha256"] = _sha(target.read_bytes())
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="cannot be read safely"):
        load_fixture(tmp_path)


def test_loader_rejects_symlinked_evidence_directory(tmp_path):
    document = _write_fixture(tmp_path)
    real_input = tmp_path / "real-input"
    (tmp_path / "input").rename(real_input)
    (tmp_path / "input").symlink_to(real_input, target_is_directory=True)
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="cannot be read safely"):
        load_fixture(tmp_path)


def test_loader_rejects_oracle_declared_as_runtime_evidence(tmp_path):
    document = _write_fixture(tmp_path)
    document["evidence_files"][0]["path"] = "oracle/expected.json"
    document["evidence_files"][0]["sha256"] = document["private_oracle"]["sha256"]
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="oracle cannot be runtime evidence"):
        load_fixture(tmp_path)


def test_loader_rejects_duplicate_json_fields(tmp_path):
    _write_fixture(tmp_path)
    (tmp_path / "case.json").write_text(
        '{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8"
    )
    with pytest.raises(FixtureLoadError, match="duplicate field"):
        load_fixture(tmp_path)


def test_loader_runs_value_suppressing_safety_gate_on_evidence(tmp_path):
    unsafe = b"password=do-not-display-this-value"
    _write_fixture(tmp_path, evidence=unsafe)

    with pytest.raises(FixtureSafetyViolation) as caught:
        load_fixture(tmp_path)
    assert "do-not-display-this-value" not in str(caught.value)
    assert caught.value.findings[0].location_class == "evidence-input"


@pytest.mark.parametrize(
    "unsafe,rule",
    [
        ("taxpayer id: 123-45-6789", "realistic-ssn"),
        ("ein=12-3456789", "realistic-ein"),
        ("Authorization: Bearer abcdefghijklmnopqrst", "secret-bearer"),
        ("path=/Users/actual-person/private.txt", "private-home-path"),
        ("client: Actual Client Incorporated", "real-party-marker"),
    ],
)
def test_safety_findings_report_rule_count_and_location_but_suppress_value(unsafe, rule):
    findings = scan_synthetic_text(unsafe, location_class="evidence-input")
    assert rule in {item.rule for item in findings}
    with pytest.raises(FixtureSafetyViolation) as caught:
        require_safe_synthetic_text(unsafe, location_class="evidence-input")
    assert unsafe not in str(caught.value)
    assert rule in str(caught.value)


def test_private_marker_is_allowed_in_oracle_but_rejected_from_shared_output():
    marker = "PRIVATE_PERSONAL synthetic preference"
    assert scan_synthetic_text(marker, location_class="private-oracle") == ()
    findings = scan_synthetic_text(marker, location_class="shared-output")
    assert len(findings) == 1
    assert findings[0].rule == "upward-personal-disclosure"


def test_safe_nonconforming_synthetic_identifiers_pass():
    require_safe_synthetic_text(
        "client: SYNTHETIC-CLIENT\n"
        "identifier=SYNTHETIC-ID-NOT-FOR-FILING\n"
        "unit=SYNTHETIC_USD_FIXTURE",
        location_class="evidence-input",
    )
