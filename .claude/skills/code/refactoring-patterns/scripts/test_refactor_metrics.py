"""
Tests for refactor_metrics.py.

Run with:
  python3 -m pytest .claude/skills/code/refactoring-patterns/scripts/test_refactor_metrics.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load module under test
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "refactor_metrics.py"

spec = importlib.util.spec_from_file_location("refactor_metrics", SCRIPT)
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)

analyze_python = rm.analyze_python
analyze_js = rm.analyze_js
MAX_FUNCTION_LINES = rm.MAX_FUNCTION_LINES
MAX_NESTING_DEPTH = rm.MAX_NESTING_DEPTH
MAX_PARAMS = rm.MAX_PARAMS
MAX_FILE_LINES = rm.MAX_FILE_LINES
MAX_FUNCTIONS = rm.MAX_FUNCTIONS
SEV_HIGH = rm.SEV_HIGH
SEV_MEDIUM = rm.SEV_MEDIUM
SEV_LOW = rm.SEV_LOW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def findings_with_metric(source: str, metric_id: str, lang: str = "python") -> list[dict]:
    fn = analyze_python if lang == "python" else analyze_js
    return [f for f in fn(source, "<test>") if f["metric_id"] == metric_id]


def make_long_function(n_lines: int, name: str = "test_func") -> str:
    """Build a Python function with n_lines of body."""
    body = "\n".join(f"    x{i} = {i}" for i in range(n_lines))
    return f"def {name}():\n{body}\n"


# ---------------------------------------------------------------------------
# Threshold constants are defined (not guessed)
# ---------------------------------------------------------------------------

class TestThresholdConstants:
    def test_max_function_lines_is_20(self):
        assert MAX_FUNCTION_LINES == 20

    def test_max_nesting_depth_is_4(self):
        assert MAX_NESTING_DEPTH == 4

    def test_max_params_is_3(self):
        assert MAX_PARAMS == 3

    def test_max_file_lines_is_300(self):
        assert MAX_FILE_LINES == 300

    def test_max_functions_is_10(self):
        assert MAX_FUNCTIONS == 10


# ---------------------------------------------------------------------------
# METRIC-01: long_function (Python)
# ---------------------------------------------------------------------------

class TestLongFunctionPython:
    def test_detects_function_over_threshold(self):
        source = make_long_function(MAX_FUNCTION_LINES + 1)
        hits = findings_with_metric(source, "METRIC-01")
        assert len(hits) == 1

    def test_at_threshold_not_flagged(self):
        source = make_long_function(MAX_FUNCTION_LINES)
        hits = findings_with_metric(source, "METRIC-01")
        assert hits == []

    def test_one_over_threshold_is_flagged(self):
        source = make_long_function(MAX_FUNCTION_LINES + 1)
        hits = findings_with_metric(source, "METRIC-01")
        assert hits[0]["value"] == MAX_FUNCTION_LINES + 1

    def test_severity_is_high(self):
        source = make_long_function(MAX_FUNCTION_LINES + 5)
        hits = findings_with_metric(source, "METRIC-01")
        assert hits[0]["severity"] == SEV_HIGH

    def test_multiple_long_functions(self):
        f1 = make_long_function(MAX_FUNCTION_LINES + 1, "func_a")
        f2 = make_long_function(MAX_FUNCTION_LINES + 1, "func_b")
        source = f1 + "\n" + f2
        hits = findings_with_metric(source, "METRIC-01")
        assert len(hits) == 2


# ---------------------------------------------------------------------------
# METRIC-02: deep_nesting (Python)
# ---------------------------------------------------------------------------

class TestDeepNestingPython:
    def _make_nested(self, depth: int) -> str:
        """Build a function with exactly `depth` nesting levels."""
        open_part = "def deep():\n"
        for i in range(depth):
            open_part += "    " * (i + 1) + "if True:\n"
        open_part += "    " * (depth + 1) + "x = 1\n"
        return open_part

    def test_detects_nesting_over_threshold(self):
        source = self._make_nested(MAX_NESTING_DEPTH + 1)
        hits = findings_with_metric(source, "METRIC-02")
        assert len(hits) == 1

    def test_at_threshold_not_flagged(self):
        source = self._make_nested(MAX_NESTING_DEPTH)
        hits = findings_with_metric(source, "METRIC-02")
        assert hits == []

    def test_severity_is_high(self):
        source = self._make_nested(MAX_NESTING_DEPTH + 1)
        hits = findings_with_metric(source, "METRIC-02")
        assert hits[0]["severity"] == SEV_HIGH


# ---------------------------------------------------------------------------
# METRIC-03: long_param_list (Python)
# ---------------------------------------------------------------------------

class TestLongParamListPython:
    def test_detects_over_threshold(self):
        params = ", ".join(f"p{i}" for i in range(MAX_PARAMS + 1))
        source = f"def func({params}):\n    pass\n"
        hits = findings_with_metric(source, "METRIC-03")
        assert len(hits) == 1

    def test_at_threshold_not_flagged(self):
        params = ", ".join(f"p{i}" for i in range(MAX_PARAMS))
        source = f"def func({params}):\n    pass\n"
        hits = findings_with_metric(source, "METRIC-03")
        assert hits == []

    def test_self_not_counted(self):
        # self + 3 params = 4, but self is excluded → 3 → no finding
        source = "def method(self, a, b, c):\n    pass\n"
        hits = findings_with_metric(source, "METRIC-03")
        assert hits == []

    def test_self_plus_over_threshold(self):
        # self + 4 params = 5, excluding self → 4 > 3 → finding
        source = "def method(self, a, b, c, d):\n    pass\n"
        hits = findings_with_metric(source, "METRIC-03")
        assert len(hits) == 1

    def test_severity_is_medium(self):
        params = ", ".join(f"p{i}" for i in range(MAX_PARAMS + 1))
        source = f"def func({params}):\n    pass\n"
        hits = findings_with_metric(source, "METRIC-03")
        assert hits[0]["severity"] == SEV_MEDIUM


# ---------------------------------------------------------------------------
# METRIC-04: large_file
# ---------------------------------------------------------------------------

class TestLargeFile:
    def test_detects_file_over_threshold(self):
        source = "\n".join(f"x{i} = {i}" for i in range(MAX_FILE_LINES + 1))
        hits = findings_with_metric(source, "METRIC-04")
        assert len(hits) == 1

    def test_at_threshold_not_flagged(self):
        source = "\n".join(f"x{i} = {i}" for i in range(MAX_FILE_LINES))
        hits = findings_with_metric(source, "METRIC-04")
        assert hits == []

    def test_severity_is_medium(self):
        source = "\n".join(f"x{i} = {i}" for i in range(MAX_FILE_LINES + 1))
        hits = findings_with_metric(source, "METRIC-04")
        assert hits[0]["severity"] == SEV_MEDIUM


# ---------------------------------------------------------------------------
# METRIC-05: many_functions
# ---------------------------------------------------------------------------

class TestManyFunctions:
    def _make_functions(self, n: int) -> str:
        return "\n".join(f"def func_{i}():\n    pass\n" for i in range(n))

    def test_detects_over_threshold(self):
        source = self._make_functions(MAX_FUNCTIONS + 1)
        hits = findings_with_metric(source, "METRIC-05")
        assert len(hits) == 1

    def test_at_threshold_not_flagged(self):
        source = self._make_functions(MAX_FUNCTIONS)
        hits = findings_with_metric(source, "METRIC-05")
        assert hits == []

    def test_severity_is_low(self):
        source = self._make_functions(MAX_FUNCTIONS + 1)
        hits = findings_with_metric(source, "METRIC-05")
        assert hits[0]["severity"] == SEV_LOW


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    def test_json_block_present(self):
        source = make_long_function(MAX_FUNCTION_LINES + 1)
        rc, stdout, _ = run_script(stdin_text=source)
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert "findings" in data
        assert "summary" in data

    def test_markdown_section_present(self):
        source = make_long_function(MAX_FUNCTION_LINES + 1)
        rc, stdout, _ = run_script(stdin_text=source)
        assert rc == 0
        assert "## Refactoring Metrics Report" in stdout

    def test_empty_input_exits_0(self):
        rc, stdout, _ = run_script(stdin_text="")
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] == 0

    def test_findings_sorted_high_first(self):
        # Generate both HIGH (long function) and LOW (many functions) findings
        funcs = "\n".join(f"def func_{i}():\n    pass\n" for i in range(MAX_FUNCTIONS + 1))
        long_f = make_long_function(MAX_FUNCTION_LINES + 1, "long_func")
        source = funcs + "\n" + long_f
        rc, stdout, _ = run_script(stdin_text=source)
        data = json.loads(stdout.split("\n\n")[0])
        severities = [f["severity"] for f in data["findings"]]
        # HIGH should appear before LOW
        high_idx = next((i for i, s in enumerate(severities) if s == SEV_HIGH), None)
        low_idx = next((i for i, s in enumerate(severities) if s == SEV_LOW), None)
        if high_idx is not None and low_idx is not None:
            assert high_idx < low_idx

    def test_summary_language_python(self):
        rc, stdout, _ = run_script(stdin_text="def foo():\n    pass\n")
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["language"] == "python"


# ---------------------------------------------------------------------------
# Input modes
# ---------------------------------------------------------------------------

class TestInputModes:
    def test_stdin_dash_arg(self):
        rc, stdout, _ = run_script(
            args=["-"],
            stdin_text=make_long_function(MAX_FUNCTION_LINES + 1),
        )
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] >= 1

    def test_file_path_python(self, tmp_path):
        f = tmp_path / "example.py"
        f.write_text(make_long_function(MAX_FUNCTION_LINES + 1))
        rc, stdout, _ = run_script(args=[str(f)])
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] >= 1

    def test_file_path_js(self, tmp_path):
        f = tmp_path / "example.js"
        content = (
            "function longFunc() {\n"
            + "\n".join(f"  var x{i} = {i};" for i in range(MAX_FUNCTION_LINES + 2))
            + "\n}\n"
        )
        f.write_text(content)
        rc, stdout, _ = run_script(args=[str(f)])
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["language"] == "javascript"

    def test_invalid_file_exits_1(self):
        rc, _, stderr = run_script(args=["/nonexistent/path/code.py"])
        assert rc == 1
        assert "ERROR" in stderr

    def test_unsupported_extension_exits_1(self, tmp_path):
        f = tmp_path / "code.rb"
        f.write_text("def foo; end")
        rc, _, stderr = run_script(args=[str(f)])
        assert rc == 1
        assert "ERROR" in stderr

    def test_directory_exits_1(self, tmp_path):
        rc, _, stderr = run_script(args=[str(tmp_path)])
        assert rc == 1
        assert "ERROR" in stderr


# ---------------------------------------------------------------------------
# JS-specific analysis
# ---------------------------------------------------------------------------

class TestJsAnalysis:
    def test_detects_long_js_function(self):
        lines = ["function longFunc() {"]
        for i in range(MAX_FUNCTION_LINES + 2):
            lines.append(f"  var x{i} = {i};")
        lines.append("}")
        source = "\n".join(lines)
        hits = findings_with_metric(source, "METRIC-01", lang="js")
        assert len(hits) == 1

    def test_detects_js_deep_nesting(self):
        source = (
            "function f() {\n"
            "  if (a) {\n"
            "    if (b) {\n"
            "      if (c) {\n"
            "        if (d) {\n"
            "          if (e) {\n"           # depth 5
            "            x = 1;\n"
            "          }\n"
            "        }\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        hits = findings_with_metric(source, "METRIC-02", lang="js")
        assert len(hits) == 1

    def test_detects_js_many_params(self):
        params = ", ".join(f"p{i}" for i in range(MAX_PARAMS + 1))
        source = f"function f({params}) {{\n  return 1;\n}}\n"
        hits = findings_with_metric(source, "METRIC-03", lang="js")
        assert len(hits) == 1
