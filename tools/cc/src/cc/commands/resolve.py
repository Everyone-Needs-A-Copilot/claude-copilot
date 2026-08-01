"""`cc resolve --explain --json` — the WS-A ecosystem-resolve contract.

Separated from main.py's dispatch so it can be tested in isolation, the
same way doctor.py separates from `config doctor` (see that module's
docstring for the precedent).

Contract sources:
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/01-architecture/schemas/resolve.schema.json
  - tools/cc/tests/fixtures/schemas/ (vendored copies used by the contract
    test)

READ-ONLY: this module never acquires the copilot lock (core/locking.py)
and never materializes/writes anything. It only (in order): loads the
layer manifest, best-effort-discovers local layer content
(core/ecosystem/discovery.py), reads (never writes) the lockfile
(core/ecosystem/lockfile.py), and folds the PURE resolver
(core/ecosystem/resolver.py) over the result.

Naming note: `cc resolve` already existed as a single-config-key resolver
(`cc resolve paths.shared_docs`). Per the same WS-A naming precedent as
`cc doctor` (see doctor.py's docstring — `cc X` IS the verb until the
`copilot` wrapper exists), this ecosystem-resolve mode rides the SAME `cc
resolve` verb, disambiguated in main.py by whether a `KEY` positional
argument was given: `cc resolve <key>` keeps its pre-existing behavior;
`cc resolve --explain [--json]` (no key) is this contract. See main.py's
`resolve_cmd` for the dispatch and a note on why this collision was
resolved this way rather than by renaming either verb.

Fail-closed security fields (deferred to later slices): every item always
emits `signer_of_introducing_commit: null` and `live_hash_matches: false`.
These become real once signature-verify (a policy module, ecosystem-
architecture.md §7.2/§9) and materialize (§3.2) land. NEVER fabricate a
"signed"/"matches" verdict before those modules exist — see
core/ecosystem/resolver.py's `_make_item()`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from cc.core.config import resolve_key
from cc.core.ecosystem import mirror
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.lockfile import default_lockfile_path, read_lockfile
from cc.core.ecosystem.manifest import load_layers, validate_layers
from cc.core.ecosystem.resolver import resolve_layers

SCHEMA_VERSION = "1.0"

# Sentinel distinguishing "no override passed" from an explicit None argument.
_UNSET: Any = object()


def _synthesize_effective_layers(
    layers: list[dict[str, Any]], *, mirror_root_base: Path
) -> list[dict[str, Any]]:
    """
    WP-372 P5.1: `discover_contributions()` requires a static local
    `source.path`, but the live manifest never carries one for a remote-
    sourced layer — `commands/update.py` synthesizes it from the mirror at
    materialize time (`mirror.synthesize_source_path()`), and this
    function does the SAME thing for `resolve --explain`, which had no
    equivalent at all before this and so always reported 0 resolved
    items. Read-only: never clones/fetches anything — if a layer's
    computed mirror path is not ALREADY on disk (no `cc update` has run
    yet), `discover_contributions()`'s own existing "path doesn't exist ->
    contributes nothing" degrade handles it honestly, exactly as it
    already does for any other unreachable local_root.
    """
    effective: list[dict[str, Any]] = []
    for layer in layers:
        layer_copy = dict(layer)
        synthesized = mirror.synthesize_source_path(layer, mirror_root_base=mirror_root_base)
        if synthesized is not None:
            source = dict(layer.get("source") or {})
            source["path"] = str(synthesized)
            layer_copy["source"] = source
        effective.append(layer_copy)
    return effective


def build_resolve_report(
    *,
    _layers: Optional[list[dict[str, Any]]] = None,
    _contributions: Optional[dict[str, Any]] = None,
    _lockfile: Optional[dict[str, Any]] = None,
    _manifest_path: Any = _UNSET,
    _lockfile_path: Any = _UNSET,
    _mirror_root: Any = _UNSET,
) -> dict[str, Any]:
    """
    Build the WS-A `resolve --explain --json` contract object.

    Injectable layers/contributions/lockfile/paths allow unit + contract
    testing without a real filesystem (mirrors `build_doctor_report()`'s
    `_machine_cfg_path`-style DI in doctor.py). With no injection and no
    `layers.manifest` configured, returns an honest empty result
    (`items: []`) — there is nothing to resolve yet, which is not an error.

    `_mirror_root` (WP-372 P5.1): the same `paths.mirrors_root`-resolved
    root `commands/update.py` uses, injected here so
    `_synthesize_effective_layers()` above can compute where each remote-
    sourced layer's mirror WOULD be without ever cloning/fetching — this
    module remains strictly read-only (still never acquires the copilot
    lock, still never touches the network).

    Raises `ManifestError` (core/ecosystem/manifest.py) if a manifest was
    found/injected but fails validation — callers (the CLI) catch this and
    report it as a plain-language error, never a stack trace.
    """
    if _layers is not None:
        layers = _layers
    else:
        manifest_path = (
            _manifest_path
            if _manifest_path is not _UNSET
            else resolve_key("layers.manifest")
        )
        if not manifest_path:
            return {"schema_version": SCHEMA_VERSION, "items": []}
        layers = load_layers(manifest_path)

    validate_layers(layers)

    mirror_root_base = (
        Path(_mirror_root).expanduser()
        if _mirror_root is not _UNSET
        else Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    )
    effective_layers = _synthesize_effective_layers(layers, mirror_root_base=mirror_root_base)

    contributions = (
        _contributions
        if _contributions is not None
        else discover_contributions(effective_layers)
    )

    if _lockfile is not None:
        lockfile = _lockfile
    else:
        lockfile_path = (
            _lockfile_path if _lockfile_path is not _UNSET else default_lockfile_path()
        )
        lockfile = read_lockfile(lockfile_path)

    items = resolve_layers(effective_layers, contributions, lockfile=lockfile)
    return {"schema_version": SCHEMA_VERSION, "items": items}


def render_resolve_report_rich(report: dict[str, Any], *, console: Any = None) -> None:
    """Human-readable (Rich) rendering of a build_resolve_report() payload."""
    from rich.console import Console

    con = console or Console()
    items = report.get("items", [])

    if not items:
        con.print(
            "[dim]resolve: nothing to resolve yet (no layer manifest configured, "
            "or the manifest has no local content to discover).[/dim]"
        )
        return

    for entry in items:
        sha = entry.get("winning_sha") or "no-sha"
        product = entry.get("product") or "unknown"
        con.print(
            f"[bold]{entry['dimension']}/{entry['item']}[/bold] -> {entry['winning_layer']} "
            f"[dim]({product})[/dim] ({sha})"
        )
        for shadow in entry.get("shadowed", []):
            stale_note = (
                " [red]STALE — upstream changed since last resolve[/red]"
                if shadow.get("stale")
                else ""
            )
            con.print(
                f"    shadows {shadow.get('layer')} (rank {shadow.get('rank')}){stale_note}"
            )
        if entry.get("live_hash_matches") is False:
            con.print(
                "    [yellow]live_hash_matches: false — unverified "
                "(signature-verify not implemented yet)[/yellow]"
            )
