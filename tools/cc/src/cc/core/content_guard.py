"""Content guard: injection neutralization and secret redaction for store writes.

Subagents read untrusted content (external repos, web pages, issue text, logs)
and then write it to `cc memory store`. Those entries are rehydrated verbatim
into *later* sessions' context, so hostile text embedded in a stored entry can
be replayed and misread as a genuine instruction, and a secret pasted into a
"lesson" or "context" entry sits on disk in plaintext forever after. This
module is the single place that stands between "text a caller asked to store"
and "text actually written to disk".

Design stance, deliberately different from a reject-at-write-time gate:
NEUTRALIZE, DO NOT DROP. A caller that asked to store something and silently
got nothing (or a hard failure) has no way to tell "my write was blocked" from
"my write succeeded", and loses their own real content in the process — worse
than storing a defanged version of it. So this module always returns text to
store: clean text unchanged, or matched spans rewritten in place so they can
no longer be parsed as an instruction / can no longer leak a live credential,
with every change recorded on the result so the caller (and the stored record
itself, via `entry_store.store_entry`'s `guard` frontmatter field) can see
exactly what happened and where.

INJECTION_PATTERNS — what's here and why. Not a port of gstack's 14-pattern
denylist; adapted to what actually threatens *our* stores (markdown files and
sqlite rows read back as prose into a future agent's context, not a live
chat transcript):

  * instruction-override / instruction-disregard — the "ignore previous
    instructions" family. The core jailbreak template; kept because a stored
    "decision" or "lesson" entry is exactly the kind of text a future agent
    trusts and re-reads.
  * role-switch-assign — "you are now a/an/the ___" or "you are now Xxx"
    role-reassignment (vs. gstack's bare "you are now ", which also matches
    ordinary status sentences like "you are now ready to submit" -- common
    in engineering prose, and noisy enough to get force-overridden on
    reflex). Narrowed to require either a lowercase article right after
    "now", or a Capitalized word (case checked case-SENSITIVELY even though
    the rest of the pattern is case-insensitive) -- catching both "you are
    now a helpful assistant" and the article-less persona template ("you are
    now DAN") without matching "you are now ready" / "you are now viewing".
  * new-system-prompt — a fabricated "new instructions:" / "new system
    prompt:" header trying to open a second instruction block inside stored
    content.
  * system-reminder-tag / role-tag — `<system-reminder>`, `<system>`,
    `<assistant>`, `<human>` style markup. system-reminder-tag is our own
    addition on top of gstack's list: this harness injects real
    `<system-reminder>` blocks into context, so forged ones are the highest-
    value single pattern here, not a generic add-on.
  * role-marker-human / role-marker-assistant — bare `Human:` / `Assistant:`
    turn markers. This is gstack's own documented highest-value pattern (the
    one that bypassed both their denylist and their datamark) and its
    symmetric sibling; ported directly.
  * tool-call-json-block — a fabricated `{"type": "tool_use", "name": ...}`
    shaped block. Deliberately requires the JSON shape (quoted keys, brace)
    rather than gstack's bare `tool_use ... name :` word-proximity match:
    this very codebase's own planning docs discuss "tool_use blocks" and
    "name:" in ordinary prose (see e.g. the transcript-parsing paragraphs in
    IMPL-plan.md), and a word-proximity pattern would flag that prose as an
    attack. Requiring literal JSON syntax keeps the false-positive rate near
    zero while still catching an actually-shaped fake tool call.
  * heading-directive — a markdown heading that consists of *only* "System"
    or "Instructions" (optionally with a trailing colon), e.g. "### System:".
    Narrowed to a whole-heading match (not "heading starts with") because our
    stores are markdown and legitimate architecture notes routinely have
    headings like "## System Architecture" or "## System Overview" — a
    prefix match would flag routine ADR structure.
  * bypass-findings / bypass-skip-checks — "always report no findings",
    "skip all security checks" style directives aimed at a future qa/sec
    agent reading this content as instructions. Kept narrow (skip must be
    immediately followed by one of a fixed noun list) so "we decided to skip
    flaky tests during the outage" — ordinary decision-log language — does
    not trip it.

Deliberately dropped from gstack's list: "approve all/every/this" was tried
and cut. "Approve this PR", "approve this proposal", "approve the migration
plan" are completely ordinary sentences in a decision/context memory entry,
and the signal-to-noise ratio was too low to justify even under the
neutralize-not-reject model. "BEGIN SYSTEM" was cut as redundant with
role-tag/system-reminder-tag/heading-directive with no independent signal of
its own.

SECRET_PATTERNS — high-confidence shapes only, per the task's own instruction
to optimize against false negatives on obvious shapes without being so
aggressive that ordinary prose triggers it:
  * private-key-block   — PEM `-----BEGIN ... PRIVATE KEY-----` blocks.
  * aws-access-key       — AWS access key id (`AKIA` + 16 alnum).
  * github-token         — GitHub PAT/OAuth/App/refresh token prefixes.
  * openai-style-token   — `sk-` + 20+ alnum, the shape shared by OpenAI and
    several other providers' secret keys.
  * slack-token          — `xox[baprs]-` Slack tokens.
  * jwt                  — three dot-separated base64url segments starting
    `eyJ` (a JWT header always base64-decodes to `{"...`).
  * bearer-token         — `Bearer <token>` in an Authorization-header shape.
  * connection-string-credentials — `scheme://user:password@host` embedded
    credentials.
  * generic-secret-assignment — `token|secret|password|api_key|
    access_token|authorization` assigned via `:` or `=` to a 4+ char value.
    This is the one broad net in the set (per the task's explicit ask for
    "generic high-entropy assignments to names like token/secret/password/
    api_key"); it is assignment-SHAPED (a key name immediately followed by a
    separator and a value), not free-floating prose, which is what keeps it
    from firing on sentences that merely discuss "the password field".

Redaction preserves context: only the credential value is replaced, never the
surrounding text (key name, `Bearer `, `scheme://user:`, `@host`), and the
existing marker text (`[REDACTED:...]`) is excluded from re-matching so a
second scan of already-redacted content is a true no-op — required both for
correctness (never double-redact) and because a stable count of findings is
what makes the audit trail trustworthy.

Neutralization does not delete or hide anything invisibly. Each flagged
injection span is wrapped in a plain-text `[[GUARD:<pattern-id>]] ...
[[/GUARD]]` marker, with a single visible middle-dot (·) spliced into the
first token of the matched text. The dot is what makes re-scanning idempotent
(it breaks the literal substring every injection regex depends on), and it is
visible on purpose: an invisible break would itself be a second layer of
content the caller can't see, which is exactly the failure mode this module
exists to prevent. A human or a future agent reading the stored entry can
still read what was written; they just can't fail to notice it was flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One neutralized/redacted match, safe to log or store — `excerpt` is
    always derived from the POST-neutralization text, so a Finding for a
    secret pattern never carries the raw secret value."""

    category: str  # "injection" | "secret"
    pattern_id: str
    line: int  # 1-based line number in the text being scanned
    excerpt: str  # the replacement text actually written (never the raw match)


@dataclass(frozen=True)
class GuardResult:
    """Result of `scan_and_neutralize()`. `text` is always safe to store:
    either the original text unchanged (`ok=True`, no findings), the
    neutralized/redacted text (`ok=True`, findings present), or — on the
    fail-safe path — the original text unchanged with `ok=False` set so the
    caller can flag the record as unscanned rather than lose the write."""

    text: str
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    ok: bool = True
    error: str | None = None

    @property
    def modified(self) -> bool:
        return bool(self.findings)

    def summary_token(self) -> str:
        """Compact status string suitable for a stored record's guard field."""
        if not self.ok:
            return "scan_error"
        if not self.findings:
            return "clean"
        ids = sorted({f.pattern_id for f in self.findings})
        return "modified:" + ",".join(ids)

    def warning_lines(self, field_name: str) -> list[str]:
        """Human-readable stderr lines for this result, or [] if nothing to say."""
        if not self.ok:
            return [
                f"content-guard: {field_name}: scan failed ({self.error}); "
                "stored unscanned"
            ]
        if not self.findings:
            return []
        ids = sorted({f.pattern_id for f in self.findings})
        lines = [
            f"content-guard: {field_name}: neutralized {len(self.findings)} "
            f"match(es) [{', '.join(ids)}]"
        ]
        for f in self.findings:
            excerpt = f.excerpt if len(f.excerpt) <= 80 else f.excerpt[:77] + "..."
            lines.append(f"content-guard:   line {f.line} ({f.category}:{f.pattern_id}) {excerpt}")
        return lines


@dataclass(frozen=True)
class PatternSpec:
    id: str
    category: str  # "injection" | "secret"
    regex: "re.Pattern[str]"
    neutralize: Callable[["re.Match[str]"], str]


# ---------------------------------------------------------------------------
# Injection neutralization primitive
# ---------------------------------------------------------------------------

# Visible marker spliced into the first token of a matched span. See module
# docstring "Neutralization does not delete or hide anything invisibly" for
# why this is a visible character rather than a zero-width one, and why it
# is what makes a second scan of already-wrapped text a no-op (it breaks the
# literal substring contiguity every injection regex below depends on).
_BREAK = "\u00b7"  # MIDDLE DOT


def _defang(matched_text: str) -> str:
    if len(matched_text) <= 1:
        return matched_text + _BREAK
    return matched_text[0] + _BREAK + matched_text[1:]


def _wrap_injection(pattern_id: str) -> Callable[["re.Match[str]"], str]:
    def _neutralize(m: "re.Match[str]") -> str:
        return f"[[GUARD:{pattern_id}]]{_defang(m.group(0))}[[/GUARD]]"

    return _neutralize


def _injection(pattern_id: str, regex: str, *, flags: int = re.IGNORECASE) -> PatternSpec:
    return PatternSpec(
        id=pattern_id,
        category="injection",
        regex=re.compile(regex, flags),
        neutralize=_wrap_injection(pattern_id),
    )


INJECTION_PATTERNS: tuple[PatternSpec, ...] = (
    _injection(
        "instruction-override",
        r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|context|rules|prompt)",
    ),
    _injection(
        "instruction-disregard",
        r"disregard\s+(all\s+)?(the\s+)?(prior|previous|above)\b",
    ),
    # Role-reassignment template "you are now ___". Matched case-insensitively
    # on the prefix, but the word right after "now" is checked case-
    # SENSITIVELY (the `(?-i:...)` scope turns the module-default IGNORECASE
    # back off just for that check): either a lowercase article (a/an/the,
    # "you are now a helpful assistant") or a capitalized word (You are now
    # DAN" / "...Grimlock" -- the classic article-less jailbreak persona
    # template). This is what lets the pattern catch both phrasings while
    # still excluding ordinary lowercase continuations like "you are now
    # ready" / "you are now viewing", which would otherwise make this the
    # noisiest pattern in the set.
    _injection(
        "role-switch-assign",
        r"\byou\s+are\s+now\s+(?-i:(?:a|an|the)\b|[A-Z])",
    ),
    _injection(
        "new-system-prompt",
        r"new\s+(system\s+)?(instructions|prompt)[ \t]*:",
    ),
    _injection(
        "system-reminder-tag",
        r"</?system-reminder\b(?:\s[^>]*)?>",
    ),
    _injection(
        "role-tag",
        r"</?(system|assistant|human)(?:\s[^>]*)?>",
    ),
    _injection(
        "role-marker-human",
        r"\bhuman[ \t]*:",
    ),
    _injection(
        "role-marker-assistant",
        r"\bassistant[ \t]*:",
    ),
    _injection(
        "tool-call-json-block",
        r'\{\s*"type"\s*:\s*"tool_use"[\s\S]{0,120}?"name"\s*:',
    ),
    _injection(
        "heading-directive",
        r"^\s*#{1,6}\s*(system|instructions?)\s*:?\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    ),
    _injection(
        "bypass-findings",
        r"\balways\s+(output|report)\s+(no|zero)\s+(findings|issues|problems|vulnerabilities)\b",
    ),
    _injection(
        "bypass-skip-checks",
        r"\bskip\s+(all\s+)?(security|review|checks?|tests?|validation)\b",
    ),
)


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def _redact_whole_match(pattern_id: str) -> Callable[["re.Match[str]"], str]:
    def _neutralize(_m: "re.Match[str]") -> str:
        return f"[REDACTED:{pattern_id}]"

    return _neutralize


def _redact_private_key(_m: "re.Match[str]") -> str:
    return "-----BEGIN [REDACTED:private-key-block]-----"


def _redact_bearer(m: "re.Match[str]") -> str:
    return f"{m.group(1)}[REDACTED:bearer-token]"


def _redact_connection_string(m: "re.Match[str]") -> str:
    return (
        f"{m.group('scheme')}{m.group('user')}:"
        f"[REDACTED:connection-string-credentials]@{m.group('host')}"
    )


def _redact_generic_assignment(m: "re.Match[str]") -> str:
    return f"{m.group(1)}{m.group(2)}[REDACTED:generic-secret-assignment]"


SECRET_PATTERNS: tuple[PatternSpec, ...] = (
    PatternSpec(
        id="private-key-block",
        category="secret",
        regex=re.compile(
            r"-----BEGIN\s+[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END\s+[A-Z ]*PRIVATE KEY-----"
        ),
        neutralize=_redact_private_key,
    ),
    PatternSpec(
        id="aws-access-key",
        category="secret",
        regex=re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        neutralize=_redact_whole_match("aws-access-key"),
    ),
    PatternSpec(
        id="github-token",
        category="secret",
        regex=re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
        neutralize=_redact_whole_match("github-token"),
    ),
    PatternSpec(
        id="openai-style-token",
        category="secret",
        regex=re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        neutralize=_redact_whole_match("openai-style-token"),
    ),
    PatternSpec(
        id="slack-token",
        category="secret",
        regex=re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        neutralize=_redact_whole_match("slack-token"),
    ),
    PatternSpec(
        id="jwt",
        category="secret",
        regex=re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        neutralize=_redact_whole_match("jwt"),
    ),
    PatternSpec(
        id="bearer-token",
        category="secret",
        regex=re.compile(r"(?i)(\bbearer[ \t]+)([A-Za-z0-9._~+/=-]{20,})"),
        neutralize=_redact_bearer,
    ),
    PatternSpec(
        id="connection-string-credentials",
        category="secret",
        regex=re.compile(
            r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^\s:/@]+):"
            r"(?P<password>(?!\[REDACTED)[^\s@]+)@(?P<host>[^\s]+)"
        ),
        neutralize=_redact_connection_string,
    ),
    PatternSpec(
        id="generic-secret-assignment",
        category="secret",
        regex=re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|authorization|auth[_-]?token|"
            # (?!bearer\b) defers "Authorization: Bearer <token>" entirely to
            # the dedicated bearer-token pattern above, so this broader net
            # doesn't also swallow the literal word "Bearer" as if it were
            # the secret value.
            #
            # The separator's whitespace is deliberately bounded, not `\s*`:
            # same-line spaces/tabs around the `:`/`=`, plus at most ONE line
            # break into an indented continuation line (`[ \t]*` leading the
            # next line), which still catches the idiomatic YAML/next-line
            # form (`token:\n  ghp_xxxx`). It cannot cross a blank line /
            # paragraph break, because an unbounded `\s*` here let a token-ish
            # word at the end of one paragraph bind to unrelated text much
            # further down the document (e.g. "...decision token:\n\n```
            # markdown" redacted the fence marker itself) -- a real false
            # positive found via this initiative's own planning docs.
            r"token|password|secret)([ \t]*[:=][ \t]*(?:\r?\n[ \t]*)?)"
            r"((?!\[REDACTED)(?!bearer\b)[^\s,;]{4,})"
        ),
        neutralize=_redact_generic_assignment,
    ),
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _apply(text: str, specs: Sequence[PatternSpec], findings: list[Finding]) -> str:
    for spec in specs:
        def _sub(m: "re.Match[str]", _spec: PatternSpec = spec) -> str:
            line_no = text.count("\n", 0, m.start()) + 1
            replacement = _spec.neutralize(m)
            findings.append(
                Finding(
                    category=_spec.category,
                    pattern_id=_spec.id,
                    line=line_no,
                    excerpt=replacement,
                )
            )
            return replacement

        text = spec.regex.sub(_sub, text)
    return text


def scan_and_neutralize(text: str) -> GuardResult:
    """Scan `text` for secrets and injection-shaped content, redacting/
    neutralizing matches in place. Always returns text safe to store.

    Fail-safe: if the scanner itself raises, the ORIGINAL text is returned
    unmodified with `ok=False` and `error` set, rather than losing the write
    or propagating the exception to the caller. Callers are expected to
    store the text as-is in that case and surface `ok=False` on the record.
    """
    try:
        findings: list[Finding] = []
        working = text
        # Secrets first: redact live credentials before injection wrapping
        # touches the same text, so a marker never ends up wrapping a still-
        # live secret.
        working = _apply(working, SECRET_PATTERNS, findings)
        working = _apply(working, INJECTION_PATTERNS, findings)
        return GuardResult(text=working, findings=tuple(findings), ok=True)
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all, see docstring
        return GuardResult(text=text, findings=(), ok=False, error=str(exc))


def combine_field_summary(results: "dict[str, GuardResult]") -> str:
    """Combine several fields' GuardResults into one compact token for a
    single stored-record column, e.g. "title=clean;content=modified:
    instruction-override". Used by callers that guard more than one field
    per record (tc's work products, tasks, PRDs); a single-field caller like
    cc's memory entries stores `GuardResult.summary_token()` directly instead.
    """
    return ";".join(f"{name}={result.summary_token()}" for name, result in results.items())


def combine_field_warnings(results: "dict[str, GuardResult]") -> list[str]:
    """Flatten several fields' warning lines into one ordered list."""
    lines: list[str] = []
    for name, result in results.items():
        lines.extend(result.warning_lines(name))
    return lines


__all__ = [
    "Finding",
    "GuardResult",
    "PatternSpec",
    "INJECTION_PATTERNS",
    "SECRET_PATTERNS",
    "scan_and_neutralize",
    "combine_field_summary",
    "combine_field_warnings",
]
