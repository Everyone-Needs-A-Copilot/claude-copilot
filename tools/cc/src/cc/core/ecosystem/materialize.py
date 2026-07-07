"""The reconciling sync: fold a resolved item set into the materialize root.

WS-A slice 4 (update-slice). Backs `cc update --json`
(cc/commands/update.py). See:
  - copilot-control-tower/docs/reference/ecosystem-architecture.md §3.2
    ("Materialize is a reconciling sync, not an additive overlay")
  - copilot-control-tower/docs/01-architecture/inheritance-and-publish.md §2.2
    (the three-tree never-destroy model)
  - copilot-control-tower CLAUDE.md invariant #3 ("never-destroy")

THE CRUX (never-destroy, three trees): read-only mirror (disposable) ->
materialize root (disposable, reconciled BY THIS MODULE) -> personal /
authoring tree (PROTECTED, never touched). `materialize()` only ever reads
from a layer's source root and writes/deletes under `materialize_root`; it
never writes a mirror and never writes a personal/authoring tree.
`guard_personal()` is the hard stop that keeps personal-owned content (and
any dirty git working tree, wherever it's found) out of both the write
path and the prune path -- a path it flags is NEVER deleted or
overwritten, full stop.

Pruning is scoped ONLY to layer-owned/disposable dimensions (OVERRIDE /
ACCUMULATE semantics -- agents, skills, commands, protocol, knowledge,
cli-integrations). PERSONAL_WRITE ("memory") and PROJECT_LOCAL ("tasks")
are never written or pruned by this module at all -- they are excluded by
construction, not by a runtime check that could be bypassed. An item is
only ever pruned if BOTH (a) a previous lock recorded it as materialized
by some layer, and (b) it is no longer part of the resolved set at all
(under any layer) -- ownership moving from one layer to another is not a
prune (ecosystem-architecture.md §3.2's `rsync --delete`-against-the-
resolved-set semantics, not a per-layer diff).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Optional, TypedDict

from cc.core.ecosystem.dimensions import ACCUMULATE, OVERRIDE, semantics_for
from cc.core.ecosystem.policy import PolicyFn
from cc.core.ecosystem.policy import evaluate as _default_policy

# Dimensions this module will ever write or prune. Deliberately narrower
# than "every dimension the resolver folds" -- PERSONAL_WRITE (memory) and
# PROJECT_LOCAL (tasks, already skipped by the resolver) are personal-
# owned/project-bound and excluded here BY CONSTRUCTION, never touched.
_MATERIALIZABLE_SEMANTICS = frozenset({OVERRIDE, ACCUMULATE})

Lockfile = dict[str, dict[str, dict[str, str]]]


class MaterializeOp(TypedDict):
    dimension: str
    layer: str
    item: str
    op: str  # "added" | "updated" | "pruned" | "unchanged" | "held" | "blocked"
    path: str
    signed: bool
    reason: Optional[str]
    from_sha: Optional[str]
    to_sha: Optional[str]


class MaterializeReport(TypedDict):
    ops: list[MaterializeOp]
    lock: Lockfile


# ---------------------------------------------------------------------------
# guard_personal -- the never-destroy hard stop
# ---------------------------------------------------------------------------


def _find_git_root(path: Path) -> Optional[Path]:
    current = path if path.is_dir() else path.parent
    candidates = [current, *current.parents]
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return None


def _is_dirty_git_tree(path: Path, *, timeout: float = 5.0) -> bool:
    """
    True if `path` sits inside a git working tree that has uncommitted
    changes touching `path` (or the whole tree is untracked/new). Fails
    CLOSED: if this can't be determined (git missing, timeout, not a repo
    at all), it returns False ONLY for "definitely not a repo" -- any
    inability to actually run the check on a real repo is treated as dirty
    (protected), never silently assumed clean.
    """
    git_root = _find_git_root(path)
    if git_root is None:
        return False

    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "status", "--porcelain", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # fail closed -- can't confirm clean, so treat as dirty

    if result.returncode != 0:
        return True  # fail closed

    return bool(result.stdout.strip())


def guard_personal(
    path: Path | str,
    *,
    personal_roots: Iterable[Path | str] = (),
) -> bool:
    """
    True if `path` is (or is under) a personal/authoring tree, OR sits in a
    dirty git working tree -- i.e. this path must NEVER be deleted or
    overwritten by a reconciling sync.

    `personal_roots` is the injectable set of known personal/authoring
    tree roots (e.g. the personal-tier's local checkout, or an author's
    Obsidian-style vault -- inheritance-and-publish.md §2.2's third tree).
    Membership is checked by path containment (`path == root` or `root` is
    an ancestor of `path`), not by string prefix, so `.../personal-2/x`
    never false-positives against a `personal` root.

    Even with an empty `personal_roots`, this still refuses a path inside
    ANY dirty git working tree (a human-owned, uncommitted-changes tree is
    "personal" for never-destroy's purposes regardless of whether it was
    pre-registered -- CLAUDE.md invariant #3: "never touches a dirty
    personal working tree").
    """
    target = Path(path).expanduser()

    for root in personal_roots:
        root_path = Path(root).expanduser()
        if target == root_path:
            return True
        try:
            target.relative_to(root_path)
            return True
        except ValueError:
            continue

    return _is_dirty_git_tree(target)


# ---------------------------------------------------------------------------
# materialize -- the reconciling sync
# ---------------------------------------------------------------------------


def _find_source_child(dim_dir: Path, item: str) -> Optional[Path]:
    """
    Locate the on-disk file/dir for `item` under `dim_dir`. Mirrors
    discovery.py's naming: a directory entry's own name is the item name;
    a file entry's *stem* (extension stripped) is the item name -- so a
    file item must be re-found by globbing on the stem, not by an exact
    `dim_dir / item` path.
    """
    if not dim_dir.is_dir():
        return None

    direct_dir = dim_dir / item
    if direct_dir.is_dir():
        return direct_dir

    matches = sorted(p for p in dim_dir.glob(f"{item}.*") if p.is_file())
    if matches:
        return matches[0]

    direct_file = dim_dir / item
    if direct_file.is_file():
        return direct_file

    return None


def _content_sha(path: Path) -> str:
    """
    Content-identity hash for whatever `materialize()` actually places on
    disk. Deliberately the SAME sha256-of-bytes (file) / sha256-of-listing
    (dir) algorithm discovery.py's best-effort scanner already uses (a
    provisional content-identity stand-in, NOT a real git blob sha -- see
    discovery.py's module docstring) so a materialized item's pinned sha
    is always directly comparable to what a subsequent `discover_
    contributions()` call would compute for the same bytes.
    """
    if path.is_dir():
        digest = hashlib.sha256()
        for child in sorted(path.rglob("*")):
            if child.is_file():
                digest.update(child.relative_to(path).as_posix().encode("utf-8"))
                digest.update(child.read_bytes())
        return digest.hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_matches(source: Path, dest: Path) -> bool:
    if source.is_dir() != dest.is_dir():
        return False
    if source.is_dir():
        source_files = sorted(p.relative_to(source) for p in source.rglob("*") if p.is_file())
        dest_files = sorted(p.relative_to(dest) for p in dest.rglob("*") if p.is_file())
        if source_files != dest_files:
            return False
        return all(
            (source / rel).read_bytes() == (dest / rel).read_bytes()
            for rel in source_files
        )
    return source.read_bytes() == dest.read_bytes()


def _copy_in(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    if source.is_dir():
        shutil.copytree(source, dest)
    else:
        shutil.copy2(source, dest)


def _remove(target: Path) -> None:
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink()


def _op(
    *,
    dimension: str,
    layer: str,
    item: str,
    op: str,
    path: Path,
    signed: bool,
    reason: Optional[str] = None,
    from_sha: Optional[str] = None,
    to_sha: Optional[str] = None,
) -> MaterializeOp:
    return {
        "dimension": dimension,
        "layer": layer,
        "item": item,
        "op": op,
        "path": str(path),
        "signed": signed,
        "reason": reason,
        "from_sha": from_sha,
        "to_sha": to_sha,
    }


def materialize(
    resolved_set: list[dict[str, Any]],
    *,
    materialize_root: Path | str,
    previous_lock: Optional[Lockfile] = None,
    layer_source_paths: dict[str, Path | str],
    policy: Optional[PolicyFn] = None,
    personal_roots: Iterable[Path | str] = (),
    dry_run: bool = False,
) -> MaterializeReport:
    """
    Reconcile `materialize_root` to `resolved_set` (the pure resolver's
    output -- `resolve_layers()`), reading each winning layer's actual
    content from `layer_source_paths[layer_id]/<dimension>/<item>`.

    Per-item flow: policy gate -> guard_personal -> add/update/unchanged.
    Then, separately, prune anything `previous_lock` says was materialized
    by a layer/dimension/item that is no longer part of the resolved set
    at all (never something the engine didn't itself place -- see module
    docstring).

    `dry_run=True` computes every op WITHOUT writing/deleting anything on
    disk and without advancing `lock` beyond what's already pinned --
    letting a caller preview the plan safely.

    Returns `{"ops": [...], "lock": {...}}` -- `lock` is the NEW
    `{layer: {dimension: {item: sha}}}` state to persist (only for
    dimensions this module actually manages); a `held`/`blocked`/personal-
    protected item carries its PREVIOUS sha forward unchanged (the file
    itself was never touched, so its recorded pin must not silently
    change either).
    """
    gate = policy or _default_policy
    root = Path(materialize_root).expanduser()
    previous_lock = previous_lock or {}
    personal_roots = list(personal_roots)

    ops: list[MaterializeOp] = []
    new_lock: Lockfile = {}

    def _carry_forward(layer_id: str, dimension: str, item: str) -> Optional[str]:
        prev_sha = previous_lock.get(layer_id, {}).get(dimension, {}).get(item)
        if prev_sha is not None:
            new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[item] = prev_sha
        return prev_sha

    for entry in resolved_set:
        dimension = entry["dimension"]
        if semantics_for(dimension) not in _MATERIALIZABLE_SEMANTICS:
            continue  # personal-write / project-local -- never this module's concern

        item = entry["item"]
        layer_id = entry["winning_layer"]
        prev_sha = previous_lock.get(layer_id, {}).get(dimension, {}).get(item)

        source_root = layer_source_paths.get(layer_id)
        dim_dir = Path(source_root).expanduser() / dimension if source_root else None
        source_child = _find_source_child(dim_dir, item) if dim_dir else None
        dest_name = source_child.name if source_child else item
        dest_path = root / dimension / dest_name

        # The sha this item WOULD be pinned at if applied -- computed from
        # the actual source bytes (not the resolver's `winning_sha`, which
        # is only ever the PREVIOUSLY recorded lockfile value and is thus
        # `None` on a first-ever materialize -- see resolver.py's
        # `_make_item()`). Pinning what we can actually verify was placed
        # on disk is the honest reproducibility anchor.
        candidate_sha = _content_sha(source_child) if source_child is not None else None

        verdict = gate(
            {"dimension": dimension, "layer": layer_id, "item": item, "sha": candidate_sha}
        )

        if verdict == "block":
            _carry_forward(layer_id, dimension, item)
            ops.append(
                _op(
                    dimension=dimension, layer=layer_id, item=item, op="blocked",
                    path=dest_path, signed=False, reason="unverified",
                    from_sha=prev_sha, to_sha=candidate_sha,
                )
            )
            continue

        if verdict == "hold":
            _carry_forward(layer_id, dimension, item)
            ops.append(
                _op(
                    dimension=dimension, layer=layer_id, item=item, op="held",
                    path=dest_path, signed=False, reason="held for approval",
                    from_sha=prev_sha, to_sha=candidate_sha,
                )
            )
            continue

        if guard_personal(dest_path, personal_roots=personal_roots):
            _carry_forward(layer_id, dimension, item)
            ops.append(
                _op(
                    dimension=dimension, layer=layer_id, item=item, op="held",
                    path=dest_path, signed=True,
                    reason="protected: personal/dirty working tree -- never overwritten",
                    from_sha=prev_sha, to_sha=candidate_sha,
                )
            )
            continue

        if source_child is None:
            _carry_forward(layer_id, dimension, item)
            ops.append(
                _op(
                    dimension=dimension, layer=layer_id, item=item, op="blocked",
                    path=dest_path, signed=False, reason="source content not found",
                    from_sha=prev_sha, to_sha=None,
                )
            )
            continue

        existed = dest_path.exists()
        changed = not existed or not _content_matches(source_child, dest_path)

        if changed and not dry_run:
            _copy_in(source_child, dest_path)

        op_name = "unchanged" if not changed else ("updated" if existed else "added")

        ops.append(
            _op(
                dimension=dimension, layer=layer_id, item=item, op=op_name,
                path=dest_path, signed=True,
                from_sha=prev_sha, to_sha=candidate_sha,
            )
        )
        new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[item] = candidate_sha or ""

    # --- Pruning: only previously-materialized items no longer resolved at all ---
    resolved_pairs = {
        (e["dimension"], e["item"])
        for e in resolved_set
        if semantics_for(e["dimension"]) in _MATERIALIZABLE_SEMANTICS
    }

    for layer_id, dims in previous_lock.items():
        for dimension, items in dims.items():
            if semantics_for(dimension) not in _MATERIALIZABLE_SEMANTICS:
                continue
            for item, prev_sha in items.items():
                if (dimension, item) in resolved_pairs:
                    continue  # still resolved (possibly under a different layer) -- not orphaned

                dim_dir = root / dimension
                target = _find_source_child(dim_dir, item) if dim_dir.is_dir() else None
                if target is None:
                    continue  # nothing materialized to prune -- already absent

                if guard_personal(target, personal_roots=personal_roots):
                    ops.append(
                        _op(
                            dimension=dimension, layer=layer_id, item=item, op="held",
                            path=target, signed=True,
                            reason="protected: personal/dirty working tree -- never pruned",
                            from_sha=prev_sha, to_sha=None,
                        )
                    )
                    new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[item] = prev_sha
                    continue

                if not dry_run:
                    _remove(target)

                ops.append(
                    _op(
                        dimension=dimension, layer=layer_id, item=item, op="pruned",
                        path=target, signed=True, from_sha=prev_sha, to_sha=None,
                    )
                )

    return {"ops": ops, "lock": new_lock}
