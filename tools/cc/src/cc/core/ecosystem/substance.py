"""Content-substance heuristic: is a winning override real, or an inert
scaffold that merely happens to exist?

Override-semantics dimensions (`core/ecosystem/dimensions.py`) assume the
nearest declaring tier's content is genuine — "nearest wins" only makes
sense when what's nearest is real. This module is the one health check on
that assumption: a `status: draft` frontmatter, a `TODO(` marker anywhere
in the file, or content disproportionately smaller than what it would
shadow, all mark a candidate as non-substantive.

`core/conformance/tier.py`'s H-3 check (`tier.shadow.substance`) applies
this exact same three-signal heuristic to knowledge-extension resolution
and predates this module; the logic is intentionally duplicated here
(rather than imported) because that module is the CHECKER (it also owns a
detail-string reporting shape this module has no business depending on)
and this module is a CONSUMER (`core/ecosystem/project_sources.py`) — they
read the same signal for different purposes and must be free to evolve
independently.

Live incident (2026-08): an org-tier `commands/protocol.md` scaffold
shipped a `TODO(pablo): this section is currently a no-op placeholder...`
header ahead of a byte-for-byte (and, worse, STALE) copy of the
foundation's real protocol. Under naive nearest-tier-wins, wiring the tier
ladder into project install would have REGRESSED every project's protocol
the moment a manifest was configured. This heuristic is the guard that
keeps an empty or placeholder declaration from shadowing real upstream
content merely by being nearer.
"""

from __future__ import annotations

import re
from typing import Optional

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.MULTILINE)

DEFAULT_MINIMUM_SIZE_RATIO = 0.5


def frontmatter_status(text: str) -> Optional[str]:
    """The `status:` value from `text`'s leading YAML frontmatter block, or
    `None` if there is no frontmatter or no `status:` key."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    status_match = _STATUS_RE.search(match.group(1))
    return status_match.group(1) if status_match else None


def is_substantive(
    text: str,
    *,
    shadow_size: int = 0,
    minimum_size_ratio: float = DEFAULT_MINIMUM_SIZE_RATIO,
) -> bool:
    """
    True when `text` reads like real content a tier actually authored,
    rather than an inert scaffold: no `status: draft` frontmatter, no
    `TODO(` marker anywhere in the file, and — when `shadow_size` (the
    byte size of the next-nearest candidate this content would shadow) is
    given and non-zero — not disproportionately smaller than it.

    A genuinely empty, marker-free file with no `shadow_size` to compare
    against is a degenerate case text content alone cannot detect; callers
    that have a real chain to compare against (`project_sources.py`'s
    winner/shadowed walk) should always pass `shadow_size`.
    """
    if frontmatter_status(text) == "draft":
        return False
    if "TODO(" in text:
        return False
    if shadow_size and len(text.encode("utf-8")) < minimum_size_ratio * shadow_size:
        return False
    return True
