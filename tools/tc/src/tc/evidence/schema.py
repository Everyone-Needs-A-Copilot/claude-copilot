"""Versioned QA evidence packet schema.

Field names and semantics come from the compact packet documented in
``.claude/agents/qa.md`` ("Delivery Evidence"):

    CRITERION: <required behavior and input/state>
    EXPECTED:  <observable outcome>
    OBSERVED:  <actual outcome>
    IDENTITY:  <checkout/revision + dirty fingerprint; runtime/config/server/data>
    BASELINE:  <before evidence, or unavailable + reason>
    ARTIFACT:  <accepted type>|<local evidence or failable command + result>
    UNTESTED:  <required cases not exercised, or none>
    VERDICT:   <supported verdict>

``EVIDENCE_SCHEMA_VERSION`` identifies the CURRENT contract enforced by
``tc.evidence.validate`` and ``tc.services.qa``. It has never been stamped on
a stored work product (there is no version marker in the free-text packet
format), so ``tc.evidence.parse.is_legacy_shaped`` uses a structural proxy
instead: IDENTITY is the one required field that no pre-v1 evidence ever
carried, so its absence identifies pre-v1 ("legacy") content. See
``tc.services.qa`` module docstring for the full legacy-evidence policy this
version number gates.
"""

from __future__ import annotations

EVIDENCE_SCHEMA_VERSION = 1

CRITERION = "CRITERION"
EXPECTED = "EXPECTED"
OBSERVED = "OBSERVED"
IDENTITY = "IDENTITY"
BASELINE = "BASELINE"
ARTIFACT = "ARTIFACT"
UNTESTED = "UNTESTED"
VERDICT = "VERDICT"

# Fields recognised by the parser (both the strict and tolerant paths use
# this same set -- see tc.evidence.parse).
KNOWN_FIELDS = (CRITERION, EXPECTED, OBSERVED, IDENTITY, BASELINE, ARTIFACT, UNTESTED, VERDICT)

# Fields the v1 contract requires present and non-empty for a packet to be
# well-formed (BASELINE may legitimately read "unavailable, reason: ..." but
# the field itself must exist -- see tc.evidence.validate).
REQUIRED_FIELDS = (CRITERION, EXPECTED, OBSERVED, IDENTITY, BASELINE, ARTIFACT, VERDICT)

VALID_VERDICTS = ("APPROVED", "APPROVED-WITH-MINOR-FIXES", "REJECTED")

# Values for UNTESTED that mean "no gap" -- anything else names a real
# untested required case and therefore cannot support approval (qa.md:
# "an untested required case cannot support approval; rerun ... or reject
# with the gap").
UNTESTED_NONE_VALUES = ("none", "n/a", "na", "")


def render_packet(packet: dict) -> str:
    """Render a parsed packet dict back into the readable text form.

    Preserves a human-readable rendering alongside the machine-readable
    dict produced by ``tc.evidence.parse.parse_packet`` -- required by the
    module boundary in wp-a-evidence.md section 5.2.
    """
    lines: list[str] = []
    records = packet.get("records") or []
    if not records:
        records = [{}]
    for record in records:
        if record.get("criterion"):
            lines.append(f"CRITERION: {record['criterion']}")
        if record.get("expected"):
            lines.append(f"EXPECTED: {record['expected']}")
        if record.get("observed"):
            lines.append(f"OBSERVED: {record['observed']}")
    if packet.get("identity"):
        lines.append(f"IDENTITY: {packet['identity']}")
    if packet.get("baseline"):
        lines.append(f"BASELINE: {packet['baseline']}")
    for artifact in packet.get("artifacts") or []:
        lines.append(f"ARTIFACT: {artifact}")
    if packet.get("untested"):
        lines.append(f"UNTESTED: {packet['untested']}")
    for verdict in packet.get("verdicts") or []:
        lines.append(f"VERDICT: {verdict}")
    return "\n".join(lines)


def to_json_envelope(packet: dict) -> dict:
    """Versioned machine-readable envelope for a parsed packet.

    Stored/returned alongside the readable rendering (``render_packet``),
    never in place of it.
    """
    return {
        "schemaVersion": EVIDENCE_SCHEMA_VERSION,
        "records": packet.get("records") or [],
        "identity": packet.get("identity"),
        "baseline": packet.get("baseline"),
        "artifacts": packet.get("artifacts") or [],
        "untested": packet.get("untested"),
        "verdicts": packet.get("verdicts") or [],
    }
