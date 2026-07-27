---
name: git-workflows
skill_category: devops
description: >-
  Git workflows, branching strategies (gitflow, trunk-based), Conventional
  Commits, commit message quality, version control best practices, and
  pull-request conventions — with deterministic convention checker script. Use
  proactively when reviewing commit message quality before merge, enforcing
  branch naming conventions, onboarding a team to Conventional Commits, or
  running a CI hook that validates commits in a PR. Run the checker for
  deterministic commit and branch convention validation.
version: 2.0.0
source: .claude/skills/devops/git-workflows.md (retired flat file); L3 checker added 2026-05-20
when_to_use:
  - Reviewing commit message quality before merge
  - Enforcing branch naming conventions in a project
  - Onboarding a team to Conventional Commits
  - CI hook that validates commits in a PR
allowed-tools:
  - Bash
  - Read
  - Edit
  - Glob
  - Grep
tags: [git, version-control, branching, commits, workflow, collaboration]
trigger_files: [".git/config", ".gitignore", ".gitattributes", "CONTRIBUTING.md"]
trigger_keywords: [git, commit, branch, merge, rebase, pull request, PR, version control, gitflow, trunk-based]
---

# Git Workflows

Best practices for Git version control, branching strategies, and commit conventions. Run the convention checker on commit message batches before merge; use this prose guidance for strategy and workflow decisions (those are judgment calls the script does not make).

## Purpose

- Establish consistent Git workflows across projects
- Ensure clean, meaningful commit history
- Prevent common Git mistakes and conflicts
- Facilitate effective code collaboration

---

## Commit Message Convention

Use **Conventional Commits** format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Valid Types

| Type | When to Use |
|------|-------------|
| `feat` | New feature for users |
| `fix` | Bug fix for users |
| `docs` | Documentation only |
| `style` | Formatting, no code change |
| `refactor` | Code restructuring, no behavior change |
| `perf` | Performance improvement |
| `test` | Adding/fixing tests |
| `chore` | Build, tooling, dependencies |
| `build` | Build system changes |
| `ci` | CI configuration changes |
| `revert` | Reverts a previous commit |

### Examples

```bash
git commit -m "feat(auth): add OAuth2 login support"
git commit -m "fix(api): handle null response from payment service"
git commit -m "feat(api)!: change response format to JSON:API spec"
# Breaking change: add BREAKING CHANGE footer
```

**Why Conventional Commits matter:** Enables automated changelogs, semantic versioning, and clear history archaeology. Once committed and merged, a commit message cannot be changed without rewriting history — enforce format before merge, not after.

---

## Branching Strategies

### Trunk-Based Development (Recommended)

**Best for:** Teams with strong CI/CD, frequent releases.

```
main ────●────●────●────●────●────●────
          \        /
           ●──────●  (short-lived feature branch)
```

**Rules:**
- Feature branches live < 2 days
- Merge to main frequently
- Use feature flags for incomplete work
- main is always deployable

### GitFlow

**Best for:** Scheduled releases, multiple versions in production.

**Branches:** `main`, `develop`, `feature/*`, `release/*`, `hotfix/*`

Prefer trunk-based for new projects. Only adopt GitFlow when you genuinely maintain multiple production versions simultaneously.

---

## Branch Naming Convention

Format: `<prefix>/<description-in-kebab-case>`

**Valid prefixes:** `feature`, `feat`, `fix`, `hotfix`, `release`, `chore`, `docs`, `refactor`, `perf`, `test`, `ci`, `build`, `spike`, `experiment`, `dependabot`

**Rules:**
- All lowercase
- Kebab-case description (hyphens, not underscores or spaces)
- No special characters except `-` and `/`
- Protected branches (`main`, `master`, `develop`, `staging`) are exempt

**Examples:**
```bash
feature/user-authentication
fix/login-null-pointer
hotfix/payment-crash-prod
release/v2-0-0
chore/update-ci-deps
```

---

## Common Workflows

### Starting New Feature

```bash
git checkout main && git pull --rebase origin main
git checkout -b feature/user-authentication
# work, commit following Conventional Commits
git push -u origin feature/user-authentication
```

### Updating Feature Branch with Main

```bash
git fetch origin
git rebase origin/main
# resolve conflicts if any, then:
git push --force-with-lease
```

---

## Anti-Patterns

### Anti-Pattern 1: Force Push to Shared Branches

| Aspect | Description |
|--------|-------------|
| **WHY** | Overwrites others' work. Causes sync issues. Can lose commits. |
| **FIX** | Use `--force-with-lease` on feature branches only. Never force push shared branches. |

### Anti-Pattern 2: Committing Secrets

| Aspect | Description |
|--------|-------------|
| **WHY** | Secrets in git history are permanent. Even after removal, they're in history. |
| **FIX** | Use `.gitignore` for `.env` files. If leaked, rotate credentials immediately. |

### Anti-Pattern 3: Giant Commits

| Aspect | Description |
|--------|-------------|
| **WHY** | Hard to review. Difficult to revert. Obscures history. |
| **FIX** | Commit early, commit often. One logical change per commit. |

---

## Invocation — Git Convention Checker (L3 Script)

Run the checker on commit messages and branch names before merge. Consume its **output only** — the script source never enters context.

**What the script checks (deterministic, closed specification):**
- **GIT-001:** Commit messages against Conventional Commits 1.0.0 format + valid type set
- **GIT-002:** Branch names against `<prefix>/<kebab-case-description>` convention

**What the script does NOT check (prose judgment):**
- Whether a branching strategy (trunk-based vs GitFlow) is appropriate for the team
- Whether a commit message is descriptive enough
- Whether commits are atomic or too large
- Rebase vs merge policy

**Input format:**
```json
{
  "commits": [
    "feat(auth): add OAuth2 login support",
    "fixed the thing"
  ],
  "branches": [
    "feature/user-authentication",
    "FEATURE/Auth"
  ]
}
```

Either key may be omitted. Empty arrays are valid.

**Run via Bash (stdin):**
```bash
echo '{"commits": ["feat: add login", "bad message"], "branches": ["feature/auth"]}' \
  | python .claude/skills/devops/git-workflows/scripts/git_check.py -
```

**Run via Bash (file argument):**
```bash
python .claude/skills/devops/git-workflows/scripts/git_check.py input.json
```

**Extract commits from git log for a PR branch:**
```bash
git log origin/main..HEAD --format="%s" \
  | python3 -c "import sys,json; print(json.dumps({'commits': sys.stdin.read().splitlines()}))" \
  | python .claude/skills/devops/git-workflows/scripts/git_check.py -
```

**Output:**
1. JSON object with `findings` array (each finding has `id`, `severity`, `item`, `title`, `detail`, `reference`) and `summary` with counts and total commits/branches checked.
2. Markdown findings table.

**Findings:**

| ID | Check | Severity | Source |
|----|-------|----------|--------|
| GIT-001 | Non-conventional commit message | HIGH | Conventional Commits 1.0.0 |
| GIT-002 | Branch name violates naming convention | MEDIUM | Team branch naming convention |

**What to do with the output:**
1. GIT-001 findings on un-merged commits: request changes before merge. Commit messages are permanent once in shared history.
2. GIT-002 findings: rename the branch before opening a PR (git branch -m old-name new-name).
3. The script exits 0 even with findings — the agent decides what to block on.

**Error handling:** Exits non-zero on bad JSON, wrong field types, or file not found. Exits 0 for valid input including empty input.

---

## Safety Rules

1. **Never force push to main/develop** — Use `--force-with-lease` only on feature branches
2. **Never commit secrets** — Use `.gitignore` and secret managers
3. **Never rewrite shared history** — Only rebase unpushed or personal branches
4. **Always pull before push** — Avoid unnecessary merge conflicts
5. **Keep commits atomic** — One logical change per commit
