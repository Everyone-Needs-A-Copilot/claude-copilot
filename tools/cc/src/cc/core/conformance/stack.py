"""Layer 2 — component stack: 4 product families x 4 tiers = 16 cells.

`HARNESS-DESIGN.md` §4 "Layer 2 — Component stack": "for all 4 families x 4
tiers, each layer declares itself, resolves, pins to a version that EXISTS,
and the pinned ref is genuinely an ancestor of the branch it claims."

This module implements exactly the 7 check ids `TEST-MATRIX.md` §2
"Component stack" defines (7 distinct ids, ~96 parameterized instances:
16x5 + 4 + 12), registered under the dot-scheme `registry.py` requires
(`^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$`) while keeping each TEST-MATRIX
mnemonic verbatim-legible as the id's second segment:

    TEST-MATRIX id  ->  registered id       ->  what it asserts
    CS-DECL         ->  stack.cs_decl       ->  the cell has a copilot.layers.yml entry
    CS-PATH         ->  stack.cs_path       ->  source.path exists and is a git root
    CS-REF-VALID    ->  stack.cs_ref_valid  ->  source.ref resolves to a real git object
    CS-ANCESTOR     ->  stack.cs_ancestor   ->  the pinned ref is an ancestor of origin/main (RC-3)
    CS-MIRROR       ->  stack.cs_mirror     ->  the checkout is a disposable mirror, not live-authoring
    CS-SIGNERS      ->  stack.cs_signers    ->  foundation layers carry a non-empty allowed_signers
    CS-DIM          ->  stack.cs_dim        ->  tier-variant copilot.layer.yml declares non-empty dimensions (RC-5)

WRAP, never REPLACE: manifest loading/validation goes straight through
`cc.core.ecosystem.manifest.load_layers`/`validate_layers` (`EXISTING-
VERIFICATION.md` #40 -- do not re-implement the manifest contract). Git
truth is read exclusively through `fsguard.run_git_readonly`, whose
allowlist deliberately excludes `fetch` -- see "Network-gating" below.

Every check here is a pure function of `(cells, manifest snapshots)` ->
`list[CheckResult]` (`HARNESS-DESIGN.md` §3.2 rule 2): nothing in this
module mutates a filesystem or a git ref. `run_stack_checks()` is the one
orchestration entry point both a machine-truth (World B) caller and a
`FleetFactory`-built synthetic fleet (World A) caller use, differing only
in which `manifest_paths` they pass in.

Network-gating (task requirement, `TEST-MATRIX.md` §7 item 3): CS-ANCESTOR
must compare the pinned ref against a *pristine* `origin/main`, never the
locally checked-out branch (`TEST-MATRIX.md` §2's own correction: "not the
local working-tree HEAD -- testing against local HEAD conflates 'wrong
branch checked out' with 'the tag itself has no merge-base,' which is the
real defect"). This module never calls `git fetch` -- `fsguard`'s read-only
allowlist does not include it, and Fast mode is specified to make zero
network calls (`HARNESS-DESIGN.md` §7.2/ADR-003). So `_resolve_default_branch()`
tries the two READ-ONLY refs that answer "an ancestor of the branch it
claims" without ever touching the checked-out HEAD -- a cached `origin/main`
(the real machine's ordinary case; this machine's four foundations all have
one cached) and, failing that, a plain local `main` branch ref (the
synthetic fleet's case -- `FleetFactory` tier repos have no `origin` remote
at all, matching WP-1's own `test_orphan_pin_reproduces_rc3_defect`, which
checks ancestry against bare `main`). If NEITHER resolves locally, the
check emits an explicit `SKIP` naming both attempted refs and stating that
establishing one would require a network fetch this harness never performs
-- never a silent fallback to whatever happens to be checked out.

Ground-truth corrections found while implementing this module (measured
against the live machine, not copied from the audit docs -- see this
project's CLAUDE.md "Investigation Depth": existing/live state is the
contract, not the producer doc that described it days earlier):

  - `TEST-MATRIX.md` §2's cell table claims `cli-foundation` (`v0.3.5`)
    passes CS-ANCESTOR ("one of only two foundation pins that actually
    resolves"). Freshly verified: `v0.3.5`'s commit message is literally
    "foundation snapshot v0.3.5", `git rev-list --count v0.3.5` == 1 (a
    parentless orphan, the exact RC-3 shape), and it has no merge-base with
    `origin/main`. It now FAILS, same as claude/codex-foundation.
  - `TEST-MATRIX.md` §2 claims `knowledge-organization`'s `ref: main` is
    clean ("main == HEAD (clean)"). Freshly verified: local `main` in
    `knowledge-copilot-internal` is 1 commit AHEAD of `origin/main`
    (unpushed), so `main` is not an ancestor of `origin/main` and
    CS-ANCESTOR now FAILS there too.
  - `TEST-MATRIX.md` §2's CS-SIGNERS row claims all 4 foundations have
    `allowed_signers: []`. Freshly verified against the live manifest:
    `claude-foundation` and `codex-foundation` now each carry one
    `SHA256:...` entry (non-empty) and PASS; `cli-foundation` and
    `knowledge-foundation` are still `[]` and FAIL. 2/4, not 0/4.
  - CS-MIRROR's own literal command (`git status --porcelain` empty AND
    not aliased) is confirmed but INSUFFICIENT to reproduce the audit's
    "0/16 PASS": run literally, only `claude-foundation` (dirty + aliased)
    fails today -- 15 of the 16 real checkouts happen to be git-clean *right
    now*, which the audit's own "every checkout is a live working tree"
    reasoning was never actually claiming to depend on. The durable,
    non-flaky signal for "is this a disposable mirror" is structural, not
    momentary: `cc.core.ecosystem.mirror.mirror_root()` (WRAPPED here, not
    re-derived -- design rule 1) defines the ONE place a disposable mirror
    is allowed to live (`paths.mirrors_root`, default `~/.copilot/mirrors`)
    and explicitly documents that location as "NEVER `~/.claude/` ... and
    NEVER an authoring vault". None of the 16 real `source.path` values are
    anywhere under that root -- every one of them points straight at the
    author's primary `/Volumes/Dev/Sites/COPILOT/<repo>` checkout. So
    CS-MIRROR here fails a cell when EITHER that structural condition holds
    (source.path is not under the configured mirrors root -- the condition
    that alone reproduces 0/16 on this machine) OR the literal command's
    two signals do (dirty working tree / known live-authoring alias),
    keeping both real defects independently detectable.

Given this drift, `expected_today` on every result this module produces
mirrors that result's own freshly-computed verdict (PASS/SKIP ->
`ExpectedToday.PASS`, FAIL -> `ExpectedToday.FAIL`) rather than transcribing
the increasingly-stale per-cell prediction table -- `report.py` does not
read `expected_today` in its exit-code or envelope logic today, so nothing
downstream depends on the literal audit numbers, and restating a doc that
has already fallen out of sync with the very state it describes would be
the "weakened assertion" the design explicitly forbids, not an honest one.
CS-DIM's finding (12/12 tier-variant cells failing, matching the docs
exactly) was independently re-verified and has NOT drifted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from cc.core.config import resolve_key
from cc.core.conformance.fsguard import (
    default_guarded_machine_paths,
    run_git_readonly,
)
from cc.core.conformance.registry import register_check
from cc.core.conformance.types import (
    CheckResult,
    Evidence,
    ExpectedToday,
    Layer,
    Scope,
    Severity,
    Verdict,
)
from cc.core.ecosystem.manifest import ManifestError, load_layers, validate_layers

# ---------------------------------------------------------------------------
# The 16-cell topology
# ---------------------------------------------------------------------------

DEFAULT_PRODUCTS: tuple[str, ...] = ("claude", "cli", "codex", "knowledge")
TIER_ROLES: tuple[str, ...] = ("foundation", "organization", "department", "personal")

# Manifest-wide rank convention (`HARNESS-DESIGN.md` throughout; mirrored by
# `tests/conformance/conftest.py::_ROLE_RANK_DEFAULT`, which this module does
# NOT import -- that constant belongs to WP-1's test fixture, this is the
# production check's own copy of the same public, stable vocabulary).
EXPECTED_RANK_BY_ROLE: Mapping[str, int] = {
    "foundation": 40,
    "organization": 30,
    "department": 20,
    "personal": 10,
}

# TEST-MATRIX.md §2's own CS-ANCESTOR command hardcodes `origin/main`. This
# machine's real foundations all have that cached; the synthetic fleet's
# tier repos (no `origin` remote at all) fall back to a plain local `main`
# branch ref -- see the module docstring's "Network-gating" section.
_CANDIDATE_DEFAULT_BRANCH_REFS: tuple[str, ...] = ("origin/main", "main")

_COPILOT_LAYER_YML = "copilot.layer.yml"


def _cell_id(product: str, role: str) -> str:
    """Canonical, matrix-legible subject naming -- deliberately NOT the raw
    manifest `id` field (which is irregular in the real manifest: cli's
    foundation is literally `id: foundation`, cli's organization is
    `id: org-internal`). `{product}-{role}` is stable and sorts into a
    clean product x tier grid regardless of what the manifest happens to
    call any given layer."""

    return f"{product}-{role}"


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

_CS_DECL = register_check(
    id="stack.cs_decl",
    layer=Layer.STACK,
    severity=Severity.S1,
    scope=Scope.PER_CELL,
    summary=(
        "CS-DECL: the product x tier cell declares itself in "
        "copilot.layers.yml with product+role+rank matching the cell, and "
        "a source.path set"
    ),
    remediation=(
        "Add a layers[] entry for this product/tier to copilot.layers.yml "
        "with product, role, rank (10/20/30/40 by tier), and source.path "
        "all set."
    ),
    expected_today=ExpectedToday.PASS,
)

_CS_PATH = register_check(
    id="stack.cs_path",
    layer=Layer.STACK,
    severity=Severity.S1,
    scope=Scope.PER_CELL,
    summary="CS-PATH: the cell's declared source.path exists on disk and is a git root",
    remediation="Clone or re-materialize the tier repo at the source.path declared in copilot.layers.yml.",
    expected_today=ExpectedToday.PASS,
)

_CS_REF_VALID = register_check(
    id="stack.cs_ref_valid",
    layer=Layer.STACK,
    severity=Severity.S0,
    scope=Scope.PER_CELL,
    summary="CS-REF-VALID: the cell's pinned source.ref resolves to a real git object in the source repo",
    remediation="Fix the dangling ref in copilot.layers.yml, or push/tag the missing commit in the source repo.",
    expected_today=ExpectedToday.PASS,
)

_CS_ANCESTOR = register_check(
    id="stack.cs_ancestor",
    layer=Layer.STACK,
    severity=Severity.S0,
    scope=Scope.PER_CELL,
    summary=(
        "CS-ANCESTOR (RC-3): the pinned ref is genuinely an ancestor of a "
        "pristine origin/main, not merely a valid git object"
    ),
    remediation=(
        "Re-cut the release tag from a connected point on main "
        "(`git tag <ref> main`), or fast-forward/push the tier branch so "
        "its pin is reachable from origin/main. Never re-cut a tag as a "
        "parentless snapshot (`git commit-tree` against no parent) -- that "
        "is RC-3's root cause, not this specific pin."
    ),
    expected_today=ExpectedToday.FAIL,
    requires_network=False,
)

_CS_MIRROR = register_check(
    id="stack.cs_mirror",
    layer=Layer.STACK,
    severity=Severity.S1,
    scope=Scope.PER_CELL,
    summary=(
        "CS-MIRROR: the layer's checkout is a disposable mirror (clean "
        "working tree, not a live-authoring alias target) -- safe to "
        "rm -rf and re-clone"
    ),
    remediation=(
        "Materialize this layer into a dedicated, disposable mirror "
        "location instead of pointing source.path at a live-authoring "
        "working tree; commit or stash any pending changes; and remove "
        "any alias (e.g. ~/.claude/copilot) that resolves onto it."
    ),
    expected_today=ExpectedToday.FAIL,
)

_CS_SIGNERS = register_check(
    id="stack.cs_signers",
    layer=Layer.STACK,
    severity=Severity.S1,
    scope=Scope.PER_CELL,
    summary="CS-SIGNERS: foundation layers carry a non-empty policy.allowed_signers",
    remediation="Add at least one compiled-in trust root (a signing key fingerprint) to this foundation's policy.allowed_signers in copilot.layers.yml.",
    expected_today=ExpectedToday.FAIL,
)

_CS_DIM = register_check(
    id="stack.cs_dim",
    layer=Layer.STACK,
    severity=Severity.S0,
    scope=Scope.PER_CELL,
    summary=(
        "CS-DIM (RC-5): the tier-variant repo's copilot.layer.yml declares "
        "a non-empty dimensions: list"
    ),
    remediation=(
        "Author copilot.layer.yml (if absent) and populate dimensions: with "
        "the dimensions this repo actually contributes content under -- "
        "never leave it as dimensions: [] once the repo carries real "
        "content."
    ),
    expected_today=ExpectedToday.FAIL,
)


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestSnapshot:
    """One `copilot.layers.yml` file, loaded and validated exactly once.
    `layers` is `None` and `error` is set when the file failed to load or
    validate -- callers treat that as COULD_NOT_RUN for anything that
    needed this snapshot, never as an empty-but-fine manifest."""

    path: Path
    layers: tuple[dict[str, Any], ...] | None
    error: str | None


def load_manifest_snapshot(path: Path) -> ManifestSnapshot:
    try:
        layers = validate_layers(load_layers(path))
        return ManifestSnapshot(path=path, layers=tuple(layers), error=None)
    except ManifestError as exc:
        return ManifestSnapshot(path=path, layers=None, error=str(exc))


def load_manifest_snapshots(paths: Iterable[Path]) -> tuple[ManifestSnapshot, ...]:
    return tuple(load_manifest_snapshot(path) for path in paths)


def discover_real_manifest_paths() -> tuple[Path, ...]:
    """The task's "all three real layer files the machine has": the three
    well-known `copilot.layers.yml` locations `fsguard` already guards
    (`fsguard.default_guarded_machine_paths()`), filtered to those that
    actually exist. World-B (machine-truth) callers use this; World-A
    (synthetic fleet) callers pass `[handle.manifest_path]` instead."""

    return tuple(
        path
        for path in default_guarded_machine_paths()
        if path.name == "copilot.layers.yml" and path.exists()
    )


def _find_matching_layer(
    layers: Iterable[Mapping[str, Any]], product: str, role: str
) -> Mapping[str, Any] | None:
    expected_rank = EXPECTED_RANK_BY_ROLE[role]
    for layer in layers:
        if (
            layer.get("product") == product
            and layer.get("role") == role
            and layer.get("rank") == expected_rank
        ):
            return layer
    return None


def _first_match(
    snapshots: Sequence[ManifestSnapshot], product: str, role: str
) -> tuple[Path, Mapping[str, Any]] | None:
    """The first loadable snapshot's matching layer entry for this cell --
    used by every check downstream of CS-DECL that needs `source.path` /
    `source.ref` / `policy` (real manifest copies are supposed to be
    identical; CS-DECL alone is responsible for checking they agree)."""

    for snapshot in snapshots:
        if snapshot.error is not None or snapshot.layers is None:
            continue
        match = _find_matching_layer(snapshot.layers, product, role)
        if match is not None:
            return snapshot.path, match
    return None


# ---------------------------------------------------------------------------
# CS-DECL
# ---------------------------------------------------------------------------


def check_cs_decl(
    cells: Sequence[tuple[str, str]], snapshots: Sequence[ManifestSnapshot]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    loadable = [snapshot for snapshot in snapshots if snapshot.error is None]
    broken = [snapshot for snapshot in snapshots if snapshot.error is not None]

    for product, role in cells:
        subject = _cell_id(product, role)

        if not snapshots:
            results.append(
                _CS_DECL.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="no real copilot.layers.yml manifest found on this machine",
                )
            )
            continue

        if not loadable:
            evidence = tuple(
                Evidence(
                    kind="manifest",
                    path=str(snapshot.path),
                    detail=snapshot.error or "",
                )
                for snapshot in broken
            )
            results.append(
                _CS_DECL.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    evidence=evidence,
                    detail=f"every discovered manifest failed to load ({len(broken)})",
                )
            )
            continue

        missing_from: list[Path] = []
        no_source_path: list[Path] = []
        for snapshot in loadable:
            assert snapshot.layers is not None
            match = _find_matching_layer(snapshot.layers, product, role)
            if match is None:
                missing_from.append(snapshot.path)
                continue
            if not match.get("source", {}).get("path"):
                no_source_path.append(snapshot.path)

        if missing_from or no_source_path:
            evidence = tuple(
                Evidence(
                    kind="manifest",
                    path=str(path),
                    expected=(
                        f"a layers[] entry with product={product!r} "
                        f"role={role!r} rank={EXPECTED_RANK_BY_ROLE[role]} "
                        "and source.path set"
                    ),
                    actual="no matching entry",
                )
                for path in missing_from
            ) + tuple(
                Evidence(
                    kind="manifest",
                    path=str(path),
                    expected="source.path set",
                    actual="matching entry has no source.path",
                )
                for path in no_source_path
            )
            plural = "y" if len(no_source_path) == 1 else "ies"
            results.append(
                _CS_DECL.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    expected_today=ExpectedToday.FAIL,
                    evidence=evidence,
                    detail=(
                        f"missing from {len(missing_from)}/{len(loadable)} "
                        f"manifest(s); {len(no_source_path)} matching "
                        f"entr{plural} lack source.path"
                    ),
                )
            )
        else:
            results.append(
                _CS_DECL.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=ExpectedToday.PASS,
                    detail=f"declared with source.path set in all {len(loadable)} checked manifest(s)",
                )
            )
    return results


# ---------------------------------------------------------------------------
# CS-PATH
# ---------------------------------------------------------------------------


def check_cs_path(
    cells: Sequence[tuple[str, str]], snapshots: Sequence[ManifestSnapshot]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for product, role in cells:
        subject = _cell_id(product, role)
        found = _first_match(snapshots, product, role)
        if found is None:
            results.append(
                _CS_PATH.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="no manifest entry to read source.path from (see CS-DECL)",
                )
            )
            continue

        _, layer = found
        raw_path = layer.get("source", {}).get("path")
        if not raw_path:
            results.append(
                _CS_PATH.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="matching entry has no source.path (see CS-DECL)",
                )
            )
            continue

        source_path = Path(raw_path)
        git_dir = source_path / ".git"
        if source_path.is_dir() and git_dir.exists():
            results.append(
                _CS_PATH.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=ExpectedToday.PASS,
                    detail=f"{source_path} exists with a .git entry",
                )
            )
        else:
            actual = (
                "directory missing" if not source_path.is_dir() else "no .git entry"
            )
            evidence = (
                Evidence(
                    kind="filesystem",
                    path=str(source_path),
                    expected="a directory with a .git entry",
                    actual=actual,
                ),
            )
            results.append(
                _CS_PATH.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    expected_today=ExpectedToday.FAIL,
                    evidence=evidence,
                    detail=f"{source_path} is not a git root ({actual})",
                )
            )
    return results


# ---------------------------------------------------------------------------
# CS-REF-VALID
# ---------------------------------------------------------------------------


def check_cs_ref_valid(
    cells: Sequence[tuple[str, str]], snapshots: Sequence[ManifestSnapshot]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for product, role in cells:
        subject = _cell_id(product, role)
        found = _first_match(snapshots, product, role)
        if found is None:
            results.append(
                _CS_REF_VALID.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="no manifest entry to read source.ref from (see CS-DECL)",
                )
            )
            continue

        manifest_path, layer = found
        source = layer.get("source", {})
        ref = source.get("ref")
        raw_path = source.get("path")

        if not ref:
            evidence = (
                Evidence(
                    kind="manifest",
                    path=str(manifest_path),
                    expected="source.ref set",
                    actual="missing",
                ),
            )
            results.append(
                _CS_REF_VALID.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    expected_today=ExpectedToday.FAIL,
                    evidence=evidence,
                    detail="no source.ref declared for this cell",
                )
            )
            continue

        if not raw_path or not Path(raw_path).is_dir():
            results.append(
                _CS_REF_VALID.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="source.path missing or not a directory (see CS-PATH)",
                )
            )
            continue

        source_path = Path(raw_path)
        check = run_git_readonly(
            ("rev-parse", "--verify", f"{ref}^{{commit}}"), cwd=source_path
        )
        if check.returncode == 0:
            results.append(
                _CS_REF_VALID.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=ExpectedToday.PASS,
                    detail=f"{ref} resolves to {check.stdout.strip()}",
                )
            )
        else:
            evidence = (
                Evidence(
                    kind="git",
                    path=str(source_path),
                    expected=f"{ref!r} resolves to a commit",
                    actual="dangling ref",
                    command=f"git -C {source_path} rev-parse --verify {ref}^{{commit}}",
                    output=(check.stdout + check.stderr).strip(),
                ),
            )
            results.append(
                _CS_REF_VALID.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    expected_today=ExpectedToday.FAIL,
                    evidence=evidence,
                    detail=f"{ref} does not resolve in {source_path}",
                )
            )
    return results


# ---------------------------------------------------------------------------
# CS-ANCESTOR (RC-3)
# ---------------------------------------------------------------------------


def _resolve_default_branch(path: Path) -> str | None:
    """Read-only, no-fetch discovery of the branch CS-ANCESTOR compares
    against -- see the module docstring's "Network-gating" section. Never
    inspects the checked-out HEAD."""

    for candidate in _CANDIDATE_DEFAULT_BRANCH_REFS:
        check = run_git_readonly(
            ("rev-parse", "--verify", f"{candidate}^{{commit}}"), cwd=path
        )
        if check.returncode == 0:
            return candidate
    return None


def _rev_list_count(path: Path, ref: str) -> int | None:
    result = run_git_readonly(("rev-list", "--count", ref), cwd=path)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def check_cs_ancestor(
    cells: Sequence[tuple[str, str]], snapshots: Sequence[ManifestSnapshot]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for product, role in cells:
        subject = _cell_id(product, role)
        found = _first_match(snapshots, product, role)
        if found is None:
            results.append(
                _CS_ANCESTOR.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="no manifest entry (see CS-DECL)",
                )
            )
            continue

        _, layer = found
        source = layer.get("source", {})
        ref = source.get("ref")
        raw_path = source.get("path")

        if not ref or not raw_path or not Path(raw_path).is_dir():
            results.append(
                _CS_ANCESTOR.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="source.ref/source.path unavailable (see CS-PATH/CS-REF-VALID)",
                )
            )
            continue

        path = Path(raw_path)
        ref_check = run_git_readonly(
            ("rev-parse", "--verify", f"{ref}^{{commit}}"), cwd=path
        )
        if ref_check.returncode != 0:
            results.append(
                _CS_ANCESTOR.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="ref does not resolve (see CS-REF-VALID)",
                )
            )
            continue

        branch_ref = _resolve_default_branch(path)
        if branch_ref is None:
            results.append(
                _CS_ANCESTOR.result(
                    subject=subject,
                    verdict=Verdict.SKIP,
                    expected_today=ExpectedToday.PASS,
                    detail=(
                        "no cached "
                        + " or ".join(_CANDIDATE_DEFAULT_BRANCH_REFS)
                        + f" ref in {path} -- CS-ANCESTOR needs a network fetch to "
                        "establish one and this harness never fetches a real repo "
                        "(fsguard's read-only git allowlist excludes 'fetch'); "
                        "explicit SKIP, never a silent fallback to whatever branch "
                        "happens to be checked out"
                    ),
                )
            )
            continue

        ancestry = run_git_readonly(
            ("merge-base", "--is-ancestor", ref, branch_ref), cwd=path
        )
        count = _rev_list_count(path, ref)
        is_ancestor = ancestry.returncode == 0
        evidence = (
            Evidence(
                kind="git-ancestry",
                path=str(path),
                expected=f"{ref!r} is an ancestor of {branch_ref}",
                actual="ancestor" if is_ancestor else "NOT an ancestor",
                detail=f"git rev-list --count {ref} = {count if count is not None else 'unknown'}",
                command=f"git -C {path} merge-base --is-ancestor {ref} {branch_ref}",
                output=(ancestry.stdout + ancestry.stderr).strip(),
            ),
        )
        if is_ancestor:
            results.append(
                _CS_ANCESTOR.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=ExpectedToday.PASS,
                    evidence=evidence,
                    detail=f"{ref} is an ancestor of {branch_ref} (rev-list --count={count})",
                )
            )
        else:
            results.append(
                _CS_ANCESTOR.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    expected_today=ExpectedToday.FAIL,
                    evidence=evidence,
                    detail=(
                        f"{ref} is NOT an ancestor of {branch_ref} (RC-3; "
                        f"rev-list --count={count})"
                    ),
                    root_cause="rc.rc3",
                )
            )
    return results


# ---------------------------------------------------------------------------
# CS-MIRROR
# ---------------------------------------------------------------------------


def _mirrors_root() -> Path:
    """The canonical, read-only mirror root every tier's disposable mirror
    is allowed to live under -- the exact resolution
    `cc.core.ecosystem.mirror.mirror_root()` itself uses
    (`paths.mirrors_root`, defaulting to `~/.copilot/mirrors`), reused via
    the same `resolve_key` primitive rather than re-derived (design rule 1:
    a check never computes ecosystem state it can ask `cc` for)."""

    configured = resolve_key("paths.mirrors_root")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".copilot" / "mirrors"


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_live_authoring_alias() -> Path | None:
    """The one known live-authoring symlink alias confirmed on this machine
    (`~/.claude/copilot` -> claude-foundation's source.path). Reads
    `Path.home()` directly -- inside a World-A test where `apply_fleet_env`
    has monkeypatched `HOME`, this naturally resolves under the synthetic
    fleet's fake home (which never has `.claude/copilot`), so it is a safe
    no-op there; inside a real World-B run it resolves the true alias."""

    candidate = Path.home() / ".claude" / "copilot"
    if not candidate.exists() and not candidate.is_symlink():
        return None
    try:
        return candidate.resolve()
    except OSError:
        return None


def check_cs_mirror(
    cells: Sequence[tuple[str, str]], snapshots: Sequence[ManifestSnapshot]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    alias_target = _resolve_live_authoring_alias()
    mirrors_root = _mirrors_root()

    for product, role in cells:
        subject = _cell_id(product, role)
        found = _first_match(snapshots, product, role)
        if found is None:
            results.append(
                _CS_MIRROR.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="no manifest entry (see CS-DECL)",
                )
            )
            continue

        _, layer = found
        raw_path = layer.get("source", {}).get("path")
        if not raw_path or not Path(raw_path).is_dir():
            results.append(
                _CS_MIRROR.result(
                    subject=subject,
                    verdict=Verdict.COULD_NOT_RUN,
                    detail="source.path missing (see CS-PATH)",
                )
            )
            continue

        path = Path(raw_path)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        not_a_mirror = not _is_under(resolved, mirrors_root)
        status = run_git_readonly(("status", "--porcelain"), cwd=path)
        dirty = bool(status.stdout.strip())
        aliased = alias_target is not None and resolved == alias_target

        if not_a_mirror or dirty or aliased:
            reasons = []
            if not_a_mirror:
                reasons.append(
                    f"source.path is not under the configured mirrors root ({mirrors_root}) -- "
                    "it is the author's primary working tree, not a disposable mirror"
                )
            if dirty:
                reasons.append("working tree has uncommitted changes")
            if aliased:
                reasons.append(
                    f"source.path is the resolved target of a live-authoring alias ({alias_target})"
                )
            evidence = (
                Evidence(
                    kind="mirror-location",
                    path=str(path),
                    expected=f"source.path under the configured mirrors root ({mirrors_root}), clean, and unaliased",
                    actual="; ".join(reasons),
                    command="git status --porcelain" if dirty else None,
                    output=status.stdout.strip() if dirty else None,
                ),
            )
            results.append(
                _CS_MIRROR.result(
                    subject=subject,
                    verdict=Verdict.FAIL,
                    expected_today=ExpectedToday.FAIL,
                    evidence=evidence,
                    detail="; ".join(reasons),
                )
            )
        else:
            results.append(
                _CS_MIRROR.result(
                    subject=subject,
                    verdict=Verdict.PASS,
                    expected_today=ExpectedToday.PASS,
                    detail=f"under the configured mirrors root ({mirrors_root}), clean, and unaliased",
                )
            )
    return results


# ---------------------------------------------------------------------------
# CS-SIGNERS
# ---------------------------------------------------------------------------


def check_cs_signers(
    products: Sequence[str], snapshots: Sequence[ManifestSnapshot]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for product in products:
        for role in TIER_ROLES:
            subject = _cell_id(product, role)
            if role != "foundation":
                results.append(
                    _CS_SIGNERS.result(
                        subject=subject,
                        verdict=Verdict.SKIP,
                        expected_today=ExpectedToday.PASS,
                        detail=(
                            "not applicable -- CS-SIGNERS only evaluates "
                            "foundation-tier layers (policy.allowed_signers "
                            "is a foundation-only compiled-in trust-root "
                            "declaration, CLAUDE.md invariant #4)"
                        ),
                    )
                )
                continue

            found = _first_match(snapshots, product, role)
            if found is None:
                results.append(
                    _CS_SIGNERS.result(
                        subject=subject,
                        verdict=Verdict.COULD_NOT_RUN,
                        detail="no manifest entry for this foundation (see CS-DECL)",
                    )
                )
                continue

            manifest_path, layer = found
            signers = (layer.get("policy") or {}).get("allowed_signers") or []
            if signers:
                results.append(
                    _CS_SIGNERS.result(
                        subject=subject,
                        verdict=Verdict.PASS,
                        expected_today=ExpectedToday.PASS,
                        detail=f"{len(signers)} allowed signer(s) declared",
                    )
                )
            else:
                evidence = (
                    Evidence(
                        kind="manifest-policy",
                        path=str(manifest_path),
                        expected="policy.allowed_signers non-empty",
                        actual="[]",
                        detail=f"layer id {layer.get('id')!r}",
                    ),
                )
                results.append(
                    _CS_SIGNERS.result(
                        subject=subject,
                        verdict=Verdict.FAIL,
                        expected_today=ExpectedToday.FAIL,
                        evidence=evidence,
                        detail="no compiled-in trust root expressed for this foundation",
                    )
                )
    return results


# ---------------------------------------------------------------------------
# CS-DIM (RC-5)
# ---------------------------------------------------------------------------


def check_cs_dim(
    products: Sequence[str], snapshots: Sequence[ManifestSnapshot]
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for product in products:
        for role in TIER_ROLES:
            subject = _cell_id(product, role)
            if role == "foundation":
                results.append(
                    _CS_DIM.result(
                        subject=subject,
                        verdict=Verdict.SKIP,
                        expected_today=ExpectedToday.PASS,
                        detail=(
                            "not applicable -- CS-DIM evaluates "
                            "copilot.layer.yml, which only tier-variant "
                            "repos carry; foundations are the canonical "
                            "dimension source, not a consumer of it"
                        ),
                    )
                )
                continue

            found = _first_match(snapshots, product, role)
            if found is None:
                results.append(
                    _CS_DIM.result(
                        subject=subject,
                        verdict=Verdict.COULD_NOT_RUN,
                        detail="no manifest entry (see CS-DECL)",
                    )
                )
                continue

            _, layer = found
            raw_path = layer.get("source", {}).get("path")
            if not raw_path or not Path(raw_path).is_dir():
                results.append(
                    _CS_DIM.result(
                        subject=subject,
                        verdict=Verdict.COULD_NOT_RUN,
                        detail="source.path missing (see CS-PATH)",
                    )
                )
                continue

            layer_file = Path(raw_path) / _COPILOT_LAYER_YML
            if not layer_file.is_file():
                evidence = (
                    Evidence(
                        kind="filesystem",
                        path=str(layer_file),
                        expected="a copilot.layer.yml with a non-empty dimensions: list",
                        actual="file does not exist",
                    ),
                )
                results.append(
                    _CS_DIM.result(
                        subject=subject,
                        verdict=Verdict.FAIL,
                        expected_today=ExpectedToday.FAIL,
                        evidence=evidence,
                        detail="no copilot.layer.yml at all -- worse than an empty dimensions list",
                        root_cause="rc.rc5",
                    )
                )
                continue

            try:
                raw = yaml.safe_load(layer_file.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                results.append(
                    _CS_DIM.result(
                        subject=subject,
                        verdict=Verdict.COULD_NOT_RUN,
                        detail=f"{layer_file} is not valid YAML: {exc}",
                    )
                )
                continue

            dimensions = raw.get("dimensions") if isinstance(raw, dict) else None
            if isinstance(dimensions, list) and dimensions:
                results.append(
                    _CS_DIM.result(
                        subject=subject,
                        verdict=Verdict.PASS,
                        expected_today=ExpectedToday.PASS,
                        detail=f"{len(dimensions)} dimension(s) declared: {dimensions!r}",
                    )
                )
            else:
                evidence = (
                    Evidence(
                        kind="copilot-layer-yml",
                        path=str(layer_file),
                        expected="dimensions: [<non-empty>]",
                        actual=f"dimensions: {dimensions!r}",
                    ),
                )
                results.append(
                    _CS_DIM.result(
                        subject=subject,
                        verdict=Verdict.FAIL,
                        expected_today=ExpectedToday.FAIL,
                        evidence=evidence,
                        detail="dimensions: [] -- declares no content despite being a tier-variant layer",
                        root_cause="rc.rc5",
                    )
                )
    return results


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_stack_checks(
    *,
    products: Sequence[str] = DEFAULT_PRODUCTS,
    manifest_paths: Sequence[Path],
) -> list[CheckResult]:
    """Run all 7 CS-* checks across `products` x `TIER_ROLES`, against the
    manifest(s) at `manifest_paths`. The single entry point both a
    machine-truth caller (`manifest_paths=discover_real_manifest_paths()`)
    and a synthetic-fleet caller (`manifest_paths=[handle.manifest_path]`)
    use."""

    cells = [(product, role) for product in products for role in TIER_ROLES]
    snapshots = load_manifest_snapshots(manifest_paths)

    results: list[CheckResult] = []
    results += check_cs_decl(cells, snapshots)
    results += check_cs_path(cells, snapshots)
    results += check_cs_ref_valid(cells, snapshots)
    results += check_cs_ancestor(cells, snapshots)
    results += check_cs_mirror(cells, snapshots)
    results += check_cs_signers(products, snapshots)
    results += check_cs_dim(products, snapshots)
    return results


__all__ = [
    "DEFAULT_PRODUCTS",
    "EXPECTED_RANK_BY_ROLE",
    "ManifestSnapshot",
    "TIER_ROLES",
    "check_cs_ancestor",
    "check_cs_decl",
    "check_cs_dim",
    "check_cs_mirror",
    "check_cs_path",
    "check_cs_ref_valid",
    "check_cs_signers",
    "discover_real_manifest_paths",
    "load_manifest_snapshot",
    "load_manifest_snapshots",
    "run_stack_checks",
]
