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

Shape -- TWO supported forms (WP-372 P1.3: the real, live, admin-authored
`ecosystem.yml` on this machine turned out to use the SECOND form, not the
first; both are reconciled here so an org can author either):

  1. Hand-authored, already-joinable entries (this reader's original,
     speculative shape -- kept for orgs that want to hand-declare an
     exception, e.g. an irregular repo name):

        github_app:
          client_id: "Iv1.xxxxxxxxxxxxxxxx"
        departments:
          - id: finance
            name: Finance
            repo: org/dept-finance-copilot

  2. Convention-derived (the REAL shape -- verified live against this
     machine's `ecosystem.yml`, `~/.copilot/mirrors/claude-organization/
     ecosystem.yml`): a department declares only its `unit` + `topology`,
     and the org declares which product `components` it has enabled
     top-level. `department_catalog()` below derives the `{id, repo}`
     shape every catalog CONSUMER needs from these two facts + the naming
     convention every real department repo on this org already follows
     (`gh api /orgs/<org>/repos`: `claude-copilot-accounting`,
     `codex-copilot-accounting`, `knowledge-copilot-accounting`,
     `cli-copilot-accounting` -- i.e. `<component>-copilot-<unit>`):

        org: Everyone-Needs-A-Copilot
        components: [knowledge, cli, claude, codex]
        departments:
          - unit: accounting
            topology: separate

`departments()` below returns the RAW list from either shape, unreconciled
(pass-through, unchanged from this module's original contract -- existing
callers/tests that already hand-author the `{id, repo}` shape are
untouched). `department_catalog()` is the new, reconciled, join-ready view:
one catalog entry per (department unit, org-enabled component) pair for
shape 2, or the entry as-authored for shape 1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from cc.core.config import resolve_key

_log = logging.getLogger(__name__)

# WP-372 P1.3(b): the naming convention every real department repo on this
# org already follows (verified live, see module docstring) -- a pure
# function of (component, unit), never hand-typed per department.
_DEPARTMENT_REPO_TEMPLATE = "{component}-copilot-{unit}"

# "separate repo per department" is the documented default topology
# (claude-copilot/docs/80-initiatives/01-ecosystem-extensions/research/
# design-naming-topology.md §5: confidential-by-default department
# content) -- the only topology this reconciliation derives today.
# `subfolder`-topology derivation is a distinct `source.path` shape this
# module does not yet compute; an entry declaring it is reported (not
# silently guessed at) rather than derived incorrectly.
_DEFAULT_TOPOLOGY = "separate"
_SUPPORTED_TOPOLOGIES = frozenset({_DEFAULT_TOPOLOGY})

# Department tier rank (PERSONAL 10 < DEPARTMENT 20 < ORG 30 < FOUNDATION
# 40 -- claude-copilot/docs/80-initiatives/01-ecosystem-extensions/
# 02-four-tier-and-github-topology.md §2) -- the manifest position a
# joined department layer must land at so it folds between personal and
# org, not after foundation (`commands/layers.py`'s `_next_rank()` would
# otherwise push an unranked join to the END of the manifest).
_DEPARTMENT_RANK = 20

# Every real department repo on this org is a private, team-scoped clone
# over the `github-work` SSH alias (four-tier-and-github-topology.md §6;
# matches this machine's own `org-internal` layer entry in
# `copilot.layers.yml`) -- never `anon` (that's the public foundation-only
# credential).
_DEFAULT_DEPARTMENT_AUTH = "ssh-work"

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


def department_catalog(cfg: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """
    The JOIN-READY department catalog (WP-372 P1.3(b)) -- `commands/
    layers.py`'s `_catalog()` consumes this, not `departments()` directly.

    Reconciles BOTH shapes `departments()` may return (see module
    docstring): an entry already carrying non-empty `{id, repo}` is passed
    through unchanged (an org's explicit, hand-authored exception always
    wins); an entry shaped `{unit, topology}` (the REAL shape this org's
    live `ecosystem.yml` uses) is DERIVED into one catalog entry PER
    ORG-ENABLED COMPONENT (top-level `components: [...]`) -- WP-372
    P2.1-prereq: a department with claude+codex+knowledge+cli repos needs
    one JOINABLE layer per product, not one layer for the whole
    department, so `{unit: accounting}` with `components: [claude, codex,
    knowledge, cli]` fans into FOUR entries: `accounting-claude`,
    `accounting-codex`, `accounting-knowledge`, `accounting-cli` -- each
    already carrying its own correct `product` (feeding `commands/
    layers.py`'s `_new_manifest_layer()` directly, so a real join never
    falls through to that function's legacy `product: "cli"` default).

    Every derived entry's `repo` is an `"owner/name"` GitHub slug (`{org}/
    {component}-copilot-{unit}`) -- the SAME shape `core/ecosystem/
    entitlement.py`'s `repo_accessible()` and this reader's original
    hand-authored example both already use, so `build_layers_report()`'s
    entitlement check needs no changes to consume derived entries.

    WHY THE READER DERIVES (not the producer/admin): deriving here is the
    entire point of the ecosystem.yml design (claude-copilot/docs/
    80-initiatives/01-ecosystem-extensions/research/design-naming-
    topology.md §2: "one fetch, entire matrix derived") -- asking an admin
    to hand-type a repo URL for every (department x component) pair is
    exactly the manual-paste tax that design exists to avoid, and a single
    `{unit, topology}` entry is inherently a ONE-TO-MANY expansion (one
    department, several product repos) that no producer-side edit alone
    could collapse back to a single hand-authored row anyway.

    Fail-open, never silently: an entry that is neither shape, an
    unresolvable `org`/`components`, or an unsupported `topology` is
    logged via `logging.getLogger(__name__).warning(...)` NAMING the
    offending entry/department and then skipped -- WP-372 P1.3(c), the
    audit's specific complaint that `commands/layers.py`'s prior
    `continue` never said why a department vanished from the catalog. One
    malformed department never prevents every other department's catalog
    from resolving (same fail-open posture as the rest of this module).
    """
    cfg = cfg if cfg is not None else load_ecosystem_config()
    org = cfg.get("org")
    components = cfg.get("components")

    catalog: list[dict[str, Any]] = []

    for entry in departments(cfg):
        entry_id = entry.get("id")
        entry_repo = entry.get("repo")
        if (
            isinstance(entry_id, str)
            and entry_id
            and isinstance(entry_repo, str)
            and entry_repo
        ):
            # Already hand-authored in the join-ready shape -- pass through
            # unreconciled; an explicit admin declaration always wins.
            catalog.append(dict(entry))
            continue

        unit = entry.get("unit")
        if not isinstance(unit, str) or not unit:
            _log.warning(
                "ecosystem.yml departments entry is missing both "
                "{id, repo} and {unit} -- skipping malformed entry: %r",
                entry,
            )
            continue

        topology = entry.get("topology", _DEFAULT_TOPOLOGY)
        if topology not in _SUPPORTED_TOPOLOGIES:
            _log.warning(
                "department %r declares topology %r, which this reader "
                "does not yet derive (only %s is implemented) -- "
                "skipping catalog derivation for this department",
                unit, topology, sorted(_SUPPORTED_TOPOLOGIES),
            )
            continue

        if not isinstance(org, str) or not org:
            _log.warning(
                "ecosystem.yml has no top-level `org` -- cannot derive a "
                "repo slug for department %r, skipping", unit,
            )
            continue

        if not isinstance(components, list) or not components:
            _log.warning(
                "ecosystem.yml has no top-level `components` list -- "
                "cannot derive per-product layers for department %r, "
                "skipping", unit,
            )
            continue

        for component in components:
            if not isinstance(component, str) or not component:
                _log.warning(
                    "ecosystem.yml `components` entry %r is not a string "
                    "-- skipping malformed component for department %r",
                    component, unit,
                )
                continue
            catalog.append(
                {
                    "id": f"{unit}-{component}",
                    "name": f"{unit.capitalize()} ({component})",
                    "repo": f"{org}/"
                    + _DEPARTMENT_REPO_TEMPLATE.format(component=component, unit=unit),
                    "product": component,
                    "role": entry.get("role", "department"),
                    "rank": entry.get("rank", _DEPARTMENT_RANK),
                    "auth": entry.get("auth", _DEFAULT_DEPARTMENT_AUTH),
                }
            )

    return catalog
