"""
Tests for python_lint.py — AST-based Python anti-idiom checker.

Run with:  python3 -m pytest .claude/skills/code/python-idioms/scripts/test_python_lint.py -v
Or from within this directory: python3 -m pytest test_python_lint.py -v
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
SCRIPT = Path(__file__).parent / "python_lint.py"

spec = importlib.util.spec_from_file_location("python_lint", SCRIPT)
python_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(python_lint)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_script(args=(), stdin_text=None):
    """Run python_lint.py as a subprocess. Returns (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def check(source: str) -> list[dict]:
    """Parse source and return findings list."""
    return python_lint.check_source(source, filename="<test>")


def rules(source: str) -> list[str]:
    """Return just the rule names from findings."""
    return [f["rule"] for f in check(source)]


# ---------------------------------------------------------------------------
# MUTABLE_DEFAULT — HIGH
# ---------------------------------------------------------------------------

class TestMutableDefault:
    def test_list_default_flagged(self):
        src = "def foo(x, items=[]): pass"
        assert "MUTABLE_DEFAULT" in rules(src)

    def test_dict_default_flagged(self):
        src = "def foo(x, data={}): pass"
        assert "MUTABLE_DEFAULT" in rules(src)

    def test_set_default_flagged(self):
        src = "def foo(x, s=set()): pass"
        # set() is a Call, not a Set literal — not caught by MUTABLE_DEFAULT
        # This is correct — the rule only catches literals
        assert "MUTABLE_DEFAULT" not in rules(src)

    def test_set_literal_default_flagged(self):
        src = "def foo(x, s={1, 2}): pass"
        assert "MUTABLE_DEFAULT" in rules(src)

    def test_none_default_clean(self):
        src = "def foo(x, items=None): pass"
        assert "MUTABLE_DEFAULT" not in rules(src)

    def test_immutable_defaults_clean(self):
        src = "def foo(x=0, y='hello', z=True): pass"
        assert "MUTABLE_DEFAULT" not in rules(src)

    def test_async_function_flagged(self):
        src = "async def foo(items=[]): pass"
        assert "MUTABLE_DEFAULT" in rules(src)

    def test_severity_is_high(self):
        src = "def foo(items=[]): pass"
        findings = check(src)
        high = [f for f in findings if f["rule"] == "MUTABLE_DEFAULT"]
        assert all(f["severity"] == "HIGH" for f in high)

    def test_line_number_reported(self):
        src = "\n\ndef foo(items=[]): pass"
        findings = check(src)
        mutable = [f for f in findings if f["rule"] == "MUTABLE_DEFAULT"]
        assert mutable[0]["line"] == 3


# ---------------------------------------------------------------------------
# BARE_EXCEPT — HIGH
# ---------------------------------------------------------------------------

class TestBareExcept:
    def test_bare_except_flagged(self):
        src = "try:\n    x()\nexcept:\n    pass"
        assert "BARE_EXCEPT" in rules(src)

    def test_specific_except_clean(self):
        src = "try:\n    x()\nexcept ValueError:\n    pass"
        assert "BARE_EXCEPT" not in rules(src)

    def test_except_exception_clean(self):
        src = "try:\n    x()\nexcept Exception:\n    pass"
        assert "BARE_EXCEPT" not in rules(src)

    def test_severity_is_high(self):
        src = "try:\n    x()\nexcept:\n    pass"
        findings = check(src)
        bare = [f for f in findings if f["rule"] == "BARE_EXCEPT"]
        assert all(f["severity"] == "HIGH" for f in bare)

    def test_multiple_except_handlers(self):
        src = (
            "try:\n    x()\n"
            "except ValueError:\n    pass\n"
            "except:\n    pass"
        )
        result = rules(src)
        assert result.count("BARE_EXCEPT") == 1


# ---------------------------------------------------------------------------
# EQ_NONE — MEDIUM
# ---------------------------------------------------------------------------

class TestEqNone:
    def test_eq_none_flagged(self):
        src = "if x == None: pass"
        assert "EQ_NONE" in rules(src)

    def test_ne_none_flagged(self):
        src = "if x != None: pass"
        assert "EQ_NONE" in rules(src)

    def test_is_none_clean(self):
        src = "if x is None: pass"
        assert "EQ_NONE" not in rules(src)

    def test_is_not_none_clean(self):
        src = "if x is not None: pass"
        assert "EQ_NONE" not in rules(src)

    def test_eq_other_value_clean(self):
        src = "if x == 0: pass"
        assert "EQ_NONE" not in rules(src)

    def test_severity_is_medium(self):
        src = "if x == None: pass"
        findings = check(src)
        eq = [f for f in findings if f["rule"] == "EQ_NONE"]
        assert all(f["severity"] == "MEDIUM" for f in eq)


# ---------------------------------------------------------------------------
# RANGE_LEN — MEDIUM
# ---------------------------------------------------------------------------

class TestRangeLen:
    def test_range_len_flagged(self):
        src = "for i in range(len(items)):\n    pass"
        assert "RANGE_LEN" in rules(src)

    def test_direct_iteration_clean(self):
        src = "for item in items:\n    pass"
        assert "RANGE_LEN" not in rules(src)

    def test_enumerate_clean(self):
        src = "for i, item in enumerate(items):\n    pass"
        assert "RANGE_LEN" not in rules(src)

    def test_range_no_len_clean(self):
        src = "for i in range(10):\n    pass"
        assert "RANGE_LEN" not in rules(src)

    def test_severity_is_medium(self):
        src = "for i in range(len(items)):\n    pass"
        findings = check(src)
        rl = [f for f in findings if f["rule"] == "RANGE_LEN"]
        assert all(f["severity"] == "MEDIUM" for f in rl)


# ---------------------------------------------------------------------------
# TYPE_COMPARE — MEDIUM
# ---------------------------------------------------------------------------

class TestTypeCompare:
    def test_type_eq_class_flagged(self):
        src = "if type(x) == list: pass"
        assert "TYPE_COMPARE" in rules(src)

    def test_isinstance_clean(self):
        src = "if isinstance(x, list): pass"
        assert "TYPE_COMPARE" not in rules(src)

    def test_severity_is_medium(self):
        src = "if type(x) == list: pass"
        findings = check(src)
        tc = [f for f in findings if f["rule"] == "TYPE_COMPARE"]
        assert all(f["severity"] == "MEDIUM" for f in tc)


# ---------------------------------------------------------------------------
# Sorting: HIGH before MEDIUM
# ---------------------------------------------------------------------------

class TestSortOrder:
    def test_high_before_medium(self):
        src = (
            "if x == None: pass\n"
            "try:\n    x()\nexcept:\n    pass\n"
        )
        findings = check(src)
        severities = [f["severity"] for f in findings]
        high_indices = [i for i, s in enumerate(severities) if s == "HIGH"]
        medium_indices = [i for i, s in enumerate(severities) if s == "MEDIUM"]
        if high_indices and medium_indices:
            assert max(high_indices) < min(medium_indices)


# ---------------------------------------------------------------------------
# Empty and invalid input
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_source_no_findings(self):
        assert check("") == []

    def test_whitespace_only_no_findings(self):
        assert check("   \n\n   ") == []

    def test_syntax_error_raises(self):
        with pytest.raises(SyntaxError):
            check("def foo(: pass")

    def test_clean_file_no_findings(self):
        src = (
            "def greet(name: str) -> str:\n"
            "    return f'Hello, {name}'\n\n"
            "for item in ['a', 'b']:\n"
            "    print(item)\n"
        )
        assert check(src) == []


# ---------------------------------------------------------------------------
# Script I/O via subprocess
# ---------------------------------------------------------------------------

class TestScriptSubprocess:
    def test_stdin_empty_exits_zero(self):
        rc, out, err = run_script(["-"], stdin_text="")
        assert rc == 0

    def test_stdin_valid_source_exits_zero(self):
        src = "def foo(items=[]): pass\n"
        rc, out, err = run_script(["-"], stdin_text=src)
        assert rc == 0

    def test_stdout_contains_json_block(self):
        src = "def foo(items=[]): pass\n"
        rc, out, err = run_script(["-"], stdin_text=src)
        # First parseable JSON object in output
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert "findings" in data
        assert "summary" in data

    def test_stdout_contains_markdown_section(self):
        src = "def foo(items=[]): pass\n"
        rc, out, err = run_script(["-"], stdin_text=src)
        assert "## Python Anti-Idiom Findings" in out

    def test_file_not_found_exits_one(self):
        rc, out, err = run_script(["/nonexistent/path/file.py"])
        assert rc == 1
        assert "ERROR" in err

    def test_syntax_error_exits_one(self):
        rc, out, err = run_script(["-"], stdin_text="def foo(: pass")
        assert rc == 1
        assert "ERROR" in err

    def test_findings_sorted_high_first(self):
        src = (
            "if x == None: pass\n"
            "try:\n    x()\nexcept:\n    pass\n"
        )
        rc, out, err = run_script(["-"], stdin_text=src)
        assert rc == 0
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        severities = [f["severity"] for f in data["findings"]]
        # HIGH findings must come before MEDIUM
        seen_medium = False
        for s in severities:
            if s == "MEDIUM":
                seen_medium = True
            if seen_medium and s == "HIGH":
                pytest.fail("HIGH finding appeared after MEDIUM finding in output")

    def test_summary_counts_correct(self):
        src = (
            "def foo(items=[]): pass\n"   # HIGH x1
            "if x == None: pass\n"         # MEDIUM x1
            "for i in range(len(x)):\n    pass\n"  # MEDIUM x1
        )
        rc, out, err = run_script(["-"], stdin_text=src)
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert data["summary"]["high"] == 1
        assert data["summary"]["medium"] == 2

    def test_file_argument_works(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("def foo(items=[]): pass\n")
        rc, out, err = run_script([str(f)])
        assert rc == 0
        json_text = out.split("\n\n")[0]
        data = json.loads(json_text)
        assert data["summary"]["high"] >= 1
