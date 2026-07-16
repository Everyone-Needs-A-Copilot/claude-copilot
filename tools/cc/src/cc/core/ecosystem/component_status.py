"""Per-(product, layer) sync-status checkers -- the `doctor --json` engine slice.

WS-A doctor-completion (Stream-B): computes one local-vs-remote sync
`Checker` per manifest layer, folding into `cc doctor --json`'s
`checkers[]` alongside the config-only checkers `commands/doctor.py`
already emits. `Checker` used to live in `commands/doctor.py`; it moved
here so this core module can build one without `commands/doctor.py`
importing back from a `commands` module (core never depends on commands).

Every manifest layer belongs to exactly one product x tier
(`core/ecosystem/manifest.py`'s own docstring: "a layer belongs to
exactly one product x tier"), so "layer x product it carries" reduces to
one checker per layer, keyed off that layer's own `product` field.

Per layer, this compares:
  - `local_sha`: a git-blob-sha1 fingerprint (the SAME canonical-JSON
    scheme `core/ecosystem/freshness.py`'s `lock_fingerprint()` already
    uses for the whole-lockfile fingerprint) of just that layer's slice of
    the local lockfile (`core/ecosystem/lockfile.py`). `None` when the
    layer has no recorded lock entry yet (nothing materialized locally) --
    an honest "unknown", never a fabricated sha.
  - `remote_sha`: the layer's published lock-pointer ref
    (`core/ecosystem/mirror.py`'s `latest_lock_sha()`, a single cheap
    `git ls-remote` -- never a full clone/fetch), falling back to an
    already-cloned mirror's local HEAD commit (`git rev-parse HEAD` inside
    `<mirror_root>/<layer id>`) ONLY when a `mirror_root` was actually
    supplied AND a mirror already exists there -- this module never clones
    anything itself and never resolves `Path.home()` (mirrors this
    codebase's "every I/O root injectable" rule -- see `update.py`'s
    module docstring). This fallback is a weaker signal (a content-tree
    commit sha, not a lock-pointer blob sha) but still an honest,
    non-fabricated value.

Severity fold (never fabricated):
  - `remote_sha is None` (neither lookup answered) -> `warn`, and the
    caller-visible `any_offline` return value is set -- "could not reach
    remote to verify sync", never coerced into pass or fail.
  - `local_sha == remote_sha` -> `pass`.
  - otherwise -> `warn` ("behind"), with a `repair: "cc update"` hint.

This module never emits `severity: "fail"` -- a sync gap is a `warn`
("update-available"-flavored), not a hard failure; `doctor.py`'s status
ladder is what decides how a `warn` here folds into the overall verdict.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from cc.core.ecosystem import mirror
from cc.core.ecosystem.freshness import lock_fingerprint
from cc.core.ecosystem.lockfile import LAYER_META_KEY

LatestShaFn = Callable[[str, str], Optional[str]]


@dataclass
class Checker:
    """A single, discretely-identified health check result.

    Shared by both the config-only checkers `commands/doctor.py` builds
    directly and the sync checkers this module builds, so the two
    representations can never drift apart (both funnel through the same
    `to_contract_dict()`).
    """

    id: str
    severity: str  # "pass" | "warn" | "fail"
    destructive: bool = False
    layer: Optional[str] = None
    product: Optional[str] = None
    detail: str = ""
    repair: Optional[str] = None
    path: Optional[str] = None
    local_sha: Optional[str] = None
    remote_sha: Optional[str] = None

    def to_contract_dict(self) -> dict:
        d: dict = {"id": self.id, "severity": self.severity, "destructive": self.destructive}
        if self.layer:
            d["layer"] = self.layer
        if self.product:
            d["product"] = self.product
        if self.detail:
            d["detail"] = self.detail
        if self.repair:
            d["repair"] = self.repair
        if self.path:
            d["path"] = self.path
        if self.local_sha:
            d["local_sha"] = self.local_sha
        if self.remote_sha:
            d["remote_sha"] = self.remote_sha
        return d


def _local_sha_for_layer(lock: dict[str, Any], layer_id: str) -> Optional[str]:
    """
    Fingerprint of `layer_id`'s slice of the local lockfile, excluding the
    reserved `_meta` descriptive block (product/tier/role -- not a content
    pin). `None` when the layer has no recorded entry at all (or only
    `_meta`) -- nothing materialized locally yet is an honest unknown, not
    a fabricated sha.
    """
    entry = lock.get(layer_id)
    if not entry:
        return None
    dims = {k: v for k, v in entry.items() if k != LAYER_META_KEY}
    if not dims:
        return None
    return lock_fingerprint(dims)


def _run_git(
    args: list[str], *, cwd: Path, timeout: float = 5.0
) -> Optional["subprocess.CompletedProcess[str]"]:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _mirror_clone_head_sha(tier: str, *, mirror_root: Optional[Path | str]) -> Optional[str]:
    """
    Best-effort local HEAD of an already-cloned mirror for `tier`, when one
    exists on disk. Never clones/fetches anything itself, and never
    resolves `Path.home()` -- `mirror_root=None` (nothing configured or
    injected) cleanly skips this fallback rather than guessing a location.
    """
    if not tier or not mirror_root:
        return None
    root = mirror.mirror_root(tier, _root=mirror_root)
    if not (root / ".git").is_dir():
        return None
    result = _run_git(["rev-parse", "HEAD"], cwd=root)
    if result is None or result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _remote_sha_for_layer(
    layer: dict[str, Any],
    *,
    latest_sha_fn: LatestShaFn,
    mirror_root: Optional[Path | str],
) -> Optional[str]:
    source = layer.get("source") or {}
    repo = source.get("repo")
    if not repo:
        return None

    ref = source.get("lock_ref") or mirror.DEFAULT_LOCK_POINTER_REF
    remote = latest_sha_fn(repo, ref)
    if remote is not None:
        return remote

    return _mirror_clone_head_sha(layer.get("id", ""), mirror_root=mirror_root)


def compute_component_checkers(
    layers: list[dict[str, Any]],
    *,
    lockfile: Optional[dict[str, Any]] = None,
    latest_sha_fn: LatestShaFn = mirror.latest_lock_sha,
    mirror_root: Optional[Path | str] = None,
) -> tuple[list[Checker], bool]:
    """
    Compute one sync `Checker` per manifest layer.

    Returns `(checkers, any_remote_unreachable)` -- the second value lets
    the caller (`commands/doctor.py`) fold "could not reach at least one
    remote" into the top-level `offline` field/status ladder without
    re-deriving it from checker text.
    """
    lock = lockfile if lockfile is not None else {}
    checkers: list[Checker] = []
    any_offline = False

    for layer in layers:
        layer_id = layer.get("id")
        product = layer.get("product")
        if not layer_id or not product:
            # Malformed layer -- `validate_layers()` should already have
            # rejected this upstream; skip defensively rather than crash a
            # health check on a layer this module can't attribute.
            continue

        local_sha = _local_sha_for_layer(lock, layer_id)
        remote_sha = _remote_sha_for_layer(
            layer, latest_sha_fn=latest_sha_fn, mirror_root=mirror_root
        )
        checker_id = f"{product}-{layer_id}-sync"

        if remote_sha is None:
            any_offline = True
            checkers.append(
                Checker(
                    id=checker_id,
                    severity="warn",
                    layer=layer_id,
                    product=product,
                    detail=f"{product}/{layer_id}: could not reach remote to verify sync",
                    local_sha=local_sha,
                    remote_sha=None,
                )
            )
        elif local_sha == remote_sha:
            checkers.append(
                Checker(
                    id=checker_id,
                    severity="pass",
                    layer=layer_id,
                    product=product,
                    detail=f"{product}/{layer_id}: tip matches remote",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                )
            )
        else:
            checkers.append(
                Checker(
                    id=checker_id,
                    severity="warn",
                    layer=layer_id,
                    product=product,
                    detail=(
                        f"{product}/{layer_id}: local {local_sha or 'none'} "
                        f"behind remote {remote_sha}"
                    ),
                    repair="cc update",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                )
            )

    return checkers, any_offline
