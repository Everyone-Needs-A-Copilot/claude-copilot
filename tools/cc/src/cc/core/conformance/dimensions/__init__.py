"""The Layer-3 dimension module contract, owned by WP-4.

`sweep.py` (also WP-4) drives ~75 repos through whichever `d01_claude.py`
.. `d13_reach.py` + `dx_gitignore.py` modules exist under this package.
THIS FILE is the one place that contract is defined -- WP-4a/b/c each add
ONLY their own module file(s) here (`HARNESS-DESIGN.md` section 9.1: "
`dimensions/__init__.py` is owned by WP-4 and defines the `DimensionCheck`
protocol; WP-4a/b/c each add only their own module files").

THE CONTRACT a dimension module MUST satisfy
---------------------------------------------
1. Its filename is one of `DIMENSION_MODULE_NAMES` below (assigned by
   `HARNESS-DESIGN.md` section 8's file layout: `d01_claude.py` ..
   `d13_reach.py`, plus `dx_gitignore.py` for the cross-dimension
   `repo.gitignore.no_self_exclusion` check).
2. At IMPORT time (module level, mirroring how `tier.py`/`stack.py`
   register -- `registry.py`'s own docstring), it calls
   `cc.core.conformance.registry.register_check(...)` once per check id
   the dimension owns (e.g. `d01_claude.py` registers
   `repo.d01.agent_roster_exact`, `repo.d01.command_set_exact`, ... --
   every id from `TEST-MATRIX.md` section 3 that dimension covers), against
   the default `DEFAULT_REGISTRY` (the `registry=` kwarg's own default --
   do not pass a private `Registry()`, or `sweep.py`'s
   `Registry.select(...)` filtering will never see the module's checks).
3. It exposes exactly one required callable:

       def run(context: RepoContext) -> Iterable[CheckResult]://

   Called ONCE PER REPO by `sweep.py`. Must return (or yield) a
   `CheckResult` for EVERY check id the module registered in step 2, for
   THIS repo -- including a `Verdict.SKIP` result (never a silent
   omission) for any check whose `applies_to_classes` excludes
   `context.rubric_class` (`HARNESS-DESIGN.md`'s own worked example,
   `repo.d08.tier_participation`: "Class A/B only; NA for C/D/E ...
   Marking a consumer 'missing tier membership' is the category error the
   CSE model exists to prevent, so `NA` is emitted explicitly, never
   silently"). `run()` itself decides this per check -- `sweep.py` does
   NOT pre-filter by class before calling `run()`, because one module can
   own several check ids with different `applies_to_classes` sets.
   `run()` must never raise for an ordinary "this check fails" outcome --
   build a `Verdict.FAIL` `CheckResult` (with evidence, per
   `types.CheckResult`'s own constructor invariant) instead. Raising is
   reserved for a genuine "I could not even attempt this check" condition
   (unreadable file racing a deletion, etc.); `sweep.py` catches any
   exception `run()` raises (or that occurs while consuming a generator it
   returns) and converts it to a single `Verdict.COULD_NOT_RUN` result for
   that repo, with the traceback text in `Evidence.detail` -- so ONE
   dimension crashing on ONE repo never aborts the repo's other dimensions
   or any other repo (`HARNESS-DESIGN.md` section 10: "A check crashes ->
   That check is UNKNOWN with the traceback in evidence; siblings
   continue").

`run()` MUST be read-only against `context.path` -- filesystem reads only,
`fsguard.run_git_readonly` for any git plumbing (never a bare
`subprocess.run(["git", ...])`). `sweep.py` runs Layer 3 against BOTH the
synthetic `FleetFactory` fixture (World A) and, when invoked against the
real machine, the configured fleet (World B) under the
`machine_readonly` tripwire -- a module that writes anywhere fails that
tripwire loudly regardless of which world it runs in.

`RepoContext`, below, is everything a dimension module gets: it is
intentionally narrow (a path, the two classification views, a git-root
bit, and the fast/full mode) rather than a grab-bag of pre-computed state,
so a module's own `run()` stays a pure function of one repo's own
filesystem plus the classification `sweep.py` already computed -- never a
second, competing classifier.

A module that does not exist yet, fails to import, or does not expose a
callable `run` is NEVER a crash: `discover_dimension_modules()` catches
every import-time exception (a broken sibling module's own bug included --
`# noqa: BLE001` is deliberate there, not an oversight) and reports it as
`DimensionModule(available=False)`; `sweep.py` turns each unavailable
module into exactly one `Verdict.COULD_NOT_RUN` `CheckResult`
(`Scope.GLOBAL`, one per missing/broken module for the whole sweep, not
per repo -- "the harness could not evaluate this dimension at all" is a
sweep-wide fact, not a per-repo one) rather than raising.
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterable

from cc.core.conformance.classes import ClassificationEntry, RepoClass
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Mode,
    Scope,
    Severity,
    Verdict,
)

# A missing dimension module is a coverage gap, not (by itself) proof the
# ecosystem is broken -- S1 ("fan-out, O(repos) manual"): every repo in the
# fleet loses that dimension's coverage until the module lands.
_MISSING_MODULE_SEVERITY = Severity.S1

# Suffixes on the synthetic (never-registered) ids `unavailable_module_results()`
# and `run_dimension_modules()`'s exception boundary produce. `sweep.py`
# never narrows these out of its `--check`/`--class`/mode filtering --
# a COULD_NOT_RUN must never be hidden behind a filter that does not
# happen to name its (synthetic, unregistered) id.
MODULE_UNAVAILABLE_SUFFIX = ".module_unavailable"
MODULE_CRASHED_SUFFIX = ".crashed"

# The closed, ordered set of dimension module base names this package
# expects to find, one per row of `HARNESS-DESIGN.md` section 8's file
# layout (`dimensions/{d01_claude,d02_codex,...,d13_reach,dx_gitignore}.py`).
# Order matches `TEST-MATRIX.md` section 3 (D1..D13) with the cross-cutting
# gitignore-self-exclusion check last. This tuple is the harness's own
# manifest of "what SHOULD exist" -- a name simply absent from disk is
# exactly as "unavailable" as one present but broken (see module docstring).
DIMENSION_MODULE_NAMES: tuple[str, ...] = (
    "d01_claude",
    "d02_codex",
    "d03_lock",
    "d04_hook",
    "d05_ccconfig",
    "d06_memory",
    "d07_knowledge",
    "d08_tier",
    "d09_declaration",
    "d10_mcp",
    "d11_registry",
    "d12_docs",
    "d13_reach",
    "dx_gitignore",
)

# Human-readable label per module name, purely for COULD_NOT_RUN detail
# text and `cc conformance list` -- never load-bearing for check logic.
DIMENSION_LABELS: dict[str, str] = {
    "d01_claude": "D1 -- Claude Copilot install shape",
    "d02_codex": "D2 -- Codex Copilot install shape",
    "d03_lock": "D3 -- lock schema and checksums",
    "d04_hook": "D4 -- enforcement hook present and locked",
    "d05_ccconfig": "D5 -- cc config machine sentinel",
    "d06_memory": "D6 -- memory entries committed, db ignored",
    "d07_knowledge": "D7 -- knowledge wiring resolves",
    "d08_tier": "D8 -- tier participation",
    "d09_declaration": "D9 -- portable project declaration",
    "d10_mcp": "D10 -- .mcp.json object shape, no retired servers",
    "d11_registry": "D11 -- ECOSYSTEM.md registry entry",
    "d12_docs": "D12 -- 40-initiatives docs scaffold",
    "d13_reach": "D13 -- scanner reachability",
    "dx_gitignore": "gitignore self-exclusion (cross-dimension)",
}


@dataclass(frozen=True)
class RepoContext:
    """Everything a dimension module's `run()` receives -- see module
    docstring for the full contract this accompanies.

    `path` is the repo's canonical (deduped, resolved) absolute path.
    `subject` is the exact string every `CheckResult` this module returns
    for this repo MUST use as `subject` (matches the `--json` envelope's
    `repos[].path`, `HARNESS-DESIGN.md` section 6.3's worked example) --
    `str(path)`, computed once here so no two modules format it
    differently.
    `classification` is `sweep.py`'s already-computed
    `classes.ClassificationEntry` for this repo; `rubric_class` and
    `taxonomy_class` are pulled up as direct fields since they are what a
    check body reads on almost every call (`classification.rubric_letter`
    / `classification.repo_class` remain reachable for anything else, e.g.
    `classification.role` for a COMPONENT repo).
    `is_git_root` is a plain `(path / ".git").exists()` bit -- D13 and
    several D1-family sub-checks need it and it is cheap enough to compute
    once in `sweep.py` rather than in every module.
    `mode` gates FULL-only sub-checks within one dimension (e.g. D1's
    `repo.d01.fitness_check_passes`, which shells out to
    `.claude/fitness-check.sh` and is FULL-mode only per `TEST-MATRIX.md`)
    -- a module registers that check with `mode=Mode.FULL` (so
    `Registry.select(modes=[Mode.FAST])` already excludes it from a fast
    sweep) AND should itself skip attempting the work in `run()` when
    `context.mode is Mode.FAST`, returning a `Verdict.SKIP` result instead
    of doing FULL-only work sweep.py did not ask for.
    """

    path: Path
    subject: str
    classification: ClassificationEntry
    is_git_root: bool
    mode: Mode

    @property
    def rubric_class(self) -> str:
        return self.classification.rubric_letter

    @property
    def taxonomy_class(self) -> RepoClass:
        return self.classification.repo_class

    @classmethod
    def build(
        cls,
        path: Path,
        *,
        classification: ClassificationEntry,
        is_git_root: bool,
        mode: Mode,
    ) -> "RepoContext":
        return cls(
            path=path,
            subject=str(path),
            classification=classification,
            is_git_root=is_git_root,
            mode=mode,
        )


@dataclass(frozen=True)
class DimensionModule:
    """The result of attempting to import one entry from
    `DIMENSION_MODULE_NAMES`. `module` is `None` exactly when `available`
    is `False` -- a missing file, an import-time exception anywhere in the
    module's own code, or a module that does not expose a callable
    `run` are all folded into the same "unavailable" outcome, each
    distinguished only by `error`'s text."""

    name: str
    module: ModuleType | None
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.module is not None

    @property
    def label(self) -> str:
        return DIMENSION_LABELS.get(self.name, self.name)


def discover_dimension_modules() -> tuple[DimensionModule, ...]:
    """Attempt to import every name in `DIMENSION_MODULE_NAMES`, in order.
    Never raises: any exception at import time (missing module, syntax
    error, an exception a sibling's own top-level code raises) is caught
    and folded into `DimensionModule(available=False, error=...)` --
    "a missing module is a COULD-NOT-RUN, not a crash" is enforced HERE,
    once, so `sweep.py` never needs its own try/except around an import.
    """

    discovered: list[DimensionModule] = []
    for name in DIMENSION_MODULE_NAMES:
        try:
            module = importlib.import_module(f"{__name__}.{name}")
        except Exception as exc:  # noqa: BLE001 -- a sibling module's own bug must never crash the sweep.
            discovered.append(
                DimensionModule(
                    name=name,
                    module=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        run = getattr(module, "run", None)
        if not callable(run):
            discovered.append(
                DimensionModule(
                    name=name,
                    module=None,
                    error=(
                        f"module {module.__name__!r} does not expose a "
                        "callable run(context) -- see dimensions/__init__.py's "
                        "module docstring for the required contract."
                    ),
                )
            )
            continue

        discovered.append(DimensionModule(name=name, module=module))
    return tuple(discovered)


def unavailable_module_results(
    modules: Iterable[DimensionModule] | None = None,
) -> tuple[CheckResult, ...]:
    """One `Verdict.COULD_NOT_RUN` `CheckResult` per unavailable dimension
    module -- a sweep-wide fact ("this dimension could not be evaluated at
    all"), so exactly one entry per missing/broken module, never one per
    repo (`sweep.py`'s per-repo aggregation would otherwise inflate a
    single "D5's module is not written yet" condition into ~75 identical
    rows). `modules` defaults to a fresh `discover_dimension_modules()`
    call so a caller can pass an already-computed tuple instead of
    re-importing.
    """

    resolved = tuple(modules) if modules is not None else discover_dimension_modules()
    results: list[CheckResult] = []
    for entry in resolved:
        if entry.available:
            continue
        results.append(
            CheckResult(
                id=f"repo.{entry.name}{MODULE_UNAVAILABLE_SUFFIX}",
                layer=Layer.REPO,
                severity=_MISSING_MODULE_SEVERITY,
                scope=Scope.GLOBAL,
                subject=f"dimensions/{entry.name}.py",
                assertion=(
                    f"{entry.label} is implemented and importable "
                    "(dimensions/__init__.py's module contract)."
                ),
                verdict=Verdict.COULD_NOT_RUN,
                expected_today=ExpectedToday.PASS,
                evidence=(
                    Evidence(
                        kind="import-error",
                        path=f"dimensions/{entry.name}.py",
                        expected="module present, importable, exposes run(context)",
                        actual=entry.error or "module not found",
                    ),
                ),
                detail=(
                    f"{entry.label} could not be evaluated for any repo this "
                    "sweep -- not one dimension check silently skipped, the "
                    "WHOLE dimension is missing coverage."
                ),
                remediation=(
                    f"implement dimensions/{entry.name}.py per this package's "
                    "module contract (dimensions/__init__.py)."
                ),
            )
        )
    return tuple(results)


def run_dimension_modules(
    context: RepoContext,
    modules: Iterable[DimensionModule] | None = None,
) -> tuple[CheckResult, ...]:
    """Run every AVAILABLE dimension module's `run(context)` against one
    repo, aggregating their results. Per-module exception boundary: if a
    module's `run()` raises (or raises while being iterated, for a
    generator), that ONE module's failure becomes a single
    `Verdict.COULD_NOT_RUN` result scoped to THIS repo (unlike
    `unavailable_module_results()`'s sweep-wide entries, a module that
    imports fine but blows up on one specific repo's data is a per-repo
    fact) -- every other module for this repo, and every other repo,
    still runs (`HARNESS-DESIGN.md` section 10's "Per-check exception
    boundary ... siblings continue", implemented here since `registry.py`
    -- WP-1's file -- has no `.run()` of its own to host it).
    """

    resolved = tuple(modules) if modules is not None else discover_dimension_modules()
    results: list[CheckResult] = []
    for entry in resolved:
        if not entry.available:
            continue
        assert (
            entry.module is not None
        )  # narrows for the type checker; `available` guarantees it.
        try:
            produced = tuple(entry.module.run(context))
        except Exception as exc:  # noqa: BLE001 -- one dimension's crash must not abort the repo's others.
            results.append(
                CheckResult(
                    id=f"repo.{entry.name}{MODULE_CRASHED_SUFFIX}",
                    layer=Layer.REPO,
                    severity=_MISSING_MODULE_SEVERITY,
                    scope=Scope.PER_REPO,
                    subject=context.subject,
                    assertion=f"{entry.label} completes without raising for this repo.",
                    verdict=Verdict.COULD_NOT_RUN,
                    expected_today=ExpectedToday.PASS,
                    evidence=(
                        Evidence(
                            kind="exception",
                            path=context.subject,
                            expected="run(context) returns without raising",
                            actual=f"{type(exc).__name__}: {exc}",
                            detail=traceback.format_exc(limit=8),
                        ),
                    ),
                    detail=f"{entry.label} raised while evaluating {context.subject}.",
                    remediation=(
                        f"fix dimensions/{entry.name}.py's run() for this "
                        "repo's on-disk shape, or make the failing branch "
                        "return a Verdict.COULD_NOT_RUN result instead of "
                        "raising."
                    ),
                )
            )
            continue
        results.extend(produced)
    return tuple(results)


__all__ = [
    "DIMENSION_LABELS",
    "DIMENSION_MODULE_NAMES",
    "MODULE_CRASHED_SUFFIX",
    "MODULE_UNAVAILABLE_SUFFIX",
    "DimensionModule",
    "RepoContext",
    "discover_dimension_modules",
    "run_dimension_modules",
    "unavailable_module_results",
]
