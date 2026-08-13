from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cc.core.evaluation.fixtures import load_fixture
from cc.core.evaluation.safety import scan_synthetic_text

CASES_ROOT = Path(__file__).parent / "fixtures" / "cases"
EXPECTED_VARIANTS = {
    "eval-01": ("F", "F+O"),
    "eval-02": ("F", "F+O"),
    "eval-03": ("F", "F+O"),
    "eval-04": ("F", "F+O"),
    "eval-05": ("F", "F+O+D"),
    "eval-06": ("F", "F+O"),
    "eval-07": ("F+O+D", "F+O+D+P"),
}
EVAL05_INPUTS = {
    "input/profit-and-loss.json",
    "input/balance-sheet.json",
    "input/payroll-summary.json",
    "input/estimated-payments.json",
    "input/repository-activity.json",
    "input/document-inventory.json",
}


def _case_roots() -> tuple[Path, ...]:
    return tuple(sorted(path for path in CASES_ROOT.iterdir() if path.is_dir()))


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _walk_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def test_eval_01_through_eval_07_load_with_digest_bound_runtime_packets():
    roots = _case_roots()
    assert tuple(path.name for path in roots) == tuple(EXPECTED_VARIANTS)

    for root in roots:
        loaded = load_fixture(root)
        case = _json(root / "case.json")
        assert loaded.fixture.case_id == root.name
        assert (
            loaded.fixture.fixture_namespace
            == f"SYNTHETIC-{root.name.upper().replace('-', '')}"
        )
        assert (
            tuple(item.value for item in loaded.fixture.layer_variants)
            == EXPECTED_VARIANTS[root.name]
        )
        assert tuple(item.value for item in loaded.fixture.runtimes) == (
            "claude",
            "codex",
        )
        assert tuple(item.path for item in loaded.evidence) == tuple(
            item["path"] for item in case["evidence_files"]
        )
        assert case["private_oracle"]["path"] not in {
            item.path for item in loaded.evidence
        }
        for evidence in loaded.evidence:
            assert hashlib.sha256(evidence.content).hexdigest() == evidence.sha256


def test_every_case_uses_the_preregistered_smallest_variant_matrix():
    observed = {
        root.name: tuple(_json(root / "case.json")["layer_variants"])
        for root in _case_roots()
    }
    assert observed == EXPECTED_VARIANTS
    assert all(
        "F+O+D+P" not in variants
        for case, variants in observed.items()
        if case != "eval-07"
    )
    assert "F+O+D" not in observed["eval-05"][:1]


def test_eval_05_has_six_separate_unmistakably_synthetic_accounting_inputs():
    root = CASES_ROOT / "eval-05"
    case = _json(root / "case.json")
    assert {item["path"] for item in case["evidence_files"]} == EVAL05_INPUTS

    combined = ""
    statuses: set[str] = set()
    for relative in sorted(EVAL05_INPUTS):
        value = _json(root / relative)
        assert value["synthetic_fixture"] is True
        assert value["fixture_namespace"] == "SYNTHETIC-EVAL05"
        combined += json.dumps(value, sort_keys=True)
        for mapping in _walk_dicts(value):
            if "status" in mapping:
                statuses.add(mapping["status"])
            if "synthetic_amount_units" in mapping:
                assert mapping["unit"] == "SYNTHETIC_USD_FIXTURE"
            if "identifier" in mapping:
                assert str(mapping["identifier"]).startswith("SYNTHETIC-")

    assert statuses >= {"complete", "partial", "missing", "not-applicable"}
    assert "SYNTHETIC-JURISDICTION-" in combined
    assert "SYNTHETIC-FORM-" in combined
    assert "SYNTHETIC-PERIOD-" in combined
    assert "conflict" in combined.lower()
    assert 'remote_identifiers_included": false' in combined
    assert 'credentials_included": false' in combined


def test_eval_05_expected_gap_interpretation_exists_only_in_private_oracle():
    root = CASES_ROOT / "eval-05"
    runtime_text = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in sorted(EVAL05_INPUTS)
    )
    oracle_text = (root / "oracle" / "expected.json").read_text(encoding="utf-8")
    assert "expected_gaps" not in runtime_text
    assert "expected_contributions" not in runtime_text
    assert "expected_gaps" in oracle_text
    assert "professional judgment" in oracle_text
    assert "final filing authority" in oracle_text


def test_eval_07_separates_private_input_shareable_input_and_oracle_assertions():
    root = CASES_ROOT / "eval-07"
    case = _json(root / "case.json")
    paths = tuple(item["path"] for item in case["evidence_files"])
    assert paths == (
        "input/shareable/decision-context.json",
        "input/private/personal-context.json",
    )

    private_text = (root / paths[1]).read_text(encoding="utf-8")
    shareable_text = (root / paths[0]).read_text(encoding="utf-8")
    oracle = _json(root / "oracle" / "expected.json")
    assert "PRIVATE_PERSONAL" in private_text
    assert "PERSONAL_ONLY" in private_text
    assert all(
        marker not in shareable_text for marker in oracle["prohibited_shared_markers"]
    )
    assert scan_synthetic_text(shareable_text, location_class="shared-artifact") == ()
    assert oracle["private_draft_assertions"]
    assert oracle["shareable_artifact_assertions"]
    assert "unattended-push-attempt" in oracle["reject_conditions"]


def test_fixture_tree_contains_no_runtime_outputs_or_live_execution_material():
    allowed_names = {"case.json", "expected.json"}
    for path in CASES_ROOT.rglob("*"):
        if not path.is_file():
            continue
        assert path.suffix == ".json"
        if path.name not in allowed_names:
            assert "input" in path.parts
        assert not any(
            part in {"output", "transcript", "run", "artifacts"} for part in path.parts
        )
