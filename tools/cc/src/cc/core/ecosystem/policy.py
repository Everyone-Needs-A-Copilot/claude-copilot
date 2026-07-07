"""Pluggable capability + signature policy gate for `materialize()`.

`evaluate(item) -> "allow" | "hold" | "block"` -- the single seam
`materialize.py` calls per resolved item before writing it to the
materialize root. Kept intentionally minimal: this is NOT the real
capability-policy engine (ecosystem.yml `policy=hold-majors`-style rules,
§7.2/§9 of ecosystem-architecture.md) or the real signature verifier --
both are later, P1 slices. This module exists only to give `materialize()`
a real seam to call today, injectable so tests can exercise the
add/update/prune path without a signature verifier existing yet.

OWNER DECISION (flagged, not silently chosen -- confirm at the next
contract freeze): the PRODUCTION DEFAULT (`evaluate()` below) is
**fail-closed: block every item, unconditionally**, because real
signature-verify has not landed. `materialize.py` reports this as
`blocked: "unverified"` -- never a silent/implicit allow. A provisional
"trust the mirror" default (allow anything that synced from a manifest-
declared, resolvable source) was considered and rejected here: the mirror
sync (`mirror.py`) has no attestation of *authorship* today, only that
`git fetch`/`reset --hard` succeeded against *some* remote -- trusting that
alone would let a compromised or misconfigured source materialize
executable content (agents/skills/commands) onto the host with no signal
at all. Fail-closed-block-all means `cc update --json` today can compute
and report the full plan (what *would* change) but will not actually place
new/changed layer content until either (a) a real signer/verifier lands,
or (b) the owner explicitly ratifies a provisional trusted-mirror stance
for a transitional period. Tests inject `permissive_policy` (or an
equivalent custom `PolicyFn`) to exercise the materialize path itself
ahead of that decision.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

Verdict = Literal["allow", "hold", "block"]
PolicyFn = Callable[[dict[str, Any]], Verdict]


def evaluate(item: dict[str, Any]) -> Verdict:
    """
    PRODUCTION DEFAULT -- fail-closed. See module docstring for the
    owner-decision rationale. Every item is blocked (reported by the
    caller as `blocked: "unverified"`) until a real signature verifier
    replaces this function (or a caller injects a different `PolicyFn`).
    """
    return "block"


def permissive_policy(_item: dict[str, Any]) -> Verdict:
    """
    Injectable, allow-everything policy for tests/callers that need to
    exercise the materialize path (add/update/prune) without a real
    signature verifier. NEVER the production default -- see `evaluate()`.
    """
    return "allow"
