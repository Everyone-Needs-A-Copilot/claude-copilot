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
    # docs subsystem
    "docs.cache_dir": "~/.claude/cache/docs",
    "docs.cache_ttl_hours": 168,
    "docs.source_order": "local,fetch",
    # Reserved for future Context7 integration; intentionally unset at launch.
    "docs.context7_endpoint": None,
    # Ecosystem layer resolution (WS-A `resolve` slice). Plain scalars that
    # ride the existing env›project›machine cascade with zero new
    # resolution logic -- NOT list-valued, and NOT config scopes (the
    # personal/department/org/foundation stack is data the resolver reads,
    # not a `cc` config scope). See
    # copilot-control-tower/docs/reference/four-tier-topology.md §7.
    "layers.manifest": None,  # path to copilot.layers.yml
    "layers.department": None,  # which department-role layer(s) apply
    # `cc freshness` (WS-A freshness slice): the tier source repo + published
    # lock-pointer ref to poll. See core/ecosystem/mirror.py's module
    # docstring for the ref-target convention.
    "layers.lock_source": None,  # tier source repo URL (git ls-remote target)
    "layers.lock_ref": "refs/copilot/lock",  # published lock-pointer ref name
    # Read-only mirror root (inheritance-and-publish.md §2.2). NEVER
    # ~/.claude (materialized tree) or an authoring vault -- see
    # core/ecosystem/mirror.py's module docstring.
    "paths.mirrors_root": "~/.copilot/mirrors",
    # The materialized tree `cc update` reconciles into -- what the host
    # actually scans (inheritance-and-publish.md §2.2's tree table). NEVER
    # a mirror and NEVER an authoring vault. See core/ecosystem/materialize.py.
    "paths.materialize_root": "~/.claude",
    # Product-native materialization roots. Claude keeps its established
    # host-scanned tree. Codex content is an app-owned local marketplace;
    # `cc onboard` registers and installs its plugins through the Codex CLI.
    "paths.claude_materialize_root": "~/.claude",
    "paths.codex_materialize_root": "~/.copilot/materialized/codex",
    # WS-A foundation slice (Stream-F). GitHub App client id for the
    # device-flow sign-in seam (core/authstore.py / core/keychain.py) --
    # read from the org's inherited `ecosystem.yml`
    # (core/ecosystem/ecosystem_config.py), NOT a secret itself (a client
    # id is public by design), so it's fine to ride the plain config
    # cascade rather than the keychain.
    "github_app.client_id": None,
    # Explicit override for the inherited ecosystem.yml location; when
    # unset, ecosystem_config.py derives <paths.materialize_root>/ecosystem.yml.
    "paths.ecosystem_config": None,
    # Source checkouts used by the explicit project activation adapters.
    # These are machine paths only; they are never written into a portable
    # project declaration or returned to Control Tower.
    "paths.claude_copilot_root": "~/.claude/copilot",
    "paths.codex_copilot_root": "~/.local/share/enac/codex-copilot",
    # Project roots this machine scans (list-valued -- see LIST_VALUED_KEYS
    # below). Unset by default: no scanning happens until an admin/user
    # configures at least one root.
    "projects.roots": None,
    # Optional explicit-project registry (Component Sync Stream-E,
    # core/ecosystem/projects.py's discover_projects()) -- a JSON file
    # listing project paths that root-scanning alone might miss (e.g. a
    # project outside every configured `projects.roots` tree). Supplements,
    # never replaces, root-scanning.
    "projects.registry": "~/.copilot/projects.json",
    # macOS Keychain service name secrets are stored/looked up under (see
    # core/keychain.py) -- never itself a secret.
    "auth.keychain_service": "com.everyoneneedsacopilot.copilot.github",
    # Device-flow OAuth scopes requested at sign-in.
    "auth.scopes": "read:org repo write:public_key",
}

# ---------------------------------------------------------------------------
# List-valued keys (ordered lists, comma-string affordances)
# ---------------------------------------------------------------------------

# Config keys whose value may be an ORDERED LIST rather than a single scalar.
# Currently only paths.knowledge_repo — see resolve_knowledge_repos() below.
# Each source layer (env / project / machine) still supplies the WHOLE list
# for this key; layers are never concatenated across sources.
LIST_VALUED_KEYS: frozenset[str] = frozenset({"paths.knowledge_repo", "projects.roots"})

# Sentinel distinguishing "no value passed" from an explicit None argument.
_UNSET = object()


def _split_csv_list(value: str) -> list[str]:
    """Split a comma-separated string into trimmed, non-empty parts."""
    return [part.strip() for part in value.split(",") if part.strip()]


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
    """Expand ~ in path-like string values (recursively for lists)."""
    if isinstance(value, str) and "~" in value:
        return str(Path(value).expanduser())
    if isinstance(value, list):
        return [_expand_path(v) for v in value]
    return value


def resolve_knowledge_repos(value: Any = _UNSET) -> list[str]:
    """
    Normalize a paths.knowledge_repo config value into an ordered list of paths.

    Accepts all three supported shapes:
      - None / absent    -> []
      - a JSON list       -> returned in order (non-empty entries only)
      - a legacy string   -> single-element list (NOT comma-split; a plain
                              string is always treated as one path for
                              back-compat with existing configs)

    If `value` is omitted, resolves "paths.knowledge_repo" from the effective
    config (env > project > machine > default) via resolve_key().

    Order in the returned list == resolution order (index 0 consulted first).
    """
    if value is _UNSET:
        value = resolve_key("paths.knowledge_repo")

    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


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
            raw_env = os.environ[env_name]
            if key in LIST_VALUED_KEYS:
                resolved[key] = _split_csv_list(raw_env)
            else:
                resolved[key] = raw_env

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
        raw_env = os.environ[env_name]
        if key in LIST_VALUED_KEYS:
            return _expand_path(_split_csv_list(raw_env))
        return _expand_path(raw_env)

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

    For LIST_VALUED_KEYS (e.g. "paths.knowledge_repo"), a comma-separated
    string value (e.g. "a,b,c") is parsed into a JSON list before writing.
    A single value with no comma is stored as a plain string, unchanged
    (back-compat — existing single-string configs keep working).

    Returns the path written to.
    """
    if (
        key in LIST_VALUED_KEYS
        and isinstance(value, str)
        and "," in value
    ):
        value = _split_csv_list(value)

    if project:
        cfg_path = project_config_path()
        if cfg_path is None:
            raise ValueError(
                "Not inside a git repository; cannot write project config."
            )
    else:
        cfg_path = machine_config_path()

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(cfg_path)
    _dotted_set(existing, key, value)

    cfg_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return cfg_path


def _as_list(current: Any) -> list[Any]:
    """Coerce an existing config value (None/string/list) into a list copy."""
    if current is None:
        return []
    if isinstance(current, list):
        return list(current)
    return [current]


def add_to_list_config(key: str, value: str, *, project: bool = False) -> Path:
    """
    Append `value` to a list-valued config key, idempotently.

    If the key currently holds a string, it is upgraded to a list (the
    existing string becomes the first element). If unset, starts a new
    list. No-op (no duplicate appended) if `value` is already present.

    Returns the path written to.
    """
    if project:
        cfg_path = project_config_path()
        if cfg_path is None:
            raise ValueError(
                "Not inside a git repository; cannot write project config."
            )
    else:
        cfg_path = machine_config_path()

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(cfg_path)
    current_list = _as_list(_dotted_get(existing, key))

    if value not in current_list:
        current_list.append(value)

    _dotted_set(existing, key, current_list)
    cfg_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return cfg_path


def remove_from_list_config(key: str, value: str, *, project: bool = False) -> Path:
    """
    Remove `value` from a list-valued config key (symmetric to add_to_list_config).

    No-op if `value` is not present. If the key was a plain string equal to
    `value`, it is removed and the key becomes an empty list.

    Returns the path written to.
    """
    if project:
        cfg_path = project_config_path()
        if cfg_path is None:
            raise ValueError(
                "Not inside a git repository; cannot write project config."
            )
    else:
        cfg_path = machine_config_path()

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(cfg_path)
    current_list = [v for v in _as_list(_dotted_get(existing, key)) if v != value]

    _dotted_set(existing, key, current_list)
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
            raise ValueError(
                "Not inside a git repository; cannot modify project config."
            )
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
        raw_env = os.environ[env_name]
        env_value: Any = _split_csv_list(raw_env) if key in LIST_VALUED_KEYS else raw_env
        return {
            "value": _expand_path(env_value),
            "source": "env",
            "reason": f"env var {env_name}",
        }

    if key in project_flat:
        raw_val = project_flat[key]
        if is_sentinel(raw_val):
            resolved = resolve_sentinel(
                raw_val, same_key=key, machine_config=machine_flat
            )
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
