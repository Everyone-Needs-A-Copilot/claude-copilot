---
name: ci-cd-patterns
skill_category: devops
description: CI/CD pipeline patterns, GitHub Actions, build automation best practices — with deterministic pipeline linting script
version: 2.0.0
source: .claude/skills/devops/ci-cd-patterns.md (retired flat file); L3 linter added 2026-05-20
when_to_use:
  - Reviewing or writing GitHub Actions workflows
  - CI pipeline has security findings (Scorecard, CodeQL)
  - Debugging slow or flaky pipelines
  - Supply-chain security review of workflows
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
tags: [ci-cd, github-actions, pipeline, anti-pattern, best-practice, automation, security]
trigger_files: [".github/workflows/*.yml", ".github/workflows/*.yaml", "Jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml"]
trigger_keywords: [ci/cd, pipeline, github actions, workflow, build, deploy, continuous integration]
---

# CI/CD Patterns

Best practices and anti-patterns for CI/CD pipelines, focusing on GitHub Actions but applicable to other CI systems. Run the linter on every workflow file before review; use this prose guidance to explain findings and propose fixes.

## Purpose

- Ensure pipelines are fast, reliable, and secure
- Prevent common mistakes that cause build failures or security issues
- Establish patterns for maintainable pipeline configurations

---

## Core Patterns

### Pattern 1: Parallel Job Execution

**When to use:** Multiple independent tasks in pipeline.

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm run lint

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm test

  # Only deploy after all checks pass
  deploy:
    needs: [lint, test]
    runs-on: ubuntu-latest
    steps:
      - run: ./deploy.sh
```

### Pattern 2: Dependency Caching

**When to use:** Repeated dependency installation across runs.

```yaml
- name: Cache dependencies
  uses: actions/cache@v4
  with:
    path: ~/.npm
    key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
    restore-keys: |
      ${{ runner.os }}-node-

- name: Install dependencies
  run: npm ci
```

### Pattern 3: Safe Deployments with Health Checks

```yaml
deploy:
  steps:
    - name: Deploy
      run: kubectl apply -f deployment.yaml

    - name: Wait for rollout
      run: kubectl rollout status deployment/app --timeout=5m

    - name: Health check
      run: curl -f https://app.example.com/health || exit 1

    - name: Rollback on failure
      if: failure()
      run: kubectl rollout undo deployment/app
```

---

## Anti-Patterns

### Anti-Pattern 1: Hardcoded Secrets

| Aspect | Description |
|--------|-------------|
| **WHY** | Secrets in code are exposed in logs, version history, and forks. Security breach risk. |
| **DETECTION** | API keys, passwords, tokens directly in workflow files. |
| **FIX** | Use GitHub Secrets. Reference via `${{ secrets.NAME }}`. |

### Anti-Pattern 2: Unpinned Action Versions

| Aspect | Description |
|--------|-------------|
| **WHY** | Branch refs are mutable — a compromised action repo can inject malicious code into your pipeline without any change to your workflow file. |
| **DETECTION** | `uses: owner/repo@branch` or `uses: owner/repo@vN` without a full SHA. |
| **FIX** | Pin to full commit SHA: `uses: actions/checkout@abc123...  # v4.1.0`. Check dependabot or Renovate to keep SHAs current. |

### Anti-Pattern 3: Missing Timeout

| Aspect | Description |
|--------|-------------|
| **WHY** | Hanging builds waste resources and block pipelines. Default 6-hour timeout is too long. |
| **DETECTION** | No `timeout-minutes` at job level. |
| **FIX** | Set explicit `timeout-minutes` per job (typically 2–3× normal run time). |

### Anti-Pattern 4: Missing Permissions Block

| Aspect | Description |
|--------|-------------|
| **WHY** | GITHUB_TOKEN defaults to broad write access on many repositories. Overpermissioned tokens are a lateral movement risk if a step is compromised. |
| **DETECTION** | No `permissions` block at workflow or job level. Flagged by OSSF Scorecard Token-Permissions check. |
| **FIX** | Add `permissions: read-all` at workflow level, then narrow per-job as needed. |

---

## Validation Checklist

### Implementation
- [ ] All secrets use `${{ secrets.NAME }}` syntax
- [ ] Actions pinned to full commit SHA
- [ ] Permissions block present (workflow or job level)
- [ ] Independent jobs run in parallel
- [ ] Timeouts set on jobs
- [ ] Health checks after deployments
- [ ] Rollback mechanism in place

---

## Invocation — CI/CD Linter (L3 Script)

Run the linter on every workflow file before review. Consume its **output only** — the script source never enters context.

**Input:** JSON representation of the GitHub Actions workflow. YAML must be converted to JSON first.

**YAML to JSON conversion:**
```bash
python3 -c "import sys,json,yaml; print(json.dumps(yaml.safe_load(sys.stdin)))" < .github/workflows/ci.yml \
  | python .claude/skills/devops/ci-cd-patterns/scripts/cicd_lint.py -
```

Or with `yq`:
```bash
yq -o json .github/workflows/ci.yml | python .claude/skills/devops/ci-cd-patterns/scripts/cicd_lint.py -
```

**Run via Bash (file argument — JSON):**
```bash
python .claude/skills/devops/ci-cd-patterns/scripts/cicd_lint.py workflow.json
```

**Input format:**
```json
{
  "name": "CI",
  "on": {"push": {"branches": ["main"]}},
  "permissions": "read-all",
  "jobs": {
    "build": {
      "runs-on": "ubuntu-latest",
      "timeout-minutes": 30,
      "permissions": {"contents": "read"},
      "steps": [
        {"name": "Checkout", "uses": "actions/checkout@<sha>"},
        {"name": "Test", "run": "npm test"}
      ]
    }
  }
}
```

**Output:**
1. JSON object with `findings` array (each finding has `id`, `severity`, `job`, `title`, `detail`, `reference`) and `summary` counts.
2. Markdown findings table sorted by severity (CRITICAL → HIGH → MEDIUM).

**Findings covered:**

| ID | Check | Severity | Source |
|----|-------|----------|--------|
| CICD-001 | Unpinned action (branch = CRITICAL, tag = HIGH) | CRITICAL/HIGH | GitHub Actions Security Hardening Guide |
| CICD-002 | Missing timeout-minutes on job | MEDIUM | GitHub Actions docs |
| CICD-003 | No permissions block (workflow or job level) | HIGH | OSSF Scorecard Token-Permissions |
| CICD-004 | Hardcoded secret in env block or run command | CRITICAL | GitHub Actions encrypted secrets docs |

**What to do with the output:**
1. CRITICAL findings (hardcoded secrets, branch-pinned actions) must be blocked — these are supply-chain and credential exposure risks.
2. HIGH findings must be addressed before the workflow is merged to the default branch.
3. MEDIUM findings should be addressed; document exceptions.

**Error handling:** Script exits non-zero on I/O failure or if the input is missing the `jobs` field (required). Exits 0 for valid input including empty input and finding-present input.

---

## Quick Reference

| Task | Pattern |
|------|---------|
| Speed up builds | Add caching, parallelize jobs |
| Secure secrets | Use `${{ secrets.NAME }}` |
| Supply-chain safety | Pin actions to full SHA |
| Least-privilege token | Add permissions block |
| Safe deployments | Health checks + rollback |
| Prevent hangs | Set timeout-minutes |
