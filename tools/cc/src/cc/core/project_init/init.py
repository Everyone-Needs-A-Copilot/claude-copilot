"""`cc project init`: the single project-state writer (ADR-001 decision 7).

One process, no git/network subprocess, no census, no projects.roots gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from cc.core.project_init.codex_trust import ensure_trust
from cc.core.project_init.gitignore import ensure_ignored
from cc.core.project_init.marker import MARKER_FILENAME, MarkerCorruptError, read_marker, write_marker
from cc.core.project_init.packs import link_packs
from cc.core.project_init.registry import register_project
from cc.core.project_init.sections import ensure_section

SCHEMA_VERSION = "1.0"


class InitError(Exception):
    """A clean, user-actionable init failure (rendered as JSON, never a traceback)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def init_project(
    project: Path | str,
    *,
    codex_config: Optional[Path | str] = None,
    packs_root: Optional[Path | str] = None,
    registry: Optional[Path | str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Initialise `project` for both runtimes. Idempotent."""
    root = Path(project).expanduser()
    if not root.exists():
        raise InitError("not-found", f"Project folder does not exist: {root}")
    if not root.is_dir():
        raise InitError("not-a-directory", f"Not a folder: {root}")
    root = root.resolve()
    changed: list[str] = []
    try:
        if write_marker(root, force=force):
            changed.append(MARKER_FILENAME)
        for name in ("CLAUDE.md", "AGENTS.md"):
            if ensure_section(root / name, root.name):
                changed.append(name)
        links, warnings = link_packs(
            root,
            read_marker(root).get("activePacks") or [],
            Path(packs_root) if packs_root else None,
        )
        if ensure_ignored(root, links):
            changed.append(".gitignore")
        trust = ensure_trust(root, codex_config)
        if trust == "added":
            changed.append("codex-trust")
        if register_project(root, Path(registry) if registry else None):
            changed.append("registry")
    except MarkerCorruptError as exc:
        raise InitError("marker-corrupt", str(exc)) from exc
    except ValueError as exc:
        raise InitError("codex-config-invalid", str(exc)) from exc
    except OSError as exc:
        raise InitError("io-error", f"{exc.__class__.__name__}: {exc}") from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "result": "changed" if changed else "unchanged",
        "project": str(root),
        "runtimes": ["claude", "codex"],
        "changed": changed,
        "pack_links": links,
        "warnings": warnings,
    }
