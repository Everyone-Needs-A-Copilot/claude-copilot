"""Verifier-issued, fail-closed gates for behavioral evaluation cells."""

from __future__ import annotations

from collections import Counter
from typing import Callable, Mapping

from cc.core.evaluation.models import (
    _EVIDENCE_AUTHORITY,
    EvaluationCell,
    GateObservation,
    GateState,
    PreflightGate,
    PreflightResult,
    PreflightState,
)
from cc.core.evaluation.schema import canonical_sha256

GateFact = tuple[GateState, str, str, str]
EvidenceProbe = Callable[[EvaluationCell], Mapping[PreflightGate, GateFact]]


class TrustedEvidenceVerifier:
    """Translate one injected trusted evidence probe into opaque gate facts.

    The probe is the authority boundary. Evaluation cells contain identities,
    never caller-authored pass booleans.
    """

    def __init__(self, probe: EvidenceProbe) -> None:
        self._probe = probe

    def verify(self, cell: EvaluationCell) -> tuple[GateObservation, ...]:
        try:
            facts = self._probe(cell)
        except Exception:
            facts = {}
        observations: list[GateObservation] = []
        for gate, fact in facts.items():
            try:
                state, reason, actor, prerequisite = fact
                observations.append(
                    GateObservation(
                        gate,
                        state,
                        reason,
                        actor,
                        prerequisite,
                        _EVIDENCE_AUTHORITY if state is GateState.PASS else None,
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(observations)


def issue_failure(
    gate: PreflightGate,
    *,
    reason: str,
    actor: str = "framework",
    prerequisite: str = "verified-evidence",
) -> GateObservation:
    return GateObservation(gate, GateState.FAIL, reason, actor, prerequisite)


def evaluate_preflight(
    observations: tuple[GateObservation, ...], *, subject_sha256: str | None = None
) -> PreflightResult:
    counts = Counter(item.gate for item in observations)
    first = {item.gate: item for item in observations}
    normalized: list[GateObservation] = []
    for gate in sorted(PreflightGate, key=lambda item: item.value):
        item = first.get(gate)
        if item is None:
            item = issue_failure(gate, reason="missing-evidence")
        elif counts[gate] != 1:
            item = issue_failure(
                gate,
                reason="duplicate-evidence",
                prerequisite="unique-evidence",
            )
        elif (
            item.state is GateState.UNSUPPORTED
            and gate is not PreflightGate.RUNTIME_CAPABILITY
        ):
            item = issue_failure(
                gate,
                reason="unsupported-not-permitted",
                actor=item.actor,
                prerequisite=item.prerequisite,
            )
        normalized.append(item)

    if any(item.state is GateState.FAIL for item in normalized):
        state = PreflightState.INVALID
    elif any(item.state is GateState.UNSUPPORTED for item in normalized):
        state = PreflightState.UNSUPPORTED
    else:
        state = PreflightState.VALID
    subject = subject_sha256 or canonical_sha256({"unbound": True})
    document = {
        "state": state.value,
        "subject_sha256": subject,
        "observations": [
            {
                "gate": item.gate.value,
                "state": item.state.value,
                "reason": item.reason,
                "actor": item.actor,
                "prerequisite": item.prerequisite,
            }
            for item in normalized
        ],
    }
    return PreflightResult(
        state,
        tuple(normalized),
        subject,
        canonical_sha256(document),
        _EVIDENCE_AUTHORITY if state is PreflightState.VALID else None,
    )
