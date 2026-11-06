"""Read-only migration planner: decides delete / keep / hold for one project."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from cc.core.ecosystem.project_ownership import declares_project_owner
from cc.core.project_init.marker import MARKER_FILENAME, read_marker
from cc.core.project_migrate import instructions
from cc.core.project_migrate.known import (
    CODEX_LOCK_FILE, LOCK_FILE, Known, LockRecord, build_known, read_lock,
)
from cc.core.project_migrate.model import (
    DELETE, EDIT_JSON, EDIT_TEXT, UNLINK, WRITE, Item, MigrateError, MigrationPlan,
)
from cc.core.project_migrate.settings_hooks import strip_framework_hooks
from cc.core.project_migrate.util import (
    git_dirty_paths, is_git_repo, overlaps, sha256_bytes, sha256_file,
)

_PACK_LINK = re.compile(r"(?:^|/)codex-copilot/packs/([^/]+)/skills/[^/]+$")
_BRIDGE_TARGETS = {
    ".claude/skills/codex-copilot": "../../plugins/codex-copilot/skills",
    ".claude/skills/codex-copilot-internal": "../../plugins/codex-copilot-internal/skills",
}
_FRAMEWORK_PLUGIN_PATHS = {
    "./plugins/codex-copilot", "./plugins/codex-copilot-internal", "./plugins/codex-copilot-accounting",
}
_FRAMEWORK_DIRS = (".claude/agents", ".claude/commands", "plugins/codex-copilot", "plugins/codex-copilot-internal")
_STATE_DIRS = (
    (".claude/memory", "project memory"),
    (".copilot", "tc state and work products"),
    (".claude/skills", "project skills (framework bridges removed separately)"),
    (".claude/rules", "project rules"),
    (".claude/cc", "project cc config"),
)
_STATE_FILES = (
    ".claude/cc/config.json", ".claude/copilot-required", ".claude/copilot-hooks-disabled",
    ".claude/settings.local.json", "SOUL.md",
)
_WALK_SKIP = {".git", ".venv", "node_modules", ".pytest_cache", ".ruff_cache", "__pycache__", ".obsidian"}
SETTINGS = ".claude/settings.json"
EMPTY_MCP = {"mcpServers": {}}


def _safe_rel(root: Path, rel: str) -> Optional[Path]:
    """Absolute path for a project-relative path, or None if it escapes the project."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    p = root / rel
    parent = Path(os.path.realpath(p.parent))
    try:
        parent.relative_to(os.path.realpath(root))
    except ValueError:
        return None
    return p


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


class _Builder:
    def __init__(self, root: Path, known: Known):
        self.root = root
        self.known = known
        self.plan = MigrationPlan(project=str(root), git=is_git_repo(root))
        self.decided: set[str] = set()
        self.lock: Optional[LockRecord] = None
        self.active_packs: list[dict[str, Any]] = []

    def act(self, kind: str, rel: str, reason: str, **detail: Any) -> None:
        self.decided.add(rel)
        self.plan.actions.append(Item(rel, reason, kind, detail))

    def keep(self, rel: str, reason: str) -> None:
        self.decided.add(rel)
        self.plan.keeps.append(Item(rel, reason, "keep"))

    def hold(self, rel: str, reason: str) -> None:
        self.decided.add(rel)
        self.plan.holds.append(Item(rel, reason, "hold"))

    # -- locks ------------------------------------------------------------
    def lock_files(self) -> None:
        lock = self.lock
        if lock is None or not lock.valid:
            if lock is not None:
                self.plan.notes.append(f"{LOCK_FILE} is unreadable ({lock.error}); no lock-listed file is removed")
            return
        for rel in sorted(lock.files):
            checksum, ownership, component = lock.files[rel]
            path = _safe_rel(self.root, rel)
            if path is None:
                self.hold(rel, "lock path escapes the project")
                continue
            if not (path.exists() or path.is_symlink()):
                continue
            if path.is_symlink() or not path.is_file():
                self.hold(rel, "lock-listed path is not a regular file")
            elif ownership != "framework":
                self.keep(rel, f"lock marks ownership={ownership}")
            elif declares_project_owner(path):
                self.keep(rel, "owner: project in frontmatter")
            elif sha256_file(path) == checksum:
                self.act(DELETE, rel, f"framework copy, bytes match {component} lock",
                         sha=checksum)
            else:
                self.hold(rel, f"lock-listed but modified since install ({component})")

    def bridges(self) -> None:
        for rel, target in _BRIDGE_TARGETS.items():
            path = self.root / rel
            if path.is_symlink():
                if os.readlink(path) == target:
                    self.act(UNLINK, rel, "framework plugin skill bridge", target=target)
                else:
                    self.keep(rel, "symlink target is not the framework bridge")

    def known_files(self) -> None:
        for rel, hashes in sorted(self.known.file_hashes.items()):
            if rel in self.decided:
                continue
            path = self.root / rel
            if not path.is_file() or path.is_symlink():
                continue
            digest = sha256_file(path)
            if digest in hashes:
                self.act(DELETE, rel, "bytes identical to the framework source", sha=digest)
            else:
                self.keep(rel, "differs from the framework source: project-owned")
        for prefix in (".claude/hooks/", ".codex/agents/"):
            hashes = self.known.tree_hashes.get(prefix, set())
            d = self.root / prefix
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                rel = prefix + f.name
                if rel in self.decided or not f.is_file() or f.is_symlink() or f.name == ".DS_Store":
                    continue
                if prefix == ".codex/agents/" and f.suffix != ".toml":
                    continue
                digest = sha256_file(f)
                if digest in hashes:
                    self.act(DELETE, rel, "legacy framework file, bytes match a known framework file",
                             sha=digest)
                else:
                    self.keep(rel, "no known framework hash: kept")

    # -- small framework files ---------------------------------------------
    def empty_mcp(self) -> None:
        path = self.root / ".mcp.json"
        if path.is_file() and _read_json(path) == EMPTY_MCP:
            self.act(DELETE, ".mcp.json", "empty mcpServers declaration", sha=sha256_file(path))

    def marketplace(self) -> None:
        rel = ".agents/plugins/marketplace.json"
        path = self.root / rel
        if not path.is_file():
            return
        data = _read_json(path)
        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, list):
            self.hold(rel, "unreadable marketplace")
            return
        paths = [((p.get("source") or {}).get("path") if isinstance(p, dict) else None) for p in plugins]
        framework = [p for p in paths if p in _FRAMEWORK_PLUGIN_PATHS]
        if framework and len(framework) == len(paths) and data.get("name") == "codex-copilot-project":
            self.act(DELETE, rel, "framework-only repo marketplace", sha=sha256_file(path))
        elif framework:
            self.hold(rel, "marketplace also lists project plugins: edit by hand")
        else:
            self.keep(rel, "marketplace lists no framework plugin")

    def settings(self) -> None:
        path = self.root / SETTINGS
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8")
        new, removed, ambiguous, empty = strip_framework_hooks(text, self.lock)
        for cmd in ambiguous:
            self.hold(SETTINGS, f"hook command resembles the framework shim but is untagged: {cmd}")
        if new is None:
            self.keep(SETTINGS, "no framework hook registration" if not ambiguous else "ambiguous hooks held")
            return
        delete = empty and bool(self.lock and self.lock.settings_created)
        self.plan.staged[SETTINGS] = new
        self.act(EDIT_JSON, SETTINGS, f"remove {removed} framework hook registration(s); other keys kept",
                 removed=removed, delete_file=delete, sha=sha256_bytes(text.encode()))

    def instruction_files(self) -> None:
        for name in ("CLAUDE.md", "AGENTS.md"):
            path = self.root / name
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                self.hold(name, "not valid UTF-8")
                continue
            res = instructions.thin_text(text, self.known.sections)
            for key, why in res.held:
                self.hold(f"{name}: {key}", why)
            if res.changed:
                self.plan.staged[name] = res.new_text
                self.act(EDIT_TEXT, name, f"remove {len(res.removed)} framework section(s)",
                         removed=res.removed, sha=sha256_bytes(text.encode()))
            else:
                self.keep(name, "no framework-owned section found")

    def own_locks(self) -> None:
        for rel in (LOCK_FILE, CODEX_LOCK_FILE):
            path = self.root / rel
            if path.is_file():
                self.act(DELETE, rel, "checksum lock retired", sha=sha256_file(path))

    # -- pack links ----------------------------------------------------------
    def pack_links(self) -> None:
        root = self.root
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _WALK_SKIP]
            for name in list(dirnames) + filenames:
                full = Path(dirpath) / name
                if not full.is_symlink():
                    continue
                rel = full.relative_to(root).as_posix()
                if rel in self.decided:
                    continue
                target = os.readlink(full)
                if full.exists():
                    continue
                m = _PACK_LINK.search(target)
                if m and full.parent.name == "skills":
                    base = full.parent.parent.relative_to(root).as_posix()
                    pack = {"name": m.group(1), "activatedBy": "./" + base if base != "." else "."}
                    self.act(UNLINK, rel, f"broken pack link (pack {pack['name']}) -> activePacks",
                             target=target, pack=pack)
                    if pack not in self.active_packs:
                        self.active_packs.append(pack)
                else:
                    self.hold(rel, f"broken symlink to {target}: not a pack link")

    def collect_active_packs(self) -> None:
        codex_lock = _read_json(self.root / CODEX_LOCK_FILE)
        sources = [
            read_marker(self.root).get("activePacks"),
            codex_lock.get("activePacks") if isinstance(codex_lock, dict) else None,
            self.active_packs,
        ]
        merged: list[dict[str, Any]] = []
        for packs in sources:
            for p in packs if isinstance(packs, list) else []:
                if not (isinstance(p, dict) and isinstance(p.get("name"), str)):
                    continue
                entry = {k: v for k, v in p.items() if k != "source"}  # source was a copy-era path
                key = (entry["name"], entry.get("activatedBy"))
                if all((m["name"], m.get("activatedBy")) != key for m in merged):
                    merged.append(entry)
        self.active_packs = merged

    # -- keeps ---------------------------------------------------------------
    def undecided_framework_files(self) -> None:
        for base in _FRAMEWORK_DIRS:
            d = self.root / base
            if not d.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(d):
                dirnames[:] = sorted(x for x in dirnames if x not in _WALK_SKIP)
                for fn in sorted(filenames):
                    if fn == ".DS_Store":
                        continue
                    rel = (Path(dirpath) / fn).relative_to(self.root).as_posix()
                    if rel in self.decided:
                        continue
                    full = self.root / rel
                    if declares_project_owner(full):
                        self.keep(rel, "owner: project in frontmatter")
                    else:
                        self.keep(rel, "not in any lock: no evidence it is framework-owned")

    def project_state(self) -> None:
        for rel, label in _STATE_DIRS:
            d = self.root / rel
            if d.is_dir():
                self.keep(rel + "/", label)
        for rel in _STATE_FILES:
            if (self.root / rel).exists() and rel not in self.decided:
                self.keep(rel, "project state")
        marker = self.root / MARKER_FILENAME
        if marker.exists():
            self.keep(MARKER_FILENAME, "project marker (rewritten by project init, other keys kept)")
        for rel in ("docs",):
            if (self.root / rel).is_dir():
                self.keep(rel + "/", "project docs (never touched)")
        plugins = self.root / "plugins"
        if plugins.is_dir():
            for p in sorted(plugins.iterdir()):
                if p.is_dir() and p.name not in ("codex-copilot", "codex-copilot-internal"):
                    self.keep(f"plugins/{p.name}/", "project-owned plugin")

    def init_writes(self) -> None:
        self.act(WRITE, MARKER_FILENAME, "write runtimes marker via project init",
                 active_packs=self.active_packs)
        for name in ("CLAUDE.md", "AGENTS.md"):
            self.act(WRITE, name, "append the thin framework section if absent")
        self.act(WRITE, "~/.codex/config.toml", "add the Codex per-project trust entry (machine state)")


def plan_migration(
    project: Path | str,
    *,
    known: Optional[Known] = None,
    claude_root: Optional[Path] = None,
    codex_root: Optional[Path] = None,
) -> MigrationPlan:
    root = Path(project).expanduser()
    if not root.exists():
        raise MigrateError("not-found", f"Project folder does not exist: {root}")
    if not root.is_dir():
        raise MigrateError("not-a-directory", f"Not a folder: {root}")
    root = root.resolve()
    b = _Builder(root, known or build_known(claude_root, codex_root))
    b.lock = read_lock(root)
    b.lock_files()
    b.bridges()
    b.known_files()
    b.empty_mcp()
    b.marketplace()
    b.settings()
    b.instruction_files()
    b.pack_links()
    b.collect_active_packs()
    b.own_locks()
    b.undecided_framework_files()
    b.project_state()
    b.init_writes()

    plan = b.plan
    if plan.git:
        dirty = git_dirty_paths(root)
        affected = [a.path for a in plan.actions if not a.path.startswith("~")]
        affected += [".gitignore"] if b.active_packs else []
        plan.dirty = sorted({d for d in dirty if any(overlaps(d, a) for a in affected)})
        for d in plan.dirty:
            plan.holds.append(Item(d, "uncommitted changes on a path this plan would change", "hold"))
    else:
        plan.notes.append("not a Git repository: recovery is the rollback manifest only")
    return plan
