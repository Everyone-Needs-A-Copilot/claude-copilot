"""D13 -- Scanner reachability (`RUBRIC.md` D13, `HARNESS-DESIGN.md`
repo.d13.scanner_reachable).

A meta-dimension: it decides whether any of D1-D12 can ever be
*maintained*. Two independent, read-only facts:

  - `repo.d13.scanner_reachable` -- per repo: is `.git` present, is the
    repo nested under a configured `projects.roots` entry, and is it
    neither excluded (`~/.copilot/excluded-projects.json`) nor held
    (`~/.copilot/project-integration-holds.json`)? A non-git directory that
    nonetheless carries a full framework install (`COPILOT/playground`,
    `PERSONAL/investr-api`) is reported E-with-orphaned-install: a FAIL
    with concrete evidence, never a silent SKIP/NA -- `RUBRIC.md` section 1
    is explicit that non-Git-ness is a *scan* exclusion, not an *install*
    exclusion. The owner has ratified `git init` for both
    (`docs/ecosystem-audit-open-questions.md` Q16-A, Q20-B).

  - `repo.d13.registries_are_empty` -- retained as a stable compatibility
    id, but now asserts the durable intent behind its original name: a
    machine registry is absent OR every exclusion it carries is attributable
    to structured review evidence.  Ratified exclusions emit one explicit
    global SKIP plus a per-path SKIP; an unreviewed path still fails.  This
    avoids treating owner-approved Q14 decisions as silent defects without
    turning an opaque registry into a pass.

`shared-docs` is a real, live complication: it is a symlink to
`knowledge-copilot-internal` (`readlink` confirmed, identical inode,
verified live 2026-08-10). The real scanner already does the right thing
here BY CONSTRUCTION -- `core/ecosystem/workspaces.py::_scan_root` skips a
symlinked child before ever testing it for `.git` -- so `shared-docs` is
correctly invisible to a scan while `knowledge-copilot-internal` is
separately reachable. `check_scanner_reachable` special-cases a symlinked
subject so a future sweep never double-counts the alias as its own broken
subject; `dedupe_repos_by_realpath` is the same dedup, exposed for whatever
builds the fleet-wide repo list (`sweep.py`, once it lands).

Every filesystem action here is a plain read (`Path.exists`/`.resolve`/
`.glob`) or a call into the existing, already-read-only
`cc.core.ecosystem.workspaces` registry readers (`is_project_excluded`,
`integration_hold`) -- never a write, and no git plumbing is needed at all.

`run(context)` below implements the `dimensions/__init__.py` module
contract (`DimensionModule`/`RepoContext`, owned by WP-4), which has since
landed. Per that contract, `run()` returns a result for EVERY check id this
module registers -- including `repo.d13.registries_are_empty`, even though
it is `Scope.GLOBAL`. `sweep.py` is expected to dedupe identical
GLOBAL-scope results across repos (a machine-wide fact reported once per
call here is still one fact, not `len(fleet)` of them); this module's job
under the contract is only to never silently omit a registered id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from cc.core.config import resolve_key
from cc.core.conformance.exclusions import (
    DEFAULT_REVIEWED_EXCLUSIONS,
    ReviewedExclusion,
    find_reviewed_exclusion,
)
from cc.core.conformance.registry import register_check
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
from cc.core.ecosystem.workspaces import (
    default_excluded_registry,
    default_integration_holds_registry,
    integration_hold,
    is_project_excluded,
)

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

# Machine-verified today (`RUBRIC.md` section 1's E-with-orphaned-install
# carve-out; `TEST-MATRIX.md` IC-D13-REACHABLE's "+2 informational" row;
# `docs/ecosystem-audit-open-questions.md` Q16/Q20): neither is a git root
# (confirmed live: no `.git` under either path), so both are permanently
# invisible to `/update-project` and `cc workspace --all` even though
# `playground` carries a full 21-file `.claude/agents/` install. The owner
# has ratified `git init` for both (Q16-A, Q20-B).
KNOWN_NOT_GIT_ROOT_REPOS: frozenset[str] = frozenset({"playground", "investr-api"})

_APPLIES_TO = ("A", "B", "C", "D", "E")  # RUBRIC.md D13: "Applies to: all classes."

_SCANNER_REACHABLE_CHECK = register_check(
    id="repo.d13.scanner_reachable",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "The directory is a git root under a configured projects.roots "
        "entry, and is neither excluded nor held."
    ),
    remediation=(
        "git init the directory (Q16-A / Q20-B) so it becomes a real git "
        "root and is picked up by the next projects.roots scan; if it is "
        "meant to stay excluded, record that explicitly in "
        "excluded-projects.json rather than leaving it silently "
        "unreachable."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)

_REGISTRIES_EMPTY_CHECK = register_check(
    id="repo.d13.registries_are_empty",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.GLOBAL,
    summary=(
        "Machine-local project exclusion/hold registries are absent, or "
        "every excluded path carries an attributable reviewed disposition."
    ),
    remediation=(
        "Remove empty/obsolete registry files, or add a bounded reviewed "
        "exclusion record carrying path, reason, authority, review evidence, "
        "and review date. Never accept an opaque path merely because it is "
        "already in excluded-projects.json."
    ),
    mode=Mode.FAST,
    applies_to_classes=(),
    expected_today=ExpectedToday.PASS,
)


def resolve_realpath(path: Path) -> Path:
    """Resolve symlinks/`..` to a canonical, inode-comparable path. Falls
    back to the input unresolved if resolution fails (a non-git-root
    subject like `investr-api` must never crash the check)."""

    try:
        return path.resolve()
    except OSError:
        return path


def dedupe_repos_by_realpath(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Collapse paths that are the same real file/inode (e.g. `shared-docs`
    and its `knowledge-copilot-internal` symlink target) down to the
    first-seen spelling, preserving order. For a future `sweep.py` building
    the fleet-wide repo list -- so a symlink alias is never processed as if
    it were its own, separately-broken subject."""

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        real = resolve_realpath(path)
        if real in seen:
            continue
        seen.add(real)
        ordered.append(path)
    return tuple(ordered)


def _configured_roots(configured_roots: Sequence[Path] | None) -> tuple[Path, ...]:
    if configured_roots is not None:
        return tuple(resolve_realpath(Path(root)) for root in configured_roots)
    raw = resolve_key("projects.roots") or []  # never raises -- config.py contract
    if isinstance(raw, str):
        raw = [raw]
    return tuple(resolve_realpath(Path(str(entry)).expanduser()) for entry in raw)


def _under_a_configured_root(repo_real: Path, roots: Sequence[Path]) -> bool:
    return any(repo_real == root or root in repo_real.parents for root in roots)


def _expected_today(repo: Path) -> ExpectedToday:
    return (
        ExpectedToday.FAIL
        if repo.name in KNOWN_NOT_GIT_ROOT_REPOS
        else ExpectedToday.PASS
    )


def check_scanner_reachable(
    repo: Path,
    *,
    configured_roots: Sequence[Path] | None = None,
    excluded_registry: Path | None = None,
    holds_registry: Path | None = None,
    reviewed_exclusions: Sequence[ReviewedExclusion] = DEFAULT_REVIEWED_EXCLUSIONS,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """`repo.d13.scanner_reachable` against one repo."""

    name = subject or str(repo)
    expected = expected_today if expected_today is not None else _expected_today(repo)

    # A symlinked subject (e.g. shared-docs -> knowledge-copilot-internal)
    # is correctly invisible to the real scanner BY DESIGN (_scan_root
    # skips symlinked children before ever testing them for `.git`) --
    # report reachability against the canonical target rather than flagging
    # the alias itself as broken. The relationship is always named in the
    # result, never silently collapsed.
    if repo.is_symlink():
        target = resolve_realpath(repo)
        target_result = check_scanner_reachable(
            target,
            configured_roots=configured_roots,
            excluded_registry=excluded_registry,
            holds_registry=holds_registry,
            subject=str(target),
        )
        detail = (
            f"symlink alias of {target} (same inode); the real scanner "
            "skips symlinked children by design, so reachability is "
            "reported against the canonical target"
        )
        return _SCANNER_REACHABLE_CHECK.result(
            subject=name,
            verdict=target_result.verdict,
            evidence=target_result.evidence,
            expected_today=target_result.expected_today,
            detail=detail,
        )

    is_git_root = (repo / ".git").exists()
    if not is_git_root:
        agents_dir = repo / ".claude" / "agents"
        agent_count = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0
        detail = (
            f"carries a framework install ({agent_count} agent file(s) "
            "under .claude/agents/) and is therefore permanently invisible "
            "to /update-project and cc workspace --all -- non-Git-ness is a "
            "scan exclusion, not an install exclusion"
            if agent_count
            else "no framework install found either"
        )
        return _SCANNER_REACHABLE_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="git-root",
                    path=str(repo),
                    expected=".git present (a real git root)",
                    actual="not a git root",
                    detail=detail,
                ),
            ),
        )

    repo_real = resolve_realpath(repo)
    roots = _configured_roots(configured_roots)
    if not _under_a_configured_root(repo_real, roots):
        return _SCANNER_REACHABLE_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="projects-roots",
                    path=str(repo_real),
                    expected=f"nested under one of {[str(r) for r in roots]}",
                    actual="not under any configured projects.roots entry",
                ),
            ),
        )

    excluded_path = (
        excluded_registry
        if excluded_registry is not None
        else default_excluded_registry()
    )
    if is_project_excluded(repo, registry=excluded_path):
        reviewed = find_reviewed_exclusion(repo, reviewed=reviewed_exclusions)
        if reviewed is not None:
            return _SCANNER_REACHABLE_CHECK.result(
                subject=name,
                verdict=Verdict.SKIP,
                expected_today=expected,
                evidence=(reviewed.evidence(repo),),
                detail=(
                    "Intentionally excluded from fan-out by a reviewed owner "
                    "decision; the repository is reachable but is not an "
                    "eligible maintenance target."
                ),
            )
        return _SCANNER_REACHABLE_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="excluded-projects",
                    path=str(excluded_path),
                    expected="not listed in excluded-projects.json",
                    actual="listed as excluded",
                ),
            ),
        )

    holds_path = (
        holds_registry
        if holds_registry is not None
        else default_integration_holds_registry()
    )
    hold = integration_hold(repo, registry=holds_path)
    if hold is not None:
        return _SCANNER_REACHABLE_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=(
                Evidence(
                    kind="integration-holds",
                    path=str(holds_path),
                    expected="not held in project-integration-holds.json",
                    actual=f"held: {hold}",
                ),
            ),
        )

    return _SCANNER_REACHABLE_CHECK.result(
        subject=name, verdict=Verdict.PASS, expected_today=expected
    )


def check_registries_are_empty(
    *,
    projects_registry: Path | None = None,
    excluded_registry: Path | None = None,
    holds_registry: Path | None = None,
    subject: str = "machine",
    reviewed_exclusions: Sequence[ReviewedExclusion] = DEFAULT_REVIEWED_EXCLUSIONS,
) -> CheckResult:
    """One global registry-disposition assertion, never per repo.

    The check id is intentionally stable for baseline compatibility.  An
    absent registry passes.  A registry containing only attributable reviewed
    exclusions skips with one evidence record per path.  Empty, malformed,
    opaque, or unmatched registries fail.
    """

    default_projects = Path(str(resolve_key("projects.registry"))).expanduser()
    candidates = {
        "projects.json": projects_registry or default_projects,
        "excluded-projects.json": excluded_registry or default_excluded_registry(),
        "project-integration-holds.json": (
            holds_registry or default_integration_holds_registry()
        ),
    }

    present = {name: path for name, path in candidates.items() if path.is_file()}
    if not present:
        return _REGISTRIES_EMPTY_CHECK.result(subject=subject, verdict=Verdict.PASS)

    failures: list[Evidence] = []
    reviewed_evidence: list[Evidence] = []

    # projects.json adds discovery candidates rather than excluding them, but
    # the legacy global check intentionally treats a newly-created registry
    # as review-worthy until a dedicated structured contract exists.
    projects_path = present.get("projects.json")
    if projects_path is not None:
        failures.append(
            Evidence(
                kind="unreviewed-registry-file",
                path=str(projects_path),
                expected="absent or covered by a dedicated reviewed registry contract",
                actual="exists",
                detail="owning_actor=ecosystem operator",
            )
        )

    excluded_path = present.get("excluded-projects.json")
    if excluded_path is not None:
        try:
            payload = json.loads(excluded_path.read_text(encoding="utf-8"))
            excluded_paths = payload.get("paths") if isinstance(payload, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            excluded_paths = None
        if not isinstance(excluded_paths, list) or not excluded_paths:
            failures.append(
                Evidence(
                    kind="unreviewed-exclusion-registry",
                    path=str(excluded_path),
                    expected="a non-empty schema-1.0 paths list with one reviewed record per path",
                    actual="empty, malformed, or unreadable registry",
                    detail="owning_actor=ecosystem operator",
                )
            )
        else:
            for raw_path in excluded_paths:
                if not isinstance(raw_path, str) or not raw_path:
                    failures.append(
                        Evidence(
                            kind="unreviewed-exclusion",
                            path=str(excluded_path),
                            expected="a non-empty path string with reviewed metadata",
                            actual=repr(raw_path),
                            detail="owning_actor=ecosystem operator",
                        )
                    )
                    continue
                reviewed = find_reviewed_exclusion(
                    raw_path, reviewed=reviewed_exclusions
                )
                if reviewed is None:
                    failures.append(
                        Evidence(
                            kind="unreviewed-exclusion",
                            path=raw_path,
                            expected=(
                                "a reviewed exclusion with reason, authority, "
                                "review evidence, and review date"
                            ),
                            actual="no matching reviewed exclusion",
                            detail=f"registry={excluded_path}; owning_actor=ecosystem operator",
                        )
                    )
                else:
                    reviewed_evidence.append(reviewed.evidence(raw_path))

    holds_path = present.get("project-integration-holds.json")
    if holds_path is not None:
        try:
            payload = json.loads(holds_path.read_text(encoding="utf-8"))
            holds = payload.get("holds") if isinstance(payload, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            holds = None
        if not isinstance(holds, dict) or not holds:
            failures.append(
                Evidence(
                    kind="unreviewed-hold-registry",
                    path=str(holds_path),
                    expected="non-empty owner-decision holds with inspection_id and plan_id",
                    actual="empty, malformed, or unreadable registry",
                    detail="owning_actor=project integration owner",
                )
            )
        else:
            for key, hold in holds.items():
                reviewed = (
                    isinstance(key, str)
                    and key.startswith("sha256:")
                    and isinstance(hold, dict)
                    and hold.get("classification") == "owner-decision"
                    and isinstance(hold.get("inspection_id"), str)
                    and bool(hold.get("inspection_id"))
                    and isinstance(hold.get("plan_id"), str)
                    and bool(hold.get("plan_id"))
                )
                if not reviewed:
                    failures.append(
                        Evidence(
                            kind="unreviewed-integration-hold",
                            path=str(holds_path),
                            expected="opaque key plus owner-decision, inspection_id, and plan_id",
                            actual=f"invalid hold entry {key!r}",
                            detail="owning_actor=project integration owner",
                        )
                    )
                else:
                    reviewed_evidence.append(
                        Evidence(
                            kind="reviewed-integration-hold",
                            path=str(holds_path),
                            expected="temporary owner-reviewed hold",
                            actual="authority=owner-decision",
                            detail=(
                                f"review_evidence=inspection:{hold['inspection_id']};"
                                f"plan:{hold['plan_id']}"
                            ),
                        )
                    )

    if failures:
        return _REGISTRIES_EMPTY_CHECK.result(
            subject=subject,
            verdict=Verdict.FAIL,
            evidence=tuple(failures),
            detail=(
                f"{len(failures)} registry entry or file condition(s) lack "
                "attributable review evidence"
            ),
        )

    return _REGISTRIES_EMPTY_CHECK.result(
        subject=subject,
        verdict=Verdict.SKIP,
        evidence=tuple(reviewed_evidence),
        detail=(
            f"{len(reviewed_evidence)} intentional exclusion/hold disposition(s) "
            "are attributable; emitted as reviewed exceptions, never as PASS"
        ),
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` per registered D13 check id, for every repo.
    `repo.d13.scanner_reachable` applies to every rubric class (`RUBRIC.md`
    D13: "Applies to: all classes"), so its `Verdict.SKIP` branch is
    unreachable in practice but kept for symmetry with every other
    dimension module. `repo.d13.registries_are_empty` declares no
    `applies_to_classes` restriction at all, so it is never skipped by
    class -- see module docstring for why it is still produced once per
    `run()` call rather than only once per sweep."""

    results: list[CheckResult] = []
    if context.rubric_class not in _APPLIES_TO:
        results.append(
            _SCANNER_REACHABLE_CHECK.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D13 applies to "
                    "all classes; this should not occur."
                ),
            )
        )
    else:
        results.append(check_scanner_reachable(context.path, subject=context.subject))
    # Constant subject ("machine"), never context.subject: this is one
    # machine-wide fact, not a claim about THIS repo -- using a fixed
    # subject means every repo's call produces an identical (id, subject)
    # key, so any consumer that dedupes on that pair collapses it to one
    # entry for free, rather than needing repo-aware special-casing.
    results.append(check_registries_are_empty())
    return tuple(results)


__all__ = [
    "KNOWN_NOT_GIT_ROOT_REPOS",
    "check_registries_are_empty",
    "check_scanner_reachable",
    "dedupe_repos_by_realpath",
    "resolve_realpath",
    "run",
]
