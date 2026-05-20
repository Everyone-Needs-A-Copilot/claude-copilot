"""
Tests for docker_lint.py — bundled alongside the linter.

Run with:  python3 -m pytest .claude/skills/devops/docker-patterns/scripts/test_docker_lint.py -v
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "docker_lint.py"

spec = importlib.util.spec_from_file_location("docker_lint", SCRIPT)
docker_lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docker_lint)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_output(stdout: str):
    """Extract JSON block from script stdout."""
    json_block = stdout.split("\n\n")[0]
    return json.loads(json_block)


def finding_ids(findings):
    return [f["id"] for f in findings]


# ---------------------------------------------------------------------------
# Minimal valid Dockerfile (passes all checks)
# ---------------------------------------------------------------------------

GOOD_DOCKERFILE = """\
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \\
    libpq-dev \\
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \\
  CMD wget -qO- http://localhost:8000/health || exit 1

EXPOSE 8000
CMD ["python", "app.py"]
"""

# ---------------------------------------------------------------------------
# DOCKER-001: Root user
# ---------------------------------------------------------------------------

class TestRootUser:
    def test_no_user_directive_raises_docker001(self):
        content = "FROM python:3.12-slim\nCMD python app.py\n"
        findings = docker_lint.check_root_user(content)
        ids = finding_ids(findings)
        assert "DOCKER-001" in ids

    def test_user_root_explicit_raises_docker001(self):
        content = "FROM python:3.12-slim\nUSER root\nCMD python app.py\n"
        findings = docker_lint.check_root_user(content)
        ids = finding_ids(findings)
        assert "DOCKER-001" in ids

    def test_user_0_raises_docker001(self):
        content = "FROM python:3.12-slim\nUSER 0\nCMD python app.py\n"
        findings = docker_lint.check_root_user(content)
        ids = finding_ids(findings)
        assert "DOCKER-001" in ids

    def test_non_root_user_no_finding(self):
        content = "FROM python:3.12-slim\nUSER appuser\nCMD python app.py\n"
        findings = docker_lint.check_root_user(content)
        assert findings == []

    def test_user_1000_no_finding(self):
        content = "FROM python:3.12-slim\nUSER 1000\nCMD python app.py\n"
        findings = docker_lint.check_root_user(content)
        assert findings == []

    def test_severity_is_critical(self):
        content = "FROM python:3.12-slim\nCMD python app.py\n"
        findings = docker_lint.check_root_user(content)
        assert findings[0]["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# DOCKER-002: Latest tag
# ---------------------------------------------------------------------------

class TestLatestTag:
    def test_from_latest_raises_docker002(self):
        findings = docker_lint.check_latest_tag("FROM python:latest\n")
        assert "DOCKER-002" in finding_ids(findings)

    def test_from_no_tag_raises_docker002(self):
        findings = docker_lint.check_latest_tag("FROM python\n")
        assert "DOCKER-002" in finding_ids(findings)

    def test_from_pinned_version_no_finding(self):
        findings = docker_lint.check_latest_tag("FROM python:3.12-slim\n")
        assert findings == []

    def test_from_digest_no_finding(self):
        findings = docker_lint.check_latest_tag(
            "FROM python:3.12-slim@sha256:abc123def456\n"
        )
        assert findings == []

    def test_from_scratch_no_finding(self):
        findings = docker_lint.check_latest_tag("FROM scratch\n")
        assert findings == []

    def test_from_arg_interpolation_no_finding(self):
        findings = docker_lint.check_latest_tag("FROM $BASE_IMAGE\n")
        assert findings == []

    def test_severity_is_high(self):
        findings = docker_lint.check_latest_tag("FROM python:latest\n")
        assert findings[0]["severity"] == "HIGH"

    def test_multistage_multiple_latest_multiple_findings(self):
        content = "FROM node:latest AS builder\nFROM python:latest\n"
        findings = docker_lint.check_latest_tag(content)
        assert len(findings) == 2


# ---------------------------------------------------------------------------
# DOCKER-003: HEALTHCHECK
# ---------------------------------------------------------------------------

class TestHealthcheck:
    def test_missing_healthcheck_raises_docker003(self):
        content = "FROM python:3.12-slim\nUSER appuser\nCMD python app.py\n"
        findings = docker_lint.check_healthcheck(content)
        assert "DOCKER-003" in finding_ids(findings)

    def test_healthcheck_present_no_finding(self):
        content = (
            "FROM python:3.12-slim\n"
            "HEALTHCHECK --interval=30s CMD wget -qO- http://localhost:8000/health || exit 1\n"
        )
        findings = docker_lint.check_healthcheck(content)
        assert findings == []

    def test_healthcheck_none_no_finding(self):
        # Explicit opt-out is accepted
        content = "FROM python:3.12-slim\nHEALTHCHECK NONE\n"
        findings = docker_lint.check_healthcheck(content)
        assert findings == []

    def test_severity_is_high(self):
        findings = docker_lint.check_healthcheck("FROM python:3.12-slim\n")
        assert findings[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# DOCKER-004: apt-get without --no-install-recommends
# ---------------------------------------------------------------------------

class TestAptNoRecommends:
    def test_apt_without_no_install_recommends_raises(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
        findings = docker_lint.check_apt_no_install_recommends(content)
        assert "DOCKER-004" in finding_ids(findings)

    def test_apt_with_no_install_recommends_no_finding(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends curl\n"
        )
        findings = docker_lint.check_apt_no_install_recommends(content)
        assert findings == []

    def test_severity_is_medium(self):
        content = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y curl\n"
        findings = docker_lint.check_apt_no_install_recommends(content)
        assert findings[0]["severity"] == "MEDIUM"


# ---------------------------------------------------------------------------
# DOCKER-005: Secrets in ENV/ARG
# ---------------------------------------------------------------------------

class TestSecretsInEnv:
    def test_env_password_raises_docker005(self):
        content = "FROM python:3.12-slim\nENV DATABASE_PASSWORD=supersecret\n"
        findings = docker_lint.check_secrets_in_env(content)
        assert "DOCKER-005" in finding_ids(findings)

    def test_arg_api_key_raises_docker005(self):
        content = "FROM python:3.12-slim\nARG API_KEY=abc123\n"
        findings = docker_lint.check_secrets_in_env(content)
        assert "DOCKER-005" in finding_ids(findings)

    def test_env_token_raises_docker005(self):
        content = "FROM python:3.12-slim\nENV SECRET_TOKEN=xyz\n"
        findings = docker_lint.check_secrets_in_env(content)
        assert "DOCKER-005" in finding_ids(findings)

    def test_env_port_no_finding(self):
        content = "FROM python:3.12-slim\nENV PORT=8000\n"
        findings = docker_lint.check_secrets_in_env(content)
        assert findings == []

    def test_env_app_name_no_finding(self):
        content = "FROM python:3.12-slim\nENV APP_NAME=myapp\n"
        findings = docker_lint.check_secrets_in_env(content)
        assert findings == []

    def test_severity_is_critical(self):
        content = "FROM python:3.12-slim\nENV DATABASE_PASSWORD=secret\n"
        findings = docker_lint.check_secrets_in_env(content)
        assert findings[0]["severity"] == "CRITICAL"

    def test_env_no_value_no_finding(self):
        # ARG without a default is fine (value injected at build time)
        content = "FROM python:3.12-slim\nARG API_KEY\n"
        findings = docker_lint.check_secrets_in_env(content)
        assert findings == []


# ---------------------------------------------------------------------------
# DOCKER-006: Layer bloat
# ---------------------------------------------------------------------------

class TestLayerBloat:
    def test_apt_without_cleanup_raises_docker006(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends curl\n"
        )
        findings = docker_lint.check_layer_bloat(content)
        assert "DOCKER-006" in finding_ids(findings)

    def test_apt_with_cleanup_no_finding(self):
        content = (
            "FROM ubuntu:22.04\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends curl \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
        )
        findings = docker_lint.check_layer_bloat(content)
        assert findings == []

    def test_apk_without_no_cache_raises_docker006(self):
        content = "FROM alpine:3.19\nRUN apk add curl\n"
        findings = docker_lint.check_layer_bloat(content)
        assert "DOCKER-006" in finding_ids(findings)

    def test_apk_with_no_cache_no_finding(self):
        content = "FROM alpine:3.19\nRUN apk add --no-cache curl\n"
        findings = docker_lint.check_layer_bloat(content)
        assert findings == []


# ---------------------------------------------------------------------------
# DOCKER-007: COPY order
# ---------------------------------------------------------------------------

class TestCopyOrder:
    def test_copy_all_before_manifest_raises_docker007(self):
        content = (
            "FROM python:3.12-slim\n"
            "COPY . .\n"
            "COPY requirements.txt .\n"
            "RUN pip install -r requirements.txt\n"
        )
        findings = docker_lint.check_copy_order(content)
        assert "DOCKER-007" in finding_ids(findings)

    def test_copy_manifest_before_all_no_finding(self):
        content = (
            "FROM python:3.12-slim\n"
            "COPY requirements.txt .\n"
            "RUN pip install -r requirements.txt\n"
            "COPY . .\n"
        )
        findings = docker_lint.check_copy_order(content)
        assert findings == []

    def test_no_copy_all_no_finding(self):
        content = (
            "FROM python:3.12-slim\n"
            "COPY requirements.txt .\n"
            "COPY src/ ./src/\n"
        )
        findings = docker_lint.check_copy_order(content)
        assert findings == []


# ---------------------------------------------------------------------------
# Severity sort order
# ---------------------------------------------------------------------------

class TestSortOrder:
    def test_critical_before_high_before_medium(self):
        # Dockerfile with root (CRITICAL), latest (HIGH), apt (MEDIUM)
        content = (
            "FROM python:latest\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "CMD python app.py\n"
        )
        findings = docker_lint.lint_dockerfile(content)
        severities = [f["severity"] for f in findings]
        # CRITICAL first, then HIGH, then MEDIUM
        crit_idx = next((i for i, s in enumerate(severities) if s == "CRITICAL"), None)
        high_idx = next((i for i, s in enumerate(severities) if s == "HIGH"), None)
        med_idx = next((i for i, s in enumerate(severities) if s == "MEDIUM"), None)
        if crit_idx is not None and high_idx is not None:
            assert crit_idx < high_idx
        if high_idx is not None and med_idx is not None:
            assert high_idx < med_idx


# ---------------------------------------------------------------------------
# Good Dockerfile — zero findings
# ---------------------------------------------------------------------------

class TestGoodDockerfile:
    def test_good_dockerfile_no_findings(self):
        findings = docker_lint.lint_dockerfile(GOOD_DOCKERFILE)
        assert findings == [], f"Unexpected findings: {findings}"


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_stdin_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="")
        assert code == 0

    def test_whitespace_only_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="   \n  ")
        assert code == 0

    def test_empty_output_has_zero_total(self):
        code, out, _ = run_script(args=("-",), stdin_text="")
        assert code == 0
        result = parse_output(out)
        assert result["summary"]["total"] == 0


# ---------------------------------------------------------------------------
# File path argument
# ---------------------------------------------------------------------------

class TestFilePathArgument:
    def test_file_path_argument(self, tmp_path):
        p = tmp_path / "Dockerfile"
        p.write_text("FROM python:latest\nCMD python app.py\n")
        code, out, _ = run_script(args=(str(p),))
        assert code == 0
        result = parse_output(out)
        assert result["summary"]["total"] > 0

    def test_nonexistent_file_exits_nonzero(self):
        code, _, err = run_script(args=("/no/such/Dockerfile",))
        assert code != 0
        assert "ERROR" in err


# ---------------------------------------------------------------------------
# Subprocess: markdown table present
# ---------------------------------------------------------------------------

class TestMarkdownOutput:
    def test_markdown_table_present_when_findings(self):
        code, out, _ = run_script(args=("-",), stdin_text="FROM python:latest\nCMD python app.py\n")
        assert code == 0
        assert "## Docker Linter Findings" in out
        assert "| # |" in out

    def test_no_issues_text_when_clean(self):
        code, out, _ = run_script(args=("-",), stdin_text=GOOD_DOCKERFILE)
        assert code == 0
        assert "_No issues found._" in out
