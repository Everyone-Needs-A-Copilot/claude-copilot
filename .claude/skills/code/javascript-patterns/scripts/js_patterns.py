#!/usr/bin/env python3
"""
JavaScript/TypeScript Anti-Pattern Checker — L3 executable for the javascript-patterns skill.

Regex-based lint-lite scanner for a closed set of well-known JS/TS anti-patterns.
No third-party dependencies required.

Scope note: This tool detects a closed, named set of patterns deterministically.
It is NOT a full AST parser and does NOT replace ESLint. It reliably catches:
  - var declarations (line-level)
  - loose equality operators (== / !=)
  - leftover console.log calls
  - excessive callback nesting depth

Input (file path as first argument, or '-'/no-arg for stdin):
  JavaScript or TypeScript source code

Output (stdout):
  1. JSON object with findings (list) and summary (counts by severity).
  2. Markdown table of findings sorted by severity then line number.

Exit codes:
  0 — success (including empty input, even with findings)
  1 — invalid input (file not found, unreadable)

Detected rules:
  VAR_DECL          MEDIUM — var declaration (use const/let instead)
  LOOSE_EQUALITY    MEDIUM — == or != operator (use === / !==)
  CONSOLE_LOG       LOW    — leftover console.log( call
  CALLBACK_NESTING  MEDIUM — callback nesting depth >= threshold (likely callback hell)

Severity levels:
  MEDIUM — idiomatic debt; common source of subtle bugs or readability issues
  LOW    — informational; debug code left in, style debt

Thresholds (documented, not ad-hoc):
  CALLBACK_NESTING_THRESHOLD = 3
    Rationale: 1–2 levels of nesting is normal (e.g., .then() + error handler);
    3+ levels is the "callback hell" shape that async/await should replace.
    Widely referenced in JS style guides (Airbnb, StandardJS, MDN async guide).
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds — documented, not ad-hoc
# ---------------------------------------------------------------------------

# Nesting depth at which callback-style code is flagged as "callback hell".
# Rationale: 3+ levels of function(){ ... } nesting indicates code that should
# be refactored to async/await. Reference: Node.js best practices guide,
# Airbnb JS style guide section on async patterns.
CALLBACK_NESTING_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Severity ordering
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}

# ---------------------------------------------------------------------------
# Patterns — each is (rule, severity, compiled regex, message template)
# Line-level patterns are applied per line. The callback nesting check is
# applied at file level.
# ---------------------------------------------------------------------------

# Matches `var ` at the start of a statement (after optional whitespace).
# Avoids matching `var` as part of an identifier (e.g., `varName`).
# The word-boundary \b before a space isn't needed because we require a space.
_RE_VAR = re.compile(r"\bvar\s+")

# Matches loose equality == or != that is NOT already === or !==.
# Uses negative lookbehind (for =) and lookahead (for =) to exclude === and !==.
_RE_LOOSE_EQ = re.compile(r"(?<![=!])(?:==(?!=)|!=(?!=))")

# Matches console.log( — leftover debug call.
_RE_CONSOLE_LOG = re.compile(r"\bconsole\.log\s*\(")

# Callback nesting: detect lines that open a callback-style function expression.
# Matches patterns like: function(...) {, (...) => {, function() {
# Used to track nesting depth across lines.
_RE_CALLBACK_OPEN = re.compile(
    r"(?:function\s*\w*\s*\([^)]*\)\s*\{|=>\s*\{|\([^)]*\)\s*=>\s*\{)"
)
_RE_BRACE_OPEN = re.compile(r"\{")
_RE_BRACE_CLOSE = re.compile(r"\}")

LINE_RULES = [
    (
        "VAR_DECL",
        "MEDIUM",
        _RE_VAR,
        "Use `const` (or `let`) instead of `var`. `var` has function-scoped hoisting "
        "which causes hard-to-trace bugs.",
    ),
    (
        "LOOSE_EQUALITY",
        "MEDIUM",
        _RE_LOOSE_EQ,
        "Use `===` / `!==` instead of `==` / `!=`. Loose equality performs implicit "
        "type coercion which can produce unexpected results.",
    ),
    (
        "CONSOLE_LOG",
        "LOW",
        _RE_CONSOLE_LOG,
        "Leftover `console.log(` call. Remove debug logging before merging.",
    ),
]


def _strip_string_literals(line: str) -> str:
    """
    Remove string literal contents from a line to avoid false positives
    from patterns inside strings/comments.
    This is a best-effort heuristic — not a full JS tokenizer.
    Replaces content of single-quoted, double-quoted, and template strings
    with placeholder characters.
    """
    # Remove single-line comments (// ...)
    line = re.sub(r"//.*$", "", line)
    # Remove string contents (single, double, template — non-greedy)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r"`(?:[^`\\]|\\.)*`", "``", line)
    return line


def _check_line_rules(lines: list[str]) -> list[dict]:
    """Apply per-line regex rules. Returns findings list."""
    findings = []
    for lineno, raw_line in enumerate(lines, 1):
        stripped = _strip_string_literals(raw_line)
        for rule, severity, pattern, message in LINE_RULES:
            if pattern.search(stripped):
                findings.append(
                    {
                        "rule": rule,
                        "severity": severity,
                        "line": lineno,
                        "col": (pattern.search(stripped).start() + 1),
                        "message": message,
                    }
                )
    return findings


def _check_callback_nesting(lines: list[str]) -> list[dict]:
    """
    Detect callback nesting depth >= CALLBACK_NESTING_THRESHOLD.

    Tracks brace depth and notes lines where function expressions open at
    depth >= threshold. This is a structural pattern, not semantic — it flags
    the shape of callback hell reliably.

    Returns one finding per deeply-nested callback opening.
    """
    findings = []
    depth = 0
    callback_depths = []  # stack of brace-depths where callbacks were opened

    for lineno, raw_line in enumerate(lines, 1):
        stripped = _strip_string_literals(raw_line)

        # Check if this line opens a callback at a concerning depth
        if _RE_CALLBACK_OPEN.search(stripped):
            # The callback opens at current depth
            if depth >= CALLBACK_NESTING_THRESHOLD:
                findings.append(
                    {
                        "rule": "CALLBACK_NESTING",
                        "severity": "MEDIUM",
                        "line": lineno,
                        "col": 1,
                        "message": (
                            f"Callback function opened at nesting depth {depth + 1} "
                            f"(threshold: {CALLBACK_NESTING_THRESHOLD}). "
                            "Refactor to async/await to flatten the structure."
                        ),
                    }
                )

        # Update depth by counting braces on this line
        depth += stripped.count("{") - stripped.count("}")
        depth = max(depth, 0)  # never go negative (handles mismatched braces)

    return findings


def check_source(source: str) -> list[dict]:
    """Run all checks on source text. Returns sorted findings list."""
    lines = source.splitlines()
    findings = _check_line_rules(lines) + _check_callback_nesting(lines)

    # Sort: severity DESC, line ASC
    findings.sort(key=lambda f: (-SEVERITY_ORDER.get(f["severity"], 0), f["line"]))
    return findings


def load_source(source_arg: str | None) -> tuple[str, str]:
    """
    Load source from a file path or stdin.
    Returns (source_text, label).
    source_arg=None or '-' -> read stdin
    """
    if source_arg is None or source_arg == "-":
        return sys.stdin.read(), "<stdin>"

    path = Path(source_arg)
    try:
        return path.read_text(encoding="utf-8"), str(path)
    except FileNotFoundError:
        raise ValueError(f"File not found: {source_arg}")
    except OSError as exc:
        raise ValueError(f"Cannot read file '{source_arg}': {exc}")


def render_markdown(findings: list[dict], label: str) -> str:
    """Render findings as a markdown table."""
    if not findings:
        return "_No anti-patterns detected._\n"

    lines = [
        "| Line | Severity | Rule | Message |",
        "|------|----------|------|---------|",
    ]
    for f in findings:
        msg = f["message"].replace("|", "\\|")
        lines.append(f"| {f['line']} | {f['severity']} | `{f['rule']}` | {msg} |")
    return "\n".join(lines) + "\n"


def run(source_arg: str | None) -> int:
    """Main logic. Returns exit code."""
    try:
        source, label = load_source(source_arg)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    source = source.strip()
    if not source:
        output = {"findings": [], "summary": {"total": 0, "medium": 0, "low": 0}}
        print(json.dumps(output, indent=2))
        print()
        print("_No source provided — no findings._")
        return 0

    findings = check_source(source)

    summary = {
        "total": len(findings),
        "medium": sum(1 for f in findings if f["severity"] == "MEDIUM"),
        "low": sum(1 for f in findings if f["severity"] == "LOW"),
    }

    output = {"findings": findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()

    print(f"## JavaScript Anti-Pattern Findings: {label}\n")
    print(render_markdown(findings, label))
    print(
        f"**Summary:** {summary['total']} finding(s) — "
        f"MEDIUM: {summary['medium']} | LOW: {summary['low']}  \n"
        "Scope: lint-lite regex scan. Use ESLint for comprehensive coverage."
    )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "JavaScript/TypeScript anti-pattern checker (lint-lite). "
            "Detects var declarations, loose equality, console.log, and callback nesting."
        ),
        epilog=(
            "Rules: VAR_DECL (MEDIUM), LOOSE_EQUALITY (MEDIUM), "
            "CONSOLE_LOG (LOW), CALLBACK_NESTING (MEDIUM). "
            "Stdlib only — no pip install required."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to a .js/.ts file, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
