"""Every byte the framework has ever released, found by content (git blob id), not by lock records.

Built from the full history of each framework repository (all refs, every path, nested skill folders,
non-Markdown files, plugin trees and symlinks) plus any non-Git release snapshot. A project file is a
framework copy when its bytes were released under the same file name; nothing else decides it.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

_ZERO = "0" * 40
_SIBLINGS = re.compile(r"^(claude|codex|cli|knowledge|product-creation)-copilot(-(internal|private|accounting|public))?$")
_EMPTY_BLOB = hashlib.sha1(b"blob 0\0").hexdigest()
_WALK_SKIP = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".worktrees"}
_MAX_SNAPSHOT_FILE = 5_000_000


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def path_blob_id(path: Path) -> Optional[tuple[str, bool]]:
    """(git blob id, is_symlink) for a file or symlink; None when unreadable."""
    try:
        if path.is_symlink():
            return blob_id(os.readlink(path).encode("utf-8", "surrogateescape")), True
        return blob_id(path.read_bytes()), False
    except OSError:
        return None


@dataclass
class FrameworkIndex:
    files: dict[str, set[str]] = field(default_factory=dict)   # blob id -> file names it shipped under
    links: dict[str, set[str]] = field(default_factory=dict)   # symlink-target blob id -> link names

    def add(self, blob: str, name: str, link: bool) -> None:
        if blob != _EMPTY_BLOB and blob != _ZERO:
            (self.links if link else self.files).setdefault(blob, set()).add(name)

    def matches(self, path: Path) -> Optional[str]:
        """The blob id when `path`'s bytes were released under this file name, else None."""
        got = path_blob_id(path)
        if got is None:
            return None
        blob, link = got
        return blob if path.name in (self.links if link else self.files).get(blob, ()) else None

    def __bool__(self) -> bool:
        return bool(self.files or self.links)

    def add_git_history(self, repo: Path) -> None:
        proc = subprocess.run(
            ["git", "-C", str(repo), "log", "--all", "--format=", "--raw", "--no-abbrev", "--no-renames", "-z"],
            capture_output=True, check=False)
        if proc.returncode != 0:
            return
        parts = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
        for i in range(0, len(parts) - 1, 2):
            meta = parts[i].lstrip("\n").split()
            if len(meta) < 5 or not meta[0].startswith(":"):
                continue
            mode, sha = meta[1], meta[3]
            if mode in ("160000", "000000"):
                continue
            self.add(sha, parts[i + 1].rsplit("/", 1)[-1], mode == "120000")

    def add_tree(self, root: Path) -> None:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in _WALK_SKIP]
            for n in fns + [d for d in dns if (Path(dp) / d).is_symlink()]:
                p = Path(dp) / n
                try:
                    if p.is_file() and not p.is_symlink() and p.stat().st_size > _MAX_SNAPSHOT_FILE:
                        continue
                except OSError:
                    continue
                got = path_blob_id(p)
                if got:
                    self.add(got[0], n, got[1])


def _git_toplevel(path: Path) -> Optional[Path]:
    """The main checkout of the repository `path` belongs to (linked worktrees resolve to it)."""
    if not path.is_dir():
        return None
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    common = Path(proc.stdout.strip())
    return common.parent if common.name == ".git" else common


def discover_repos(roots: Iterable[Optional[Path]]) -> tuple[list[Path], list[Path]]:
    """(git repositories, non-git snapshot trees) that make up the released framework."""
    repos: list[Path] = []
    trees: list[Path] = []

    def add_repo(p: Path) -> None:
        if p not in repos:
            repos.append(p)

    for env in filter(None, os.environ.get("CC_FRAMEWORK_REPOS", "").split(os.pathsep)):
        top = _git_toplevel(Path(env).expanduser())
        add_repo(top) if top else trees.append(Path(env).expanduser())
    for root in roots:
        if root is None or not Path(root).is_dir():
            continue
        top = _git_toplevel(Path(root))
        if top is None:
            if Path(root) not in trees:
                trees.append(Path(root))
            continue
        add_repo(top)
        try:
            for sib in sorted(top.parent.iterdir()):
                if _SIBLINGS.match(sib.name) and (sib / ".git").exists():
                    add_repo(sib)
        except OSError:
            pass
    return repos, trees


def build_index(repos: Iterable[Path] = (), trees: Iterable[Path] = ()) -> FrameworkIndex:
    index = FrameworkIndex()
    for r in repos:
        index.add_git_history(Path(r))
    for t in trees:
        index.add_tree(Path(t))
    return index
