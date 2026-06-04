"""
Tests for stride_coverage.py — bundled alongside the checker.

Run with:  python3 -m pytest .claude/skills/security/threat-modeling/scripts/test_stride_coverage.py -v
Or from within this directory: python3 -m pytest test_stride_coverage.py -v
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load module
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "stride_coverage.py"

import importlib.util

spec = importlib.util.spec_from_file_location("stride_coverage", SCRIPT)
stride_coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stride_coverage)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_finding(**overrides):
    base = {
        "title": "Test Finding",
        "stride": ["S"],
    }
    base.update(overrides)
    return base


def make_scored_finding(**overrides):
    """Finding with all DREAD dimensions."""
    base = {
        "title": "Scored Finding",
        "stride": ["S"],
        "D": 5,
        "R": 5,
        "E": 5,
        "A": 5,
        "D2": 5,
    }
    base.update(overrides)
    return base


def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_json_output(out: str) -> dict:
    """Parse the JSON block (first chunk before the blank line separator)."""
    return json.loads(out.split("\n\n")[0])


# ---------------------------------------------------------------------------
# STRIDE alias normalization
# ---------------------------------------------------------------------------


class TestStrideAliasNormalization:
    def test_canonical_key_s(self):
        assert stride_coverage.normalize_stride_tag("S", "x") == "S"

    def test_canonical_key_r2(self):
        assert stride_coverage.normalize_stride_tag("R2", "x") == "R2"

    def test_canonical_key_d3(self):
        assert stride_coverage.normalize_stride_tag("D3", "x") == "D3"

    def test_full_name_spoofing(self):
        assert stride_coverage.normalize_stride_tag("Spoofing", "x") == "S"

    def test_full_name_repudiation(self):
        assert stride_coverage.normalize_stride_tag("Repudiation", "x") == "R2"

    def test_full_name_denial_of_service(self):
        assert stride_coverage.normalize_stride_tag("Denial of Service", "x") == "D3"

    def test_alias_dos(self):
        assert stride_coverage.normalize_stride_tag("DoS", "x") == "D3"

    def test_alias_rep(self):
        assert stride_coverage.normalize_stride_tag("Rep", "x") == "R2"

    def test_alias_eop(self):
        assert stride_coverage.normalize_stride_tag("eop", "x") == "E"

    def test_case_insensitive(self):
        assert stride_coverage.normalize_stride_tag("SPOOFING", "x") == "S"
        assert stride_coverage.normalize_stride_tag("tampering", "x") == "T"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown STRIDE category"):
            stride_coverage.normalize_stride_tag("XSS", "x")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="unknown STRIDE category"):
            stride_coverage.normalize_stride_tag("", "x")


# ---------------------------------------------------------------------------
# validate_finding
# ---------------------------------------------------------------------------


class TestValidateFinding:
    def test_minimal_valid(self):
        f = stride_coverage.validate_finding(make_finding(), 0)
        assert f["title"] == "Test Finding"
        assert f["stride"] == ["S"]

    def test_missing_title_raises(self):
        with pytest.raises(ValueError, match="title"):
            stride_coverage.validate_finding({"stride": ["S"]}, 0)

    def test_missing_stride_raises(self):
        with pytest.raises(ValueError, match="'stride'"):
            stride_coverage.validate_finding({"title": "x"}, 0)

    def test_empty_stride_array_raises(self):
        with pytest.raises(ValueError, match="non-empty JSON array"):
            stride_coverage.validate_finding({"title": "x", "stride": []}, 0)

    def test_stride_not_list_raises(self):
        with pytest.raises(ValueError, match="non-empty JSON array"):
            stride_coverage.validate_finding({"title": "x", "stride": "S"}, 0)

    def test_non_string_tag_raises(self):
        with pytest.raises(ValueError, match="must be a string"):
            stride_coverage.validate_finding({"title": "x", "stride": [1]}, 0)

    def test_duplicate_tags_deduplicated(self):
        f = stride_coverage.validate_finding(
            {"title": "x", "stride": ["S", "S", "T"]}, 0
        )
        assert f["stride"] == ["S", "T"]

    def test_full_name_normalized(self):
        f = stride_coverage.validate_finding(
            {"title": "x", "stride": ["Spoofing", "Tampering"]}, 0
        )
        assert f["stride"] == ["S", "T"]

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            stride_coverage.validate_finding("not a dict", 0)


# ---------------------------------------------------------------------------
# compute_coverage
# ---------------------------------------------------------------------------


class TestComputeCoverage:
    def _make_validated(self, stride_keys: list[str], title: str = "T") -> dict:
        return {"title": title, "stride": stride_keys}

    def test_all_covered_no_gaps(self):
        findings = [
            self._make_validated(["S", "T"], "f1"),
            self._make_validated(["R2", "I"], "f2"),
            self._make_validated(["D3", "E"], "f3"),
        ]
        coverage, gaps = stride_coverage.compute_coverage(findings)
        assert gaps == []
        assert "f1" in coverage["S"]
        assert "f1" in coverage["T"]

    def test_single_finding_five_gaps(self):
        findings = [self._make_validated(["S"], "f1")]
        coverage, gaps = stride_coverage.compute_coverage(findings)
        assert "S" not in gaps
        assert set(gaps) == {"T", "R2", "I", "D3", "E"}

    def test_empty_findings_all_gaps(self):
        coverage, gaps = stride_coverage.compute_coverage([])
        assert set(gaps) == set(stride_coverage.STRIDE_KEYS)

    def test_coverage_lists_correct_findings(self):
        findings = [
            self._make_validated(["S"], "find-A"),
            self._make_validated(["S", "T"], "find-B"),
        ]
        coverage, gaps = stride_coverage.compute_coverage(findings)
        assert "find-A" in coverage["S"]
        assert "find-B" in coverage["S"]
        assert "find-B" in coverage["T"]
        assert "find-A" not in coverage["T"]


# ---------------------------------------------------------------------------
# score_finding (DREAD)
# ---------------------------------------------------------------------------


class TestScoreFinding:
    def test_no_dread_dims_returns_none(self):
        f = {"title": "x", "stride": ["S"]}
        assert stride_coverage.score_finding(f) is None

    def test_all_fives_medium(self):
        f = make_scored_finding()
        score, band = stride_coverage.score_finding(f)
        assert score == 5.0
        assert band == "Medium"

    def test_all_tens_critical(self):
        f = make_scored_finding(D=10, R=10, E=10, A=10, D2=10)
        score, band = stride_coverage.score_finding(f)
        assert score == 10.0
        assert band == "Critical"

    def test_all_ones_low(self):
        f = make_scored_finding(D=1, R=1, E=1, A=1, D2=1)
        score, band = stride_coverage.score_finding(f)
        assert score == 1.0
        assert band == "Low"

    def test_partial_dread_raises(self):
        f = {"title": "x", "stride": ["S"], "D": 5, "R": 5}  # missing E, A, D2
        with pytest.raises(ValueError, match="partial DREAD scores"):
            stride_coverage.score_finding(f)

    def test_invalid_dim_out_of_range(self):
        f = make_scored_finding(D=0)
        with pytest.raises(ValueError, match="out of range"):
            stride_coverage.score_finding(f)

    def test_dim_eleven_out_of_range(self):
        f = make_scored_finding(D=11)
        with pytest.raises(ValueError, match="out of range"):
            stride_coverage.score_finding(f)

    def test_bool_dim_rejected(self):
        f = make_scored_finding(D=True)
        with pytest.raises(ValueError, match="must be a number"):
            stride_coverage.score_finding(f)

    def test_boundary_9_critical(self):
        f = make_scored_finding(D=9, R=9, E=9, A=9, D2=9)
        score, band = stride_coverage.score_finding(f)
        assert score == 9.0
        assert band == "Critical"

    def test_boundary_4_medium(self):
        f = make_scored_finding(D=4, R=4, E=4, A=4, D2=4)
        score, band = stride_coverage.score_finding(f)
        assert score == 4.0
        assert band == "Medium"

    def test_boundary_7_high(self):
        f = make_scored_finding(D=7, R=7, E=7, A=7, D2=7)
        score, band = stride_coverage.score_finding(f)
        assert score == 7.0
        assert band == "High"


# ---------------------------------------------------------------------------
# load_input
# ---------------------------------------------------------------------------


class TestLoadInput:
    def test_empty_stdin_returns_empty(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert stride_coverage.load_input(None) == []

    def test_valid_stdin(self, monkeypatch):
        data = [make_finding()]
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
        result = stride_coverage.load_input(None)
        assert len(result) == 1

    def test_file_path(self, tmp_path):
        data = [make_finding(title="from-file")]
        p = tmp_path / "findings.json"
        p.write_text(json.dumps(data))
        result = stride_coverage.load_input(str(p))
        assert result[0]["title"] == "from-file"

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            stride_coverage.load_input("/no/such/file.json")

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
        with pytest.raises(ValueError, match="Invalid JSON"):
            stride_coverage.load_input(None)

    def test_object_not_array_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO('{"title":"x"}'))
        with pytest.raises(ValueError, match="must be a JSON array"):
            stride_coverage.load_input(None)


# ---------------------------------------------------------------------------
# Integration (subprocess)
# ---------------------------------------------------------------------------


class TestSubprocessIntegration:
    def test_full_coverage_exits_zero(self):
        findings = [
            make_finding(title="Spoof", stride=["S"]),
            make_finding(title="Tamper", stride=["T"]),
            make_finding(title="Repud", stride=["R2"]),
            make_finding(title="Info", stride=["I"]),
            make_finding(title="DoS", stride=["D3"]),
            make_finding(title="EoP", stride=["E"]),
        ]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["gaps"] == 0

    def test_gap_reported(self):
        findings = [make_finding(title="Spoof only", stride=["S"])]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["gaps"] == 5  # T, R2, I, D3, E missing

    def test_dread_scoring_integrated(self):
        findings = [
            make_scored_finding(
                title="Critical threat",
                stride=["S", "E"],
                D=10,
                R=10,
                E=10,
                A=10,
                D2=10,
            ),
            make_scored_finding(
                title="Low threat", stride=["T"], D=1, R=1, E=1, A=1, D2=1
            ),
        ]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        # Critical threat should rank first
        assert result["findings"][0]["title"] == "Critical threat"
        assert result["summary"]["critical"] == 1
        assert result["summary"]["low"] == 1

    def test_empty_input_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="[]")
        assert code == 0

    def test_missing_title_exits_nonzero(self):
        findings = [{"stride": ["S"]}]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_missing_stride_exits_nonzero(self):
        findings = [{"title": "x"}]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_unknown_stride_tag_exits_nonzero(self):
        findings = [{"title": "x", "stride": ["XYZ"]}]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_partial_dread_exits_nonzero(self):
        findings = [{"title": "x", "stride": ["S"], "D": 5, "R": 5}]  # partial
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_coverage_markdown_in_output(self):
        findings = [make_finding(title="x", stride=["S"])]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        assert "STRIDE Coverage" in out
        assert "Spoofing" in out
        assert "GAP" in out

    def test_dread_table_present_when_scores_provided(self):
        findings = [make_scored_finding(title="scored", stride=["S"])]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        assert "DREAD Severity Rankings" in out

    def test_dread_table_absent_when_no_scores(self):
        findings = [make_finding(title="unscored", stride=["S"])]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        assert "DREAD Severity Rankings" not in out

    def test_file_path_argument(self, tmp_path):
        findings = [
            make_finding(title="File test", stride=["S", "T", "R2", "I", "D3", "E"]),
        ]
        p = tmp_path / "findings.json"
        p.write_text(json.dumps(findings))
        code, out, err = run_script(args=(str(p),))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["gaps"] == 0

    def test_full_name_aliases_accepted(self):
        findings = [make_finding(title="x", stride=["Spoofing", "Denial of Service"])]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert "S" in result["coverage"]
        assert "D3" in result["coverage"]
