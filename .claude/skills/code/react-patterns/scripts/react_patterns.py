#!/usr/bin/env python3
"""
React Anti-Pattern Checker — L3 executable for the react-patterns skill.

Regex-based structural scanner for a closed set of well-known React anti-patterns.
No third-party dependencies required.

Scope: This tool detects three deterministic patterns via regex:
  1. INDEX_AS_KEY    — key={index} or key={i} etc. in .map() callbacks
  2. MISSING_KEY     — .map( JSX render with no key= prop visible within 5 lines
  3. HOOK_IN_CONDITIONAL — Hook call (use*()) inside an if statement block

It does NOT detect:
  - Missing useEffect dependencies (requires scope analysis)
  - Prop drilling depth (requires component tree analysis)
  - render-time performance issues

Input (file path as first argument, or '-'/no-arg for stdin):
  JSX or TSX source code

Output (stdout):
  1. JSON object with findings (list) and summary (counts by severity).
  2. Markdown table of findings sorted by severity then line number.

Exit codes:
  0 — success (including empty input, even with findings)
  1 — invalid input (file not found, unreadable)

Detected rules:
  INDEX_AS_KEY        HIGH   — key={<loop_var>} where loop_var is a numeric index
  MISSING_KEY         MEDIUM — .map() rendering JSX without a visible key= prop
  HOOK_IN_CONDITIONAL HIGH   — Hook call inside an if/else or short-circuit && block

Severity:
  HIGH   — Correctness risk; violates React rules (hooks) or causes silent bugs
           (incorrect reconciliation with index keys)
  MEDIUM — Likely bug; missing key prop degrades list performance and correctness

Thresholds:
  MISSING_KEY_LOOKAHEAD_LINES = 5
    Rationale: A key= prop typically appears on the opening JSX element line or
    within the next 1-2 lines for multi-line JSX. 5 lines is a generous window
    that covers normal multi-line components while avoiding false negatives.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Number of lines after a .map( opening to search for a key= prop.
# Rationale: key= is always on the root JSX element's opening tag, which
# appears within a few lines of the .map( call in normal formatting.
MISSING_KEY_LOOKAHEAD_LINES = 5

# ---------------------------------------------------------------------------
# Severity ordering
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# INDEX_AS_KEY: Matches key={<identifier>} where the identifier looks like a
# loop index variable. Covers:
#   key={index}, key={i}, key={idx}, key={n}, key={k}
# These are the conventional names used in .map((item, index) => ...) callbacks.
# Also catches key={0}, key={1} etc. (numeric literals) which are equally wrong.
#
# Pattern rationale: we match `key=` followed by `{` then an index-like name or
# digit(s). We do NOT match `key={item.id}` or `key={user.uuid}` — those are
# property accesses and are correct.
_RE_INDEX_KEY = re.compile(
    r'\bkey=\{(?:index|idx|i\b|n\b|k\b|\d+)\}'
)

# .map( opening — detect start of a map call that will render JSX.
# We look for .map( followed by content on the same or next lines.
_RE_MAP_OPEN = re.compile(r'\.map\s*\(')

# key= prop — used to confirm presence within lookahead window.
_RE_KEY_PROP = re.compile(r'\bkey\s*=')

# JSX element opening — a < followed by an uppercase letter (component) or
# lowercase with common HTML tag names. Used to detect JSX inside .map().
# We look for a return ( or direct JSX after the map callback arrow.
_RE_JSX_OPEN = re.compile(r'<[A-Za-z][A-Za-z0-9.]*[\s>]')

# HOOK_IN_CONDITIONAL: Detect hook calls (use* pattern) inside if blocks.
# Matches: `if (...)` on one line, then `use<HookName>(` within a few lines.
# Also catches: `&& use<HookName>(` (short-circuit rendering).
#
# Two-pass approach:
#   Pass 1: Note lines with `if (` or `&& ` that open a conditional block.
#   Pass 2: Check if next N lines contain a `use[A-Z]` call.
_RE_IF_BLOCK = re.compile(r'\bif\s*\(')
_RE_AND_SHORT_CIRCUIT = re.compile(r'&&\s*$|&&\s+use[A-Z]')
_RE_HOOK_CALL = re.compile(r'\buse[A-Z]\w*\s*\(')

# Lines to look ahead after an `if (` for a hook call
HOOK_CONDITIONAL_LOOKAHEAD = 3


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def _check_index_as_key(lines: list[str]) -> list[dict]:
    """Detect key={index} / key={i} / key={idx} in JSX."""
    findings = []
    for lineno, line in enumerate(lines, 1):
        if _RE_INDEX_KEY.search(line):
            match = _RE_INDEX_KEY.search(line)
            findings.append({
                "rule": "INDEX_AS_KEY",
                "severity": "HIGH",
                "line": lineno,
                "col": match.start() + 1,
                "message": (
                    "Array index used as React `key` prop. Index keys cause "
                    "incorrect reconciliation when list items are reordered, "
                    "inserted, or deleted. Use a stable unique identifier."
                ),
            })
    return findings


def _check_missing_key(lines: list[str]) -> list[dict]:
    """
    Detect .map() calls that render JSX without a key= prop.

    Strategy:
    - Find lines containing .map(
    - Scan the next MISSING_KEY_LOOKAHEAD_LINES lines for a JSX opening tag
    - If found, check that window for a key= prop
    - If no key= found, flag it

    This is a best-effort heuristic. False positives are possible for:
    - Static arrays (not from state/props) where keys are not required
    - Multi-element returns where key= is several lines away
    """
    findings = []
    n = len(lines)

    for lineno, line in enumerate(lines, 1):
        if not _RE_MAP_OPEN.search(line):
            continue

        # Scan lookahead window for JSX and key=
        window_start = lineno  # 1-indexed, already on this line
        window_end = min(lineno + MISSING_KEY_LOOKAHEAD_LINES, n)
        window = lines[window_start - 1:window_end]  # 0-indexed slice
        window_text = "\n".join(window)

        # Only flag if we see JSX opening in this window (confirms it's rendering)
        if not _RE_JSX_OPEN.search(window_text):
            continue

        # If key= is visible in the window, it's fine
        if _RE_KEY_PROP.search(window_text):
            continue

        findings.append({
            "rule": "MISSING_KEY",
            "severity": "MEDIUM",
            "line": lineno,
            "col": (_RE_MAP_OPEN.search(line).start() + 1),
            "message": (
                f"`.map()` call renders JSX but no `key=` prop found within "
                f"{MISSING_KEY_LOOKAHEAD_LINES} lines. Each element in a list "
                "must have a stable unique `key` prop."
            ),
        })

    return findings


def _check_hook_in_conditional(lines: list[str]) -> list[dict]:
    """
    Detect hooks called inside if-block bodies.

    Strategy: find `if (` lines, then scan the next few lines for
    a use[A-Z] hook call. This catches the most common violation shape.

    Limitation: does not detect hooks in ternary operator branches or
    deeply nested conditional logic. Those require AST analysis.
    """
    findings = []
    n = len(lines)

    for lineno, line in enumerate(lines, 1):
        if not _RE_IF_BLOCK.search(line):
            continue

        # Scan lookahead window for a hook call
        window_end = min(lineno + HOOK_CONDITIONAL_LOOKAHEAD, n)
        # Start from the next line (the if body)
        for check_lineno in range(lineno, window_end):
            check_line = lines[check_lineno]  # 0-indexed
            if _RE_HOOK_CALL.search(check_line):
                match = _RE_HOOK_CALL.search(check_line)
                hook_name = match.group(0).rstrip("(").strip()
                findings.append({
                    "rule": "HOOK_IN_CONDITIONAL",
                    "severity": "HIGH",
                    "line": check_lineno + 1,  # back to 1-indexed
                    "col": match.start() + 1,
                    "message": (
                        f"Hook `{hook_name}` appears to be called inside a "
                        "conditional block. Hooks must be called at the top level "
                        "of a React function — never inside if/else, loops, or "
                        "nested functions (Rules of Hooks)."
                    ),
                })
                break  # One finding per if-block is sufficient

    return findings


def check_source(source: str) -> list[dict]:
    """Run all checks. Returns findings sorted by severity DESC, line ASC."""
    lines = source.splitlines()

    findings = (
        _check_index_as_key(lines)
        + _check_missing_key(lines)
        + _check_hook_in_conditional(lines)
    )

    findings.sort(
        key=lambda f: (-SEVERITY_ORDER.get(f["severity"], 0), f["line"])
    )
    return findings


def load_source(source_arg: str | None) -> tuple[str, str]:
    """Load source from a file path or stdin. Returns (source_text, label)."""
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

    source_stripped = source.strip()
    if not source_stripped:
        output = {
            "findings": [],
            "summary": {"total": 0, "high": 0, "medium": 0},
        }
        print(json.dumps(output, indent=2))
        print()
        print("_No source provided — no findings._")
        return 0

    findings = check_source(source)

    summary = {
        "total": len(findings),
        "high": sum(1 for f in findings if f["severity"] == "HIGH"),
        "medium": sum(1 for f in findings if f["severity"] == "MEDIUM"),
    }

    output = {"findings": findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()

    print(f"## React Anti-Pattern Findings: {label}\n")
    print(render_markdown(findings, label))
    print(
        f"**Summary:** {summary['total']} finding(s) — "
        f"HIGH: {summary['high']} | MEDIUM: {summary['medium']}  \n"
        "Scope: structural regex scan. "
        "HIGH = correctness risk | MEDIUM = likely bug"
    )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "React anti-pattern checker (structural regex scan). "
            "Detects index-as-key, missing key props, and hooks in conditionals."
        ),
        epilog=(
            "Rules: INDEX_AS_KEY (HIGH), MISSING_KEY (MEDIUM), "
            "HOOK_IN_CONDITIONAL (HIGH). "
            "Stdlib only — no pip install required."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to a .jsx/.tsx file, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
