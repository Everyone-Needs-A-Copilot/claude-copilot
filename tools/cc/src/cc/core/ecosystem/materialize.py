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
import stat
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
    product: str
    dimension: str
    layer: str
    item: str
    op: str  # "added" | "updated" | "pruned" | "unchanged" | "held" | "blocked"
    path: str
    signed: bool
    reason: Optional[str]
    from_sha: Optional[str]
    to_sha: Optional[str]
    # ADDITIVE (task 220 Fix 1): non-None only when this op is a fold
    # fallback substitution -- the resolver's actual OVERRIDE winner
    # (`entry["winning_layer"]`) was policy-blocked (unverified), so this
    # op instead materializes the next-ranked SHADOWED layer whose own
    # copy verifies. Carries the ORIGINAL (blocked) winning layer's id so
    # the report stays honest about what actually happened -- never
    # silently reported as if the blocked layer's own content landed on
    # disk. `None` for every ordinary (non-substituted) op, including a
    # `blocked` op where no shadowed layer verified either.
    blocked_winner: Optional[str]


class MaterializeReport(TypedDict):
    ops: list[MaterializeOp]
    lock: Lockfile


# Native target allow-list. Product content is rejected before policy
# evaluation if it names a dimension outside this table. Codex receives
# complete plugins as atomic directories; Claude receives its native content
# dimensions. Neither product can write into the other's root.
PRODUCT_TARGET_ALLOWLIST: dict[str, dict[str, str]] = {
    "claude": {
        "agents": "agents",
        "skills": "skills",
        "commands": "commands",
        "protocol": "protocol",
        "knowledge": "knowledge",
        "cli-integrations": "cli-integrations",
    },
    "codex": {
        "plugins": "plugins",
        "knowledge": "knowledge",
    },
}


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


def _has_configured_remote(git_root: Path, *, timeout: float = 5.0) -> bool:
    """
    True if the git working tree rooted at `git_root` has at least one
    configured remote (`git remote`) -- i.e. it is a real clone of
    somewhere, not just a bare local scratch repo (materialize.py's own
    tests deliberately `git init` throwaway repos with no remote, which
    must stay unaffected by the WP-372 P0.3 "clean tracked repo" guard
    below). Fails CLOSED, same posture as `_is_dirty_git_tree()`: if the
    check itself can't run, treat it as IF a remote is configured (the
    safer assumption -- protect, don't silently allow).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "remote"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # fail closed

    if result.returncode != 0:
        return True  # fail closed

    return bool(result.stdout.strip())


def _is_under_any(path: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        if path == root:
            return True
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _first_symlink_escaping_root(path: Path, root: Path) -> Optional[tuple[Path, Path]]:
    """
    Walk `path`'s ancestor chain from itself up to (but not including)
    `root`, looking for the first EXISTING component that is itself a
    symlink whose resolved target lands OUTSIDE `root`'s own resolved
    boundary.

    Returns `(symlink_path, resolved_target)` for the first such offender,
    or `None` if nothing along the chain escapes `root`.

    This is the exact shape of the WP-372 P0 live incident:
    `~/.claude/knowledge` was a symlink into the org authoring repo
    `knowledge-copilot-internal`, so every write "under"
    `~/.claude/knowledge/<item>` silently landed outside the materialize
    root (`~/.claude`) it was supposed to be confined to.

    Only the segment between `root` and `path` (inclusive of `path`) is
    ever inspected -- this is a one-target confinement check, not a
    general filesystem symlink audit, and never resolves anything above
    `root` itself.
    """
    try:
        root_real = root.resolve()
    except OSError:
        return None

    try:
        path.relative_to(root)
    except ValueError:
        # `path` isn't even nominally under `root` -- not this check's
        # job (materialize.py only ever builds in-root targets; this is
        # defense-in-depth on top of that construction, not the primary
        # confinement mechanism).
        return None

    for candidate in [path, *path.parents]:
        if candidate == root:
            break
        try:
            if not candidate.is_symlink():
                continue
            target_real = candidate.resolve()
        except OSError:
            continue
        try:
            target_real.relative_to(root_real)
        except ValueError:
            return candidate, target_real

    return None


def guard_personal_reason(
    path: Path | str,
    *,
    personal_roots: Iterable[Path | str] = (),
    materialize_root: Path | str | None = None,
    mirror_roots: Iterable[Path | str] = (),
) -> Optional[str]:
    """
    The never-destroy hard stop, WP-372 P0.3 shape (three protections,
    defense in depth -- the live incident defeated the pre-P0.3 version of
    this check because it only ever looked at `path` itself, never at what
    a symlink along the way actually resolved to, and never at whether
    `path` was itself sitting inside someone else's git remote):

      1. `personal_roots` containment (unchanged from before P0.3) --
         `path` is (or is under) a registered personal/authoring root.
      2. SYMLINK ESCAPE (new): if `materialize_root` is given, refuse when
         any ancestor of `path` between `materialize_root` and `path`
         itself is a symlink whose resolved target lands outside
         `materialize_root` -- the exact incident shape
         (`~/.claude/knowledge` -> a real org authoring checkout).
      3. CLEAN TRACKED REPO (new, ALSO gated on `materialize_root` being
         given -- see below): refuse when `path` sits inside ANY git
         working tree that has a configured remote, UNLESS that tree is
         itself under one of `mirror_roots` (a disposable, engine-managed
         mirror clone is expected to have a remote and is never personal).
         This catches a materialize target that IS itself an authoring
         checkout even with no symlink involved, and even when clean (the
         incident repo was clean at the moment it was destroyed -- dirty
         alone was never a sufficient guard).
      4. DIRTY TREE (unchanged from before P0.3) -- `path` sits inside ANY
         dirty git working tree, registered or not.

    Checks 2 and 3 are BOTH gated on `materialize_root` being passed (not
    just check 2): they only make sense for a caller that is confining
    writes/deletes to one specific root -- exactly `materialize()`'s own
    write and prune loops below, the one place the P0 incident's write
    actually happened. Callers that reuse this same gate for a DIFFERENT
    purpose must not get check 3 for free: `deprovision.py`'s mirror-tier
    wipe intentionally deletes disposable mirror clones, which ARE git
    repos with a configured remote by construction (`cc update` clones
    them from one) -- passing no `materialize_root` there (as it always
    has) keeps that wipe working exactly as before. Likewise
    `commands/projects.py` / `core/ecosystem/projects.py` write into a
    discovered PROJECT's own repo, which legitimately has its own remote
    too -- `cc update --fanout`'s entire purpose would break if every
    fanout target were suddenly "protected" for having a remote, so those
    call sites also never pass `materialize_root` and stay on checks 1/4
    only, unchanged from before P0.3.

    Returns the (human-readable) reason string for the FIRST protection
    that fires, or `None` if `path` is not protected by any of them.
    `guard_personal()` below is the boolean view of this for callers that
    only need the yes/no answer (deprovision.py, projects.py, and this
    module's own prune loop).
    """
    target = Path(path).expanduser()

    for root in personal_roots:
        root_path = Path(root).expanduser()
        if target == root_path:
            return f"personal root {root_path}"
        try:
            target.relative_to(root_path)
            return f"personal root {root_path}"
        except ValueError:
            continue

    if materialize_root is not None:
        boundary = Path(materialize_root).expanduser()

        escape = _first_symlink_escaping_root(target, boundary)
        if escape is not None:
            symlink_path, resolved_target = escape
            return (
                f"symlink {symlink_path} resolves to {resolved_target}, which "
                f"escapes the materialize root {boundary} -- refusing to "
                "write or delete through it"
            )

        mirror_root_paths = [Path(m).expanduser() for m in mirror_roots]
        git_root = _find_git_root(target)
        if (
            git_root is not None
            and not _is_under_any(git_root, mirror_root_paths)
            and _has_configured_remote(git_root)
        ):
            return (
                f"{target} sits inside a git working tree at {git_root} with "
                "a configured remote -- treated as a protected authoring "
                "repository, not a disposable materialize/mirror target"
            )

    if _is_dirty_git_tree(target):
        return "personal/dirty working tree"

    return None


def guard_personal(
    path: Path | str,
    *,
    personal_roots: Iterable[Path | str] = (),
    materialize_root: Path | str | None = None,
    mirror_roots: Iterable[Path | str] = (),
) -> bool:
    """
    True if `path` must NEVER be deleted or overwritten by a reconciling
    sync -- see `guard_personal_reason()` for the full four-check ladder
    this is a boolean view of (personal root / symlink escape / clean
    tracked repo with a remote / dirty git tree).

    `personal_roots` is the injectable set of known personal/authoring
    tree roots (e.g. the personal-tier's local checkout, or an author's
    Obsidian-style vault -- inheritance-and-publish.md §2.2's third tree).
    Membership is checked by path containment (`path == root` or `root` is
    an ancestor of `path`), not by string prefix, so `.../personal-2/x`
    never false-positives against a `personal` root.

    `materialize_root`/`mirror_roots` are optional and default to a no-op
    (preserving this function's pre-P0.3 behavior exactly for callers that
    don't pass them, e.g. `deprovision.py`'s mirror-tier wipe, which MUST
    keep treating a mirror clone -- itself a git repo with a remote -- as
    disposable, not personal).

    Even with nothing else configured, this still refuses a path inside
    ANY dirty git working tree (a human-owned, uncommitted-changes tree is
    "personal" for never-destroy's purposes regardless of whether it was
    pre-registered -- CLAUDE.md invariant #3: "never touches a dirty
    personal working tree").
    """
    return (
        guard_personal_reason(
            path,
            personal_roots=personal_roots,
            materialize_root=materialize_root,
            mirror_roots=mirror_roots,
        )
        is not None
    )


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


def content_item_path(
    content_root: Path | str, *, dimension: str, item: str
) -> Optional[Path]:
    """Resolve an item name to the file or directory materialize consumes."""
    if any(
        not value or Path(value).is_absolute() or Path(value).name != value
        for value in (dimension, item)
    ):
        return None
    return _find_source_child(Path(content_root).expanduser() / dimension, item)


def stable_directory_content_sha(files: Iterable[tuple[str, bytes]]) -> str:
    """Return the canonical lock identity for an immutable directory tree.

    Callers that already hold verified object bytes can use this without
    materializing them first.  Keeping the algorithm here makes the projected
    lock identity exactly the one ``materialize()`` records for a directory.
    """
    digest = hashlib.sha256()
    for relative_path, content in sorted(files, key=lambda item: item[0]):
        digest.update(relative_path.encode("utf-8"))
        digest.update(content)
    return digest.hexdigest()


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
        return stable_directory_content_sha(
            (
                (child.relative_to(path).as_posix(), child.read_bytes())
                for child in path.rglob("*")
                if child.is_file()
            )
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialized_item_content_sha(
    *,
    product: str,
    dimension: str,
    item: str,
    materialize_roots: dict[str, Path | str],
    target_allowlist: Optional[dict[str, dict[str, str]]] = None,
) -> Optional[str]:
    """Read one managed destination with the materializer's lock algorithm.

    This is the read-only counterpart to ``materialize()``'s private target
    and content helpers.  It resolves file extensions exactly the same way as
    the writer, refuses paths outside the product allow-list, and treats any
    symlink or non-file/non-directory node in the managed item as a mismatch.
    A caller can therefore compare the returned digest directly with the
    item's lock pin without trusting source-checkout bytes.
    """
    allowlist = target_allowlist or PRODUCT_TARGET_ALLOWLIST
    root_value = materialize_roots.get(product)
    relative_value = allowlist.get(product, {}).get(dimension)
    if (
        root_value is None
        or not relative_value
        or not item
        or Path(item).is_absolute()
        or Path(item).name != item
    ):
        return None
    root = Path(root_value).expanduser()
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    dimension_root = root / relative
    target = _find_source_child(dimension_root, item)
    if target is None:
        return None
    try:
        target_relative = target.relative_to(root)
        candidates = [root]
        current = root
        for part in target_relative.parts:
            current = current / part
            candidates.append(current)
        for candidate in candidates:
            metadata = candidate.lstat()
            if candidate.is_symlink() or not (
                stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
            ):
                return None
        if target.is_dir():
            for child in target.rglob("*"):
                metadata = child.lstat()
                if child.is_symlink() or not (
                    stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
                ):
                    return None
        return _content_sha(target)
    except (OSError, ValueError):
        return None


def _content_matches(source: Path, dest: Path) -> bool:
    if source.is_dir() != dest.is_dir():
        return False
    if source.is_dir():
        source_files = sorted(
            p.relative_to(source) for p in source.rglob("*") if p.is_file()
        )
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
    product: str,
    dimension: str,
    layer: str,
    item: str,
    op: str,
    path: Path,
    signed: bool,
    reason: Optional[str] = None,
    from_sha: Optional[str] = None,
    to_sha: Optional[str] = None,
    blocked_winner: Optional[str] = None,
) -> MaterializeOp:
    return {
        "product": product,
        "dimension": dimension,
        "layer": layer,
        "item": item,
        "op": op,
        "path": str(path),
        "signed": signed,
        "reason": reason,
        "from_sha": from_sha,
        "to_sha": to_sha,
        "blocked_winner": blocked_winner,
    }


def materialize(
    resolved_set: list[dict[str, Any]],
    *,
    materialize_root: Path | str | None = None,
    materialize_roots: Optional[dict[str, Path | str]] = None,
    target_allowlist: Optional[dict[str, dict[str, str]]] = None,
    previous_lock: Optional[Lockfile] = None,
    layer_source_paths: dict[str, Path | str],
    layer_source_refs: Optional[dict[str, str]] = None,
    layer_policies: Optional[dict[str, dict[str, Any]]] = None,
    layer_products: Optional[dict[str, str]] = None,
    policy: Optional[PolicyFn] = None,
    personal_roots: Iterable[Path | str] = (),
    mirror_roots: Iterable[Path | str] = (),
    protected_orphan_layers: Iterable[str] = (),
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

    WP-372 P0.3 (the live incident post-mortem -- see `guard_personal_reason()`):
    every `guard_personal()` call below passes THIS entry's own product-
    scoped confinement root (`_confinement_root()`), so the symlink-escape
    and clean-tracked-repo checks are always evaluated against the exact
    boundary this write/prune is supposed to stay inside -- never a bare
    personal-roots-only check the way this module used to call it.
    `mirror_roots` (optional; defaults to none configured) exempts a
    disposable, engine-managed mirror clone from the clean-tracked-repo
    check should a target ever legitimately resolve into one.

    `layer_source_refs` (task 215 blocker fix, G-9; optional at this call
    boundary, but REQUIRED for `verify_git_item()` to ever verify anything
    -- security review blocker 2, 2026-08-10): each layer's actually-
    resolved/pinned `source.ref` (e.g. a signed foundation snapshot tag),
    threaded through to `policy.evaluate()`/`verify_git_item()`, which now
    verifies the SIGNED TAG's tree directly (`git verify-tag` +
    `git cat-file -e <commit>:<path>`) rather than walking `git log` history
    -- the tag's signature is the only fact that matters, not which commit
    last touched the path, and not the working tree's arbitrary HEAD.
    Omitted or missing for a given layer, this is simply `None` and
    `verify_git_item()` blocks (fails closed) -- there is no fallback
    verification technique left to run without a pinned tag to check.
    """
    gate = policy or _default_policy
    if materialize_roots is None and materialize_root is None:
        raise ValueError("materialize_root or materialize_roots is required")
    legacy_root = (
        Path(materialize_root).expanduser() if materialize_root is not None else None
    )
    product_roots = {
        product: Path(path).expanduser()
        for product, path in (materialize_roots or {}).items()
    }
    allowlist = target_allowlist or PRODUCT_TARGET_ALLOWLIST
    layer_policies = layer_policies or {}
    layer_products = layer_products or {}
    layer_source_refs = layer_source_refs or {}
    previous_lock = previous_lock or {}
    personal_roots = list(personal_roots)
    mirror_roots = list(mirror_roots)
    protected_orphan_layers = set(protected_orphan_layers)

    ops: list[MaterializeOp] = []
    new_lock: Lockfile = {}

    def _confinement_root(product: str) -> Optional[Path]:
        """The materialize-root boundary THIS product's writes/deletes must
        stay inside -- single-root mode uses `legacy_root` for everything;
        multi-root mode looks up this specific product's own root (never a
        DIFFERENT product's root, so a claude-targeted symlink escape can
        never be masked by codex's boundary or vice versa)."""
        return legacy_root if materialize_roots is None else product_roots.get(product)

    def _guard_reason(target: Path, product: str) -> Optional[str]:
        return guard_personal_reason(
            target,
            personal_roots=personal_roots,
            materialize_root=_confinement_root(product),
            mirror_roots=mirror_roots,
        )

    def _target(product: str, dimension: str, name: str) -> Optional[Path]:
        if materialize_roots is None:
            assert legacy_root is not None
            return legacy_root / dimension / name
        root = product_roots.get(product)
        relative = allowlist.get(product, {}).get(dimension)
        if root is None or not relative:
            return None
        rel_path = Path(relative)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return None
        target = root / rel_path / name
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    def _carry_forward(layer_id: str, dimension: str, item: str) -> Optional[str]:
        prev_sha = previous_lock.get(layer_id, {}).get(dimension, {}).get(item)
        if prev_sha is not None:
            new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[item] = prev_sha
        return prev_sha

    def _first_verified_shadow(
        *,
        dimension: str,
        item: str,
        product: str,
        shadowed: list[dict[str, Any]],
    ) -> Optional[tuple[str, Path, Optional[str]]]:
        """Fold un-freeze (task 220 Fix 1): when the resolver's OVERRIDE
        winner is policy-blocked, try each shadowed layer in the
        resolver's own nearest-shadowed-first order (`resolver.py`'s
        `_resolve_override()`) and return the first one whose own copy
        actually verifies against THIS SAME policy gate -- rather than
        freezing the slot at the blocked winner's last-good content
        forever. Blocked content still never materializes: this only
        widens WHICH layer's already-verifiable content is eligible to
        fill the slot, it never weakens the gate itself (the exact same
        `gate()` callable, called the exact same way, is applied to each
        shadow candidate).

        Returns `(layer_id, source_child, candidate_sha)` for the first
        shadowed layer that (a) has real source content on disk and (b)
        the policy gate allows, or `None` if every shadowed layer is also
        blocked/held/missing -- in which case the caller's existing
        `blocked` handling is unchanged.
        """
        for shadow in shadowed:
            shadow_id = shadow["layer"]
            shadow_source_root = layer_source_paths.get(shadow_id)
            shadow_dim_dir = (
                Path(shadow_source_root).expanduser() / dimension
                if shadow_source_root
                else None
            )
            shadow_source_child = (
                _find_source_child(shadow_dim_dir, item) if shadow_dim_dir else None
            )
            if shadow_source_child is None:
                continue
            shadow_candidate_sha = _content_sha(shadow_source_child)
            shadow_verdict = gate(
                {
                    "product": product,
                    "dimension": dimension,
                    "layer": shadow_id,
                    "item": item,
                    "sha": shadow_candidate_sha,
                    "source_root": str(shadow_source_root)
                    if shadow_source_root
                    else None,
                    "relative_path": f"{dimension}/{shadow_source_child.name}",
                    "layer_policy": layer_policies.get(shadow_id),
                    "ref": layer_source_refs.get(shadow_id),
                }
            )
            if shadow_verdict != "allow":
                continue
            return shadow_id, shadow_source_child, shadow_candidate_sha
        return None

    for entry in resolved_set:
        dimension = entry["dimension"]
        if semantics_for(dimension) not in _MATERIALIZABLE_SEMANTICS:
            continue  # personal-write / project-local -- never this module's concern

        item = entry["item"]
        layer_id = entry["winning_layer"]
        product = entry.get("product") or layer_products.get(layer_id, "")
        prev_sha = previous_lock.get(layer_id, {}).get(dimension, {}).get(item)

        source_root = layer_source_paths.get(layer_id)
        dim_dir = Path(source_root).expanduser() / dimension if source_root else None
        source_child = _find_source_child(dim_dir, item) if dim_dir else None
        dest_name = source_child.name if source_child else item
        dest_path = _target(product, dimension, dest_name)
        if dest_path is None:
            _carry_forward(layer_id, dimension, item)
            fallback_root = product_roots.get(product) or legacy_root or Path(".")
            ops.append(
                _op(
                    product=product,
                    dimension=dimension,
                    layer=layer_id,
                    item=item,
                    op="blocked",
                    path=fallback_root,
                    signed=False,
                    reason="product target is not allowlisted",
                    from_sha=prev_sha,
                    to_sha=None,
                )
            )
            continue

        # The sha this item WOULD be pinned at if applied -- computed from
        # the actual source bytes (not the resolver's `winning_sha`, which
        # is only ever the PREVIOUSLY recorded lockfile value and is thus
        # `None` on a first-ever materialize -- see resolver.py's
        # `_make_item()`). Pinning what we can actually verify was placed
        # on disk is the honest reproducibility anchor.
        candidate_sha = _content_sha(source_child) if source_child is not None else None

        verdict = gate(
            {
                "product": product,
                "dimension": dimension,
                "layer": layer_id,
                "item": item,
                "sha": candidate_sha,
                "source_root": str(source_root) if source_root else None,
                "relative_path": f"{dimension}/{dest_name}",
                "layer_policy": layer_policies.get(layer_id),
                "ref": layer_source_refs.get(layer_id),
            }
        )

        blocked_winner: Optional[str] = None
        if verdict == "block":
            fallback = _first_verified_shadow(
                dimension=dimension,
                item=item,
                product=product,
                shadowed=entry.get("shadowed") or [],
            )
            if fallback is None:
                _carry_forward(layer_id, dimension, item)
                ops.append(
                    _op(
                        product=product,
                        dimension=dimension,
                        layer=layer_id,
                        item=item,
                        op="blocked",
                        path=dest_path,
                        signed=False,
                        reason="unverified",
                        from_sha=prev_sha,
                        to_sha=candidate_sha,
                    )
                )
                continue

            # Fold fallback (task 220 Fix 1): the OVERRIDE winner is
            # policy-blocked (unverified) and a shadowed layer's own copy
            # verifies. The blocked winner's own PRIOR pin (if any)
            # carries forward untouched -- it was never actually applied,
            # so its recorded sha must not silently change -- and
            # materialization proceeds below using the verified shadow
            # layer's own id/content/prior pin instead. `blocked_winner`
            # travels with every op emitted from here on so the report
            # never silently implies the blocked layer's content is what
            # landed on disk.
            _carry_forward(layer_id, dimension, item)
            blocked_winner = layer_id
            layer_id, source_child, candidate_sha = fallback
            prev_sha = previous_lock.get(layer_id, {}).get(dimension, {}).get(item)
            fallback_dest = _target(product, dimension, source_child.name)
            if fallback_dest is not None:
                dest_path = fallback_dest
            verdict = "allow"

        if verdict == "hold":
            _carry_forward(layer_id, dimension, item)
            ops.append(
                _op(
                    product=product,
                    dimension=dimension,
                    layer=layer_id,
                    item=item,
                    op="held",
                    path=dest_path,
                    signed=False,
                    reason="held for approval",
                    from_sha=prev_sha,
                    to_sha=candidate_sha,
                )
            )
            continue

        guard_reason = _guard_reason(dest_path, product)
        if guard_reason is not None:
            _carry_forward(layer_id, dimension, item)
            ops.append(
                _op(
                    product=product,
                    dimension=dimension,
                    layer=layer_id,
                    item=item,
                    op="held",
                    path=dest_path,
                    signed=True,
                    reason=f"protected: {guard_reason} -- never overwritten",
                    from_sha=prev_sha,
                    to_sha=candidate_sha,
                    blocked_winner=blocked_winner,
                )
            )
            continue

        if source_child is None:
            _carry_forward(layer_id, dimension, item)
            ops.append(
                _op(
                    product=product,
                    dimension=dimension,
                    layer=layer_id,
                    item=item,
                    op="blocked",
                    path=dest_path,
                    signed=False,
                    reason="source content not found",
                    from_sha=prev_sha,
                    to_sha=None,
                    blocked_winner=blocked_winner,
                )
            )
            continue

        existed = dest_path.exists()
        changed = not existed or not _content_matches(source_child, dest_path)

        if changed and not dry_run:
            _copy_in(source_child, dest_path)

        op_name = "unchanged" if not changed else ("updated" if existed else "added")
        substitution_reason = (
            f"winner {blocked_winner} blocked: unverified; materialized "
            f"verified layer {layer_id} instead"
            if blocked_winner is not None
            else None
        )

        ops.append(
            _op(
                product=product,
                dimension=dimension,
                layer=layer_id,
                item=item,
                op=op_name,
                path=dest_path,
                signed=True,
                reason=substitution_reason,
                from_sha=prev_sha,
                to_sha=candidate_sha,
                blocked_winner=blocked_winner,
            )
        )
        new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[item] = (
            candidate_sha or ""
        )

    # --- Pruning: only previously-materialized items no longer resolved at all ---
    resolved_pairs = {
        (
            e.get("product", "") if materialize_roots is not None else "",
            e["dimension"],
            e["item"],
        )
        for e in resolved_set
        if semantics_for(e["dimension"]) in _MATERIALIZABLE_SEMANTICS
    }

    for layer_id, dims in previous_lock.items():
        product = (
            layer_products.get(layer_id, "") if materialize_roots is not None else ""
        )
        for dimension, items in dims.items():
            if semantics_for(dimension) not in _MATERIALIZABLE_SEMANTICS:
                continue
            for item, prev_sha in items.items():
                if (product, dimension, item) in resolved_pairs:
                    continue  # still resolved (possibly under a different layer) -- not orphaned

                target_probe = _target(product, dimension, item)
                if target_probe is None:
                    new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[
                        item
                    ] = prev_sha
                    continue
                dim_dir = target_probe.parent
                target = _find_source_child(dim_dir, item) if dim_dir.is_dir() else None
                if target is None:
                    continue  # nothing materialized to prune -- already absent

                guard_reason = _guard_reason(target, product)
                if guard_reason is not None:
                    ops.append(
                        _op(
                            product=product,
                            dimension=dimension,
                            layer=layer_id,
                            item=item,
                            op="held",
                            path=target,
                            signed=True,
                            reason=f"protected: {guard_reason} -- never pruned",
                            from_sha=prev_sha,
                            to_sha=None,
                        )
                    )
                    new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[
                        item
                    ] = prev_sha
                    continue

                # A revoked/stale protected layer must be removed when its
                # engine-owned bytes still match the lock. If a person changed
                # those bytes, preserve that human work and surface a hold.
                # Ordinary orphan reconciliation retains its legacy behavior;
                # callers opt layers into this stricter never-destroy branch.
                current_sha = _content_sha(target)
                if layer_id in protected_orphan_layers and current_sha != prev_sha:
                    ops.append(
                        _op(
                            product=product,
                            dimension=dimension,
                            layer=layer_id,
                            item=item,
                            op="held",
                            path=target,
                            signed=False,
                            reason="protected: materialized content was customized -- never pruned",
                            from_sha=prev_sha,
                            to_sha=current_sha,
                        )
                    )
                    new_lock.setdefault(layer_id, {}).setdefault(dimension, {})[
                        item
                    ] = prev_sha
                    continue

                if not dry_run:
                    _remove(target)

                ops.append(
                    _op(
                        product=product,
                        dimension=dimension,
                        layer=layer_id,
                        item=item,
                        op="pruned",
                        path=target,
                        signed=True,
                        from_sha=prev_sha,
                        to_sha=None,
                    )
                )

    return {"ops": ops, "lock": new_lock}


# ---------------------------------------------------------------------------
# materialize_ecosystem_config -- WP-372 P1.3(a): deliver the org's
# inherited ecosystem.yml to the materialize root
# ---------------------------------------------------------------------------


def materialize_ecosystem_config(
    layers: list[dict[str, Any]],
    *,
    layer_source_paths: dict[str, Optional[str]],
    materialize_root: Optional[Path | str],
    personal_roots: Iterable[Path | str] = (),
    mirror_roots: Iterable[Path | str] = (),
    dry_run: bool = False,
) -> Optional[MaterializeOp]:
    """
    Deliver the org's inherited `ecosystem.yml` to
    `<materialize_root>/ecosystem.yml` -- `core/ecosystem/
    ecosystem_config.py`'s `ecosystem_config_path()` already documents this
    as its default location; nothing in the codebase actually placed the
    file there before WP-372 P1.3.

    THIS IS DELIBERATELY NOT A NEW DIMENSION in `PRODUCT_TARGET_ALLOWLIST`
    or `core/ecosystem/dimensions.py`. Every dimension `materialize()`
    (above) folds is a DIRECTORY of many items at `<layer root>/
    <dimension>/<item>`; `ecosystem.yml` is a single well-known file that
    sits at a layer's OWN ROOT (`<layer root>/ecosystem.yml`) -- the same
    repo-root-metadata convention `copilot.layer.yml` already uses.
    Threading a root-level singleton through the generic per-item pipeline
    (`core/ecosystem/discovery.py`'s `discover_contributions()`, this
    module's own `_find_source_child()`) would mean special-casing "this
    one dimension's folder IS the layer root" in code shared by every
    OTHER dimension every other product/layer combination also flows
    through -- a much larger blast radius than one small, dedicated,
    independently-testable copy step for a single file. This function
    still reuses the actual security-critical piece of that pipeline
    directly: `guard_personal_reason()`, unchanged, so a materialize target
    that is itself a protected personal/authoring tree, or a symlink
    escaping `materialize_root` (WP-372 P0.3 -- the exact live-incident
    shape), is refused exactly like every other materialize write.

    "Winning" layer: among `layers` with `product == "claude"` (the only
    product `ecosystem.yml` is host-config for today), the one with the
    LOWEST `rank` (nearest-tier-wins -- the same precedence every OVERRIDE
    dimension already applies) whose `layer_source_paths` entry actually
    has an `ecosystem.yml` at its root. Typically only the organization
    tier ships one; a personal or future foundation-shipped copy would
    still resolve correctly under this same precedence. Layers with no
    local `ecosystem.yml` (i.e. every tier except org, today) are silently
    skipped -- consistent with `ecosystem_config.py`'s own "absent is a
    valid machine state" fail-open contract -- and this function returns
    `None` when no `claude`-product layer has one at all.

    Returns a single `MaterializeOp` (reusing the exact shape `materialize()`
    itself emits, so a caller can append it straight into that function's
    `ops` list / `changed` rendering) describing what happened, or `None`
    if there was nothing to do. `dry_run=True` computes the op WITHOUT
    writing anything, mirroring `materialize()`'s own `dry_run` contract.

    KNOWN LIMITATION (deliberate, documented, not "fixed" by this
    function): unlike every dimension `materialize()` folds, this
    singleton is NOT pruned if every `claude`-product layer stops shipping
    an `ecosystem.yml` (e.g. the org removes it) -- there is no per-layer
    lock entry tracking provenance for it the way `materialize()`'s own
    `new_lock` does for dimension items, and guessing "this machine's
    `~/.claude/ecosystem.yml` must be ours to delete" without that
    provenance would risk deleting a file this function never wrote. The
    conservative failure mode (a stale file lingers) is preferred over the
    unsafe one (deleting something we cannot prove we own) -- the same
    bias `core/ecosystem/dimensions.py`'s `semantics_for()` documents for
    an unrecognized dimension ("only ever shadows an extra copy, safe
    failure mode").
    """
    claude_layers = sorted(
        (layer for layer in layers if layer.get("product") == "claude"),
        key=lambda layer: (
            layer.get("rank", 0) if isinstance(layer.get("rank"), int) else 0
        ),
    )

    if materialize_root is None:
        return None
    dest = Path(materialize_root).expanduser() / "ecosystem.yml"

    for layer in claude_layers:
        source_root = layer_source_paths.get(layer["id"])
        if not source_root:
            continue
        source_file = Path(source_root).expanduser() / "ecosystem.yml"
        try:
            if not source_file.is_file():
                continue
        except OSError:
            continue

        candidate_sha = _content_sha(source_file)

        guard_reason = guard_personal_reason(
            dest,
            personal_roots=personal_roots,
            materialize_root=Path(materialize_root).expanduser(),
            mirror_roots=mirror_roots,
        )
        if guard_reason is not None:
            return _op(
                product="claude",
                dimension="ecosystem",
                layer=layer["id"],
                item="ecosystem",
                op="held",
                path=dest,
                signed=True,
                reason=f"protected: {guard_reason} -- never overwritten",
                from_sha=None,
                to_sha=candidate_sha,
            )

        existed = dest.exists()
        changed = not existed or not _content_matches(source_file, dest)
        if changed and not dry_run:
            _copy_in(source_file, dest)
        op_name = "unchanged" if not changed else ("updated" if existed else "added")

        return _op(
            product="claude",
            dimension="ecosystem",
            layer=layer["id"],
            item="ecosystem",
            op=op_name,
            path=dest,
            signed=True,
            from_sha=None,
            to_sha=candidate_sha,
        )

    return None
