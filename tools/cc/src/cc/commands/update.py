"""`cc update --json` -- the WS-A reconciling ecosystem sync (MUTATING).

WS-A slice 4 (update-slice). See:
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/01-architecture/schemas/update.schema.json
  - copilot-control-tower/docs/reference/ecosystem-architecture.md §3.2, §5.2
  - copilot-control-tower/docs/01-architecture/inheritance-and-publish.md §2.2
  - tools/cc/tests/fixtures/schemas/ (vendored copy used by the contract test)

Unlike `doctor`/`resolve --explain`/`freshness` (all strictly read-only),
`update` MATERIALIZES and DELETES files: it acquires the advisory
`copilot_lock()` mutex (core/locking.py) for the whole operation, syncs
each layer's read-only mirror (core/ecosystem/mirror.py's
`clone_or_update_mirror()`), runs the fail-closed policy gate
(core/ecosystem/policy.py), reconciles the materialize root
(core/ecosystem/materialize.py's `materialize()` -- the reconciling sync,
never-destroy guarded), and writes the new `copilot.lock.json`
(core/ecosystem/lockfile.py's `write_lockfile()`).

SAFETY: every I/O root (manifest path, mirror root, materialize root,
lockfile read/write path, the advisory lock path itself) is injectable via
this module's `_..._path`/`_..._root` keyword arguments -- see
`build_update_report()`/`execute_update()`. Real production defaults only
ever resolve through `resolve_key()`'s normal config cascade (never a bare
`Path.home()` call in this module); tests MUST inject every root (see
tests/test_ecosystem_materialize.py, tests/test_update_contract.py) so
nothing here is ever exercised against a real machine.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Optional

from cc.core.config import personal_roots_from_config, resolve_key
from cc.core.ecosystem import mirror
from cc.core.ecosystem.freshness import lock_fingerprint
from cc.core.ecosystem.lockfile import (
    default_lockfile_path,
    layer_meta,
    read_lockfile,
    set_layer_meta,
    write_lockfile,
)
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers
from cc.core.ecosystem.materialize import materialize, materialize_ecosystem_config
from cc.core.ecosystem.policy import PolicyFn
from cc.core.ecosystem.policy import evaluate as default_policy
from cc.core.ecosystem.resolver import resolve_layers
from cc.core.locking import LockContentionError, copilot_lock, lock_path

SCHEMA_VERSION = "1.0"

# Sentinel distinguishing "no override passed" from an explicit None argument.
_UNSET: Any = object()


def _empty_report(lock_sha: str, *, result: str = "up-to-date") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "host": socket.gethostname(),
        "result": result,
        "lock_before": lock_sha,
        "lock_after": lock_sha,
        "changed": [],
        "held_for_approval": [],
        "blocked": [],
    }


def _shadowed_by_lookup(
    resolved: list[dict[str, Any]],
) -> dict[tuple[str, str, str], Optional[str]]:
    lookup: dict[tuple[str, str, str], Optional[str]] = {}
    for entry in resolved:
        shadowed = entry.get("shadowed") or []
        lookup[(entry.get("product", ""), entry["dimension"], entry["item"])] = (
            shadowed[0]["layer"] if shadowed else None
        )
    return lookup


def build_update_report(
    *,
    _layers: Optional[list[dict[str, Any]]] = None,
    _manifest_path: Any = _UNSET,
    _contributions: Optional[dict[str, Any]] = None,
    _previous_lock: Optional[dict[str, Any]] = None,
    _lockfile_path: Any = _UNSET,
    _lock_write_path: Any = _UNSET,
    _mirror_root: Any = _UNSET,
    _materialize_root: Any = _UNSET,
    _materialize_roots: Any = _UNSET,
    _target_allowlist: Any = _UNSET,
    _policy: Optional[PolicyFn] = None,
    _personal_roots: Any = _UNSET,
    _dry_run: bool = False,
) -> dict[str, Any]:
    """
    Build the WS-A `update --json` contract object AND (unless
    `_dry_run=True`) perform the reconciling sync it describes: mirror
    sync -> resolve -> policy gate -> materialize -> write
    `copilot.lock.json`.

    Every root is injectable (see module docstring) -- callers/tests MUST
    supply `_mirror_root`/`_materialize_root`/`_lockfile_path`/
    `_lock_write_path`/`_layers` (or `_manifest_path`) to keep this
    entirely inside a tmp sandbox. `_dry_run=True` computes every op
    WITHOUT writing/pruning materialize-root content and WITHOUT writing
    the lockfile -- a safe preview of the plan.

    `_personal_roots`: WP-372 P0.3 -- when NOT explicitly injected (the
    real production path; only tests override this), defaults to
    `personal_roots_from_config()` (`core/config.py`) rather than the
    empty tuple this used to silently default to. This is half of closing
    the live incident's guard hole -- every configured
    `paths.knowledge_repo` entry and `projects.roots` entry is a known
    human-owned tree and is now ALWAYS passed to `guard_personal()`,
    whether or not it happens to be dirty right now.

    Does NOT acquire `copilot_lock()` itself -- that is `execute_update()`'s
    job (the CLI-facing wrapper), so this function stays a plain,
    independently-testable build step the same way `build_doctor_report()`/
    `build_resolve_report()`/`build_freshness_report()` do, just with real
    (injected-root) side effects instead of none.
    """
    if _layers is not None:
        layers = _layers
    else:
        manifest_path = (
            _manifest_path if _manifest_path is not _UNSET else resolve_key("layers.manifest")
        )
        if not manifest_path:
            empty_sha = lock_fingerprint({})
            return _empty_report(empty_sha)
        layers = load_layers(manifest_path)

    validate_layers(layers)

    if _previous_lock is not None:
        previous_lock = _previous_lock
    else:
        lockfile_path = (
            _lockfile_path if _lockfile_path is not _UNSET else default_lockfile_path()
        )
        previous_lock = read_lockfile(lockfile_path)

    lock_before = lock_fingerprint(previous_lock)

    mirror_root_base = (
        Path(_mirror_root).expanduser()
        if _mirror_root is not _UNSET
        else Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    )
    materialize_root: Optional[Path] = None
    materialize_roots: Optional[dict[str, Path]] = None
    if _materialize_roots is not _UNSET:
        materialize_roots = {
            product: Path(path).expanduser() for product, path in _materialize_roots.items()
        }
    elif _materialize_root is not _UNSET:
        # Backward-compatible injected single-root path used by existing
        # callers and fixtures.
        materialize_root = Path(_materialize_root).expanduser()
    else:
        generic = Path(str(resolve_key("paths.materialize_root"))).expanduser()
        claude_root = resolve_key("paths.claude_materialize_root")
        codex_root = resolve_key("paths.codex_materialize_root")
        materialize_roots = {
            "claude": Path(str(claude_root)).expanduser() if claude_root else generic,
            "codex": Path(str(codex_root)).expanduser() if codex_root else generic / "codex",
        }

    # --- Mirror sync: clone/fetch+reset each remote-sourced layer, confined
    # to <mirror_root_base>/<layer id> (mirror.py's own confinement proof).
    effective_layers: list[dict[str, Any]] = []
    source_shas: dict[str, str] = {}
    any_offline_without_cache = False

    externally_consumed_products = mirror.EXTERNALLY_CONSUMED_PRODUCTS

    for layer in sorted(layers, key=lambda item: item["rank"]):
        layer_copy = dict(layer)
        source = dict(layer.get("source") or {})
        repo = source.get("repo")
        local_path = source.get("path")
        subpath = source.get("subpath")
        product = layer.get("product")

        if repo and not local_path:
            transport = mirror.resolve_transport(repo, layer.get("auth", "anon"))
            product_root = (
                mirror_root_base / str(product)
                if product in externally_consumed_products
                else mirror_root_base
            )
            sync = mirror.clone_or_update_mirror(
                layer["id"], transport, source.get("ref", "main"),
                mirror_root=product_root,
            )
            mirror_path = Path(sync["path"])
            has_cached_content = mirror_path.is_dir() and any(mirror_path.iterdir())

            if sync["offline"] and not has_cached_content:
                any_offline_without_cache = True
            else:
                source_sha = sync["head_sha"] or layer_meta(
                    previous_lock, layer["id"]
                ).get("source_sha")
                if source_sha:
                    source_shas[layer["id"]] = source_sha
                source = dict(source)
                # WP-372 P5.1: shared with commands/resolve.py -- see
                # mirror.synthesize_source_path()'s own docstring for why
                # this is no longer computed inline here.
                content_root = mirror.synthesize_source_path(
                    layer,
                    mirror_root_base=mirror_root_base,
                    externally_consumed_products=externally_consumed_products,
                )
                source["path"] = str(content_root)
        elif local_path and subpath:
            relative = Path(str(subpath))
            if relative.is_absolute() or ".." in relative.parts:
                raise ManifestError(
                    f"Layer {layer['id']!r} source.subpath must stay inside its checkout."
                )
            source = dict(source)
            source["path"] = str(Path(str(local_path)).expanduser() / relative)

        layer_copy["source"] = source
        effective_layers.append(layer_copy)

    if any_offline_without_cache:
        # Honest offline result -- no partial materialize, lock untouched
        # (ecosystem-architecture.md §5.2: unreachable != drift).
        return _empty_report(lock_before, result="offline")

    from cc.core.ecosystem.discovery import discover_contributions

    materialized_layers = [
        layer
        for layer in effective_layers
        if layer.get("product") not in externally_consumed_products
    ]
    materialized_ids = {layer["id"] for layer in materialized_layers}
    contributions = (
        {
            layer_id: value
            for layer_id, value in _contributions.items()
            if layer_id in materialized_ids
        }
        if _contributions is not None
        else discover_contributions(materialized_layers)
    )

    resolved = (
        resolve_layers(materialized_layers, contributions, lockfile=previous_lock)
        if materialized_layers
        else []
    )

    layer_source_paths = {
        layer["id"]: (layer.get("source") or {}).get("path")
        for layer in effective_layers
        if (layer.get("source") or {}).get("path")
    }
    # G-9 (task 215 blocker fix): each layer's actually-resolved/pinned
    # `source.ref` (e.g. a signed foundation snapshot tag), threaded to the
    # policy gate -- see materialize()'s own `layer_source_refs` docstring
    # and `verify_git_item()`'s docstring: the pinned tag is now REQUIRED
    # for `verify_git_item()` to verify anything at all (security review
    # blocker 2, 2026-08-10), so an item whose layer has no resolved ref
    # here blocks rather than falling back to any other check.
    layer_source_refs = {
        layer["id"]: (layer.get("source") or {}).get("ref")
        for layer in effective_layers
        if (layer.get("source") or {}).get("ref")
    }

    # WP-372 P0.3: production feeder for guard_personal()'s personal_roots
    # -- see build_update_report()'s own docstring above and
    # core/config.py's personal_roots_from_config() for the full rationale.
    personal_roots = (
        list(_personal_roots) if _personal_roots is not _UNSET else personal_roots_from_config()
    )

    mat_report = materialize(
        resolved,
        materialize_root=materialize_root,
        materialize_roots=materialize_roots,
        target_allowlist=None if _target_allowlist is _UNSET else _target_allowlist,
        previous_lock=previous_lock,
        layer_source_paths=layer_source_paths,
        layer_source_refs=layer_source_refs,
        layer_policies={layer["id"]: layer.get("policy", {}) for layer in effective_layers},
        layer_products={layer["id"]: layer["product"] for layer in effective_layers},
        policy=_policy or default_policy,
        personal_roots=personal_roots,
        mirror_roots=[mirror_root_base],
        dry_run=_dry_run,
    )

    incomplete_layers = {
        op["layer"] for op in mat_report["ops"] if op["op"] in {"blocked", "held"}
    }
    if not _dry_run:
        for layer in effective_layers:
            layer_id = layer["id"]
            if layer_id in incomplete_layers:
                continue
            set_layer_meta(
                mat_report["lock"],
                layer_id,
                product=layer["product"],
                tier=layer.get("role"),
                role=layer.get("role"),
                source_sha=source_shas.get(layer_id),
            )

    if not _dry_run:
        lock_write_path = (
            _lock_write_path if _lock_write_path is not _UNSET else _lockfile_path_default()
        )
        write_lockfile(lock_write_path, mat_report["lock"])

    lock_after = lock_fingerprint(mat_report["lock"])
    shadow_lookup = _shadowed_by_lookup(resolved)

    # WP-372 P1.3(a): deliver the org's inherited ecosystem.yml alongside
    # the regular dimension fold -- see materialize_ecosystem_config()'s
    # own docstring (core/ecosystem/materialize.py) for why this is a
    # dedicated step, not a new PRODUCT_TARGET_ALLOWLIST dimension. Runs
    # AFTER the lock/set_layer_meta bookkeeping above so this op (which
    # never touches mat_report["lock"] -- see that function's "known
    # limitation" docstring section) can never be mistaken for a
    # dimension-tracked item when computing `incomplete_layers`.
    claude_materialize_root = (
        materialize_roots.get("claude") if materialize_roots is not None else materialize_root
    )
    ecosystem_op = materialize_ecosystem_config(
        effective_layers,
        layer_source_paths=layer_source_paths,
        materialize_root=claude_materialize_root,
        personal_roots=personal_roots,
        mirror_roots=[mirror_root_base],
        dry_run=_dry_run,
    )
    if ecosystem_op is not None:
        mat_report["ops"].append(ecosystem_op)

    changed: list[dict[str, Any]] = []
    held_for_approval: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for op in mat_report["ops"]:
        if op["op"] == "blocked":
            blocked.append(
                {
                    "product": op["product"],
                    "dimension": op["dimension"],
                    "layer": op["layer"],
                    "item": op["item"],
                    "reason": op.get("reason"),
                }
            )
        elif op["op"] == "held":
            held_for_approval.append(
                {
                    "product": op["product"],
                    "dimension": op["dimension"],
                    "from": op.get("from_sha") or "",
                    "to": op.get("to_sha") or "",
                    "reason": op.get("reason") or "held",
                }
            )
        else:
            changed.append(
                {
                    "product": op["product"],
                    "dimension": op["dimension"],
                    "layer": op["layer"],
                    "item": op["item"],
                    "op": op["op"],
                    "from": op.get("from_sha"),
                    "to": op.get("to_sha"),
                    "signed": op["signed"],
                    "severity_trailer": None,
                    "shadowed_by": shadow_lookup.get(
                        (op["product"], op["dimension"], op["item"])
                    ),
                    # ADDITIVE (task 220 Fix 1): non-null only for a fold
                    # fallback substitution -- `layer` above is the
                    # SHADOWED layer whose verified copy actually
                    # materialized; `blocked_winner` names the resolver's
                    # real OVERRIDE winner, which was policy-blocked
                    # (unverified) and never applied. `reason` carries the
                    # human-readable explanation. Both are `null` for
                    # every ordinary (non-substituted) change.
                    "blocked_winner": op.get("blocked_winner"),
                    "reason": op.get("reason"),
                }
            )

    # Overall result precedence: blocked > held > applied > up-to-date.
    # OWNER-DEFENSIBLE CHOICE (flag for confirmation at freeze): with
    # today's fail-closed policy default (policy.py `evaluate()` blocks
    # everything unverified), any non-empty resolved+materializable set
    # will report `blocked` until a real signature verifier lands --
    # this is intentional honesty, not a bug: nothing new was actually
    # applied, so `applied` would overclaim.
    if blocked:
        result = "blocked"
    elif held_for_approval:
        result = "held"
    elif any(op["op"] in ("added", "updated", "pruned") for op in mat_report["ops"]):
        result = "applied"
    else:
        result = "up-to-date"

    return {
        "schema_version": SCHEMA_VERSION,
        "host": socket.gethostname(),
        "result": result,
        "lock_before": lock_before,
        "lock_after": lock_after,
        "changed": changed,
        "held_for_approval": held_for_approval,
        "blocked": blocked,
    }


def _lockfile_path_default() -> Any:
    """Real default write target -- only reached when nothing was injected
    (never exercised in tests, which always inject `_lock_write_path`)."""
    path = default_lockfile_path()
    if path is None:
        raise RuntimeError(
            "cc update: cannot determine where to write copilot.lock.json "
            "(not inside a git repo and no lockfile path configured/injected)."
        )
    return path


def compute_exit_code(report: dict[str, Any]) -> int:
    """
    Map a `build_update_report()` payload to the WS-A contract's exit code:
      0 = applied | up-to-date
      1 = held | blocked
      2 = reserved for environment/unexpected errors (raised by the CLI
          handler when `build_update_report()`/`execute_update()` itself
          throws, or on lock contention -- never returned from here).
    """
    result = report.get("result")
    if result in ("applied", "up-to-date"):
        return 0
    if result in ("held", "blocked"):
        return 1
    # "offline" -- honest non-error non-mutation; treat as a clean 0 (nothing
    # was changed, nothing to act on beyond retrying later).
    return 0


def execute_update(
    *,
    dry_run: bool = False,
    _lock_path: Any = _UNSET,
    **build_kwargs: Any,
) -> tuple[dict[str, Any], int]:
    """
    CLI-facing wrapper: acquire `copilot_lock()`, then build (and, unless
    `dry_run`, apply) the update report. Returns `(report, exit_code)`.

    `_lock_path` is injectable so tests can point the mutex at a tmp file
    (and simulate contention by holding it open concurrently) without ever
    touching the real `~/.claude/memory/copilot.lock`.
    """
    target_lock_path = _lock_path if _lock_path is not _UNSET else lock_path()

    try:
        with copilot_lock(path=target_lock_path):
            report = build_update_report(_dry_run=dry_run, **build_kwargs)
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

    return report, compute_exit_code(report)


def render_update_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a `build_update_report()` payload."""
    from rich.console import Console

    con = console or Console()

    if "error" in report:
        con.print(f"[red]update: {report['error'].get('message')}[/red]")
        return

    result = report.get("result", "unknown")
    color = {
        "applied": "green",
        "up-to-date": "green",
        "held": "yellow",
        "blocked": "red",
        "offline": "yellow",
    }.get(result, "red")
    con.print(f"[bold {color}]update: {result}[/bold {color}]")

    for c in report.get("changed", []):
        con.print(f"  [{c['op']}] {c['dimension']}/{c['item']} ({c['layer']})")
    for h in report.get("held_for_approval", []):
        con.print(f"  [yellow]held[/yellow] {h['dimension']}: {h.get('reason')}")
    for b in report.get("blocked", []):
        con.print(f"  [red]blocked[/red] {b['dimension']}/{b.get('item')}: {b.get('reason')}")
