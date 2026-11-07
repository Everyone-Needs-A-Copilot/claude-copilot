"""Adoption: tell framework-owned stale copies from owner-customized ones.

A real file or directory sitting where a release link belongs shadows the
release. It is FRAMEWORK-OWNED when every file in it matches (byte or
whitespace-normalized) some historical version of any framework item: the
git history of the framework repos, extracted older framework trees, or
recorded sha256 values from the old install's manifest/lock files. Such copies
are backed up and replaced by the link. Anything else is OWNER-CUSTOMIZED:
kept, not linked, and reported with a one-line diff summary.

Matching is by content digest alone (a file identical to a framework file is
framework content wherever it lives), so renames and moved skill folders match.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..engine import layout
from .plan import LinkPlan

ADOPT_BACKUP_DIR = Path("rollback") / "adopted"
# Where framework items have lived over time (repo-relative); other paths are not scanned.
HISTORY_PATHSPECS = (".claude/agents", ".claude/commands", ".claude/skills", "agents", "commands",
                     "skills", "plugins", "03-ai-enabling")
_TREE_SUBDIRS = (".claude/agents", ".claude/commands", ".claude/skills", "agents", "commands", "skills",
                 "plugins", "03-ai-enabling")
_JUNK_NAMES = {".DS_Store", "__pycache__", ".coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}
_JUNK_SUFFIXES = (".pyc", ".pyo")
_HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
_MAX_FILE_BYTES = 8 * 1024 * 1024


def normalize(data: bytes) -> bytes:
    """CRLF to LF, trailing whitespace stripped per line, trailing blank lines dropped."""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).rstrip("\n").encode("utf-8")


def _digests(data: bytes) -> tuple[str, str]:
    return hashlib.sha256(data).hexdigest(), hashlib.sha256(normalize(data)).hexdigest()


def is_junk(path: Path) -> bool:
    return (path.name in _JUNK_NAMES or path.name.endswith(_JUNK_SUFFIXES)
            or any(part in _JUNK_NAMES for part in path.parts))


class FrameworkIndex:
    """Digest set of every known framework file version."""

    def __init__(self) -> None:
        self.digests: set[str] = set()
        self.sources: dict[str, int] = {}
        self.roots: list[Path] = []  # checkouts and worktrees the release covers (symlink adoption)

    def add_root(self, root: Path | str) -> None:
        real = Path(os.path.realpath(root))
        if real not in self.roots:
            self.roots.append(real)

    def covers(self, real_path: Path) -> bool:
        return any(real_path == r or r in real_path.parents for r in self.roots)

    def add_bytes(self, data: bytes, source: str) -> None:
        raw, norm = _digests(data)
        before = len(self.digests)
        self.digests.update((raw, norm))
        self.sources[source] = self.sources.get(source, 0) + len(self.digests) - before

    def add_text_records(self, text: str, source: str) -> None:
        """Recorded sha256 values (manifests, lock files); name-agnostic."""
        found = set(_HEX64.findall(text))
        self.digests.update(found)
        self.sources[source] = self.sources.get(source, 0) + len(found)

    def add_tree(self, root: Path, source: str, subdirs: Iterable[str] = _TREE_SUBDIRS) -> None:
        for sub in subdirs:
            base = root / sub
            if not base.is_dir():
                continue
            for dirpath, dirs, files in os.walk(base, followlinks=False):
                dirs[:] = [d for d in dirs if d not in _JUNK_NAMES and d != ".git"]
                for name in files:
                    path = Path(dirpath) / name
                    if is_junk(path) or path.is_symlink():
                        continue
                    try:
                        if path.stat().st_size <= _MAX_FILE_BYTES:
                            self.add_bytes(path.read_bytes(), source)
                    except OSError:
                        continue

    def add_git_history(self, repo: Path, source: str, pathspecs: Iterable[str] = HISTORY_PATHSPECS) -> None:
        """Every blob ever committed under the pathspecs, across all refs."""
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--all", "--no-renames", "--raw", "--no-abbrev", "--format=",
             "--", *pathspecs], capture_output=True, text=True, check=False)
        if log.returncode != 0:
            return
        blobs: set[str] = set()
        for line in log.stdout.splitlines():
            head, _, _path = line.partition("\t")
            fields = head.split()
            # ":oldmode newmode oldsha newsha status"; symlinks (120000) and deletions carry no content
            if len(fields) >= 5 and fields[1] != "120000" and set(fields[3]) != {"0"}:
                blobs.add(fields[3])
        if not blobs:
            return
        proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert proc.stdin is not None and proc.stdout is not None
        try:
            import threading
            feeder = threading.Thread(
                target=lambda: (proc.stdin.write("".join(f"{b}\n" for b in sorted(blobs)).encode()),
                                proc.stdin.close()), daemon=True)
            feeder.start()
            while True:
                header = proc.stdout.readline()
                if not header:
                    break
                parts = header.split()
                if len(parts) < 3 or parts[1] != b"blob":
                    continue
                size = int(parts[2])
                data = proc.stdout.read(size)
                proc.stdout.read(1)
                if size <= _MAX_FILE_BYTES:
                    self.add_bytes(data, source)
            feeder.join()
        finally:
            proc.wait()

    def matches(self, data: bytes) -> bool:
        raw, norm = _digests(data)
        return raw in self.digests or norm in self.digests


def _git_dir(path: Path) -> bool:
    return (path / ".git").exists()


def _worktrees(repo: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return []
    return [Path(line[len("worktree "):]) for line in out.stdout.splitlines() if line.startswith("worktree ")]


def default_index(home: Path | str | None = None, release_dir: Path | str | None = None,
                  extra_repos: Iterable[Path | str] = ()) -> FrameworkIndex:
    """Index from what the machine records: release sources, older framework trees, lock records."""
    base = layout.home_root(home)
    copilot = layout.copilot_home(base)
    index = FrameworkIndex()
    repos: list[Path] = [Path(p) for p in extra_repos]
    manifest = Path(release_dir) / layout.MANIFEST_NAME if release_dir else layout.current_path(base) / layout.MANIFEST_NAME
    try:
        for comp in json.loads(manifest.read_text(encoding="utf-8")).get("components", []):
            repos.append(Path(str(comp.get("source", ""))))
    except (OSError, ValueError, AttributeError):
        pass
    seen: set[Path] = set()
    for repo in repos:
        repo = repo.expanduser()
        if repo in seen or not repo.is_dir() or not _git_dir(repo):
            continue
        seen.add(repo)
        index.add_git_history(repo, f"git:{repo.name}")
        index.add_root(repo)
        for tree in _worktrees(repo):
            index.add_root(tree)
    index.add_root(copilot)  # releases and the current pointer are framework by definition
    for parent, label in ((copilot / "framework-snapshots", "snapshot"), (copilot / layout.RELEASES_DIRNAME, "release")):
        if not parent.is_dir():
            continue
        for tree in sorted(p for p in parent.iterdir() if p.is_dir()):
            roots = [tree, tree / layout.COMPONENT_CLAUDE]
            roots += sorted((tree / "knowledge").glob("*")) if (tree / "knowledge").is_dir() else []
            for root in roots:
                index.add_tree(root, f"{label}:{tree.name}")
    for record in (copilot / "framework-install.lock", base / ".claude" / "cc" / "copilot.lock.json",
                   base / ".claude" / "cc" / "skill-distribution.json",
                   base / ".claude" / "agents" / "manifest.json"):
        try:
            index.add_text_records(record.read_text(encoding="utf-8"), f"record:{record.name}")
        except OSError:
            continue
    return index


@dataclass
class Adoption:
    path: str  # relative to HOME
    kind: str  # file | dir | symlink
    backup: str  # relative to HOME
    old_target: str = ""  # symlink adoption: where the link pointed before


@dataclass
class Customized:
    name: str
    path: str  # relative to HOME
    shadows: str  # the framework item (link target or its source) this copy shadows
    diff: str  # one-line summary

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path, "shadows": self.shadows, "diff": self.diff}


@dataclass
class AdoptionResult:
    adopt: list[Adoption] = field(default_factory=list)
    customized: list[Customized] = field(default_factory=list)


def _files_of(path: Path) -> dict[str, Path]:
    if path.is_file():
        return {"": path}
    out: dict[str, Path] = {}
    for dirpath, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _JUNK_NAMES)
        for name in sorted(files):
            p = Path(dirpath) / name
            if not is_junk(p):
                out[str(p.relative_to(path))] = p
    return out


def _is_framework_owned(path: Path, index: FrameworkIndex, generated: str | None = None) -> bool:
    files = _files_of(path)
    if not files:
        return path.is_dir()  # empty directory (or only junk): nothing of the owner's inside
    for rel, p in files.items():
        try:
            data = p.read_bytes()
        except OSError:
            return False
        if generated is not None and not rel and (data == generated.encode() or normalize(data) == normalize(generated.encode())):
            continue
        if not index.matches(data):
            return False
    return True


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _diff_summary(local: Path, target: Path, generated: str | None) -> str:
    if local.is_file():
        new = generated if generated is not None else (_read(target) if target.is_file() else "")
        a, b = _read(local).splitlines(), new.splitlines()
        added = removed = 0
        for line in difflib.unified_diff(b, a, lineterm="", n=0):
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return f"{added} line(s) added, {removed} removed versus the release version"
    local_files = _files_of(local)
    release_files = _files_of(target) if target.is_dir() else {}
    if generated is not None and (local / "SKILL.md").is_file():
        return _diff_summary(local / "SKILL.md", target, generated)
    differ = [r for r in local_files if r in release_files and normalize(local_files[r].read_bytes())
              != normalize(release_files[r].read_bytes())]
    only_local = [r for r in local_files if r not in release_files]
    only_release = [r for r in release_files if r not in local_files]
    return (f"{len(differ)} file(s) differ, {len(only_local)} only in your copy, "
            f"{len(only_release)} only in the release")


def _lexical_target(path: Path) -> Path:
    raw = Path(os.readlink(path))
    return raw if raw.is_absolute() else path.parent / raw


def _classify_symlink(home: Path, link: str, name: str, path: Path, index: FrameworkIndex,
                      out: AdoptionResult) -> None:
    """A symlink resolving into a covered checkout or worktree bypasses the release: adopt it.

    Anything else (another place, or a link to a copy the owner keeps) is owner content.
    """
    old = os.readlink(path)
    if str(_lexical_target(path)).startswith(str(layout.copilot_home(home)) + os.sep):
        return  # already served by a release: receipt-owned or foreign, apply decides, nothing bypasses
    real = Path(os.path.realpath(path))
    if index.covers(real):
        out.adopt.append(Adoption(link, "symlink", "", old))
        return
    out.customized.append(Customized(name, str(path), link,
                                     f"symlink to {old} (resolves to {real}), outside the checkouts the release covers"))


def _settle_chained(home: Path, out: AdoptionResult) -> None:
    """A link kept for pointing at a home skill dir that this run adopts follows that decision."""
    adopted = {a.path: a for a in out.adopt}
    for c in list(out.customized):
        path = Path(c.path)
        if not path.is_symlink():
            continue
        target = _lexical_target(path)
        try:
            rel = str(Path(os.path.normpath(target)).relative_to(os.path.normpath(home)))
        except ValueError:
            continue
        if rel in adopted and adopted[rel].kind != "symlink":
            out.customized.remove(c)
            out.adopt.append(Adoption(str(path.relative_to(home)), "symlink", "", os.readlink(path)))


def _classify(home: Path, link: str, name: str, target: str, generated: str | None,
              index: FrameworkIndex, out: AdoptionResult) -> None:
    path = home / link
    if path.is_symlink():
        _classify_symlink(home, link, name, path, index, out)
        return
    if not path.exists():
        return
    if _is_framework_owned(path, index, generated):
        out.adopt.append(Adoption(link, "file" if path.is_file() else "dir", ""))
    else:
        real_target = Path(os.path.realpath(target)) if os.path.lexists(target) else Path(target)
        out.customized.append(Customized(name, str(path), target, _diff_summary(path, real_target, generated)))


def classify(plan: LinkPlan, home: Path | str, index: FrameworkIndex) -> AdoptionResult:
    """Read-only: what adoption would do for each real item sitting at a link target or category folder."""
    base = Path(home)
    out = AdoptionResult()
    linked_names: dict[str, set[str]] = {}
    linked_links: set[str] = set()
    for e in plan.entries:
        linked_links.add(e.link)
        linked_names.setdefault(e.link.rsplit("/", 1)[0], set()).add(e.name)
        _classify(base, e.link, e.name, e.target, e.generated, index, out)
    # Category folders: real directories in a skills dir holding skills but not themselves linked.
    for parent in sorted({e.link.rsplit("/", 1)[0] for e in plan.entries if e.kind == "skill"}):
        root = base / parent
        if not root.is_dir() or root.is_symlink():
            continue
        names = linked_names.get(parent, set())
        for child in sorted(root.iterdir()):
            link = f"{parent}/{child.name}"
            if (child.name.startswith(".") or link in linked_links or child.is_symlink()
                    or not child.is_dir() or (child / "SKILL.md").is_file()):
                continue  # dot-folders (Codex's own .system) are tool-managed, never owner content
            nested = [p for p in _files_of(child).values() if p.name == "SKILL.md"]
            if not nested:
                continue
            overlap = sorted({p.parent.name for p in nested} & names)
            owned_any = any(index.matches(p.read_bytes()) for p in _files_of(child).values())
            if not overlap and not owned_any:
                continue  # unrelated to the framework
            if _is_framework_owned(child, index):
                out.adopt.append(Adoption(link, "dir", ""))
            else:
                bad = sorted(rel for rel, p in _files_of(child).items() if not index.matches(p.read_bytes()))
                out.customized.append(Customized(
                    child.name, str(child), f"category folder shadowing {', '.join(overlap) or 'framework skills'}",
                    f"{len(bad)} file(s) not matching any framework version, e.g. {', '.join(bad[:3])}"))
    _settle_chained(base, out)
    return out


KEPT_DIRS = (".claude/agents", ".claude/commands", ".claude/skills", ".claude/rules", ".codex/skills")


def inventory_kept(plan: LinkPlan, home: Path | str, accounted: Iterable[str],
                   index: FrameworkIndex | None = None) -> list[dict[str, str]]:
    """Every real entry left in a managed category directory that no link serves and nothing else listed.

    origin: `framework-archive` (an `_archive` folder, shipped with the framework but never served),
    `tool-managed` (dot-folders such as Codex's `.system`), `framework-copy` (matches a framework version
    the release no longer serves), else `owner`. Nothing here is ever changed.
    """
    base = Path(home)
    skip = set(accounted)
    planned = {e.link for e in plan.entries}
    out: list[dict[str, str]] = []
    for rel in KEPT_DIRS:
        root = base / rel
        if not root.is_dir() or root.is_symlink():
            continue
        for child in sorted(root.iterdir()):
            link = f"{rel}/{child.name}"
            if link in skip or child.name == ".DS_Store":
                continue
            if child.is_symlink() and str(_lexical_target(child)).startswith(str(layout.copilot_home(base)) + os.sep):
                continue  # served by a release (receipt-owned or foreign link), not an owner item
            if child.name == "_archive":
                origin, reason = "framework-archive", "archive folder; not served by releases"
            elif child.name.startswith("."):
                origin, reason = "tool-managed", "managed by its own tool"
            elif index is not None and not child.is_symlink() and _is_framework_owned(child, index):
                origin, reason = "framework-copy", "matches a framework version this release does not serve"
            else:
                origin = "owner"
                reason = ("owner item shadows a planned release link; left untouched" if link in planned
                          else "not part of any release; left untouched")
            out.append({"path": link, "origin": origin, "reason": reason})
    return out


def backup_dir(home: Path | str, release_id: str) -> Path:
    return layout.copilot_home(home) / ADOPT_BACKUP_DIR / release_id


def serialize(result: AdoptionResult) -> dict[str, Any]:
    return {"adopt": [a.__dict__ for a in result.adopt], "customized": [c.as_dict() for c in result.customized]}
