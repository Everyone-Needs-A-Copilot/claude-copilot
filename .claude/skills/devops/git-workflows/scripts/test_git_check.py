"""
Tests for git_check.py — bundled alongside the checker.

Run with:  python3 -m pytest .claude/skills/devops/git-workflows/scripts/test_git_check.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "git_check.py"

spec = importlib.util.spec_from_file_location("git_check", SCRIPT)
git_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(git_check)


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
# GIT-001: Conventional Commits validation
# ---------------------------------------------------------------------------


class TestConventionalCommits:
    # Valid messages
    @pytest.mark.parametrize(
        "msg",
        [
            "feat(auth): add OAuth2 login support",
            "fix(api): handle null response from payment service",
            "docs: update README",
            "chore: bump dependencies",
            "feat!: remove deprecated endpoint",
            "fix(ui)!: change button color (breaking)",
            "refactor(db): extract connection pool",
            "perf: improve query caching",
            "test: add unit tests for auth module",
            "build: upgrade webpack to v5",
            "ci: add matrix builds",
            "revert: feat(auth): add OAuth2 login",
            "style: fix indentation",
        ],
    )
    def test_valid_commit_no_finding(self, msg):
        findings = git_check.check_commit_message(msg, 0)
        assert findings == [], f"Unexpected finding for: {msg!r}"

    # Invalid messages
    @pytest.mark.parametrize(
        "msg",
        [
            "Add new feature",  # no type
            "Fixed the bug",  # no type
            "feat add login",  # missing colon
            "FEAT: add login",  # uppercase type
            "feat:add login",  # missing space after colon
            "random: add login",  # unknown type
            "Update dependencies",  # vague, no type
            "",  # empty (allowed — skipped)
        ],
    )
    def test_invalid_commit_finding_or_skip(self, msg):
        findings = git_check.check_commit_message(msg, 0)
        if msg == "":
            assert findings == []  # empty is skipped
        else:
            assert "GIT-001" in finding_ids(findings), f"Expected GIT-001 for: {msg!r}"

    def test_merge_commit_skipped(self):
        findings = git_check.check_commit_message(
            "Merge branch 'main' into feature/x", 0
        )
        assert findings == []

    def test_revert_commit_skipped(self):
        findings = git_check.check_commit_message('Revert "feat: add login"', 0)
        assert findings == []

    def test_unknown_type_reports_type_name(self):
        findings = git_check.check_commit_message("unknown: do something", 0)
        assert "GIT-001" in finding_ids(findings)
        assert "unknown" in findings[0]["detail"]

    def test_severity_is_high(self):
        findings = git_check.check_commit_message("bad commit message", 0)
        assert findings[0]["severity"] == "HIGH"

    def test_all_valid_types_accepted(self):
        for t in git_check.VALID_COMMIT_TYPES:
            msg = f"{t}: do something"
            findings = git_check.check_commit_message(msg, 0)
            assert findings == [], f"Type '{t}' should be valid but got: {findings}"

    def test_scope_optional_both_work(self):
        assert git_check.check_commit_message("feat: no scope", 0) == []
        assert git_check.check_commit_message("feat(scope): with scope", 0) == []


# ---------------------------------------------------------------------------
# GIT-002: Branch naming validation
# ---------------------------------------------------------------------------


class TestBranchNaming:
    # Valid branches
    @pytest.mark.parametrize(
        "branch",
        [
            "feature/user-authentication",
            "fix/login-null-pointer",
            "hotfix/payment-crash",
            "release/v2-0-0",
            "chore/update-deps",
            "docs/add-api-reference",
            "refactor/auth-module",
            "feat/dark-mode",
            "dependabot/npm-lodash-4-17-21",
            "main",  # protected — exempt
            "master",  # protected — exempt
            "develop",  # protected — exempt
        ],
    )
    def test_valid_branch_no_finding(self, branch):
        findings = git_check.check_branch_name(branch, 0)
        assert findings == [], f"Unexpected finding for: {branch!r}"

    # Invalid branches
    @pytest.mark.parametrize(
        "branch",
        [
            "FEATURE/auth",  # uppercase prefix
            "Feature/auth",  # mixed case prefix
            "feature/User-Auth",  # uppercase in description
            "my-branch",  # no prefix/separator
            "bugfix/login thing",  # space in name
            "random/feature",  # unrecognised prefix
            "fix/",  # empty description
            "feature",  # no slash
        ],
    )
    def test_invalid_branch_raises_git002(self, branch):
        findings = git_check.check_branch_name(branch, 0)
        assert "GIT-002" in finding_ids(findings), f"Expected GIT-002 for: {branch!r}"

    def test_protected_branches_exempt(self):
        for b in git_check.PROTECTED_BRANCHES:
            findings = git_check.check_branch_name(b, 0)
            assert findings == [], f"Protected branch '{b}' should be exempt"

    def test_severity_is_medium(self):
        findings = git_check.check_branch_name("mybranch", 0)
        assert findings[0]["severity"] == "MEDIUM"

    def test_uppercase_branch_error_message(self):
        findings = git_check.check_branch_name("Feature/Auth", 0)
        assert "GIT-002" in finding_ids(findings)
        assert "uppercase" in findings[0]["detail"].lower()


# ---------------------------------------------------------------------------
# Full check_all integration
# ---------------------------------------------------------------------------


class TestCheckAll:
    def test_mixed_commits_and_branches(self):
        data = {
            "commits": [
                "feat(auth): add login",  # valid
                "bad commit",  # invalid
            ],
            "branches": [
                "feature/user-auth",  # valid
                "FEATURE/auth",  # invalid
            ],
        }
        findings = git_check.check_all(data)
        ids = finding_ids(findings)
        assert "GIT-001" in ids
        assert "GIT-002" in ids

    def test_all_valid_no_findings(self):
        data = {
            "commits": ["feat: add feature", "fix(api): handle error"],
            "branches": ["feature/my-feature", "fix/bug-123"],
        }
        findings = git_check.check_all(data)
        assert findings == []

    def test_sort_order_high_before_medium(self):
        data = {
            "commits": ["bad commit"],  # HIGH
            "branches": ["mybranch"],  # MEDIUM
        }
        findings = git_check.check_all(data)
        severities = [f["severity"] for f in findings]
        high_idx = next(i for i, s in enumerate(severities) if s == "HIGH")
        med_idx = next(i for i, s in enumerate(severities) if s == "MEDIUM")
        assert high_idx < med_idx

    def test_only_commits_key(self):
        data = {"commits": ["bad message"]}
        findings = git_check.check_all(data)
        assert "GIT-001" in finding_ids(findings)

    def test_only_branches_key(self):
        data = {"branches": ["mybranch"]}
        findings = git_check.check_all(data)
        assert "GIT-002" in finding_ids(findings)

    def test_empty_arrays_no_findings(self):
        data = {"commits": [], "branches": []}
        findings = git_check.check_all(data)
        assert findings == []


# ---------------------------------------------------------------------------
# Load input validation
# ---------------------------------------------------------------------------


class TestLoadInput:
    def test_non_array_commits_raises(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO('{"commits": "not an array"}'))
        with pytest.raises(ValueError, match="commits"):
            git_check.load_input(None)

    def test_non_string_commit_raises(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO('{"commits": [1, 2]}'))
        with pytest.raises(ValueError, match="string"):
            git_check.load_input(None)

    def test_non_object_raises(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO('["feat: test"]'))
        with pytest.raises(ValueError, match="JSON object"):
            git_check.load_input(None)

    def test_empty_input_returns_none(self, monkeypatch):
        import io, sys as _sys

        monkeypatch.setattr(_sys, "stdin", io.StringIO(""))
        result = git_check.load_input(None)
        assert result is None

    def test_file_path(self, tmp_path):
        data = {"commits": ["feat: test"]}
        p = tmp_path / "input.json"
        p.write_text(json.dumps(data))
        result = git_check.load_input(str(p))
        assert result["commits"] == ["feat: test"]

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            git_check.load_input("/no/such/file.json")


# ---------------------------------------------------------------------------
# Subprocess integration
# ---------------------------------------------------------------------------


class TestSubprocess:
    def test_valid_input_exits_zero(self):
        data = {"commits": ["feat: add feature"], "branches": ["feature/my-feat"]}
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0

    def test_bad_json_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text="not json")
        assert code != 0
        assert "ERROR" in err

    def test_empty_stdin_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="")
        assert code == 0

    def test_findings_produce_markdown(self):
        data = {"commits": ["bad commit"], "branches": ["MYBRANCH"]}
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        assert "## Git Convention Checker Findings" in out
        assert "| # |" in out

    def test_no_findings_no_issues_message(self):
        data = {"commits": ["feat: add feature"], "branches": ["feature/my-feat"]}
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        assert "_No issues found._" in out

    def test_file_path_argument(self, tmp_path):
        data = {"commits": ["feat: add feature"]}
        p = tmp_path / "input.json"
        p.write_text(json.dumps(data))
        code, out, _ = run_script(args=(str(p),))
        assert code == 0

    def test_summary_counts(self):
        data = {
            "commits": ["bad", "also bad"],
            "branches": ["MYBRANCH"],
        }
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(data))
        assert code == 0
        result = parse_output(out)
        assert result["summary"]["high"] == 2  # two bad commits
        assert result["summary"]["medium"] == 1  # one bad branch
        assert result["summary"]["total"] == 3
