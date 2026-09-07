"""Single source of truth for accepted QA evidence artifact types.

Fixes defect 1 in wp-a-evidence.md section 3.4: before this registry, `tc`'s
predicate accepted `screenshot-check`/`a11y-check`/`design-fidelity-check`
but rejected `adversarial-run`, while `.claude/hooks/subagent-stop.sh`
accepted `adversarial-run` but rejected the three UI types -- a QA verdict
the Claude hook treated as passing could be refused by the task authority,
and vice versa. Every consumer (this predicate, the Claude hook, the Codex
`scripts/copilot-gate.sh` wrapper, and `.claude/agents/qa.md`'s documented
list) is expected to derive its accepted-type set from `ARTIFACT_TYPES`
rather than declaring its own.
"""

from __future__ import annotations

# name -> whether this type is SUFFICIENT ALONE to satisfy the artifact
# requirement for a passing verdict. All current types are independently
# sufficient; the flag exists so a future type that must be paired with
# another (e.g. requires corroboration) has somewhere to say so without
# another registry appearing elsewhere.
#
# `adversarial-run` is accepted and sufficient on its own, but it is
# availability-gated (only ever produced when a second-model CLI is
# configured -- see `.claude/hooks/bin/adversarial-pass.sh`) and must never
# become independently MANDATORY: its presence here means "if present, it
# counts", never "must be present".
ARTIFACT_TYPES: dict[str, bool] = {
    "test-run": True,
    "file-check": True,
    "diff-check": True,
    "adversarial-run": True,
    "screenshot-check": True,
    "a11y-check": True,
    "design-fidelity-check": True,
}


def is_valid_artifact_type(name: str) -> bool:
    """True when `name` is a recognized artifact type."""
    return name in ARTIFACT_TYPES


def is_sufficient_alone(name: str) -> bool:
    """True when a single artifact of this type satisfies the requirement
    on its own (all currently registered types are)."""
    return ARTIFACT_TYPES.get(name, False)
