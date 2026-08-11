"""The conformance harness result model.

Every check — regardless of which layer (tier / stack / repo / lock /
roundtrip / regression) computes it — reports its outcome as one or more
`CheckResult` records. This module is the ONLY place that shape is defined,
so every sibling work package (WP-2..WP-7) and the CLI surface (WP-8) share
one vocabulary and cannot drift.

Design source of truth: the conformance harness design spec (`HARNESS-DESIGN.md`
§3.2 "five architectural rules", §3.3 "check identifier scheme", §3.4
"severity mapping"). Two rules from that spec are enforced here, not just
documented:

  - Rule 3 ("Evidence is mandatory and specific"): a `CheckResult` with
    `verdict=FAIL` MUST carry at least one `Evidence` entry, and every
    `Evidence` entry MUST carry a non-empty `path`. `CheckResult.__post_init__`
    raises `ValueError` immediately if a check body tries to construct a FAIL
    result without it — this is a fail-fast constructor invariant, not merely
    a test assertion (see `tests/conformance/test_harness_core.py`'s
    `test_every_failure_carries_path_level_evidence` for the pytest-visible
    proof of the same rule).
  - Rule 5 ("Three verdicts, plus a fourth for honesty"): `COULD_NOT_RUN`
    (the harness could not determine an answer) is a verdict distinct from
    both `FAIL` and `PASS` and must never be coerced into either — see
    `report.compute_exit_code()`, which gives it its own, non-zero exit code
    (2) independent of `--fail-on`.

Nothing in this module touches a filesystem, a subprocess, or the network —
it is pure data, exactly like `cc.core.ecosystem.resolver`. Checks in other
layers build these records; this module never builds them itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class Layer(StrEnum):
    """The six harness layers, matching the `cc conformance check --layer`
    CLI surface exactly (`HARNESS-DESIGN.md` §6.1)."""

    TIER = "tier"
    STACK = "stack"
    REPO = "repo"
    LOCK = "lock"
    ROUNDTRIP = "roundtrip"
    REGRESSION = "regression"


class Mode(StrEnum):
    """Fast mode is local-only and cached; full mode adds network, `cc
    doctor`, `cc reconcile assess`, `fitness-check.sh`, and the round-trip
    (`HARNESS-DESIGN.md` §7.2)."""

    FAST = "fast"
    FULL = "full"


class Scope(StrEnum):
    """What one `CheckResult` is a claim about."""

    GLOBAL = "global"
    PER_TIER = "per-tier"
    PER_REPO = "per-repo"
    PER_CELL = "per-cell"


class Severity(StrEnum):
    """`RUBRIC.md` §4, reused verbatim (`HARNESS-DESIGN.md` §3.4). S0 is the
    most severe (systemic, no repair path); S3 is cosmetic. Severity is a
    property of the CHECK, declared once at registration — never computed
    per repo (`HARNESS-DESIGN.md` §3.4)."""

    S0 = "S0"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"


# Lower rank = more severe. Used by `--fail-on` threshold comparisons
# (`--fail-on S1` means "exit non-zero on any S0 or S1 failure").
SEVERITY_RANK: Mapping[Severity, int] = {
    Severity.S0: 0,
    Severity.S1: 1,
    Severity.S2: 2,
    Severity.S3: 3,
}


def severity_at_or_above(severity: Severity, threshold: Severity) -> bool:
    """True when `severity` is at least as severe as `threshold` (i.e. S0 is
    "at or above" every threshold; S3 is only "at or above" S3)."""

    return SEVERITY_RANK[severity] <= SEVERITY_RANK[threshold]


class Verdict(StrEnum):
    """Four verdicts, never three (`HARNESS-DESIGN.md` §3.2 rule 5).

    `SKIP` is the harness's own "not applicable" answer (e.g. D8 tier
    participation is `NA`/SKIP for class C/D/E repos by design, never
    silently omitted — `HARNESS-DESIGN.md` repo.d08.tier_participation).
    `COULD_NOT_RUN` is the harness's own "I don't know" answer (a crashed
    check, an unreadable repo, a malformed manifest) and is NEVER coerced
    into `PASS` — see `inv.no_fabricated_healthy` in the design's fitness
    function table (§13).
    """

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    COULD_NOT_RUN = "could-not-run"


# Verdicts that must never be reported as a passing result by any consumer.
NON_PASSING_VERDICTS = frozenset({Verdict.FAIL, Verdict.COULD_NOT_RUN})


class ExpectedToday(StrEnum):
    """Whether THIS check instance is expected to pass or fail on the
    machine as it stands today (`TEST-MATRIX.md`'s "Expected verdict TODAY"
    column). Distinct from `Verdict` — `expected_today` is a claim about
    what SHOULD happen; `verdict` is what actually happened. A check whose
    `verdict` disagrees with its `expected_today` is exactly the signal a
    committed baseline (`report.compare_to_baseline`) is built to catch."""

    PASS = "pass"
    FAIL = "fail"


class BareReadyError(ValueError):
    """Raised when rendered text contains the literal word "ready" with no
    qualifier. `cc workspace verify`'s `ready` classification is provably
    not a pass oracle (see `EXISTING-VERIFICATION.md` §2) — printing it bare
    inverts the real ranking. Enforced in `report.py`, defined here so both
    `types.py` consumers and `report.py` share one exception type."""


@dataclass(frozen=True)
class Evidence:
    """One concrete, specific fact backing a verdict.

    `kind`/`path` are always required. `expected`/`actual`/`detail` are
    free-text and may be empty for a PASS/SKIP entry that only needs to
    name what it looked at, but per Rule 3 a FAIL result's evidence must
    have a non-empty `path` (enforced in `CheckResult.__post_init__`, not
    here, because emptiness is only forbidden in the FAIL context).

    `command`/`output` are additive, optional fields for evidence sourced
    from a subprocess (e.g. a `git merge-base --is-ancestor` probe) — the
    literal command run and its captured output, so a failing check's
    evidence is independently reproducible by a human without re-running
    the harness.
    """

    kind: str
    path: str
    expected: str = ""
    actual: str = ""
    detail: str = ""
    command: str | None = None
    output: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
            "detail": self.detail,
        }
        if self.command is not None:
            result["command"] = self.command
        if self.output is not None:
            result["output"] = self.output
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Evidence":
        return cls(
            kind=str(data["kind"]),
            path=str(data["path"]),
            expected=str(data.get("expected", "")),
            actual=str(data.get("actual", "")),
            detail=str(data.get("detail", "")),
            command=data.get("command"),
            output=data.get("output"),
        )


@dataclass(frozen=True)
class CheckResult:
    """One test result: the outcome of running one check against one
    subject.

    Every field the engineering brief requires a "test result" to carry is
    present directly on this record (denormalized, not looked up through
    the registry at render time) so `report.py` can serialize a
    `CheckResult` on its own without a registry round-trip, and so a
    `CheckResult` captured into a baseline file is self-describing:
    stable `id`, `assertion` statement, `scope`, `subject`, `verdict`,
    `evidence`, `severity`, and `expected_today`.

    `root_cause` is optional: Layer 6 (regression pins) and any other check
    that maps onto a named root cause (RC-1..RC-7) sets it so `report.py`
    can group S0 failures BY CAUSE rather than by repo
    (`HARNESS-DESIGN.md` §11: "It does not open a ticket per repo for an
    S0 ... the report groups S0 failures by cause, not by repo.").
    """

    id: str
    layer: Layer
    severity: Severity
    scope: Scope
    subject: str
    assertion: str
    verdict: Verdict
    expected_today: ExpectedToday
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    detail: str = ""
    remediation: str = ""
    root_cause: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("CheckResult.id must be non-empty.")
        if not self.subject:
            raise ValueError(
                f"CheckResult {self.id!r} has an empty subject — every "
                "result must name what it is a claim about, even for "
                "global-scope checks (use the manifest/config path)."
            )
        if self.verdict is Verdict.FAIL and not self.evidence:
            raise ValueError(
                f"CheckResult {self.id!r} is FAIL with no evidence. "
                "'Failed' without a path and an actual value is a harness "
                "bug (HARNESS-DESIGN.md §3.2 rule 3) — attach at least one "
                "Evidence entry."
            )
        for entry in self.evidence:
            if not entry.path:
                raise ValueError(
                    f"CheckResult {self.id!r} has an Evidence entry with no "
                    "path — every failure's evidence must be a concrete, "
                    "specific path, never a bare assertion."
                )

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "layer": self.layer.value,
            "severity": self.severity.value,
            "scope": self.scope.value,
            "subject": self.subject,
            "assertion": self.assertion,
            "verdict": self.verdict.value,
            "expected_today": self.expected_today.value,
            "evidence": [entry.as_dict() for entry in self.evidence],
            "detail": self.detail,
            "remediation": self.remediation,
        }
        if self.root_cause is not None:
            result["root_cause"] = self.root_cause
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CheckResult":
        return cls(
            id=str(data["id"]),
            layer=Layer(data["layer"]),
            severity=Severity(data["severity"]),
            scope=Scope(data["scope"]),
            subject=str(data["subject"]),
            assertion=str(data.get("assertion", "")),
            verdict=Verdict(data["verdict"]),
            expected_today=ExpectedToday(data["expected_today"]),
            evidence=tuple(
                Evidence.from_dict(entry) for entry in data.get("evidence", [])
            ),
            detail=str(data.get("detail", "")),
            remediation=str(data.get("remediation", "")),
            root_cause=data.get("root_cause"),
        )


__all__ = [
    "BareReadyError",
    "CheckResult",
    "Evidence",
    "ExpectedToday",
    "Layer",
    "Mode",
    "NON_PASSING_VERDICTS",
    "Scope",
    "SEVERITY_RANK",
    "Severity",
    "Verdict",
    "severity_at_or_above",
]
