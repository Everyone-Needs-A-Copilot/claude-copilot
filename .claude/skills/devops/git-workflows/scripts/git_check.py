#!/usr/bin/env python3
"""
Git Convention Checker — L3 executable for the git-workflows skill.

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON object with optional fields:
  {
    "commits": [
      "feat(auth): add OAuth2 login support",
      "bad commit message",
      ...
    ],
    "branches": [
      "feature/user-authentication",
      "UPPERCASE-branch",
      ...
    ]
  }

  Either or both keys may be present. Empty arrays are valid.

Output (stdout):
  1. JSON object with 'findings' array and 'summary' counts.
  2. Markdown findings table.

Exit codes:
  0 — success (including empty input and findings-present input)
  1 — invalid input (bad JSON, wrong types, file not found)

Checks and their sources:
  GIT-001  Commit message does not follow Conventional Commits spec
           — Conventional Commits 1.0.0: https://www.conventionalcommits.org/en/v1.0.0/
           — Format: <type>[optional scope]: <description>
           — Valid types: feat, fix, docs, style, refactor, perf, test, chore, build, ci, revert
  GIT-002  Branch name violates naming convention
           — Common team convention: <prefix>/<short-description-kebab-case>
           — Prefixes: feature/, fix/, hotfix/, release/, chore/, docs/, refactor/
           — Name must be lowercase kebab-case; no spaces, uppercase, or special chars

Severity ranks:
  HIGH   = 2  (commit messages are git history — uncorrectable after merge)
  MEDIUM = 3  (branch names are correctable before merge)

Design note on git-workflows deterministic core:
  Branching strategy choice (GitFlow vs trunk-based) and rebase vs merge policy are
  prose judgment that depends on team context. The deterministic core here is limited
  to format validation against two closed specifications (Conventional Commits 1.0.0
  and a conventional branch naming scheme). Everything else in this skill is prose.
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------
HIGH = "HIGH"
MEDIUM = "MEDIUM"

SEVERITY_RANK = {HIGH: 2, MEDIUM: 3}

# ---------------------------------------------------------------------------
# Conventional Commits 1.0.0 — https://www.conventionalcommits.org/en/v1.0.0/
# ---------------------------------------------------------------------------

# Valid type keywords from the Conventional Commits spec + Angular convention
# Source: https://www.conventionalcommits.org/ + Angular commit message guidelines
VALID_COMMIT_TYPES = frozenset([
    "feat",     # A new feature
    "fix",      # A bug fix
    "docs",     # Documentation only
    "style",    # Formatting, no code change
    "refactor", # Code restructuring, no behavior change
    "perf",     # Performance improvement
    "test",     # Adding or fixing tests
    "chore",    # Build, tooling, dependencies
    "build",    # Build system changes
    "ci",       # CI configuration changes
    "revert",   # Reverts a previous commit
])

# Conventional Commits format: type(scope)!: description  or  type!: description
# Breaking change indicator: ! after type/scope
# Description must be non-empty after the colon+space
CONVENTIONAL_COMMIT_RE = re.compile(
    r"^"
    r"(?P<type>[a-z]+)"           # type: lowercase word
    r"(?:\((?P<scope>[^)]+)\))?"  # optional (scope)
    r"(?P<breaking>!)?"           # optional ! for breaking change
    r":\s+"                       # colon + space (required)
    r"(?P<description>.+)"        # non-empty description
    r"$",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Branch naming convention
# ---------------------------------------------------------------------------

# Valid branch prefixes (conventional)
VALID_BRANCH_PREFIXES = frozenset([
    "feature",
    "feat",
    "fix",
    "hotfix",
    "release",
    "chore",
    "docs",
    "refactor",
    "perf",
    "test",
    "ci",
    "build",
    "spike",
    "experiment",
    "dependabot",  # automated dependency updates
])

# Protected branches that are never linted
PROTECTED_BRANCHES = frozenset(["main", "master", "develop", "dev", "staging", "production", "prod"])

# Branch name must be: prefix/description in lowercase-kebab-case
# Description part: lowercase letters, digits, hyphens only
BRANCH_RE = re.compile(
    r"^"
    r"(?P<prefix>[a-z][a-z0-9-]*)"  # prefix: lowercase
    r"/"                              # separator
    r"(?P<description>[a-z0-9][a-z0-9_-]*)"  # description: lowercase kebab/snake
    r"$",
)

# Pattern to detect uppercase or spaces (quick reject)
UPPERCASE_OR_SPACE_RE = re.compile(r"[A-Z\s]")


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------

def check_commit_message(message: str, index: int) -> list[dict]:
    """GIT-001: Validate a single commit message against Conventional Commits 1.0.0."""
    # Strip leading/trailing whitespace
    msg = message.strip()
    if not msg:
        return []  # Empty message: skip (separate policy concern)

    # Skip merge commit messages (auto-generated)
    if msg.startswith("Merge ") or msg.startswith("Revert \""):
        return []

    match = CONVENTIONAL_COMMIT_RE.match(msg)
    if not match:
        return [{
            "id": "GIT-001",
            "severity": HIGH,
            "item": message[:60],
            "index": index,
            "title": f"Non-conventional commit message (#{index + 1}): {message[:50]!r}",
            "detail": (
                f"Commit #{index + 1} does not follow Conventional Commits 1.0.0 format. "
                "Required: <type>[(<scope>)][!]: <description> "
                "(e.g., 'feat(auth): add login endpoint'). "
                f"Valid types: {', '.join(sorted(VALID_COMMIT_TYPES))}."
            ),
            "reference": "Conventional Commits 1.0.0 — https://www.conventionalcommits.org/",
        }]

    commit_type = match.group("type")
    if commit_type not in VALID_COMMIT_TYPES:
        return [{
            "id": "GIT-001",
            "severity": HIGH,
            "item": message[:60],
            "index": index,
            "title": f"Unknown commit type '{commit_type}' (#{index + 1}): {message[:50]!r}",
            "detail": (
                f"Commit type '{commit_type}' is not in the Conventional Commits valid type set. "
                f"Valid types: {', '.join(sorted(VALID_COMMIT_TYPES))}."
            ),
            "reference": "Conventional Commits 1.0.0 — https://www.conventionalcommits.org/",
        }]

    return []  # Valid


def check_branch_name(branch: str, index: int) -> list[dict]:
    """GIT-002: Validate a branch name against naming conventions."""
    name = branch.strip()
    if not name:
        return []

    # Protected branches are exempt
    if name in PROTECTED_BRANCHES:
        return []

    findings = []

    # Quick fail: uppercase or spaces
    if UPPERCASE_OR_SPACE_RE.search(name):
        findings.append({
            "id": "GIT-002",
            "severity": MEDIUM,
            "item": name,
            "index": index,
            "title": f"Branch name has uppercase or spaces: {name!r}",
            "detail": (
                f"Branch '{name}' contains uppercase letters or spaces. "
                "Use lowercase-kebab-case: prefix/short-description (e.g., feature/user-auth). "
                "Uppercase branch names cause issues on case-insensitive filesystems (macOS/Windows)."
            ),
            "reference": "Git branch naming convention",
        })
        return findings  # No point checking further

    # Must match prefix/description pattern
    if not BRANCH_RE.match(name):
        findings.append({
            "id": "GIT-002",
            "severity": MEDIUM,
            "item": name,
            "index": index,
            "title": f"Branch name doesn't follow prefix/description pattern: {name!r}",
            "detail": (
                f"Branch '{name}' does not follow the <prefix>/<description> naming convention. "
                f"Use a recognised prefix: {', '.join(sorted(VALID_BRANCH_PREFIXES))}. "
                "Example: feature/user-authentication, fix/login-null-pointer."
            ),
            "reference": "Git branch naming convention",
        })
        return findings

    # Check prefix is in the recognised set
    match = BRANCH_RE.match(name)
    prefix = match.group("prefix")
    if prefix not in VALID_BRANCH_PREFIXES:
        findings.append({
            "id": "GIT-002",
            "severity": MEDIUM,
            "item": name,
            "index": index,
            "title": f"Unrecognised branch prefix '{prefix}': {name!r}",
            "detail": (
                f"Branch '{name}' uses prefix '{prefix}' which is not in the recognised set. "
                f"Use one of: {', '.join(sorted(VALID_BRANCH_PREFIXES))}."
            ),
            "reference": "Git branch naming convention",
        })

    return findings


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def check_all(data: dict) -> list[dict]:
    """Run all checks on commits and branches."""
    findings = []

    for i, msg in enumerate(data.get("commits", [])):
        findings.extend(check_commit_message(msg, i))

    for i, branch in enumerate(data.get("branches", [])):
        findings.extend(check_branch_name(branch, i))

    findings.sort(key=lambda f: (SEVERITY_RANK.get(f["severity"], 99), f["id"], f.get("index", 0)))
    return findings


def render_markdown(findings: list[dict]) -> str:
    if not findings:
        return "_No issues found._\n"
    lines = [
        "| # | ID | Severity | Item | Title |",
        "|---|----|----------|------|-------|",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(
            f"| {i} | {f['id']} | {f['severity']} | {f['item'][:40]} | {f['title'][:60]} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_input(source: str | None) -> dict | None:
    """Load JSON from file or stdin."""
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
            f"Input from {label} must be a JSON object with 'commits' and/or 'branches' arrays, "
            f"got {type(data).__name__}"
        )

    # Validate field types if present
    for field in ("commits", "branches"):
        if field in data and not isinstance(data[field], list):
            raise ValueError(
                f"Field '{field}' must be an array of strings, "
                f"got {type(data[field]).__name__}"
            )
        if field in data:
            for i, item in enumerate(data[field]):
                if not isinstance(item, str):
                    raise ValueError(
                        f"'{field}[{i}]' must be a string, got {type(item).__name__}"
                    )

    return data


def run(source: str | None) -> int:
    try:
        data = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if data is None:
        output = {"findings": [], "summary": {"total": 0, "high": 0, "medium": 0}}
        print(json.dumps(output, indent=2))
        print()
        print("_No input provided._")
        return 0

    findings = check_all(data)

    summary = {
        "total": len(findings),
        "high": sum(1 for f in findings if f["severity"] == HIGH),
        "medium": sum(1 for f in findings if f["severity"] == MEDIUM),
        "commits_checked": len(data.get("commits", [])),
        "branches_checked": len(data.get("branches", [])),
    }

    output = {"findings": findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()

    print("## Git Convention Checker Findings\n")
    print(render_markdown(findings))
    if findings:
        print(
            "**Severity:** HIGH = commit message (permanent once merged) | "
            "MEDIUM = branch name (correctable)"
        )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Git convention checker. Validates commit messages (Conventional Commits 1.0.0) "
            "and branch names against a conventional naming scheme."
        ),
        epilog=(
            'Input: JSON object with "commits" (array of strings) and/or '
            '"branches" (array of strings). Pass file path or \'-\' for stdin.'
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to JSON input file, or '-' for stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
