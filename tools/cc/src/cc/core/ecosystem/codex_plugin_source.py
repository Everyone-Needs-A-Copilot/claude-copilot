"""Resolve the effective signed atomic Codex plugin for project installs."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cc.core.config import resolve_key
from cc.core.ecosystem import entitlement
from cc.core.ecosystem.discovery import discover_contributions
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers
from cc.core.ecosystem.mirror import synthesize_effective_layers
from cc.core.ecosystem.policy import (
    GitTreeSnapshot,
    read_git_tree_snapshot,
    verify_git_item_provenance,
)
from cc.core.ecosystem.resolver import resolve_layers


class CodexPluginSourceError(ValueError):
    """A configured Codex tier source could not earn write authority."""


@dataclass(frozen=True)
class CodexPluginSource:
    path: Path
    repository_root: Path
    relative_path: str
    layer: str
    ref: str
    tree: str
    signer: str
    snapshot: GitTreeSnapshot

    def provenance(self) -> dict[str, str]:
        return {
            "layer": self.layer,
            "ref": self.ref,
            "tree": self.tree,
            "signer": self.signer,
        }


def _protected_directory(path: Path) -> Path:
    try:
        nominal = Path(os.path.abspath(path.expanduser()))
        metadata = nominal.lstat()
    except OSError as exc:
        raise CodexPluginSourceError(
            "The effective Codex plugin source is unavailable."
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in {0, os.getuid()}
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise CodexPluginSourceError(
            "The effective Codex plugin source is not protected."
        )
    return nominal


def resolve_codex_plugin_source(
    *,
    manifest_path: Any = None,
    mirror_root_base: Any = None,
    entitlement_state_path: Any = None,
    entitlement_login: str | None = None,
    entitlement_now: Any = None,
) -> CodexPluginSource | None:
    source, _bindings = resolve_codex_plugin_source_with_bindings(
        manifest_path=manifest_path,
        mirror_root_base=mirror_root_base,
        entitlement_state_path=entitlement_state_path,
        entitlement_login=entitlement_login,
        entitlement_now=entitlement_now,
    )
    return source


def resolve_codex_plugin_source_with_bindings(
    *,
    manifest_path: Any = None,
    mirror_root_base: Any = None,
    entitlement_state_path: Any = None,
    entitlement_login: str | None = None,
    entitlement_now: Any = None,
) -> tuple[CodexPluginSource | None, tuple[entitlement.EntitlementBinding, ...]]:
    """Return the nearest eligible verified plugin, or ``None`` with no ladder.

    A configured effective winner that fails cryptographic or byte verification
    blocks.  Private entitlement bindings cover every configured protected Codex
    layer, including an ineligible/absent row, so a fallback plan cannot race a
    later reauthorization.
    """
    configured = (
        resolve_key("layers.manifest") if manifest_path is None else manifest_path
    )
    if not configured:
        return None, ()
    try:
        layers = load_layers(configured)
        has_protected = any(entitlement.is_protected_layer(layer) for layer in layers)
        state_path = (
            Path(entitlement_state_path).expanduser()
            if entitlement_state_path is not None
            else entitlement.entitlement_state_path()
            if has_protected
            else None
        )
        login = (
            entitlement.current_login()
            if entitlement_login is None and has_protected
            else entitlement_login
        )
        eligible_layers, decisions = entitlement.filter_eligible_layers(
            layers,
            state_path=state_path,
            login=login,
            now=entitlement_now,
        )
        bindings = (
            entitlement.bind_layer_decisions(
                layers,
                decisions,
                state_path=state_path,
                login=login,
            )
            if state_path is not None
            else ()
        )
        codex_layers = [
            layer for layer in eligible_layers if layer.get("product") == "codex"
        ]
        if not codex_layers:
            return None, bindings
        validate_layers(codex_layers)
        base = (
            Path(str(resolve_key("paths.mirrors_root"))).expanduser()
            if mirror_root_base is None
            else Path(str(mirror_root_base)).expanduser()
        )
        effective = synthesize_effective_layers(codex_layers, mirror_root_base=base)
        contributions = discover_contributions(effective, dimensions=("plugins",))
        resolved = resolve_layers(effective, contributions)
    except ManifestError as exc:
        raise CodexPluginSourceError(
            "The configured Codex layer manifest is invalid."
        ) from exc
    item = next(
        (
            row
            for row in resolved
            if row.get("dimension") == "plugins" and row.get("item") == "codex-copilot"
        ),
        None,
    )
    if item is None:
        return None, bindings
    layer = next(row for row in effective if row.get("id") == item["winning_layer"])
    source = layer.get("source") or {}
    policy = layer.get("policy") or {}
    source_path = source.get("path")
    ref = source.get("ref")
    signers = policy.get("allowed_signers")
    if not source_path or not isinstance(ref, str) or not isinstance(signers, list):
        raise CodexPluginSourceError(
            "The effective Codex plugin lacks signed source provenance."
        )
    root = _protected_directory(Path(str(source_path)))
    plugin = _protected_directory(root / "plugins/codex-copilot")
    verified = verify_git_item_provenance(
        root, "plugins/codex-copilot", signers, ref=ref
    )
    if verified is None:
        raise CodexPluginSourceError(
            "The effective Codex plugin does not match its authorized signed release."
        )
    snapshot = read_git_tree_snapshot(verified.repository_root, verified.tree)
    if snapshot is None:
        raise CodexPluginSourceError(
            "The signed Codex plugin tree could not be read from its immutable Git object."
        )
    return (
        CodexPluginSource(
            path=plugin,
            repository_root=Path(verified.repository_root),
            relative_path=verified.relative_path,
            layer=str(layer["id"]),
            ref=verified.ref,
            tree=verified.tree,
            signer=verified.signer,
            snapshot=snapshot,
        ),
        bindings,
    )
