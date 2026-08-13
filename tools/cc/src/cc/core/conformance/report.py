"""Human output and `--json` output for `cc conformance check|report`.

Two refusals are load-bearing (`HARNESS-DESIGN.md` §3.2 rule 4 and §6.2):
never roll results up to a single percentage/score, and never print the
word "ready" without its "(by waiver, N files)"-shaped qualifier (`cc
workspace verify`'s `ready` is not a pass oracle -- see
`EXISTING-VERIFICATION.md` §2). Both are enforced here, not merely
documented: `render_human`/`to_envelope` scan every string they are about
to emit and raise rather than print a violation.

This module also owns process exit-code computation
(`HARNESS-DESIGN.md` §6.4):

    0  conforms at the requested --fail-on threshold
    1  a check at or above the threshold failed
    2  the harness could not run at least one selected check (COULD_NOT_RUN)
    3  a --baseline comparison found something that PASSED before and now FAILS

Precedence when more than one condition applies in the same run: a baseline
regression (3) is checked first (it is the sharpest signal -- something
that used to be fine got worse, independent of severity threshold), then
COULD_NOT_RUN (2, since "we could not tell" must never be silently masked
by an unrelated FAIL elsewhere), then FAIL (1). The design spec does not
spell out this precedence for combined conditions; this ordering is this
module's own documented decision, not inferred from an explicit rule.
"""

from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from cc.core.conformance.types import (
    BareReadyError,
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
    Verdict,
    severity_at_or_above,
)

SCHEMA_VERSION = "1.0"
CONTRACT_ID = "ecosystem-conformance"
CONTRACT_VERSION = "1"

_ROUNDTRIP_SCRATCH_SUBJECT = re.compile(
    r"^.*/cc-conformance-roundtrip-[^/]+/project(?P<suffix>(?:::.+)?)$"
)

# These tier checks inspect the framework checkout itself.  An installed
# immutable snapshot has a different checkout prefix from the authoring tree,
# but the inspected framework facet is the same baseline subject.  Keep this
# list deliberately check-specific: ordinary repo subjects must remain exact.
_FRAMEWORK_FACET_SUBJECTS: Mapping[str, tuple[str, ...]] = {
    "tier.precedence.commands_dimension_has_no_consumer": (
        "tools/cc/src/cc/commands",
        "tools/cc/src/cc/core/ecosystem",
    ),
    "tier.effectiveness.extension_resolution_wired_beyond_prose": (
        ".claude",
        "plugins",
        "scripts",
    ),
}

NO_AVERAGING_NOTE = (
    "Counts are not averaged. S0 and S3 are not commensurable "
    "(RUBRIC.md section 4) -- there is no aggregate score."
)

# Matches a bare "ready" -- i.e. NOT immediately followed by an opening
# paren (the qualifier shape "ready (by waiver, N files)") and not part of
# a longer word ("already", "readystate"). Case-sensitive on purpose: this
# guards the literal status WORD, not incidental prose.
_BARE_READY_PATTERN = re.compile(r"(?<![\w(])ready\b(?!\s*\()")


def assert_no_bare_ready(*texts: str) -> None:
    """Raise `BareReadyError` if any of `texts` contains the word "ready"
    without an immediately-following `(...)` qualifier. Applied to every
    string this module is about to render or serialize."""

    for text in texts:
        if _BARE_READY_PATTERN.search(text):
            raise BareReadyError(
                f"refusing to print a bare 'ready': {text!r}. "
                "cc workspace verify's `ready` classification is not a pass "
                "oracle (EXISTING-VERIFICATION.md section 2) -- always "
                "qualify it, e.g. 'ready (by waiver, N files)'."
            )


def _assert_result_texts_are_safe(result: CheckResult) -> None:
    assert_no_bare_ready(
        result.subject, result.assertion, result.detail, result.remediation
    )
    for entry in result.evidence:
        assert_no_bare_ready(entry.expected, entry.actual, entry.detail)


# ---------------------------------------------------------------------------
# Filtering (post-hoc, over already-computed CheckResults)
# ---------------------------------------------------------------------------


def filter_by_repo(
    results: Sequence[CheckResult], repos: Iterable[str | Path]
) -> tuple[CheckResult, ...]:
    """`--repo PATH` — keep only results whose `subject` names one of
    `repos` (matched as a path suffix, so both an absolute and a
    repo-relative caller spelling work)."""

    wanted = [str(repo) for repo in repos]
    if not wanted:
        return tuple(results)
    return tuple(
        result
        for result in results
        if result.scope is Scope.GLOBAL
        or any(
            result.subject == repo or result.subject.endswith(f"/{Path(repo).name}")
            for repo in wanted
        )
    )


def deduplicate_global_results(
    results: Sequence[CheckResult],
) -> tuple[CheckResult, ...]:
    """Emit each global ``(id, subject)`` claim once.

    Dimension modules run once per repo by contract, so a global check can
    arrive many times.  Byte-for-byte equivalent results collapse to their
    first occurrence.  Conflicting duplicates are *not* guessed away: they
    collapse to one attributable ``COULD_NOT_RUN`` result naming the stale
    cache/check-wiring prerequisite and its owning actor.
    """

    output: list[CheckResult] = []
    index_by_key: dict[tuple[str, str], int] = {}
    for result in results:
        if result.scope is not Scope.GLOBAL:
            output.append(result)
            continue
        key = (result.id, result.subject)
        prior_index = index_by_key.get(key)
        if prior_index is None:
            index_by_key[key] = len(output)
            output.append(result)
            continue
        prior = output[prior_index]
        if prior == result:
            continue
        output[prior_index] = replace(
            prior,
            verdict=Verdict.COULD_NOT_RUN,
            expected_today=ExpectedToday.PASS,
            evidence=(
                Evidence(
                    kind="global-result-conflict",
                    path=result.subject,
                    expected="one stable machine-wide verdict for this check",
                    actual=(
                        f"conflicting duplicates: {prior.verdict.value} and "
                        f"{result.verdict.value}"
                    ),
                    detail=(
                        "missing prerequisite: consistent uncached global input; "
                        "owning actor: conformance harness maintainer"
                    ),
                ),
            ),
            detail=(
                "Global check instances disagreed. Missing prerequisite: "
                "consistent uncached global input. Owning actor: conformance "
                "harness maintainer."
            ),
            remediation=(
                "Invalidate the conformance cache, then inspect why this global "
                "check depends on per-repo execution state."
            ),
        )
    return tuple(output)


_COULD_NOT_RUN_PREREQUISITES: Mapping[Layer, tuple[str, str]] = {
    Layer.TIER: (
        "a readable layer manifest, knowledge ladder, and tier source material",
        "ecosystem configuration owner",
    ),
    Layer.STACK: (
        "a readable layer manifest and locally resolvable source/ref evidence",
        "layer source owner",
    ),
    Layer.REPO: (
        "a readable project plus an executable conformance dimension",
        "project owner or conformance harness maintainer",
    ),
    Layer.LOCK: (
        "a readable, supported lock whose recorded files can be inspected",
        "project installer owner",
    ),
    Layer.ROUNDTRIP: (
        "the framework source, cc binary, installer adapters, and scratch git tools",
        "cc framework maintainer",
    ),
    Layer.REGRESSION: (
        "the configured layer sources and fleet evidence required by the regression pin",
        "ecosystem operator",
    ),
}


def attribute_could_not_run_results(
    results: Sequence[CheckResult],
) -> tuple[CheckResult, ...]:
    """Attach an explicit prerequisite and owning actor to every unknown.

    Existing check-specific evidence is preserved.  This normalizer is the
    CLI boundary, so older checks that only said "could not run" still become
    actionable without being coerced to PASS or FAIL.
    """

    attributed: list[CheckResult] = []
    for result in results:
        if result.verdict is not Verdict.COULD_NOT_RUN:
            attributed.append(result)
            continue
        prerequisite, owner = _COULD_NOT_RUN_PREREQUISITES[result.layer]
        if any(entry.kind == "could-not-run-attribution" for entry in result.evidence):
            attributed.append(result)
            continue
        context = result.detail.strip()
        detail = (
            f"{context.rstrip('.')} " if context else ""
        ) + f"Missing prerequisite: {prerequisite}. Owning actor: {owner}."
        attributed.append(
            replace(
                result,
                evidence=(
                    *result.evidence,
                    Evidence(
                        kind="could-not-run-attribution",
                        path=result.subject,
                        expected=prerequisite,
                        actual="not established",
                        detail=f"owning_actor={owner}",
                    ),
                ),
                detail=detail,
            )
        )
    return tuple(attributed)


def filter_by_severity_threshold(
    results: Sequence[CheckResult], fail_on: Severity
) -> tuple[CheckResult, ...]:
    """`--fail-on S1` — keep only results at or above the given severity."""

    return tuple(
        result for result in results if severity_at_or_above(result.severity, fail_on)
    )


def group_by_root_cause(
    results: Sequence[CheckResult],
) -> dict[str, tuple[CheckResult, ...]]:
    """Group FAILing results by `root_cause` (falling back to the check
    `id` when no root cause is attached) so an S0 that fails identically
    across N repos is reported once, by cause -- never opened as N
    per-repo tickets (`HARNESS-DESIGN.md` §11)."""

    groups: dict[str, list[CheckResult]] = {}
    for result in results:
        if result.verdict is not Verdict.FAIL:
            continue
        key = result.root_cause or result.id
        groups.setdefault(key, []).append(result)
    return {key: tuple(value) for key, value in groups.items()}


# ---------------------------------------------------------------------------
# Summary (counts only -- never an average)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Summary:
    by_severity: Mapping[str, int]
    by_layer: Mapping[str, Mapping[str, int]]
    could_not_run_total: int
    note: str = NO_AVERAGING_NOTE

    def as_dict(self) -> dict[str, Any]:
        return {
            "by_severity": dict(self.by_severity),
            "by_layer": {
                layer: dict(counts) for layer, counts in self.by_layer.items()
            },
            "could_not_run_total": self.could_not_run_total,
            "note": self.note,
        }


def summarize(results: Sequence[CheckResult]) -> Summary:
    by_severity: dict[str, int] = {severity.value: 0 for severity in Severity}
    by_layer: dict[str, dict[str, int]] = {
        layer.value: {"pass": 0, "fail": 0, "skip": 0, "could_not_run": 0}
        for layer in Layer
    }
    could_not_run_total = 0

    for result in results:
        layer_counts = by_layer[result.layer.value]
        if result.verdict is Verdict.PASS:
            layer_counts["pass"] += 1
        elif result.verdict is Verdict.FAIL:
            layer_counts["fail"] += 1
            by_severity[result.severity.value] += 1
        elif result.verdict is Verdict.SKIP:
            layer_counts["skip"] += 1
        elif result.verdict is Verdict.COULD_NOT_RUN:
            layer_counts["could_not_run"] += 1
            could_not_run_total += 1

    return Summary(
        by_severity=by_severity,
        by_layer=by_layer,
        could_not_run_total=could_not_run_total,
    )


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaselineEntry:
    id: str
    subject: str
    verdict: Verdict

    def key(self) -> tuple[str, str]:
        return (self.id, baseline_subject(self.id, self.subject))

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "subject": self.subject, "verdict": self.verdict.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BaselineEntry":
        return cls(
            id=str(data["id"]),
            subject=str(data["subject"]),
            verdict=Verdict(data["verdict"]),
        )


def load_baseline(path: Path) -> tuple[BaselineEntry, ...]:
    """Load a baseline file: `{"generated_at": "...", "entries": [{"id",
    "subject", "verdict"}, ...]}`. WP-9 owns producing this file's content
    (`cc conformance baseline write`); this loader is the shared reader
    every consumer (`check --baseline`, `report --baseline`) uses."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    entries_raw = raw.get("entries", []) if isinstance(raw, dict) else []
    return tuple(BaselineEntry.from_dict(entry) for entry in entries_raw)


def baseline_subject(check_id: str, subject: str) -> str:
    """Return the stable identity used for baseline comparisons.

    Round-trip checks deliberately run under a fresh random temporary
    directory.  Persisting that directory name would make every healthy run
    look like an unrelated new check.  Only that known scratch prefix is
    normalized.  The two framework-internal tier checks also use a stable
    facet identity so the authoring checkout and an immutable installed
    snapshot compare as the same subject.  All other repository subjects and
    facet suffixes remain exact.
    """

    if check_id.startswith("roundtrip."):
        match = _ROUNDTRIP_SCRATCH_SUBJECT.fullmatch(subject)
        if match:
            return "roundtrip:canonical-scratch-project" + (
                match.group("suffix") or ""
            )
    for facet in _FRAMEWORK_FACET_SUBJECTS.get(check_id, ()):
        if subject == facet or subject.endswith(f"/{facet}"):
            return f"framework:{facet}"
    return subject


@dataclass(frozen=True)
class BaselineComparison:
    file: str
    fixed: tuple[CheckResult, ...]
    still_failing: tuple[CheckResult, ...]
    regressed: tuple[CheckResult, ...]
    new_failures: tuple[CheckResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "fixed": len(self.fixed),
            "still_failing": len(self.still_failing),
            "regressed": len(self.regressed),
            "new_failures": len(self.new_failures),
        }

    @property
    def has_regression(self) -> bool:
        """True iff something that PASSED in the baseline now FAILS --
        the exact, sole trigger for exit code 3."""

        return bool(self.regressed)


def compare_to_baseline(
    results: Sequence[CheckResult],
    baseline: Sequence[BaselineEntry],
    *,
    file: str = "",
) -> BaselineComparison:
    baseline_by_key: dict[tuple[str, str], Verdict] = {
        entry.key(): entry.verdict for entry in baseline
    }

    fixed: list[CheckResult] = []
    still_failing: list[CheckResult] = []
    regressed: list[CheckResult] = []
    new_failures: list[CheckResult] = []

    for result in results:
        key = (result.id, baseline_subject(result.id, result.subject))
        baseline_verdict = baseline_by_key.get(key)
        if baseline_verdict is None:
            if result.verdict is Verdict.FAIL:
                new_failures.append(result)
            continue
        if baseline_verdict is Verdict.FAIL and result.verdict is Verdict.PASS:
            fixed.append(result)
        elif baseline_verdict is Verdict.FAIL and result.verdict is Verdict.FAIL:
            still_failing.append(result)
        elif baseline_verdict is Verdict.PASS and result.verdict is Verdict.FAIL:
            regressed.append(result)

    return BaselineComparison(
        file=file,
        fixed=tuple(fixed),
        still_failing=tuple(still_failing),
        regressed=tuple(regressed),
        new_failures=tuple(new_failures),
    )


# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------


def compute_exit_code(
    results: Sequence[CheckResult],
    *,
    fail_on: Severity = Severity.S3,
    baseline: BaselineComparison | None = None,
) -> int:
    if baseline is not None and baseline.has_regression:
        return 3
    if any(result.verdict is Verdict.COULD_NOT_RUN for result in results):
        return 2
    thresholded = filter_by_severity_threshold(results, fail_on)
    if any(result.verdict is Verdict.FAIL for result in thresholded):
        return 1
    return 0


# ---------------------------------------------------------------------------
# JSON envelope
# ---------------------------------------------------------------------------


def to_envelope(
    results: Sequence[CheckResult],
    *,
    mode: Mode,
    generated_at: datetime | None = None,
    host: str | None = None,
    baseline: BaselineComparison | None = None,
) -> dict[str, Any]:
    """Build the full `conformance.schema.json`-validated payload."""

    for result in results:
        _assert_result_texts_are_safe(result)

    summary = summarize(results)
    overall_pass = (
        compute_exit_code(results, fail_on=Severity.S3, baseline=baseline) == 0
    )

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "generated_at": (generated_at or datetime.now(timezone.utc)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "host": host or socket.gethostname(),
        "mode": mode.value,
        "result": "pass" if overall_pass else "fail",
        "checks": [result.as_dict() for result in results],
        "summary": summary.as_dict(),
    }
    if baseline is not None:
        envelope["baseline"] = baseline.as_dict()
    return envelope


# ---------------------------------------------------------------------------
# Human output
# ---------------------------------------------------------------------------

_LAYER_TITLES: Mapping[Layer, str] = {
    Layer.TIER: "tier resolution",
    Layer.STACK: "component stack",
    Layer.REPO: "install conformance",
    Layer.LOCK: "lock integrity",
    Layer.ROUNDTRIP: "round-trip",
    Layer.REGRESSION: "root-cause regression",
}


def render_human(
    results: Sequence[CheckResult],
    *,
    mode: Mode,
    generated_at: datetime | None = None,
    fail_on: Severity = Severity.S3,
    baseline: BaselineComparison | None = None,
) -> str:
    """Human-readable report. Never prints a percentage (no `%` character
    appears anywhere in this function's output) and never prints a bare
    'ready' (`assert_no_bare_ready` runs over every rendered line)."""

    for result in results:
        _assert_result_texts_are_safe(result)

    timestamp = (generated_at or datetime.now(timezone.utc)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    repos = {result.subject for result in results}
    lines: list[str] = [
        f"Copilot Ecosystem Conformance -- {mode.value} -- "
        f"{len(repos)} subject(s) -- {timestamp}",
        "",
    ]

    by_layer: dict[Layer, list[CheckResult]] = {layer: [] for layer in Layer}
    for result in results:
        by_layer[result.layer].append(result)

    for layer in Layer:
        layer_results = by_layer[layer]
        if not layer_results:
            continue
        passed = sum(1 for r in layer_results if r.verdict is Verdict.PASS)
        failed = sum(1 for r in layer_results if r.verdict is Verdict.FAIL)
        lines.append(
            f"LAYER  {layer.value:<10} {_LAYER_TITLES[layer]:<30} "
            f"{len(layer_results):>4} checks  {passed:>4} pass  {failed:>4} FAIL"
        )
        for result in layer_results:
            if result.verdict is not Verdict.FAIL:
                continue
            lines.append(
                f"  FAIL  {result.severity.value}  {result.id}  ({result.subject})"
            )
            if result.detail:
                lines.append(f"            {result.detail}")
            for entry in result.evidence:
                detail = f"expected={entry.expected!r} actual={entry.actual!r}"
                lines.append(f"            {entry.path}  {detail}")
                if entry.detail:
                    lines.append(f"            {entry.detail}")
            if result.remediation:
                lines.append(f"            fix  {result.remediation}")
        lines.append("")

    summary = summarize(results)
    lines.append(
        "SEVERITY ROLL-UP  (never averaged -- S0 and S3 are not commensurable)"
    )
    for severity in Severity:
        count = summary.by_severity[severity.value]
        lines.append(f"  {severity.value}  {count} check(s) failing")
    lines.append("")

    if summary.could_not_run_total:
        lines.append(
            f"COULD-NOT-RUN  {summary.could_not_run_total} check(s) -- "
            "the harness could not determine an answer; this is NOT a pass."
        )

    if baseline is not None:
        lines.append(
            f"BASELINE  {baseline.file}    fixed {len(baseline.fixed)}    "
            f"still-failing {len(baseline.still_failing)}    "
            f"NEW {len(baseline.new_failures)}    "
            f"regressed {len(baseline.regressed)}"
        )

    exit_code = compute_exit_code(results, fail_on=fail_on, baseline=baseline)
    result_word = "pass" if exit_code == 0 else "fail"
    lines.append(
        f"RESULT    {result_word} (--fail-on {fail_on.value})    exit {exit_code}"
    )

    text = "\n".join(lines)
    assert_no_bare_ready(text)
    if "%" in text:
        raise AssertionError(
            "render_human() produced a '%' character -- the harness must "
            "never compute or print an aggregate percentage "
            "(HARNESS-DESIGN.md section 3.2 rule 4)."
        )
    return text


__all__ = [
    "BaselineComparison",
    "BaselineEntry",
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "NO_AVERAGING_NOTE",
    "SCHEMA_VERSION",
    "Summary",
    "assert_no_bare_ready",
    "baseline_subject",
    "compare_to_baseline",
    "compute_exit_code",
    "deduplicate_global_results",
    "filter_by_repo",
    "filter_by_severity_threshold",
    "group_by_root_cause",
    "attribute_could_not_run_results",
    "load_baseline",
    "render_human",
    "summarize",
    "to_envelope",
]
