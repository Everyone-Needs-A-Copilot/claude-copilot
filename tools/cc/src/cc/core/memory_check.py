"""memory_check.py — token-free drift detection for cc memory entries.

Phase 2 / Stream-B of PRD-7 (TASK-118).

Parses stored memory entries into typed "claims" and runs deterministic
checkers (pure Python, ZERO model tokens) against each claim:

  - path-exists      : referenced file paths exist on disk
  - command-resolves : binary or npm script is on PATH / in package.json
  - version-conflict : same package named with conflicting versions across entries
  - link-resolves    : edge/link frontmatter keys resolve to something meaningful
  - staleness        : entries not updated by any commit in N days

Negation-awareness (critical to avoid false positives):
  - Paths under negation markers ("not yet built", "removed", "deprecated",
    "NOT ", "not ", "n't ", "no longer") are skipped.
  - URL-shaped tokens (/api/x, /v1/y) are NOT treated as filesystem paths.
  - HTTP verbs followed by a path (GET /x, POST /api) are skipped.
  - <placeholder> / <name> template tokens are never checked.

Scoring: 100 − (error×10 + warning×3 + info×1), floored at 0.

Result shape mirrors .claude/hooks/lib/validation_result.py (CheckResult /
ValidationReport) but is defined locally to avoid cross-package import
complexity.  The shape is byte-identical so consumers can use either module.

Design decision: NOT importing validation_result from the hooks lib because:
  - cc lives in tools/cc with its own venv; .claude/hooks/lib is outside that
    package and would require sys.path hacks or a separate install step.
  - Mirroring the same dataclass shape keeps the contract stable without
    coupling two unrelated installation paths.
  - Documented in WP-125 architecture notes.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Result shape (mirrors validation_result.py — see module docstring)
# ---------------------------------------------------------------------------

Status = str   # "pass" | "fail" | "warn" | "info"

_SEVERITY: Dict[str, int] = {"fail": 2, "warn": 1, "info": 0, "pass": 0}
_SCORE_DEDUCT: Dict[str, int] = {"fail": 10, "warn": 3, "info": 1, "pass": 0}


@dataclass
class CheckResult:
    check: str
    status: Status
    message: str = ""
    expected: Optional[str] = None
    actual: Optional[str] = None
    artifact: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"check": self.check, "status": self.status}
        if self.expected is not None:
            d["expected"] = self.expected
        if self.actual is not None:
            d["actual"] = self.actual
        if self.message:
            d["message"] = self.message
        if self.artifact is not None:
            d["artifact"] = self.artifact
        return d


@dataclass
class EntryReport:
    """Check results for a single memory entry."""

    entry_id: str
    entry_type: str
    path: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.checks:
            return "pass"
        sev = max(_SEVERITY.get(c.status, 0) for c in self.checks)
        if sev >= 2:
            return "fail"
        if sev >= 1:
            return "warn"
        return "pass"

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "path": self.path,
            "verdict": self.verdict,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class MemoryCheckReport:
    """Aggregated report across all entries."""

    entries: List[EntryReport] = field(default_factory=list)
    cross_entry_checks: List[CheckResult] = field(default_factory=list)

    @property
    def score(self) -> int:
        """0–100: starts at 100, deducts per-severity."""
        deduction = 0
        for er in self.entries:
            for c in er.checks:
                deduction += _SCORE_DEDUCT.get(c.status, 0)
        for c in self.cross_entry_checks:
            deduction += _SCORE_DEDUCT.get(c.status, 0)
        return max(0, 100 - deduction)

    @property
    def verdict(self) -> str:
        all_checks = self.cross_entry_checks[:]
        for er in self.entries:
            all_checks.extend(er.checks)
        if not all_checks:
            return "pass"
        sev = max(_SEVERITY.get(c.status, 0) for c in all_checks)
        if sev >= 2:
            return "fail"
        if sev >= 1:
            return "warn"
        return "pass"

    def flagged(self) -> List[dict]:
        """Return only checks that are not 'pass'."""
        result = []
        for er in self.entries:
            for c in er.checks:
                if c.status != "pass":
                    result.append({"entry_id": er.entry_id, **c.to_dict()})
        for c in self.cross_entry_checks:
            if c.status != "pass":
                result.append({"entry_id": "cross-entry", **c.to_dict()})
        return result

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "entries": [er.to_dict() for er in self.entries],
            "cross_entry_checks": [c.to_dict() for c in self.cross_entry_checks],
            "flagged": self.flagged(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_shell_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ---------------------------------------------------------------------------
# Negation-awareness helpers
# ---------------------------------------------------------------------------

# Paragraph-level negation markers — if a paragraph heading or sentence
# contains one of these, paths within that paragraph are skipped.
_NEGATION_PATTERNS = re.compile(
    r"\b(not yet built|not yet|removed|deprecated|retired|no longer|"
    r"n't |NOT |never |planned|TODO|to-do|to be |future)\b",
    re.IGNORECASE,
)

# API/URL route detection — two-part:
# 1. Must start with /  followed by alphanumeric (a broad pattern)
# 2. Then apply refined logic in _is_url_route() to distinguish FS paths
_URL_ROUTE_RE = re.compile(r"^/[a-zA-Z0-9]")

# Known API route prefixes — paths starting with these are URL routes, not FS paths.
_API_ROUTE_PREFIX_RE = re.compile(r"^/(?:api|v\d+|graphql|rpc|ws|webhooks|oauth|auth)(?:/|$)", re.IGNORECASE)

# HTTP verb + path: GET /x, POST /api/y, PUT /...
_HTTP_VERB_PATH_RE = re.compile(
    r"^\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/", re.IGNORECASE
)

# Template placeholder: <something> or {{something}}
_PLACEHOLDER_RE = re.compile(r"^<[^>]+>$|^\{\{[^}]+\}\}$")

# Version reference: package@version or "package": "^1.2.3"
_VERSION_CLAIM_RE = re.compile(
    r'(?:'
    # npm-style  foo@^1.2.3  or foo@1.2
    r'([\w\-@/]+)@([^\s,;"\']+)'
    r'|'
    # JSON-style  "foo": "^1.2.3"
    r'"([\w\-@/]+)"\s*:\s*"([^"]+)"'
    r'|'
    # prose-style  foo version 1.2.3  /  foo v1.2.3
    r'\b([\w\-@/]+)\s+(?:version\s+|v)([\d][^\s,;"\']*)'
    r')',
    re.IGNORECASE,
)

# Filesystem path heuristic: starts with / or ~/ and has no URL scheme
_FS_PATH_RE = re.compile(r"(?:^|(?<=\s)|(?<=['\"`(]))(/[\w/.\-_]+|~/[\w/.\-_]+)")

# Backtick / inline-code path: `path/to/file` or `~/path`
_BACKTICK_PATH_RE = re.compile(r"`(/[\w/.\-_]+|~/[\w/.\-_]+|\.[\w/.\-_]+)`")

# Relative paths that are clearly file-like (contain a dot and a known extension)
_RELATIVE_PATH_EXT = re.compile(
    r"(?:^|(?<=\s)|(?<=['\"`(]))((?:\.{1,2}/)?[\w./\-]+\."
    r"(?:py|js|ts|tsx|sh|md|yaml|yml|json|toml|cfg|conf|env|txt|sql))"
)

# Command reference: backtick commands
_CMD_BACKTICK_RE = re.compile(r"`([a-zA-Z][\w/.\-]*)(?:\s[^`]*)?`")


def _split_paragraphs(text: str) -> List[Tuple[str, str]]:
    """Split body into (heading_or_empty, paragraph_text) pairs."""
    paragraphs: List[Tuple[str, str]] = []
    current_heading = ""
    current_lines: List[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if current_lines:
                paragraphs.append((current_heading, "\n".join(current_lines)))
                current_lines = []
            current_heading = line
        else:
            current_lines.append(line)
    if current_lines:
        paragraphs.append((current_heading, "\n".join(current_lines)))
    return paragraphs


def _is_negated_context(heading: str, paragraph: str) -> bool:
    """Return True if this paragraph is under a negation marker."""
    combined = heading + " " + paragraph
    return bool(_NEGATION_PATTERNS.search(combined))


def _is_url_route(token: str) -> bool:
    """Return True for URL API routes like /api/x or /v1/items (not filesystem paths).

    Heuristics applied in order:
    1. Must match the broad URL_ROUTE_RE (starts with /letter-or-digit).
    2. If it has a known API prefix (/api/, /v1/, /graphql/, etc.) → URL route.
    3. If it has a file extension (dot in last component) → NOT a URL route (FS path).
    4. If it has depth <= 2 and no known FS prefixes → URL route.
    5. Otherwise → NOT a URL route (treat as FS path to avoid false positives).

    Known FS prefixes: /private/, /var/, /usr/, /opt/, /tmp/, /etc/, /bin/
    and user home directories (Linux: /home/ subtree, macOS: /Users/ subtree)
    """
    if not _URL_ROUTE_RE.match(token):
        return False
    # Known API route prefixes — always treat as URL route
    if _API_ROUTE_PREFIX_RE.match(token):
        return True
    # File extension in last component → filesystem path
    last_component = token.rsplit("/", 1)[-1]
    if "." in last_component:
        return False
    # Known filesystem root prefixes → not a URL route
    _FS_ROOTS = ("/private/", "/var/", "/usr/", "/home/", "/opt/", "/tmp/", "/etc/",
                 "/bin/", "/sbin/", "/lib/", "/Applications/", "/Users/", "/Volumes/")
    for root in _FS_ROOTS:
        if token.startswith(root):
            return False
    # Short path (depth <= 2) without known FS prefix and no extension → URL route
    components = [c for c in token.split("/") if c]
    if len(components) <= 2:
        return True
    # Deep path without extension and without known FS prefix — conservative: not URL
    return False


def _is_placeholder(token: str) -> bool:
    """Return True for template placeholders like <name> or {{value}}."""
    return bool(_PLACEHOLDER_RE.match(token.strip()))


def _normalise_path(token: str) -> Path:
    """Expand ~ and return a Path."""
    return Path(token).expanduser()


# ---------------------------------------------------------------------------
# Claim types
# ---------------------------------------------------------------------------


@dataclass
class PathClaim:
    """A filesystem path mentioned in an entry."""

    raw: str
    source_entry_id: str
    negated: bool = False


@dataclass
class CommandClaim:
    """A command/binary referenced in an entry."""

    command: str
    source_entry_id: str


@dataclass
class VersionClaim:
    """A package version assertion in an entry."""

    package: str
    version: str
    source_entry_id: str


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------


def _extract_path_claims(entry_id: str, body: str) -> List[PathClaim]:
    """Extract filesystem path claims from entry body, with negation awareness."""
    claims: List[PathClaim] = []
    seen: set = set()

    for heading, paragraph in _split_paragraphs(body):
        negated = _is_negated_context(heading, paragraph)

        # Backtick paths (highest confidence)
        for m in _BACKTICK_PATH_RE.finditer(paragraph):
            token = m.group(1)
            if token in seen:
                continue
            seen.add(token)
            if _is_placeholder(token) or _is_url_route(token):
                continue
            # Skip HTTP verb lines
            line = _get_line_for_match(paragraph, m.start())
            if _HTTP_VERB_PATH_RE.match(line):
                continue
            line_negated = negated or bool(_NEGATION_PATTERNS.search(line))
            claims.append(PathClaim(raw=token, source_entry_id=entry_id, negated=line_negated))

        # Relative paths with known extensions
        for m in _RELATIVE_PATH_EXT.finditer(paragraph):
            token = m.group(1)
            if token in seen:
                continue
            seen.add(token)
            if _is_placeholder(token):
                continue
            line = _get_line_for_match(paragraph, m.start())
            if _HTTP_VERB_PATH_RE.match(line):
                continue
            line_negated = negated or bool(_NEGATION_PATTERNS.search(line))
            claims.append(PathClaim(raw=token, source_entry_id=entry_id, negated=line_negated))

        # Absolute paths in prose (less confident — skip URL routes)
        for m in _FS_PATH_RE.finditer(paragraph):
            token = m.group(1)
            if token in seen:
                continue
            seen.add(token)
            if _is_placeholder(token) or _is_url_route(token):
                continue
            line = _get_line_for_match(paragraph, m.start())
            if _HTTP_VERB_PATH_RE.match(line):
                continue
            line_negated = negated or bool(_NEGATION_PATTERNS.search(line))
            claims.append(PathClaim(raw=token, source_entry_id=entry_id, negated=line_negated))

    return claims


def _get_line_for_match(text: str, pos: int) -> str:
    """Return the full line containing the character at pos."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end]


def _extract_command_claims(entry_id: str, body: str) -> List[CommandClaim]:
    """Extract command references from backtick code spans."""
    claims: List[CommandClaim] = []
    seen: set = set()
    # Only pick up single-word or known command patterns; skip paths
    for m in _CMD_BACKTICK_RE.finditer(body):
        cmd_token = m.group(1)
        if cmd_token in seen:
            continue
        # Skip if this looks like a path
        if "/" in cmd_token or cmd_token.endswith((".md", ".py", ".js", ".ts", ".sh")):
            continue
        # Skip placeholders
        if _is_placeholder(cmd_token):
            continue
        seen.add(cmd_token)
        claims.append(CommandClaim(command=cmd_token, source_entry_id=entry_id))
    return claims


def _extract_version_claims(entry_id: str, body: str) -> List[VersionClaim]:
    """Extract package-version assertions from entry body."""
    claims: List[VersionClaim] = []
    seen: set = set()
    for m in _VERSION_CLAIM_RE.finditer(body):
        groups = m.groups()
        # Match one of three groups pairs
        if groups[0] and groups[1]:
            pkg, ver = groups[0], groups[1]
        elif groups[2] and groups[3]:
            pkg, ver = groups[2], groups[3]
        elif groups[4] and groups[5]:
            pkg, ver = groups[4], groups[5]
        else:
            continue
        pkg = pkg.strip().lower()
        ver = ver.strip().lstrip("^~>=<!")
        key = (pkg, ver)
        if key in seen:
            continue
        seen.add(key)
        claims.append(VersionClaim(package=pkg, version=ver, source_entry_id=entry_id))
    return claims


# ---------------------------------------------------------------------------
# Deterministic checkers (ZERO model tokens)
# ---------------------------------------------------------------------------


def check_path_exists(claim: PathClaim) -> CheckResult:
    """Check that a referenced filesystem path exists on disk."""
    if claim.negated:
        return CheckResult(
            check="path-exists",
            status="pass",
            message=f"Skipped (negated context): {claim.raw}",
            artifact=claim.raw,
        )

    raw = claim.raw
    # Expand home dir and resolve
    p = Path(raw).expanduser()

    if p.exists():
        return CheckResult(
            check="path-exists",
            status="pass",
            message=f"Path exists: {raw}",
            artifact=str(p),
        )

    # Soft: relative paths might be repo-relative — check from CWD too
    if not p.is_absolute():
        return CheckResult(
            check="path-exists",
            status="warn",
            message=f"Relative path not found (cwd-relative): {raw}",
            expected="path exists",
            actual="not found",
            artifact=raw,
        )

    return CheckResult(
        check="path-exists",
        status="fail",
        message=f"Path does not exist: {raw}",
        expected="exists",
        actual="not found",
        artifact=raw,
    )


def check_command_resolves(claim: CommandClaim) -> CheckResult:
    """Check that a binary is on PATH or is a known npm script."""
    cmd = claim.command.split()[0] if " " in claim.command else claim.command

    # Check system PATH
    if shutil.which(cmd) is not None:
        return CheckResult(
            check="command-resolves",
            status="pass",
            message=f"Command on PATH: {cmd}",
            artifact=shutil.which(cmd),
        )

    # Check npm/package.json scripts
    pkg_json = Path("package.json")
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if cmd in scripts:
                return CheckResult(
                    check="command-resolves",
                    status="pass",
                    message=f"Command is an npm script: {cmd}",
                    artifact="package.json",
                )
        except (json.JSONDecodeError, OSError):
            pass

    return CheckResult(
        check="command-resolves",
        status="warn",
        message=f"Command not found on PATH or in package.json scripts: {cmd}",
        expected="on PATH or npm script",
        actual="not found",
        artifact=cmd,
    )


def check_version_conflicts(
    all_claims: List[VersionClaim],
) -> List[CheckResult]:
    """Detect cross-entry version conflicts for the same package."""
    by_package: Dict[str, List[VersionClaim]] = {}
    for vc in all_claims:
        by_package.setdefault(vc.package, []).append(vc)

    results: List[CheckResult] = []
    for pkg, claims in by_package.items():
        versions = list({c.version for c in claims})
        if len(versions) <= 1:
            continue
        source_ids = [c.source_entry_id for c in claims]
        results.append(
            CheckResult(
                check="version-conflict",
                status="warn",
                message=(
                    f"Package '{pkg}' has conflicting version claims across entries: "
                    f"{', '.join(sorted(versions))}"
                ),
                expected="single consistent version",
                actual=f"{len(versions)} different versions",
                artifact=f"entries: {', '.join(source_ids[:3])}{'...' if len(source_ids) > 3 else ''}",
            )
        )
    return results


def check_staleness(
    entry: Dict[str, Any],
    max_days: int = 90,
) -> Optional[CheckResult]:
    """Warn if the entry has not been updated in more than max_days days."""
    updated = entry.get("updated") or entry.get("created") or ""
    if not updated:
        return None

    try:
        from datetime import datetime, timezone, timedelta

        # Parse ISO format: 2026-01-01T12:00:00Z or 2026-01-01
        if "T" in updated:
            dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(updated).replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age = now - dt
        if age > timedelta(days=max_days):
            return CheckResult(
                check="staleness",
                status="warn",
                message=f"Entry not updated in {age.days} days (threshold: {max_days})",
                expected=f"updated within {max_days} days",
                actual=f"{age.days} days old",
                artifact=updated,
            )
    except (ValueError, TypeError):
        pass

    return None


# ---------------------------------------------------------------------------
# Entry-level runner
# ---------------------------------------------------------------------------


def check_entry(
    entry: Dict[str, Any],
    *,
    check_paths: bool = True,
    check_commands: bool = True,
    check_stale: bool = True,
    staleness_days: int = 90,
) -> EntryReport:
    """Run all single-entry checkers and return an EntryReport."""
    entry_id = entry.get("id", "unknown")
    entry_type = entry.get("type", "unknown")
    entry_path = entry.get("path", "")
    body = entry.get("content", "")

    report = EntryReport(
        entry_id=entry_id,
        entry_type=entry_type,
        path=entry_path,
    )

    if check_paths:
        path_claims = _extract_path_claims(entry_id, body)
        for claim in path_claims:
            report.checks.append(check_path_exists(claim))

    if check_commands:
        cmd_claims = _extract_command_claims(entry_id, body)
        for claim in cmd_claims:
            report.checks.append(check_command_resolves(claim))

    if check_stale:
        stale_check = check_staleness(entry, max_days=staleness_days)
        if stale_check is not None:
            report.checks.append(stale_check)

    return report


# ---------------------------------------------------------------------------
# Cross-entry runner
# ---------------------------------------------------------------------------


def check_all_entries(
    entries: List[Dict[str, Any]],
    *,
    check_paths: bool = True,
    check_commands: bool = True,
    check_stale: bool = True,
    staleness_days: int = 90,
) -> MemoryCheckReport:
    """Run all checkers across a list of parsed entry dicts."""
    report = MemoryCheckReport()

    all_version_claims: List[VersionClaim] = []

    for entry in entries:
        er = check_entry(
            entry,
            check_paths=check_paths,
            check_commands=check_commands,
            check_stale=check_stale,
            staleness_days=staleness_days,
        )
        report.entries.append(er)

        # Collect version claims for cross-entry conflict check
        body = entry.get("content", "")
        entry_id = entry.get("id", "unknown")
        all_version_claims.extend(_extract_version_claims(entry_id, body))

    # Cross-entry version conflict check
    conflict_checks = check_version_conflicts(all_version_claims)
    report.cross_entry_checks.extend(conflict_checks)

    return report
