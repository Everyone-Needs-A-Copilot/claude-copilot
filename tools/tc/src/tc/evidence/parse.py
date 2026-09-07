"""Text QA-evidence packet parsing.

``parse_packet(text)`` turns the free-text packet described in
``tc.evidence.schema`` into a structured dict. It is deliberately tolerant
of legacy (pre-v1) content too -- callers use ``is_legacy_shaped`` to tell
the two apart (see ``tc.services.qa`` for the legacy-evidence policy that
decision feeds).

Two defects from wp-a-evidence.md section 3.4 are closed here, in one place,
so both the strict and legacy paths share the fix:

  * Defect 6 (quoted approval examples): a VERDICT/ARTIFACT line inside a
    fenced code block or an indented (quoted/example) block is not
    authoritative. ``_authoritative_lines`` skips both before any field is
    ever extracted, so a documentation example ("``` VERDICT: APPROVED
    ```") embedded in a QA write-up can never register as a second, real
    verdict. Genuine duplicate unquoted VERDICT lines with differing values
    are still a real conflict -- see ``tc.evidence.validate``.
  * Defect 8 (case sensitivity): field names match case-insensitively, the
    same way ``.claude/hooks/subagent-stop.sh``'s `grep -qiE` already does,
    closing the divergence between the two authorities.
"""

from __future__ import annotations

import re
from typing import Any

from .schema import KNOWN_FIELDS

_FIELD_RE = re.compile(r"^\s*(" + "|".join(KNOWN_FIELDS) + r")\s*:\s*(.*)$", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```")

# A top-level field line has at most this many leading spaces. Anything more
# indented is treated as a quoted/nested example, not a live field -- the
# heuristic named in the module docstring for defect 6. This does not parse
# markdown structurally; it resolves the specific case wp-a-evidence.md
# describes (an indented or fenced example inside a QA write-up).
_MAX_TOP_LEVEL_INDENT = 3


def _authoritative_lines(text: str):
    """Yield (FIELD_NAME_UPPER, value) for lines that are not inside a
    fenced code block and not indented past `_MAX_TOP_LEVEL_INDENT`."""
    in_fence = False
    for raw_line in text.splitlines():
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = raw_line.lstrip(" ")
        indent = len(raw_line) - len(stripped)
        if indent > _MAX_TOP_LEVEL_INDENT:
            continue
        match = _FIELD_RE.match(raw_line)
        if not match:
            continue
        yield match.group(1).upper(), match.group(2).strip()


def _extract(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for name, value in _authoritative_lines(text or ""):
        fields.setdefault(name, []).append(value)
    return fields


def parse_packet(text: str) -> dict[str, Any]:
    """Parse `text` into a structured packet dict.

    Shape::

        {
          "records":  [{"criterion": str|None, "expected": str|None, "observed": str|None}, ...],
          "identity": str | None,   # last authoritative IDENTITY line
          "baseline": str | None,   # last authoritative BASELINE line
          "artifacts": [str, ...],  # every authoritative ARTIFACT line, "<type>|<detail>"
          "untested": str | None,   # last authoritative UNTESTED line
          "verdicts": [str, ...],   # every authoritative VERDICT line, in order
          "raw": str,               # the original text, unmodified
        }

    CRITERION/EXPECTED/OBSERVED are paired positionally (the Nth occurrence
    of each forms one record), which is how multiple criteria travel in a
    single work product. IDENTITY/BASELINE/UNTESTED use the last occurrence
    when repeated (later restatements supersede earlier ones); VERDICT
    keeps every occurrence so ``tc.evidence.validate`` can flag genuine
    conflicts rather than silently picking one.
    """
    fields = _extract(text)
    criteria = fields.get("CRITERION", [])
    expected = fields.get("EXPECTED", [])
    observed = fields.get("OBSERVED", [])
    count = max(len(criteria), len(expected), len(observed))
    records = [
        {
            "criterion": criteria[i] if i < len(criteria) else None,
            "expected": expected[i] if i < len(expected) else None,
            "observed": observed[i] if i < len(observed) else None,
        }
        for i in range(count)
    ]
    identity_values = fields.get("IDENTITY")
    baseline_values = fields.get("BASELINE")
    untested_values = fields.get("UNTESTED")
    return {
        "records": records,
        "identity": identity_values[-1] if identity_values else None,
        "baseline": baseline_values[-1] if baseline_values else None,
        "artifacts": fields.get("ARTIFACT", []),
        "untested": untested_values[-1] if untested_values else None,
        "verdicts": fields.get("VERDICT", []),
        "raw": text or "",
    }


def is_legacy_shaped(text: str) -> bool:
    """True when `text` carries evidence (a VERDICT and/or ARTIFACT line)
    but no IDENTITY field at all.

    IDENTITY is the one field the v1 contract requires that no pre-v1
    packet ever had (the old predicate checked only ARTIFACT and VERDICT),
    so its total absence is a reliable, self-contained signal that this
    content predates ``EVIDENCE_SCHEMA_VERSION`` -- no stored version number
    is needed. See ``tc.services.qa`` for the policy this feeds.
    """
    fields = _extract(text or "")
    has_evidence_markers = bool(fields.get("VERDICT") or fields.get("ARTIFACT"))
    return has_evidence_markers and "IDENTITY" not in fields
