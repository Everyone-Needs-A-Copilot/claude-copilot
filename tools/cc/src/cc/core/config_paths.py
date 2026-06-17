"""Config path resolution: machine config, project config, secrets files."""

from __future__ import annotations

import subprocess
from pathlib import Path


def machine_config_path() -> Path:
    """Return the machine-level config path (~/.claude/cc/config.json)."""
    return Path.home() / ".claude" / "cc" / "config.json"


def machine_secrets_path() -> Path:
    """Return the machine-level secrets dotenv (~/.claude/cc/secrets.env)."""
    return Path.home() / ".claude" / "cc" / "secrets.env"


def repo_root() -> Path | None:
    """Return the git repository root, or None if not inside a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def project_config_path() -> Path | None:
    """Return the project-level config path (<git root>/.claude/cc/config.json), or None."""
    root = repo_root()
    if root is None:
        return None
    return root / ".claude" / "cc" / "config.json"


def project_secrets_path() -> Path | None:
    """Return the project-level secrets dotenv, or None if not in a repo."""
    root = repo_root()
    if root is None:
        return None
    return root / ".claude" / "cc" / "secrets.env"
