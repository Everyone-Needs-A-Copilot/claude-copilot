"""Codex per-project trust entry: atomic, locked, backed up, idempotent."""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator, Optional

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def default_codex_config() -> Path:
    from cc.core.project_init.homes import codex_home

    return codex_home() / "config.toml"


def _quote(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


def _has_entry(text: str, project: str) -> bool:
    if tomllib is not None:
        try:
            projects = tomllib.loads(text).get("projects", {})
            return isinstance(projects, dict) and project in projects
        except tomllib.TOMLDecodeError:
            pass
    return f'[projects."{_quote(project)}"]' in text


@contextlib.contextmanager
def _locked(config: Path) -> Iterator[None]:
    lock = config.with_name(config.name + ".lock")
    with open(lock, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_trust(project: Path | str, config: Optional[Path | str] = None) -> str:
    """Add `[projects."<abs>"] trust_level = "trusted"` once.

    Returns "added" or "present". Raises ValueError when an existing config is
    not valid TOML (it is never rewritten in that state).
    """
    cfg = Path(config) if config else default_codex_config()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    abs_project = str(Path(project).resolve())
    with _locked(cfg):
        try:
            text = cfg.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        if tomllib is not None and text:
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                raise ValueError(f"Codex config is not valid TOML: {exc}") from exc
        if _has_entry(text, abs_project):
            return "present"
        if cfg.exists():
            shutil.copy2(cfg, cfg.with_name(cfg.name + ".bak"))
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        if text.endswith("\n") and not text.endswith("\n\n"):
            sep = "\n"
        new = f'{text}{sep}[projects."{_quote(abs_project)}"]\ntrust_level = "trusted"\n'
        fd, tmp = tempfile.mkstemp(dir=cfg.parent, prefix=".config.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(new)
            if cfg.exists():
                os.chmod(tmp, cfg.stat().st_mode & 0o7777)
            os.replace(tmp, cfg)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return "added"
