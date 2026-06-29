"""cc env — emit shell-eval-able exports for the effective config.

Usage:
    eval "$(cc env)"          # hydrate CC_* exports into current shell
    cc env --json             # JSON for programmatic use
    cc env --include-secrets  # also emit values from secrets.env
"""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console

from cc.core.config import (
    get_resolved_config,
    load_machine_secrets,
    load_project_secrets,
    resolve_key,
)

err_console = Console(stderr=True)


def _key_to_env_name(key: str) -> str:
    """Convert dotted config key to CC_UPPER_UNDERSCORE env var name."""
    return "CC_" + key.replace(".", "_").upper()


def run_env(
    *,
    include_secrets: bool = False,
    output_json: bool = False,
) -> dict[str, str]:
    """
    Build the exports dict from the effective config.

    Separated from the CLI handler so it can be unit-tested directly.
    Secrets are excluded unless include_secrets=True.
    """
    cfg = get_resolved_config()
    exports: dict[str, str] = {}

    for key, value in cfg.items():
        if value is None:
            continue
        env_name = _key_to_env_name(key)
        exports[env_name] = str(value)

    if include_secrets:
        machine_secrets = load_machine_secrets()
        project_secrets = load_project_secrets()
        for k, v in {**machine_secrets, **project_secrets}.items():
            exports[k] = v

    # Emit short-form aliases for the knowledge repo path variables.
    # Agents reference CC_KNOWLEDGE_REPO and CC_SHARED_DOCS (not the nested
    # CC_PATHS_* form), so produce both names when the source key is set.
    _PATH_ALIASES: dict[str, str] = {
        "CC_KNOWLEDGE_REPO": "CC_PATHS_KNOWLEDGE_REPO",
        "CC_SHARED_DOCS": "CC_PATHS_SHARED_DOCS",
    }
    for alias, source in _PATH_ALIASES.items():
        if source in exports and alias not in exports:
            exports[alias] = exports[source]

    return exports
