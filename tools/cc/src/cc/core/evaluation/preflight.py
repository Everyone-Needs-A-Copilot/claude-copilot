"""Fail-closed deterministic gates for behavioral evaluation cells."""

from __future__ import annotations

from collections import Counter

from cc.core.evaluation.models import (
    GateObservation,
    GateState,
    PreflightGate,
    PreflightResult,
    PreflightState,
)
from cc.core.evaluation.schema import canonical_sha256


def evaluate_preflight(
    observations: tuple[GateObservation, ...],
) -> PreflightResult:
    """Classify a complete gate packet without treating absence as weakness.

    Runtime capability is the only gate allowed to produce ``UNSUPPORTED``.
    Every other missing, duplicate, failed, or unsupported gate is ``INVALID``.
    """

    counts = Counter(item.gate for item in observations)
    first = {item.gate: item for item in observations}
    normalized: list[GateObservation] = []
    for gate in sorted(PreflightGate, key=lambda item: item.value):
        item = first.get(gate)
        if item is None:
            item = GateObservation(
                gate,
                GateState.FAIL,
                "missing-evidence",
                "framework",
                "verified-evidence",
            )
        elif counts[gate] != 1:
            item = GateObservation(
                gate,
                GateState.FAIL,
                "duplicate-evidence",
                "framework",
                "unique-evidence",
            )
        elif (
            item.state is GateState.UNSUPPORTED
            and gate is not PreflightGate.RUNTIME_CAPABILITY
        ):
            item = GateObservation(
                gate,
                GateState.FAIL,
                "unsupported-not-permitted",
                item.actor,
                item.prerequisite,
            )
        normalized.append(item)

    if any(item.state is GateState.FAIL for item in normalized):
        state = PreflightState.INVALID
    elif any(item.state is GateState.UNSUPPORTED for item in normalized):
        state = PreflightState.UNSUPPORTED
    else:
        state = PreflightState.VALID

    document = {
        "state": state.value,
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
    return PreflightResult(state, tuple(normalized), canonical_sha256(document))
