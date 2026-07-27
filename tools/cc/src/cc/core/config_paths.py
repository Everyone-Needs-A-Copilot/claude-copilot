"""Config path resolution: machine config, project config, secrets files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Overrides the machine-config root directory (normally `~/.claude/cc`).
# Honored by `machine_config_path()`/`machine_secrets_path()` below -- the
# SAME env-var-seam idiom `core/config.py`'s own `CC_<KEY>` cascade already
# uses everywhere else, just applied one level lower than a config key.
#
# Why an env var and not this codebase's usual `_root: Path | str | None`
# keyword-injection convention (core/authstore.py, core/ecosystem/mirror.py):
# `write_config()`/`machine_config_path()` are reached through a long,
# fan-out call chain -- a dozen functions in core/config.py, plus
# commands/config.py, commands/onboard.py, commands/workspaces.py,
# commands/mcp_serve.py, commands/doctor.py -- and every one of those call
# sites (present and future) would need a `_root` kwarg threaded through it
# for the injection to actually reach this module. A single process-wide
# env var closes the seam at its one true source instead, with nothing to
# thread and nothing for a new call site to forget.
#
# This is not a hypothetical hardening: a test
# (`test_manifest_repair_is_not_a_checkbox_and_applies_without_any_consent`,
# tests/test_onboard_contract.py) reached `write_config()` through
# `commands/onboard.py` without patching anything, and wrote a pytest
# tmpdir path into a developer's REAL `~/.claude/cc/config.json`.
# tests/conftest.py's `_isolate_machine_config` autouse fixture sets this
# env var to a fresh tmp directory for EVERY test in the suite, so no
# individual test has to remember to opt in.
_MACHINE_ROOT_ENV = "CC_MACHINE_ROOT"


def _machine_root() -> Path:
    """Return the machine-config root directory, honoring `CC_MACHINE_ROOT`."""
    override = os.environ.get(_MACHINE_ROOT_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "cc"


def machine_config_path() -> Path:
    """Return the machine-level config path (~/.claude/cc/config.json by
    default; see `_machine_root()` for the `CC_MACHINE_ROOT` override)."""
    return _machine_root() / "config.json"


def machine_secrets_path() -> Path:
    """Return the machine-level secrets dotenv (~/.claude/cc/secrets.env by
    default; see `_machine_root()` for the `CC_MACHINE_ROOT` override)."""
    return _machine_root() / "secrets.env"


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
