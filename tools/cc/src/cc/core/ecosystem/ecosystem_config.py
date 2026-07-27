"""READ-ONLY reader for the org's inherited `ecosystem.yml`.

WS-A foundation slice (Stream-F): the org-tier config an admin authors once
and every machine inherits (GitHub App client id for device-flow sign-in,
the department roster). This module NEVER writes anything -- mirrors
core/ecosystem/lockfile.py's `read_lockfile()` fail-open precedent: a
missing or malformed `ecosystem.yml` degrades to `{}` (every lookup
gracefully returns "unset" -- `None`/`[]`) rather than raising, so a
first-run machine (no inherited config materialized yet) still works.

Parsed with `yaml.safe_load` -- the same loader core/ecosystem/manifest.py's
`load_layers()` already uses for `copilot.layers.yml`, so this module adds
no new YAML dependency.

Shape (owner-ratified, admin-authored, inherited via the same
foundation->org->dept->personal materialize path every other layer-owned
file uses -- see copilot-control-tower/docs/reference/
ecosystem-architecture.md):

    github_app:
      client_id: "Iv1.xxxxxxxxxxxxxxxx"
    departments:
      - id: finance
        name: Finance
        repo: org/dept-finance-copilot
      - id: engineering
        name: Engineering
        repo: org/dept-engineering-copilot
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from cc.core.config import resolve_key

# Sentinel distinguishing "no override passed" from an explicit None
# argument (mirrors core/ecosystem/mirror.py's `_root` / commands/
# freshness.py's `_UNSET` injection convention).
_UNSET: Any = object()


def ecosystem_config_path(*, _path: Any = _UNSET) -> Optional[Path]:
    """
    Resolve the path to the inherited `ecosystem.yml`.

    `_path` is injectable so tests can point this at `tmp_path` (or `None`,
    to simulate "no config anywhere") without touching real config files --
    mirrors `mirror_root()`'s `_root` injection convention. When `_path` is
    the sentinel (not supplied), resolves the `paths.ecosystem_config`
    config key (env>project>machine>default cascade, same as every other
    `cc` path key); if that key is unset, derives
    `<paths.materialize_root>/ecosystem.yml` (the materialized tree every
    other layer-owned, inherited file already lands under -- see
    core/config.py DEFAULTS' `paths.materialize_root` docstring). Returns
    `None` only when neither is resolvable (no materialize root configured
    either) -- treated identically to "file absent" by `load_ecosystem_config()`.
    """
    if _path is not _UNSET:
        return Path(_path).expanduser() if _path is not None else None

    configured = resolve_key("paths.ecosystem_config")
    if configured:
        return Path(configured).expanduser()

    materialize_root = resolve_key("paths.materialize_root")
    if not materialize_root:
        return None
    return Path(materialize_root).expanduser() / "ecosystem.yml"


def load_ecosystem_config(path: Optional[Path | str] = None) -> dict[str, Any]:
    """
    Read-only YAML load of the inherited `ecosystem.yml`.

    Fail-open `{}` on missing/malformed -- mirrors `read_lockfile()`'s
    semantics (core/ecosystem/lockfile.py): a first-run machine (no
    ecosystem.yml materialized yet) or an unreadable file never raises,
    every lookup just degrades to "unset".

    `path=None` (default) resolves the real location via
    `ecosystem_config_path()`; pass an explicit path (e.g. a `tmp_path`
    fixture file) to bypass resolution entirely.
    """
    resolved = Path(path).expanduser() if path is not None else ecosystem_config_path()
    if resolved is None or not resolved.exists():
        return {}

    try:
        data: Any = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def github_client_id(cfg: Optional[dict[str, Any]] = None) -> Optional[str]:
    """
    Return `cfg["github_app"]["client_id"]`, or `None` if absent/malformed.

    `cfg=None` (default) loads the real `ecosystem.yml` via
    `load_ecosystem_config()`; pass an already-loaded dict (e.g. from a
    test fixture) to avoid re-reading the file.
    """
    cfg = cfg if cfg is not None else load_ecosystem_config()
    github_app = cfg.get("github_app")
    if not isinstance(github_app, dict):
        return None
    client_id = github_app.get("client_id")
    return client_id if isinstance(client_id, str) and client_id else None


def departments(cfg: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """
    Return the `departments:` list (each `{id, name, repo, ...}`), or `[]`
    if absent/malformed.

    `cfg=None` (default) loads the real `ecosystem.yml` via
    `load_ecosystem_config()`; pass an already-loaded dict (e.g. from a
    test fixture) to avoid re-reading the file. Non-dict entries in the
    list are silently dropped (malformed data degrades to "not there"
    rather than raising, same fail-open posture as the rest of this
    module).
    """
    cfg = cfg if cfg is not None else load_ecosystem_config()
    depts = cfg.get("departments")
    if not isinstance(depts, list):
        return []
    return [dept for dept in depts if isinstance(dept, dict)]
