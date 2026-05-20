"""
Tests for dread_score.py — bundled alongside the scorer.

Run with:  python3 -m pytest .claude/skills/security/stride-dread/scripts/test_dread_score.py -v
Or from within this directory: python3 -m pytest test_dread_score.py -v
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Resolve the scorer module path so tests work regardless of cwd
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "dread_score.py"

# Import the module functions directly for unit tests
import importlib.util

spec = importlib.util.spec_from_file_location("dread_score", SCRIPT)
dread_score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dread_score)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_finding(**overrides):
    """Return a minimal valid finding dict, optionally overriding fields."""
    base = {"title": "Test Finding", "D": 5, "R": 5, "E": 5, "A": 5, "D2": 5}
    base.update(overrides)
    return base


def run_script(args=(), stdin_text=None):
    """Run dread_score.py as a subprocess; return (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# assign_band — boundary values
# ---------------------------------------------------------------------------

class TestAssignBand:
    def test_low_boundary_low_end(self):
        assert dread_score.assign_band(1.0) == "Low"

    def test_low_boundary_top(self):
        # 3.9 is the highest Low
        assert dread_score.assign_band(3.9) == "Low"

    def test_medium_boundary_bottom(self):
        # 4.0 is the lowest Medium
        assert dread_score.assign_band(4.0) == "Medium"

    def test_medium_boundary_top(self):
        assert dread_score.assign_band(6.9) == "Medium"

    def test_high_boundary_bottom(self):
        # 7.0 is the lowest High
        assert dread_score.assign_band(7.0) == "High"

    def test_high_boundary_top(self):
        assert dread_score.assign_band(8.9) == "High"

    def test_critical_boundary_bottom(self):
        # 9.0 is the lowest Critical
        assert dread_score.assign_band(9.0) == "Critical"

    def test_critical_boundary_top(self):
        assert dread_score.assign_band(10.0) == "Critical"

    def test_midpoints(self):
        assert dread_score.assign_band(2.0) == "Low"
        assert dread_score.assign_band(5.5) == "Medium"
        assert dread_score.assign_band(8.0) == "High"
        assert dread_score.assign_band(9.5) == "Critical"


# ---------------------------------------------------------------------------
# score_finding — arithmetic correctness
# ---------------------------------------------------------------------------

class TestScoreFinding:
    def test_all_tens_is_critical(self):
        f = dread_score.validate_finding(make_finding(D=10, R=10, E=10, A=10, D2=10), 0)
        result = dread_score.score_finding(f)
        assert result["score"] == 10.0
        assert result["band"] == "Critical"

    def test_all_ones_is_low(self):
        f = dread_score.validate_finding(make_finding(D=1, R=1, E=1, A=1, D2=1), 0)
        result = dread_score.score_finding(f)
        assert result["score"] == 1.0
        assert result["band"] == "Low"

    def test_average_rounds_to_one_decimal(self):
        # (1+2+3+4+5)/5 = 3.0 exactly
        f = dread_score.validate_finding(make_finding(D=1, R=2, E=3, A=4, D2=5), 0)
        result = dread_score.score_finding(f)
        assert result["score"] == 3.0

    def test_fractional_average(self):
        # (7+8+9+10+6)/5 = 40/5 = 8.0
        f = dread_score.validate_finding(make_finding(D=7, R=8, E=9, A=10, D2=6), 0)
        result = dread_score.score_finding(f)
        assert result["score"] == 8.0
        assert result["band"] == "High"

    def test_boundary_4_is_medium_not_low(self):
        # score = (4+4+4+4+4)/5 = 4.0 -> Medium
        f = dread_score.validate_finding(make_finding(D=4, R=4, E=4, A=4, D2=4), 0)
        result = dread_score.score_finding(f)
        assert result["score"] == 4.0
        assert result["band"] == "Medium"

    def test_boundary_9_is_critical_not_high(self):
        # score = (9+9+9+9+9)/5 = 9.0 -> Critical
        f = dread_score.validate_finding(make_finding(D=9, R=9, E=9, A=9, D2=9), 0)
        result = dread_score.score_finding(f)
        assert result["score"] == 9.0
        assert result["band"] == "Critical"


# ---------------------------------------------------------------------------
# validate_finding — invalid dimension rejection
# ---------------------------------------------------------------------------

class TestValidateFinding:
    def test_zero_is_invalid(self):
        with pytest.raises(ValueError, match="out of range"):
            dread_score.validate_finding(make_finding(D=0), 0)

    def test_eleven_is_invalid(self):
        with pytest.raises(ValueError, match="out of range"):
            dread_score.validate_finding(make_finding(R=11), 0)

    def test_negative_is_invalid(self):
        with pytest.raises(ValueError, match="out of range"):
            dread_score.validate_finding(make_finding(E=-1), 0)

    def test_string_dim_is_invalid(self):
        with pytest.raises(ValueError, match="must be a number"):
            dread_score.validate_finding(make_finding(A="high"), 0)

    def test_bool_is_invalid(self):
        # booleans are subclass of int in Python; we explicitly reject them
        with pytest.raises(ValueError, match="must be a number"):
            dread_score.validate_finding(make_finding(D2=True), 0)

    def test_none_dim_is_invalid(self):
        with pytest.raises(ValueError, match="must be a number"):
            dread_score.validate_finding(make_finding(D=None), 0)

    def test_missing_dim_reports_field_name(self):
        finding = {"title": "Missing D2", "D": 5, "R": 5, "E": 5, "A": 5}
        with pytest.raises(ValueError, match="D2"):
            dread_score.validate_finding(finding, 0)

    def test_missing_title_raises(self):
        finding = {"D": 5, "R": 5, "E": 5, "A": 5, "D2": 5}
        with pytest.raises(ValueError, match="title"):
            dread_score.validate_finding(finding, 0)

    def test_boundary_1_is_valid(self):
        f = dread_score.validate_finding(make_finding(D=1), 0)
        assert f["D"] == 1.0

    def test_boundary_10_is_valid(self):
        f = dread_score.validate_finding(make_finding(D2=10), 0)
        assert f["D2"] == 10.0

    def test_float_dim_is_valid(self):
        # floats like 7.5 are allowed
        f = dread_score.validate_finding(make_finding(D=7.5), 0)
        assert f["D"] == 7.5


# ---------------------------------------------------------------------------
# load_input — stdin vs file path
# ---------------------------------------------------------------------------

class TestLoadInput:
    def test_stdin_hyphen(self, monkeypatch):
        data = [make_finding()]
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
        result = dread_score.load_input("-")
        assert len(result) == 1

    def test_stdin_none(self, monkeypatch):
        data = [make_finding(title="stdin-none")]
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(data)))
        result = dread_score.load_input(None)
        assert result[0]["title"] == "stdin-none"

    def test_file_path(self, tmp_path):
        data = [make_finding(title="from-file")]
        p = tmp_path / "findings.json"
        p.write_text(json.dumps(data))
        result = dread_score.load_input(str(p))
        assert result[0]["title"] == "from-file"

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            dread_score.load_input("/nonexistent/path/findings.json")

    def test_empty_stdin_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        result = dread_score.load_input(None)
        assert result == []

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("{not valid json"))
        with pytest.raises(ValueError, match="Invalid JSON"):
            dread_score.load_input(None)

    def test_non_array_json_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO('{"title": "oops"}'))
        with pytest.raises(ValueError, match="must be a JSON array"):
            dread_score.load_input(None)


# ---------------------------------------------------------------------------
# Ranking order — subprocess integration tests
# ---------------------------------------------------------------------------

class TestRankingOrder:
    def _run_with_findings(self, findings):
        payload = json.dumps(findings)
        code, out, err = run_script(args=("-",), stdin_text=payload)
        return code, out, err

    def test_ranked_by_score_descending(self):
        findings = [
            make_finding(title="Low Finding", D=1, R=1, E=1, A=1, D2=1),       # score 1.0
            make_finding(title="Critical Finding", D=10, R=10, E=10, A=10, D2=10),  # score 10.0
            make_finding(title="Medium Finding", D=5, R=5, E=5, A=5, D2=5),    # score 5.0
        ]
        code, out, _ = self._run_with_findings(findings)
        assert code == 0
        result = json.loads(out.split("\n\n")[0])  # first block before blank line is JSON
        titles = [f["title"] for f in result["findings"]]
        assert titles[0] == "Critical Finding"
        assert titles[-1] == "Low Finding"

    def test_summary_counts_bands(self):
        findings = [
            make_finding(title="C1", D=10, R=10, E=10, A=10, D2=10),
            make_finding(title="H1", D=7, R=7, E=7, A=7, D2=7),
            make_finding(title="M1", D=5, R=5, E=5, A=5, D2=5),
            make_finding(title="L1", D=1, R=1, E=1, A=1, D2=1),
        ]
        code, out, _ = self._run_with_findings(findings)
        assert code == 0
        result = json.loads(out.split("\n\n")[0])
        assert result["summary"]["critical"] == 1
        assert result["summary"]["high"] == 1
        assert result["summary"]["medium"] == 1
        assert result["summary"]["low"] == 1

    def test_markdown_table_present(self):
        findings = [make_finding()]
        code, out, _ = self._run_with_findings(findings)
        assert code == 0
        assert "| # |" in out
        assert "DREAD Severity Rankings" in out


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_array_exits_zero(self):
        code, out, err = run_script(args=("-",), stdin_text="[]")
        assert code == 0
        result = json.loads(out.split("\n\n")[0])
        assert result["findings"] == []

    def test_empty_stdin_exits_zero(self):
        code, out, err = run_script(args=("-",), stdin_text="")
        assert code == 0

    def test_whitespace_only_stdin_exits_zero(self):
        code, out, err = run_script(args=("-",), stdin_text="   \n  ")
        assert code == 0


# ---------------------------------------------------------------------------
# Invalid input — subprocess must exit non-zero
# ---------------------------------------------------------------------------

class TestInvalidInputSubprocess:
    def test_invalid_dim_value_exits_nonzero(self):
        findings = [make_finding(D=0)]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_missing_dimension_exits_nonzero(self):
        findings = [{"title": "Missing dims", "D": 5, "R": 5}]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0

    def test_bad_json_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text="not json at all")
        assert code != 0
        assert "ERROR" in err

    def test_object_instead_of_array_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text='{"title":"oops"}')
        assert code != 0


# ---------------------------------------------------------------------------
# File-path argument integration
# ---------------------------------------------------------------------------

class TestFilePathArgument:
    def test_file_path_argument(self, tmp_path):
        findings = [make_finding(title="File Input Test", D=8, R=8, E=8, A=8, D2=8)]
        p = tmp_path / "test_findings.json"
        p.write_text(json.dumps(findings))
        code, out, err = run_script(args=(str(p),))
        assert code == 0
        result = json.loads(out.split("\n\n")[0])
        assert result["findings"][0]["title"] == "File Input Test"
        assert result["findings"][0]["band"] == "High"

    def test_nonexistent_file_exits_nonzero(self):
        code, _, err = run_script(args=("/no/such/file.json",))
        assert code != 0
        assert "ERROR" in err
