#!/usr/bin/env python3
"""
Python Anti-Idiom Checker — L3 executable for the python-idioms skill.

Uses Python stdlib `ast` to parse source and detect known anti-patterns.
No third-party dependencies required.

Input (file path as first argument, or '-'/no-arg for stdin):
  Python source code (.py file contents)

Output (stdout):
  1. JSON object with findings (list) and summary (counts by severity).
  2. Markdown table of findings sorted by severity then line number.

Exit codes:
  0 — success (including empty input, even with findings)
  1 — invalid input (file not found, unreadable, syntax error in source)

Detected rules (all deterministic — no judgment required):
  MUTABLE_DEFAULT  HIGH   — mutable default argument (list/dict/set literal)
  BARE_EXCEPT      HIGH   — bare `except:` clause (no exception type)
  EQ_NONE          MEDIUM — `== None` or `!= None` (use `is`/`is not`)
  RANGE_LEN        MEDIUM — `for i in range(len(x)):` (use enumerate)
  TYPE_COMPARE     MEDIUM — `type(x) == SomeType` (use isinstance)

Severity levels (documented, not ad-hoc):
  HIGH   — Correctness risk; can cause bugs (silent error swallowing,
           shared mutable state across calls)
  MEDIUM — Idiomatic debt; not buggy but violates Python style guide
           (PEP 8 / Python docs anti-pattern catalogue)
  LOW    — Reserved for future rules; not currently used
"""

import argparse
import ast
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Severity ordering (higher index = higher priority for sort)
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}

# Mutable types that must not appear as default argument values.
# Source: Python docs "Programming FAQ — Mutable default arguments"
MUTABLE_DEFAULT_NODE_TYPES = (ast.List, ast.Dict, ast.Set)


# ---------------------------------------------------------------------------
# AST visitors — each returns a list of finding dicts
# ---------------------------------------------------------------------------

class _Visitor(ast.NodeVisitor):
    """Base visitor that accumulates findings."""

    def __init__(self):
        self.findings = []

    def _add(self, node, rule, severity, message):
        self.findings.append({
            "rule": rule,
            "severity": severity,
            "line": getattr(node, "lineno", 0),
            "col": getattr(node, "col_offset", 0),
            "message": message,
        })


class MutableDefaultVisitor(_Visitor):
    """Detect mutable default arguments in function definitions.

    Rule: MUTABLE_DEFAULT — HIGH
    Source: Python docs "Programming FAQ" and PEP 8 anti-pattern catalogue.
    A mutable default (list/dict/set literal) is shared across all calls;
    this is a well-known correctness bug, not merely a style issue.
    """

    def visit_FunctionDef(self, node):
        self._check_defaults(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _check_defaults(self, node):
        defaults = node.args.defaults + node.args.kw_defaults
        for default in defaults:
            if default is None:
                continue
            if isinstance(default, MUTABLE_DEFAULT_NODE_TYPES):
                type_name = type(default).__name__.replace("ast.", "").lower()
                # Map ast node type to Python literal name
                type_map = {"list": "list", "dict": "dict", "set": "set"}
                readable = type_map.get(type_name, type_name)
                self._add(
                    default,
                    "MUTABLE_DEFAULT",
                    "HIGH",
                    f"Mutable default argument ({readable} literal) in "
                    f"function '{node.name}'. Use None sentinel instead.",
                )


class BareExceptVisitor(_Visitor):
    """Detect bare `except:` clauses.

    Rule: BARE_EXCEPT — HIGH
    Source: PEP 8 "Programming Recommendations"; bare except silently swallows
    KeyboardInterrupt and SystemExit, masking genuine errors.
    """

    def visit_ExceptHandler(self, node):
        if node.type is None:  # bare except:
            self._add(
                node,
                "BARE_EXCEPT",
                "HIGH",
                "Bare `except:` clause catches KeyboardInterrupt and SystemExit. "
                "Specify the exception type(s) to catch.",
            )
        self.generic_visit(node)


class EqNoneVisitor(_Visitor):
    """Detect `x == None` and `x != None` comparisons.

    Rule: EQ_NONE — MEDIUM
    Source: PEP 8 "Programming Recommendations" — use `is None` / `is not None`.
    `== None` works for standard objects but can be overridden via __eq__,
    making `is` the semantically correct choice per the Python data model.
    """

    def visit_Compare(self, node):
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant) and comparator.value is None:
                op_str = "==" if isinstance(op, ast.Eq) else "!="
                correct = "is" if isinstance(op, ast.Eq) else "is not"
                self._add(
                    node,
                    "EQ_NONE",
                    "MEDIUM",
                    f"Use `{correct} None` instead of `{op_str} None` "
                    f"(PEP 8 — identity comparison for None).",
                )
        self.generic_visit(node)


class RangeLenVisitor(_Visitor):
    """Detect `for i in range(len(x)):` patterns.

    Rule: RANGE_LEN — MEDIUM
    Source: Python idiom guide; `enumerate(x)` is the idiomatic replacement
    that avoids an extra indexing step and is more readable.
    """

    def visit_For(self, node):
        # Match: for <name> in range(len(<something>)):
        iter_ = node.iter
        if (
            isinstance(iter_, ast.Call)
            and isinstance(iter_.func, ast.Name)
            and iter_.func.id == "range"
            and len(iter_.args) == 1
            and isinstance(iter_.args[0], ast.Call)
            and isinstance(iter_.args[0].func, ast.Name)
            and iter_.args[0].func.id == "len"
        ):
            self._add(
                node,
                "RANGE_LEN",
                "MEDIUM",
                "Use `enumerate(x)` instead of `range(len(x))` when an index "
                "and value are both needed, or iterate directly.",
            )
        self.generic_visit(node)


class TypeCompareVisitor(_Visitor):
    """Detect `type(x) == SomeType` comparisons.

    Rule: TYPE_COMPARE — MEDIUM
    Source: PEP 8 "Programming Recommendations"; `isinstance` is preferred
    because it handles subclasses correctly and is the idiomatic approach.
    """

    def visit_Compare(self, node):
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq):
                # Check if left side is type(...)
                if (
                    isinstance(node.left, ast.Call)
                    and isinstance(node.left.func, ast.Name)
                    and node.left.func.id == "type"
                ):
                    self._add(
                        node,
                        "TYPE_COMPARE",
                        "MEDIUM",
                        "Use `isinstance(x, T)` instead of `type(x) == T`. "
                        "`isinstance` handles subclasses correctly (PEP 8).",
                    )
                    break
                # Also catch: SomeType == type(...)
                if (
                    isinstance(comparator, ast.Call)
                    and isinstance(comparator.func, ast.Name)
                    and comparator.func.id == "type"
                ):
                    self._add(
                        node,
                        "TYPE_COMPARE",
                        "MEDIUM",
                        "Use `isinstance(x, T)` instead of `type(x) == T`. "
                        "`isinstance` handles subclasses correctly (PEP 8).",
                    )
                    break
        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

VISITORS = [
    MutableDefaultVisitor,
    BareExceptVisitor,
    EqNoneVisitor,
    RangeLenVisitor,
    TypeCompareVisitor,
]


def check_source(source: str, filename: str = "<source>") -> list[dict]:
    """Parse source and run all visitors. Returns raw findings list."""
    tree = ast.parse(source, filename=filename)  # raises SyntaxError on bad source

    all_findings = []
    for visitor_cls in VISITORS:
        v = visitor_cls()
        v.visit(tree)
        all_findings.extend(v.findings)

    # Sort: severity DESC, line ASC
    all_findings.sort(
        key=lambda f: (-SEVERITY_ORDER.get(f["severity"], 0), f["line"])
    )
    return all_findings


def load_source(source_arg: str | None) -> tuple[str, str]:
    """
    Load Python source from a file path or stdin.
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


def render_markdown(findings: list[dict]) -> str:
    """Render findings as a markdown table."""
    if not findings:
        return "_No anti-idioms detected._\n"

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
        output = {"findings": [], "summary": {"total": 0, "high": 0, "medium": 0, "low": 0}}
        print(json.dumps(output, indent=2))
        print()
        print("_No source provided — no findings._")
        return 0

    try:
        findings = check_source(source, filename=label)
    except SyntaxError as exc:
        print(f"ERROR: Syntax error in source '{label}': {exc}", file=sys.stderr)
        return 1

    summary = {
        "total": len(findings),
        "high": sum(1 for f in findings if f["severity"] == "HIGH"),
        "medium": sum(1 for f in findings if f["severity"] == "MEDIUM"),
        "low": sum(1 for f in findings if f["severity"] == "LOW"),
    }

    output = {"findings": findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()

    print(f"## Python Anti-Idiom Findings: {label}\n")
    print(render_markdown(findings))
    print(
        f"**Summary:** {summary['total']} finding(s) — "
        f"HIGH: {summary['high']} | MEDIUM: {summary['medium']} | LOW: {summary['low']}  \n"
        "Severity: HIGH = correctness risk | MEDIUM = idiomatic debt | LOW = style"
    )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Python anti-idiom checker. Parses source via AST, emits ranked findings.",
        epilog=(
            "Rules: MUTABLE_DEFAULT (HIGH), BARE_EXCEPT (HIGH), "
            "EQ_NONE (MEDIUM), RANGE_LEN (MEDIUM), TYPE_COMPARE (MEDIUM). "
            "Stdlib only — no pip install required."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to a .py file, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
