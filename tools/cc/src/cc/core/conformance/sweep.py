"""Layer 3 (`repo.*`) orchestration: discover every reachable directory
under `projects.roots`, classify it (`classes.py`), run every available
dimension module (`dimensions/`) against it, and aggregate the results --
cached, parallel, and filterable by `--repo` / `--class` / `--check`.

`HARNESS-DESIGN.md` section 4 Layer 3 / section 7.2 is the design source
of truth for every design decision below (in-process not subprocess,
process-pool parallelism, per-repo fingerprint caching, `--full` bypassing
the cache). This module does not know what "D1" or "D4" mean -- it only
knows how to find repos, classify them, and hand each one to
`dimensions.run_dimension_modules()`.

Discovery, precisely (measured on this machine, `EXISTING-VERIFICATION.md`
/ `CLASSIFICATION.md`): `projects.roots` resolves to a single root,
`/Volumes/Dev/Sites`. Under it, three non-dot directories (`COPILOT`,
`PERSONAL`, `TSM`) each hold no `.git` of their own and each contain the
real, audited repos as their own immediate children -- 55 + 15 + 6 = 76
raw candidates, one of which (`COPILOT/shared-docs`) is a symlink to
`COPILOT/knowledge-copilot-internal`, not a distinct directory, so
`discover_repos()` dedupes by resolved realpath down to 75
(`CLASSIFICATION.md`'s own header: "76 scanned directories, 75 real").
`discover_repos()` does not hardcode "COPILOT/PERSONAL/TSM" by name --
`_iter_candidates()` below makes one purely structural decision per
directory (does it already look like a repo root, or does it need one
more level of descent) so a future root laid out flat (repos directly
under the root, no grouping level) or nested differently still discovers
correctly, without ever guessing a directory's CLASS from its name (the
`-internal`/`test-pilot` trap `HARNESS-DESIGN.md` repeatedly warns
against -- name never decides class; `classes.py` does that from
`classification.toml` plus `.git` presence only).
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from cc.core.config import resolve_key
from cc.core.conformance.cache import (
    ConformanceCache,
    RepoFingerprint,
    compute_repo_fingerprint,
    default_cache_path,
)
from cc.core.conformance.classes import (
    ClassificationEntry,
    load_classification_table,
)
from cc.core.conformance.dimensions import (
    MODULE_CRASHED_SUFFIX,
    DimensionModule,
    RepoContext,
    discover_dimension_modules,
    run_dimension_modules,
    unavailable_module_results,
)
from cc.core.conformance.registry import DEFAULT_REGISTRY, Registry
from cc.core.conformance.types import CheckResult, Layer, Mode

# Directory names never worth treating as a "group" level to descend
# through, and never worth returning as a candidate repo either -- purely
# a walk-time skip list, mirrors `cc.core.ecosystem.projects._SKIP_DIR_NAMES`
# in spirit (this module does not import that constant: this walk is a raw
# structural filesystem scan over `projects.roots`, not the lock-manifest
# discovery `projects.discover_projects()` does -- see module docstring's
# "discovery, precisely" note for why the two are deliberately different).
_SKIP_NAMES = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__"})

# Default bounded depth for the structural scan (root -> group -> repo).
# `CLASSIFICATION.md`'s own audit never went deeper than this, and neither
# does `classification.toml`'s seeded table -- see `_iter_candidates()`.
DEFAULT_MAX_DEPTH = 2

# The relative paths `compute_repo_fingerprint()` stats per repo for the
# fast-mode cache. Not exhaustive of every dimension's own sub-paths (each
# `dNN_*.py` module is the authority on those); this is a cache-invalidation
# heuristic covering the primary artifact of each of the 13 dimensions plus
# the cross-cutting gitignore check, extend it when a new one needs finer
# invalidation -- an over-broad list only costs a few extra `stat()` calls,
# never correctness (`cache.py`'s own fingerprint already treats a missing
# path as `(-1, -1)`, i.e. itself a fingerprint-changing fact).
DIMENSION_FINGERPRINT_PATHS: tuple[str, ...] = (
    ".claude/agents",
    ".claude/commands",
    ".claude/fitness-check.sh",
    "CLAUDE.md",
    "AGENTS.md",
    "plugins/codex-copilot",
    "scripts/copilot-gate.sh",
    ".codex-copilot.json",
    "copilot.lock.json",
    ".claude/hooks/copilot-hook.sh",
    ".claude/cc/config.json",
    ".claude/memory/entries",
    ".claude/memory/memory.db",
    "docs/40-initiatives",
    "copilot.project.json",
    ".mcp.json",
    "ECOSYSTEM.md",
    ".gitignore",
)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveredRepo:
    """One reachable directory after dedup. `path` is the canonical,
    resolved, non-symlink path every downstream consumer (classification,
    dimension checks, cache) uses as identity. `aliases` records every raw
    candidate path (symlinks included) that resolved to the same realpath
    -- `COPILOT/shared-docs` ends up as an alias of
    `COPILOT/knowledge-copilot-internal`'s `DiscoveredRepo`, never a
    second, separate one."""

    path: Path
    root: Path
    aliases: tuple[Path, ...]
    is_git_root: bool

    @property
    def raw_count(self) -> int:
        """How many pre-dedup candidates resolved to this one repo (1 for
        every ordinary directory, 2 for `knowledge-copilot-internal` on
        this machine, because of the `shared-docs` symlink alias)."""

        return len(self.aliases)


def _looks_like_repo_root(path: Path) -> bool:
    return (path / ".git").exists()


def _is_traversable_dir(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    if path.name in _SKIP_NAMES:
        return False
    try:
        if path.is_symlink():
            return path.is_dir()
        return path.is_dir()
    except OSError:
        return False


def _iter_candidates(node: Path, *, depth: int, max_depth: int) -> Iterable[Path]:
    """Yield candidate repo directories under `node`. One adaptive rule,
    applied at every level: a directory that already looks like a repo
    root (`.git` present), or that has reached `max_depth`, is itself a
    candidate and is never descended into further. Otherwise, descend into
    its own non-dot, non-skip-listed children. Fail-open: an unreadable
    directory is yielded as its own candidate rather than aborting the
    walk (mirrors `cc.core.ecosystem.projects._scan_root`'s "one bad
    directory never aborts the rest" convention)."""

    if _looks_like_repo_root(node) or depth >= max_depth:
        yield node
        return

    try:
        children = sorted(
            child for child in node.iterdir() if _is_traversable_dir(child)
        )
    except OSError:
        yield node
        return

    if not children:
        yield node
        return

    for child in children:
        yield from _iter_candidates(child, depth=depth + 1, max_depth=max_depth)


def discover_repos(
    roots: Iterable[Path | str] | None = None,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[DiscoveredRepo, ...]:
    """Enumerate every reachable directory under `roots` (default:
    `resolve_key("projects.roots")`), deduped by resolved realpath.
    Deterministic (sorted by canonical path) order, so a repeated run over
    an unchanged fleet produces byte-identical discovery output, which
    `--repo`/`--class` filtering and the cache both depend on for
    stability."""

    if roots is None:
        roots = resolve_key("projects.roots") or []
    root_paths = [Path(root).expanduser() for root in roots]

    # realpath -> (root the walk found it under, every raw candidate path
    # that resolved to it). A dict preserves first-seen insertion order,
    # which is irrelevant here since the final return is explicitly sorted.
    by_realpath: dict[str, tuple[Path, list[Path]]] = {}

    for root in root_paths:
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        for candidate in _iter_candidates(root, depth=0, max_depth=max_depth):
            try:
                real = candidate.resolve()
            except OSError:
                real = candidate
            key = str(real)
            if key not in by_realpath:
                by_realpath[key] = (root, [candidate])
            else:
                by_realpath[key][1].append(candidate)

    discovered: list[DiscoveredRepo] = []
    for key, (root, raw_candidates) in by_realpath.items():
        # Prefer a non-symlink alias as the canonical display path (the
        # real directory, e.g. `knowledge-copilot-internal`, never the
        # `shared-docs` symlink that happens to point at it).
        canonical = next(
            (candidate for candidate in raw_candidates if not candidate.is_symlink()),
            raw_candidates[0],
        )
        discovered.append(
            DiscoveredRepo(
                path=Path(key),
                root=root,
                aliases=tuple(sorted(raw_candidates)),
                is_git_root=_looks_like_repo_root(canonical),
            )
        )

    return tuple(sorted(discovered, key=lambda repo: str(repo.path)))


def _repo_matches_filter(repo: DiscoveredRepo, wanted: Sequence[str]) -> bool:
    """Same suffix-match semantics as `report.filter_by_repo` (an exact
    string match, or a `/<name>` suffix match), applied to the DISCOVERED
    REPO LIST before any check runs -- `report.filter_by_repo` itself
    operates post-hoc on already-computed `CheckResult`s and is not
    reusable here (`sweep.py` wants to skip the work entirely, not filter
    results after paying for it), so this is the pre-execution twin, kept
    behaviorally identical on purpose."""

    if not wanted:
        return True
    repo_str = str(repo.path)
    return any(
        repo_str == want or repo_str.endswith(f"/{Path(want).name}") for want in wanted
    )


# ---------------------------------------------------------------------------
# Sweep options / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepOptions:
    """Everything `run_sweep()` needs. `mode=Mode.FULL` both selects the
    FULL-mode dimension checks (via `registry.select(modes=...)`) AND
    forces the cache off (`HARNESS-DESIGN.md` section 7.2: "`--full`" is
    the cache-bypass, not a separate flag) -- pass `use_cache=False`
    explicitly for a fast-mode run that should still skip the cache (the
    CLI's own `--no-cache`).

    `classes` and `repo_classes` are two DIFFERENT, ANDed vocabularies, on
    purpose. `classes` is the rubric letter (`registry.REPO_CLASSES`,
    "A".."E") a registered check's own `applies_to_classes` is defined in
    terms of -- unchanged, so nothing already passing rubric letters here
    (`Registry.select(classes=...)`'s own contract) is affected. `repo_
    classes` is the human-facing `classes.RepoClass` taxonomy name
    (`COMPONENT`/`PRODUCT`/`SITE-CONTENT`/`DOCS-KNOWLEDGE`/`SCRATCH-
    ARCHIVE`, exact `ClassificationEntry.repo_class.value` match) -- added
    because PRODUCT and SITE-CONTENT both collapse to rubric letter "C"
    (`classes.py`'s own module docstring), so a rubric-letter-only filter
    cannot express "PRODUCT repos only, not SITE-CONTENT" even though an
    operator reading `classification.toml` reasonably expects to."""

    roots: tuple[Path, ...] | None = None
    repos: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    repo_classes: tuple[str, ...] = ()
    check_ids: tuple[str, ...] = ()
    mode: Mode = Mode.FAST
    jobs: int | None = None
    use_cache: bool = True
    cache_path: Path | None = None
    max_depth: int = DEFAULT_MAX_DEPTH
    registry: Registry = field(default=DEFAULT_REGISTRY)
    classification_path: Path | None = None


@dataclass(frozen=True)
class SweepResult:
    results: tuple[CheckResult, ...]
    repos_discovered: int
    repos_selected: int
    cache_hits: int
    cache_misses: int
    unavailable_dimensions: tuple[str, ...]


def _selected_modes(mode: Mode) -> tuple[Mode, ...]:
    # FULL mode runs both FAST and FULL-registered checks; FAST mode runs
    # only FAST-registered checks (`HARNESS-DESIGN.md` section 7.2's two
    # modes table: fast is a strict subset of full).
    return (Mode.FAST, Mode.FULL) if mode is Mode.FULL else (Mode.FAST,)


def _repo_worker(
    repo_path: Path,
    classification: ClassificationEntry,
    is_git_root: bool,
    mode: Mode,
    modules: tuple[DimensionModule, ...] | None = None,
) -> tuple[CheckResult, ...]:
    """The unit of parallel work: one repo, every available dimension
    module.

    `modules`, when given, is the sweep's already-computed
    `discover_dimension_modules()` result -- `run_sweep()`'s SERIAL path
    passes it through so each repo does not re-import every `dNN_*.py`
    module from scratch, and so a test's monkeypatched
    `discover_dimension_modules` actually reaches this function (calling
    `run_dimension_modules(context)` with no override would resolve
    `discover_dimension_modules` through `dimensions/__init__.py`'s OWN
    module globals, not through whatever `sweep.py`'s caller patched).

    `modules=None` (the PARALLEL/`ProcessPoolExecutor` path's only option)
    means "discover fresh in THIS process" -- a `DimensionModule` tuple
    holds live `ModuleType` objects, which are not picklable, so it can
    never cross the process-pool boundary; each worker process re-imports
    `dimensions/` itself, which is also what makes per-process check
    registration safe (every worker gets its own `DEFAULT_REGISTRY`, so
    nothing is shared, and nothing collides, across process boundaries)."""

    context = RepoContext.build(
        repo_path,
        classification=classification,
        is_git_root=is_git_root,
        mode=mode,
    )
    return run_dimension_modules(context, modules=modules)


def run_sweep(options: SweepOptions | None = None) -> SweepResult:
    """Discover, classify, and sweep every selected repo, in parallel,
    cached on the fast path. Returns every produced `CheckResult`
    (per-repo dimension results plus the sweep-wide "dimension module
    unavailable" signals) filtered down to what `options` asked for.

    `--repo` / `--class` are applied to the REPO LIST before any check
    runs (`_repo_matches_filter`, `classes.classify`). `--check` (and the
    implicit `layer=Layer.REPO`, `modes=_selected_modes(options.mode)`)
    is applied via `options.registry.select(...)` -- the task's own "wire
    --repo/--class/--layer selection through to Registry.select" -- and
    then used to filter the AGGREGATED results by check id: dimension
    modules always compute everything relevant for a repo (so one module
    that owns several check ids does not need to know about CLI
    filtering), and this function narrows the output afterward. The
    sweep-wide "module unavailable" signals (`unavailable_module_results`)
    are never id-filtered this way -- they are not registered checks, and
    hiding "this dimension could not run at all" behind a `--check` filter
    that happens not to name it would be exactly the kind of silent gap
    `inv.no_fabricated_healthy` exists to prevent.
    """

    opts = options or SweepOptions()

    discovered = discover_repos(opts.roots, max_depth=opts.max_depth)
    selected = [repo for repo in discovered if _repo_matches_filter(repo, opts.repos)]

    table = load_classification_table(opts.classification_path)
    classified: list[tuple[DiscoveredRepo, ClassificationEntry]] = []
    for repo in selected:
        entry = _classify_repo(repo, table)
        if opts.classes and entry.rubric_letter not in opts.classes:
            continue
        if opts.repo_classes and entry.repo_class.value not in opts.repo_classes:
            continue
        classified.append((repo, entry))

    dimension_modules = discover_dimension_modules()
    unavailable_names = tuple(m.name for m in dimension_modules if not m.available)

    cache = _build_cache(opts)
    cache_hits = 0
    cache_misses = 0

    per_repo_results: list[CheckResult] = []
    jobs = opts.jobs if opts.jobs is not None else min(32, (os.cpu_count() or 1))

    to_compute: list[tuple[DiscoveredRepo, ClassificationEntry, RepoFingerprint]] = []
    for repo, entry in classified:
        fingerprint = compute_repo_fingerprint(repo.path, DIMENSION_FINGERPRINT_PATHS)
        cached = cache.get(repo.path, fingerprint)
        if cached is not None:
            cache_hits += 1
            per_repo_results.extend(cached)
            continue
        cache_misses += 1
        to_compute.append((repo, entry, fingerprint))

    if to_compute:
        if jobs > 1 and len(to_compute) > 1:
            with ProcessPoolExecutor(max_workers=jobs) as executor:
                futures = {
                    executor.submit(
                        _repo_worker, repo.path, entry, repo.is_git_root, opts.mode
                    ): (repo, entry, fingerprint)
                    for repo, entry, fingerprint in to_compute
                }
                for future in futures:
                    repo, entry, fingerprint = futures[future]
                    computed = future.result()
                    cache.put(repo.path, fingerprint, computed)
                    per_repo_results.extend(computed)
        else:
            for repo, entry, fingerprint in to_compute:
                computed = _repo_worker(
                    repo.path,
                    entry,
                    repo.is_git_root,
                    opts.mode,
                    modules=dimension_modules,
                )
                cache.put(repo.path, fingerprint, computed)
                per_repo_results.extend(computed)

    cache.save()

    registrations = opts.registry.select(
        layers=(Layer.REPO,),
        modes=_selected_modes(opts.mode),
        check_ids=opts.check_ids or None,
        classes=opts.classes or None,
    )
    registered_ids = {registration.id for registration in registrations}
    # Always narrow to the registered id set -- not only when --check/
    # --class were passed. This is what makes a FAST sweep actually
    # exclude a FULL-only check's result even when a dimension module
    # (incorrectly, or not yet updated) computed it anyway; the common
    # "no CLI filters at all" case still returns everything, because
    # `registered_ids` then equals every id `registry.select()` reports
    # for `_selected_modes(opts.mode)`, which is every check that ought to
    # run in that mode. The two synthetic, never-registered id shapes
    # (`dimensions.MODULE_CRASHED_SUFFIX`) are exempted -- a per-repo
    # COULD_NOT_RUN must never be hidden behind a filter that does not
    # happen to name its id (the `.module_unavailable` sweep-wide signals
    # get the same treatment below, by construction: they are appended
    # after this filter runs, never through it).
    per_repo_results = [
        result
        for result in per_repo_results
        if result.id in registered_ids or result.id.endswith(MODULE_CRASHED_SUFFIX)
    ]

    unavailable_results = unavailable_module_results(dimension_modules)

    all_results = tuple(
        sorted(
            (*per_repo_results, *unavailable_results),
            key=lambda result: (result.subject, result.id),
        )
    )

    return SweepResult(
        results=all_results,
        repos_discovered=len(discovered),
        repos_selected=len(classified),
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        unavailable_dimensions=unavailable_names,
    )


def _classify_repo(
    repo: DiscoveredRepo, table: dict[str, ClassificationEntry]
) -> ClassificationEntry:
    from cc.core.conformance.classes import classify

    return classify(
        repo.path, root=repo.root, table=table, is_git_root=repo.is_git_root
    )


def _build_cache(options: SweepOptions) -> ConformanceCache:
    if options.mode is Mode.FULL or not options.use_cache:
        return ConformanceCache.disabled()
    path = options.cache_path or default_cache_path()
    return ConformanceCache(path)


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DIMENSION_FINGERPRINT_PATHS",
    "DiscoveredRepo",
    "SweepOptions",
    "SweepResult",
    "discover_repos",
    "run_sweep",
]
