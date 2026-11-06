"""Small shared helpers (hashing, git status, atomic writes)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def sha256_file(path: Path) -> Optional[str]:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def is_git_repo(project: Path) -> bool:
    return (project / ".git").exists()


def git_dirty_paths(project: Path) -> list[str]:
    """Porcelain paths (project-relative, '/'-separated; untracked dirs end with '/')."""
    proc = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain", "-z", "--untracked-files=normal"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        return []
    out: list[str] = []
    entries = proc.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        status, path = e[:2], e[3:]
        out.append(path)
        if "R" in status or "C" in status:
            if i < len(entries) and entries[i]:
                out.append(entries[i])
            i += 1
    return out


def overlaps(dirty: str, affected: str) -> bool:
    d = dirty.rstrip("/")
    a = affected.rstrip("/")
    return d == a or a.startswith(d + "/") or d.startswith(a + "/")


def atomic_write(path: Path, data: bytes, mode: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        if mode is None:
            try:
                mode = path.stat().st_mode & 0o7777
            except OSError:
                mode = 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
