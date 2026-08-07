"""Sentinel resolution for two-layer config.

Sentinels allow project config to reference machine config values without
hardcoding machine-specific paths.

Sentinel table:
  "@machine"            — use machine config value at the same dotted key
  "@machine:<other>"    — use machine config value at a different dotted key
  "@env:<VAR>"          — read from environment variable
  "@disabled"           — explicitly disable this feature (returns None)
  plain string          — used verbatim
"""

from __future__ import annotations

import os
from typing import Any


def is_sentinel(value: Any) -> bool:
    """Return True if value is a sentinel string."""
    if not isinstance(value, str):
        return False
    return value.startswith("@")


def resolve_sentinel(
    value: str,
    *,
    same_key: str,
    machine_config: dict[str, Any],
) -> Any:
    """
    Resolve a sentinel string.

    Args:
        value:          The sentinel string (e.g. "@machine", "@machine:paths.shared_docs").
        same_key:       The dotted key being resolved in the project config, used for
                        "@machine" (no suffix) to look up the same key in machine config.
        machine_config: The flat dotted-key dict from machine config.

    Returns:
        Resolved value, or None for @disabled, or the original literal if the
        sentinel is not recognised (future-proofing).
    """
    if value == "@machine":
        return machine_config.get(same_key)

    if value.startswith("@machine:"):
        other_key = value[len("@machine:") :]
        return machine_config.get(other_key)

    if value == "@disabled":
        return None

    if value.startswith("@env:"):
        var_name = value[len("@env:") :]
        return os.environ.get(var_name)

    # Unknown sentinel — return literal (forward-compatible)
    return value
