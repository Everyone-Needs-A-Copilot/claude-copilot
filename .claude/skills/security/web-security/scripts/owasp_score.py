#!/usr/bin/env python3
"""
OWASP Top 10 Finding Validator and Coverage Scorer — L3 executable for the web-security skill.

Purpose:
  Given a list of security findings, each tagged with an OWASP Top 10 (2021) category,
  validate the findings, compute per-category finding counts, identify coverage gaps,
  and score overall review completeness. Optionally ranks findings by a supplied
  severity field (Critical/High/Medium/Low or numeric 1-4).

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON array of finding objects:
  [
    {
      "title": "SQL injection in search endpoint",
      "owasp": "A03",               // OWASP category key (required)
      "severity": "High",           // Critical | High | Medium | Low (optional)
      "status": "open"              // open | mitigated | accepted | n/a (optional)
    },
    ...
  ]

OWASP category keys (2021 edition — use short form, e.g. "A01"):
  A01 Broken Access Control
  A02 Cryptographic Failures
  A03 Injection
  A04 Insecure Design
  A05 Security Misconfiguration
  A06 Vulnerable and Outdated Components
  A07 Identification and Authentication Failures
  A08 Software and Data Integrity Failures
  A09 Security Logging and Monitoring Failures
  A10 Server-Side Request Forgery (SSRF)

  Full category names (case-insensitive) are also accepted as 'owasp' values.

Output (stdout):
  1. JSON object: { findings (normalized), category_counts, gaps, summary }
  2. Markdown: category breakdown table + gap warnings + severity summary

Exit codes:
  0 — success (including empty input or findings with all-n/a status)
  1 — invalid input (bad JSON, unknown category, invalid severity)
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# OWASP Top 10 (2021) catalog
# ---------------------------------------------------------------------------
OWASP_CATEGORIES: dict[str, str] = {
    "A01": "Broken Access Control",
    "A02": "Cryptographic Failures",
    "A03": "Injection",
    "A04": "Insecure Design",
    "A05": "Security Misconfiguration",
    "A06": "Vulnerable and Outdated Components",
    "A07": "Identification and Authentication Failures",
    "A08": "Software and Data Integrity Failures",
    "A09": "Security Logging and Monitoring Failures",
    "A10": "Server-Side Request Forgery (SSRF)",
}
OWASP_KEYS = list(OWASP_CATEGORIES.keys())

# Alias map: lowercased name/alias -> canonical key
OWASP_ALIASES: dict[str, str] = {}
for _k, _name in OWASP_CATEGORIES.items():
    OWASP_ALIASES[_k.lower()] = _k
    OWASP_ALIASES[_name.lower()] = _k

# Extra common shorthands
_OWASP_EXTRA: list[tuple[str, str]] = [
    ("broken access control", "A01"),
    ("access control", "A01"),
    ("idor", "A01"),
    ("cryptographic failures", "A02"),
    ("crypto failures", "A02"),
    ("injection", "A03"),
    ("sql injection", "A03"),
    ("sqli", "A03"),
    ("xss", "A03"),
    ("insecure design", "A04"),
    ("security misconfiguration", "A05"),
    ("misconfiguration", "A05"),
    ("vulnerable components", "A06"),
    ("outdated components", "A06"),
    ("authentication failures", "A07"),
    ("authentication", "A07"),
    ("integrity failures", "A08"),
    ("deserialization", "A08"),
    ("logging failures", "A09"),
    ("logging and monitoring", "A09"),
    ("ssrf", "A10"),
    ("server-side request forgery", "A10"),
]
for _alias, _key in _OWASP_EXTRA:
    OWASP_ALIASES[_alias.lower()] = _key

# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------
SEVERITIES = ("Critical", "High", "Medium", "Low")
SEVERITY_ALIASES: dict[str, str] = {s.lower(): s for s in SEVERITIES}
SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}  # lower index = higher severity

# ---------------------------------------------------------------------------
# Status values
# ---------------------------------------------------------------------------
STATUSES = ("open", "mitigated", "accepted", "n/a")
STATUS_ALIASES: dict[str, str] = {s.lower(): s for s in STATUSES}


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_owasp(raw: str, finding_title: str) -> str:
    """Normalize raw OWASP value to canonical key (e.g. 'A03'). Raises ValueError if unknown."""
    normalized = raw.strip().lower()
    if normalized not in OWASP_ALIASES:
        raise ValueError(
            f"Finding '{finding_title}': unknown OWASP category '{raw}'. "
            f"Use short codes (A01-A10) or full names from OWASP Top 10 (2021). "
            f"Valid codes: {', '.join(OWASP_KEYS)}."
        )
    return OWASP_ALIASES[normalized]


def normalize_severity(raw: str, finding_title: str) -> str:
    """Normalize raw severity string; raise ValueError if unrecognized."""
    normalized = raw.strip().lower()
    if normalized not in SEVERITY_ALIASES:
        raise ValueError(
            f"Finding '{finding_title}': unknown severity '{raw}'. "
            f"Valid values: {', '.join(SEVERITIES)}."
        )
    return SEVERITY_ALIASES[normalized]


def normalize_status(raw: str, finding_title: str) -> str:
    """Normalize raw status string; raise ValueError if unrecognized."""
    normalized = raw.strip().lower()
    if normalized not in STATUS_ALIASES:
        raise ValueError(
            f"Finding '{finding_title}': unknown status '{raw}'. "
            f"Valid values: {', '.join(STATUSES)}."
        )
    return STATUS_ALIASES[normalized]


# ---------------------------------------------------------------------------
# Finding validation
# ---------------------------------------------------------------------------

def validate_finding(finding: object, index: int) -> dict:
    if not isinstance(finding, dict):
        raise ValueError(f"Finding at index {index} must be a JSON object, got {type(finding).__name__}")

    if "title" not in finding:
        raise ValueError(f"Finding at index {index} missing required field 'title'")
    title = finding["title"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Finding at index {index}: 'title' must be a non-empty string")

    if "owasp" not in finding:
        raise ValueError(
            f"Finding '{title}' (index {index}) missing required field 'owasp'. "
            f"Provide an OWASP Top 10 (2021) category code, e.g. \"A03\"."
        )
    owasp_raw = finding["owasp"]
    if not isinstance(owasp_raw, str):
        raise ValueError(f"Finding '{title}' (index {index}): 'owasp' must be a string.")

    owasp_key = normalize_owasp(owasp_raw, title)

    result: dict = {
        "title": title.strip(),
        "owasp": owasp_key,
        "owasp_name": OWASP_CATEGORIES[owasp_key],
    }

    if "severity" in finding:
        sev_raw = finding["severity"]
        if not isinstance(sev_raw, str):
            raise ValueError(f"Finding '{title}' (index {index}): 'severity' must be a string.")
        result["severity"] = normalize_severity(sev_raw, title)

    if "status" in finding:
        status_raw = finding["status"]
        if not isinstance(status_raw, str):
            raise ValueError(f"Finding '{title}' (index {index}): 'status' must be a string.")
        result["status"] = normalize_status(status_raw, title)

    return result


# ---------------------------------------------------------------------------
# Coverage computation
# ---------------------------------------------------------------------------

def compute_category_counts(findings: list[dict]) -> dict[str, list[str]]:
    """Returns { owasp_key -> [finding titles] } for all findings."""
    counts: dict[str, list[str]] = {k: [] for k in OWASP_KEYS}
    for f in findings:
        counts[f["owasp"]].append(f["title"])
    return counts


def compute_gaps(category_counts: dict[str, list[str]]) -> list[str]:
    """OWASP keys with zero findings."""
    return [k for k in OWASP_KEYS if not category_counts[k]]


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def sort_findings(findings: list[dict]) -> list[dict]:
    """
    Sort: first by severity (Critical > High > Medium > Low > unscored),
    then alphabetically by OWASP key within same severity.
    """
    def sort_key(f: dict) -> tuple[int, str]:
        sev = f.get("severity")
        sev_order = SEVERITY_ORDER.get(sev, len(SEVERITIES)) if sev else len(SEVERITIES)
        return sev_order, f["owasp"]

    return sorted(findings, key=sort_key)


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

def render_category_table(category_counts: dict[str, list[str]], gaps: list[str]) -> str:
    lines = [
        "## OWASP Top 10 (2021) Coverage\n",
        "| Code | Category | Findings | Status |",
        "|------|----------|----------|--------|",
    ]
    for k in OWASP_KEYS:
        count = len(category_counts[k])
        status = "**GAP**" if k in gaps else str(count)
        lines.append(f"| {k} | {OWASP_CATEGORIES[k]} | {count} | {status} |")
    lines.append("")
    if gaps:
        gap_names = ", ".join(f"{k} ({OWASP_CATEGORIES[k]})" for k in gaps)
        lines.append(f"> **Coverage gaps ({len(gaps)}):** {gap_names}")
        lines.append("> These categories were not reviewed. Add explicit findings or 'not applicable' notes.")
    else:
        lines.append("> **All 10 OWASP categories reviewed.**")
    return "\n".join(lines) + "\n"


def render_severity_summary(findings: list[dict]) -> str:
    scored = [f for f in findings if "severity" in f]
    if not scored:
        return ""
    counts = {s: sum(1 for f in scored if f.get("severity") == s) for s in SEVERITIES}
    open_counts = {s: sum(1 for f in scored if f.get("severity") == s and f.get("status", "open") == "open") for s in SEVERITIES}
    lines = [
        "\n## Severity Summary\n",
        "| Severity | Total | Open |",
        "|----------|-------|------|",
    ]
    for s in SEVERITIES:
        lines.append(f"| {s} | {counts[s]} | {open_counts[s]} |")
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
            "category_counts": {k: [] for k in OWASP_KEYS},
            "gaps": OWASP_KEYS,
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

    sorted_findings = sort_findings(validated)
    category_counts = compute_category_counts(validated)
    gaps = compute_gaps(category_counts)

    severity_counts = {s: sum(1 for f in validated if f.get("severity") == s) for s in SEVERITIES}
    open_findings = [f for f in validated if f.get("status", "open") == "open"]

    output = {
        "findings": sorted_findings,
        "category_counts": category_counts,
        "gaps": gaps,
        "summary": {
            "total": len(validated),
            "open": len(open_findings),
            "categories_reviewed": len(OWASP_KEYS) - len(gaps),
            "categories_total": len(OWASP_KEYS),
            "gaps": len(gaps),
            **{s.lower(): severity_counts[s] for s in SEVERITIES},
        },
    }

    print(json.dumps(output, indent=2))
    print()
    print(render_category_table(category_counts, gaps))
    sev_table = render_severity_summary(validated)
    if sev_table:
        print(sev_table)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "OWASP Top 10 finding validator and coverage scorer. "
            "Reads JSON findings tagged with OWASP categories, reports coverage gaps."
        ),
        epilog=(
            "Input format: JSON array of objects with fields: "
            "title (str, required), owasp (str, required), "
            "severity (Critical|High|Medium|Low, optional), "
            "status (open|mitigated|accepted|n/a, optional). "
            "OWASP values: A01-A10 short codes or full OWASP Top 10 (2021) category names."
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
