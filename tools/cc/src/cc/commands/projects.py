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
"""

from __future__ import annotations

import hashlib
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from cc.commands.update import compute_exit_code
from cc.core.ecosystem.freshness import compute_freshness, lock_fingerprint
from cc.core.ecosystem.materialize import guard_personal
from cc.core.ecosystem.projects import (
    GLOBAL_ONCE_PRODUCTS,
    PROJECT_LOCK_FILENAME,
    PROJECT_SCOPED_PRODUCTS,
    discover_projects,
    framework_owned_paths,
    project_freshness,
    read_project_lock,
    write_project_lock,
)
from cc.core.locking import LockContentionError, copilot_lock, lock_path

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
      - `component` not embedded in this project's manifest, or already at
        `target_version`, or has no framework-owned files at all ->
        `up-to-date`, zero writes.
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
        Project-owned files are never read, hashed, or written.

    `lock_before`/`lock_after` reuse `core/ecosystem/freshness.py`'s
    `lock_fingerprint()` (the same canonical-JSON git-blob-sha1 scheme
    `cc update --json` already uses) applied to this project's OWN
    manifest dict -- so the fields satisfy update.schema.json's `git_sha`
    pattern without inventing a second fingerprint scheme.

    Does NOT acquire `copilot_lock()` -- see module docstring (that is
    `execute_materialize_project()`'s job, and `build_fanout_report()`
    calls this function directly for the same reason).
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

    if current_version == resolved_target:
        return _report(result="up-to-date")

    if not release_tag:
        return _report(
            result="blocked",
            blocked=[{"dimension": component, "reason": "unverified"}],
        )

    rel_paths = framework_owned_paths(entry)
    if not rel_paths:
        return _report(result="up-to-date")

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

    missing = [rel_path for rel_path in rel_paths if not (source_base / rel_path).is_file()]
    if missing:
        return _report(
            result="blocked",
            blocked=[
                {"dimension": component, "item": rel_path, "reason": "source content not found"}
                for rel_path in missing
            ],
        )

    changed: list[dict[str, Any]] = []
    files_by_path = {
        f.get("path"): f
        for f in entry.get("files", []) or []
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    }

    for rel_path in rel_paths:
        src = source_base / rel_path
        dest = project / rel_path
        src_bytes = src.read_bytes()
        to_sha = _sha256_hex(src_bytes)

        existed = dest.is_file()
        from_sha = _sha256_hex(dest.read_bytes()) if existed else None
        content_matches = existed and dest.read_bytes() == src_bytes

        if not content_matches and not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src_bytes)

        op = "unchanged" if content_matches else ("updated" if existed else "added")
        changed.append(
            {
                "dimension": component,
                "layer": component,
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


def build_fanout_report(
    *,
    _projects: Optional[list[Path]] = None,
    _roots: Any = _UNSET,
    _registry: Any = _UNSET,
    _latest_by_product: Optional[dict[str, Optional[str]]] = None,
    _release_tags: Optional[dict[str, Optional[str]]] = None,
    _source_roots: Optional[dict[str, Any]] = None,
    triggered_by: str = "manual",
    _personal_roots: Iterable[Path | str] = (),
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

    Fail-open per project AND per component: an unreadable project
    manifest, or an unexpected error materializing one component, is
    recorded as a `failed` result and never aborts the rest of the sweep.
    """
    latest_by_product = _latest_by_product or {}
    release_tags = _release_tags or {}
    source_roots = _source_roots or {}

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
    updated = held = up_to_date = failed = 0

    for project in projects:
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

            if not folded["stale"]:
                if folded["stale"] is False:
                    up_to_date += 1
                    results.append(
                        {"path": str(project), "component": product, "result": "up-to-date"}
                    )
                # stale is None (unknown latest) -- honestly nothing to fan
                # out yet; not counted at all (never guessed as up-to-date).
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
        f"failed={summary.get('failed', 0)} (of {summary.get('total', 0)})"
    )
    for r in report.get("results", []):
        result = r.get("report", {}).get("result", r.get("result", "unknown"))
        color = {"applied": "green", "up-to-date": "green", "held": "yellow"}.get(result, "red")
        con.print(f"  [{color}]{result}[/{color}] {r.get('path')} ({r.get('component')})")
