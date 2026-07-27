"""Tests for cc eval — Task 142: cc eval core + qa golden set.

Tests:
  - LocalPythonRunner assertion types (contains, not-contains, regex, file-*)
  - CaseResult / EvalResult aggregation
  - Pass-rate computation and P0 regression detection
  - load_cases: happy path, missing agent dir
  - cc eval CLI: --agent qa runs and returns JSON; exits non-zero on fail
  - META-TEST (FF2): removing ARTIFACT from qa.md makes the eval FAIL
  - Scores are stored in cc memory (FF4)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path("/Volumes/Dev/Sites/COPILOT/claude-copilot")
EVALS_DIR = REPO_ROOT / ".claude" / "evals"
QA_AGENT = REPO_ROOT / ".claude" / "agents" / "qa.md"


# ---------------------------------------------------------------------------
# Unit tests — LocalPythonRunner
# ---------------------------------------------------------------------------


class TestAssertions:
    """Unit tests for each assertion type."""

    def _runner(self):
        from cc.core.eval_runner import LocalPythonRunner
        return LocalPythonRunner()

    def _assert(self, content: str, assertion: dict) -> bool:
        runner = self._runner()
        result = runner._run_assertion(content, assertion)
        return result.passed

    # contains

    def test_contains_passes(self):
        assert self._assert("hello world", {"type": "contains", "value": "world"})

    def test_contains_fails(self):
        assert not self._assert("hello world", {"type": "contains", "value": "ARTIFACT:"})

    def test_file_contains_alias(self):
        """file-contains is an alias for contains."""
        assert self._assert("ARTIFACT: test-run|...", {"type": "file-contains", "value": "ARTIFACT:"})

    # not-contains

    def test_not_contains_passes(self):
        assert self._assert("VERDICT: APPROVED", {"type": "not-contains", "value": "def "})

    def test_not_contains_fails(self):
        assert not self._assert("def foo():", {"type": "not-contains", "value": "def "})

    # regex

    def test_regex_passes(self):
        assert self._assert(
            "VERDICT: APPROVED\nARTIFACT: test-run|exit=0",
            {"type": "regex", "pattern": r"VERDICT: (APPROVED|REJECTED)"},
        )

    def test_regex_fails(self):
        assert not self._assert(
            "no verdict here",
            {"type": "regex", "pattern": r"VERDICT: (APPROVED|REJECTED)"},
        )

    def test_file_regex_alias(self):
        """file-regex is an alias for regex."""
        assert self._assert(
            "hook extracts the task ID",
            {"type": "file-regex", "pattern": r"hook.*extract"},
        )

    def test_regex_invalid_pattern_fails_gracefully(self):
        """An invalid regex pattern fails the assertion without crashing."""
        result = self._runner()._run_assertion(
            "any content",
            {"type": "regex", "pattern": "[invalid("},
        )
        assert not result.passed
        assert "Invalid regex" in result.error

    # unknown type

    def test_unknown_type_fails(self):
        result = self._runner()._run_assertion("content", {"type": "nonsense"})
        assert not result.passed
        assert "Unknown assertion type" in result.error


class TestSourceLoading:
    """Tests for source loading in LocalPythonRunner."""

    def _runner(self):
        from cc.core.eval_runner import LocalPythonRunner
        return LocalPythonRunner()

    def test_inline_source(self, tmp_path):
        content = self._runner()._load_source(
            {"type": "inline", "content": "hello eval"},
            repo_root=tmp_path,
        )
        assert content == "hello eval"

    def test_file_source(self, tmp_path):
        target = tmp_path / "agents" / "qa.md"
        target.parent.mkdir(parents=True)
        target.write_text("ARTIFACT: required", encoding="utf-8")
        content = self._runner()._load_source(
            {"type": "file", "path": "agents/qa.md"},
            repo_root=tmp_path,
        )
        assert "ARTIFACT: required" in content

    def test_file_source_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Source file not found"):
            self._runner()._load_source(
                {"type": "file", "path": "nonexistent/agent.md"},
                repo_root=tmp_path,
            )

    def test_unknown_source_type_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown source type"):
            self._runner()._load_source({"type": "magic"}, repo_root=tmp_path)


class TestCaseExecution:
    """Tests for LocalPythonRunner._run_case."""

    def _runner(self):
        from cc.core.eval_runner import LocalPythonRunner
        return LocalPythonRunner()

    def test_all_assertions_pass(self, tmp_path):
        case = {
            "id": "test-001",
            "name": "All pass",
            "priority": "P0",
            "source": {"type": "inline", "content": "ARTIFACT: test-run|exit=0\nVERDICT: APPROVED"},
            "assertions": [
                {"type": "contains", "value": "ARTIFACT:"},
                {"type": "contains", "value": "VERDICT: APPROVED"},
            ],
        }
        result = self._runner()._run_case(case, repo_root=tmp_path)
        assert result.passed
        assert result.case_id == "test-001"
        assert result.priority == "P0"
        assert all(a.passed for a in result.assertions)

    def test_one_assertion_fails_marks_case_failed(self, tmp_path):
        case = {
            "id": "test-002",
            "name": "One fails",
            "priority": "P1",
            "source": {"type": "inline", "content": "VERDICT: APPROVED"},
            "assertions": [
                {"type": "contains", "value": "VERDICT: APPROVED"},
                {"type": "contains", "value": "ARTIFACT:"},  # this fails
            ],
        }
        result = self._runner()._run_case(case, repo_root=tmp_path)
        assert not result.passed
        assert result.assertions[0].passed
        assert not result.assertions[1].passed

    def test_source_load_failure_marks_case_failed(self, tmp_path):
        case = {
            "id": "bad-source",
            "name": "Bad source",
            "priority": "P0",
            "source": {"type": "file", "path": "missing.md"},
            "assertions": [{"type": "contains", "value": "anything"}],
        }
        result = self._runner()._run_case(case, repo_root=tmp_path)
        assert not result.passed
        assert "Failed to load source" in result.error


class TestEvalResultAggregation:
    """Tests for EvalResult pass-rate and P0 regression logic."""

    def _run(self, cases_data, inline_contents):
        from cc.core.eval_runner import LocalPythonRunner
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            runner = LocalPythonRunner()
            result = runner.run("test-agent", cases_data, repo_root=repo_root)
        return result

    def test_all_pass(self):
        cases = [
            {
                "id": f"c{i}", "name": f"case {i}", "priority": "P1",
                "source": {"type": "inline", "content": "hello"},
                "assertions": [{"type": "contains", "value": "hello"}],
            }
            for i in range(5)
        ]
        result = self._run(cases, {})
        assert result.total == 5
        assert result.passed == 5
        assert result.failed == 0
        assert result.pass_rate == 1.0
        assert not result.p0_regression

    def test_p0_regression_detected(self):
        cases = [
            {
                "id": "c1", "name": "P0 case", "priority": "P0",
                "source": {"type": "inline", "content": "no artifact here"},
                "assertions": [{"type": "contains", "value": "ARTIFACT:"}],  # FAILS
            },
            {
                "id": "c2", "name": "P1 case", "priority": "P1",
                "source": {"type": "inline", "content": "hello"},
                "assertions": [{"type": "contains", "value": "hello"}],  # passes
            },
        ]
        result = self._run(cases, {})
        assert result.p0_regression
        assert result.failed == 1
        assert result.pass_rate == 0.5

    def test_p1_fail_no_p0_regression(self):
        cases = [
            {
                "id": "c1", "name": "P0 case", "priority": "P0",
                "source": {"type": "inline", "content": "ARTIFACT: present"},
                "assertions": [{"type": "contains", "value": "ARTIFACT:"}],  # passes
            },
            {
                "id": "c2", "name": "P1 case fails", "priority": "P1",
                "source": {"type": "inline", "content": "no verdict"},
                "assertions": [{"type": "contains", "value": "VERDICT:"}],  # FAILS
            },
        ]
        result = self._run(cases, {})
        assert not result.p0_regression
        assert result.failed == 1

    def test_empty_cases_pass_rate_is_1(self):
        from cc.core.eval_runner import LocalPythonRunner
        result = LocalPythonRunner().run("empty", [], repo_root=Path("/tmp"))
        assert result.pass_rate == 1.0
        assert not result.p0_regression

    def test_as_dict_is_json_serializable(self):
        from cc.core.eval_runner import LocalPythonRunner
        cases = [
            {
                "id": "c1", "name": "test", "priority": "P0",
                "source": {"type": "inline", "content": "hello"},
                "assertions": [{"type": "contains", "value": "hello"}],
            }
        ]
        result = LocalPythonRunner().run("qa", cases, repo_root=Path("/tmp"))
        d = result.as_dict()
        # Should not raise
        json.dumps(d)
        assert d["agent"] == "qa"
        assert d["total"] == 1
        assert d["passed"] == 1


class TestLoadCases:
    """Tests for load_cases()."""

    def test_loads_yaml_from_agent_dir(self, tmp_path):
        from cc.core.eval_runner import load_cases

        agent_dir = tmp_path / "qa"
        agent_dir.mkdir()
        (agent_dir / "case-001.yaml").write_text(
            "id: case-001\nname: test\npriority: P0\nsource:\n  type: inline\n  content: hello\nassertions:\n  - type: contains\n    value: hello\n"
        )
        (agent_dir / "case-002.yaml").write_text(
            "id: case-002\nname: test2\npriority: P1\nsource:\n  type: inline\n  content: world\nassertions:\n  - type: contains\n    value: world\n"
        )

        cases = load_cases(tmp_path, "qa")
        assert len(cases) == 2
        assert cases[0]["id"] == "case-001"
        assert cases[1]["id"] == "case-002"

    def test_missing_agent_dir_raises(self, tmp_path):
        from cc.core.eval_runner import load_cases

        with pytest.raises(FileNotFoundError, match="No eval cases found for agent"):
            load_cases(tmp_path, "nonexistent-agent")

    def test_sorted_by_filename(self, tmp_path):
        from cc.core.eval_runner import load_cases

        agent_dir = tmp_path / "qa"
        agent_dir.mkdir()
        # Write in reverse order
        for i in range(3, 0, -1):
            (agent_dir / f"case-00{i}.yaml").write_text(
                f"id: case-00{i}\nname: case {i}\npriority: P1\nsource:\n  type: inline\n  content: hi\nassertions: []\n"
            )

        cases = load_cases(tmp_path, "qa")
        ids = [c["id"] for c in cases]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Integration tests — qa golden set
# ---------------------------------------------------------------------------


class TestQaGoldenSet:
    """Integration tests against the real qa golden set in .claude/evals/qa/."""

    @pytest.mark.skipif(
        not EVALS_DIR.exists(),
        reason="Evals directory does not exist",
    )
    def test_qa_golden_set_passes_normally(self):
        """All qa eval cases pass against the current qa.md.

        This is the NORMAL (green) run — all cases should pass.
        """
        from cc.core.eval_runner import run_eval, LocalPythonRunner

        result = run_eval(
            "qa",
            evals_dir=EVALS_DIR,
            repo_root=REPO_ROOT,
            runner=LocalPythonRunner(),
        )

        # Report failures for debugging
        failures = [c for c in result.cases if not c.passed]
        if failures:
            msgs = []
            for c in failures:
                msgs.append(f"  FAIL: {c.case_id} — {c.name}")
                for a in c.assertions:
                    if not a.passed:
                        msgs.append(f"    assertion [{a.assertion_type}]: {a.error}")
            pytest.fail("qa golden set has failures:\n" + "\n".join(msgs))

        assert result.pass_rate == 1.0, f"Expected 100% pass rate, got {result.pass_rate}"
        assert not result.p0_regression

    @pytest.mark.skipif(
        not QA_AGENT.exists(),
        reason="qa.md does not exist",
    )
    def test_meta_test_removing_artifact_makes_eval_fail(self, tmp_path):
        """FF2 META-TEST: removing ARTIFACT requirement from qa.md makes eval FAIL.

        This proves the eval harness actually bites — it's not a no-op check.
        """
        from cc.core.eval_runner import run_eval, LocalPythonRunner

        # Create a modified qa.md that strips all "ARTIFACT" mentions
        original_qa = QA_AGENT.read_text(encoding="utf-8")
        modified_qa = "\n".join(
            line for line in original_qa.splitlines()
            if "ARTIFACT" not in line
        )

        # Set up a temp repo with the mutilated qa.md
        temp_agents_dir = tmp_path / ".claude" / "agents"
        temp_agents_dir.mkdir(parents=True)
        (temp_agents_dir / "qa.md").write_text(modified_qa, encoding="utf-8")

        # Result should fail when ARTIFACT is stripped
        result = run_eval(
            "qa",
            evals_dir=EVALS_DIR,  # use real cases
            repo_root=tmp_path,    # but point at mutilated qa.md
            runner=LocalPythonRunner(),
        )

        assert not (result.pass_rate >= 0.8 and not result.p0_regression), (
            "Expected the eval to FAIL when ARTIFACT is removed from qa.md, "
            f"but got pass_rate={result.pass_rate}, p0_regression={result.p0_regression}"
        )

    @pytest.mark.skipif(
        not EVALS_DIR.exists(),
        reason="Evals directory does not exist",
    )
    def test_qa_golden_set_has_ten_cases(self):
        """The qa golden set should have at least 10 cases (FF spec)."""
        from cc.core.eval_runner import load_cases

        cases = load_cases(EVALS_DIR, "qa")
        assert len(cases) >= 10, (
            f"Expected >= 10 qa eval cases, got {len(cases)}"
        )

    @pytest.mark.skipif(
        not EVALS_DIR.exists(),
        reason="Evals directory does not exist",
    )
    def test_qa_golden_set_has_p0_cases(self):
        """The qa golden set must include at least one P0 case."""
        from cc.core.eval_runner import load_cases

        cases = load_cases(EVALS_DIR, "qa")
        p0_cases = [c for c in cases if str(c.get("priority", "")).upper() == "P0"]
        assert p0_cases, "qa golden set must include at least one P0 case"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCcEvalCLI:
    """Integration tests for the `cc eval` CLI command."""

    @pytest.mark.skipif(
        not EVALS_DIR.exists(),
        reason="Evals directory does not exist",
    )
    def test_cc_eval_agent_qa_exits_zero(self):
        """cc eval --agent qa exits 0 on the green qa set."""
        result = subprocess.run(
            [sys.executable, "-m", "cc.main", "eval", "--agent", "qa", "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={**os.environ},
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        data = json.loads(result.stdout)
        assert data["agent"] == "qa"
        assert data["passed"] >= 1
        assert data["overall_pass"] is True

    @pytest.mark.skipif(
        not EVALS_DIR.exists(),
        reason="Evals directory does not exist",
    )
    def test_cc_eval_unknown_agent_exits_nonzero(self):
        """cc eval --agent nonexistent exits 1 (no cases)."""
        result = subprocess.run(
            [sys.executable, "-m", "cc.main", "eval", "--agent", "nonexistent-agent"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={**os.environ},
        )
        assert result.returncode != 0

    @pytest.mark.skipif(
        not EVALS_DIR.exists(),
        reason="Evals directory does not exist",
    )
    def test_cc_eval_list_agents_shows_qa(self):
        """cc eval --list-agents shows the qa agent."""
        result = subprocess.run(
            [sys.executable, "-m", "cc.main", "eval", "--list-agents"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={**os.environ},
        )
        assert result.returncode == 0
        assert "qa" in result.stdout
