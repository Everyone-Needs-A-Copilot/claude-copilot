#!/usr/bin/env python3
"""
arch_fitness.py — L3 executable for the system-design-patterns skill.

Scores one or more Architecture Decision Records (ADRs) or design documents
for structural completeness. Each document is validated against a required
field schema and receives a coverage score and a completeness band.

This is a STRUCTURAL COMPLETENESS checker — it verifies that required sections
are present and non-empty. It does NOT evaluate prose quality (that is L2 prose
judgment, left to the model).

Deterministic core:
  - Required-field presence checking (closed list of ADR fields)
  - Coverage scoring: (present fields / total required fields) × 100
  - Band assignment based on coverage percentage

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON array of ADR/design-doc objects. Each object:
  {
    "id":           "ADR-001",           // required — identifier
    "title":        "Use PostgreSQL",    // required — short title
    "status":       "Accepted",          // required — one of the VALID_STATUSES
    "date":         "2026-01-15",        // required — ISO 8601 date string
    "context":      "...",               // required — non-empty prose
    "decision":     "We will use...",    // required — non-empty prose
    "consequences": "...",               // required — non-empty prose (pos/neg)
    "alternatives": [...],               // optional — list of rejected alternatives
    "references":   [...],               // optional — supporting references
    "trade_off_checklist": {...}         // optional — structured trade-off answers
  }

  The "trade_off_checklist" object, if present, should contain boolean answers
  for the 8 standard trade-off questions (see TRADE_OFF_FIELDS below).
  Any missing checklist answers are flagged as LOW-severity gaps.

Output (stdout):
  1. JSON block: { "documents": [...scored...], "summary": {...} }
  2. Markdown table of scored documents.

Exit codes:
  0 — success (including empty input)
  1 — invalid input (bad JSON, not an array, wrong types)

Scoring rules (no voodoo — each threshold is justified):
  REQUIRED_FIELDS (7 fields): These map to the ADR template sections that every
    ADR MUST have to be usable. Source: Nygard ADR format (adr.github.io) +
    Thoughtworks Technology Radar ADR guidance.

  Coverage bands:
    90–100%: COMPLETE    — all required fields present, no gaps
    70–89%:  ADEQUATE    — minor gaps; usable but should be completed
    50–69%:  PARTIAL     — significant gaps; decision rationale may be unclear
    0–49%:   INCOMPLETE  — major gaps; ADR should not be considered authoritative

  Thresholds cite: ISO/IEC 25010 documentation completeness criteria;
  Nygard ADR "lightweight but sufficient" principle (2011).

  TRADE_OFF_FIELDS (8 boolean keys) map to the 8-item trade-off analysis
  checklist in the system-design-patterns skill. Source: SKILL.md §Trade-Off
  Analysis Checklist.
"""

import argparse
import json
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Constants — all thresholds cited above and below
# ---------------------------------------------------------------------------

# Required ADR fields with human-readable labels
# Source: Nygard ADR format (https://adr.github.io); Thoughtworks TechRadar
REQUIRED_FIELDS = [
    ("id", "Identifier (id)"),
    ("title", "Short title (title)"),
    ("status", "Decision status (status)"),
    ("date", "Date (date)"),
    ("context", "Context section"),
    ("decision", "Decision statement"),
    ("consequences", "Consequences section"),
]

# Optional fields — presence is rewarded but absence is not penalised in scoring
OPTIONAL_FIELDS = ["alternatives", "references", "trade_off_checklist"]

# Valid status values per ADR lifecycle
# Source: https://adr.github.io — standard status vocabulary
VALID_STATUSES = {"proposed", "accepted", "deprecated", "superseded", "rejected"}

# Trade-off checklist keys — from the SKILL.md §Trade-Off Analysis Checklist
# Source: system-design-patterns SKILL.md
TRADE_OFF_FIELDS = [
    "quality_attribute_optimised",
    "quality_attribute_sacrificed",
    "reversibility",
    "evidence_based",
    "team_readiness",
    "failure_mode_understood",
    "migration_path",
    "documentation",
]

# Coverage band thresholds (percentage, inclusive lower bound)
# Source: ISO/IEC 25010 completeness criteria + Nygard "lightweight but sufficient"
COVERAGE_BANDS = [
    (90.0, "COMPLETE"),
    (70.0, "ADEQUATE"),
    (50.0, "PARTIAL"),
    (0.0, "INCOMPLETE"),
]

# Date pattern for basic ISO 8601 validation (YYYY-MM-DD)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Severity order for sorting findings
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assign_band(coverage_pct: float) -> str:
    """Map coverage percentage to a completeness band."""
    for threshold, label in COVERAGE_BANDS:
        if coverage_pct >= threshold:
            return label
    return "INCOMPLETE"


def is_nonempty_string(value: Any) -> bool:
    """Return True if value is a non-empty, non-whitespace string."""
    return isinstance(value, str) and bool(value.strip())


def finding(severity: str, location: str, message: str) -> dict:
    return {"severity": severity, "location": location, "message": message}


# ---------------------------------------------------------------------------
# Document validator / scorer
# ---------------------------------------------------------------------------


def validate_document(doc: Any, index: int) -> dict:
    """
    Validate type and structure of one ADR document.
    Returns the validated doc dict, or raises ValueError.
    """
    if not isinstance(doc, dict):
        raise ValueError(
            f"Document at index {index} must be a JSON object, got {type(doc).__name__}"
        )
    doc_id = doc.get("id", f"<index {index}>")
    if not isinstance(doc_id, str):
        raise ValueError(f"Document at index {index}: 'id' must be a string")
    return doc


def score_document(doc: dict) -> dict:
    """
    Score one validated ADR document.
    Returns the doc augmented with: coverage_pct, band, gaps, optional_present.
    """
    gaps = []
    present = 0
    total = len(REQUIRED_FIELDS)
    doc_id = doc.get("id", "<unknown>")

    for field_key, field_label in REQUIRED_FIELDS:
        value = doc.get(field_key)
        if field_key == "status":
            if not is_nonempty_string(value):
                gaps.append(
                    finding(
                        "MEDIUM",
                        f"{doc_id}.{field_key}",
                        f"Missing required field: {field_label}",
                    )
                )
            elif value.strip().lower() not in VALID_STATUSES:
                gaps.append(
                    finding(
                        "MEDIUM",
                        f"{doc_id}.{field_key}",
                        f"Invalid status '{value}'. Must be one of: {', '.join(sorted(VALID_STATUSES))} "
                        f"[adr.github.io status vocabulary]",
                    )
                )
                present += 1  # field present but invalid — still counts as present for coverage
            else:
                present += 1
        elif field_key == "date":
            if not is_nonempty_string(value):
                gaps.append(
                    finding(
                        "MEDIUM",
                        f"{doc_id}.{field_key}",
                        f"Missing required field: {field_label}",
                    )
                )
            elif not ISO_DATE_RE.match(value.strip()):
                gaps.append(
                    finding(
                        "LOW",
                        f"{doc_id}.{field_key}",
                        f"Date '{value}' does not match ISO 8601 format YYYY-MM-DD",
                    )
                )
                present += 1
            else:
                present += 1
        else:
            if not is_nonempty_string(value):
                sev = (
                    "HIGH"
                    if field_key in ("context", "decision", "consequences")
                    else "MEDIUM"
                )
                gaps.append(
                    finding(
                        sev,
                        f"{doc_id}.{field_key}",
                        f"Missing required field: {field_label}",
                    )
                )
            else:
                present += 1

    # Optional fields — low-severity advisory gaps
    optional_present = []
    for opt_key in OPTIONAL_FIELDS:
        val = doc.get(opt_key)
        if val is not None and val != "" and val != [] and val != {}:
            optional_present.append(opt_key)

    # Trade-off checklist sub-fields (optional but tracked)
    checklist = doc.get("trade_off_checklist")
    if isinstance(checklist, dict):
        for tf_key in TRADE_OFF_FIELDS:
            if checklist.get(tf_key) is None:
                gaps.append(
                    finding(
                        "LOW",
                        f"{doc_id}.trade_off_checklist.{tf_key}",
                        f"Trade-off checklist item '{tf_key}' not answered "
                        f"[system-design-patterns SKILL.md §Trade-Off Analysis Checklist]",
                    )
                )
    elif "trade_off_checklist" not in doc:
        gaps.append(
            finding(
                "LOW",
                f"{doc_id}.trade_off_checklist",
                "Optional trade-off checklist not provided "
                "[system-design-patterns SKILL.md §Trade-Off Analysis Checklist]",
            )
        )

    coverage_pct = round((present / total) * 100, 1)
    band = assign_band(coverage_pct)

    return {
        "id": doc_id,
        "title": doc.get("title", ""),
        "coverage_pct": coverage_pct,
        "band": band,
        "gaps": sorted(
            gaps, key=lambda g: (SEVERITY_ORDER.get(g["severity"], 99), g["location"])
        ),
        "optional_present": optional_present,
    }


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def render_markdown(scored_docs: list[dict]) -> str:
    if not scored_docs:
        return "_No documents provided._\n"

    lines = [
        "| # | ID | Title | Coverage | Band | HIGH | MEDIUM | LOW |",
        "|---|-----|-------|----------|------|------|--------|-----|",
    ]
    for i, d in enumerate(scored_docs, 1):
        high = sum(1 for g in d["gaps"] if g["severity"] == "HIGH")
        medium = sum(1 for g in d["gaps"] if g["severity"] == "MEDIUM")
        low = sum(1 for g in d["gaps"] if g["severity"] == "LOW")
        lines.append(
            f"| {i} | {d['id']} | {d['title']} "
            f"| {d['coverage_pct']}% | {d['band']} "
            f"| {high} | {medium} | {low} |"
        )
    return "\n".join(lines) + "\n"


def build_summary(scored_docs: list[dict]) -> dict:
    if not scored_docs:
        return {"total": 0, "complete": 0, "adequate": 0, "partial": 0, "incomplete": 0}
    return {
        "total": len(scored_docs),
        "complete": sum(1 for d in scored_docs if d["band"] == "COMPLETE"),
        "adequate": sum(1 for d in scored_docs if d["band"] == "ADEQUATE"),
        "partial": sum(1 for d in scored_docs if d["band"] == "PARTIAL"),
        "incomplete": sum(1 for d in scored_docs if d["band"] == "INCOMPLETE"),
    }


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def load_input(source: str | None) -> Any:
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
        return None  # empty input

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from {label}: {exc}")

    if not isinstance(data, list):
        raise ValueError(
            f"Input from {label} must be a JSON array of ADR objects, "
            f"got {type(data).__name__}"
        )

    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(source: str | None) -> int:
    try:
        docs = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if docs is None:
        output = {"documents": [], "summary": build_summary([])}
        print(json.dumps(output, indent=2))
        print()
        print("_No input provided._")
        return 0

    # Validate structure
    validated = []
    for i, doc in enumerate(docs):
        try:
            validated.append(validate_document(doc, i))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Score each document
    scored = [score_document(doc) for doc in validated]

    output = {
        "documents": scored,
        "summary": build_summary(scored),
    }

    print(json.dumps(output, indent=2))
    print()

    print("## Architecture Decision Record Completeness Report\n")
    print(render_markdown(scored))
    print(
        "**Bands:** COMPLETE = 90-100% | ADEQUATE = 70-89% | "
        "PARTIAL = 50-69% | INCOMPLETE = 0-49%  "
        "(score = required fields present / 7 required fields)"
    )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "ADR completeness scorer. Reads a JSON array of ADR/design-doc objects, "
            "emits coverage scores and gap findings."
        ),
        epilog=(
            "Input: JSON array of ADR objects with fields: "
            "id, title, status, date, context, decision, consequences (all required). "
            "Optional: alternatives, references, trade_off_checklist. "
            "Pass '-' or omit the argument to read from stdin."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to JSON ADR file, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
