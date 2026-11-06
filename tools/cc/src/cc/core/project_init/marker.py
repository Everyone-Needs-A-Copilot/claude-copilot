"""The project marker (copilot.project.json): the one writer.

Every project gets BOTH runtimes. There is no Claude-only declaration, so the
writer takes no runtime argument. Existing optional keys (activePacks and
unknown keys) are preserved on rewrite.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

MARKER_FILENAME = "copilot.project.json"
MARKER_SCHEMA_VERSION = "1.0"
RUNTIMES = ("claude", "codex")


def read_marker(project: Path | str) -> dict[str, Any]:
    """Return the existing marker object, or {} when absent or unreadable."""
    try:
        raw = json.loads((Path(project) / MARKER_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def build_marker(existing: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    marker = {k: v for k, v in (existing or {}).items()}
    marker["schema_version"] = MARKER_SCHEMA_VERSION
    marker["components"] = list(RUNTIMES)  # legacy readers (workspaces.read_declaration)
    marker["runtimes"] = list(RUNTIMES)
    return marker


def write_marker(project: Path | str) -> bool:
    """Write the marker atomically. Returns True when bytes changed."""
    root = Path(project)
    target = root / MARKER_FILENAME
    payload = (json.dumps(build_marker(read_marker(root)), indent=2, sort_keys=True) + "\n").encode()
    try:
        if target.read_bytes() == payload:
            return False
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=root, prefix=".copilot.project.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True
