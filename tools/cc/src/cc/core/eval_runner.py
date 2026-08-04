"""cc eval — pure-Python pluggable eval runner.

Architecture
------------
- Runner is a Protocol (structural typing).
- LocalPythonRunner: deterministic assertion engine. No LLM calls. No Node dep.
- Pluggable: a promptfoo adapter can be added later by implementing the same
  Runner protocol and passing it to run_eval().

Assertion types (LocalPythonRunner)
------------------------------------
  contains       — source content includes the value string (case-sensitive)
  not-contains   — source content does NOT include the value string
  regex          — source content matches the regex pattern
  file-contains  — alias for contains (explicit intent marker for structural cases)
  file-regex     — alias for regex   (explicit intent marker for structural cases)

Source types
------------
  inline         — content is embedded in the case YAML
  file           — content is read from the given path (relative to repo_root)

YAML case format
----------------
  id:          qa-struct-001          # unique across the agent's set
  name:        "Short human label"
  priority:    P0                     # P0 = blocks on regression; P1 = warning only
  description: |                      # optional prose
    ...
  type:        structural             # structural | behavioral (informational only)
  source:
    type:      file                   # file | inline
    path:      ".claude/agents/qa.md" # only for type: file (relative to repo_root)
    content:   |                      # only for type: inline
      ...
  assertions:
    - type:        contains
      value:       "ARTIFACT:"
      description: "Brief human label"
    - type:        regex
      pattern:     "VERDICT: (APPROVED|REJECTED)"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class AssertionResult:
    """Result of a single assertion within a case."""

    passed: bool
    assertion_type: str
    description: str
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "assertion_type": self.assertion_type,
            "description": self.description,
            "error": self.error,
        }


@dataclass
class CaseResult:
    """Result of a single eval case."""

    case_id: str
    name: str
    priority: str
    passed: bool
    assertions: list[AssertionResult] = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "name": self.name,
            "priority": self.priority,
            "passed": self.passed,
            "assertions": [a.as_dict() for a in self.assertions],
            "error": self.error,
        }


@dataclass
class EvalResult:
    """Aggregated result of running all cases for an agent."""

    agent: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    p0_regression: bool
    cases: list[CaseResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "p0_regression": self.p0_regression,
            "cases": [c.as_dict() for c in self.cases],
        }


# ---------------------------------------------------------------------------
# Runner protocol — pluggable seam
# ---------------------------------------------------------------------------


@runtime_checkable
class Runner(Protocol):
    """Pluggable runner interface.

    Any object that implements ``run()`` satisfies this protocol.
    The default implementation is ``LocalPythonRunner``.
    A promptfoo adapter can be added later without changing the
    caller (``run_eval``).
    """

    def run(
        self,
        agent: str,
        cases: list[dict[str, Any]],
        *,
        repo_root: Path,
    ) -> EvalResult: ...


# ---------------------------------------------------------------------------
# LocalPythonRunner — default, zero-dep deterministic engine
# ---------------------------------------------------------------------------


class LocalPythonRunner:
    """Pure-Python deterministic assertion runner.

    Runs deterministic assertions (contains, not-contains, regex) against
    source content.  No LLM calls.  No Node.js dependency.  Intended as the
    always-on baseline; an LLM-judge adapter can be layered on top later.
    """

    # --- public API ---------------------------------------------------------

    def run(
        self,
        agent: str,
        cases: list[dict[str, Any]],
        *,
        repo_root: Path,
    ) -> EvalResult:
        """Run all cases and return an aggregate EvalResult."""
        case_results: list[CaseResult] = []

        for case in cases:
            result = self._run_case(case, repo_root=repo_root)
            case_results.append(result)

        total = len(case_results)
        passed_count = sum(1 for c in case_results if c.passed)
        failed_count = total - passed_count
        pass_rate = passed_count / total if total > 0 else 1.0

        p0_regression = any(
            not c.passed and c.priority.upper() == "P0" for c in case_results
        )

        return EvalResult(
            agent=agent,
            total=total,
            passed=passed_count,
            failed=failed_count,
            pass_rate=pass_rate,
            p0_regression=p0_regression,
            cases=case_results,
        )

    # --- private helpers ----------------------------------------------------

    def _load_source(self, source: dict[str, Any], repo_root: Path) -> str:
        """Return the text content for a case source spec."""
        source_type = source.get("type", "inline")

        if source_type == "file":
            raw_path = source.get("path")
            if not raw_path:
                raise ValueError("source.type=file requires a 'path' key")
            resolved = repo_root / raw_path
            if not resolved.exists():
                raise FileNotFoundError(
                    f"Source file not found: {resolved} "
                    f"(resolved from path={raw_path!r}, repo_root={repo_root})"
                )
            return resolved.read_text(encoding="utf-8")

        elif source_type == "inline":
            return source.get("content", "")

        else:
            raise ValueError(
                f"Unknown source type {source_type!r}. Must be 'file' or 'inline'."
            )

    def _run_assertion(
        self, content: str, assertion: dict[str, Any]
    ) -> AssertionResult:
        """Evaluate a single assertion dict against content."""
        raw_type = assertion.get("type", "contains")
        description = str(assertion.get("description", assertion.get("value", assertion.get("pattern", ""))))

        # Normalize file-* aliases → base type
        atype = raw_type
        if atype == "file-contains":
            atype = "contains"
        elif atype == "file-regex":
            atype = "regex"

        if atype == "contains":
            value = str(assertion.get("value", ""))
            passed = value in content
            return AssertionResult(
                passed=passed,
                assertion_type=atype,
                description=description,
                error=(
                    "" if passed else f"Expected to find {value!r} in content but it was absent"
                ),
            )

        elif atype == "not-contains":
            value = str(assertion.get("value", ""))
            passed = value not in content
            return AssertionResult(
                passed=passed,
                assertion_type=atype,
                description=description,
                error=(
                    "" if passed else f"Expected {value!r} to be absent but it was found in content"
                ),
            )

        elif atype == "regex":
            pattern = str(assertion.get("pattern", ""))
            try:
                compiled = re.compile(pattern, re.DOTALL)
            except re.error as exc:
                return AssertionResult(
                    passed=False,
                    assertion_type=atype,
                    description=description,
                    error=f"Invalid regex pattern {pattern!r}: {exc}",
                )
            passed = bool(compiled.search(content))
            return AssertionResult(
                passed=passed,
                assertion_type=atype,
                description=description,
                error=(
                    "" if passed else f"Pattern {pattern!r} did not match content"
                ),
            )

        elif atype == "regex-not":
            pattern = str(assertion.get("pattern", ""))
            try:
                compiled = re.compile(pattern, re.DOTALL)
            except re.error as exc:
                return AssertionResult(
                    passed=False,
                    assertion_type=atype,
                    description=description,
                    error=f"Invalid regex pattern {pattern!r}: {exc}",
                )
            passed = not bool(compiled.search(content))
            return AssertionResult(
                passed=passed,
                assertion_type=atype,
                description=description,
                error=(
                    "" if passed else f"Pattern {pattern!r} matched but was expected to be absent"
                ),
            )

        else:
            return AssertionResult(
                passed=False,
                assertion_type=atype,
                description=description,
                error=f"Unknown assertion type {atype!r}",
            )

    def _run_case(self, case: dict[str, Any], repo_root: Path) -> CaseResult:
        """Run all assertions for a single case."""
        case_id = str(case.get("id", "unknown"))
        name = str(case.get("name", case_id))
        priority = str(case.get("priority", "P1")).upper()

        # Load source content
        source_spec = case.get("source", {"type": "inline", "content": ""})
        try:
            content = self._load_source(source_spec, repo_root=repo_root)
        except Exception as exc:
            return CaseResult(
                case_id=case_id,
                name=name,
                priority=priority,
                passed=False,
                error=f"Failed to load source: {exc}",
            )

        # Run assertions
        assertion_results: list[AssertionResult] = []
        for assertion in case.get("assertions", []):
            result = self._run_assertion(content, assertion)
            assertion_results.append(result)

        all_passed = all(r.passed for r in assertion_results) if assertion_results else True

        return CaseResult(
            case_id=case_id,
            name=name,
            priority=priority,
            passed=all_passed,
            assertions=assertion_results,
        )


# ---------------------------------------------------------------------------
# Case loader
# ---------------------------------------------------------------------------


def load_cases(evals_dir: Path, agent: str) -> list[dict[str, Any]]:
    """Load all YAML case files for an agent from ``<evals_dir>/<agent>/``.

    Returns a list of case dicts, sorted by filename (stable order).
    Raises ``FileNotFoundError`` if the agent directory does not exist.
    """
    try:
        import yaml as _yaml  # pyyaml is a declared dependency
    except ImportError as exc:
        raise ImportError(
            "pyyaml is required for cc eval. Install with: pip install pyyaml"
        ) from exc

    agent_dir = evals_dir / agent
    if not agent_dir.exists():
        raise FileNotFoundError(
            f"No eval cases found for agent {agent!r}. "
            f"Expected directory: {agent_dir}"
        )

    cases: list[dict[str, Any]] = []
    for yaml_file in sorted(agent_dir.glob("*.yaml")):
        try:
            with open(yaml_file, encoding="utf-8") as fh:
                case = _yaml.safe_load(fh)
            if case and isinstance(case, dict):
                cases.append(case)
        except Exception as exc:
            # Non-fatal: report but continue so one bad file doesn't abort the run
            import warnings
            warnings.warn(f"Skipping {yaml_file.name}: {exc}", stacklevel=2)

    return cases


# ---------------------------------------------------------------------------
# Top-level convenience function
# ---------------------------------------------------------------------------


def run_eval(
    agent: str,
    *,
    evals_dir: Path,
    repo_root: Path,
    runner: Runner | None = None,
) -> EvalResult:
    """Load cases and run them through the runner.

    Args:
        agent:      Agent name (e.g. "qa").
        evals_dir:  Path to the ``.claude/evals`` directory.
        repo_root:  Repository root (used to resolve relative file paths).
        runner:     Pluggable runner. Defaults to ``LocalPythonRunner()``.

    Returns:
        ``EvalResult`` with per-case results and aggregate statistics.
    """
    if runner is None:
        runner = LocalPythonRunner()

    cases = load_cases(evals_dir, agent)
    return runner.run(agent, cases, repo_root=repo_root)
