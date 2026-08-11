"""Cross-dimension -- a repo's `.gitignore` must not exclude its own
framework install (`HARNESS-DESIGN.md` §4 Layer 3,
`repo.gitignore.no_self_exclusion`; `TEST-MATRIX.md` §8's Q23 batch).

Six real repos are answered by the owner (Q23, answer A across all six --
`docs/ecosystem-audit-open-questions.md`): the gitignore rule is wrong and
must be narrowed so the framework's own artifacts reach a fresh clone. Each
was a one-off finding in the source audit; this module generalizes them into
ONE structural rule instead of six repo-specific patches, so a SEVENTH repo
that makes the identical mistake is caught automatically rather than needing
its own Q-number:

  - `admin-server` `.gitignore:86` -- `.claude/` (the whole directory; 0 of
    19 locked claude files ever reach a clone).
  - `convoco` `.gitignore:73` -- `.claude/*` (partially clawed back by `!`
    negations for `.claude/cc/`, `.claude/memory/`, `.claude/skills/`,
    `.claude/work-products/`, but NOT for the four `_CLAUDE_REQUIRED_LOCK_
    PATHS` -- `protocol.md`/`continue.md`/`fitness-check.sh`/
    `copilot-hook.sh` stay excluded; convoco is the ecosystem's most active
    repo at 466 commits/60d).
  - `pipeline-copilot` `.gitignore:34` -- `/plugins/codex-copilot` (the
    whole 61-file codex plugin tree).
  - `convoco-site` `.gitignore:53` -- `.claude/cc/config.json` specifically
    (the `@machine` sentinel never reaches a clone, even though the rest of
    `.claude/` is fine).
  - `force-readiness-assessment` `.gitignore:19` -- `.claude/memory/` (48 of
    59 entries never committed).
  - `product-creation-copilot` `.gitignore:2` -- `docs/` wholesale (the
    entire `docs/40-initiatives/_template/` tree, D12's own scaffold).

**Why `--no-index` matters here and is used deliberately.** Plain
`git check-ignore` (no `--no-index`) reports a path as NOT ignored once it
is already tracked in the index, regardless of what the current `.gitignore`
pattern says -- correct for "will `git add` pick up a NEW copy of this,"
wrong for "does this rule exclude the framework install," which is a
pattern-level question independent of today's incidental tracking history.
`force-readiness-assessment` is the concrete case: 11 of its 59 memory
entries were committed before `.gitignore:19` was added, so a plain
`git check-ignore -- .claude/memory/entries` reports "not ignored" (some
tracked content lives under it) even though the pattern excludes the
directory and the other 48 entries never reach a clone. `--no-index` asks
the real question this check exists to answer: does the *pattern* exclude
the path, not "did tracking happen to start before the rule did."

**Why matched output is filtered for `!`-negation.** `git check-ignore -v`
prints the LAST pattern that matched a path, including a negation (`!...`)
that un-ignores it again -- `convoco`'s own `.gitignore:75`
(`!.claude/cc/config.json`) shows up in `-v` output for that exact path, but
the path is correctly TRACKED, not excluded. Treating every printed line as
a violation would produce a false positive on the one repo (`convoco`) that
got the negation right for that specific file. Only a matched pattern that
does NOT start with `!` is a real exclusion.

The candidate path list below is deliberately independent of any one repo's
`copilot.lock.json` (unlike `d03_lock.py`/`d04_hook.py`, which read the
lock's own `files[]` list): `docs/40-initiatives` is never a locked path
(verified live against `product-creation-copilot`'s own lock -- 0 `docs/`
entries in either component), and `.claude/memory/entries` is never locked
either (dynamic runtime content, not a checksummed framework file) --
confirmed empty for `force-readiness-assessment`'s own lock. Framework
install therefore means "each dimension's own primary artifact location"
(D1 agents/commands, D2 codex plugin, D3 the lock file itself, D4 the hook,
D5 the cc config, D6 memory entries, D10 `.mcp.json`, D12 the initiatives
scaffold), not merely what happens to be lock-recorded.

Every filesystem action here is a plain `Path.exists()` (cheap, and the
gate that keeps this check from ever citing a path the repo never
installed) plus exactly one `git check-ignore` call per repo, run
exclusively through `fsguard.run_git_readonly` (on the read-only
allowlist) -- never a write.

`run(context)` below implements the `dimensions/__init__.py` module
contract (`DimensionModule`/`RepoContext`, owned by WP-4); `dx_gitignore`
is already named in that module's `DIMENSION_MODULE_NAMES` tuple, so this
file landing here is the entirety of "wiring it into discovery."
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from cc.core.conformance.fsguard import run_git_readonly
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

if TYPE_CHECKING:
    from cc.core.conformance.dimensions import RepoContext

# One representative, existence-gated candidate path per dimension whose
# primary artifact is framework-owned. Order is stable (dict-free tuple) so
# evidence ordering is deterministic across runs. Extending this list (a new
# dimension's own artifact) is a one-line, reviewed addition here -- never a
# per-repo special case.
FRAMEWORK_OWNED_CANDIDATES: tuple[str, ...] = (
    ".claude",  # D1 -- the framework tree itself; catches a blanket exclusion directly
    ".claude/agents",  # D1
    ".claude/commands",  # D1
    ".claude/fitness-check.sh",  # D1
    ".claude/hooks/copilot-hook.sh",  # D4
    ".claude/cc/config.json",  # D5
    ".claude/memory/entries",  # D6
    "plugins/codex-copilot",  # D2
    "scripts/copilot-gate.sh",  # D2
    "copilot.lock.json",  # D3
    ".mcp.json",  # D10
    "docs/40-initiatives",  # D12
)

# Re-verified live 2026-08-10: all six repos below were narrowed per owner
# Q23 answer A (`docs/ecosystem-audit-open-questions.md`) -- none excludes a
# framework-owned path any more (`repo.gitignore.no_self_exclusion` now
# passes 6/6). Kept as a named, empty set (rather than deleted) so a FUTURE
# repo found to make the identical mistake has an obvious place to be
# recorded, and so this module's own history stays attached to the six it
# used to name. The check's ability to detect this exact shape is proven by
# `test_dimensions_dx_gitignore.py`'s fixture tests (`test_fail_reproduces_
# admin_server`, `test_fail_reproduces_product_creation_copilot_docs_
# exclusion`, and `TestFindSelfExcludedPaths`'s per-repo-shape reproductions),
# never by this constant alone.
KNOWN_SELF_EXCLUDING_REPOS: frozenset[str] = frozenset()

_APPLIES_TO = ("A", "B", "C", "D")  # matches d03/d10/d12's lock-bearing classes

_GITIGNORE_NO_SELF_EXCLUSION_CHECK = register_check(
    id="repo.gitignore.no_self_exclusion",
    layer=Layer.REPO,
    severity=Severity.S1,
    scope=Scope.PER_REPO,
    summary=(
        "No .gitignore rule excludes a path the repo's own framework "
        "install owns (agents/commands, the codex plugin tree, the "
        "enforcement hook, the cc config sentinel, memory entries, "
        ".mcp.json, or the initiatives scaffold)."
    ),
    remediation=(
        "Narrow the offending .gitignore rule (add a `!`-negation for the "
        "specific framework-owned path, or scope the original pattern more "
        "precisely) so a fresh clone actually receives the framework "
        "install -- generalizes the owner's Q23 answer A across all six "
        "named repos into one structural rule."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _expected_today(repo: Path) -> ExpectedToday:
    return (
        ExpectedToday.FAIL
        if repo.name in KNOWN_SELF_EXCLUDING_REPOS
        else ExpectedToday.PASS
    )


def _parse_check_ignore_line(line: str) -> tuple[str, str, str, str] | None:
    """Parse one `git check-ignore -v` output line into `(source, linenum,
    pattern, matched_path)`. Format: `<source>:<linenum>:<pattern>\\t<path>`
    -- the pattern itself may contain `:`, so only the first two colons are
    split on. Returns `None` for a line that does not fit the shape (never
    raises -- a git output surprise degrades to "ignore this line," not a
    crash)."""

    if "\t" not in line:
        return None
    meta, _, matched_path = line.partition("\t")
    parts = meta.split(":", 2)
    if len(parts) != 3:
        return None
    source, linenum, pattern = parts
    return source, linenum, pattern, matched_path


def find_self_excluded_paths(
    repo: Path, candidates: Iterable[str] = FRAMEWORK_OWNED_CANDIDATES
) -> tuple[list[tuple[str, str, str]], list[str], int]:
    """Run one batched, read-only `git check-ignore -v --no-index` over
    every candidate that exists on disk. Returns
    `(excluded, could_not_run_errors, considered_count)` where `excluded` is
    a list of `(candidate_path, gitignore_source, pattern)` for every
    candidate a REAL (non-`!`-negated) rule excludes -- `candidate_path` is
    echoed back exactly as passed in `candidates` (repo-relative, matching
    `FRAMEWORK_OWNED_CANDIDATES`' own shape), never resolved to an absolute
    path here; callers that need an absolute path (e.g. `Evidence.path`)
    join it onto `repo` themselves -- and `could_not_run_errors` carries a
    message when `git` itself could not answer (e.g. not a git repository)
    rather than "not excluded."
    """

    existing = [c for c in candidates if (repo / c).exists()]
    if not existing:
        return [], [], 0

    result = run_git_readonly(
        ("check-ignore", "-v", "--no-index", "--", *existing), cwd=repo
    )

    # 0 = at least one candidate matched a pattern (negations included);
    # 1 = none matched anything -- both are legitimate "the tool ran fine"
    # outcomes (`fsguard.run_git_readonly`'s own convention: a non-zero
    # exit from check-ignore is often the interesting answer, never an
    # error to swallow). Only something outside {0, 1} (e.g. 128 -- not a
    # git repository) means the harness could not determine an answer.
    if result.returncode not in (0, 1):
        return (
            [],
            [
                f"git check-ignore exited {result.returncode}: "
                f"{result.stderr.strip()}"
            ],
            len(existing),
        )

    excluded: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        parsed = _parse_check_ignore_line(line)
        if parsed is None:
            continue
        source, linenum, pattern, matched_path = parsed
        if pattern.startswith("!"):
            # A negation un-ignores the path again -- e.g. convoco's own
            # `.gitignore:75:!.claude/cc/config.json` -- never a violation.
            continue
        excluded.append((matched_path, f"{source}:{linenum}", pattern))

    return excluded, [], len(existing)


def check_gitignore_no_self_exclusion(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """`repo.gitignore.no_self_exclusion` against one repo."""

    repo = Path(repo)
    name = subject or str(repo)
    expected = expected_today if expected_today is not None else _expected_today(repo)
    registration = _GITIGNORE_NO_SELF_EXCLUSION_CHECK

    excluded, errors, considered = find_self_excluded_paths(repo)

    if errors:
        return CheckResult(
            id=registration.id,
            layer=registration.layer,
            severity=registration.severity,
            scope=registration.scope,
            subject=name,
            assertion=registration.summary,
            verdict=Verdict.COULD_NOT_RUN,
            expected_today=expected,
            detail="; ".join(errors),
            remediation=registration.remediation,
        )

    if considered == 0:
        return registration.result(
            subject=name,
            verdict=Verdict.SKIP,
            detail=(
                "none of the framework-owned candidate paths exist on disk "
                "-- nothing installed for this check to protect"
            ),
            expected_today=expected,
        )

    if excluded:
        return registration.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=tuple(
                Evidence(
                    kind="gitignore-self-exclusion",
                    path=str(repo / candidate_path),
                    expected="not excluded by any .gitignore rule",
                    actual=f"excluded by {source}:{pattern}",
                    detail=(
                        "a fresh clone of this repo will never receive this "
                        "framework-owned path"
                    ),
                    command="git check-ignore -v --no-index -- "
                    f"{candidate_path}",
                )
                for candidate_path, source, pattern in excluded
            ),
            detail=(
                f"{len(excluded)} of {considered} framework-owned "
                "candidate path(s) excluded by .gitignore"
            ),
        )

    return registration.result(
        subject=name,
        verdict=Verdict.PASS,
        expected_today=expected,
        detail=f"{considered} framework-owned candidate path(s) checked, none excluded",
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` for `repo.gitignore.no_self_exclusion`, for
    every repo (`Verdict.SKIP` for a class this check does not apply to)."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _GITIGNORE_NO_SELF_EXCLUSION_CHECK.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- applies to "
                    "classes A/B/C/D, not E."
                ),
            ),
        )
    return (
        check_gitignore_no_self_exclusion(context.path, subject=context.subject),
    )


__all__ = [
    "FRAMEWORK_OWNED_CANDIDATES",
    "KNOWN_SELF_EXCLUDING_REPOS",
    "check_gitignore_no_self_exclusion",
    "find_self_excluded_paths",
    "run",
]
