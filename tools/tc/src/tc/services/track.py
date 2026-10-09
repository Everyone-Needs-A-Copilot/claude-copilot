"""tc.services.track — keep a project's task state committed to Git.

Standard (tc 2.4): a project commits ``.copilot/tasks.db``, its archive
``.copilot/tasks.db-history`` and the ``.copilot/wp/`` work-product files, so
its tasks travel with the repository between machines. SQLite's WAL, SHM and
journal files and the auto-archive stamp stay ignored.

``ensure_tracked`` writes that rule into the project's ``.gitignore`` as one
managed block and removes older rules that ignored the database. A bare
``.copilot/`` rule becomes ``.copilot/*``, which ignores the same contents but
lets the block re-include the task files (Git cannot re-include a file inside
an ignored directory). Line endings are preserved.

Opt-out: a public repository must not publish its task state (work products
hold internal notes and machine paths). A ``.gitignore`` containing the line
``# tc: task state stays local`` is left untouched.

Interim: committed SQLite cannot merge, so work on one machine at a time and
pull before starting. Git-mergeable task files are the planned successor
(codex-copilot ADR-001).

This module has ZERO import-time side effects.
"""

from __future__ import annotations

from pathlib import Path

BEGIN = "# >>> tc task state (committed so tasks travel with the project)"
END = "# <<< tc task state"
BLOCK = (
    BEGIN,
    "!.copilot/tasks.db",
    "!.copilot/tasks.db-history",
    "!.copilot/wp/",
    ".copilot/*.db-wal",
    ".copilot/*.db-shm",
    ".copilot/*-journal",
    ".copilot/tasks.db-archive-stamp",
    END,
)
OPT_OUT = "# tc: task state stays local"
_WHOLE_DIR = {".copilot/", ".copilot", "/.copilot/", "/.copilot"}
_DB_RULES = {
    ".copilot/tasks.db", ".copilot/tasks.db*", "/.copilot/tasks.db", "/.copilot/tasks.db*",
    ".copilot/tasks.db-wal", ".copilot/tasks.db-shm", "/.copilot/tasks.db-wal", "/.copilot/tasks.db-shm",
}


def rendered(text: str) -> str:
    """``text`` (a .gitignore) rewritten to the standard (unchanged if opted out)."""
    if OPT_OUT in text.splitlines():
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    if BEGIN in lines and END in lines[lines.index(BEGIN):]:
        i = lines.index(BEGIN)
        j = lines.index(END, i)
        lines = lines[:i] + lines[j + 1:]
    out = []
    for line in lines:
        s = line.strip()
        if s in _WHOLE_DIR:
            out.append(line.replace(s, s.rstrip("/") + "/*"))
        elif s not in _DB_RULES:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return newline.join(out + ([""] if out else []) + list(BLOCK)) + newline


def ensure_tracked(project_root: Path, *, check: bool = False) -> bool:
    """Bring ``project_root/.gitignore`` to the standard. Returns True if it
    changed (or, with ``check``, would change)."""
    gi = Path(project_root) / ".gitignore"
    old = gi.read_bytes().decode("utf-8") if gi.exists() else ""
    new = rendered(old)
    if new == old:
        return False
    if not check:
        gi.write_bytes(new.encode("utf-8"))
    return True
