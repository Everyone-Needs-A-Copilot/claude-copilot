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
  - `local_sha`: when the source publishes a lock-pointer ref, a
    git-blob-sha1 fingerprint (the SAME canonical-JSON
    scheme `core/ecosystem/freshness.py`'s `lock_fingerprint()` already
    uses for the whole-lockfile fingerprint) of just that layer's slice of
    the local lockfile (`core/ecosystem/lockfile.py`). When no lock-pointer
    exists and the already-cloned mirror is the only available comparison,
    `local_sha` is instead the exact source commit recorded by the last
    successful update under the layer's `_meta.source_sha`. `None` when
    the comparable local identity is unknown -- an honest "unknown", never
    a fabricated sha.
  - `remote_sha`: the layer's published lock-pointer ref when present. If
    the repository answers but that optional pointer is absent, the declared
    source ref is used instead and compared with the visible checkout HEAD
    (or the recorded source commit when no checkout HEAD is readable). This
    is the common Personal-repository shape. An already-cloned hidden mirror
    remains the offline fallback used by inherited layers. No path here ever
    clones, fetches, or resolves `Path.home()`.

Severity fold (never fabricated):
  - `remote_sha is None` after no remote response -> `warn`, and the
    caller-visible `any_offline` return value is set -- "could not reach
    remote to verify sync", never coerced into pass or fail.
  - the repository answered but neither the pointer nor declared source ref
    exists -> `warn` without an offline signal.
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
from cc.core.ecosystem.lockfile import LAYER_META_KEY, layer_meta

LatestShaResult = Optional[str] | mirror.RemoteRefProbe
LatestShaFn = Callable[[str, str], LatestShaResult]


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
    layer_role: Optional[str] = None
    product: Optional[str] = None
    detail: str = ""
    repair: Optional[str] = None
    path: Optional[str] = None
    local_sha: Optional[str] = None
    remote_sha: Optional[str] = None

    def to_contract_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "severity": self.severity,
            "destructive": self.destructive,
        }
        if self.layer:
            d["layer"] = self.layer
        if self.layer_role:
            d["layer_role"] = self.layer_role
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
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _mirror_clone_head_sha(
    tier: str,
    *,
    product: Optional[str],
    mirror_root: Optional[Path | str],
) -> Optional[str]:
    """
    Best-effort local HEAD of an already-cloned mirror for `tier`, when one
    exists on disk. Never clones/fetches anything itself, and never
    resolves `Path.home()` -- `mirror_root=None` (nothing configured or
    injected) cleanly skips this fallback rather than guessing a location.
    """
    if not tier or not mirror_root:
        return None
    base = Path(mirror_root).expanduser()
    root = (
        base / product / tier
        if product in {"knowledge", "cli"}
        else mirror.mirror_root(tier, _root=base)
    )
    if not (root / ".git").is_dir():
        return None
    result = _run_git(["rev-parse", "HEAD"], cwd=root)
    if result is None or result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _visible_checkout_head_sha(layer: dict[str, Any]) -> Optional[str]:
    """Read HEAD from the layer's configured visible checkout, if present."""
    source = layer.get("source") or {}
    configured = source.get("path")
    if not configured:
        return None
    root = Path(str(configured)).expanduser()
    if not root.is_dir():
        return None
    result = _run_git(["rev-parse", "HEAD"], cwd=root)
    if result is None or result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _matches_foundation_release_snapshot(
    layer: dict[str, Any], *, local_sha: Optional[str], remote_sha: str
) -> bool:
    """Prove a visible checkout matches a disconnected Foundation snapshot.

    Foundation releases are published as annotated tags whose peeled commit is
    a parentless, immutable snapshot. The authoring checkout can therefore have
    a different commit identity while carrying the exact released tree. Keep
    this exception deliberately narrow: no other role, lightweight/ordinary
    tag, branch, missing local ref, or tree mismatch can pass through it.
    """
    if layer.get("role") != "foundation" or not local_sha:
        return False

    source = layer.get("source") or {}
    configured = source.get("path")
    declared_ref = source.get("ref")
    if not configured or not declared_ref:
        return False
    root = Path(str(configured)).expanduser()
    if not root.is_dir():
        return False

    object_type = _run_git(["cat-file", "-t", str(declared_ref)], cwd=root)
    peeled = _run_git(["rev-parse", f"{declared_ref}^{{}}"], cwd=root)
    parents = _run_git(
        ["rev-list", "--parents", "-n", "1", f"{declared_ref}^{{}}"], cwd=root
    )
    head_tree = _run_git(["rev-parse", f"{local_sha}^{{tree}}"], cwd=root)
    snapshot_tree = _run_git(
        ["rev-parse", f"{declared_ref}^{{tree}}"], cwd=root
    )
    results = (object_type, peeled, parents, head_tree, snapshot_tree)
    if any(result is None or result.returncode != 0 for result in results):
        return False

    assert object_type is not None
    assert peeled is not None
    assert parents is not None
    assert head_tree is not None
    assert snapshot_tree is not None
    parent_fields = parents.stdout.strip().split()
    return (
        object_type.stdout.strip() == "tag"
        and peeled.stdout.strip() == remote_sha
        and len(parent_fields) == 1
        and parent_fields[0] == remote_sha
        and head_tree.stdout.strip() == snapshot_tree.stdout.strip()
    )


def _normalize_probe(result: LatestShaResult) -> mirror.RemoteRefProbe:
    """Accept the historical Optional[str] test seam and the richer probe."""
    if isinstance(result, mirror.RemoteRefProbe):
        return result
    if result is None:
        return mirror.RemoteRefProbe(reachable=False, sha=None)
    return mirror.RemoteRefProbe(reachable=True, sha=result)


def _remote_sha_for_layer(
    layer: dict[str, Any],
    *,
    latest_sha_fn: LatestShaFn,
    mirror_root: Optional[Path | str],
) -> tuple[Optional[str], str, bool]:
    source = layer.get("source") or {}
    repo = source.get("repo")
    if not repo:
        return None, "unknown", False

    ref = source.get("lock_ref") or mirror.DEFAULT_LOCK_POINTER_REF
    lock_probe = _normalize_probe(latest_sha_fn(repo, ref))
    if lock_probe.sha is not None:
        return lock_probe.sha, "lock", True

    # A successful empty response means the repository is reachable and only
    # the optional lock pointer is absent. Personal repositories commonly use
    # this shape. Their declared source branch is the next honest identity to
    # compare; a second absent ref remains a warning, but never "offline"
    # because the first response already proved reachability.
    if lock_probe.reachable:
        source_ref = source.get("ref") or "main"
        source_probe = _normalize_probe(latest_sha_fn(repo, source_ref))
        if source_probe.sha is not None:
            return source_probe.sha, "source", True
        return None, "missing", True

    mirror_sha = _mirror_clone_head_sha(
        layer.get("id", ""),
        product=layer.get("product"),
        mirror_root=mirror_root,
    )
    return (
        mirror_sha,
        "source" if mirror_sha is not None else "unknown",
        mirror_sha is not None,
    )


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

        remote_sha, comparison_kind, remote_reachable = _remote_sha_for_layer(
            layer, latest_sha_fn=latest_sha_fn, mirror_root=mirror_root
        )
        local_sha = (
            _visible_checkout_head_sha(layer)
            or layer_meta(lock, layer_id).get("source_sha")
            if comparison_kind in {"source", "missing"}
            else _local_sha_for_layer(lock, layer_id)
        )
        checker_id = f"{product}-{layer_id}-sync"
        raw_role = str(layer.get("role") or "")
        layer_role = {
            "org": "organization",
            "organization": "organization",
            "dept": "department",
            "department": "department",
            "personal": "personal",
            "foundation": "foundation",
        }.get(raw_role, raw_role or None)

        if remote_sha is None and not remote_reachable:
            any_offline = True
            checkers.append(
                Checker(
                    id=checker_id,
                    severity="warn",
                    layer=layer_id,
                    layer_role=layer_role,
                    product=product,
                    detail=f"{product}/{layer_id}: could not reach remote to verify sync",
                    local_sha=local_sha,
                    remote_sha=None,
                )
            )
        elif remote_sha is None:
            checkers.append(
                Checker(
                    id=checker_id,
                    severity="warn",
                    layer=layer_id,
                    layer_role=layer_role,
                    product=product,
                    detail=(
                        f"{product}/{layer_id}: remote is reachable but the "
                        "declared sync reference is missing"
                    ),
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
                    layer_role=layer_role,
                    product=product,
                    detail=f"{product}/{layer_id}: tip matches remote",
                    local_sha=local_sha,
                    remote_sha=remote_sha,
                )
            )
        elif comparison_kind == "source" and _matches_foundation_release_snapshot(
            layer, local_sha=local_sha, remote_sha=remote_sha
        ):
            checkers.append(
                Checker(
                    id=checker_id,
                    severity="pass",
                    layer=layer_id,
                    layer_role=layer_role,
                    product=product,
                    detail=(
                        f"{product}/{layer_id}: checkout content matches remote "
                        "Foundation release snapshot"
                    ),
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
                    layer_role=layer_role,
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
