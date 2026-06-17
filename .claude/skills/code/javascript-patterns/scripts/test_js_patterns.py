"""
Tests for js_patterns.py — regex-based JavaScript/TypeScript anti-pattern checker.

Run with:  python3 -m pytest .claude/skills/code/javascript-patterns/scripts/test_js_patterns.py -v
Or from within this directory: python3 -m pytest test_js_patterns.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the module under test (works regardless of cwd)
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "js_patterns.py"

spec = importlib.util.spec_from_file_location("js_patterns", SCRIPT)
js_patterns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(js_patterns)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_script(args=(), stdin_text=None):
    """Run js_patterns.py as a subprocess. Returns (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def check(source: str) -> list[dict]:
    """Check source and return findings list."""
    return js_patterns.check_source(source)


def rules(source: str) -> list[str]:
    """Return just the rule names from findings."""
    return [f["rule"] for f in check(source)]


# ---------------------------------------------------------------------------
# VAR_DECL — MEDIUM
# ---------------------------------------------------------------------------


class TestVarDecl:
    def test_var_declaration_flagged(self):
        assert "VAR_DECL" in rules("var x = 1;")

    def test_const_clean(self):
        assert "VAR_DECL" not in rules("const x = 1;")

    def test_let_clean(self):
        assert "VAR_DECL" not in rules("let x = 1;")

    def test_var_in_identifier_clean(self):
        # 'variance', 'varName' should not trigger
        assert "VAR_DECL" not in rules("const variance = 0.5;")
        assert "VAR_DECL" not in rules("const varName = 'test';")

    def test_var_in_comment_ignored(self):
        # Comments are stripped before matching
        assert "VAR_DECL" not in rules("// var x = 1;")

    def test_severity_is_medium(self):
        findings = [f for f in check("var x = 1;") if f["rule"] == "VAR_DECL"]
        assert all(f["severity"] == "MEDIUM" for f in findings)

    def test_multiple_var_declarations(self):
        src = "var a = 1;\nvar b = 2;\n"
        result = rules(src)
        assert result.count("VAR_DECL") == 2

    def test_line_number_reported(self):
        src = "\nvar x = 1;\n"
        findings = [f for f in check(src) if f["rule"] == "VAR_DECL"]
        assert findings[0]["line"] == 2


# ---------------------------------------------------------------------------
# LOOSE_EQUALITY — MEDIUM
# ---------------------------------------------------------------------------


class TestLooseEquality:
    def test_double_eq_flagged(self):
        assert "LOOSE_EQUALITY" in rules("if (x == y) {}")

    def test_not_eq_flagged(self):
        assert "LOOSE_EQUALITY" in rules("if (x != y) {}")

    def test_triple_eq_clean(self):
        assert "LOOSE_EQUALITY" not in rules("if (x === y) {}")

    def test_strict_not_eq_clean(self):
        assert "LOOSE_EQUALITY" not in rules("if (x !== y) {}")

    def test_assignment_clean(self):
        assert "LOOSE_EQUALITY" not in rules("x = 5;")

    def test_compound_assignment_clean(self):
        assert "LOOSE_EQUALITY" not in rules("x += 1;")

    def test_inside_string_ignored(self):
        # == inside a string should be ignored
        src = 'const msg = "use == for loose equality";'
        assert "LOOSE_EQUALITY" not in rules(src)

    def test_severity_is_medium(self):
        findings = [f for f in check("if (a == b) {}") if f["rule"] == "LOOSE_EQUALITY"]
        assert all(f["severity"] == "MEDIUM" for f in findings)


# ---------------------------------------------------------------------------
# CONSOLE_LOG — LOW
# ---------------------------------------------------------------------------


class TestConsoleLog:
    def test_console_log_flagged(self):
        assert "CONSOLE_LOG" in rules("console.log('debug');")

    def test_console_log_no_args_flagged(self):
        assert "CONSOLE_LOG" in rules("console.log()")

    def test_console_error_clean(self):
        # Only console.log specifically is flagged
        assert "CONSOLE_LOG" not in rules("console.error('oops');")

    def test_console_warn_clean(self):
        assert "CONSOLE_LOG" not in rules("console.warn('warning');")

    def test_severity_is_low(self):
        findings = [f for f in check("console.log('x');") if f["rule"] == "CONSOLE_LOG"]
        assert all(f["severity"] == "LOW" for f in findings)

    def test_inside_string_ignored(self):
        src = 'const msg = "call console.log() for debugging";'
        assert "CONSOLE_LOG" not in rules(src)


# ---------------------------------------------------------------------------
# CALLBACK_NESTING — MEDIUM
# (threshold = 3, i.e., depth >= 3 when a callback opens)
# ---------------------------------------------------------------------------


class TestCallbackNesting:
    def test_shallow_nesting_clean(self):
        src = (
            "getData(function(data) {\n"
            "  process(data, function(result) {\n"
            "    console.log(result);\n"
            "  });\n"
            "});\n"
        )
        assert "CALLBACK_NESTING" not in rules(src)

    def test_deep_nesting_flagged(self):
        # 3+ levels of nesting should be flagged
        src = (
            "getData(function(data) {\n"
            "  process(data, function(result) {\n"
            "    save(result, function(saved) {\n"
            "      notify(saved, function() {\n"
            "        done();\n"
            "      });\n"
            "    });\n"
            "  });\n"
            "});\n"
        )
        assert "CALLBACK_NESTING" in rules(src)

    def test_severity_is_medium(self):
        src = (
            "a(function() {\n"
            "  b(function() {\n"
            "    c(function() {\n"
            "      d(function() {\n"
            "        e();\n"
            "      });\n"
            "    });\n"
            "  });\n"
            "});\n"
        )
        findings = [f for f in check(src) if f["rule"] == "CALLBACK_NESTING"]
        assert all(f["severity"] == "MEDIUM" for f in findings)

    def test_callback_nesting_threshold_constant(self):
        # Verify the threshold is 3 as documented
        assert js_patterns.CALLBACK_NESTING_THRESHOLD == 3


# ---------------------------------------------------------------------------
# Sorting: MEDIUM before LOW
# ---------------------------------------------------------------------------


class TestSortOrder:
    def test_medium_before_low(self):
        src = (
            "console.log('debug');\n"  # LOW
            "var x = 1;\n"  # MEDIUM
        )
        findings = check(src)
        severities = [f["severity"] for f in findings]
        medium_indices = [i for i, s in enumerate(severities) if s == "MEDIUM"]
        low_indices = [i for i, s in enumerate(severities) if s == "LOW"]
        if medium_indices and low_indices:
            assert max(medium_indices) < min(low_indices)


# ---------------------------------------------------------------------------
# Empty and edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_source_no_findings(self):
        assert check("") == []

    def test_whitespace_only_no_findings(self):
        assert check("   \n\n   ") == []

    def test_clean_typescript_no_findings(self):
        src = (
            "const fetchUser = async (id: string): Promise<User> => {\n"
            "  try {\n"
            "    const response = await fetch(`/api/users/${id}`);\n"
            "    return await response.json();\n"
            "  } catch (error) {\n"
            "    throw new Error('Failed');\n"
            "  }\n"
            "};\n"
        )
        # Should only produce LOOSE_EQUALITY false-positives from ternary? No.
        result = rules(src)
        assert "VAR_DECL" not in result
        assert "CONSOLE_LOG" not in result


# ---------------------------------------------------------------------------
# Script I/O via subprocess
# ---------------------------------------------------------------------------


class TestScriptSubprocess:
    def test_stdin_empty_exits_zero(self):
        rc, out, err = run_script(["-"], stdin_text="")
        assert rc == 0

    def test_stdin_valid_exits_zero(self):
        rc, out, err = run_script(["-"], stdin_text="var x = 1;\n")
        assert rc == 0

    def test_stdout_contains_json_block(self):
        rc, out, err = run_script(["-"], stdin_text="var x = 1;\n")
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert "findings" in data
        assert "summary" in data

    def test_stdout_contains_markdown_section(self):
        rc, out, err = run_script(["-"], stdin_text="var x = 1;\n")
        assert "## JavaScript Anti-Pattern Findings" in out

    def test_file_not_found_exits_one(self):
        rc, out, err = run_script(["/nonexistent/file.js"])
        assert rc == 1
        assert "ERROR" in err

    def test_summary_counts_correct(self):
        src = (
            "var a = 1;\n"  # MEDIUM (VAR_DECL)
            "if (x == y) {}\n"  # MEDIUM (LOOSE_EQUALITY)
            "console.log('hi');\n"  # LOW (CONSOLE_LOG)
        )
        rc, out, err = run_script(["-"], stdin_text=src)
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert data["summary"]["medium"] >= 2
        assert data["summary"]["low"] >= 1

    def test_file_argument_works(self, tmp_path):
        f = tmp_path / "sample.js"
        f.write_text("var x = 1;\n")
        rc, out, err = run_script([str(f)])
        assert rc == 0
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert data["summary"]["medium"] >= 1
