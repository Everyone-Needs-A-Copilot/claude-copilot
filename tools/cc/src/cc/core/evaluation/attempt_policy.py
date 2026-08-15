"""Released, bounded retry policy for technical evaluation invalidations."""

from __future__ import annotations

from cc.core.evaluation.schema import canonical_sha256

MAX_ATTEMPTS = 2
RETRIABLE_TECHNICAL_REASONS = ("runtime-timeout",)

ATTEMPT_POLICY_DOCUMENT = {
    "schema_version": "1.0",
    "maximum_attempts": MAX_ATTEMPTS,
    "retry_parent_state": "technical-error",
    "retriable_technical_reasons": list(RETRIABLE_TECHNICAL_REASONS),
    "abandoned_claim": "requires-new-matrix-revision",
    "reset_or_delete": "prohibited",
}
ATTEMPT_POLICY_SHA256 = canonical_sha256(ATTEMPT_POLICY_DOCUMENT)


def is_retriable_technical_reason(reason: object) -> bool:
    return isinstance(reason, str) and reason in RETRIABLE_TECHNICAL_REASONS


__all__ = [
    "ATTEMPT_POLICY_DOCUMENT",
    "ATTEMPT_POLICY_SHA256",
    "MAX_ATTEMPTS",
    "RETRIABLE_TECHNICAL_REASONS",
    "is_retriable_technical_reason",
]
