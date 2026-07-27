"""
Tests for cicd_lint.py — bundled alongside the linter.

Run with:  python3 -m pytest .claude/skills/devops/ci-cd-patterns/scripts/test_cicd_lint.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "cicd_lint.py"

spec = importlib.util.spec_from_file_location("cicd_lint", SCRIPT)
cicd_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cicd_lint)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_output(stdout: str):
    return json.loads(stdout.split("\n\n")[0])


def finding_ids(findings):
    return [f["id"] for f in findings]


# ---------------------------------------------------------------------------
# Minimal compliant workflow (passes all checks)
# ---------------------------------------------------------------------------

GOOD_WORKFLOW = {
    "name": "CI",
    "on": {"push": {"branches": ["main"]}},
    "permissions": "read-all",
    "jobs": {
        "build": {
            "runs-on": "ubuntu-latest",
            "timeout-minutes": 30,
            "permissions": {"contents": "read"},
            "steps": [
                {
                    "name": "Checkout",
                    "uses": "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",  # SHA-pinned
                },
                {
                    "name": "Run tests",
                    "run": "npm test",
                },
            ],
        }
    },
}


# ---------------------------------------------------------------------------
# CICD-001: Unpinned actions
# ---------------------------------------------------------------------------


class TestUnpinnedActions:
    def _make_workflow(self, uses_ref):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"][0]["uses"] = uses_ref
        return w

    def test_branch_ref_raises_cicd001_critical(self):
        findings = cicd_lint.check_unpinned_actions(
            self._make_workflow("actions/checkout@main")
        )
        ids = finding_ids(findings)
        assert "CICD-001" in ids
        assert findings[0]["severity"] == "CRITICAL"

    def test_tag_ref_raises_cicd001_high(self):
        findings = cicd_lint.check_unpinned_actions(
            self._make_workflow("actions/checkout@v4")
        )
        ids = finding_ids(findings)
        assert "CICD-001" in ids
        assert findings[0]["severity"] == "HIGH"

    def test_sha_pinned_no_finding(self):
        sha = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
        findings = cicd_lint.check_unpinned_actions(self._make_workflow(sha))
        assert findings == []

    def test_local_action_no_finding(self):
        findings = cicd_lint.check_unpinned_actions(
            self._make_workflow("./local-action")
        )
        assert findings == []

    def test_docker_action_no_finding(self):
        findings = cicd_lint.check_unpinned_actions(
            self._make_workflow("docker://alpine:3.19")
        )
        assert findings == []

    def test_no_uses_step_no_finding(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"][0] = {"name": "Run", "run": "echo hello"}
        findings = cicd_lint.check_unpinned_actions(w)
        assert findings == []

    def test_duplicate_uses_deduplicated(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"] = [
            {"uses": "actions/checkout@main"},
            {"uses": "actions/checkout@main"},  # duplicate
        ]
        findings = cicd_lint.check_unpinned_actions(w)
        assert len([f for f in findings if "checkout@main" in f["title"]]) == 1


# ---------------------------------------------------------------------------
# CICD-002: Missing timeout
# ---------------------------------------------------------------------------


class TestMissingTimeout:
    def test_no_timeout_raises_cicd002(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["jobs"]["build"]["timeout-minutes"]
        findings = cicd_lint.check_missing_timeout(w)
        assert "CICD-002" in finding_ids(findings)

    def test_timeout_present_no_finding(self):
        findings = cicd_lint.check_missing_timeout(GOOD_WORKFLOW)
        assert findings == []

    def test_severity_is_medium(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["jobs"]["build"]["timeout-minutes"]
        findings = cicd_lint.check_missing_timeout(w)
        assert findings[0]["severity"] == "MEDIUM"

    def test_multiple_jobs_each_checked(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["test"] = {"runs-on": "ubuntu-latest", "steps": []}
        w["jobs"]["lint"] = {"runs-on": "ubuntu-latest", "steps": []}
        findings = cicd_lint.check_missing_timeout(w)
        job_ids = [f["job"] for f in findings if f["id"] == "CICD-002"]
        assert "test" in job_ids
        assert "lint" in job_ids


# ---------------------------------------------------------------------------
# CICD-003: Missing permissions
# ---------------------------------------------------------------------------


class TestMissingPermissions:
    def test_no_permissions_anywhere_raises_cicd003(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["permissions"]
        del w["jobs"]["build"]["permissions"]
        findings = cicd_lint.check_permissions_block(w)
        assert "CICD-003" in finding_ids(findings)

    def test_top_level_read_all_and_no_job_perms_no_finding(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["jobs"]["build"]["permissions"]
        findings = cicd_lint.check_permissions_block(w)
        # top-level read-all covers all jobs
        assert findings == []

    def test_job_level_perms_no_finding(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["permissions"]
        findings = cicd_lint.check_permissions_block(w)
        # job-level permissions present
        assert findings == []

    def test_severity_is_high(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["permissions"]
        del w["jobs"]["build"]["permissions"]
        findings = cicd_lint.check_permissions_block(w)
        assert findings[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# CICD-004: Hardcoded secrets
# ---------------------------------------------------------------------------


class TestHardcodedSecrets:
    def test_env_block_secret_raises_cicd004(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"][1]["env"] = {"API_KEY": "abc123supersecret"}
        findings = cicd_lint.check_hardcoded_secrets(w)
        assert "CICD-004" in finding_ids(findings)

    def test_env_block_secrets_ref_no_finding(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"][1]["env"] = {"API_KEY": "${{ secrets.API_KEY }}"}
        findings = cicd_lint.check_hardcoded_secrets(w)
        assert findings == []

    def test_run_block_inline_secret_raises_cicd004(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"][1][
            "run"
        ] = "curl -H 'Authorization: Bearer SECRET=mytoken123' https://api.example.com"
        findings = cicd_lint.check_hardcoded_secrets(w)
        assert "CICD-004" in finding_ids(findings)

    def test_severity_is_critical(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"][1]["env"] = {"PASSWORD": "hunter2"}
        findings = cicd_lint.check_hardcoded_secrets(w)
        assert findings[0]["severity"] == "CRITICAL"

    def test_env_without_secret_name_no_finding(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        w["jobs"]["build"]["steps"][1]["env"] = {
            "PORT": "8080",
            "NODE_ENV": "production",
        }
        findings = cicd_lint.check_hardcoded_secrets(w)
        assert findings == []


# ---------------------------------------------------------------------------
# Good workflow — zero findings
# ---------------------------------------------------------------------------


class TestGoodWorkflow:
    def test_good_workflow_no_findings(self):
        findings = cicd_lint.lint_workflow(GOOD_WORKFLOW)
        assert findings == [], f"Unexpected findings: {findings}"


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder:
    def test_critical_before_medium(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["jobs"]["build"]["timeout-minutes"]  # MEDIUM
        w["jobs"]["build"]["steps"][0]["uses"] = "actions/checkout@main"  # CRITICAL
        findings = cicd_lint.lint_workflow(w)
        severities = [f["severity"] for f in findings]
        crit_idx = next((i for i, s in enumerate(severities) if s == "CRITICAL"), None)
        med_idx = next((i for i, s in enumerate(severities) if s == "MEDIUM"), None)
        if crit_idx is not None and med_idx is not None:
            assert crit_idx < med_idx


# ---------------------------------------------------------------------------
# Load input validation
# ---------------------------------------------------------------------------


class TestLoadInput:
    def test_missing_jobs_raises(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO('{"name": "CI", "on": {}}'))
        with pytest.raises(ValueError, match="jobs"):
            cicd_lint.load_input(None)

    def test_non_object_raises(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO("[1, 2, 3]"))
        with pytest.raises(ValueError, match="JSON object"):
            cicd_lint.load_input(None)

    def test_empty_input_returns_none(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO(""))
        result = cicd_lint.load_input(None)
        assert result is None

    def test_invalid_json_raises(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO("{bad json"))
        with pytest.raises(ValueError, match="Invalid JSON"):
            cicd_lint.load_input(None)


# ---------------------------------------------------------------------------
# Subprocess integration
# ---------------------------------------------------------------------------


class TestSubprocess:
    def test_good_workflow_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(GOOD_WORKFLOW))
        assert code == 0

    def test_bad_json_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text="not json")
        assert code != 0
        assert "ERROR" in err

    def test_missing_jobs_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text='{"name": "CI"}')
        assert code != 0
        assert "ERROR" in err

    def test_missing_file_exits_nonzero(self):
        code, _, err = run_script(args=("/no/such/workflow.json",))
        assert code != 0
        assert "ERROR" in err

    def test_empty_stdin_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="")
        assert code == 0

    def test_markdown_table_present_with_findings(self):
        w = json.loads(json.dumps(GOOD_WORKFLOW))
        del w["jobs"]["build"]["timeout-minutes"]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(w))
        assert code == 0
        assert "## CI/CD Pipeline Linter Findings" in out
        assert "| # |" in out

    def test_file_path_argument(self, tmp_path):
        p = tmp_path / "workflow.json"
        p.write_text(json.dumps(GOOD_WORKFLOW))
        code, out, _ = run_script(args=(str(p),))
        assert code == 0
