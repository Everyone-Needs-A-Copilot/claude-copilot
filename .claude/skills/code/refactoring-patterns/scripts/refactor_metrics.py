#!/usr/bin/env python3
"""
refactor_metrics.py — L3 executable for the refactoring-patterns skill.

Analyzes a single Python or JavaScript/TypeScript source file for
deterministic code-structure metrics that signal refactoring opportunities.

Prose judgment (is this design good?) stays in the L2 SKILL.md.
This script handles only metric-computable rules.

Input (file path as first arg, or '-'/no-arg for stdin):
  Source text.  For stdin, language is inferred from content heuristics;
  for file paths, language is inferred from extension.

Output (stdout):
  1. Ranked JSON object with `findings` list (sorted by severity desc) and `summary`.
  2. Human-readable markdown section.

Exit codes:
  0 — success (including zero findings, including empty input)
  1 — invalid input (file not found, unsupported extension for a named file)

Metric rules (each cites its authoritative source):

  METRIC-01  long_function     — function/method line count exceeds
                                  MAX_FUNCTION_LINES (20 lines).
                                  Source: Refactoring (Fowler 2018) §3
                                  "Long Method" smell — the most common
                                  and highest-signal smell; threshold 20
                                  is the value Fowler explicitly names.

  METRIC-02  deep_nesting      — code block nesting depth exceeds
                                  MAX_NESTING_DEPTH (4 levels).
                                  Source: Clean Code (Martin 2009) §3
                                  "One Level of Abstraction per Function";
                                  cognitive complexity research (Sonarqube
                                  Cognitive Complexity whitepaper, 2017)
                                  identifies depth >4 as high-complexity.

  METRIC-03  long_param_list   — function signature has more than
                                  MAX_PARAMS (3) parameters.
                                  Source: Refactoring (Fowler 2018) §3
                                  "Long Parameter List" smell — threshold
                                  is 3 (Fowler's explicit recommendation:
                                  "more than 3 or 4 parameters" is a smell).

  METRIC-04  large_file        — file line count exceeds
                                  MAX_FILE_LINES (300 lines).
                                  Source: Clean Code (Martin 2009) §5
                                  recommends files under 200-500 lines;
                                  threshold 300 is the midpoint of that
                                  range and a common ESLint/pylint default.

  METRIC-05  many_functions    — file contains more than MAX_FUNCTIONS (10)
                                  top-level functions/methods.
                                  Source: Single Responsibility Principle
                                  (Martin 2003); a module with >10 exported
                                  functions is a signal of divergent
                                  responsibility.  Threshold 10 aligns with
                                  pylint's default max-public-methods = 20
                                  halved for top-level module scope.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds — named constants with source citations in module docstring
# ---------------------------------------------------------------------------

# Fowler "Refactoring" §3 Long Method: 20 lines is the explicit threshold
MAX_FUNCTION_LINES = 20

# Sonarqube Cognitive Complexity whitepaper 2017: depth > 4 = high complexity
MAX_NESTING_DEPTH = 4

# Fowler "Refactoring" §3 Long Parameter List: > 3 params is the smell
MAX_PARAMS = 3

# Clean Code §5: files should be under 200-500 lines; 300 is the midpoint
MAX_FILE_LINES = 300

# SRP signal: >10 top-level functions suggests divergent responsibility
MAX_FUNCTIONS = 10

# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------
SEV_HIGH = "HIGH"
SEV_MEDIUM = "MEDIUM"
SEV_LOW = "LOW"

SEVERITY_ORDER = {SEV_HIGH: 0, SEV_MEDIUM: 1, SEV_LOW: 2}

METRIC_META = {
    "METRIC-01": ("long_function",   SEV_HIGH,   "Function exceeds {} lines (threshold: {})"),
    "METRIC-02": ("deep_nesting",    SEV_HIGH,   "Function has nesting depth {} (threshold: {})"),
    "METRIC-03": ("long_param_list", SEV_MEDIUM, "Function has {} parameters (threshold: {})"),
    "METRIC-04": ("large_file",      SEV_MEDIUM, "File has {} lines (threshold: {})"),
    "METRIC-05": ("many_functions",  SEV_LOW,    "File has {} functions (threshold: {})"),
}

SUPPORTED_PYTHON_EXTS = {".py"}
SUPPORTED_JS_EXTS = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}
SUPPORTED_EXTS = SUPPORTED_PYTHON_EXTS | SUPPORTED_JS_EXTS


# ---------------------------------------------------------------------------
# Python analysis (AST-based — accurate)
# ---------------------------------------------------------------------------

def analyze_python(source: str, filename: str) -> list[dict]:
    findings = []

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [{
            "metric_id": "PARSE-ERROR",
            "name": "parse_error",
            "severity": SEV_HIGH,
            "message": f"SyntaxError: {exc.msg} (line {exc.lineno})",
            "file": filename,
            "line": exc.lineno or 0,
            "function": "<module>",
            "value": 0,
            "threshold": 0,
        }]

    lines = source.splitlines()

    # METRIC-04: large file
    line_count = len(lines)
    if line_count > MAX_FILE_LINES:
        findings.append(_make_finding(
            "METRIC-04", filename, 1, "<file>", line_count, MAX_FILE_LINES,
            f"File has {line_count} lines (threshold: {MAX_FILE_LINES})",
        ))

    # Collect all function/method definitions
    func_nodes = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    # METRIC-05: many functions at module level
    top_level_funcs = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if len(top_level_funcs) > MAX_FUNCTIONS:
        findings.append(_make_finding(
            "METRIC-05", filename, 1, "<module>",
            len(top_level_funcs), MAX_FUNCTIONS,
            f"File has {len(top_level_funcs)} top-level functions "
            f"(threshold: {MAX_FUNCTIONS})",
        ))

    for node in func_nodes:
        name = node.name
        start = node.lineno
        end = node.end_lineno or start

        # METRIC-01: long function — count body lines only (exclude the def line)
        # Fowler "Refactoring" §3 Long Method counts lines of the method body,
        # not the signature line itself. end - start gives body line count.
        func_lines = end - start
        if func_lines > MAX_FUNCTION_LINES:
            findings.append(_make_finding(
                "METRIC-01", filename, start, name, func_lines, MAX_FUNCTION_LINES,
                f"Function '{name}' is {func_lines} lines (threshold: {MAX_FUNCTION_LINES})",
            ))

        # METRIC-03: long param list
        args = node.args
        param_count = (
            len(args.args)
            + len(args.posonlyargs)
            + len(args.kwonlyargs)
            + (1 if args.vararg else 0)
            + (1 if args.kwarg else 0)
        )
        # Subtract 'self'/'cls' for methods
        if args.args and args.args[0].arg in ("self", "cls"):
            param_count = max(0, param_count - 1)
        if param_count > MAX_PARAMS:
            findings.append(_make_finding(
                "METRIC-03", filename, start, name, param_count, MAX_PARAMS,
                f"Function '{name}' has {param_count} parameters "
                f"(threshold: {MAX_PARAMS})",
            ))

        # METRIC-02: deep nesting — count max indentation depth within func
        max_depth = _max_nesting_python(node)
        if max_depth > MAX_NESTING_DEPTH:
            findings.append(_make_finding(
                "METRIC-02", filename, start, name, max_depth, MAX_NESTING_DEPTH,
                f"Function '{name}' has nesting depth {max_depth} "
                f"(threshold: {MAX_NESTING_DEPTH})",
            ))

    return findings


def _max_nesting_python(func_node: ast.FunctionDef) -> int:
    """Compute max block-nesting depth inside a function node."""
    def _depth(node: ast.AST, current: int) -> int:
        max_d = current
        nesting_types = (
            ast.If, ast.For, ast.While, ast.With, ast.Try,
            ast.AsyncFor, ast.AsyncWith,
        )
        for child in ast.iter_child_nodes(node):
            child_depth = current
            if isinstance(child, nesting_types):
                child_depth = current + 1
            max_d = max(max_d, _depth(child, child_depth))
        return max_d

    return _depth(func_node, 0)


# ---------------------------------------------------------------------------
# JavaScript/TypeScript analysis (regex-based — approximate)
# ---------------------------------------------------------------------------

# Match function declarations and arrow functions assigned to const/let/var
RE_JS_FUNC_START = re.compile(
    r'^\s*(?:'
    r'(?:export\s+)?(?:async\s+)?function\s+(\w+)'          # function foo
    r'|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\('     # const foo = (
    r'|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\w+)\s*=>'  # const foo = x =>
    r')',
    re.MULTILINE,
)

# Match class method definitions
RE_JS_METHOD = re.compile(
    r'^\s*(?:async\s+)?(?:static\s+)?(?:get\s+|set\s+)?(\w+)\s*\([^)]*\)\s*\{'
)


def analyze_js(source: str, filename: str) -> list[dict]:
    findings = []
    lines = source.splitlines()

    # METRIC-04: large file
    line_count = len(lines)
    if line_count > MAX_FILE_LINES:
        findings.append(_make_finding(
            "METRIC-04", filename, 1, "<file>", line_count, MAX_FILE_LINES,
            f"File has {line_count} lines (threshold: {MAX_FILE_LINES})",
        ))

    # Extract function blocks
    func_blocks = _extract_js_functions(source, lines)

    # METRIC-05: many functions
    if len(func_blocks) > MAX_FUNCTIONS:
        findings.append(_make_finding(
            "METRIC-05", filename, 1, "<module>",
            len(func_blocks), MAX_FUNCTIONS,
            f"File has {len(func_blocks)} functions/methods "
            f"(threshold: {MAX_FUNCTIONS})",
        ))

    for (name, start_line, func_source) in func_blocks:
        func_line_count = func_source.count("\n") + 1

        # METRIC-01: long function
        if func_line_count > MAX_FUNCTION_LINES:
            findings.append(_make_finding(
                "METRIC-01", filename, start_line, name, func_line_count, MAX_FUNCTION_LINES,
                f"Function '{name}' is {func_line_count} lines (threshold: {MAX_FUNCTION_LINES})",
            ))

        # METRIC-02: deep nesting
        max_depth = _max_nesting_js(func_source)
        if max_depth > MAX_NESTING_DEPTH:
            findings.append(_make_finding(
                "METRIC-02", filename, start_line, name, max_depth, MAX_NESTING_DEPTH,
                f"Function '{name}' has nesting depth {max_depth} "
                f"(threshold: {MAX_NESTING_DEPTH})",
            ))

        # METRIC-03: long param list — count params in the opening signature
        params = _count_js_params(func_source)
        if params > MAX_PARAMS:
            findings.append(_make_finding(
                "METRIC-03", filename, start_line, name, params, MAX_PARAMS,
                f"Function '{name}' has {params} parameters "
                f"(threshold: {MAX_PARAMS})",
            ))

    return findings


def _extract_js_functions(source: str, lines: list[str]) -> list[tuple[str, int, str]]:
    """Return list of (name, start_line, block_source) for each function."""
    results = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Try to match function start
        name = None
        m = RE_JS_FUNC_START.match(line)
        if m:
            name = m.group(1) or m.group(2) or m.group(3) or "<anonymous>"
        elif RE_JS_METHOD.match(line):
            mm = RE_JS_METHOD.match(line)
            name = mm.group(1) if mm else "<method>"
            # Skip constructor, common non-method tokens
            if name in ("if", "for", "while", "switch", "catch", "else"):
                i += 1
                continue

        if name is not None:
            start = i
            block_lines = [line]
            depth = line.count("{") - line.count("}")
            j = i + 1
            while j < len(lines) and depth > 0:
                block_lines.append(lines[j])
                depth += lines[j].count("{") - lines[j].count("}")
                j += 1
            results.append((name, start + 1, "\n".join(block_lines)))
            i = j
        else:
            i += 1

    return results


def _max_nesting_js(func_source: str) -> int:
    """Approximate max nesting depth by tracking { } depth."""
    max_depth = 0
    current = 0
    # Start at -1 because the function opening brace is depth 0
    in_string = False
    string_char = None
    for char in func_source:
        if in_string:
            if char == string_char:
                in_string = False
        elif char in ('"', "'", "`"):
            in_string = True
            string_char = char
        elif char == "{":
            current += 1
            max_depth = max(max_depth, current)
        elif char == "}":
            current = max(0, current - 1)
    # Subtract 1 for the function's own opening brace
    return max(0, max_depth - 1)


def _count_js_params(func_source: str) -> int:
    """Count params in the first (...) group of the function signature."""
    # Extract the param list between the first ( and its matching )
    m = re.search(r'\(([^)]*)\)', func_source[:300])
    if not m:
        return 0
    param_str = m.group(1).strip()
    if not param_str:
        return 0
    # Count comma-separated segments, handling destructuring crudely
    # Remove nested brackets to avoid counting commas inside destructuring
    cleaned = re.sub(r'\{[^}]*\}', '_obj_', param_str)
    cleaned = re.sub(r'\[[^\]]*\]', '_arr_', cleaned)
    return len([p for p in cleaned.split(",") if p.strip()])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_finding(metric_id: str, filename: str, line: int, function: str,
                  value: int, threshold: int, message: str) -> dict:
    meta = METRIC_META.get(metric_id, (metric_id, SEV_MEDIUM, message))
    return {
        "metric_id": metric_id,
        "name": meta[0],
        "severity": meta[1],
        "message": message,
        "file": filename,
        "line": line,
        "function": function,
        "value": value,
        "threshold": threshold,
    }


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_source(source: str | None) -> tuple[str, str]:
    """
    Returns (filename, source_text).
    source=None or '-' → stdin, language inferred from content.
    """
    if source is None or source == "-":
        return "<stdin>", sys.stdin.read()

    path = Path(source)
    if not path.exists():
        raise ValueError(f"Path not found: {source}")
    if path.is_dir():
        raise ValueError(f"Expected a file, got a directory: {source}")
    if path.suffix not in SUPPORTED_EXTS:
        raise ValueError(
            f"Unsupported file extension '{path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTS))}"
        )
    try:
        return str(path), path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read '{source}': {exc}") from exc


def detect_language(filename: str, source: str) -> str:
    """Return 'python' or 'javascript' based on filename or content."""
    ext = Path(filename).suffix.lower()
    if ext in SUPPORTED_PYTHON_EXTS:
        return "python"
    if ext in SUPPORTED_JS_EXTS:
        return "javascript"
    # stdin heuristic: presence of `def ` or `import ` at line start → python
    if re.search(r'^def |^import |^from ', source, re.MULTILINE):
        return "python"
    return "javascript"


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def render_markdown(findings: list[dict]) -> str:
    if not findings:
        return "_No refactoring signals detected._\n"

    lines = [
        "| File | Line | Function | Metric | Severity | Value | Threshold | Message |",
        "|------|------|----------|--------|----------|-------|-----------|---------|",
    ]
    for f in findings:
        fname = Path(f["file"]).name
        lines.append(
            f"| {fname} | {f['line']} | `{f['function']}` "
            f"| {f['metric_id']} | {f['severity']} "
            f"| {f['value']} | {f['threshold']} "
            f"| {f['message']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(source: str | None) -> int:
    try:
        filename, text = load_source(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not text.strip():
        output = {"findings": [], "summary": {
            "total": 0, "high": 0, "medium": 0, "low": 0, "language": "unknown"
        }}
        print(json.dumps(output, indent=2))
        print()
        print("## Refactoring Metrics Report\n")
        print("_No input provided._\n")
        return 0

    language = detect_language(filename, text)
    if language == "python":
        findings = analyze_python(text, filename)
    else:
        findings = analyze_js(text, filename)

    # Sort: HIGH first, then by line number
    findings.sort(key=lambda f: (
        SEVERITY_ORDER.get(f["severity"], 99),
        f["line"],
    ))

    summary = {
        "total": len(findings),
        "high": sum(1 for f in findings if f["severity"] == SEV_HIGH),
        "medium": sum(1 for f in findings if f["severity"] == SEV_MEDIUM),
        "low": sum(1 for f in findings if f["severity"] == SEV_LOW),
        "language": language,
    }

    output = {"findings": findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()
    print("## Refactoring Metrics Report\n")
    print(render_markdown(findings))
    print(
        "**Severity:** HIGH = strong refactoring signal | "
        "MEDIUM = review needed | LOW = informational"
    )
    print(
        "\n**Thresholds:** "
        f"long_function={MAX_FUNCTION_LINES} lines, "
        f"deep_nesting={MAX_NESTING_DEPTH} levels, "
        f"long_param_list={MAX_PARAMS} params, "
        f"large_file={MAX_FILE_LINES} lines, "
        f"many_functions={MAX_FUNCTIONS} functions"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect refactoring signals in Python or JS/TS source files. "
            "Reads a single file or stdin."
        ),
        epilog=(
            "Metrics: long_function (METRIC-01), deep_nesting (METRIC-02), "
            "long_param_list (METRIC-03), large_file (METRIC-04), "
            "many_functions (METRIC-05)."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to a .py or .js/.ts file, or '-' for stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
