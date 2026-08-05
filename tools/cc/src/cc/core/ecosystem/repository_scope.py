"""Proven repository scope for project reconciliation.

Project discovery intentionally finds every Git checkout below an approved
root. The ecosystem layer manifest is the separate authority that says which
of those checkouts are Copilot component repositories rather than product
projects. A checkout is managed separately only when both facts agree:

* a validated layer declares its literal local ``source.path``; and
* that checkout's Git ``origin`` has the same canonical GitHub identity as the
  layer's ``source.repo``.

Names are never evidence. This keeps ordinary products such as
``method-copilot`` in project reconciliation while excluding every proven
Foundation/Organization/Department/Personal component checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypedDict
from urllib.parse import urlsplit

from cc.core.config import resolve_key
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers

Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

ECOSYSTEM_PRODUCTS = frozenset({"claude", "codex", "knowledge", "cli"})


class RepositoryScope(TypedDict):
    kind: str
    product: str
    role: str
    layer_id: str
    repository: str


def repository_identity(value: Any) -> str | None:
    """Return canonical ``owner/repository`` identity for GitHub transports."""
    if not isinstance(value, str) or not value:
        return None
    candidate = value.strip()
    if candidate.startswith("git@") and ":" in candidate:
        candidate = candidate.split(":", 1)[1]
    else:
        parsed = urlsplit(candidate)
        if parsed.hostname and parsed.hostname.casefold() == "github.com":
            candidate = parsed.path
    candidate = candidate.strip("/")
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    parts = candidate.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return "/".join(parts).casefold()


def _run_git(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _git_root(path: Path) -> bool:
    try:
        marker = path / ".git"
        return marker.is_dir() or marker.is_file()
    except OSError:
        return False


def managed_ecosystem_repositories(
    *,
    manifest_source: Path | str | list[dict[str, Any]] | None = None,
    run: Run = _run_git,
) -> dict[str, RepositoryScope]:
    """Return checkout path -> proven ecosystem-management metadata.

    Missing, malformed, ambiguous, symlinked, or wrong-origin evidence never
    excludes a project. The manifest/doctor surfaces remain responsible for
    reporting those ecosystem problems; project reconciliation simply refuses
    to guess across the boundary.
    """
    source: Path | str | list[dict[str, Any]] | None = manifest_source
    if source is None:
        source = resolve_key("layers.manifest")
    if not source:
        return {}
    try:
        layers = validate_layers(load_layers(source))
    except (ManifestError, OSError, TypeError, ValueError):
        return {}

    scopes: dict[str, RepositoryScope] = {}
    conflicts: set[str] = set()
    for layer in layers:
        product = layer.get("product")
        role = layer.get("role")
        layer_id = layer.get("id")
        layer_source = layer.get("source")
        if (
            product not in ECOSYSTEM_PRODUCTS
            or not isinstance(role, str)
            or not role
            or not isinstance(layer_id, str)
            or not layer_id
            or not isinstance(layer_source, Mapping)
        ):
            continue
        expected = repository_identity(layer_source.get("repo"))
        raw_path = layer_source.get("path")
        if not expected or not isinstance(raw_path, str) or not raw_path:
            continue
        checkout = Path(raw_path).expanduser()
        try:
            if (
                not checkout.is_absolute()
                or checkout.is_symlink()
                or not checkout.is_dir()
            ):
                continue
            resolved = checkout.resolve(strict=True)
        except OSError:
            continue
        if not _git_root(resolved):
            continue
        try:
            origin = run(
                ("git", "-C", str(resolved), "remote", "get-url", "origin")
            )
        except (OSError, subprocess.SubprocessError):
            continue
        actual = (
            repository_identity(origin.stdout.strip())
            if origin.returncode == 0
            else None
        )
        if actual != expected:
            continue
        key = str(resolved)
        scope: RepositoryScope = {
            "kind": "ecosystem-repository",
            "product": str(product),
            "role": role,
            "layer_id": layer_id,
            "repository": expected,
        }
        previous = scopes.get(key)
        if previous is not None and previous != scope:
            conflicts.add(key)
            continue
        scopes[key] = scope

    for key in conflicts:
        scopes.pop(key, None)
    return scopes


__all__ = [
    "ECOSYSTEM_PRODUCTS",
    "RepositoryScope",
    "managed_ecosystem_repositories",
    "repository_identity",
]
