"""Link plan: which user-level links both runtimes get from one release.

Precedence (first source wins a name; mirrors `cc skill` project -> machine ->
knowledge, with company tiers nearest first as in CC_KNOWLEDGE_REPOS):
  claude overlays (personal, department, organization), framework
  (claude-copilot), product-creation-copilot, knowledge tiers (personal,
  department, organization, foundation).
An item in a claude overlay tier (personal, department, organization) whose files are all identical
to some released framework version (the release's own framework trees plus the git history of the
framework repos) is a stale copy: it never shadows the release, and is listed in `stale_copies`. A
personal item that really differs still overrides and is listed in `personal_overrides`.
Link targets always go through `<copilot home>/current/...`, never into a
release directory or a worktree.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from cc.core.skill_store import _parse_skill_frontmatter, _skill_name_from_fm

from ..engine import layout

TIER_ORDER = (
    layout.TIER_PERSONAL,
    layout.TIER_DEPARTMENT_ACCOUNTING,
    layout.TIER_ORGANIZATION,
    layout.TIER_FOUNDATION,
)
OVERLAY_ORDER = tuple(t for t in TIER_ORDER if t in layout.OVERLAY_TIERS)
KNOWLEDGE_SKILLS_SUBPATH = Path("03-ai-enabling") / "01-skills"
FRAMEWORK_RULES_IMPORT = (
    f"@~/.copilot/{layout.CURRENT_NAME}/{layout.COMPONENT_CLAUDE}/templates/framework-rules.md"
)
PLAN_SCHEMA = 1
CLAUDE, CODEX = "claude", "codex"
_SKIP_DIRS = {"_archive", "node_modules"}
FRAMEWORK_AGENT_FILES = ("manifest.json", "manifest.schema.json")  # framework artifacts beside the agents
PERSONAL_SOURCES = (f"claude/{layout.TIER_PERSONAL}", f"{layout.KNOWLEDGE_PRODUCT}/{layout.TIER_PERSONAL}")
_FRAMEWORK_TREES = (layout.COMPONENT_CLAUDE, layout.COMPONENT_CODEX, layout.COMPONENT_PRODUCT_CREATION)
SAFE_LINK_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")


def is_safe_link_name(name: str) -> bool:
    """A single path component from a conservative charset (no separators, no leading dot)."""
    return bool(SAFE_LINK_NAME.match(name)) and name not in (".", "..")


def is_safe_link_path(link: str) -> bool:
    """`.claude|.codex / <dir> / <safe name>` relative to HOME, nothing else."""
    parts = link.split("/")
    return (len(parts) == 3 and parts[0] in (".claude", ".codex") and is_safe_link_name(parts[1])
            and is_safe_link_name(parts[2]))


@dataclass(frozen=True)
class LinkEntry:
    runtime: str  # claude | codex
    kind: str  # skill | agent | command | rule
    name: str
    link: str  # path relative to HOME
    target: str  # absolute, through <home>/.copilot/current
    source: str  # e.g. "knowledge/organization"
    description_chars: int = 0
    generated: str | None = None  # file content when the link points at a generated dir


@dataclass
class LinkPlan:
    release_id: str
    entries: list[LinkEntry] = field(default_factory=list)
    shadowed: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    agents_block: str | None = None
    description_chars: dict[str, int] = field(default_factory=dict)
    skill_counts: dict[str, int] = field(default_factory=dict)
    project_collisions: list[dict[str, str]] = field(default_factory=list)
    stale_copies: list[dict[str, str]] = field(default_factory=list)  # overlay copies of framework files; release wins
    personal_overrides: list[dict[str, str]] = field(default_factory=list)  # personal items that really differ


def _iter_skill_dirs(base: Path) -> Iterable[Path]:
    """Yield directories under base holding SKILL.md (symlinks followed, not entered below a skill)."""
    for root, dirs, files in os.walk(base, followlinks=True):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
        if "SKILL.md" in files:
            dirs[:] = []
            yield Path(root)


def _skill_info(skill_dir: Path) -> tuple[str, int]:
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return skill_dir.name, 0
    fm = _parse_skill_frontmatter(text)
    return _skill_name_from_fm(fm, skill_dir.name), len(str(fm.get("description", "") or ""))


class _Builder:
    def __init__(self, release_dir: Path, home: Path | str | None, tiers: tuple[str, ...],
                 framework_repos: Iterable[Path | str] = ()) -> None:
        self.release = release_dir
        self.framework_repos = [Path(p) for p in framework_repos]
        self._index: Any = None
        self.current = layout.current_path(home)
        self.tiers = tiers
        self.plan = LinkPlan(release_id=release_dir.name)
        self.taken: dict[tuple[str, str, str], LinkEntry] = {}
        self.home = layout.home_root(home)

    def component_root(self, rel: str) -> Path | None:
        root = self.release / rel
        if not root.is_dir():
            return None
        if ".worktrees" in root.resolve().parts:
            self.plan.warnings.append(f"{rel}: resolves into a .worktrees path; skipped")
            return None
        return root

    def framework_index(self) -> Any:
        if self._index is None:
            from .adopt import FrameworkIndex  # adopt imports this module

            index = FrameworkIndex()
            for comp in _FRAMEWORK_TREES:
                index.add_tree(self.release / comp, f"release:{comp}")
            for repo in self.framework_repos:
                if (repo / ".git").exists():
                    index.add_git_history(repo, f"git:{repo.name}")
            self._index = index
        return self._index

    def is_stale_copy(self, path: Path, source: str) -> bool:
        if not source.startswith("claude/") or source.split(" ")[0] not in (
                f"claude/{t}" for t in OVERLAY_ORDER):
            return False
        from .adopt import _is_framework_owned

        return _is_framework_owned(path, self.framework_index())

    def target_for(self, path: Path) -> str:
        return str(self.current / path.relative_to(self.release))

    def add(self, runtime: str, kind: str, name: str, link: str, path: Path, source: str,
            chars: int = 0, generated: str | None = None, target: str | None = None) -> None:
        if not is_safe_link_path(link):
            self.plan.warnings.append(f"unsafe link name rejected: {name!r} ({source}) -> {link!r}")
            return
        key = (runtime, kind, name)
        if self.is_stale_copy(path, source.split(" ")[0]):
            self.plan.stale_copies.append({"runtime": runtime, "kind": kind, "name": name, "source": source.split(" ")[0]})
            return
        entry = LinkEntry(runtime, kind, name, link, target or self.target_for(path), source, chars, generated)
        winner = self.taken.get(key)
        if winner is not None:
            self.plan.shadowed.append({"runtime": runtime, "kind": kind, "name": name,
                                       "winner": winner.source, "shadowed": source})
            return
        self.taken[key] = entry
        self.plan.entries.append(entry)


def _skill_roots(b: _Builder) -> list[tuple[str, Path]]:
    """(source, skills dir); codex-copilot's root-level `skills/` serves both runtimes."""
    roots: list[tuple[str, Path]] = []
    for tier in OVERLAY_ORDER:
        if tier not in b.tiers:
            continue
        rel = f"claude/{tier}"
        root = b.component_root(rel)
        if root is not None:
            for sub in ("skills", ".claude/skills"):
                if (root / sub).is_dir():
                    roots.append((rel, root / sub))
    for rel, sub in ((layout.COMPONENT_CLAUDE, ".claude/skills"),
                     (layout.COMPONENT_PRODUCT_CREATION, "skills")):
        root = b.component_root(rel)
        if root is not None and (root / sub).is_dir():
            roots.append((rel, root / sub))
    codex = b.component_root(layout.COMPONENT_CODEX)
    if codex is not None and (codex / "skills").is_dir():
        roots.append((layout.COMPONENT_CODEX, codex / "skills"))
    for tier in b.tiers:
        rel = f"{layout.KNOWLEDGE_PRODUCT}/{tier}"
        root = b.component_root(rel)
        if root is not None and (root / KNOWLEDGE_SKILLS_SUBPATH).is_dir():
            roots.append((rel, root / KNOWLEDGE_SKILLS_SUBPATH))
    return roots


def _codex_plugin_skill_names(b: _Builder) -> set[str]:
    root = b.release / layout.COMPONENT_CODEX / "plugins"
    names: set[str] = set()
    if root.is_dir():
        for skills in root.glob("*/skills"):
            names.update(p.name for p in skills.iterdir() if p.is_dir())
    return names


def _plan_skills(b: _Builder) -> None:
    plugin_names = _codex_plugin_skill_names(b)
    for source, base in _skill_roots(b):
        for skill_dir in sorted(_iter_skill_dirs(base)):
            name, chars = _skill_info(skill_dir)
            b.add(CLAUDE, "skill", name, f".claude/skills/{name}", skill_dir, source, chars)
            if name in plugin_names and source != layout.COMPONENT_CODEX:
                b.plan.warnings.append(
                    f"codex skill '{name}' ({source}) not linked: the codex plugin already serves that name")
                continue
            b.add(CODEX, "skill", name, f".codex/skills/{name}", skill_dir, source, chars)


def _claude_item_roots(b: _Builder, subs: tuple[str, ...]) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    comps = [f"claude/{t}" for t in OVERLAY_ORDER if t in b.tiers] + [layout.COMPONENT_CLAUDE]
    for rel in comps:
        root = b.component_root(rel)
        if root is None:
            continue
        for sub in subs:
            if (root / sub).is_dir():
                roots.append((rel, root / sub))
    return roots


def _plan_agents(b: _Builder) -> None:
    for source, base in _claude_item_roots(b, (".claude/agents", "agents")):
        for item in sorted(base.iterdir()):
            if item.name in _SKIP_DIRS or item.name.startswith("."):
                continue
            if (item.is_file() and (item.suffix == ".md" or item.name in FRAMEWORK_AGENT_FILES)
                    or item.name == "_shared" and item.is_dir()):
                b.add(CLAUDE, "agent", item.name, f".claude/agents/{item.name}", item, source)


def _plan_commands(b: _Builder, as_skills: frozenset[str]) -> None:
    for source, base in _claude_item_roots(b, (".claude/commands",)):
        for item in sorted(base.glob("*.md")):
            if not item.is_file():
                continue
            if item.stem in as_skills:
                # User-level commands beat project commands (spike): emit overridable ones as skills.
                body = item.read_text(encoding="utf-8")
                content = body if body.startswith("---") else (
                    f"---\nname: {item.stem}\ndescription: Framework command /{item.stem}\n---\n\n{body}")
                gen = layout.copilot_home(b.home) / "generated" / "command-skills" / item.stem
                for runtime, rdir in ((CLAUDE, ".claude"), (CODEX, ".codex")):
                    b.add(runtime, "skill", item.stem, f"{rdir}/skills/{item.stem}", item,
                          f"{source} (command)", len(item.stem), generated=content, target=str(gen))
                continue
            b.add(CLAUDE, "command", item.name, f".claude/commands/{item.name}", item, source)


def _plan_rules(b: _Builder) -> None:
    for source, base in _claude_item_roots(b, (".claude/rules",)):
        for item in sorted(base.iterdir()):
            if item.is_file() and not item.name.startswith("."):
                b.add(CLAUDE, "rule", item.name, f".claude/rules/{item.name}", item, source)


def _collisions(plan: LinkPlan, project_roots: Iterable[Path]) -> None:
    linked = {(e.runtime, e.name): e.source for e in plan.entries if e.kind == "skill"}
    for project in project_roots:
        project = Path(project)
        for runtime, sub in ((CLAUDE, ".claude/skills"), (CODEX, ".agents/skills")):
            base = project / sub
            if not base.is_dir():
                continue
            for skill_dir in _iter_skill_dirs(base):
                name, _ = _skill_info(skill_dir)
                source = linked.get((runtime, name))
                if source:
                    plan.project_collisions.append(
                        {"project": str(project), "runtime": runtime, "name": name, "tier": source})


def _personal_overrides(plan: LinkPlan) -> list[dict[str, str]]:
    out = []
    for e in plan.entries:
        if e.source.split(" ")[0] not in PERSONAL_SOURCES:
            continue
        shadows = next((s["shadowed"] for s in plan.shadowed if s["winner"] == e.source
                        and (s["runtime"], s["kind"], s["name"]) == (e.runtime, e.kind, e.name)), "")
        out.append({"runtime": e.runtime, "kind": e.kind, "name": e.name, "link": e.link,
                    "source": e.source, "shadows": shadows})
    return out


def build_plan(release_dir: Path | str, home: Path | str | None = None, *,
               framework_repos: Iterable[Path | str] = (),
               tiers: tuple[str, ...] = TIER_ORDER,
               command_skill_names: Iterable[str] = (),
               project_roots: Iterable[Path | str] = ()) -> LinkPlan:
    """Derive the link plan for one release directory (read-only)."""
    release = Path(release_dir)
    b = _Builder(release, home, tuple(tiers), framework_repos)
    _plan_skills(b)
    _plan_agents(b)
    _plan_commands(b, frozenset(command_skill_names))
    _plan_rules(b)
    block = release / layout.CODEX_AGENTS_BLOCK_NAME
    if block.is_file():
        b.plan.agents_block = block.read_text(encoding="utf-8")
    else:
        b.plan.warnings.append(f"{layout.CODEX_AGENTS_BLOCK_NAME} absent in release; no AGENTS.md block")
    plan = b.plan
    for runtime in (CLAUDE, CODEX):
        skills = [e for e in plan.entries if e.runtime == runtime and e.kind == "skill"]
        plan.skill_counts[runtime] = len(skills)
        plan.description_chars[runtime] = sum(e.description_chars for e in skills)
    _collisions(plan, [Path(p) for p in project_roots])
    plan.personal_overrides = _personal_overrides(plan)
    return plan


def plan_to_json(plan: LinkPlan) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "release": plan.release_id,
        "entries": [e.__dict__ for e in plan.entries],
        "shadowed": plan.shadowed,
        "warnings": plan.warnings,
        "agents_block": plan.agents_block,
        "description_chars": plan.description_chars,
        "skill_counts": plan.skill_counts,
        "project_collisions": plan.project_collisions,
        "stale_copies": plan.stale_copies,
        "personal_overrides": plan.personal_overrides,
    }


def plan_from_json(data: dict[str, Any]) -> LinkPlan:
    if data.get("schema") != PLAN_SCHEMA:
        raise ValueError("links.json schema must be 1")
    return LinkPlan(
        release_id=data["release"],
        entries=[LinkEntry(**row) for row in data["entries"]],
        shadowed=data.get("shadowed", []),
        warnings=data.get("warnings", []),
        agents_block=data.get("agents_block"),
        description_chars=data.get("description_chars", {}),
        skill_counts=data.get("skill_counts", {}),
        project_collisions=data.get("project_collisions", []),
        stale_copies=data.get("stale_copies", []),
        personal_overrides=data.get("personal_overrides", []),
    )


def write_plan(plan: LinkPlan, release_dir: Path | str) -> Path:
    """Write links.json into a release directory being built (atomic)."""
    path = Path(release_dir) / layout.LINK_PLAN_NAME
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(plan_to_json(plan), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
