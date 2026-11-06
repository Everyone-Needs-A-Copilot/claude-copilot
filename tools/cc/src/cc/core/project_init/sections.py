"""Thin delimited framework section for CLAUDE.md and AGENTS.md.

Appended only when absent. Existing content is never rewritten; a second run
changes nothing. Framework text lives in the release, not the project.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

SECTION_BEGIN = "<!-- copilot:framework-section:begin v1 -->"
SECTION_END = "<!-- copilot:framework-section:end -->"

_BODY = """## Copilot

This project runs on the Copilot framework (Claude and Codex), resolved from this machine's installed release. Project-specific rules belong outside this delimited section. Health: `cc doctor`."""

SECTION = f"{SECTION_BEGIN}\n{_BODY}\n{SECTION_END}\n"


def has_section(text: str) -> bool:
    return SECTION_BEGIN in text


def ensure_section(path: Path, project_name: str) -> bool:
    """Append the section if absent (create the file if missing). True if changed."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        data = None
    if data is None:
        new = f"# {project_name}\n\n{SECTION}".encode()
    else:
        text = data.decode("utf-8", errors="surrogateescape")
        if has_section(text):
            return False
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        new = data + (sep + SECTION).encode("utf-8", errors="surrogateescape")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(new)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True
