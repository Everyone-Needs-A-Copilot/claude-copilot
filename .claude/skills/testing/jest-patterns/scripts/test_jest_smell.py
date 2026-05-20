"""
Tests for jest_smell.py.

Run with:
  python3 -m pytest .claude/skills/testing/jest-patterns/scripts/test_jest_smell.py -v
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
SCRIPT = Path(__file__).parent / "jest_smell.py"

spec = importlib.util.spec_from_file_location("jest_smell", SCRIPT)
jest_smell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jest_smell)

analyze_source = jest_smell.analyze_source
SEV_ERROR = jest_smell.SEV_ERROR
SEV_WARN = jest_smell.SEV_WARN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def findings_with_smell(source: str, smell_id: str) -> list[dict]:
    return [f for f in analyze_source(source) if f["smell_id"] == smell_id]


# ---------------------------------------------------------------------------
# SMELL-01: test_only
# ---------------------------------------------------------------------------

class TestTestOnly:
    def test_detects_it_only(self):
        source = "it.only('should work', () => { expect(1).toBe(1); });\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert len(hits) == 1

    def test_detects_test_only(self):
        source = "test.only('should work', () => { expect(1).toBe(1); });\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert len(hits) == 1

    def test_detects_describe_only(self):
        source = "describe.only('suite', () => {});\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert len(hits) == 1

    def test_no_false_positive_on_only_in_string(self):
        # "only" appearing inside a test description should not trigger
        source = "test('the only valid case', () => { expect(1).toBe(1); });\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert hits == []

    def test_severity_is_error(self):
        source = "it.only('x', () => { expect(1).toBe(1); });\n"
        hits = findings_with_smell(source, "SMELL-01")
        assert hits[0]["severity"] == SEV_ERROR


# ---------------------------------------------------------------------------
# SMELL-02: test_skip
# ---------------------------------------------------------------------------

class TestTestSkip:
    def test_detects_it_skip(self):
        source = "it.skip('should work', () => { expect(1).toBe(1); });\n"
        hits = findings_with_smell(source, "SMELL-02")
        assert len(hits) == 1

    def test_detects_test_skip(self):
        source = "test.skip('should work', () => { expect(1).toBe(1); });\n"
        hits = findings_with_smell(source, "SMELL-02")
        assert len(hits) == 1

    def test_detects_xit(self):
        source = "xit.skip('should work', () => {});\n"
        hits = findings_with_smell(source, "SMELL-02")
        assert len(hits) == 1

    def test_severity_is_warn(self):
        source = "it.skip('x', () => { expect(1).toBe(1); });\n"
        hits = findings_with_smell(source, "SMELL-02")
        assert hits[0]["severity"] == SEV_WARN


# ---------------------------------------------------------------------------
# SMELL-03: no_expect
# ---------------------------------------------------------------------------

class TestNoExpect:
    def test_detects_missing_expect(self):
        source = "it('should work', () => {\n  const x = 1;\n});\n"
        hits = findings_with_smell(source, "SMELL-03")
        assert len(hits) == 1

    def test_passes_with_expect(self):
        source = "it('should work', () => {\n  expect(1).toBe(1);\n});\n"
        hits = findings_with_smell(source, "SMELL-03")
        assert hits == []

    def test_severity_is_error(self):
        source = "it('should work', () => {\n  const x = 1;\n});\n"
        hits = findings_with_smell(source, "SMELL-03")
        assert hits[0]["severity"] == SEV_ERROR

    def test_passes_with_test_keyword(self):
        source = "test('should work', () => {\n  expect(true).toBe(true);\n});\n"
        hits = findings_with_smell(source, "SMELL-03")
        assert hits == []


# ---------------------------------------------------------------------------
# SMELL-04: async_no_await
# ---------------------------------------------------------------------------

class TestAsyncNoAwait:
    def test_detects_async_without_await(self):
        source = (
            "it('should work', async () => {\n"
            "  const result = fetchData();\n"
            "  expect(result).toBeDefined();\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-04")
        assert len(hits) == 1

    def test_passes_with_await(self):
        source = (
            "it('should work', async () => {\n"
            "  const result = await fetchData();\n"
            "  expect(result).toBeDefined();\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-04")
        assert hits == []

    def test_sync_test_not_flagged(self):
        source = (
            "it('should work', () => {\n"
            "  expect(1).toBe(1);\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-04")
        assert hits == []

    def test_severity_is_error(self):
        source = (
            "it('x', async () => {\n"
            "  const r = fetchData();\n"
            "  expect(r).toBeDefined();\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-04")
        assert hits[0]["severity"] == SEV_ERROR


# ---------------------------------------------------------------------------
# SMELL-05: setTimeout_zero
# ---------------------------------------------------------------------------

class TestSetTimeoutZero:
    def test_detects_settimeout_zero(self):
        source = (
            "it('should work', () => {\n"
            "  setTimeout(done, 0);\n"
            "  expect(1).toBe(1);\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-05")
        assert len(hits) == 1

    def test_no_false_positive_nonzero_timeout(self):
        source = (
            "it('should work', () => {\n"
            "  setTimeout(done, 1000);\n"
            "  expect(1).toBe(1);\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-05")
        assert hits == []

    def test_severity_is_warn(self):
        source = (
            "it('x', () => {\n"
            "  setTimeout(cb, 0);\n"
            "  expect(1).toBe(1);\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-05")
        assert hits[0]["severity"] == SEV_WARN


# ---------------------------------------------------------------------------
# SMELL-06: console_log
# ---------------------------------------------------------------------------

class TestConsoleLog:
    def test_detects_console_log(self):
        source = (
            "it('should work', () => {\n"
            "  console.log('debug');\n"
            "  expect(1).toBe(1);\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-06")
        assert len(hits) == 1

    def test_no_false_positive_without_log(self):
        source = (
            "it('should work', () => {\n"
            "  expect(1).toBe(1);\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-06")
        assert hits == []

    def test_severity_is_warn(self):
        source = (
            "it('x', () => {\n"
            "  console.log('x');\n"
            "  expect(1).toBe(1);\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-06")
        assert hits[0]["severity"] == SEV_WARN


# ---------------------------------------------------------------------------
# SMELL-07: done_callback
# ---------------------------------------------------------------------------

class TestDoneCallback:
    def test_detects_done_callback(self):
        source = (
            "it('should work', (done) => {\n"
            "  fetchData().then(result => {\n"
            "    expect(result).toBeDefined();\n"
            "    done();\n"
            "  });\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-07")
        assert len(hits) == 1

    def test_severity_is_warn(self):
        source = (
            "it('x', (done) => {\n"
            "  expect(1).toBe(1);\n"
            "  done();\n"
            "});\n"
        )
        hits = findings_with_smell(source, "SMELL-07")
        assert hits[0]["severity"] == SEV_WARN


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    def test_json_block_present(self):
        source = "it.only('x', () => { expect(1).toBe(1); });\n"
        rc, stdout, _ = run_script(stdin_text=source)
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert "findings" in data
        assert "summary" in data

    def test_markdown_section_present(self):
        source = "it.only('x', () => { expect(1).toBe(1); });\n"
        rc, stdout, _ = run_script(stdin_text=source)
        assert rc == 0
        assert "## Jest Test Smell Report" in stdout

    def test_empty_input_exits_0(self):
        rc, stdout, _ = run_script(stdin_text="")
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] == 0

    def test_empty_input_no_findings(self):
        rc, stdout, _ = run_script(stdin_text="")
        data = json.loads(stdout.split("\n\n")[0])
        assert data["findings"] == []

    def test_summary_counts(self):
        source = (
            "it.only('x', () => { expect(1).toBe(1); });\n"  # ERROR
            "it.skip('y', () => { expect(1).toBe(1); });\n"   # WARN
        )
        rc, stdout, _ = run_script(stdin_text=source)
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["error"] >= 1
        assert data["summary"]["warn"] >= 1


# ---------------------------------------------------------------------------
# Input modes
# ---------------------------------------------------------------------------

class TestInputModes:
    def test_stdin_dash_arg(self):
        rc, stdout, _ = run_script(
            args=["-"],
            stdin_text="it.only('x', () => { expect(1).toBe(1); });\n",
        )
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] >= 1

    def test_file_path_arg(self, tmp_path):
        f = tmp_path / "example.test.js"
        f.write_text("it.only('x', () => { expect(1).toBe(1); });\n")
        rc, stdout, _ = run_script(args=[str(f)])
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        assert data["summary"]["total"] >= 1

    def test_invalid_file_exits_1(self):
        rc, _, stderr = run_script(args=["/nonexistent/path/test.js"])
        assert rc == 1
        assert "ERROR" in stderr

    def test_non_js_file_exits_1(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("print('hello')")
        rc, _, stderr = run_script(args=[str(f)])
        assert rc == 1
        assert "ERROR" in stderr

    def test_directory_walks_test_files(self, tmp_path):
        (tmp_path / "foo.test.js").write_text(
            "it.only('x', () => { expect(1).toBe(1); });\n"
        )
        (tmp_path / "helper.js").write_text("const x = 1;\n")
        rc, stdout, _ = run_script(args=[str(tmp_path)])
        assert rc == 0
        data = json.loads(stdout.split("\n\n")[0])
        # Only foo.test.js is analyzed (helper.js is skipped)
        assert data["summary"]["files_analyzed"] == 1
