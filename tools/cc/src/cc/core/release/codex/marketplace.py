"""Generate `codex-marketplace/` inside a release (ADR-001 decision 3).

Plugins come from the foundation component and the codex tier overlays; the
first tier to claim a plugin name wins and later duplicates are recorded as
shadowed. Plugin directories are copied verbatim (Codex drops symlinks at
install and hashes the whole directory for hook trust), so a symlink anywhere
in a plugin is a build error and the directory digest is recorded per release.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from cc.core.release.engine import layout, pointer, schema

MARKETPLACE_NAME = "enac-materialized"
RECEIPT_NAME = "marketplace-receipt.json"
MANIFEST_RELATIVE = Path(".agents") / "plugins" / "marketplace.json"
PLUGIN_MANIFEST = Path(".codex-plugin") / "plugin.json"
HOOKS_RELATIVE = Path("hooks") / "hooks.json"
_IGNORED = ("__pycache__", ".DS_Store", ".git")

# Plugin source roots in precedence order: (component path, tier label).
PLUGIN_ROOTS = (
    (layout.COMPONENT_CODEX, layout.TIER_FOUNDATION),
    (f"codex/{layout.TIER_ORGANIZATION}", layout.TIER_ORGANIZATION),
    (f"codex/{layout.TIER_DEPARTMENT_ACCOUNTING}", layout.TIER_DEPARTMENT_ACCOUNTING),
    (f"codex/{layout.TIER_PERSONAL}", layout.TIER_PERSONAL),
)


class MarketplaceError(RuntimeError):
    """The marketplace cannot be generated or violates a release invariant."""


@dataclass(frozen=True)
class PluginEntry:
    name: str
    version: str
    tier: str
    component: str
    digest: str
    hooks_sha256: str | None


def tree_digest(root: Path) -> str:
    """Digest of every file path and byte under `root` (symlinks not followed)."""
    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED)
        for name in sorted(filenames):
            if name in _IGNORED or name.endswith(".pyc"):
                continue
            path = Path(dirpath, name)
            digest.update(str(path.relative_to(root)).encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _symlinks(root: Path) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED]
        for name in dirnames + filenames:
            if Path(dirpath, name).is_symlink():
                found.append(str(Path(dirpath, name).relative_to(root)))
    return sorted(found)


def _read_plugin(directory: Path) -> tuple[str, str]:
    try:
        data = json.loads((directory / PLUGIN_MANIFEST).read_text(encoding="utf-8"))
        name, version = data["name"], data["version"]
    except (OSError, ValueError, KeyError) as exc:
        raise MarketplaceError(f"{directory}: unreadable {PLUGIN_MANIFEST}: {exc}") from exc
    if not isinstance(name, str) or not isinstance(version, str) or not name or not version:
        raise MarketplaceError(f"{directory}: plugin name and version must be non-empty strings")
    return name, version


def _file_sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def generate(release_directory: Path) -> dict:
    """Copy plugins into `release_directory/codex-marketplace`; return the receipt dict."""
    market = release_directory / layout.MARKETPLACE_DIRNAME
    if market.exists():
        raise MarketplaceError(f"{market} already exists")
    claimed: dict[str, PluginEntry] = {}
    shadowed: list[dict] = []
    for component, tier in PLUGIN_ROOTS:
        plugins_dir = release_directory / component / "plugins"
        if not plugins_dir.is_dir():
            continue
        for source in sorted(p for p in plugins_dir.iterdir() if (p / PLUGIN_MANIFEST).is_file()):
            name, version = _read_plugin(source)
            if name in claimed:
                shadowed.append({"name": name, "tier": tier, "component": component,
                                 "version": version, "winner": claimed[name].tier})
                continue
            links = _symlinks(source)
            if links:
                raise MarketplaceError(
                    f"{name}: symlinks are dropped by Codex at install: {', '.join(links)}"
                )
            target = market / "plugins" / name
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(*_IGNORED, "*.pyc"))
            claimed[name] = PluginEntry(name, version, tier, component, tree_digest(target),
                                        _file_sha(target / HOOKS_RELATIVE))
    foundation = layout.COMPONENT_CODEX
    if foundation not in claimed:
        raise MarketplaceError(f"foundation plugin {foundation!r} not found in the release")
    document = {
        "name": MARKETPLACE_NAME,
        "interface": {"displayName": "Copilot Control Tower"},
        "plugins": [
            {
                "name": entry.name,
                "source": {"source": "local", "path": f"./plugins/{entry.name}"},
                "policy": {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
            for entry in claimed.values()
        ],
    }
    (market / MANIFEST_RELATIVE).parent.mkdir(parents=True, exist_ok=True)
    (market / MANIFEST_RELATIVE).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return {
        "schema": 1,
        "marketplace": MARKETPLACE_NAME,
        "release": release_directory.name,
        "plugins": [
            {"name": e.name, "version": e.version, "tier": e.tier, "component": e.component,
             "digest": e.digest, "hooksSha256": e.hooks_sha256}
            for e in claimed.values()
        ],
        "shadowed": shadowed,
    }


def load_receipt(release_directory: Path) -> dict:
    path = release_directory / layout.MARKETPLACE_DIRNAME / RECEIPT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema"] != 1 or not isinstance(data["plugins"], list):
            raise ValueError("unsupported receipt")
    except (OSError, ValueError, KeyError) as exc:
        raise MarketplaceError(f"cannot read marketplace receipt {path}: {exc}") from exc
    return data


def compare_with_previous(receipt: dict, previous_root: Path | None,
                          retrust: Iterable[str] | bool = ()) -> dict:
    """Enforce hooks.json stability; return receipt additions.

    Fails when a plugin's hooks.json bytes changed from the previous release
    unless `retrust` is True or names the plugin. Whole-directory changes (which
    also move Codex's content hash) are listed, not failed.
    """
    declared = sorted(p["name"] for p in receipt["plugins"]) if retrust is True else sorted(retrust or ())
    additions = {"retrust": declared, "trustContentChanged": []}
    if previous_root is None:
        return additions
    try:
        before = {p["name"]: p for p in load_receipt(previous_root)["plugins"]}
    except MarketplaceError:
        return additions  # previous release predates the marketplace
    broken = []
    for plugin in receipt["plugins"]:
        old = before.get(plugin["name"])
        if old is None:
            continue
        if old["digest"] != plugin["digest"]:
            additions["trustContentChanged"].append(plugin["name"])
        if old["hooksSha256"] != plugin["hooksSha256"] and plugin["name"] not in declared:
            broken.append(plugin["name"])
    if broken:
        raise MarketplaceError(
            "hooks.json bytes changed from the previous release without a declared re-trust: "
            + ", ".join(broken)
        )
    return additions


def build_marketplace(release_directory: Path, previous_root: Path | None = None, *,
                      retrust: Iterable[str] | bool = (), strict_frozen: bool = False) -> dict:
    receipt = generate(release_directory)
    receipt.update(compare_with_previous(receipt, previous_root, retrust))
    changed = receipt["trustContentChanged"]
    if strict_frozen and changed and not set(changed) <= set(receipt["retrust"]):
        raise MarketplaceError("plugin directory changed (Codex content trust would reset): "
                               + ", ".join(sorted(set(changed) - set(receipt["retrust"]))))
    (release_directory / layout.MARKETPLACE_DIRNAME / RECEIPT_NAME).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def make_post_build(home: Path | str | None = None, *, retrust: Iterable[str] | bool = (),
                    strict_frozen: bool = False
                    ) -> Callable[[Path, Sequence[schema.Component]], None]:
    """A `build_release(post_build=...)` hook; compares against the current release."""
    def hook(target: Path, _components: Sequence[schema.Component]) -> None:
        current = pointer.current_release_id(home)
        previous = layout.release_dir(current, home) if current else None
        build_marketplace(target, previous, retrust=retrust, strict_frozen=strict_frozen)
    return hook
