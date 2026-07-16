"""`cc freshness --json` -- the WS-A cheap-poll freshness contract.

Separated from main.py's dispatch so it can be tested in isolation, the
same way doctor.py/resolve.py separate from their commands (see those
modules' docstrings for the precedent).

Contract sources:
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/01-architecture/schemas/freshness.schema.json
  - tools/cc/tests/fixtures/schemas/ (vendored copies used by the contract
    test)

READ-ONLY: this module never acquires the copilot lock (core/locking.py)
and never materializes/writes/clones anything. It only reads (in order):
the local lockfile (core/ecosystem/lockfile.py, via
core/ecosystem/freshness.py's current_lock_sha()) and a tier's published
lock-pointer ref (core/ecosystem/mirror.py's latest_lock_sha(), a single
cheap `git ls-remote` -- never a full `update`).

SCHEMA DIVERGENCE (flagged, not silently patched -- see this repo's own
schemas/README.md "sync rule": "the schema encodes the most defensible
interpretation and carries a $comment flagging the assumption for the
owner to tighten"). The freshness.schema.json this slice was handed
required `current_lock_sha` / `latest_lock_sha` / `stale` as non-nullable,
with `additionalProperties: false` -- a shape with no way to encode
"couldn't check" (only "fresh" or "stale"), which directly conflicts with
the honesty rule (a schema-valid instance would be forced to fabricate a
SHA or a stale verdict when offline / before any lock exists). This slice
amends the schema (both the copilot-control-tower source of truth and the
vendored test fixture) the same way doctor.schema.json was already
corrected once: `current_lock_sha` / `latest_lock_sha` / `stale` become
nullable (`null` = unknown, never "no"/"fresh"), and a required `offline`
boolean is added, mirroring doctor.schema.json's existing `offline`
field. Confirm with the CLI/schema owner at the next contract freeze.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from cc.core.config import resolve_key
from cc.core.ecosystem import mirror
from cc.core.ecosystem.freshness import (
    build_per_layer_freshness,
    compute_freshness,
    current_lock_sha,
)

SCHEMA_VERSION = "1.0"

# Sentinel distinguishing "no override passed" from an explicit None argument.
_UNSET: Any = object()


def build_freshness_report(
    *,
    _source: Any = _UNSET,
    _ref: Any = _UNSET,
    _lockfile: Optional[dict[str, Any]] = None,
    _lockfile_path: Any = _UNSET,
    _latest_sha: Any = _UNSET,
    per_layer: bool = False,
    _layers: Optional[list[dict[str, Any]]] = None,
    _manifest_path: Any = _UNSET,
    _mirror_root: Any = _UNSET,
    _layer_latest_lookup: Optional[dict[str, Optional[str]]] = None,
) -> dict[str, Any]:
    """
    Build the WS-A `freshness --json` contract object.

    `_source`/`_ref`: the tier source repo URL + published lock-pointer ref
    to poll (see core/ecosystem/mirror.py). Default to the resolved
    `layers.lock_source` / `layers.lock_ref` config keys when not injected
    (mirrors `cc resolve --explain`'s `resolve_key("layers.manifest")`
    default in commands/resolve.py). No `layers.lock_source` configured is
    an honest "nothing to check yet" -- both SHAs null, `stale` null,
    `offline` false (no network call was even attempted).

    `_latest_sha` lets tests/callers inject the remote result directly
    (mirrors `_lockfile`'s injection) instead of invoking `git ls-remote`.

    `per_layer` (default `False`, OPT-IN): when `True`, additionally folds
    in a `layers: [...]` array (core/ecosystem/freshness.py's
    `build_per_layer_freshness()`) alongside the existing top-level fields
    -- purely additive, the top-level fields are computed identically
    either way. The CLI's own `freshness_cmd()` (cc/main.py) calls this
    function with NO arguments, so it never hits `per_layer=True` --
    wiring an actual `--per-layer` flag is a later integration step (this
    slice only adds the internal capability). `_layers`/`_manifest_path`
    mirror `commands/update.py`'s own manifest-loading convention (pass
    layers directly, or a manifest path resolved via `layers.manifest`);
    `_mirror_root` mirrors every other injectable root in this codebase;
    `_layer_latest_lookup` forwards straight to
    `build_per_layer_freshness()`'s own `_latest_lookup` injection point.
    """
    source = resolve_key("layers.lock_source") if _source is _UNSET else _source
    ref = (
        (resolve_key("layers.lock_ref") or mirror.DEFAULT_LOCK_POINTER_REF)
        if _ref is _UNSET
        else _ref
    )

    # Forward lockfile overrides only when actually supplied -- `_UNSET`
    # here is THIS module's sentinel, a different object identity than
    # core/ecosystem/freshness.py's own `_UNSET`, so it must never be
    # passed through as a literal value (it would blow up read_lockfile()
    # trying to Path() a sentinel object instead of falling back to that
    # function's own default).
    lockfile_kwargs: dict[str, Any] = {}
    if _lockfile is not None:
        lockfile_kwargs["_lockfile"] = _lockfile
    if _lockfile_path is not _UNSET:
        lockfile_kwargs["_lockfile_path"] = _lockfile_path
    current = current_lock_sha(**lockfile_kwargs)

    if _latest_sha is not _UNSET:
        latest = _latest_sha
    elif not source:
        latest = None
    else:
        latest = mirror.latest_lock_sha(source, ref)

    # `offline` is true only when a remote check was actually attempted
    # (a source was configured) and it came back unknown -- distinct from
    # "nothing configured yet", which also yields latest=None but is not
    # itself an offline condition.
    offline = bool(source) and latest is None

    freshness = compute_freshness(current, latest)

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "current_lock_sha": freshness["current_lock_sha"],
        "latest_lock_sha": freshness["latest_lock_sha"],
        "stale": freshness["stale"],
        "offline": offline,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if per_layer:
        if _layers is not None:
            layers = _layers
        else:
            manifest_path = (
                _manifest_path if _manifest_path is not _UNSET else resolve_key("layers.manifest")
            )
            if not manifest_path:
                layers = []
            else:
                from cc.core.ecosystem.manifest import load_layers

                layers = load_layers(manifest_path)

        mirror_root_base = (
            _mirror_root if _mirror_root is not _UNSET else resolve_key("paths.mirrors_root")
        )
        report["layers"] = build_per_layer_freshness(
            layers,
            _mirror_root=mirror_root_base,
            _latest_lookup=_layer_latest_lookup,
        )

    return report


def render_freshness_report_rich(report: dict, *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a build_freshness_report() payload."""
    from rich.console import Console

    con = console or Console()
    stale = report.get("stale")
    current = report.get("current_lock_sha")
    latest = report.get("latest_lock_sha")

    if report.get("offline"):
        con.print(
            f"[yellow]freshness: offline[/yellow] -- could not reach the tier's "
            f"published lock-pointer ref. (local lock: {current or 'none'})"
        )
    elif stale is None:
        con.print(
            "[dim]freshness: unknown -- no local lock and/or no tier source "
            "configured yet (layers.lock_source).[/dim]"
        )
    elif stale:
        con.print(
            f"[yellow]freshness: STALE[/yellow]  current={current}  latest={latest}"
        )
    else:
        con.print(f"[green]freshness: up to date[/green]  ({current})")
