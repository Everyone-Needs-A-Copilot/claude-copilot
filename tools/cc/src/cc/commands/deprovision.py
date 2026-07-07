"""`cc deprovision --json` -- the WS-A ecosystem wipe (MUTATING).

WS-A slice 5 (deprovision-slice). Graduates `deprovision` out of
`commands/lifecycle.py`'s lock-acquiring stub (`repair` remains
engine-blocked there). See:
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/01-architecture/schemas/deprovision.schema.json
  - copilot-control-tower/docs/reference/ecosystem-architecture.md §5.2
  - tools/cc/tests/fixtures/schemas/ (vendored copy used by the contract test)

Unlike `doctor`/`resolve --explain`/`freshness` (read-only) and like
`update` (materializes/deletes), `deprovision` DELETES files: it acquires
the advisory `copilot_lock()` mutex (core/locking.py) for the whole
operation (cli-contract.md: "a global per-host mutex across all verbs so
`deprovision` drains pending syncs before wiping"), then runs
core/ecosystem/deprovision.py's `deprovision()` engine -- the same
never-destroy (`guard_personal()`), three-tree-model guarded wipe that
backs this module's report.

SAFETY: every I/O root (materialize root, mirror root, lockfile read path,
the advisory lock path itself) is injectable via this module's
`_..._path`/`_..._root` keyword arguments -- see `build_deprovision_report()`/
`execute_deprovision()`. Real production defaults only ever resolve
through `resolve_key()`'s normal config cascade / `default_lockfile_path()`
(never a bare `Path.home()` call in this module); tests MUST inject every
root (see tests/test_deprovision_contract.py) so nothing here is ever
exercised against a real machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from cc.core.config import resolve_key
from cc.core.ecosystem.deprovision import deprovision
from cc.core.ecosystem.lockfile import default_lockfile_path, read_lockfile
from cc.core.locking import LockContentionError, copilot_lock, lock_path

SCHEMA_VERSION = "1.0"

# Sentinel distinguishing "no override passed" from an explicit None argument.
_UNSET: Any = object()


def build_deprovision_report(
    *,
    _previous_lock: Optional[dict[str, Any]] = None,
    _lockfile_path: Any = _UNSET,
    _mirror_root: Any = _UNSET,
    _materialize_root: Any = _UNSET,
    _mode: str = "soft",
    _personal_roots: Iterable[Any] = (),
    _dry_run: bool = False,
) -> dict[str, Any]:
    """
    Build the WS-A `deprovision --json` contract object AND (unless
    `_dry_run=True`) perform the wipe it describes: read the previous
    lockfile, then `core/ecosystem/deprovision.py`'s `deprovision()`
    engine wipes materialized content + mirror clones, retaining any
    personal/dirty path it guards.

    Every root is injectable (see module docstring) -- callers/tests MUST
    supply `_mirror_root`/`_materialize_root`/`_lockfile_path` (or
    `_previous_lock` directly) to keep this entirely inside a tmp sandbox.
    `_dry_run=True` computes the exact plan/counts WITHOUT touching disk.

    Does NOT acquire `copilot_lock()` itself -- that is
    `execute_deprovision()`'s job (the CLI-facing wrapper), so this stays a
    plain, independently-testable build step, same as `build_update_report()`.
    """
    if _previous_lock is not None:
        previous_lock = _previous_lock
    else:
        lockfile_path = (
            _lockfile_path if _lockfile_path is not _UNSET else default_lockfile_path()
        )
        previous_lock = read_lockfile(lockfile_path)

    mirror_root = (
        Path(_mirror_root).expanduser()
        if _mirror_root is not _UNSET
        else Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    )
    materialize_root = (
        Path(_materialize_root).expanduser()
        if _materialize_root is not _UNSET
        else Path(str(resolve_key("paths.materialize_root"))).expanduser()
    )

    engine_report = deprovision(
        materialize_root=materialize_root,
        mirror_root=mirror_root,
        previous_lock=previous_lock,
        mode=_mode,
        personal_roots=_personal_roots,
        dry_run=_dry_run,
    )

    removed_materialized = engine_report["removed_materialized"]
    removed_clones = engine_report["removed_clones"]
    retained_dirty = engine_report["retained_dirty"]

    # Overall result precedence: partial (a wipe was attempted and failed)
    # > noop (nothing at all was found to remove) > wiped (everything
    # findable was either removed/quarantined, or intentionally retained
    # as protected -- retained_dirty is an expected, always-reported
    # field, not a failure).
    if engine_report["partial"]:
        result = "partial"
    elif removed_materialized == 0 and not removed_clones and not retained_dirty:
        result = "noop"
    else:
        result = "wiped"

    return {
        "schema_version": SCHEMA_VERSION,
        "result": result,
        "removed": {
            "materialized": removed_materialized,
            "clones": removed_clones,
        },
        "retained_dirty": retained_dirty,
        "secrets_touched": engine_report["secrets_touched"],
    }


def compute_exit_code(report: dict[str, Any]) -> int:
    """
    Map a `build_deprovision_report()` payload to the deprovision contract's
    exit code (cli-contract.md doesn't spell this out per-verb the way it
    does for `doctor`/`publish`; this mirrors `doctor`'s "0 clean / 1 any
    fail / 2 env error" precedent, the closest existing analog):
      0 = wiped | noop  (clean success, nothing outstanding)
      1 = partial       (something couldn't be removed -- needs attention)
      2 = reserved for environment/unexpected errors (raised by the CLI
          handler when `build_deprovision_report()`/`execute_deprovision()`
          itself throws, or on lock contention -- never returned from here).
    """
    result = report.get("result")
    if result == "partial":
        return 1
    return 0


def execute_deprovision(
    *,
    dry_run: bool = False,
    _lock_path: Any = _UNSET,
    **build_kwargs: Any,
) -> tuple[dict[str, Any], int]:
    """
    CLI-facing wrapper: acquire `copilot_lock()`, then build (and, unless
    `dry_run`, apply) the deprovision report. Returns `(report, exit_code)`.

    `_lock_path` is injectable so tests can point the mutex at a tmp file
    (and simulate contention by holding it open concurrently) without ever
    touching the real `~/.claude/memory/copilot.lock`.
    """
    target_lock_path = _lock_path if _lock_path is not _UNSET else lock_path()

    try:
        with copilot_lock(path=target_lock_path):
            report = build_deprovision_report(_dry_run=dry_run, **build_kwargs)
    except LockContentionError as exc:
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "error": {"code": "lock-contention", "message": str(exc)},
            },
            2,
        )

    return report, compute_exit_code(report)


def render_deprovision_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_deprovision_report()` payload."""
    from rich.console import Console

    con = console or Console()

    if "error" in report:
        con.print(f"[red]deprovision: {report['error'].get('message')}[/red]")
        return

    result = report.get("result", "unknown")
    color = {"wiped": "green", "noop": "green", "partial": "yellow"}.get(result, "red")
    con.print(f"[bold {color}]deprovision: {result}[/bold {color}]")

    removed = report.get("removed", {})
    con.print(f"  materialized removed: {removed.get('materialized', 0)}")
    for clone in removed.get("clones", []):
        con.print(f"  [yellow]mirror removed/quarantined:[/yellow] {clone}")
    for path in report.get("retained_dirty", []):
        con.print(f"  [cyan]retained (protected):[/cyan] {path}")
    con.print(f"  secrets_touched: {report.get('secrets_touched', 0)}")
