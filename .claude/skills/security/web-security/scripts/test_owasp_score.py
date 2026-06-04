"""
Tests for owasp_score.py — bundled alongside the scorer.

Run with:  python3 -m pytest .claude/skills/security/web-security/scripts/test_owasp_score.py -v
Or from within this directory: python3 -m pytest test_owasp_score.py -v
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
SCRIPT = Path(__file__).parent / "owasp_score.py"

import importlib.util

spec = importlib.util.spec_from_file_location("owasp_score", SCRIPT)
owasp_score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owasp_score)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_finding(**overrides):
    base = {"title": "Test Finding", "owasp": "A03"}
    base.update(overrides)
    return base


def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_json_output(out: str) -> dict:
    return json.loads(out.split("\n\n")[0])


# ---------------------------------------------------------------------------
# normalize_owasp
# ---------------------------------------------------------------------------


class TestNormalizeOwasp:
    def test_short_code_a01(self):
        assert owasp_score.normalize_owasp("A01", "x") == "A01"

    def test_short_code_a10(self):
        assert owasp_score.normalize_owasp("A10", "x") == "A10"

    def test_lowercase_short_code(self):
        assert owasp_score.normalize_owasp("a03", "x") == "A03"

    def test_full_name_injection(self):
        assert owasp_score.normalize_owasp("Injection", "x") == "A03"

    def test_full_name_case_insensitive(self):
        assert owasp_score.normalize_owasp("INJECTION", "x") == "A03"

    def test_alias_ssrf(self):
        assert owasp_score.normalize_owasp("SSRF", "x") == "A10"

    def test_alias_idor(self):
        assert owasp_score.normalize_owasp("IDOR", "x") == "A01"

    def test_alias_sqli(self):
        assert owasp_score.normalize_owasp("sqli", "x") == "A03"

    def test_alias_authentication(self):
        assert owasp_score.normalize_owasp("authentication", "x") == "A07"

    def test_alias_deserialization(self):
        assert owasp_score.normalize_owasp("deserialization", "x") == "A08"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown OWASP category"):
            owasp_score.normalize_owasp("A99", "x")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="unknown OWASP category"):
            owasp_score.normalize_owasp("", "x")


# ---------------------------------------------------------------------------
# normalize_severity
# ---------------------------------------------------------------------------


class TestNormalizeSeverity:
    def test_critical(self):
        assert owasp_score.normalize_severity("Critical", "x") == "Critical"

    def test_lowercase_high(self):
        assert owasp_score.normalize_severity("high", "x") == "High"

    def test_uppercase_low(self):
        assert owasp_score.normalize_severity("LOW", "x") == "Low"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown severity"):
            owasp_score.normalize_severity("Blocker", "x")


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------


class TestNormalizeStatus:
    def test_open(self):
        assert owasp_score.normalize_status("open", "x") == "open"

    def test_mitigated(self):
        assert owasp_score.normalize_status("MITIGATED", "x") == "mitigated"

    def test_accepted(self):
        assert owasp_score.normalize_status("accepted", "x") == "accepted"

    def test_na(self):
        assert owasp_score.normalize_status("n/a", "x") == "n/a"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown status"):
            owasp_score.normalize_status("closed", "x")


# ---------------------------------------------------------------------------
# validate_finding
# ---------------------------------------------------------------------------


class TestValidateFinding:
    def test_minimal_valid(self):
        f = owasp_score.validate_finding(make_finding(), 0)
        assert f["title"] == "Test Finding"
        assert f["owasp"] == "A03"
        assert f["owasp_name"] == "Injection"

    def test_missing_title_raises(self):
        with pytest.raises(ValueError, match="title"):
            owasp_score.validate_finding({"owasp": "A03"}, 0)

    def test_missing_owasp_raises(self):
        with pytest.raises(ValueError, match="'owasp'"):
            owasp_score.validate_finding({"title": "x"}, 0)

    def test_severity_normalized(self):
        f = owasp_score.validate_finding(make_finding(severity="high"), 0)
        assert f["severity"] == "High"

    def test_status_normalized(self):
        f = owasp_score.validate_finding(make_finding(status="MITIGATED"), 0)
        assert f["status"] == "mitigated"

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError, match="unknown severity"):
            owasp_score.validate_finding(make_finding(severity="blocker"), 0)

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="unknown status"):
            owasp_score.validate_finding(make_finding(status="closed"), 0)

    def test_owasp_name_populated(self):
        f = owasp_score.validate_finding(make_finding(owasp="A01"), 0)
        assert f["owasp_name"] == "Broken Access Control"

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            owasp_score.validate_finding("not a dict", 0)


# ---------------------------------------------------------------------------
# compute_category_counts
# ---------------------------------------------------------------------------


class TestComputeCategoryCounts:
    def _vf(self, owasp: str, title: str = "T") -> dict:
        return {
            "title": title,
            "owasp": owasp,
            "owasp_name": owasp_score.OWASP_CATEGORIES[owasp],
        }

    def test_counts_single_category(self):
        findings = [self._vf("A03", "f1"), self._vf("A03", "f2")]
        counts = owasp_score.compute_category_counts(findings)
        assert len(counts["A03"]) == 2

    def test_empty_findings_all_zero(self):
        counts = owasp_score.compute_category_counts([])
        assert all(len(v) == 0 for v in counts.values())

    def test_all_categories_present_in_result(self):
        counts = owasp_score.compute_category_counts([])
        assert set(counts.keys()) == set(owasp_score.OWASP_KEYS)


# ---------------------------------------------------------------------------
# compute_gaps
# ---------------------------------------------------------------------------


class TestComputeGaps:
    def test_all_empty_gives_all_gaps(self):
        counts = {k: [] for k in owasp_score.OWASP_KEYS}
        gaps = owasp_score.compute_gaps(counts)
        assert set(gaps) == set(owasp_score.OWASP_KEYS)

    def test_fully_covered_no_gaps(self):
        counts = {k: ["dummy"] for k in owasp_score.OWASP_KEYS}
        assert owasp_score.compute_gaps(counts) == []

    def test_single_gap(self):
        counts = {k: ["x"] for k in owasp_score.OWASP_KEYS}
        counts["A09"] = []
        gaps = owasp_score.compute_gaps(counts)
        assert gaps == ["A09"]


# ---------------------------------------------------------------------------
# sort_findings
# ---------------------------------------------------------------------------


class TestSortFindings:
    def _f(self, severity=None, owasp="A03"):
        f = {"title": "x", "owasp": owasp, "owasp_name": ""}
        if severity:
            f["severity"] = severity
        return f

    def test_critical_before_high(self):
        findings = [self._f("High"), self._f("Critical")]
        sorted_ = owasp_score.sort_findings(findings)
        assert sorted_[0]["severity"] == "Critical"

    def test_unscored_last(self):
        findings = [self._f(), self._f("Medium")]
        sorted_ = owasp_score.sort_findings(findings)
        assert sorted_[0]["severity"] == "Medium"
        assert "severity" not in sorted_[1]


# ---------------------------------------------------------------------------
# load_input
# ---------------------------------------------------------------------------


class TestLoadInput:
    def test_empty_stdin(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert owasp_score.load_input(None) == []

    def test_file_path(self, tmp_path):
        data = [make_finding(title="from-file")]
        p = tmp_path / "findings.json"
        p.write_text(json.dumps(data))
        result = owasp_score.load_input(str(p))
        assert result[0]["title"] == "from-file"

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            owasp_score.load_input("/no/such/file.json")

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("{bad"))
        with pytest.raises(ValueError, match="Invalid JSON"):
            owasp_score.load_input(None)

    def test_non_array_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO('{"title":"x"}'))
        with pytest.raises(ValueError, match="must be a JSON array"):
            owasp_score.load_input(None)


# ---------------------------------------------------------------------------
# Subprocess integration
# ---------------------------------------------------------------------------


class TestSubprocessIntegration:
    def test_basic_valid_exits_zero(self):
        findings = [make_finding()]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0

    def test_full_coverage_no_gaps(self):
        findings = [make_finding(owasp=k) for k in owasp_score.OWASP_KEYS]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["gaps"] == 0

    def test_partial_coverage_reports_gaps(self):
        findings = [make_finding(owasp="A01"), make_finding(owasp="A03")]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["gaps"] == 8  # 10 total - 2 covered = 8 gaps

    def test_severity_counts_in_summary(self):
        findings = [
            make_finding(title="C1", owasp="A01", severity="Critical"),
            make_finding(title="H1", owasp="A02", severity="High"),
            make_finding(title="M1", owasp="A03", severity="Medium"),
            make_finding(title="L1", owasp="A04", severity="Low"),
        ]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["critical"] == 1
        assert result["summary"]["high"] == 1
        assert result["summary"]["medium"] == 1
        assert result["summary"]["low"] == 1

    def test_missing_owasp_exits_nonzero(self):
        findings = [{"title": "x"}]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_unknown_owasp_exits_nonzero(self):
        findings = [make_finding(owasp="A99")]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_invalid_severity_exits_nonzero(self):
        findings = [make_finding(severity="Blocker")]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code != 0
        assert "ERROR" in err

    def test_empty_input_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="[]")
        assert code == 0

    def test_bad_json_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text="not json")
        assert code != 0
        assert "ERROR" in err

    def test_markdown_table_in_output(self):
        findings = [make_finding()]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        assert "OWASP Top 10" in out
        assert "GAP" in out  # at least one gap (only A03 covered)

    def test_severity_table_present_when_severities_provided(self):
        findings = [make_finding(severity="High")]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        assert "Severity Summary" in out

    def test_severity_table_absent_when_no_severities(self):
        findings = [make_finding()]  # no severity field
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        assert "Severity Summary" not in out

    def test_full_name_alias_accepted(self):
        findings = [make_finding(owasp="Injection")]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert result["findings"][0]["owasp"] == "A03"

    def test_file_path_argument(self, tmp_path):
        findings = [make_finding()]
        p = tmp_path / "findings.json"
        p.write_text(json.dumps(findings))
        code, out, _ = run_script(args=(str(p),))
        assert code == 0

    def test_status_open_count(self):
        findings = [
            make_finding(title="open-finding", owasp="A01", status="open"),
            make_finding(title="mitigated-finding", owasp="A02", status="mitigated"),
        ]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(findings))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["open"] == 1

    def test_object_not_array_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text='{"title":"x"}')
        assert code != 0
