"""Machine-wide project discovery + per-project freshness.

Component Sync initiative (Stream-E, WS-A-style verbs), Phase 2 (read-only):
copilot-control-tower/docs/80-initiatives/02-component-sync/ (README +
ADR-001 lock-manifest-as-propagation-index + ADR-002
auto-apply-and-hold-on-dirty + phases/phase-2-discovery-and-freshness.md).

THE INDEX (ADR-001): every project that embeds a framework component
tracks a per-project lock manifest -- a `copilot.lock.json` at that
project's OWN repo root, recording `{component, version, release_tag,
source, files: [{path, ownership, checksum}]}` per embedded component.
This is the machine-readable, per-file-ownership index that makes
machine-wide propagation computable without guessing or scanning
heuristics.

NAMING COLLISION (deliberately not hidden -- same posture as
core/ecosystem/lockfile.py's own module docstring, which already flags an
analogous "two different files, same conceptual name" situation): this
module's per-project manifest is ALSO named `copilot.lock.json`, but it is
a DIFFERENT SHAPE living in a DIFFERENT repo (a consumer project's own
root) than lockfile.py's per-layer SHA-pin lockfile (which lives at
*this* framework checkout's own `repo_root()`). The two never collide on
disk in the common case (a consumer project embedding claude-copilot/
codex-copilot is a different git repo than the claude-copilot framework
checkout itself). The one edge case where a single repo could be BOTH a
framework checkout (writing lockfile.py's shape via `cc update`) AND a
Component-Sync-tracked project (writing this module's shape) is left
unresolved here -- same deferred status as lockfile.py's own note --
because reconciling the two schemas under one filename is Phase 1's job
(freeze the lock-manifest schema), not this read-side slice's.

PRODUCT CLASSIFICATION (encoded as data via two frozensets, not inferred
from a possibly-stale per-file `scope` field): `PROJECT_SCOPED_PRODUCTS`
(claude, codex) fan out per project; `GLOBAL_ONCE_PRODUCTS` (knowledge,
cli) update once per machine and are reported at machine scope, never
duplicated per project (phase-2 doc, acceptance criteria). See
manifest.py's own module comment for the canonical four-product list this
mirrors.

Fail-open throughout: one bad candidate directory, unreadable manifest, or
corrupt registry entry never aborts the whole sweep -- mirrors
lockfile.py's read_lockfile() "missing/corrupt degrades to empty, never
raises" rule, and doctor.py/freshness.py's "no OTHER project's/layer's
result is ever aborted by one bad input" convention.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional, TypedDict

from cc.core.config import resolve_key
from cc.core.ecosystem.freshness import compute_freshness
from cc.core.ecosystem.materialize import guard_personal

# Sentinel distinguishing "no override passed" from an explicit None argument.
_UNSET: Any = object()

# Per-project tracked lock manifest filename -- see module docstring's
# "NAMING COLLISION" note for why this deliberately reuses the same
# filename as lockfile.py's (differently-shaped, differently-located)
# per-layer lockfile.
PROJECT_LOCK_FILENAME = "copilot.lock.json"

# Products that fan out per embedding project (Claude Copilot, Codex
# Copilot harness layers) -- ecosystem-architecture-level classification,
# per the initiative README's AS-7 reference. See module docstring.
PROJECT_SCOPED_PRODUCTS: frozenset[str] = frozenset({"claude", "codex"})

# Products that update once per machine (Knowledge Copilot, CLI Copilot) --
# reported once at machine scope, never fanned into any project's own
# components[] list.
GLOBAL_ONCE_PRODUCTS: frozenset[str] = frozenset({"knowledge", "cli"})

# Directory names never worth recursing into while scanning for candidate
# project roots -- heavy/irrelevant subtrees that never themselves contain
# a project's own top-level lock manifest. Purely a performance/safety
# bound, never a correctness rule (a project root itself is still found
# even if one of its own children happens to share one of these names).
_SKIP_DIR_NAMES = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}
)


# ---------------------------------------------------------------------------
# Per-project lock manifest I/O (fail-open reader, canonical-JSON writer)
# ---------------------------------------------------------------------------


def read_project_lock(path: Optional[Path | str]) -> dict[str, Any]:
    """
    Fail-open reader for a per-project component-embed lock manifest.

    Mirrors lockfile.py's `read_lockfile()` pattern exactly (same
    degrade-to-`{}` behavior for `None`/missing/corrupt/non-object JSON --
    a project that has not yet embedded anything, or whose manifest is
    momentarily unreadable, is an honest "nothing recorded", never a
    crash), just scoped to this module's different manifest shape
    (`{"schema_version": ..., "components": [...]}` -- see module
    docstring) rather than lockfile.py's `{layer: {dim: {item: sha}}}`.
    """
    if path is None:
        return {}

    resolved = Path(path).expanduser()
    if not resolved.exists():
        return {}

    try:
        data: Any = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def write_project_lock(path: Path | str, manifest: dict[str, Any]) -> None:
    """
    Write a per-project lock manifest as canonical (sort_keys, indent=2)
    JSON -- same convention as lockfile.py's `write_lockfile()`, so the
    file diffs cleanly in the embedding project's own source control (it
    is, by design, a tracked file -- ADR-001).

    Creates parent directories as needed. Callers are responsible for
    holding `copilot_lock()` around any write (mirrors lockfile.py's own
    "this function does not lock anything itself" contract).
    """
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def framework_owned_paths(entry: dict[str, Any]) -> list[str]:
    """
    Relative paths of every `ownership: framework` file in one component's
    manifest entry -- the ONLY paths a materialize run is ever allowed to
    write (ADR-001: "per-file ownership is the load-bearing field").
    `ownership: project` files are never returned here, structurally
    keeping them out of any write path built on top of this helper.
    """
    paths: list[str] = []
    for file_entry in entry.get("files", []) or []:
        if not isinstance(file_entry, dict):
            continue
        if file_entry.get("ownership") != "framework":
            continue
        rel_path = file_entry.get("path")
        if isinstance(rel_path, str) and rel_path:
            paths.append(rel_path)
    return paths


def _component_scope(product: str, entry: dict[str, Any]) -> str:
    """
    `"per-project"` | `"global"` classification for `product`.

    `PROJECT_SCOPED_PRODUCTS`/`GLOBAL_ONCE_PRODUCTS` are authoritative for
    the four known products (module docstring). For an unrecognized
    product, fall back to the manifest entry's own declared `scope` field
    if present and valid; otherwise default to `"per-project"` -- the
    conservative choice (an unknown product silently treated as
    global-once could get reported once and never surfaced as needing a
    per-project update; treating it as per-project only risks an extra,
    harmless per-project listing -- mirrors dimensions.py's
    `semantics_for()` "unknown defaults to the safer fold" precedent).
    """
    if product in PROJECT_SCOPED_PRODUCTS:
        return "per-project"
    if product in GLOBAL_ONCE_PRODUCTS:
        return "global"
    declared = entry.get("scope")
    if declared in ("per-project", "global"):
        return declared
    return "per-project"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _has_lock_manifest(path: Path) -> bool:
    try:
        return (path / PROJECT_LOCK_FILENAME).is_file()
    except OSError:
        return False


def _scan_root(root: Path, *, max_depth: int) -> list[Path]:
    """
    Recursive (bounded-depth) scan of `root` for directories carrying their
    own `copilot.lock.json`. Fail-open: an unreadable directory (permission
    error, race with a deletion, etc.) is skipped, never aborts the rest of
    the walk. Never follows symlinked directories (avoids an unbounded
    cycle across a machine's directory tree).
    """
    found: list[Path] = []

    def _walk(current: Path, depth: int) -> None:
        try:
            if _has_lock_manifest(current):
                found.append(current)
            if depth >= max_depth:
                return
            children = sorted(current.iterdir())
        except OSError:
            return

        for child in children:
            try:
                if child.is_symlink() or not child.is_dir():
                    continue
                if child.name in _SKIP_DIR_NAMES or child.name.startswith("."):
                    continue
            except OSError:
                continue
            _walk(child, depth + 1)

    _walk(root, 0)
    return found


def _read_registry(path: Optional[Path]) -> list[Path]:
    """
    Fail-open reader for the optional explicit-project registry
    (`~/.copilot/projects.json` by default -- injectable). Accepts either a
    bare JSON list of path strings, or `{"projects": [...]}`. Any other
    shape, or a missing/corrupt file, degrades to an empty list rather than
    raising -- this registry is a supplement to root-scanning, never a
    required input.
    """
    if path is None:
        return []

    try:
        if not path.exists():
            return []
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("projects", [])
    else:
        entries = []

    result: list[Path] = []
    if not isinstance(entries, list):
        return result

    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            continue
        try:
            result.append(Path(entry).expanduser())
        except (OSError, ValueError):
            continue
    return result


def discover_projects(
    *,
    roots: Optional[Iterable[Path | str]] = None,
    _registry: Any = _UNSET,
    max_depth: int = 3,
) -> list[Path]:
    """
    Enumerate every lock-manifested project on the machine: the union of
    (a) every directory found by recursively scanning `roots` (default:
    the resolved `projects.roots` config list -- config.py DEFAULTS) up to
    `max_depth`, and (b) every explicit path listed in the optional
    registry file (default: `projects.registry` config key, `_registry`
    injectable for tests -- `_registry=None` explicitly disables the
    registry lookup, distinct from "not supplied" which auto-resolves).

    Deduped by resolved absolute path, returned in a deterministic
    (sorted) order -- so a project reachable via BOTH a root scan and the
    registry is never double-counted.

    Fail-open per candidate: an unreadable root, a broken registry entry,
    or a candidate that vanishes mid-scan is skipped, never aborts the
    whole sweep (module docstring).
    """
    if roots is None:
        configured_roots = resolve_key("projects.roots") or []
        roots = configured_roots
    root_paths = [Path(r).expanduser() for r in roots]

    if _registry is not _UNSET:
        registry_path = Path(_registry).expanduser() if _registry is not None else None
    else:
        configured_registry = resolve_key("projects.registry")
        registry_path = Path(configured_registry).expanduser() if configured_registry else None

    found: dict[str, Path] = {}

    for root in root_paths:
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        for candidate in _scan_root(root, max_depth=max_depth):
            try:
                found[str(candidate.resolve())] = candidate
            except OSError:
                continue

    for candidate in _read_registry(registry_path):
        try:
            if not _has_lock_manifest(candidate):
                continue
            found[str(candidate.resolve())] = candidate
        except OSError:
            continue

    return [found[key] for key in sorted(found)]


# ---------------------------------------------------------------------------
# Per-project freshness
# ---------------------------------------------------------------------------


class ComponentFreshness(TypedDict):
    product: str
    current: Optional[str]
    latest: Optional[str]
    stale: Optional[bool]
    held: bool


class ProjectFreshness(TypedDict):
    path: str
    stale: Optional[bool]
    components: list[ComponentFreshness]


def project_freshness(
    project: Path | str,
    *,
    latest_by_product: dict[str, Optional[str]],
    _manifest: Optional[dict[str, Any]] = None,
    _personal_roots: Iterable[Path | str] = (),
) -> ProjectFreshness:
    """
    Fold one project's lock manifest against `latest_by_product` (caller-
    supplied -- a real caller resolves this from the mirrors via the
    existing freshness machinery; see `commands/projects.py`'s
    `build_all_projects_freshness()`, which defaults it honestly to `{}`
    -- unknown latest, never a fabricated version -- when nothing is
    injected).

    Only `PROJECT_SCOPED_PRODUCTS` components are folded here (a
    global-once component embedded/recorded in a project's manifest is
    reported once at machine scope by the caller, never per project --
    phase-2 doc acceptance criteria).

    Same honesty rule as `core/ecosystem/freshness.py`'s
    `compute_freshness()` (reused directly, not reimplemented): a
    component's `stale` is `None` whenever either version is unknown,
    `True`/`False` only when both are known -- never coerced.

    `held`: `True` when this component IS stale AND at least one of its
    `ownership: framework` paths currently sits inside a dirty git working
    tree (reused, unweakened, via `materialize.py`'s `guard_personal()`) --
    a preview of what a materialize run against this project would report,
    computed WITHOUT writing/locking/mutating anything (this function never
    calls `guard_personal()` for a component that isn't even stale, since
    there is nothing pending to hold).

    Overall project `stale`: `True` if any component is definitely stale;
    else `None` if any component's staleness is unknown; else `False`
    (every component known-current, including the vacuous case of zero
    tracked per-project components).
    """
    project_path = Path(project).expanduser()
    manifest = (
        _manifest
        if _manifest is not None
        else read_project_lock(project_path / PROJECT_LOCK_FILENAME)
    )

    components: list[ComponentFreshness] = []
    overall_stale: Optional[bool] = False

    raw_components = manifest.get("components", []) if isinstance(manifest, dict) else []
    for entry in raw_components if isinstance(raw_components, list) else []:
        if not isinstance(entry, dict):
            continue
        product = entry.get("component")
        if not isinstance(product, str) or not product:
            continue
        if _component_scope(product, entry) != "per-project":
            continue

        current = entry.get("version")
        latest = latest_by_product.get(product)
        folded = compute_freshness(current, latest)
        stale = folded["stale"]

        held = False
        if stale:
            held = any(
                guard_personal(project_path / rel_path, personal_roots=_personal_roots)
                for rel_path in framework_owned_paths(entry)
            )

        components.append(
            {
                "product": product,
                "current": current if isinstance(current, str) else None,
                "latest": latest,
                "stale": stale,
                "held": held,
            }
        )

        if stale is True:
            overall_stale = True
        elif stale is None and overall_stale is not True:
            overall_stale = None

    return {"path": str(project_path), "stale": overall_stale, "components": components}
