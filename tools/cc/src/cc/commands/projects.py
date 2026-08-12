"""Machine-wide fan-out sync: `cc projects` (Component Sync Stream-E).

Backs the app's "Updated Claude Copilot across N of your projects" surface
(copilot-control-tower/docs/80-initiatives/02-component-sync/README.md
Target Outcomes + phases/phase-2-discovery-and-freshness.md,
phases/phase-3-materialize-and-fanout.md). NOT wired into `cc/main.py`'s
Typer app in this slice -- integration wires the `cc projects`/
`cc materialize --project`/`--fanout` subcommands separately; this module
only builds the `--json` contract objects (mirrors `commands/update.py`'s
own `build_*`/`execute_*` split, and its own precedent of being callable
standalone before CLI wiring lands).

Three surfaces:
  - `build_all_projects_freshness()` -- READ-ONLY sweep across every
    discovered project (`core/ecosystem/projects.py`'s `discover_projects()`
    + `project_freshness()`), plus a deduped machine-scope `global` section
    for `GLOBAL_ONCE_PRODUCTS`. Changes zero files.
  - `build_materialize_project_report()` / `execute_materialize_project()`
    -- per-project, per-component materialize: framework-owned files only,
    held on dirty WIP (never stashed/forced), blocked on an unverified
    (no `release_tag`) target, offline when the source content root is
    unreachable. Reuses `update.schema.json`'s own report shape (`schema_
    version`, `result`, `lock_before`, `lock_after`, `changed`,
    `held_for_approval`, `blocked`) plus an additive `path` field -- see
    that schema's `$comment` for the additive-only rule this follows.
  - `build_fanout_report()` / `execute_fanout()` -- the roll-up: iterates
    every discovered project's PROJECT_SCOPED_PRODUCTS components, fans a
    materialize attempt out to every stale one, and aggregates
    `{updated, held, up_to_date, failed, total}` + per-`(project,
    component)` results.

LOCKING: `build_*` functions never acquire `copilot_lock()` themselves
(mirrors `update.py`'s own `build_update_report()`/`execute_update()`
split) -- `execute_materialize_project()`/`execute_fanout()` are the only
lock-acquiring entry points. Critically, `build_fanout_report()` calls
`build_materialize_project_report()` DIRECTLY (never
`execute_materialize_project()`) for each project it fans out to: nesting
two lock ACQUISITIONS from the same process would either deadlock or
self-report spurious contention (`copilot_lock()`'s `flock` is per-open-
file-description, not reentrant) -- the whole fan-out sweep holds the
mutex exactly once.

NEVER-DESTROY: materialize writes ONLY `ownership: framework` paths
(`core/ecosystem/projects.py`'s `framework_owned_paths()`), and reuses
`materialize.py`'s own `guard_personal()` UNWEAKENED for the dirty-tree
hold check (never a second, looser reimplementation of that guard) --
ADR-002's "hold the whole component update for that project" rule.
ALSO holds on recorded-checksum drift (task-372) -- a framework-owned
file whose on-disk content no longer matches the checksum this manifest
itself last recorded is held with reason `"locally-modified"` regardless
of git status, so a customization the project owner COMMITTED (tree
clean, `guard_personal()` alone sees nothing to hold) is never silently
overwritten by a later fanout.

PER-ARTIFACT TIER RESOLUTION (component-sync fan-out reconnection): the
`claude` component's `commands`/`agents` dimensions no longer materialize
from ONE ROOT PER PRODUCT. `build_materialize_project_report()` resolves
each tracked `.claude/{commands,agents}/<item>.md` path individually
through `core/ecosystem/project_sources.py`'s `resolve_claude_content()`
-- the SAME nearest-SUBSTANTIVE-tier-wins resolver `workspaces.py`'s
`_claude_plan()` already consumes for the initial single-project install
-- so fan-out and single-project install can never disagree about which
tier is "current". This is the ONLY tier-resolution implementation
either path calls; nothing here re-derives nearest-wins a second way.
`source_root`/`source_roots["claude"]` (from `resolve_fanout_sources()`)
remains the FOUNDATION root: it is `resolve_claude_content()`'s own
`foundation_root` argument, its degrade target when no manifest is
configured, and the sole source for every framework-owned path that has
no ladder concept at all (`fitness-check.sh`, the enforcement hook,
evals, the project template -- see `project_sources.py`'s
`INSTALL_DIMENSIONS`). `codex` has no ladder concept yet and always
takes the single-root path unchanged.
"""

from __future__ import annotations

import hashlib
import re
import socket
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from cc.commands.update import compute_exit_code
from cc.core.ecosystem.freshness import compute_freshness, lock_fingerprint
from cc.core.ecosystem.materialize import guard_personal
from cc.core.ecosystem.project_sources import (
    INSTALL_DIMENSIONS,
    ResolvedItem,
    claude_resolution_checksums,
    resolve_all_claude_items,
    resolve_claude_content,
)
from cc.core.ecosystem.projects import (
    GLOBAL_ONCE_PRODUCTS,
    PROJECT_LOCK_FILENAME,
    PROJECT_SCOPED_PRODUCTS,
    discover_projects,
    framework_owned_paths,
    locally_modified_paths,
    project_freshness,
    read_project_lock,
    write_project_lock,
)
from cc.core.locking import LockContentionError, copilot_lock, lock_path

# `.claude/commands/<item>.md` / `.claude/agents/<item>.md` -- the only
# `claude` framework-owned paths with a ladder concept (`INSTALL_DIMENSIONS`).
# Every other framework-owned path (fitness-check.sh, the hook, evals, ...)
# never matches this and stays foundation-sourced.
_CLAUDE_LADDER_PATH_RE = re.compile(r"^\.claude/(commands|agents)/([^/]+)\.md$")


def _claude_ladder_dimension_item(rel_path: str) -> Optional[tuple[str, str]]:
    """`(dimension, item)` for a `claude` component's ladder-eligible
    tracked path, or `None` for a path `resolve_claude_content()` has no
    opinion about (module docstring's PER-ARTIFACT TIER RESOLUTION note)."""
    match = _CLAUDE_LADDER_PATH_RE.match(rel_path)
    if match is None:
        return None
    dimension, item = match.group(1), match.group(2)
    if dimension not in INSTALL_DIMENSIONS:
        return None
    return dimension, item


def _claude_content_stale(
    entry: dict[str, Any], *, checksum_by_key: Mapping[tuple[str, str], str]
) -> bool:
    """
    CONTENT-LEVEL STALENESS (mechanism defect fix, 2026-08): True if ANY
    of `entry`'s ladder-eligible tracked paths (`.claude/{commands,agents}/
    <item>.md`) would resolve to DIFFERENT bytes than what this project's
    manifest last recorded for it — the signal a bare version-string
    comparison can never see, because org/department/personal tier
    content changing does not bump the foundation's version (see
    `project_sources.py`'s `resolve_claude_content()` docstring, PER-
    ARTIFACT TIER RESOLUTION note).

    `checksum_by_key` is `claude_resolution_checksums()`'s pre-computed
    `{(dimension, item): "sha256:<hex>"}` map, built ONCE per fan-out
    sweep (`build_fanout_report()`) or once per standalone materialize
    call (`build_materialize_project_report()`'s own fallback) — comparing
    against it here costs ZERO additional file I/O: the recorded checksum
    already lives in `entry`, and the resolved-tier checksum was hashed
    once, never per project.

    A path with no ladder concept, no recorded checksum yet (a first-time
    add — nothing to compare, not a drift), or nothing resolvable in
    `checksum_by_key` (no manifest configured, or no tier declares it) is
    never a drift signal here — matches `locally_modified_paths()`'s own
    posture on the equivalent question at the destination side.
    """
    if not checksum_by_key:
        return False
    files_by_path = {
        f.get("path"): f
        for f in entry.get("files", []) or []
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    }
    for rel_path in framework_owned_paths(entry):
        parsed = _claude_ladder_dimension_item(rel_path)
        if parsed is None:
            continue
        resolved_checksum = checksum_by_key.get(parsed)
        if resolved_checksum is None:
            continue
        recorded = files_by_path.get(rel_path, {}).get("checksum")
        if not isinstance(recorded, str):
            continue
        if resolved_checksum != recorded:
            return True
    return False


SCHEMA_VERSION = "1.0"

# Sentinel distinguishing "no override passed" from an explicit None argument.
_UNSET: Any = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()  # noqa: S324 (content-identity, not a security hash)


# ---------------------------------------------------------------------------
# Read-side: all-projects freshness sweep
# ---------------------------------------------------------------------------


def build_all_projects_freshness(
    *,
    _projects: Optional[list[Path]] = None,
    _roots: Any = _UNSET,
    _registry: Any = _UNSET,
    _latest_by_product: Optional[dict[str, Optional[str]]] = None,
    _personal_roots: Iterable[Path | str] = (),
) -> dict[str, Any]:
    """
    Build the `cc projects freshness --all --json`-style contract object:
    a per-project sweep (`PROJECT_SCOPED_PRODUCTS` components only) plus a
    deduped machine-scope `global` section (`GLOBAL_ONCE_PRODUCTS`).

    `_latest_by_product` is the caller-supplied `{product: latest_version}`
    lookup (module docstring: "compute from mirrors via existing freshness
    machinery" is the real caller's job, e.g. a later CLI-wiring slice);
    defaulting to `{}` here is the honest "nothing known" state -- every
    component then folds to `stale: None`, never a fabricated verdict
    (mirrors `core/ecosystem/freshness.py`'s own honesty rule).

    Pure read: never acquires `copilot_lock()`, never writes/deletes
    anything -- mirrors `commands/freshness.py`'s read-only precedent.
    Fail-open per project: one project with an unreadable/corrupt manifest
    or an unexpected error is skipped (never included in `projects`, never
    aborts the rest of the sweep) -- `total` reflects only the projects
    actually folded in.
    """
    latest_by_product = _latest_by_product or {}

    if _projects is not None:
        projects = _projects
    else:
        discover_kwargs: dict[str, Any] = {}
        if _roots is not _UNSET:
            discover_kwargs["roots"] = _roots
        if _registry is not _UNSET:
            discover_kwargs["_registry"] = _registry
        projects = discover_projects(**discover_kwargs)

    project_entries: list[dict[str, Any]] = []
    global_seen: dict[str, dict[str, Any]] = {}

    for project in projects:
        try:
            manifest = read_project_lock(Path(project) / PROJECT_LOCK_FILENAME)
            entry = project_freshness(
                project,
                latest_by_product=latest_by_product,
                _manifest=manifest,
                _personal_roots=_personal_roots,
            )
        except Exception:
            # Fail-open: this one project's scan never aborts the sweep
            # (module docstring / phase-2 doc's own fail-open rule).
            continue

        project_entries.append(dict(entry))

        raw_components = manifest.get("components", []) if isinstance(manifest, dict) else []
        for comp in raw_components if isinstance(raw_components, list) else []:
            if not isinstance(comp, dict):
                continue
            product = comp.get("component")
            if not isinstance(product, str) or product not in GLOBAL_ONCE_PRODUCTS:
                continue
            if product in global_seen:
                continue  # global-once: first recorded sighting wins.
            current = comp.get("version")
            latest = latest_by_product.get(product)
            folded = compute_freshness(current, latest)
            global_seen[product] = {
                "product": product,
                "current": current if isinstance(current, str) else None,
                "latest": latest,
                "stale": folded["stale"],
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "total": len(project_entries),
        "projects": project_entries,
        "global": [global_seen[key] for key in sorted(global_seen)],
    }


def render_all_projects_freshness_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_all_projects_freshness()` payload."""
    from rich.console import Console

    con = console or Console()
    con.print(f"[bold]projects freshness[/bold]: {report.get('total', 0)} project(s) tracked")

    for g in report.get("global", []):
        state = "stale" if g.get("stale") else ("unknown" if g.get("stale") is None else "current")
        con.print(f"  [dim](global)[/dim] {g['product']}: {state}")

    for p in report.get("projects", []):
        stale = p.get("stale")
        color = "yellow" if stale else ("dim" if stale is None else "green")
        con.print(f"  [{color}]{p['path']}[/{color}]")
        for c in p.get("components", []):
            flag = " [yellow](waiting on your unsaved changes)[/yellow]" if c.get("held") else ""
            con.print(f"    {c['product']}: {c.get('current')} -> {c.get('latest')}{flag}")


# ---------------------------------------------------------------------------
# Write-side: per-project materialize
# ---------------------------------------------------------------------------


def build_materialize_project_report(
    project_path: Path | str,
    *,
    component: str,
    target_version: Any = _UNSET,
    release_tag: Optional[str] = None,
    source_root: Any = _UNSET,
    _manifest: Optional[dict[str, Any]] = None,
    _lock_manifest_path: Any = _UNSET,
    _personal_roots: Iterable[Path | str] = (),
    _claude_layers: Optional[list[dict[str, Any]]] = None,
    _claude_resolution_cache: Optional[Mapping[tuple[str, str], ResolvedItem]] = None,
    _claude_checksum_cache: Optional[Mapping[tuple[str, str], str]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Build (and, unless `dry_run=True`, apply) a per-project, per-component
    materialize: bring `component`'s `ownership: framework` files in
    `project_path` to `target_version`, per ADR-002's auto-apply rules.

    Result precedence (never both applied and something else):
      - `component` not in `PROJECT_SCOPED_PRODUCTS` -> `blocked`
        ("component is global-once; not materialized per project" -- a
        global-once component's single machine-wide apply is `cc update`'s
        job, never duplicated here).
      - `component` not embedded in this project's manifest, or has no
        framework-owned files at all -> `up-to-date`, zero writes.
      - already at `target_version` AND (for `claude`) every ladder-
        eligible tracked file's resolved-tier content already matches
        what this project's manifest recorded -> `up-to-date`, zero
        writes. CONTENT-LEVEL STALENESS WIDENING (mechanism defect fix,
        2026-08): a version-string match ALONE is no longer sufficient
        proof of "nothing pending" for `claude` -- org/department/
        personal tier content can change without ever bumping the
        foundation's version (`project_sources.py`'s PER-ARTIFACT TIER
        RESOLUTION note). `_claude_content_stale()` compares the
        resolved tier's checksum against the RECORDED checksum for each
        ladder-eligible path (via `_claude_resolution_cache`/
        `_claude_checksum_cache`, or a fresh one-off resolve when neither
        is supplied) -- zero extra file reads on the destination side,
        since the comparison never touches the project's own on-disk
        file, only the two checksums. A genuine version bump still
        triggers an update exactly as before; this only widens what ELSE
        also counts as "stale".
      - no `release_tag` supplied -> `blocked` ("unverified" -- SAME reason
        string `materialize.py` uses for its own fail-closed policy
        default; ADR-002's rule 1: only a PUBLISHED release tag licenses
        auto-apply, so an untagged target is refused exactly like an
        unsigned item, never silently applied).
      - `source_root` missing/unreadable, or ANY framework-owned file's
        source content absent under it -> `offline` (honest "could not
        reach the content this update needs" -- mirrors `update.py`'s own
        "no partial materialize" rule: nothing is written, never a partial
        apply of only the files that WERE found).
      - any framework-owned path's ACTUAL on-disk checksum no longer
        matches the checksum THIS manifest last recorded for it -> `held`,
        reason `"locally-modified"` (task-372: independent of git status --
        catches a customization the owner COMMITTED, not just an
        uncommitted one; `guard_personal()`'s dirty-tree check alone cannot
        see a clean-but-customized tree, and empirically did not hold one).
        Checked BEFORE the dirty-tree guard so a genuine content
        customization is always reported as "locally-modified", the more
        actionable of the two reasons, even if the tree also happens to be
        dirty for an unrelated reason.
      - any framework-owned path sits inside a dirty git working tree
        (`guard_personal()`, reused unweakened) -> `held`, `heldReason`
        carried in the existing `held_for_approval[].reason` field as
        `"dirty-working-tree"` (update.schema.json's shape has no separate
        `heldReason` field; this is the additive-only reuse the module
        docstring describes), the WHOLE component held, zero files
        touched.
      - otherwise -> `applied`: every framework-owned file is written
        (content-compared first; `dry_run=True` computes the same plan
        without writing/pruning anything, same convention as
        `materialize.py`'s own `dry_run`), the manifest entry's `version`/
        `release_tag`/per-file `checksum`s are updated, and (unless
        `dry_run`) the manifest is rewritten via `write_project_lock()`.
        Project-owned files are never read, hashed, or written. For
        `component == "claude"`, each ladder-eligible file (`.claude/
        {commands,agents}/<item>.md`) is written from wherever
        `resolve_claude_content()` resolves it (nearest substantive tier),
        not necessarily `source_root` -- `changed[].layer` records the
        REAL winning tier id for that file (e.g. `"claude-organization"`),
        never just the component name, so a materialize's own report is
        the attribution proof. Every other framework-owned path (no ladder
        concept) still comes from `source_root` and reports `layer ==
        component`, unchanged from before.

    `lock_before`/`lock_after` reuse `core/ecosystem/freshness.py`'s
    `lock_fingerprint()` (the same canonical-JSON git-blob-sha1 scheme
    `cc update --json` already uses) applied to this project's OWN
    manifest dict -- so the fields satisfy update.schema.json's `git_sha`
    pattern without inventing a second fingerprint scheme.

    Does NOT acquire `copilot_lock()` -- see module docstring (that is
    `execute_materialize_project()`'s job, and `build_fanout_report()`
    calls this function directly for the same reason).

    `_claude_layers` is test-only (same convention as `_manifest`/
    `_personal_roots` above): forwarded verbatim as `resolve_claude_
    content()`'s own `_layers` override. `None` (the default) means "not
    overridden" -- `resolve_claude_content()` auto-resolves the real
    `layers.manifest` config key, exactly like production callers.

    `_claude_resolution_cache`/`_claude_checksum_cache`: optional pre-
    built `resolve_all_claude_items()`/`claude_resolution_checksums()`
    results (`project_sources.py`), consumed for BOTH the content-
    staleness check above AND the real write-time resolution. `build_
    fanout_report()` builds each of these ONCE per sweep and passes them
    to every project's call here, so a 66-project fan-out run pays the
    discovery/resolve/substance/hash cost exactly once, never once per
    project. `None` (the default -- a standalone caller like `cc
    materialize --project`) means this call builds its own small one-off
    cache scoped to just this project's own ladder items, no more I/O than
    a version-differs materialize already paid before this fix existed.
    """
    project = Path(project_path).expanduser()
    manifest = (
        _manifest
        if _manifest is not None
        else read_project_lock(
            (_lock_manifest_path if _lock_manifest_path is not _UNSET else project / PROJECT_LOCK_FILENAME)
        )
    )
    lock_before = lock_fingerprint(manifest)

    def _report(
        *,
        result: str,
        changed: Optional[list[dict[str, Any]]] = None,
        held_for_approval: Optional[list[dict[str, Any]]] = None,
        blocked: Optional[list[dict[str, Any]]] = None,
        lock_after: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "host": socket.gethostname(),
            "path": str(project),
            "result": result,
            "lock_before": lock_before,
            "lock_after": lock_after if lock_after is not None else lock_before,
            "changed": changed or [],
            "held_for_approval": held_for_approval or [],
            "blocked": blocked or [],
        }

    if component not in PROJECT_SCOPED_PRODUCTS:
        return _report(
            result="blocked",
            blocked=[
                {
                    "dimension": component,
                    "reason": "component is global-once; not materialized per project",
                }
            ],
        )

    raw_components = manifest.get("components", []) if isinstance(manifest, dict) else []
    entry = next(
        (
            c
            for c in (raw_components if isinstance(raw_components, list) else [])
            if isinstance(c, dict) and c.get("component") == component
        ),
        None,
    )
    if entry is None:
        return _report(result="up-to-date")

    current_version = entry.get("version")
    resolved_target = target_version if target_version is not _UNSET else current_version

    # `rel_paths` is a pure, side-effect-free computation from `entry` --
    # moved up here (from its original position after the release_tag
    # check below) only so the content-staleness check can use it too. The
    # actual "no framework-owned files -> up-to-date" BRANCH stays at its
    # original position, unchanged relative to the release_tag check.
    rel_paths = framework_owned_paths(entry)

    # CONTENT-LEVEL STALENESS WIDENING (mechanism defect fix, 2026-08): see
    # this function's own docstring. `ladder_items` is computed once here
    # and reused again below at write time (never re-derived) -- `resolve
    # _all_claude_items()`/`claude_resolution_checksums()` similarly
    # computed (or reused from the caller's cache) once and shared between
    # the staleness check and the write step.
    ladder_items: dict[str, list[str]] = {}
    if component == "claude":
        for rel_path in rel_paths:
            parsed = _claude_ladder_dimension_item(rel_path)
            if parsed is None:
                continue
            dimension, item = parsed
            ladder_items.setdefault(dimension, []).append(item)

    resolution_cache = _claude_resolution_cache
    if ladder_items and resolution_cache is None:
        resolution_cache = resolve_all_claude_items(_layers=_claude_layers)

    checksum_cache = _claude_checksum_cache
    if ladder_items and checksum_cache is None:
        checksum_cache = claude_resolution_checksums(resolution_cache) if resolution_cache else {}

    version_stale = current_version != resolved_target
    content_stale = bool(checksum_cache) and _claude_content_stale(
        entry, checksum_by_key=checksum_cache
    )

    if not version_stale and not content_stale:
        return _report(result="up-to-date")

    if not release_tag:
        return _report(
            result="blocked",
            blocked=[{"dimension": component, "reason": "unverified"}],
        )

    if not rel_paths:
        return _report(result="up-to-date")

    # task-372 protocol-override fix: recorded-checksum drift is its OWN
    # hold signal, independent of `guard_personal()`'s git-dirty check.
    # `guard_personal()` only protects a file while it is UNCOMMITTED --
    # the moment a human commits their customization (the ordinary, expected
    # git workflow), the tree goes clean and the dirty-tree guard sees
    # nothing to hold, so a stale-but-committed customization was silently
    # overwritten by whatever the fanout target's source content is
    # (empirically confirmed live: a project's committed edit to a
    # `ownership: framework` file was clobbered with `result: "applied"`,
    # zero hold, zero block). `locally_modified_paths()` is shared with
    # `project_freshness()`'s read-only preview so the two never disagree.
    files_by_path = {
        f.get("path"): f
        for f in entry.get("files", []) or []
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    }

    if locally_modified_paths(project, entry):
        return _report(
            result="held",
            held_for_approval=[
                {
                    "dimension": component,
                    "from": current_version or "",
                    "to": resolved_target or "",
                    "reason": "locally-modified",
                }
            ],
        )

    if any(
        guard_personal(project / rel_path, personal_roots=_personal_roots)
        for rel_path in rel_paths
    ):
        return _report(
            result="held",
            held_for_approval=[
                {
                    "dimension": component,
                    "from": current_version or "",
                    "to": resolved_target or "",
                    "reason": "dirty-working-tree",
                }
            ],
        )

    source_base = Path(source_root).expanduser() if source_root not in (_UNSET, None) else None
    if source_base is None or not source_base.is_dir():
        return _report(result="offline")

    # PER-ARTIFACT TIER RESOLUTION (module docstring): for `claude`, every
    # ladder-eligible tracked path resolves individually through
    # `resolve_claude_content()` -- nearest-SUBSTANTIVE-tier-wins, exactly
    # like `_claude_plan()`'s single-project install -- rather than always
    # copying from `source_base`. A path this resolves nothing for (not a
    # `commands`/`agents` item, or `component != "claude"`) keeps the prior
    # single-root behavior unchanged. `ladder_items` and `resolution_cache`
    # were already computed above (for the content-staleness check) --
    # reused here verbatim, never re-derived.
    ladder_by_relpath: dict[str, ResolvedItem] = {}
    if component == "claude" and ladder_items:
        resolved_map = resolve_claude_content(
            foundation_root=source_base,
            items=ladder_items,
            _layers=_claude_layers,
            _resolution_cache=resolution_cache,
        )
        for rel_path in rel_paths:
            parsed = _claude_ladder_dimension_item(rel_path)
            if parsed is None:
                continue
            resolved = resolved_map.get(parsed)
            if resolved is not None:
                ladder_by_relpath[rel_path] = resolved

    def _source_for(rel_path: str) -> Path:
        resolved = ladder_by_relpath.get(rel_path)
        return resolved.path if resolved is not None else source_base / rel_path

    missing = [rel_path for rel_path in rel_paths if not _source_for(rel_path).is_file()]
    if missing:
        return _report(
            result="blocked",
            blocked=[
                {"dimension": component, "item": rel_path, "reason": "source content not found"}
                for rel_path in missing
            ],
        )

    changed: list[dict[str, Any]] = []

    for rel_path in rel_paths:
        src = _source_for(rel_path)
        dest = project / rel_path
        src_bytes = src.read_bytes()
        to_sha = _sha256_hex(src_bytes)
        # task-372 sibling defect (item-1 note 9): a bare write_bytes() never
        # sets a mode, so a materialized `.sh` (fitness-check.sh, and now the
        # copilot-hook.sh shim) landed non-executable -- a silent fail-open
        # that looks fine (`op: "added"`/"updated"`, checksum matches) while
        # actually doing nothing when the harness tries to exec it. Carry the
        # SOURCE file's mode through unconditionally, matching how the recipe
        # engine's COPY_FILE_FROM_SOURCE already does this (`_prepare_mutation`
        # in reconciliation_transaction.py).
        src_mode = stat.S_IMODE(src.stat().st_mode)

        existed = dest.is_file()
        from_sha = _sha256_hex(dest.read_bytes()) if existed else None
        content_matches = existed and dest.read_bytes() == src_bytes
        mode_matches = existed and stat.S_IMODE(dest.stat().st_mode) == src_mode

        if not dry_run and (not content_matches or not mode_matches):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src_bytes)
            dest.chmod(src_mode)

        op = "unchanged" if content_matches else ("updated" if existed else "added")
        resolved_item = ladder_by_relpath.get(rel_path)
        changed.append(
            {
                "dimension": component,
                # Real attribution: the actual tier that supplied this file
                # (e.g. "claude-organization"), not just the product name --
                # `resolved_item` is only set for `claude`'s ladder-eligible
                # paths (module docstring); every other path (`codex`, or a
                # `claude` scaffold path with no ladder concept) keeps the
                # prior `component`-name convention unchanged.
                "layer": resolved_item.layer if resolved_item is not None else component,
                "item": rel_path,
                "op": op,
                "from": from_sha,
                "to": to_sha,
                "signed": True,
                "severity_trailer": None,
                "shadowed_by": None,
            }
        )

        if not dry_run and rel_path in files_by_path:
            files_by_path[rel_path]["checksum"] = f"sha256:{to_sha}"

    if not dry_run:
        entry["version"] = resolved_target
        entry["release_tag"] = release_tag
        write_project_lock(
            (_lock_manifest_path if _lock_manifest_path is not _UNSET else project / PROJECT_LOCK_FILENAME),
            manifest,
        )

    lock_after = lock_fingerprint(manifest) if not dry_run else lock_before
    return _report(result="applied", changed=changed, lock_after=lock_after)


def execute_materialize_project(
    project_path: Path | str,
    *,
    _lock_path: Any = _UNSET,
    **build_kwargs: Any,
) -> tuple[dict[str, Any], int]:
    """
    CLI-facing wrapper: acquire `copilot_lock()`, then build (and, unless
    `dry_run`) apply the per-project materialize report. Returns
    `(report, exit_code)` -- reuses `update.py`'s own `compute_exit_code()`
    (identical `result` enum, so identical mapping; imported, never
    reimplemented) for everything except lock contention, which -- like
    `execute_update()` -- is reported as `error.code = "lock-contention"`
    with exit code 2.
    """
    target_lock_path = _lock_path if _lock_path is not _UNSET else lock_path()

    try:
        with copilot_lock(path=target_lock_path):
            report = build_materialize_project_report(project_path, **build_kwargs)
    except LockContentionError as exc:
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "error": {"code": "lock-contention", "message": str(exc)},
            },
            2,
        )

    return report, compute_exit_code(report)


# ---------------------------------------------------------------------------
# Write-side: fan-out roll-up
# ---------------------------------------------------------------------------


def resolve_fanout_sources() -> tuple[
    dict[str, str], dict[str, Optional[str]], dict[str, Optional[str]]
]:
    """
    Resolve the real `(source_roots, latest_by_product, release_tags)` triple
    `cc/main.py`'s `update --fanout` call site wires into `execute_fanout()`
    -- the piece that was simply never wired (main.py used to call
    `execute_fanout(dry_run=dry_run)` with NEITHER argument, so every
    project folded to `latest = None` -> `stale: None` -> silently never
    counted; see `build_fanout_report()`'s own note on that below).

    Reuses `core/ecosystem/workspaces.py`'s OWN single-project-install
    resolution -- `_resolved_framework_root()` (the `paths.claude_copilot_
    root` / `paths.codex_copilot_root` config keys) and `_source_version()`
    (VERSION.json / plugin.json reading, `f"v{version}"` release-tag
    convention) -- rather than re-deriving "where does this product's
    current content live" a second way. This is deliberate: the fan-out's
    idea of "what's current" must never be able to disagree with what
    `cc workspace configure`'s single-project install path already
    considers current.

    RECONNECTED (component-sync fan-out): this function itself still
    resolves ONE root per product -- that root is now what makes it
    reconnected, not a stale artifact of it. For `codex` (no ladder
    concept) that root is materialized verbatim, unchanged. For `claude`,
    `source_roots["claude"]` is consumed as `resolve_claude_content()`'s
    `foundation_root` argument by `build_materialize_project_report()` (the
    function `build_fanout_report()` calls directly for every project) --
    that call site, not this one, is where each tracked `.claude/{commands,
    agents}/<item>.md` path resolves individually through the full tier
    ladder (foundation -> org -> department -> personal), exactly like
    `_claude_plan()`'s single-project install (commit 49d7fee). Freshness
    (`latest_by_product["claude"]`) still folds on the FOUNDATION version
    only -- per-artifact resolution changes WHICH TIER'S COPY of an item
    applies, never what "latest" means for staleness comparison -- so
    fan-out and single-project install can never disagree about which
    tier is current.

    A product whose configured root is unset/unreadable, or whose version
    file can't be read, resolves to `latest = None` / `release_tag = None`
    and is left OUT of `source_roots` -- the honest "unknown" state
    (`compute_freshness()`'s own rule: never fabricate a version), not a
    crash and not a guess.
    """
    from cc.core.ecosystem.workspaces import (
        ActivationError,
        _resolved_framework_root,
        _source_version,
    )

    source_roots: dict[str, str] = {}
    latest_by_product: dict[str, Optional[str]] = {}
    release_tags: dict[str, Optional[str]] = {}

    for product in sorted(PROJECT_SCOPED_PRODUCTS):
        try:
            source = _resolved_framework_root(f"paths.{product}_copilot_root", None)
        except ActivationError:
            latest_by_product[product] = None
            release_tags[product] = None
            continue

        version = _source_version(source, product)
        if version == "unknown":
            latest_by_product[product] = None
            release_tags[product] = None
            continue

        source_roots[product] = str(source)
        latest_by_product[product] = version
        release_tags[product] = f"v{version}"

    return source_roots, latest_by_product, release_tags


def build_fanout_report(
    *,
    _projects: Optional[list[Path]] = None,
    _roots: Any = _UNSET,
    _registry: Any = _UNSET,
    _latest_by_product: Optional[dict[str, Optional[str]]] = None,
    _release_tags: Optional[dict[str, Optional[str]]] = None,
    _source_roots: Optional[dict[str, Any]] = None,
    _excluded_registry: Optional[Path | str] = None,
    triggered_by: str = "manual",
    _personal_roots: Iterable[Path | str] = (),
    _claude_layers: Optional[list[dict[str, Any]]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Build the `materialize.fanout`-style roll-up: for every discovered
    project's `PROJECT_SCOPED_PRODUCTS` components that are stale against
    `_latest_by_product`, attempt a materialize via
    `build_materialize_project_report()` (called DIRECTLY, never through
    `execute_materialize_project()` -- see module docstring on why nested
    lock acquisition is avoided), and aggregate the roll-up counts.

    `triggered_by` is carried through as provenance (`"cadence-sync" |
    "manual" | "release-tag"` per the initiative README) -- purely
    descriptive, no behavior changes on its value.

    Global-once (`GLOBAL_ONCE_PRODUCTS`) components are NOT applied here --
    their single machine-wide apply belongs to `cc update` (already built,
    never touched by this stream); this fan-out is scoped to the owner's
    stated pain point (`PROJECT_SCOPED_PRODUCTS` propagating across every
    embedding project), matching `build_all_projects_freshness()`'s own
    per-project/global split.

    `summary.failed` folds in BOTH `blocked` and `offline` per-(project,
    component) outcomes (a fan-out-level roll-up has no separate slot for
    "unreachable mirror" vs. "policy-blocked" -- both mean "did not apply,
    and it's not because the user's WIP is in the way") -- but each
    `results[]` entry still carries its own honest `result` value
    (`"offline"` is never misreported as `"blocked"` or vice versa at the
    per-item level, only at the aggregate count level).

    OBSERVABILITY (task-fanout-total-zero fix): every (project, component)
    pair this sweep looks at lands in `results[]` with a reason -- none is
    ever a bare `continue` that drops it from the count. Two skip reasons
    that used to vanish silently now show up explicitly:
      - the project is on the machine-local excluded-projects registry
        (`_excluded_registry`, defaulting to NONE here -- see below) --
        `result: "excluded"`, not counted in `updated`/`held`/`up_to_date`/
        `failed` (an owner decision to leave a project alone is not a
        failure and must never make a routine run look broken), tallied in
        its own `summary.excluded` instead.
      - `_latest_by_product` has no known version for this product (e.g.
        its source root could not be resolved/read -- see
        `resolve_fanout_sources()`) -- `result: "blocked"`, `reason`
        explains why, folded into `summary.failed` like every other
        did-not-apply outcome. A fan-out that returns `total: 0` while
        finding nothing reads as "nothing to do"; an honest, reasoned skip
        is the whole point of this sweep existing.

    `_excluded_registry` defaults to `None` (no exclusion check at all) --
    deliberately NOT `default_excluded_registry()` here, so this function
    never touches the real machine's `~/.copilot/excluded-projects.json`
    unless a caller (the real one: `cc/main.py`'s `--fanout` wiring)
    explicitly supplies it. Same posture as `_roots`/`_registry` above:
    `build_*` functions stay inert by default, `execute_fanout()`'s real
    caller is the one production wiring point.

    Fail-open per project AND per component: an unreadable project
    manifest, or an unexpected error materializing one component, is
    recorded as a `failed` result and never aborts the rest of the sweep.

    `_claude_layers` is test-only, forwarded verbatim to every
    `build_materialize_project_report()` call this sweep makes (its own
    `resolve_claude_content()` `_layers` override) -- `None` (the default,
    and production's only value) means every project's `claude` files
    resolve through the REAL configured tier ladder, identically to how
    single-project install already does.

    CONTENT-LEVEL STALENESS WIDENING (mechanism defect fix, 2026-08): a
    version-string match against `_latest_by_product` alone used to mean
    "up to date" -- but org/department/personal tier content can change
    without ever bumping the FOUNDATION's version, which is the only
    thing `_latest_by_product["claude"]` tracks (`resolve_fanout_sources()`
    's own note). That left a live, provable gap: adding real content at
    the organization tier was invisible to every already-on-latest-
    version project forever, because `build_materialize_project_report()`
    was never even CALLED for them. This function now resolves the
    `claude` product's FULL nearest-substantive-tier winner set and hashes
    every winning file EXACTLY ONCE per sweep (`resolve_all_claude_items()`
    / `claude_resolution_checksums()`, `project_sources.py`) -- project-
    independent by construction, so every one of the ~66 fleet projects
    below reuses the identical map: a `claude` component whose version
    matches `latest` is STILL attempted if any of its ladder-eligible
    tracked paths' recorded checksum no longer matches what the ladder
    would resolve today, at the cost of one dict lookup per tracked path,
    never a second discovery/hash pass. A genuine foundation version bump
    still triggers an update exactly as before -- this only widens what
    ELSE also counts as stale, it does not replace the version check.
    """
    latest_by_product = _latest_by_product or {}
    release_tags = _release_tags or {}
    source_roots = _source_roots or {}

    # Computed ONCE for the whole sweep -- see the docstring section above.
    # Degrades to `{}` (no manifest configured, or nothing to resolve) with
    # zero extra cost; every per-project content check below is then a
    # guaranteed no-op fast-path (`_claude_content_stale()`'s own `if not
    # checksum_by_key: return False`).
    claude_resolution = resolve_all_claude_items(_layers=_claude_layers)
    claude_checksums = claude_resolution_checksums(claude_resolution)

    if _projects is not None:
        projects = _projects
    else:
        discover_kwargs: dict[str, Any] = {}
        if _roots is not _UNSET:
            discover_kwargs["roots"] = _roots
        if _registry is not _UNSET:
            discover_kwargs["_registry"] = _registry
        projects = discover_projects(**discover_kwargs)

    results: list[dict[str, Any]] = []
    updated = held = up_to_date = failed = excluded = 0

    for project in projects:
        if _excluded_registry is not None:
            from cc.core.ecosystem.workspaces import is_project_excluded

            if is_project_excluded(project, registry=_excluded_registry):
                excluded += 1
                results.append(
                    {
                        "path": str(project),
                        "component": None,
                        "result": "excluded",
                        "reason": (
                            "excluded from fan-out (cc workspace revert / owner "
                            "decision) -- stays on disk, never synced"
                        ),
                    }
                )
                continue

        try:
            manifest = read_project_lock(Path(project) / PROJECT_LOCK_FILENAME)
        except Exception:
            failed += 1
            results.append(
                {
                    "path": str(project),
                    "component": None,
                    "result": "blocked",
                    "reason": "could not read project lock manifest",
                }
            )
            continue

        raw_components = manifest.get("components", []) if isinstance(manifest, dict) else []
        for entry in raw_components if isinstance(raw_components, list) else []:
            if not isinstance(entry, dict):
                continue
            product = entry.get("component")
            if not isinstance(product, str) or product not in PROJECT_SCOPED_PRODUCTS:
                continue

            current = entry.get("version")
            target = latest_by_product.get(product)
            folded = compute_freshness(current, target)
            version_stale = folded["stale"]

            # CONTENT-LEVEL STALENESS WIDENING (function docstring): a
            # version MATCH alone is no longer proof this project has
            # nothing pending for `claude` -- `claude_checksums` was
            # resolved once for the whole sweep above, so this costs zero
            # additional I/O here.
            content_stale = (
                version_stale is False
                and product == "claude"
                and _claude_content_stale(entry, checksum_by_key=claude_checksums)
            )

            if not version_stale and not content_stale:
                if version_stale is False:
                    up_to_date += 1
                    results.append(
                        {"path": str(project), "component": product, "result": "up-to-date"}
                    )
                else:
                    # stale is None (unknown latest) -- WHY this pair was
                    # skipped is now always visible, never a silent vanish
                    # from `results`/`total` (module docstring's
                    # OBSERVABILITY note). Folded into `failed` like every
                    # other did-not-apply outcome, since it genuinely
                    # neither applied nor held.
                    failed += 1
                    results.append(
                        {
                            "path": str(project),
                            "component": product,
                            "result": "blocked",
                            "reason": (
                                f"latest version for {product!r} is unknown "
                                "(no source root resolved) -- nothing to fan out yet"
                            ),
                        }
                    )
                continue

            try:
                report = build_materialize_project_report(
                    project,
                    component=product,
                    target_version=target,
                    release_tag=release_tags.get(product),
                    source_root=source_roots.get(product, _UNSET),
                    _manifest=manifest,
                    _personal_roots=_personal_roots,
                    _claude_layers=_claude_layers,
                    _claude_resolution_cache=claude_resolution,
                    _claude_checksum_cache=claude_checksums,
                    dry_run=dry_run,
                )
            except Exception as exc:
                failed += 1
                results.append(
                    {
                        "path": str(project),
                        "component": product,
                        "result": "blocked",
                        "reason": str(exc),
                    }
                )
                continue

            result = report.get("result")
            results.append({"path": str(project), "component": product, "report": report})

            if result == "applied":
                updated += 1
            elif result == "held":
                held += 1
            elif result == "up-to-date":
                up_to_date += 1
            else:  # "blocked" | "offline"
                failed += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "triggered_by": triggered_by,
        "summary": {
            "updated": updated,
            "held": held,
            "up_to_date": up_to_date,
            "failed": failed,
            "excluded": excluded,
            "total": len(results),
        },
        "results": results,
    }


def execute_fanout(
    *,
    _lock_path: Any = _UNSET,
    **build_kwargs: Any,
) -> tuple[dict[str, Any], int]:
    """
    CLI-facing wrapper: acquire `copilot_lock()` ONCE for the whole
    fan-out sweep, then build the roll-up. Exit code: `0` if every
    (project, component) pair is `applied`/`up-to-date`; `1` if any is
    `held`/`blocked`/`offline` (summary.held or summary.failed > 0); `2`
    on lock contention (`error.code = "lock-contention"`, mirrors every
    other mutating verb in this codebase).
    """
    target_lock_path = _lock_path if _lock_path is not _UNSET else lock_path()

    try:
        with copilot_lock(path=target_lock_path):
            report = build_fanout_report(**build_kwargs)
    except LockContentionError as exc:
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "error": {"code": "lock-contention", "message": str(exc)},
            },
            2,
        )

    summary = report["summary"]
    exit_code = 1 if (summary["held"] > 0 or summary["failed"] > 0) else 0
    return report, exit_code


def render_fanout_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_fanout_report()` payload."""
    from rich.console import Console

    con = console or Console()
    summary = report.get("summary", {})
    con.print(
        f"[bold]fan-out[/bold]: updated={summary.get('updated', 0)} "
        f"held={summary.get('held', 0)} up-to-date={summary.get('up_to_date', 0)} "
        f"failed={summary.get('failed', 0)} excluded={summary.get('excluded', 0)} "
        f"(of {summary.get('total', 0)})"
    )
    for r in report.get("results", []):
        sub_report = r.get("report", {})
        result = sub_report.get("result", r.get("result", "unknown"))
        color = {
            "applied": "green",
            "up-to-date": "green",
            "held": "yellow",
            "excluded": "dim",
        }.get(result, "red")
        # `reason` lives at the top level for a fan-out-level skip (excluded,
        # unknown-latest, unreadable manifest) or nested inside the first
        # held/blocked entry for a real per-project materialize attempt --
        # either way, WHY is always surfaced here, never just the verdict.
        reason = r.get("reason")
        if reason is None:
            nested = sub_report.get("held_for_approval") or sub_report.get("blocked") or []
            if nested and isinstance(nested[0], dict):
                reason = nested[0].get("reason")
        suffix = f" -- {reason}" if reason and result not in ("applied", "up-to-date") else ""
        con.print(f"  [{color}]{result}[/{color}] {r.get('path')} ({r.get('component')}){suffix}")
