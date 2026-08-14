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
and never materializes/writes anything. It loads the layer manifest,
best-effort-discovers local layer content, reads the lockfile, folds the
PURE resolver, then re-proves signed-source and materialized-byte evidence
without changing any receipt, cache, lock, or destination.

Naming note: `cc resolve` already existed as a single-config-key resolver
(`cc resolve paths.shared_docs`). Per the same WS-A naming precedent as
`cc doctor` (see doctor.py's docstring — `cc X` IS the verb until the
`copilot` wrapper exists), this ecosystem-resolve mode rides the SAME `cc
resolve` verb, disambiguated in main.py by whether a `KEY` positional
argument was given: `cc resolve <key>` keeps its pre-existing behavior;
`cc resolve --explain [--json]` (no key) is this contract. See main.py's
`resolve_cmd` for the dispatch and a note on why this collision was
resolved this way rather than by renaming either verb.

Fail-closed security fields are enriched only here, at the I/O boundary.
The pure resolver still defaults them to null/false. A signer is emitted
only after the winning item is reverified against its immutable signed tag;
`live_hash_matches` becomes true only when the destination's freshly computed
canonical content hash equals the winning lock pin. Protected Knowledge uses
its private active receipt and signed Git-object projection as authority,
never mutable checkout bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from cc.core.config import resolve_key
from cc.core.ecosystem import entitlement, mirror
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.knowledge_skill_source import (
    inspect_protected_knowledge_lock_projection,
)
from cc.core.ecosystem.lockfile import default_lockfile_path, read_lockfile
from cc.core.ecosystem.manifest import load_layers, validate_layers
from cc.core.ecosystem.materialize import (
    content_item_path,
    materialized_item_content_sha,
)
from cc.core.ecosystem.policy import verify_git_item
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

    WP-372 (protocol-override live-verify): also joins a declared
    `source.subpath` onto an explicit local `source.path` (the live
    manifest's `claude-foundation` entry: `path: .../claude-copilot`,
    `subpath: .claude`), so a visible-checkout layer's real content is
    always discoverable and can appear in another layer's `shadowed[]`.

    A thin, unchanged-behavior wrapper: the actual computation now lives in
    `core/ecosystem/mirror.py`'s `synthesize_effective_layers()`, the
    SINGLE SOURCE OF TRUTH shared with `core/ecosystem/project_sources.py`
    (project-install ladder resolution) — see that function's own
    docstring — so `cc resolve --explain` and a project install can never
    compute a layer's effective content root differently.
    """
    return mirror.synthesize_effective_layers(layers, mirror_root_base=mirror_root_base)


def _resolved_materialize_roots(
    injected: Any,
) -> dict[str, Path]:
    if injected is not _UNSET:
        return {
            str(product): Path(path).expanduser()
            for product, path in injected.items()
        }
    generic_value = resolve_key("paths.materialize_root")
    claude_value = resolve_key("paths.claude_materialize_root")
    codex_value = resolve_key("paths.codex_materialize_root")
    generic = Path(str(generic_value)).expanduser() if generic_value else None
    roots: dict[str, Path] = {}
    if claude_value:
        roots["claude"] = Path(str(claude_value)).expanduser()
    elif generic is not None:
        roots["claude"] = generic
    if codex_value:
        roots["codex"] = Path(str(codex_value)).expanduser()
    elif generic is not None:
        roots["codex"] = generic / "codex"
    return roots


def _enrich_provenance(
    items: list[dict[str, Any]],
    layers: list[dict[str, Any]],
    *,
    materialize_roots: dict[str, Path],
    knowledge_cache_root: Path | str | None,
) -> None:
    """Mutate resolver result dictionaries with freshly re-proved evidence."""
    layer_by_id = {str(layer["id"]): layer for layer in layers}
    knowledge_projection_by_layer: dict[str, Any] = {}
    for entry in items:
        layer_id = str(entry.get("winning_layer") or "")
        layer = layer_by_id.get(layer_id)
        if layer is None:
            continue

        if layer.get("product") == "knowledge" and entitlement.is_protected_layer(
            layer
        ):
            if layer_id not in knowledge_projection_by_layer:
                knowledge_projection_by_layer[layer_id] = (
                    inspect_protected_knowledge_lock_projection(
                        layer, cache_root=knowledge_cache_root
                    )
                )
            projection = knowledge_projection_by_layer[layer_id]
            if (
                projection is not None
                and entry.get("dimension") == projection.dimension
                and entry.get("item") == projection.item
            ):
                entry["signer_of_introducing_commit"] = projection.signer
                entry["live_hash_matches"] = bool(
                    entry.get("winning_sha")
                    and entry["winning_sha"] == projection.content_sha256
                )
            continue

        source = layer.get("source") or {}
        source_root = source.get("path")
        source_ref = source.get("ref")
        policy = layer.get("policy")
        signers = policy.get("allowed_signers") if isinstance(policy, dict) else None
        if (
            isinstance(source_root, str)
            and isinstance(source_ref, str)
            and isinstance(signers, list)
            and signers
        ):
            source_item = content_item_path(
                source_root,
                dimension=str(entry["dimension"]),
                item=str(entry["item"]),
            )
            if source_item is not None:
                try:
                    relative_path = source_item.relative_to(
                        Path(source_root).expanduser()
                    ).as_posix()
                except ValueError:
                    relative_path = ""
                if relative_path:
                    verified, signer = verify_git_item(
                        source_root,
                        relative_path,
                        signers,
                        ref=source_ref,
                    )
                    if verified and signer:
                        entry["signer_of_introducing_commit"] = signer

        winning_sha = entry.get("winning_sha")
        if isinstance(winning_sha, str) and winning_sha:
            live_sha = materialized_item_content_sha(
                product=str(entry.get("product") or ""),
                dimension=str(entry["dimension"]),
                item=str(entry["item"]),
                materialize_roots=materialize_roots,
            )
            entry["live_hash_matches"] = live_sha == winning_sha


def build_resolve_report(
    *,
    _layers: Optional[list[dict[str, Any]]] = None,
    _contributions: Optional[dict[str, Any]] = None,
    _lockfile: Optional[dict[str, Any]] = None,
    _manifest_path: Any = _UNSET,
    _lockfile_path: Any = _UNSET,
    _mirror_root: Any = _UNSET,
    _materialize_roots: Any = _UNSET,
    _knowledge_cache_root: Any = _UNSET,
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
    _enrich_provenance(
        items,
        effective_layers,
        materialize_roots=_resolved_materialize_roots(_materialize_roots),
        knowledge_cache_root=(
            None if _knowledge_cache_root is _UNSET else _knowledge_cache_root
        ),
    )
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
        signer = entry.get("signer_of_introducing_commit")
        if signer:
            con.print(f"    signer: {signer}")
        if entry.get("live_hash_matches") is False:
            if entry.get("winning_sha"):
                con.print(
                    "    [red]MODIFIED — on-disk content no longer matches "
                    "the recorded SHA[/red]"
                )
            else:
                con.print("    [yellow]no recorded SHA is available[/yellow]")
