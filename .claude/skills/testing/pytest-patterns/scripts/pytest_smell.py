#!/usr/bin/env python3
"""
pytest_smell.py — L3 executable for the pytest-patterns skill.

Analyzes a Python test file (or all test files in a directory) for
deterministic test smells. Prose judgment (is the test design good?) stays
in the L2 SKILL.md; this script handles only pattern-matchable rules.

Input (file path as first arg, or '-'/no-arg for stdin):
  Python source text of one test file  — OR —
  A directory path: walks all test_*.py / *_test.py files under it.

Output (stdout):
  1. Ranked JSON object with `findings` list and `summary`.
  2. Human-readable markdown section.

Exit codes:
  0 — success (including zero findings, including empty input)
  1 — invalid input (file not found, not a .py file when checking single file,
      unreadable content)

Smell rules (each cites the authoritative reason for the threshold):
  SMELL-01  no_assert          — test function body has no assert/pytest.raises/
                                  assertRaises call.  A test without an assertion
                                  can never fail; it provides no value.
                                  (Source: pytest docs "assert" section; xUnit
                                  Patterns §4 "Assertion-Free Test" smell)
  SMELL-02  bare_except        — bare `except:` or `except Exception:` with no
                                  re-raise or specific assertion on the exception.
                                  (Source: PEP 8 "Programming Recommendations";
                                  xUnit Patterns "Erratic Test" category)
  SMELL-03  test_naming        — test function does not start with `test_`.
                                  pytest requires this prefix to collect the test.
                                  (Source: pytest collection docs — default
                                  python_functions = test_*)
  SMELL-04  magic_number       — numeric literal ≥ 1000 inside an assert
                                  expression not assigned to a named constant.
                                  (Source: Clean Code §17 "Magic Numbers" rule;
                                  threshold 1000 chosen as a conservative lower
                                  bound for numbers unlikely to be incidental
                                  small-integer arithmetic)
  SMELL-05  empty_test         — test function body is only `pass` or only a
                                  docstring (no executable statement at all).
                                  (Source: xUnit Patterns "Empty Test" smell)
  SMELL-06  sleep_in_test      — `time.sleep(` call inside a test function.
                                  Fixed sleeps cause intermittent failures;
                                  use polling helpers or fake timers.
                                  (Source: Google Testing Blog "Avoiding Flakey
                                  Tests" — sleep is the canonical flaky-test
                                  cause)
  SMELL-07  print_in_test      — `print(` call inside a test function (not in a
                                  fixture).  Tests should use captured output
                                  or logging, not print statements.
                                  (Source: pytest capfd/capsys docs — print
                                  is an anti-pattern that pollutes CI output)
  SMELL-08  mock_only_assertions — every assertion in the test is a
                                  Mock/AsyncMock call-verification
                                  (`.assert_called*`, `.assert_awaited*`,
                                  `.assert_has_calls`, `.assert_any_call`,
                                  etc.) and at least one of them is positive.
                                  A test with no assertion on a real value,
                                  return, exception, or observable state
                                  passes regardless of whether the code under
                                  test actually works. Does NOT fire when
                                  every mock assertion is negative
                                  (`assert_not_called`/`assert_not_awaited` —
                                  proving "no write occurred" is legitimate)
                                  or when a real assertion is also present.
                                  (Source: qa.md "NEVER use Mock when Stub
                                  suffices"; xUnit Patterns "Interaction
                                  Testing" — verifying calls instead of
                                  outcomes)
                                  KNOWN LIMITATION: cannot structurally
                                  distinguish a mock standing in for a
                                  genuinely-owned outbound boundary (e.g. a
                                  CLI asserting the HTTP request it built,
                                  where the call IS the observable) from a
                                  mock standing in for a write path the test
                                  never observes. Also cannot detect a
                                  "tautological" real assertion — one that
                                  reads back a value the test itself supplied
                                  as a literal — since that requires dataflow
                                  tracing this detector does not do. Under-
                                  fires on both; treat findings as a lower
                                  bound, not a complete list.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Severity constants — these are structural certainty levels, not risk bands.
# WARN  = the pattern is always undesirable but may have rare valid uses.
# ERROR = the pattern is never acceptable in a test suite.
# (Inspired by ESLint severity model; "error" vs "warn" maps 1:1 to actionability.)
# ---------------------------------------------------------------------------
SEV_ERROR = "ERROR"
SEV_WARN = "WARN"

SMELL_META = {
    "SMELL-01": ("no_assert", SEV_ERROR, "Test has no assertion — can never fail"),
    "SMELL-02": (
        "bare_except",
        SEV_WARN,
        "Bare except/except Exception without re-raise",
    ),
    "SMELL-03": ("test_naming", SEV_ERROR, "Test function does not start with `test_`"),
    "SMELL-04": ("magic_number", SEV_WARN, "Large magic number (>=1000) in assert"),
    "SMELL-05": ("empty_test", SEV_ERROR, "Empty test body (only pass or docstring)"),
    "SMELL-06": ("sleep_in_test", SEV_WARN, "time.sleep() call inside test — flaky"),
    "SMELL-07": (
        "print_in_test",
        SEV_WARN,
        "print() call inside test — pollutes CI output",
    ),
    "SMELL-08": (
        "mock_only_assertions",
        SEV_WARN,
        "All assertions are mock-call verifications — test can pass regardless of real behavior",
    ),
}

# Mock/AsyncMock call-verification methods (unittest.mock).  Named
# `assert_<verb>` (snake_case) — deliberately does not overlap with
# unittest.TestCase's camelCase `assertEqual`/`assertTrue`/etc., which are
# real assertions and must not be classified as mock verifications.
MOCK_ASSERT_METHODS = {
    "assert_called",
    "assert_called_once",
    "assert_called_with",
    "assert_called_once_with",
    "assert_any_call",
    "assert_has_calls",
    "assert_not_called",
    "assert_awaited",
    "assert_awaited_once",
    "assert_awaited_with",
    "assert_awaited_once_with",
    "assert_any_await",
    "assert_has_awaits",
    "assert_not_awaited",
}

# The subset of MOCK_ASSERT_METHODS that assert an interaction did NOT
# happen. Proving "no write occurred" (e.g. on an authorization-deny path)
# has no other observable and is a legitimate test on its own.
NEGATIVE_MOCK_ASSERT_METHODS = {"assert_not_called", "assert_not_awaited"}

# Threshold for SMELL-04: magic number lower bound.
# Chosen as the smallest value that is unlikely to be meaningful arithmetic in
# a test (e.g., HTTP status codes are 3-digit; UUIDs/IDs are typically larger).
# Source: Clean Code §17 — "avoid magic numbers in any context."
MAGIC_NUMBER_THRESHOLD = 1000


# ---------------------------------------------------------------------------
# AST-based smell detectors
# ---------------------------------------------------------------------------


def _has_assertion(func_node: ast.FunctionDef) -> bool:
    """Return True if the function contains any form of assertion."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            return True
        # pytest.raises(...) — Call where attr is 'raises' on name 'pytest'
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in (
                "raises",
                "warns",
                "approx",
            ):
                return True
            # assertRaises, assertEqual, etc. — unittest style
            if isinstance(fn, ast.Attribute) and fn.attr.startswith("assert"):
                return True
            # assert_called_*, assert_any_call, assert_called_once, etc.
            if isinstance(fn, ast.Attribute) and "assert" in fn.attr.lower():
                return True
    return False


def _is_empty_body(func_node: ast.FunctionDef) -> bool:
    """Return True if the body is only pass and/or a docstring (no real code)."""
    body = func_node.body
    real_stmts = 0
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            # docstring
            continue
        real_stmts += 1
    return real_stmts == 0


def _has_bare_except(func_node: ast.FunctionDef) -> bool:
    """Return True if the function contains a bare except or except Exception without re-raise."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # bare except:
        if node.type is None:
            # Check there's no raise inside this handler
            for child in ast.walk(node):
                if isinstance(child, ast.Raise):
                    break
            else:
                return True
        # except Exception:
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            for child in ast.walk(node):
                if isinstance(child, ast.Raise):
                    break
            else:
                return True
    return False


def _has_magic_number_in_assert(func_node: ast.FunctionDef) -> bool:
    """Return True if any assert contains a numeric literal >= MAGIC_NUMBER_THRESHOLD."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Assert):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(
                child.value, (int, float)
            ):
                if abs(child.value) >= MAGIC_NUMBER_THRESHOLD:
                    return True
    return False


def _has_sleep(func_node: ast.FunctionDef) -> bool:
    """Return True if the function calls time.sleep(...)."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            fn = node.func
            # time.sleep(...)
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr == "sleep"
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "time"
            ):
                return True
            # from time import sleep; sleep(...)
            if isinstance(fn, ast.Name) and fn.id == "sleep":
                return True
    return False


def _classify_assertions(func_node: ast.FunctionDef) -> tuple[int, int, int]:
    """
    Walk every assertion-like statement in a test function and classify it.

    Returns (real_count, mock_positive_count, mock_negative_count).

    "Real" = a plain `assert` statement, `pytest.raises(...)`/`pytest.warns(...)`,
    or any unittest-style `self.assertXxx(...)` call (or unrecognized
    `assert_*` method) not in MOCK_ASSERT_METHODS — classified as real to
    avoid false positives (prefer under-firing over over-firing).

    "Mock" = a call to one of the Mock/AsyncMock verification methods in
    MOCK_ASSERT_METHODS, split into positive/negative.
    """
    real = 0
    mock_pos = 0
    mock_neg = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assert):
            real += 1
            continue
        if isinstance(node, ast.Call):
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            attr = fn.attr
            if attr in MOCK_ASSERT_METHODS:
                if attr in NEGATIVE_MOCK_ASSERT_METHODS:
                    mock_neg += 1
                else:
                    mock_pos += 1
            elif attr in ("raises", "warns"):
                real += 1
            elif attr.startswith("assert"):
                # unittest.TestCase-style assertion (assertEqual, assertTrue,
                # assertRaises, ...) or an unrecognized assert_* method.
                real += 1
    return real, mock_pos, mock_neg


def _is_mock_only_assertions(func_node: ast.FunctionDef) -> bool:
    """
    SMELL-08: every assertion in the function is a mock-call verification,
    and at least one of them is positive (not just assert_not_called /
    assert_not_awaited).
    """
    real, mock_pos, _mock_neg = _classify_assertions(func_node)
    if real > 0:
        return False
    return mock_pos > 0


def _has_print(func_node: ast.FunctionDef) -> bool:
    """Return True if the function calls print(...)."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "print":
                return True
    return False


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def analyze_source(source: str, filename: str = "<input>") -> list[dict]:
    """
    Parse source and return a list of finding dicts.
    Each finding: { smell_id, name, severity, message, file, line, function }
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        # SyntaxError is not a smell — report as an error finding
        return [
            {
                "smell_id": "PARSE-ERROR",
                "name": "parse_error",
                "severity": SEV_ERROR,
                "message": f"SyntaxError: {exc.msg} (line {exc.lineno})",
                "file": filename,
                "line": exc.lineno or 0,
                "function": "<module>",
            }
        ]

    findings = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        name = node.name
        line = node.lineno

        # SMELL-03: naming
        if not name.startswith("test_") and not name.startswith("test"):
            # Only flag functions that look like they should be tests
            # (decorated with @pytest.mark.* or inside a Test* class at module level
            # is hard to detect with simple AST; so we only flag functions inside
            # classes named Test* or at module-level with "test" substring in name)
            parent_classes = [
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef)
                and any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child is node
                    for child in ast.walk(n)
                )
            ]
            is_in_test_class = any(c.name.startswith("Test") for c in parent_classes)
            # Only flag if it's in a Test* class and doesn't start with test_
            if is_in_test_class and not name.startswith("test"):
                findings.append(
                    _make_finding(
                        "SMELL-03",
                        filename,
                        line,
                        name,
                        f"Function '{name}' in a Test class does not start with 'test_'",
                    )
                )

        # Skip non-test functions for further checks
        if not (name.startswith("test_") or name.startswith("test")):
            continue
        if not (name.lower().startswith("test")):
            continue

        # SMELL-05: empty body (check before no_assert to avoid double-reporting)
        if _is_empty_body(node):
            findings.append(
                _make_finding(
                    "SMELL-05",
                    filename,
                    line,
                    name,
                    f"Test '{name}' has an empty body (only pass or docstring)",
                )
            )
            continue  # empty → no assertion by definition; don't double-report

        # SMELL-01: no assertion
        if not _has_assertion(node):
            findings.append(
                _make_finding(
                    "SMELL-01",
                    filename,
                    line,
                    name,
                    f"Test '{name}' has no assertion — it can never fail",
                )
            )

        # SMELL-02: bare except
        if _has_bare_except(node):
            findings.append(
                _make_finding(
                    "SMELL-02",
                    filename,
                    line,
                    name,
                    f"Test '{name}' uses bare except / except Exception without re-raise",
                )
            )

        # SMELL-04: magic number in assert
        if _has_magic_number_in_assert(node):
            findings.append(
                _make_finding(
                    "SMELL-04",
                    filename,
                    line,
                    name,
                    f"Test '{name}' contains a magic number (>={MAGIC_NUMBER_THRESHOLD}) in an assert",
                )
            )

        # SMELL-06: sleep
        if _has_sleep(node):
            findings.append(
                _make_finding(
                    "SMELL-06",
                    filename,
                    line,
                    name,
                    f"Test '{name}' calls time.sleep() — use polling helpers or fake timers",
                )
            )

        # SMELL-07: print
        if _has_print(node):
            findings.append(
                _make_finding(
                    "SMELL-07",
                    filename,
                    line,
                    name,
                    f"Test '{name}' calls print() — use capfd/capsys or logging instead",
                )
            )

        # SMELL-08: every assertion is a mock-call verification
        if _is_mock_only_assertions(node):
            findings.append(
                _make_finding(
                    "SMELL-08",
                    filename,
                    line,
                    name,
                    f"Test '{name}' asserts only on mock calls — it can pass "
                    "regardless of whether the code under test actually works",
                )
            )

    return findings


def _make_finding(
    smell_id: str, filename: str, line: int, function: str, message: str
) -> dict:
    meta = SMELL_META.get(smell_id, (smell_id, SEV_WARN, message))
    return {
        "smell_id": smell_id,
        "name": meta[0],
        "severity": meta[1],
        "message": message,
        "file": filename,
        "line": line,
        "function": function,
    }


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def load_sources(source: str | None) -> list[tuple[str, str]]:
    """
    Returns a list of (filename, source_text) pairs.
    source=None or '-' → read stdin as a single file named '<stdin>'.
    source is a directory → walk test_*.py / *_test.py recursively.
    source is a .py file → read that file.
    """
    if source is None or source == "-":
        return [("<stdin>", sys.stdin.read())]

    path = Path(source)

    if not path.exists():
        raise ValueError(f"Path not found: {source}")

    if path.is_dir():
        pairs = []
        for p in sorted(path.rglob("*.py")):
            if p.name.startswith("test_") or p.name.endswith("_test.py"):
                try:
                    pairs.append((str(p), p.read_text(encoding="utf-8")))
                except OSError as exc:
                    raise ValueError(f"Cannot read '{p}': {exc}") from exc
        return pairs

    if path.suffix != ".py":
        raise ValueError(f"Input file must be a .py file, got: {source}")

    try:
        return [(str(path), path.read_text(encoding="utf-8"))]
    except OSError as exc:
        raise ValueError(f"Cannot read '{source}': {exc}") from exc


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def render_markdown(findings: list[dict]) -> str:
    if not findings:
        return "_No test smells detected._\n"

    lines = [
        "| File | Line | Function | Smell | Severity | Message |",
        "|------|------|----------|-------|----------|---------|",
    ]
    for f in findings:
        fname = Path(f["file"]).name
        lines.append(
            f"| {fname} | {f['line']} | `{f['function']}` "
            f"| {f['smell_id']} | {f['severity']} | {f['message']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(source: str | None) -> int:
    try:
        sources = load_sources(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    all_findings: list[dict] = []
    for filename, text in sources:
        if not text.strip():
            continue
        all_findings.extend(analyze_source(text, filename))

    # Sort: ERROR first, then by file+line
    all_findings.sort(
        key=lambda f: (0 if f["severity"] == SEV_ERROR else 1, f["file"], f["line"])
    )

    summary = {
        "total": len(all_findings),
        "error": sum(1 for f in all_findings if f["severity"] == SEV_ERROR),
        "warn": sum(1 for f in all_findings if f["severity"] == SEV_WARN),
        "files_analyzed": len(sources),
    }

    output = {"findings": all_findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()
    print("## pytest Test Smell Report\n")
    print(render_markdown(all_findings))
    print(
        "**Severity:** ERROR = must fix (test is broken/useless) | "
        "WARN = should fix (flaky/noisy)"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect test smells in pytest test files. "
            "Reads one .py file, a directory of test files, or stdin."
        ),
        epilog=(
            "Smells detected: no_assert (SMELL-01), bare_except (SMELL-02), "
            "test_naming (SMELL-03), magic_number (SMELL-04), empty_test (SMELL-05), "
            "sleep_in_test (SMELL-06), print_in_test (SMELL-07), "
            "mock_only_assertions (SMELL-08)."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to a .py test file, a directory, or '-' for stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
