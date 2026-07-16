"""`cc layers [join] --json` -- entitlement discovery + join (WS-A Stream-C,
D7.1, proposed contract addition -- not yet in upstream WS-A scope).

See:
  - copilot-control-tower/docs/01-architecture/cli-contract.md ("copilot
    layers [join] --json (proposed contract addition, D7.1)")
  - copilot-control-tower/docs/01-architecture/schemas/layers.schema.json
  - tools/cc/tests/fixtures/schemas/ (vendored copy used by the contract test)

`cc layers --json` (also the bare `cc layers --json` default, no
subcommand) is READ-ONLY: it enumerates every department/org layer the
current account context could plausibly join (the catalog --
`core/ecosystem/ecosystem_config.departments()`, the org's inherited
`ecosystem.yml`) and reports, per layer, whether the current identity is
**entitled** (GitHub repo access, D3 -- computed CLI-side via
`core/ecosystem/entitlement.py`, never by Control Tower) and whether it is
already **joined** (present in the local layer manifest,
`core/ecosystem/manifest.py`'s `copilot.layers.yml`).

`cc layers join <id> --json` is MUTATING, the same class of operation as
`cc update` (cc/commands/update.py): it acquires the advisory
`copilot_lock()` mutex, syncs the layer's read-only mirror
(`core/ecosystem/mirror.py`'s `clone_or_update_mirror()`), extends the
local manifest with the new layer entry, then reuses `cc update`'s own
`build_update_report()` (cc/commands/update.py) -- unmodified, imported --
to materialize that one layer through the identical mirror-sync -> resolve
-> policy-gate -> materialize -> lock-write pipeline `cc update` uses for
every already-joined layer. This module adds NO parallel materialize
logic of its own.

SAFETY: every I/O root (identity root, manifest path, mirror root,
materialize root, lockfile path, the advisory lock path itself) is
injectable via this module's `_..._path`/`_..._root` keyword arguments --
see `build_layers_report()` / `build_layers_join_report()` /
`execute_layers_join()`. Real production defaults only ever resolve
through `resolve_key()`'s normal config cascade or another already-
established module's own default (`authstore.auth_root()`,
`ecosystem_config.ecosystem_config_path()`, ...) -- never a bare
`Path.home()` call introduced in THIS module; tests MUST inject every root
(see tests/test_layers_contract.py) so nothing here is ever exercised
against a real machine or a real network.
"""

from __future__ import annotations

import json as _json
import socket
from pathlib import Path
from typing import Any, Optional

import typer
import yaml

from cc.core import authstore, keychain
from cc.core.config import resolve_key
from cc.core.ecosystem import entitlement, mirror
from cc.core.ecosystem.ecosystem_config import departments as _departments_from_cfg
from cc.core.ecosystem.ecosystem_config import (
    ecosystem_config_path,
    load_ecosystem_config,
)
from cc.core.ecosystem.lockfile import default_lockfile_path, read_lockfile
from cc.core.ecosystem.manifest import ManifestError, load_layers
from cc.core.locking import LockContentionError, copilot_lock, lock_path

SCHEMA_VERSION = "1.0"

# The macOS Keychain service the GitHub device-flow token is stored under
# (core/keychain.py). Mirrors tests/test_keychain.py's own `SERVICE`
# constant -- there is no `commands/auth.py` yet (a different, not-yet-
# built WS-A stream) to import this from, so it is declared here as the
# single source of truth this module needs until that module exists.
GITHUB_KEYCHAIN_SERVICE = "com.everyoneneedsacopilot.copilot.github"

# Sentinel distinguishing "no override passed" from an explicit None argument
# (mirrors commands/update.py's `_UNSET` convention).
_UNSET: Any = object()


class NoIdentityError(RuntimeError):
    """Raised by `build_layers_join_report()` when no GitHub identity is
    resolvable at all (signed out, or signed in with no stored token) --
    cli-contract.md D7.1: "2 = env/credential error (e.g. no GitHub
    identity resolvable at all)". Mapped to the `{schema_version, error}`
    envelope + exit 2 by `execute_layers_join()`, the same pattern
    `commands/update.py`'s `execute_update()` uses for
    `LockContentionError` / `ManifestError`.
    """


# ---------------------------------------------------------------------------
# Shared helpers (list + join)
# ---------------------------------------------------------------------------


def _resolve_identity(
    *,
    _identity: Optional[dict[str, Any]],
    _identity_root: Any,
) -> dict[str, Any]:
    if _identity is not None:
        return _identity
    root = None if _identity_root is _UNSET else _identity_root
    return authstore.read_identity(_root=root)


def _resolve_token(
    login: Optional[str],
    *,
    _get_secret: Any,
) -> Optional[str]:
    if not login:
        return None
    return _get_secret(login, service=GITHUB_KEYCHAIN_SERVICE)


def _catalog(
    *,
    _departments: Optional[list[dict[str, Any]]],
    _ecosystem_cfg: Optional[dict[str, Any]],
    _ecosystem_cfg_path: Any,
) -> list[dict[str, Any]]:
    """
    Resolve the department/org layer catalog -- the org's inherited
    `ecosystem.yml` (`core/ecosystem/ecosystem_config.py`). Every entry
    this module ever emits is tier `"department"` -- `departments()` is
    the only catalog source this proposed contract wires up today (an
    `"org"` tier entry has no producer yet); the `tier` enum still admits
    `"org"` for whenever that catalog source exists.

    Fail-open: a missing/malformed `ecosystem.yml` degrades to `[]` (never
    raises) -- `ecosystem_config.py`'s own read-only fail-open contract,
    unchanged here.
    """
    if _departments is not None:
        return _departments
    if _ecosystem_cfg is not None:
        return _departments_from_cfg(_ecosystem_cfg)

    path = (
        _ecosystem_cfg_path
        if _ecosystem_cfg_path is not _UNSET
        else ecosystem_config_path()
    )
    cfg = load_ecosystem_config(path)
    return _departments_from_cfg(cfg)


def _find_layer(
    catalog: list[dict[str, Any]], layer_id: str
) -> Optional[dict[str, Any]]:
    for entry in catalog:
        if entry.get("id") == layer_id:
            return entry
    return None


def _local_layers(
    *,
    _layers: Optional[list[dict[str, Any]]],
    _manifest_path: Any,
    swallow_errors: bool,
) -> list[dict[str, Any]]:
    """
    The local join state: layers already present in `copilot.layers.yml`
    (`layers.manifest` config key). `swallow_errors=True` (the `list`
    report's posture) degrades a missing/malformed manifest to `[]` --
    "never crash on missing config, an empty catalog is a valid report".
    `swallow_errors=False` (the `join` report's posture) instead lets
    `ManifestError` propagate, mirroring `commands/update.py`'s
    `execute_update()`: a genuinely broken manifest is an honest error,
    not silently ignored right before this module is about to WRITE to
    that same file.
    """
    if _layers is not None:
        return _layers

    manifest_path = (
        _manifest_path if _manifest_path is not _UNSET else resolve_key("layers.manifest")
    )
    if not manifest_path:
        return []

    resolved_path = Path(manifest_path).expanduser()
    if not resolved_path.exists():
        # No manifest on disk yet -- "nothing joined so far" is a valid,
        # non-error state for BOTH list and join (unlike `cc update`, where
        # a configured-but-missing manifest is a real misconfiguration
        # worth flagging via ManifestError): the very first `layers join`
        # on a fresh machine is what CREATES this file.
        return []

    if swallow_errors:
        try:
            return load_layers(resolved_path)
        except ManifestError:
            return []
    return load_layers(resolved_path)


def _entitlement_for(
    repo: Optional[str],
    *,
    login: Optional[str],
    token: Optional[str],
    _get_json: entitlement.GetJsonFn,
) -> tuple[Optional[bool], Optional[str]]:
    """Returns `(entitled, reason)` -- `reason` is `None` when `entitled`
    is a definite `True`/`False` (no explanation needed)."""
    if not login or not token:
        return None, "signed-out"
    if not repo:
        return None, "offline"
    result = entitlement.repo_accessible(repo, token, get_json=_get_json)
    if result is None:
        return None, "offline"
    return result, None


# ---------------------------------------------------------------------------
# `cc layers --json` (list) -- read-only
# ---------------------------------------------------------------------------


def build_layers_report(
    *,
    _identity: Optional[dict[str, Any]] = None,
    _identity_root: Any = _UNSET,
    _get_secret: Any = keychain.get_secret,
    _departments: Optional[list[dict[str, Any]]] = None,
    _ecosystem_cfg: Optional[dict[str, Any]] = None,
    _ecosystem_cfg_path: Any = _UNSET,
    _layers: Optional[list[dict[str, Any]]] = None,
    _manifest_path: Any = _UNSET,
    _get_json: entitlement.GetJsonFn = entitlement.default_get_json,
) -> dict[str, Any]:
    """
    Build the WS-A `layers --json` contract object (read-only -- never
    takes `copilot_lock()`, never writes anything).

    Never crashes on missing config: a signed-out identity, an absent
    `ecosystem.yml`, or an absent/malformed local manifest all degrade to
    an honest, still-valid report (empty catalog / all-null-entitled /
    nothing-joined) rather than raising.
    """
    identity = _resolve_identity(_identity=_identity, _identity_root=_identity_root)
    login = identity.get("login") if isinstance(identity.get("login"), str) else None
    token = _resolve_token(login, _get_secret=_get_secret)

    catalog = _catalog(
        _departments=_departments,
        _ecosystem_cfg=_ecosystem_cfg,
        _ecosystem_cfg_path=_ecosystem_cfg_path,
    )
    local_layers = _local_layers(
        _layers=_layers, _manifest_path=_manifest_path, swallow_errors=True
    )
    joined_ids = {
        str(layer["id"]) for layer in local_layers if layer.get("id")
    }

    layers_out: list[dict[str, Any]] = []
    for dept in catalog:
        layer_id = dept.get("id")
        repo = dept.get("repo")
        if not layer_id or not repo:
            # Malformed catalog entry -- skip rather than crash (mirrors
            # ecosystem_config.py's own fail-open posture for the file
            # this data came from).
            continue

        entitled, reason = _entitlement_for(
            repo, login=login, token=token, _get_json=_get_json
        )

        entry: dict[str, Any] = {
            "tier": "department",
            "id": str(layer_id),
            "name": str(dept.get("name") or layer_id),
            "repo": str(repo),
            "entitled": entitled,
            "joined": str(layer_id) in joined_ids,
        }
        if reason:
            entry["reason"] = reason
        layers_out.append(entry)

    return {
        "schema_version": SCHEMA_VERSION,
        "host": socket.gethostname(),
        "layers": layers_out,
    }


def render_layers_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_layers_report()` payload."""
    from rich.console import Console

    con = console or Console()
    layers = report.get("layers", [])
    if not layers:
        con.print("[dim]No department/org layers found.[/dim]")
        return

    for layer in layers:
        entitled = layer.get("entitled")
        entitled_color = "green" if entitled else ("yellow" if entitled is None else "red")
        entitled_label = "unknown" if entitled is None else str(bool(entitled)).lower()
        joined_label = "joined" if layer.get("joined") else "not joined"
        reason = f" ({layer['reason']})" if layer.get("reason") else ""
        con.print(
            f"  [{layer.get('tier')}] {layer.get('id')} — {layer.get('name')}: "
            f"entitled=[{entitled_color}]{entitled_label}[/{entitled_color}] "
            f"{joined_label}{reason}"
        )


# ---------------------------------------------------------------------------
# `cc layers join <id> --json` -- MUTATING
# ---------------------------------------------------------------------------


def _default_manifest_write_path() -> Optional[Path]:
    """
    Best-effort default location to WRITE the layer manifest when
    `layers.manifest` is unset and no `_manifest_write_path` was injected
    (i.e. this machine has never joined a layer before). Mirrors
    `core/ecosystem/lockfile.py`'s `default_lockfile_path()`: lives at
    `<repo root>/copilot.layers.yml`; returns `None` (never guesses
    further) when there is no repo root to anchor to.
    """
    from cc.core.config_paths import repo_root

    root = repo_root()
    if root is None:
        return None
    return root / "copilot.layers.yml"


def _next_rank(layers: list[dict[str, Any]]) -> int:
    ranks = [layer["rank"] for layer in layers if isinstance(layer.get("rank"), int)]
    return (max(ranks) + 10) if ranks else 100


def _new_manifest_layer(dept: dict[str, Any], *, source_path: Optional[str]) -> dict[str, Any]:
    source: dict[str, Any] = {"repo": str(dept["repo"]), "ref": dept.get("ref", "main")}
    if source_path:
        source["path"] = source_path
    return {
        "id": str(dept["id"]),
        "role": dept.get("role", "department"),
        "product": dept.get("product", "cli"),
        "source": source,
        "auth": dept.get("auth", "anon"),
        "activation": dept.get("activation", "always"),
    }


def _write_manifest(path: Path, layers: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": 1, "layers": layers}, sort_keys=False),
        encoding="utf-8",
    )


def _join_result(result: str, *, tier: str, layer_id: str, reason: Optional[str] = None,
                  synced_lock_sha: Optional[str] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "result": result,
        "tier": tier,
        "id": layer_id,
    }
    if synced_lock_sha is not None:
        payload["synced_lock_sha"] = synced_lock_sha
    if reason:
        payload["reason"] = reason
    return payload


def build_layers_join_report(
    layer_id: str,
    *,
    _identity: Optional[dict[str, Any]] = None,
    _identity_root: Any = _UNSET,
    _get_secret: Any = keychain.get_secret,
    _departments: Optional[list[dict[str, Any]]] = None,
    _ecosystem_cfg: Optional[dict[str, Any]] = None,
    _ecosystem_cfg_path: Any = _UNSET,
    _layers: Optional[list[dict[str, Any]]] = None,
    _manifest_path: Any = _UNSET,
    _manifest_write_path: Any = _UNSET,
    _get_json: entitlement.GetJsonFn = entitlement.default_get_json,
    _previous_lock: Optional[dict[str, Any]] = None,
    _lockfile_path: Any = _UNSET,
    _lock_write_path: Any = _UNSET,
    _mirror_root: Any = _UNSET,
    _materialize_root: Any = _UNSET,
    _policy: Any = None,
) -> dict[str, Any]:
    """
    Build the WS-A `layers join <id> --json` contract object AND (when the
    layer is entitled and not already joined) PERFORM the join it
    describes: sync the layer's read-only mirror, extend the local layer
    manifest, then materialize that one layer through `cc update`'s own
    `build_update_report()` (imported, unmodified).

    Does NOT acquire `copilot_lock()` itself -- that is
    `execute_layers_join()`'s job (the CLI-facing wrapper), same split as
    `build_update_report()` / `execute_update()`.

    Raises `NoIdentityError` when no GitHub identity is resolvable at all
    (signed out, or no token stored) -- cli-contract.md D7.1's "2 =
    env/credential error" case. Raises `ManifestError` when the existing
    local manifest is present but malformed (propagated from
    `core/ecosystem/manifest.py`'s `load_layers()`/`validate_layers()`, the
    same mapping `commands/update.py`'s `execute_update()` uses).
    """
    identity = _resolve_identity(_identity=_identity, _identity_root=_identity_root)
    login = identity.get("login") if isinstance(identity.get("login"), str) else None
    token = _resolve_token(login, _get_secret=_get_secret)
    if not login or not token:
        raise NoIdentityError(
            "cc layers join: no GitHub identity resolvable -- sign in first."
        )

    catalog = _catalog(
        _departments=_departments,
        _ecosystem_cfg=_ecosystem_cfg,
        _ecosystem_cfg_path=_ecosystem_cfg_path,
    )
    dept = _find_layer(catalog, layer_id)
    if dept is None:
        return _join_result(
            "error", tier="department", layer_id=layer_id,
            reason=f"unknown layer id: {layer_id!r}",
        )

    local_layers = _local_layers(
        _layers=_layers, _manifest_path=_manifest_path, swallow_errors=False
    )
    if any(str(layer.get("id")) == layer_id for layer in local_layers):
        return _join_result("already-joined", tier="department", layer_id=layer_id)

    repo = dept.get("repo")
    entitled, reason = _entitlement_for(
        repo, login=login, token=token, _get_json=_get_json
    )
    if entitled is None:
        return _join_result(
            "offline", tier="department", layer_id=layer_id, reason=reason
        )
    if entitled is False:
        return _join_result("not-entitled", tier="department", layer_id=layer_id)

    # --- Entitled + not-yet-joined: sync the mirror, then join. ---
    mirror_root_base = (
        Path(_mirror_root).expanduser()
        if _mirror_root is not _UNSET
        else Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    )
    transport = mirror.resolve_transport(str(repo), dept.get("auth", "anon"))
    sync = mirror.clone_or_update_mirror(
        layer_id, transport, dept.get("ref", "main"), mirror_root=mirror_root_base
    )
    mirror_path = Path(sync["path"])
    has_cached_content = mirror_path.is_dir() and any(mirror_path.iterdir())
    if sync["offline"] and not has_cached_content:
        return _join_result(
            "offline", tier="department", layer_id=layer_id, reason=sync.get("error")
        )

    new_layer = _new_manifest_layer(dept, source_path=str(mirror_path))

    manifest_write_path = (
        _manifest_write_path
        if _manifest_write_path is not _UNSET
        else (
            (_manifest_path if _manifest_path is not _UNSET else resolve_key("layers.manifest"))
            or _default_manifest_write_path()
        )
    )
    if manifest_write_path is None:
        raise RuntimeError(
            "cc layers join: cannot determine where to write copilot.layers.yml "
            "(not inside a git repo and no `layers.manifest` configured/injected)."
        )

    updated_layers = local_layers + [
        {
            **new_layer,
            "rank": (
                dept["rank"]
                if isinstance(dept.get("rank"), int)
                else _next_rank(local_layers)
            ),
        }
    ]
    _write_manifest(Path(manifest_write_path).expanduser(), updated_layers)
    joined_layer = updated_layers[-1]

    # --- Materialize the one newly-joined layer -- reuse cc update's own
    # pipeline (mirror-sync -> resolve -> policy-gate -> materialize ->
    # lock-write) unmodified, imported here.
    from cc.commands.update import build_update_report

    materialize_root = (
        Path(_materialize_root).expanduser()
        if _materialize_root is not _UNSET
        else Path(str(resolve_key("paths.materialize_root"))).expanduser()
    )
    if _previous_lock is not None:
        previous_lock = _previous_lock
    else:
        lockfile_path = (
            _lockfile_path if _lockfile_path is not _UNSET else default_lockfile_path()
        )
        previous_lock = read_lockfile(lockfile_path)
    lock_write_path = (
        _lock_write_path if _lock_write_path is not _UNSET else default_lockfile_path()
    )

    update_report = build_update_report(
        _layers=[joined_layer],
        _previous_lock=previous_lock,
        _mirror_root=mirror_root_base,
        _materialize_root=materialize_root,
        _lock_write_path=lock_write_path,
        _policy=_policy,
    )

    return _join_result(
        "joined",
        tier="department",
        layer_id=layer_id,
        synced_lock_sha=update_report.get("lock_after"),
    )


def compute_layers_join_exit_code(report: dict[str, Any]) -> int:
    """
    Map a `build_layers_join_report()` payload to the WS-A contract's exit
    code (cli-contract.md D7.1): `0` for `joined`/`already-joined`/
    `not-entitled`/`offline` (all normal, renderable outcomes); `1` for
    `error` (e.g. unknown layer id -- "join refused"). Lock contention /
    no-identity / invalid-manifest are NOT reachable here -- they raise
    before a report is built, and are mapped to `2` by
    `execute_layers_join()` directly (mirrors `commands/update.py`'s
    `compute_exit_code()` / `execute_update()` split).
    """
    if report.get("result") == "error":
        return 1
    return 0


def execute_layers_join(
    layer_id: str,
    *,
    _lock_path: Any = _UNSET,
    **build_kwargs: Any,
) -> tuple[dict[str, Any], int]:
    """
    CLI-facing wrapper: acquire `copilot_lock()`, then build (and, when
    entitled + not-yet-joined, apply) the join report. Returns
    `(report, exit_code)` -- mirrors `commands/update.py`'s
    `execute_update()` exactly.

    `_lock_path` is injectable so tests can point the mutex at a tmp file
    (and simulate contention by holding it open concurrently) without ever
    touching the real `~/.claude/memory/copilot.lock`.
    """
    target_lock_path = _lock_path if _lock_path is not _UNSET else lock_path()

    try:
        with copilot_lock(path=target_lock_path):
            report = build_layers_join_report(layer_id, **build_kwargs)
    except LockContentionError as exc:
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "error": {"code": "lock-contention", "message": str(exc)},
            },
            2,
        )
    except ManifestError as exc:
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "error": {"code": "invalid-manifest", "message": str(exc)},
            },
            2,
        )
    except NoIdentityError as exc:
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "error": {"code": "signed-out", "message": str(exc)},
            },
            2,
        )

    return report, compute_layers_join_exit_code(report)


def render_layers_join_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_layers_join_report()` /
    `execute_layers_join()` payload."""
    from rich.console import Console

    con = console or Console()

    if "error" in report:
        con.print(f"[red]layers join: {report['error'].get('message')}[/red]")
        return

    result = report.get("result", "unknown")
    color = {
        "joined": "green",
        "already-joined": "green",
        "not-entitled": "yellow",
        "offline": "yellow",
        "error": "red",
    }.get(result, "red")
    con.print(f"[bold {color}]layers join {report.get('id')}: {result}[/bold {color}]")
    if report.get("reason"):
        con.print(f"  reason: {report['reason']}")
    if report.get("synced_lock_sha"):
        con.print(f"  synced_lock_sha: {report['synced_lock_sha']}")


# ---------------------------------------------------------------------------
# Typer app
# ---------------------------------------------------------------------------

layers_app = typer.Typer(
    name="layers",
    help=(
        "Discover and join department/org layers (WS-A `layers`/`layers join` "
        "contract, D7.1 -- proposed addition, not yet upstream)."
    ),
    no_args_is_help=False,
    invoke_without_command=True,
)


def _run_list(*, output_json: bool) -> None:
    try:
        report = build_layers_report()
    except Exception as exc:  # environment/unexpected error -> exit 2
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "error": {"code": "environment-error", "message": str(exc)},
                    }
                )
            )
        else:
            typer.echo(f"layers: environment error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_layers_report_rich(report)
    raise typer.Exit(0)


@layers_app.callback(invoke_without_command=True)
def layers_main(
    ctx: typer.Context,
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A layers contract as JSON."
    ),
) -> None:
    """List every department/org layer this account could join, and
    whether it is entitled/joined (WS-A `layers --json` contract).
    Read-only -- does not take the copilot lock. Bare `cc layers` is the
    same as `cc layers list`.
    """
    if ctx.invoked_subcommand is not None:
        return
    _run_list(output_json=output_json)


@layers_app.command("list")
def list_cmd(
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A layers contract as JSON."
    ),
) -> None:
    """List every department/org layer this account could join (same as
    the bare `cc layers` default)."""
    _run_list(output_json=output_json)


@layers_app.command("join")
def join_cmd(
    layer_id: str = typer.Argument(..., help="The layer id to join (from `cc layers list`)."),
    output_json: bool = typer.Option(
        False, "--json", help="Output the WS-A layers-join contract as JSON."
    ),
) -> None:
    """Join an entitled, not-yet-joined department/org layer (WS-A `layers
    join <id> --json` contract) -- MUTATING: acquires the copilot lock,
    syncs the layer's mirror, extends the local manifest, and materializes
    it via `cc update`'s own pipeline. `not-entitled` is a normal outcome,
    not a crash.
    """
    try:
        report, exit_code = execute_layers_join(layer_id)
    except Exception as exc:  # environment/unexpected error -> exit 2
        if output_json:
            typer.echo(
                _json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "error": {"code": "environment-error", "message": str(exc)},
                    }
                )
            )
        else:
            typer.echo(f"layers join: environment error: {exc}", err=True)
        raise typer.Exit(2) from exc

    if "error" in report:
        exit_code = 2

    if output_json:
        typer.echo(_json.dumps(report))
    else:
        render_layers_join_report_rich(report)
    raise typer.Exit(exit_code)
