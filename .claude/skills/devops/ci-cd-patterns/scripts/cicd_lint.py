#!/usr/bin/env python3
"""
CI/CD Pipeline Linter — L3 executable for the ci-cd-patterns skill.

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON representation of a GitHub Actions workflow file.
  Accepts the standard workflow structure:
  {
    "name": "CI",
    "on": {...},
    "permissions": {...},     // optional top-level
    "jobs": {
      "build": {
        "runs-on": "ubuntu-latest",
        "timeout-minutes": 30,  // optional
        "permissions": {...},   // optional job-level
        "steps": [
          {"uses": "actions/checkout@v4", ...},
          {"run": "echo hello", ...}
        ]
      }
    }
  }

  NOTE: YAML workflow files must be converted to JSON before passing.
  Use: python3 -c "import sys,json,yaml; print(json.dumps(yaml.safe_load(sys.stdin)))" < workflow.yml

Output (stdout):
  1. JSON object with 'findings' array and 'summary' counts.
  2. Markdown findings table.

Exit codes:
  0 — success (including empty input and findings-present input)
  1 — invalid input (bad JSON, missing 'jobs' field, file not found)

Checks and their sources:
  CICD-001  Unpinned action version (uses: owner/repo@branch or @vN without SHA)
            — GitHub Actions security hardening guide; supply-chain attack vector
            — Refs: https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions
  CICD-002  Missing timeout-minutes on job
            — GitHub Actions default 6-hour timeout wastes runners; mask hung builds
            — GitHub docs recommend explicit timeout
  CICD-003  Missing permissions block (top-level or job-level)
            — GitHub Actions security: GITHUB_TOKEN defaults to read-write on older repos
            — OSSF Scorecard check: Token-Permissions
  CICD-004  Secret-like value hardcoded in step env or run block
            — GitHub Actions security hardening; secrets in config leak in logs/forks
  CICD-005  Workflow-level write permissions with no job-level restriction
            — Principle of least privilege; jobs should narrow permissions further

Severity ranks:
  CRITICAL = 1  (supply-chain / credential exposure)
  HIGH     = 2  (security / token permissions)
  MEDIUM   = 3  (reliability / timeout)
  INFO     = 4  (advisory)
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------
CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
INFO = "INFO"

SEVERITY_RANK = {CRITICAL: 1, HIGH: 2, MEDIUM: 3, INFO: 4}

# ---------------------------------------------------------------------------
# Patterns — named constants with citations
# ---------------------------------------------------------------------------

# Action reference patterns
# Pinned = uses SHA: owner/repo@sha256hex or owner/repo@40hexchars
# Branch = uses a branch name (main, master, v1, etc.) — insecure
# Tag = uses @vN (semantic tag) — better than branch but not SHA-pinned

# A 40-char hex string is a full git SHA (secure pin)
SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}$", re.IGNORECASE)
# Matches @vN or @vN.M.P (tag-only, not SHA) — WARN level
TAG_RE = re.compile(r"@v\d[\d.]*$")
# Branch names — everything else that isn't a SHA or empty
BRANCH_REF_RE = re.compile(r"@([^@]+)$")

# Secret-like env variable names (same conservative list as docker_lint)
SECRET_KEY_NAMES_RE = re.compile(
    r"\b(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|ACCESS_KEY|"
    r"AUTH_KEY|CREDENTIALS|DATABASE_URL|DB_PASSWORD|DB_PASS)\b",
    re.IGNORECASE,
)

# Detects hardcoded-looking secrets: KEY: value where value is not a ${{ }} expression
# and looks like a credential (non-empty, not a common non-secret pattern)
SECRET_VALUE_RE = re.compile(
    r"(?:^|\s)(?:PASSWORD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|ACCESS_KEY|"
    r"AUTH_KEY|DB_PASSWORD|DB_PASS)\s*[:=]\s*(?!\$\{\{)(['\"]?[A-Za-z0-9+/=_\-]{8,}['\"]?)",
    re.IGNORECASE | re.MULTILINE,
)

# Permissions that grant write access
WRITE_PERMISSIONS = {
    "write", "write-all", "read-write",
}

# Known safe (docker-hub-style) action refs that should be excluded
SKIP_PREFIXES = ("docker://",)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_jobs(workflow: dict):
    """Yield (job_id, job_dict) pairs."""
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return
    yield from jobs.items()


def _iter_steps(job: dict):
    """Yield step dicts for a job."""
    steps = job.get("steps", [])
    if not isinstance(steps, list):
        return
    yield from steps


def _has_write_permissions(perms: object) -> bool:
    """Return True if a permissions object grants any write access."""
    if perms is None:
        return False
    if isinstance(perms, str):
        return perms.lower() in WRITE_PERMISSIONS
    if isinstance(perms, dict):
        return any(v.lower() in WRITE_PERMISSIONS for v in perms.values() if isinstance(v, str))
    return False


def _is_sha_pinned(ref: str) -> bool:
    return bool(SHA_PIN_RE.search(ref))


def _is_tag_pinned(ref: str) -> bool:
    return bool(TAG_RE.search(ref))


def _action_label(uses: str) -> str:
    """Short label for a uses: value."""
    return uses[:60] + ("..." if len(uses) > 60 else "")


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_unpinned_actions(workflow: dict) -> list[dict]:
    """CICD-001: Action uses without SHA pin."""
    findings = []
    seen: set[str] = set()

    for job_id, job in _iter_jobs(workflow):
        for step in _iter_steps(job):
            uses = step.get("uses", "")
            if not uses or uses in seen:
                continue
            # Skip docker:// and local path actions
            if any(uses.startswith(p) for p in SKIP_PREFIXES) or uses.startswith("./"):
                continue

            seen.add(uses)

            if _is_sha_pinned(uses):
                continue  # Best practice: SHA pinned → OK

            severity = CRITICAL
            if _is_tag_pinned(uses):
                # Semantic tag without SHA — better than branch but still mutable
                severity = HIGH
                detail = (
                    f"Action '{_action_label(uses)}' is pinned to a semantic tag, not a "
                    "full commit SHA. Tags are mutable — a repo owner can push a new "
                    "commit to the same tag. Pin to the full SHA for supply-chain safety: "
                    "uses: owner/repo@<40-char-sha>  # vN.M"
                )
            else:
                detail = (
                    f"Action '{_action_label(uses)}' uses a branch reference. "
                    "Branch refs are mutable — any push to that branch changes what runs "
                    "in your pipeline without any change to your workflow file. "
                    "Pin to a full commit SHA: uses: owner/repo@<40-char-sha>  # vN.M"
                )

            findings.append({
                "id": "CICD-001",
                "severity": severity,
                "job": job_id,
                "title": f"Unpinned action: {_action_label(uses)}",
                "detail": detail,
                "reference": "GitHub Actions Security Hardening Guide — Pinning actions to a full length commit SHA",
            })

    return findings


def check_missing_timeout(workflow: dict) -> list[dict]:
    """CICD-002: Missing timeout-minutes on jobs."""
    findings = []
    for job_id, job in _iter_jobs(workflow):
        if "timeout-minutes" not in job:
            findings.append({
                "id": "CICD-002",
                "severity": MEDIUM,
                "job": job_id,
                "title": f"Missing timeout-minutes on job '{job_id}'",
                "detail": (
                    f"Job '{job_id}' has no timeout-minutes set. GitHub Actions defaults "
                    "to 360 minutes (6 hours). A hung build wastes runner minutes and "
                    "blocks the pipeline for hours. Set timeout-minutes based on expected "
                    "duration (typically 2–3× normal run time)."
                ),
                "reference": "GitHub Actions docs — timeout-minutes",
            })
    return findings


def check_permissions_block(workflow: dict) -> list[dict]:
    """CICD-003: Missing permissions block."""
    findings = []
    top_level_perms = workflow.get("permissions")

    # If top-level permissions is 'read-all' or empty dict, that's restrictive — OK
    top_level_restrictive = (
        top_level_perms is not None and
        (top_level_perms == "read-all" or
         (isinstance(top_level_perms, dict) and not _has_write_permissions(top_level_perms)) or
         (isinstance(top_level_perms, str) and top_level_perms.lower() == "read-all"))
    )

    for job_id, job in _iter_jobs(workflow):
        job_perms = job.get("permissions")
        if job_perms is None and top_level_perms is None:
            findings.append({
                "id": "CICD-003",
                "severity": HIGH,
                "job": job_id,
                "title": f"No permissions block on job '{job_id}'",
                "detail": (
                    f"Job '{job_id}' has no permissions block and the workflow has no "
                    "top-level permissions. GITHUB_TOKEN defaults to broad write access "
                    "on many repositories. Add an explicit permissions block (at workflow "
                    "or job level) with the minimum required access."
                ),
                "reference": "OSSF Scorecard — Token-Permissions; GitHub docs — permissions",
            })

    return findings


def check_hardcoded_secrets(workflow: dict) -> list[dict]:
    """CICD-004: Secret-like values hardcoded in step env or run blocks."""
    findings = []
    seen_keys: set[str] = set()

    for job_id, job in _iter_jobs(workflow):
        for step in _iter_steps(job):
            step_name = step.get("name", "<unnamed step>")

            # Check env block
            env = step.get("env", {})
            if isinstance(env, dict):
                for key, value in env.items():
                    if SECRET_KEY_NAMES_RE.search(key) and key not in seen_keys:
                        # Only flag if the value is NOT a ${{ secrets.X }} reference
                        if isinstance(value, str) and not value.strip().startswith("${{"):
                            seen_keys.add(key)
                            findings.append({
                                "id": "CICD-004",
                                "severity": CRITICAL,
                                "job": job_id,
                                "title": f"Hardcoded secret in env: {key} (step: {step_name})",
                                "detail": (
                                    f"Step '{step_name}' in job '{job_id}' sets env.{key} "
                                    "to a literal value. Hardcoded credentials appear in "
                                    "workflow file history, forks, and PR diffs. "
                                    "Use ${{ secrets.NAME }} instead."
                                ),
                                "reference": "GitHub Actions Security — encrypted secrets",
                            })

            # Check run block for inline credential patterns
            run = step.get("run", "")
            if isinstance(run, str):
                for match in SECRET_VALUE_RE.finditer(run):
                    key_name = re.match(
                        r"(?:PASSWORD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|ACCESS_KEY|"
                        r"AUTH_KEY|DB_PASSWORD|DB_PASS)",
                        match.group(0).strip(),
                        re.IGNORECASE,
                    )
                    label = key_name.group(0) if key_name else "credential"
                    if label not in seen_keys:
                        seen_keys.add(label)
                        findings.append({
                            "id": "CICD-004",
                            "severity": CRITICAL,
                            "job": job_id,
                            "title": f"Possible hardcoded secret in run block: {label} (step: {step_name})",
                            "detail": (
                                f"Step '{step_name}' in job '{job_id}' has a run command "
                                f"containing a credential-like assignment ({label}=...). "
                                "Use ${{ secrets.NAME }} to keep credentials out of "
                                "the workflow file and build logs."
                            ),
                            "reference": "GitHub Actions Security — encrypted secrets",
                        })

    return findings


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_unpinned_actions,
    check_missing_timeout,
    check_permissions_block,
    check_hardcoded_secrets,
]


def lint_workflow(workflow: dict) -> list[dict]:
    """Run all checks and return sorted findings."""
    all_findings = []
    for check in ALL_CHECKS:
        all_findings.extend(check(workflow))
    all_findings.sort(key=lambda f: (SEVERITY_RANK[f["severity"]], f["id"], f.get("job", "")))
    return all_findings


def render_markdown(findings: list[dict]) -> str:
    if not findings:
        return "_No issues found._\n"
    lines = [
        "| # | ID | Severity | Job | Title |",
        "|---|----|----------|-----|-------|",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(
            f"| {i} | {f['id']} | {f['severity']} | {f.get('job', '-')} | {f['title']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_input(source: str | None) -> dict | None:
    """Load JSON workflow from file or stdin. Returns None for empty input."""
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
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from {label}: {exc}")

    if not isinstance(data, dict):
        raise ValueError(
            f"Input from {label} must be a JSON object (workflow), got {type(data).__name__}"
        )

    if "jobs" not in data:
        raise ValueError(
            f"Workflow object from {label} missing required field 'jobs'"
        )

    return data


def run(source: str | None) -> int:
    try:
        workflow = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if workflow is None:
        output = {"findings": [], "summary": {"total": 0, "critical": 0, "high": 0, "medium": 0, "info": 0}}
        print(json.dumps(output, indent=2))
        print()
        print("_No workflow content provided._")
        return 0

    findings = lint_workflow(workflow)

    summary = {
        "total": len(findings),
        "critical": sum(1 for f in findings if f["severity"] == CRITICAL),
        "high": sum(1 for f in findings if f["severity"] == HIGH),
        "medium": sum(1 for f in findings if f["severity"] == MEDIUM),
        "info": sum(1 for f in findings if f["severity"] == INFO),
    }

    output = {"findings": findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()

    print("## CI/CD Pipeline Linter Findings\n")
    print(render_markdown(findings))
    if findings:
        print(
            "**Severity:** CRITICAL = supply-chain/credential | "
            "HIGH = token permissions/security | MEDIUM = reliability"
        )
        print(
            "\n**Note:** Input must be JSON. Convert YAML workflow with: "
            "`python3 -c \"import sys,json,yaml; print(json.dumps(yaml.safe_load(sys.stdin)))\" < .github/workflows/ci.yml`"
        )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "CI/CD pipeline linter for GitHub Actions workflows. "
            "Input must be JSON (convert YAML with python yaml.safe_load)."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to JSON workflow file, or '-' for stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
