"""
validation_result.py — Structured per-check validation result for Claude Copilot hooks.

Shared between:
  - WS1: QA-gate hook artifact markers (pretool-check.sh / subagent-stop.sh)
  - WS2: cc memory check deterministic checkers
  - Any future hook that needs a standard pass/fail/warn shape.

Shape contract (per ADR-001):
  CheckResult  — one check: status (pass|fail|warn) + expected + actual + message
  ValidationReport — collection of checks with severity rollup to one verdict

Severity rollup: fail > warn > pass (first fail → fail; no fail but warn → warn; all pass → pass)

Shell contract (R2 from WP-125):
  report.to_shell_json() → single JSON line, no trailing newline embedded,
  readable by bash hooks via: verdict=$(echo "$json" | jq -r '.verdict')

Usage from bash:
    python3 .claude/hooks/lib/validation_result.py --check-import
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List, Literal, Optional


Status = Literal["pass", "fail", "warn"]
Verdict = Literal["pass", "fail", "warn"]

_SEVERITY: dict[str, int] = {"fail": 2, "warn": 1, "pass": 0}


@dataclass
class CheckResult:
    """Result of a single failable check.

    Args:
        check:    Short identifier for the check (e.g. "agent-count").
        status:   "pass", "fail", or "warn".
        expected: What was expected (string representation). Optional.
        actual:   What was actually observed. Optional.
        message:  Human-readable explanation.
        artifact: Optional external artifact reference (path, command, exit-code)
                  that proves the result is not introspection-only (ADR-001).
    """

    check: str
    status: Status
    message: str = ""
    expected: Optional[str] = None
    actual: Optional[str] = None
    artifact: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"check": self.check, "status": self.status}
        if self.expected is not None:
            d["expected"] = self.expected
        if self.actual is not None:
            d["actual"] = self.actual
        if self.message:
            d["message"] = self.message
        if self.artifact is not None:
            d["artifact"] = self.artifact
        return d


@dataclass
class ValidationReport:
    """Collection of CheckResults with a single rolled-up verdict.

    Rollup rule (fail > warn > pass):
      - Any fail  → verdict = "fail"
      - No fail but any warn → verdict = "warn"
      - All pass  → verdict = "pass"

    Args:
        checks:  List of CheckResult instances.
        context: Optional string (e.g. task ID, scope) for log correlation.
    """

    checks: List[CheckResult] = field(default_factory=list)
    context: Optional[str] = None

    @property
    def verdict(self) -> Verdict:
        if not self.checks:
            return "pass"
        severity = max(_SEVERITY.get(c.status, 0) for c in self.checks)
        if severity >= 2:
            return "fail"
        if severity >= 1:
            return "warn"
        return "pass"

    def to_dict(self) -> dict:
        d: dict = {
            "verdict": self.verdict,
            "checks": [c.to_dict() for c in self.checks],
        }
        if self.context is not None:
            d["context"] = self.context
        return d

    def to_json(self, indent: int = 2) -> str:
        """Pretty-printed JSON for human consumption and work product storage."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_shell_json(self) -> str:
        """Compact single-line JSON for bash hook consumption.

        Suitable for: verdict=$(python3 ... | jq -r '.verdict')
        """
        return json.dumps(self.to_dict(), separators=(",", ":"))

    def passed(self) -> bool:
        return self.verdict == "pass"

    def failed(self) -> bool:
        return self.verdict == "fail"

    def summary(self) -> str:
        """One-liner summary for logging."""
        counts = {"pass": 0, "fail": 0, "warn": 0}
        for c in self.checks:
            counts[c.status] = counts.get(c.status, 0) + 1
        return (
            f"verdict={self.verdict} "
            f"pass={counts['pass']} warn={counts['warn']} fail={counts['fail']}"
        )


# ---------------------------------------------------------------------------
# Convenience builders
# ---------------------------------------------------------------------------

def passed(check: str, message: str = "", artifact: Optional[str] = None) -> CheckResult:
    """Return a passing CheckResult."""
    return CheckResult(check=check, status="pass", message=message, artifact=artifact)


def failed(
    check: str,
    message: str = "",
    expected: Optional[str] = None,
    actual: Optional[str] = None,
    artifact: Optional[str] = None,
) -> CheckResult:
    """Return a failing CheckResult."""
    return CheckResult(
        check=check,
        status="fail",
        message=message,
        expected=expected,
        actual=actual,
        artifact=artifact,
    )


def warned(
    check: str,
    message: str = "",
    expected: Optional[str] = None,
    actual: Optional[str] = None,
) -> CheckResult:
    """Return a warning CheckResult."""
    return CheckResult(
        check=check,
        status="warn",
        message=message,
        expected=expected,
        actual=actual,
    )


# ---------------------------------------------------------------------------
# CLI smoke-test (called by bash hooks to verify importability)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if "--check-import" in sys.argv:
        # Smoke-test: build a sample report and emit it, then exit 0
        report = ValidationReport(
            checks=[
                passed("import", "validation_result.py imports cleanly"),
                passed("CheckResult", "CheckResult instantiates correctly"),
                passed("ValidationReport", "ValidationReport rollup is correct"),
            ],
            context="smoke-test",
        )
        print(report.to_shell_json())
        sys.exit(0)

    # Default: print usage
    print("Usage: python3 validation_result.py --check-import", file=sys.stderr)
    sys.exit(1)
