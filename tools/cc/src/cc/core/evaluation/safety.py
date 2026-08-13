"""Value-suppressing safety checks for synthetic evaluation material."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyFinding:
    rule: str
    location_class: str
    count: int


class FixtureSafetyViolation(ValueError):
    def __init__(self, findings: tuple[SafetyFinding, ...]) -> None:
        self.findings = findings
        summary = ", ".join(
            f"{item.rule}@{item.location_class}:{item.count}" for item in findings
        )
        super().__init__(f"Synthetic fixture safety check failed ({summary})")


_RULES = (
    (
        "secret-private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("secret-bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (
        "secret-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    ),
    (
        "secret-assignment",
        re.compile(r"(?i)\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]{8,}"),
    ),
    ("realistic-ssn", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("realistic-ein", re.compile(r"(?<!\d)\d{2}-\d{7}(?!\d)")),
    (
        "realistic-account",
        re.compile(
            r"(?i)\b(?:account|routing|taxpayer)[ _-]?(?:number|id)?\s*[:#=]\s*\d{6,17}\b"
        ),
    ),
    (
        "private-home-path",
        re.compile(r"(?:/Users/[^/\s]+|/home/[^/\s]+|[A-Za-z]:\\Users\\[^\\\s]+)"),
    ),
    (
        "personal-email",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "personal-phone",
        re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),
    ),
    (
        "real-party-marker",
        re.compile(
            r"(?im)^\s*(?:client|person|employee|company|legal[ _-]?name)\s*:"
            r"(?![ \t]*SYNTHETIC-)[ \t]*[^\r\n]+"
        ),
    ),
)

_PRIVATE_MARKERS = re.compile(
    r"(?i)\b(?:PRIVATE_PERSONAL|PERSONAL_CONTEXT|PERSONAL_ONLY|DO_NOT_SHARE_PERSONAL)\b"
)


def scan_synthetic_text(text: str, *, location_class: str) -> tuple[SafetyFinding, ...]:
    """Return rule/count/location only; never include matched values."""

    if not location_class or any(character.isspace() for character in location_class):
        raise ValueError("Safety location class must be a stable identifier.")
    findings = [
        SafetyFinding(rule, location_class, len(tuple(pattern.finditer(text))))
        for rule, pattern in _RULES
        if pattern.search(text)
    ]
    if location_class in {"shared-output", "shared-artifact"}:
        count = len(tuple(_PRIVATE_MARKERS.finditer(text)))
        if count:
            findings.append(
                SafetyFinding("upward-personal-disclosure", location_class, count)
            )
    return tuple(findings)


def require_safe_synthetic_text(text: str, *, location_class: str) -> None:
    findings = scan_synthetic_text(text, location_class=location_class)
    if findings:
        raise FixtureSafetyViolation(findings)
