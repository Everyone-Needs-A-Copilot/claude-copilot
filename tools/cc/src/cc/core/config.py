"""Two-layer config system: load, merge, and resolve machine + project config.

Resolution precedence (highest wins):
  1. CC_<UPPER_DOTTED> env var
  2. Project config (with sentinel resolution against machine layer)
  3. Machine config
  4. Built-in defaults

Config files use a flat JSON schema with nested objects.
Dotted-key notation is used throughout this module (e.g. "paths.shared_docs").
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from cc.core.config_paths import (
    machine_config_path,
    machine_secrets_path,
    project_config_path,
    project_secrets_path,
    repo_root,
)
from cc.core.sentinels import is_sentinel, resolve_sentinel

# ---------------------------------------------------------------------------
# Built-in defaults (lowest precedence)
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "paths.memory": "~/.claude/memory",
    "paths.shared_docs": None,
    "paths.knowledge_repo": None,
    "paths.global_skills_dir": "~/.claude/skills",
    "paths.embedding_cache": "~/.claude/cache/models",
    "memory.embedding_model": "none",
    "memory.default_threshold": 0.7,
    "skills.cache_ttl_hours": 24,
    "telemetry.enabled": False,
}


# ---------------------------------------------------------------------------
# Flat dict helpers (dotted-key access)
# ---------------------------------------------------------------------------

def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict to dotted-key notation."""
    result: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(_flatten(v, full_key))
            else:
                result[full_key] = v
    return result


def _dotted_get(obj: dict[str, Any], key: str) -> Any:
    """Get a value from a nested dict using dotted-key notation."""
    parts = key.split(".")
    current: Any = obj
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _dotted_set(obj: dict[str, Any], key: str, value: Any) -> None:
    """Set a value in a nested dict using dotted-key notation (mutates in place)."""
    parts = key.split(".")
    current = obj
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


# ---------------------------------------------------------------------------
# Config file I/O
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    """Read JSON from path; return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_secrets(path: Path | None) -> dict[str, str]:
    """Load a dotenv file as a flat key=value dict (no shell expansion)."""
    if path is None or not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def load_machine_config() -> dict[str, Any]:
    """Load machine config from ~/.claude/cc/config.json (returns defaults if missing)."""
    return _read_json(machine_config_path())


def load_project_config() -> dict[str, Any]:
    """Load project config from <git root>/.claude/cc/config.json (empty if missing/not in repo)."""
    path = project_config_path()
    if path is None:
        return {}
    return _read_json(path)


def load_machine_secrets() -> dict[str, str]:
    """Load machine secrets from ~/.claude/cc/secrets.env."""
    return _load_secrets(machine_secrets_path())


def load_project_secrets() -> dict[str, str]:
    """Load project secrets from <git root>/.claude/cc/secrets.env."""
    return _load_secrets(project_secrets_path())


# ---------------------------------------------------------------------------
# Merge + resolution
# ---------------------------------------------------------------------------

def _expand_path(value: Any) -> Any:
    """Expand ~ in path-like string values."""
    if isinstance(value, str) and "~" in value:
        return str(Path(value).expanduser())
    return value


def get_resolved_config(
    *,
    _machine: dict[str, Any] | None = None,
    _project: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return the fully resolved config dict (dotted-key notation).

    Merge order (highest wins):
      1. CC_* env vars
      2. Project config (sentinels resolved against machine config)
      3. Machine config
      4. Built-in defaults

    Args:
        _machine: Override machine config (used in tests).
        _project: Override project config (used in tests).
    """
    machine = _machine if _machine is not None else load_machine_config()
    project = _project if _project is not None else load_project_config()

    machine_flat = _flatten(machine)
    project_flat = _flatten(project)

    # Start with defaults
    resolved: dict[str, Any] = dict(DEFAULTS)

    # Layer 3: machine config
    for k, v in machine_flat.items():
        if k not in ("$schema", "version"):
            resolved[k] = v

    # Layer 2: project config (with sentinel resolution)
    for k, v in project_flat.items():
        if k in ("$schema", "version"):
            continue
        if is_sentinel(v):
            resolved_val = resolve_sentinel(v, same_key=k, machine_config=machine_flat)
            resolved[k] = resolved_val
        else:
            resolved[k] = v

    # Layer 1: CC_* env vars (dotted key → uppercase with _ separators)
    for key in list(resolved.keys()):
        env_name = "CC_" + key.replace(".", "_").upper()
        if env_name in os.environ:
            resolved[key] = os.environ[env_name]

    # Expand ~ in all string values
    resolved = {k: _expand_path(v) for k, v in resolved.items()}

    return resolved


def resolve_key(
    key: str,
    *,
    scope: Optional[str] = None,
    _machine: dict[str, Any] | None = None,
    _project: dict[str, Any] | None = None,
) -> Any:
    """
    Resolve a single dotted config key.

    Args:
        key:    Dotted key (e.g. "paths.shared_docs").
        scope:  "machine" | "project" | None (=effective, all layers).
    """
    machine = _machine if _machine is not None else load_machine_config()
    project = _project if _project is not None else load_project_config()

    machine_flat = _flatten(machine)
    project_flat = _flatten(project)

    if scope == "machine":
        return _expand_path(machine_flat.get(key, DEFAULTS.get(key)))

    if scope == "project":
        val = project_flat.get(key)
        if val is None:
            return None
        if is_sentinel(val):
            return resolve_sentinel(val, same_key=key, machine_config=machine_flat)
        return _expand_path(val)

    # Effective (all layers)
    # Env var first
    env_name = "CC_" + key.replace(".", "_").upper()
    if env_name in os.environ:
        return _expand_path(os.environ[env_name])

    # Project
    if key in project_flat:
        val = project_flat[key]
        if is_sentinel(val):
            result = resolve_sentinel(val, same_key=key, machine_config=machine_flat)
            return _expand_path(result)
        return _expand_path(val)

    # Machine
    if key in machine_flat:
        return _expand_path(machine_flat[key])

    # Default
    return _expand_path(DEFAULTS.get(key))


def write_config(key: str, value: Any, *, project: bool = False) -> Path:
    """
    Write a key to the machine or project config file.

    Returns the path written to.
    """
    if project:
        cfg_path = project_config_path()
        if cfg_path is None:
            raise ValueError("Not inside a git repository; cannot write project config.")
    else:
        cfg_path = machine_config_path()

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(cfg_path)
    _dotted_set(existing, key, value)

    cfg_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return cfg_path


def unset_config(key: str, *, project: bool = False) -> bool:
    """
    Remove a key from the machine or project config file.

    Returns True if key was present and removed, False if not found.
    """
    if project:
        cfg_path = project_config_path()
        if cfg_path is None:
            raise ValueError("Not inside a git repository; cannot modify project config.")
    else:
        cfg_path = machine_config_path()

    if not cfg_path.exists():
        return False

    existing = _read_json(cfg_path)
    parts = key.split(".")
    current: Any = existing

    # Navigate to parent
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]

    if not isinstance(current, dict) or parts[-1] not in current:
        return False

    del current[parts[-1]]
    cfg_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return True


def where_key(key: str) -> dict[str, Any]:
    """
    Return the winning layer for a key with reason.

    Returns dict with keys: value, source, reason.
    """
    machine = load_machine_config()
    project = load_project_config()
    machine_flat = _flatten(machine)
    project_flat = _flatten(project)

    env_name = "CC_" + key.replace(".", "_").upper()
    if env_name in os.environ:
        return {
            "value": _expand_path(os.environ[env_name]),
            "source": "env",
            "reason": f"env var {env_name}",
        }

    if key in project_flat:
        raw_val = project_flat[key]
        if is_sentinel(raw_val):
            resolved = resolve_sentinel(raw_val, same_key=key, machine_config=machine_flat)
            return {
                "value": _expand_path(resolved),
                "source": "project",
                "reason": f"project config sentinel {raw_val!r} → machine",
            }
        return {
            "value": _expand_path(raw_val),
            "source": "project",
            "reason": "project config literal",
        }

    if key in machine_flat:
        return {
            "value": _expand_path(machine_flat[key]),
            "source": "machine",
            "reason": "machine config",
        }

    default_val = DEFAULTS.get(key)
    return {
        "value": _expand_path(default_val),
        "source": "default",
        "reason": "built-in default",
    }
