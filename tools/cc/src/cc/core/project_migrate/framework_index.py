"""Released framework capabilities, found by content (git blob id), not only lock records.

Built from distributed capability paths across framework history and release snapshots. Historical
product trees in those repositories are not capability provenance. Project copies must match both
the released bytes and file name; explicit project ownership is handled by the migration planner.
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

# History also contains former product trees and acceptance replicas. Their bytes
# are not evidence that a file was distributed as a Copilot capability.
_CAPABILITY_ROOTS = (
    ".claude/agents", ".claude/commands", ".claude/hooks", ".claude/skills",
    ".claude/extensions", ".claude/rules", ".claude/evals", ".codex/agents", ".codex/skills", ".codex/hooks", ".agents/skills",
    ".agents/plugins", "plugins", "skills", "commands", "templates/central-hooks", "templates/hooks", "templates/commands",
    "03-ai-enabling/01-skills",
    "00-best-practices/03-templates/07-initiative-package/bin",
)
_CAPABILITY_FILES = {".claude/fitness-check.sh", ".claude/settings.template.json", ".codex/hooks.json"}
_SHARED_KNOWLEDGE_SCRIPTS = (
    "scripts/initiatives/", "scripts/copilot-", "scripts/check-",
    "scripts/install-", "scripts/backfill-freshness",
)


def framework_source(root: Path, rel: str) -> bool:
    """Whether a historical path is a distributed capability, rather than product data.

    Knowledge repositories formerly housed entire applications. Root scripts in
    that history need current canonical source or a shared-tool namespace; legacy
    shared tools remain recognizable after retirement. Lock records independently
    prove other historically deployed files.
    """
    if rel.startswith(".claude/hooks/state/"):
        return False
    if rel in _CAPABILITY_FILES:
        return True
    if any(rel == base or rel.startswith(base + "/") for base in _CAPABILITY_ROOTS):
        return True
    if rel.startswith("scripts/"):
        return (not root.name.startswith("knowledge-copilot")
                or (root / rel).is_file()
                or rel.startswith(_SHARED_KNOWLEDGE_SCRIPTS))
    return False


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
            rel = parts[i + 1]
            if framework_source(repo, rel):
                self.add(sha, rel.rsplit("/", 1)[-1], mode == "120000")

    def add_tree(self, root: Path) -> None:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in _WALK_SKIP]
            for n in fns + [d for d in dns if (Path(dp) / d).is_symlink()]:
                p = Path(dp) / n
                if not framework_source(root, p.relative_to(root).as_posix()):
                    continue
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
        else:
            add_repo(top)
        # Sibling framework repos: git checkouts by history, release snapshots (no .git) by content.
        try:
            for sib in sorted((top or Path(root)).parent.iterdir()):
                if not (_SIBLINGS.match(sib.name) and sib.is_dir()):
                    continue
                if (sib / ".git").exists():
                    add_repo(sib)
                elif top is None and sib not in trees:
                    trees.append(sib)
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
