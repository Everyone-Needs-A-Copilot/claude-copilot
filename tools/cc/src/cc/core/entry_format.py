"""Entry format: frontmatter schema, validation, and serialization for memory entries."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

VALID_TYPES = frozenset({"decision", "context", "lesson", "reference", "person"})


class EntryValidationError(ValueError):
    """Raised when a memory entry fails schema validation."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_entry_type(entry_type: str) -> str:
    """Return entry_type if valid, else raise EntryValidationError."""
    if entry_type not in VALID_TYPES:
        raise EntryValidationError(
            f"Invalid type {entry_type!r}. Must be one of: {sorted(VALID_TYPES)}"
        )
    return entry_type


def parse_tags(raw: str | list[str] | None) -> list[str]:
    """Normalise tags from comma-separated string or list to a sorted list of stripped tokens."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return sorted(t.strip() for t in raw if t.strip())
    return sorted(t.strip() for t in raw.split(",") if t.strip())


def build_frontmatter(
    *,
    entry_id: str,
    entry_type: str,
    tags: list[str],
    scope: str,
    created: str | None = None,
    updated: str | None = None,
) -> dict[str, Any]:
    """Build a validated frontmatter dict for a new or updated entry."""
    validate_entry_type(entry_type)
    now = _now_iso()
    return {
        "id": entry_id,
        "type": entry_type,
        "tags": tags,
        "created": created or now,
        "updated": updated or now,
        "scope": scope,
    }


def serialize_frontmatter(fm: dict[str, Any]) -> str:
    """Render frontmatter dict to YAML block (no external dependency)."""
    lines = ["---"]
    for key in ("id", "type", "tags", "created", "updated", "scope"):
        value = fm.get(key)
        if isinstance(value, list):
            items = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{items}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Parse YAML frontmatter from a markdown string.

    Returns (frontmatter_dict, body_text).
    Raises EntryValidationError if the opening --- block is missing.
    """
    if not text.startswith("---"):
        raise EntryValidationError("Entry is missing frontmatter block.")

    # Find the closing ---
    end = text.find("\n---", 3)
    if end == -1:
        raise EntryValidationError("Frontmatter block is not closed.")

    raw_yaml = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")

    fm: dict[str, Any] = {}
    for line in raw_yaml.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # Parse list values: [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            fm[key] = [v.strip() for v in inner.split(",") if v.strip()] if inner.strip() else []
        else:
            fm[key] = val

    return fm, body


def render_entry(fm: dict[str, Any], body: str) -> str:
    """Combine frontmatter dict and body into a full entry markdown string."""
    return serialize_frontmatter(fm) + "\n" + body.rstrip("\n") + "\n"
