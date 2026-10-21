"""Which project files the project has claimed for itself.

A project may keep its own agent or command under a framework name and mark it
`owner: project` in its frontmatter: the documented way to stop sync from
replacing it (CLAUDE.md "Project-Owned Agents"). Such a file is never
framework-owned. Installs and updates must not overwrite it or record it in the
lock, verification must not call it drift even if an older lock recorded it,
and it must never hold a project for an owner decision. Conformance check
`lock.ownership.frontmatter_agrees` states the same rule.
"""

from __future__ import annotations

import stat
from pathlib import Path

from cc.core.entry_format import EntryValidationError, parse_frontmatter


def declares_project_owner(path: Path) -> bool:
    """Whether a regular markdown file declares `owner: project` in its frontmatter."""
    if not path.name.endswith(".md"):
        return False
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return False
        frontmatter, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, EntryValidationError):
        return False
    return frontmatter.get("owner") == "project"
