"""Pure QA evidence packet validation.

Fitness function (wp-a-evidence.md section 5.4, item 3): this module MUST
NOT import ``tc.db``, ``tc.services``, ``subprocess``, or ``os`` -- enforced
mechanically by ``tools/tc/tests/test_evidence_validate.py``'s import-purity
test. It never executes anything an artifact string contains; it only
inspects the recorded text a caller hands it. Field presence and hashes
cannot prove behavioral truth on their own -- this module is the structural
half of that judgment (required fields, coherent verdict, known artifact
type, no unresolved untested case, identity not visibly stale); it does not
and cannot verify that the recorded OBSERVED outcome actually happened.

Closes defect 2 (the packet was previously entirely unvalidated -- only
ARTIFACT and VERDICT were checked) and defect 6 (duplicate/quoted VERDICT
handling; see ``tc.evidence.parse`` for where the quote/case handling
itself lives -- this module only judges what parsing already resolved).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .artifact_types import is_valid_artifact_type
from .schema import UNTESTED_NONE_VALUES, VALID_VERDICTS

_FINGERPRINT_TOKEN_RE = re.compile(r"(?:dirty|fingerprint)[:=]\s*([0-9a-f]{6,})", re.IGNORECASE)


def _identity_errors(identity: Optional[str], current_identity: Optional[dict]) -> list[str]:
    errors: list[str] = []
    if not identity:
        errors.append("missing IDENTITY")
        return errors
    if not current_identity:
        return errors

    revision = current_identity.get("revision")
    if revision and revision not in identity:
        errors.append(
            f"stale IDENTITY: recorded identity does not include the current revision "
            f"({revision!r}); implementation may have changed since this evidence was recorded"
        )
        return errors

    if current_identity.get("dirty") and "clean" in identity.lower():
        errors.append(
            "stale IDENTITY: recorded identity claims a clean working tree, but the "
            "current working tree is dirty"
        )
        return errors

    dirty_fingerprint = current_identity.get("dirty_fingerprint")
    match = _FINGERPRINT_TOKEN_RE.search(identity)
    if dirty_fingerprint and match and match.group(1) not in dirty_fingerprint and dirty_fingerprint not in match.group(1):
        errors.append(
            "stale IDENTITY: recorded dirty-tree fingerprint does not match the "
            "current working tree"
        )
    return errors


def validate_packet(packet: dict[str, Any], *, current_identity: Optional[dict] = None) -> dict[str, Any]:
    """Validate a parsed packet (see ``tc.evidence.parse.parse_packet``).

    Args:
        packet: the dict returned by ``parse_packet``.
        current_identity: optional ``{"revision": str|None, "dirty":
            bool|None, "dirty_fingerprint": str|None}`` describing the
            CURRENT implementation state, for staleness comparison against
            the packet's recorded IDENTITY (defect 4). Callers compute this
            themselves (it requires git/subprocess, which this module may
            not import) and pass it in; omit it to skip staleness
            comparison entirely (e.g. when the current state cannot be
            determined).

    Returns:
        ``{"valid": bool, "verdict": str|None, "errors": [str, ...], "reason": str}``.
        ``valid=True`` iff there are no errors at all: a coherent
        non-REJECTED verdict, every required field present and non-empty,
        every ARTIFACT type recognized, no named untested required case,
        and (when `current_identity` is supplied) IDENTITY is not stale.
    """
    errors: list[str] = []
    records = packet.get("records") or []

    if not records or not any(r.get("criterion") for r in records):
        errors.append("missing CRITERION")
    else:
        for index, record in enumerate(records):
            if not record.get("criterion"):
                errors.append(f"record {index}: missing CRITERION")
            if not record.get("expected"):
                errors.append(f"record {index}: missing EXPECTED")
            if not record.get("observed"):
                errors.append(f"record {index}: missing OBSERVED")

    errors.extend(_identity_errors(packet.get("identity"), current_identity))

    if not packet.get("baseline"):
        errors.append("missing BASELINE")

    artifacts = packet.get("artifacts") or []
    if not artifacts:
        errors.append("missing ARTIFACT")
    else:
        for artifact in artifacts:
            artifact_type = artifact.split("|", 1)[0].strip() if artifact else ""
            if not is_valid_artifact_type(artifact_type):
                errors.append(f"unrecognized ARTIFACT type {artifact_type!r}")

    untested = packet.get("untested")
    if untested and untested.strip().lower() not in UNTESTED_NONE_VALUES:
        errors.append(f"untested required case(s) recorded and cannot support approval: {untested}")

    verdicts = packet.get("verdicts") or []
    verdict_value: Optional[str] = None
    if not verdicts:
        errors.append("missing VERDICT")
    elif len(set(verdicts)) > 1:
        errors.append(f"conflicting VERDICT values: {sorted(set(verdicts))}")
    else:
        verdict_value = verdicts[0]
        if verdict_value not in VALID_VERDICTS:
            errors.append(f"unsupported VERDICT {verdict_value!r}")
        elif verdict_value == "REJECTED":
            errors.append("VERDICT is REJECTED")

    valid = not errors
    reason = "evidence packet is well-formed and current" if valid else errors[0]
    return {"valid": valid, "verdict": verdict_value, "errors": errors, "reason": reason}
