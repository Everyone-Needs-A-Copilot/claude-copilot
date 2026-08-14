"""Layer 1 — tier / hierarchy resolution checks.

Implements the 9 test ids in `TEST-MATRIX.md` section 1 ("Hierarchy"),
verbatim: H-1 through H-9. Every check here is a PURE function of its
inputs (`HARNESS-DESIGN.md` §3.2 rule 2) — nothing in this module calls
`resolve_knowledge_repos()`, `cc.commands.env.run_env()`, or reads the real
manifest itself. Callers (the test face here, and eventually WP-8's CLI
surface) supply real-machine data or synthetic-fleet data through the same
parameters, so every check runs unmodified in both World A and World B
(`HARNESS-DESIGN.md` §5.1).

Wraps only (`HARNESS-DESIGN.md` §3.2 rule 1 — "a check never computes
ecosystem state it can ask `cc` for"):
  - `cc.core.extensions_resolver.resolve_extension` — H-1, H-2, H-3 (agent
    extension precedence; this IS `cc extensions resolve`'s own resolution
    function, called in-process).
  - `cc.core.config.get_resolved_config` — H-9 (project-over-machine config
    cascade; this IS what `cc env`/`cc config` read).
  - Manifest layer data (already loaded + validated by
    `cc.core.ecosystem.manifest`) — H-4's ladder-order comparison reads
    already-validated layer dicts, never re-parses or re-validates a
    manifest itself.

Two checks are net-new (`HARNESS-DESIGN.md` §2.4 item 1 — "no code anywhere
checks that a winning tier's content is *substantive*"):
  - H-3 (`tier.shadow.substance`) — the Q25 shadow-substance bug. Traced in
    `extensions_resolver.py:210-237`: the only content gate on the winning
    extension file is `file_abs.is_file()`; there is no substance check
    anywhere in that code path. This module is the detector, not a fix —
    it stayed FAIL until the scaffold was filled with real content (owner
    ratified answer: Q25 = A); re-verified live 2026-08-10 that the
    personal `cw.extension.md` scaffold now carries real, substantive
    content, so this check now PASSes (it still FAILs if a future scaffold
    regresses).
  - H-5 (`tier.knowledge.singular_alias_paths_exist`) — the Q24 ladder-
    integrity bug. `cc env`'s `CC_KNOWLEDGE_REPO` (singular, back-compat
    alias, `commands/env.py:116-121`) always carries only the FIRST ladder
    entry; three framework agents (`cw`, `sd`, `ta`) used to dereference
    five sub-paths under that singular scalar that existed only in a
    FARTHER tier. This module extracts the sub-paths those agents actually
    reference (by regex over their own file text — never a hardcoded
    sub-path list, so the check tracks the agents' real content rather
    than a snapshot of it) and asserts each one exists under whichever
    repo the singular alias currently resolves to. Re-verified live
    2026-08-10 (owner ratified answer: Q24 = A): cw/sd/ta were migrated to
    walk `CC_KNOWLEDGE_REPOS` first-existing-wins instead, so none of them
    dereferences the singular alias any more — this check now SKIPs for
    all three (nothing left to exercise it against), rather than FAILing.

H-8 (`tier.precedence.commands_dimension_has_no_consumer`) is also net-new
in a narrower sense: it does not compute resolution at all. `TEST-MATRIX.md`
H-8's own fail criterion is "the harness cannot locate any consumer of
`dimensions:` at all", so this check is a grep-shaped absence assertion,
the same shape Layer 6's RC regression pins use.
`find_dimensions_consumers` structurally excludes its own `core/conformance/`
package (see `_is_under_excluded_package` below) so this stays a true
absence assertion regardless of how wide a caller's `source_root` is —
before that exclusion existed, scanning the whole `src/cc` tree found the
checkers themselves (`root_causes.py`, `stack.py`, this file) reading
`dimensions:` for read-only inspection and reported a false PASS ("a
consumer exists") purely because the check's own package matched its own
pattern; re-verified live 2026-08-11 that with the exclusion in place, the
real framework now has a consumer in `core/ecosystem/discovery.py`. The
consumer surface is checked once across `src/cc`; a sibling directory with
no duplicate implementation is not a separate capability failure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
from cc.core.extensions_resolver import ACTION_APPLY, resolve_extension

# `resolve_extension`'s own signature types `missing_skills_checker` as
# `Callable[[list[str]], list[str]] | None`; extensions_resolver.py does not
# export a named alias for it, so we spell the same shape locally rather
# than import a private detail.
MissingSkillsChecker = Callable[[list[str]], list[str]]

# ---------------------------------------------------------------------------
# Registration — the 9 TEST-MATRIX.md §1 test ids, verbatim.
# ---------------------------------------------------------------------------

H1_NEAREST_DECLARED_WINS = register_check(
    id="tier.precedence.nearest_declared_wins",
    layer=Layer.TIER,
    severity=Severity.S0,
    scope=Scope.GLOBAL,
    summary=(
        "TEST-MATRIX H-1: the nearest tier that DECLARES an agent extension "
        "wins resolution (personal 10 > department 20 > organization 30 > "
        "foundation 40)"
    ),
    remediation=(
        "n/a -- descriptive regression guard over "
        "extensions_resolver.resolve_extension's iteration-order contract; "
        "if this fails, the ladder-walk itself has broken, not a single "
        "repo's content"
    ),
    expected_today=ExpectedToday.PASS,
)

H2_ABSENCE_IS_NOT_SHADOW = register_check(
    id="tier.precedence.absence_is_not_shadow",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.GLOBAL,
    summary=(
        "TEST-MATRIX H-2: a farther tier's real content is not silently "
        "shadowed by a nearer tier's simple ABSENCE (no declaration at all)"
    ),
    remediation="n/a -- descriptive regression guard, same mechanism as H-1",
    expected_today=ExpectedToday.PASS,
)

H3_SHADOW_SUBSTANCE = register_check(
    id="tier.shadow.substance",
    layer=Layer.TIER,
    severity=Severity.S0,
    scope=Scope.PER_TIER,
    summary=(
        "TEST-MATRIX H-3 (owner decision Q25): a nearer tier's WINNING "
        "content must be substantive -- not an empty/draft scaffold "
        "silently shadowing real upstream content"
    ),
    remediation=(
        "Q25 answer A -- fill the personal scaffold extension file with "
        "real content, or withdraw its knowledge-manifest.json entry so "
        "resolution falls through to the real upstream content"
    ),
    # Was FAIL (the bug); Q25 answer A has been applied -- the personal
    # cw.extension.md scaffold now carries real, substantive content
    # (re-verified live 2026-08-10). Re-flip to FAIL if a future scaffold
    # regresses.
    expected_today=ExpectedToday.PASS,
)

H4_LADDER_ORDER = register_check(
    id="tier.knowledge.ladder_order",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.GLOBAL,
    summary=(
        "TEST-MATRIX H-4: CC_KNOWLEDGE_REPOS exports the full knowledge "
        "ladder in ascending-rank (nearest-first) order"
    ),
    remediation="n/a -- descriptive regression guard over cc env's ladder export",
    expected_today=ExpectedToday.PASS,
)

H5_SINGULAR_ALIAS_PATHS_EXIST = register_check(
    id="tier.knowledge.singular_alias_paths_exist",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.GLOBAL,
    summary=(
        "TEST-MATRIX H-5 (owner decision Q24): every $CC_KNOWLEDGE_REPO "
        "sub-path a framework agent dereferences actually exists under "
        "wherever the singular back-compat alias resolves today"
    ),
    remediation=(
        "Q24 answer A -- migrate cw/sd/ta to walk the CC_KNOWLEDGE_REPOS "
        "ladder instead of dereferencing the singular CC_KNOWLEDGE_REPO alias"
    ),
    # Was FAIL (the bug); Q24 answer A has been applied -- cw/sd/ta were
    # migrated to walk CC_KNOWLEDGE_REPOS first-existing-wins, so no
    # framework agent dereferences the singular alias any more (every
    # agent now SKIPs this check, having nothing to exercise it against;
    # re-flip to FAIL if a future agent reintroduces a $CC_KNOWLEDGE_REPO
    # sub-path reference).
    expected_today=ExpectedToday.PASS,
)

H6_DECLARED_SKILL_PATHS_EXIST = register_check(
    id="tier.knowledge.declared_skill_paths_exist",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.PER_TIER,
    summary=(
        "TEST-MATRIX H-6: every skills.local[] path a tier's "
        "knowledge-manifest.json declares exists on disk"
    ),
    remediation=(
        "remove or correct the dangling skills.local[] entry, or add the "
        "missing knowledge-manifest.json if the rung has none at all"
    ),
    expected_today=ExpectedToday.PASS,
)

H7_NO_HOLLOW_RUNG = register_check(
    id="tier.knowledge.no_hollow_rung",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.GLOBAL,
    summary="TEST-MATRIX H-7: every rank in the knowledge ladder has a knowledge-manifest.json",
    remediation="add a knowledge-manifest.json (even a minimal one) to the hollow rung",
    # Was FAIL (the department rung was hollow); Q26 closed it --
    # knowledge-copilot-accounting now has its own knowledge-manifest.json,
    # so all 4 ladder rungs are real. Re-flip to FAIL if a rung goes
    # hollow again.
    expected_today=ExpectedToday.PASS,
)

H8_COMMANDS_DIMENSION_HAS_NO_CONSUMER = register_check(
    id="tier.precedence.commands_dimension_has_no_consumer",
    layer=Layer.TIER,
    severity=Severity.S2,
    scope=Scope.GLOBAL,
    summary=(
        "TEST-MATRIX H-8 (fixture-only, no live instance): a populated "
        "copilot.layer.yml `dimensions:` array has at least one real "
        "consumer that reads it to shadow/materialize a command by tier "
        "precedence"
    ),
    remediation=(
        "build the missing consumer (a command-materialize step that "
        "reads a layer's declared `dimensions:`), or fold command-"
        "dimension declarations into an existing materialize path"
    ),
    # Was uniformly FAIL while dimensions was write-only. The real consumer
    # now lives in `core/ecosystem/discovery.py` and feeds the materialization
    # path, so the one framework-wide verdict is expected to pass.
    expected_today=ExpectedToday.PASS,
)

H9_PROJECT_OVERRIDES_MACHINE_LADDER = register_check(
    id="tier.config.project_overrides_machine_ladder",
    layer=Layer.TIER,
    severity=Severity.S1,
    scope=Scope.GLOBAL,
    summary=(
        "TEST-MATRIX H-9 (fixture-only, no live instance): a project's "
        "explicit literal paths.knowledge_repo overrides the machine "
        "@machine ladder default"
    ),
    remediation="n/a -- descriptive regression guard over the ordinary config cascade",
    expected_today=ExpectedToday.PASS,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _repo_declares_agent(repo: str, agent: str) -> bool:
    """Whether `repo`'s own `knowledge-manifest.json` declares an
    `extensions[]` entry for `agent` -- a plain declaration check (does an
    entry with this agent name exist in the list), never resolution
    semantics (no type/override/fallback/`requiredSkills` handling, no
    file-existence check). Deliberately independent of
    `resolve_extension()` so H-1/H-2/H-3 compare `resolve_extension`'s
    actual winner against an EXPECTATION built by a different code path --
    comparing a function's output to itself would prove nothing (an
    always-agrees tautology can never catch a real regression)."""

    manifest_path = Path(repo).expanduser() / "knowledge-manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    extensions = data.get("extensions")
    if not isinstance(extensions, list):
        return False
    return any(
        isinstance(entry, dict) and entry.get("agent") == agent for entry in extensions
    )


def _declaring_repos_in_order(
    agent: str, knowledge_repos: Sequence[str]
) -> tuple[str, ...]:
    """Which repos, in ladder order, declare an `extensions[]` entry for
    `agent` at all -- regardless of whether that entry ultimately wins.
    See `_repo_declares_agent` for why this reads manifests directly
    instead of calling `resolve_extension` per-repo."""

    return tuple(repo for repo in knowledge_repos if _repo_declares_agent(repo, agent))


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.MULTILINE)


def _frontmatter_status(text: str) -> str | None:
    """Extract the `status:` value from a file's leading YAML frontmatter
    block, or `None` if there is no frontmatter or no `status:` key."""

    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    status_match = _STATUS_RE.search(match.group(1))
    return status_match.group(1) if status_match else None


_ALIAS_SUBPATH_RE = re.compile(r"\$CC_KNOWLEDGE_REPO/([A-Za-z0-9_.\-/]+)")


def extract_knowledge_alias_subpaths(text: str) -> tuple[str, ...]:
    """Every distinct sub-path a piece of agent-instruction text
    dereferences under the singular `$CC_KNOWLEDGE_REPO` alias, in
    first-seen order. Never a hardcoded sub-path list -- this tracks
    whatever the agent's OWN current text says, so the check does not
    silently go stale if an agent's consumption contract changes."""

    seen: list[str] = []
    for match in _ALIAS_SUBPATH_RE.finditer(text):
        cleaned = match.group(1).rstrip(").,;:'\"")
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return tuple(seen)


_DIMENSIONS_READ_RE = re.compile(
    r"""\[\s*["']dimensions["']\s*\]|\.get\(\s*["']dimensions["']"""
)

# The checkers' own package. `check_h8_commands_dimension_has_no_consumer`
# and `stack.py`'s dimensions-declared check both legitimately READ a
# layer's `dimensions:` field while INSPECTING a copilot.layer.yml (a
# read-only harness assertion, never a materialize/shadow consumer) -- so a
# naive scan of the WHOLE `src/cc` tree finds the checkers reading their own
# subject and reports a false "a consumer exists" PASS. This bit the harness
# for real: `commands/conformance.py`'s caller already knew to pass only
# `core/ecosystem` and `commands` as `source_root` (never the whole tree),
# but that was CALLER DISCIPLINE, not a structural guarantee -- nothing
# stopped a future caller (a `--full` repo sweep, a refactor) from widening
# `source_root` and silently resurrecting the false PASS. This exclusion
# makes `find_dimensions_consumers` immune to that regardless of what
# `source_root` it is ever called with, matching the fix instruction "only
# counts real consumers in core/ecosystem and commands" as an ENFORCED
# property of the function, not a hopeful convention at each call site.
_EXCLUDED_PACKAGE_SEGMENTS: tuple[str, ...] = ("core", "conformance")


def _is_under_excluded_package(path: Path, source_root: Path) -> bool:
    """True when `path` sits under a `core/conformance/` subtree anywhere
    beneath `source_root` -- the checkers' own package, which must never
    count as a materialize/shadow consumer of `dimensions:` no matter how
    wide a caller's `source_root` is."""

    parts = path.relative_to(source_root).parts
    segment_len = len(_EXCLUDED_PACKAGE_SEGMENTS)
    return any(
        parts[i : i + segment_len] == _EXCLUDED_PACKAGE_SEGMENTS
        for i in range(len(parts) - segment_len + 1)
    )


def find_dimensions_consumers(source_root: Path) -> tuple[Path, ...]:
    """Every `*.py` file under `source_root` that READS a `"dimensions"`
    dict key (`x["dimensions"]` / `x.get("dimensions")`) -- as opposed to
    merely declaring one as a dict-literal key (`"dimensions": [...]`,
    which `commands/onboard.py`'s scaffold writers do and which this
    regex deliberately does NOT match, since a write is not a consumer) --
    and never a hit inside the checkers' own `core/conformance/` package
    (`_is_under_excluded_package`), which reads `dimensions:` only to
    inspect it, not to materialize/shadow anything by it."""

    hits: list[Path] = []
    for path in sorted(source_root.rglob("*.py")):
        if _is_under_excluded_package(path, source_root):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _DIMENSIONS_READ_RE.search(text):
            hits.append(path)
    return tuple(hits)


def knowledge_ladder_from_layers(
    layers: Sequence[Mapping[str, Any]], *, product: str = "knowledge"
) -> tuple[str, ...]:
    """The ordered (nearest-first) list of `source.path` values for one
    product's layers, read from already-loaded, already-validated layer
    dicts (`cc.core.ecosystem.manifest.validate_layers`'s return value) --
    never a re-parse of the manifest file itself."""

    ranked = sorted(
        (layer for layer in layers if layer.get("product") == product),
        key=lambda layer: layer["rank"],
    )
    return tuple(
        str(layer["source"]["path"])
        for layer in ranked
        if isinstance(layer.get("source"), dict) and layer["source"].get("path")
    )


# ---------------------------------------------------------------------------
# H-1 -- nearest DECLARED tier wins
# ---------------------------------------------------------------------------


def check_h1_nearest_declared_wins(
    agent: str,
    *,
    knowledge_repos: Sequence[str],
    missing_skills_checker: MissingSkillsChecker | None = None,
) -> CheckResult:
    repos = list(knowledge_repos)
    resolution = resolve_extension(
        agent, knowledge_repos=repos, missing_skills_checker=missing_skills_checker
    )
    declaring = _declaring_repos_in_order(agent, repos)

    if not declaring:
        return H1_NEAREST_DECLARED_WINS.result(
            subject=agent,
            verdict=Verdict.SKIP,
            detail=f"no tier in the ladder declares an extensions[] entry for {agent!r}",
        )

    expected_winner = declaring[0]
    if resolution.matched and resolution.source_repo == expected_winner:
        return H1_NEAREST_DECLARED_WINS.result(
            subject=agent,
            verdict=Verdict.PASS,
            detail=(
                f"{agent!r} resolves to {expected_winner} "
                f"(nearest of {len(declaring)} declaring tier(s): {list(declaring)})"
            ),
        )

    evidence = (
        Evidence(
            kind="extension-resolution",
            path=resolution.source_repo or expected_winner,
            expected=f"winning source_repo == {expected_winner!r}",
            actual=f"source_repo={resolution.source_repo!r}, matched={resolution.matched!r}",
            detail=f"declaring tiers in ladder order (independently read from each manifest): {list(declaring)}",
        ),
    )
    return H1_NEAREST_DECLARED_WINS.result(
        subject=agent,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail="resolve_extension did not select the nearest declaring tier",
    )


# ---------------------------------------------------------------------------
# H-2 -- a nearer tier's absence never blocks a farther tier's real content
# ---------------------------------------------------------------------------


def check_h2_absence_is_not_shadow(
    agent: str,
    *,
    knowledge_repos: Sequence[str],
    missing_skills_checker: MissingSkillsChecker | None = None,
) -> CheckResult:
    repos = list(knowledge_repos)
    declaring = _declaring_repos_in_order(agent, repos)

    if not declaring:
        return H2_ABSENCE_IS_NOT_SHADOW.result(
            subject=agent,
            verdict=Verdict.SKIP,
            detail=f"no tier in the ladder declares an extensions[] entry for {agent!r}",
        )

    nearest_declaring = declaring[0]
    nearer_absent = repos[: repos.index(nearest_declaring)]
    if not nearer_absent:
        # The nearest tier in the ladder already declares this agent -- H-2's
        # "absence" scenario is not exercised by this subject (that is H-1's
        # case, e.g. `cw`).
        return H2_ABSENCE_IS_NOT_SHADOW.result(
            subject=agent,
            verdict=Verdict.SKIP,
            detail=(
                f"the nearest ladder tier ({nearest_declaring}) already declares "
                f"{agent!r} -- no nearer absence to exercise"
            ),
        )

    resolution = resolve_extension(
        agent, knowledge_repos=repos, missing_skills_checker=missing_skills_checker
    )
    ok = (
        resolution.action == ACTION_APPLY
        and resolution.source_repo == nearest_declaring
        and not resolution.missing_skills
    )
    if ok:
        return H2_ABSENCE_IS_NOT_SHADOW.result(
            subject=agent,
            verdict=Verdict.PASS,
            detail=(
                f"{len(nearer_absent)} nearer tier(s) declare nothing for {agent!r}; "
                f"resolution reached {nearest_declaring} unmodified, missing_skills=[]"
            ),
        )

    evidence = (
        Evidence(
            kind="extension-resolution",
            path=resolution.source_repo or nearest_declaring,
            expected=f"source_repo == {nearest_declaring!r}, action == {ACTION_APPLY!r}, missing_skills == []",
            actual=(
                f"source_repo={resolution.source_repo!r}, action={resolution.action!r}, "
                f"missing_skills={resolution.missing_skills!r}"
            ),
            detail=f"nearer, non-declaring tiers: {nearer_absent}",
        ),
    )
    return H2_ABSENCE_IS_NOT_SHADOW.result(
        subject=agent,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail="a nearer tier's absence blocked or altered resolution of the farther declaring tier",
    )


# ---------------------------------------------------------------------------
# H-3 -- shadow-substance (THE BUG, Q25)
# ---------------------------------------------------------------------------


def check_h3_shadow_substance(
    agent: str,
    *,
    knowledge_repos: Sequence[str],
    missing_skills_checker: MissingSkillsChecker | None = None,
    minimum_size_ratio: float = 0.5,
) -> CheckResult:
    repos = list(knowledge_repos)
    resolution = resolve_extension(
        agent, knowledge_repos=repos, missing_skills_checker=missing_skills_checker
    )
    if not resolution.matched or not resolution.file:
        return H3_SHADOW_SUBSTANCE.result(
            subject=agent,
            verdict=Verdict.SKIP,
            detail=f"no tier in the ladder declares an extensions[] entry for {agent!r}",
        )

    declaring = _declaring_repos_in_order(agent, repos)
    shadowed = [repo for repo in declaring if repo != resolution.source_repo]
    if not shadowed:
        return H3_SHADOW_SUBSTANCE.result(
            subject=agent,
            verdict=Verdict.SKIP,
            detail=f"only one tier ({resolution.source_repo}) declares {agent!r} -- nothing is shadowed",
        )

    winner_path = Path(resolution.file)
    winner_text = winner_path.read_text(encoding="utf-8")
    winner_status = _frontmatter_status(winner_text)
    todo_count = winner_text.count("TODO(")
    winner_size = winner_path.stat().st_size

    shadow_repo = shadowed[0]
    shadow_resolution = resolve_extension(
        agent,
        knowledge_repos=[shadow_repo],
        missing_skills_checker=missing_skills_checker,
    )
    shadow_size = (
        Path(shadow_resolution.file).stat().st_size if shadow_resolution.file else 0
    )

    is_draft = winner_status == "draft"
    has_todo = todo_count > 0
    size_ratio_ok = shadow_size == 0 or winner_size >= minimum_size_ratio * shadow_size
    substantive = not is_draft and not has_todo and size_ratio_ok

    detail = (
        f"winner={resolution.source_repo} ({winner_size}B, status={winner_status!r}, "
        f"{todo_count}x 'TODO('); shadowed={shadow_repo} ({shadow_size}B)"
    )

    if substantive:
        return H3_SHADOW_SUBSTANCE.result(
            subject=agent, verdict=Verdict.PASS, detail=detail
        )

    evidence = (
        Evidence(
            kind="extension-file",
            path=str(winner_path),
            expected=(
                f"status != 'draft', no 'TODO(' markers, size >= "
                f"{int(minimum_size_ratio * 100)}% of the nearest shadowed candidate"
            ),
            actual=f"status={winner_status!r}, {todo_count}x 'TODO(', {winner_size}B",
            detail=f"shadows {shadow_repo}'s {shadow_size}B extension file",
        ),
    )
    return H3_SHADOW_SUBSTANCE.result(
        subject=agent,
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# H-4 -- knowledge ladder order
# ---------------------------------------------------------------------------


def check_h4_ladder_order(
    *, actual_ladder: Sequence[str], expected_ladder: Sequence[str]
) -> CheckResult:
    actual = tuple(actual_ladder)
    expected = tuple(expected_ladder)

    if actual == expected:
        return H4_LADDER_ORDER.result(
            subject="CC_KNOWLEDGE_REPOS",
            verdict=Verdict.PASS,
            detail=f"{len(actual)}-entry ladder matches manifest rank order: {list(actual)}",
        )

    evidence = (
        Evidence(
            kind="env-export",
            path="CC_KNOWLEDGE_REPOS",
            expected=", ".join(expected),
            actual=", ".join(actual),
        ),
    )
    return H4_LADDER_ORDER.result(
        subject="CC_KNOWLEDGE_REPOS", verdict=Verdict.FAIL, evidence=evidence
    )


# ---------------------------------------------------------------------------
# H-5 -- singular alias sub-paths must exist (THE BUG, Q24)
# ---------------------------------------------------------------------------


def check_h5_singular_alias_paths_exist(
    *, agent_files: Mapping[str, str], cc_knowledge_repo: str
) -> tuple[CheckResult, ...]:
    """`agent_files`: `{display name -> file text}`, e.g.
    `{"cw.md": Path(...).read_text(), ...}`. One `CheckResult` per agent
    file, aggregating every missing sub-path that file references."""

    repo_root = Path(cc_knowledge_repo)
    results: list[CheckResult] = []
    for name, text in agent_files.items():
        subpaths = extract_knowledge_alias_subpaths(text)
        if not subpaths:
            results.append(
                H5_SINGULAR_ALIAS_PATHS_EXIST.result(
                    subject=name,
                    verdict=Verdict.SKIP,
                    detail="no $CC_KNOWLEDGE_REPO sub-path reference found",
                )
            )
            continue

        missing = [sp for sp in subpaths if not (repo_root / sp.rstrip("/")).exists()]
        if not missing:
            results.append(
                H5_SINGULAR_ALIAS_PATHS_EXIST.result(
                    subject=name,
                    verdict=Verdict.PASS,
                    detail=f"all {len(subpaths)} referenced sub-path(s) exist under {repo_root}",
                )
            )
            continue

        evidence = tuple(
            Evidence(
                kind="knowledge-subpath",
                path=str(repo_root / sp.rstrip("/")),
                expected="exists",
                actual="missing",
                detail=f"referenced by {name} via $CC_KNOWLEDGE_REPO",
            )
            for sp in missing
        )
        results.append(
            H5_SINGULAR_ALIAS_PATHS_EXIST.result(
                subject=name,
                verdict=Verdict.FAIL,
                evidence=evidence,
                detail=(
                    f"{len(missing)} of {len(subpaths)} referenced sub-path(s) do not "
                    f"exist under the singular alias's current target ({repo_root})"
                ),
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# H-6 -- declared skill paths exist, per tier
# ---------------------------------------------------------------------------


def check_h6_declared_skill_paths_exist(
    *, tier_repos: Mapping[str, str]
) -> tuple[CheckResult, ...]:
    """`tier_repos`: `{tier label -> repo path}`, e.g.
    `{"knowledge-personal": "/path/to/knowledge-copilot-private", ...}`."""

    results: list[CheckResult] = []
    for label, repo in tier_repos.items():
        repo_path = Path(repo)
        manifest_path = repo_path / "knowledge-manifest.json"

        if not manifest_path.is_file():
            evidence = (
                Evidence(
                    kind="knowledge-manifest",
                    path=str(manifest_path),
                    expected="present",
                    actual="missing",
                    detail="hollow rung -- no manifest to declare skills from",
                ),
            )
            results.append(
                H6_DECLARED_SKILL_PATHS_EXIST.result(
                    subject=label,
                    verdict=Verdict.FAIL,
                    evidence=evidence,
                    expected_today=ExpectedToday.FAIL,
                )
            )
            continue

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            evidence = (
                Evidence(
                    kind="knowledge-manifest",
                    path=str(manifest_path),
                    expected="valid JSON object",
                    actual=f"unreadable/malformed: {exc}",
                ),
            )
            results.append(
                H6_DECLARED_SKILL_PATHS_EXIST.result(
                    subject=label, verdict=Verdict.FAIL, evidence=evidence
                )
            )
            continue

        # `skills.local[]` entries are TYPED OBJECTS per the real schema
        # (`docs/schemas/knowledge-manifest-schema.json`: required `name` +
        # `path`, optional `description`/`keywords`) -- never raw path
        # strings. Every manifest on this machine (0-222 entries) already
        # matches this shape; a non-dict entry or one missing a string
        # `path` is a structurally invalid declaration, not a path to check
        # for existence, so it is excluded from `declared_paths` rather than
        # silently treated as `p` (which would previously have skipped EVERY
        # entry, since `isinstance(p, str)` is never true for a dict -- the
        # bug this check existed to catch: 0 declared paths, everywhere,
        # always, a false PASS that could never fail).
        skills = data.get("skills")
        declared = skills.get("local") if isinstance(skills, dict) else None
        declared_paths = [
            entry["path"]
            for entry in (declared or [])
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        ]

        missing = [p for p in declared_paths if not (repo_path / p).exists()]
        if missing:
            evidence = tuple(
                Evidence(
                    kind="knowledge-skill-path",
                    path=str(repo_path / p),
                    expected="exists",
                    actual="missing",
                    detail=f"declared in {manifest_path.name}'s skills.local[]",
                )
                for p in missing
            )
            results.append(
                H6_DECLARED_SKILL_PATHS_EXIST.result(
                    subject=label, verdict=Verdict.FAIL, evidence=evidence
                )
            )
            continue

        results.append(
            H6_DECLARED_SKILL_PATHS_EXIST.result(
                subject=label,
                verdict=Verdict.PASS,
                detail=f"{len(declared_paths)} declared skill path(s), 0 broken",
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# H-7 -- no hollow rung
# ---------------------------------------------------------------------------


def check_h7_no_hollow_rung(*, tier_repos: Mapping[str, str]) -> CheckResult:
    missing = [
        (label, repo)
        for label, repo in tier_repos.items()
        if not (Path(repo) / "knowledge-manifest.json").is_file()
    ]
    if not missing:
        return H7_NO_HOLLOW_RUNG.result(
            subject="knowledge-ladder",
            verdict=Verdict.PASS,
            detail=f"all {len(tier_repos)} ladder rung(s) have a knowledge-manifest.json",
        )

    evidence = tuple(
        Evidence(
            kind="knowledge-manifest",
            path=str(Path(repo) / "knowledge-manifest.json"),
            expected="present",
            actual="missing",
            detail=f"{label} rung is hollow",
        )
        for label, repo in missing
    )
    return H7_NO_HOLLOW_RUNG.result(
        subject="knowledge-ladder",
        verdict=Verdict.FAIL,
        evidence=evidence,
        detail=f"{len(missing)} of {len(tier_repos)} ladder rung(s) are hollow",
    )


# ---------------------------------------------------------------------------
# H-8 -- commands dimension has no consumer (fixture-only, no live instance)
# ---------------------------------------------------------------------------


def check_h8_commands_dimension_has_no_consumer(*, source_root: Path) -> CheckResult:
    consumers = find_dimensions_consumers(source_root)
    if consumers:
        return H8_COMMANDS_DIMENSION_HAS_NO_CONSUMER.result(
            subject=str(source_root),
            verdict=Verdict.PASS,
            detail=(
                f"{len(consumers)} consumer(s) found: "
                f"{', '.join(str(path) for path in consumers)}"
            ),
            expected_today=ExpectedToday.PASS,
        )

    evidence = (
        Evidence(
            kind="code-scan",
            path=str(source_root),
            expected=(
                "at least one module reads a layer's `dimensions:` field to "
                "shadow or materialize a command by tier precedence"
            ),
            actual="0 matches",
            detail=(
                "copilot.layer.yml's `dimensions:` field is only ever WRITTEN "
                '(commands/onboard.py scaffolds `"dimensions": []` at two call '
                "sites), never READ anywhere under the selected source surface -- "
                "RC-5's authoring gap has no materialization consumer yet"
            ),
        ),
    )
    return H8_COMMANDS_DIMENSION_HAS_NO_CONSUMER.result(
        subject=str(source_root),
        verdict=Verdict.FAIL,
        evidence=evidence,
        expected_today=ExpectedToday.FAIL,
    )


# ---------------------------------------------------------------------------
# H-9 -- project config overrides the machine ladder (fixture-only)
# ---------------------------------------------------------------------------


def check_h9_project_overrides_machine_ladder(
    *, machine_config_path: Path, project_config_path: Path, subject: str
) -> CheckResult:
    from cc.core.config import get_resolved_config

    machine_config = json.loads(machine_config_path.read_text(encoding="utf-8"))
    project_config = json.loads(project_config_path.read_text(encoding="utf-8"))

    resolved = get_resolved_config(_machine=machine_config, _project=project_config)

    project_value = (project_config.get("paths") or {}).get("knowledge_repo")
    machine_value = (machine_config.get("paths") or {}).get("knowledge_repo")
    actual = resolved.get("paths.knowledge_repo")

    if actual == project_value and actual != machine_value:
        return H9_PROJECT_OVERRIDES_MACHINE_LADDER.result(
            subject=subject,
            verdict=Verdict.PASS,
            detail=f"project literal override {actual!r} wins over the machine ladder default {machine_value!r}",
        )

    evidence = (
        Evidence(
            kind="config-key",
            path=str(project_config_path),
            expected=f"paths.knowledge_repo == {project_value!r} (the project's own literal override)",
            actual=f"paths.knowledge_repo == {actual!r}",
            detail=f"machine ladder default was {machine_value!r}",
        ),
    )
    return H9_PROJECT_OVERRIDES_MACHINE_LADDER.result(
        subject=subject, verdict=Verdict.FAIL, evidence=evidence
    )


__all__ = [
    "H1_NEAREST_DECLARED_WINS",
    "H2_ABSENCE_IS_NOT_SHADOW",
    "H3_SHADOW_SUBSTANCE",
    "H4_LADDER_ORDER",
    "H5_SINGULAR_ALIAS_PATHS_EXIST",
    "H6_DECLARED_SKILL_PATHS_EXIST",
    "H7_NO_HOLLOW_RUNG",
    "H8_COMMANDS_DIMENSION_HAS_NO_CONSUMER",
    "H9_PROJECT_OVERRIDES_MACHINE_LADDER",
    "check_h1_nearest_declared_wins",
    "check_h2_absence_is_not_shadow",
    "check_h3_shadow_substance",
    "check_h4_ladder_order",
    "check_h5_singular_alias_paths_exist",
    "check_h6_declared_skill_paths_exist",
    "check_h7_no_hollow_rung",
    "check_h8_commands_dimension_has_no_consumer",
    "check_h9_project_overrides_machine_ladder",
    "extract_knowledge_alias_subpaths",
    "find_dimensions_consumers",
    "knowledge_ladder_from_layers",
]
