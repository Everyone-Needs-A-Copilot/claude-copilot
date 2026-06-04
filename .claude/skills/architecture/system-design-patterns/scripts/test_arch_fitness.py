"""
Tests for arch_fitness.py — bundled alongside the scorer.

Run with:
  python3 -m pytest .claude/skills/architecture/system-design-patterns/scripts/test_arch_fitness.py -v
"""

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "arch_fitness.py"

spec = importlib.util.spec_from_file_location("arch_fitness", SCRIPT)
arch_fitness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arch_fitness)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_json_block(stdout: str) -> dict:
    return json.loads(stdout.split("\n\n")[0])


def full_adr(**overrides):
    """Build a fully-complete ADR document."""
    doc = {
        "id": "ADR-001",
        "title": "Use PostgreSQL as primary database",
        "status": "accepted",
        "date": "2026-01-15",
        "context": "We need a relational database that supports ACID transactions.",
        "decision": "We will use PostgreSQL because it is battle-tested and open source.",
        "consequences": "Positive: ACID transactions. Negative: operational complexity.",
        "alternatives": [{"alternative": "MySQL", "reason": "Limited JSON support"}],
        "references": ["https://postgresql.org"],
        "trade_off_checklist": {
            "quality_attribute_optimised": True,
            "quality_attribute_sacrificed": True,
            "reversibility": True,
            "evidence_based": True,
            "team_readiness": True,
            "failure_mode_understood": True,
            "migration_path": True,
            "documentation": True,
        },
    }
    doc.update(overrides)
    return doc


def minimal_adr(**overrides):
    """Build the minimum valid ADR (all 7 required fields, no optionals)."""
    doc = {
        "id": "ADR-002",
        "title": "Minimal ADR",
        "status": "proposed",
        "date": "2026-02-01",
        "context": "Context here.",
        "decision": "We will do X.",
        "consequences": "Positive: A. Negative: B.",
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# assign_band — boundary values
# ---------------------------------------------------------------------------


class TestAssignBand:
    def test_100_is_complete(self):
        assert arch_fitness.assign_band(100.0) == "COMPLETE"

    def test_90_is_complete(self):
        assert arch_fitness.assign_band(90.0) == "COMPLETE"

    def test_89_9_is_adequate(self):
        assert arch_fitness.assign_band(89.9) == "ADEQUATE"

    def test_70_is_adequate(self):
        assert arch_fitness.assign_band(70.0) == "ADEQUATE"

    def test_69_9_is_partial(self):
        assert arch_fitness.assign_band(69.9) == "PARTIAL"

    def test_50_is_partial(self):
        assert arch_fitness.assign_band(50.0) == "PARTIAL"

    def test_49_9_is_incomplete(self):
        assert arch_fitness.assign_band(49.9) == "INCOMPLETE"

    def test_0_is_incomplete(self):
        assert arch_fitness.assign_band(0.0) == "INCOMPLETE"


# ---------------------------------------------------------------------------
# score_document — coverage arithmetic
# ---------------------------------------------------------------------------


class TestScoreDocument:
    def test_all_required_fields_100_percent(self):
        doc = minimal_adr()
        result = arch_fitness.score_document(doc)
        assert result["coverage_pct"] == 100.0
        assert result["band"] == "COMPLETE"

    def test_missing_one_required_field_reduces_coverage(self):
        # 6 of 7 fields present = 85.7% → ADEQUATE
        doc = minimal_adr()
        del doc["consequences"]
        result = arch_fitness.score_document(doc)
        assert result["coverage_pct"] < 90.0
        assert result["band"] == "ADEQUATE"

    def test_missing_three_required_fields_partial_or_incomplete(self):
        # 4 of 7 = 57.1% → PARTIAL
        doc = minimal_adr()
        del doc["consequences"]
        del doc["decision"]
        del doc["context"]
        result = arch_fitness.score_document(doc)
        assert result["coverage_pct"] < 70.0

    def test_only_id_present_is_incomplete(self):
        doc = {"id": "ADR-X"}
        result = arch_fitness.score_document(doc)
        assert result["band"] == "INCOMPLETE"
        assert result["coverage_pct"] < 50.0

    def test_full_adr_100_percent(self):
        doc = full_adr()
        result = arch_fitness.score_document(doc)
        assert result["coverage_pct"] == 100.0
        assert result["band"] == "COMPLETE"

    def test_no_gaps_for_full_required_fields(self):
        doc = minimal_adr()
        result = arch_fitness.score_document(doc)
        # Only LOW-severity trade-off checklist advisory expected
        high_medium = [g for g in result["gaps"] if g["severity"] in ("HIGH", "MEDIUM")]
        assert len(high_medium) == 0

    def test_missing_context_is_high_severity(self):
        doc = minimal_adr()
        del doc["context"]
        result = arch_fitness.score_document(doc)
        high_gaps = [g for g in result["gaps"] if g["severity"] == "HIGH"]
        assert any("context" in g["location"] for g in high_gaps)

    def test_missing_decision_is_high_severity(self):
        doc = minimal_adr()
        del doc["decision"]
        result = arch_fitness.score_document(doc)
        high_gaps = [g for g in result["gaps"] if g["severity"] == "HIGH"]
        assert any("decision" in g["location"] for g in high_gaps)

    def test_missing_consequences_is_high_severity(self):
        doc = minimal_adr()
        del doc["consequences"]
        result = arch_fitness.score_document(doc)
        high_gaps = [g for g in result["gaps"] if g["severity"] == "HIGH"]
        assert any("consequences" in g["location"] for g in high_gaps)

    def test_missing_id_is_medium_severity(self):
        doc = minimal_adr()
        del doc["id"]
        # id is required; check validates and scores still work
        result = arch_fitness.score_document(doc)
        medium_gaps = [g for g in result["gaps"] if g["severity"] == "MEDIUM"]
        assert len(medium_gaps) >= 1

    def test_invalid_status_flagged(self):
        doc = minimal_adr(status="approved")  # not in VALID_STATUSES
        result = arch_fitness.score_document(doc)
        gap_msgs = [g["message"] for g in result["gaps"]]
        assert any("Invalid status" in m for m in gap_msgs)

    def test_valid_statuses_not_flagged(self):
        for status in arch_fitness.VALID_STATUSES:
            doc = minimal_adr(status=status)
            result = arch_fitness.score_document(doc)
            assert not any("Invalid status" in g["message"] for g in result["gaps"])

    def test_invalid_date_format_low_severity(self):
        doc = minimal_adr(date="15/01/2026")  # wrong format
        result = arch_fitness.score_document(doc)
        low_gaps = [g for g in result["gaps"] if g["severity"] == "LOW"]
        assert any("ISO 8601" in g["message"] for g in low_gaps)

    def test_valid_iso_date_not_flagged(self):
        doc = minimal_adr(date="2026-01-15")
        result = arch_fitness.score_document(doc)
        assert not any("ISO 8601" in g["message"] for g in result["gaps"])

    def test_trade_off_checklist_missing_keys_flagged_low(self):
        doc = minimal_adr(trade_off_checklist={"quality_attribute_optimised": True})
        result = arch_fitness.score_document(doc)
        low_gaps = [g for g in result["gaps"] if g["severity"] == "LOW"]
        # 7 of 8 keys missing
        assert len([g for g in low_gaps if "trade_off_checklist" in g["location"]]) == 7

    def test_full_checklist_no_checklist_gaps(self):
        checklist = {k: True for k in arch_fitness.TRADE_OFF_FIELDS}
        doc = minimal_adr(trade_off_checklist=checklist)
        result = arch_fitness.score_document(doc)
        checklist_gaps = [
            g for g in result["gaps"] if "trade_off_checklist" in g["location"]
        ]
        assert len(checklist_gaps) == 0

    def test_no_trade_off_checklist_has_single_advisory(self):
        doc = minimal_adr()  # no trade_off_checklist
        result = arch_fitness.score_document(doc)
        advisory = [g for g in result["gaps"] if "trade_off_checklist" in g["location"]]
        assert len(advisory) == 1
        assert advisory[0]["severity"] == "LOW"

    def test_optional_present_tracked(self):
        doc = full_adr()
        result = arch_fitness.score_document(doc)
        assert "alternatives" in result["optional_present"]
        assert "references" in result["optional_present"]


# ---------------------------------------------------------------------------
# coverage_pct arithmetic correctness
# ---------------------------------------------------------------------------


class TestCoverageArithmetic:
    def test_7_of_7_is_100(self):
        doc = minimal_adr()
        result = arch_fitness.score_document(doc)
        assert result["coverage_pct"] == 100.0

    def test_6_of_7_is_85_7(self):
        doc = minimal_adr()
        del doc["title"]
        result = arch_fitness.score_document(doc)
        # 6/7 = 0.857... rounded to 1 decimal = 85.7
        assert result["coverage_pct"] == round(6 / 7 * 100, 1)

    def test_1_of_7_is_14_3(self):
        doc = {"id": "ADR-X"}
        result = arch_fitness.score_document(doc)
        assert result["coverage_pct"] == round(1 / 7 * 100, 1)


# ---------------------------------------------------------------------------
# load_input
# ---------------------------------------------------------------------------


class TestLoadInput:
    def test_stdin_hyphen(self, monkeypatch):
        data = [minimal_adr()]
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
        result = arch_fitness.load_input("-")
        assert len(result) == 1

    def test_stdin_none(self, monkeypatch):
        data = [minimal_adr()]
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
        result = arch_fitness.load_input(None)
        assert result[0]["id"] == "ADR-002"

    def test_file_path(self, tmp_path):
        data = [minimal_adr()]
        p = tmp_path / "adrs.json"
        p.write_text(json.dumps(data))
        result = arch_fitness.load_input(str(p))
        assert result[0]["id"] == "ADR-002"

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            arch_fitness.load_input("/nonexistent/adrs.json")

    def test_empty_stdin_returns_none(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        result = arch_fitness.load_input(None)
        assert result is None

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("{bad"))
        with pytest.raises(ValueError, match="Invalid JSON"):
            arch_fitness.load_input(None)

    def test_object_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO('{"id": "x"}'))
        with pytest.raises(ValueError, match="must be a JSON array"):
            arch_fitness.load_input(None)


# ---------------------------------------------------------------------------
# Subprocess integration
# ---------------------------------------------------------------------------


class TestSubprocess:
    def test_valid_input_exits_zero(self):
        data = [minimal_adr()]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0

    def test_output_has_json_block(self):
        data = [minimal_adr()]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        result = parse_json_block(out)
        assert "documents" in result
        assert "summary" in result

    def test_output_has_markdown_section(self):
        data = [minimal_adr()]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        assert "Architecture Decision Record" in out

    def test_empty_input_exits_zero(self):
        code, out, err = run_script(args=("-",), stdin_text="")
        assert code == 0

    def test_empty_array_exits_zero(self):
        code, out, err = run_script(args=("-",), stdin_text="[]")
        assert code == 0
        result = parse_json_block(out)
        assert result["summary"]["total"] == 0

    def test_bad_json_exits_nonzero(self):
        code, out, err = run_script(args=("-",), stdin_text="not json")
        assert code != 0
        assert "ERROR" in err

    def test_object_not_array_exits_nonzero(self):
        code, out, err = run_script(args=("-",), stdin_text='{"id": "x"}')
        assert code != 0
        assert "ERROR" in err

    def test_file_path_argument(self, tmp_path):
        data = [minimal_adr()]
        p = tmp_path / "adrs.json"
        p.write_text(json.dumps(data))
        code, out, err = run_script(args=(str(p),))
        assert code == 0
        result = parse_json_block(out)
        assert result["documents"][0]["id"] == "ADR-002"

    def test_nonexistent_file_exits_nonzero(self):
        code, _, err = run_script(args=("/no/such/file.json",))
        assert code != 0
        assert "ERROR" in err

    def test_multiple_documents(self):
        data = [minimal_adr(id="ADR-001"), minimal_adr(id="ADR-002")]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        result = parse_json_block(out)
        assert result["summary"]["total"] == 2

    def test_summary_counts_add_up(self):
        data = [minimal_adr(), full_adr()]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        result = parse_json_block(out)
        s = result["summary"]
        total = s["complete"] + s["adequate"] + s["partial"] + s["incomplete"]
        assert total == s["total"]

    def test_full_adr_has_no_high_medium_gaps(self):
        data = [full_adr()]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        result = parse_json_block(out)
        doc = result["documents"][0]
        high_med = [g for g in doc["gaps"] if g["severity"] in ("HIGH", "MEDIUM")]
        assert len(high_med) == 0

    def test_non_dict_element_exits_nonzero(self):
        data = ["not-an-object"]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code != 0
        assert "ERROR" in err

    def test_band_boundaries_90_percent(self):
        # 6 of 7 fields = 85.7% → ADEQUATE; 7 of 7 = 100% → COMPLETE
        full = [minimal_adr()]
        code, out, err = run_script(args=("-",), stdin_text=json.dumps(full))
        assert code == 0
        result = parse_json_block(out)
        assert result["documents"][0]["band"] == "COMPLETE"
