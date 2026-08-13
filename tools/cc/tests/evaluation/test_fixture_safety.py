from __future__ import annotations

import hashlib
import json
import os
import shutil
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


CASES_ROOT = Path(__file__).parent / "fixtures" / "cases"


def _write_fixture(root: Path, *, evidence: bytes | None = None) -> dict:
    shutil.copytree(CASES_ROOT / "eval-05", root, dirs_exist_ok=True)
    document = json.loads((root / "case.json").read_text(encoding="utf-8"))
    if evidence is not None:
        declared = document["evidence_files"][0]
        (root / declared["path"]).write_bytes(evidence)
        declared["sha256"] = _sha(evidence)
    (root / "case.json").write_text(json.dumps(document), encoding="utf-8")
    return document


def test_loader_verifies_exact_files_and_keeps_oracle_out_of_runtime_evidence(tmp_path):
    document = _write_fixture(tmp_path)
    loaded = load_fixture(tmp_path)

    assert loaded.fixture.case_id == "eval-05"
    assert (
        loaded.fixture_sha256
        == hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert tuple(item.path for item in loaded.evidence) == tuple(
        item["path"] for item in document["evidence_files"]
    )
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
    evidence_path = tmp_path / document["evidence_files"][0]["path"]
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


def test_loader_rejects_hardlinked_evidence_even_when_bytes_match(tmp_path):
    document = _write_fixture(tmp_path)
    evidence_path = tmp_path / document["evidence_files"][0]["path"]
    outside = tmp_path / "outside-evidence.json"
    outside.write_bytes(evidence_path.read_bytes())
    evidence_path.unlink()
    os.link(outside, evidence_path)

    with pytest.raises(FixtureLoadError, match="bounded regular file"):
        load_fixture(tmp_path)


def test_loader_rejects_hardlink_created_after_oracle_snapshot(tmp_path, monkeypatch):
    document = _write_fixture(tmp_path)
    oracle_path = tmp_path / document["private_oracle"]["path"]
    evidence_path = tmp_path / document["evidence_files"][0]["path"]
    original_read = __import__(
        "cc.core.evaluation.fixtures", fromlist=["_read_regular_file"]
    )._read_regular_file
    switched = False

    def link_oracle_after_read(root_descriptor, relative_path, *, file_identities):
        nonlocal switched
        content = original_read(
            root_descriptor, relative_path, file_identities=file_identities
        )
        if relative_path == document["private_oracle"]["path"] and not switched:
            switched = True
            evidence_path.unlink()
            os.link(oracle_path, evidence_path)
        return content

    monkeypatch.setattr(
        "cc.core.evaluation.fixtures._read_regular_file", link_oracle_after_read
    )
    with pytest.raises(FixtureLoadError, match="bounded regular file"):
        load_fixture(tmp_path)
    assert switched


def test_loader_rejects_duplicate_inode_moved_between_fixture_paths(
    tmp_path, monkeypatch
):
    document = _write_fixture(tmp_path)
    oracle_path = tmp_path / document["private_oracle"]["path"]
    evidence_path = tmp_path / document["evidence_files"][0]["path"]
    original_read = __import__(
        "cc.core.evaluation.fixtures", fromlist=["_read_regular_file"]
    )._read_regular_file
    switched = False

    def move_oracle_after_read(root_descriptor, relative_path, *, file_identities):
        nonlocal switched
        content = original_read(
            root_descriptor, relative_path, file_identities=file_identities
        )
        if relative_path == document["private_oracle"]["path"] and not switched:
            switched = True
            evidence_path.unlink()
            oracle_path.replace(evidence_path)
        return content

    monkeypatch.setattr(
        "cc.core.evaluation.fixtures._read_regular_file", move_oracle_after_read
    )
    with pytest.raises(FixtureLoadError, match="unique file identities"):
        load_fixture(tmp_path)
    assert switched


def test_loader_rejects_same_size_post_read_mutation(tmp_path, monkeypatch):
    document = _write_fixture(tmp_path)
    evidence_path = tmp_path / document["evidence_files"][0]["path"]
    evidence = evidence_path.read_bytes()
    original_read = os.read
    mutated = False

    def mutate_after_content_read(file_descriptor, size):
        nonlocal mutated
        chunk = original_read(file_descriptor, size)
        if chunk == evidence and not mutated:
            mutated = True
            evidence_path.write_bytes(evidence)
        return chunk

    monkeypatch.setattr(os, "read", mutate_after_content_read)
    with pytest.raises(FixtureLoadError, match="changed during verified read"):
        load_fixture(tmp_path)
    assert mutated


def test_loader_rejects_fixture_root_swap_to_symlink(tmp_path, monkeypatch):
    root = tmp_path / "case"
    attacker = tmp_path / "attacker"
    root.mkdir()
    attacker.mkdir()
    _write_fixture(root)
    _write_fixture(attacker)
    attacker_case = json.loads((attacker / "case.json").read_text(encoding="utf-8"))
    attacker_case["case_id"] = "eval-99"
    (attacker / "case.json").write_text(json.dumps(attacker_case), encoding="utf-8")

    original_open = os.open
    swapped = False

    def swap_before_root_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and Path(path) == root and dir_fd is None:
            swapped = True
            root.rename(tmp_path / "original-case")
            root.symlink_to(attacker, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_root_open)
    with pytest.raises(FixtureLoadError, match="root cannot be opened safely"):
        load_fixture(root)
    assert swapped


def test_loader_rejects_oracle_declared_as_runtime_evidence(tmp_path):
    document = _write_fixture(tmp_path)
    document["evidence_files"][0]["path"] = "oracle/expected.json"
    document["evidence_files"][0]["sha256"] = document["private_oracle"]["sha256"]
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="oracle cannot be runtime evidence"):
        load_fixture(tmp_path)


def test_loader_rejects_runtime_evidence_that_copies_private_oracle_bytes(tmp_path):
    document = _write_fixture(tmp_path)
    oracle = (tmp_path / "oracle" / "expected.json").read_bytes()
    leaked_path = tmp_path / "input" / "leaked-oracle.json"
    leaked_path.write_bytes(oracle)
    document["evidence_files"].append(
        {
            "path": "input/leaked-oracle.json",
            "sha256": _sha(oracle),
            "media_type": "application/json",
            "synthetic_fixture": True,
            "fixture_namespace": "SYNTHETIC-EVAL05",
        }
    )
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="aliases the private oracle"):
        load_fixture(tmp_path)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("layer_variants", ["F", "F+O+D", "F+O+D+P"], "layer matrix"),
        ("runtimes", ["claude"], "runtime matrix"),
        ("revision", 2, "not preregistered"),
        ("case_id", "eval-99", "not preregistered"),
    ],
)
def test_loader_rejects_fixture_matrix_or_identity_outside_preregistration(
    tmp_path, field, value, error
):
    document = _write_fixture(tmp_path)
    document[field] = value
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match=error):
        load_fixture(tmp_path)


@pytest.mark.parametrize(
    "source_case,target_case",
    [
        (source_case, target_case)
        for source_case in sorted(path.name for path in CASES_ROOT.iterdir())
        for target_case in sorted(path.name for path in CASES_ROOT.iterdir())
        if source_case != target_case
    ],
)
def test_loader_rejects_all_pairwise_known_case_identity_substitutions(
    tmp_path, source_case, target_case
):
    shutil.copytree(CASES_ROOT / source_case, tmp_path, dirs_exist_ok=True)
    document = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    document["case_id"] = target_case
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="preregistration"):
        load_fixture(tmp_path)


def test_loader_requires_explicit_preregistration_for_legitimate_packet_edits(
    tmp_path,
):
    document = _write_fixture(tmp_path)
    document["problem_statement"] += " Clarify the synthetic review handoff."
    (tmp_path / "case.json").write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FixtureLoadError, match="packet differs"):
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
def test_safety_findings_report_rule_count_and_location_but_suppress_value(
    unsafe, rule
):
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
