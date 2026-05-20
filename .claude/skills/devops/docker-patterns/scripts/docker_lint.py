#!/usr/bin/env python3
"""
Docker Linter — L3 executable for the docker-patterns skill.

Input (file path as first argument, or '-'/no-arg for stdin):
  The raw text content of a Dockerfile (not JSON).
  Pass '-' or omit argument to read from stdin.

Output (stdout):
  1. JSON object with 'findings' array and 'summary' counts, sorted by severity rank.
  2. Markdown findings table.

Exit codes:
  0 — success (including empty input and findings-present input)
  1 — invalid input (cannot read file)

Checks and their sources:
  DOCKER-001  Running as root (no USER directive)
              — CIS Docker Benchmark 4.1
  DOCKER-002  :latest tag on FROM (or no tag)
              — Docker best practices; unpredictable, breaks reproducibility
  DOCKER-003  Missing HEALTHCHECK
              — Docker best practices; required for orchestrator health signalling
  DOCKER-004  apt-get without --no-install-recommends
              — Docker slim-image best practice; inflates image size
  DOCKER-005  Secret-like value in ENV or ARG
              — CIS Docker Benchmark 4.10; secrets persist in image history
  DOCKER-006  Layer-bloat signal: RUN apt-get/apk without cleanup in same layer
              — Docker best practices; each RUN creates a layer; cache must be cleared
  DOCKER-007  COPY . . before dependency manifest copy
              — Docker cache optimisation; source copy before deps invalidates cache

Severity ranks (for sorting; agent decides what to block on):
  CRITICAL = 1  (security — secrets in image, running as root)
  HIGH     = 2  (security / reliability — latest tag, no health check)
  MEDIUM   = 3  (size / cache efficiency)
  INFO     = 4  (advisory)
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Severity constants — sourced above in module docstring
# ---------------------------------------------------------------------------
CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
INFO = "INFO"

# Rank for sort order (lower = more severe)
SEVERITY_RANK = {CRITICAL: 1, HIGH: 2, MEDIUM: 3, INFO: 4}

# ---------------------------------------------------------------------------
# Patterns — all named constants, no magic literals
# ---------------------------------------------------------------------------

# FROM line: captures image name and optional tag/digest
# Matches: FROM [--platform=...] <image>[:<tag>][@<digest>] [AS <name>]
FROM_PATTERN = re.compile(
    r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+?)(?:\s+AS\s+\S+)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# USER directive: any non-root explicit user
USER_PATTERN = re.compile(r"^\s*USER\s+(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

# HEALTHCHECK directive (including HEALTHCHECK NONE which is explicit opt-out)
HEALTHCHECK_PATTERN = re.compile(r"^\s*HEALTHCHECK\b", re.IGNORECASE | re.MULTILINE)

# apt-get install without --no-install-recommends
# Matches 'apt-get install' lines that do NOT contain --no-install-recommends
APT_INSTALL_PATTERN = re.compile(r"apt-get\s+install\b", re.IGNORECASE)
APT_NO_RECOMMENDS_PATTERN = re.compile(r"--no-install-recommends", re.IGNORECASE)

# Secret-like ENV/ARG patterns
# Flags: ENV KEY=value or ARG KEY=value where value looks like a secret.
# Uses (?:^|_) / (?:_|$) instead of \b because underscores are word characters
# in Python regex, so \b does not act as a segment boundary inside names like
# DATABASE_PASSWORD or SECRET_TOKEN. The pattern matches the secret word as a
# complete underscore-delimited segment of the key name.
# Source: common secret key names (conservative list to avoid false positives)
SECRET_KEY_NAMES = re.compile(
    r"(?:^|_)(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|ACCESS_KEY|"
    r"AUTH_KEY|CREDENTIALS|DATABASE_URL|DB_PASSWORD|DB_PASS)(?:_|$)",
    re.IGNORECASE,
)
ENV_ARG_WITH_VALUE = re.compile(
    r"^\s*(ENV|ARG)\s+(.+)\s*$", re.IGNORECASE | re.MULTILINE
)

# apt-get/apk update or install in a RUN without cleanup in same instruction
# Looks for RUN lines containing package manager invocations
RUN_APT_PATTERN = re.compile(r"apt-get\s+(?:update|install)\b", re.IGNORECASE)
RUN_APT_CLEANUP = re.compile(r"rm\s+-rf\s+/var/lib/apt/lists", re.IGNORECASE)
RUN_APK_PATTERN = re.compile(r"apk\s+(?:add|update)\b", re.IGNORECASE)
RUN_APK_CLEANUP = re.compile(r"--no-cache\b", re.IGNORECASE)

# Instruction boundary: each RUN block (handles line continuations with \).
# The lookahead (?=\n\s*[A-Z]|\n?\Z) matches either a following Dockerfile
# instruction (newline + uppercase letter) or end-of-content with optional
# trailing newline. The \n?\Z branch is required when the RUN block is the
# last instruction in the file (content may end with \n or without).
RUN_BLOCK_PATTERN = re.compile(
    r"^\s*RUN\s+((?:.|\\\n)*?)(?=\n\s*[A-Z]|\n?\Z)",
    re.MULTILINE,
)

# COPY . . before a dependency manifest copy heuristic
# Detects COPY . . or COPY ./ ./ (broad context copy)
COPY_ALL_PATTERN = re.compile(r"^\s*COPY\s+\.\s+\.\s*$", re.IGNORECASE | re.MULTILINE)
# Dependency manifests that should come before COPY . .
DEP_MANIFEST_COPY = re.compile(
    r"^\s*COPY\s+.*(?:package(?:-lock)?\.json|requirements(?:[\w.-]*)?\.txt|"
    r"Pipfile(?:\.lock)?|poetry\.lock|go\.(?:mod|sum)|Gemfile(?:\.lock)?|"
    r"pom\.xml|build\.gradle|Cargo\.toml)\b",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Root-user detection helpers
# ---------------------------------------------------------------------------

def _is_root_user(user_val: str) -> bool:
    """Return True if the USER value indicates root."""
    stripped = user_val.strip().split(":")[0]  # handle user:group
    return stripped in ("root", "0")


# ---------------------------------------------------------------------------
# Core checks
# ---------------------------------------------------------------------------

def check_root_user(content: str) -> list[dict]:
    """DOCKER-001: No USER directive, or USER root."""
    findings = []
    user_matches = USER_PATTERN.findall(content)

    if not user_matches:
        findings.append({
            "id": "DOCKER-001",
            "severity": CRITICAL,
            "title": "No USER directive — container runs as root",
            "detail": (
                "No USER instruction found. Containers default to root, which means a "
                "container escape gives the attacker root on the host. Add a non-root USER "
                "before the final CMD/ENTRYPOINT."
            ),
            "reference": "CIS Docker Benchmark §4.1",
        })
    else:
        root_users = [u for u in user_matches if _is_root_user(u)]
        if root_users and len(root_users) == len(user_matches):
            # All USER directives set root (or no non-root USER ever set)
            findings.append({
                "id": "DOCKER-001",
                "severity": CRITICAL,
                "title": f"USER set to root (USER {root_users[-1].strip()})",
                "detail": (
                    "The final USER directive sets the process to root. "
                    "Use a named non-root user (e.g., appuser with uid >=1000) "
                    "for the runtime stage."
                ),
                "reference": "CIS Docker Benchmark §4.1",
            })
    return findings


def check_latest_tag(content: str) -> list[dict]:
    """DOCKER-002: FROM uses :latest or no tag."""
    findings = []
    for match in FROM_PATTERN.finditer(content):
        image_ref = match.group(1)
        # Skip scratch and ARG-interpolated images
        if image_ref.lower() == "scratch" or image_ref.startswith("$"):
            continue
        # Has a digest pin → OK
        if "@sha256:" in image_ref:
            continue
        # Has a tag that is not :latest → OK
        if ":" in image_ref and not image_ref.endswith(":latest"):
            continue
        tag = ":latest" if ":latest" in image_ref else "(no tag)"
        findings.append({
            "id": "DOCKER-002",
            "severity": HIGH,
            "title": f"FROM uses unpinned tag: {image_ref} {tag}",
            "detail": (
                f"Image '{image_ref}' uses :latest or no tag. This makes builds "
                "non-reproducible — the same Dockerfile can pull different images on "
                "different days. Pin to a specific version or digest."
            ),
            "reference": "Docker best practices — pinned base images",
        })
    return findings


def check_healthcheck(content: str) -> list[dict]:
    """DOCKER-003: Missing HEALTHCHECK."""
    if not HEALTHCHECK_PATTERN.search(content):
        return [{
            "id": "DOCKER-003",
            "severity": HIGH,
            "title": "Missing HEALTHCHECK directive",
            "detail": (
                "No HEALTHCHECK instruction found. Without it, Docker/Kubernetes cannot "
                "distinguish a started container from a healthy one. Add HEALTHCHECK with "
                "appropriate --interval, --timeout, --start-period, and --retries values. "
                "If health checks are managed externally, add HEALTHCHECK NONE explicitly."
            ),
            "reference": "Docker best practices — container health",
        }]
    return []


def check_apt_no_install_recommends(content: str) -> list[dict]:
    """DOCKER-004: apt-get install without --no-install-recommends."""
    findings = []
    for match in RUN_BLOCK_PATTERN.finditer(content):
        block = match.group(1)
        if APT_INSTALL_PATTERN.search(block) and not APT_NO_RECOMMENDS_PATTERN.search(block):
            # Extract a short snippet for context
            snippet = block.strip().splitlines()[0][:80]
            findings.append({
                "id": "DOCKER-004",
                "severity": MEDIUM,
                "title": "apt-get install without --no-install-recommends",
                "detail": (
                    f"RUN block starts with: {snippet!r}. "
                    "Without --no-install-recommends, apt installs suggested and "
                    "recommended packages, significantly inflating image size. "
                    "Add --no-install-recommends to every apt-get install."
                ),
                "reference": "Docker slim-image best practices",
            })
    return findings


def check_secrets_in_env(content: str) -> list[dict]:
    """DOCKER-005: Secret-like variable name in ENV or ARG with a value."""
    findings = []
    seen_keys: set[str] = set()
    for match in ENV_ARG_WITH_VALUE.finditer(content):
        directive = match.group(1).upper()
        rest = match.group(2)
        # ENV/ARG can set multiple vars: KEY=val KEY2=val2
        # Simple split: look for KEY=value pairs or just KEY
        pairs = re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=\S+', rest)
        for key in pairs:
            if SECRET_KEY_NAMES.search(key) and key not in seen_keys:
                seen_keys.add(key)
                findings.append({
                    "id": "DOCKER-005",
                    "severity": CRITICAL,
                    "title": f"Secret-like value in {directive}: {key}",
                    "detail": (
                        f"{directive} {key}=... bakes a credential into the image. "
                        "Values set in ENV/ARG persist in the image layer history and are "
                        "visible via 'docker inspect'. Use Docker secrets (--secret), "
                        "Vault, or runtime environment injection instead."
                    ),
                    "reference": "CIS Docker Benchmark §4.10",
                })
    return findings


def check_layer_bloat(content: str) -> list[dict]:
    """DOCKER-006: apt-get/apk without cache cleanup in the same RUN layer."""
    findings = []
    for match in RUN_BLOCK_PATTERN.finditer(content):
        block = match.group(1)
        if RUN_APT_PATTERN.search(block) and not RUN_APT_CLEANUP.search(block):
            snippet = block.strip().splitlines()[0][:80]
            findings.append({
                "id": "DOCKER-006",
                "severity": MEDIUM,
                "title": "apt-get used without cache cleanup in same RUN layer",
                "detail": (
                    f"RUN block starts with: {snippet!r}. "
                    "apt-get leaves package lists in /var/lib/apt/lists/ which bloat the "
                    "layer. Add '&& rm -rf /var/lib/apt/lists/*' in the same RUN "
                    "instruction to keep the layer small."
                ),
                "reference": "Docker best practices — layer hygiene",
            })
        elif RUN_APK_PATTERN.search(block) and not RUN_APK_CLEANUP.search(block):
            snippet = block.strip().splitlines()[0][:80]
            findings.append({
                "id": "DOCKER-006",
                "severity": MEDIUM,
                "title": "apk add used without --no-cache",
                "detail": (
                    f"RUN block starts with: {snippet!r}. "
                    "apk without --no-cache writes to the local cache, bloating the layer. "
                    "Use 'apk add --no-cache <package>'."
                ),
                "reference": "Alpine Docker best practices",
            })
    return findings


def check_copy_order(content: str) -> list[dict]:
    """DOCKER-007: COPY . . appears before dependency manifest copies."""
    copy_all_matches = list(COPY_ALL_PATTERN.finditer(content))
    if not copy_all_matches:
        return []

    dep_manifest_matches = list(DEP_MANIFEST_COPY.finditer(content))
    if not dep_manifest_matches:
        return []  # No manifest to check order against

    findings = []
    first_copy_all = copy_all_matches[0].start()
    last_dep_manifest = max(m.start() for m in dep_manifest_matches)

    if first_copy_all < last_dep_manifest:
        findings.append({
            "id": "DOCKER-007",
            "severity": MEDIUM,
            "title": "COPY . . appears before dependency manifest COPY",
            "detail": (
                "COPY . . is placed before a dependency manifest COPY (e.g., package.json, "
                "requirements.txt). Any code change will invalidate the dependency "
                "install layer, forcing a full reinstall on every build. "
                "Reorder: copy manifests first, run install, then COPY . ."
            ),
            "reference": "Docker layer cache optimisation best practices",
        })
    return findings


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

ALL_CHECKS = [
    check_root_user,
    check_latest_tag,
    check_healthcheck,
    check_apt_no_install_recommends,
    check_secrets_in_env,
    check_layer_bloat,
    check_copy_order,
]


def lint_dockerfile(content: str) -> list[dict]:
    """Run all checks and return deduplicated findings sorted by severity."""
    all_findings = []
    for check in ALL_CHECKS:
        all_findings.extend(check(content))

    # Sort: severity rank first, then check ID
    all_findings.sort(key=lambda f: (SEVERITY_RANK[f["severity"]], f["id"]))
    return all_findings


def render_markdown(findings: list[dict]) -> str:
    """Render findings as a markdown table."""
    if not findings:
        return "_No issues found._\n"
    lines = [
        "| # | ID | Severity | Title |",
        "|---|----|----------|-------|",
    ]
    for i, f in enumerate(findings, 1):
        lines.append(
            f"| {i} | {f['id']} | {f['severity']} | {f['title']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_input(source: str | None) -> str:
    """Load Dockerfile text from file path or stdin."""
    if source is None or source == "-":
        return sys.stdin.read()
    try:
        with open(source, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        raise ValueError(f"Input file not found: {source}")
    except OSError as exc:
        raise ValueError(f"Cannot read input file '{source}': {exc}")


def run(source: str | None) -> int:
    """Main logic. Returns exit code."""
    try:
        content = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    content = content.strip()
    if not content:
        output = {"findings": [], "summary": {"total": 0, "critical": 0, "high": 0, "medium": 0, "info": 0}}
        print(json.dumps(output, indent=2))
        print()
        print("_No Dockerfile content provided._")
        return 0

    findings = lint_dockerfile(content)

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

    print("## Docker Linter Findings\n")
    print(render_markdown(findings))
    if findings:
        print(
            "**Severity:** CRITICAL = security (CIS/OWASP) | "
            "HIGH = reliability/security | MEDIUM = size/cache"
        )

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Docker linter. Reads a Dockerfile, outputs ranked findings as JSON + markdown.",
        epilog="Input: raw Dockerfile text (not JSON). Pass file path or '-' for stdin.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to Dockerfile, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
