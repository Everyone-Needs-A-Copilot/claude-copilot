"""D12 -- Docs / initiatives scaffolding (`RUBRIC.md` D12, `TEST-MATRIX.md`
IC-D12-INITIATIVES).

PRESENT requires `docs/40-initiatives/README.md` AND
`docs/40-initiatives/_template/{phases,decisions,retrospectives}/` to exist
on disk **and** actually reach a fresh clone -- i.e. none of those paths may
be excluded by the repo's own `.gitignore`.

`product-creation-copilot` is the concrete case the second half of this
check exists for: `.gitignore:2` excludes `docs/` wholesale, so its real
`_template/{phases,decisions,retrospectives}/` tree exists on THIS disk
(verified live 2026-08-10 -- `ls docs/40-initiatives/_template/` shows all
three subdirectories plus `README.md`) while `git ls-files docs/` returns
**zero** tracked files. A fresh clone of this Layer-1 registry tool receives
none of it. Reporting that as PRESENT because the directory happens to
exist in one already-cloned working tree would be exactly the kind of
hollow pass this harness exists to catch -- so a gitignored initiatives
tree is a FAIL with specific evidence naming the ignored path, never a PASS
on the strength of local disk state alone.

Fast, read-only: disk-presence checks are plain `Path.stat()`; the
gitignore check is the sole filesystem action requiring git plumbing, and it
runs exclusively through `fsguard.run_git_readonly` (on the read-only
allowlist), never a write.

`run(context)` below implements the `dimensions/__init__.py` module
contract (`DimensionModule`/`RepoContext`, owned by WP-4), which has since
landed.
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

REQUIRED_TEMPLATE_SUBDIRS: tuple[str, ...] = ("phases", "decisions", "retrospectives")

# Machine-verified today (`TEST-MATRIX.md` IC-D12-INITIATIVES /
# `RUBRIC.md` D12): docs/40-initiatives/ (or its _template/) is absent
# entirely, confirmed live via `ls -d .../docs/40-initiatives` for
# `TSM/hermes` (the reference install itself lacks this dimension) and
# cited from the audit for the rest.
KNOWN_ABSENT_REPOS: frozenset[str] = frozenset(
    {
        "convoco-site",
        "crm-automation-copilot",
        "drip-copilot",
        "method-copilot",
        "preflight-copilot",
        "saas-financial-model",
        "transformation",
        "workflow-copilot",
        "hermes",  # TSM/hermes
    }
)

# Machine-verified today: docs/40-initiatives/ exists but has no
# _template/ subtree at all (confirmed live via `ls`).
KNOWN_MISSING_TEMPLATE_REPOS: frozenset[str] = frozenset(
    {"job-finder", "sproutworks", "h3"}
)

# Machine-verified today (see module docstring): the tree is fully present
# on disk but wholly gitignored, so 0 files are tracked -- confirmed live
# via `git ls-files docs/` returning empty and
# `git check-ignore -v docs/40-initiatives/_template/phases` matching
# `.gitignore:2:docs/`.
KNOWN_GITIGNORED_REPOS: frozenset[str] = frozenset({"product-creation-copilot"})

_APPLIES_TO = ("A", "B", "C", "D")  # RUBRIC.md D12: "A, B, C. Optional for D."

_INITIATIVES_CHECK = register_check(
    id="repo.d12.initiatives_scaffold",
    layer=Layer.REPO,
    severity=Severity.S3,
    scope=Scope.PER_REPO,
    summary=(
        "docs/40-initiatives/ has a README.md and a "
        "_template/{phases,decisions,retrospectives}/ tree, none of it "
        "excluded by .gitignore."
    ),
    remediation=(
        "Create docs/40-initiatives/README.md and "
        "_template/{phases,decisions,retrospectives}/ from shared-docs' "
        "07-initiative-package template; if a .gitignore rule excludes "
        "docs/ or any part of this tree, narrow it so the scaffold "
        "actually reaches a fresh clone."
    ),
    mode=Mode.FAST,
    applies_to_classes=_APPLIES_TO,
    expected_today=ExpectedToday.PASS,
)


def _expected_today(repo: Path) -> ExpectedToday:
    name = repo.name
    if (
        name in KNOWN_ABSENT_REPOS
        or name in KNOWN_MISSING_TEMPLATE_REPOS
        or name in KNOWN_GITIGNORED_REPOS
    ):
        return ExpectedToday.FAIL
    return ExpectedToday.PASS


def _required_relative_paths() -> tuple[str, ...]:
    return ("docs/40-initiatives/README.md",) + tuple(
        f"docs/40-initiatives/_template/{sub}" for sub in REQUIRED_TEMPLATE_SUBDIRS
    )


def _missing_disk_paths(repo: Path) -> list[str]:
    missing: list[str] = []
    readme = repo / "docs" / "40-initiatives" / "README.md"
    if not readme.is_file():
        missing.append(str(readme))
    for sub in REQUIRED_TEMPLATE_SUBDIRS:
        target = repo / "docs" / "40-initiatives" / "_template" / sub
        if not target.is_dir():
            missing.append(str(target))
    return missing


def _gitignored_paths(repo: Path) -> list[str]:
    """Which required paths (that DO exist on disk) a fresh clone would not
    receive, per `git check-ignore` (read-only, allowlisted plumbing)."""

    ignored: list[str] = []
    for relative in _required_relative_paths():
        if not (repo / relative).exists():
            continue  # _missing_disk_paths already covers plain absence
        result = run_git_readonly(("check-ignore", "-q", "--", relative), cwd=repo)
        if result.returncode == 0:
            ignored.append(relative)
    return ignored


def check_initiatives_scaffold(
    repo: Path,
    *,
    subject: str | None = None,
    expected_today: ExpectedToday | None = None,
) -> CheckResult:
    """`repo.d12.initiatives_scaffold` against one repo."""

    name = subject or str(repo)
    expected = expected_today if expected_today is not None else _expected_today(repo)

    missing = _missing_disk_paths(repo)
    if missing:
        return _INITIATIVES_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=tuple(
                Evidence(
                    kind="initiatives-scaffold",
                    path=path,
                    expected="present on disk",
                    actual="missing",
                )
                for path in missing
            ),
        )

    ignored = _gitignored_paths(repo)
    if ignored:
        return _INITIATIVES_CHECK.result(
            subject=name,
            verdict=Verdict.FAIL,
            expected_today=expected,
            evidence=tuple(
                Evidence(
                    kind="initiatives-scaffold",
                    path=str(repo / relative),
                    expected="tracked by git (reaches a fresh clone)",
                    actual="excluded by a .gitignore rule",
                    detail=(
                        "the tree exists in THIS working copy but a fresh "
                        "clone would not receive it -- reporting PRESENT on "
                        "local disk state alone would be a hollow pass"
                    ),
                    command=f"git check-ignore -q -- {relative}",
                )
                for relative in ignored
            ),
        )

    return _INITIATIVES_CHECK.result(
        subject=name, verdict=Verdict.PASS, expected_today=expected
    )


def run(context: "RepoContext") -> Iterable[CheckResult]:
    """The `dimensions/__init__.py` module contract's required entry
    point: one `CheckResult` for `repo.d12.initiatives_scaffold`, for every
    repo (`Verdict.SKIP` for a class D12 does not apply to)."""

    if context.rubric_class not in _APPLIES_TO:
        return (
            _INITIATIVES_CHECK.result(
                subject=context.subject,
                verdict=Verdict.SKIP,
                detail=(
                    f"N/A for class {context.rubric_class} -- D12 applies to "
                    "classes A/B/C, optional for D."
                ),
            ),
        )
    return (check_initiatives_scaffold(context.path, subject=context.subject),)


__all__ = [
    "KNOWN_ABSENT_REPOS",
    "KNOWN_GITIGNORED_REPOS",
    "KNOWN_MISSING_TEMPLATE_REPOS",
    "REQUIRED_TEMPLATE_SUBDIRS",
    "check_initiatives_scaffold",
    "run",
]
