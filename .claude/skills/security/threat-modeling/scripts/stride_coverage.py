#!/usr/bin/env python3
"""
STRIDE Coverage Checker — L3 executable for the threat-modeling skill.

Purpose:
  Given a list of findings (each tagged with one or more STRIDE categories),
  verify that all six STRIDE categories are represented and surface any gaps.
  Also re-runs DREAD scoring if scores are provided (delegates arithmetic to
  this module; keeps prose judgment in the SKILL.md L2).

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON array of finding objects:
  [
    {
      "title": "SQL Injection allows data extraction",
      "stride": ["T", "I"],         // one or more STRIDE letters (required)
      "D": 9,                       // DREAD dimensions (optional; omit all 5 to skip scoring)
      "R": 8,
      "E": 7,
      "A": 10,
      "D2": 6
    },
    ...
  ]

STRIDE letters (case-insensitive):
  S = Spoofing
  T = Tampering
  R2 = Repudiation   (use "R2" or "Rep" to avoid collision with DREAD R)
  I = Information Disclosure
  D3 = Denial of Service  (use "D3" or "DoS" to avoid collision with DREAD D/D2)
  E = Elevation of Privilege

  Aliases accepted: "Spoofing", "Tampering", "Repudiation", "Information Disclosure",
                    "Denial of Service", "Elevation of Privilege" (case-insensitive)

Output (stdout):
  1. JSON object: { findings (with stride_labels + optional score/band), coverage, gaps, summary }
  2. Markdown: coverage table + gap warnings + (optional) DREAD rank table

Exit codes:
  0 — success (including empty input)
  1 — invalid input (bad JSON, missing required field, unknown STRIDE category)

DREAD band thresholds (same as stride-dread scorer — documented, not guessed):
  0.0 – 3.9  -> Low
  4.0 – 6.9  -> Medium
  7.0 – 8.9  -> High
  9.0 – 10.0 -> Critical
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# STRIDE category normalization
# ---------------------------------------------------------------------------
# Canonical STRIDE keys and their display names
STRIDE_KEYS = ("S", "T", "R2", "I", "D3", "E")
STRIDE_NAMES = {
    "S":  "Spoofing",
    "T":  "Tampering",
    "R2": "Repudiation",
    "I":  "Information Disclosure",
    "D3": "Denial of Service",
    "E":  "Elevation of Privilege",
}

# Alias map: everything that can appear in input -> canonical key
STRIDE_ALIASES: dict[str, str] = {}
for _k in STRIDE_KEYS:
    STRIDE_ALIASES[_k.lower()] = _k
    STRIDE_ALIASES[STRIDE_NAMES[_k].lower()] = _k

# Common shorthand aliases
_EXTRA: list[tuple[str, str]] = [
    ("spoofing", "S"),
    ("tampering", "T"),
    ("repudiation", "R2"),
    ("rep", "R2"),
    ("information disclosure", "I"),
    ("info disclosure", "I"),
    ("info", "I"),
    ("denial of service", "D3"),
    ("dos", "D3"),
    ("d3", "D3"),
    ("elevation of privilege", "E"),
    ("eop", "E"),
    ("elevation", "E"),
    ("privilege", "E"),
    # Lower-case single letters that are unambiguous
    ("s", "S"),
    ("t", "T"),
    ("i", "I"),
    ("e", "E"),
    # r2 already covered above; d3 already covered
]
for _alias, _key in _EXTRA:
    STRIDE_ALIASES[_alias.lower()] = _key

# ---------------------------------------------------------------------------
# DREAD scoring (same logic as stride-dread/scripts/dread_score.py)
# ---------------------------------------------------------------------------
DREAD_DIMS = ("D", "R", "E", "A", "D2")
DREAD_BANDS = [
    (9.0, "Critical"),
    (7.0, "High"),
    (4.0, "Medium"),
    (0.0, "Low"),
]


def assign_dread_band(score: float) -> str:
    for threshold, label in DREAD_BANDS:
        if score >= threshold:
            return label
    return "Low"


def score_finding(finding: dict) -> tuple[float, str] | None:
    """
    Compute DREAD score if all five dimensions are present; return None otherwise.
    Raises ValueError if any dimension is present but invalid.
    """
    present = [dim for dim in DREAD_DIMS if dim in finding]
    if not present:
        return None
    if len(present) != len(DREAD_DIMS):
        missing = [d for d in DREAD_DIMS if d not in finding]
        raise ValueError(
            f"Finding '{finding.get('title', '?')}': partial DREAD scores provided. "
            f"Either include all five dimensions (D, R, E, A, D2) or omit all. "
            f"Missing: {missing}"
        )
    values: list[float] = []
    for dim in DREAD_DIMS:
        raw = finding[dim]
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise ValueError(
                f"Finding '{finding.get('title', '?')}': dimension '{dim}' must be a number, "
                f"got {type(raw).__name__} ({raw!r})"
            )
        v = float(raw)
        if v < 1 or v > 10:
            raise ValueError(
                f"Finding '{finding.get('title', '?')}': dimension '{dim}' = {raw} is out of range (1-10)."
            )
        values.append(v)
    avg = round(sum(values) / len(values), 1)
    return avg, assign_dread_band(avg)


# ---------------------------------------------------------------------------
# Finding validation
# ---------------------------------------------------------------------------

def normalize_stride_tag(raw: str, finding_title: str) -> str:
    """Normalize one STRIDE tag to its canonical key; raise ValueError if unknown."""
    normalized = raw.strip().lower()
    if normalized not in STRIDE_ALIASES:
        raise ValueError(
            f"Finding '{finding_title}': unknown STRIDE category '{raw}'. "
            f"Valid values: S (Spoofing), T (Tampering), R2/Rep (Repudiation), "
            f"I (Information Disclosure), D3/DoS (Denial of Service), E (Elevation of Privilege). "
            f"Full names are also accepted."
        )
    return STRIDE_ALIASES[normalized]


def validate_finding(finding: object, index: int) -> dict:
    """Validate one finding dict. Returns cleaned dict or raises ValueError."""
    if not isinstance(finding, dict):
        raise ValueError(f"Finding at index {index} must be a JSON object, got {type(finding).__name__}")

    if "title" not in finding:
        raise ValueError(f"Finding at index {index} missing required field 'title'")

    title = finding["title"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Finding at index {index}: 'title' must be a non-empty string")

    if "stride" not in finding:
        raise ValueError(
            f"Finding '{title}' (index {index}) missing required field 'stride'. "
            f"Provide a JSON array of STRIDE category tags, e.g. [\"S\", \"T\"]."
        )

    stride_raw = finding["stride"]
    if not isinstance(stride_raw, list) or len(stride_raw) == 0:
        raise ValueError(
            f"Finding '{title}' (index {index}): 'stride' must be a non-empty JSON array of category tags."
        )

    stride_keys: list[str] = []
    seen: set[str] = set()
    for tag in stride_raw:
        if not isinstance(tag, str):
            raise ValueError(
                f"Finding '{title}' (index {index}): each STRIDE tag must be a string, got {type(tag).__name__}."
            )
        canonical = normalize_stride_tag(tag, title)
        if canonical not in seen:
            stride_keys.append(canonical)
            seen.add(canonical)

    return {
        "title": title.strip(),
        "stride": stride_keys,
        # Pass-through all DREAD dims (validated later by score_finding)
        **{k: finding[k] for k in DREAD_DIMS if k in finding},
    }


# ---------------------------------------------------------------------------
# Coverage analysis
# ---------------------------------------------------------------------------

def compute_coverage(findings: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    """
    Returns:
      coverage: { stride_key -> [finding titles that address it] }
      gaps: list of stride_keys with zero coverage
    """
    coverage: dict[str, list[str]] = {k: [] for k in STRIDE_KEYS}
    for f in findings:
        for k in f["stride"]:
            coverage[k].append(f["title"])
    gaps = [k for k in STRIDE_KEYS if not coverage[k]]
    return coverage, gaps


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_input(source: str | None) -> list:
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
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from {label}: {exc}")

    if not isinstance(data, list):
        raise ValueError(
            f"Input from {label} must be a JSON array of finding objects, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_coverage_table(coverage: dict[str, list[str]], gaps: list[str]) -> str:
    lines = [
        "## STRIDE Coverage\n",
        "| Category | Covered | Findings |",
        "|----------|---------|----------|",
    ]
    for k in STRIDE_KEYS:
        covered = "YES" if coverage[k] else "**GAP**"
        titles = ", ".join(coverage[k]) if coverage[k] else "—"
        lines.append(f"| {STRIDE_NAMES[k]} | {covered} | {titles} |")
    lines.append("")
    if gaps:
        gap_names = ", ".join(STRIDE_NAMES[g] for g in gaps)
        lines.append(f"> **Coverage gaps:** {gap_names}")
        lines.append("> Review the threat model — missing categories indicate blind spots.")
    else:
        lines.append("> **All six STRIDE categories covered.**")
    return "\n".join(lines) + "\n"


def render_dread_table(scored_findings: list[dict]) -> str:
    if not scored_findings:
        return ""
    lines = [
        "\n## DREAD Severity Rankings (findings with scores)\n",
        "| # | Title | D | R | E | A | D2 | Score | Band |",
        "|---|-------|---|---|---|---|----|-------|------|",
    ]
    for i, f in enumerate(scored_findings, 1):
        lines.append(
            f"| {i} | {f['title']} "
            f"| {f['D']:.0f} | {f['R']:.0f} | {f['E']:.0f} | {f['A']:.0f} | {f['D2']:.0f} "
            f"| **{f['score']}** | {f['band']} |"
        )
    lines.append("")
    lines.append(
        "**Bands:** Critical = 9-10 | High = 7-8.9 | Medium = 4-6.9 | Low = 0-3.9  "
        "(score = average of D / R / E / A / D2, each 1-10)"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run(source: str | None) -> int:
    try:
        raw_findings = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not raw_findings:
        output = {
            "findings": [],
            "coverage": {k: [] for k in STRIDE_KEYS},
            "gaps": list(STRIDE_KEYS),
            "summary": "No findings provided.",
        }
        print(json.dumps(output, indent=2))
        print()
        print("_No findings provided._")
        return 0

    validated: list[dict] = []
    for i, item in enumerate(raw_findings):
        try:
            validated.append(validate_finding(item, i))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Score DREAD where dimensions are provided
    scored: list[dict] = []
    for f in validated:
        try:
            result = score_finding(f)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        entry = {k: v for k, v in f.items()}
        entry["stride_labels"] = [STRIDE_NAMES[k] for k in f["stride"]]
        if result is not None:
            entry["score"], entry["band"] = result
        scored.append(entry)

    # Sort findings with scores by score desc; unscored append at end
    with_scores = sorted([f for f in scored if "score" in f], key=lambda x: x["score"], reverse=True)
    without_scores = [f for f in scored if "score" not in f]
    all_findings = with_scores + without_scores

    coverage, gaps = compute_coverage(scored)

    output = {
        "findings": all_findings,
        "coverage": coverage,
        "gaps": gaps,
        "summary": {
            "total": len(scored),
            "gaps": len(gaps),
            "covered_categories": len(STRIDE_KEYS) - len(gaps),
            "total_categories": len(STRIDE_KEYS),
            **(
                {
                    "critical": sum(1 for f in with_scores if f["band"] == "Critical"),
                    "high": sum(1 for f in with_scores if f["band"] == "High"),
                    "medium": sum(1 for f in with_scores if f["band"] == "Medium"),
                    "low": sum(1 for f in with_scores if f["band"] == "Low"),
                }
                if with_scores
                else {}
            ),
        },
    }

    print(json.dumps(output, indent=2))
    print()
    print(render_coverage_table(coverage, gaps))
    if with_scores:
        print(render_dread_table(with_scores))

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "STRIDE coverage checker. Reads JSON findings tagged with STRIDE categories, "
            "reports coverage gaps, and optionally computes DREAD scores."
        ),
        epilog=(
            "Input format: JSON array of objects with fields: "
            "title (str), stride (array of STRIDE tags), "
            "and optionally D/R/E/A/D2 (1-10 each) for DREAD scoring. "
            "STRIDE tags: S, T, R2, I, D3, E (or full names)."
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
