#!/usr/bin/env python3
"""
DREAD Severity Scorer — L3 executable for the stride-dread skill.

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON array of finding objects:
  [
    {
      "title": "SQL Injection in login endpoint",
      "D": 9,   // Damage potential      (1-10)
      "R": 8,   // Reproducibility       (1-10)
      "E": 7,   // Exploitability        (1-10)
      "A": 10,  // Affected users        (1-10)
      "D2": 6   // Discoverability       (1-10)
    },
    ...
  ]

Output (stdout):
  1. Ranked JSON array (score desc) with computed score + band appended.
  2. Markdown table of the same findings.

Exit codes:
  0 — success (including empty input)
  1 — invalid input (bad JSON, missing field, out-of-range dimension)

DREAD dimension key naming:
  D  = Damage potential
  R  = Reproducibility
  E  = Exploitability
  A  = Affected users
  D2 = Discoverability
  (D2 avoids collision with D; both are 1-10 integers)

Band thresholds (documented, no voodoo):
  0.0 – 3.9  -> Low      (informational, accept risk, track)
  4.0 – 6.9  -> Medium   (fix next cycle)
  7.0 – 8.9  -> High     (fix current cycle)
  9.0 – 10.0 -> Critical (block deployment)
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Band thresholds — change here and the table/docs stay consistent
# ---------------------------------------------------------------------------
BANDS = [
    (9.0, "Critical"),
    (7.0, "High"),
    (4.0, "Medium"),
    (0.0, "Low"),
]

DIMENSIONS = ("D", "R", "E", "A", "D2")
DIM_LABELS = {
    "D":  "Damage",
    "R":  "Reproducibility",
    "E":  "Exploitability",
    "A":  "Affected Users",
    "D2": "Discoverability",
}


def assign_band(score: float) -> str:
    """Map a 0-10 average score to a severity band."""
    for threshold, label in BANDS:
        if score >= threshold:
            return label
    return "Low"  # score exactly 0 falls here (unreachable via the 0.0 entry but kept for safety)


def validate_finding(finding: object, index: int) -> dict:
    """
    Validate one finding dict.
    Returns the validated dict or raises ValueError with a clear message.
    """
    if not isinstance(finding, dict):
        raise ValueError(f"Finding at index {index} must be a JSON object, got {type(finding).__name__}")

    if "title" not in finding:
        raise ValueError(f"Finding at index {index} missing required field 'title'")

    title = finding["title"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Finding at index {index}: 'title' must be a non-empty string")

    validated = {"title": title.strip()}

    for dim in DIMENSIONS:
        if dim not in finding:
            raise ValueError(
                f"Finding '{title}' (index {index}) missing required dimension '{dim}' "
                f"({DIM_LABELS[dim]}). All five dimensions required: D, R, E, A, D2."
            )
        raw = finding[dim]
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise ValueError(
                f"Finding '{title}' (index {index}): dimension '{dim}' must be a number, "
                f"got {type(raw).__name__} ({raw!r})"
            )
        value = float(raw)
        if value < 1 or value > 10:
            raise ValueError(
                f"Finding '{title}' (index {index}): dimension '{dim}' = {raw} is out of range. "
                f"All dimensions must be 1-10 inclusive."
            )
        validated[dim] = value

    return validated


def score_finding(finding: dict) -> dict:
    """Compute average score and band for a validated finding."""
    average = round(sum(finding[dim] for dim in DIMENSIONS) / len(DIMENSIONS), 1)
    return {**finding, "score": average, "band": assign_band(average)}


def render_markdown(findings: list[dict]) -> str:
    """Render ranked findings as a markdown table."""
    if not findings:
        return "_No findings provided._\n"

    lines = [
        "| # | Title | D | R | E | A | D2 | Score | Band |",
        "|---|-------|---|---|---|---|----|-------|------|",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(
            f"| {i} | {f['title']} "
            f"| {f['D']:.0f} | {f['R']:.0f} | {f['E']:.0f} | {f['A']:.0f} | {f['D2']:.0f} "
            f"| **{f['score']}** | {f['band']} |"
        )
    return "\n".join(lines) + "\n"


def load_input(source: str | None) -> list:
    """
    Load JSON from a file path or stdin.
    source=None or '-' -> read stdin
    otherwise          -> read file at that path
    """
    if source is None or source == "-":
        raw = sys.stdin.read()
        label = "<stdin>"
    else:
        try:
            with open(source, encoding="utf-8") as fh:
                raw = fh.read()
        except FileNotFoundError:
            raise ValueError(f"Input file not found: {source}")
        except OSError as exc:
            raise ValueError(f"Cannot read input file '{source}': {exc}")
        label = source

    raw = raw.strip()
    if not raw:
        return []  # empty input -> empty findings list (not an error)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from {label}: {exc}")

    if not isinstance(data, list):
        raise ValueError(
            f"Input from {label} must be a JSON array of finding objects, "
            f"got {type(data).__name__}"
        )

    return data


def run(source: str | None) -> int:
    """Main logic. Returns exit code."""
    try:
        raw_findings = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not raw_findings:
        output = {"findings": [], "summary": "No findings to score."}
        print(json.dumps(output, indent=2))
        print()
        print("_No findings provided._")
        return 0

    validated = []
    for i, item in enumerate(raw_findings):
        try:
            validated.append(validate_finding(item, i))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    scored = [score_finding(f) for f in validated]
    ranked = sorted(scored, key=lambda x: x["score"], reverse=True)

    # JSON output
    output = {
        "findings": ranked,
        "summary": {
            "total": len(ranked),
            "critical": sum(1 for f in ranked if f["band"] == "Critical"),
            "high": sum(1 for f in ranked if f["band"] == "High"),
            "medium": sum(1 for f in ranked if f["band"] == "Medium"),
            "low": sum(1 for f in ranked if f["band"] == "Low"),
        },
    }
    print(json.dumps(output, indent=2))
    print()

    # Markdown table
    print("## DREAD Severity Rankings\n")
    print(render_markdown(ranked))
    print(
        "**Bands:** Critical = 9-10 | High = 7-8.9 | Medium = 4-6.9 | Low = 0-3.9  "
        "(score = average of D / R / E / A / D2, each 1-10)"
    )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DREAD severity scorer. Reads JSON findings, outputs ranked JSON + markdown table.",
        epilog=(
            "Input format: JSON array of objects with fields: "
            "title (str), D (1-10), R (1-10), E (1-10), A (1-10), D2 (1-10). "
            "D=Damage, R=Reproducibility, E=Exploitability, A=AffectedUsers, D2=Discoverability."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to JSON findings file, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
