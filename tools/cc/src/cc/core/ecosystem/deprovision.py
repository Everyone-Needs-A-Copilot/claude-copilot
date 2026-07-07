"""Wipe the disposable ecosystem trees: the `cc deprovision --json` engine
(MUTATING).

WS-A slice 5 (deprovision-slice). See:
  - copilot-control-tower/docs/01-architecture/schemas/deprovision.schema.json
  - copilot-control-tower/docs/01-architecture/cli-contract.md
  - copilot-control-tower/docs/reference/ecosystem-architecture.md §5.2
    (repair/deprovision split)
  - copilot-control-tower/docs/01-architecture/architecture.md §8.3
    (MDM-native deprovision, the `Deprovisioned` forced-domain flag,
    soft-then-hard)
  - copilot-control-tower/docs/01-architecture/inheritance-and-publish.md
    §2.2 (the three-tree never-destroy model)
  - copilot-control-tower CLAUDE.md invariants #3 ("never-destroy") / #4
    ("security posture is inherited and enforced, never weakened")

THE CRUX (never-destroy, three trees -- same model as materialize.py):
read-only mirror (disposable) -> materialize root (disposable, engine-
owned) -> personal/authoring tree (PROTECTED, never touched).
`deprovision()` only ever deletes (a) items `materialize()` itself
previously placed there, per the lockfile it wrote (`previous_lock`), and
(b) whole mirror-tier clones under `mirror_root` -- it NEVER deletes
anything not recorded as engine-placed (an unrelated file sitting in
`materialize_root` that was never in the lock is simply never considered,
by construction, not by a runtime check that could be bypassed).
`guard_personal()` (materialize.py's hard stop) is re-run here as the same
non-bypassable gate: any path it flags is retained byte-identical,
appended to `retained_dirty`, and never removed or quarantined.

SECRETS: no secret is ever materialized by this engine or by
`materialize()` -- secrets live in the OS keychain / a managed secret
store, never inside a layer's tracked content (excluded by construction:
`materialize.py` only ever writes OVERRIDE/ACCUMULATE dimensions, never
PERSONAL_WRITE/PROJECT_LOCAL). `secrets_touched` is therefore always `0`.
As a belt-and-suspenders, fail-closed defense-in-depth check (not the
primary safety mechanism -- that's the construction above), `deprovision()`
positively refuses to remove/quarantine any path that LOOKS like a secret
(`secrets.env`, `.env`, `credentials.json`, `*.pem`, `*.key`, `*.p12`,
`*.pfx`) by raising rather than silently skipping or silently wiping it --
a secret-shaped path in the wipe set would mean something upstream already
violated the never-materializes-secrets invariant, and that is a hard stop,
not a quiet degrade.

MODE (soft vs hard -- architecture.md §8.3's "soft-then-hard" two-phase):
  - "soft" (the default -- reversible-by-default): removes materialized
    content immediately (the actual on-host security exposure -- the
    confidential content a leaver could otherwise keep, B-C7), but
    QUARANTINES each mirror tier (renames it to
    `<mirror_root>/.quarantine/<tier>` instead of deleting) so a flip-back
    (the MDM `Deprovisioned` flag reverting within the grace window) can
    restore mirrors without a re-clone, per architecture.md §8.3.
  - "hard": removes materialized content AND permanently deletes every
    mirror tier, including anything already sitting in `.quarantine` from
    a prior soft pass -- the full removal.
  OWNER-DEFENSIBLE CHOICE (flag for confirmation at freeze): the real MDM-
  driven debounce/settling-window orchestration (soft now, hard after a
  grace window unless a flip-back cancels it) belongs to whatever calls
  this repeatedly (Control Tower / the MDM agent) -- this one-shot engine
  call performs exactly one phase (soft OR hard) per invocation, with
  "soft" as the safer default per the autonomy rule (prefer the reversible
  method). This slice does not delete `copilot.lock.json` itself in either
  mode -- that pointer file is tiny metadata, not materialized content nor
  a mirror clone; a future slice may fold that into "hard" once the owner
  ratifies it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, Optional, TypedDict

from cc.core.ecosystem.dimensions import ACCUMULATE, OVERRIDE, semantics_for
from cc.core.ecosystem.materialize import _find_source_child, guard_personal

# Dimensions `materialize()` ever writes -- see materialize.py's own
# `_MATERIALIZABLE_SEMANTICS`. Re-checked here defensively: even a
# malformed/hand-edited lockfile claiming ownership of a PERSONAL_WRITE or
# PROJECT_LOCAL dimension item is never wiped by this engine.
_MATERIALIZABLE_SEMANTICS = frozenset({OVERRIDE, ACCUMULATE})

Lockfile = dict[str, dict[str, dict[str, str]]]

_QUARANTINE_DIRNAME = ".quarantine"

# Secret-shaped path patterns -- defense-in-depth only (see module
# docstring). Never expected to actually match anything in the wipe set.
_SECRET_EXACT_NAMES = frozenset({"secrets.env", ".env", "credentials.json"})
_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})


class SecretPathError(RuntimeError):
    """Raised if a path that looks secret-shaped ever lands in the wipe set."""


def _looks_like_secret(path: Path) -> bool:
    return path.name in _SECRET_EXACT_NAMES or path.suffix in _SECRET_SUFFIXES


def _assert_not_secret(path: Path) -> None:
    if _looks_like_secret(path):
        raise SecretPathError(
            f"deprovision: refusing to wipe secret-shaped path {path} -- "
            "secrets must never be materialized (they live in the OS "
            "keychain / managed secret store); this is a fail-closed "
            "belt-and-suspenders guard, not expected to ever trigger."
        )


class DeprovisionOp(TypedDict):
    kind: str  # "materialized" | "mirror"
    dimension: Optional[str]
    layer: Optional[str]
    item: Optional[str]
    tier: Optional[str]
    path: str
    action: str  # "removed" | "quarantined" | "retained" | "failed"
    reason: Optional[str]


class DeprovisionReport(TypedDict):
    ops: list[DeprovisionOp]
    removed_materialized: int
    removed_clones: list[str]
    retained_dirty: list[str]
    secrets_touched: int
    partial: bool


def _safe_remove(target: Path) -> bool:
    """
    Attempt removal; return True if `target` no longer exists afterward
    (removed by us, or was already absent), False if removal was ATTEMPTED
    but failed (permissions, in-use file, etc.) -- surfaced by the caller
    as `partial`, never silently swallowed the way materialize.py's own
    best-effort prune `_remove()` is (that helper is fine for a reconciling
    sync's prune step; a wipe operation needs to know if it actually
    finished).
    """
    try:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    except OSError:
        pass
    return not target.exists()


def deprovision(
    *,
    materialize_root: Path | str,
    mirror_root: Path | str,
    previous_lock: Optional[Lockfile] = None,
    mode: str = "soft",
    personal_roots: Iterable[Path | str] = (),
    dry_run: bool = False,
) -> DeprovisionReport:
    """
    Wipe the disposable trees: every item `previous_lock` records as
    materialized (under `materialize_root`), plus every mirror tier under
    `mirror_root`. The PROTECTED personal/authoring tree is never in
    scope -- `guard_personal()` retains (never removes/quarantines) any
    path it flags, collecting it into `retained_dirty` byte-identical.

    `dry_run=True` computes the exact same plan/counts WITHOUT touching
    disk (mirrors `materialize()`'s own `dry_run` contract) -- a safe
    preview.

    Returns counts + ops; `commands/deprovision.py` shapes this into the
    `deprovision --json` contract.
    """
    if mode not in ("soft", "hard"):
        raise ValueError(f"deprovision: invalid mode {mode!r} -- must be 'soft' or 'hard'")

    previous_lock = previous_lock or {}
    personal_roots = list(personal_roots)
    root = Path(materialize_root).expanduser()
    mroot = Path(mirror_root).expanduser()

    ops: list[DeprovisionOp] = []
    removed_materialized = 0
    removed_clones: list[str] = []
    retained_dirty: list[str] = []
    partial = False

    # --- Materialized content: only what the engine previously placed ---
    for layer_id, dims in previous_lock.items():
        for dimension, items in dims.items():
            if semantics_for(dimension) not in _MATERIALIZABLE_SEMANTICS:
                continue  # never this engine's concern (memory/tasks)

            dim_dir = root / dimension
            for item in items:
                target = _find_source_child(dim_dir, item) if dim_dir.is_dir() else None
                if target is None:
                    continue  # nothing materialized here -- already absent

                if guard_personal(target, personal_roots=personal_roots):
                    retained_dirty.append(str(target))
                    ops.append(
                        {
                            "kind": "materialized",
                            "dimension": dimension,
                            "layer": layer_id,
                            "item": item,
                            "tier": None,
                            "path": str(target),
                            "action": "retained",
                            "reason": "protected: personal/dirty working tree -- never wiped",
                        }
                    )
                    continue

                _assert_not_secret(target)

                if dry_run:
                    removed_materialized += 1
                    ops.append(
                        {
                            "kind": "materialized",
                            "dimension": dimension,
                            "layer": layer_id,
                            "item": item,
                            "tier": None,
                            "path": str(target),
                            "action": "removed",
                            "reason": None,
                        }
                    )
                    continue

                if _safe_remove(target):
                    removed_materialized += 1
                    ops.append(
                        {
                            "kind": "materialized",
                            "dimension": dimension,
                            "layer": layer_id,
                            "item": item,
                            "tier": None,
                            "path": str(target),
                            "action": "removed",
                            "reason": None,
                        }
                    )
                else:
                    partial = True
                    ops.append(
                        {
                            "kind": "materialized",
                            "dimension": dimension,
                            "layer": layer_id,
                            "item": item,
                            "tier": None,
                            "path": str(target),
                            "action": "failed",
                            "reason": "removal attempted but path still exists",
                        }
                    )

    # --- Mirrors: every tier clone under mirror_root ---
    quarantine_dir = mroot / _QUARANTINE_DIRNAME

    def _process_tier(tier_path: Path, *, already_quarantined: bool) -> None:
        nonlocal partial
        tier_name = tier_path.name

        if guard_personal(tier_path, personal_roots=personal_roots):
            retained_dirty.append(str(tier_path))
            ops.append(
                {
                    "kind": "mirror",
                    "dimension": None,
                    "layer": None,
                    "item": None,
                    "tier": tier_name,
                    "path": str(tier_path),
                    "action": "retained",
                    "reason": "protected: personal/dirty working tree -- never wiped",
                }
            )
            return

        _assert_not_secret(tier_path)

        if mode == "hard":
            if dry_run:
                removed_clones.append(tier_name)
                ops.append(
                    {
                        "kind": "mirror", "dimension": None, "layer": None, "item": None,
                        "tier": tier_name, "path": str(tier_path), "action": "removed",
                        "reason": None,
                    }
                )
                return
            if _safe_remove(tier_path):
                removed_clones.append(tier_name)
                ops.append(
                    {
                        "kind": "mirror", "dimension": None, "layer": None, "item": None,
                        "tier": tier_name, "path": str(tier_path), "action": "removed",
                        "reason": None,
                    }
                )
            else:
                partial = True
                ops.append(
                    {
                        "kind": "mirror", "dimension": None, "layer": None, "item": None,
                        "tier": tier_name, "path": str(tier_path), "action": "failed",
                        "reason": "removal attempted but path still exists",
                    }
                )
            return

        # mode == "soft" and not already sitting in quarantine: relocate,
        # don't delete, so a flip-back restores without a re-clone.
        if already_quarantined:
            # A prior soft pass already quarantined this tier and no hard
            # pass has run yet -- nothing further to do this invocation.
            return

        destination = quarantine_dir / tier_name
        if dry_run:
            removed_clones.append(tier_name)
            ops.append(
                {
                    "kind": "mirror", "dimension": None, "layer": None, "item": None,
                    "tier": tier_name, "path": str(tier_path), "action": "quarantined",
                    "reason": None,
                }
            )
            return

        try:
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            shutil.move(str(tier_path), str(destination))
            moved = not tier_path.exists()
        except OSError:
            moved = False

        if moved:
            removed_clones.append(tier_name)
            ops.append(
                {
                    "kind": "mirror", "dimension": None, "layer": None, "item": None,
                    "tier": tier_name, "path": str(tier_path), "action": "quarantined",
                    "reason": None,
                }
            )
        else:
            partial = True
            ops.append(
                {
                    "kind": "mirror", "dimension": None, "layer": None, "item": None,
                    "tier": tier_name, "path": str(tier_path), "action": "failed",
                    "reason": "quarantine move attempted but path still exists",
                }
            )

    if mroot.is_dir():
        active_tiers = sorted(
            p for p in mroot.iterdir() if p.is_dir() and p.name != _QUARANTINE_DIRNAME
        )
        for tier_path in active_tiers:
            _process_tier(tier_path, already_quarantined=False)

        # "hard" also purges anything a prior "soft" pass already parked in
        # quarantine -- the full removal.
        if mode == "hard" and quarantine_dir.is_dir():
            for tier_path in sorted(p for p in quarantine_dir.iterdir() if p.is_dir()):
                _process_tier(tier_path, already_quarantined=True)

    return {
        "ops": ops,
        "removed_materialized": removed_materialized,
        "removed_clones": removed_clones,
        "retained_dirty": retained_dirty,
        "secrets_touched": 0,
        "partial": partial,
    }
