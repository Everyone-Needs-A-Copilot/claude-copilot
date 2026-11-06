"""Source-repo guard: a framework source repo's own files are never "framework copies".

The framework index holds every byte the framework ever released, including the target repo's
own files and its siblings', so the classifier cannot tell a source file from a synced copy by
content. This module decides by role instead. The protected set comes from what the release
reads (the contract below mirrors `release/links/plan.py`, `release/codex/marketplace.py` and the
release build) and from what a live user-level link resolves into (`links.json`).
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from cc.core.project_init.marker import read_marker
from cc.core.release.engine import layout

LOCKS = ("copilot.lock.json", ".codex-copilot.json")  # consumer artefacts: never protected
BRIDGES = (".claude/skills/codex-copilot", ".claude/skills/codex-copilot-internal")
ALL = "."  # the whole tree is read (the release archives it)
SOURCE_LABEL = "source (kept)"

_CLAUDE_COMMON = (".claude/skills", "skills")
_CLI_ROOTS = (".claude/skills", ".agents/skills", ".claude/rules", ".claude/commands/setup-integration.md",
              "scripts", ".claude/hooks/state", "copilot_overlay", "cli.overlay.yml",
              "copilot.layer.yml", "copilot.layers.yml")
_KNOWLEDGE_ROOTS = ("03-ai-enabling", ".claude/extensions", ".claude/rules", ".claude/settings.template.json",
                    ".claude/skills/README.md", ".agents/skills", "scripts")
# Repos the release reads that are not release.json components with a checkout of their own.
_ALIASES = {"copilot-control-tower": layout.COMPONENT_CONTROL_TOWER}


def read_roots(name: str, repo: str) -> tuple[str, ...]:
    """Paths (relative, prefixes) the release reads from component `name` (`repo` = checkout name)."""
    if name in (layout.COMPONENT_CLAUDE, layout.COMPONENT_CODEX):
        return (ALL,)  # whole tree archived; the Codex skill bridge and marketplace live inside it
    if name == layout.COMPONENT_CLI:
        return _CLI_ROOTS
    if name == layout.COMPONENT_PRODUCT_CREATION:
        return (".claude/rules", "scripts", "skills")
    if name == layout.COMPONENT_CONTROL_TOWER:
        return ("scripts/tests/fixtures",)
    product, _, _tier = name.partition("/")
    if product == layout.KNOWLEDGE_PRODUCT:
        return _KNOWLEDGE_ROOTS
    if product == "claude":
        return _CLAUDE_COMMON  # overlay agents/commands are stale copies, never sources
    if product == "codex":
        return (f"plugins/{repo}", "skills")  # the tier's own plugin; plugins/codex-copilot is the foundation's
    if product == "cli":
        return _CLI_ROOTS
    return ()


def _under(rel: str, prefix: str) -> bool:
    return prefix == ALL or rel == prefix or rel.startswith(prefix.rstrip("/") + "/")


@dataclass
class SourceGuard:
    name: str = ""                       # release component this repo is a source of ("" = not one)
    prefixes: list[str] = field(default_factory=list)
    globs: list[str] = field(default_factory=list)   # copilot.project.json protectedPaths
    linked: list[str] = field(default_factory=list)  # live link targets resolving into this repo
    excluded: tuple[str, ...] = ()

    @property
    def is_source(self) -> bool:
        return bool(self.name)

    @property
    def active(self) -> bool:
        return bool(self.prefixes or self.globs or self.linked)

    def why(self, rel: str) -> Optional[str]:
        if rel in LOCKS:
            return None
        for g in self.globs:
            if fnmatch.fnmatch(rel, g) or _under(rel, g.rstrip("/*")):
                return f"{SOURCE_LABEL}: declared in copilot.project.json protectedPaths"
        for p in self.linked:
            if _under(rel, p):
                return f"{SOURCE_LABEL}: a live user-level link resolves into it"
        if any(_under(rel, e) for e in self.excluded):
            return None
        for p in self.prefixes:
            if _under(rel, p):
                return f"{SOURCE_LABEL}: the release reads this path from {self.name}"
        return None

    def protects(self, rel: str) -> bool:
        return self.why(rel) is not None


def _real(p: str | Path) -> str:
    return os.path.realpath(str(p))


def _common_dir_name(root: Path) -> str:
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return ""
    common = Path(out.stdout.strip())
    return common.parent.name if common.name == ".git" else ""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def default_release_dir() -> Path:
    from cc.core.project_init.homes import copilot_home

    return copilot_home() / layout.CURRENT_NAME


def live_link_targets(release_dir: Path) -> dict[str, set[str]]:
    """component path (release.json `path`) -> repo-relative paths a live link target resolves into.

    Both the link path as the release sees it and its resolved path count: a bridge symlink inside
    claude-copilot is read through, so the symlink and the files behind it are one contract.
    """
    manifest = _load(release_dir / "release.json") or {}
    links = _load(release_dir / "links.json") or {}
    comps = sorted((str(c.get("path", "")) for c in manifest.get("components", []) if c.get("path")),
                   key=len, reverse=True)
    sources = {str(c.get("path")): _real(c["source"]) for c in manifest.get("components", [])
               if c.get("path") and c.get("source")}
    out: dict[str, set[str]] = {}
    base = _real(release_dir)
    for entry in links.get("entries", []):
        target = str(entry.get("target", ""))
        marker = f"/{layout.CURRENT_NAME}/"
        if marker not in target:
            continue
        sub = target.split(marker, 1)[1]
        comp = next((c for c in comps if sub == c or sub.startswith(c + "/")), None)
        if comp is None:
            continue
        inside = sub[len(comp):].lstrip("/")
        found = out.setdefault(comp, set())
        if inside:
            found.add(inside)
        resolved = _real(release_dir / sub)
        for root, repo_rel in ((os.path.join(base, comp), None), (sources.get(comp), None)):
            if root and resolved.startswith(root + os.sep):
                found.add(os.path.relpath(resolved, root))
    return out


def build_guard(project: Path, release_dir: Optional[Path | str] = None) -> SourceGuard:
    root = Path(project)
    release = Path(release_dir) if release_dir else default_release_dir()
    manifest = _load(release / "release.json") or {}
    real_root = _real(root)
    names = {_real(root).rsplit(os.sep, 1)[-1], _common_dir_name(root)} - {""}
    guard = SourceGuard()
    comp: Optional[dict[str, Any]] = None
    for c in manifest.get("components", []):
        src = str(c.get("source", ""))
        if src and (_real(src) == real_root or os.path.basename(src.rstrip("/")) in names):
            comp = c
            break
    repo = next(iter(names), root.name)
    if comp is not None:
        guard.name = str(comp["name"])
        repo = os.path.basename(str(comp["source"]).rstrip("/"))
    else:
        alias = next((_ALIASES[n] for n in names if n in _ALIASES), "")
        guard.name = alias
    if guard.name:
        guard.prefixes = list(read_roots(guard.name, repo))
        guard.excluded = BRIDGES if ALL not in guard.prefixes else ()
        if comp is not None:
            guard.linked = sorted(live_link_targets(release).get(str(comp.get("path", "")), set()))
    declared = read_marker(root).get("protectedPaths")
    if isinstance(declared, list):
        guard.globs = [g for g in declared if isinstance(g, str) and g]
    return guard


def split_protected(paths: Iterable[str], guard: SourceGuard) -> tuple[list[str], list[str]]:
    keep, rest = [], []
    for p in paths:
        (keep if guard.protects(p) else rest).append(p)
    return keep, rest
