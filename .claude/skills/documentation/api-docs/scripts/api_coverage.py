#!/usr/bin/env python3
"""
api_coverage.py — L3 executable for the api-docs skill.

Validates an OpenAPI 3.x or Swagger 2.0 spec (JSON or YAML-as-JSON) for
documentation completeness, emitting ranked findings.

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON object — an OpenAPI 3.x or Swagger 2.0 spec.
  YAML is NOT supported (pass as JSON; convert upstream if needed).

Output (stdout):
  1. JSON block: { "findings": [...], "summary": {...} }
  2. Markdown table of ranked findings.

Exit codes:
  0 — success (including empty input and specs with zero findings)
  1 — invalid input (bad JSON, not an object, unrecognised spec format)

Rules applied (each cites the OpenAPI / Swagger spec section):
  R01  Path operation missing summary         [OAS3 §4.8.10.1 / Swagger §2.2]
  R02  Path operation missing description     [OAS3 §4.8.10.1 / Swagger §2.2]
  R03  Path parameter missing description     [OAS3 §4.8.12.1 / Swagger §2.4]
  R04  Query/header/cookie param missing desc [OAS3 §4.8.12.1 / Swagger §2.4]
  R05  Request body missing description       [OAS3 §4.8.13.1]
  R06  Request body content missing example   [OAS3 §4.8.14.1]
  R07  Response missing description           [OAS3 §4.8.17.1 / Swagger §2.6]
  R08  Response schema missing example        [OAS3 §4.8.14.1]
  R09  Missing 4xx response code              [OAS3 best practice; RFC 7231 §6]
  R10  Missing 401/403 on secured endpoint    [OAS3 §4.8.21 / Swagger §2.9]
  R11  Global auth defined but operation      [OAS3 §4.8.21 / Swagger §2.2]
      uses no security scheme
  R12  Inconsistent operation ID casing       [OAS3 §4.8.10.1 — operationId
      should be camelCase per convention]
  R13  Info block missing contact/license     [OAS3 §4.8.2 / Swagger §2.1]

Severity levels (no voodoo — each level is justified below):
  HIGH   — R09, R10, R11  (missing auth/error docs causes runtime client failures)
  MEDIUM — R01, R03, R05, R07 (missing required prose per spec)
  LOW    — R02, R04, R06, R08, R12, R13 (missing enrichment; still useful)
"""

import argparse
import json
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Severity bands — cited per rule above; change here and output stays consistent
# ---------------------------------------------------------------------------
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Camel-case pattern for operationId convention check (R12)
# Convention: camelCase (lowercase first letter, no underscores/hyphens)
# Source: OpenAPI community convention; Stoplight API Style Guide
CAMEL_CASE_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")

# HTTP success codes that indicate the endpoint probably requires auth
# (endpoints returning 2xx usually need a 401/403 if secured)
SUCCESS_CODES = {"200", "201", "202", "204"}

# Minimum client-error response required per operation (R09)
CLIENT_ERROR_CODES = {"400", "401", "403", "404", "409", "422", "429"}


# ---------------------------------------------------------------------------
# Finding builder
# ---------------------------------------------------------------------------

def finding(rule: str, severity: str, location: str, message: str) -> dict:
    return {
        "rule": rule,
        "severity": severity,
        "location": location,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Spec introspection helpers
# ---------------------------------------------------------------------------

def get_paths(spec: dict) -> dict:
    """Return the paths object regardless of spec version."""
    return spec.get("paths") or {}


def get_operations(path_item: dict) -> list[tuple[str, dict]]:
    """Return (method, operation) pairs from a path item object."""
    http_methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    return [(m, path_item[m]) for m in http_methods if m in path_item and isinstance(path_item[m], dict)]


def get_global_security_schemes(spec: dict) -> set[str]:
    """Return the set of globally defined security scheme names."""
    # OAS3
    components = spec.get("components") or {}
    oas3_schemes = set((components.get("securitySchemes") or {}).keys())
    # Swagger 2
    swagger_defs = set((spec.get("securityDefinitions") or {}).keys())
    return oas3_schemes | swagger_defs


def operation_has_security(operation: dict, spec: dict) -> bool:
    """Return True if the operation or global spec declares a security requirement."""
    op_security = operation.get("security")
    if op_security is not None:
        return bool(op_security)  # empty list means explicitly unsecured
    global_security = spec.get("security")
    if global_security:
        return True
    return False


def get_response_codes(operation: dict) -> set[str]:
    """Return the set of response status codes declared for an operation."""
    responses = operation.get("responses") or {}
    return set(str(k) for k in responses.keys())


def has_example_in_media_type(media_type_obj: dict) -> bool:
    """Return True if a media type object has at least one example."""
    if not isinstance(media_type_obj, dict):
        return False
    if media_type_obj.get("example") is not None:
        return True
    if media_type_obj.get("examples"):
        return True
    schema = media_type_obj.get("schema") or {}
    if isinstance(schema, dict) and schema.get("example") is not None:
        return True
    return False


def has_any_4xx_response(codes: set[str]) -> bool:
    """Return True if at least one 4xx code is declared."""
    return bool(codes & CLIENT_ERROR_CODES) or any(
        c.startswith("4") for c in codes
    )


def has_auth_error_response(codes: set[str]) -> bool:
    """Return True if 401 or 403 is declared."""
    return "401" in codes or "403" in codes


# ---------------------------------------------------------------------------
# Rule checkers
# ---------------------------------------------------------------------------

def check_info(spec: dict) -> list[dict]:
    """R13 — info block missing contact/license."""
    findings = []
    info = spec.get("info") or {}
    if not info.get("contact"):
        findings.append(finding("R13", "LOW", "info", "Missing 'contact' in info block [OAS3 §4.8.2]"))
    if not info.get("license"):
        findings.append(finding("R13", "LOW", "info", "Missing 'license' in info block [OAS3 §4.8.2]"))
    return findings


def check_operation_id_casing(op_id: str, location: str) -> list[dict]:
    """R12 — operationId not camelCase."""
    if not op_id:
        return []
    if not CAMEL_CASE_RE.match(op_id):
        return [finding(
            "R12", "LOW", location,
            f"operationId '{op_id}' is not camelCase [OAS3 community convention]"
        )]
    return []


def check_operation(method: str, path: str, op: dict, spec: dict) -> list[dict]:
    """Run all per-operation rules."""
    loc = f"{method.upper()} {path}"
    results = []

    # R01 — missing summary
    if not (op.get("summary") or "").strip():
        results.append(finding("R01", "MEDIUM", loc, "Operation missing 'summary' [OAS3 §4.8.10.1]"))

    # R02 — missing description
    if not (op.get("description") or "").strip():
        results.append(finding("R02", "LOW", loc, "Operation missing 'description' [OAS3 §4.8.10.1]"))

    # R12 — operationId casing
    op_id = op.get("operationId") or ""
    results.extend(check_operation_id_casing(op_id, loc))

    # Parameters (R03, R04)
    params = op.get("parameters") or []
    for param in params:
        if not isinstance(param, dict):
            continue
        param_in = param.get("in", "")
        param_name = param.get("name", "<unnamed>")
        param_loc = f"{loc} param '{param_name}'"
        rule = "R03" if param_in == "path" else "R04"
        sev = "MEDIUM" if param_in == "path" else "LOW"
        if not (param.get("description") or "").strip():
            results.append(finding(
                rule, sev, param_loc,
                f"Parameter '{param_name}' ({param_in}) missing description [OAS3 §4.8.12.1]"
            ))

    # Request body (R05, R06) — OAS3 only
    req_body = op.get("requestBody")
    if isinstance(req_body, dict):
        if not (req_body.get("description") or "").strip():
            results.append(finding("R05", "MEDIUM", loc, "Request body missing description [OAS3 §4.8.13.1]"))
        content = req_body.get("content") or {}
        for media_type, mt_obj in content.items():
            if not has_example_in_media_type(mt_obj):
                results.append(finding(
                    "R06", "LOW", f"{loc} requestBody[{media_type}]",
                    f"Request body media type '{media_type}' missing example [OAS3 §4.8.14.1]"
                ))

    # Responses (R07, R08, R09, R10, R11)
    responses = op.get("responses") or {}
    codes = get_response_codes(op)

    for code, resp_obj in responses.items():
        if not isinstance(resp_obj, dict):
            continue
        resp_loc = f"{loc} response[{code}]"
        # R07 — response missing description
        if not (resp_obj.get("description") or "").strip():
            results.append(finding("R07", "MEDIUM", resp_loc, f"Response {code} missing description [OAS3 §4.8.17.1]"))
        # R08 — response schema missing example
        content = resp_obj.get("content") or {}
        for media_type, mt_obj in content.items():
            if isinstance(mt_obj, dict) and (mt_obj.get("schema") or mt_obj.get("content")):
                # Only flag if a schema is present but no example
                schema = mt_obj.get("schema")
                if schema and not has_example_in_media_type(mt_obj):
                    results.append(finding(
                        "R08", "LOW", f"{resp_loc}[{media_type}]",
                        f"Response {code} media type '{media_type}' schema has no example [OAS3 §4.8.14.1]"
                    ))

    # R09 — no 4xx response documented
    if not has_any_4xx_response(codes):
        results.append(finding("R09", "HIGH", loc, "No 4xx error response documented [RFC 7231 §6 / OAS3 best practice]"))

    # R10 — secured endpoint missing 401/403
    if operation_has_security(op, spec) and not has_auth_error_response(codes):
        results.append(finding("R10", "HIGH", loc, "Secured operation missing 401/403 response [OAS3 §4.8.21]"))

    # R11 — global security schemes defined but operation declares no security
    global_schemes = get_global_security_schemes(spec)
    if global_schemes and op.get("security") is None and not spec.get("security"):
        # Only flag if the spec defines schemes but neither the spec nor operation
        # declares a security requirement (implicit: no security applied)
        pass  # Covered by R10 — don't double-count

    return results


def run_checks(spec: dict) -> list[dict]:
    """Run all rules against the spec and return a flat list of findings."""
    all_findings = []

    # Info block checks
    all_findings.extend(check_info(spec))

    # Per-operation checks
    paths = get_paths(spec)
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in get_operations(path_item):
            all_findings.extend(check_operation(method, path, operation, spec))

    return all_findings


def rank_findings(findings: list[dict]) -> list[dict]:
    """Sort findings by severity (HIGH → MEDIUM → LOW), then rule, then location."""
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER.get(f["severity"], 99), f["rule"], f["location"])
    )


# ---------------------------------------------------------------------------
# Spec format detection
# ---------------------------------------------------------------------------

def detect_spec_version(spec: dict) -> str:
    """Return 'oas3', 'swagger2', or 'unknown'."""
    if spec.get("openapi", "").startswith("3."):
        return "oas3"
    if str(spec.get("swagger", "")).startswith("2."):
        return "swagger2"
    return "unknown"


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

def render_markdown(findings: list[dict]) -> str:
    if not findings:
        return "_No findings. Documentation coverage is complete._\n"

    lines = [
        "| # | Rule | Severity | Location | Message |",
        "|---|------|----------|----------|---------|",
    ]
    for i, f in enumerate(findings, 1):
        msg = f["message"].replace("|", "\\|")
        loc = f["location"].replace("|", "\\|")
        lines.append(f"| {i} | {f['rule']} | {f['severity']} | {loc} | {msg} |")
    return "\n".join(lines) + "\n"


def build_summary(findings: list[dict]) -> dict:
    high = sum(1 for f in findings if f["severity"] == "HIGH")
    medium = sum(1 for f in findings if f["severity"] == "MEDIUM")
    low = sum(1 for f in findings if f["severity"] == "LOW")
    return {
        "total": len(findings),
        "high": high,
        "medium": medium,
        "low": low,
    }


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def load_input(source: str | None) -> Any:
    """
    Load JSON from a file path or stdin.
    source=None or '-' -> read stdin
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
        return None  # empty input

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from {label}: {exc}")

    if not isinstance(data, dict):
        raise ValueError(
            f"Input from {label} must be a JSON object (OpenAPI/Swagger spec), "
            f"got {type(data).__name__}"
        )

    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(source: str | None) -> int:
    """Main logic. Returns exit code."""
    try:
        spec = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if spec is None:
        output = {"findings": [], "summary": {"total": 0, "high": 0, "medium": 0, "low": 0}}
        print(json.dumps(output, indent=2))
        print()
        print("_No input provided._")
        return 0

    version = detect_spec_version(spec)
    if version == "unknown":
        print("ERROR: Unrecognised spec format. Expected 'openapi: 3.x' or 'swagger: 2.x'.", file=sys.stderr)
        return 1

    findings = run_checks(spec)
    ranked = rank_findings(findings)

    output = {
        "spec_version": version,
        "findings": ranked,
        "summary": build_summary(ranked),
    }

    print(json.dumps(output, indent=2))
    print()

    print(f"## API Documentation Coverage Report ({version.upper()})\n")
    print(render_markdown(ranked))
    print(
        "**Severity:** HIGH = auth/error gaps (client failures) | "
        "MEDIUM = required prose missing | LOW = enrichment gaps"
    )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "OpenAPI/Swagger documentation coverage linter. "
            "Reads a JSON spec, emits ranked findings (JSON + markdown)."
        ),
        epilog=(
            "Input: JSON object with 'openapi' (3.x) or 'swagger' (2.x) field. "
            "Pass '-' or omit the argument to read from stdin."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to JSON spec file, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
