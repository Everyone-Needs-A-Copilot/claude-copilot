"""What counts as framework-owned: the per-project lock plus known framework sources."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from cc.core.project_migrate import instructions
from cc.core.project_migrate.util import sha256_file

LOCK_FILE = "copilot.lock.json"
CODEX_LOCK_FILE = ".codex-copilot.json"


def default_claude_root() -> Path:
    # .../tools/cc/src/cc/core/project_migrate/known.py -> repository / snapshot root
    return Path(__file__).resolve().parents[6]


def default_codex_root() -> Optional[Path]:
    env = os.environ.get("CC_CODEX_COPILOT_ROOT")
    for cand in (env, str(Path.home() / ".copilot" / "current" / "codex-copilot")):
        if cand and Path(cand).is_dir():
            return Path(cand)
    return None


@dataclass
class LockRecord:
    """Parsed copilot.lock.json: path -> (checksum, ownership, component)."""

    files: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    symlinks: dict[str, str] = field(default_factory=dict)       # managed internal-symlink paths
    hook_commands: set[str] = field(default_factory=set)         # registered hook command strings
    settings_created: bool = False                               # settings.json absent before framework
    codex_hooks_created: bool = False                            # .codex/hooks.json absent before framework
    valid: bool = True
    error: str = ""


def read_lock(project: Path) -> Optional[LockRecord]:
    path = project / LOCK_FILE
    if not path.exists() and not path.is_symlink():
        return None
    rec = LockRecord()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        components = data["components"]
        if not isinstance(components, list):
            raise ValueError("components is not a list")
        for comp in components:
            name = str(comp.get("component", ""))
            for f in comp.get("files", []):
                rec.files[str(f["path"])] = (str(f["checksum"]), str(f.get("ownership", "framework")), name)
            for out in comp.get("managed_outputs", []):
                if out.get("kind") == "internal-symlink":
                    rec.symlinks[str(out["path"])] = name
        for mut in data.get("mutations", []) or []:
            if mut.get("kind") == "settings-hook":
                for entry in mut.get("entries", []):
                    if entry.get("command"):
                        rec.hook_commands.add(str(entry["command"]))
                if mut.get("target_existed_before") is False and mut.get("target") == ".claude/settings.json":
                    rec.settings_created = True
                if mut.get("target_existed_before") is False and mut.get("target") == ".codex/hooks.json":
                    rec.codex_hooks_created = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        rec = LockRecord(valid=False, error=f"{exc.__class__.__name__}: {exc}")
    return rec


@dataclass
class Known:
    """Framework knowledge not tied to one project's lock."""

    file_hashes: dict[str, set[str]]                 # project-relative path -> sha256 set
    tree_hashes: dict[str, set[str]]                 # dir prefix -> sha256 set (any file name)
    sections: dict[str, set[str]]                    # instruction-file section key -> texts
    codex_resolved: bool = True                      # a codex-copilot root was found
    codex_hook_commands: set[str] = field(default_factory=set)  # commands in the framework's Codex hooks.json


def build_known(
    claude_root: Optional[Path] = None,
    codex_root: Optional[Path] = None,
    extra_sections: Optional[dict[str, set[str]]] = None,
    extra_hashes: Optional[dict[str, set[str]]] = None,
) -> Known:
    claude = claude_root or default_claude_root()
    codex = codex_root if codex_root is not None else default_codex_root()
    file_hashes: dict[str, set[str]] = {}
    tree_hashes: dict[str, set[str]] = {}

    def add_file(rel: str, src: Optional[Path]) -> None:
        if src is not None:
            digest = sha256_file(src)
            if digest:
                file_hashes.setdefault(rel, set()).add(digest)

    add_file(".claude/fitness-check.sh", claude / ".claude" / "fitness-check.sh")
    add_file(".claude/hooks/copilot-hook.sh", claude / ".claude" / "hooks" / "copilot-hook.sh")
    if codex is not None:
        add_file("scripts/copilot-gate.sh", codex / "scripts" / "copilot-gate.sh")
    for prefix, root in ((".claude/hooks/", claude / ".claude" / "hooks"),
                         (".codex/agents/", (codex / ".codex" / "agents") if codex else None)):
        if root is not None and root.is_dir():
            for f in root.iterdir():
                if f.is_file():
                    d = sha256_file(f)
                    if d:
                        tree_hashes.setdefault(prefix, set()).add(d)
    for rel, hashes in (extra_hashes or {}).items():
        file_hashes.setdefault(rel, set()).update(hashes)

    section_sources = [claude / "templates" / "CLAUDE.template.md"]
    if codex is not None:
        section_sources.append(codex / "templates" / "AGENTS.project.template.md")
    sections = instructions.known_sections_from_files(section_sources)
    try:  # the historical managed blocks are marker-delimited; the current text is also known
        from cc.core.ecosystem import reconciliation_recipes as rr

        for block in (rr._CLAUDE_BLOCK, rr._CODEX_BLOCK):
            for k, v in instructions.known_sections_from_text(block).items():
                sections.setdefault(k, set()).update(v)
    except Exception:  # pragma: no cover - recipes are optional knowledge
        pass
    for k, v in (extra_sections or {}).items():
        sections.setdefault(k, set()).update(v)
    return Known(file_hashes, tree_hashes, sections, codex_resolved=codex is not None,
                 codex_hook_commands=_codex_hook_commands(codex))


def _codex_hook_commands(codex: Optional[Path]) -> set[str]:
    """Hook commands the framework's own Codex hooks.json registers (its identity record)."""
    if codex is None:
        return set()
    try:
        data = json.loads((codex / "plugins" / "codex-copilot" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        return {h["command"] for groups in data["hooks"].values() for g in groups
                for h in g.get("hooks", []) if isinstance(h.get("command"), str)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()
